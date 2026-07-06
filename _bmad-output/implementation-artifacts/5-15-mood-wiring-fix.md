---
baseline_commit: eb9e2964860cd183050607a00ffb9b260bee70af
---

# Story 5.15: mood 배선 수정 — read scene mood from structure output, normalize at chain time, expose in artifacts API

Status: review

Story key: `5-15` · Epic: 5

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a SCP YouTube content producer,
I want each scene's `mood` to come from the structure stage (the only stage whose prompt enforces the mood enum), normalized and logged at chain time, and visible in the scenario artifacts API,
so that Epic 7's mood-driven sound design (7-1), color grade (7-2), and transition variety (7-4) actually vary per scene instead of silently collapsing to all-`dread`, and so a human can inspect per-scene mood at the scenario gate.

### Context: found during E2E baseline 2026-07-06 (run 272b05a4)

Defects D1 (major) and D2 (minor) of the E2E baseline (`e2e-baseline-2026-07-06.md`). The structure prompt constrains `mood` to the enum {dread, clinical, escalation, revelation}, but `build_scenes` reads mood from the **writing** stage's output ([scenario_chain.py:372](src/yt_flow/pipeline/nodes/scenario_chain.py#L372)) — and the writing prompt has no enum constraint, so the writing LLM reinvents free-form moods. In the baseline run, 8/8 scenes had invalid moods ("shock", "mystery", "intrigue", "horror", "awe mixed with dread", "tension", "unresolved mystery"; only scene 8's "dread" was coincidentally valid). `resolve_mood()`'s silent fallback collapsed every scene to `dread` → J6 mood diversity unobservable, J7 (post-fx variety) unverifiable at all. Secondarily (D2), the scenario artifacts API omits `mood` from the scene payload, so the gate reviewer can't see it.

## Acceptance Criteria

1. **Mood sourced from structure.** Given a scenario chain run where `structure_step` returned scenes with `mood` values, When `build_scenes` assembles `SceneState`s, Then each scene's `mood` is read from the **structure** scene at the same positional index (the same positional rule `_write_and_review` already uses for `scene_role`), and the writing output's `mood` key is ignored entirely.
2. **Valid mood passes through verbatim, silently.** Given a structure scene whose `mood` is one of `sound_design.MOOD_VALUES`, When `build_scenes` runs, Then `SceneState.mood` equals that value exactly and no warning is logged.
3. **Invalid/missing mood normalizes with a WARNING — never silently.** Given a structure scene whose `mood` is missing, empty, non-string, or not in `MOOD_VALUES` — or given writing produced more scenes than structure so no structure entry exists at that index — When `build_scenes` runs, Then `SceneState.mood` is `DEFAULT_MOOD` (`"dread"`) via `resolve_mood` (or equivalent), a `WARNING` log names the scene number and the raw offending value, and the run does **not** fail (graceful normalization, no new failure mode).
4. **Post-chain invariant.** Given any scenario stage completed after this story, Then every `SceneState.mood` in `PipelineState.scenes` is a member of `MOOD_VALUES` — downstream defensive `resolve_mood` calls in `video.py`/`color_grade.py` remain in place but become no-ops for new runs.
5. **Artifacts API exposes mood.** Given `GET /runs/{run_id}/stages/scenario/artifacts`, When the scenario stage has been reached, Then each entry in `scenes` includes a `"mood"` key with the stored value; for pre-7.1 checkpoints whose scenes have no `mood` key, the endpoint returns `null` for it instead of raising (use `.get`, not bracket access).
6. **No regressions.** All existing scenario/chain/API tests pass after signature/test updates; the existing tests' `monkeypatch("yt_flow.services.prompt_service.get_prompt", ...)` pattern still works unchanged; the Story 6.1 variant→label wiring in `_call_stage` is untouched; **no prompt content change is required** for AC 1–5 (pure code-side wiring).
7. **(Optional — may be skipped without failing the story.)** If the writing prompt is tightened (e.g. dropping its now-dead `mood` output field or adding the enum), the change follows `docs/PROMPT_POLICY.md` in full: repo file first, seed under `candidate`, A/B + golden-set gate, promote by label move. Not doing this task at all is an acceptable outcome.

## Tasks / Subtasks

- [x] **Task 1 — Rewire `build_scenes` to structure-sourced, normalized mood** (AC: 1, 2, 3, 4)
  - [x] Add a `structure: list[dict]` parameter to `build_scenes(writing, visual_by_scene)` ([scenario_chain.py:320](src/yt_flow/pipeline/nodes/scenario_chain.py#L320)). Single production caller: [scenario.py:183](src/yt_flow/pipeline/nodes/scenario.py#L183) — `structure` is already in scope there (computed at line 162), so this is one-line plumbing.
  - [x] Replace the mood expression at [scenario_chain.py:372](src/yt_flow/pipeline/nodes/scenario_chain.py#L372) (`mood=str(writing_scene.get("mood") or DEFAULT_MOOD)`): read `raw = structure[idx].get("mood")` when `idx < len(structure)` and the entry is a dict (guard like `_scene_role_text` does at lines 154–160, structure entries are raw LLM JSON), else `None`; if `raw not in MOOD_VALUES`, `logger.warning("scenario: scene %d mood %r not in %s; falling back to %r", ...)`; store `resolve_mood(raw)`.
  - [x] Update the `sound_design` import at [scenario_chain.py:17](src/yt_flow/pipeline/nodes/scenario_chain.py#L17) to bring in `MOOD_VALUES`/`resolve_mood` (keep or drop `DEFAULT_MOOD` as the code needs — it's only used for this expression and `_fallback_prompt` doesn't use it).
- [x] **Task 2 — Expose mood in the scenario artifacts payload** (AC: 5)
  - [x] In `get_stage_artifacts`'s scenario branch ([run_service.py:83-100](src/yt_flow/services/run_service.py#L83-L100)), add `"mood": s.get("mood")` to the per-scene dict. `.get` is mandatory — scenes checkpointed before Story 7.1 have no `mood` key and bracket access would 500 the gate view for old runs.
- [x] **Task 3 — Tests** (AC: 1–6)
  - [x] Rewrite the mood block in [tests/pipeline/nodes/test_scenario_chain.py:534-563](tests/pipeline/nodes/test_scenario_chain.py#L534): delete/replace `test_build_scenes_populates_mood_from_writing_scene` (536) and `test_build_scenes_stores_unrecognized_mood_verbatim_resolved_later` (549) — both assert the buggy behavior this story removes. New cases: valid structure mood → verbatim + no warning; writing mood present but structure mood differs → structure wins; invalid structure mood ("shock") → `DEFAULT_MOOD` + `caplog` WARNING containing scene num and raw value; missing mood key / non-dict structure entry → `DEFAULT_MOOD` + WARNING; `len(writing scenes) > len(structure)` → trailing scene gets `DEFAULT_MOOD` + WARNING.
  - [x] Update every existing `chain.build_scenes(writing, visual_by_scene)` call for the new signature (test file lines 485, 502, 518, 525, plus the mood block) — pass a minimal aligned `structure` (e.g. `[{"mood": "dread"}]` or `[{}]` per scene).
  - [x] [tests/api/test_stage_artifacts.py](tests/api/test_stage_artifacts.py): add `"mood": "escalation"` to the `_scene` helper (line 20) and assert `body["scenes"][0]["mood"] == "escalation"` in `test_scenario_artifacts` (line 90); add one case for a scene dict *without* a `mood` key asserting `mood is None` (pre-7.1 checkpoint shape, AC:5).
  - [x] Cassettes: `tests/fixtures/cassettes/deepseek_structure.json` currently has **zero** `mood` keys (verified via grep) — add valid enum moods to its scene objects so the stage-aware end-to-end fakes (`deepseek_stage_aware` in [tests/stubs/fakes.py:184](tests/stubs/fakes.py#L184)) exercise the happy path; keep at least one scene mood-less if you want the node-level test to also cover the WARNING path, or rely on the unit tests above for that.
  - [x] Run: `PYTHONPATH=$PWD/src pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/api/test_stage_artifacts.py -q`, then the full suite.
- [ ] **Task 4 (OPTIONAL, PROMPT_POLICY-gated) — tighten the writing prompt** (AC: 7 — skipped, see Completion Notes)
  - [ ] Only if pursued: the writing prompt has **no repo file** (`prompts/scenario/` contains only research/structure/tts_normalize/visual_breakdown; `scenario/writing` was seeded from `/mnt/work/projects/yt.pipe/templates/scenario/03_writing.md`, whose output example literally shows `"mood": "tense"` — an out-of-enum value). Per PROMPT_POLICY rule 1 the repo is SoT, so first materialize `prompts/scenario/writing.md`, then remove the dead `mood` field from its output schema (or add the enum), seed under `candidate`, run A/B + `scripts/eval_prompts.py --label candidate --baseline production`, promote by label move. **Recommended default: skip** — after Task 1 the writing `mood` output is ignored, so this is cleanup, not correctness.

## Dev Notes

### Root cause & data flow (current vs. changed)

- **Enum contract lives only in structure.** [prompts/scenario/structure.md:48](prompts/scenario/structure.md#L48) puts `"mood": "dread/clinical/escalation/revelation"` in the output schema, and lines 52–55 define the 4-value axis ("`mood` drives the scene's background-music/ambient/stinger audio bed — a separate 4-value axis from `emotional_beat`"). No other prompt constrains mood.
- **Current wiring reads the wrong stage.** `writing_step` receives structure as `scene_structure` JSON ([scenario_chain.py:134](src/yt_flow/pipeline/nodes/scenario_chain.py#L134)) but its prompt never asks for enum moods; `build_scenes` then takes `writing_scene.get("mood")` at [scenario_chain.py:372](src/yt_flow/pipeline/nodes/scenario_chain.py#L372). `str(... or DEFAULT_MOOD)` only catches *falsy* values — a truthy garbage string like `"shock"` is stored verbatim into `SceneState.mood` ([state.py:46](src/yt_flow/domain/state.py#L46)) and later silently collapsed by `resolve_mood` ([sound_design.py:36-38](src/yt_flow/pipeline/nodes/sound_design.py#L36-L38): `return mood if mood in MOOD_VALUES else DEFAULT_MOOD` — no logging) at every point of use.
- **Changed behavior:** mood comes from `structure[idx]` (positional — the same 1:1 rule `_write_and_review` uses to pick `scene_role`, [scenario.py:111-125](src/yt_flow/pipeline/nodes/scenario.py#L111-L125), including its existing WARNING when writing over-produces scenes at lines 117–120; mirror that precedent). Normalize with `resolve_mood` at chain time and WARN on anything not already valid, so bad LLM output is *visible in logs* but never fatal. After this, `SceneState.mood` is guaranteed `∈ MOOD_VALUES` for new runs.
- **Do NOT hard-validate in `structure_step`** ([scenario_chain.py:97-116](src/yt_flow/pipeline/nodes/scenario_chain.py#L97-L116)). Raising there would turn a cosmetic LLM slip into a whole-stage failure — the opposite of the crash-free posture this codebase takes for LLM-quality issues (cf. `tts_normalize_step`'s per-scene fallback + warning, lines 296–307). Normalization belongs in `build_scenes` where the `SceneState` is minted.

### What must be preserved (do not touch)

- **6-1 variant→label wiring:** `_call_stage`'s `label` branch ([scenario_chain.py:54-58](src/yt_flow/pipeline/nodes/scenario_chain.py#L54-L58)) — `label=None` must keep going through `prompt_service.get_prompt` (not `get_prompt_with_fallback`) because existing tests monkeypatch `yt_flow.services.prompt_service.get_prompt` (pattern at [test_scenario_chain.py:51-53](tests/pipeline/nodes/test_scenario_chain.py#L51-L53) and `fake_get_prompt_for_chain` in [tests/stubs/fakes.py:172](tests/stubs/fakes.py#L172)). This story changes no prompt fetching at all.
- **Downstream defensive `resolve_mood` calls stay:** [video.py:512](src/yt_flow/pipeline/nodes/video.py#L512) (asset validation), [video.py:625](src/yt_flow/pipeline/nodes/video.py#L625) (sound design), [video.py:889/893](src/yt_flow/pipeline/nodes/video.py#L889) (transition variety), and `build_post_filter` ([color_grade.py:29-31](src/yt_flow/pipeline/nodes/color_grade.py#L29-L31)). They protect resumed pre-fix checkpoints and manual state edits; leave them.
- **`edit_artifact` already preserves mood:** the scenario edit path mutates only `target["narration"]` ([run_service.py:643-644](src/yt_flow/services/run_service.py#L643-L644)) — gate edits can't clobber mood, no change needed there.
- **Frontend `EditableTextPanel` round-trip hazard — do not "display" mood by injecting it into the text.** The scenario gate panel renders `data.scenes.map((s) => s.narration).join("\n\n")` as *editable* text ([ArtifactPanel.tsx:136](frontend/src/components/ArtifactPanel.tsx#L136)) that is written back verbatim via `edit_artifact`; prefixing mood into that string would corrupt narration on save. AC:5 is API-only; a read-only mood badge in the UI is a Saved Question, not this story.
- **Old checkpoints:** `build_scenes` only runs during the scenario stage, so resumed runs past scenario are unaffected; pre-7.1 checkpoints lack the `mood` key entirely, which is why the API serializer must use `.get` (AC:5) — same reason the existing serializer uses `sh.get("layered_fallback", False)` at [run_service.py:108](src/yt_flow/services/run_service.py#L108).

### Test plan (actual files & conventions)

- **Unit (chain):** [tests/pipeline/nodes/test_scenario_chain.py](tests/pipeline/nodes/test_scenario_chain.py) — pure-function `build_scenes` tests need no prompts or fakes; use `caplog` (`caplog.at_level(logging.WARNING)`) to assert the AC:3 warning text. The existing `_ONE_SHOT_VISUAL` helper (line 534) is reusable; add a parallel minimal `structure` fixture.
- **Node-level:** [tests/pipeline/nodes/test_scenario.py](tests/pipeline/nodes/test_scenario.py) drives `scenario_node` through `deepseek_stage_aware()` ([tests/stubs/fakes.py:184](tests/stubs/fakes.py#L184)), which replays the JSON cassettes in [tests/fixtures/cassettes/](tests/fixtures/cassettes/) (OpenAI-shaped: `choices[0].message.content` holds the payload string). `deepseek_structure.json` and `deepseek_writing.json` both currently contain no `mood` keys, so today's node-level runs would hit the fallback path — add enum moods to the structure cassette's scenes for happy-path coverage.
- **API:** [tests/api/test_stage_artifacts.py](tests/api/test_stage_artifacts.py) mocks the graph via `_mock_graph` (canned `aget_state` values) — extend `_scene`/assertions per Task 3.
- Runner: `PYTHONPATH=$PWD/src pytest ... -q` (worktree editable-install shadowing caveat: the global editable install points at the main tree, so set `PYTHONPATH` when running from a worktree). Finish with the full suite + `ruff check src/yt_flow tests`.

### Ponytail

Minimal diff, no new abstractions: one added parameter on an existing pure function, ~6 lines of mood resolution (guard + warn + `resolve_mood`), one dict key in an existing serializer, test updates. **No** new module, no `Mood` class/validator, no config flag (this is a bug fix, not a feature toggle), no schema migration, no changes to `sound_design.py` (`resolve_mood` is reused as-is — its silent fallback stays correct for its call sites; the *chain* owns the loud warning because that's where the authoritative value is minted). If the inline resolution reads badly, one tiny module-private helper in `scenario_chain.py` is the ceiling.

### Project Structure Notes

- Files touched: `src/yt_flow/pipeline/nodes/scenario_chain.py` (import + `build_scenes`), `src/yt_flow/pipeline/nodes/scenario.py` (one call site), `src/yt_flow/services/run_service.py` (one serializer key), `tests/pipeline/nodes/test_scenario_chain.py`, `tests/api/test_stage_artifacts.py`, `tests/fixtures/cassettes/deepseek_structure.json`. **No new files, no new dependency, no prompt change required, no DB/schema change, no frontend change.**
- Layer rule [AD-1] intact: `scenario_chain.py` already imports from `sound_design` (same pipeline layer) and `services.prompt_service`; nothing new crosses a layer.
- Epic interaction: unblocks live observability of 7-1/7-2/7-4 (their code is done; their *variety* was invisible under all-dread). Independent of Epic 8's image-compositing rework — safe to implement in parallel; the only shared file with typical Epic 8 work is `run_service.py` (one-line serializer addition, low collision risk, but note the recurring sprint-status/parallel-session hazard from 5-7/1-13 reviews).

### References

- [Source: _bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md#결함 D1/D2] — live evidence, run 272b05a4 (8/8 invalid moods; API omits mood)
- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.15] — story draft
- [Source: prompts/scenario/structure.md#L48-L55] — the mood enum contract (only place it exists)
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L320-L375] — `build_scenes` (mood at L372); L97-L116 `structure_step`; L134 writing receives `scene_structure`
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L111-L125,L162,L183] — positional structure↔writing rule; `structure` in scope at the `build_scenes` call
- [Source: src/yt_flow/pipeline/nodes/sound_design.py#L12-L38] — `MOOD_VALUES`, `DEFAULT_MOOD`, `resolve_mood` (silent fallback)
- [Source: src/yt_flow/domain/state.py#L46] — `SceneState.mood`
- [Source: src/yt_flow/services/run_service.py#L80-L100] — scenario artifacts serialization (mood absent)
- [Source: docs/PROMPT_POLICY.md] — protocol governing the optional Task 4
- [Source: /mnt/work/projects/yt.pipe/templates/scenario/03_writing.md#L88] — writing prompt's `"mood": "tense"` example (out-of-enum; why writing output is untrustworthy)

### Saved Questions (non-blocking)

1. **UI mood badge at the scenario gate** — AC:5 exposes mood in the API only; a read-only per-scene badge in the scenario panel (NOT inside `EditableTextPanel`'s editable text — see round-trip hazard) would complete D2 for non-API users. Separate small frontend story if wanted.
2. **Writing prompt cleanup** — after this fix, writing's `mood` output is dead weight and its `"tense"` example misleads the LLM. Worth a PROMPT_POLICY-gated cleanup eventually, but it first requires materializing `prompts/scenario/writing.md` in-repo (rule 1); bundled here only as optional Task 4.
3. **Backfill for run 272b05a4** — no checkpoint migration is planned; old runs keep their stored moods (defensively resolved downstream). Re-validating 7-1/7-2/7-4 variety needs a fresh E2E run after this story — fold into the next baseline iteration rather than a dedicated re-render?
4. **Structure prompt rule 7 vs. mood** — structure.md rule 7 says adjacent scenes must differ in *emotional beat*; nothing requires mood variety across scenes. If a future run yields valid-but-uniform moods (all dread legitimately), that's prompt tuning territory, not wiring.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5 (bmad-dev-story)

### Debug Log References

- `PYTHONPATH=$PWD/src pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/api/test_stage_artifacts.py -q` → 68 passed
- `PYTHONPATH=$PWD/src pytest -q` (full suite) → 702 passed, 1 skipped, 1 failed (`test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`). Bisected via `git stash` (this story's files vs. the rest of the working tree): the failure reproduces with *only* Story 5.14's in-progress, uncommitted changes applied (`config.py`, `image.py`, `comfyui_client.py`, `tests/stubs/fakes.py`) and does not reproduce on a clean `git stash`-restored HEAD or with only this story's files applied. Pre-existing to 5.15, caused by a concurrent in-progress session (5.14) sharing this working tree — not fixed here per user instruction to leave 5.14 alone.
- `ruff check src/yt_flow/pipeline/nodes/scenario.py src/yt_flow/pipeline/nodes/scenario_chain.py src/yt_flow/services/run_service.py tests/api/test_stage_artifacts.py tests/pipeline/nodes/test_scenario_chain.py` → clean

### Completion Notes List

- `build_scenes` now takes a `structure: list[dict]` param and reads `mood` positionally from the structure scene (guarded like `_scene_role_text`, same precedent as `_write_and_review`'s `scene_role` lookup). Invalid/missing/non-dict/out-of-range → `resolve_mood` fallback + `logger.warning` naming the scene number and raw value. Writing's own `mood` output is now fully ignored.
- `scenario.py`'s single call site updated to pass the already-in-scope `structure` list — one-line plumbing, no new state threading.
- `run_service.get_stage_artifacts`'s scenario branch now exposes `"mood": s.get("mood")` — `.get` (not bracket access) so pre-7.1 checkpoints without a `mood` key serialize to `null` instead of 500ing.
- Test suite: replaced the two mood tests that asserted the old (buggy) writing-sourced behavior with five new cases covering AC1-4 (valid pass-through no-warning, structure-wins-over-writing, invalid mood, missing key, non-dict entry, writing-over-produces-scenes trailing fallback). Updated the four non-mood `build_scenes` call sites for the new signature. Added a valid `"mood": "escalation"` to `deepseek_structure.json`'s first scene for cassette-driven happy-path coverage (second scene deliberately left mood-less — it's never read since the writing cassette only produces 1 scene). API test: `_scene` helper gained `mood`/`include_mood` params; added a dedicated pre-7.1-checkpoint case asserting `mood is None`.
- Task 4 (optional writing-prompt cleanup, AC:7) **skipped** per the story's own recommended default — after Task 1 the writing stage's `mood` output is fully dead, so removing it is cleanup, not correctness, and materializing `prompts/scenario/writing.md` in-repo first (PROMPT_POLICY rule 1) is out of scope for a wiring bug fix.
- Full regression suite: 702 passed, 1 pre-existing skip, 1 failure — see Debug Log for the bisection proving that failure belongs to the concurrently in-progress Story 5.14, not this story.

### File List

- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `src/yt_flow/services/run_service.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `tests/api/test_stage_artifacts.py`
- `tests/fixtures/cassettes/deepseek_structure.json`

## Change Log

- 2026-07-06: Implemented Story 5.15 (mood sourced from structure, normalized+warned at chain time, exposed in scenario artifacts API). Tasks 1-3 complete (all ACs 1-6 satisfied); Task 4 (optional prompt cleanup, AC:7) skipped per its own recommended default. Targeted suite 68/68 passed, full regression 702 passed/1 skipped/1 pre-existing failure (bisected to concurrent Story 5.14 WIP, not this story), ruff clean. Status → review.
