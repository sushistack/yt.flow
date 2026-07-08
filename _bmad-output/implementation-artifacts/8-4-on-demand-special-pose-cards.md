---
created: 2026-07-06
baseline_commit: 0267f0b
story_key: 8-4-on-demand-special-pose-cards
story_id: "8.4"
epic: 8
previous_story: 8-3-bg-only-generation-multicard-compositing
depends_on:
  - 8-1-shot-cast-metadata-bg-prompts       # CastMember schema + closed pose enum this story extends with pose_hint
  - 8-2-character-card-sprite-pipeline      # character_cards table (hint:* keys) + generate_cards_from_descriptor path
  - 8-3-bg-only-generation-multicard-compositing   # resolve_cast_cards, the lookup this story extends
related:
  - 5-8 / 5-10                              # _ensure_character_reference non-fatal provisioning pattern, reused here
---

# Story 8.4: On-Demand Special-Pose Cards

Status: in-progress

## Story

As Jay,
I want visual_breakdown to optionally emit a free-text `pose_hint` on a cast member (e.g. "kneeling over a corpse", "strapped to an operating table"), and a run-time provisioning step that generates a one-off special-pose card when no cached card matches — cached under a deterministic key for cross-run reuse, capped per run, and never able to fail the run,
so that per-scene key-art poses are possible without exploding the pre-generated sprite library — the on-demand tier of the industry-standard sprite-library model Jay approved 2026-07-06 (base poses pre-generated per 8.2; everything else generated exactly when a scene demands it).

## Context

**Context: Epic 8 pose dimension (Jay decision 2026-07-06)** — the tiered model splits poses into (1) a pre-generated base library, `{standing, sitting}` × 4 angles, owned by 8.2 with the closed `CastPose` enum owned by 8.1, and (2) **this story**: on-demand special poses as per-scene key art. The enum stays closed — a free-text pose is a *hint*, carried in a separate optional field, and always degradable to the base pose. This is the same containment strategy that keeps D1-class LLM taxonomy violations harmless: the machine contract (`pose`) is tiny and closed; the expressive channel (`pose_hint`) is advisory, resolved opportunistically, and non-binding.

Why on-demand instead of a bigger library: each card is a real ComfyUI render plus eyes-on QA (8.2's cost basis), and special poses have near-zero reuse across episodes ("kneeling over a corpse" is SCP-049 key art, not library material). Generating at run time, keyed deterministically, gives reuse when it *does* recur for free.

This story also inherits two proven patterns wholesale:

- **5-8/5-10's `_ensure_character_reference`** (`run_service.py:368-444`): best-effort, non-fatal, pre-graph provisioning that logs-and-swallows every failure (AD-10). This story adds the *post-scenario-gate* sibling that 8.2's Saved Question #1 anticipated — pose_hints only exist after the scenario stage runs, so provisioning hooks the scenario-gate approval, not run start.
- **8.3's resolver fallback posture**: a missing pose card degrades to the base pose with a warning; only a *broken* asset (opaque card) fails the stage. `pose_hint` resolution slots into exactly that split.

## Interfaces (Epic 8 contract — Consumes and extends)

Normative definitions live in `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` (CastMember schema, closed `CastPose` enum) and `8-2-character-card-sprite-pipeline.md#Interfaces` (#4: pose-aware card storage — `character_cards` keyed unique `(scp_id, pose, angle)`; #1-3: RGBA sprite artifact contract). This story extends both at their designated extension points and defines nothing that contradicts them.

**Schema extension (this story Produces; owned here, referenced by 8.1's decision record):**

```python
class CastMember(TypedDict):
    card_key: str
    position: CastPosition
    depth: CastDepth
    pose: CastPose                    # closed enum, unchanged — 8.1
    pose_hint: NotRequired[str]       # NEW: optional free-text special pose, e.g. "kneeling over a corpse".
                                      # Advisory only: resolution falls back to `pose` when no hint card exists.
```

- **Parse rule (extends 8.1 Interfaces rule 4)**: `pose_hint` present as a non-empty string → stripped and passed through; missing, empty, non-string, or longer than 80 chars → key omitted entirely (no `None`, no empty string in state). Never affects the parse of the other fields; never fails the stage.
- **`pose` is still populated normally** — the hint does not replace it; it is what the hint *falls back to*.

**Cache key (this story Produces; stored in 8.2's `character_cards`):**

```python
def pose_hint_key(hint: str) -> str:
    return "hint:" + hashlib.sha256(hint.strip().lower().encode()).hexdigest()[:10]
```

- Stored as the `pose` column value with `angle="front"` — a special-pose card is **one** key-art render, not a 4-angle set (cost guardrail; the compositor treats it like any front card).
- Deterministic → the same hint on any later run (same or different episode) is a cache hit; no registry, no TTL, no cleanup job.

**Resolution rule (extends 8.3's `resolve_cast_cards` lookup; consumed by video_node unchanged):**

- Member carries `pose_hint` → compute `pose_hint_key`, look up `get_card(scp_id, key, "front")`; hit → that card resolves the member (`{"card_key", "pose": key, "angle": "front", "path", "fallback": False}`), skipping LLM angle selection for that member; miss → resolve exactly as if `pose_hint` were absent (base `pose` semantics, 8.3), plus one `logger.warning`. Alpha validation (8.3 AC10) applies to hint cards identically.

## Acceptance Criteria

1. **Schema.** Given `src/yt_flow/domain/state.py`, then `CastMember` gains `pose_hint: NotRequired[str]` (import `NotRequired` from `typing` — stdlib, AD-1), documented as the 8.4 on-demand tier; `CastPose` is untouched (enum stays closed). `tests/domain/test_state_imports.py` `EXPECTED_FIELDS["CastMember"]` gains `"pose_hint"` and the guard stays green.
2. **Lenient parse.** Given 8.1's `parse_cast` in `scenario_chain.py`, then it implements the Interfaces parse rule: valid hint → stripped pass-through; invalid/absent → key omitted; all existing normalization (position/depth/pose/card_key) is unchanged, and every 8.1 parser test still passes byte-identically. Table-driven tests cover: valid hint, whitespace-padded hint, empty string, non-string, >80 chars, hint on an entry whose other fields are defaulted.
3. **Prompt contract.** Given `prompts/scenario/visual_breakdown.md` (as rewritten by 8.1), then it additionally teaches `pose_hint`: optional per cast member, free-text English ≤ 6 words, **only** when neither `standing` nor `sitting` can express the beat (examples: "kneeling over a corpse", "lying on operating table", "reaching toward the camera"); most shots must omit it; `pose` must still be set to the nearest base pose (the fallback). The pre-output self-check gains "pose_hint used sparingly (≤ ~3 distinct hints per scenario) and never as a substitute for `pose`". Rollout follows `docs/PROMPT_POLICY.md` exactly as 8.1 AC8 (repo file first, `candidate` seed via `scripts/migrate_prompts.py`, golden-set gate via `scripts/eval_prompts.py`, promotion is Jay's move, parser works against both prompt versions).
4. **Provisioning hook.** Given `src/yt_flow/services/run_service.py`, then a new `_ensure_special_pose_cards(scp_id, scenes) -> None` runs when the **scenario gate is approved** — in `resume_run` (`run_service.py:487-495`), before the graph resumes, when the pending gate's stage is `scenario` and the decision is approve (read `scenes` from the graph state snapshot, the same access `get_stage_artifacts` uses). It: collects distinct `(card_key, pose_hint)` pairs from all shots' cast (scene order, first-seen order); skips pairs whose `pose_hint_key` card already exists (`get_card`); generates the rest via AC5 up to the AC6 cap; and is wrapped in the same log-and-swallow envelope as `_ensure_character_reference` — **no failure in this function may fail or delay-fail the run** (AD-10). Idempotent by construction (cache-check first), so reject→revise→re-approve cycles and 1.10 resume paths need no special handling.
5. **Generation.** Given `CharacterService`, then a thin `generate_special_pose_card(card_key, pose_hint) -> str | None` reuses 8.2's machinery: prompt = visual_descriptor + pose_hint + the sprite requirements (studio background, full body, single subject — same `_compile_generation_prompt` path), IPAdapter reference = the card_key's **standing front card** (`angle_front_path`; no card row/front path → return `None` + warning, never t2i a stranger), one render, RGBA-validated at save (8.2 AC4), saved to `workspace/{card_key}/characters/hint_{sha}_front.png`, upserted into `character_cards` as `(scp_id, "hint:<sha>", "front")` via 8.2's `save_card`. Generation failure → `None` + warning; **no row is written on failure** (so a later run retries — mirrors 5-8's rollback rationale).
6. **Cost guardrails.** Given `src/yt_flow/config.py`, then `Settings` gains `special_pose_max_per_run: int = 3` (documented in `.env.example`); `_ensure_special_pose_cards` generates at most that many *new* cards per invocation (cache hits are free and don't count), logging a warning listing the skipped hints when the cap binds; and the hook is a **no-op when `settings.comfyui_mock` is true** (mock runs must never wait on or fake special-pose renders — stub-profile e2e behavior is unchanged).
7. **Resolver extension.** Given 8.3's `resolve_cast_cards`, then it implements the Interfaces resolution rule: hint hit → hint card (LLM angle selection skipped for that member); hint miss → base-pose resolution + one warning per distinct missed hint; members without `pose_hint` are resolved exactly as 8.3 shipped them (its tests stay green unmodified). Alpha validation covers hint cards (opaque hint card → the 8.3 AC10 hard error).
8. **No-hint runs are byte-identical.** Given a run whose scenario emits no `pose_hint` anywhere (including every pre-8.4 checkpoint and the un-promoted-prompt window), then `_ensure_special_pose_cards` does nothing, `resolve_cast_cards` output is unchanged, and no new warnings appear — verified by running 8.3's resolver/compose tests against the extended code.
9. **Gate visibility (D2 lesson).** Given the scenario stage artifact endpoint, then `pose_hint` is visible to a human at the scenario gate. 8.1 AC7's serializer emits each cast member dict whole (`sh.get("cast", [])`), so this holds automatically — add a test assertion that a cast member's `pose_hint` survives serialization, so a future field-whitelist refactor can't silently drop it (the exact D2 failure mode).
10. **Tests.** Given automated verification: `pose_hint_key` determinism + normalization (case/whitespace variants hash equal); parse table per AC2; `_ensure_special_pose_cards` unit tests with fake service seams (cache-hit skip, cap enforcement incl. warning, generation-failure swallow, mock-mode no-op, scenes-without-cast no-op) — extend `tests/stubs/fakes.py::patch_character_reference_seams`'s pattern with a special-pose seam so stub-profile smoke and e2e-stub API tests stay green; `generate_special_pose_card` service tests (mock provider: success upsert, opaque rejection, missing front card → `None`); resolver hint hit/miss tests in `test_character_angle_selector.py`. Always `workspace_path=str(tmp_path)` (memory: workspace-pollution trap). `uv run pytest tests/domain tests/pipeline/nodes/test_scenario_chain.py tests/services -q`, then full `uv run pytest -q`, green.

## Tasks / Subtasks

- [x] Task 1 — Schema + parser (AC: 1, 2)
  - [x] Add `pose_hint: NotRequired[str]` to `CastMember` in `src/yt_flow/domain/state.py`; update the drift guard (`tests/domain/test_state_imports.py`).
  - [x] Extend 8.1's `parse_cast` in `scenario_chain.py` with the pass-through rule (strip; drop unless non-empty `str` ≤ 80 chars); add the AC2 test table to `tests/pipeline/nodes/test_scenario_chain.py`.
- [ ] Task 2 — Prompt (AC: 3)
  - [ ] Add the `pose_hint` section + self-check line to `prompts/scenario/visual_breakdown.md`; seed `candidate` per PROMPT_POLICY; golden-set gate + hand-inspect one SCP-049 scenario for hint sparsity/quality; record evidence in Dev Agent Record. Do not touch the `production` label.
- [x] Task 3 — Cache key + generation (AC: 5, 10)
  - [x] `pose_hint_key(hint)` in `character_service.py` next to `_POSE_DESCRIPTIONS` — it is a service-layer storage-key concern, not pipeline state (stdlib `hashlib` only; 8.3's resolver and the hook both live behind the service boundary and import it from there, so `domain/` gains nothing from hosting it).
  - [x] `CharacterService.generate_special_pose_card(card_key, pose_hint)` per AC5, reusing 8.2's `generate_cards_from_descriptor` internals (provider call, RGBA save validation, `save_card` upsert) — one render, front-card reference, `None`-on-failure.
- [x] Task 4 — Provisioning hook (AC: 4, 6, 8)
  - [x] `Settings.special_pose_max_per_run: int = 3` (`config.py`, character settings block) + `.env.example` line.
  - [x] `_ensure_special_pose_cards(scp_id, scenes)` in `run_service.py` per AC4 (docstring: cite 5-8's pattern and this story); wire into `resume_run`'s scenario-approve path; `comfyui_mock` no-op guard first.
  - [x] Unit tests via the seam pattern (AC10); confirm `tests/pipeline/test_stub_profile_smoke.py` and `tests/api/test_e2e_stub_run.py` pass untouched.
- [x] Task 5 — Resolver extension (AC: 7, 8, 9)
  - [x] Extend `resolve_cast_cards`: hint lookup before base-pose resolution, per Interfaces; warnings per distinct missed hint.
  - [x] Hint hit/miss tests in `tests/services/test_character_angle_selector.py`; 8.3's existing tests must pass unmodified (AC8); serializer pass-through assertion (AC9).
- [ ] Task 6 — Live validation (AC: 3, 5)
  - [ ] Against real ComfyUI (memory: `$HOME/workspaces/ComfyUI`, `./run.sh`, :8188): generate one real special-pose card for SCP-049 (e.g. "kneeling over a corpse"), verify RGBA + framing + the pose actually reads, verify the cache hit on a second invocation; record file paths + evidence in Dev Agent Record.

### Review Findings

- [x] [Review][Patch] `pose_hint` is accepted but not provisioned, generated, resolved, capped, or tested [src/yt_flow/services/character_service.py]
- [x] [Review][Patch] `pose_hint` is documented in visual_breakdown but not in the authoritative cast emitter [prompts/scenario/cast_decision.md]
- [x] [Review][Patch] `cast_decision_step` silently drops malformed, duplicate, or out-of-range sentence mappings [src/yt_flow/pipeline/nodes/scenario_chain.py]
- [x] [Review][Patch] Recoverable cast enum casing/whitespace degrades to defaults [src/yt_flow/pipeline/nodes/scenario_chain.py]
- [x] [Review][Patch] Non-string chapter card title/kicker values are coerced to repr text [src/yt_flow/pipeline/nodes/scenario_chain.py]

## Dev Notes

### Why the hook lives at scenario-gate approval

`pose_hint` does not exist until the scenario stage has run, so 5-8's pre-graph placement is impossible. The scenario gate is the earliest point where (a) the hints exist, (b) a human has *just reviewed the cast at the gate* (8.1 AC7 / this story's AC9 — bad hints get caught before money is spent), and (c) the image stage hasn't started, so by the time video_node resolves cards the renders are long done. The hook blocks the approve→resume path for at most `special_pose_max_per_run` renders; that is the same blocking posture 5-8 already takes at `start_run` and Jay accepted there. No background queue, no job table — resolver-side fallback (AC7) makes a missed/slow card benign, which is what permits this simplicity. `# ponytail:` the hook is deliberately NOT invoked on `resume_run_from_failure`/`full_restart_run` — the cache-check makes re-provisioning free on the happy path, and a run that failed past scenario either already has its cards or degrades gracefully.

### Why one front-angle card per hint

A special pose is per-scene key art: it appears in one or two shots, composed by the same depth/position machinery as any card. Four angles would quadruple cost for angle variety no shot has asked for; the resolver simply pins `angle="front"` for hint cards. If a real scenario ever demands an angled special pose, the storage key `(scp_id, "hint:<sha>", angle)` already accommodates it — generation scope is the only thing that grows.

### Trust boundary on LLM-authored hints

The hint goes into an image-generation prompt only — never a shell, path, or SQL context (the filename uses the sha, not the text; the DB value is the sha-keyed pose string). The 80-char parse cap bounds prompt injection surface at "weird picture", which the gate human and the RGBA/framing validation both catch. This is the same trust level 5-12's descriptor enrichment already accepted for descriptors.

### Current Code State — files to read before editing

- `src/yt_flow/services/run_service.py:368-444` — `_ensure_character_reference` (the pattern: session bootstrap, existence-check-first, log-and-swallow envelope); `resume_run` (487-495) — the hook site; `get_stage_artifacts` (60+) — the state-snapshot access pattern for reading `scenes`.
- `src/yt_flow/services/character_service.py` — post-8.2: `generate_cards_from_descriptor`, `save_card`/`get_card`, `_POSE_DESCRIPTIONS`, `_compile_generation_prompt`; post-8.3: `resolve_cast_cards`.
- `src/yt_flow/domain/state.py` — post-8.1 `CastMember`; `src/yt_flow/db/models.py` — post-8.2 `CharacterCard`.
- `src/yt_flow/config.py:38` — `comfyui_mock`; character settings block (~73-88) for the new cap field.
- `prompts/scenario/visual_breakdown.md` — post-8.1 rewrite (cast schema section, self-check).
- `tests/stubs/fakes.py:130` — `patch_character_reference_seams` (the seam pattern to extend).

### Preserved behavior (do not break)

- **8.1/8.2/8.3 contracts verbatim**: closed `CastPose` enum; `character_cards` keying; `resolve_cast_cards` base-pose semantics incl. standing fallback; alpha hard-fail. This story only *adds* a lookup tier and a hook.
- **5-8's `_ensure_character_reference`** — untouched; the new hook is a sibling, not a modification.
- **Gate approve latency envelope**: cap defaults to 3 renders; a human just clicked approve and 5-8 set the precedent that provisioning may block briefly. If Jay finds it slow in practice, lower the cap — do not build async machinery speculatively.
- **Mock/stub profiles**: `comfyui_mock=true` short-circuits the hook (AC6); stub e2e suites pass with zero fixture changes beyond the seam addition.
- **Old checkpoints / old prompt**: no `pose_hint` anywhere → AC8 byte-identical guarantee.

### Architecture compliance

- AD-1: `pose_hint` is stdlib typing in `domain/`; hook + generation stay in `services/`; the resolver extension rides 8.3's existing injection seam — no new cross-layer imports.
- AD-2: `pose_hint` is a plain optional string in checkpoint state; hint cards are DB/filesystem artifacts, never written back into state.
- AD-10: provisioning is best-effort non-fatal end to end; only the pre-existing opaque-asset error class fails a stage.

### Testing standards

Pure-function tests for key/parse; seam-mocked service/hook tests (no real ComfyUI/LLM in units); one mandatory live-ComfyUI validation task with recorded evidence (5-10/8.2 precedent — pose quality is an eyes-on judgment). Always `workspace_path=str(tmp_path)`.

### Ponytail note

One optional TypedDict key, one hash function, one service method that reuses 8.2's generation path, one hook that reuses 5-8's envelope, one int setting. No new table (8.2's keying absorbs hint cards by design), no queue, no retry/TTL/cleanup machinery, no per-hint status tracking (the row's existence IS the status), no hint-quality LLM judge. The cap is a constant-with-a-config-field, not a budgeting subsystem.

## Project Structure Notes

- Modified: `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py` (parser), `src/yt_flow/services/character_service.py`, `src/yt_flow/services/run_service.py`, `src/yt_flow/config.py`, `.env.example`, `prompts/scenario/visual_breakdown.md`, tests (`test_state_imports.py`, `test_scenario_chain.py`, `test_character_angle_selector.py`, `tests/services/` hook tests, `tests/stubs/fakes.py`).
- No new runtime modules, no schema migration (reuses 8.2's `character_cards`).
- Sequencing: strictly after 8.1+8.2+8.3 (depends_on is real); it touches the same hot files as all three — rebase, don't parallel-edit (memory: repeated shared-file collisions).

## References

- `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` — CastMember schema, closed `CastPose`, parser leniency rules this story extends.
- `8-2-character-card-sprite-pipeline.md#Interfaces` #4 — normative pose-aware storage (`character_cards`, `hint:*` keys reserved for this story) + RGBA sprite contract; AC7 `generate_cards_from_descriptor`.
- `8-3-bg-only-generation-multicard-compositing.md` — `resolve_cast_cards` contract + fallback posture this story extends; alpha validation.
- `src/yt_flow/services/run_service.py:368-444` — 5-8/5-10 `_ensure_character_reference` (the provisioning pattern).
- `docs/PROMPT_POLICY.md` — prompt change protocol (AC3).
- `_bmad-output/planning-artifacts/epics.md#Story 8.4` — epic draft.
- Memory: `reference_comfyui_local`, `project_test-isolation-workspace-pollution`, `project_5-8-review-done` (provisioning pattern history).

## Dev Agent Record

### Agent Model Used

### Debug Log References

- Task 1 red test: `uv run pytest tests/domain/test_state_imports.py tests/pipeline/nodes/test_scenario_chain.py -q` failed as expected before implementation (`CastMember` missing `pose_hint`; parser did not preserve valid hints).
- Task 1 green test: `uv run pytest tests/domain/test_state_imports.py tests/pipeline/nodes/test_scenario_chain.py -q` → `88 passed`.
- Task 1 regression: `uv run pytest -q` → `841 passed, 1 skipped, 1 warning`.
- Task 2 candidate seed: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` → `created: scenario/visual_breakdown` and other prompts skipped.
- Task 2 golden-set gate: `uv run python scripts/eval_prompts.py --label candidate --baseline production` → `FAIL`; all three items failed because Langfuse baseline could not fetch `scenario/cast_decision` with `production` label. Story says not to touch `production`, so Task 2 cannot be completed in this run without external Prompt Hub correction/approval.
- Code review patch verification: `uv run pytest tests/domain/test_state_imports.py tests/pipeline/nodes/test_scenario_chain.py tests/services/test_character_service_generation.py tests/services/test_character_angle_selector.py tests/services/test_run_service_character_provisioning.py tests/api/test_stage_artifacts.py -q` → `231 passed, 1 warning`.
- Stub/e2e regression: `uv run pytest tests/pipeline/nodes/test_scenario.py tests/pipeline/test_stub_profile_smoke.py tests/api/test_e2e_stub_run.py -q` → `19 passed, 1 warning`.
- Full regression: `uv run pytest -q` → `912 passed, 1 skipped, 1 warning`.
- Lint: `uv run ruff check .` → `All checks passed!`.

### Completion Notes List

- Task 1: Added the optional `pose_hint` CastMember field and lenient parser pass-through/drop behavior, with table tests for valid, stripped, empty, non-string, overlong, and defaulted-field cases.
- Code review patches: implemented deterministic `hint:*` keying, special-pose generation, scenario-approval provisioning with cap/mock/no-op behavior, resolver hint hit/miss fallback, cast-decision coverage validation, enum whitespace/case normalization, and scenario artifact `pose_hint` visibility.
- Remaining: Task 2 prompt rollout still needs a passing Langfuse golden-set gate, and Task 6 live ComfyUI pose-quality validation remains open.

### File List

- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `tests/domain/test_state_imports.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `src/yt_flow/config.py`
- `.env.example`
- `src/yt_flow/services/character_service.py`
- `src/yt_flow/services/run_service.py`
- `prompts/scenario/cast_decision.md`
- `tests/api/test_stage_artifacts.py`
- `tests/services/test_character_angle_selector.py`
- `tests/services/test_character_service_generation.py`
- `tests/services/test_run_service_character_provisioning.py`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Change Log

- 2026-07-06: Story created — pose dimension added per Jay (industry-standard sprite-library tiering). This story owns the on-demand tier: `pose_hint` schema extension, deterministic `hint:*` cache keys in 8.2's `character_cards`, the scenario-gate provisioning hook (5-8 pattern), the per-run cap, and the resolver hint lookup.

## Saved Questions / Clarifications

1. **Hint quality gate.** The scenario-gate human sees `pose_hint` values (AC9) but nothing enforces they act on them; a nonsense hint costs one render and degrades to base pose. If wasted renders become a pattern, the cheap fix is surfacing "N special cards will be generated on approve" in the gate UI — UI story, not this one.
2. **Cap scope for A/B pairs.** `special_pose_max_per_run` is per run; an A/B pair can spend 2× the cap (though identical hints across legs are cache hits, so in practice the second leg is usually free). If Jay wants a per-episode budget instead, it needs a shared counter — deferred until it actually bites.
3. **Sitting-as-hint overlap.** The prompt says "use `pose` for base poses", but the LLM may still emit `pose_hint: "sitting on chair"`. The hash key makes this a harmless duplicate card, not a bug. A normalization pass (hint ≈ base pose → drop hint) is possible but adds a synonym problem — skipped deliberately (`# ponytail:`), revisit only if duplicate-ish cards show up in practice.
4. **Derived-entity special poses.** `generate_special_pose_card` requires an existing standing front card as the identity anchor; an unseeded derived entity (`SCP-049-2` never carded) gets `None` + warning — same gap as 8.2 Saved Question #1, same resolution path once Jay rules on unattended derived-entity generation.
