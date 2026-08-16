---
title: 'Story 12.7 — Prose harness: script-wide device quotas become per-scene assignments'
type: 'feature'
created: '2026-08-16'
status: 'in-review'
baseline_revision: '29d5903'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/12-7-prose-harness-device-allocation.md'
  - '{project-root}/_bmad-output/implementation-artifacts/12-6-live-validation/ablation.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** `prompts/scenario/writing.md:38-48` states its immersion-device quotas **for the whole script** ("2인칭: 시나리오 전체에서 최소 3회"), but `writing_step` (`scenario_chain.py:1780`) runs **one LLM call per scene** and each call sees only its own scene plus a one-line summary of its neighbours (`_writing_scene_brief:1746`). A writer that cannot count what the other scenes did fills the quota in its own scene, so a whole-script "≥3" executes 8 times: measured on the 12.6 output (`after_scenes.json`, SCP-049, 8 scenes) 극적 질문 fired in **8/8 scenes** and 2인칭 in 6/8. A second, independent per-scene question requirement hides in the 종결어미 rhythm rule (`writing.md:61`), and a third leak in `prompts/scenario/writing_scene_repair.md:25`. Compounding it, the flat `문장 길이: 15~25자` rule (`writing.md:52`) forbids the causal/contrastive subordinate clauses that connect one fact to the next, so scenes open on bare facts (0/7 scenes connected to the previous one). Jay's verdict on the result: "맥락 없이 상세한 내용만 주저리주저리한다".

**Approach:** Copy the `hook_type` shape — a whole-script decision made in Python over the whole outline, delivered to each scene as its own share. Add a deterministic `_allocate_devices(structure)` that writes `assigned_devices` onto each outline scene right after `_validate_retention_outline`; because `_writing_scene_brief` builds its payload as `{**structure[idx], …}` and the repair step json.dumps the same dicts, that single write reaches both prompts with no further plumbing. Then rewrite the prompt's quota block to "use only what is assigned, and do not use what is not", fix **all three** question sources, and relax the sentence-length rule to allow connective sentences while keeping short-sentence dramatic pauses. No new LLM call. The exact prompt wording is not invented here — arms A and B of `12-6-live-validation/ablation.md` ran it live and it is committed in `run_ablation.py`; this story productionises that wording plus the two allocation holes the ablation exposed.

## Boundaries & Constraints

**Always:**
- Allocation is computed in Python from the **whole outline**, never requested from the writer. Rules read only fields `_validate_retention_outline` already constrains to a closed vocabulary (`pattern_interrupt`, `loops_closed`, `word_budget`) plus position — never `act` names, which vary by archetype.
- `_allocate_devices` is **total**: for any outline of n ≥ 1 scenes, every device in `WRITING_DEVICES` is owned by ≥ 1 scene and the **last** scene owns ≥ 1 device.
- Grounding rules are untouched: the `fact_references` obligation, the "no assertion outside it" prohibition, and the three permitted-adaptation categories all stay exactly as written.
- `scene_num` stays positional; nothing in this story may make the model's `scene_num` authoritative.
- Prompt edits are made in `prompts/*.md` and seeded via `scripts/migrate_prompts.py` (repo file is the source of truth, DEV MODE → straight to `production`).

**Block If:**
- The live re-measurement shows a **writing-stage-originated** grounding violation that control did not have (AC8) — that is a real regression and needs a human decision, not a prompt tweak.
- Seeding's `--dry-run` shows drift in a prompt this story did not edit.

**Never:**
- Do not touch the structure stage's `fact_references` / `event` generation. Every grounding violation the ablation found in all three arms traced to the outline, not the writer; that is Story 12.8. Reading a violation in the re-measurement as this story's regression is the single most likely wrong turn.
- Do not add a device-counting validator or a retry on device counts. Allocation is deterministic; compliance is measured, not enforced by re-rolling an LLM.
- Do not ban short sentences. The relaxation removes a uniform ceiling; the dramatic-pause pattern (`writing.md:54-55`) stays.
- Do not add `assigned_devices` to `SceneState` or persist it into run state — the writing prompt is its only consumer.
- No audio/pause work (Jay's second complaint) — separate concern, out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Typical outline | 8-9 scenes, `pattern_interrupt` has 2 `direct_address` + 1 `tone_shift`, loops closed in scenes 4 and 7 | `dramatic_question` → scenes 1 and n; `second_person` → the two `direct_address` scenes; `narrator_reaction` → the `tone_shift` scene; `hypothetical` → the lowest-indexed `second_person` scene; every other scene gets `[]` | No error expected |
| No `direct_address` anywhere | all `pattern_interrupt` are `none` | `second_person` falls back to the two largest-`word_budget` middle scenes; hook and final scene are never used as fallback carriers | No error expected |
| Degenerate outline | n = 1, or n = 2, or every loop closed in the hook scene | Still total: every device owned ≥ 1 time, last scene non-empty; fallback pool widens to all scenes when the middle band is empty | No error expected |
| Missing/garbage fields | scene lacks `pattern_interrupt`, or `word_budget` is `None`/non-numeric | Treated as `"none"` / sort key 0; allocation still total | No exception raised — allocation never fails a run |
| Brief assembly | `_writing_scene_brief(structure, idx)` on an allocated outline | `write_only_this_scene.assigned_devices` is that scene's list (possibly `[]`) | Absent key if `structure_step` was bypassed; prompt treats absence as "none assigned" |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/scenario_chain.py:1718` -- `_validate_retention_outline(scenes)` call at the end of `structure_step`, after the await. The allocation write goes immediately after it: validated outline in, annotated outline out.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:872-962` -- `_validate_retention_outline`; the closed vocabularies allocation is allowed to read (`hook_type` scene-1-only rule at `:925-932` is the precedent shape: a whole-script decision enforced in Python, `none` everywhere else).
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1746-1777` -- `_writing_scene_brief`; payload is `{**scene, "scene_num": idx+1}` at `:1763`, so any field on the outline scene reaches the prompt. No change needed here beyond a docstring line.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1780-1872` -- `writing_step`, one `_call_stage_with_retry` per scene via `asyncio.gather`; variables at `:1848-1855`. Unchanged.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1875+` -- `writing_scene_repair_step`; json.dumps the same outline dicts into `{{scene_structure}}`, so it inherits `assigned_devices` for free.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:95-112` -- Story 12.1/12.6 retention constants; the device vocabulary belongs beside them.
- `prompts/scenario/writing.md:38-49` -- the quota block (source #1 of the question). `:52` sentence length. `:53` connective bullet. `:61` 종결어미 의문형 (source #2). `:115` "여전히 전부 필수지만" contradicts allocation. `:139-159` the "Stage 2 리텐션 계약 준수" list that already documents per-scene outline fields — the natural home for an `assigned_devices` bullet. `:203-211` pre-output self-check.
- `prompts/scenario/writing_scene_repair.md:25` -- `pattern_interrupt` bullet; source #3 of device reintroduction.
- `_bmad-output/implementation-artifacts/12-6-live-validation/run_ablation.py:57-108` -- `allocate()`, the live-validated allocation; `:110-188` the exact replacement prompt strings for arms A and B. Both are the starting text, not a reference to paraphrase.
- `_bmad-output/implementation-artifacts/12-6-live-validation/armA_scenes.json` -- carries a full `structure` (the outline) under the `structure` key. This is the pinned outline the re-measurement reuses so writing is the only thing that changes (Trap 4).
- `_bmad-output/implementation-artifacts/12-6-live-validation/count_devices.py` -- the device instrument; `label=path` CLI, counts 2인칭/질문/리액션/가정 plus sentence shape, prints `배정 대비 실제` per arm and dumps `리액션_hits` so narrator-stance words can be separated from lurid object adjectives by hand (AC9).
- `scripts/measure_script.py` -- `--scenes-json <dump> --durations-json <seconds>` mode (the mode the ablation used) gives 어절/WPM without a graph run.
- `_bmad-output/implementation-artifacts/12-6-live-validation/run_after_tts.py` -- synthesises per-scene WAVs and writes the durations JSON that WPM needs.
- `scripts/migrate_prompts.py` -- `--dry-run` prints the manifest only (no client, no writes); the real change set is confirmed by comparing against `client.get_prompt` as `12-6-live-validation/seeding.md` did.
- `tests/pipeline/nodes/test_scenario_chain.py` -- existing home for retention-contract and prompt-text pinning tests.

## Tasks & Acceptance

**Execution:**

- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:95-112` -- add `WRITING_DEVICES = ("dramatic_question", "second_person", "narrator_reaction", "hypothetical")` with a comment stating that 감각 묘사 is deliberately absent (it is texture, free in every scene) and that the tuple is the writing prompt's vocabulary. -- AC1/AC4: one closed vocabulary both the allocator and the test read.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` (beside `_writing_scene_brief`) -- add `_allocate_devices(structure: list[dict]) -> list[list[str]]`, porting `run_ablation.py:57-108` with two corrections: (a) `dramatic_question` owners are **the hook scene and the final scene** (the last loop-closer becomes only a fallback when n < 2), closing the arm-A hole where scene 9 of 9 drew nothing; (b) `hypothetical` gets its **own** slot — the lowest-indexed `second_person` owner — instead of being folded into the 2인칭 bullet, closing the arm-A hole where 상황 가정 went to 0 occurrences. Fallback pool is the middle band `range(1, n-1)` ordered by descending `word_budget`, widened to `range(n)` when that band is empty. Never raises: missing `pattern_interrupt` reads as `"none"`, non-numeric `word_budget` sorts as 0. -- AC1/AC4.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1718` -- after `_validate_retention_outline(scenes)` in `structure_step`, write `scene["assigned_devices"] = devices` for each `(scene, devices)` pair. Comment that this is the same seam `hook_type` uses (whole-outline decision, per-scene delivery) and that the `{**scene}` splat in `_writing_scene_brief` plus the repair step's json.dumps are the two consumers, so no other call site changes. -- AC1.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1746-1777` -- extend `_writing_scene_brief`'s steering sentence with one clause naming `assigned_devices` as this scene's complete device list, and note it in the docstring. -- AC1/AC2: the free-text variable carries the instruction so it survives even if a prompt version lags.
- [x] `prompts/scenario/writing.md:38-49` -- replace the whole `### 필수 몰입 기법 (전부 사용)` block (up to `### 문장 & 페이싱 규칙`) with `run_ablation.py`'s `WRITING_DEVICE_BLOCK` verbatim, retitled `### 몰입 기법 — 이 씬에 배정된 것만 사용`, plus one added numbered bullet for **상황 가정** keyed to `hypothetical` (its own device now, with the "만약 당신이 이 SCP를 만난다면" example) and 2인칭 no longer carrying it. Keep the explicit "배정되지 않은 기법은 쓰지 마세요" sentence and the per-device "배정되지 않았다면 …" negative instruction — those are what produced 4/4 exact compliance. -- AC2.
- [x] `prompts/scenario/writing.md:61` -- replace the 종결어미 의문형 line with `run_ablation.py`'s `QUESTION_RHYTHM_NEW`: 의문형 applies **only** when `dramatic_question` is assigned, and an unassigned scene builds rhythm from forms 1·3·4. -- AC3: source #2 of the per-scene question. Editing only the technique block yields a null result.
- [x] `prompts/scenario/writing.md:115` -- `여전히 전부 필수지만` → `배정된 기법은 여전히 필수지만`, so the fact-grounding section stops contradicting the allocation. -- AC2/AC3.
- [x] `prompts/scenario/writing.md:52-53` -- replace the sentence-length line with `SENTENCE_LENGTH_NEW` (기본 15~25자, 인과·대조 연결 구문은 40자까지, 한 씬에 두세 개까지) and append `CONNECTIVE_NEW`'s bullet requiring each scene's first sentence to establish the link to `previous_scene_context` before entering its own facts (Scene 1 exempt), with the ❌/✅ pair. Leave `:54-55`'s dramatic-pause rule untouched. -- AC5/AC6.
- [x] `prompts/scenario/writing.md:139-159` -- add an `assigned_devices` bullet to the "Stage 2 리텐션 계약 준수" list alongside `hook_type` / `pattern_interrupt`, stating it is the complete device set for this scene. -- AC2: the outline-field list is where a writer looks for what a per-scene field means.
- [x] `prompts/scenario/writing.md:203-211` -- add one pre-output self-check line: no device outside `assigned_devices` was used (질문·2인칭·리액션·상황 가정). -- AC2.
- [x] `prompts/scenario/writing_scene_repair.md:25` -- append `run_ablation.py`'s `REPAIR_NEW` line: `assigned_devices` is the complete set, do not add an unassigned device while repairing. -- AC3: source #3.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- add: `_allocate_devices` totality over synthetic outlines n = 1…12 (every `WRITING_DEVICES` member owned ≥ 1×, last scene non-empty, hook owns `dramatic_question`); `direct_address` scenes own `second_person`; `tone_shift`/`pov_shift` own `narrator_reaction`; `hypothetical` lands on a `second_person` scene; missing `pattern_interrupt`/`word_budget` does not raise; `structure_step` leaves `assigned_devices` on every outline scene; `_writing_scene_brief` payload carries it; and prompt-text pins — `writing.md` contains `assigned_devices` and no longer contains `"### 필수 몰입 기법 (전부 사용)"`, `"- 문장 길이: 15~25자 (TTS 최적화용 — 짧고 펀치있게)"`, or `'2. 의문형 (-까요?/-을까요? — 위 "극적 질문" 기법과 동일)'`; `writing_scene_repair.md` contains `assigned_devices`; every `WRITING_DEVICES` member appears in `writing.md`. -- covers the I/O matrix and makes AC3's three-source rule a test rather than a hope.
- [x] `_bmad-output/implementation-artifacts/12-7-live-validation/run_writing_only.py` -- new driver: load the pinned outline from `12-6-live-validation/after_scenes.json`'s `structure` key (the **control** run's own outline — a fairer pin than arm A's, since the control numbers were measured against it), strip any pre-existing `assigned_devices`, monkeypatch `scenario.structure_step` to return that outline unchanged (so the production `_allocate_devices` + `structure_step` write path still runs), drive `scenario_node` on SCP-049, and dump `{scenes, structure, allocation, scenario_quality, stages}` to JSON. -- Trap 4: the outline is held fixed so device counts, sentence length and WPM are attributable to the writing change alone.
- [x] `_bmad-output/implementation-artifacts/12-7-live-validation/` -- run the driver, synthesise durations with `12-6-live-validation/run_after_tts.py`, then `count_devices.py control=…/after_scenes.json after=…/after_scenes.json` and `scripts/measure_script.py --scenes-json … --durations-json …`; commit the dumps, both reports and a `.gitignore` modelled on `12-6-live-validation/.gitignore` (ignore `tts_audio/` and listening copies, commit everything a number is re-derived from). If live LLM access is unavailable, record that explicitly in the report and leave AC7-AC9 open rather than substituting a stub run. -- AC7/AC9. Seeding runs BEFORE this: the chain fetches prompts from Langfuse, so an unseeded run would measure the old prompt.
- [x] `_bmad-output/implementation-artifacts/12-7-live-validation/after.md` -- the report: control-vs-after table (질문·2인칭·리액션·가정 총계와 사용 씬 수, 배정 대비 실제 일치, 평균 문장 길이, 앞 씬 연결 씬 수, 총 어절, WPM, `review_overall_pass`), the reaction re-classification by hand (narrator-stance vs object adjective, per AC9), and a **grounding section that separates writing-originated from outline-originated violations** with the sentence and its `fact_references` quoted for each. -- AC8/AC9.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- **added in review:** `_require_seeded_device_allocation`, called at `writing_step` entry. The allocation travels inside free text, so an unseeded `scenario/writing` renders without error and silently reverts to script-wide quotas; the prompt-text tests read the repo file and cannot see it. Mirrors 12.6's `_require_seeded_budget_variables`.
- [x] `_bmad-output/implementation-artifacts/12-7-live-validation/first_sentences.py` -- **added in review:** prints each scene's opening sentence so AC6's count is a judgment against committed output rather than an unre-derivable number.
- [x] `uv run python scripts/migrate_prompts.py --label production --source prompts` -- run `--dry-run` first and diff the two edited prompts against Langfuse as `12-6-live-validation/seeding.md` did; confirm the change set is exactly `scenario/writing` and `scenario/writing_scene_repair`, then seed. Record the output in `12-7-live-validation/seeding.md`. -- CLAUDE.md DEV MODE; known-drifted `character/*` prompts must not ride along.

**Acceptance Criteria:**

- Given any outline the retention validator accepts, when `_allocate_devices` runs, then every member of `WRITING_DEVICES` is owned by at least one scene and the final scene owns at least one device — with no LLM call added anywhere in the writing stage.
- Given a scene with no device assigned, when its narration is written, then it contains no dramatic question, no 2인칭 address, no narrator reaction and no hypothetical — and its 종결어미 variety is satisfied by the declarative / nominal / inverted forms alone.
- Given the technique block is edited but `writing.md:61` or `writing_scene_repair.md:25` is not, when the test suite runs, then a test fails naming the unedited source.
- Given the live re-measurement of SCP-049 on the pinned outline, when `count_devices.py` compares it to the 12.6 control, then 질문 and 2인칭 each fire only in their assigned scenes, the per-scene question rate falls from 1.0+ to at most the assigned share, and 상황 가정 is present at least once.
- Given the same measurement, when `measure_script.py` reports WPM, then it is at most 165; if it exceeds 165 the sentence relaxation is tightened and re-measured before the story closes.
- Given the same measurement, when each scene's first sentence is read, then scenes 2…n establish the link to the previous scene before entering their own facts, and the count is recorded against the control's 0/7.
- Given the same measurement's grounding review, when each flagged sentence is traced, then the report attributes it to the writing stage or to the outline's `fact_references`/`event`, and the count of **writing-originated** new violations is 0.
- Given the seeding dry run, when it is inspected, then only `scenario/writing` and `scenario/writing_scene_repair` differ from what Langfuse holds.

## Spec Change Log

## Review Triage Log

### 2026-08-16 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 2, medium 11, low 6)
- defer: 3: (medium 2, low 1)
- reject: 6
- addressed_findings:
  - `[high]` `[patch]` `허용되는 각색` §2/§3 licensed a 2인칭 address and an open question in EVERY scene, contradicting the allocation block three sections above — added "배정된 씬에서만" qualifiers to both categories.
  - `[high]` `[patch]` AC6's connective-opening rule made a scene restate the PREVIOUS scene's finding as settled fact outside its own `fact_references`; observed live (pass 2, scene 8: "마스크가 곧 피부였던…"). Rule narrowed to 상태·시간·감정 only, with that sentence pinned as the ❌ example, and re-measured (pass 3: gone, `review_overall_pass` back to true).
  - `[medium]` `[patch]` `writing.md`'s `pattern_interrupt` bullet orders every `direct_address` scene to address the viewer while the allocation capped `second_person` at two — a third such scene got both instructions. Cap removed (allocation now owns every `direct_address` scene) plus a cross-reference line; new test pins it.
  - `[medium]` `[patch]` `writing_scene_repair.md:25` still ordered `pattern_interrupt` techniques on the line above the new allocation line — added an explicit precedence line.
  - `[medium]` `[patch]` No runtime check that the SEEDED `scenario/writing` knows about `assigned_devices`; because the allocation rides in free text, an unseeded prompt renders fine and silently reverts to script-wide quotas while every prompt-text test stays green. Added `_require_seeded_device_allocation`, mirroring 12.6's `_require_seeded_budget_variables`, called at `writing_step` entry.
  - `[medium]` `[patch]` The driver claimed "writing is the only variable" while the research stage ran live, regenerating four writing inputs. Docstring corrected and the research payload is now dumped so the residual confound is inspectable.
  - `[medium]` `[patch]` The no-`direct_address` fallback stacked 2인칭 + 리액션 + 가정 onto one scene — the clustering the story exists to remove. Reaction fallback now steps aside when the pool allows.
  - `[medium]` `[patch]` `_repair_and_review` hands `{}` for a scene past the outline, so the repair prompt would read a missing `assigned_devices` as "none assigned" and strip every device. Added the missing-key rule to the repair prompt, plus a line preserving the connective opening.
  - `[medium]` `[patch]` The pre-output self-check would strip questions belonging to a quoted transcript in a `format_change` scene — added the exemption.
  - `[medium]` `[patch]` The technique block deleted 감각 묘사's "2~3씬마다 하나 이상" floor, which is the only device left in an unassigned scene. Floor restored inside the free bullet.
  - `[medium]` `[patch]` `count_devices.py`'s `ASSIGNED_AXIS` had no `hypothetical` entry, so the device AC4 exists to rescue was the one axis never checked against its assignment. Added.
  - `[medium]` `[patch]` Raw reaction count rose (control 9 → 10) and the report's judgment section never addressed it; re-classified by hand in every pass and reported (pass 3: 3 hits in 3 scenes, one of them a genuine out-of-assignment leak).
  - `[medium]` `[patch]` AC2 closed with a documented counter-example and no recorded exception — the residual leak is now stated as a residual defect rather than folded into a pass.
  - `[low]` `[patch]` `test_allocate_devices_gives_the_question_to_the_hook_and_the_final_scene` set `loops_closed`, which `_allocate_devices` never reads — vacuous fixture removed.
  - `[low]` `[patch]` `_allocate_devices([])` raised `ValueError` from `min()` while the docstring promised it never raises — early return.
  - `[low]` `[patch]` `run_writing_only.py` parsed `--run-id` and ignored it (two different run ids across the dump and the audio), `relative_to(ROOT)` could raise AFTER a paid live run, and `outline.extend` doubled the dump on a second call. All three fixed.
  - `[low]` `[patch]` The "앞 씬과 연결하며 시작" count had no committed re-derivation — added `first_sentences.py`, which prints the sentences the judgment is made against.
  - `[low]` `[patch]` The 40자 ceiling is exceeded (4 sentences in two scenes, max 75자) and the report claimed no tightening was needed on WPM alone — recorded, with control's own violation of the old rule as context.
  - `[low]` `[patch]` Sentence-length growth pushes more sentences past `subtitle.py`'s `_CUE_CHAR_SOFT_CAP = 44` — recorded as an unmeasured downstream effect rather than left silent.

## Design Notes

**Why the allocation is written onto the outline rather than passed as a new variable.** `_writing_scene_brief` builds `{**structure[idx], "scene_num": idx+1}`, and `writing_scene_repair_step` json.dumps the same dicts. One write after validation therefore reaches both prompts; a new prompt variable would reach one of them and need a second edit for the other. This is the ablation's proven seam.

**Allocation rules read only validator-constrained fields**, so a different archetype naming its acts differently cannot shift the assignment:

```python
question   = {0, n - 1}                                     # hook + final (arm A's hole)
second_person = [direct_address scenes][:2] or middle_by_budget[:2]
reaction   = [tone_shift/pov_shift scenes][:2] or middle_by_budget[:1]
hypothetical = {min(second_person)}                         # its own slot (arm A's other hole)
```

**The two ablation holes, restated so they are not re-opened.** Arm A gave scene 9 of 9 nothing because `dramatic_question` went to the *last loop-closer*, which closed in scene 7; and 상황 가정 vanished entirely (5 → 0) because it shared the `second_person` bullet, so the model read one device where the control prompt had two. Both are allocation bugs, not prompt-wording bugs.

**Expected measurement shape** (from the ablation, same SCP): 질문 8/8 씬 → 2 씬, 2인칭 6/8 → 2 씬, 평균 문장 33.1자 → ~42자, 앞 씬 연결 0/7 → ~7/7, WPM 148 → ~158. Arm B's `review_overall_pass: false` came from a critic `pacing` note on the hook restating one fact twice — a known cost of the longer sentences; if it recurs, the fix is the hook scene's own rule, not the allocation.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q` -- expected: all pass, including the new allocation-totality and prompt-pin tests.
- `uv run pytest tests/ -q -x --ignore=tests/e2e` -- expected: no regression elsewhere in the scenario chain.
- `uv run python -c "from yt_flow.pipeline.nodes.scenario_chain import _allocate_devices, WRITING_DEVICES; ..."` -- expected: totality holds for n = 1…12 (also asserted in the test file).
- `uv run python scripts/migrate_prompts.py --dry-run --source prompts` -- expected: manifest lists `scenario/writing` and `scenario/writing_scene_repair` with unchanged variable sets.
- `uv run python _bmad-output/implementation-artifacts/12-7-live-validation/run_writing_only.py --out …/after_scenes.json` -- expected: 8-9 scenes written against the pinned outline, `allocation` recorded.
- `uv run python _bmad-output/implementation-artifacts/12-6-live-validation/count_devices.py control=…/after_scenes.json after=…/12-7-live-validation/after_scenes.json` -- expected: 배정 대비 실제 일치 on 질문 and 2인칭.

**Manual checks (if no CLI):**
- Read each scene's first sentence in the new dump and record how many establish the link to the previous scene (AC6 has no automated instrument).
- Re-classify every `리액션_hits` word as narrator stance vs object adjective before calling a hit a compliance violation (AC9).

## Auto Run Result

Status: done

**Change.** `writing.md`'s immersion-device quotas were stated for the whole script while writing runs one LLM call per scene, so a "전체에서 최소 3회" rule executed once per scene — measured at 극적 질문 in 8 of 8 scenes. A deterministic `_allocate_devices` now decides over the whole outline in Python and `structure_step` writes each scene's share onto it as `assigned_devices`; because `_writing_scene_brief` splats the outline scene and the repair step json.dumps the same dicts, that one write reaches both prompts with no new variable and no new LLM call. The prompts were rewritten to obey the assignment (all four question sources, not the three the story named), the flat 15~25자 sentence rule was relaxed so causal/contrastive clauses can connect one fact to the next, and each scene now opens on the previous scene's state rather than a bare fact.

**Files.**
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `WRITING_DEVICES`, `_allocate_devices`, the `structure_step` annotation, the `_writing_scene_brief` steering clause, and `_require_seeded_device_allocation` (an unseeded prompt reverts silently, so the runtime text is checked at `writing_step` entry).
- `prompts/scenario/writing.md` — device block keyed to `assigned_devices` (상황 가정 given its own device), 종결어미 의문형 made conditional, sentence-length relaxation, first-sentence connection rule, `assigned_devices` documented in the retention-contract list, self-check line, plus the review's guard clauses (adaptation categories, `format_change` transcript exemption, restored sensory floor, `pattern_interrupt` cross-reference).
- `prompts/scenario/writing_scene_repair.md` — allocation precedence, missing-key rule, connective-opening preservation.
- `tests/pipeline/nodes/test_scenario_chain.py` — allocation totality (n=1…12), per-rule ownership, empty/garbage inputs, `structure_step` annotation, brief carriage, seeding guard, and prompt-text pins that fail if any question source is left unedited.
- `_bmad-output/implementation-artifacts/12-7-live-validation/` — driver, dumps, measurement report, opening-sentence extractor, seeding record.
- `_bmad-output/implementation-artifacts/12-6-live-validation/count_devices.py` — `hypothetical` added to the assignment axis map.

**Review.** 19 patches applied (high 2, medium 11, low 6), 3 deferred, 6 rejected; no intent gap and no spec loopback. The two high findings were both live-confirmed rather than argued: two adaptation categories licensed a 2인칭 address and an open question in every scene, and the new connective-opening rule made scene 8 restate scene 7's finding as settled fact outside its own `fact_references`. Both were fixed, re-seeded and re-measured.

**Verification.** `uv run pytest tests/ -q -x --ignore=tests/e2e` → 2982 passed, 1 skipped. Three live runs on the same pinned outline (SCP-049, same clone voice), one per prompt revision, because a prompt that was not measured must not ship. Shipped run: 질문 2 occurrences in 2 of 8 scenes (control 9 in 8 of 8) with 배정 [1,8] = 실제 [1,8]; 2인칭 2 in 2 of 8 (control 7 in 6 of 8) with 배정 [2,6] = 실제 [2,6]; scenes with no assignment used none of the four devices; 앞 씬 연결 7/7 (control 0/7); WPM 146.9 against a 165 ceiling; every scene inside ±20% of its word budget; `review_overall_pass` true. Grounding: the one fidelity finding (scene 7's dropped "appears fused" hedge) is reproduced verbatim from the outline's `event.consequence` and `key_points` — writing-originated new violations: 0.

**Residual risks.** The narrator-stance adverb "놀랍게도" leaked into one unassigned scene in two of three runs and survives the self-check. Sentence length still exceeds the stated 40자 allowance in two scenes (max 75자) — as it did under the old rule, so the item reads as a tendency knob rather than a ceiling. Longer sentences push more text past `subtitle.py`'s 44-char cue cap; the resulting on-screen rhythm was not measured. The research stage is not pinned, so `frozen_descriptor`/`entity_sheet`/`story_logline` move between runs (now recorded in the dump). One run per prompt revision: allocation compliance is deterministic, but sentence length (41.2–45.9자) and WPM (146.9–158.5) vary across the three runs by the amounts shown.

