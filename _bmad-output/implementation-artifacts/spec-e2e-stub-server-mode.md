---
title: 'E2E Stub-Server Mode'
type: 'chore'
created: '2026-07-02'
status: 'done'
route: 'one-shot'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `tests/conftest.py::stub_profile` only monkeypatches DeepSeek/Qwen/ComfyUI/ffmpeg/Langfuse-Prompt-Hub in-process, so Playwright (which drives a real browser against a real server process) can't reuse it and would otherwise hit real external APIs.

**Approach:** A standalone script (`scripts/run_e2e_stub_server.py`) reuses `tests/stubs/fakes.py` as plain attribute assignment before booting the real `yt_flow.api.main:app` via uvicorn — zero new production stub flags. Verifying it end-to-end over real HTTP surfaced a genuine pre-existing SQLite concurrency bug (two connections on one file, synchronous writes blocking the event loop) that made every real run fail within 1-2 gate approvals; fixed alongside since the script can't demonstrate anything without it.

</frozen-after-approval>

## Suggested Review Order

**E2E stub server (the actual deliverable)**

- Entry point: reuses `tests/stubs/fakes.py` via plain attribute assignment, then boots the real app unchanged.
  [`run_e2e_stub_server.py:41`](../../scripts/run_e2e_stub_server.py#L41)

- Same 6 seams as `stub_profile`, verified reachable since call sites use module-attribute access.
  [`run_e2e_stub_server.py:56`](../../scripts/run_e2e_stub_server.py#L56)

**Pre-existing SQLite locking bug (found while verifying, not caused by the script)**

- WAL + 30s busy_timeout on the SQLModel engine — this file is shared with the checkpointer.
  [`db/__init__.py:24`](../../src/yt_flow/db/__init__.py#L24)

- Same WAL + timeout on the checkpointer's aiosqlite connection (the other half of the shared file).
  [`pipeline/graph.py:66`](../../src/yt_flow/pipeline/graph.py#L66)

- Root cause: synchronous SQLite writes ran inline in async code, blocking the event loop mid-lock.
  [`services/run_service.py:234`](../../src/yt_flow/services/run_service.py#L234)

- Every `_write_run`/`_mirror_gate_state` call adjacent to an `astream()` invocation now goes through `asyncio.to_thread` — the `_consume` hot path plus `resume_run_from_failure`, `full_restart_run`, `retry_stage` (the adversarial review caught the latter three being missed on the first pass).
  [`services/run_service.py:384`](../../src/yt_flow/services/run_service.py#L384)

**Verified**

- Two full 5-gate runs (SCP-096, SCP-173, SCP-049) reached `complete` over real HTTP with the fix; `uv run pytest` (468 passed) and `npm test` (94 passed) stayed green.
