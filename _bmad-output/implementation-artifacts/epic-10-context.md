# Epic 10 Context: Viewing-Verdict Defect Correction — 2026-08-08 Jay E2E Review

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A human watched a full end-to-end render and listed 16 concrete visual/audio defects. This epic exists to fix them **and**, more importantly, to make it provable which story removed which defect — the prior session closed a whole epic of image-compositing work and the watched output did not change, with no way to attribute the outcome afterwards. Every story therefore closes on rendered artifacts a human judged, never on passing tests or wired code. A second reason the epic exists: the reviewed run was rendered with ground-placement and parallax accidentally disabled, so several complaints describe features that were **off**, not features that failed — separating "off" from "ineffective" is prerequisite work for everything downstream.

## Stories

- Story 10.1: Grounding/compositing live verification
- Story 10.1b: Card–plate fusion via IC-Light relight (rejected on viewing)
- Story 10.1c: Shot recomposition — background + cards + placement instruction → one generated image
- Story 10.1d: Recompose runtime-precondition preflight (backlog)
- Story 10.1e: Recompose on/off paired scoring and default verdict (backlog)
- Story 10.2: Force people-free backgrounds
- Story 10.3: Art-style consistency and LoRA compatibility
- Story 10.4: Image–narration semantic alignment
- Story 10.4b: Stop asking the renderer to draw an absence
- Story 10.5: Action/pose state not reflected in cast cards
- Story 10.6: Cast presentation coherence — D-class quality, visual duplicates
- Story 10.7: Scene sound replacement — siren cue
- Story 10.8: Cast pose/angle coverage (backlog)

## Requirements & Constraints

- **Closure requires rendered evidence.** A story closes only when the cited defect is demonstrably gone in frames or clips a human judged. Metrics may inform, but a viewing verdict overrides a favorable measurement.
- **Measure before declaring cause.** Multiple rounds here disproved their own premises (9 of 10 hypotheses falsified in one round). Establish a control leg and pre-register the decision rule before rendering or scoring; record contradicting results rather than dropping them.
- **Attribution over throughput.** When a change ships, it must be traceable to a defect number and to a paired before/after artifact.
- **New render paths enter disabled by default.** Flipping a default needs a paired, blind, pre-registered comparison plus a runtime-precondition guard, not a single favorable demo.
- **Cheap screening before GPU spend.** Prompt-level changes are screened as text against a judge (seconds, no GPU) before any render A/B is authorized — this ordering has already saved roughly six GPU-hours in one round.
- **Live-validation directories are evidence, not scratch.** Commit the adjudication images and the scripts that re-derive every number; raw sweeps stay ignored but must never be blanket-deleted.
- Overall pipeline budget remains an end-to-end run within about two hours, dominated by image generation; any per-shot cost added by a new path counts against that.

## Technical Decisions

- **Canonical direction: recreation, not overlay.** The final frame is generated from the background plate plus character cards plus a natural-language placement instruction — the model places the figures and produces a single image. Compositing-then-refining (masked low-denoise img2img, relighting the sprite, applying ControlNet/IPAdapter to an already-composited still) is rejected: all three take an already-pasted result as input, so code constants still decide position, scale and pose. Test of whether a result is recreation: if the card-region pixels closely match the source card, it is still an overlay.
- **Accepted cost of recreation:** cards can no longer move independently of the background, so layered parallax and character idle motion go away. This is intended removal, not regression — motion mismatch between card and plate was the leading suspect for the "floating" complaint. The grounding/occlusion/contact-shadow/parallax machinery only becomes dead code once recreation is the shipped default; deleting it belongs to that flip.
- **Background source reuse is intentional.** Fewer distinct backgrounds across a run is the target, not a diversity regression — spatial continuity is channel identity. Fix scarcity by adding more source plates, never by deriving variants from one plate. Recreation must therefore hold the plate composition and redraw mainly the figures and their contact region.
- **Prompt control is positive requirement, not negative accumulation.** Adding negative-prompt clauses has backfired twice, and regex scrubbing of prompt text damages valid content. Control generation by stating what the frame's subject must be.
- **Diffusion cannot render an absence.** Any prompt whose subject is emptiness produces incoherent frames; prompts must name an existing object, surface or trace.
- **Evaluation instrument shape.** Blind scoring (frame only, sentence withheld) must run before match scoring (frame plus sentence), or the judge learns to agree. Likert axes that never vary below their ceiling are dead axes — replace with booleans. Known confounds must be removed from an axis before it is used as a gate, and exclusion from a score is insufficient if the confound still invalidates rows.
- **Layering rule still binds.** Pipeline nodes do not import services/DB; where a service must reach a node module, it goes through the explicit allowlist seam and the allowed node module is re-checked for upward imports so the exception cannot launder a cycle.
- **Feature flags and config live in settings with an env prefix**; a decision that only ever reaches an env file has not shipped — gates will read green while the artifact is wrong.
- Cast/pose conditioning uses structural conditioning (pose guides) rather than text-only pose requests; text-only pose instructions are empirically ignored by the model.

## Cross-Story Dependencies

- 10.1 is the baseline for the whole epic: it establishes the on/off comparison every later story is judged against.
- 10.1b superseded 10.1's finding and was itself rejected on viewing; 10.1c replaced it and is the canonical direction.
- 10.1d (runtime preflight) must land before 10.1e (paired scoring), and both are the stated unlock conditions for making recreation the default.
- 10.1e depends on the rebuilt visual-evaluation axis owned by Epic 13; 10.4's instrument work and confound removal also hand off there.
- 10.4b's remaining live defect (frames that show a place but no event) is handed forward as a measurable target with an existing text-level screening gate.
- 10.2's people-free-background guard must be enabled before match-style scoring is trusted, since figures appearing in plates confound it.
- 10.5 depends on the pose-conditioning assets produced by Epic 8's pose work; its unresolved sitting-pose slots and 10.6's non-retroactive card fixes both wait on a human asset-replacement gate.
- 10.6 fixed generation rules but not existing assets — the defect remains on screen for runs that reuse current cast cards.
- 10.8 spans two layers (the cast-decision prompt and the approved card library); fixing either alone changes nothing on screen.
- Script-quality and plate-substitution complaints from the same review were routed out of this epic to the scripting and compositing epics respectively.
