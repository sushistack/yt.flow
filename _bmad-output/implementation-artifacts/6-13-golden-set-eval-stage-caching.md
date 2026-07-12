---
created: 2026-07-12
baseline_commit: 82b169d
story_key: 6-13-golden-set-eval-stage-caching
story_id: "6.13"
epic: 6
previous_story: 6-12-ab-promotion-gate-freeze-deferred-candidate
depends_on: []
related:
  - 6-2-golden-set-offline-eval             # created scripts/eval_prompts.py this story adds caching to
  - 6-3-prompt-cache-hit-optimization       # different layer: DeepSeek's own prefix-cache (cheaper calls); this story skips calls entirely
  - 6-9-scene-repair-truncation-axis-regression
  - 6-10-statistical-promotion-gate-repair-robustness  # the repeated timeout/cost pain across 6-3/6-4's live gate re-runs this story targets
evidence: "2026-07-12: Jay flagged that editing one golden-set prompt file re-triggers a full re-run of all 3 SCPs x 8 scenario-chain stages in scripts/eval_prompts.py, which is exactly the cost/time pattern documented across 6-3 through 6-11 (repeated 600s/1200s timeouts, multi-run token spend). Industry-standard check (promptfoo docs, 2026-07-12): local disk cache keyed with a version identifier so an unchanged prompt short-circuits the LLM call; adopted here as a rendered-text hash instead (see Dev Notes)."
---

# Story 6.13: 골든셋 평가 스테이지 단위 캐싱

Status: done

## Story

As Jay,
I want `scripts/eval_prompts.py` to cache each scenario-chain stage's DeepSeek call by its exact rendered prompt text, and skip the real call when a cached result already exists,
so that editing one prompt template only re-executes the golden-set stage(s) that actually changed, instead of re-running all 3 SCPs × 8 stages from scratch every time.

## Acceptance Criteria

1. **Given** any DeepSeek call issued through `scripts/eval_prompts.py` (both the full-scenario path `_run_scenario`/`evaluate_label` and the single-stage path `_run_stage_chain`/`run_stage`), **when** a call's fully-rendered prompt text (the exact string produced by `prompt.compile(**variables)`, the same value `_call_stage` hands to `call_deepseek`) plus the configured model name has been seen before, **then** the real DeepSeek call is skipped and the previously recorded `(raw, usage, finish_reason)` is returned unchanged.
2. **Given** a prompt template edit that changes one stage's rendered text (re-seeding a new Langfuse prompt version, or a variable changing), **when** the golden set runs again, **then** only that stage's cache entry misses and re-calls DeepSeek — every other stage in the same run whose rendered text is unchanged still hits cache.
3. **Given** the cache implementation, **then** it stores entries as local JSON files under `tmp/eval-prompts/cache/` (already-git-ignored `tmp/`, no new dependency — stdlib `hashlib` + `json` + `pathlib` only), keyed by `sha256(rendered_prompt_text + model_name)`.
4. **Given** `uv run python scripts/eval_prompts.py --no-cache ...`, **when** passed, **then** every stage call bypasses the cache entirely (no read, no write) — for when a cache bug is suspected.
5. **Given** the real pipeline's execution path (`run_service`, the `/runs` API, `scenario_node` as called in production), **then** it is completely unaffected — caching is wired only inside `eval_prompts.py`'s own call sites; `scenario.py` and `scenario_chain.py` are not modified.
6. **Given** `_run_scenario`'s full-scenario path (which always calls `scenario.py`'s module-level `_call_deepseek` internally — not an injectable parameter), **when** caching is enabled, **then** `eval_prompts.py` substitutes a caching wrapper for that module-level name only for the duration of the call, and restores the original afterward even if the call raises.
7. **Given** `_run_stage_chain`'s existing `_recording_call` wrapper (already the single seam every `*_step` call goes through on the single-stage path), **when** caching is enabled, **then** the cache check/store is added directly inside `_recording_call` — no new indirection layer.
8. **Given** the test suite, **then** it proves: (a) two calls with identical rendered text + model produce exactly one underlying DeepSeek call, (b) different rendered text (e.g. a re-seeded prompt version) produces a second underlying call while an unrelated, unchanged cache key still hits, (c) `--no-cache` forces a fresh call every time even when a matching entry exists on disk.

## Tasks / Subtasks

- [x] Task 1: Add `_cache_key(rendered, model) -> str` (sha256 hex digest) + `_cache_get(key)` / `_cache_put(key, raw, usage, finish_reason)` helpers in `scripts/eval_prompts.py`, storing under `ARTIFACT_ROOT / "cache"` (AC1, AC3)
- [x] Task 2: Add a `_cached_call_deepseek(call_deepseek)` wrapper factory matching the existing `call_deepseek(rendered: str, s: Settings) -> tuple[str, dict, str | None]` signature — closes over the real callable, checks the cache before delegating, and stores `(raw, usage, finish_reason)` on miss. Model name comes from the `s: Settings` argument already passed to every call (`s.deepseek_model`) — do not construct a fresh `Settings()` inside the wrapper. Cache whatever the real call returns unconditionally, including a truncated response (`finish_reason == "length"`) — `_call_stage`'s truncation check runs on the wrapper's return value, so a cached truncation replays the same `TruncationError` deterministically without special-casing it here (AC1, AC2)
- [x] Task 3: Wire the wrapper into `_run_stage_chain`'s `_recording_call` (`scripts/eval_prompts.py:378-382`) — wrap the inner `_call_deepseek` call, keep `last_raw`/`last_finish_reason` bookkeeping unchanged (AC7)
- [x] Task 4: Wire the wrapper into `_run_scenario` (`scripts/eval_prompts.py:185-205`) by monkeypatching `yt_flow.pipeline.nodes.scenario._call_deepseek` for the duration of the `scenario_node(...)` call, restoring in a `finally` block (AC6)
- [x] Task 5: Add `--no-cache` to `main()`'s argparse block (`scripts/eval_prompts.py:689+`), threading a toggle both wiring points check before consulting the cache (AC4)
- [x] Task 6: Tests in `tests/test_eval_prompts.py` — cache hit skips the fake DeepSeek call (assert call count), changed rendered text misses while other keys still hit, `--no-cache` always misses even with a pre-populated cache file (AC8)

### Review Findings

Reviewed via `bmad-code-review` (Blind Hunter + Edge Case Hunter + Acceptance Auditor, 2026-07-12). All `patch` findings applied in bulk per Jay's direction; full regression suite green (1335 passed, 1 pre-existing skip) after fixes.

- [x] [Review][Patch] Concurrent monkeypatch of `scenario_module._call_deepseek` races under `max_concurrency` [scripts/eval_prompts.py:_run_scenario] — fixed: set/restore always relative to the fixed module-load `_call_deepseek`, never the currently-observed attribute, so an overlapping task's `finally` can no longer leave the module permanently stuck on a stale wrapper (residual: an occasional missed cache hit under interleaving, a cost-only, not correctness, degradation — documented with a `ponytail:` comment).
- [x] [Review][Patch] Cache key omitted `deepseek_max_tokens`, a request-body field that governs truncation [scripts/eval_prompts.py:_cache_key] — fixed: `_cache_key` now hashes `rendered + model + max_tokens`; a max-tokens bump meant to fix a truncated response no longer replays the stale truncated entry.
- [x] [Review][Patch] `--reps` median-of-N gate (Story 6.10) silently defeated by the cache — every rep rendered identical text/model, so reps 2..N replayed rep 1's cached generation instead of drawing an independent sample [scripts/eval_prompts.py:_eval_reps] — fixed: the reps>1 branch now always passes `no_cache=True`, regardless of `--no-cache`.
- [x] [Review][Patch] Non-atomic cache write + uncaught JSON corruption [scripts/eval_prompts.py:_cache_put/_cache_get] — fixed: writes go to a temp file then `Path.replace` (atomic on POSIX); `_cache_get` treats `JSONDecodeError`/`KeyError` as a miss instead of crashing (relevant given this script's 600-1200s per-stage timeouts and history of interrupted runs).
- [x] [Review][Patch] AC8(a)/(b) "identical/changed rendered text -> one/second call" was proven only against the isolated `_cached_call_deepseek` helper, not through the real `_run_stage_chain`/`_run_scenario` wiring points — fixed: added `test_run_stage_chain_cache_enabled_reuses_result_on_second_identical_run` and `test_run_scenario_cache_enabled_hits_cache_on_second_call` exercising the actual seams end-to-end.
- [x] [Review][Patch] Comment on `_run_stage_chain`'s `deepseek_call` line overclaimed per-stage global re-resolution [scripts/eval_prompts.py:_run_stage_chain] — fixed: reworded to state it resolves once at this call's entry (still honoring a monkeypatch set up before the call), not per stage.
- [x] [Review][Dismiss] AC7 ("no new indirection layer") reads as contradicting Task 3's own instruction to reuse the wrapper — no code change; Task 3 explicitly directs wiring the `_cached_call_deepseek` wrapper into `_recording_call`, so the spec's own wording is self-contradictory, not a code defect. Reusing the wrapper (vs. duplicating cache logic inline) is the correct DRY choice.

## Dev Notes

### Source Context

- Jay's trigger: golden-set prompt edits land across many of the 7-8 scenario-chain templates (Epic 6's own history — 6-3 reordered 6 files, 6-4/6-7 touched all 8, 6-9/6-10/6-11 touched subsets), but every `scripts/eval_prompts.py` invocation re-executes the *entire* 3-SCP × 8-stage chain regardless of which single file changed — the literal cost/timeout pain documented in `6-3-6-4-review-metrics-report.md` and the Dev Agent Records of 6-3, 6-6, 6-9, 6-10.
- Industry precedent (checked 2026-07-12): promptfoo — the reference CLI for LLM prompt regression testing — caches to local disk (`~/.promptfoo/cache` by default, `--no-cache` to bypass) and keys on a version identifier so an unchanged prompt short-circuits the call. [Source: https://www.promptfoo.dev/docs/configuration/caching/]
- This story keys on the fully **rendered** prompt text instead of a separate template-version field: `prompt.compile(**variables)`'s output already changes whenever either the template content (and therefore its Langfuse `prompt.version`) or the variables change, so hashing the rendered string alone is a strictly simpler and equally correct key — one hash instead of combining name + label + version + variables. (ponytail: the leanest correct key beats a composite one.)
- Langfuse Datasets/Experiments (`evaluate_label`'s `Dataset.run_experiment`) are a results-recording/comparison tool, not a memoization store. Epic 6's stated goal — "Langfuse native features only, no bespoke infra" — governs the *promotion gate*, not this dev-tooling cache; repurposing Langfuse as a cache would need custom score/metadata plumbing for no benefit over a local JSON file, so the cache stays local. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops`]
- This is a different layer from Story 6.3's DeepSeek prefix-cache: 6.3 makes an *actual* call cheaper (cache-hit tokens billed at 1/10 price); this story skips the call entirely when the eval harness already has the answer. Neither story's code needs to change for the other.

### Existing Code To Reuse / Modify

- `_call_stage` (`src/yt_flow/pipeline/nodes/scenario_chain.py:249-294`) fetches + compiles the prompt (`prompt.compile(**variables)` → `rendered`), then calls the injected `call_deepseek(rendered, s)` — `rendered` is exactly the string this story's cache key hashes. **Do not modify this function** — both of `eval_prompts.py`'s own execution paths already control what `call_deepseek` callable gets passed down to it.
- `_run_stage_chain` (`scripts/eval_prompts.py:368-412`) already defines `_recording_call` (lines 378-382), a wrapper around the real `_call_deepseek` passed as the `call_deepseek` argument to every `*_step` call in the single-stage path — this is the exact, already-proven seam. Add the cache check/store inside it; keep its existing `last_raw`/`last_finish_reason` side effects intact on both hit and miss.
- `_run_scenario` (`scripts/eval_prompts.py:185-205`) calls `scenario_node(state, trace_sink=stages)`. `scenario_node` (`src/yt_flow/pipeline/nodes/scenario.py:311`) has **no** `call_deepseek` parameter — every `*_step` call inside it (and inside `_write_and_review`) references the module-level `_call_deepseek` by direct name (verified: `scenario.py` lines 203-432 all pass the bare name `_call_deepseek` positionally). The only way to intercept it without touching `scenario.py`/`scenario_chain.py` (AC5) is monkeypatching the module attribute `yt_flow.pipeline.nodes.scenario._call_deepseek` for the duration of the call, restoring it in `finally`. This is the same category of technique 6-3's Dev Agent Record used for `_record_trace` before that got replaced by the cleaner `trace_sink` parameter — here there is no equivalent clean parameter to add without touching pipeline code, which AC5 explicitly keeps out of scope, so the monkeypatch is the correct choice, not a shortcut to fix later.
- `ARTIFACT_ROOT = Path(__file__).parent.parent / "tmp" / "eval-prompts"` (`scripts/eval_prompts.py:69`) already exists and is git-ignored — reuse it; the new cache directory is `ARTIFACT_ROOT / "cache"`, no new gitignore entry needed if `tmp/` is already covered (verify, don't assume).
- Test doubles: `FakePrompt.compile()` (`tests/pipeline/nodes/test_scenario_chain.py:28-30`, and two more instances around lines 442/752) return a fixed `"rendered"` string with no `.version` attribute. This is irrelevant to this story since the cache key hashes the rendered text directly rather than a Langfuse `prompt.version` field — no test-double changes needed there. `tests/test_eval_prompts.py`'s own fakes for `scenario_node`/`_call_deepseek` are the ones to extend for AC8 — read the current fakes before adding a call-count assertion so the new tests match the existing faking style in that file.

### Project Structure Notes

- All changes confined to `scripts/eval_prompts.py` + `tests/test_eval_prompts.py`. No changes to `src/yt_flow/pipeline/nodes/scenario.py` or `scenario_chain.py` (AC5) — the monkeypatch in Task 4 lives entirely in the eval script.
- New directory `tmp/eval-prompts/cache/`, created lazily by the cache-write helper the same way `write_artifact`/`_new_run_dir` already `mkdir(parents=True, exist_ok=True)` under `ARTIFACT_ROOT`.

### Out Of Scope

- Caching the real pipeline's production DeepSeek calls (`run_service`, the `/runs` API) — this is a golden-set eval dev-loop cost fix only (AC5).
- Cache eviction/TTL/size limits — entries are content-addressed by rendered text and only grow when a prompt's actual content changes; add pruning only if disk usage is ever measured as a real problem (YAGNI).
- Un-freezing Story 6-12's A/B promotion gate (`--baseline`) — this story reduces the cost of running `eval_prompts.py`, it does not decide whether/when the frozen gate runs again.
- Cross-process cache sharing / remote cache — a local per-machine file cache is sufficient for one developer's iterate-on-a-prompt loop; no CI wiring exists for this gate (out of scope per 6.2's own AC8).

### References

- [Source: scripts/eval_prompts.py#L185-L205] — `_run_scenario`, the full-scenario path lacking an injectable `call_deepseek`
- [Source: scripts/eval_prompts.py#L368-L421] — `_run_stage_chain`/`_recording_call`, the already-injectable single-stage path
- [Source: scripts/eval_prompts.py#L69] — `ARTIFACT_ROOT`, reused for the new cache directory
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L249-L294] — `_call_stage`, where `rendered` (the cache key's core input) is produced
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L311] — `scenario_node`'s signature, confirming no injectable `call_deepseek` parameter
- [https://www.promptfoo.dev/docs/configuration/caching/] — industry-standard local disk cache + version-keyed invalidation precedent (checked 2026-07-12)
- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.13: 골든셋 평가 스테이지 단위 캐싱]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Ran `PYTHONPATH=$PWD/src uv run pytest tests/test_eval_prompts.py -q` iteratively during implementation; discovered the pre-existing `test_run_stage_chain_captures_raw_and_finish_reason_on_truncation` broke once caching was wired in by default — its local `FakePrompt.compile()` returned the same literal `"rendered"` string regardless of stage/variables, so research/structure/writing all hashed to one cache key and the 2nd/3rd stage calls incorrectly served the 1st stage's cached (non-truncated) response instead of consuming the scripted truncation. Fixed by making `FakePrompt.compile()` incorporate its variables into the returned text (still a fake, but no longer collision-prone) — a required test-double fix, not a production code change.
- Full regression suite: `PYTHONPATH=$PWD/src uv run pytest -q` → 1329 passed, 1 pre-existing unrelated skip, 265.65s.
- `uv run ruff check scripts/eval_prompts.py tests/test_eval_prompts.py` → clean.
- Manually verified `tmp/` is already git-ignored (`.gitignore:41`) — no new gitignore entry needed (Dev Notes assumption confirmed, not just assumed).
- Manually verified `--no-cache` appears in `--help` output.

### Completion Notes List

- Added a content-addressed local JSON cache (`_cache_key`/`_cache_get`/`_cache_put`, stdlib `hashlib`+`json`+`pathlib` only) under `tmp/eval-prompts/cache/`, keyed by `sha256(rendered_prompt_text \0 model_name)` — a NUL separator instead of bare concatenation, so no two distinct `(rendered, model)` pairs can collide by concatenating to the same string.
- Added `_cached_call_deepseek(call_deepseek)`, a wrapper factory matching `call_deepseek`'s exact signature; reused identically at both wiring points (no duplicated cache logic). Reads `s.deepseek_model` from the per-call `Settings` argument, never constructs its own `Settings()`. Caches truncated (`finish_reason == "length"`) responses unconditionally, same as any other result.
- Wired into `_run_stage_chain`'s existing `_recording_call` seam (Task 3) and into `_run_scenario` via a `finally`-guarded monkeypatch of `yt_flow.pipeline.nodes.scenario._call_deepseek` (Task 4, since `scenario_node`'s internal `*_step` calls reference that module-level name directly with no injectable parameter). Neither `scenario.py` nor `scenario_chain.py` was touched (AC5).
- `--no-cache` (Task 5) is threaded through `evaluate_label`/`run_stage`/`_run_scenario`/`_run_stage_chain` as a plain `no_cache: bool = False` parameter — when true, the raw `_call_deepseek` is used directly (no wrapping at all), so there is no cache read *or* write, per AC4.
- Task 6 tests cover the cache helpers directly (hit/miss/roundtrip), `_cached_call_deepseek`'s three AC8 behaviors (identical text → 1 call; changed text misses while an unrelated unchanged key still hits; a truncated response caches unconditionally), the `_run_scenario` wire/restore-on-raise/no-cache-bypass behavior, an end-to-end `_run_stage_chain` proof that `--no-cache` calls fresh even when every stage renders identical text (which would otherwise force a false cache hit), and CLI-level threading of `--no-cache` into `evaluate_label`. All cache tests redirect `ep.CACHE_ROOT` into pytest's `tmp_path` via an autouse fixture so cache files never leak onto the real disk across test runs.
- Full regression suite green (1329 passed, 1 pre-existing skip); ruff clean.

### File List

- `scripts/eval_prompts.py`
- `tests/test_eval_prompts.py`

## Change Log

- 2026-07-12: Implemented golden-set stage cache (`_cache_key`/`_cache_get`/`_cache_put`/`_cached_call_deepseek`), wired into both `_run_stage_chain` and `_run_scenario`, added `--no-cache`; fixed a pre-existing test double (`FakePrompt.compile`) that would have collided with the new cache; full regression suite green. Status → review.
- 2026-07-12: Code review (adversarial + edge-case + acceptance-auditor) found and fixed 6 real issues: concurrency race on the `scenario_module._call_deepseek` monkeypatch under `max_concurrency`, cache key missing `deepseek_max_tokens` (stale truncated replays), `--reps` median-of-N gate silently defeated by caching across reps, non-atomic cache writes with no corruption handling, AC8 cache-hit/miss behavior only proven at the helper level (added real end-to-end tests), and a stale comment. 1 finding (AC7 wording) dismissed as a self-contradiction with Task 3, not a code defect. Full regression suite green (1335 passed, 1 pre-existing skip). Status → done.
