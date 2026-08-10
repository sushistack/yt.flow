---
title: 'Story 10.4 — Image/narration semantic match (findings 2·4·7·9·16)'
type: 'feature'
created: '2026-08-10'
status: 'done'
baseline_revision: '3869f95'
review_loop_iteration: 1
followup_review_recommended: true
context: []
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `visual_breakdown` requires every `image_prompt` to be atmospheric, tactile and background-only, but never requires it to render the sentence's **event** (who / what / result) — and nothing in the pipeline measures whether a rendered frame reads as the sentence it illustrates. That is the whole of Jay's findings 2·4·7·9·16 ("무슨 배경인지 모르는 배경이 많음", "나레이션과 전혀 맞지 않는 이미지", "도입부 이미지도 의미를 모르겠음"): shot `S00100` illustrates "손이 닿는 순간, 그는 죽었습니다" with an extreme close-up of a fluid drop on concrete — beautiful texture, no event.

**Root cause, measured (iteration 1):** the pipeline enforces a **1:1 sentence↔shot bijection** — the prompt orders "exactly one `VisualShot` per sentence", and `visual_breakdown_step.parse` rejects anything else. A sentence with no visual content is therefore *forced* to own a frame, and the model invents an unrelated one: `S00303` "이 방에 병이 가득하오" and `S00708` "이게 에스씨피 재단입니다" both scored `match: 1`. No wording of the prompt can fix this while the parser demands a bijection. The prompt's YAML contract already carries `sentence_end` — the parser has simply been ignoring it.

**Approach:** Replace the bijection with an **ordered cover**: a shot may span several consecutive sentences, and several consecutive shots may split one sentence. Then re-measure with the same axis, paired by sentence over the whole 66-sentence run rather than a 15-shot slate.

## Boundaries & Constraints

**Always:**
- The blind caption call runs **first and without the sentence**. Showing a VLM the sentence before asking "does this match" produces confirmation, not measurement — that anchoring control is the axis's whole claim to being evidence.
- **Every sentence stays covered.** The ordered cover may merge or split, never drop: sentence 1..N each belong to at least one shot, shot ranges are non-decreasing, and `sentence_start <= sentence_end`. A gap is a parse failure, not a warning — subtitles and shot cuts are derived from this cover.
- Both A/B legs are rendered in one harness run with the same workflow JSON, same sampler settings, and scored by the same script with the same model. Because the cover changes shot counts, the two legs are **paired by sentence**, not by shot slot: each sentence's score is that of the shot covering it.
- Reuse the DashScope Qwen-VL path already wired (`settings.character_vision_*`, the call shape in `services/vision_check.py` and `scripts/score_composites.py`). No new dependency, no new provider, no new config knob.
- Every number recorded carries its provenance: frame source, model, verbatim judge prompt, per-shot rows, and a one-command re-derivation (`gotcha_a-measurement-without-its-sample-band`).
- Prompt edits are repo-file-first, then `uv run python scripts/migrate_prompts.py --label production --source prompts` with its output saved as evidence. DEV MODE: no A/B promotion gate, no golden set.
- No negative-prompt string anywhere in the repo gains a term (`gotcha_negative-prompt-overstuffing`).

**Block If:**
- Pass B's paired result is **not** a win under the pre-registered rule (below) → do not seed to production, leave the prompt file reverted, HALT `blocked` with the paired table as evidence. Code changes stay on disk either way; only the runtime prompt is gated.
- ComfyUI or `YTFLOW_CHARACTER_VISION_API_KEY` is unavailable → HALT `blocked`. This story cannot close on a green test suite; it closes on live frames.

**Never:**
- **No runtime regeneration guard on a low semantic score.** Re-rendering the same `image_prompt` on a new seed cannot put an event into a frame whose prompt never described one — that is the structural difference from Story 10.2, where the prompt was clean and the sampler drew a person. Deferred, with the evidence that would justify a scenario-layer repair instead.
- No new axis wired into `eval_service.AXES` / `AxisScores` / `determine_winner` / the Langfuse judge rubric. That is Story 13.2 and it touches the frozen A/B promotion gate (6.12). This story writes the recommendation, not the wiring.
- **No new field on `ShotData` / `SceneState`, no checkpoint schema change.** `sentence_indices` is already a `list[int]` and `sentence_end` is already in the YAML output contract — the cover is expressed with what exists. A pre-cover checkpoint whose every shot has a one-element `sentence_indices` must keep deserializing and rendering identically.
- No unbounded fan-out. The cover's shot count per scene stays within a stated bound of the sentence count — an ordered cover with no ceiling lets one scene mint 40 renders.
- No regex or token scrub over `image_prompt` (`gotcha_person-token-regex-is-unusable-on-image-prompt`; 10.2 measured that layer wrong on 27/313 real prompts and deleted it).
- Do not re-render, move, or overwrite anything under `workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/` — it is the preserved baseline Jay watched.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal shot | frame PNG + its Korean sentence(s) | Two rows recorded: blind (`place`, `event`, `readable` **boolean**) then match (`match` 1–5, `evidence`, `missing`). Blind call carries no sentence | No error expected |
| Multi-sentence shot | `sentence_indices` covers >1 sentence | Sentences joined in order and scored once | — |
| Cover: shot spans sentences 3–5 | `sentence_start: 3, sentence_end: 5` | `sentence_indices == [2,3,4]`; `cast` is the **union** over those sentences, deduped by `card_key`, first occurrence's `position`/`depth` kept | — |
| Cover: two shots split sentence 4 | two consecutive shots both `sentence_start: 4, sentence_end: 4` | Both survive `plan_shot_clips`; sentence 4's window is divided among them in order, and total scene coverage is unchanged | — |
| Cover: sentence uncovered | shot ranges skip sentence 6 | `parse` raises with the missing indices named; the stage's one corrective retry feeds it back via `parse_error` | Second failure propagates as today |
| Cover: ranges out of order or inverted | `sentence_end < sentence_start`, or shot j+1 starts before shot j | `parse` raises naming the offending shot | As above |
| Pre-cover checkpoint | every shot has one-element `sentence_indices` | `plan_shot_clips` returns byte-identical clips to pre-10.4 | — |
| Frame missing or < 1 KB | `image_path` points at nothing | Row recorded with `skipped` + reason; not scored; counted in the summary | Never raises; script exits non-zero |
| Prose / fenced / non-JSON reply | Qwen-VL prefaces JSON with commentary | Outermost `{`…`}` brace slice (`label_location_plates._parse_verdict` shape), one retry, then the row is marked `error` | Script exits non-zero |
| Score not an int in 1..5 | `"match": "high"` or `true` | Row marked `error`; never coerced (`bool` rejected as an `int` subtype) | As above |
| `readable` not a boolean | `"readable": "yes"` | Row marked `error`; never coerced | As above |
| Scene 1, first shot | `scene_num == 1 and shot is shots[0]` | Row flagged `hook: true`, judged against the hook bar (`readable` true and `match >= 4`), reported on its own summary line | — |
| `--reps N` | N > 1 | Each question sampled N times; the **median** int is the row's score and the **majority** the boolean, all samples kept | A rep that errors is dropped; < 2 usable reps → row marked `error` |
| `--frames shots` cross-check | `workspace/<run>/shots/<base>.mp4` exists | Mid-frame extracted with ffmpeg; `frame_source` recorded per row | Missing mp4 → that row is skipped with a reason |

</intent-contract>

## Code Map

- `prompts/scenario/visual_breakdown.md` -- the runtime prompt. `:5` "Your job is NOT to literally illustrate each sentence" is the direct licence for the failure; slot 3 (`### image_prompt Structure (8 Slots)`, "Action, pose, or state") is where the event requirement belongs; `### Pre-Output Self-Check (MANDATORY)` is the checklist. The negative-prompt contract and the background-only rule are **frozen** (10.2). Runtime reads Langfuse, not this file.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `:1854` `visual_breakdown_step` (injected `call_llm`, prompt variables, `parse` closure); `:963` `_call_stage` fetches via `prompt_service.get_prompt` — **that is the monkeypatch seam** the A/B harness pins each leg to a repo-file text with; `:579` `split_sentences`; `:2422` `build_scenes` (`sentence_indices`, `shot_id = S{scene:03d}{i:02d}`, empty-prompt merge at `:2456`); `:818` `_validate_retention_outline` is Story 12.1's precedent for "the LLM output is checked, not trusted".
- `src/yt_flow/pipeline/nodes/scenario.py:429` -- the only production caller; visual_breakdown runs on `_call_deepseek`.
- `src/yt_flow/pipeline/nodes/shot_timing.py:33` `plan_shot_clips` -- derives each shot's clip window from `sentence_indices` + `subtitle.sentence_windows`. `:63-70` already handles many-sentences→one-shot (`windows[min][0]`..`windows[max][1]`); what breaks is one-sentence→many-shots — identical windows, then `:78-80` sets the earlier clip's end to the later's start (duration 0) and `_merge_short_clips` deletes it. The fix is a start-offset, not a rewrite.
- `src/yt_flow/services/run_service.py:100` -- passes `sentence_indices` straight to the stage-artifact API; a longer list needs no change there, but the UI reads it.
- `prompts/scenario/structure.md` -- 12.1's `event: {who, what, consequence}` block + "❌ 형용사/의도 서술 금지". The visual-layer edit is the same transition; copy the *shape* of the requirement, not the prose.
- `src/yt_flow/pipeline/nodes/image.py` -- `:141` `_shot_seed` (the A/B's seed source), `:169` `_inject_prompts`, `:195` `_shot_base`, `:102` `BG_NEGATIVE_SUFFIX` (frozen), `:136` `_effective_negative_prompt`.
- `scripts/score_composites.py` -- the closest existing analogue: module-constant prompt, `_parse`/`fail_reason`/`score_frame`, `extract_frames` (`:125` ffprobe + `-ss t -frames:v 1` inset from both ends), `--json` report, exit 1 gates a live task. Its docstring records qwen-vl-plus's measured ceiling.
- `scripts/label_location_plates.py:69` `_parse_verdict` -- the brace-slice parse to mirror. `services/vision_check.py:66` -- the DashScope call shape (endpoint, `temperature: 0`, data-URL content list).
- `src/yt_flow/services/eval_service.py:444` `_load_state` -- reads a run's `PipelineState` from the LangGraph checkpoint; requires `scenes` + `scp_text`. Run `8a9a288b-800f-4c73-88a2-25ae6b5a4d7d` has 46 checkpoints, 9 scenes, 66 shots, SCP-049.
- `tests/test_score_composites.py` -- the script-test convention: `importlib` load from path, fake the `httpx` seam, assert the decision rule directly.
- `_bmad-output/implementation-artifacts/10-2-live-validation/`, `10-3-live-validation/` -- the house style for the new evidence dir (docstring stating what is real vs faked, `__file__`-anchored paths, pinned source run as a module constant, JSON log per arm, README with re-derive block + measurement tables + "what this sample does NOT say").

## Tasks & Acceptance

**Execution:**
- [ ] `scripts/score_shot_narration.py` -- replace the `legible` 1--5 score with a **boolean `readable`** (can a viewer say where this is and what happened, from this frame alone). The Likert slot was dead — 66 frames produced `{4:46, 5:20}`, nothing below 4 — while the *same replies* wrote `event: "unclear"` on 9/66. Ask for the discrete value the model already volunteers. `MIN_LEGIBLE`/`MIN_LEGIBLE_HOOK` become `readable is True`; `match` and its thresholds are unchanged.
- [ ] `scripts/score_shot_narration.py` -- add `--pair-by sentence`: emit one row per **sentence** (the covering shot's verdict) alongside the per-shot rows, so two legs with different shot counts are still comparable. Also carry `n_shots` and `sentences_per_shot` into the summary.
- [ ] `tests/test_score_shot_narration.py` -- update for the boolean (non-boolean `readable` is an error, never coerced; majority vote under `--reps`), and add the sentence-paired emission incl. a shot covering 3 sentences and two shots splitting one.
- [ ] `prompts/scenario/visual_breakdown.md` -- replace the 1:1 rule with the **ordered cover** contract: a shot may span consecutive sentences (`sentence_start <= sentence_end`), consecutive shots may split one sentence, every sentence must be covered, ranges never move backwards, and shot count per scene stays within a stated bound. State plainly when to merge (a sentence with no visual content of its own — "이게 SCP 재단입니다") and when to split (one sentence carrying two distinct beats). Fold in the iteration-1 event/hook wording preserved at `10-4-live-validation/prompt_new.md` — do not re-derive it. Update the Output Format example and the Pre-Output Self-Check.
- [ ] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `visual_breakdown_step.parse`: replace the bijection (`len(shots) == len(sentences)` + `sorted(starts) == [1..N]`) with cover validation — every sentence covered, ranges non-decreasing and non-inverted, count within bound — raising with the offending indices named so the existing one corrective retry can act on it. `shot["cast"]` becomes the deduped union of `cast_by_sentence` over the shot's range (first occurrence's `position`/`depth` wins), replacing the single-sentence lookup at `:1888`.
- [ ] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `build_scenes`: `sentence_indices = list(range(sentence_start - 1, sentence_end))` instead of the single index at `:2468`. Keep the empty-`image_prompt` merge and the leading-empty fallback exactly as they are, and keep the three deterministic repairers (`_enforce_camera_variety`, `_suppress_cast_on_no_figure_framing`, `_enforce_cast_diversity`) in their load-bearing order.
- [ ] `src/yt_flow/pipeline/nodes/shot_timing.py` -- `plan_shot_clips`: today two shots claiming the same sentence produce identical windows and one is silently merged away. Offset each shot's **start** within its first sentence's window by its share position among the shots starting on that sentence; the existing "gaps attach to the preceding shot" loop then derives every end unchanged. A scene where each sentence starts exactly one shot must produce byte-identical clips to pre-10.4.
- [ ] `tests/pipeline/nodes/test_scenario_chain.py` + `tests/pipeline/nodes/test_shot_timing.py` -- every cover row of the I/O matrix: span, split, uncovered sentence, inverted/backwards range, over-bound count, cast union dedup, and the pre-cover-checkpoint regression (one-element `sentence_indices` → identical clips).
- [ ] `_bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py` -- re-score the **preserved** 66 baseline frames with the boolean instrument into `baseline_v2.json` (do not re-render; `baseline.json` stays as the iteration-1 record). Report how many frames the boolean calls unreadable against the 9/66 `event: "unclear"` the Likert version buried.
- [ ] `_bmad-output/implementation-artifacts/10-4-live-validation/run_ab.py` -- PASS B, properly powered. Both legs over **all 9 scenes / 66 sentences** of `8a9a288b-800f-4c73-88a2-25ae6b5a4d7d`: leg `old` = bijection prompt + bijection parser (`git show 3869f95:`), leg `new` = cover prompt + cover parser. Render every leg's shots, score with `--pair-by sentence`, `--reps 1` (n=66 replaces repetition), and report the **paired** mean Δ with a bootstrap 95% CI plus the shot-count change per scene. Writes `ab2_old.json`, `ab2_new.json`, `ab2_result.json`.
- [ ] `scripts/migrate_prompts.py` -- run `--label production --source prompts` **only if** the win rule holds, saving output to `10-4-live-validation/migrate_prompts.txt`.
- [ ] `_bmad-output/implementation-artifacts/10-4-live-validation/README.md` -- extend, do not rewrite: keep the iteration-1 baseline section as the pre-change record, add the instrument change and what it recovered, the cover contract, the paired result with its CI and the rule quoted above it, the shot-count deltas, the surviving confounds, and the Story 13.2 judgment.
- [ ] `_bmad-output/planning-artifacts/epics.md` -- update the Story 10.4 entry to the cover finding and its measured result.

**Acceptance Criteria:**
- Given the pre-registered win rule — *the paired mean Δ `match` over the 66 sentences is positive and its bootstrap 95% CI excludes 0; the count of unreadable frames does not increase; and the hook shot is `readable` with `match >= 4`* — when pass B completes, then the README quotes it verbatim above the result and the prompt is seeded to `production` if and only if all three hold.
- Given the run's 66 sentences, when either leg's cover is inspected, then every sentence is covered by at least one shot and no shot range is inverted or moves backwards — verified from the emitted JSON, not asserted.
- Given the four sentences that scored `match <= 2` at baseline (`S00105`, `S00303`, `S00708`, `S00503`), when the new leg's cover is inspected, then the README states for each whether it was merged into a neighbour, split, or left alone, and what it scored — this is the specific prediction the root-cause claim makes and it must be checked against, not around.
- Given a pre-cover checkpoint (every shot one sentence), when `plan_shot_clips` runs, then the clip plan is identical to pre-10.4 — an old run must still render.
- Given the whole change set, when `git diff 3869f95` is inspected, then no negative-prompt string gained a term, no field was added to `ShotData`/`SceneState`, and `src/yt_flow/` changes are confined to `scenario_chain.py` and `shot_timing.py`.
- Given the recorded evidence, when the README states a conclusion, then it states the sample size, the instrument's own noise floor from iteration 1 (same-prompt control sd 1.87), and the confounds that survive — including the 11/66 rows that dock a frame for an absent composited person.

## Spec Change Log

### 2026-08-10 — iteration 1 → 2 (Jay unblocks; the lever changes)

**Triggering findings.** Iteration 1 built the axis, measured the baseline honestly, and ran a prompt A/B that landed inside its own noise floor (effect −0.333 against a same-prompt control of sd 1.87 at n=15). Jay answered the three blocking questions: (1) fix the experiment properly rather than rerun it; (2) replace the dead `legible` Likert; (3) **"한 대본 문장에 여러 이미지가 있을 수 있고, 한 이미지에 여러 대본 문장셋이 매핑될 수 있다"** — the 1:1 sentence↔shot constraint is the defect, and it has been his standing position.

**Why (3) is the real lever, confirmed by iteration 1's own data.** The worst-scoring rows are sentences with nothing to render: `S00303` "이 방에 병이 가득하오"(match 1), `S00708` "이게 에스씨피 재단입니다"(match 1), `S00204` "아주 협조적으로요"(match 3). Under 1:1 each is *forced* to own a frame, so the model invents an unrelated one. Under an ordered cover those sentences fold into a neighbour and the defect disappears by construction — no prompt wording can achieve that while the parser enforces a bijection.

**Amended.** The prompt-wording lever is demoted to a companion of the mapping change (the iteration-1 text is preserved at `10-4-live-validation/prompt_new.md` and folded in, not re-derived). The new scope is the N:M ordered cover — prompt contract, parser validation, `build_scenes`, and the shot-timing split — plus the boolean instrument and a properly powered paired experiment. The 15-shot slate is replaced by the full 66-sentence run: at sd 1.87, n=66 gives SE ≈ 0.23, so the pre-registered bar becomes a paired mean Δ whose 95% CI excludes 0. `--reps 3` is dropped — sample size now does the work repetition was doing.

**Known-bad state avoided.** Rerunning the same underpowered 15-shot A/B on a reworded prompt, concluding from it, and shipping a prompt edit whose measured effect is smaller than the instrument's own noise.

**KEEP (must survive re-derivation).**
- The two-call axis shape: blind first with the sentence withheld, then match. The anchoring control is the measurement's whole claim to being evidence.
- `baseline.json` and its 66 rows — the pre-change measurement. Do not re-render those frames; re-score them if the instrument changes, into a NEW file.
- The recorded confounds: 11/66 `missing` texts docking for absent composited people, and 28/66 blind captions reading a body inside the plate.
- `run_ab.py`'s pairing/rendering machinery and `prompt_old.md`/`prompt_new.md`.
- Exit codes that fail on any skipped or errored row.

## Review Triage Log

## Design Notes

**Why the timing fix is six lines, not a rewrite.** `plan_shot_clips` already derives every clip *end* from the next clip's start, and stretches the first/last to the scene. So only the *start* needs to know about sharing: offset shot j's start inside its first sentence's window by its share position among the shots that start on that sentence.

```
share_idx = how many earlier shots start on this same sentence
share_n   = how many shots in total start on it          # 1 in every pre-cover run
w0, w1    = windows[min(idxs)]
start     = w0 + (w1 - w0) * share_idx / share_n         # == w0 when share_n == 1
```
`share_n == 1` reproduces today's arithmetic exactly, which is why the pre-cover regression test is the real check on this change.

**Why the cover is the fix and the wording was not.** Iteration 1's four worst rows are sentences with no visual content of their own. Under a bijection each must own a frame, so the model fabricates one; under a cover it folds into its neighbour and never gets rendered as a claim. That is a structural remedy, and it makes a falsifiable prediction (AC3) — which is the point of doing it this way round rather than rewording and hoping.

**Why two calls and not one.** Ask a VLM "does this image express this sentence" while showing it the sentence, and it will find a way to say yes — the same failure mode that made three OPA judgment signals worthless in 10.1c ("the question itself was wrong"). The blind caption is the control: it is the frame's own testimony about what it depicts, taken before the sentence exists. Finding 2 is then answerable directly from the blind rows (`event: "unclear"`), independently of any match score.

**Why the lever is the prompt and not a seed ladder.** 10.2's guard works because a clean prompt plus a bad sample is fixable by resampling. Here the prompt itself is the defect — "extreme close-up of a concrete floor, a single drop of clear fluid striking dust" has no event to render, and every seed will faithfully render no event. A regeneration ladder would triple image-stage cost to re-roll the same emptiness.

**Why the plate and not the composited frame is the primary measurement.** `image_prompt` controls the background only; cards are composited later. Judging composited frames would fold Epic 8's placement quality into a score meant to isolate the prompt. The `--frames shots` cross-check exists precisely so this choice is measured rather than assumed.

**Golden shape of the target transition** (the prompt edit's intent, not text to paste):

```
sentence: "두 손이 맞닿자, 그는 그 자리에서 쓰러졌습니다."
BAD  (as built): extreme close-up of a concrete floor, a single drop of clear fluid
                 striking dust and spreading into a dark stain, ...
GOOD (event visible): low-angle wide of the examination floor where a body has just
                 gone down — the black medical bag knocked open, instruments scattered
                 in a spray away from an empty impact hollow in the dust, one glove
                 still rocking, ...
```
The person stays out of the prose (10.2's rule is intact); what changes is that the *result of the event* is now the subject of the frame.

## Verification

**Commands:**
- `uv run pytest tests/test_score_shot_narration.py tests/pipeline/nodes/test_shot_timing.py tests/pipeline/nodes/test_scenario_chain.py -q` -- expected: all pass
- `uv run pytest -q` -- expected: no new failures vs baseline `3869f95` (`test_services_does_not_import_api_or_pipeline` fails at baseline too — pre-existing, Story 10.1c)
- `uv run ruff check scripts tests` -- expected: clean
- `git diff 3869f95 --stat -- src/yt_flow` -- expected: only `pipeline/nodes/scenario_chain.py` and `pipeline/nodes/shot_timing.py`
- `git diff 3869f95 -- src/yt_flow/domain/state.py` -- expected: **empty** (no schema change)
- `git diff 3869f95 -- prompts scripts | grep -E '^\+' | grep -iE 'negative_prompt|person, people|silhouette'` -- expected: no line adding a negative-prompt term
- `uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py --rescore` -- expected: `baseline_v2.json`, 66 rows, `baseline.json` untouched
- `uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_ab.py` -- expected: both legs rendered over all 9 scenes and scored, `ab2_result.json` carrying the paired mean Δ and its bootstrap CI

**Manual checks:**
- `10-4-live-validation/README.md` states the win rule before its result, and its conclusion matches the JSON rows rather than exceeding them.
- The pair JPEGs are recognisably the same shot slot (same seed) with different content.

## Auto Run Result

Status: blocked

**Blocking condition:** pass B did not satisfy the pre-registered win rule. Per this spec's Block If, the prompt edit was **reverted and never seeded** — `prompts/scenario/visual_breakdown.md` is byte-identical to baseline `3869f95`, Langfuse `scenario/visual_breakdown` is still v14, and `migrate_prompts.txt` is deliberately absent. The decision to accept a null result, widen the slate, or change the instrument is not one this workflow can make unattended.

**What shipped (uncommitted).** The judgment axis and its measurements, which is what this story's closing condition asked for.
- [`scripts/score_shot_narration.py`](../../scripts/score_shot_narration.py) — two DashScope Qwen-VL calls per shot: a **blind** call (frame only, sentence withheld → `place`/`event`/`legible`) then a **match** call (frame + its sentence → `match`/`evidence`/`missing`). Hook flagging for scene 1 shot 0, `--reps` median, `--frames images|shots`, exits 1 on any skipped or errored row.
- [`tests/test_score_shot_narration.py`](../../tests/test_score_shot_narration.py) — 25 offline tests at the `httpx` seam, including the assertion that the blind request body carries no narration text.
- [`10-4-live-validation/`](10-4-live-validation/) — `run_baseline.py`, `run_ab.py`, 8 JSON reports, 30 renders, 15 pair JPEGs, both prompt texts, and a 423-line README.
- [`epics.md`](../planning-artifacts/epics.md) — the Story 10.4 entry now carries the measured numbers instead of the hypothesis.

**PASS A — 66/66 frames of the run Jay watched, 0 skipped, 0 errored.** Failure rate 7.6% (5/66), mean `match` 3.606, mean `legible` 4.303.
- **Finding 4 reproduces.** 4 shots below `MIN_MATCH`: `S00105`(1), `S00303`(1), `S00708`(1), `S00503`(2). `match` distribution `{1:3, 2:1, 3:27, 4:23, 5:12}`.
- **Finding 2 does not reproduce as a score — the `legible` axis as designed is dead.** 0/66 below `MIN_LEGIBLE`; the distribution is `{4:46, 5:20}` with no observation under 4 across 66 frames. Yet **9/66 (13.6%)** of the same blind replies wrote `event: "unclear"` while scoring that frame `legible: 4` — the model contradicts its own rubric in one reply. A different question is needed, not a different threshold.
- **Hook `S00100`** — `legible` 4 / `match` 3 → fails the 4/4 bar. The opening frame's blind `place` reading was "a cracked stone corridor" against "손이 닿는 순간, 그는 죽었습니다".
- **Confound, measured not assumed:** despite both judge prompts stating that people are composited from separate cards, **11/66** `missing` texts still dock the frame for an absent person ("there is no visible sign of a person or their death"). The `match` score is partly measuring card absence.
- **Second-order finding (not this story's scope):** 28/66 (42%) blind captions read a body *inside the plate* — Story 10.2's findings 5·12 independently reproduced at population scale on a run where the guard was off.
- Cross-checks: rescoring 8 shots at `--reps 3` reproduced pass A **exactly 8/8**; the `--frames shots` composited cross-check moved **no** `match` on the 4 slate shots that have a per-shot clip (only 42/66 shots do).

**PASS B — 15 slots (scene 1 + scene 5) × 2 legs, same seed / workflow / negative prompt, `--reps 3`.**

| pre-registered clause | old | new | held |
|---|---:|---:|---|
| mean `match` does not decrease | 3.267 | 2.933 | ✗ |
| count below `MIN_MATCH` does not increase | 2 | 1 | ✓ |
| hook reaches `match ≥ 4` and `legible ≥ 4` | 5 / 4 | 3 / 4 | ✗ |

`won: false`. **The verdict is "no measurable effect", not "the new prompt is worse."** The baseline frames and the old leg were rendered from the same prompt version, so their delta is a pure same-prompt control: mean Δ `match` **−0.267**, mean |Δ| **1.47**, sd **1.87** — against an A/B effect of **−0.333**. The experiment sits inside its own noise floor at n=15. Also measured, as an untested hypothesis for why the added event clauses did not render: the new prompt made `image_prompt` 44% longer (121 vs 84 words).

**Verification.** `uv run pytest tests/test_score_shot_narration.py -q` → 25 passed. `uv run pytest -q` → 1 failed / 2574 passed; the one failure is `test_services_does_not_import_api_or_pipeline`, which fails identically at baseline `3869f95` (Story 10.1c's `recompose_service`). `uv run ruff check` → clean. `git diff 3869f95 --stat -- src/yt_flow` → **empty**; `-- prompts` → **empty**. No negative-prompt term added anywhere.

**What a follow-up needs to decide (the blocking questions).**
1. The instrument or the sample? A −0.333 effect against a 1.87 sd control needs either a much larger slate or a per-shot paired design, not a rerun of the same 15.
2. The `legible` question is wrong. The blind reply already knows the answer (`event: "unclear"` on 9/66) but the 1–5 score refuses to express it. Ask for the boolean the model is already volunteering.
3. Strip the card-absence confound from `match` before trusting it as a 13.2 axis — 11/66 rows are measuring the wrong thing.
4. Whether the prompt lever is right at all. Pass A's real spread is in `match`, and its worst rows (`S00303`, `S00708`) fail on sentences that have no visual content to render at all ("이 방에 병이 가득하오", "이게 SCP 재단입니다") — that is a scenario-layer sentence/shot pairing problem, not an `image_prompt` wording problem.

**Residual state.** ComfyUI was started detached (`setsid`) for pass B and is still running. Nothing was committed.

### Iteration 2 (2026-08-10) — the mapping hypothesis was tested, and it lost

Status: blocked. Same gate as iteration 1 and for the same reason — pass B is not a win, so `prompts/scenario/visual_breakdown.md` stays reverted and unseeded (Langfuse `scenario/visual_breakdown` still v14, `migrate_prompts.txt` absent). **The code stays on disk**; only the runtime prompt is gated.

**Instrument (Jay decision 2) — the boolean recovered a signal the Likert buried.** Same 66 preserved frames, same judge, same blind body, only the readability question changed: **12/66 (18.2%) unreadable** against the Likert's **0/66**. All 12 had been scored `legible: 4` while the *same reply* wrote `event: "unclear"`. `mean_match` moved 3.606 → 3.621, so this is a change of question, not of judge. 6 of the 12 also score `match >= 3` — finding 2 and finding 4 are genuinely orthogonal defects, as AC3 of iteration 1 required us to check.

**Cover (Jay decision 3) — implemented, exercised, and it does not move `match`.**
- Code: bijection → ordered cover in `visual_breakdown_step.parse` (+ `_cast_union`), range expansion in `build_scenes`, and the six-line start-offset in `plan_shot_clips` that stops a split sentence's earlier clip from being silently deleted. `ShotData`/`SceneState` unchanged; a pre-cover checkpoint renders identically (regression test).
- PASS B, all 9 scenes, paired by sentence, n=66: shot count 66 → 55 (**−16.7%**), 18/18 scene-legs with `uncovered: []`, `monotonic: true`, `inverted: []`. **Δ mean `match` = −0.152, bootstrap 95% CI [−0.394, +0.076]** → no measurable effect. `won: false`.
- **AC3's prediction failed 0/4.** All four target sentences were LEFT ALONE by the model — including `S00708` "이게 에스씨피 공사구-이입니다", whose sentence is quoted verbatim in the cover prompt as its first merge example. The model produced **11 merges, 0 splits**, and merged sentences (Δ −0.136) were indistinguishable from unmerged ones (Δ −0.159). At that point the hypothesis was *untested*, not refuted.

**Merge probe — the decisive test.** Rule fixed and written down before any score was read: *a sentence merges iff, read alone, it introduces no renderable visual referent (no place, no physical object/body/surface, no physical change/motion); it merges into the preceding sentence's shot.* Applied mechanically to all 16 sentences of scenes 3 and 7, it selected 5 merges — and independently picked out both AC3 targets. Both scenes obeyed the dictated cover exactly.

| arm | merged (n=5) | untouched, same scenes (n=11) |
|---|---:|---:|
| M1 — control frames, joined text, 0 renders | **0.000** (+0 / −0 / =5) | −0.182 |
| M2 — dictated cover, re-authored prompts, 11 renders | **+0.200** (+1 / −0 / =4) | **+0.182** |

M1 moved nothing on all five, and cost the host 2 points on one (scene 3 sentence 2 was a lone `match: 5` and became a 3 once its frame had to carry the merged sentence too — merging is not free). M2's +0.200 is indistinguishable from the +0.182 the *untouched* sentences of the same scenes gained, so the lift is whole-scene re-authoring, not merging; the single largest move (+2) is an unmerged sentence, and `S00708` went 3 → 3 → 3.

A validity check fell out of M1 for free: the 8 singleton spans fed the judge identical frames and identical text and reproduced the control **8/8 exactly** — `temperature: 0` is stable, so "Δ 0" means no change registered, not noise.

**Verdict: the sentence↔shot mapping is dead as a `match`-score lever.** The merges the root-cause claim wanted were hand-authored by a stated rule, obeyed, rendered, scored, and bought nothing. The cover code is worth keeping, but on **render cost and cut rhythm** (−16.7% renders) — not on semantic match. Stated limits: n=5 merged over 2 scenes at `--reps 1`; +0.200 sits inside pass B's per-sentence sd of 0.98; and `match` clusters hard at 3 (15/16 M1 rows unchanged), so the axis has poor resolution in exactly this band.

**What this leaves for findings 2·4·7·9·16.** Two levers this story measured but never pulled: the **12/66 unreadable** rate the boolean exposed, and the **11/66 card-absence confound** polluting `match` itself. Story 13.2 should wire `readable` as an axis and strip the confound before another run is spent on mapping.

**Verification.** `uv run pytest -q` → 1 failed / 2613 passed / 1 skipped; the failure is the pre-existing `test_services_does_not_import_api_or_pipeline` (Story 10.1c). `ruff` clean. `git diff 3869f95 --stat -- src/yt_flow` → only `pipeline/nodes/scenario_chain.py` (+95) and `pipeline/nodes/shot_timing.py` (+20). `-- src/yt_flow/domain/state.py` → empty. `-- prompts` → empty. No negative-prompt term added. `baseline.json` md5 unchanged (`705bd280…`); `ab2_old/` intact at 66 frames.

**Decision Jay owns.** Keep the cover code (uncommitted, green, justified by render cost) or drop it; and whether 13.2 picks up `readable` + the confound. ComfyUI is still running detached.

### Closing (2026-08-10, Jay) — `done`, and re-scoped from research

Jay's call: reporting "the lever did not work" is not a result — go find how the field solves this. Desk research was done and written up at [`technical-narration-image-semantic-alignment-2026-08-10.md`](../planning-artifacts/research/technical-narration-image-semantic-alignment-2026-08-10.md). Three things it changes:

1. **The 12 unreadable frames have a named, published cause.** Their prompts make an *absence* the subject (`open air`, `vast empty concrete floor`, `blank wall section`), and diffusion models cannot realise absence — "a room without a cat" yields a cat on 5/5 seeds, because the text encoder's correct representation of the negation does not transfer to pixels. So this was never a wording problem. Our own three rules collide to produce those prompts: background-only `image_prompt` + a sentence that is entirely about a person + a prompt section teaching negative space as craft. → **Story 10.4b**.
2. **The instrument is a generation behind.** VLM-Likert was superseded by QG/A decomposition — TIFA, then DSG (atomic propositions + a dependency graph that invalidates answers whose premises failed), and VQAScore (P("yes") for *"Does this figure show {text}?"*). DSG fixes both defects this story measured: the clustering at 3, and the 11/66 card-absence confound (person-propositions simply are not generated). → **Story 13.2, and it goes first** — running 10.4b against a score with no resolution would reproduce this round exactly.
3. **The cover was the right shape for the wrong stated reason.** Every current story-visualisation system (ViStoryBench, DreamStory, Dialogue Director, Narrative Graph Prompting) treats narration→shots as LLM shot *planning*, not per-sentence mapping. The narrow claim this story earned is "freeing the count does not by itself raise a semantic-match score" — measured with the instrument item 2 says to replace. The code stays.

**Provenance correction (found while auditing, recorded not fixed).** 51 of the 66 baseline frames are Story 10.1c's `recomposed/` re-creations from 2026-08-09, not the 2026-08-08 render Jay watched — `recompose_service` repoints `shot["image_path"]`. The recomposed subset scores worse (unreadable 20% vs 13%; blind reading "corridor" 57% vs 27%, n=15 control). Comparative results are unaffected (both A/B legs and the probe rendered fresh plates); the absolute baseline *label* was wrong and is corrected in the README's new §0 and in the `epics.md` entry.

**Delivered.** The axis (`scripts/score_shot_narration.py` + 43 tests), the boolean instrument that recovered 12/66 from a dead Likert, the N:M ordered cover (`scenario_chain.py`, `shot_timing.py` — including a real bug nobody had noticed: a split sentence's earlier clip was silently deleted), the evidence directory, and the research doc. The runtime prompt was never seeded and stays at `3869f95` / Langfuse v14 — the one gated artifact stayed gated.

**Follow-ups filed:** Story 10.4b (absence-as-subject) and the Story 13.2 instrument upgrade, both in `epics.md`. Order is 13.2 → 10.4b.
