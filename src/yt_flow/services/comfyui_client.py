"""Minimal async ComfyUI HTTP adapter (Story 1.6).

Integration helper only: submits an API-format workflow to a local ComfyUI
server and returns the generated image bytes. Lives in ``services/`` because it
is an external-integration adapter, not DB/SSE orchestration. [AD-1]

HTTP-only (no WebSocket): ``POST /prompt`` -> poll ``GET /history/{id}`` ->
``GET /view``. ``httpx`` is already available transitively (langfuse/fastapi),
so no new dependency is added. [Ponytail]
"""

import asyncio
import mimetypes

import httpx

# Story 5.14: bounded retry for connection-class failures only (DNS, refused,
# transport timeout). Any non-2xx response (validation rejection, 5xx) and
# generation-timeout are never retried here. ponytail: module constants, no
# Settings field — no anticipated second value.
CONNECT_ATTEMPTS = 3
CONNECT_RETRY_DELAY = 2.0


class ComfyUIError(RuntimeError):
    """A ComfyUI submission/validation/transport failure; becomes image-stage error."""


async def _request_with_retry(request_coro):
    """Retry a single HTTP call up to CONNECT_ATTEMPTS times on transport failure.

    Only ``httpx.TransportError`` (connection refused, DNS failure, transport
    timeout) is retried; validation (``HTTPStatusError``) and everything else
    pass straight through unretried. [AC5]
    """
    last_exc: httpx.TransportError | None = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return await request_coro()
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt + 1 < CONNECT_ATTEMPTS:
                await asyncio.sleep(CONNECT_RETRY_DELAY)
    raise ComfyUIError(
        f"ComfyUI connection failed after {CONNECT_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


async def check_health(base_url: str) -> None:
    """Verify ComfyUI is reachable before submitting shots. [AC4]

    ``GET /system_stats`` with the same bounded transport retry as prompt
    submission. Raises :class:`ComfyUIError` on final failure so callers can
    fail fast without submitting anything.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(5.0)) as client:
        try:
            resp = await _request_with_retry(lambda: client.get("/system_stats"))
            resp.raise_for_status()
        except (httpx.HTTPError, ComfyUIError) as exc:
            raise ComfyUIError(f"ComfyUI unreachable at {base_url}: {exc}") from exc


async def submit_and_fetch(
    base_url: str,
    workflow: dict,
    *,
    poll_interval: float = 1.0,
    max_polls: int = 180,
) -> bytes:
    """Run one workflow and return the first output image's bytes.

    Raises :class:`ComfyUIError` on validation (`error`/`node_errors`), HTTP
    failure, or if no image appears within ``max_polls * poll_interval`` seconds.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        prompt_id = await _submit(client, workflow)
        image_ref = await _await_image(client, prompt_id, poll_interval, max_polls)
        return await _download(client, image_ref)


async def upload_image(base_url: str, image_bytes: bytes, filename: str) -> str:
    """Upload an image to ComfyUI's input directory for use in a ``LoadImage`` node.

    ComfyUI's ``LoadImage`` node resolves ``inputs.image`` as a filename in its
    input directory (optionally ``"name [subfolder]"``), not raw image bytes —
    the image must be uploaded via ``POST /upload/image`` first. Returns the
    string to set as ``LoadImage.inputs.image``.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        return await _upload(client, image_bytes, filename)


async def submit_and_fetch_outputs(
    base_url: str,
    workflow: dict,
    output_node_ids: list[str],
    *,
    poll_interval: float = 1.0,
    max_polls: int = 180,
) -> dict[str, bytes]:
    """Run one workflow and return bytes keyed by output node ID.

    Polls until at least one of ``output_node_ids`` has output (ComfyUI writes
    all outputs atomically when the prompt completes), then downloads whatever
    is available. Missing node IDs are absent from the returned dict — callers
    decide if an absent output is an error or background-only mode.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        prompt_id = await _submit(client, workflow)
        node_refs = await _await_outputs(client, prompt_id, output_node_ids, poll_interval, max_polls)
        result = {}
        for node_id, ref in node_refs.items():
            result[node_id] = await _download(client, ref)
        return result


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error") or data.get("node_errors") or data)
    except Exception:  # noqa: BLE001 — fall back to raw body on non-JSON errors
        return resp.text


async def _upload(client: httpx.AsyncClient, image_bytes: bytes, filename: str) -> str:
    try:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        resp = await client.post(
            "/upload/image",
            files={"image": (filename, image_bytes, content_type)},
            data={"overwrite": "true"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ComfyUIError(f"ComfyUI image upload failed: {exc}") from exc

    data = resp.json()
    name = data.get("name")
    if not name:
        raise ComfyUIError(f"ComfyUI upload response missing name: {data!r}")
    subfolder = data.get("subfolder", "")
    return f"{name} [{subfolder}]" if subfolder else name


async def _submit(client: httpx.AsyncClient, workflow: dict) -> str:
    try:
        resp = await _request_with_retry(lambda: client.post("/prompt", json={"prompt": workflow}))
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # ComfyUI returns HTTP 400 with {"error", "node_errors"} on validation failure.
        raise ComfyUIError(f"ComfyUI rejected prompt: {_error_detail(exc.response)}") from exc
    except httpx.HTTPError as exc:
        raise ComfyUIError(f"ComfyUI request failed: {exc}") from exc
    data = resp.json()
    if data.get("error") or data.get("node_errors"):
        raise ComfyUIError(f"ComfyUI validation error: {data.get('error') or data.get('node_errors')}")
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(f"ComfyUI response missing prompt_id: {data!r}")
    return prompt_id


async def _await_image(client: httpx.AsyncClient, prompt_id: str, interval: float, max_polls: int) -> dict:
    """Poll history until the prompt's outputs carry an image ref, or time out.

    Transient HTTP errors during polling (e.g. a brief 5xx while ComfyUI is busy
    or restarting) are swallowed and retried within the poll budget rather than
    aborting the whole submission on the first blip. [review]
    """
    for _ in range(max_polls):
        try:
            resp = await client.get(f"/history/{prompt_id}")
            resp.raise_for_status()
            entry = resp.json().get(prompt_id)
        except httpx.HTTPError:
            entry = None  # transient; fall through to sleep + retry
        if entry:
            for out in entry.get("outputs", {}).values():
                images = out.get("images")
                if images:
                    return images[0]  # {"filename", "subfolder", "type"}
        await asyncio.sleep(interval)
    raise ComfyUIError(f"ComfyUI produced no image for prompt_id={prompt_id} within timeout")


async def _await_outputs(
    client: httpx.AsyncClient,
    prompt_id: str,
    node_ids: list[str],
    interval: float,
    max_polls: int,
) -> dict[str, dict]:
    """Poll history until any of node_ids has output; return {node_id: image_ref}.

    ComfyUI writes all outputs atomically, so once any requested node appears the
    rest are also available. Missing node IDs simply won't be in the returned dict.
    """
    for _ in range(max_polls):
        try:
            resp = await client.get(f"/history/{prompt_id}")
            resp.raise_for_status()
            entry = resp.json().get(prompt_id)
        except httpx.HTTPError:
            entry = None  # transient; retry within budget
        if entry:
            outputs = entry.get("outputs", {})
            found = {
                nid: outputs[nid]["images"][0]
                for nid in node_ids
                if nid in outputs and outputs[nid].get("images")
            }
            if found:
                return found
        await asyncio.sleep(interval)
    raise ComfyUIError(f"ComfyUI produced no image for prompt_id={prompt_id} within timeout")


async def _download(client: httpx.AsyncClient, image_ref: dict) -> bytes:
    resp = await client.get(
        "/view",
        params={
            "filename": image_ref.get("filename", ""),
            "subfolder": image_ref.get("subfolder", ""),
            "type": image_ref.get("type", "output"),
        },
    )
    resp.raise_for_status()
    if not resp.content:
        raise ComfyUIError(f"ComfyUI /view returned empty body for {image_ref!r}")
    return resp.content
