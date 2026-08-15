"""Minimal async ComfyUI HTTP adapter (Story 1.6).

Integration helper only: submits an API-format workflow to a local ComfyUI
server and returns the generated image bytes. Lives in ``services/`` because it
is an external-integration adapter, not DB/SSE orchestration. [AD-1]

HTTP-only (no WebSocket): ``POST /prompt`` -> poll ``GET /history/{id}`` ->
``GET /view``. ``httpx`` is already available transitively (langfuse/fastapi),
so no new dependency is added. [Ponytail]
"""

import asyncio
import logging
import math
import mimetypes
import uuid
from collections.abc import Iterable

import httpx

from yt_flow.config import Settings

logger = logging.getLogger(__name__)

# Story 5.14: bounded retry for connection-class failures only (DNS, refused,
# transport timeout). Any non-2xx response (validation rejection, 5xx) and
# generation-timeout are never retried here. ponytail: module constants, no
# Settings field — no anticipated second value.
CONNECT_ATTEMPTS = 3
CONNECT_RETRY_DELAY = 2.0

# Health probe: a *dead* server refuses the TCP connection, so crash detection
# lives entirely in the connect timeout. The read timeout is the long,
# configurable one (see Settings.comfyui_health_read_timeout_sec).
HEALTH_CONNECT_TIMEOUT = 5.0

# Provenance probe (Story 13.3): the SHORT read timeout, deliberately not
# ``comfyui_health_read_timeout_sec``. That 120s budget exists because a health
# *gate* must not read a mid-prompt stall as a crash; this call is observability
# [AD-10] and is awaited before the shot loop, so a busy GPU would otherwise
# stall even a fully-resumed run for two minutes to record a version string.
# Timing out records ``null``, which is the honest answer.
STATS_READ_TIMEOUT = 5.0

# Dropped-prompt recovery. MEASURED over many live runs (2026-08-08): ComfyUI
# intermittently *accepts* a submission — POST /prompt returns HTTP 200 with a
# prompt_id and node_errors={} — and then never queues or executes it. The
# prompt is in neither GET /queue nor GET /history, so the poller used to wait
# out the whole 900s budget and then kill the image stage, losing a multi-hour
# run. It dropped after 1, 2 and 5 successful shots on different attempts;
# hand-submitting the same workflow completes in ~20s, so the graph is valid.
#
# DROP_GRACE_SEC is both the grace before a missing prompt is judged dropped (a
# fresh submission takes a moment to appear in /queue) and the re-check cadence
# afterwards — ~180 cheap /queue calls across a full 900s budget.
# ponytail: module constants like CONNECT_ATTEMPTS above, not Settings fields —
# nothing configures these per-environment.
DROP_GRACE_SEC = 5.0
DROP_RESUBMITS = 2


class ComfyUIError(RuntimeError):
    """A ComfyUI submission/validation/transport failure; becomes image-stage error."""


# ── Workflow node manifest (no HTTP) ────────────────────────────────────────
# Injection targets are addressed by a declared ``_meta.title``, never by JSON
# node ID: the ComfyUI UI renumbers nodes on copy/paste and re-export, and an
# injection pinned to ``"6"`` then writes the prompt into whatever landed there
# — structurally valid, silently wrong. Keys are written ``ytflow:<name>``; the
# prefix is the signal to whoever opens the graph that code reads that exact
# string. (Story 13.3 AC1)
# ponytail: the prefix is a naming convention, not a validated constant — a key
# that does not match a declared title already raises here, listing the titles
# present, so a separate prefix check would reject nothing the resolver accepts.


def resolve_nodes(workflow: dict, keys: Iterable[str]) -> dict[str, str]:
    """Map each key to the node ID whose ``_meta.title`` equals it, exactly.

    Resolution is by title, full stop — nothing here enforces the ``ytflow:``
    prefix (``MANIFEST_PREFIX`` was deleted as scaffolding), and the repo's own
    ``test_resolve_nodes_matches_exactly_never_by_substring`` resolves the plain
    title ``"Negative Prompt"``. The prefix is a convention for whoever opens the
    graph, described on the banner above; it is not a contract this function
    checks.

    Exact match only, never substring: ``comfyui_sdxl_anime_lora_layered_inspyrenet_api.json``
    carries both ``"Negative Prompt"`` and ``"Background Inpaint Negative Prompt
    (entity exclusion)"``, so a substring rule resolves two nodes and picks one
    arbitrarily.

    There is deliberately **no ID fallback**. An unresolved key raises
    :class:`ValueError` naming the key *and* listing the titles actually present,
    so an operator who renamed a node in the UI can fix it without reading code;
    a duplicated title raises too, because ambiguity is a defect and not a coin
    flip. Non-dict values are skipped while scanning — an API-format workflow may
    carry top-level provenance scalars (``ytflow_verified_iclight``, ``_ytflow_note``).
    """
    by_title: dict[str, list[str]] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        meta = node.get("_meta")
        title = meta.get("title") if isinstance(meta, dict) else None
        if isinstance(title, str):
            by_title.setdefault(title, []).append(node_id)

    resolved: dict[str, str] = {}
    for key in keys:
        node_ids = by_title.get(key, [])
        if not node_ids:
            raise ValueError(
                f"workflow node title {key!r} not found; titles present: {sorted(by_title)}"
            )
        if len(node_ids) > 1:
            raise ValueError(
                f"workflow node title {key!r} is ambiguous — nodes {sorted(node_ids)} "
                f"share it; titles present: {sorted(by_title)}"
            )
        resolved[key] = node_ids[0]
    return resolved


class _PromptDropped(Exception):
    """ComfyUI acknowledged the prompt but holds it in neither queue nor history.

    Internal: never escapes :func:`_submit_and_await`, which resubmits.
    """


def _poll_budget(poll_interval: float | None, max_polls: int | None) -> tuple[float, int]:
    """Resolve (interval, polls) from Settings unless the caller overrode them.

    ponytail: Settings() per call — construction is cheap next to a ~400s
    generation, and this keeps the seam monkeypatchable in tests.
    """
    if poll_interval is not None and max_polls is not None:
        return poll_interval, max_polls
    s = Settings()  # type: ignore[call-arg]
    interval = poll_interval if poll_interval is not None else s.comfyui_poll_interval_sec
    if max_polls is not None:
        return interval, max_polls
    return interval, max(1, math.ceil(s.comfyui_generation_timeout_sec / interval))


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

    A slow answer is not a crash: ComfyUI is single-threaded on the GPU and
    stops serving ``/system_stats`` while a prompt runs (~20s/generation,
    measured run fdd69699). So the probe uses a short connect timeout — a real
    crash means connection refused / no listener, which still fails promptly —
    and a long, configurable read timeout.
    """
    timeout = httpx.Timeout(
        Settings().comfyui_health_read_timeout_sec,  # type: ignore[call-arg]
        connect=HEALTH_CONNECT_TIMEOUT,
    )
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        try:
            resp = await _request_with_retry(lambda: client.get("/system_stats"))
            resp.raise_for_status()
        except (httpx.HTTPError, ComfyUIError) as exc:
            raise ComfyUIError(f"ComfyUI unreachable at {base_url}: {exc}") from exc


async def get_system_stats(base_url: str) -> dict | None:
    """``GET /system_stats`` as raw JSON for render provenance, ``None`` on failure.

    A separate function rather than a return value bolted onto
    :func:`check_health`: that signature is ``-> None`` and ~15 test fakes plus
    ``scripts/seed_location_plates.py`` monkeypatch it with that shape.

    Best-effort by contract [AD-10] — every failure (down, slow, non-JSON) logs
    and answers ``None``, which the caller records as a null provenance block.
    Unretried, short-timeout (:data:`STATS_READ_TIMEOUT`, *not* the health gate's
    long configurable one) and called once per run: this is observability, not a
    health gate, and it must not delay a run that never renders anything.
    """
    timeout = httpx.Timeout(STATS_READ_TIMEOUT, connect=HEALTH_CONNECT_TIMEOUT)
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            resp = await client.get("/system_stats")
            resp.raise_for_status()
            stats = resp.json()
        return stats if isinstance(stats, dict) else None
    except Exception as exc:  # noqa: BLE001 — provenance must never fail the stage
        logger.warning("ComfyUI /system_stats unavailable, recording null provenance: %s", exc)
        return None


async def submit_and_fetch(
    base_url: str,
    workflow: dict,
    *,
    poll_interval: float | None = None,
    max_polls: int | None = None,
) -> bytes:
    """Run one workflow and return the first output image's bytes.

    Raises :class:`ComfyUIError` on validation (`error`/`node_errors`), HTTP
    failure, or if no image appears within the poll budget. The budget defaults
    to ``comfyui_generation_timeout_sec`` / ``comfyui_poll_interval_sec``.

    A prompt ComfyUI accepts but never queues is resubmitted up to
    :data:`DROP_RESUBMITS` times rather than waiting out the budget.
    """
    poll_interval, max_polls = _poll_budget(poll_interval, max_polls)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        image_ref = await _submit_and_await(client, workflow, _await_image, poll_interval, max_polls)
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
    poll_interval: float | None = None,
    max_polls: int | None = None,
) -> dict[str, bytes]:
    """Run one workflow and return bytes keyed by output node ID.

    Polls until at least one of ``output_node_ids`` has output (ComfyUI writes
    all outputs atomically when the prompt completes), then downloads whatever
    is available. Missing node IDs are absent from the returned dict — callers
    decide if an absent output is an error or background-only mode.
    """
    poll_interval, max_polls = _poll_budget(poll_interval, max_polls)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        node_refs = await _submit_and_await(
            client, workflow,
            lambda c, pid, i, m: _await_outputs(c, pid, output_node_ids, i, m),
            poll_interval, max_polls,
        )
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


def _bust_save_cache(workflow: dict) -> dict:
    """Return a copy whose save nodes have a unique ``filename_prefix``.

    ComfyUI has an execution cache: resubmitting a byte-identical graph serves
    every node from cache, so ``SaveImage`` never re-executes and the history
    entry carries **no outputs at all** (``status_str=success, completed=True,
    messages=[..., execution_cached, ...], outputs=[]``). The poller then waits
    for an image that can never appear. Story 11.1 makes seeds deterministic per
    (run_id, scene, shot), so any retry of a shot inside a run hits this exactly.

    Only the save node's ``filename_prefix`` widget changes, which is enough to
    miss that one node's cache key: the sampler (seed, prompts, model, steps) is
    untouched and still served from cache, so the pixels are identical and the
    seed recorded in sidecars still describes the image. Only the file's name on
    ComfyUI's disk differs — the client fetches it by the filename history
    reports, so nothing downstream cares.
    """
    token = uuid.uuid4().hex[:8]
    out = dict(workflow)
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or not isinstance(inputs.get("filename_prefix"), str):
            continue
        prefix = inputs["filename_prefix"]
        out[nid] = {**node, "inputs": {**inputs, "filename_prefix": f"{prefix}_{token}"}}
    return out


async def _submit(client: httpx.AsyncClient, workflow: dict) -> str:
    workflow = _bust_save_cache(workflow)
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


async def _poll_history(client, prompt_id: str, interval: float, max_polls: int, extract, want: str):
    """Poll ``/history/{prompt_id}`` until ``extract(outputs)`` is truthy, or time out.

    Transient HTTP errors (a brief 5xx while ComfyUI is busy, a reset, a 404) are
    retried within the poll budget rather than aborting the submission — but they
    are *counted and logged*, and the timeout error reports them. A silent
    ``except`` here made "no image within timeout" indistinguishable between
    "ComfyUI never ran it", "it ran and we couldn't see it" and "every poll
    errored", which is exactly the state that resists diagnosis.
    """
    polls = errors = 0
    last_exc: Exception | None = None
    last_outputs: dict | None = None
    next_live_check = DROP_GRACE_SEC
    for polls in range(1, max_polls + 1):
        entry = history_ok = None
        try:
            resp = await client.get(f"/history/{prompt_id}")
            resp.raise_for_status()
            entry = resp.json().get(prompt_id)
            history_ok = True
        except httpx.HTTPError as exc:
            errors += 1
            last_exc = exc
            # ponytail: first error and every 50th at WARNING, rest at DEBUG —
            # a real incident is always visible, 900 polls can't flood the log.
            logger.log(
                logging.WARNING if errors == 1 or errors % 50 == 0 else logging.DEBUG,
                "ComfyUI history poll %d for prompt_id=%s failed (%d errored so far): %s: %s",
                polls, prompt_id, errors, type(exc).__name__, exc,
            )
        if entry is not None:
            last_outputs = entry.get("outputs", {})
            found = extract(last_outputs)
            if found:
                return found
            finished = _finished_status(entry)
            if finished is not None:
                raise ComfyUIError(
                    f"ComfyUI finished prompt_id={prompt_id} without an image for {want} "
                    f"(output nodes seen: {sorted(last_outputs or {}) or 'none'}; {finished}) — "
                    f"terminal after {polls} poll(s), not waiting out the budget"
                )
        elif history_ok and polls * interval >= next_live_check:
            # Absent from history *and* the read succeeded: the one state where
            # a silent drop is possible. Anything short of a clean "ComfyUI does
            # not know this prompt" keeps us waiting. [drop recovery]
            next_live_check += DROP_GRACE_SEC
            if not await _is_live(client, prompt_id):
                raise _PromptDropped(
                    f"prompt_id={prompt_id} is in neither /queue nor /history after "
                    f"{polls} poll(s) (~{polls * interval:.0f}s)"
                )
        await asyncio.sleep(interval)

    detail = f"{polls} polls, {errors} errored"
    if last_exc is not None:
        detail += f", last error {type(last_exc).__name__}: {last_exc}"
    if last_outputs is not None:
        raise ComfyUIError(
            f"ComfyUI has prompt_id={prompt_id} in history but it carried no image "
            f"for {want} (output nodes seen: {sorted(last_outputs) or 'none'}); {detail}"
        )
    raise ComfyUIError(
        f"ComfyUI produced no image for prompt_id={prompt_id} within timeout — the "
        f"prompt never appeared in history ({detail})"
    )


async def _is_live(client: httpx.AsyncClient, prompt_id: str) -> bool:
    """Does ComfyUI still hold ``prompt_id`` in ``queue_running`` or ``queue_pending``?

    Unknown counts as live, deliberately: a slow or failing ``/queue`` (ComfyUI
    stalls HTTP while the GPU runs, see :func:`check_health`) must never be read
    as a drop. A busy server that parks our prompt in ``queue_pending`` for
    minutes is live and keeps polling — only a healthy ``/queue`` that does not
    mention the prompt at all, while history has no entry either, is a drop.
    """
    try:
        resp = await client.get("/queue")
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return True
    # Entries are [number, prompt_id, prompt, extra_data, outputs]; `in` compares
    # by == so non-matching dicts/ints are harmless, and being lenient here errs
    # toward "still live", which is the safe direction.
    return any(
        isinstance(item, list | tuple) and prompt_id in item
        for key in ("queue_running", "queue_pending")
        for item in data.get(key) or []
    )


async def _submit_and_await(client, workflow: dict, awaiter, interval: float, max_polls: int):
    """Submit, poll, and resubmit if ComfyUI silently drops the prompt.

    Each attempt goes through :func:`_submit`, so cache-busting is re-applied to
    every resubmission — a resubmit must not be served from the execution cache.
    Bounded at :data:`DROP_RESUBMITS`; the final error reports the drop count.
    """
    dropped = 0
    while True:
        prompt_id = await _submit(client, workflow)
        try:
            return await awaiter(client, prompt_id, interval, max_polls)
        except _PromptDropped as exc:
            dropped += 1
            if dropped > DROP_RESUBMITS:
                raise ComfyUIError(
                    f"ComfyUI dropped the prompt {dropped} time(s) — accepted it with "
                    f"HTTP 200 + prompt_id but never queued or executed it (last: {exc})"
                ) from exc
            logger.warning(
                "ComfyUI dropped a prompt (%s); resubmitting (%d/%d)",
                exc, dropped, DROP_RESUBMITS,
            )


def _finished_status(entry: dict) -> str | None:
    """Describe ``entry``'s status if ComfyUI is done with it, else ``None``.

    A finished prompt with no image is terminal, not slow: the missing output
    will never arrive, so polling on is pure latency. Only a status ComfyUI
    actually wrote counts — an entry without one (or mid-flight) keeps polling.
    """
    status = entry.get("status") or {}
    if not (status.get("completed") or status.get("status_str") == "error"):
        return None
    # messages are [event_name, payload] pairs; the names are the diagnosis.
    events = [m[0] if isinstance(m, list | tuple) and m else m for m in status.get("messages") or []]
    return f"status_str={status.get('status_str')!r}, events={events}"


def _first_image(outputs: dict) -> dict | None:
    for out in outputs.values():
        if out.get("images"):
            return out["images"][0]  # {"filename", "subfolder", "type"}
    return None


async def _await_image(client: httpx.AsyncClient, prompt_id: str, interval: float, max_polls: int) -> dict:
    """Poll history until the prompt's outputs carry an image ref, or time out."""
    return await _poll_history(client, prompt_id, interval, max_polls, _first_image, "any output node")


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
    def extract(outputs: dict) -> dict[str, dict]:
        return {
            nid: outputs[nid]["images"][0]
            for nid in node_ids
            if outputs.get(nid, {}).get("images")
        }

    return await _poll_history(
        client, prompt_id, interval, max_polls, extract, f"node(s) {node_ids}"
    )


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
