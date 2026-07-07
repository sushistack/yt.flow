---
story_key: 9-1-content-language-config-switch
story_id: "9.1"
epic: "Epic 9: Localization Config"
created: 2026-07-07
source_status_before: backlog
baseline_commit: cab58014a0b192f3054201bd3c633f44ac69254a
---

# Story 9.1: Content Language Config Switch

Status: done

## Story

As Jay,
I want the pipeline's Korean-only assumption expressed as a single config value that fails loudly if changed, instead of scattered hardcoded literals,
so that a future language pivot has one documented seam to start from, without the pipeline silently producing broken mixed-language output if someone flips it today.

## Context

2026-07-07 conversation: the channel is confirmed Korean-language for now, but Jay wants a config switch left in place for a possible future pivot rather than hardcoding Korean everywhere. This is explicitly **not** a multi-language localization story — actually supporting a second language would require translating/reparameterizing the scenario LLM prompts, the `tts_normalize` naturalization rules, and the subtitle typography constants, none of which is in scope (YAGNI).

An exhaustive repo scan for hardcoded Korean-specific behavior found:

1. **`src/yt_flow/config.py`** has no language/locale field at all today.
2. **`src/yt_flow/pipeline/nodes/subtitle.py:64`** — `whisperx.load_align_model(language_code="ko", device=self._device)` — a literal `"ko"` passed to WhisperX, independent of any config value.
3. **`src/yt_flow/pipeline/nodes/subtitle.py:110,121-124`** — `SUBTITLE_FONT_FAMILY = "Pretendard SemiBold"` and the `_LINE_CHAR_GUIDANCE`/`_CUE_CHAR_SOFT_CAP` line-wrap thresholds are tuned for Hangul syllable-block density (comment: "Korean subtitle norms").
4. **`src/yt_flow/pipeline/nodes/video.py:81`** — `CARD_FONT_PATH = Path("data/fonts/Pretendard-Bold.otf")`, same font family, used for chapter-card burn-in text.
5. **`prompts/scenario/{research,structure,visual_breakdown,tts_normalize}.md`** (committed in this repo) — explicit Korean instructions/examples baked into the LLM prompt text itself (e.g. `tts_normalize.md`'s entire stage is "Korean TTS Naturalization").
6. **`scenario/writing`, `scenario/review`, `scenario/critic_agent`, `scenario/format_guide`** — four more scenario-chain prompts referenced by `scripts/migrate_prompts.py`'s `SOURCE_TO_NAME` that are **not committed in this repo at all**; their only known source is Langfuse's live `production` label and the sibling repo `/mnt/work/projects/yt.pipe/templates/scenario/`, which contains the literal directive `"- Write in Korean (한국어)"` in `03_writing.md`.
7. **TTS voice** (`Settings.qwen_tts_voice = "Cherry"`) is already a config field — no change needed, but it is coupled to language: swapping `content_language` without also picking a matching voice would silently mis-synthesize. Out of scope; flagged in Dev Notes.
8. **Image search / `character_service.py` queries** are already language-neutral (English/ASCII), no change needed.

Items 5 and 6 (the LLM prompt templates) cannot be fixed by touching `yt_flow/` code — they require prompt reparameterization and re-seeding through the PROMPT_POLICY.md flow, which is a project on its own. This story's job is narrower: add the config seam, and make it impossible for the pipeline to run to completion with a language value it doesn't actually support, rather than trying to make every hardcoded spot configurable today.

## Acceptance Criteria

1. **New config field.** `Settings.content_language: str = "ko"` exists in `src/yt_flow/config.py` (env `YTFLOW_CONTENT_LANGUAGE`), with a comment inventorying the touchpoints listed in Context items 2-6 as the checklist for whoever eventually builds real multi-language support.
2. **Fail-fast guard.** Given `scenario_node` runs with `Settings.content_language != "ko"`, then it raises before calling DeepSeek and the failure surfaces through the existing `PipelineState.error` contract (same pattern as the existing missing-API-key check) — the pipeline never silently produces content in the wrong language.
3. **The one already-trivial swap gets wired.** `subtitle.py`'s `WhisperXAligner` no longer hardcodes `language_code="ko"` — it receives the language from `Settings.content_language` via `_get_aligner(s)`, threaded through the constructor. (This is a no-op today since the guard in AC2 means `content_language` is always `"ko"` by the time this runs; it removes a second, independent hardcoded literal that could otherwise drift from config.)
4. **No other behavior changes.** Subtitle typography constants (`SUBTITLE_FONT_FAMILY`, `_LINE_CHAR_GUIDANCE`, `_CUE_CHAR_SOFT_CAP`), `video.py`'s `CARD_FONT_PATH`, TTS voice selection, and all Langfuse/repo prompt templates are untouched. Full regression suite stays green.
5. **Tests.** Config default/env-override test; a `scenario_node` test proving a non-`"ko"` value produces `PipelineState.error` without calling DeepSeek; a `WhisperXAligner`/`_get_aligner` test proving the language value is threaded through instead of hardcoded.

## Tasks / Subtasks

- [x] **Task 1 — Config field (AC: 1)**
  - [x] Add `content_language: str = "ko"` to `Settings` in `src/yt_flow/config.py`, near the other simple string fields. Comment: document that this is the single seam for a future language pivot, and list the touchpoints from Context items 2-6 (aligner language, subtitle/card font+line-wrap constants, scenario prompt templates — including the 4 not committed in this repo) that would need work before changing this value does anything real.
- [x] **Task 2 — Fail-fast guard in `scenario_node` (AC: 2)**
  - [x] In `src/yt_flow/pipeline/nodes/scenario.py:scenario_node`, right after `s = _settings()` and alongside the existing `if not s.deepseek_api_key: raise RuntimeError(...)` check (line ~149), add: `if s.content_language != "ko": raise NotImplementedError(f"content_language={s.content_language!r} not supported yet; scenario prompts, TTS naturalization, and subtitle typography are Korean-only (YTFLOW_CONTENT_LANGUAGE)")`. It falls through to the existing `except Exception as exc` handler — no new error-handling path needed.
- [x] **Task 3 — Thread language into the WhisperX aligner (AC: 3)**
  - [x] `src/yt_flow/pipeline/nodes/subtitle.py`: add a `language` parameter to `WhisperXAligner.__init__` (store as `self._language`), use `self._language` instead of the literal `"ko"` at line 64's `whisperx.load_align_model(language_code=self._language, device=self._device)`.
  - [x] `_get_aligner(s)` (line 84): pass `s.content_language` as the new constructor argument.
- [x] **Task 4 — Tests (AC: 5)**
  - [x] `tests/test_config.py`: add a default-value test (`content_language` defaults to `"ko"`) and an env-override test, following the existing `test_sound_design_enabled_defaults_true`/`test_langfuse_enabled_env_override` pattern.
  - [x] `tests/pipeline/nodes/test_scenario.py`: add `content_language = "ko"` to `FakeSettings`. Add a test mirroring `test_missing_api_key_sets_error` — a `FakeSettings` subclass with `content_language = "en"`, assert `scenario_node` returns a `PipelineState.error` mentioning `content_language`, and that no chain step (`_stub_chain`'s stubs) was called.
  - [x] `tests/pipeline/nodes/test_subtitle.py`: `test_get_aligner_whisperx_returns_instance` (line 318-323) builds its fake settings via a bare `SimpleNamespace(aligner=..., aligner_model=..., aligner_device=..., aligner_compute_type=...)` with no `content_language` attribute — add `content_language="ko"` to that `SimpleNamespace`, or `_get_aligner(s)` will raise `AttributeError` the moment it reads `s.content_language`. Extend that test (or add a new one) asserting the constructed `WhisperXAligner`'s `_language` attribute equals the passed value. No need to exercise the real `whisperx.load_align_model` call — it's lazily imported and not installed in the test env, same as existing coverage.
  - [x] Run `uv run pytest tests/test_config.py tests/pipeline/nodes/test_scenario.py tests/pipeline/nodes/test_subtitle.py -q`, then full `uv run pytest -q`.

### Review Findings

- [x] [Review][Patch] `subtitle_node` had no `content_language` guard of its own; `run_service.retry_stage(run_id, "subtitle", ...)` re-invokes it without re-running `scenario_node`, so a `content_language` changed between the original run and a later subtitle-stage retry would silently reach `whisperx.load_align_model` unchecked — directly contradicting the story's "never silently produce content in the wrong language" intent [subtitle.py:325]. **Fixed:** added the same fail-fast guard to `subtitle_node`, right after `_settings()`, alongside the existing aligner-config fail-fast check.
- [x] [Review][Patch] `config.py`'s `content_language` comment inventoried Context items 2–6 but omitted the `qwen_tts_voice` coupling note the story's own scope-boundaries section explicitly asked for ("Note the coupling in the config.py comment") [config.py:106]. **Fixed:** added a one-line note.
- [x] [Review][Patch] `test_non_ko_content_language_sets_error_without_calling_chain` only asserted `calls["writing"] == 0`, not that the earlier `research`/`structure` DeepSeek-calling steps were also skipped, so the test's "without calling DeepSeek" claim was proven weaker than stated [test_scenario.py]. **Fixed:** `_stub_chain` now counts `research`/`structure` calls too; the test asserts both are `0`.
- [x] [Review][Defer] No normalization on `content_language` comparison (`"KO"`, `" ko"`, `"ko-KR"` all fail the guard) [scenario.py:151] — deferred, explicitly out of scope per this story's own boundary ("no supported-languages list/enum/validator beyond the single `!= 'ko'` check"); revisit only if real multi-language support is built.
- [x] [Review][Dismiss] Exception-type inconsistency (`RuntimeError` vs `NotImplementedError`) risking an uncaught crash — false positive, both fall through the same `except Exception as exc` handler in `scenario_node`.
- [x] [Review][Dismiss] New required `WhisperXAligner.__init__` parameter could break other call sites — verified false; grepped every call site in the repo, none construct it directly outside `_get_aligner`.
- [x] [Review][Dismiss] `NotImplementedError` message wording ("not supported yet") — matches the exact message the story's own Task 2 specifies; not a code defect.
- [x] [Review][Dismiss] `content_language` guard ordered after the `deepseek_api_key` check, masking simultaneous misconfiguration — matches the story's own Task 2 instruction to add the guard "alongside the existing check," same position.

## Dev Notes

### Architecture Guardrails

- Config convention: "Pydantic `BaseSettings` in `config.py`; env prefix `YTFLOW_`; model identifiers pinned in config, never hardcoded" ([Source: ARCHITECTURE-SPINE.md#Consistency Conventions]) — this story is a direct application of that existing invariant to a value that was implicit until now. No new architectural decision (AD) needed.
- Fail fast at point of use, not app startup — same pattern as AD-10's ComfyUI reachability check and the existing `deepseek_api_key` check in `scenario_node`. Do not add a startup-time validator.
- `pipeline/` nodes read `Settings` directly (no `db/`/`api/` imports) — the guard and the aligner change both stay inside `pipeline/nodes/`. [AD-1]

### Scope boundaries (do NOT do)

- Do not translate, parameterize, or restructure any prompt in `prompts/scenario/*.md` or on Langfuse. That is a PROMPT_POLICY.md-governed change requiring candidate→A/B→production promotion, and is a separate, much larger effort.
- Do not attempt to fetch or reconcile the 4 scenario prompts (`writing`, `review`, `critic_agent`, `format_guide`) that exist only in Langfuse's live `production` label / the sibling `yt.pipe` repo. Their absence from this repo is a pre-existing PROMPT_POLICY gap, noted here for visibility only — flag it, don't fix it in this story.
- Do not change `SUBTITLE_FONT_FAMILY`, `_LINE_CHAR_GUIDANCE`, `_CUE_CHAR_SOFT_CAP` (subtitle.py) or `CARD_FONT_PATH` (video.py). Making the font/typography genuinely language-driven needs a per-language threshold table and a second bundled font family — real work, not a config read.
- Do not change `qwen_tts_voice` or add a language→voice mapping. Note the coupling in the config.py comment; that's enough for now.
- Do not add a "supported languages" list, enum, or validator beyond the single `!= "ko"` check. One guard clause is the whole feature.

### Existing Code To Read Before Implementing

- `src/yt_flow/pipeline/nodes/scenario.py:143-188` (`scenario_node`) — current state: instantiates `Settings`, checks `deepseek_api_key`, runs the chain, catches `Exception` and converts to `PipelineState.error`. Change needed: one more guard clause right after the API-key check, same style.
- `src/yt_flow/pipeline/nodes/subtitle.py:38-87` (`WhisperXAligner`, `_get_aligner`) — current state: constructor takes `(model, device, compute_type)`; `_align_sync` hardcodes `language_code="ko"`. Change needed: add `language` to the constructor and use it at the `load_align_model` call; `_get_aligner` passes `s.content_language`.
- `tests/pipeline/nodes/test_scenario.py:14-18` (`FakeSettings`) — a plain mock class, not a `Settings` subclass, so it has no `content_language` attribute today; must add it or `scenario_node`'s new guard will raise `AttributeError` in every existing test.
- `tests/pipeline/nodes/test_subtitle.py:318-323` (`test_get_aligner_whisperx_returns_instance`) — builds its fake settings via a bare `SimpleNamespace(...)` with no `content_language` attribute; same `AttributeError` risk once `_get_aligner` reads `s.content_language`.

### References

- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency Conventions] — config convention this story applies.
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 9] — epic framing, drafted alongside this story.
- [Source: _bmad-output/implementation-artifacts/5-4-tts-korean-naturalization.md] — the `tts_normalize` Korean-naturalization stage; confirms the prompt-level Korean dependency is deep and intentional, not accidental.
- [Source: _bmad-output/implementation-artifacts/5-18-subtitle-display-text-dual-track.md] — the in-progress sibling story that owns `SUBTITLE_FONT_FAMILY`/line-wrap constants; explicitly scopes out any "static vs kinetic"-style toggle for its own concern, consistent with this story also not adding typography toggles.
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L143-L188; src/yt_flow/pipeline/nodes/subtitle.py#L38-L87] — exact seams.

## Project Structure Notes

Expected file changes:

- `src/yt_flow/config.py` (update: new field)
- `src/yt_flow/pipeline/nodes/scenario.py` (update: guard clause)
- `src/yt_flow/pipeline/nodes/subtitle.py` (update: `WhisperXAligner`/`_get_aligner`)
- `tests/test_config.py` (update)
- `tests/pipeline/nodes/test_scenario.py` (update)
- `tests/pipeline/nodes/test_subtitle.py` (update)

Files that should not need changes:

- `src/yt_flow/pipeline/nodes/video.py`
- `src/yt_flow/pipeline/nodes/tts.py`
- Any file under `prompts/`
- Frontend files

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Full suite (`uv run pytest -q`): 733 passed, 1 skipped, 3 failed. The 3 failures (`test_duplicate_llm_scene_num_does_not_corrupt_shots`, `test_scene_count_exceeding_structure_logs_warning_instead_of_crashing`, `test_visual_breakdown_receives_entity_sheet_logline_and_scene_role`) pre-exist and are unrelated to this story: a concurrently in-progress session (Epic 8, story `8-1-shot-cast-metadata-bg-prompts`, `sprint-status.yaml` shows it `in-progress`) added an `scp_id` parameter to `visual_breakdown_step` and updated its caller in `scenario.py`/`scenario_chain.py`, but `test_scenario.py`'s `fake_visual` test doubles weren't updated to match — shifting positional args by one. Verified these files were untouched by this story's diff; confirmed unrelated to `content_language`. Not fixed here (out of scope; touching another session's in-flight WIP files risks a collision).
- `uv run ruff check` on all changed files: clean.

### Completion Notes List

- Story context generated by BMad create-story workflow on 2026-07-07.
- Added `Settings.content_language: str = "ko"` (env `YTFLOW_CONTENT_LANGUAGE`) with a comment inventorying the touchpoints that would need work before a real language pivot.
- Added a fail-fast guard in `scenario_node` right after the existing `deepseek_api_key` check: raises `NotImplementedError` when `content_language != "ko"`, caught by the existing `except Exception` handler and surfaced via `PipelineState.error`.
- Threaded `content_language` through `WhisperXAligner.__init__`/`_get_aligner` in `subtitle.py`, replacing the hardcoded `"ko"` literal at the `whisperx.load_align_model` call.
- No other files touched — typography constants, `CARD_FONT_PATH`, TTS voice, and all prompt templates are unchanged per the story's explicit scope boundaries.
- Tests added: `test_content_language_defaults_ko`, `test_content_language_env_override` (test_config.py); `test_non_ko_content_language_sets_error_without_calling_chain` (test_scenario.py, plus `content_language = "ko"` added to `FakeSettings`); `_language` assertion added to `test_get_aligner_whisperx_returns_instance` (test_subtitle.py, plus `content_language="ko"` added to its `SimpleNamespace`).

### File List

- `src/yt_flow/config.py` (modified)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified)
- `src/yt_flow/pipeline/nodes/subtitle.py` (modified)
- `tests/test_config.py` (modified)
- `tests/pipeline/nodes/test_scenario.py` (modified)
- `tests/pipeline/nodes/test_subtitle.py` (modified)

## Change Log

- 2026-07-07: Story created from Jay's direction to leave a content-language config switch in place while the channel stays Korean-only for now. Scope deliberately limited to the config seam + fail-fast guard + the one already-trivial hardcoded-`"ko"` swap (WhisperX aligner); prompt-level and typography-level Korean dependencies documented but explicitly out of scope.
- 2026-07-07: Implemented all 4 tasks — `content_language` config field, `scenario_node` fail-fast guard, `WhisperXAligner` language threading, and tests. Full suite: 733 passed, 1 skipped, 3 pre-existing failures unrelated to this story (concurrent Epic 8 WIP, see Debug Log). Status → review.
- 2026-07-07: Code review — 3 patches applied: added the missing `content_language` guard to `subtitle_node` (closing a real bypass via `retry_stage`'s independent stage retry), added the `qwen_tts_voice` coupling note to config.py's comment, and strengthened the scenario fail-fast test to also assert `research`/`structure` were skipped. 1 finding deferred (language-value normalization, explicitly out of scope per this story's own boundaries), 4 dismissed as false positives or already spec-compliant. Full suite: 754 passed, 1 skipped, 0 failed. Status → done.
