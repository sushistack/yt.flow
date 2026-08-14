"""Character image generation — provider-agnostic protocol + ComfyUI/Qwen implementations.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
"""

import json
import logging
import os
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import override

import httpx

from yt_flow.config import Settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_POSITIVE_NODE_TITLE = "ytflow:positive_prompt"  # the declared manifest keys (Story 13.3)
_NEGATIVE_NODE_TITLE = "ytflow:negative_prompt"
_NEGATIVE_TITLE_KEYWORDS = ("negative", "neg ", "bad")

# The structural-conditioning graph and the title that marks its guide input. A second
# workflow file rather than dynamic node insertion (Story 10.5): it is shorter, and with
# the feature off the existing graph does not change by one byte.
# ponytail: a constant, not a Settings field — there is exactly one such workflow and
# nothing configures it. Promote it to config the day a second guide graph exists.
_POSE_GUIDE_WORKFLOW_PATH = "data/workflows/comfyui_character_pose_guide_api.json"
_GUIDE_NODE_TITLE = "ytflow:guide_image"


def _node_title(node: dict) -> str:
    """The node's declared ``_meta.title``, or ``""`` for every shape that isn't one.

    Foreign workflows are this module's whole reason to exist, and they carry
    ``_meta: null`` and non-string titles — both of which crashed the callers
    below when they reached into ``_meta`` directly. Same posture as
    ``comfyui_client.resolve_nodes``, which guards these exact two shapes.
    """
    meta = node.get("_meta")
    title = meta.get("title") if isinstance(meta, dict) else None
    return title if isinstance(title, str) else ""


def _is_negative_node(node: dict) -> bool:
    """The declared manifest title first, the title-keyword heuristic second.

    Story 13.3 deleted the node-ID set this used to consult (``{"7", "37_neg"}``):
    a renumber that lands a *positive* encoder on ``"7"`` had it misclassified as
    negative and skipped.

    ponytail: the keyword fallback stays. This provider also runs against foreign
    workflows and :meth:`_default_workflow`, which carry no manifest, so an
    exact-match-only rule would silently stop finding the negative encoder there.
    """
    title = _node_title(node)
    return title == _NEGATIVE_NODE_TITLE or any(kw in title.lower() for kw in _NEGATIVE_TITLE_KEYWORDS)


def _is_guide_node(node: dict) -> bool:
    """True for the pose-guide ``LoadImage``, which is not the identity reference.

    The guide graph has two ``LoadImage`` nodes and the helpers below address
    ``LoadImage`` by class alone, so without this the reference would be written over
    the guide (and the t2i fallback would delete the guide out from under an
    otherwise-live ControlNet link).
    """
    return _node_title(node) == _GUIDE_NODE_TITLE


def _drop_reference_only_nodes(workflow: dict) -> None:
    """Remove disconnected i2i-only nodes after t2i fallback rewiring."""
    for node_id, node in list(workflow.items()):
        if not isinstance(node, dict):
            continue
        if node.get("class_type") in ("IPAdapter", "IPAdapterAdvanced", "LoadImage") and not _is_guide_node(node):
            workflow.pop(node_id, None)


_SUBJECT_HEIGHT_FRACTION = 0.94
# Leaves the feet a transparent gutter. video.py's CARD_EDGE_FEATHER boxblurs the alpha
# plane, and with the subject flush against the last row there is no padding for the
# feather to eat — so it eats the shoe line instead and the character reads as standing
# on a softened stub.
_BOTTOM_GUTTER = 8


def _normalize_subject_scale(png_bytes: bytes) -> bytes:
    """Rescale the cut-out subject to a fixed share of the canvas, feet at the bottom.

    The front angle is generated t2i and the other three i2i from it, so the checkpoint
    frames them differently: a card set would come back with the front figure noticeably
    smaller than its own side and back views. Prompt wording cannot fix that — framing is
    not something the text encoder controls — but on an alpha cutout it is arithmetic.

    Deliberately does NOT try to detect a two-figure card from the bounding box. That was
    tried and removed: measured on real cards a two-figure sprite was 0.359 wide-to-tall
    and a known-good single figure 0.358, because the figures overlap — so the check missed
    the case it existed for while rejecting legitimate wide poses (`sitting`, and Story 8.4
    `pose_hint` cards like "lying on operating table"), which silently fell back to the base
    standing card. Counting people is a vision-model question, not a geometry one.
    """
    import io

    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    alpha = np.array(im)[:, :, 3]
    rows = np.flatnonzero(alpha.max(axis=1) > 10)
    cols = np.flatnonzero(alpha.max(axis=0) > 10)
    if rows.size == 0 or cols.size == 0:
        raise ValueError("generated character sprite has an empty alpha mask")

    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(cols[0]), int(cols[-1]) + 1
    subject_h, subject_w = bottom - top, right - left
    width, height = im.size
    scale = (height * _SUBJECT_HEIGHT_FRACTION) / subject_h
    new_w, new_h = max(1, round(subject_w * scale)), max(1, round(subject_h * scale))
    if new_w > width:  # very wide subject: fit to width instead so nothing is clipped
        new_h = max(1, round(new_h * width / new_w))
        new_w = width
    subject = im.crop((left, top, right, bottom)).resize((new_w, new_h), Image.LANCZOS)

    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # No mask argument. Passing the source as its own mask double-applies alpha: a
    # (20,20,20,140) edge pixel lands as (11,11,11,77), so every anti-aliased edge comes
    # out at ~45% of its opacity with RGB dragged toward black. That is exactly the
    # feathered edge band _clean_alpha_noise preserves on purpose (Story 11.1 AC5), and
    # compositing the result gives every character a thin dark halo.
    out.paste(subject, ((width - new_w) // 2, height - new_h - _BOTTOM_GUTTER))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _clean_alpha_noise(png_bytes: bytes) -> bytes:
    """Remove InSPyReNet's ordered-dither cutout artifacts from a generated sprite.

    InSPyReNet's pyramid decoder leaves faint checkerboard-dither bands across flat,
    low-contrast garment regions (most visible as a horizontal noise stripe on plain
    fabric). Threshold + morphological close/open + keep-largest-component removes
    it without any model-level change (Story 8.2 follow-up, 2026-07-08).
    # ponytail: fixed kernel sizes tuned against live 832x1216 sprite renders.
    """
    import io

    import numpy as np
    from PIL import Image
    from scipy import ndimage

    im = Image.open(io.BytesIO(png_bytes))
    if im.mode != "RGBA":
        raise ValueError("generated character sprite is missing an alpha channel")
    im = im.convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    binary = alpha > 100
    if not np.any(binary):
        raise ValueError("generated character sprite has an empty alpha mask")
    binary = ndimage.binary_closing(binary, structure=np.ones((25, 25)))
    binary = ndimage.binary_opening(binary, structure=np.ones((7, 7)))
    labeled, num_components = ndimage.label(binary)
    if num_components == 0:
        return png_bytes
    sizes = ndimage.sum(binary, labeled, range(1, num_components + 1))
    # Largest component only. The old rule kept anything >= 2% of the largest, which
    # is right for dither speckle but let whole secondary figures through: the
    # checkpoint likes to compose a character reference sheet, and the flanking
    # half-drawn duplicates are 30-70% of the subject, far above 2%. A card must be
    # one subject, and the generation prompt cannot currently enforce that (the live
    # Langfuse prompt is missing the repo file's single-subject clause), so the cut
    # happens here where it is deterministic (Story 8.15).
    # ponytail: a genuinely detached element (dropped prop, floating accessory) would
    # be discarded too; the 25x25 closing above already bridges anything attached.
    # Switch back to a fraction-of-largest rule if a real card ever loses a limb.
    keep_mask = labeled == (int(np.argmax(sizes)) + 1)
    # Interior (2px erode) snaps to 255 — the dither band lives in flat regions
    # inside the component, so snapping there still removes it. The edge band
    # (keep_mask minus interior) keeps the ORIGINAL alpha so anti-aliased edges
    # survive compositing instead of a binary cutout (Story 11.1 AC5). Outside
    # the mask stays 0.
    interior = ndimage.binary_erosion(keep_mask, structure=np.ones((5, 5)))
    arr[:, :, 3] = np.where(interior, 255, np.where(keep_mask, alpha, 0)).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(out, format="PNG")
    return out.getvalue()

# ── Protocol ──────────────────────────────────────────────────────────────────


class CharacterImageProvider(ABC):
    """Provider-agnostic character image generation protocol.

    Each provider implementation handles a specific backend (ComfyUI, Qwen, etc.).
    Callers inject a provider instance and call ``generate()`` without caring
    about the underlying API.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        ref_image_path: str | None,
        *,
        width: int = 832,
        height: int = 1216,
        ipadapter_weight: float | None = None,
        negative_suffix: str | None = None,
        pose_guide_path: str | None = None,
    ) -> bytes:
        """Generate a character image. Returns raw PNG bytes.

        Args:
            prompt: The angle-specific generation prompt.
            ref_image_path: Path to the reference image for i2i base, or None for t2i.
            width: Target image width.
            height: Target image height.
            ipadapter_weight: Optional IPAdapter conditioning weight.
            negative_suffix: Optional per-call terms appended to the negative prompt.
            pose_guide_path: Optional structural guide raster (Story 10.5). When given,
                generation runs on the ControlNet workflow with this image as the control
                signal; when ``None`` the call is byte-identical to the pre-10.5 path.

        Returns:
            Raw image bytes (PNG format).
        """
        ...

    @property
    @abstractmethod
    def supports_i2i(self) -> bool:
        """Whether this provider supports image-to-image generation."""
        ...

    @property
    def produces_alpha(self) -> bool:
        """Whether provider output is expected to be an RGBA/alpha sprite."""
        return True


# ── ComfyUI Implementation ────────────────────────────────────────────────────


class ComfyUICharacterProvider(CharacterImageProvider):
    """Character generation via local ComfyUI server using i2i workflow.

    Wraps the existing ``comfyui_client`` module. Loads a ComfyUI workflow JSON
    template and injects the reference image + prompt into the appropriate nodes.
    Falls back to t2i (text-to-image) if i2i is not configured.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.comfyui_url.rstrip("/")
        self._workflow_path = settings.character_comfyui_workflow_path
        # Story 13.1: both degradations below are invisible in the returned bytes — a
        # t2i fallback is a different person, an unapplied guide is an unconditioned
        # pose, and both come back as a perfectly valid PNG. The caller (which knows
        # the card_key and the run) reads these after each generate() and files the
        # warning; a plain attribute keeps this provider free of any run/state import.
        self.last_i2i_fallback = False
        self.last_pose_guide_applied = False

    @property
    @override
    def supports_i2i(self) -> bool:
        return True

    @override
    async def generate(
        self,
        prompt: str,
        ref_image_path: str | None,
        *,
        width: int = 832,
        height: int = 1216,
        ipadapter_weight: float | None = None,
        negative_suffix: str | None = None,
        pose_guide_path: str | None = None,
    ) -> bytes:
        from yt_flow.services.comfyui_client import submit_and_fetch, upload_image

        # The guide is uploaded before the graph is chosen so a failed read/upload picks
        # the unconditioned graph instead of raising out of generate(). Raising here
        # would cost the whole card, where the identical failure on the identity
        # reference below merely falls back to t2i.
        self.last_i2i_fallback = False
        guide_name: str | None = None
        if pose_guide_path is not None:
            try:
                guide_name = await upload_image(
                    self._base_url, Path(pose_guide_path).read_bytes(), Path(pose_guide_path).name
                )
            except Exception as exc:  # noqa: BLE001 — an unreadable guide must not cost the card
                logger.warning("pose guide %r unusable: %s; rendering unconditioned", pose_guide_path, exc)

        self.last_pose_guide_applied = guide_name is not None
        workflow = self._load_workflow(pose_guide=guide_name is not None)
        workflow = self._inject_prompt(workflow, prompt)
        workflow = self._inject_dimensions(workflow, width, height)
        workflow = self._inject_seed(workflow)
        if negative_suffix:
            workflow = self._inject_negative_suffix(workflow, negative_suffix)
        if ipadapter_weight is not None:
            workflow = self._inject_ipadapter_weight(workflow, ipadapter_weight)
        if guide_name is not None:
            workflow = self._inject_guide_image(workflow, guide_name)

        if ref_image_path is None:
            workflow = self._remove_i2i_input(workflow)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI t2i generation succeeded (%dx%d)", width, height)
            return _normalize_subject_scale(_clean_alpha_noise(result))

        # Try i2i with reference image
        try:
            ref_bytes = Path(ref_image_path).read_bytes()
            uploaded_name = await upload_image(self._base_url, ref_bytes, Path(ref_image_path).name)
            workflow = self._inject_reference_image(workflow, uploaded_name)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI i2i generation succeeded (%dx%d)", width, height)
            cleaned = _clean_alpha_noise(result)
        except Exception as exc:
            logger.warning("ComfyUI i2i failed: %s; falling back to t2i", exc)
            self.last_i2i_fallback = True
            # Fallback: bypass the reference-image conditioning and use t2i
            workflow = self._remove_i2i_input(workflow)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI t2i fallback succeeded (%dx%d)", width, height)
            cleaned = _clean_alpha_noise(result)
        # Outside the except. Normalising inside the i2i `try` meant a raise from it was
        # caught by the t2i fallback, which then re-rendered the angle *without the front
        # card as reference* and returned it as valid — a different person in the same
        # set, logged as "ComfyUI i2i failed". Framing is not a reason to drop the anchor.
        return _normalize_subject_scale(cleaned)

    def _load_workflow(self, pose_guide: bool = False) -> dict:
        """Load ComfyUI workflow JSON template.

        Relative paths resolve against ``YTFLOW_PROJECT_ROOT`` (falls back to CWD),
        matching ``character_service.py``'s existing convention — the app may run
        from a CWD other than the project root.

        ``pose_guide`` selects the ControlNet-conditioned graph (Story 10.5). It is a
        separate committed file, so the default path is untouched by that feature.
        """
        project_root = Path(os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd()))
        path = project_root / (_POSE_GUIDE_WORKFLOW_PATH if pose_guide else self._workflow_path)
        if not path.exists():
            if pose_guide:
                # Not silent: falling through to the default graph would drop the
                # structural conditioning while still reporting a successful render.
                logger.warning("pose-guide workflow %s is missing; degrading to the unconditioned graph", path)
            # ponytail: fallback to default workflow path
            path = project_root / "data/workflows/comfyui_character_multi_angle_api.json"
        if path.exists():
            return json.loads(path.read_text())
        # Built-in minimal workflow
        return self._default_workflow()

    def _inject_prompt(self, workflow: dict, prompt: str) -> dict:
        """Inject the generation prompt into the positive CLIP text encoder node.

        The declared ``ytflow:positive_prompt`` title wins when the graph carries
        one — the mirror of :func:`_is_negative_node`, and for the same reason.
        The old id set excluded node ``"7"`` *even untitled*, so with it deleted a
        manifest-less foreign workflow whose untitled negative encoder comes first
        in file order would take the positive prompt straight into the negative.
        Never touches a node :func:`_is_negative_node` claims.
        """
        encoders = [
            node for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"
            and "text" in (node.get("inputs") or {})
        ]
        target = next(
            (n for n in encoders if _node_title(n) == _POSITIVE_NODE_TITLE),
            next((n for n in encoders if not _is_negative_node(n)), None),
        )
        if target is not None:
            target["inputs"]["text"] = prompt
        return workflow

    @staticmethod
    def _inject_negative_suffix(workflow: dict, suffix: str) -> dict:
        """Append per-call suppression terms to the negative CLIP text encoder node.

        ``_inject_prompt`` deliberately never writes negatives, and the authored
        workflow's negative text is shared with entity cards (SCP-049 legitimately
        needs a mask) — so caller-scoped suppression is appended here per call
        instead of edited into the workflow JSON (Story 8.15).

        Every matching node gets the suffix, matching ``_inject_dimensions``/
        ``_inject_seed`` — a workflow with two negative encoders would otherwise
        suppress on one branch only.
        """
        injected = False
        for node_id, node in workflow.items():
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            if not _is_negative_node(node):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or "text" not in inputs:
                continue
            existing = inputs["text"]
            if not isinstance(existing, str):
                # A graph link like ["12", 0] — f-stringing it would both sever the
                # edge and paste the link into the prompt text.
                logger.warning("Negative node %s text is a graph link (%r); suffix not injected", node_id, existing)
                continue
            inputs["text"] = f"{existing}, {suffix}" if existing else suffix
            injected = True
        if not injected:
            logger.warning("No negative CLIPTextEncode node matched; dropped negative suffix %r", suffix)
        return workflow

    @staticmethod
    def _inject_dimensions(workflow: dict, width: int, height: int) -> dict:
        """Inject width/height into the Empty Latent Image node."""
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                node["inputs"]["width"] = width
                node["inputs"]["height"] = height
        return workflow

    @staticmethod
    def _inject_seed(workflow: dict) -> dict:
        """Randomize KSampler.seed — the authored workflow JSON pins seed=0, which
        would make repeated angle generations more likely to converge on near-identical
        output for a given prompt/reference pair."""
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                node["inputs"]["seed"] = random.randint(0, 2**32 - 1)
        return workflow

    @staticmethod
    def _inject_ipadapter_weight(workflow: dict, weight: float) -> dict:
        """Inject per-call IPAdapter conditioning weight."""
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") in ("IPAdapter", "IPAdapterAdvanced"):
                node.setdefault("inputs", {})["weight"] = weight
        return workflow

    @staticmethod
    def _inject_reference_image(workflow: dict, image_name: str) -> dict:
        """Inject the uploaded reference image's filename into the Load Image node.

        ``image_name`` must already be an uploaded-to-ComfyUI filename (see
        ``comfyui_client.upload_image``) — ``LoadImage.inputs.image`` resolves
        against ComfyUI's input directory, it does not accept raw image bytes.

        Skips the pose-guide node: it writes *every* ``LoadImage``, so on the guide
        graph the reference would land in the ControlNet input and the character would
        be structurally conditioned on a copy of itself (Story 10.5).
        """
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage" and not _is_guide_node(node):
                node["inputs"]["image"] = image_name
        return workflow

    @staticmethod
    def _inject_guide_image(workflow: dict, image_name: str) -> dict:
        """Inject the uploaded structural guide into the ``ytflow:guide_image`` node."""
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage" and _is_guide_node(node):
                node["inputs"]["image"] = image_name
                return workflow
        logger.warning("No %r node in the workflow; pose guide %r not injected", _GUIDE_NODE_TITLE, image_name)
        return workflow

    @staticmethod
    def _remove_i2i_input(workflow: dict) -> dict:
        """Convert i2i workflow to t2i by bypassing reference-image conditioning.

        IPAdapter-conditioned workflows (Story 5.10): the reference conditions the
        model/cross-attention via an ``IPAdapter``/``IPAdapterAdvanced`` node, not
        the sampler's starting latent — reconnect ``KSampler.model`` directly to
        whatever fed the IPAdapter node, bypassing it.

        Legacy VAEEncode-based i2i workflows (pre-5.10, kept for compatibility):
        reconnect ``KSampler.latent_image`` to ``EmptyLatentImage`` instead.
        """
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") in ("IPAdapter", "IPAdapterAdvanced"):
                upstream_model = node.get("inputs", {}).get("model")
                if upstream_model is None:
                    logger.warning(
                        "t2i fallback: IPAdapter node %s has no upstream model input; cannot bypass", node_id
                    )
                    break
                reconnected = False
                for sampler in workflow.values():
                    if isinstance(sampler, dict) and sampler.get("class_type") == "KSampler":
                        if sampler.get("inputs", {}).get("model") == [node_id, 0]:
                            sampler["inputs"]["model"] = upstream_model
                            logger.info("t2i fallback: KSampler model bypassed IPAdapter node %s", node_id)
                            reconnected = True
                if not reconnected:
                    logger.warning(
                        "t2i fallback: no KSampler references IPAdapter node %s; workflow left i2i-wired", node_id
                    )
                    return workflow
                _drop_reference_only_nodes(workflow)
                return workflow

        # Legacy shape: find the EmptyLatentImage node ID
        latent_node_id = None
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                latent_node_id = node_id
                break

        if latent_node_id is None:
            return workflow  # No latent node to connect to — stay with i2i

        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                if "latent_image" in node.get("inputs", {}):
                    node["inputs"]["latent_image"] = [latent_node_id, 0]
                    logger.info("t2i fallback: KSampler latent reconnected to EmptyLatentImage")
                break
        return workflow

    @staticmethod
    def _default_workflow() -> dict:
        """Built-in minimal SDXL workflow (t2i only)."""
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 832, "height": 1216, "batch_size": 1},
            },
            # Titled, unlike the rest of this graph: node "7" used to be found as
            # the negative encoder by its *id*, and Story 13.3 deleted that route.
            # Its text ("bad quality...") is not a title, so the keyword fallback
            # would not have caught it and the negative suffix would have been
            # dropped with only a log line to show for it.
            "6": {
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "ytflow:positive_prompt"},
                "inputs": {"text": "prompt placeholder", "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "_meta": {"title": _NEGATIVE_NODE_TITLE},
                "inputs": {"text": "bad quality, blurry", "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "character", "images": ["8", 0]},
            },
        }


# ── Qwen Implementation ──────────────────────────────────────────────────────


class QwenCharacterProvider(CharacterImageProvider):
    """Character generation via Qwen image generation API (DashScope/SiliconFlow).

    Uses the Qwen image generation endpoint for text-to-image. Does NOT support
    i2i natively, so always uses t2i with the enriched descriptor in the prompt.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.character_qwen_api_key
        self._model = settings.character_qwen_model
        self._endpoint = "https://dashscope-intl.aliyuncs.com"

    @property
    @override
    def supports_i2i(self) -> bool:
        return False  # Qwen image gen is t2i only

    @property
    @override
    def produces_alpha(self) -> bool:
        return False

    @override
    async def generate(
        self,
        prompt: str,
        ref_image_path: str | None,
        *,
        width: int = 832,
        height: int = 1216,
        ipadapter_weight: float | None = None,
        negative_suffix: str | None = None,
        pose_guide_path: str | None = None,
    ) -> bytes:
        # ponytail: negative_suffix/pose_guide_path are accepted for signature parity and
        # ignored — card generation refuses this provider outright (produces_alpha is
        # False), so it can never receive either. Logged rather than dropped in silence in
        # case some other caller ever does.
        if negative_suffix:
            logger.warning("QwenCharacterProvider ignores negative_suffix %r (API takes no negative prompt)", negative_suffix)
        if pose_guide_path:
            logger.warning("QwenCharacterProvider ignores pose_guide_path %r (no structural conditioning)", pose_guide_path)
        if not self._api_key:
            raise RuntimeError("Qwen API key not configured (YTFLOW_CHARACTER_QWEN_API_KEY)")

        # Qwen accepts size like "832*1216"
        size_str = f"{width}*{height}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            # DashScope image generation endpoint
            resp = await client.post(
                f"{self._endpoint}/api/v1/services/aigc/image-generation/generation",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": self._model,
                    "input": {
                        "prompt": prompt,
                    },
                    "parameters": {
                        "size": size_str,
                        "n": 1,
                    },
                },
            )
        resp.raise_for_status()
        data = resp.json()

        # DashScope async: poll for result
        task_id = data.get("output", {}).get("task_id")
        if task_id:
            result_url = await self._poll_task(client, task_id)
            return await self._download_image(client, result_url)

        # Sync response fallback
        results = data.get("output", {}).get("results", [])
        if results and results[0].get("url"):
            return await self._download_image(client, results[0]["url"])

        raise RuntimeError(f"Qwen generation returned no results: {data!r}")

    async def _poll_task(self, client: httpx.AsyncClient, task_id: str, max_polls: int = 60) -> str:
        """Poll async DashScope task until complete."""
        import asyncio
        for _ in range(max_polls):
            resp = await client.get(
                f"{self._endpoint}/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                results = data.get("output", {}).get("results", [])
                if results and results[0].get("url"):
                    return results[0]["url"]
                raise RuntimeError("Qwen task succeeded but no image URL in response")
            if status == "FAILED":
                raise RuntimeError(f"Qwen task failed: {data}")
            await asyncio.sleep(1)
        raise RuntimeError(f"Qwen task {task_id} timed out after {max_polls}s")

    async def _download_image(self, client: httpx.AsyncClient, url: str) -> bytes:
        """Download generated image from URL with safety checks.

        Validates Content-Type and enforces a 50 MB max size limit.
        SSRF is implicitly safe here — the URL comes from DashScope, not user input.
        """
        _MAX_RESULT_SIZE = 50 * 1024 * 1024  # 50 MB
        _ALLOWED_CT = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp"})

        resp = await client.get(url)
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "").split(";")[0].strip()
        if ct not in _ALLOWED_CT:
            raise ValueError(f"Qwen returned disallowed content-type: {ct!r}")

        # Stream to avoid memory bomb
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=8192):
            total += len(chunk)
            if total > _MAX_RESULT_SIZE:
                raise ValueError(f"Qwen result too large: >{_MAX_RESULT_SIZE} bytes")
            chunks.append(chunk)

        return b"".join(chunks)


# ── Provider Factory ─────────────────────────────────────────────────────────


def create_provider(settings: Settings) -> CharacterImageProvider:
    """Return the configured character image provider."""
    provider = settings.character_image_provider
    if provider == "comfyui":
        return ComfyUICharacterProvider(settings)
    if provider == "qwen":
        return QwenCharacterProvider(settings)
    raise ValueError(f"Unknown character image provider: {provider!r}")
