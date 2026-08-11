---
title: 'Story 10.1c — Close-out: AD-1 boundary, default-enable verdict, obsolete-code cleanup'
type: 'chore'
created: '2026-08-11'
status: 'in-review'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: 'fae0b98'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** Story 10.1c's implementation and live adjudication are finished and committed (51 recompose passes, 0 errors, `video_recompose.mp4` 3:06, Jay's motion verdict PASS — findings 3·11 gone), but three things keep it open: `services/recompose_service.py` imports `yt_flow.pipeline.nodes.shot_recompose`, which violates AD-1 and is the repository's only failing test; `shot_recompose_enabled` is still `False` with no recorded verdict on whether to flip it; and the epic declares the card-compositing mechanisms obsolete without anyone having reconciled that against the flag actually being off.

**Approach:** Bring the recompose service under the existing `_pure_node_imports` contract (same services→pure-node direction as `eval_service`), and close the allowlist loophole by asserting the allowlisted node modules are themselves layer-pure. Record an evidence-based verdict on the default flag. Then do only the cleanup that is real while the flag is off: delete the orphaned module, make the obsolete work structurally unreachable for recomposed shots rather than deleting the live overlay path, and fix the one stale-state defect that flipping the flag would expose.

## Boundaries & Constraints

**Always:** The overlay path (`_build_card_chain` and everything feeding it) is the production path while `shot_recompose_enabled` is `False` — its behaviour must be bit-identical after this story. `render_composite_still` and `render_card_coverage_mask` are kept deliberately as measurement tools despite having no production caller. `pipeline/nodes/shot_recompose.py` stays layer-pure (stdlib + `yt_flow.domain` only). Only the 10-1c entry may be touched in `epics.md` / `sprint-status.yaml` — another session is editing 13-2 concurrently.

**Block If:** the AD-1 fix cannot be made without either widening the allowlist beyond the `eval_service` precedent or moving orchestration (ComfyUI client, workspace, `Settings`) into `pipeline/`.

**Never:** Do not delete or disable depth-aware ground placement (8.16), `_GROUND_Y_MAX`, occlusion masks, contact shadows, layered 2.5D parallax (11.5) or character idle motion (1.9c) — they are the live default path, and the epic's "accepted cost" wording is conditional on recompose becoming the default. Do not revive composite-then-refine (IC-Light fusion, mask low-denoise img2img, ControlNet/IPAdapter over a composited still). Do not add negative-prompt clauses. Do not build a plate-placement assessor. Do not start any other story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recomposed shot | `shot` with `image_path` + `depth_map_path` from the original plate; recompose succeeds | `image_path` rewritten to the recomposed frame **and** `depth_map_path` dropped, so 2.5D parallax records `no_depth_map` instead of warping the new frame with the old plate's depth | No error expected |
| Skipped shot | card key absent from `CARD_LOOKS`, or unreadable plate | `image_path` and `depth_map_path` both untouched; shot stays on the overlay path | Warning logged, `stats["skipped"]` incremented |
| Flag off | `shot_recompose_enabled=False` | Ground placement, occlusion, contact shadow, layered parallax and idle motion all run exactly as before | No error expected |
| Allowlisted node module turns impure | a module in `_pure_node_imports` starts importing `yt_flow.services` / `yt_flow.api` / `yt_flow.db` | `test_services_does_not_import_api_or_pipeline` fails | Assertion names the module and the offending import |

</intent-contract>

## Code Map

- `src/yt_flow/services/recompose_service.py` -- the AD-1 violator (line 17); also where `image_path` is rewritten (line ~98) without clearing `depth_map_path`
- `src/yt_flow/pipeline/nodes/shot_recompose.py` -- pure domain half (stdlib + `yt_flow.domain.png` only); the allowlist target
- `tests/services/test_character_service.py:539-564` -- `test_services_does_not_import_api_or_pipeline`, `_pure_node_imports` at line 548
- `src/yt_flow/pipeline/nodes/video.py:2402-2429` -- 8.16 ground-resolver block immediately followed by the 10.1c recompose block (wrong order: placements are resolved for shots that then drop their cards)
- `src/yt_flow/pipeline/nodes/video.py:1386-1500` -- `_FUSION_STILL_SPEC`, `render_composite_still`, `render_card_coverage_mask` (KEEP as measurement tools)
- `src/yt_flow/pipeline/nodes/composite_fusion.py` -- orphan from rejected Story 10.1b; zero importers in `src/`, `tests/`, `scripts/`, `e2e/`; no test file
- `src/yt_flow/config.py:272-281` -- `shot_recompose_enabled` (default `False`) and its epic comment block
- `src/yt_flow/services/parallax_service.py:571,94-107` -- `NO_DEPTH` fallback and its provenance taxonomy

## Tasks & Acceptance

**Execution:**
- [x] `tests/services/test_character_service.py` -- add `"recompose_service.py": {"yt_flow.pipeline.nodes.shot_recompose"}` to `_pure_node_imports`, update the docstring to state why, and assert every allowlisted module is itself free of `yt_flow.services` / `yt_flow.api` / `yt_flow.db` imports -- an allowlist without a purity check is a hole in AD-1, not an exemption from it
- [x] `src/yt_flow/services/recompose_service.py` -- drop `depth_map_path` on every shot whose `image_path` is rewritten -- the old plate's depth map does not describe the characters the model just drew into the frame; `parallax_service` already degrades to `NO_DEPTH` with a recorded reason
- [x] `src/yt_flow/pipeline/nodes/video.py` -- move the 10.1c recompose block above the 8.16 ground-resolver block so placements are resolved only for cards that survive; keep the ordering rationale in the comment and leave the ground/occlusion/shadow code itself untouched
- [x] `src/yt_flow/pipeline/nodes/composite_fusion.py` -- delete the file -- composite-then-refine is discarded by the epic and nothing imports it
- [x] `src/yt_flow/pipeline/nodes/video.py` -- note beside `render_composite_still` / `render_card_coverage_mask` that they are caller-less **by decision** (measurement tools), so a later dead-code sweep does not remove them
- [x] `tests/services/test_recompose_service.py` -- new: cover the recomposed / skipped rows of the I/O matrix (`image_path` rewritten + `depth_map_path` dropped + cast entry removed; skipped shot untouched) with a stub ComfyUI client -- the service layer currently has no tests
- [x] `src/yt_flow/config.py` -- keep `shot_recompose_enabled = False` and record the verdict and its unblock condition in the comment block
- [x] `_bmad-output/planning-artifacts/epics.md` + `_bmad-output/implementation-artifacts/sprint-status.yaml` -- **10-1c entry only** -- record the default-off verdict, the cleanup outcome, and close the story

**Acceptance Criteria:**
- Given the repository at `fae0b98`, when the full test suite runs, then `test_services_does_not_import_api_or_pipeline` passes and no test that passed before now fails.
- Given `shot_recompose_enabled=False`, when `video_node` renders a scene, then ground placement, occlusion masks, contact shadows, layered parallax and idle motion produce the same filter chain as at `fae0b98`.
- Given `shot_recompose_enabled=True` and a shot that recomposes successfully, when `video_node` continues, then no ground placement is resolved for that shot's cards and its 2.5D parallax reports `no_depth_map` rather than warping with the pre-recompose depth map.
- Given a future change that makes `shot_recompose.py` import from `services/`, when the layer-boundary test runs, then it fails.
- Given the closed story, when `config.py` and the 10-1c epic entry are read, then both state that the default stays off, the evidence on both sides, and what would flip it.

## Review Triage Log

### 2026-08-11 — Review pass

Reviewer coverage note: the Edge Case Hunter pass ran and returned 8 findings. The Blind Hunter (adversarial) pass was **not run** — the user declined that subagent launch — so this triage rests on one reviewer plus the orchestrator's own verification, not two.

- intent_gap: 0
- bad_spec: 0
- patch: 5: (high 2, medium 3, low 0)
- defer: 1: (high 0, medium 1, low 0)
- reject: 3: (high 0, medium 1, low 2)
- addressed_findings:
  - `[high]` `[patch]` Recompose was not re-entrant: `video` is a retryable stage and the frame swap is in place, so a second pass would take an already-recomposed frame as its plate and draw every figure twice (the duplicate-figure failure this story spent a round debunking), while `run_dir` fell to the `else` branch and wrote outside the run. Added a re-entry guard keyed on `RECOMPOSED_DIR` — now a named constant in `shot_recompose.py`, so the path and the check cannot drift — which drops the cards and counts the shot as skipped. Test: `test_rerunning_over_an_already_recomposed_shot_is_a_no_op`.
  - `[high]` `[patch]` Torn state on a write failure: shot dicts are rewritten as the loop goes, so an `OSError` (ENOSPC, read-only workspace, cross-device `replace`) escaped to `video_node`, whose blanket `except` keeps the **original** `cast_cards` — the already-swapped shots would then get their characters composited on top of a frame that already contains them, and the ground resolver would ground those duplicates. Contained the write in a per-shot `except OSError` → `stats["failed"]`. Test: `test_write_failure_leaves_the_shot_renderable`.
  - `[medium]` `[patch]` The AD-1 guard resolved `ast.ImportFrom.module` without `node.level`, so `from ..api import main` yielded `"api"`, matched no prefix, and walked straight through the guard it exists to be. Relative imports are now resolved against the file's own package. Verified by probe: a temporary `from ...services import comfyui_client` in `shot_recompose.py` makes the test fail; reverted.
  - `[medium]` `[patch]` The new purity re-check is direct-only, but its docstring implied it closed the whole `services→pipeline→services` cycle. Amended the docstring to state the limit rather than tightening the check — a transitive import-graph walk in a unit test buys less than it costs.
  - `[medium]` `[patch]` `test_cached_frame_is_reused_without_a_second_render` restored `image_path` to the plate by hand, i.e. asserted cache reuse from a state the pipeline cannot present — which is exactly what hid the re-entry defect. Kept it (it does cover the cache) but labelled its scope and added the real re-entry state as its own test.
  - `[medium]` `[defer]` In-place mutation of the graph's shot dicts contradicts AD-4, which `image_node` follows by copying (`image.py:582`). The worst consequence is patched above; the design question is deferred to the flip commit — recorded in `deferred-work.md`.
  - `[medium]` `[reject]` "Cache hit does not validate the PNG." The write is `tmp.write_bytes` then `tmp.replace`, so a killed process leaves a `.tmp` file, not a corrupt `out` — the scenario needs a hand-placed corrupt file.
  - `[low]` `[reject]` "A stale allowlist entry raises `FileNotFoundError` instead of an assertion." It still fails loudly and names the file.
  - `[low]` `[reject]` "`data/workflows/comfyui_fusion_img2img_api.json` is orphaned by the deletion." It is still parametrized by `tests/test_workflow_definitions.py`'s glob (the LoRA-allowlist regression guard) and cited by `10-3-live-validation/`; deleting it loses a guarded row for nothing. The companion point — that the deliberately-kept `render_composite_still` / `render_card_coverage_mask` have no tests — is the recorded keep decision, not a defect of this change.

## Design Notes

**Default-enable verdict: stays off.** For: Jay's viewing verdict on the full render passed and the epic ranks viewing verdict above metrics; the 42-plate sweep had 0 composition collapses; the ⛳ anchor names recreation the canonical direction. Against, and decisive for the *default*: (a) the 10-4 post-hoc audit (epics.md, 2026-08-10) scored recomposed frames **worse** on the blind-legibility axis than the original plates — unreadable 20% vs 13%, misread-as-corridor 57% vs 27% — on Epic 10's largest defect cluster, and that axis is itself being rebuilt in 13-2; (b) the path requires ComfyUI started with `--lowvram --disable-smart-memory` and an fp8 text encoder, with nothing in the codebase detecting or enforcing it — the failure mode on a stock install is a swap deadlock (12 minutes, 0 results), which the `try/except` fallback does not catch; (c) 90–120 s × 51 passes adds 1.3–1.7 h to a 2 h E2E budget; (d) the epic's own constraint is that new paths enter default-off. **Unblock condition:** 13-2's rebuilt axes score a paired recompose-on/off set; flip if legibility is neutral-or-better and a runtime-prerequisite guard exists.

**Consequence for the cleanup.** The epic's "accepted cost — do not revive" list is conditional on recreation *becoming* the path. With the flag off, deleting ground placement, `_GROUND_Y_MAX`, occlusion, contact shadow, layered parallax or idle motion would delete production code, so this story does not delete them — it makes them unreachable-by-construction when the flag is on (block reorder) and deletes only what is dead under both settings (`composite_fusion.py`). Their removal belongs to the commit that flips the default.

## Verification

**Commands:**
- `uv run pytest tests/services/test_character_service.py::test_services_does_not_import_api_or_pipeline tests/services/test_recompose_service.py -q` -- expected: all pass
- `uv run pytest tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_video_depth_placement.py tests/pipeline/nodes/test_video_parallax_25d.py tests/pipeline/nodes/test_shot_recompose.py tests/services/test_compositing_service.py tests/services/test_parallax_service.py tests/api/test_lifespan_injection_gates.py -q` -- expected: all pass, no regression vs `fae0b98`
- `uv run pytest -q -p no:cacheprovider --ignore=e2e` -- expected: 0 failures (was 1 at `fae0b98`)
- `rg -n 'composite_fusion' src tests scripts e2e` -- expected: no matches

**Manual checks (if no CLI):**
- `git diff fae0b98 -- src/yt_flow/pipeline/nodes/video.py` shows a block move plus comments only — no edit inside `_build_card_chain`, `_apply_placement`, `ground_y_expr`, `_occlusion_fragment` or `MotionSource`.

## Auto Run Result

Status: done

**Implemented.** Closed Story 10.1c on its three open items. The AD-1 violation is resolved by
bringing `recompose_service` under the same `_pure_node_imports` contract `eval_service` already
uses, with a new re-check that the allowlisted node module is itself layer-pure (an allowlist
without that check is a hole, not an exemption). `shot_recompose_enabled` **stays off** by an
evidence-recorded verdict. The obsolete-code cleanup was scoped to what the flag-off decision
actually makes dead.

**Files changed**
- `src/yt_flow/services/recompose_service.py` — drop the now-stale `depth_map_path` when the frame is swapped; re-entry guard; per-shot containment of write failures
- `src/yt_flow/pipeline/nodes/shot_recompose.py` — `RECOMPOSED_DIR` named so the cache path and the re-entry check cannot drift
- `src/yt_flow/pipeline/nodes/video.py` — recompose block moved above the 8.16 ground resolver (block move + comments only); KEEP note on `render_composite_still` / `render_card_coverage_mask`
- `src/yt_flow/pipeline/nodes/composite_fusion.py` — deleted (rejected 10.1b, zero importers, zero tests)
- `src/yt_flow/config.py` — the default-off verdict, both sides of the evidence, and the unblock condition
- `tests/services/test_character_service.py` — AD-1 allowlist + purity re-check + relative-import resolution
- `tests/services/test_recompose_service.py` — new, 8 tests (the service layer had none)
- `_bmad-output/planning-artifacts/epics.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml` — 10-1c entry only; `deferred-work.md` — one AD-4 entry

**Review findings.** 5 patched (2 high, 3 medium), 1 deferred (medium), 3 rejected. The Blind
Hunter reviewer was declined by the user, so only the Edge Case Hunter pass ran — this is why
`followup_review_recommended: true`.

**Verification.** `uv run pytest -q -p no:cacheprovider --ignore=e2e --ignore=tests/services/test_eval_service.py`
→ **2549 passed, 1 skipped, 0 failed**. The AD-1 guard was probed live in both directions (an
absolute and a relative `services` import in `shot_recompose.py` each make it fail; reverted).
`git diff fae0b98 -- video.py` confirmed to be a block move plus comments, with no hunk inside
`_build_card_chain`, `_apply_placement`, `ground_y_expr`, `_occlusion_fragment` or `MotionSource`.

**Residual risks.**
1. `tests/services/test_eval_service.py` has 7 failures in the working tree. They are the
   concurrent Story 13-2 session's in-flight edits to `eval_service.py` / `test_eval_service.py`
   (`_motion_repeat_ratio` ordering) — files this story never touches, excluded from the run above
   and from the commit. The repository's one pre-existing failure that this story owned is fixed.
2. The recompose path is exercised only by unit tests here; the live evidence predates this
   change. The re-entry and write-failure guards have not been seen on real hardware.
3. The default-off verdict rests partly on a 10-4 measurement with n=15 on the control side. If
   13-2's rebuilt axes contradict it on a paired sample, the verdict flips — that is the
   documented unblock condition, not a defect.
