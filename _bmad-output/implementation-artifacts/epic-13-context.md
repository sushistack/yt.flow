# Epic 13 Context: Quality Observability & Gate Maturity — Surfacing Silent Failure + Visual Evaluation Axes

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

This pipeline's recurring accident pattern is **silent success masquerading**: code paths that are correct, non-fatal by design, and produce no artifact — and neither tests nor git can see that layer. Documented instances include a "done" feature whose backing table held 0 rows because the seed path never ran, vision enrichment failing with HTTP 400 for roughly a month without anyone noticing, and alignment tooling that in practice never executed once. Epic 13 closes that blind spot structurally on three fronts: make non-fatal degradations visible to the human at the gate, replace a proven-dead visual scoring instrument with one that actually resolves defects, and remove the brittle/unrecorded parts of the ComfyUI render path so results are reproducible and attributable. A fourth story re-arms the A/B promotion gate once the pipeline is complete enough for quality tuning to mean anything.

## Stories

- Story 13.1: Surface silent degradations as gate warnings
- Story 13.2: Extend evaluation axes — frame/motion axes (instrument replacement first)
- Story 13.3: ComfyUI workflow ops hardening — remove node-ID coupling, add reproducibility
- Story 13.4: Release the A/B promotion gate freeze — enter the quality-tuning phase

## Requirements & Constraints

- **Non-fatal stays non-fatal.** Degradation paths (missing character card for a cast member, location-plate miss falling back to generation, relight/harmonization failure, segmentation flat fallback, special-pose cap overflow, enrichment HTTP failure) must keep passing the run. The defect to fix is only "the human does not know" — never convert these into run failures.
- **Warnings must reach a human decision point.** Per-run warning records accumulate and are exposed on the gate response and in the gate-control UI. Reuse the existing checkpoint → gate interrupt → `gate_pending`/artifact → typed warning delivery axis rather than inventing a second transport.
- **Additive, not replacing.** The scenario-specific quality warning contract already shipped must be preserved verbatim at the scenario gate; generic run warnings ride alongside it. The UI must keep the two warning meanings distinct, not merge them into one badge.
- **No new service layer for 13.1.** Add fields to the existing state/artifact paths.
- **Evaluation must see the video, not only the text.** Judge scoring today covers narration text axes only, so a visually poor render scores identically to a good one. New axes are rule/tool-based (no LLM judgment) and score from existing run outputs — composite frames, effect specs, timings — so no GPU re-run is needed.
- **Instrument replacement precedes new visual axes, and this order is not negotiable.** The existing 1–5 VLM Likert axes are measurably dead: one axis produced no value below 4 across 66 frames while the same replies free-texted `event: "unclear"` on 9/66 (a boolean surfaced 12/66), and the other clustered at 3 with 15 of 16 probe rows unmoved. Adding axes on top of that instrument reproduces an unmeasurable result.
- **Do not spend more render runs on sentence↔shot mapping.** A hand-built ordered cover failed to move the match score; the finding is narrow ("freeing the count does not by itself raise semantic match"), and the instrument that produced it is the thing being replaced.
- **Reproducibility is a requirement, not a nicety.** Custom-node versions are currently recorded nowhere; at least one architectural decision was later inverted purely from that missing observability. Render provenance must be recorded per output.
- **13.4 gate release requires an explicit, evidence-backed judge decision.** Because the same model family now owns both Korean prose generation and the judge, self-preference bias was moved rather than removed. Restoring promotion authority without first deciding (and justifying with measurements) whether to keep that judge or split it to a different provider is not allowed.

## Technical Decisions

- **Recommended scoring method for 13.2: DSG-style proposition decomposition** (atomic typed propositions → natural-language questions → dependency graph, where a question only counts correct if its dependencies were also correct). Chosen because it fixes both measured instrument defects at once: a fraction over several propositions is continuous so it cannot cluster, per-proposition results give attribution, and person-propositions can simply not be generated — structurally removing the card-absence confound where frames were docked for a person composited by a later layer.
- **VQAScore is a conditional alternative, not the default.** It needs token log-probabilities from the scoring endpoint; endpoint support must be verified, never assumed. DSG needs only yes/no answers, so it is the safe baseline.
- **Wire the boolean readability signal** the model already volunteers, rather than relying on a Likert legibility score.
- **Metric transfer is unproven for our material.** Published human-correlation numbers are on general text-to-image benchmarks — not Korean narration, not this genre, and notably not background plates whose subject is composited afterwards. Behaviour on our frames must be measured locally.
- **Candidate new axes:** composite-quality score (reusing the threshold calibrated when compositing scoring was introduced — if that work is not yet landed, ship the remaining axes only), motion diversity / archetype coverage over the closed motion enum (including consecutive-identical-motion ratio), and cut-alignment error promoted from an existing rule metric to a first-class evaluation axis.
- **13.3 replaces node-ID coupling with a title-based parameter manifest.** Prompt injection is currently hardcoded to workflow-JSON node ID strings, so renumbering a node silently injects into the wrong place or fails. Look nodes up by their `_meta.title` instead, ID-independent, following the same manifest philosophy already used for asset manifests.
- **13.3 pins reproducibility inputs in git:** ComfyUI-Manager snapshot plus core version; and writes render provenance (workflow hash, parameters, seed, torch/ROCm versions) into the existing per-output sidecar, extending the sidecar that already carries the seed.
- **13.4 is a policy-and-config unfreeze:** lift the suspended promotion rules in the prompt policy doc, remove the environment-variable freeze on the A/B gate, re-evaluate the deferred candidate prompts under the statistical median-of-N gate, and include 13.2's visual axes in the gate.

## UX & Interaction Patterns

- Gate controls live in the run-detail artifact-panel footer and appear only while a stage's gate is pending; the stage sidebar carries the gate indicator (the "act here" signal). 13.1's warning badge attaches to this existing surface — no new page, no toast/push (state is encoded in the sidebar and panel).
- Warning presentation must let the operator distinguish scenario-quality warnings from generic run warnings at a glance.

## Cross-Story Dependencies

- **13.2 before the narration→image prompt fix** (the follow-up story that stops making emptiness the subject of a prompt): running that change against the old clustered score would repeat the same blocked outcome.
- **13.2's composite-quality axis depends on** the depth/compositing scoring work having landed and calibrated its threshold; ship without that axis if it has not.
- **13.2's motion and cut-alignment axes depend on** the closed motion-archetype enum and the alignment rule metric already produced by the cinematic-motion epic.
- **13.1 depends on and must not break** the scenario pass-2 quality-warning contract delivered by the scenario/narration quality epic.
- **13.4 is gated on** the GPU-heavy image-compositing and cinematic-motion epics closing and E2E output passing Jay's bar; it is the deliberate inverse of the earlier gate-freeze story (kept separate because deciding "the pipeline is complete" is its own decision), and it additionally requires 13.2's axes and the judge-provider decision.
- **Sequencing recommendation:** start with 13.1 — it is the cheapest story, has essentially no GPU dependency, and immediately reduces debugging cost. 13.2's scoring runs on CPU over existing outputs; 13.3's code work is non-GPU but its verification needs a live ComfyUI.
