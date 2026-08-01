---
created: 2026-08-01
baseline_commit: 6aa795abd6aa783df165c8d609d7b1040bfea2aa
story_key: 8-18-cast-decision-diversity-validator
story_id: "8.18"
epic: 8
previous_story: 8-13-derived-entity-card-on-demand
depends_on:
  - 8-12-cast-placement-scale-calibration  # the prompt rules this story now enforces in code
  - 8-10-cast-decision-split-call          # cast_decision stage whose output is validated
related:
  - 11-2-camera-motion-archetypes          # _enforce_camera_variety — the exact repair-validator pattern to clone
  - 6-7-yaml-syntax-only-repair-path       # deterministic-repair lineage (no LLM re-call)
  - 6-11-deterministic-yaml-freetext-normalization  # mark-targeted repair lesson: fix violating entries only, never rewrite siblings
workflow_decision: "Pure functions inside scenario_chain.py, hooked in build_scenes next to _enforce_camera_variety. No new service, no config knob, no prompt changes, no LLM re-call (ponytail: one implementation, no interface)."
evidence: "8.12 calibration moved position center 78%→16.8% but compliance is still prompt-obedience only — zero code enforcement of anti-repetition / stacking / camera_angle↔depth rules (epics.md Story 8.18, Jay 2026-07-12: 'AI 배치가 확률적/제어불가')."
---

# Story 8.18: cast_decision Output — Deterministic Placement-Diversity Validator

Status: done

## Story

As Jay,
I want the placement-diversity rules that cast_decision is *asked* to follow enforced by deterministic code repair,
so that composition quality no longer depends on how well the LLM obeyed the prompt on any given run — violations are fixed instantly, without an LLM re-call, on every run.

## Context — what exists, what's missing

8.12 (done, prompt-only) taught `prompts/scenario/cast_decision.md` a "Composition" section: rule-of-thirds default, anti-repetition across consecutive sentences, opposing-thirds for multi-cast, calibrated depth semantics. It measurably improved distributions (center 78%→16.8%). But nothing in code *checks* any of it — `parse_cast` (scenario_chain.py:210) only normalizes enum values per-entry; it has no cross-entry or cross-shot awareness. A run where the LLM regresses to center-stacking ships as-is.

The codebase already contains the exact pattern this story needs, built twice:

1. **`_enforce_camera_variety` (scenario_chain.py:167, Story 11.2 AC4)** — a pure function called from `build_scenes` (scenario_chain.py:1158) on the freshly built per-scene `shots` list. Adjacent-duplicate `camera_movement` is deterministically reassigned from a preference table, INFO-logged, no LLM re-call, mutates only the shot dicts build_scenes just created [AD-4]. **This is the template. Clone its shape, hook site, logging style, and test block.**
2. **`_repair_movement` (scenario_chain.py:124, Story 8.9)** — the compatibility-repair-table lineage: an invalid combination normalizes deterministically, never fails the scenario stage.

## Scope guard / Non-goals

- **No prompt changes.** cast_decision.md / visual_breakdown.md are `production` (8.12); the prompt keeps teaching the rules, this story adds the code backstop. Touching prompts would trigger PROMPT_POLICY — out of scope.
- **No new service, no config knob.** Pure functions inside `scenario_chain.py` (epics: "서비스 추출은 이 경우 불필요한 인터페이스"). Thresholds are module constants next to `_VALID_POSITIONS` (scenario_chain.py:50).
- **Never repair `camera_angle`.** For camera↔depth contradictions, repair the **depth side only**: `camera_angle` (= visual_breakdown's `camera_type`) is baked into the shot's generated-background framing via `image_prompt` and feeds entity angle selection (`character_service.py:1198` catalogue for `_select_entity_angles`). Changing it post-hoc desyncs text and pixels. Changing a cast member's `depth` only changes compositing scale/stacking (`video.py:182 _DEPTH_SCALE`) — safe.
- **Don't touch `camera_movement`** — 11.2's `_enforce_camera_variety` owns that axis; the two validators run side by side, each on its own fields.
- **Don't change `parse_cast` leniency** — per-entry normalization stays exactly as is; the new validator runs *after* it, cross-entry/cross-shot.
- **Mark-targeted repair only (6.11 lesson):** fix the violating member's field(s); never rewrite or reorder sibling members, other shots, or untouched fields. 6.11's spec-compliant whole-doc transform silently corrupted healthy sibling lines — do not repeat that shape.

## Acceptance Criteria

1. **New pure function `_enforce_cast_diversity(shots: list) -> None`** in `scenario_chain.py`, called from `build_scenes` for each scene right next to `_enforce_camera_variety(shots, mood)` (scenario_chain.py:1158), operating on the just-built shot dicts (post `parse_cast`, post empty-prompt merge — so "consecutive" means consecutive *on screen*). Mutates only those dicts [AD-4]. Never raises on any input (D1 philosophy: a violation degrades/repairs, it never fails the scenario stage).
2. **R1 — within-shot slot stacking ban:** two or more cast members in one shot sharing the same `position` → each later member (list order) is reassigned to a free slot, preferring the opposing third (`left`↔`right`) then `center`. With all 3 slots occupied by 4+ members, remaining members keep their slot (3-slot renderer limit — log at INFO and stop; do not invent sub-slots).
3. **R2 — consecutive-repeat cap:** for a given `card_key`, a run of **more than 2 consecutive shots** with the identical `(position, depth)` pair → the 3rd (and each subsequent violating) shot's member gets `position` reassigned to a deterministic different slot that also respects R1 occupancy. Threshold is a module constant (`_MAX_CONSECUTIVE_SAME_PLACEMENT = 2`); a single repeat stays legal because the prompt legitimately allows a continuous beat ("unless the character hasn't moved and the beat is one continuous shot"). Position-only reassignment — depth stays untouched here, deliberately (`# ponytail:` breaking the slot repetition suffices visually; repairing depth would fight the 8.12-calibrated "mostly mid" distribution and could newly violate R4).
4. **R3 — camera_angle↔depth contradiction repair** (only the two explicit "never" pairings from 8.12 AC3 / visual_breakdown.md:234-236, exactly as scoped there — the full agreement table was never a hard rule):
   - `camera_angle == "wide"` and dominant cast depth `near` (strict majority of members) → demote every `near` member to `mid`.
   - `camera_angle in ("close-up", "over-the-shoulder")` and the shot's cast is a lone `far` member → promote that member to `mid`.
   - `camera_angle` is `None` or any other value → no check (free-string tolerance; `parse_cast` never sees this field).
5. **Movement re-derivation invariant:** any member whose `position` was reassigned (R1 or R2) and who carries movement fields gets `movement_direction` re-derived via the existing `_repair_movement(movement_mode, movement_direction, new_position)` (scenario_chain.py:124) — parse_cast computed it against the *old* position (scenario_chain.py:240); skipping this re-derive can leave a degenerate `cross`/`enter`/`exit` direction (zero-amplitude cross). `movement_mode`/`movement_pace` unchanged.
6. **Determinism + idempotence:** same input → same output (no randomness, fixed iteration order, fixed slot-preference order); running the validator twice equals running it once. Each repair logs one INFO line naming shot_id, card_key, field, old→new value (mirror `_enforce_camera_variety`'s log shape, scenario_chain.py:189).
7. **Regression tests** in `tests/pipeline/nodes/test_scenario_chain.py`, as a block mirroring the `_enforce_camera_variety` block (test_scenario_chain.py:1943-1977):
   - the epics' mandated fake case: LLM emitted **all-identical values** (every shot, every member `center`/`mid`) → after repair, no R1/R2 violation remains;
   - each rule (R1, R2, R3) repaired in isolation;
   - determinism (two runs, equal results) and idempotence (second pass is a no-op);
   - valid, diverse sequences pass through **byte-identical** (no gratuitous mutation);
   - movement re-derive: a `cross` member whose direction matched its new position gets a non-degenerate direction after reassignment;
   - single-shot scene and empty-cast shots are harmless no-ops;
   - `build_scenes` integration: violations planted in raw visual_breakdown payloads come out repaired in the returned scenes.
8. **Existing suite stays green:** `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q` passes in full — in particular the parse_cast, `_repair_movement`, and `_enforce_camera_variety` tests are untouched and unaffected.

## Tasks / Subtasks

- [x] Task 1: Read `_enforce_camera_variety` + its test block fully; write `_enforce_cast_diversity` skeleton with the R1→R2→R3 pass order and INFO logging (AC: 1, 6)
  - [x] Subtask 1.1: Module constant `_MAX_CONSECUTIVE_SAME_PLACEMENT = 2` next to the `_VALID_*` constants
  - [x] Subtask 1.2: Rule order rationale in the docstring: R1 (intra-shot) first, then R2 (cross-shot, respecting R1's occupancy), R3 (depth) last so nothing reintroduces a stacking violation — implemented as R1→R3→R2; see Completion Notes (AC6 idempotence forces R2 after R3)
- [x] Task 2: R1 slot-stacking repair (AC: 2)
- [x] Task 3: R2 consecutive-repeat cap with run tracking per card_key (AC: 3)
- [x] Task 4: R3 camera↔depth two-pairing repair, depth side only (AC: 4)
- [x] Task 5: Movement `_repair_movement` re-derive on every position reassignment (AC: 5)
- [x] Task 6: Hook into `build_scenes` beside `_enforce_camera_variety` (AC: 1)
- [x] Task 7: Test block per AC 7; full-suite run per AC 8

## Dev Notes

### Hook site and data shapes

- `build_scenes` (scenario_chain.py:1098) builds each scene's `shots` as a list of `ShotData` TypedDicts; `cast` is `list[CastMember]` (domain/state.py:62 — `card_key`, `position: Literal["left","center","right"]`, `depth: Literal["near","mid","far"]`, `pose`, plus optional `pose_hint`/`motion_*`/`movement_*` keys). `camera_angle: str | None` comes from visual_breakdown's `camera_type` free string (scenario_chain.py:1147) — treat it as untrusted text, match only the exact values in AC 4.
- Empty-`image_prompt` sentences are merged into the previous shot *before* the validator runs (scenario_chain.py:1131-1139) — consecutive-shot semantics are therefore screen-truth, not sentence-truth. Do not move the hook earlier (e.g. into `cast_decision_step.parse`): sentence-level adjacency ≠ shot-level adjacency, and `camera_angle` doesn't exist yet at that stage (8.12 dev notes: cast_decision runs BEFORE visual_breakdown).
- Scene boundaries: like `_enforce_camera_variety`, do **not** check across scenes — 5.16's dip-to-black severs visual continuity (scenario_chain.py:179-181 documents this rationale; reuse it).

### What position/depth actually do downstream (don't promise more)

- `position` → 3-slot x anchor: `video.py:189 _POSITION_X_FRAC = {left: 1/3, center: 0.5, right: 2/3}`. It is a slot, not free x — repairs speak only in the 3-value vocabulary.
- `depth` → scale + stacking: `video.py:182 _DEPTH_SCALE = {near: 1.0, mid: 0.75, far: 0.55}`, consumed by `_character_scale_filter` (video.py:531). Depth changes are render-safe (no image regeneration involved).
- `camera_angle` → entity angle-selection catalogue (`character_service.py:1198`) and checkpoint serialization (`run_service.py:99`). This is why AC 4 repairs depth, never the angle.

### Architecture compliance

- **[AD-4]** validators mutate only the dicts `build_scenes` just created, never an input state object — `_enforce_camera_variety`'s docstring states this contract verbatim; repeat it.
- **D1 lesson / resolve_mood philosophy** (parse_cast docstring, scenario_chain.py:211-215): taxonomy violations degrade or repair; the scenario stage never fails because of them. The validator must be total — garbage in (missing keys, weird types) → skip that member/shot with a warning, never raise. Members are TypedDicts produced by `parse_cast`, so `position`/`depth`/`card_key` are guaranteed present post-parse; defensive `.get` is still cheap insurance for direct-call tests.
- **Ponytail:** one function + helpers, module constants, no config field in `config.py`, no new file. This story adds ~60-80 lines of validator + tests. If you find yourself writing a class or a new module, stop.

### Previous story intelligence

- **11.2 (`_enforce_camera_variety`, commit ce4bcef)** — reviewed clean with 0 fixes (rare); its shape is proven. Its test block (test_scenario_chain.py:1943-1977: property, determinism, single-shot-harmless, valid-untouched) is the required test skeleton.
- **8.12** — established the exact rule texts being enforced and their measured baselines (position center 16.8%/left 44.0%/right 39.2%; depth near 32%/mid 54.4%/far 13.6% on SCP-049 candidate run). The R3 "two explicit never-pairings only" scope comes from its review finding (8-12 story file, Review Findings: the programmatic check deliberately never covered the full agreement table — this story keeps that same honest scope).
- **6.11** — a spec-compliant whole-document transformation silently corrupted healthy sibling lines; the redesign was mark-targeted repair. Apply the same discipline: touch violating members' violating fields only, assert in tests that everything else is byte-identical.
- **8.13 (previous epic-8 story)** — no direct code overlap; its relevant habit: Task 0 = read the real code you're assuming about before writing new code (its AC6 "verify, don't assume" framing caught a wrong assumption). Same here: read `_enforce_camera_variety` and `_repair_movement` before writing.

### Git intelligence

Last 5 commits are all Epic 11 (11.1-11.4) touching `image.py`/`video.py`/`scenario_chain.py`/`character_motion.py` — `scenario_chain.py` is under active parallel churn (11.2 added lines 152-193 recently). **Concurrent-edit hazard**: if another 11.x session is live, coordinate on `scenario_chain.py` and expect `sprint-status.yaml` merge friction (recurring — 5-14/1-10/5-23 precedents; stage the story-status line surgically).

### Web research

Not applicable — zero new dependencies; the story is internal pattern reuse (stdlib + existing helpers only). No library/version decisions exist to research.

### Project Structure Notes

- Validator + constants: `src/yt_flow/pipeline/nodes/scenario_chain.py` (alongside `_enforce_camera_variety`, `_repair_movement`, `_VALID_*`).
- Tests: `tests/pipeline/nodes/test_scenario_chain.py` (append a `_enforce_cast_diversity` block after the camera-variety block).
- Worktree gotcha: run tests with `PYTHONPATH=$PWD/src` — the global editable install shadows worktree sources otherwise.
- No other files should change (except sprint-status.yaml on completion). If the implementation wants to touch `video.py`, `parse_cast`, prompts, or `config.py`, the scope guard above says no.

### References

- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md] — 2026-08-01 품질 전략 리서치: cast_decision 배치 다양성 결함(round-robin 편향)을 확정한 근거 문서 — 이 스토리의 발의 배경
- [Source: _bmad-output/planning-artifacts/epics.md#Story 8.18] — story mandate: deterministic repair, no LLM re-call, pure function in scenario_chain.py, fake all-same-value regression test
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:167-193] — `_enforce_camera_variety`, the pattern template (hook, logging, AD-4 contract, scene-boundary rationale)
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:124-149] — `_repair_movement`, reused for AC 5
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:210-247] — `parse_cast`, the upstream normalizer the validator runs after
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:1098-1158] — `build_scenes` hook site
- [Source: prompts/scenario/cast_decision.md#Composition] — the prompt-side rules being code-enforced (R1/R2 texts)
- [Source: prompts/scenario/visual_breakdown.md:226-239] — camera_type↔depth consistency rules (R3's two "never" pairings + dominant-depth tie-break)
- [Source: _bmad-output/implementation-artifacts/8-12-cast-placement-scale-calibration.md] — calibration baselines, pipeline-order constraint, "two pairings only" scope
- [Source: src/yt_flow/pipeline/nodes/video.py:182,189,531] — what depth/position mean at render time
- [Source: src/yt_flow/domain/state.py:17-18,62-97] — CastPosition/CastDepth/CastMember/ShotData contracts
- [Source: tests/pipeline/nodes/test_scenario_chain.py:1943-1977] — camera-variety test block to mirror

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Red phase: 21 new tests failed on missing `_enforce_cast_diversity` (expected), then all passed post-implementation.
- `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q` → 261 passed.
- Full repo suite `uv run pytest -q` → 1473 passed, 1 skipped (no regressions).
- `ruff check` clean on both changed files; `ruff format --check` failures pre-exist at baseline (verified via stash) — repo does not enforce format.

### Completion Notes List

- Implemented `_enforce_cast_diversity(shots)` + helper `_reassign_position` in `scenario_chain.py`, hooked in `build_scenes` directly after `_enforce_camera_variety` (AC1). Module constants `_MAX_CONSECUTIVE_SAME_PLACEMENT = 2` and `_SLOT_PREFERENCES` next to the `_VALID_*` block.
- **Deliberate deviation from Subtask 1.2's stated pass order:** implemented R1→R3→R2 (not R1→R2→R3). Rationale: R2's run key is `(position, depth)`; if R3's depth demotion runs after R2, it can complete a >2-run behind R2's back (e.g. `(center,mid)`,`(center,mid)`,`(center,near→mid)` under a wide camera), so a second invocation repairs more than the first — violating AC6 idempotence, which is an explicit AC and outranks the task's ordering note. The ordering note's actual goal ("nothing reintroduces a stacking violation") still holds: R3 never touches `position`, and R2 only moves onto free slots. Documented in the docstring.
- R2 corner case: when all 3 slots are occupied in the violating shot, the repeat persists (R1's no-stacking beats R2's variety), INFO-logged — mirrors AC2's 4+-member "keep their slot" philosophy. `# ponytail:` marked.
- Movement re-derive (AC5) lives inside `_reassign_position` so R1 and R2 can't diverge on it; only `movement_direction` changes, `movement_mode`/`movement_pace` untouched.
- Two pre-existing `build_scenes` cast-attachment tests used `camera_type: "wide"` with a lone `near` member — a fixture that now legitimately trips R3 (a lone member is a strict majority). Changed those fixtures' `camera_type` to `"medium"` (their concern is cast attachment, not camera); the AC8-protected parse_cast / `_repair_movement` / `_enforce_camera_variety` test blocks are untouched.
- Scope guard respected: no prompt, config, `video.py`, or `parse_cast` changes; no new files or dependencies.

### Senior Developer Review (AI)

- **[MEDIUM — fixed]** R1's free-slot computation ignored slots legitimately claimed by *later, non-violating* members, so a repair could cascade-displace a healthy sibling (e.g. `[A left, B left, C right]` → B took C's `right`, C got pushed to `center`) — violating the story's own mark-targeted scope guard (6.11 lesson) and AC2's free-slot semantics. Fixed: R1 now reserves upcoming members' distinct positions (`reserved = {later positions} - occupied`); B goes to `center`, C never moves. Regression test `test_enforce_cast_diversity_r1_does_not_displace_later_sibling` added (22 tests in the block now). Side effect verified sound: with 4+ members the violator now keeps its slot instead of innocents cascading — consistent with AC2's "remaining members keep their slot" philosophy; 3-member shots can never hit the empty-free branch (proof: 2 removals max from 3 slots).
- **[LOW — no action]** `_assert_no_diversity_violations` test helper checks R1/R2 only, not R3 — acceptable: its call sites use `camera_angle=None` where R3 is definitionally inert, and R3 has 4 dedicated tests.
- **[LOW — no action]** A non-dict shot is skipped without resetting R2 run tracking — unreachable from `build_scenes` output (it only appends `ShotData` dicts); direct-call defensive edge only.
- Verified during review: R1→R3→R2 pass-order deviation rationale (AC6 idempotence) is correct; R2 slot bookkeeping (`slots.discard/add`) cannot un-reserve a duplicated slot because duplicates only survive R1 when all 3 slots are occupied, where R2's `free` is empty; movement re-derive gate (`"movement_mode" in member`) is sound since `parse_cast` sets the movement trio atomically; git changes match the File List (orchestration `.md` is automator bookkeeping, excluded scope); AC8 re-verified post-fix — file suite 262 passed, full repo suite 1474 passed / 1 skipped, ruff clean.

### File List

- `src/yt_flow/pipeline/nodes/scenario_chain.py` — modified: constants `_MAX_CONSECUTIVE_SAME_PLACEMENT`/`_SLOT_PREFERENCES`, `_reassign_position`, `_enforce_cast_diversity`, one-line hook in `build_scenes`
- `tests/pipeline/nodes/test_scenario_chain.py` — modified: new `_enforce_cast_diversity` test block (22 tests incl. review-added sibling-displacement regression) + `import copy` + two stale `camera_type: "wide"` fixtures switched to `"medium"`
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — modified: story status tracking
- `_bmad-output/implementation-artifacts/8-18-cast-decision-diversity-validator.md` — modified: this story file

## Change Log

- 2026-08-01: Story 8.18 implemented — deterministic cast placement-diversity validator (R1 slot stacking, R2 consecutive-repeat cap, R3 camera↔depth never-pairings) hooked into `build_scenes`; 21 new tests, full suite green (1473 passed). Status → review.
- 2026-08-01: Senior Developer Review (AI) — 1 MEDIUM fixed (R1 cascade could displace a non-violating sibling; free slots now reserve later members' claims), 2 LOW verified no-action, +1 regression test (22 total); full suite re-verified green (1474 passed). Status → done.
