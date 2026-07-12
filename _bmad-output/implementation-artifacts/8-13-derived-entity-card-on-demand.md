---
created: 2026-07-10
baseline_commit: 7244668bc3342321f8bfe7832361209a4f9c17e2
story_key: 8-13-derived-entity-card-on-demand
story_id: "8.13"
epic: 8
previous_story: 8-12-cast-placement-scale-calibration
depends_on:
  - 8-2-character-card-sprite-pipeline     # generate_cards_from_descriptor — the actual reused generator
  - 8-4-on-demand-special-pose-cards       # trigger-timing precedent (_ensure_special_pose_cards pattern), not the generator itself
  - 8-10-cast-decision-split-call          # cast_decision.md's <scp_id>-<n> vocabulary this story finally implements
  - 8-6-asset-library-management           # draft/approved lifecycle, style_epoch, manifest registration
related:
  - 8-3-bg-only-generation-multicard-compositing  # cast card resolution this story feeds (unblocks the SCP-049-2-class skip)
workflow_decision: "Reuse CharacterService.generate_cards_from_descriptor (Story 8.2) via a new post-scenario provisioning pass modeled on _ensure_special_pose_cards (Story 8.4). No new workflow stage, no new generator function."
evidence: "Iteration 1 run d55a265b: cast_decision assigned card_key='SCP-049-2' to 10 shots per its own taught vocabulary; no Character row exists for it; video_node logged 'no character row for cast member SCP-049-2, skipping' ×10 — narration referencing the reclassified entity played over an empty background. Jay chose on-demand generation over restricting the vocabulary (2026-07-10)."
---

# Story 8.13: Derived-Entity Card On-Demand Generation

Status: done

## Story

As Jay,
I want a card automatically generated the first time cast_decision references a derived entity (`<scp_id>-<n>`, e.g. `SCP-049-2`),
so that narration about a reclassified/duplicate entity actually shows something on screen instead of silently skipping every shot that references it.

## Context — the gap, and why 8.4's own generator can't be reused directly

`prompts/scenario/cast_decision.md` explicitly teaches the LLM: "A duplicate/offshoot of the entity uses `card_key: <scp_id>-<n>`, e.g. `SCP-049-2`." The LLM did exactly that on a real SCP-049 run — and nothing ever created that card. `video_node`'s cast resolver (`resolve_cast_cards`, `CharacterService`) has no row for `SCP-049-2` and logs a skip for every shot referencing it (confirmed 10/10 in the iteration-1 run).

The obvious reuse candidate, `generate_special_pose_card` (Story 8.4), **cannot** be used here: it hard-requires an existing `Character` row with a standing front card for the *same* `card_key` (`character.angle_front_path`, character_service.py:850) — by design, since it's for a new pose of a card that already exists. A derived entity has no row at all under its own key; that's the whole problem.

The correct reuse target is `CharacterService.generate_cards_from_descriptor(card_key, descriptor, *, pose, anchor_path, angles)` (Story 8.2, character_service.py:773) — it already:
- creates a new `Character` row via `_ensure_character(card_key)` if none exists (works unmodified for `card_key="SCP-049-2"`),
- accepts an `anchor_path` to condition the front-angle generation on an existing image (this is the "family resemblance to the base entity" mechanism — pass the base entity's own approved front card),
- generates the full angle set and persists `angle_*_path` columns exactly like a fresh 8.2 character.

So this story is primarily **wiring**, not new generation logic: detect the gap, gather the two inputs `generate_cards_from_descriptor` needs (a descriptor, an anchor), and call it. Timing/orchestration should mirror `_ensure_special_pose_cards` (Story 8.4, run_service.py:459) — a best-effort, capped, post-scenario provisioning pass, AD-10 non-fatal.

## Acceptance Criteria

1. New post-scenario provisioning function (parallel to `_ensure_special_pose_cards`, called alongside it from the same site in `start_run`): scans `scenes` for cast `card_key` values matching the derived-entity pattern (`<scp_id>-<n>`, i.e. the run's own `scp_id` followed by `-` and digits) that have no existing `Character` row (`check_existing_character` returns `None`).
2. For each distinct missing derived `card_key` (dedup — a derived entity referenced in 5 shots is generated once): resolve inputs —
   - `anchor_path`: the base entity's (`scp_id`) approved standing-front card path, if one exists (`check_existing_character(scp_id).angle_front_path`). If the base entity has no front card either, degrade to no-anchor generation (t2i from descriptor alone) — do not block on the base card; log a WARNING noting the missing family-resemblance anchor.
   - `descriptor`: pull the derived entity's textual description from the scenario artifact — check what visual_breakdown/cast_decision sidecar data actually carries this (the story draft in epics.md assumed "visual_breakdown sidecar" — verify the exact field during implementation; if no derived-specific description exists anywhere in scene state, fall back to the base entity's own `visual_descriptor` + a generic "reclassified/duplicate instance" qualifier).
3. Call `generate_cards_from_descriptor(card_key, descriptor, pose="standing", anchor_path=anchor_path)` — full angle set, matching a normal 8.2 character creation. Capped at `Settings.derived_entity_max_per_run: int = Field(2, ge=0)` (env `YTFLOW_DERIVED_ENTITY_MAX_PER_RUN`) distinct derived entities per run; excess logs a WARNING (naming the skipped keys) and degrades — cast resolution falls back to its existing skip behavior for anything over the cap, never fails the run (AD-10, matching 8.4's `special_pose_max_per_run` precedent exactly).
4. Any generation failure for one derived entity (provider error, missing descriptor, etc.) degrades to skip for that key only — never fails the run (AD-10, same try/except envelope as `_ensure_special_pose_cards`).
5. Successfully generated cards register in the 8.6 asset registry the same way pipeline-auto-generated 8.2 cards do today (draft→approved-direct per the existing precedent — no new lifecycle branch).
6. `resolve_cast_cards` needs no changes if the `Character` row + angle paths now exist — verify this is actually true (the resolver should already find any `card_key` with a matching row); if it turns out to have `scp_id`-shaped assumptions that reject a `-2` suffix, fix those as part of this story (should be data-driven, not pattern-restricted, but confirm against the real code, don't assume).
7. Live verification: re-run (or replay against a checkpoint of) the SCP-049 scenario that produced the `SCP-049-2` gap; confirm a card gets generated, registered, and actually appears composited in the relevant shots — no more skip-logging for that key.
8. Tests: derived-key detection (dedup, pattern matching, existing-row exclusion), cap enforcement, anchor-missing degrade path, generation-failure degrade path, mocked `generate_cards_from_descriptor` call assertions (correct card_key/descriptor/anchor_path passed).

## Tasks / Subtasks

- [x] Task 0: Read `resolve_cast_cards` fully to confirm AC:6's assumption before writing any generation code
- [x] Task 1: Derived-key scan + dedup helper (AC:1)
- [x] Task 2: Descriptor/anchor resolution — locate the actual source field for a derived entity's description (AC:2)
- [x] Task 3: Provisioning function wired into `resume_run` alongside `_ensure_special_pose_cards`, with cap + AD-10 envelope (AC:3,4)
- [x] Task 4: Confirm/fix `resolve_cast_cards` for `-N` suffixed keys if needed (AC:6)
- [x] Task 5: Tests (AC:8)
- [x] Task 6: Live verification (AC:7)

## Dev Notes

- **Scope guard:** this story does not touch `cast_decision.md`'s vocabulary (Jay explicitly chose generation over restriction) and does not touch 8.12's placement/scale calibration — those are independent.
- Naming collision risk: confirm the derived-key regex doesn't false-positive on anything else the prompt vocabulary might emit — currently only entities use `<scp_id>-<n>`; stock cast (`STOCK-*`) and hint-pose keys (`hint:<sha>`) use different prefixes, so a simple `f"{scp_id}-\\d+$"` match should be safe, but verify against real `parse_cast` output.
- **ponytail:** one detection helper + one thin wrapper around an existing generator, mirroring an existing orchestration pattern (8.4) almost line-for-line. Resist the urge to build a general "unknown card_key" framework — this story is specifically the `<scp_id>-<n>` shape the prompt already commits to.

### Project Structure Notes

- Modify: `src/yt_flow/services/run_service.py` (new provisioning function + wiring), `src/yt_flow/config.py` (`derived_entity_max_per_run`)
- Verify/possibly modify: `src/yt_flow/services/character_service.py` (`resolve_cast_cards`, AC:6)
- Tests: alongside existing `_ensure_special_pose_cards`/`generate_cards_from_descriptor` test fixtures

### References

- [Source: src/yt_flow/services/character_service.py:773-841] — `generate_cards_from_descriptor`, the generator this story calls
- [Source: src/yt_flow/services/character_service.py:842-909] — `generate_special_pose_card`, confirmed NOT reusable here (requires existing identity)
- [Source: src/yt_flow/services/run_service.py:459-506] — `_ensure_special_pose_cards`, the orchestration pattern this story mirrors
- [Source: prompts/scenario/cast_decision.md] — `<scp_id>-<n>` vocabulary this story finally backs with real generation
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — SCP-049-2 skip evidence

## Change Log

- 2026-07-12: Implemented `_ensure_derived_entity_cards` (run_service.py) + `derived_entity_max_per_run` config, wired into `resume_run`'s scenario-approve path; added test coverage (AC1-6,8); live-verified against real run `d55a265b` with a live ComfyUI (AC7); full regression suite green (1310 passed, 1 skipped).
- 2026-07-12: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) found a real bug — a swallowed generation failure (no exception raised, just no front card produced) left a permanent un-retryable stub `Character` row. Fixed by checking `angle_front_path` after generation and rolling back the stub on miss (mirrors `_ensure_character_reference`'s existing precedent), plus a misleading log-message fix and a minor `_abs_asset_path` reuse cleanup. Added a regression test for the rollback. Four lower-severity findings (missing scene/shot isinstance guard, TOCTOU race, per-call cap, held-open DB session) deferred as pre-existing patterns shared with `_ensure_special_pose_cards`/`_ensure_character_reference` — see Review Findings below and `deferred-work.md`.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5

### Debug Log References

None — no failures requiring debug iteration.

### Completion Notes List

- **Wiring site correction (Task 3):** the story text assumed `_ensure_special_pose_cards` is called from `start_run`. Reading the real code (Task 0) showed it's actually called from `resume_run`'s scenario-approve branch (`run_service.py`, after `values = snap.values or {}`) — that's the true post-scenario-approval site, so `_ensure_derived_entity_cards` is wired there instead, called alongside it.
- **AC:6 confirmed true, no code change:** `resolve_cast_cards`/`check_existing_character` key off `card_key`/`scp_id` as opaque strings with a plain equality lookup — no regex or shape assumption anywhere. Added `test_derived_entity_key_resolves_once_character_row_exists` (`test_character_angle_selector.py`) to lock this in as a regression guard rather than leaving it as an unverified read-time observation.
- **AC:2 descriptor source confirmed absent:** verified `parse_cast`/`CastMember` (scenario_chain.py) and `cast_decision.md`'s output schema carry no per-cast-member description field at all — only `card_key`/`position`/`depth`/`pose`/`pose_hint`/motion/movement fields. Implemented the fallback path directly (base entity's `visual_descriptor` + a generic reclassified/duplicate qualifier) rather than a dead lookup for a field that doesn't exist.
- **Detection uses plain string ops, not regex:** `card_key.startswith(f"{scp_id}-")` + `.isdigit()` on the remainder — simpler than a compiled pattern for this one shape, ponytail-preferred.
- **Cap pattern mirrors `special_pose_max_per_run` exactly:** plain `int = 2` field (no `Field(ge=0)`), `max(0, settings.derived_entity_max_per_run)` guard at the call site — matches the existing 8.4 precedent instead of introducing a new validation style.
- **Live verification (AC:7):** replayed the real completed run `d55a265b` (SCP-049, the actual run that produced the iteration-1 `SCP-049-2` skip) against a live local ComfyUI. Confirmed: a `Character` row for `SCP-049-2` is created with all 4 angles generated (i2i, anchored to `SCP-049`'s own front card), registered in the asset library via the existing `generate_candidates_from_reference` path (no new registration code needed, AC:5), and all 10 real shots that previously logged "no character row for cast member SCP-049-2, skipping" now resolve `SCP-049-2` in their cast cards via a real (unmocked) `resolve_cast_cards` call.
- Full regression suite: 1310 passed, 1 skipped, 0 failed.

### File List

- `src/yt_flow/config.py` — added `derived_entity_max_per_run: int = 2`
- `src/yt_flow/services/run_service.py` — added `_ensure_derived_entity_cards`; wired into `resume_run` alongside `_ensure_special_pose_cards`
- `tests/services/test_run_service_character_provisioning.py` — derived-entity provisioning tests (mock-mode skip, no-op, dedup, existing-row skip, anchor resolution, missing-anchor degrade, cap+warning, generation-failure degrade, `resume_run` wiring)
- `tests/services/test_character_angle_selector.py` — added `test_derived_entity_key_resolves_once_character_row_exists` confirming AC:6

### Review Findings

- [x] [Review][Patch] Generation failure leaves a permanent, un-retryable stub `Character` row [src/yt_flow/services/run_service.py:59,84-92] — `generate_cards_from_descriptor` never raises on a total generation failure (every angle fails inside `generate_candidates_from_reference`, which swallows its own errors), it just returns `angle_front_path=None` on an already-created row. The dedup check (`check_existing_character(key) is None`) then treats that row as "already provisioned" forever, unlike the codebase's own precedent (`_ensure_character_reference`, run_service.py:450-454) which deletes the row and re-raises on total failure specifically so a future run retries. Fixed to check `angle_front_path` after generation and delete+retry-eligible on miss.
- [x] [Review][Patch] Misleading warning when the base entity has no `Character` row at all vs. merely no front card [src/yt_flow/services/run_service.py:70-78] — the log text unconditionally says "has no front card" even when `base is None` (no row exists at all). Fixed to distinguish the two cases.
- [x] [Review][Patch] Manual `Path(settings.assets_path) / base.angle_front_path` duplicates `CharacterService._abs_asset_path` [src/yt_flow/services/run_service.py:73] — reuses the existing helper instead.
- [x] [Review][Defer] No `isinstance` guard on `scene`/`shot` (only `member` is guarded) [src/yt_flow/services/run_service.py:41-53] — deferred, pre-existing pattern copied verbatim from `_ensure_special_pose_cards` (same gap exists there too); AD-10 envelope already prevents a run failure, just degrades the whole derived-entity pass instead of skipping one bad record.
- [x] [Review][Defer] TOCTOU race on concurrent `resume_run` calls for the same run [src/yt_flow/services/run_service.py:59-92] — deferred, mirrors the accepted risk pattern `_ensure_character_reference` already documents via its own `ponytail:` comment (no distributed lock; add one if duplicate-provisioning races become frequent enough to matter).
- [x] [Review][Defer] `derived_entity_max_per_run` cap is enforced per function call, not per run [src/yt_flow/services/run_service.py:62-64] — deferred, mirrors `_ensure_special_pose_cards`'s identical per-call cap design; only reachable if the scenario gate is rejected and re-approved (re-entering this call site), an existing edge case shared with the sibling function, not unique to this story.
- [x] [Review][Defer] DB session held open across sequential ComfyUI-bound generation calls [src/yt_flow/services/run_service.py:57-91] — deferred, mirrors `_ensure_special_pose_cards`'s identical session-scoping pattern; local SQLite, negligible contention.
