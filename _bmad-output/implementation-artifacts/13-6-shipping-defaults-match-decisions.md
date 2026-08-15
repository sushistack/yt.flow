---
story_key: 13-6-shipping-defaults-match-decisions
story_id: "13.6"
epic: "Epic 13: 품질 관측 & 게이트 성숙 — 조용한 실패 표면화 + 시각 평가 축"
created: 2026-08-15
source_status_before: backlog
baseline_commit: 4769608b4b1c05b7129ed716f087e22fdcb15495
---

# Story 13.6: 결정과 출하 기본값의 표류를 드러낸다

Status: draft

## Story

As Jay,
I want a decision I made about how videos should look or sound to be visible in the code that ships, and any gap between "decided" and "default" to be listed rather than discovered in a finished video,
so that I stop watching a render and asking why a change I approved weeks ago is not in it.

## Context

On 2026-08-15 Jay reviewed the E2E output of run `e5ed4b3a` and named four things as decided-but-apparently-not-applied. Three of them were real, and all three had the same shape — **the feature was built, reviewed and merged, and then sat behind a default that nothing ever flipped**:

| 결정 | 실제 출하값 | 어디에 |
|---|---|---|
| 떨림 없애기 | `camera_noise_enabled = True` | 코드 기본값 |
| 카드 얹기 대신 LLM 재합성 | `shot_recompose_enabled = False` | 코드 기본값 |
| 클론 음성 | `qwen_tts_clone_enabled = False` | **`.env`** |

The voice case is the sharpest: Story 5.24 registered the clone voice and `.env` already carried a working `YTFLOW_QWEN_TTS_CLONE_VOICE_ID`. Everything was in place except one boolean, and the run shipped the stock `Cherry` voice. Nothing anywhere reported that a registered clone voice was going unused.

Two of the three were then flipped on 2026-08-15 — **in `.env` only**. That is the same trap one layer down: a fresh checkout, a different box, or a `.env` divergence silently reverts a judged decision, and the next E2E surprise is identical to this one.

### Why this belongs to Epic 13

The epic's premise is silent success masquerade. A decision that does not reach the shipping default is a *silent no-op*: the pipeline reports success, the gates are green, the warnings list is empty, and the artifact simply does not contain the thing that was approved. It is the same category as 13.1's quiet degradations, one level above the code.

This story is deliberately **not** "flip these three booleans". Flipping them is a one-line edit that belongs to whichever story owns each feature (10.1e owns recompose; the motion/voice verdicts follow Jay's review of the 2026-08-15 rebuild). What is missing is the *mechanism* that makes the gap visible.

## Acceptance Criteria

1. **Decision-bearing settings are declared as such.** A feature flag whose value encodes a product judgement (motion on/off, voice source, compositing strategy, guard budgets) is distinguishable in code from an operational knob (timeouts, poll intervals, paths). The declaration carries: the deciding story, the date, and the decided value.
2. **A drift report exists and is runnable in one command.** It lists every decision-bearing setting whose **effective value differs from the decided value**, and separately every one whose effective value comes from `.env` rather than the code default. Empty output is the healthy state. This is a reporting tool, not a gate — it must never fail a run.
3. **The report is honest about where the value came from.** `.env` beating a code default is already a recorded hazard in this repo (`gotcha_env-file-beats-code-default`: a stale `YTFLOW_*` pin silently re-applied an old value). Given a setting whose effective value is supplied by `.env`, Then the report names `.env` as the source, even when the value happens to match the decision.
4. **A run records which decisions it shipped under.** The per-render provenance sidecar added by Story 13.3 already records workflow hash, resolved nodes and environment snapshot; extend the same idea so a finished video can answer "was the shake on?" from an artifact rather than from memory. Additive only — Story 13.3's AC8 rule stands: `_existing_complete_shot` compares exactly three keys and provenance must never enter that comparison, or every setting change re-renders 155 backgrounds.
5. **The three known gaps are recorded, not silently closed.** This story does not flip `camera_noise_enabled`, `qwen_tts_clone_enabled` or `shot_recompose_enabled`. It makes each one appear in the drift report with its deciding story, so closing them is a visible act.
6. **Scope discipline.** No new dependency. No new config field for the mechanism itself. Do not build a UI for this — a command and a report are the whole requirement.
7. **Tests.** A setting decided ON but defaulting OFF appears in the report; a matching setting does not; a value supplied by `.env` is reported as env-sourced even when it matches. The report tolerates a setting whose decision metadata is absent (the migration is incremental) without crashing.

## Tasks / Subtasks

- [ ] **Task 1 — Classify (AC: 1)**
  - [ ] Walk `config.py` and mark decision-bearing fields. Candidates observed 2026-08-15: `camera_noise_enabled`, `parallax_enabled`, `post_fx_enabled`, `shot_recompose_enabled`, `stock_plate_substitution_enabled`, `background_person_guard_attempts`, `composite_harmonization_tier`, `depth_placement_enabled`, `pose_guide_conditioning_enabled`, `qwen_tts_clone_enabled`, `qwen_tts_voice`.
  - [ ] Several already carry a dated verdict in a comment (`shot_recompose_enabled` has a full one; `pose_guide_conditioning_enabled` records its 2026-08-14 flip). Harvest those rather than re-deciding — the prose is the source.
- [ ] **Task 2 — Drift report (AC: 2, 3, 7)**
- [ ] **Task 3 — Provenance of decisions (AC: 4)** — mind AC8 of 13.3.
- [ ] **Task 4 — Record the three known gaps (AC: 5)**
- [ ] **Task 5 — Docs** — where the report is run and what to do with a non-empty result.

## Dev Notes

### Traps

1. **`Settings()` does not tell you where a value came from.** Pydantic resolves env over default silently. Determining the source requires comparing against the field default explicitly — that is the whole content of AC3.
2. **Do not turn this into a gate.** A failing build because a flag is off would be worse than the disease: half these flags are legitimately off pending live evidence (`shot_recompose_enabled` has three recorded reasons). Report, do not enforce.
3. **Do not re-litigate the decisions.** Several off-by-default flags are off *on purpose* and say so in their comments. The story's job is to surface the delta, not to argue with it.
4. **`qwen_tts_voice` is coupled to content language** (`config.py` comment) — it is decision-bearing but not a boolean. The classification must survive non-boolean settings.

### Files

**UPDATE**
- [src/yt_flow/config.py](../../src/yt_flow/config.py) — classification metadata; verdict comments already present at ~194 (`pose_guide_conditioning_enabled`) and ~293 (`shot_recompose_enabled`) are the model.
- `scripts/` — the report command.
- Provenance touchpoint in `src/yt_flow/pipeline/nodes/image.py` (13.3's `_build_provenance`).

### References

- [Source: _bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md] — the epic's surfacing pattern
- [Source: _bmad-output/implementation-artifacts/13-3-comfyui-workflow-ops-hardening.md] — provenance shape and the AC8 resume rule
- Project memory: `gotcha_env-file-beats-code-default`, `project_e2e-iteration3-done`
- [Source: src/yt_flow/config.py#L293-307] — a well-formed recorded verdict, for the metadata shape

## Dev Agent Record
