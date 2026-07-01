"""Minimal async ComfyUI HTTP adapter (Story 1.6).

Integration helper only: submits an API-format workflow to a local ComfyUI
server and returns the generated image bytes. Lives in ``services/`` because it
is an external-integration adapter, not DB/SSE orchestration. [AD-1]

HTTP-only (no WebSocket): ``POST /prompt`` -> poll ``GET /history/{id}`` ->
``GET /view``. ``httpx`` is already available transitively (langfuse/fastapi),
so no new dependency is added. [Ponytail]
"""

import asyncio

import httpx


class ComfyUIError(RuntimeError):
    """A ComfyUI submission/validation/transport failure; becomes image-stage error."""


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


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error") or data.get("node_errors") or data)
    except Exception:  # noqa: BLE001 — fall back to raw body on non-JSON errors
        return resp.text


async def _submit(client: httpx.AsyncClient, workflow: dict) -> str:
    try:
        resp = await client.post("/prompt", json={"prompt": workflow})
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
