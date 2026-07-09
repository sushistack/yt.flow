---
created: 2026-07-10
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

Status: ready-for-dev

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

- [ ] Task 0: Read `resolve_cast_cards` fully to confirm AC:6's assumption before writing any generation code
- [ ] Task 1: Derived-key scan + dedup helper (AC:1)
- [ ] Task 2: Descriptor/anchor resolution — locate the actual source field for a derived entity's description (AC:2)
- [ ] Task 3: Provisioning function wired into `start_run` alongside `_ensure_special_pose_cards`, with cap + AD-10 envelope (AC:3,4)
- [ ] Task 4: Confirm/fix `resolve_cast_cards` for `-N` suffixed keys if needed (AC:6)
- [ ] Task 5: Tests (AC:8)
- [ ] Task 6: Live verification (AC:7)

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

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
