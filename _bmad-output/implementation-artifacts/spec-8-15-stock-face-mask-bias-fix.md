---
title: 'Story 8.15: STOCK character face-mask bias fix'
type: 'bugfix'
created: '2026-08-01'
baseline_revision: 'fcad36f7eaac8451e70bf32a10d75914ff60b354'
status: 'blocked'
review_loop_iteration: 0
followup_review_recommended: true
final_revision: '6f7238b'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** All three STOCK extras (`STOCK-d-class`, `STOCK-researcher`, `STOCK-security`) render with SCP-049's skull mask and glowing red eyes, so ordinary humans are visually indistinguishable from the entity. Root cause is a three-link chain, not just thin descriptors: (1) `STOCK_DESCRIPTORS` carries clothing/build terms and **zero** face/head terms; (2) the `horror.safetensors` LoRA @0.6 in the shared character workflow biases an unconstrained face toward masks; (3) a **descriptor-poisoning loop** — after the front card is generated, `enrich_descriptor_from_references` writes a vision-model description of that bad front back into `characters.visual_descriptor`, so the remaining three angles *explicitly prompt for* the mask. The poisoned text is live in the DB today (e.g. `STOCK-d-class`: "white, skull-like mask … red, glowing eyes").

**Approach:** Give each STOCK descriptor explicit bare-face/no-mask terms plus a STOCK-only negative-prompt suffix threaded through to the ComfyUI negative node (the shared workflow's own negative must stay mask-neutral — SCP-049 legitimately needs a mask). Regenerate all three key sets into a **staged** new style epoch that runtime never reads, then promote to live only via an explicit operator approval command.

## Boundaries & Constraints

**Always:**
- Staged cards must not become live. Runtime standing-card resolution is a bare column read (`_resolve_card_path`, character_service.py:1307-1331 reads `Character.angle_*_path` with **no** status and **no** epoch filter), so writing `angle_*_path` *is* going live. Staging therefore writes files only — no `Character` row repoint, no `add_asset`, no `approve_asset`.
- `epoch_1` files, DB rows, and manifest entries stay byte-identical until promotion. Rejection must be a no-op recoverable by deleting the staged directory.
- The regenerated `visual_descriptor` must be verified free of mask/skull/glowing-eye language after generation — that is the measurable proof link (3) is broken.
- Negative-prompt strengthening is per-call and STOCK-scoped. `data/workflows/comfyui_character_multi_angle_api.json`'s node "7" text is shared with entity cards and must not gain mask/skull terms.
- Existing `seed_stock_cast.py` is modified in place; no new service.

**Block If:**
- Any of the three staged front cards still shows a mask, helmet covering the face, or glowing eyes → HALT `blocked`, do not promote.
- After all three key sets are staged: HALT `blocked` with blocking condition `awaiting Jay visual approval`, listing every staged file path. Promotion is Jay's command, never this run's.
- ComfyUI at `localhost:8188` unreachable or a key yields <4 cards → HALT `blocked`.

**Never:**
- Do not auto-approve, auto-promote, or repoint live card paths.
- Do not add mask/skull/eye terms to the shared workflow negative node, and do not lower/remove the `horror` LoRA (shared with entity cards).
- Do not promote or re-seed the Langfuse `character-generation` prompt. Verified live: version 3, label `production`, and it is **missing** the repo file's studio-sprite/no-crop/"same face, mask or head design" boilerplate — the repo `prompts/character/generation.md` never reaches ComfyUI. Real defect, out of scope here (PROMPT_POLICY promotion is the operator's, and AI sessions are hard-blocked from the evaluator). Record it as a follow-up; this story must work without it.
- Do not touch `src/yt_flow/pipeline/nodes/subtitle.py`, `tts.py`, `scenario_chain.py`, or anything under `_bmad-output/story-automator/` — a concurrent session owns them.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stage a replacement set | `--stage`, live epoch 1 complete for key | epoch bumped once to 2; 4 files at `epoch_2/{angle}_candidate_1.png`; `Character.angle_*_path` still epoch_1; no manifest write | No error expected |
| Stage is idempotent-safe | `--stage` run twice | Second run regenerates into the same staged epoch; never bumps twice, never overwrites epoch_1 | No error expected |
| Completeness guard | `--stage` with a complete live set | Guard bypassed (staging always regenerates) | No error expected |
| Promote after approval | approve command, staged files present | `angle_*_path` + `selected_image_path` repointed to epoch_2; manifest entries added and approved | Missing/alpha-less staged file → refuse, leave live state untouched, exit non-zero |
| Promote before staging | approve command, no staged files | Refuse with a clear message | Exit non-zero, no writes |
| Stale derived cards | `STOCK-d-class` has 3 approved `hint:*` special-pose cards derived from the poisoned front | On promotion they are retired so 8.4's on-demand path rebuilds them from the new front | Retire failure logs a warning; promotion still completes |
| Partial angle failure | one angle fails during staging | <4 cards → RuntimeError as today; nothing promoted | Existing `RuntimeError` path |

</intent-contract>

## Code Map

- `scripts/seed_stock_cast.py` — `STOCK_DESCRIPTORS` (:20-33, the content fix), `_pose_complete` guard (:51-59), `seed_key` (:81-104), argparse (:142-150). New `--stage` flag + `STOCK_NEGATIVE` constant land here.
- `src/yt_flow/services/character_service.py` — `generate_cards_from_descriptor` (:779-846): repoints `angle_*_path` at :841-845 (the live-write to suppress) and runs the poisoning enrichment at :831-837. `generate_candidates_from_reference` (:681-777): epoch path at :713-714, `add_asset`/`approve_asset` at :754-759 (suppress when staging). `_resolve_card_path` (:1307-1331): proof that standing resolution ignores status/epoch.
- `src/yt_flow/services/character_image_provider.py` — `CharacterImageProvider.generate` ABC (:92-112), `ComfyUICharacterProvider.generate` (:149+), `_inject_prompt` deliberately skips negative nodes (:206-223). Negative suffix injection goes here.
- `src/yt_flow/services/asset_service.py` — `style_epoch` / `bump_style_epoch` (:119-126, currently **no caller**; this story is the first). In-place `add_asset` overwrite caveat at :49-53 — avoided by not writing the manifest while staged.
- `assets/manifest.json` — `style_epoch: 1`, 41 assets, all 15 STOCK entries approved.
- `tests/test_seed_stock_cast.py` — 8 existing tests; note :141 asserts descriptors self-referentially, so descriptor content is currently untested.
- No relit cache exists on disk, so bumping the global epoch costs nothing today (`composite_harmonization.py:199` would treat entries as misses).

## Tasks & Acceptance

**Execution:**
- [x] `scripts/seed_stock_cast.py` -- rewrite the three `STOCK_DESCRIPTORS` to lead with explicit head/face state (bare head, ordinary unremarkable human face, visible eyes and skin, no mask, no helmet covering the face, no glowing eyes) while keeping existing wardrobe terms; drop "or doctor" ambiguity from the researcher entry -- descriptors are the only face constraint that actually reaches ComfyUI today.
- [x] `scripts/seed_stock_cast.py` -- add a `STOCK_NEGATIVE` constant (skull mask, plague doctor mask, gas mask, full-face mask, glowing eyes, red glowing eyes, monster face, undead, horror creature face) and pass it down as `negative_suffix` -- suppression belongs where the LoRA bias is, without touching the shared workflow negative.
- [x] `src/yt_flow/services/character_image_provider.py` -- add `negative_suffix: str | None = None` to the `generate` ABC and both implementations; in the ComfyUI implementation append it to the negative CLIP node's existing text (node "7" / titles matching negative|neg |bad) -- `_inject_prompt` intentionally refuses to write negatives, so this is a separate injector.
- [x] `src/yt_flow/services/character_service.py` -- thread `negative_suffix` through `generate_cards_from_descriptor` → `generate_candidates_from_reference` → `provider.generate`; add `stage: bool = False` which, when true, skips `add_asset`/`approve_asset`/`save_card` and skips the final `angle_*_path`/`selected_image_path` repoint -- staging must be filesystem-only.
- [x] `scripts/seed_stock_cast.py` -- add `--stage`: bump the style epoch once per invocation if the target epoch already holds live cards, bypass `_pose_complete`, generate with `stage=True`, and print every staged path -- one flag with one meaning, so staged output can never land on live files.
- [x] `scripts/approve_stock_cast.py` -- new operator CLI mirroring `scripts/approve_location_plate.py`: `--key` (default all three) / `--reject`; verifies each staged file exists with a real alpha channel, then repoints `angle_*_path` + `selected_image_path`, registers and approves manifest entries, and retires `STOCK-d-class`'s stale `hint:*` cards; `--reject` deletes the staged directory and touches nothing live -- promotion is the only path that makes cards live.
- [x] `tests/test_seed_stock_cast.py` -- assert each descriptor contains bare-face/no-mask terms and no mask/skull/glowing-eye terms; assert `--stage` bypasses the completeness guard and calls through with `stage=True` and a non-empty `negative_suffix`.
- [x] `tests/services/test_character_service_generation.py` -- assert `stage=True` writes files but performs no manifest write, no approval, and no `angle_*_path` repoint; assert `negative_suffix` reaches the provider.
- [x] `tests/services/test_character_image_provider.py` (or nearest existing provider test) -- assert the negative suffix is appended to the negative node's existing text and that the positive node is unchanged.
- [x] Run the live staging pass against ComfyUI on `localhost:8188` for all three keys, verify each staged front visually and verify the resulting `visual_descriptor` values are mask-free, then HALT for Jay's approval.

**Acceptance Criteria:**
- Given the three fixed descriptors, when the test suite runs, then descriptor content is asserted (not self-referentially) and the full suite stays green.
- Given a `--stage` run, when it completes, then 12 staged files exist under `epoch_2`, and `Character.angle_*_path`, `assets/manifest.json`, and every `epoch_1` file are unchanged.
- Given staged cards, when a pipeline run resolves `STOCK-*` cast, then it still resolves the epoch_1 cards — staged cards are invisible to runtime until promotion.
- Given generation completed, when `characters.visual_descriptor` is read for each STOCK key, then it contains no mask/skull/glowing-eye language.
- Given the approve command with `--reject`, when it runs, then the staged directory is gone and live state is byte-identical to before staging.
- Given all three key sets are staged, when the run reaches its end, then it HALTs `blocked` with `awaiting Jay visual approval` and lists all staged paths — nothing is promoted by this run.

## Spec Change Log

### 2026-08-01 — Design amendment (outside intent-contract)

- **Triggering finding:** the Design Notes reasoned that writing `visual_descriptor` during staging was harmless, and AC4 was built on top of that. Review showed the opposite: `enrich_descriptor_from_references` overwrites that column with vision-model text whose own prompt says "an SCP Foundation character" — the exact token the descriptors were purged of, and the token live probing proved is the mask attractor. Angles 2–4 are prompted from that column, so three of four staged cards were being generated from re-poisoned text.
- **Amended:** `generate_cards_from_descriptor` gained `enrich: bool = True`; the STOCK seeding path passes `enrich=False`. Derived keys keep enrichment (they need the family resemblance). `--reject` now restores the pre-stage descriptor from a sidecar written into the staged directory, so a rejected stage really is a no-op on live state.
- **Known-bad state avoided:** a staged set whose front is clean and whose other three angles carry the mask, with no automated signal — the exact defect this story exists to remove, reintroduced by its own fix.
- **KEEP:** the staging-writes-files-only design (no `add_asset`, no `approve_asset`, no row repoint) and the promotion-time epoch bump both survived review and must survive any re-derivation.

### 2026-08-01 — Scope addition (outside intent-contract)

- **Triggering finding:** the first live staging pass failed with a 400 from the vision API. Root cause: the enrichment call borrowed `deepseek_max_tokens`, and `YTFLOW_DEEPSEEK_MAX_TOKENS=16384` exceeds qwen-vl-plus's documented `[1, 8192]` range — so every enrichment call had been failing silently since that value was raised (2026-07-12, E2E iteration 2).
- **Amended:** added `character_vision_max_tokens: int = Field(2000, gt=0, le=8192)` and pointed the call at it, with a regression test. Not in the original task list; recorded here rather than left as an unexplained drive-by.

## Review Triage Log

### 2026-08-01 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 5, medium 7, low 2)
- defer: 4: (medium 3, low 1)
- reject: 3
- addressed_findings:
  - `[high]` `[patch]` Shared test stub `_FakeCharacterImageProvider.generate` lacked `negative_suffix`, so every stubbed angle raised `TypeError` into a broad `except` — silently failing while the suite stayed green. Kwarg added.
  - `[high]` `[patch]` Vision enrichment reinjected "SCP Foundation" into `visual_descriptor`, re-poisoning angles 2–4. Added `enrich=False` for STOCK keys (see Spec Change Log).
  - `[high]` `[patch]` `STOCK_NEGATIVE` had grown to repeat `face` five times; live renders came back with a blank white face and a black void face. Trimmed to ten terms naming `face` zero times; body/age steering moved to the descriptor.
  - `[high]` `[patch]` `approve_stock_cast.py` checked for a character row inside the mutation loop, so a later missing row left earlier keys promoted *and* skipped the epoch bump — the next `--stage` would then regenerate over the freshly promoted live files. Check moved into the up-front pass.
  - `[high]` `[patch]` `--reject` left `visual_descriptor` describing a deleted image. Pre-stage value now snapshotted to a sidecar and restored.
  - `[medium]` `[patch]` `--reject` exited 0 when nothing was staged, reading as a successful undo.
  - `[medium]` `[patch]` `--key` promotion bumped the global epoch, orphaning any sibling still staged. Now refused.
  - `[medium]` `[patch]` `--stage --pose sitting` and derived keys staged files the approve script can neither promote nor reject. Now rejected up front.
  - `[medium]` `[patch]` `_inject_negative_suffix` would stringify a graph link into the prompt, stopped at the first negative node, and silently dropped the suffix when no node matched. All three fixed.
  - `[medium]` `[patch]` `approve_stock_cast.py` had zero tests despite being the only component that can destroy live assets. Added 9.
  - `[medium]` `[patch]` `STOCK-security` was missing the leg-coverage terms its siblings got.
  - `[low]` `[patch]` `QwenCharacterProvider.generate` silently discarded `negative_suffix`; now warns.
  - `[low]` `[patch]` `character_vision_max_tokens` was unclamped, so an env override could reproduce the 400 it prevents.
  - `[low]` `[patch]` Removed vacuous assertions that restated documented defaults.

## Design Notes

Why staging instead of `--force`: `--force` regenerates into `epoch_{current}/{angle}_candidate_1.png`, i.e. it **overwrites the live cards in place** and repoints nothing (paths are unchanged strings), so a bad regeneration is instantly live and unrecoverable. Bumping the epoch first makes the staged set a parallel directory, which is what makes an approval gate possible at all — and `bump_style_epoch()` already exists, unused, for exactly this.

Why not an approval status column: standing cards live on `Character.angle_*_path`, a table with no status column, and `_resolve_card_path` reads it directly. Adding a status column plus a filter to the hot resolution path is a larger, riskier change than pointing the row at approved files only after approval. Epoch directories give the same guarantee with no schema change.

## Verification

**Commands:**
- `PYTHONPATH=$PWD/src python -m pytest tests/test_seed_stock_cast.py tests/services/test_character_service_generation.py -q` -- expected: all pass
- `PYTHONPATH=$PWD/src python -m pytest -q` -- expected: full suite green, no regressions against the 1345-test baseline
- `python scripts/seed_stock_cast.py --stage` -- expected: 12 staged paths printed under `epoch_2`
- `sqlite3 yt_flow.db "select scp_id, angle_front_path from characters where scp_id like 'STOCK%'"` -- expected: still `epoch_1` paths after staging
- `git diff --stat assets/manifest.json` -- expected: no change after staging

**Manual checks (if no CLI):**
- Open each staged `epoch_2/front_candidate_1.png`: an ordinary human face, no mask/helmet over the face, no glowing eyes, correct wardrobe per key.

## Auto Run Result

Status: **blocked** — blocking condition: **awaiting Jay visual approval**

Code is complete, reviewed, patched and committed (`6f7238b`). Nothing is live: promotion is deliberately the operator's command.

### What changed

The mask bias is fixed, but not by the mechanism the draft assumed. Live probing on the real checkpoint (5 single-image variants, every other lever held constant) showed the literal token **`"SCP Foundation"`** in the positive prompt is itself the attractor: with it the render is a skull mask or a visored helmet, without it an ordinary person. Strengthening the negative prompt made things *worse* — a list that repeated `face` across several phrases suppressed faces themselves, producing a blank white face and a black void with eye slits. So the descriptors dropped the org name, went purely affirmative (text encoders do not negate — `"no mask"` in a positive prompt summons masks), and the negative was trimmed to ten terms that never say `face`.

### Files changed

- `scripts/seed_stock_cast.py` — rewrote `STOCK_DESCRIPTORS` (no org name, affirmative, adult/hair/long-trousers), added `STOCK_NEGATIVE`, `--stage`, the pre-stage descriptor sidecar, and a guard refusing stage targets the approve script cannot promote
- `scripts/approve_stock_cast.py` — **new** operator CLI: verifies every staged file up front, repoints `angle_*_path`, registers+approves manifest entries, retires stale `hint:*` cards, bumps the style epoch; `--reject` restores the descriptor and deletes the staged directory
- `src/yt_flow/services/character_service.py` — `negative_suffix`, `stage`, and `enrich` threaded through card generation; staging writes files only
- `src/yt_flow/services/character_image_provider.py` — per-call negative-suffix injection (the shared workflow's own negative stays mask-neutral for SCP-049), with link-valued-text and no-match-found guards
- `src/yt_flow/config.py` — `character_vision_max_tokens: Field(2000, gt=0, le=8192)`
- `tests/` — 12 new tests incl. 9 for the destructive approve CLI; fixed the shared provider stub

### Review findings

14 patches applied (5 high, 7 medium, 2 low), 4 deferred, 3 rejected. See Review Triage Log. Follow-up review recommended: the patch set was broad and touched a destructive CLI plus the provider protocol.

### Verification

- `PYTHONPATH=$PWD/src python -m pytest -q` → **1494 passed, 1 skipped** (baseline 1482)
- `ruff check scripts/ src/ tests/` → clean
- Staging invariants after the live pass: `characters.angle_*_path` still on `epoch_1`, `assets/manifest.json` md5 unchanged (`b2af93a2…`), all 12 `epoch_1` files untouched, 12 new files under `epoch_2`

### Per-key visual verdict (the gate Jay owns)

| Key | Mask defect | Verdict |
|---|---|---|
| `STOCK-d-class` | gone | **pass** — plain face, hair, single subject; reads a little young, hair over one eye, feet slightly malformed |
| `STOCK-researcher` | gone | **fail** — correct face and wardrobe but **two figures** in one card |
| `STOCK-security` | gone | **pass**, best of the three; garbled "SSECOURITY" lettering, and a more painterly style than d-class |

Staged files awaiting inspection:

```
assets/characters/STOCK-d-class/epoch_2/{front,back,side,three_quarter}_candidate_1.png
assets/characters/STOCK-researcher/epoch_2/{front,back,side,three_quarter}_candidate_1.png
assets/characters/STOCK-security/epoch_2/{front,back,side,three_quarter}_candidate_1.png
```

Promote: `PYTHONPATH=$PWD/src python scripts/approve_stock_cast.py` (all three in one invocation).
Reject: `PYTHONPATH=$PWD/src python scripts/approve_stock_cast.py --reject`.
Re-roll one key: `PYTHONPATH=$PWD/src python scripts/seed_stock_cast.py --stage --key STOCK-researcher` (seeds are randomised per call, so a re-roll is a genuinely different sample).

### Residual risks

- **The multi-figure defect has a known cause this story could not touch.** The Langfuse `character-generation` prompt is at v3 / `production` and lacks the repo file's `"one single subject … no extra characters"` boilerplate, so `prompts/character/generation.md` never reaches ComfyUI. Promoting it is the operator's call under PROMPT_POLICY. Until then, single-subject framing is unenforced and re-rolls are the only lever.
- **Front-card quality is not deterministic.** Seeds are randomised per call, so any one sample is weak evidence; the gate plus re-rolls is the control, not the prompt alone.
- **`enrich=False` for STOCK trades cross-angle identity for token safety.** Non-front angles now rest on IPAdapter alone, which the code's own comment says does not lock facial identity. Acceptable for deliberately generic extras; verify the back/side/three-quarter cards, not only the fronts.
- Three deferred items (special-pose regeneration without suppression, manifest in-place overwrite on promotion, latent `sitting`-card staleness) are recorded in `deferred-work.md`.
