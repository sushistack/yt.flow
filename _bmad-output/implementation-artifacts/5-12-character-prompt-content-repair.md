---
created: 2026-07-05
story_key: 5-12-character-prompt-content-repair
story_id: "5.12"
epic: 5
previous_story: 5-11-segmentation-failure-shot-fallback
depends_on:
  - 5-10-entity-reference-pipeline-repair
  - 1-11-character-domain-reference-search
  - 1-13-video-llm-character-selection
baseline_commit: 8eb6ea2d52a7096c3538cb0246a9e8a4d4d79618
---

# Story 5.12: 캐릭터 생성 프롬프트 콘텐츠 복구 (Vision 디스크립터 배선 + Langfuse 브레이스 버그)

Status: done

## Story

As Jay,
I want the automatic character-reference pipeline to actually describe the reference image in its generation prompt, and the Langfuse-hosted `"character-generation"` prompt template to actually substitute its per-angle variables,
so that the 4 canonical angle images Story 5.10 now successfully generates are genuinely angle-differentiated and identity-described, instead of relying entirely on IPAdapter image-conditioning with a blank or literally-unsubstituted text prompt.

## Context

Story 5.10 fixed both real blockers preventing Story 5.8's optimistic entity-reference path from ever running against a real ComfyUI server (DuckDuckGo 403 → SCP Wiki-first fetch; missing/invalid character workflow → authored + live-validated an IPAdapter-based workflow). Its live end-to-end re-validation (2026-07-05, fresh `SCP-1471`, run `7dcef476-268e-41f7-a4c9-fe50c5b240c4`) proved the *mechanics* work — a real reference image is fetched, all 4 angles generate via real ComfyUI, and every entity-visible shot's `character_path` resolves to a real generated angle image, not a same-frame segmentation cutout.

But that same live validation surfaced two further, previously-undiscovered defects one layer up, in the *prompt content* that feeds the (now-working) generation mechanism — both confirmed live, not theorized:

1. **`CharacterService.enrich_descriptor_from_references`** (Story 1.11's Vision LLM descriptor extraction — analyzes the downloaded reference image and produces a text description) **is never called** from `run_service._ensure_character_reference` (Story 5.8's automatic trigger, `src/yt_flow/services/run_service.py:366-427`). It calls `search_references` and `generate_candidates_from_reference` only. Grepping `src/yt_flow` confirms `enrich_descriptor_from_references` has zero callers anywhere in the codebase. The result: every automatically-provisioned `Character.visual_descriptor` is permanently `None`, so `generate_candidates_from_reference`'s `_get_visual_descriptor()` always returns `None`, and the compiled generation prompt's `visual_descriptor` slot is always empty. Character identity currently transfers to the generated angle images *only* via IPAdapter's raw image conditioning — confirmed working reasonably well in 5.10's live test (a real SCP-1471 photo produced a visually-consistent masked-figure illustration), but with zero textual grounding of what the reference image actually shows.
2. **The Langfuse Prompt Hub's `"character-generation"` prompt uses single-brace placeholders** (`{visual_descriptor}`, `{angle}`, `{angle_description}`, `{scp_id}`) — but Langfuse's `TextPromptClient.compile(**vars)` only substitutes double-brace (`{{varname}}`) mustache-style tokens. Calling `get_prompt("character-generation").compile(angle="front", ...)` returns the literal, unsubstituted template text with `{angle}` still spelled out. Confirmed live: two of Story 5.10's four generated angle images (`front`/`side` in one run) were byte-for-byte MD5-identical, because all 4 angle-generation calls received the exact same (empty, unsubstituted) prompt text — angle differentiation in that run came entirely from ComfyUI's own sampling variance, not from the prompt.

Both defects sit in code/content that Stories 1.11/1.12/1.13 and the Langfuse Prompt Hub own — Story 5.10's own workflow-file and wiki-fetch fixes are correct and must not be touched or re-litigated here (see `5-10-entity-reference-pipeline-repair.md`'s Dev Agent Record and "Saved Questions" section for the full evidence trail this story exists because of).

**Related, unconfirmed suspicion worth checking first:** `prompts/character/angle_selection.md` (Story 1.13's per-shot LLM angle-selection prompt, consumed the same way via `_load_angle_selection_prompt` → `get_prompt("character-angle-selection").compile(...)`) uses the *same* single-brace style (`{scp_id}`, `{available_angles}`, `{shot_catalogue}`). Story 5.10's live validation run had **all 49 shots across all 8 scenes resolve to the "front" angle** — consistent with (but not proven to be caused by) the LLM receiving the same kind of unsubstituted, context-free prompt every time and defaulting/hallucinating to a single answer. Task 1 below should check whether `"character-angle-selection"` has the identical Langfuse brace bug before assuming Story 1.13's angle-selection logic itself is at fault for the all-front result.

## Acceptance Criteria

**Vision LLM descriptor wiring**

1. **Given** `run_service._ensure_character_reference` provisions a new character with at least one downloaded reference image, **when** provisioning proceeds to multi-angle generation, **then** `CharacterService.enrich_descriptor_from_references` is called with the downloaded reference image path(s) beforehand, and its result (or `None` on failure) is persisted to `Character.visual_descriptor` before `generate_candidates_from_reference` runs.
2. **Given** Vision LLM enrichment fails (API error, no key configured, empty response), **when** provisioning continues, **then** generation proceeds with an empty/fallback descriptor exactly as it does today — this must remain non-fatal (AD-10), consistent with Story 5.8's existing failure contract for the surrounding `_ensure_character_reference` try/except.
3. **Given** the manual Character Management UI path (Story 3.7) already calls (or doesn't call) `enrich_descriptor_from_references` today, **when** this story wires it into the automatic path, **then** the two paths' behavior is reconciled deliberately (call it from both, or document why the manual path differs) — not left silently inconsistent.

**Langfuse prompt template brace-syntax fix**

4. **Given** `docs/PROMPT_POLICY.md`'s change protocol (repo file → seed `candidate` label → A/B/golden-set gate → promote `production`), **when** the `"character-generation"` prompt's variable syntax is fixed, **then** the fix follows that exact protocol — no direct edit of the `production`-labeled prompt text in the Langfuse UI/API.
5. **Given** `prompts/character/generation.md` is the repo source-of-truth file (currently single-brace, correct for its own `str.format()`-based local-fallback consumption in `character_service.py`), **when** the Langfuse-hosted copy is corrected, **then** the two representations' differing needs are resolved without breaking the local-file fallback branch — determine via `scripts/migrate_prompts.py`/`scripts/seed_eval_prompts.py` whether the seeding process is expected to transform single-brace to double-brace, or whether a Langfuse-specific double-brace variant needs to be authored/seeded separately.
6. **Given** the fix lands and is promoted to `production` per policy, **when** `generate_candidates_from_reference` compiles a prompt for each of the 4 canonical angles, **then** the 4 resulting prompt strings are genuinely distinct (differ at minimum in the `angle`/`angle_description` substitution) — verified by a live re-generation showing 4 non-identical output images (MD5 check, not just "no crash").
7. **Given** the related suspicion in Context above, **when** this story investigates, **then** it explicitly checks (and, if confirmed, fixes under the same protocol) whether `"character-angle-selection"` has the identical single/double-brace mismatch — do not assume Story 1.13's angle-selection LLM logic itself needs to change if the root cause is this same template bug.

**Regression safety**

8. **Given** Story 5.8's non-fatal auxiliary-enrichment contract and Story 5.10's rollback/dedup/tri-state contracts, **when** this story's changes land, **then** none of them are broken: `_ensure_character_reference`'s try/except/rollback structure, the concurrent-run dedup guard, and `select_character_angles`'s `None`/`{}`/`dict` tri-state all continue to behave exactly as before.

## Tasks / Subtasks

- [x] **Task 1 — Confirm scope before fixing (AC: 7)**
  - [x] Reproduce/confirm the `"character-generation"` brace bug directly against the real Langfuse instance (call `get_prompt("character-generation").compile(angle="front", angle_description="x", scp_id="y", visual_descriptor="z")` and confirm the literal placeholders come back unsubstituted — Story 5.10 already did this once; re-confirm before changing anything).
  - [x] Do the same check for `"character-angle-selection"` — confirm or rule out the same bug before touching Story 1.13's angle-selection code.
  - [x] Read `scripts/migrate_prompts.py` and `scripts/seed_eval_prompts.py` fully to determine which script (if either) is responsible for seeding `prompts/character/*.md` into Langfuse, and whether either does any brace-syntax transformation today.
- [x] **Task 2 — Wire Vision LLM descriptor enrichment into auto-provisioning (AC: 1-3)**
  - [x] In `run_service._ensure_character_reference`, after `search_references` succeeds and before the per-angle `generate_candidates_from_reference` loop, call `svc.enrich_descriptor_from_references(scp_id, ref_image_paths=[r.local_path for r in refs])` and persist the result via `svc.update_character(character.id, visual_descriptor=...)` if non-`None`.
  - [x] Check whether Story 3.7's Character Management UI routes (`api/routes/characters.py`) already call `enrich_descriptor_from_references` somewhere in their generation flow — if yes, mirror the same call site/pattern; if no, decide and document why (both paths should not silently diverge without a stated reason).
  - [x] Confirm the existing non-fatal contract: a Vision LLM failure here must not raise past `_ensure_character_reference`'s outer try/except, and must not count as the "total failure" that triggers `delete_character` rollback (only total search/generation failure should, per Story 5.8's existing logic — enrichment is enrichment, not a hard requirement).
  - [x] Unit tests: mock `enrich_descriptor_from_references` in `test_run_service_character_provisioning.py`, covering success (descriptor persisted before generation) and failure (generation still proceeds, no rollback triggered by enrichment failure alone).
- [x] **Task 3 — Fix the Langfuse prompt template brace syntax (AC: 4-6, per PROMPT_POLICY.md)**
  - [x] Determine the correct fix shape from Task 1's findings — likely either (a) the seeding script needs to convert `{var}` → `{{var}}` when pushing to Langfuse, or (b) `prompts/character/generation.md` (and `angle_selection.md` if confirmed affected) need a Langfuse-specific double-brace variant maintained alongside the local-fallback single-brace version.
  - [x] Follow `docs/PROMPT_POLICY.md`'s change protocol exactly: edit the repo prompt file(s), seed under `candidate` label, run an A/B against the same `scp_id`, run the golden-set regression gate if applicable to character prompts, then promote `production` — do not hand-edit the Langfuse UI's prompt text directly.
  - [x] If `"character-angle-selection"` is confirmed affected by Task 1, apply the identical fix/protocol to it in the same story (do not split into a third follow-up unless scope genuinely balloons).
- [x] **Task 4 — Live re-validation (AC: 6, 8)**
  - [x] Re-run the same live scenario Story 5.10 used (fresh `scp_id`, no existing `CharacterModel`, real wiki fetch + real ComfyUI) through `_ensure_character_reference` (or a full `run_service.start_run`) and confirm: `visual_descriptor` is populated before generation; the 4 generated angle images are no longer MD5-duplicated; if Task 3 also fixed angle-selection, confirm shots resolve to a mix of angles (not uniformly "front") for a scene set with narratively distinct camera directions.
  - [x] Run the full regression suite: `uv run pytest tests/services/test_run_service_character_provisioning.py tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/pipeline/nodes/test_image.py tests/services/test_run_service_gate.py tests/services/test_run_service_resume.py tests/pipeline/test_stub_profile_smoke.py -q` plus new tests from Tasks 2-3 — must stay green.
  - [x] Record the run ID and outcome in Dev Agent Record.

### Review Findings

- [x] [Review][Patch] `scripts/seed_character_prompts.py`'s `except Exception: pass` around `get_prompt` conflated "prompt not found" with real failures (auth/network/misconfigured host), risking spurious duplicate prompt versions on a transient error [scripts/seed_character_prompts.py:54-60]
- [x] [Review][Patch] `docs/PROMPT_POLICY.md` rule 1 was factually stale — claimed `scripts/seed_eval_prompts.py` seeds character prompts, but that script only ever handled `evaluation/judge`/`evaluation/pairwise`; the new `scripts/seed_character_prompts.py` wasn't mentioned at all [docs/PROMPT_POLICY.md:7]
- [x] [Review][Patch] `docs/PROMPT_POLICY.md` rule 4 (golden-set gate before promotion) didn't document this story's two policy-sanctioned deviations for stages the gate/A-B mechanism doesn't cover (golden-set only exercises `scenario`; character prompts aren't wired into `POST /runs/{id}/ab`) [docs/PROMPT_POLICY.md:16]
- [x] [Review][Patch] `run_service.py`'s inner try/except wrapped both the enrichment HTTP call and the `update_character` DB write under one log message ("vision descriptor enrichment failed"), misattributing a DB-persistence failure to the Vision LLM if `update_character` ever throws [src/yt_flow/services/run_service.py:419-421]

## Dev Notes

### Critical Implementation Guardrails

- **Do not touch `run_service._ensure_character_reference`'s control flow, rollback, or dedup logic** beyond inserting the one new enrichment call in the right place — Story 5.8's code review already hardened this against three real failure modes (settings-init ordering, permanent-failure poisoning, concurrent-creation race), and Story 5.10 relied on it staying correct. Adding the enrichment call must slot into the existing try/except, not restructure it.
- **Do not touch Story 5.10's wiki-fetch or ComfyUI-workflow code** (`image_search.py::ScpWikiImageFetch`, `character_image_provider.py`, `comfyui_client.py`, `data/workflows/comfyui_character_multi_angle_api.json`) — those are validated and out of scope here. This story is about what text goes *into* the prompt, not how the workflow executes it.
- **`select_character_angles`'s tri-state contract is load-bearing** (`character_service.py:795-830`; consumed at `video.py:618-650`) — `None`/`{}`/`dict`. Nothing in this story should change that contract, even if Task 3 touches the angle-selection prompt's content.
- **PROMPT_POLICY.md is non-negotiable process, not a suggestion** — CLAUDE.md explicitly points every AI session at it. No direct Langfuse UI edits of `production`-labeled prompt text, even for a "one-character bug fix."

### Current Code State — Files To Read Before Editing

- `src/yt_flow/services/run_service.py:366-427` (`_ensure_character_reference`) — insertion point for Task 2's enrichment call.
- `src/yt_flow/services/character_service.py:394-473` (`enrich_descriptor_from_references`) — already fully implemented, just uncalled from the auto path. Read its signature carefully: takes `scp_id` and `ref_image_paths: list[str]`.
- `src/yt_flow/services/character_service.py:509-577` (`generate_candidates_from_reference`) and `:591-631` (`_compile_generation_prompt`) — where the (currently-empty) `visual_descriptor` and the (currently-unsubstituted) Langfuse prompt both feed in.
- `src/yt_flow/services/character_service.py:929-970` (`_load_angle_selection_prompt`) — check for the same brace pattern per Task 1.
- `prompts/character/generation.md`, `prompts/character/angle_selection.md`, `prompts/character/vision_enrichment.md` — repo source-of-truth prompt files (`vision_enrichment.md` has no variable placeholders, so it's not affected by the brace bug even if hosted identically).
- `scripts/migrate_prompts.py`, `scripts/seed_eval_prompts.py` — whichever seeds `prompts/character/*` into Langfuse; read fully before deciding Task 3's exact fix shape.
- `docs/PROMPT_POLICY.md` — the change protocol Task 3 must follow exactly.
- `api/routes/characters.py` — check whether Story 3.7's manual UI-triggered generation flow already calls `enrich_descriptor_from_references` (AC3 needs this answered either way).
- `_bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md` — full Dev Agent Record + Saved Questions documenting exactly why this story exists; read before starting.

### Architecture Compliance

- AD-1 (`services/` imports `domain`/`db`, never `pipeline`/`api`) — all touched files (`run_service.py`, `character_service.py`) are already `services/`-layer; no new cross-layer import.
- AD-10 (non-fatal auxiliary failures) — Vision LLM enrichment failure must degrade gracefully exactly like every other step in `_ensure_character_reference` already does.
- No new pipeline stage, no new LangGraph node, no `db/models.py` schema change expected — this story only changes prompt content/seeding and one new method call in an existing function.

### Testing Requirements

- Follow `tests/stubs/fakes.py`'s existing fake patterns (`fake_get_image_provider`, etc.) — likely needs a new `fake_enrich_descriptor`/similar wired into `patch_character_reference_seams()` so `stub_profile`/`test_run_service_gate.py`/`test_run_service_resume.py` stay offline, matching how Story 5.8 had to wire three fakes into those same three places when it added a new call inside `_ensure_character_reference`.
- Prompt-content changes (Task 3) cannot be meaningfully unit-tested against the real Langfuse instance in CI — verify via the golden-set/A-B protocol PROMPT_POLICY.md already defines, plus the live re-validation in Task 4. A local unit test can still assert the *local-fallback* `.format()` path stays correct if that file's syntax changes.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/services/run_service.py` (Task 2 — new enrichment call in `_ensure_character_reference`)
  - `prompts/character/generation.md` and possibly `prompts/character/angle_selection.md` (Task 3 — exact change depends on Task 1's findings)
  - Possibly `scripts/migrate_prompts.py` or `scripts/seed_eval_prompts.py` (Task 3 — if the fix belongs in the seeding transform rather than the prompt file itself)
  - `tests/services/test_run_service_character_provisioning.py` (Task 2 tests)
  - `tests/stubs/fakes.py`, `tests/conftest.py`, `tests/services/test_run_service_gate.py`, `tests/services/test_run_service_resume.py` (new fake wiring, matching Story 5.8's precedent)
- No `db/models.py` schema change expected.

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Story 5.12`
- Direct predecessor: `_bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md` (Dev Agent Record + Saved Questions — this story's whole reason for existing)
- Related: `1-11-character-domain-reference-search.md` (Vision LLM enrichment origin), `1-13-video-llm-character-selection.md` (angle-selection prompt, possibly same bug), `6-1-prompt-policy-variant-label-wiring.md`, `6-2-golden-set-offline-eval.md` (Prompt Ops precedent for this exact change protocol)
- Prompt policy: `docs/PROMPT_POLICY.md`
- Architecture: AD-1, AD-10 — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Task 1 live repro (direct `get_prompt(name).compile(...)` against `langfuse.eli.kr`): both `character-generation` and `character-angle-selection` returned literal unsubstituted single-brace text — confirmed.
- Task 1 script audit: neither `scripts/migrate_prompts.py` (sources from external `yt.pipe/templates`, converts `{var}`→`{{var}}`, but never discovers `prompts/character/*`) nor `scripts/seed_eval_prompts.py` (repo-native manifest, but only `evaluation/judge` + `evaluation/pairwise`, no conversion since those files are already authored double-brace) seeds `prompts/character/*.md` at all. Root cause: the 3 character prompts were seeded into Langfuse by some other, now-absent process, verbatim single-brace, under flat hyphenated names (`character-generation`, `character-angle-selection`, `character-vision-enrichment`) that don't match either script's naming convention.
- Task 3 fix shape: added `scripts/seed_character_prompts.py`, mirroring `seed_eval_prompts.py`'s manifest shape but reusing `migrate_prompts.convert_placeholders` (import, no duplication) to convert braces at seed time. Repo files (`prompts/character/*.md`) stay single-brace unchanged — required by the local `.format()`/`.replace()` fallback branch in `character_service.py` (AC5). Verified the JSON literal in `angle_selection.md` (`{"scene_num": N, ...}`) survives conversion untouched (regex requires a bare identifier immediately inside braces).
- Task 3 protocol deviation (documented, not silently skipped): (a) golden-set regression gate (`scripts/eval_prompts.py`) only runs the `scenario` stage per `docs/PROMPT_POLICY.md` — not applicable to character prompts, skipped per the policy's own "if applicable" carve-out. (b) The standard `POST /runs/{id}/ab` A/B mechanism only threads `prompt_variant` into `PipelineState` for the scenario stage (`run_service.py:198-207,447-456`) — `character_service.py`'s `_compile_generation_prompt`/`_load_angle_selection_prompt` call `get_prompt(name)` with no label at all (always production), so character prompts are not wired into that A/B system and running one would not have exercised the `candidate` label. Substituted the equivalent verification: seeded `candidate`, directly compiled `candidate` for all 4 angles with identical inputs and confirmed 4 distinct outputs plus intact JSON literal, then promoted `production` via the same script (`--label production`) — consistent with this project's existing single-operator, script-driven label convention (no Protected Labels available, per `docs/PROMPT_POLICY.md`'s own note).
- Task 3 live promotion executed: `uv run python scripts/seed_character_prompts.py --label candidate` (created all 3), verified candidate output, then `uv run python scripts/seed_character_prompts.py --label production` (created new versions for `character-generation` and `character-angle-selection`; `character-vision-enrichment` skipped as byte-identical — no vars to convert). Re-fetched production after promotion and confirmed both now substitute correctly.
- Task 4 live re-validation: fresh `SCP-682` (no prior `CharacterModel`), real wiki/DuckDuckGo fetch, real ComfyUI (`http://127.0.0.1:8188`, confirmed up), real DeepSeek. Direct `run_service._ensure_character_reference("SCP-682")` call (not a full `start_run` — no scenario/shots needed to exercise the character-provisioning path).
  - 4 angle images generated, all MD5-distinct (`front`, `back`, `side`, `three_quarter` — 4/4 unique, vs. Story 5.10's 2/4-duplicate finding).
  - `select_character_angles` called directly afterward with a synthetic 4-scene set carrying narratively distinct camera cues (direct confrontation / retreat-into-shadows / cautious side-observation / calm dialogue) — resolved to all 4 distinct angles (`front`/`back`/`side`/`three_quarter`), matching `angle_selection.md`'s own stated heuristic exactly. Confirms the Context section's suspicion: Story 5.10's "49/49 shots → front" live result was this same brace bug, not a defect in Story 1.13's selection logic.
  - `enrich_descriptor_from_references` fired (proving the Task 2 wiring executes) but failed with a real HTTP 400 from `api.deepseek.com`: `"unknown variant \`image_url\`, expected \`text\`"` — the configured `deepseek-v4-flash` endpoint does not accept multimodal image content at all. This is a pre-existing gap in Story 1.11's implementation/model choice, not introduced by or in scope for this story (guardrails explicitly forbid touching Story 1.11/1.12/1.13 logic beyond the one new call site). It did, however, prove AC2's non-fatal contract under a **real** failure, not a simulated one: `visual_descriptor` stayed unset, no exception propagated, no rollback, and all 4 angle images still generated successfully. AC1's "populated before generation" ordering is verified separately by the new unit test (mocked success case), since this environment's DeepSeek deployment can't currently exercise a real success path. Flagging as a follow-up candidate: Story 1.11's Vision LLM enrichment needs a vision-capable model/endpoint before it can ever populate a real descriptor.
  - Full regression suite: `PYTHONPATH=$PWD/src uv run pytest -q` → 628 passed, 1 skipped (pre-existing), 0 failed.

### Completion Notes List

- AC1/AC2: `run_service._ensure_character_reference` now calls `CharacterService.enrich_descriptor_from_references` after `search_references` and before the per-angle generation loop, persisting a non-`None` result via `update_character(..., visual_descriptor=...)`. The call is wrapped in its own inner `try/except`, separate from the surrounding search/generation `try/except`, so an enrichment failure logs a warning and continues — it cannot trigger the total-failure `delete_character` rollback. Verified both by unit test (success + failure) and by a real live failure (see Debug Log).
- AC3: The Character Management UI's manual generate flow (`api/routes/characters.py::generate_candidates`, `POST /{id}/generate`) does **not** call `enrich_descriptor_from_references` either — both paths were previously consistent in omitting it, just silently so. Reconciled deliberately rather than wiring it into the route too: the manual path already has a human in the loop who can inspect the reference image and set `visual_descriptor` directly via `PATCH /{id}` (an allowlisted field) before triggering generation, so automated Vision LLM enrichment is optional there. The automatic path (`_ensure_character_reference`) has no human in the loop at all, so it needs the automated call to ever get a descriptor. `api/routes/characters.py` was intentionally left unmodified — it is not in this story's "Expected modified files" list and the guardrails scope Task 2 to `run_service.py` only.
- AC4-6: Root cause was not a missing brace-conversion step in an existing script — no existing script seeds `prompts/character/*.md` into Langfuse at all (see Debug Log). Added `scripts/seed_character_prompts.py`, reusing `migrate_prompts.convert_placeholders` so the conversion logic isn't duplicated. Repo prompt files stay untouched/single-brace (needed by the local-fallback `.format()`/`.replace()` branches, already covered by pre-existing tests in `test_character_service_generation.py` that exercise the fallback path against a fake Langfuse host). Followed the PROMPT_POLICY.md protocol with two documented, policy-sanctioned deviations (golden-set gate not applicable to this stage; standard A/B run doesn't route character prompts, so direct candidate-vs-production compile comparison substituted for the "same input" check) — see Debug Log for full reasoning. Both prompts promoted to `production` and re-verified live.
- AC7: Confirmed `character-angle-selection` had the identical single/double-brace bug (Task 1) and fixed it under the same protocol in this story, per the guardrail to not split into a third follow-up story.
- AC8: No changes to `_ensure_character_reference`'s control flow/rollback/dedup, `image_search.py`/`character_image_provider.py`/`comfyui_client.py`, or `select_character_angles`'s tri-state contract. All pre-existing regression tests plus the 6 provisioning-race/rollback tests in `test_run_service_character_provisioning.py` still pass unchanged.
- New tests added: `test_enrichment_success_persists_descriptor_before_generation` and `test_enrichment_failure_is_non_fatal_generation_still_proceeds` in `tests/services/test_run_service_character_provisioning.py`.

### File List

- `src/yt_flow/services/run_service.py` — wired `enrich_descriptor_from_references` call into `_ensure_character_reference` (Task 2); docstring updated.
- `scripts/seed_character_prompts.py` — new; seeds `prompts/character/*.md` into Langfuse with brace conversion (Task 3).
- `tests/services/test_run_service_character_provisioning.py` — 2 new tests for enrichment success/failure wiring (Task 2).
- `_bmad-output/implementation-artifacts/5-12-character-prompt-content-repair.md` — this story file (frontmatter `baseline_commit`, task checkboxes, Dev Agent Record, Change Log, Status).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status transitions (`ready-for-dev` → `in-progress` → `review`).
- (Langfuse, no repo diff) `character-generation` and `character-angle-selection` prompts: new `candidate` versions created, then new `production` versions created via `scripts/seed_character_prompts.py --label production`.

## Change Log

- 2026-07-05: Story drafted via create-story workflow, from Story 5.10's Saved Questions follow-up recommendations (Vision LLM descriptor never wired into auto-provisioning; Langfuse `"character-generation"` prompt brace-syntax bug). Both root causes pre-confirmed live during Story 5.10's end-to-end validation — this story's job is fixing both, plus checking whether Story 1.13's angle-selection prompt shares the same brace bug.
- 2026-07-05: Implemented and closed for review. Wired Vision LLM descriptor enrichment into `_ensure_character_reference` (non-fatal, isolated try/except); confirmed `character-angle-selection` shared the same brace bug as `character-generation` and fixed both via a new `scripts/seed_character_prompts.py` (candidate → production, per PROMPT_POLICY.md, with 2 documented protocol deviations for steps that don't apply to character-stage prompts). Live re-validation on fresh `SCP-682`: 4 angle images now MD5-distinct (was 2/4 duplicate), angle-selection now resolves to a genuine mix of angles matching narrative cues (was 49/49 "front"), and a real Vision LLM enrichment failure (DeepSeek model doesn't support image input) proved the non-fatal contract holds under real conditions. Full regression suite green (628 passed, 1 pre-existing skip).
- 2026-07-05: Code review (joint with Story 5.13) via bmad-code-review — 3 parallel layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 4 findings confirmed and fixed for this story: seed script's `except Exception: pass` narrowed to `langfuse.api.NotFoundError` (live-verified against `langfuse.eli.kr`); `docs/PROMPT_POLICY.md` rules 1 and 4 corrected to name `seed_character_prompts.py` and document the 2 stage-carve-out deviations; `run_service.py`'s enrichment-failure log message corrected to not misattribute a DB-persistence failure to the Vision LLM. Several other adversarial findings investigated and dismissed as false positives or by-design (verified against actual code, not just claims). Full regression suite green (628 passed, 1 pre-existing skip). Status → done.
