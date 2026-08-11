# Epic 10 Context: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰 (Viewing-Verdict Defect Correction)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Jay watched E2E run `8a9a288b` (SCP-049, 3:06) on 2026-08-08 and listed 16 numbered visual/audio defects (지적 1–16). This epic exists to make **which story actually removed which visual defect** traceable — the prior session closed several Epic 8 stories and the watched result did not change, with no way to prove afterwards what had helped. Each story therefore owns a specific 지적 number and closes only on artifact evidence (rendered frames/clips a human judged), never on passing tests or wired code. A standing caveat: the reviewed run was rendered with `depth_placement_enabled=false`, so 8.16 grounding and 11.5 parallax were both **off**; 지적 3·11 were evidence that features were disabled, not that they were ineffective. Story 10.1 established that off/on baseline first, and the epic's confirmed direction (below) grew out of it.

## Stories

- Story 10.1: Grounding/composite live verification (지적 3·11) — **done**
- Story 10.1b: Card-plate fusion via harmonization tier 3 / IC-Light (지적 3) — **rejected** (live viewing verdict "나빠졌다")
- Story 10.1c: Shot recomposition — background + cards + placement instruction → one generated image (지적 3·11) — **done** (feature ships default OFF)
- Story 10.2: Force unpopulated backgrounds (지적 5·12) — **done**
- Story 10.3: Style consistency + LoRA compatibility (지적 10·12) — **done**
- Story 10.4: Image↔narration semantic match (지적 2·4·7·9·16) — **done** (measurement axis built; mapping hypothesis killed; prompt not promoted)
- Story 10.4b: Never ask the renderer to draw an absence — remove unreadable frames (지적 2) — **open (backlog)**
- Story 10.5: Action state not reflected on cards (지적 6) — **open (backlog)**
- Story 10.6: Cast display coherence — D-class quality, visual duplicates (지적 14·15) — **open (backlog)**
- Story 10.7: Scene sound replacement — siren (지적 13) — **done**

Out of epic scope: 지적 1 (narration wording → Epic 12), 지적 8 (set/plate reuse → Epic 8).

## Requirements & Constraints

- **Closing condition for every story:** produce an artifact showing the assigned 지적 number is gone. Metrics support the argument; the human viewing verdict decides. A gate metric that improves while viewing does not is itself a finding to record, not a pass.
- **Measurement discipline** (earned the hard way in this epic): state the sample band/coordinates with any pixel number, keep a control leg, and leave a one-command recompute script beside the evidence. Pre-register the pass/fail rule *before* seeing scores; do not invent a threshold at the moment you first see a distribution.
- **Isolate before attributing.** Recorded root causes in this epic have been found inverted (the style-drift culprit was the opposite LoRA of the one documented). Re-confirm attribution by loading one variable at a time.
- **New paths enter default off** and must degrade to the existing path in a recorded way (a silent fallback is a defect).
- Remaining open stories need new pipeline runs, so they are gated on a working `YTFLOW_GEMINI_API_KEY`; work that only re-runs the `video`/`image` stage of an existing run is not.
- Automated E2E budget is ~2 hours and is dominated by image generation; any per-shot generative pass must be costed against that ceiling.
- Only commercially licensed models/weights may enter the monetized pipeline (this is why IC-Light v2/Flux are permanently excluded).

## Technical Decisions

### ⛳ Confirmed direction (Jay, 2026-08-08) — card and background are finally **fused into one image**

**Read this before proposing anything that contradicts it.** Overlaying a card onto a plate with ffmpeg is not the deliverable. Background and character cards are **inputs used to re-create the image**. Jay's words: *"물리적으로 이어 붙이는 게 아니라"*, *"아예 1개의 이미지로 합성"*, *"기존 배경 + 캐릭터 카드들을 이용한 이미지의 재창조"*.

The discriminator, one line: if the card region of the output is nearly identical to the source card pixels, that is overlaying, not re-creation. Card pixels are a **reference for identity**, not protected content; composition and identity are held by conditioning, not by masks or by placement arithmetic in code.

**Rejected and not to be revived** (all are "overlay then fix"): harmonization tier 3 / IC-Light relight; masked low-denoise img2img fusion; ControlNet+IPAdapter applied on top of a composited still. All three take an already-overlaid frame as input, so `ffmpeg`-side code constants keep deciding position/scale/pose and the model only paints over them — and no constant can stand a figure on a floorless plate. Keep `composite_harmonization_tier` at **1**.

**Adopted path (10.1c, live-validated):** Qwen-Image-Edit-2511 (Apache-2.0, Q4_K_M) with plate as `image1`, cards as `image2/3`, and a natural-language placement instruction; **sequential insertion, one figure per pass, far→mid→near**, with a preservation clause so earlier passes survive. It draws a floor where none existed and casts a matching shadow. Operational preconditions the code does **not** yet detect or enforce: ComfyUI must run with `--lowvram --disable-smart-memory`, and the text encoder must stay **fp8** (GGUF Q4 lacks the vision tower and fails outright). ~90–120s per pass. The feature stays **off by default**; flipping it requires readability parity on 13.2's rebuilt axes for paired on/off sets plus a runtime precondition guard, and the flip commit is what removes the then-dead placement code (8.16 grounding, `_GROUND_Y_MAX` clamp, occlusion mask, contact shadow, 11.5 parallax, idle motion). Accepted cost of fusion: the card can no longer move independently of the background, so layered parallax and character idle motion go away — that removal is intended.

### ⛳ Background policy — source reuse is intent, not a diversity regression

Reusing one background source across many shots is **desired**: spatial continuity and cross-episode consistency are the channel identity, so the same room should be the same picture. Do not "fix" shrinking background variety, and do not derive per-shot variants from one plate — Jay: *"소스가 되는 배경 수를 늘려야지, 하나의 소스로 여러 개를 만들려고 하지 마. 그게 더 이상해져, 일관성 없어지고."* The remedy is a larger plate library, and `stock_plate_substitution_enabled` is on the **enable** trajectory. Implication for re-creation: hold the plate's composition hard; what gets redrawn is the figure and its junction with the floor, not the room.

### Standing prohibitions (each has live counter-evidence)

- Do not add negative-prompt clauses per defect — it has backfired twice.
- Do not regex-scrub person tokens out of `image_prompt` — it also deletes camera, scale, depicted figures, and absences.
- Diffusion cannot render an absence. A prompt whose subject is "nothing" produces geometry noise; the frame's subject must always be an existing object/surface/trace.
- Backgrounds are supposed to be unpopulated (the card-compositing architecture assumes it), yet blind captions read people in a large share of plates — treat that as an active confound in any semantic-match measurement, and enable 10.2's guard before gating on such a score.

### Evaluation instrumentation (from 10.4 → rebuilt in 13.2, now available)

- VLM 1–5 Likert axes died twice on their own data. `legible` is **abolished**, replaced by boolean `readable` (which surfaced ~18% unreadable frames the Likert scale scored 0%). `match` collapsed onto 3.
- The current instrument is **DSG** (atomic propositions + dependency graph) via the shot-narration scoring script: person propositions are generated then treated as satisfied-and-unasked (the card layer supplies them) so they neither pollute the denominator nor invalidate background propositions. VQAScore was live-rejected — the vision judge returns null logprobs.
- `readable` and `dsg_score` are **separate axes** and rank-uncorrelated; `dsg_score` is deliberately **not** a gate and has no threshold yet.
- Blind-first ordering is the only basis of these measurements: ask about the frame with the sentence hidden, then ask about the match. Showing the sentence first makes the VLM find a way to agree.
- Visual axes are record-only in A/B (they require a paid VLM pass); motion axes are tiebreak inputs and are **regression detectors, not discriminators** (they saturate on healthy runs).
- Mapping/coverage is dead as a semantic-match lever: hand-authored merges moved `match` by exactly 0.000. The N:M sentence↔shot coverage code stays, justified by render cost and cut rhythm (66→55 shots), not by meaning.

### Architectural boundary

Pipeline nodes must not be imported by `services/` except through explicitly allowlisted, contract-matching seams; an allowlisted node module is itself re-checked for not importing `api`/`services`/`db`, so the allowlist cannot launder a services→pipeline→services cycle. When a new image path replaces `shot["image_path"]`, every derived artifact key (depth maps, masks) must be dropped or regenerated — a stale derived map warps the new frame and reproduces the exact symptom the new path removed.

## Cross-Story Dependencies

- 10.1 → 10.1b → 10.1c is a single chain of verdicts; 10.1c supersedes both predecessors and owns the confirmed direction. Its 6-shot slate, frame-pair maker, and measurement script are reusable comparison infrastructure for any later card/background work.
- **10.4b must not start before 13.2's instrument is in place** — judging with the collapsed 3-heavy `match` score would repeat 10.4's inconclusive round verbatim. 13.2's instrument replacement is complete (status: review), so this blocker is cleared in substance.
- 10.4b's alternative to "draw a background for a sentence with no renderable referent" is either 10.4's coverage code (fold into a neighbouring frame) or 10.1c's recomposition path — so its scope depends on 10.1c's default-off flip decision.
- 10.2's unpopulated-background guard must be enabled before any semantic-match number is used as a gate (person-in-plate readings confound it).
- 10.5 inherits 8.20's residue (pose-conditioning column, closed pose-guide key, guide assets) and is blocked on choosing a replacement technique after 8.20's live rejection.
- Backgrounds/plates interact with Epic 8 (plate library growth, `stock_plate_substitution_enabled`); evaluation axes and promotion gating live in Epic 13 (13.2 axes, 13.4 winner-determination); narration/script quality defects were handed to Epic 12.
