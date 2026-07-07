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


def _drop_reference_only_nodes(workflow: dict) -> None:
    """Remove disconnected i2i-only nodes after t2i fallback rewiring."""
    for node_id, node in list(workflow.items()):
        if not isinstance(node, dict):
            continue
        if node.get("class_type") in ("IPAdapter", "IPAdapterAdvanced", "LoadImage"):
            workflow.pop(node_id, None)


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

    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    binary = alpha > 100
    binary = ndimage.binary_closing(binary, structure=np.ones((25, 25)))
    binary = ndimage.binary_opening(binary, structure=np.ones((7, 7)))
    labeled, num_components = ndimage.label(binary)
    if num_components == 0:
        return png_bytes
    sizes = ndimage.sum(binary, labeled, range(1, num_components + 1))
    largest = int(np.argmax(sizes)) + 1
    keep_mask = labeled == largest
    # Snap to fully opaque/transparent — the mask already decided foreground vs
    # not, so keeping the original dithered alpha here would just re-draw the
    # noise band we closed over.
    arr[:, :, 3] = np.where(keep_mask, 255, 0).astype(np.uint8)
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
    ) -> bytes:
        """Generate a character image. Returns raw PNG bytes.

        Args:
            prompt: The angle-specific generation prompt.
            ref_image_path: Path to the reference image for i2i base, or None for t2i.
            width: Target image width.
            height: Target image height.
            ipadapter_weight: Optional IPAdapter conditioning weight.

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
    ) -> bytes:
        from yt_flow.services.comfyui_client import submit_and_fetch, upload_image

        workflow = self._load_workflow()
        workflow = self._inject_prompt(workflow, prompt)
        workflow = self._inject_dimensions(workflow, width, height)
        workflow = self._inject_seed(workflow)
        if ipadapter_weight is not None:
            workflow = self._inject_ipadapter_weight(workflow, ipadapter_weight)

        if ref_image_path is None:
            workflow = self._remove_i2i_input(workflow)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI t2i generation succeeded (%dx%d)", width, height)
            return _clean_alpha_noise(result)

        # Try i2i with reference image
        try:
            ref_bytes = Path(ref_image_path).read_bytes()
            uploaded_name = await upload_image(self._base_url, ref_bytes, Path(ref_image_path).name)
            workflow = self._inject_reference_image(workflow, uploaded_name)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI i2i generation succeeded (%dx%d)", width, height)
            return _clean_alpha_noise(result)
        except Exception as exc:
            logger.warning("ComfyUI i2i failed: %s; falling back to t2i", exc)
            # Fallback: bypass the reference-image conditioning and use t2i
            workflow = self._remove_i2i_input(workflow)
            result = await submit_and_fetch(self._base_url, workflow)
            logger.info("ComfyUI t2i fallback succeeded (%dx%d)", width, height)
            return _clean_alpha_noise(result)

    def _load_workflow(self) -> dict:
        """Load ComfyUI workflow JSON template.

        Relative paths resolve against ``YTFLOW_PROJECT_ROOT`` (falls back to CWD),
        matching ``character_service.py``'s existing convention — the app may run
        from a CWD other than the project root.
        """
        project_root = Path(os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd()))
        path = project_root / self._workflow_path
        if not path.exists():
            # ponytail: fallback to default workflow path
            path = project_root / "data/workflows/comfyui_character_multi_angle_api.json"
        if path.exists():
            return json.loads(path.read_text())
        # Built-in minimal workflow
        return self._default_workflow()

    def _inject_prompt(self, workflow: dict, prompt: str) -> dict:
        """Inject the generation prompt into the positive CLIP text encoder node.

        Only modifies the positive prompt node (typically node "6" in SDXL).
        Never touches the negative prompt node (typically node "7").
        """
        negative_node_ids = {"7", "37_neg"}  # ponytail: well-known negative prompt node IDs
        for node_id, node in workflow.items():
            if node_id in negative_node_ids:
                continue
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                meta_title = node.get("_meta", {}).get("title", "").lower()
                is_negative = any(kw in meta_title for kw in ("negative", "neg ", "bad"))
                if not is_negative:
                    if "text" in node.get("inputs", {}):
                        node["inputs"]["text"] = prompt
                        break
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
        """
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node["inputs"]["image"] = image_name
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
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "prompt placeholder", "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
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
    ) -> bytes:
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
