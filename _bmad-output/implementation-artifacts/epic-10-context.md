# Epic 10 Context: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰 (Viewing-Verdict Defect Correction)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Jay watched E2E run `8a9a288b` (SCP-049, 3:06) on 2026-08-08 and listed 16 numbered visual/audio defects (지적 1–16). This epic exists to make **which story actually removed which visual defect** traceable — the prior session closed several Epic 8 stories, the watched result did not change, and there was no way to prove afterwards what had helped. Each story owns a specific 지적 number and closes only on artifact evidence (rendered frames/clips a human judged), never on passing tests or wired code. A standing caveat: the reviewed run was rendered with `depth_placement_enabled=false`, so 8.16 grounding and 11.5 parallax were both **off**; 지적 3·11 were evidence that features were disabled, not that they were ineffective. Story 10.1 established that off/on baseline, and the epic's confirmed direction (below) grew out of it. Nine of ten stories are now closed; only 10.5 remains.

## Stories

- Story 10.1: Grounding/composite live verification (지적 3·11) — **done**
- Story 10.1b: Card-plate fusion via harmonization tier 3 / IC-Light (지적 3) — **rejected** (live viewing verdict "나빠졌다")
- Story 10.1c: Shot recomposition — background + cards + placement instruction → one generated image (지적 3·11) — **done** (feature ships default OFF)
- Story 10.2: Force unpopulated backgrounds (지적 5·12) — **done** (guard ships default OFF)
- Story 10.3: Style consistency + LoRA compatibility (지적 10·12) — **done**
- Story 10.4: Image↔narration semantic match (지적 2·4·7·9·16) — **done** (measurement axis built; mapping hypothesis killed; prompt not promoted)
- Story 10.4b: Never ask the renderer to draw an absence (지적 2) — **done, closed on an invalid premise** (change reverted; one real bug kept)
- Story 10.5: Action state not reflected on cards (지적 6) — **open (backlog)** — the only remaining story
- Story 10.6: Cast display coherence — D-class quality, visual duplicates (지적 14·15) — **done** (rule fixed; not retroactive to existing assets)
- Story 10.7: Scene sound replacement — siren (지적 13) — **done**

Out of epic scope: 지적 1 (narration wording → Epic 12), 지적 8 (set/plate reuse → Epic 8).

## Requirements & Constraints

- **Closing condition for every story:** produce an artifact showing the assigned 지적 number is gone. Metrics support the argument; the human viewing verdict decides. A gate metric that improves while viewing does not is itself a finding to record, not a pass. A rule fix that cannot reach already-generated assets closes the *rule*, not the defect — say so explicitly.
- **Verify the premise before starting.** 10.4b was closed as invalid-premise: the behaviour it was written to remove had already been fixed by a one-line 10.2 prompt edit, and the story's own quoted evidence ("all 12 prompts subject an absence") did not survive row-level checking. Re-derive the defect from current text/data and its timeline before spending a run on it.
- **Screen before you render.** A prompt-text judge pass (no GPU, ~2 min for a full script) is the entry gate for any prompt change; only candidates that beat the measured text baseline earn a paired render A/B. This ordering demonstrably saved ~6 GPU-hours in one round.
- **Measurement discipline:** state the sample band/coordinates with any pixel number, keep a control leg, leave a one-command recompute script beside the evidence. Pre-register the pass/fail rule *before* seeing scores. Watch for effects that are LLM sampling variance rather than stable properties — re-running the same prompt can move the metric as much as the change does.
- **Isolate before attributing.** Recorded root causes in this epic have been found inverted (the style-drift culprit was the opposite LoRA of the one documented). Re-confirm attribution by loading one variable at a time.
- **New paths enter default off** and must degrade to the existing path in a recorded way (a silent fallback is a defect).
- ComfyUI returning HTTP 200 does not mean the GPU is free — inspect the queue's running/pending workflow classes before planning a render budget. Automated E2E budget is ~2 hours and is dominated by image generation.
- `yt_flow.db` is gitignored, so "git status is clean" proves nothing about asset/DB state; assert row counts and field contents with read-only queries instead.
- Only commercially licensed models/weights may enter the monetized pipeline (this is why IC-Light v2/Flux are permanently excluded).

## Technical Decisions

### ⛳ Confirmed direction (Jay, 2026-08-08) — card and background are finally **fused into one image**

**Read this before proposing anything that contradicts it.** Overlaying a card onto a plate with ffmpeg is not the deliverable. Background and character cards are **inputs used to re-create the image**. Jay's words: *"물리적으로 이어 붙이는 게 아니라"*, *"아예 1개의 이미지로 합성"*, *"기존 배경 + 캐릭터 카드들을 이용한 이미지의 재창조"*.

The discriminator, one line: if the card region of the output is nearly identical to the source card pixels, that is overlaying, not re-creation. Card pixels are a **reference for identity**, not protected content; composition and identity are held by conditioning, not by masks or placement arithmetic in code.

**Rejected and not to be revived** (all are "overlay then fix"): harmonization tier 3 / IC-Light relight; masked low-denoise img2img fusion; ControlNet+IPAdapter applied on top of a composited still. All three take an already-overlaid frame as input, so ffmpeg-side code constants keep deciding position/scale/pose and the model only paints over them — and no constant can stand a figure on a floorless plate. Keep `composite_harmonization_tier` at **1**.

**Adopted path (10.1c, live-validated):** Qwen-Image-Edit-2511 (Apache-2.0, Q4_K_M) with plate as `image1`, cards as `image2/3`, and a natural-language placement instruction; **sequential insertion, one figure per pass, far→mid→near**, with a preservation clause so earlier passes survive. It draws a floor where none existed and casts a matching shadow. Operational preconditions the code does **not** detect or enforce: ComfyUI must run with `--lowvram --disable-smart-memory`, and the text encoder must stay **fp8** (GGUF Q4 lacks the vision tower and fails outright). ~90–120s per pass. The feature stays **off by default**; flipping it requires readability parity on 13.2's rebuilt axes for paired on/off sets plus a runtime precondition guard, and the flip commit is what removes the then-dead placement code (8.16 grounding, `_GROUND_Y_MAX` clamp, occlusion mask, contact shadow, 11.5 parallax, idle motion). Accepted cost: the card can no longer move independently of the background, so layered parallax and idle motion go away — that removal is intended.

### ⛳ Background policy — source reuse is intent, not a diversity regression

Reusing one background source across many shots is **desired**: spatial continuity and cross-episode consistency are the channel identity, so the same room should be the same picture. Do not "fix" shrinking background variety, and do not derive per-shot variants from one plate — Jay: *"소스가 되는 배경 수를 늘려야지, 하나의 소스로 여러 개를 만들려고 하지 마. 그게 더 이상해져, 일관성 없어지고."* The remedy is a larger plate library, and `stock_plate_substitution_enabled` is on the **enable** trajectory. Implication for re-creation: hold the plate's composition hard; what gets redrawn is the figure and its junction with the floor, not the room.

### Standing prohibitions (each has live counter-evidence)

- Do not add negative-prompt clauses per defect — it has backfired twice.
- Do not regex-scrub person tokens (or any clause class) out of `image_prompt` — a clause scrubber built in 10.2 damaged 27 of 313 real prompts (camera slots, deliberately reserved card space, emptiness assertions) and was deleted after measurement.
- Diffusion cannot render an absence. A prompt whose subject is "nothing" produces geometry noise; the frame's subject must always be an existing object/surface/trace. (This teaching has been removed from the live prompt already — do not re-open it as a defect without re-measuring.)
- Backgrounds are supposed to be unpopulated, yet blind captions read people in a large share of plates. 10.2's post-generation detector exists but is **default off** (`background_person_guard_attempts=0`); it must be explicitly enabled before any semantic-match score is used as a gate. Its root cause is still unproven.
- Derived character cards must have **authored** descriptors — inheriting the base entity's `visual_descriptor` (plus an anchor image) makes the derivative look like the original. Unauthored derived keys skip with a WARNING rather than guessing.

### Evaluation instrumentation (from 10.4 → rebuilt in 13.2, available)

- VLM 1–5 Likert axes died twice on their own data. `legible` is **abolished**, replaced by boolean `readable` (which surfaced ~18% unreadable frames the Likert scale scored 0%). `match` collapsed onto 3.
- The current instrument is **DSG** (atomic propositions + dependency graph) via the shot-narration scoring script: person propositions are generated then treated as satisfied-and-unasked (the card layer supplies them) so they neither pollute the denominator nor invalidate background propositions. VQAScore was live-rejected — the vision judge returns null logprobs.
- `readable` and `dsg_score` are **separate axes** and rank-uncorrelated; `dsg_score` is deliberately **not** a gate and has no threshold yet.
- Blind-first ordering is the only basis of these measurements: ask about the frame with the sentence hidden, then ask about the match. Showing the sentence first makes the VLM find a way to agree.
- A **prompt-text** compliance judge (no render, no GPU) complements the frame judges. Its live baseline on the current prompt: physical-subject compliance 100%, but `visible_event` — does the prompt contain a visible trace of *this sentence's event* — sits at **84.9% (56/66)**. That gap is the epic's surviving image-semantics defect and the target any successor must beat. It explains the unreadable frames whose subject was already concrete but whose event read as "unclear".
- Mapping/coverage is dead as a semantic-match lever: hand-authored merges moved `match` by exactly 0.000. The N:M sentence↔shot coverage code stays, justified by render cost and cut rhythm (66→55 shots), not by meaning.

### Architectural boundary

Pipeline nodes must not be imported by `services/` except through explicitly allowlisted, contract-matching seams; an allowlisted node module is itself re-checked for not importing `api`/`services`/`db`, so the allowlist cannot launder a services→pipeline→services cycle. When a new image path replaces `shot["image_path"]`, every derived artifact key (depth maps, masks) must be dropped or regenerated — a stale derived map warps the new frame and reproduces the exact symptom the new path removed.

## Cross-Story Dependencies

- 10.1 → 10.1b → 10.1c is a single chain of verdicts; 10.1c supersedes both predecessors and owns the confirmed direction. Its 6-shot slate, frame-pair maker, and measurement script are reusable comparison infrastructure for any later card/background work.
- 13.2's instrument rebuild is **done**, so the "wait for a resolving instrument" blocker that governed 10.4/10.4b is cleared; the remaining semantic-image work is a successor to 10.4b targeting `visible_event`, not a re-run of its prompt wording.
- 10.5 is the only open story. It inherits 8.20's residue (pose-conditioning column, closed pose-guide key, guide assets) and is blocked on choosing a replacement technique after 8.20's live rejection; 10.6 handed it fresh evidence that requested poses are ignored in 7/7 renders (figures stand regardless of instruction).
- 10.6's fix is not retroactive: derived cards are only generated when no row exists, so `SCP-049-2` keeps its inherited plague-doctor descriptor and 지적 15 remains visible in any run reusing current assets. Removing it from screen is an asset-replacement decision behind Jay's gate.
- Ungated on-demand pose-hint cards (no approval/epoch filter) contaminated the D-class frames; that gating decision is also deferred to Jay.
- Backgrounds/plates interact with Epic 8 (plate library growth, `stock_plate_substitution_enabled`); evaluation axes and promotion gating live in Epic 13 (13.2 axes, 13.4 winner determination); narration/script quality defects were handed to Epic 12.
