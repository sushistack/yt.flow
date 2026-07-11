---
title: 'Langfuse tracing coverage audit — close failure-path gaps on LLM calls'
type: 'bugfix'
created: '2026-07-10'
status: 'done'
context: ['{project-root}/_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md']
baseline_commit: '79543855e99b8b6305a24abf3c93d147d8a073a1'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Five LLM call sites have real Langfuse coverage gaps: an A/B-eval failure closes its trace looking like a clean success, one judge call type has no span of its own, a Vision-LLM call is completely untraced, a silent angle-selection fallback leaves no signal, and a caught scenario error never marks its span as an error. Architecture rule (ARCHITECTURE-SPINE.md:98-99, 112) requires every LLM-bearing stage traced and observability failures non-fatal — these five call sites don't meet that bar today.

**Approach:** Add `@observe` to the two undecorated LLM call functions, and explicitly mark `level="ERROR"`/`"WARNING"` + `status_message` on the current span at each of the three "caught, not re-raised" failure points, using the existing `get_client()`/`observe` seam (`observability.py`) — no new tracing infrastructure.

## Boundaries & Constraints

**Always:** Every new tracing call stays wrapped in try/except that never raises (AD-10, non-fatal); reuse `get_client()`/`observe` from `observability.py`, no new dependency; business behavior/outputs (fallback values, return types) are unchanged — only trace metadata is added.

**Ask First:** If adding `@observe` to a `character_service` method breaks an existing test that patches/mocks it directly, stop and ask before restructuring the test.

**Never:** Build a central LLM client wrapper (out of scope). Touch `image.py`/`tts.py`/`subtitle.py`/`video.py` node-level `@observe` or `eval_prompts.py` — already correctly traced. Fix retry-attempt visibility in `scenario_chain._call_stage_with_retry` / `eval_service._post_chat` — deferred (LOW severity, separate concern from missing failure marking).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A/B eval raises mid-scoring | `evaluate_ab` scoring/pairwise call throws | Exception still propagates unchanged | "ab-evaluation" span marked `level="ERROR"` before it closes |
| Pairwise judge call added to tracing | `_pairwise_once` invoked | Own span/generation now exists | On raise, `@observe` auto-marks it `ERROR` |
| Vision enrichment fails | HTTP/parse error from Vision API | Unchanged fallback (`descriptor` or `None`) | Span marked `level="ERROR"` before returning fallback |
| Angle selection LLM call/parse fails | HTTP error, bad JSON, or wrong shape | Unchanged fallback angle map | Span marked `level="WARNING"` naming the failure branch |
| Scenario node raises internally | any exception inside `scenario_node`'s try block | Unchanged `PipelineState.error` string | `_record_trace` now passes `level="ERROR"`, `status_message=str(error)` |

</frozen-after-approval>

## Code Map

- `src/yt_flow/services/eval_service.py` -- `evaluate_ab` (377-435) swallows exceptions from the trace's perspective; `_pairwise_once` (227-240) has no span; `_enter_trace`/`_finish_trace`/`_exit_trace` (658-694) are the lifecycle helpers to extend
- `src/yt_flow/services/character_service.py` -- `enrich_descriptor_from_references` (560-638) has zero tracing; `_select_entity_angles` (1319-1403) has three silent-fallback branches (1367-1369, 1373-1375, 1377-1379); needs `from yt_flow.observability import get_client, observe` import added
- `src/yt_flow/pipeline/nodes/scenario.py` -- `_record_trace` (85-98) omits `level`/`status_message` on the `error` branch

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/services/eval_service.py` -- catch+mark `level="ERROR"` on the "ab-evaluation" span around `evaluate_ab`'s body, then re-raise, before `finally: _exit_trace(span)` -- `_exit_trace` today calls `span.__exit__(None, None, None)` unconditionally, hiding any failure
- [x] `src/yt_flow/services/eval_service.py` -- add `@observe(name="pairwise-once")` to `_pairwise_once` -- currently invisible inside an opaque parent span
- [x] `src/yt_flow/services/character_service.py` -- add `@observe(name="character-vision-enrich")` to `enrich_descriptor_from_references`; in its `except`, best-effort `get_client().update_current_span(level="ERROR", status_message=str(exc))` before returning the fallback -- zero trace record today
- [x] `src/yt_flow/services/character_service.py` -- add `@observe(name="select-entity-angles")` to `_select_entity_angles`; at each of its three fallback returns, best-effort mark the span `level="WARNING"` naming which check failed -- today only a `logger.warning`
- [x] `src/yt_flow/pipeline/nodes/scenario.py` -- pass `level="ERROR", status_message=str(error)` into `_record_trace`'s `update_current_span` when `error is not None` -- today an error-level-blind normal span
- [x] `tests/services/test_eval_service.py` / `tests/services/test_character_service.py` / `tests/pipeline/nodes/test_scenario.py` -- one test per fix asserting the faked Langfuse client received the expected `level`/`status_message` for its I/O Matrix row

**Acceptance Criteria:**
- Given `evaluate_ab` raises after `_enter_trace` succeeds, when the exception propagates, then `update_current_span` is called with `level="ERROR"` before `_exit_trace` runs, and the original exception still reaches the caller unchanged.
- Given `enrich_descriptor_from_references`'s HTTP call fails, when the except block runs, then the current span is marked `level="ERROR"` and the function still returns its existing fallback value (unchanged behavior).
- Given `_select_entity_angles` hits any of its three fallback branches, when the fallback map is returned, then the current span is marked `level="WARNING"` with a distinguishing `status_message`.
- Given `scenario_node` catches an exception, when `_record_trace(error=exc)` runs, then `update_current_span` receives `level="ERROR"` and `status_message=str(exc)`.

## Spec Change Log

## Verification

**Commands:**
- `uv run pytest tests/services/test_eval_service.py tests/services/test_character_service.py tests/pipeline/nodes/test_scenario.py -q` -- expected: all pass, including new assertions on span `level`/`status_message`
- `uv run pytest -q` -- expected: full suite green, no regression from added decorators

## Suggested Review Order

**A/B evaluation trace no longer lies about failure**

- Entry point: the exception mark now runs before the span closes, fixing the worst gap (a failed eval looked like a clean success).
  [`eval_service.py:435`](../../src/yt_flow/services/eval_service.py#L435)
- Best-effort helper that does the actual marking, guarded so tracing itself can never raise.
  [`eval_service.py:701`](../../src/yt_flow/services/eval_service.py#L701)
- Pairwise comparison calls get their own span instead of being invisible inside the parent chain span.
  [`eval_service.py:227`](../../src/yt_flow/services/eval_service.py#L227)

**Vision LLM enrichment goes from zero tracing to a real span**

- The call now has its own span at all; previously nothing in Langfuse referenced this Qwen-VL call.
  [`character_service.py:561`](../../src/yt_flow/services/character_service.py#L561)
- Failure marks the span ERROR before falling back to the existing/`None` descriptor — fallback behavior itself is unchanged.
  [`character_service.py:633`](../../src/yt_flow/services/character_service.py#L633)

**Angle-selection fallback stops being silent**

- Own span added so a systemic DeepSeek outage degrading every cast card is now visible, not just logged.
  [`character_service.py:1325`](../../src/yt_flow/services/character_service.py#L1325)
- One of three call sites marking the span WARNING with the specific failure reason before returning the fallback map.
  [`character_service.py:1376`](../../src/yt_flow/services/character_service.py#L1376)
- Shared helper for the three fallback branches — same reason/detail shape each time.
  [`character_service.py:1422`](../../src/yt_flow/services/character_service.py#L1422)

**Scenario error span now carries a real error level**

- A caught scenario exception now sets `level="ERROR"`/`status_message`, not just a metadata blob — also aligned to use `str()` consistently instead of mixing `repr()`/`str()`.
  [`scenario.py:96`](../../src/yt_flow/pipeline/nodes/scenario.py#L96)
