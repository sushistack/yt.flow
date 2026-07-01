"""CharacterService — manages character CRUD, reference image search, and safe downloads.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
Characters live in SQLite, not PipelineState — long-lived configuration. [AD-2]
"""

import asyncio
import base64
import ipaddress
import logging
import mimetypes
import re
from pathlib import Path
from typing import override
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
from yt_flow.db.models import CharacterCandidate as CandidateModel
from yt_flow.db.models import ReferenceImage as ReferenceImageModel
from yt_flow.domain.state import ReferenceImage, SearchResult
from yt_flow.domain.exceptions import ValidationError
from yt_flow.services.image_search import DuckDuckGoImageSearch, ImageSearch

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_DOWNLOAD_TIMEOUT = 30.0
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
    "front": "character front view, facing camera, full body",
    "back": "character back view, seen from behind, full body",
    "side": "character side profile view, full body",
    "three_quarter": "character three-quarter view, 45 degree angle, full body",
}
_CANONICAL_ANGLES = list(_ANGLE_DESCRIPTIONS.keys())  # ["front", "back", "side", "three_quarter"]

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


# ── Service ───────────────────────────────────────────────────────────────────


class CharacterService:
    """Manages character CRUD, reference image search/download, and multi-angle generation."""

    def __init__(
        self,
        session: Session,
        image_search: ImageSearch | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._image_search = image_search or DuckDuckGoImageSearch()
        self._settings = settings or Settings()

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

    def delete_character(self, id: str) -> None:
        """Delete a character and all associated records (references, candidates)."""
        model = self._session.get(CharacterModel, id)
        if model is None:
            raise LookupError(f"Character not found: {id}")
        # Cascade-delete reference images
        refs = self._session.exec(
            select(ReferenceImageModel).where(ReferenceImageModel.character_id == id)
        ).all()
        for ref in refs:
            self._session.delete(ref)
        # Cascade-delete candidates (nullable FK — set NULL for surviving records)
        candidates = self._session.exec(
            select(CandidateModel).where(CandidateModel.character_id == id)
        ).all()
        for candidate in candidates:
            candidate.character_id = None
            self._session.add(candidate)
        self._session.delete(model)
        self._session.commit()
        logger.info("Character deleted: id=%s (cleaned %d refs, %d candidates)", id, len(refs), len(candidates))

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
        """Internal: search, download with safety checks, persist ReferenceImage records."""
        safe_scp = _sanitize_scp_id(scp_id)
        refs_dir = Path(workspace_path) / safe_scp / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)

        results = await self._image_search.search(query=query, max_results=max_results)
        logger.info("Search returned %d results for %r", len(results), query)

        records: list[ReferenceImageModel] = []
        for i, result in enumerate(results, start=1):
            try:
                ext = await self._download_reference_image(result.url, refs_dir, i)
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

    async def enrich_descriptor_from_references(
        self,
        scp_id: str,
        ref_image_paths: list[str],
    ) -> str | None:
        """Analyze reference images with Vision LLM and return an enriched visual descriptor.

        Loads images as base64 data URIs and sends them to the DeepSeek multimodal
        API with a vision enrichment prompt. Returns the descriptor string on success,
        or ``None`` on failure (non-fatal — the pipeline continues).
        """
        if not ref_image_paths:
            logger.warning("enrich_descriptor_from_references: no reference images provided for %s", scp_id)
            return None

        s = self._settings
        if not s.deepseek_api_key:
            logger.warning("enrich_descriptor_from_references: DeepSeek API key not configured")
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
                    f"{s.deepseek_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
                    json={
                        "model": s.deepseek_model,
                        "messages": [{"role": "user", "content": content_parts}],
                        "max_tokens": s.deepseek_max_tokens,
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

        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            logger.warning("enrich_descriptor_from_references: Vision LLM call failed for %s: %s", scp_id, exc)
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
        ref_image_path: str,
        angles: list[str] | None = None,
    ) -> list[str]:
        """Generate character images for each angle using the configured provider.

        For each angle, compiles an angle-specific prompt, calls the provider's
        ``generate()`` (i2i with t2i fallback), and saves the result to
        ``workspace/{scp_id}/characters/{angle}_candidate_1.png``.

        Args:
            scp_id: The SCP identifier (e.g. "SCP-096").
            ref_image_path: Path to the reference image for i2i base.
            angles: List of angle names; defaults to all 4 canonical angles.

        Returns:
            List of saved image file paths.
        """
        if angles is None:
            angles = list(_CANONICAL_ANGLES)

        s = self._settings
        workspace = Path(s.workspace_path)
        safe_scp = _sanitize_scp_id(scp_id)
        chars_dir = workspace / safe_scp / "characters"
        chars_dir.mkdir(parents=True, exist_ok=True)

        provider = self._get_image_provider()
        visual_desc = self._get_visual_descriptor(scp_id)

        saved_paths: list[str] = []
        failed_angles: list[str] = []

        for angle in angles:
            angle_desc = _ANGLE_DESCRIPTIONS.get(angle, f"character {angle} view, full body")
            prompt = self._compile_generation_prompt(
                visual_descriptor=visual_desc or "",
                angle=angle,
                angle_description=angle_desc,
                scp_id=scp_id,
            )

            out_path = chars_dir / f"{angle}_candidate_1.png"
            try:
                img_bytes = await provider.generate(
                    prompt=prompt,
                    ref_image_path=ref_image_path,
                    width=s.character_image_width,
                    height=s.character_image_height,
                )
                out_path.write_bytes(img_bytes)
                saved_paths.append(str(out_path))
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
            "Full-body character illustration, clean composition, suitable for video compositing. "
            "Consistent character design, proportions, and color palette."
        )

    # ── Candidate Tracking (AC4) ──────────────────────────────────────────

    def create_candidate_batch(
        self,
        scp_id: str,
        angles: list[str] | None = None,
    ) -> list[CandidateModel]:
        """Create pending candidate records for each angle. Returns the list of candidates."""
        if angles is None:
            angles = ["front", "back", "side", "three_quarter"]

        character = self.check_existing_character(scp_id)
        candidates: list[CandidateModel] = []

        for angle in angles:
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

    # ── LLM Angle Selection (Story 1.13) ──────────────────────────────────

    async def select_character_angles(
        self,
        scp_id: str,
        scenes: list[dict],
    ) -> dict[str, dict[str, str]] | None:
        """Select the best character angle per shot using LLM analysis of scene context.

        Analyzes all shots across scenes in a single LLM call. Shots without
        ``character_path`` are skipped. Returns a dict mapping
        ``{shot_key: {"angle": name, "path": file_path}}``,
        or ``None`` if no Character record exists for the SCP ID.
        """
        character = self.check_existing_character(scp_id)
        if character is None:
            logger.info("select_character_angles: no character for %s, skipping", scp_id)
            return None

        # Collect all shots with character_path, building a shot catalogue for the LLM
        shot_catalogue: list[dict] = []
        for scene in sorted(scenes, key=lambda s: s["scene_num"]):
            for shot in scene.get("shots", []):
                if shot.get("character_path") is None:
                    continue  # AC5: skip non-character shots
                shot_catalogue.append({
                    "scene_num": scene["scene_num"],
                    "shot_id": shot["shot_id"],
                    "narration": scene.get("narration", ""),
                    "camera_angle": shot.get("camera_angle") or "",
                    "camera_movement": shot.get("camera_movement") or "",
                })

        if not shot_catalogue:
            logger.info("select_character_angles: no shots with character_path for %s", scp_id)
            return {}

        # Build available angle list
        available_angles: dict[str, str] = {}
        angle_fields = {
            "front": character.angle_front_path,
            "back": character.angle_back_path,
            "side": character.angle_side_path,
            "three_quarter": character.angle_three_quarter_path,
        }
        for angle_name, path_val in angle_fields.items():
            if path_val:
                available_angles[angle_name] = _ANGLE_DESCRIPTIONS.get(angle_name, angle_name)

        if not available_angles:
            logger.warning("select_character_angles: no angle paths set for %s", scp_id)
            return None

        # Compile prompt
        prompt_text = self._load_angle_selection_prompt(
            scp_id=scp_id,
            shot_catalogue=shot_catalogue,
            available_angles=available_angles,
        )

        # Call LLM
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
            logger.warning("select_character_angles: LLM call failed for %s: %s", scp_id, exc)
            return self._angle_fallback(shot_catalogue)

        # Parse LLM response — JSON array of {scene_num, shot_id, angle}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("select_character_angles: invalid JSON from LLM: %r", raw[:200])
            return self._angle_fallback(shot_catalogue)

        if not isinstance(parsed, list):
            logger.warning("select_character_angles: expected JSON array, got %s", type(parsed).__name__)
            return self._angle_fallback(shot_catalogue)

        # Build result map: shot_key → {angle, path}
        result: dict[str, dict[str, str]] = {}
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            shot_key = f"{entry.get('scene_num', '?')}:{entry.get('shot_id', '?')}"
            angle = (entry.get("angle") or "front").lower()
            # Validate — unrecognized angle → "front"
            if angle not in ("front", "back", "side", "three_quarter"):
                angle = "front"
            # Check angle asset actually exists
            if angle not in angle_fields or not angle_fields[angle]:
                # pick first available as fallback
                angle = next(iter(available_angles))
            result[shot_key] = {"angle": angle, "path": angle_fields[angle] or ""}

        # Fill in any missing shots from the catalogue with "front" fallback
        fallback_angle = "front" if "front" in available_angles else next(iter(available_angles))
        for shot in shot_catalogue:
            key = f"{shot['scene_num']}:{shot['shot_id']}"
            if key not in result:
                result[key] = {"angle": fallback_angle, "path": angle_fields.get(fallback_angle, "")}

        logger.info(
            "select_character_angles: %d shots, %d angles assigned for %s",
            len(shot_catalogue), len(result), scp_id,
        )
        return result

    @staticmethod
    def _angle_fallback(shot_catalogue: list[dict]) -> dict[str, dict[str, str]]:
        """Return all-front fallback when LLM fails or returns invalid data."""
        return {f"{s['scene_num']}:{s['shot_id']}": {"angle": "front", "path": ""} for s in shot_catalogue}

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
