---
created: 2026-07-08
baseline_commit: 2fe45aa8fe75b5a578e4dd724635a727e8eab889
story_key: 8-10-cast-decision-split-call
story_id: "8.10"
epic: 8
previous_story: 8-3-bg-only-generation-multicard-compositing
depends_on:
  - 8-1-shot-cast-metadata-bg-prompts       # replaces its visual_breakdown cast-authoring responsibility
  - 8-3-bg-only-generation-multicard-compositing  # the consumer this unblocks (cast was always [] until now)
blocks: []
related:
  - 8-1-shot-cast-metadata-bg-prompts       # documented the 0/125 cast-population gap this story fixes
---

# Story 8.10: Split Cast Decision Into Its Own LLM Call

Status: done

## Story

As Jay,
I want cast-per-shot decided by a small, focused LLM call instead of being bundled into the same call that composes the 8-slot cinematography prompt,
so that `cast` actually gets populated in real runs — Story 8.1 shipped the schema and Story 8.3 shipped the compositor, but neither could be validated live because the combined call never emitted `cast` at all.

## Context

Discovered mid-flight during Story 8.3's Task 6 live validation (AC13 DoD): before spending GPU time on a live SCP-049 A/B re-render, a sanity check on the actual candidate prompt's real output confirmed 8.1's own hand-inspection finding (0/125 shots got a non-empty `cast`, documented in `8-1-shot-cast-metadata-bg-prompts.md`'s Dev Agent Record) was still true, and root-caused it precisely.

**Root cause (systematic-debugging Phase 1-3, reproduced live against the exact production call shape — see Debug Log References):**

`deepseek-v4-flash`, given the candidate `scenario/visual_breakdown` prompt (which explicitly instructs a `cast` array and forbids describing people in `image_prompt`), reliably ignores both instructions. It emits the *exact schema field name from the prompt's pre-8.1 version* — `"entity_visible": true/false`, a field that appears nowhere in the current prompt text — and writes full character prose directly into `image_prompt` (e.g. "D-9341, a gaunt man with a shaved head..."). This is not a parsing bug: `parse_cast()` correctly defaults a missing `cast` key to `[]`; the model's raw JSON genuinely never contains the key.

Ruled out during investigation:
- **Not a Langfuse seeding bug** — fetched the live `candidate` label directly; content matches the repo file exactly (version 2).
- **Not `response_format`/temperature drift** — reproduced with the exact production `_call_deepseek` call shape (`response_format: json_object`, no temperature override).
- **Not "thinking mode"** — `deepseek-v4-flash` supports a `"thinking": {"type": "disabled"}` request param (confirmed via a real 400 on `tool_choice` forcing, which surfaced this). Disabling it does **not** fix the schema drift — same `entity_visible` output either way. (Also confirmed `response_format: json_schema` and forced `tool_choice` are both unavailable on this account/model — DeepSeek only supports loose `json_object` mode here, so schema enforcement via API params isn't an option.)
- **Not a model-capability ceiling** — a trivial isolated prompt ("here's one shot, populate cast with card_key=Bob") gets the schema exactly right, every time.

**Confirmed hypothesis:** the failure is specific to competing with the visual_breakdown prompt's size/complexity (12KB, 8-slot composition rules, multiple few-shot examples, a mandatory self-check checklist). A small, focused, isolated call whose *only* job is deciding cast per sentence — given the same numbered sentences, entity/stock `card_key` vocabulary, and `characters_present` context — reliably produces correct `cast` JSON. Verified with the actual production narration content (Korean SCP-049 interview scene): correctly identified the entity, correctly inferred `"sitting"` for a D-class described as tied to a chair, correctly placed the researcher as a background observer.

**The fix is architectural, not more prompt text on the combined call**: split cast decision into its own LLM call (`cast_decision_step`, new `prompts/scenario/cast_decision.md`) that runs *before* `visual_breakdown_step` per scene. Its result is then fed into `visual_breakdown_step` as a fixed, already-decided input (`{{cast_by_sentence}}`) — the model no longer needs to *decide and emit* a schema-compliant `cast` array while also composing prose; it only needs to avoid describing the pre-decided people. `visual_breakdown_step` itself attaches the authoritative cast onto each returned shot by `sentence_start`, regardless of anything the model echoes in its own JSON — robust by construction, not by hoping the model behaves.

Live re-validation with the real fix in place, same production call shape, same SCP-049 scene: **all 3 shots correctly populated `cast`, and every `image_prompt` was genuinely background-only** — no body/face/clothing text anywhere. See Dev Agent Record.

## Acceptance Criteria

1. **New focused cast-decision step.** `scenario_chain.py` gains `cast_decision_step(scp_id, scene, sentences, s, call_deepseek, *, label=None) -> dict[int, list]`, calling a new Langfuse prompt `scenario/cast_decision` and returning `{sentence_number: raw_cast_list}` (1-based). Raises `ValueError` on a non-1:1 sentence-to-entry count mismatch (matches `visual_breakdown_step`'s existing strictness); tolerates malformed individual entries (non-dict, non-int sentence number) by skipping them, not failing the whole call.
2. **`visual_breakdown_step` consumes pre-decided cast.** Gains a `cast_by_sentence` parameter (4th positional, before `frozen_descriptor`), compiles it into the prompt as `{{cast_by_sentence}}` JSON, and — after parsing the model's shots — attaches `cast_by_sentence.get(shot["sentence_start"], [])` onto every returned shot dict, overwriting anything the model itself emitted for that key. The model's own output schema no longer includes `cast` at all.
3. **`prompts/scenario/visual_breakdown.md` rewritten** to remove the cast-authoring responsibility: "Card Vocabulary" section replaced with "Pre-Decided Cast" (renders `{{cast_by_sentence}}`, explains the model must never describe a sentence's decided cast in prose); "Cast, Placement & Background-Only Rules" section shrunk to a background-only reference note (worked example + two few-shot patterns, no cast-deciding instructions); output-format JSON schema and self-check checklist drop every cast-authoring bullet. `stock_cast_keys` variable removed from `visual_breakdown_step`'s compiled variables (no longer referenced in that prompt).
4. **New `prompts/scenario/cast_decision.md`** — short, focused prompt: card vocabulary, `characters_present`, numbered sentences, and the same four-field cast schema (`card_key`/`position`/`depth`/`pose`) 8.1 defined, asking only for `{"shots": [{"sentence": N, "cast": [...]}]}`.
5. **`scenario.py` orchestration wired.** `_breakdown_for` calls `cast_decision_step` before `visual_breakdown_step` per scene (same `label` gating as every other stage — this is still an all-or-nothing per-run A/B toggle, not independently promotable) and threads its result through.
6. **Both prompts seeded as `candidate`** via `uv run python scripts/migrate_prompts.py --source prompts --label candidate` (note: `--source prompts`, not `--source prompts/scenario` as `docs/PROMPT_POLICY.md` currently documents — the latter drops the `scenario/` name prefix; a doc fix is flagged, not fixed, here since it's pre-existing and orthogonal).
7. **Live re-validation.** The real `cast_decision_step` + `visual_breakdown_step` pair, called against the real DeepSeek API with the real seeded `candidate` prompts, on the same production narration used to diagnose the bug, produces populated `cast` on every shot with a background-only `image_prompt` (no body/face/clothing/designator text). Recorded in Dev Agent Record.
8. **Tests.** `test_scenario_chain.py`: new tests for `cast_decision_step` (happy path, count-mismatch rejection, malformed-entry tolerance, non-list-cast tolerance) and for `visual_breakdown_step`'s cast-attachment behavior; existing `visual_breakdown_step` call sites and the placeholder-presence test updated for the new signature/schema. `test_scenario.py`: `_stub_chain` and all bespoke chain-mocking blocks updated to stub `cast_decision_step`; positional `fake_visual` signatures updated for the new `cast_by_sentence` parameter. `tests/stubs/fakes.py` gains a `deepseek_cast_decision.json` cassette and a `_STAGE_CASSETTES` entry so the existing stub-profile / E2E-stub-run tests (which exercise the real chain end-to-end against fakes) keep working. `uv run pytest -q` fully green; `ruff check .` clean.

## Tasks / Subtasks

- [x] Task 1 — `cast_decision_step` + new prompt (AC: 1, 4, 6)
  - [x] Implement `cast_decision_step` in `scenario_chain.py`.
  - [x] Write `prompts/scenario/cast_decision.md`.
  - [x] Seed both prompts as `candidate` (`--source prompts`, not `prompts/scenario` — see AC6 note).
- [x] Task 2 — `visual_breakdown_step` + prompt rewrite (AC: 2, 3)
  - [x] Add `cast_by_sentence` parameter; compile it into the prompt; attach onto returned shots post-parse.
  - [x] Rewrite `prompts/scenario/visual_breakdown.md`'s cast sections; drop `stock_cast_keys` from compiled variables.
- [x] Task 3 — orchestration wiring (AC: 5)
  - [x] `scenario.py`'s `_breakdown_for` calls `cast_decision_step` before `visual_breakdown_step`, same `label` gating.
- [x] Task 4 — tests + stub fixtures (AC: 8)
  - [x] `test_scenario_chain.py`: new `cast_decision_step` tests; updated `visual_breakdown_step` call sites/schema test.
  - [x] `test_scenario.py`: `cast_decision_step` stubbed everywhere `visual_breakdown_step` is; positional fake signatures updated.
  - [x] `tests/stubs/fakes.py`: new cassette + `_STAGE_CASSETTES` entry.
  - [x] Full suite green (834 passed, 1 skipped), ruff clean.
- [x] Task 5 — live re-validation (AC: 7)
  - [x] Real `cast_decision_step` + `visual_breakdown_step` call against real DeepSeek + real seeded `candidate` prompts on the production narration used for root-cause diagnosis — cast populated on all 3 shots, image_prompt genuinely background-only.

## Dev Notes

### Why split, not more prompt engineering

8.1 already tried the "more prompt text" route twice (a "CRITICAL RULE" callout + worked example, then a second pass removing contradictory body-prose examples and adding cast-populated JSON few-shots) and the result was identical both times: 0/125 shots got `cast`. The systematic-debugging process here found the actual mechanism — schema drift toward a pre-existing, semantically-obvious legacy field name — which is not something more instructions on the *same* call fixes; competing task complexity is the variable that matters, confirmed by the isolated-call test succeeding on the first try with a much shorter prompt.

### Architecture note

This is intentionally NOT folded back into `visual_breakdown_step`'s own schema as an echo-and-validate pattern (i.e. asking the model to also emit `cast` and cross-checking it matches `cast_decision_step`'s answer) — that would reintroduce exactly the failure mode this story fixes (the model still has to hold cast-schema-compliance in its head while composing prose). Cast is decided once, upstream, and never asked of the visual-composition call again.

### Files touched

- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `cast_decision_step` (new), `visual_breakdown_step` (signature + cast-attachment)
- `src/yt_flow/pipeline/nodes/scenario.py` — `_breakdown_for` wiring
- `prompts/scenario/cast_decision.md` (new)
- `prompts/scenario/visual_breakdown.md` — cast sections rewritten
- `tests/pipeline/nodes/test_scenario_chain.py`, `tests/pipeline/nodes/test_scenario.py`, `tests/stubs/fakes.py`
- `tests/fixtures/cassettes/deepseek_cast_decision.json` (new)

### Preserved behavior

- `parse_cast`'s leniency table (Story 8.1) is unchanged and still the final validation point in `build_scenes` — `cast_decision_step`/`visual_breakdown_step` pass raw, unvalidated member dicts through.
- Old checkpoints / non-candidate (`label=None`) production runs are unaffected: `cast_decision_step` only runs when the chain runs at all, and its result degrades to `[]` per-shot the same way a missing `cast` key always has, if a run somehow reaches it without the candidate label ever being promoted.
- No change to `CastMember`/`CastPose` domain types, `resolve_cast_cards`, or any Story 8.2/8.3 consumer — this story only fixes cast *origination*, not consumption.

### Follow-ups (not this story)

- `docs/PROMPT_POLICY.md`'s documented re-seed command (`--source prompts/scenario`) actually produces mis-prefixed Langfuse names (`visual_breakdown` instead of `scenario/visual_breakdown`); the correct invocation is `--source prompts` (the parent dir). Small doc fix, flagged for a future prompt-policy touch-up, not fixed here (out of scope, no functional impact once discovered).
- The AC13 DoD in Story 8.3 can now be attempted for real (candidate leg will actually emit `cast`) — Jay may want to re-run that live A/B against `272b05a4` with the real candidate-prompt-driven pipeline now that this blocker is gone, superseding 8.3's hand-crafted-cast substitute evidence with a fully organic one.

## Change Log

- 2026-07-08: Story created and implemented in the same session as Story 8.3's live validation, which discovered the root cause. Root-caused via live reproduction against the real DeepSeek API (systematic-debugging Phase 1-3), fixed by splitting cast decision into its own LLM call, re-validated live. Full regression green, ruff clean. Status → done (single-session story; no separate review pass requested).
