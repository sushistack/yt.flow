---
title: 'Story 10.2 — Background must be unpopulated (findings 5·12)'
type: 'bugfix'
created: '2026-08-09'
status: 'done'
baseline_revision: '79cb473'
review_loop_iteration: 1
final_revision: 'd7ef3a0'
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: ['oversized', 'dirty-tree-unrelated-10-7']
---

<intent-contract>

## Intent

**Problem:** Jay's findings 5·12 — the *background itself* already contains people (a large female face, an anime character), and a cast card is then placed on top, so the frame holds two figures. Story 10.1c's recompose makes this worse, not better: recompose preserves the plate, so a person painted into the background survives into the final single image. The whole card-compositing premise (Epic 8) is that the background is unpopulated; nothing in the code enforces that today — `image_prompt` is background-only *by prompt contract only*, and there is no post-generation check of any kind.

**Approach:** Two enforcement layers, both deterministic code, plus one composition correction. (1) Fix a self-contradiction inside `visual_breakdown` that literally instructs the model to put "a figure small in an enormous space" in the frame, and require the frame's focal point to be an occupied *physical object* — positive-space direction, zero net prompt growth. (2) A `build_scenes`-time scrub that strips person-bearing clauses out of `image_prompt`, in the exact 8.18/8.19 in-place-repair idiom. (3) A post-generation Qwen-VL check on the rendered background; on a hit, regenerate with a bumped seed, bounded, fail-open.

## Boundaries & Constraints

**Always:**
- Detection reuses the existing DashScope Qwen-VL path (`_DASHSCOPE_VISION_ENDPOINT` + `settings.character_vision_*`). No new dependency, no new model download, no local VLM.
- The guard is non-fatal: a missing API key, HTTP error, or unparseable reply accepts the image and logs a warning. It must never fail the image stage (AD-10) nor silently look like a clean pass.
- The final accepted seed is what gets written to the resume sidecar, otherwise a bumped seed makes every resume regenerate forever.
- Prompt-file edits follow `docs/PROMPT_POLICY.md`: repo file is source of truth, seeded to `production` with `scripts/migrate_prompts.py`. DEV MODE — no A/B, no promotion gate.
- Scrub/guard failures degrade the shot, never the run; every drop or regeneration is logged with shot id and reason.

**Block If:**
- Live validation cannot produce a single populated background to catch (i.e. detection never fires across the probe set) — a guard proven only on synthetic input does not close this story.
- Closing would require growing `BG_NEGATIVE_SUFFIX` or the LLM-authored `negative_prompt` contract.

**Never:**
- Do not grow any negative prompt. `BG_NEGATIVE_SUFFIX` (`image.py:83`) and the `negative_prompt` contract (`visual_breakdown.md:203`) must be byte-identical before and after. Negative accumulation has backfired three times (`gotcha_negative-prompt-overstuffing`; on 2026-08-09 "do not draw circles" strengthened the circles).
- Do not add more "no person" prose to the prompt. It already says it in six places and the render still draws people — more repetition is the failure mode, not the fix.
- Do not touch the stock-plate path: plates are already screened for `has_person` at seeding (`scripts/label_location_plates.py`) and only `approved` rows are served. Scope is the *generated* background path.
- Do not start any other Epic 10 story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Clean prompt, clean render | `image_prompt` with no person tokens; VLM says `has_person=false` | Image accepted on attempt 0; sidecar seed == `_shot_seed(...)` | No error expected |
| Prompt names a person | `image_prompt` = "...a lone figure stands at the far door, damp concrete floor..." | Offending comma-clause removed before generation; remaining prose intact; INFO log with shot id + dropped clause | Non-string / empty prompt is skipped, not raised |
| Whole prompt is person-only | every clause carries a person token | Prompt is left unchanged (never emptied) and a warning is logged — an empty positive prompt renders garbage | Warning only, shot proceeds |
| Model prior draws a person | clean prompt; VLM says `has_person=true` on attempt 0 | Regenerate with a derived seed; accept the first attempt that reads clean; sidecar records that seed | — |
| Every attempt populated | VLM says `has_person=true` on all attempts | Last attempt is kept, warning logged naming the shot and attempt count | Warning, run continues |
| Vision key absent / HTTP 4xx / unparseable reply | `character_vision_api_key == ""`, timeout, prose reply | Image accepted unchecked, one warning per run (not per shot) for the key case | Fail-open, never raises |
| Mock / stock-plate path | `comfyui_mock=True` or a stock plate was copied | Guard is not invoked; zero VLM calls | — |

</intent-contract>

## Code Map

- `prompts/scenario/visual_breakdown.md` -- runtime prompt; `:112` "A figure small in an enormous space" contradicts the background-only rule at `:7-20`; `:203` negative contract (do not touch). Runtime reads Langfuse, not this file.
- `src/yt_flow/pipeline/nodes/image.py` -- `:83` `BG_NEGATIVE_SUFFIX` (frozen); `:140` `_shot_seed`; `:143` `_inject_prompts`; `:186` `_write_sidecar`; `:214` `_existing_complete_shot`; the real-mode generate/write block the guard wraps
- `src/yt_flow/services/vision_check.py` -- the guard's detector (new file)
- `src/yt_flow/services/character_service.py` -- `:41` `_DASHSCOPE_VISION_ENDPOINT`, the reuse anchor
- `scripts/label_location_plates.py` -- `:52` `LABEL_PROMPT`, `:69` `_parse_verdict` brace-slice, `:104` `score_plate` — the call shape to mirror. Note: its `has_person` definition is a *seeding-time* definition and is deliberately NOT reused verbatim (see Design Notes).
- `src/yt_flow/config.py` -- `:178-184` `character_vision_*`; the guard knob sits beside `:246` `stock_plate_substitution_enabled`
- `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `:341` `_suppress_cast_on_no_figure_framing` (Story 8.19) must be left exactly as it is; iteration 1 disarmed it and that must not recur
- Tests live in `tests/pipeline/nodes/test_image.py` (NOT `test_image_node.py`) and `tests/services/` for the detector
- [`10-2-live-validation/`](10-2-live-validation/) -- evidence from iteration 1's live probe; `before.png`/`after.png` and their verdicts are valid and must be preserved

**Discovered during iteration 2 (as built):**

- `src/yt_flow/config.py` -- `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS = 4` and `BACKGROUND_PERSON_GUARD_BREAKER_STREAK = 3` are module constants *above* `Settings`, not fields: the ladder ceiling has to be readable by `image.py` without constructing `Settings`, and it bounds the knob (`Field(2, ge=0, le=...)`) at the same time. One number, one place.
- `src/yt_flow/pipeline/nodes/image.py` -- `_shot_seed` grew `attempt: int = 0` (attempt 0 keeps the old `run:scene:shot` string; only bumped rungs get `:attempt`); new `_seed_ladder()` returns the fixed-length rung list; `_existing_complete_shot` now takes that list and tests `sidecar["seed"] not in seeds`. `_populated()` is a closure inside `image_node` because the breaker and the counters are per-run state, and it is where the detector call is wrapped.
- `src/yt_flow/pipeline/nodes/image.py` -- the health-check cadence now counts `request_count`, not `generated_count`: a guard retry is a second submission, and the cadence exists to bound submissions fired at a crashed ComfyUI (triage `[low][patch]`).
- `src/yt_flow/services/vision_check.py` -- imports nothing from `pipeline/`, so `test_services_does_not_import_api_or_pipeline` is unaffected. That test still fails at baseline for `recompose_service` (Story 10.1c), unchanged by this story.

**Discovered during iteration 2's review pass (as built):**

- `src/yt_flow/services/vision_check.py` -- `:29` defines `_DASHSCOPE_VISION_ENDPOINT` as its own literal instead of importing it from `character_service`: that import dragged `db.models` / `sqlmodel` / `image_search` into `yt_flow.pipeline.nodes.image`'s graph, the first time `pipeline/` would have reached the DB layer. A test (`test_endpoint_matches_character_services_definition`) keeps the two copies equal and a subprocess test (`test_importing_the_image_node_does_not_pull_in_the_db_layer`) pins the invariant. `character_service` itself is untouched.
- `src/yt_flow/services/vision_check.py` -- `CHECK_PROMPT` now states ONE rule ("is a real body occupying space in this frame"); the earlier draft called a *silhouette* a person and "a shadow with no body casting it" not a person, which is undecidable. The request pins `temperature: 0`, and the module docstring states the residual nondeterminism (the verdict is still a hosted model's).
- `src/yt_flow/config.py` -- `background_person_guard_attempts` defaults to **0 (off)**, like `stock_plate_substitution_enabled` and `shot_recompose_enabled`; enabling it is `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS=2` (documented in `.env.example`). `BACKGROUND_PERSON_GUARD_BREAKER_TOTAL = 6` joins the streak breaker; the `MAX_ATTEMPTS` comment now states that the ladder length is a resume contract that may only grow.
- `src/yt_flow/pipeline/nodes/image.py` -- guard accounting fixes: `regenerated` counts only rungs another render actually follows; a fourth counter `unscreened` counts every generated shot the guard did not screen (knob 0 / no key / breaker tripped) and joins the run-level WARNING; `guard_counts` + `depth_counts` are declared *before* the `try` so the error-path `_record_trace` reports them too; the sidecar records `guard_exhausted` (outside the resume equality check) and `_sidecar_guard_exhausted` folds it back into `guard_counts` on resume; the health cadence is a "requests since the last check" counter, because `request_count % N == 0` evaluated once per shot steps over multiples now that one shot can fire 1..N submissions.
- [`10-2-live-validation/run_gate.py`](10-2-live-validation/run_gate.py) -- the live gate for the **real `image_node`** (the probe only ever reimplemented the ladder). Writes `gate_*.png`, `gate_*_done.json`, `gate_log.json`, `gate_log_resume.json`; `gate_workspace/` is gitignored.
- [`10-2-live-validation/run_probe.py`](10-2-live-validation/run_probe.py) -- the `--arm scrub` half was removed (it imported the deleted `_scrub_person_clauses`, so it could not even load) and replaced by `--replay-hit`, which re-renders the recorded hit from `before_verdict.json` and writes `confirm_*` files instead of overwriting the preserved pair.
- Tests: `tests/services/test_vision_check.py` (new, 20 cases) and the `Background-person guard (Story 10.2)` block at the end of `tests/pipeline/nodes/test_image.py`. `FakeSettings` gained `guard_attempts=0` / `vision_api_key=""` defaults so every pre-10.2 test keeps asserting exactly one render per shot.

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- **do not add any text-layer scrub.** `_scrub_person_clauses` / `_PERSON_TOKENS` from iteration 1 are removed and must not come back; `build_scenes` keeps its pre-10.2 call order -- measured net harm, see Spec Change Log 2026-08-09.
- [x] `prompts/scenario/visual_breakdown.md` -- change exactly two words' worth of text: in the negative-space bullet replace "A figure small in an enormous space" with a non-human equivalent. Leave the "visual hook" bullet's existing craft examples intact and add no frame-fraction requirement -- the only defensible edit is deleting the prompt's own instruction to draw a figure; anything else is unmeasured prompt churn.
- [x] `scripts/migrate_prompts.py` -- run `--label production --source prompts` and save the command output (prompt name + version) into `10-2-live-validation/migrate_prompts.txt` -- the runtime reads Langfuse; the one step that changes runtime behaviour must leave evidence.
- [x] `src/yt_flow/config.py` -- `background_person_guard_attempts: int` with an explicit upper bound (0 disables) -- one knob; the bound also fixes the resume ladder length.
- [x] `src/yt_flow/services/vision_check.py` -- `async background_has_person(image_bytes, settings) -> bool | None`. Every statement that can raise, including the key check and the base64 encode, sits inside the `try`. Narrow the detector's `has_person` definition to a figure *present in the scene*: an anatomical diagram, illustration, poster, photograph, skull, statue or mannequin is NOT a person for this guard -- the runtime case is "will a composited card collide with a body already in frame", which is not the seeding-time screen's question, and SCP set dressing is full of depicted humans.
- [x] `src/yt_flow/pipeline/nodes/image.py` -- bounded attempt loop around generate/write. Requirements: (a) the detector call is wrapped so no exception from it can reach the node's error boundary; (b) the seed ladder length is the config field's maximum, independent of the run's current `background_person_guard_attempts`, so lowering the knob or losing the key never invalidates an already-accepted shot; (c) after 3 consecutive undecidable verdicts the guard disables itself for the rest of the run with one warning; (d) the trace records regenerated / exhausted / unavailable counts, and a run-level WARNING summarises any non-zero exhausted or unavailable count -- a dead guard must not read as a clean pass.
- [x] `tests/services/test_vision_check.py` -- new: missing key, HTTP error, fenced/prose-wrapped JSON, non-boolean `has_person`, non-bytes input, happy path -- iteration 1 shipped this module with zero direct tests.
- [x] `tests/pipeline/nodes/test_image.py` -- guard matrix with a monkeypatched detector: accepted on attempt 0; regenerated then accepted; exhausted-then-kept; fail-open on `None`; **a detector that raises must leave `out["error"] is None` and still produce the image**; not invoked in mock/stock-plate paths; sidecar seed == accepted seed; resume skips a bumped-seed shot *after the knob is lowered to 0*; the consecutive-failure breaker stops calling the detector.
- [x] `tests/pipeline/nodes/test_image.py` -- assert `BG_NEGATIVE_SUFFIX` equals its current literal -- makes "negative prompt did not grow" a test, not a claim.
- [x] `src/yt_flow/pipeline/nodes/image.py` + `src/yt_flow/services/vision_check.py` + `src/yt_flow/config.py` -- review-pass patches P1-P12: regeneration count, `unscreened` accounting, error-path trace, exhausted-on-resume, health cadence, total-undecidable breaker, DB-layer import break, one-rule detector prompt, `temperature: 0`, default-off knob, `.env.example` entry, resume-contract comment on `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS`.
- [x] `tests/pipeline/nodes/test_image.py` + `tests/services/test_vision_check.py` -- one test per behavioural patch above (regeneration count, `unscreened` on knob-0 and after the breaker, error-path counters, sidecar `guard_exhausted` + resume fold-back + legacy sidecars still matching, cadence under guard retries, total-undecidable breaker, DB-free import graph, one-rule prompt, `temperature: 0`, endpoint parity).
- [x] `10-2-live-validation/run_gate.py` -- LIVE GATE: drive the **real `image_node`** (guard knob 2, real ComfyUI, real DashScope) over the recorded hit `S00114`, the two named finding-5·12 shots `S00104`/`S00403`, and two *depicted*-human shots `S00305`/`S00713`; save every frame, sidecar, verdict and counter, and report results that go against the story rather than tuning the prompt.
- [x] `_bmad-output/implementation-artifacts/10-2-live-validation/` -- keep `before.png`/`after.png` + verdicts + `probe_log_guard.json` + `run_probe.py`; delete the scrub-arm artifacts (`scrub_*`, `probe_log_scrub.json`) since that layer is gone, noting in the README that `scrub_after.png` was pixel-identical to `before.png`; rewrite the README's conclusion to match the evidence (see AC5).

**Acceptance Criteria:**
- Given a real ComfyUI and a real vision key, when the evidence is inspected, then `10-2-live-validation/` holds a before frame a Qwen-VL verdict calls populated and an after frame it calls clean, both from the guard's own regeneration ladder. (Already satisfied by iteration 1's probe: shot `S00114`, seed `3285965459` → `has_person=true`, a full-frame anime face; attempt 2, seed `3292677910` → clean.)
- Given the re-derived guard, when a short confirmation probe re-runs `run_probe.py` against the recorded hit, then the guard still detects and clears it, and the run is recorded in the README.
- Given the whole change set, when `git diff` is inspected, then no negative-prompt string anywhere in the repo has gained a term, and `prompts/scenario/visual_breakdown.md` differs from baseline by one bullet.
- Given a run where the vision key is unset or the knob is 0, when the image stage executes, then every shot is produced exactly as before this story, one warning is logged, and a shot previously accepted on a bumped seed is still skipped on resume.
- Given the real `image_node` (not a reimplementation of its ladder), when it runs live with the knob at 2, then it is observed detecting a populated background, regenerating, accepting a bumped rung, pinning that rung in the sidecar, and resuming from it on a second pass — and its `guard_*` counters are recorded. (Satisfied 2026-08-10 by `run_gate.py`: 5 shots, 7 submissions, `S00114` cleared on rung 2, `guard_regenerated=2`, resume pass 0 submissions. Two *depicted*-human shots did not fire the guard; `S00305`'s render contained no diagram, so that half of the check is void — stated in the README rather than papered over.)
- Given the live evidence, when the README and this spec state a root cause, then the statement matches the sample: 14/14 probes whose prompt carried no person token rendered clean and the single hit came from a prompt that originally did, the hit rate 1/15 is a stop-at-first-success censored sample, and the attribution to the checkpoint prior is stated as **unproven** rather than as a finding. No control probe exists that isolates checkpoint prior from prompt semantics.

## Spec Change Log

### 2026-08-09 — iteration 1 → 2 (bad_spec)

**Triggering findings.** (a) The `build_scenes` text scrub this spec prescribed was replayed over the four real corpora on disk: **27 of 313** shot prompts are mutated, and most mutations are false positives that destroy meaning — `"POV shot from human eye level"` (the whole camera slot, clause 0), `"left side of frame open for a standing figure"` (the composition instruction that reserves space *for the card*), `"the chair area empty of any human presence"` (an explicit emptiness assertion), `"first-person call"`, `"each patch approximately the size of a human torso"`, plus anatomical diagrams, a labelled skull and pinned medical illustrations. (b) Its only live measurement was a **negative result**: on `S00114`, removing the person clause and re-rendering the same seed still read `has_person=true`, so the scrub did not fix the one shot it was tested on. (c) It silently disarmed Story 8.19's no-figure-framing suppression, and a test locked that in. (d) The guard could fail the image stage, contradicting this spec's own Boundaries, with a test asserting the contradiction. (e) The resume ladder was derived from the run's current `guard_attempts`, so lowering the knob or losing the vision key resurrects the regenerate-forever bug the ladder exists to prevent. (f) The evidence directory presented `scrub_after.png` as an independent observation when it is pixel-identical to `before.png`, and concluded a root cause the sample does not support.

**Amended.** The text layer is removed from the Tasks entirely; enforcement is the prompt correction plus the pixel guard. The prompt edit is narrowed to the single self-contradicting bullet. The guard gains: a hard-bounded seed ladder independent of runtime config, a wrapped detector call, a consecutive-failure breaker, unavailable/exhausted accounting, and a narrowed `has_person` definition that does not fire on depicted humans. Detector unit tests are now required. AC5 requires the evidence to state its own limits.

**Known-bad state avoided.** Shipping an unconditional, un-switchable prompt rewriter with no demonstrated benefit that damages ~9% of production prompts, disarms an existing validator, and whose root-cause claim inverts what its own control probes say — the exact pattern `gotcha_recorded-root-cause-can-be-inverted` and this epic's "build a control before attributing cause" constraint exist to stop.

**KEEP (must survive re-derivation).**
- The pixel guard's shape: `_shot_seed(run_id, scene_num, shot_id, attempt)` with attempt 0 hashing the pre-10.2 string byte-identically, so existing workspaces keep resuming.
- `_existing_complete_shot` accepting the whole seed ladder rather than one seed.
- `vision_check` mirroring `label_location_plates.score_plate`'s call and brace-slice parse, refusing to coerce a non-boolean `has_person`, and returning `None` (never raising) as the fail-open outcome.
- The `for/else` attempt loop reading as "else == every rung was populated".
- The one-warning-per-run behaviour when the vision key is absent, and never calling the detector in mock or stock-plate paths.
- The `BG_NEGATIVE_SUFFIX` literal-pinning test.
- The live evidence `before.png` / `after.png` / their verdicts / `probe_log_guard.json` / `run_probe.py` — do not re-render them.

## Review Triage Log

### 2026-08-09 — Review pass
- intent_gap: 0
- bad_spec: 15: (high 6, medium 9, low 0)
- patch: 2: (high 0, medium 0, low 2)
- defer: 2: (high 0, medium 2, low 0)
- reject: 5
- addressed_findings:
  - `[high]` `[bad_spec]` Text scrub damages 27/313 real prompts (camera slot, card-space reservation, emptiness assertions, set dressing) — layer removed from the spec
  - `[high]` `[bad_spec]` Text scrub has no demonstrated benefit; its only live measurement was negative — layer removed
  - `[high]` `[bad_spec]` Text scrub disarms Story 8.19 suppression and a test pins the regression — layer removed, 8.19 restored untouched
  - `[high]` `[bad_spec]` Guard can fail the image stage, contradicting the spec's own Boundaries; a test asserted the contradiction — call-site wrapping and an inverted test now required
  - `[high]` `[bad_spec]` Resume ladder derived from runtime `guard_attempts` reintroduces regenerate-forever — fixed-length ladder now required
  - `[high]` `[bad_spec]` Evidence duplicated (`scrub_after.png` pixel-identical to `before.png`) and root-cause claim unsupported by its own controls — AC5 added
  - `[medium]` `[bad_spec]` `vision_check` key check + base64 encode outside its `try` — fail-open hole
  - `[medium]` `[bad_spec]` `vision_check` shipped with zero direct tests — test file now required
  - `[medium]` `[bad_spec]` Detector counts statues/mannequins/posters/diagrams as people — narrowed definition now required
  - `[medium]` `[bad_spec]` No breaker on repeated detector failure (120s timeout × every shot) — breaker now required
  - `[medium]` `[bad_spec]` A dead guard reads as a clean pass — unavailable accounting + run-level warning now required
  - `[medium]` `[bad_spec]` Prompt edit scope creep (three craft directives deleted, a frame-fraction rule added that conflicts with macro framings) — narrowed to one bullet
  - `[medium]` `[bad_spec]` Scrub regex built from a string with no `re.escape`, at import time — moot with the layer removed
  - `[medium]` `[bad_spec]` First-clause drop produced a malformed prompt and was the one case untested — moot with the layer removed
  - `[medium]` `[bad_spec]` Scrub had no kill switch while the evidence-backed layer had one — moot with the layer removed
  - `[low]` `[patch]` `migrate_prompts` run left no artifact — output capture folded into the task list
  - `[low]` `[patch]` Health-check cadence counts shots, not requests, so guard retries loosen it — folded into the image-node task

### 2026-08-10 — Review pass (iteration 2)
- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 2, medium 8, low 4)
- defer: 2: (high 0, medium 2, low 0)
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[high]` `[patch]` `image_node`'s own guard path had never run live — the probe reimplemented the ladder. Added `run_gate.py`, which drives the real node over 5 real shots (the recorded hit `S00114`, the two named finding-5·12 shots `S00104`/`S00403`, and two depicted-human shots), and recorded its counters, sidecars and a resume pass
  - `[high]` `[patch]` A guard that never screened a frame (knob 0, no key, breaker tripped) was indistinguishable in the trace from a verified clean pass — added an `unscreened` count, surfaced on the span and in the run-level warning
  - `[medium]` `[patch]` `guard_regenerated` counted the final rung, overstating regenerations by one on every exhausted shot — only rungs another render follows are counted
  - `[medium]` `[patch]` The error-path `_record_trace` dropped `guard_counts`/`depth_counts`, losing the accounting exactly when a post-mortem needs it
  - `[medium]` `[patch]` An exhausted (known-populated) frame resumed as if verified — the sidecar now records `guard_exhausted` and the resume path folds it back into the run-level warning, without breaking pre-existing sidecars
  - `[medium]` `[patch]` The `request_count % N` health cadence stepped over multiples once retries made the counter jump 1–3 per shot — replaced with a since-last-check counter
  - `[medium]` `[patch]` The breaker counted only *consecutive* undecidables, so an alternating failure never tripped it — added a total-undecidable trip
  - `[medium]` `[patch]` `vision_check` imported the endpoint from `character_service`, dragging `db.models`/`sqlmodel` into the image node's import graph for one URL — constant defined locally
  - `[medium]` `[patch]` The detector prompt contradicted itself on silhouette vs shadow — rewritten as one rule
  - `[medium]` `[patch]` The guard shipped on by default against this project's land-new-behaviour-off convention and triples worst-case image-stage cost — default is now 0
  - `[low]` `[patch]` Detector sampled nondeterministically, making Story 11.1's seed determinism conditional on a hosted model — `temperature: 0` pinned and the residual nondeterminism documented
  - `[low]` `[patch]` `.env.example` had no entry for the new knob
  - `[low]` `[patch]` `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS` is a resume contract that may only grow — recorded at its definition
  - `[low]` `[patch]` README overstated re-derivability and `probe_log_confirm.json` carried a meaningless field

## Deferred (not this story)

- No aggregate render budget: the ladder is bounded per shot, so a person-heavy run could still fire ~3× the renders with nothing run-level to stop it. Size it from a real run's `guard_regenerated`.
- The guard's counters ride the Langfuse span and the run log only; nothing carries them onto the gate/SSE payload the way `scenario_quality` does. That generic surfacing is Story 13.1's scope.

## Design Notes

The prompt forbids people in six separate places and the render still draws them; a seventh sentence is not the fix (`gotcha_negative-prompt-overstuffing`). One thing in the prompt is genuinely wrong rather than insufficient — the negative-space bullet asks for "a figure small in an enormous space" — and deleting it is the whole prompt-side change. Everything else is enforced in pixels.

Why no text layer: measured on 313 real shot prompts, a person-token scrub fires on 27 and is wrong on most of them, because the vocabulary that names a person also names camera positions (`human eye level`, `first-person`), scale references (`the size of a human torso`), depicted humans (`medical diagram`, `human skull`), explicit *absences* (`empty of any human presence`, `no visible figure`) and card-space reservations (`open for a standing figure`). Distinguishing those needs semantics, and the shot where the scrub was actually tested still rendered a person after the clause came out. If a real run later shows a high `guard_exhausted` rate concentrated on person-bearing prompts, that is the evidence that would justify a *semantic* text layer routed through the existing bounded LLM self-correction — not a regex.

The detector's question is not the plate labeler's question. Seeding asks "is this plate clean enough to bank"; the runtime asks "will a composited card collide with a body already in this frame". A poster of a person cannot collide with a card, so counting it burns three renders and then ships the frame anyway.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_scenario_chain.py tests/services/test_vision_check.py -q` -- expected: all pass
- `uv run pytest -q` -- expected: no new failures vs baseline `79cb473` (`test_services_does_not_import_api_or_pipeline` fails at baseline too — pre-existing, from Story 10.1c)
- `git diff 79cb473 -- src prompts scripts | grep -E '^\+' | grep -iE 'negative|person, people|silhouette'` -- expected: no line that adds a negative-prompt term
- `git diff 79cb473 -- src/yt_flow/pipeline/nodes/scenario_chain.py` -- expected: **empty**
- `git diff 79cb473 --stat -- prompts/scenario/visual_breakdown.md` -- expected: 1 insertion, 1 deletion
- `uv run python scripts/migrate_prompts.py --label production --source prompts` -- expected: `scenario/visual_breakdown` seeded; output saved to `10-2-live-validation/migrate_prompts.txt`

**Manual checks (if no CLI):**
- `10-2-live-validation/` holds the before/after pair, both verdicts, the probe log, the re-run script, the migrate output, and a README whose stated conclusion matches AC5.

## Auto Run Result

Status: done

**What was implemented.** Two things, not three. (1) One bullet of `prompts/scenario/visual_breakdown.md` — the negative-space rule literally asked for "a figure small in an enormous space" while the same prompt forbids people in six other places; that instruction is now a non-human object. Seeded to Langfuse `production` as version 14. (2) A post-generation background-person guard in `image_node`: every generated background is shown to Qwen-VL (`qwen-vl-plus` via the existing DashScope wiring), and a populated frame is re-rendered on a derived seed, bounded, with the accepted seed pinned into the resume sidecar. The guard is fail-open at every step and ships **off** (`background_person_guard_attempts=0`).

A third layer — a `build_scenes`-time regex scrub of person-bearing clauses — was specified, built, measured, and **deleted**. Replayed over 313 real shot prompts it damaged 27 of them (it deleted an entire camera slot `POV shot from human eye level`, the composition clause `left side of frame open for a standing figure` that reserves space *for the card*, the assertion `the chair area empty of any human presence`, plus anatomical diagrams and a labelled skull), it disarmed Story 8.19's no-figure-framing suppression, and on the one shot where it was actually tested it did not work — removing the person clause and re-rendering the same seed still produced the person. `scenario_chain.py` is byte-identical to baseline.

**Files changed.**
- `prompts/scenario/visual_breakdown.md` — one bullet (1 insertion, 1 deletion)
- `src/yt_flow/services/vision_check.py` (new) — `background_has_person(image_bytes, settings) -> bool | None`; `None` is the fail-open outcome for every failure mode; `temperature: 0`; narrowed `has_person` (a body in the scene, not a poster/diagram/statue/skull)
- `src/yt_flow/pipeline/nodes/image.py` — fixed-length seed ladder, bounded attempt loop, wrapped detector call, undecidable breaker, `regenerated/exhausted/unavailable/unscreened` counters on the span and in a run-level warning, `guard_exhausted` persisted in the sidecar and folded back on resume, health cadence counts submissions
- `src/yt_flow/config.py` — `background_person_guard_attempts` (default 0, max 4), breaker constants
- `.env.example` — the new knob
- `tests/services/test_vision_check.py` (new), `tests/pipeline/nodes/test_image.py` — 708 tests in the story's three files
- `10-2-live-validation/` — probe, gate, frames, verdicts, counters, README

**Review findings.** Pass 1: 15 bad_spec (6 high) → spec amended, code reverted and re-derived. Pass 2: 0 intent_gap, 0 bad_spec, 14 patches applied (2 high, 8 medium, 4 low), 2 deferred, 6 rejected.

**Verification.** `uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_vision_check.py tests/pipeline/nodes/test_scenario_chain.py -q` → 708 passed. `uv run pytest -q` → 1 failed, 2549 passed, 1 skipped; the single failure is `test_services_does_not_import_api_or_pipeline`, which fails identically at baseline `79cb473` (Story 10.1c's `recompose_service` imports `pipeline.nodes.shot_recompose`) and is unrelated. `git diff 79cb473 -- src/yt_flow/pipeline/nodes/scenario_chain.py` → empty. No negative-prompt term added anywhere; `BG_NEGATIVE_SUFFIX` is pinned by a test.

**Live evidence.** `before.png` is a full-frame anime face rendered from a real prompt — Jay's finding 5 reproduced on demand; `after.png` is the guard's accepted re-render, an unpopulated wet-tiled floor. `run_gate.py` then drove the **real `image_node`** (knob 2, live ComfyUI, live DashScope) over five real shots including the two the finding-5·12 handoff actually named (`S00104`, `S00403`): 7 submissions, `guard_regenerated=2`, `error=None`, and a resume pass that skipped all five with 0 submissions.

**Residual risks.**
- The guard ships **off**. Nothing changes in a run until `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS=2` is set. That is the deliberate land-new-behaviour-off convention, and this directory is the evidence for flipping it.
- **The cause is unproven.** 13 of 15 probe prompts name no person and all rendered clean; the only hit is the only prompt that contained "human". No control isolates the checkpoint's character prior from prompt semantics. The tempting "AnimagineXL paints people into clean prompts" reading is not supported by this sample.
- The narrowed `has_person` definition is only half-tested live: the skull shot rendered a painted portrait instead (the detector correctly said no), and the diagram shot rendered no diagram at all, so it is void as evidence.
- One verdict went against the story and was recorded, not tuned away: `S00114` rung 1 was called populated on a tiny figure inside a lens reflection, costing an extra render.
- The detector is a hosted model, so a replayed run can accept a different rung despite Story 11.1's deterministic seeds.
- No run-level render budget, and the counters do not reach the human gate payload — both deferred.
