# Epic 14 Context: Visual Asset Layer — Moving to Curated Sets (Backgrounds, D-Class, Objects)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A full-length viewing verdict left five coupled visual defects: broken perspective, inconsistent backgrounds, people drawn into supposedly empty backgrounds, narration that does not match the background or the character pose, and art-style drift across shots. They share one prescription — **stop generating a fresh background per shot and instead pick from human-approved asset sets**. Consistency, emptiness and style are filtered once at approval time; perspective, affordance and narration match, which cannot be guessed at generation time, become queryable metadata attached to the asset. Per-run GPU cost drops because backgrounds are no longer synthesized per shot (filling the sets is a one-time expense). This is not a new architecture: it completes an earlier, abandoned plate-reuse attempt and connects the existing stock-plate, asset-library and plate-data layers. (~~"and embedding-search"~~ — **falsified 2026-08-25, Story 14.1**: no embedding-search layer has ever existed. Story 8.19 explicitly declined its Stage 2; there is no `asset_retrieval_service.py`, no threshold and no score, and `pyproject.toml`/`config.py` carry zero embedding dependencies. Candidate ranking is founded on **measured plate metadata** — a `camera_angle -> viewpoint` map lookup plus filters — not on retrieval. The wording is struck rather than deleted because this premise was already corrected once in `epics.md` and reappeared here; a false cause fixed in one place gets re-cited from the other, `gotcha_recorded-root-cause-can-be-inverted`.)

## Stories

- Story 14.0: Research gate — perspective/population/narration work does not start without evidence (**done**)
- Story 14.1: Approved background plate sets — per-shot, prompt-aware reuse
- Story 14.2: Plate affordance gate — only plates a person can stand in get cast shots (**done**, knob ships OFF)
- Story 14.3: Art-style contract — plates and cards share one render style
- Story 14.4: People-free backgrounds as the shipping default — guard promotion + "person inside a picture" (**done**)
- Story 14.5: Narration ↔ background/pose match (**done** — the prompt edit was rejected; measurement corrections were the yield)
- Story 14.6: D-class and object asset sets + card library regeneration
- Story 14.7: Align the scenario reviewer with post-recompose rules (**done**)

## Requirements & Constraints

- **Reuse is the goal, not a regression.** When candidates run short, grow the set — never derive variants from one plate, and never "fix" reduced background diversity. The earlier attempt failed because assignment was keyed on scene rather than the shot's own image prompt, collapsing a 21-shot scene onto one plate.
- **Negative prompts are not the answer to background population.** Adding a negative clause per defect has wrecked renders twice, and person tokens were already present when a framed portrait still rendered. The only mechanism that has worked in this project is **detect-then-regenerate** (render, judge pixels, bump the seed).
- **Viewpoint is not a function of prompt text.** Same prompt, new seed flipped the viewpoint category in 2 of 5 controlled pairs. Text screening cannot guarantee framing; a viewpoint gate must measure the rendered pixels and re-roll.
- **Never promote a prompt-derived checklist to a visual gate.** Those questions are leading: unreadable frames score *higher* because there is nothing in them to contradict. Sub-axes are worse than the aggregate, not better. Any verdict that gates work must be **blind** to the generating prompt. A fourth round of instrumentation is not authorized — the next round changes the generator.
- **Screen every prompt change as text before spending GPU.** Two minutes of text screening has saved roughly six GPU-hours; both prompt edits attempted in this epic were adjudicated this way (one shipped, one rejected).
- **A decision only ships if it reaches the code default.** Product judgements live as the `config.py` default plus a dated verdict comment; env files stay unpinned, because a pinned example file is a revert every fresh checkout performs on day one. The drift report is an instrument, not a build gate.
- **Undecidable judgements are accepted, not retried** — they consume no ladder rung, but they must raise a per-shot warning, land in the render sidecar, and re-fire on resume. Never count an unscreened frame as clean.
- **Sampler-internal interventions are unavailable** (no custom node installed implements them). Narration-match work goes through the prompt-rewriting layer instead.
- **Identity floor holds.** No new scene-conditioned human-insertion model is being adopted; poses come from *more approved cards*, not from re-posing away from the approved pixels. Art-style work must not loosen identity to close the style gap.
- **Writing to a character's angle paths is publishing** — regeneration happens behind an approval gate.

## Technical Decisions

- **The shot is the image-generation unit**, mapped N:M onto narration sentences. Plate assignment, affordance judging and match scoring must all be per-shot; dropping to scene granularity reproduces the known collapse.
- **Affordance = asset metadata plus a runtime path for free-generated shots, with one shared judgement schema.** Stock-substituted shots get their verdict from the asset; free-generated shots get it at runtime. The runtime half is permanent, not throwaway — what the approved sets change is its scope, not its existence.
- **A shared judgement prompt is not enough — the request envelope must match too.** Image-before-text vs text-before-image is a deterministic order effect that flipped reproduction from 3/7 to 5/7 with zero within-condition flips. Pin image-first plus temperature 0 wherever an offline curator and the runtime must agree. (The people-free guard still uses the other order; that gap is deferred, so its measured numbers are envelope-specific.)
- **One VLM blind spot is permanent, not intermittent**: corpse/medical/gore plates get a hard content rejection from the vision endpoint. Since those are routine output here, treating "undecidable" as "no standing room" would delete cast from that whole class.
- **Do not build a floor/ceiling text-mass gate.** Measured on shipped plates, surface-noun mass runs *opposite* to the hypothesis, and the residual signal is prompt-length confounding. Lighting vocabulary shows a main effect only, with no dose-response and counterexamples at maximum dose.
- **Camera-angle field and prompt body do not conflict** (43/43 agreement) — an assumption to the contrary was repeated across four documents and is false. The field never reaches the background renderer's prompt but does drive cast-card angle selection, so it is not render-inert. The intervention point is inside the prompt text.
- **Existing end behavior for an unusable plate already exists** — cast suppression on no-figure framing. Extend that rather than adding a layer, and do not widen its keyword vocabulary (high-angle plates are overwhelmingly fine).
- **Denominators must exclude rows whose correct answer is "no event"** — descriptive or definitional sentences carry no depictable event, and pooling them rewards inventing content the narration never claimed.
- **Any regeneration comparison needs a same-prompt control leg.** Re-rolling the old prompt alone moved the target axis by +7pp; without that leg the re-roll noise is credited to the edit.

## Cross-Story Dependencies

- The research gate (14.0) blocked 14.2, 14.3 and 14.5; it is closed, and each of the three inherits a constraint from it (assets-not-models for pose, metadata-plus-runtime for affordance, prompt-rewriting for narration match).
- **14.2's metadata half depends on 14.1** — without approved sets there is nothing to attach a verdict to. The runtime half shipped first and is currently the only reachable path, since stock substitution is off and every shot is free-generated. 14.2's gate is also inert for shots that take a plate copy, so its interaction with 14.1 must be designed jointly.
- **14.1 owns the "person inside a picture" class** (framed art, monitors, posters, anatomical models, statues), handed over from 14.4 as an approval-gate criterion; the runtime guard deliberately does not fire on it. Until the sets cover free-generated shots, that defect class is an accepted, documented risk.
- **14.3 inherits three misattributed cases from 14.2** — tilted-floor perspective, figure-scale dominance, and placement off an existing floor. All three have adequate standing room, so no affordance gate can catch them; they belong to the recompose placement/grounding layer.
- **14.5's pose half moved to 14.6.** Measuring pose match is pointless while the card library is the un-regenerated product of a superseded prompt and cast fallbacks are asset-absence.
- **14.6 closes the non-retroactive state** left by an earlier character-prompt update and supplies the poses 14.0 decided to solve with assets rather than models.
- Pixel adjudication for the remaining axes is not owned by any single story — it rides the next full end-to-end iteration's blind readability judgement.
