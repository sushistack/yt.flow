---
created: 2026-07-06
baseline_commit: 0267f0b
story_key: 8-1-shot-cast-metadata-bg-prompts
story_id: "8.1"
epic: 8
previous_story: 7-5-kinetic-subtitles
depends_on: []
blocks:
  - 8-3-bg-only-generation-multicard-compositing   # consumes ShotData.cast + background-only image_prompt
  - 8-4-on-demand-special-pose-cards               # extends CastMember with pose_hint; consumes the closed pose enum
related:
  - 8-2-character-card-sprite-pipeline             # parallel-safe; shares only the card_key + pose vocabulary
---

# Story 8.1: Per-Shot Cast Metadata + Background-Only Prompts

Status: done

## Story

As Jay,
I want the scenario stage's visual_breakdown to emit, per shot, a `cast` list (which character cards appear, each with rough placement metadata) and an image_prompt that describes only the background (no entity/person descriptions),
so that the image stage can generate clean entity-free backgrounds and the video stage can composite N pre-cut character cards under data control — instead of the abandoned "generate frame with entity → segment → inpaint" pipeline whose defects (D5/D10/D11/D13) sank the E2E baseline.

## Context

**Context: E2E baseline 2026-07-06 (run 272b05a4, SCP-049)** — report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`. Jay made a binding architecture decision at the image gate (report sections "Jay 실시간 피드백" and "추가 결정/확장 확정"): abandon the same-frame segmentation+inpaint lineage (1.6b/5-6/5-7) in favor of **background-only generation + pre-generated RGBA character-card compositing**. This story is the scenario-side third of Epic 8: it owns the data contract (`cast`) and the prompt change; it touches **no image or video code**.

Baseline defects this story addresses directly:

- **D11 (major/design)**: visual_breakdown has no per-shot entity-presence signal, so image_node segments *every* shot — entity-less shots had whole rooms (S00100) and light blobs (S00604) cut out as "characters". An empty `cast` list is the missing signal.
- **D3 (minor)**: 6/59 prompts used the bare token "SCP-049(-2)" with no visual descriptor — a meaningless token to SDXL. Cast absorbs this: the entity's appearance lives in the card; the prompt never carries bare SCP tokens.
- **D13 enabler**: multi-card compositing (8.3) needs per-card placement metadata ("배치 메타데이터 필수, 없으면 카드가 중앙에 겹침" — Jay, 확장 확정). This story defines and emits it.

Lesson D1 applies everywhere here: the writing LLM violated the `mood` enum in 8/8 scenes despite the `structure.md` constraint. Every field this story adds MUST parse leniently with deterministic fallbacks (mirroring `sound_design.resolve_mood`), never fail the scenario stage on a taxonomy violation.

## Interfaces (Epic 8 contract — Produces)

This section is the single normative definition. Stories 8.2/8.3 reference it verbatim; if you change anything here, you are changing three stories.

```python
# src/yt_flow/domain/state.py  (new in this story)
CastPosition = Literal["left", "center", "right"]
CastDepth = Literal["near", "mid", "far"]
CastPose = Literal["standing", "sitting"]  # closed v1 vocabulary — special poses arrive via
                                           # 8.4's optional pose_hint field, NEVER as new enum values

class CastMember(TypedDict):
    card_key: str          # exact CharacterModel.scp_id key:
                           #   SCP entity        -> scp_id, e.g. "SCP-049"
                           #   fixed stock cast  -> "STOCK-d-class" | "STOCK-researcher" | "STOCK-security"
                           #   derived entity    -> "<scp_id>-<n>", e.g. "SCP-049-2"
    position: CastPosition # horizontal slot in frame
    depth: CastDepth       # distance plane: drives scale, parallax amplitude, and stacking
    pose: CastPose         # body stance: selects which pose entry of the card library 8.3 resolves

STOCK_CAST_KEYS = ("STOCK-d-class", "STOCK-researcher", "STOCK-security")  # single source of truth

class ShotData(TypedDict):
    ...existing fields...
    cast: list[CastMember]   # [] == background-only shot: downstream does NO overlay work at all
```

**Semantics (binding for 8.2/8.3):**

1. **Empty cast list = background-only shot.** No segmentation, no overlay, no angle selection for that shot (resolves D11).
2. **Stacking (z-order) is derived, not stored**: composite far → mid → near; a stable sort by depth preserves cast-list order within the same depth. There is deliberately **no `z` field** — a free integer is exactly the kind of constraint LLMs violate (D1), and depth already totally orders the planes; ties fall back to list order deterministically. One `sorted(cast, key=...)` line replaces a whole failure mode.
3. **`image_prompt` is background-only**: entity/person/creature descriptions are stripped by the visual_breakdown prompt itself; characters exist in the shot *only* via `cast`. No bare SCP tokens in prompts (D3).
4. **Parser leniency (D1 lesson)**: invalid `position` → `"center"`; invalid `depth` → `"mid"`; invalid/missing `pose` → `"standing"`; entry with an unusable `card_key` (empty/non-string) → dropped with a warning; `cast` missing or not a list → `[]`. A taxonomy violation must never fail the scenario stage.
5. **`card_key` normalization**: strip whitespace; uppercase a `scp-`/`SCP-` prefix to canonical `SCP-`; `STOCK-*` keys must match `STOCK_CAST_KEYS` exactly (case-sensitive match after a case-insensitive comparison — normalize to the canonical casing). Keys that are none of {run's scp_id, STOCK_CAST_KEYS member, `<scp_id>-<n>` derived pattern, or any other plausible `SCP-\d+(-\d+)?`} still pass through as-is (downstream resolves against the DB and skips-with-warning) — the parser normalizes, it does not gatekeep.
6. **Pose is one closed axis (2026-07-06 amendment — industry-standard sprite-library tiering)**: `"standing"` is the universal default and always exists in the card library (8.2 seeds it for every card_key); `"sitting"` resolves to a sitting card when 8.2 has one and falls back to standing with a warning when it doesn't (8.3). The enum stays closed at two values — free-text special poses are NOT enum values; they arrive via the *separate optional* `pose_hint` field that Story 8.4 adds (schema owned there, not here). No expression/costume/outfit axes.

## Acceptance Criteria

1. **Domain types.** Given `src/yt_flow/domain/state.py`, then `CastMember` (fields exactly `card_key`, `position`, `depth`, `pose` as above), `CastPosition`/`CastDepth`/`CastPose` literals, and `STOCK_CAST_KEYS` exist there (pure stdlib typing, no upper-layer import — AD-1), and `ShotData` gains `cast: list[CastMember]`.
2. **Drift guard updated.** Given `tests/domain/test_state_imports.py`, then `EXPECTED_FIELDS` gains `"CastMember": {"card_key", "position", "depth", "pose"}`, `ShotData`'s expected set gains `"cast"`, and `test_typeddicts_import`'s name list gains `"CastMember"` — the guard passes with the new shapes and still fails on any further drift.
3. **Prompt contract.** Given `prompts/scenario/visual_breakdown.md`, then its output schema replaces the boolean `entity_visible` with a `cast` array per shot (objects with `card_key`/`position`/`depth`/`pose`, allowed values spelled out, back-to-front listing encouraged but not required), and the prompt body is rewritten so that: (a) `image_prompt` describes environment/lighting/atmosphere ONLY — the "When `entity_visible: true` copy the frozen descriptor verbatim" rules (current lines 138-153) are replaced by "the entity NEVER appears in image_prompt; it appears via cast"; (b) bare SCP designators (e.g. "SCP-049") are forbidden inside `image_prompt` (D3); (c) named human cast (D-class/researchers/guards) are likewise never described in `image_prompt` — they become `STOCK-*` cast entries; (d) a shot with no characters emits `"cast": []` (D11); (e) placement guidance ties position/depth to composition intent (e.g. "entity looming near-left, researcher far-right"); (f) the entity's *environmental* signature (aftermath cues, marks) remains fair game for background prompts — the entity-absence storytelling section (current lines 147-153) survives, re-scoped to every shot's background; (g) `pose` is taught with composition intent — default `"standing"`; `"sitting"` for interview/interrogation, containment-chair, desk/console-work, medical-restraint, and collapsed/slumped beats; only these two values are legal (free-text poses are forbidden here — Story 8.4 adds a separate `pose_hint` field for that later; this prompt version emits only the enum).
4. **Prompt template inputs.** Given the compiled prompt, then it receives the run entity's `scp_id` and the allowed stock keys so the LLM can only reference real card vocabulary (extend the existing `visual_breakdown_step` variable dict — `scenario_chain.py:186-200`; `STOCK_CAST_KEYS` compiled in, plus a note that `<scp_id>-<n>` derived keys are allowed).
5. **Lenient parser.** Given `build_scenes` (`scenario_chain.py:320-375`), when a raw shot carries `cast`, then each `ShotData` is constructed with a normalized `cast` per Interfaces rules 4-6 (including `pose` defaulting to `"standing"` on any invalid/missing value); when `cast` is missing/malformed (including every output of the *old* production prompt), then `cast=[]` and the stage still succeeds. Shots merged into a previous shot (empty `image_prompt` transition sentences, lines 338-341) contribute no cast of their own; the `_fallback_prompt` backfill shot (lines 342-344) gets `cast=[]`.
6. **Old checkpoints resume.** Given a pre-8.1 checkpointed run, when it resumes, then nothing reads `shot["cast"]` with a hard key access anywhere this story touches — downstream consumers (8.3) are contractually bound to `shot.get("cast") or []`, and this story's own code never assumes the key exists on inbound dicts.
7. **Gate visibility.** Given the scenario stage artifact endpoint, then the per-shot serialization in `run_service.get_stage_artifacts` (`src/yt_flow/services/run_service.py:83-100`) includes `"cast": sh.get("cast", [])` — the D2 defect was exactly this serializer silently dropping a new state field (`mood`), so a human at the scenario gate could not review it; do not repeat that with `cast`.
8. **PROMPT_POLICY rollout.** Given `docs/PROMPT_POLICY.md`, then the prompt change follows the change protocol: repo file edited first; seeded as `candidate` via `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario`; A/B run + golden-set gate (`uv run python scripts/eval_prompts.py --label candidate --baseline production` — the golden set includes SCP-049, and `visual_breakdown` IS a scenario-stage prompt, so the standard gate applies with no substitute procedure needed). **Promotion to `production` is NOT part of this story's DoD** — the story ships with `candidate` seeded and the eval evidence recorded; Jay moves the label. The parser (AC5) must work against both prompt versions precisely because of this window.
9. **No image/video changes.** Given this story's diff, then `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/pipeline/nodes/video.py`, `src/yt_flow/config.py`, and all ComfyUI workflow JSONs are untouched. Runtime behavior downstream of scenario is byte-identical (cast is emitted, carried, displayed — and ignored until 8.3).
10. **Tests.** Given automated verification, then: cast normalization has a direct unit-test table (valid entry; bad position; bad depth; bad pose; missing pose → `"standing"`; non-dict entry; empty card_key; `scp-049` case normalization; stock-key casing; missing cast; cast-not-a-list); `build_scenes` tests cover cast attach + merge behavior + legacy no-cast payloads; the drift guard passes; the artifact serializer test asserts `cast` appears. `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/domain/test_state_imports.py tests/services -q` and the full suite stay green.

## Tasks / Subtasks

- [x] Task 1 — Domain types + drift guard (AC: 1, 2)
  - [x] Add `CastPosition`, `CastDepth`, `CastPose`, `CastMember`, `STOCK_CAST_KEYS` to `src/yt_flow/domain/state.py` (near `AngleName`, line 16); add `cast: list[CastMember]` to `ShotData` (lines 25-36). Pure stdlib typing only.
  - [x] Update `tests/domain/test_state_imports.py` `EXPECTED_FIELDS` (lines 13-41) and the import list (lines 44-47).
- [x] Task 2 — Cast parser (AC: 5, 6)
  - [x] Add a pure `parse_cast(raw: object) -> list[CastMember]` helper in `scenario_chain.py` implementing Interfaces rules 4-6 (leniency + normalization, incl. `pose` → `"standing"` default), logging a `logger.warning` per dropped entry (module already has `logger`).
  - [x] Wire it into `build_scenes`'s `ShotData(...)` construction (line 346-358): `cast=parse_cast(raw_shot.get("cast"))`. Merged/backfill shots per AC5.
  - [x] Do NOT tighten `visual_breakdown_step`'s validation (lines 205-212) beyond today's 1:1 count check — cast problems degrade, they don't retry the stage.
- [x] Task 3 — Prompt rewrite (AC: 3, 4)
  - [x] Rewrite `prompts/scenario/visual_breakdown.md` per AC3: output schema (`cast` replaces `entity_visible`, current example at lines 205-223; example member carries all four fields incl. `pose`), entity-visible rules section (138-153) replaced with cast+background-only rules, pose guidance per AC3(g) folded into the placement-guidance block, Character Visual Anchoring section (172-176) re-scoped (anchoring now applies to *card* vocabulary, not prompt prose), pre-output self-check (225-243) updated (checks: no entity/person description in image_prompt; no bare SCP tokens; cast values ∈ allowed sets incl. `pose` ∈ {standing, sitting}; environment shots have `"cast": []`).
  - [x] Add the card vocabulary inputs (`{{scp_id}}` if not already available in the variable dict, plus a compiled stock-keys line) and pass them from `visual_breakdown_step` (`scenario_chain.py:186-200`).
  - [x] Keep everything that still applies: 8-slot structure, forbidden generic terms, camera_type rules, 1:1 mapping, negative_prompt prefix. Additionally instruct negative_prompt to include person/figure exclusion terms for background-only intent (belt; 8.3 adds the code-side suspenders).
- [x] Task 4 — Gate artifact exposure (AC: 7)
  - [x] Add `"cast": sh.get("cast", [])` to the scenario serializer in `run_service.get_stage_artifacts` (`run_service.py:83-100`); extend its test (`tests/api/` or `tests/services/` — follow wherever `get_stage_artifacts` is currently covered).
- [x] Task 5 — Prompt rollout per policy (AC: 8)
  - [x] Seed: `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario`.
  - [x] Golden-set gate: `uv run python scripts/eval_prompts.py --label candidate --baseline production`; record the verdict in Dev Agent Record. Note: the judge axes don't score cast correctness — additionally hand-inspect one candidate-label SCP-049 scenario for (a) empty-cast environment shots, (b) no entity descriptions in image_prompt, (c) sane placement values, (d) pose values ∈ {standing, sitting} used with plausible composition intent (not sitting-everywhere / standing-everywhere-including-interview-scenes), and record findings.
  - [x] Do not move the `production` label; do not edit prompts in the Langfuse UI (policy rules 2/5).
- [x] Task 6 — Tests + regression (AC: 9, 10)
  - [x] `tests/pipeline/nodes/test_scenario_chain.py`: `parse_cast` table tests + `build_scenes` cast attach/merge/legacy tests.
  - [x] Update `tests/stubs/fakes.py` / any scene-dict fixtures that build `ShotData` literals to include `cast` (TypedDicts don't enforce at runtime, but fixtures should model the real contract; grep for `"character_path"` in tests to find shot-literal builders).
  - [x] Full suite: `uv run pytest -q` green; confirm zero diffs under `src/yt_flow/pipeline/nodes/image.py` / `video.py`.

### Review Findings

- [x] [Review][Patch] Candidate prompt still fails the cast/background-only contract [prompts/scenario/visual_breakdown.md:149]
- [x] [Review][Patch] 8.1 prompt claims current image-stage enforcement even though AC9 forbids image changes [prompts/scenario/visual_breakdown.md:218]
- [x] [Review][Patch] 8.2 image/config/workflow changes are mixed into the 8.1 review range [src/yt_flow/pipeline/nodes/image.py:35]
- [x] [Review][Patch] 8.2 character-card pipeline code is mixed into the 8.1 review range [scripts/seed_stock_cast.py:1]
- [x] [Review][Patch] Anchorless ComfyUI card generation can submit a placeholder LoadImage node [src/yt_flow/services/character_image_provider.py:101]
- [x] [Review][Patch] Qwen card provider path cannot satisfy the new alpha-sprite requirement [src/yt_flow/services/character_service.py:635]
- [x] [Review][Patch] Descriptor card generation continues side/back angles without a front identity anchor [src/yt_flow/services/character_service.py:681]
- [x] [Review][Patch] Stock card seeding completion checks ignore missing or corrupt files [scripts/seed_stock_cast.py:35]
- [x] [Review][Patch] Concurrent card seeding can race unique constraints [src/yt_flow/services/character_service.py:225]
- [x] [Review][Patch] A single --anchor can be reused across every stock cast member [scripts/seed_stock_cast.py:94]
- [x] [Review][Patch] Seeder/service accept pose values outside the closed cast enum [scripts/seed_stock_cast.py:122]
- [x] [Review][Patch] Alpha check can accept malformed PNG bytes [src/yt_flow/domain/png.py:10]

## Dev Notes

### Why the schema looks like this (decision record)

- The epic draft asked for "position/scale/z-order". Delivered as `position` (3-slot) + `depth` (3-plane): **scale and parallax amplitude are derived from `depth` by 8.3's module constants** (same pattern as `CHAR_DEPTH_FACTOR`, `video.py:104-115`), and **z-order is derived from `depth` + list order** (Interfaces rule 2). Storing derived values invites contradictions the renderer must then arbitrate; storing free-form numerics invites D1-class LLM violations. Three-value enums are the most an LLM reliably respects and the most the composition actually needs ("대략적 좌우·원근 수준" — Jay's own scoping).
- `card_key` reuses `CharacterModel.scp_id` verbatim (`db/models.py:27`, unique-indexed) because 8.2 seeds `STOCK-*` rows under that same key — no schema change, no second identifier namespace. `_PATH_UNSAFE_RE` (`character_service.py:68`) already accepts these key shapes.
- `entity_visible` already exists in today's prompt output but is **dropped on the floor** by `build_scenes` (it never reaches `ShotData`) — so replacing it in the prompt breaks no consumer. Grep confirms no `src/yt_flow` code reads `entity_visible`.
- **`pose` (2026-07-06 amendment, per Jay — industry-standard sprite-library tiering)**: game/VN sprite systems pre-generate a small library of base poses × angles and treat everything else as per-scene key art. `pose` is the library selector: a two-value closed enum (`standing`/`sitting`), same D1-driven reasoning as position/depth — the LLM reliably respects tiny enums and violates anything freer. The on-demand tier (free-text special poses) is deliberately NOT in this enum; Story 8.4 adds it as a *separate optional* `pose_hint` field so the enum stays closed and the lenient parse stays trivial. Same fallback philosophy as `mood`: the default is always renderable because 8.2 seeds standing for every card_key.

### Current Code State — files to read before editing

- `src/yt_flow/domain/state.py:25-36` — `ShotData`; module header documents the AD-1/AD-2 rules (stdlib-only, JSON-serializable — `cast` as list-of-dicts is checkpoint-safe).
- `src/yt_flow/pipeline/nodes/scenario_chain.py:171-212` — `visual_breakdown_step` (prompt variable dict at 186-200; the only validation is the 1:1 count check at 206-211). `build_scenes` 320-375: empty-prompt merge at 338-341, `_fallback_prompt` backfill at 342-344, `ShotData` literal at 346-358 (`entity_visible` is not read; `camera_type` is). Mood's lenient `.get(...) or DEFAULT_MOOD` at 372 is the leniency pattern to copy.
- `prompts/scenario/visual_breakdown.md` — full current contract; sections listed per-AC above. Note `characters_present` is already a template input (line 23) — it stays (scene-level context), cast is the *shot-level* output.
- `src/yt_flow/services/run_service.py:83-100` — scenario artifact whitelist serializer (the D2 trap).
- `tests/domain/test_state_imports.py:13-53` — drift guard.
- `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` — D1/D3/D11/D13 sections + both Jay decision blocks.

### Preserved behavior (do not break)

- **Scenario stage failure semantics**: only structural failures (bad JSON, count mismatch) fail the stage; taxonomy violations degrade (D1/mood precedent). `parse_cast` must never raise on LLM data.
- **1:1 sentence-to-shot mapping + merge logic** (`build_scenes:334-344`) — untouched except the added `cast=` kwarg.
- **`mood` population** (`build_scenes:372`) — untouched.
- **Old production prompt keeps working**: until Jay promotes the candidate, real runs produce shots without `cast` → parser yields `[]` → downstream identical to today. Old checkpoints resume for the same reason (AC6).
- **Stub/mock profiles**: `YTFLOW_COMFYUI_MOCK` / stub-profile e2e tests exercise scenario via fakes — fabricated scenes without `cast` must keep passing (they will, given `.get`-based parsing; still update fixtures per Task 6).
- **A/B mechanism** (Story 4.1/6.1): `prompt_variant` label reading is orthogonal; `candidate` seeding must not disturb `production` compilation.

### Architecture compliance

- AD-1: everything lands in `domain/` + `pipeline/nodes/` + one serializer line in `services/`; no new cross-layer imports.
- AD-2: `cast` is plain list-of-dicts in a TypedDict — JSON-checkpoint-safe; lenient resume for old checkpoints.
- AD-4: node still returns state updates only; no DB/SSE work added.

### Testing standards

Pure-function tests assert return values directly (no LLM, no network) — the `test_scenario_chain.py` convention. Prompt-quality verification is the golden-set gate + hand inspection (Task 5), not unit tests. Run: `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/domain/test_state_imports.py -q`, then full `uv run pytest -q`.

### Ponytail note

Minimal diff: one TypedDict + one tuple constant, one pure parser function, one `cast=` kwarg, one serializer line, one prompt rewrite. No new pipeline stage, no config flag (there is nothing to toggle — cast is inert until 8.3), no speculative fields (`scale` and `z` deliberately absent; `pose` was originally deferred and is now included per Jay's 2026-07-06 decision — as ONE closed two-value axis, not a matrix: no expression, no costume, no free-text pose values in this enum). Mark any deliberate simplification with `# ponytail:`.

## Project Structure Notes

- Modified: `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/services/run_service.py` (one serializer line), `prompts/scenario/visual_breakdown.md`, `tests/domain/test_state_imports.py`, `tests/pipeline/nodes/test_scenario_chain.py`, `tests/stubs/fakes.py` (fixtures only).
- No new modules, no config changes, no workflow JSON changes.
- Concurrent-edit hazard: `run_service.py` and `state.py` are shared hot files (see memory of 1.10/2.x collisions) — if 8.2/8.3 sessions run in parallel, coordinate or use a worktree.

## References

- `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` — D1, D3, D11, D13; "Jay 실시간 피드백" + "추가 결정/확장 확정" (multi-card + placement metadata requirements).
- `_bmad-output/planning-artifacts/epics.md#Epic 8 / Story 8.1` — epic draft.
- `docs/PROMPT_POLICY.md` — change protocol (rules 1-5), golden-set gate commands.
- `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `prompts/scenario/visual_breakdown.md`, `src/yt_flow/services/run_service.py:60-110` — edit surfaces (line refs in Dev Notes).
- `tests/domain/test_state_imports.py` — drift guard.
- Sibling stories: `8-2-character-card-sprite-pipeline.md` (card production incl. the pose-aware card storage), `8-3-bg-only-generation-multicard-compositing.md` (sole consumer of `cast`; resolves `(pose, angle)`), `8-4-on-demand-special-pose-cards.md` (adds the optional `pose_hint` field on top of this schema).

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5), via bmad-dev-story.

### Debug Log References

- Golden-set gate run (joint candidate-vs-production): **FAIL** — `SCP-049/SCP-173/SCP-096: item failure` on both sides in the joint run. Isolating with `--label production` alone showed the baseline itself failing 2/3 items on stages this story never touches: `SCP-173: scenario/review response truncated (finish_reason=length)`, `SCP-096: Expecting ',' delimiter: line 45 column 90 (char 4323)` (JSON parse failure, pre-`visual_breakdown`). `--label candidate` alone succeeded on all 3 items (atmosphere/narrative_coherence/article_fidelity scores recorded in Langfuse dataset run `golden-eval-candidate - 2026-07-07T13:03:52Z`). Per PROMPT_POLICY.md's strict criteria (no item may fail on either label) the gate is FAIL, but the failures are baseline flakiness in `research`/`review` stages this story does not touch, not a regression this story introduced — captured here per AC8, not fixed (config.py / other stages are out of this story's scope).
- Hand inspection (Task 5, AC:8) across 3 live scenario_node runs (SCP-049 ×2, SCP-173 ×1, using `prompt_variant="B"` against the seeded `candidate` label) surfaced a real prompt-compliance gap: **0/125 shots across all 3 successful runs got a non-empty `cast`** — the LLM (deepseek-v4-flash) kept describing the entity/D-class/researchers directly in `image_prompt` (e.g. "a gaunt man with a shaved head... torn orange jumpsuit", "SCP-173" appearing 17 times as a bare token in one run) instead of using `cast` entries, despite the rewritten rules explicitly forbidding this. Attempted one round of prompt strengthening (added a top-of-document "CRITICAL RULE" callout + a concrete BAD→GOOD worked example, re-seeded as `candidate`) — re-tested and the gap persisted identically (0/56 cast-populated shots on SCP-173 post-strengthening). Several other runs failed on `visual_breakdown`/`review` response truncation or a 1:1 count mismatch — all pre-existing failure modes (structural validation / `max_tokens`), not new ones; truncation frequency may be modestly higher because the cast schema lengthens `visual_breakdown`'s output per shot, but `deepseek_max_tokens` is in `config.py`, which AC9 forbids touching in this story.
- Code review patch (2026-07-07): removed remaining body-shaped shadow/person-implied prompt examples, added explicit JSON few-shot examples with populated `cast`, and removed the false claim that the image stage already enforces person exclusions. Re-seeded `scenario/visual_breakdown` as a fresh `candidate` via `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario` (`created: visual_breakdown`). A post-patch `uv run python scripts/eval_prompts.py --label candidate --baseline production` attempt was manually interrupted after more than 8 minutes without a final verdict; no post-patch hand-inspection verdict is claimed here.
- Conclusion recorded for Jay (see Saved Questions #4, new): the code contract (domain types, parser, serializer, tests) is complete and correct per AC1-2/4-7/9-10, and the prompt document meets every literal AC3 sub-requirement — but the candidate prompt does not yet reliably get the LLM to use `cast` instead of prose. Further prompt iteration (few-shot examples, restructuring, or a different model/temperature) is needed before promotion; this is explicitly out of this story's DoD (AC8) and is not a regression against the old `entity_visible` prompt, which had the same category of enum-violation risk (D1) this story's lenient parser already absorbs safely — `cast=[]` degrading gracefully to background-only downstream is the intended fallback either way.

### Completion Notes List

- Domain types (`CastMember`/`CastPosition`/`CastDepth`/`CastPose`/`STOCK_CAST_KEYS`), `ShotData.cast`, drift guard, `parse_cast` lenient normalizer, `build_scenes` wiring (incl. merge/backfill semantics), `visual_breakdown_step`'s `scp_id`/`stock_cast_keys` threading, the scenario artifact serializer's `cast` field, and the full `visual_breakdown.md` prompt rewrite are all implemented and unit-tested (AC1-2, AC4-7, AC9-10 — `uv run pytest -q` full suite green, 753 passed / 1 pre-existing skip).
- AC8 (prompt rollout): candidate seeded, golden-set gate run, hand inspection done — see Debug Log References above for the original FAIL verdict and cast-compliance finding. Code review strengthened and re-seeded the candidate again; production label was not moved (per policy), and the post-review eval attempt was interrupted before verdict.
- **Concurrent-edit collision during this session**: a separate parallel session was actively implementing Story 5.20 (cc-attribution-credits) in the same working tree and, mid-session, overwrote `src/yt_flow/domain/state.py`, `tests/domain/test_state_imports.py`, `src/yt_flow/services/run_service.py`, `tests/api/test_stage_artifacts.py`, and `tests/pipeline/nodes/test_video.py` with a version that predated this story's edits, dropping the `cast` additions. Detected via an unrelated `ImportError: cannot import name 'CastDepth'` during hand inspection; re-applied this story's diffs on top of the then-current (5.20-inclusive) file contents and re-ran the full targeted test set to confirm both stories' changes coexist correctly. No 5.20 content was reverted or lost. Flagged to Jay mid-session; instructed to continue rather than pause or move to a worktree.

### File List

- `src/yt_flow/domain/state.py` — `CastPosition`/`CastDepth`/`CastPose`/`CastMember`/`STOCK_CAST_KEYS`; `ShotData.cast`.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `parse_cast`, `_normalize_card_key`, `build_scenes` wiring, `visual_breakdown_step` gains `scp_id` param + `stock_cast_keys` variable.
- `src/yt_flow/pipeline/nodes/scenario.py` — thread `scp_id` into the `visual_breakdown_step` call site.
- `src/yt_flow/services/run_service.py` — scenario artifact serializer emits `"cast": sh.get("cast", [])`.
- `prompts/scenario/visual_breakdown.md` — cast/placement/pose contract replaces `entity_visible`; background-only rules; CRITICAL RULE callout + worked example (post-hand-inspection strengthening pass).
- `tests/domain/test_state_imports.py` — `CastMember` + `ShotData.cast` drift-guard coverage.
- `tests/pipeline/nodes/test_scenario_chain.py` — `parse_cast` table tests, `build_scenes` cast attach/merge/backfill tests, `visual_breakdown_step` signature + placeholder updates.
- `tests/pipeline/nodes/test_scenario.py` — `fake_visual` signatures updated for the new `scp_id` leading param.
- `tests/api/test_stage_artifacts.py` — `cast` fixture param + 2 new tests (present / pre-8.1-checkpoint-default).
- `tests/api/test_stages.py`, `tests/pipeline/nodes/test_video.py`, `tests/pipeline/test_stub_profile_smoke.py`, `tests/services/test_character_angle_selector.py` — shot-literal fixtures gain `"cast": []` to model the real `ShotData` contract.

## Change Log

- 2026-07-06: Story created from Epic 8 architecture decision (E2E baseline run 272b05a4). Owns the Epic 8 `CastMember` interface definition.
- 2026-07-06: pose dimension added per Jay — industry-standard sprite-library tiering. `CastMember` gains `pose: Literal["standing","sitting"]` (lenient parse → `"standing"`); prompt contract teaches pose with composition intent; drift guard/tests extended. Free-text special poses stay out of the enum — Story 8.4 (new) owns the optional `pose_hint` field and on-demand card provisioning.
- 2026-07-07: Implemented (this session). Domain types, lenient parser, prompt rewrite, serializer exposure, and full test coverage delivered per AC1-2/4-7/9-10. AC8 (rollout) completed to spec: candidate seeded, golden-set gate run (FAIL — baseline flakiness in untouched stages, not a regression), hand-inspection done and a real cast-compliance gap documented for Jay. Status → review.
- 2026-07-07: Code review findings patched. Prompt examples strengthened with concrete cast-populated JSON few-shots, contradictory image-stage enforcement text removed, scenario candidate re-seeded; 8.2 review spillover findings fixed separately and kept out of the 8.1 commit boundary.

## Saved Questions / Clarifications

1. **Promotion timing.** AC8 deliberately stops at `candidate` + eval evidence; until Jay promotes, live runs emit `cast=[]` everywhere and 8.3 (if merged first) renders background-only videos. If Jay wants promotion inside this story, the golden-set gate must pass first and the judge axes say nothing about cast quality — hand inspection (Task 5) is the real check.
2. **Derived-entity descriptors.** The prompt can emit `card_key: "SCP-049-2"`, but nothing in this story guarantees a card exists for it — 8.2 provides the seeding mechanism and 8.3 skips-with-warning at composition. Whether derived-entity cards should be auto-provisioned mid-run (post-scenario hook) is an open product question recorded in 8.2/8.3 as well.
3. **`characters_present` (scene-level, structure stage) vs per-shot cast** — left untouched as LLM context. If they conflict, cast wins (it's the machine-read contract). Consider unifying in a later prompt iteration, not here.
4. **Cast-compliance gap (new, from hand inspection).** Across every successful candidate-label run tested (SCP-049 ×2, SCP-173 ×1 — 125 shots total), the LLM never populated a `cast` entry and kept describing the entity/D-class/researchers directly in `image_prompt`, including bare "SCP-173" tokens. One round of prompt strengthening (top-of-doc CRITICAL RULE + worked example) did not change this. The code-side contract (parser, serializer, tests) is correct and ships regardless — a `cast=[]` always degrades safely to today's background-only-downstream behavior — but the prompt itself needs another iteration (stronger few-shot demonstration, restructuring so cast rules aren't competing with the unchanged 8-slot/Visual-Vocabulary sections' implicit modeling of dense subject prose, or a stricter enforcement pass) before Jay should consider promoting `candidate` to `production`. Recommend a short, focused prompt-only follow-up (no code changes) before 8.3 depends on real cast data in production traffic.
