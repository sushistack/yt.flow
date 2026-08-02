"""CharacterService — manages character CRUD, reference image search, and safe downloads.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
Characters live in SQLite, not PipelineState — long-lived configuration. [AD-2]
"""

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
from yt_flow.db.models import CharacterCard as CharacterCardModel
from yt_flow.db.models import CharacterCandidate as CandidateModel
from yt_flow.db.models import ReferenceImage as ReferenceImageModel
from yt_flow.domain.exceptions import ValidationError
from yt_flow.domain.png import has_alpha
from yt_flow.observability import get_client, observe
from yt_flow.services.asset_service import AssetService
from yt_flow.services.image_search import DuckDuckGoImageSearch, ImageSearch, ScpWikiImageFetch

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_DOWNLOAD_TIMEOUT = 30.0
# DashScope Qwen-VL (Story 5.13) — hardcoded like QwenCharacterProvider's endpoint;
# only the model/API key are config-pinned (ponytail: no config for a value that never changes).
_DASHSCOPE_VISION_ENDPOINT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
_CONTENT_TYPE_RE = re.compile(r"^image/(png|jpeg|jpg|webp)")
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# RFC 1918 + loopback ranges
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Canonical angles for character generation — single source of truth
_ANGLE_DESCRIPTIONS: dict[str, str] = {
    "front": "front view, facing camera, full body, feet visible",
    "back": "from behind, back view, facing away, full body, feet visible",
    "side": "side profile view, from side, facing left, full body, feet visible",
    "three_quarter": "three-quarter view, 45 degree angle, facing slightly left, full body, feet visible",
}
_CANONICAL_ANGLES = list(_ANGLE_DESCRIPTIONS.keys())  # ["front", "back", "side", "three_quarter"]
CANONICAL_ANGLES = _CANONICAL_ANGLES  # public alias for API-layer validation

# Story 8.3: standing-pose card storage — CharacterModel's fast-path columns,
# keyed by angle. Non-standing poses live in CharacterCard rows instead (get_card).
_ANGLE_FIELD_NAMES: dict[str, str] = {
    "front": "angle_front_path",
    "back": "angle_back_path",
    "side": "angle_side_path",
    "three_quarter": "angle_three_quarter_path",
}
# ponytail: live-tuned starting points; frontal references need less pull as view diverges.
# Raised 2026-07-07 (Story 8.2 Task 8 follow-up) — the original values let the
# self-referencing stock/derived chain (AC7) redraw the face/mask/insignia per
# angle; identity now takes priority, re-tune down only if angle turn regresses.
# Re-tuned down 2026-08-01 (Story 8.15) on exactly that condition: staged STOCK
# cards came back with "side" and "three_quarter" rendered as another frontal.
# The 07-07 raise assumed text-side identity was also working, but vision
# enrichment started failing silently on 07-12 (qwen-vl max_tokens 400, fixed in
# this story), so the weights had been carrying identity alone — and failing at
# it. With enrichment restored, text locks the face and these can pull less.
# Nudged back up 2026-08-02: 0.30/0.35 did restore the angle turn (side finally renders
# a real profile) but lost identity — hair colour and face changed per angle. Text now
# carries identity properly (the read-back is appended to the authored descriptor rather
# than replacing it, and colours are pinned concretely), so a little more reference pull
# is affordable. Below the 07-07 values that killed the turn.
_ANGLE_IPADAPTER_WEIGHTS: dict[str, float] = {
    "front": 0.2,
    "three_quarter": 0.4,
    "side": 0.35,
    "back": 0.35,
}
def _scrub_phrase(text: str, phrase: str) -> str:
    """Drop every case-insensitive occurrence of ``phrase``, tidying the seams.

    Used on vision-enriched descriptors so a prompt token the caller deliberately
    excluded cannot re-enter through the model's read-back (Story 8.15).
    """
    cleaned = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


_POSE_DESCRIPTIONS: dict[str, str] = {
    "standing": "standing upright",
    "sitting": "sitting on a plain simple chair, seated pose",
}
_VALID_CARD_POSES = frozenset(_POSE_DESCRIPTIONS)
_SPECIAL_POSE_RE = re.compile(r"^hint:[0-9a-f]{10}$")

# Fields that can be updated via update_character — guards against injection
_UPDATE_ALLOWLIST = frozenset({
    "canonical_name", "aliases", "visual_descriptor", "style_guide",
    "image_prompt_base", "selected_image_path",
    "angle_front_path", "angle_back_path", "angle_side_path", "angle_three_quarter_path",
})

# Dangerous path characters to block in scp_id
_PATH_UNSAFE_RE = re.compile(r"[\.]{2,}|[/\\\\]|\x00")


# ── Validation ───────────────────────────────────────────────────────────────


def _validate_create(scp_id: str, canonical_name: str, aliases: list[str] | None) -> None:
    """Validate create_character inputs. Raises ValidationError on failure."""
    if not scp_id or not scp_id.strip():
        raise ValidationError("scp_id", "must not be empty")
    if _PATH_UNSAFE_RE.search(scp_id):
        raise ValidationError("scp_id", "must not contain path separators or '..'")
    if not canonical_name or not canonical_name.strip():
        raise ValidationError("canonical_name", "must not be empty")
    if aliases is not None:
        for a in aliases:
            if not a or not a.strip():
                raise ValidationError("aliases", "must not contain empty strings")


async def _is_private_host(host: str) -> bool:
    """Check if a hostname resolves to a private/loopback IP (SSRF protection).

    DNS resolution is offloaded to a thread to avoid blocking the event loop.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — resolve DNS asynchronously
        import socket
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.run_in_executor(None, lambda: socket.getaddrinfo(host, None))
        except socket.gaierror:
            return False  # unresolvable host → let downstream fail
        for info in infos:
            try:
                a = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            for net in _PRIVATE_NETS:
                if a in net:
                    return True
        return False

    for net in _PRIVATE_NETS:
        if addr in net:
            return True
    return False


def _sanitize_scp_id(scp_id: str) -> str:
    """Strip path separators and dangerous chars from scp_id for filesystem use."""
    return _PATH_UNSAFE_RE.sub("_", scp_id)


def _validate_card_pose(pose: str) -> None:
    if pose not in _VALID_CARD_POSES and not _SPECIAL_POSE_RE.fullmatch(pose):
        raise ValidationError("pose", f"must be one of {sorted(_VALID_CARD_POSES)} or hint:<sha256[:10]>")


def _validate_card_angle(angle: str) -> None:
    if angle not in _ANGLE_DESCRIPTIONS:
        raise ValidationError("angle", f"must be one of {list(_ANGLE_DESCRIPTIONS)}")


def _normalize_pose(pose: object) -> str:
    """Defensive pose mapping (Story 8.3 Interfaces): anything but "sitting" is
    "standing" — covers an old checkpoint carrying a pre-8.1 or malformed value."""
    return "sitting" if pose == "sitting" else "standing"


def pose_hint_key(hint: str) -> str:
    """Deterministic storage key for Story 8.4 on-demand special-pose cards."""
    return "hint:" + hashlib.sha256(hint.strip().lower().encode()).hexdigest()[:10]


def _first_available_angle(character: CharacterModel) -> str | None:
    """Prefer front, otherwise return any standing angle path available on the row."""
    for angle in ("front", "three_quarter", "side", "back"):
        if getattr(character, _ANGLE_FIELD_NAMES[angle]):
            return angle
    return None


# ── Service ───────────────────────────────────────────────────────────────────


class CharacterService:
    """Manages character CRUD, reference image search/download, and multi-angle generation."""

    def __init__(
        self,
        session: Session,
        image_search: ImageSearch | None = None,
        settings: Settings | None = None,
        wiki_fetch: ScpWikiImageFetch | None = None,
    ) -> None:
        self._session = session
        self._image_search = image_search or DuckDuckGoImageSearch()
        self._settings = settings or Settings()
        self._wiki_fetch = wiki_fetch or ScpWikiImageFetch()

    @property
    def _asset_service(self) -> AssetService:
        return AssetService(self._settings.assets_path, self._session)

    def _abs_asset_path(self, path: str) -> str:
        """Resolve a stored assets/-relative path to a real filesystem path (Story 8.6)."""
        return str(Path(self._settings.assets_path) / path)

    # ── CRUD ──────────────────────────────────────────────────────────────

    def create_character(
        self,
        scp_id: str,
        canonical_name: str,
        aliases: list[str] | None = None,
    ) -> CharacterModel:
        """Create and persist a Character. Raises ValidationError on bad input."""
        _validate_create(scp_id, canonical_name, aliases)

        model = CharacterModel(
            scp_id=scp_id.strip(),
            canonical_name=canonical_name.strip(),
            aliases=aliases or [],
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        logger.info("Character created: id=%s scp=%s name=%r", model.id, model.scp_id, model.canonical_name)
        return model

    def get_character(self, id: str) -> CharacterModel | None:
        """Get a character by ID, or None."""
        return self._session.get(CharacterModel, id)

    def check_existing_character(self, scp_id: str) -> CharacterModel | None:
        """Return the first character for an SCP ID, or None."""
        return self._session.exec(
            select(CharacterModel).where(CharacterModel.scp_id == scp_id)
        ).first()

    def list_characters(self, scp_id: str) -> list[CharacterModel]:
        """List all characters for an SCP ID, newest first."""
        return list(
            self._session.exec(
                select(CharacterModel)
                .where(CharacterModel.scp_id == scp_id)
                .order_by(CharacterModel.created_at.desc())
            ).all()
        )

    def list_all_characters(self) -> list[CharacterModel]:
        """List all characters in the database, newest first."""
        return list(
            self._session.exec(
                select(CharacterModel).order_by(CharacterModel.created_at.desc())
            ).all()
        )

    def update_character(self, id: str, **fields) -> CharacterModel:
        """Partial update of character fields. Returns the updated model.

        Only fields in ``_UPDATE_ALLOWLIST`` are applied — unknown keys are
        silently ignored. ``updated_at`` is always refreshed to current time.
        """
        model = self._session.get(CharacterModel, id)
        if model is None:
            raise LookupError(f"Character not found: {id}")
        from datetime import datetime, timezone
        for k, v in fields.items():
            if k in _UPDATE_ALLOWLIST and hasattr(model, k):
                setattr(model, k, v)
        model.updated_at = datetime.now(tz=timezone.utc).isoformat()
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        logger.info("Character updated: id=%s fields=%s", id, list(fields.keys()))
        return model

    def save_card(self, scp_id: str, pose: str, angle: str, image_path: str) -> CharacterCardModel:
        """Upsert a pose-aware character card row.

        Pipeline-generated cards are auto-approved (Story 8.6, Jay 2026-07-08) — there
        is no human curation step mid-run, so gating them behind a manual approval
        would silently break 8.4's on-demand special-pose cards (generated and
        consumed within the same run).
        """
        _validate_card_pose(pose)
        _validate_card_angle(angle)
        epoch = self._asset_service.style_epoch
        existing = self.get_card(scp_id, pose, angle, include_drafts=True)
        if existing is None:
            model = CharacterCardModel(
                scp_id=scp_id, pose=pose, angle=angle, image_path=image_path,
                status="approved", style_epoch=epoch,
            )
        else:
            model = existing
            model.image_path = image_path
            model.status = "approved"
            model.style_epoch = epoch
        self._session.add(model)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            model = self.get_card(scp_id, pose, angle, include_drafts=True)
            if model is None:
                raise
            model.image_path = image_path
            model.status = "approved"
            model.style_epoch = epoch
            self._session.add(model)
            self._session.commit()
        self._session.refresh(model)
        return model

    def get_card(
        self, scp_id: str, pose: str, angle: str, *, include_drafts: bool = False,
    ) -> CharacterCardModel | None:
        """Return the card row for a `(scp_id, pose, angle)` key, or None.

        Pipeline consumers only ever see approved cards (AC4) — pass
        ``include_drafts=True`` only for identity lookups (upsert) that must find
        the row regardless of status.
        """
        card = self._session.exec(
            select(CharacterCardModel).where(
                CharacterCardModel.scp_id == scp_id,
                CharacterCardModel.pose == pose,
                CharacterCardModel.angle == angle,
            )
        ).first()
        if card is None or include_drafts:
            return card
        return card if card.status == "approved" else None

    def delete_character(self, id: str) -> None:
        """Delete a character and all associated records (references, candidates, cards)."""
        model = self._session.get(CharacterModel, id)
        if model is None:
            raise LookupError(f"Character not found: {id}")
        # Cascade-delete reference images
        refs = self._session.exec(
            select(ReferenceImageModel).where(ReferenceImageModel.character_id == id)
        ).all()
        for ref in refs:
            self._session.delete(ref)
        # Cascade-delete candidates. Regression: this used to only null the FK
        # ("orphan" the row) instead of deleting it, but list_candidates() and
        # the /{id} detail route both look candidates up by the scp_id *string*,
        # not character_id — so a deleted character's stale (possibly "ready")
        # candidates would get silently "adopted" by any future character
        # created for the same scp_id, making it appear fully generated
        # without ever running generation.
        candidates = self._session.exec(
            select(CandidateModel).where(CandidateModel.character_id == id)
        ).all()
        for candidate in candidates:
            self._session.delete(candidate)
        cards = self._session.exec(
            select(CharacterCardModel).where(CharacterCardModel.scp_id == model.scp_id)
        ).all()
        for card in cards:
            self._session.delete(card)
        self._session.delete(model)
        self._session.commit()
        logger.info(
            "Character deleted: id=%s (cleaned %d refs, %d candidates, %d cards)",
            id, len(refs), len(candidates), len(cards),
        )

    # ── Reference Image Search ────────────────────────────────────────────

    async def search_references(
        self,
        scp_id: str,
        workspace_path: str | Path,
        max_results: int = 10,
    ) -> list[ReferenceImageModel]:
        """Search DuckDuckGo for SCP reference images, download with safety checks.

        Deduplicates: if references already exist in DB for this scp_id's character,
        skips the search entirely and returns existing refs.
        """
        character = self.check_existing_character(scp_id)
        if character is None:
            raise LookupError(f"No character found for scp_id={scp_id}. Create one first.")

        # Deduplication check
        existing = self.get_reference_images(character.id)
        if existing:
            logger.info("References already exist for %s (%d), skipping search", scp_id, len(existing))
            return existing

        return await self._do_search_and_download(
            character=character,
            query=f"{scp_id} SCP Foundation",
            max_results=max_results,
            workspace_path=workspace_path,
            scp_id=scp_id,
        )

    async def research_references(
        self,
        scp_id: str,
        workspace_path: str | Path,
        max_results: int = 10,
    ) -> list[ReferenceImageModel]:
        """Clear existing references and do a fresh search."""
        character = self.check_existing_character(scp_id)
        if character is None:
            raise LookupError(f"No character found for scp_id={scp_id}")

        # Delete existing reference images
        existing = self._session.exec(
            select(ReferenceImageModel).where(ReferenceImageModel.character_id == character.id)
        ).all()
        for ref in existing:
            self._session.delete(ref)
        self._session.commit()

        return await self._do_search_and_download(
            character=character,
            query=f"{scp_id} SCP Foundation",
            max_results=max_results,
            workspace_path=workspace_path,
            scp_id=scp_id,
        )

    async def _do_search_and_download(
        self,
        character: CharacterModel,
        query: str,
        max_results: int,
        workspace_path: str | Path,
        scp_id: str,
    ) -> list[ReferenceImageModel]:
        """Internal: search, download with safety checks, persist ReferenceImage records.

        Tries the SCP Wiki's official page image first (attributable, canonical source);
        falls back to ``self._image_search`` (DuckDuckGo) unchanged on any wiki miss.
        """
        safe_scp = _sanitize_scp_id(scp_id)
        refs_dir = Path(workspace_path) / safe_scp / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)

        try:
            wiki_image = await self._wiki_fetch.fetch(scp_id)
        except Exception as exc:
            # ScpWikiImageFetch.fetch() documents "never raises", but this call site
            # must not depend on that promise — any violation must fall back to
            # search, not escalate to CharacterService's caller as total failure.
            logger.warning("SCP Wiki fetch raised for %s: %s; falling back to search", scp_id, exc)
            wiki_image = None
        if wiki_image is not None:
            try:
                ext = await self._download_reference_image(wiki_image.image_url, refs_dir, 1)
                record = ReferenceImageModel(
                    character_id=character.id,
                    url=wiki_image.page_url,  # AC3: page URL preserved for CC BY-SA attribution
                    local_path=str(refs_dir / f"ref_1.{ext}"),
                )
                self._session.add(record)
                self._session.commit()
            except Exception as exc:
                logger.warning("SCP Wiki image download/persist failed for %s: %s; falling back to search", scp_id, exc)
            else:
                logger.info("Downloaded SCP Wiki reference image for %s", scp_id)
                return [record]

        results = await self._image_search.search(query=query, max_results=max_results)
        logger.info("Search returned %d results for %r", len(results), query)

        records: list[ReferenceImageModel] = []
        for i, result in enumerate(results, start=1):
            try:
                ext = await self._download_reference_image(result["url"], refs_dir, i)
            except Exception as exc:
                logger.warning("Skipping reference image %d: %s", i, exc)
                continue

            record = ReferenceImageModel(
                character_id=character.id,
                url=result["url"],
                local_path=str(refs_dir / f"ref_{i}.{ext}"),
            )
            self._session.add(record)
            records.append(record)

        self._session.commit()
        logger.info("Downloaded %d reference images for %s", len(records), scp_id)
        return records

    async def _download_reference_image(
        self,
        url: str,
        refs_dir: Path,
        num: int,
    ) -> str:
        """Download a single reference image with safety checks.

        Returns the file extension (png/jpg/webp) on success.
        Raises on any safety violation or download failure.

        Redirects are NOT followed to prevent SSRF bypass (redirect to private IP).
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""

        # SSRF protection: block private/loopback IPs
        if await _is_private_host(host):
            raise ValueError(f"Blocked private IP: {host}")

        # Only allow http/https
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Blocked scheme: {parsed.scheme}")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_DOWNLOAD_TIMEOUT),
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=False,  # Do NOT follow redirects — SSRF protection
            max_redirects=0,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            # Content-Type check
            ct = resp.headers.get("content-type", "")
            if not _CONTENT_TYPE_RE.match(ct):
                raise ValueError(f"Disallowed content-type: {ct!r}")

            data = resp.content

        # Size check
        if len(data) > _MAX_FILE_SIZE:
            raise ValueError(f"File too large: {len(data)} bytes (max {_MAX_FILE_SIZE})")

        # Determine extension from content-type
        ext = ct.split("/")[-1].split(";")[0]  # "image/png" → "png"
        if ext == "jpeg":
            ext = "jpg"

        out_path = refs_dir / f"ref_{num}.{ext}"
        out_path.write_bytes(data)
        logger.debug("Downloaded reference image: %s → %s (%d bytes)", url, out_path, len(data))
        return ext

    def get_reference_images(self, character_id: str) -> list[ReferenceImageModel]:
        """Get all reference images for a character."""
        return list(
            self._session.exec(
                select(ReferenceImageModel).where(
                    ReferenceImageModel.character_id == character_id
                )
            ).all()
        )

    # ── Vision LLM Descriptor Enrichment (AC1, AC2) ───────────────────────

    @observe(name="character-vision-enrich")
    async def enrich_descriptor_from_references(
        self,
        scp_id: str,
        ref_image_paths: list[str],
    ) -> str | None:
        """Analyze reference images with Vision LLM and return an enriched visual descriptor.

        Loads images as base64 data URIs and sends them to the DashScope Qwen-VL
        multimodal API with a vision enrichment prompt. Returns the descriptor string
        on success, or ``None`` on failure (non-fatal — the pipeline continues).
        """
        if not ref_image_paths:
            logger.warning("enrich_descriptor_from_references: no reference images provided for %s", scp_id)
            return None

        s = self._settings
        if not s.character_vision_api_key:
            logger.warning("enrich_descriptor_from_references: vision API key not configured")
            return None

        # Load images as base64 data URIs
        image_parts = []
        for path_str in ref_image_paths[:3]:  # max 3 images to keep context small
            try:
                p = Path(path_str)
                if not p.exists():
                    logger.warning("Reference image not found: %s", path_str)
                    continue
                raw = p.read_bytes()
                mime = mimetypes.guess_type(path_str)[0] or "image/png"
                b64 = base64.b64encode(raw).decode("ascii")
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
                logger.debug("Loaded reference image: %s (%d bytes)", path_str, len(raw))
            except Exception as exc:
                logger.warning("Failed to load reference image %s: %s", path_str, exc)
                continue

        if not image_parts:
            logger.warning("enrich_descriptor_from_references: no valid images loaded for %s", scp_id)
            return None

        # Build prompt — try Langfuse prompt, fall back to built-in
        prompt_text = self._load_vision_enrichment_prompt()

        # Build multimodal message
        content_parts: list[dict] = [{"type": "text", "text": prompt_text}]
        content_parts.extend(image_parts)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(
                    _DASHSCOPE_VISION_ENDPOINT,
                    headers={"Authorization": f"Bearer {s.character_vision_api_key}"},
                    json={
                        "model": s.character_vision_model,
                        "messages": [{"role": "user", "content": content_parts}],
                        "max_tokens": s.character_vision_max_tokens,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            descriptor = data["choices"][0]["message"]["content"].strip()
            if not descriptor:
                logger.warning("enrich_descriptor_from_references: empty response from Vision LLM for %s", scp_id)
                return None
            logger.info("Vision LLM enriched descriptor for %s (%d chars)", scp_id, len(descriptor))
            return descriptor

        except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError) as exc:
            logger.warning("enrich_descriptor_from_references: Vision LLM call failed for %s: %s", scp_id, exc)
            try:
                get_client().update_current_span(level="ERROR", status_message=str(exc))
            except Exception:  # noqa: BLE001 — tracing must never break the pipeline
                pass
            # Fallback: use existing visual_descriptor if present
            character = self.check_existing_character(scp_id)
            if character and character.visual_descriptor:
                logger.info("Falling back to existing visual_descriptor for %s", scp_id)
                return character.visual_descriptor
            return None

    @staticmethod
    def _load_vision_enrichment_prompt() -> str:
        """Load the vision enrichment prompt, trying Langfuse first then local file then built-in."""
        # 1. Try Langfuse Prompt Hub
        try:
            from yt_flow.services.prompt_service import get_prompt
            return get_prompt("character-vision-enrichment").compile()
        except Exception:
            pass

        # 2. Try local file (resolve relative to project root)
        import os
        project_root = os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd())
        prompt_path = Path(project_root) / "prompts" / "character" / "vision_enrichment.md"
        if prompt_path.exists():
            return prompt_path.read_text()

        # 3. Built-in fallback
        return (
            "You are a forensic visual analyst specializing in character design for animation and illustration.\n\n"
            "Analyze the provided reference image(s) of an SCP Foundation character. Produce a single, dense "
            "paragraph (4-8 sentences) describing the character's visual appearance in exhaustive detail, "
            "suitable as a prompt for an image generation model.\n\n"
            "Cover these dimensions:\n"
            "- Silhouette & Proportions: overall body shape, height/build, limb proportions, head-to-body ratio\n"
            "- Texture & Materials: skin texture, clothing/armor materials, any surface quality\n"
            "- Color Palette: dominant colors with specific descriptive names, accent colors, gradients or patterns\n"
            "- Distinguishing Features: any anomalous traits, scars, markings, accessories, equipment\n"
            "- Lighting & Mood: implied lighting, overall mood conveyed by the design\n"
            "- Style Notes: whether the art style is realistic, stylized, anime, painterly, etc.\n\n"
            "Return ONLY the descriptor paragraph, no preamble, no labels, no markdown formatting."
        )

    # ── Multi-Angle Generation (AC3, AC8) ──────────────────────────────────

    async def generate_candidates_from_reference(
        self,
        scp_id: str,
        ref_image_path: str | None,
        angles: list[str] | None = None,
        pose: str = "standing",
        negative_suffix: str | None = None,
        stage: bool = False,
    ) -> list[str]:
        """Generate character images for each angle using the configured provider.

        For each angle, compiles an angle-specific prompt, calls the provider's
        ``generate()`` (i2i with t2i fallback), and saves the result to
        ``assets/characters/{scp_id}/epoch_{style_epoch}/{angle}_candidate_1.png``
        (Story 8.6 — the asset library, not the run-scoped workspace).

        Args:
            scp_id: The SCP identifier (e.g. "SCP-096").
            ref_image_path: Path to the reference image for i2i base.
            angles: List of angle names; defaults to all 4 canonical angles.
            negative_suffix: Optional per-call negative-prompt terms (Story 8.15).
            stage: Write files into the *next* style epoch only — no manifest
                entry, no approval, no card row. Nothing runtime reads is touched,
                so a staged set is invisible until ``approve_stock_cast.py`` runs.

        Returns:
            List of saved image file paths, relative to ``assets_path``.
        """
        _validate_card_pose(pose)
        if angles is None:
            angles = list(_CANONICAL_ANGLES)
        for angle in angles:
            _validate_card_angle(angle)

        s = self._settings
        assets_root = Path(s.assets_path)
        safe_scp = _sanitize_scp_id(scp_id)
        asset_service = self._asset_service
        epoch = asset_service.style_epoch + (1 if stage else 0)
        chars_dir = assets_root / "characters" / safe_scp / f"epoch_{epoch}"
        chars_dir.mkdir(parents=True, exist_ok=True)

        provider = self._get_image_provider()
        if not getattr(provider, "produces_alpha", True):
            raise RuntimeError(
                f"{provider.__class__.__name__} does not produce alpha sprites; use the ComfyUI character provider"
            )
        visual_desc = self._get_visual_descriptor(scp_id)

        saved_paths: list[str] = []
        failed_angles: list[str] = []

        for angle in angles:
            angle_desc = _ANGLE_DESCRIPTIONS.get(angle, f"character {angle} view, full body")
            pose_desc = _POSE_DESCRIPTIONS.get(pose, pose)
            prompt = self._compile_generation_prompt(
                visual_descriptor=visual_desc or "",
                angle=angle,
                angle_description=f"{angle_desc}, {pose_desc}",
                scp_id=scp_id,
            )

            out_path = chars_dir / (
                f"{angle}_candidate_1.png" if pose == "standing" else f"{pose}_{angle}.png"
            )
            try:
                img_bytes = await provider.generate(
                    prompt=prompt,
                    ref_image_path=ref_image_path,
                    width=s.character_image_width,
                    height=s.character_image_height,
                    ipadapter_weight=_ANGLE_IPADAPTER_WEIGHTS.get(angle),
                    negative_suffix=negative_suffix,
                )
                if not has_alpha(img_bytes):
                    raise ValueError(f"generated card for {scp_id} angle={angle} has no alpha channel")
                out_path.write_bytes(img_bytes)
                rel_path = str(out_path.relative_to(assets_root))
                if not stage:
                    # Manifest write before the DB row so a mid-write failure never
                    # leaves an "approved" CharacterCard with no manifest provenance.
                    asset_service.add_asset(
                        f"{safe_scp}/{pose}_{angle}", rel_path,
                        source={"type": "comfyui_generation", "ipadapter_weight": _ANGLE_IPADAPTER_WEIGHTS.get(angle)},
                        card_key=safe_scp, pose=pose, angle=angle,
                    )
                    asset_service.approve_asset(f"{safe_scp}/{pose}_{angle}")
                    if pose != "standing":
                        self.save_card(scp_id, pose, angle, rel_path)
                saved_paths.append(rel_path)
                logger.info(
                    "Generated %s candidate for %s → %s (%d bytes, i2i=%s)",
                    angle, scp_id, out_path, len(img_bytes), provider.supports_i2i,
                )
            except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                logger.warning("Failed to generate %s candidate for %s: %s", angle, scp_id, exc)
                failed_angles.append(angle)
                # Continue with next angle; don't fail the whole batch
            except Exception:
                logger.exception("Unexpected error generating %s candidate for %s", angle, scp_id)
                failed_angles.append(angle)

        if failed_angles and not saved_paths:
            logger.error("All %d angles failed for %s: %s", len(failed_angles), scp_id, failed_angles)
        return saved_paths

    async def generate_cards_from_descriptor(
        self,
        card_key: str,
        descriptor: str,
        *,
        pose: str = "standing",
        anchor_path: str | None = None,
        angles: list[str] | None = None,
        negative_suffix: str | None = None,
        enrich_ban: str | None = None,
        stage: bool = False,
    ) -> list[str]:
        """Generate and persist a card library from a descriptor.

        Front is generated t2i by default, then non-front angles self-reference the
        front card for identity consistency. An explicit anchor can condition the
        front angle instead.

        ``enrich_ban`` is a phrase stripped from the enriched descriptor before it
        is persisted. The enrichment prompt says "an SCP Foundation character", so
        its read-back reinjects into every non-front angle the exact token the STOCK
        descriptors were purged of — the mask attractor (Story 8.15). Scrubbing beats
        skipping enrichment outright: the read-back is what keeps the four angles the
        same person, and without it the cards drifted into three different faces.

        With ``stage=True`` the cards land in the next style epoch and the live
        ``angle_*_path`` columns are left alone — ``_resolve_card_path`` reads those
        columns with no status or epoch filter, so repointing them *is* going live.
        """
        _validate_card_pose(pose)
        if angles is None:
            angles = list(_CANONICAL_ANGLES)
        for angle in angles:
            _validate_card_angle(angle)
        if "front" in angles:
            angles = ["front", *(angle for angle in angles if angle != "front")]

        character = self._ensure_character(card_key)
        if descriptor and character.visual_descriptor != descriptor:
            character = self.update_character(character.id, visual_descriptor=descriptor)

        saved: list[str] = []
        front_path: str | None = anchor_path
        angle_paths: dict[str, str] = {}
        for angle in angles:
            if angle != "front" and front_path is None:
                logger.warning(
                    "Skipping %s card for %s pose=%s because no front/anchor image is available",
                    angle, card_key, pose,
                )
                continue
            ref_path = anchor_path if angle == "front" else (
                self._abs_asset_path(front_path) if front_path else None
            )
            generated = await self.generate_candidates_from_reference(
                card_key,
                ref_image_path=ref_path,
                angles=[angle],
                pose=pose,
                negative_suffix=negative_suffix,
                stage=stage,
            )
            if not generated:
                continue
            path = generated[0]
            saved.append(path)
            if angle == "front":
                front_path = path
            if angle == "front" and anchor_path is None:
                # Describe the just-generated face/mask/insignia in text so the
                # self-referencing angles below stay the same person, not just
                # the same outfit — IPAdapter alone doesn't lock facial identity.
                enriched = await self.enrich_descriptor_from_references(card_key, [self._abs_asset_path(path)])
                if enriched and enrich_ban:
                    enriched = _scrub_phrase(enriched, enrich_ban)
                if enriched:
                    # Append, never replace. The enrichment prompt has dimensions for
                    # silhouette, texture, outfit palette, anomalous traits, lighting
                    # and art style — but none for hair, eyes or face, so its read-back
                    # cannot carry a human's identity. Replacing the caller's descriptor
                    # with it dropped exactly the attributes the non-front angles need:
                    # STOCK cards came back with the front's black hair turning brown or
                    # teal and the face changing person between angles. Keeping the
                    # authored text as the spine fixes that; the read-back still adds
                    # the outfit and material specifics it is good at (Story 8.15).
                    merged = f"{descriptor}\n{enriched}" if descriptor else enriched
                    character = self.update_character(character.id, visual_descriptor=merged)
            if pose == "standing":
                angle_paths[angle] = path

        if pose == "standing" and angle_paths and not stage:
            updates: dict[str, str] = {f"angle_{angle}_path": path for angle, path in angle_paths.items()}
            if "front" in angle_paths:
                updates["selected_image_path"] = angle_paths["front"]
            self.update_character(character.id, **updates)
        return saved

    async def generate_special_pose_card(self, card_key: str, pose_hint: str) -> str | None:
        """Generate one front-angle special-pose card, or ``None`` on any recoverable miss.

        Story 8.4 keeps special poses anchored to an existing standing front card:
        no front identity anchor means no generation, so we never t2i a stranger.
        """
        hint_key = pose_hint_key(pose_hint)
        character = self.check_existing_character(card_key)
        front_path = character.angle_front_path if character is not None else None
        if not front_path:
            logger.warning("generate_special_pose_card: no standing front card for %s", card_key)
            return None
        front_path = self._abs_asset_path(front_path)

        provider = self._get_image_provider()
        if not getattr(provider, "produces_alpha", True):
            logger.warning(
                "generate_special_pose_card: %s does not produce alpha sprites",
                provider.__class__.__name__,
            )
            return None

        visual_desc = character.visual_descriptor or self._get_visual_descriptor(card_key) or ""
        prompt = self._compile_generation_prompt(
            visual_descriptor=f"{visual_desc}\nSpecial pose: {pose_hint.strip()}",
            angle="front",
            angle_description=(
                f"{_ANGLE_DESCRIPTIONS['front']}, {pose_hint.strip()}, "
                "studio background, full body, single subject"
            ),
            scp_id=card_key,
        )

        safe_scp = _sanitize_scp_id(card_key)
        assets_root = Path(self._settings.assets_path)
        asset_service = self._asset_service
        chars_dir = assets_root / "characters" / safe_scp / f"epoch_{asset_service.style_epoch}"
        chars_dir.mkdir(parents=True, exist_ok=True)
        out_path = chars_dir / f"{hint_key.replace(':', '_')}_front.png"
        try:
            img_bytes = await provider.generate(
                prompt=prompt,
                ref_image_path=front_path,
                width=self._settings.character_image_width,
                height=self._settings.character_image_height,
                ipadapter_weight=_ANGLE_IPADAPTER_WEIGHTS["front"],
            )
            if not has_alpha(img_bytes):
                raise ValueError(f"generated special-pose card for {card_key} has no alpha channel")
            out_path.write_bytes(img_bytes)
            rel_path = str(out_path.relative_to(assets_root))
            # Manifest write before the DB row (see generate_candidates_from_reference).
            asset_service.add_asset(
                f"{safe_scp}/{hint_key}_front", rel_path,
                source={"type": "comfyui_generation", "ipadapter_weight": _ANGLE_IPADAPTER_WEIGHTS["front"]},
                card_key=safe_scp, pose=hint_key, angle="front",
            )
            asset_service.approve_asset(f"{safe_scp}/{hint_key}_front")
            self.save_card(card_key, hint_key, "front", rel_path)
            logger.info("Generated special-pose card for %s pose=%s -> %s", card_key, hint_key, out_path)
            return rel_path
        except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "generate_special_pose_card: failed for %s pose_hint=%r: %s",
                card_key, pose_hint, exc,
            )
            return None

    def _ensure_character(self, scp_id: str) -> CharacterModel:
        character = self.check_existing_character(scp_id)
        if character is not None:
            return character
        try:
            return self.create_character(scp_id, scp_id)
        except IntegrityError:
            self._session.rollback()
            character = self.check_existing_character(scp_id)
            if character is None:
                raise
            return character

    def _get_image_provider(self):
        """Lazy-init the CharacterImageProvider from settings."""
        from yt_flow.services.character_image_provider import create_provider
        return create_provider(self._settings)

    def _get_visual_descriptor(self, scp_id: str) -> str | None:
        """Get the current visual descriptor for an SCP character."""
        character = self.check_existing_character(scp_id)
        if character and character.visual_descriptor:
            return character.visual_descriptor
        return None

    @staticmethod
    def _compile_generation_prompt(
        visual_descriptor: str,
        angle: str,
        angle_description: str,
        scp_id: str,
    ) -> str:
        """Compile the angle-specific generation prompt from template."""
        # 1. Try Langfuse
        try:
            from yt_flow.services.prompt_service import get_prompt
            return get_prompt("character-generation").compile(
                visual_descriptor=visual_descriptor,
                angle=angle,
                angle_description=angle_description,
                scp_id=scp_id,
            )
        except Exception:
            pass

        # 2. Try local file (resolve relative to project root via settings workspace)
        import os
        project_root = os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd())
        prompt_path = Path(project_root) / "prompts" / "character" / "generation.md"
        if prompt_path.exists():
            template = prompt_path.read_text()
            return template.format(
                visual_descriptor=visual_descriptor,
                angle=angle,
                angle_description=angle_description,
                scp_id=scp_id,
            )

        # 3. Built-in fallback
        return (
            f"Character visual description: {visual_descriptor}\n"
            f"Angle: {angle} — {angle_description}\n"
            f"SCP ID: {scp_id}\n\n"
            "Create a transparent-sprite source image: one single subject, full body, feet visible, "
            "centered on canvas, clean silhouette, no crop, no bust portrait. Place the subject on a "
            "plain flat light-gray studio background only, with no scenery, room, unrelated furniture, "
            "unrelated props, environment detail, text, watermark, border, or extra characters; a plain "
            "minimal chair or stool is allowed only when the requested pose explicitly requires sitting. "
            "Lighting is soft and even "
            "studio lighting with no cast shadow, no drop shadow, and no dramatic or high-contrast lighting "
            "on the subject or floor. Suitable for later background removal and video compositing. "
            "Maintain consistent character design, proportions, and color palette across all angles — the "
            "same face, mask or head design, and clothing markings must appear identical regardless of angle."
        )

    # ── Candidate Tracking (AC4) ──────────────────────────────────────────

    def create_candidate_batch(
        self,
        scp_id: str,
        angles: list[str] | None = None,
    ) -> list[CandidateModel]:
        """Create pending candidate records for each angle. Returns the list of candidates.

        Deletes any existing candidate row(s) for the same (scp_id, angle) first —
        the table has no real unique constraint (see db/models.py), so calling this
        twice for the same angle (e.g. a regenerate-on-failure retry) would otherwise
        leave ambiguous duplicate rows behind.
        """
        if angles is None:
            angles = ["front", "back", "side", "three_quarter"]

        character = self.check_existing_character(scp_id)
        candidates: list[CandidateModel] = []

        for angle in angles:
            for stale in self._session.exec(
                select(CandidateModel).where(
                    CandidateModel.scp_id == scp_id,
                    CandidateModel.angle == angle,
                )
            ).all():
                self._session.delete(stale)

            candidate = CandidateModel(
                character_id=character.id if character else None,
                scp_id=scp_id,
                angle=angle,
                candidate_num=1,
                status="pending",
            )
            self._session.add(candidate)
            candidates.append(candidate)

        self._session.commit()
        logger.info("Created %d pending candidates for %s", len(candidates), scp_id)
        return candidates

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
        image_path: str | None = None,
    ) -> CandidateModel:
        """Update a candidate's status and optionally its image path."""
        candidate = self._session.get(CandidateModel, candidate_id)
        if candidate is None:
            raise LookupError(f"Candidate not found: {candidate_id}")
        candidate.status = status
        if image_path is not None:
            candidate.image_path = image_path
        self._session.add(candidate)
        self._session.commit()
        self._session.refresh(candidate)
        return candidate

    def list_candidates(
        self,
        scp_id: str,
        angle: str | None = None,
    ) -> list[CandidateModel]:
        """List candidates for an SCP, optionally filtered by angle."""
        stmt = select(CandidateModel).where(CandidateModel.scp_id == scp_id)
        if angle:
            stmt = stmt.where(CandidateModel.angle == angle)
        return list(self._session.exec(stmt).all())

    def get_candidate_status(self, candidate_id: str) -> CandidateModel | None:
        """Get a single candidate by ID."""
        return self._session.get(CandidateModel, candidate_id)

    # ── Candidate Selection + Memorization (AC5, AC6) ─────────────────────

    def select_candidate(
        self,
        scp_id: str,
        candidate_num: int,
        angle: str,
    ) -> CharacterModel:
        """Select a candidate image for an angle and update the character record.

        Maps angle → angle_*_path on the Character record. Auto-creates the
        character record if it doesn't exist yet (memorization).

        Returns:
            Updated character model.
        """
        # Validate angle name
        if angle not in _ANGLE_DESCRIPTIONS:
            raise ValueError(
                f"Invalid angle: {angle!r}. Must be one of {list(_ANGLE_DESCRIPTIONS.keys())}"
            )

        # Find or create character
        character = self.check_existing_character(scp_id)
        if character is None:
            character = self.create_character(scp_id, scp_id)  # memorization: auto-create

        # Find the matching candidate
        candidates = self._session.exec(
            select(CandidateModel).where(
                CandidateModel.scp_id == scp_id,
                CandidateModel.angle == angle,
                CandidateModel.candidate_num == candidate_num,
            )
        ).all()
        if not candidates:
            raise LookupError(
                f"No candidate found for {scp_id} angle={angle} num={candidate_num}"
            )
        candidate = candidates[0]
        if candidate.status != "ready":
            raise ValueError(
                f"Candidate {candidate.id} is not ready (status={candidate.status})"
            )
        if not candidate.image_path:
            raise ValueError(f"Candidate {candidate.id} has no image path")

        # Map angle to the correct field; batch both updates in one call
        angle_field = f"angle_{angle}_path"
        updates: dict[str, str | None] = {angle_field: candidate.image_path}
        if angle == "front":
            updates["selected_image_path"] = candidate.image_path

        character = self.update_character(character.id, **updates)

        logger.info(
            "Selected candidate %s for %s angle=%s → %s",
            candidate.id, scp_id, angle, candidate.image_path,
        )
        return character

    def finalize_character(self, id: str) -> CharacterModel:
        """Finalize character after all 4 angles have been selected.

        Verifies all 4 angle_*_path fields are populated. If so, marks the
        character as complete and returns it.
        """
        character = self.get_character(id)
        if character is None:
            raise LookupError(f"Character not found: {id}")

        angles = ["front", "back", "side", "three_quarter"]
        missing = []
        for angle in angles:
            field = f"angle_{angle}_path"
            if not getattr(character, field, None):
                missing.append(angle)

        if missing:
            raise ValueError(f"Missing angles for {id}: {missing}")

        logger.info("Character finalized: %s (%s)", id, character.scp_id)
        return character

    # ── Cast Resolution (Story 1.13 → reworked in Story 8.3) ────────────────

    async def resolve_cast_cards(
        self,
        scp_id: str,
        scenes: list[dict],
    ) -> dict[str, list[dict]]:
        """Resolve every shot's ``cast`` into concrete card assets.

        Replaces the 1.13 all-shots angle override (D13): overlay membership
        now comes from ``ShotData.cast`` (Story 8.1), not "does this shot have
        a character_path". LLM angle selection is spent only on shots whose
        cast contains the run's own entity (``scp_id``); every other cast
        member (stock/derived extras) resolves deterministically to the
        "front" angle — no LLM call for extras until variety is actually
        wanted (Saved Question 3).

        Returns ``{shot_key: [card, ...]}`` in cast order for every shot whose
        cast is non-empty; a shot with an empty cast or zero resolvable cards
        is simply absent — no tri-state ``None`` (that only ever meant "no
        Character row for scp_id", which no longer applies since stock cards
        exist independently of the entity). Each ``card`` dict carries
        ``card_key``, ``pose``, ``angle``, ``path``, ``fallback`` (Interfaces)
        plus ``position``/``depth``/``motion_style``/``motion_energy``/
        ``movement_mode``/``movement_direction``/``movement_pace`` copied
        straight from the cast member (Story 8.8 adds motion_*, 8.9 adds
        movement_*, same default-on-missing convention as position/depth) —
        video_node needs them for stacking/scale/anchor/motion and re-deriving
        them after members are filtered out would just duplicate this method's
        skip logic.
        """
        entity_catalogue: list[dict] = []
        for scene in sorted(scenes, key=lambda s: s["scene_num"]):
            for shot in scene.get("shots", []):
                if any(
                    isinstance(m, dict)
                    and m.get("card_key") == scp_id
                    and not (
                        isinstance(m.get("pose_hint"), str)
                        and self.get_card(scp_id, pose_hint_key(m["pose_hint"]), "front") is not None
                    )
                    for m in (shot.get("cast") or [])
                ):
                    entity_catalogue.append({
                        "scene_num": scene["scene_num"],
                        "shot_id": shot["shot_id"],
                        "narration": scene.get("narration", ""),
                        "camera_angle": shot.get("camera_angle") or "",
                        "camera_movement": shot.get("camera_movement") or "",
                    })

        entity_angles = (
            await self._select_entity_angles(scp_id, entity_catalogue) if entity_catalogue else {}
        )

        result: dict[str, list[dict]] = {}
        missed_hints: set[tuple[str, str]] = set()
        for scene in scenes:
            for shot in scene.get("shots", []):
                cast = shot.get("cast") or []
                if not cast:
                    continue
                shot_key = f"{scene['scene_num']}:{shot['shot_id']}"
                cards: list[dict] = []
                for member in cast:
                    if not isinstance(member, dict) or not member.get("card_key"):
                        logger.warning(
                            "resolve_cast_cards: malformed cast member in %s, skipping: %r",
                            shot_key, member,
                        )
                        continue
                    card_key = member["card_key"]
                    raw_hint = member.get("pose_hint")
                    if isinstance(raw_hint, str) and raw_hint.strip():
                        hint_pose = pose_hint_key(raw_hint)
                        hint_card = self.get_card(card_key, hint_pose, "front")
                        if hint_card is not None:
                            cards.append({
                                "card_key": card_key,
                                "pose": hint_pose,
                                "angle": "front",
                                "path": self._abs_asset_path(hint_card.image_path),
                                "fallback": False,
                                "angle_fallback": False,
                                "asset_fallback": False,
                                "fallback_reason": None,
                                "position": member.get("position", "center"),
                                "depth": member.get("depth", "mid"),
                                "motion_style": member.get("motion_style", "breath"),
                                "motion_energy": member.get("motion_energy", "medium"),
                                "movement_mode": member.get("movement_mode", "anchored"),
                                "movement_direction": member.get("movement_direction", "none"),
                                "movement_pace": member.get("movement_pace", "slow"),
                            })
                            continue
                        miss = (card_key, hint_pose)
                        if miss not in missed_hints:
                            logger.warning(
                                "resolve_cast_cards: no special-pose card for %s pose=%s; falling back to base pose",
                                card_key, hint_pose,
                            )
                            missed_hints.add(miss)
                    character = self.check_existing_character(card_key)
                    if character is None:
                        logger.warning(
                            "resolve_cast_cards: no character row for cast member %s, skipping", card_key,
                        )
                        continue
                    if card_key == scp_id:
                        pick = entity_angles.get(shot_key, {})
                        angle = pick.get("angle", "front")
                        angle_fallback = pick.get("fallback", False)
                    else:
                        angle = "front" if getattr(character, _ANGLE_FIELD_NAMES["front"]) else (
                            _first_available_angle(character) or "front"
                        )
                        angle_fallback = False
                    pose = _normalize_pose(member.get("pose"))
                    resolved = self._resolve_card_path(character, pose, angle)
                    if resolved is None:
                        logger.warning(
                            "resolve_cast_cards: no card asset for %s pose=%s angle=%s, skipping",
                            card_key, pose, angle,
                        )
                        continue
                    path, resolved_pose, pose_fallback = resolved
                    cards.append({
                        "card_key": card_key,
                        "pose": resolved_pose,
                        "angle": angle,
                        "path": path,
                        "fallback": angle_fallback or pose_fallback,
                        "angle_fallback": angle_fallback,
                        "asset_fallback": pose_fallback,
                        "fallback_reason": (
                            "angle+asset" if angle_fallback and pose_fallback
                            else "angle" if angle_fallback
                            else "asset" if pose_fallback
                            else None
                        ),
                        "position": member.get("position", "center"),
                        "depth": member.get("depth", "mid"),
                        "motion_style": member.get("motion_style", "breath"),
                        "motion_energy": member.get("motion_energy", "medium"),
                        "movement_mode": member.get("movement_mode", "anchored"),
                        "movement_direction": member.get("movement_direction", "none"),
                        "movement_pace": member.get("movement_pace", "slow"),
                    })
                if cards:
                    result[shot_key] = cards

        logger.info(
            "resolve_cast_cards: %d shot(s) with cards for %s", len(result), scp_id,
        )
        return result

    def _resolve_card_path(
        self, character: CharacterModel, pose: str, angle: str,
    ) -> tuple[str, str, bool] | None:
        """Return ``(path, resolved_pose, fallback)`` or ``None`` if unresolvable.

        Non-standing poses read the pose-keyed ``character_cards`` table
        (Story 8.2 Interfaces #4); a pose-miss falls back to the standing card
        for the same angle (``fallback=True``) — standing always exists for a
        resolvable card_key per 8.2's seeding contract, but the fallback
        lookup can still miss on a partially-seeded row (skip, don't crash).
        """
        angle_field = _ANGLE_FIELD_NAMES.get(angle, "angle_front_path")
        if pose != "standing":
            card = self.get_card(character.scp_id, pose, angle)
            if card is not None:
                return self._abs_asset_path(card.image_path), pose, False
            logger.warning(
                "resolve_cast_cards: no %s card for %s angle=%s, falling back to standing",
                pose, character.scp_id, angle,
            )
        path = getattr(character, angle_field)
        if not path:
            return None
        return self._abs_asset_path(path), "standing", pose != "standing"

    @observe(name="select-entity-angles")
    async def _select_entity_angles(
        self, scp_id: str, shot_catalogue: list[dict],
    ) -> dict[str, dict]:
        """LLM angle pick per entity shot. Returns ``{shot_key: {"angle", "fallback"}}``.

        Card-path resolution (including pose) happens separately in
        ``_resolve_card_path`` — this only ever needs to pick an angle name.
        """
        character = self.check_existing_character(scp_id)
        if character is None:
            logger.info("resolve_cast_cards: no character row for entity %s", scp_id)
            return {}

        available_angles: dict[str, str] = {
            angle_name: _ANGLE_DESCRIPTIONS[angle_name]
            for angle_name in _CANONICAL_ANGLES
            if getattr(character, _ANGLE_FIELD_NAMES[angle_name])
        }
        if not available_angles:
            logger.warning("resolve_cast_cards: no angle paths set for entity %s", scp_id)
            return {}

        # Fallback angle used whenever a clean LLM pick isn't possible — prefer "front"
        # but fall through to the first available angle so the pick is always real [AC3].
        fallback_angle = _first_available_angle(character) or next(iter(available_angles))

        prompt_text = self._load_angle_selection_prompt(
            scp_id=scp_id,
            shot_catalogue=shot_catalogue,
            available_angles=available_angles,
        )

        s = self._settings
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    f"{s.deepseek_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
                    json={
                        "model": s.deepseek_model,
                        "messages": [{"role": "user", "content": prompt_text}],
                        "max_tokens": 1024,
                        "temperature": 0.3,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("resolve_cast_cards: LLM call failed for %s: %s", scp_id, exc)
            self._mark_angle_fallback("llm_call_failed", str(exc))
            return self._angle_fallback_map(shot_catalogue, fallback_angle)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("resolve_cast_cards: invalid JSON from LLM: %r", raw[:200])
            self._mark_angle_fallback("invalid_json", raw[:200])
            return self._angle_fallback_map(shot_catalogue, fallback_angle)

        if not isinstance(parsed, list):
            logger.warning("resolve_cast_cards: expected JSON array, got %s", type(parsed).__name__)
            self._mark_angle_fallback("non_array_response", type(parsed).__name__)
            return self._angle_fallback_map(shot_catalogue, fallback_angle)

        # Only catalogue shots are honored — hallucinated or malformed-id LLM
        # entries are ignored and the affected shots get the fallback angle below.
        catalogue_keys = {f"{s['scene_num']}:{s['shot_id']}" for s in shot_catalogue}
        result: dict[str, dict] = {}
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            shot_key = f"{entry.get('scene_num', '?')}:{entry.get('shot_id', '?')}"
            if shot_key not in catalogue_keys:
                continue
            raw_angle = (entry.get("angle") or "").lower()
            angle = raw_angle if raw_angle in _CANONICAL_ANGLES else fallback_angle
            is_fallback = angle != raw_angle
            if angle not in available_angles:
                angle = fallback_angle
                is_fallback = True
            result[shot_key] = {"angle": angle, "fallback": is_fallback}

        for key in catalogue_keys:
            if key not in result:
                result[key] = {"angle": fallback_angle, "fallback": True}

        return result

    @staticmethod
    def _angle_fallback_map(shot_catalogue: list[dict], angle: str) -> dict[str, dict]:
        """Map every catalogued shot to the fallback angle (LLM failed / invalid data)."""
        return {f"{s['scene_num']}:{s['shot_id']}": {"angle": angle, "fallback": True}
                for s in shot_catalogue}

    @staticmethod
    def _mark_angle_fallback(reason: str, detail: str) -> None:
        """Best-effort span WARNING naming which fallback branch fired — today only
        a ``logger.warning``, with nothing distinguishing the branch in Langfuse."""
        try:
            get_client().update_current_span(level="WARNING", status_message=f"{reason}: {detail}")
        except Exception:  # noqa: BLE001 — tracing must never break the pipeline
            pass

    @staticmethod
    def _load_angle_selection_prompt(
        scp_id: str,
        shot_catalogue: list[dict],
        available_angles: dict[str, str],
    ) -> str:
        """Load the angle selection prompt, trying Langfuse first, then local file, then built-in."""
        # 1. Try Langfuse Prompt Hub
        try:
            from yt_flow.services.prompt_service import get_prompt
            return get_prompt("character-angle-selection").compile(
                scp_id=scp_id,
                shot_catalogue=json.dumps(shot_catalogue, indent=2),
                available_angles=json.dumps(available_angles, indent=2),
            )
        except Exception:
            pass

        # 2. Try local file
        import os
        project_root = os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd())
        prompt_path = Path(project_root) / "prompts" / "character" / "angle_selection.md"
        if prompt_path.exists():
            template = prompt_path.read_text()
            return template.replace("{scp_id}", scp_id) \
                           .replace("{shot_catalogue}", json.dumps(shot_catalogue, indent=2)) \
                           .replace("{available_angles}", json.dumps(available_angles, indent=2))

        # 3. Built-in fallback
        return (
            f"You are a film director selecting the best camera angle for each shot of an SCP Foundation video.\n\n"
            f"SCP ID: {scp_id}\n\n"
            f"Available character angles:\n{json.dumps(available_angles, indent=2)}\n\n"
            f"Shot catalogue (all shots needing an angle):\n{json.dumps(shot_catalogue, indent=2)}\n\n"
            "For each shot, select the most appropriate angle based on:\n"
            "- The narration text — what is happening in this scene?\n"
            "- Camera angle and movement metadata — is the shot zooming, panning, or static?\n"
            "- Narrative tension — front for direct confrontation, back for mystery, "
            "side for observation, three_quarter for dialogue\n\n"
            "Return ONLY a JSON array (no markdown, no preamble):\n"
            '[{"scene_num": N, "shot_id": "S...", "angle": "front"}, ...]\n'
        )
