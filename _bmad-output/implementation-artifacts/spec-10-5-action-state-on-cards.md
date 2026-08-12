---
title: 'Story 10.5 — Action state on cards (지적 6)'
type: 'feature'
created: '2026-08-12'
status: 'in-review'
baseline_revision: 'd04442f05562a539e296c5fca3845189456d2fd7'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/8-20-live-validation/DECISION-RECORD.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-6-live-validation/README.md'
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** The narration says *"그는 그 자리에서 쓰러졌습니다"* and the card on screen is standing. In run `8a9a288b`, **23 of 66 cast slots** did not draw the requested state, and the cause splits in two. **(A) 14 slots** — `STOCK-d-class` and `SCP-049-2` own **zero** `sitting` cards, so `_resolve_card_path` fell back to standing silently (`pose_fallback=True`); this is missing assets, not a missing technique. **(B) 9 slots** — `pose_guide_key` conditions nothing: Story 8.20's Task 2 output (closed vocabulary, six guide rasters, `characters.pose_conditioning` column, backfill) is complete and has **no consumer at generation time**. 10.6 added one more measurement: of seven renders that asked for `"lying supine on table"`, **7/7 came back standing or seated and 0 supine**.

**Approach:** (A) is solved with the script that already exists (`seed_stock_cast.py --pose sitting`) — but a front card is rendered into the validation directory and judged by eye **before** anything is written live. (B) settles *which pipeline* before comparing techniques: reuse 10.6's exact key, hint and seeds, and add one leg that isolates the IPAdapter anchor and one leg that conditions structure with the SDXL ControlNet Union already installed on this host. Only the winning leg is wired into production, default **off**.

## Boundaries & Constraints

**Always:**
- The closing condition is **frame evidence** — a card where the requested state is actually drawn, judged by eye — not wired code and not a passing test.
- Pre-registration (legs, seeds, judging criteria, decision table) is committed to `10-5-live-validation/README.md` **before any render exists**. No post-hoc edits; anything the rule misses is recorded, not patched into the rule (10.6 missed figure-count exactly this way).
- Every pixel number carries its value, its sample-band coordinates, a control, and a one-command recompute script. Alpha threshold is `>8`; treat **254** as saturation — an `alpha == 255` validator would reject every card this chain produces (8.20 §3.4).
- Pre-verification renders go **only** under `_bmad-output/implementation-artifacts/10-5-live-validation/`. Writes to live `characters.*` columns or `character_cards` rows happen only **after** the corresponding frame has been judged.
- New paths enter **default off** and degrade to the existing path in a recorded way.
- ComfyUI is already up — do not stop it (cold load is ~500 s) and never `pkill -f`. Before rendering, read `/queue` and check `class_type` for another session's workflow: HTTP 200 is not a free GPU. One character render is ~306 s and the GPU is shared with the 10-4b session.

**Block If:**
- The ControlNet leg OOMs or peak VRAM exceeds the 15.92 GB usable ceiling → record the measurements (peak VRAM, failing node, renders attempted/succeeded) and **HALT `blocked`**. 8.20 recommendation 3 (ship `edit_only` only, or move pose generation to another host) is explicitly **Jay's scope decision, not a dev decision**. Do not decide relocation unattended.
- Any result that matches no row of the pre-registered decision table → record the frames and HALT `blocked`. Do not invent a third hypothesis unattended.
- Seeding a `sitting` set for `SCP-049-2` is forbidden in this story (see **Never**); closing those 3 slots requires Jay's gate first.

**Never:**
- Do not extend the `pose_hint` vocabulary. The state set stays minimal (collapsed / seated).
- Do not add negative-prompt clauses (backfired three times). Never put `"SCP Foundation"` in a card prompt (mask attractor).
- Do not fix framing with prompt words — framing is alpha-bbox arithmetic.
- **Do not seed `SCP-049-2 --pose sitting` live.** Its standing set is still the masked one 10.6 flagged and its `visual_descriptor` is still the inherited plague-doctor text. `generate_cards_from_descriptor` **overwrites** that column, which executes unattended the asset replacement 10.6 deferred to Jay's gate; and a maskless sitting set beside a masked standing set turns the hazard `deferred-work.md` already records ("one video can show the same extra masked when sitting and bare-faced when standing") from latent into live.
- Do not build a new registry for silent degradation. Story 13.1 (`ready-for-dev`, unimplemented) owns this data as `run_warnings` / `cast_card_fallback` and explicitly forbids a competing channel.
- Do not touch `prompts/scenario/visual_breakdown.md`, `pipeline/nodes/video.py`, or `pipeline/nodes/image.py` (the 10-4b session holds them). Edit **only the 10-5 entries** in `epics.md` / `sprint-status.yaml`.
- Do not revert 10.6's just-landed `negative_suffix=self._maskless_negative_suffix(card_key, visual_desc)` in `generate_special_pose_card`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Sitting card exists | `pose="sitting"`, approved `character_cards(STOCK-d-class,'sitting','front')` row | `_resolve_card_path` returns that path, `pose_fallback=False` | none |
| Sitting card absent (today) | `pose="sitting"`, no row | standing path + `pose_fallback=True` (unchanged) | existing `logger.warning` kept |
| Guide requested, feature off | `pose_guide_key="humanoid_lying_supine"`, setting off | identical to today; guide ignored, zero behaviour change | none |
| Guide requested, feature on | above + setting on + guide approved | generation runs on the ControlNet workflow | guide unresolvable (`resolve_pose_guide` → `None`) → warn, degrade to existing workflow |
| No guide, feature on | `pose_guide_key` absent | existing workflow, unchanged | none |

</intent-contract>

## Code Map

- `src/yt_flow/services/character_service.py:946-1015` — `generate_special_pose_card(card_key, pose_hint)`. Requires `character.angle_front_path` as anchor (`:953`); the hint reaches the model as **text only** (`:969-977`); calls `provider.generate(..., ipadapter_weight=_ANGLE_IPADAPTER_WEIGHTS["front"]=0.2, negative_suffix=_maskless_negative_suffix(...))` (`:986-995`, the latter is 10.6's edit — preserve it); then `add_asset` → `approve_asset` → `save_card` in **one pass** (`:996-1007`). Zero references to `pose_conditioning` / `pose_guide_key`.
- `src/yt_flow/services/character_service.py:1408-1431` — `_resolve_card_path`. Non-standing goes through `get_card` (which *does* filter `status == "approved"`); on a miss it logs (`:1424`) and reads `Character.angle_{angle}_path`, which has **no status and no epoch filter**, returning `pose_fallback=True`. The `asset_fallback` / `fallback_reason` fields computed at `:1385-1391` have **no reader** in `src/` (only `video.py:2374` aggregates a count into Langfuse metadata).
- `src/yt_flow/services/character_image_provider.py:221-267` — `ComfyUICharacterProvider.generate(prompt, ref_image_path, *, width, height, ipadapter_weight, negative_suffix)`. `_load_workflow` (`:269`, from `settings.character_comfyui_workflow_path`); `_inject_reference_image` (`:360-371`) writes **every** `LoadImage` node, so it would clobber a second image input; `_inject_ipadapter_weight` (`:352-358`); `_inject_seed` (`:342-350`). A failed i2i silently re-renders as t2i (`:256-262`).
- `data/workflows/comfyui_character_multi_angle_api.json` — 13 nodes: `6` positive / `7` negative / `5` EmptyLatent / `20` LoadImage (ref) / `23` IPAdapterAdvanced / `3` KSampler / `12` InspyrenetRembg. **No structural-conditioning node of any kind.**
- `data/workflows/comfyui_shot_recompose_api.json:30,34,32` — the pattern to copy: `ControlNetLoader{control_net_name:"controlnet-union-sdxl-1.0-promax.safetensors"}` → `SetUnionControlNetType{type:...}` → `ControlNetApplyAdvanced{positive,negative,control_net,image,strength,start_percent,end_percent}`. The model is installed on this host (2.5 GB, `~/workspaces/ComfyUI/models/controlnet/`).
- `scripts/seed_stock_cast.py:91,184-228,278-291` — `VALID_POSES=("standing","sitting")`. `--key X --pose sitting` **already works end to end today**: `_POSE_DESCRIPTIONS["sitting"]="sitting on a plain simple chair, seated pose"` (`character_service.py:106`) → 4 angles → `assets/characters/<key>/epoch_N/sitting_<angle>.png` + approved manifest entries + 4 `save_card` rows. `--stage` rejects non-standing (`:123-132`). The front is t2i unless `--anchor` is passed.
- `src/yt_flow/services/run_service.py:504-554` — `_ensure_special_pose_cards` collects only `(card_key, pose_hint)` pairs (`:521-528`); `pose_guide_key` is discarded here. Cap is `settings.special_pose_max_per_run = 3` (`config.py:188`).
- `src/yt_flow/domain/pose.py:28,72-116` — `DEFAULT_POSE_CONDITIONING="edit_only"`, the six `POSE_GUIDE_KEYS`, `canonical_guide_key`, compatibility table. `asset_service.resolve_pose_guide:166` has **zero callers**.
- `assets/pose_guides/humanoid_lying_supine.png` — 832×1216 RGB, approved in the manifest as `coco18/humanoid/openpose`. Usable as a ControlNet openpose input with no preprocessor.
- `_bmad-output/implementation-artifacts/10-6-live-validation/render_legs.py` + `README.md` — the harness to clone: same key (`STOCK-d-class`), same hint (`"lying supine on table"`), same seeds (1061/1062/1063), `random.seed(s)` pinned immediately before `provider.generate()`. Its three ②-B frames are this story's **control leg** (all standing or seated, 0 supine).
- `_bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md:34,89,140` — owner of `run_warnings` / `cast_card_fallback`. Status `ready-for-dev`, unimplemented.

## Tasks & Acceptance

**Execution:**

- [x] `_bmad-output/implementation-artifacts/10-5-live-validation/README.md` — write the pre-registration **before any render**: the three legs for (B), the seed triple, the per-render judging criterion, the decision table, the control's provenance, and (A)'s front-card judging criterion. Record the working-tree commit and the timestamp — the rule must be fixed before pixels exist.
- [x] `data/workflows/comfyui_character_pose_guide_api.json` — copy `comfyui_character_multi_angle_api.json` and insert `ControlNetLoader` + `SetUnionControlNetType{type:"openpose"}` + `ControlNetApplyAdvanced` between nodes `6`/`7` and the KSampler, plus a guide `LoadImage` carrying `_meta.title = "ytflow:guide_image"` (the convention `comfyui_qwen_pose_edit_api.json` already uses). A separate file rather than dynamic node insertion: it is shorter, and with the feature off the existing graph does not change by one byte.
- [x] `src/yt_flow/services/character_image_provider.py` — add `pose_guide_path: str | None = None` to `generate()`. When present, load the pose-guide workflow, upload the guide, and inject it into the `ytflow:guide_image` node only. **Narrow `_inject_reference_image` so it skips that titled node** — today it writes every `LoadImage` and would overwrite the guide with the reference. No guide → today's path exactly.
- [x] `_bmad-output/implementation-artifacts/10-5-live-validation/render_legs.py` — clone `10-6-live-validation/render_legs.py`; render the two new legs at seeds 1061/1062/1063. Before rendering, read `/queue` and print the `class_type` set of running/pending jobs, waiting while another session's workflow holds the GPU. Append per-render wall time and `/system_stats` peak VRAM to `measurements.jsonl`.
- [x] Live run (B) — 2 new legs × 3 seeds. Judge each PNG by eye against the pre-registered criterion and write the table into the README. **If the ControlNet leg OOMs, go straight to the Block If procedure.**
- [x] `_bmad-output/implementation-artifacts/10-5-live-validation/probe_sitting.py` + live run (A) — render **one** `STOCK-d-class` sitting front into the validation directory (no live write), using `_POSE_DESCRIPTIONS["sitting"]` and `STOCK_NEGATIVE` verbatim. Proceed only if it passes the judging criterion.
- [x] ~~Run `uv run python scripts/seed_stock_cast.py --key STOCK-d-class --pose sitting --anchor assets/characters/STOCK-d-class/epoch_2/front_candidate_1.png`~~ — **deliberately NOT run.** The pre-registered probe failed (the sitting front came back standing), and the README's fail branch says nothing is seeded. Closed **0** of the 14 (A) slots, not 11. Afterwards assert the 4 `character_cards` rows and the manifest entries with read-only queries (`yt_flow.db` is gitignored, so `git status` proves nothing).
- [x] Wire the winner, per the decision table — if ControlNet wins: add `pose_guide_conditioning_enabled: bool = False` to `config.py`; extend `run_service._ensure_special_pose_cards` to collect `(card_key, pose_hint, pose_guide_key)`; extend `generate_special_pose_card(card_key, pose_hint, pose_guide_key=None)` to pass a guide only when the setting is on **and** `asset_service.resolve_pose_guide` succeeds (otherwise warn and take the existing path). If the anchor leg wins instead: introduce one pose-card-specific IPAdapter weight constant and nothing else. If neither wins: no code change.
- [x] `tests/services/test_character_service_generation.py` + `tests/services/test_character_image_provider.py` — cover only what was wired: with the feature off the workflow path and `generate` kwargs are identical to today; an unresolvable guide degrades to the existing path; the guide is injected into the `ytflow:guide_image` node and does not overwrite the reference node. 10.6's `test_generate_special_pose_card_applies_stock_negative_to_maskless_keys` must still pass.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` — append two entries: ① `SCP-049-2`'s sitting set must be seeded only **after** that key's standing/descriptor replacement (10.6's Jay gate); seeding first makes the masked-standing / maskless-sitting mismatch live (3 slots). ② The `pose_fallback` silent degradation is **13.1's**, with the reasoning for not opening a second channel here.
- [x] `_bmad-output/planning-artifacts/epics.md` + `_bmad-output/implementation-artifacts/sprint-status.yaml` — update the **10-5 entries only** with the outcome, stating how many slots were closed and how many were deliberately left, as numbers.

**Acceptance Criteria:**

- Given no render exists yet, when `10-5-live-validation/README.md` is committed, then it already contains the legs, seeds, judging criterion and decision table, and no later commit modifies those sections — provable with `git log --diff-filter=A` over that directory.
- Given 10.6's three ②-B frames are fixed as the control, when the two new legs render at the **same seeds**, then each leg's supine count is reported with its `n=3` denominator, and a winner is declared only if it beats the control's 0/3.
- Given judging is done by eye, when supporting pixel measurements are attached, then the alpha-bbox aspect ratio (`w/h`, threshold `>8`) is reported with its value, band definition and recompute script, and any disagreement between that number and the viewing verdict is **recorded as a finding** rather than promoting the metric to the verdict.
- Given the ControlNet leg runs, when it completes or fails, then peak VRAM and renders attempted/succeeded are recorded, and if it OOMs or exceeds 15.92 GB the story ends `blocked` with those measurements.
- Given the `STOCK-d-class` sitting front probe passed judging, when seeding runs, then `character_cards` holds four `(STOCK-d-class,'sitting',{front,side,back,three_quarter})` rows with `status='approved'` and the standing `angle_*_path` columns are unchanged.
- Given the new conditioning path is wired, when the setting is at its default (off), then the workflow file loaded by `generate_special_pose_card` and the arguments passed to `provider.generate` are byte-identical to before this story.
- Given neither new leg beats the control, when the story closes, then no code changed beyond (A), and (B) is escalated `blocked` with its measurements — a lost A/B is a result, not a reason to ship.

## Spec Change Log

- **2026-08-12 — (A)'s premise was falsified by its own probe; the task list was not rewritten to match.** The Intent calls (A) "missing assets, not a missing technique" and the tasks budgeted 11 of 14 slots for a script run needing no code. The pre-registered probe rendered the exact front angle that run would have produced and it came back **standing, no chair** (`10-5-live-validation/probeA_sitting_front_seed1071.png`), with the pose clause verified present in the compiled prompt. So (A) and (B) are one defect with one cause, and (A) closed 0 slots. **KEEP:** the ordering that caught this — probe into the validation directory and judge *before* the live write — is what stopped four approved-but-wrong `sitting` card rows from shipping; the same ordering must survive any re-derivation. **KEEP:** the pre-registered fail branch ("if the probe fails, nothing is seeded") was followed as written rather than reinterpreted after seeing the frame. The successor scope (author a seated openpose guide, thread a guide through the seeding path) is recorded in `deferred-work.md`, not silently folded in here.

## Review Triage Log

### 2026-08-12 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 2, medium 5, low 2)
- defer: 4: (high 1, medium 2, low 1)
- reject: 3: (medium 1, low 2)
- addressed_findings:
  - `[high]` `[patch]` The pose-guide read/upload sat outside the i2i `try`, so an unreadable guide or a failed upload killed the whole card while the identical failure on the identity reference merely falls back to t2i — contradicting the method's own "every rejection path degrades to the pre-10.5 call". Moved the upload ahead of the graph choice so a failure selects the unconditioned graph; covered by `test_an_unreadable_guide_costs_the_conditioning_not_the_card`.
  - `[high]` `[patch]` `SetUnionControlNetType` is pinned to `openpose`, but `guide_compatible` legitimately approves `scribble` silhouette guides for the creature profiles (`SCP-682` is `pose_conditioning='scribble'`) and `cast_decision.md` teaches `creature_*` keys — a silhouette raster would have been fed to the union model declared as a skeleton at strength 0.9. Non-openpose guides now fail closed with a reason; widening means measuring the pair, not editing the check.
  - `[medium]` `[patch]` The manifest recorded `pose_guide` whenever the resolver succeeded, including when the provider silently degraded to the default graph for a missing workflow file — the provenance field added to tell conditioned from unconditioned cards apart was the thing that could lie. The workflow file is now checked before the guide is accepted.
  - `[medium]` `[patch]` Dedup kept the guide key of the *first* shot spelling a hint, so the common shape (an earlier shot with no guide key, a later one with it) silently dropped conditioning. First **non-empty** guide wins now, with a regression test.
  - `[medium]` `[patch]` `git status --porcelain assets/` was used as proof that no live card was written, but `.gitignore:19-20` is `assets/*` with only `!assets/manifest.json` unignored, so it is blank either way — the same vacuousness the run correctly flagged for `yt_flow.db`. Replaced in `epics.md` and appended as a correction in the validation README with evidence that can actually fail (`find assets/characters -name 'sitting_*'` plus file dates).
  - `[medium]` `[patch]` The five `test_run_service_character_provisioning` tests only widened the fake's signature, so reverting the guide key to a dropped field left the suite green. Added two tests that assert the key reaches `generate_special_pose_card` and that dedup keeps it.
  - `[medium]` `[patch]` The provider tests exercised `_inject_guide_image` / `_remove_i2i_input` as static helpers, so deleting the entire `pose_guide_path` block from `generate()` was caught by nothing. Added an end-to-end `generate()` test through upload and the ControlNet graph.
  - `[low]` `[patch]` Reported cost was warm-only (`~6초/장`); L2's first render was 68.1 s against 28.8 s, i.e. ~44 s of one-time ControlNet load that lands on the first guided card of a run. Corrected in `epics.md` and the README, together with the caveat that the VRAM figure is a whole-device sample on an empty GPU.
  - `[low]` `[patch]` The `deferred-work.md` hand-off to Story 13.1 cited stale line anchors (`character_service.py:1424`, `1385-1391`); corrected to `:1487` and `:1447-1452`, and `os.environ.setdefault` in a test was replaced with `monkeypatch.setenv` so a leaked project root cannot make the assertion read another tree's workflow.

Deferred (not this story's to fix, appended to `deferred-work.md`): flipping the flag regenerates nothing because the special-pose cache key has no guide/setting component `[high]`; the two workflow graphs can drift with no test pinning them `[medium]`; manifest provenance stores the raw guide key with no canonical form or hash `[medium]`; `render_legs.py` can record a zero peak-VRAM as a measured pass and waits on the GPU without a deadline `[low]`. Rejected: the module-constant workflow path bypassing `character_comfyui_workflow_path` (one graph exists, it carries a `ponytail:` note, and `.env` pins the *scene* workflow, not the character one); the guide graph's `EmptyLatentImage` at 1024×1024 (`_inject_dimensions` always overwrites it); the "self-validating fixture" objection to the default-workflow test (folded into the graph-drift deferral instead).

## Design Notes

**Do not cite 8.20's VRAM rejection as-is.** Its 15.20–16.18 GB peaks were measured on **Qwen-Image-Edit-2511 Q4_K_M** (13.24 GB resident), and the OOM was not in diffusion — it was `InspyrenetRembg` asking for another 4.5 GB afterwards. This story's pipeline is **SDXL/AnimagineXL + IPAdapter**, a single-digit-GB resident model, and the ControlNet Union promax it would add is 2.5 GB, is **already installed on this host**, and is already driven by `comfyui_shot_recompose_api.json` with the same node triple. So 8.20 recommendation 2 ("a ControlNet on this host is unlikely to fit") is a conditional statement about Qwen, not a rejection of the SDXL path — which is why "measure before adopting" still stands, and why a bad measurement goes to Block If. (Misciting 8.20's numbers across pipelines has already happened three times in this repo.)

**Why the anchor leg runs too.** The hypothesis that a standing frontal IPAdapter anchor locks the structure is weak on its face — the weight is only 0.2. But that leg adds **zero new models**, costs the same as the ControlNet leg, and satisfies the epic's rule against asserting a cause without a control. The isolation method matters: passing `ref_image_path=None` makes the provider take its t2i path, which changes the **graph topology** and breaks pairing (10.6 hit exactly this confound in its ① pair). So the reference stays and only `ipadapter_weight` moves to `0.0` — one variable.

**Pre-registration (draft; finalized in the README before rendering):**

| Leg | ipadapter_weight | Workflow | Guide |
|---|---|---|---|
| L0 control | 0.2 | multi_angle | none — **reuses 10.6's three ②-B frames** (zero new renders) |
| L1 anchor isolation | **0.0** | multi_angle | none |
| L2 structural conditioning | 0.2 | pose_guide | `humanoid_lying_supine.png`, strength 0.9 |

Judgment, per render, from viewing the PNG: **supine = the torso's long axis is horizontal on screen and the head/foot height difference is under one third of body length.** Decision table — L2 ≥2/3 supine while L0 is 0/3 → **adopt structural conditioning**; L1 ≥2/3 and L2 ≤1/3 → **the anchor was the cause**, adjust the weight only; both ≤1/3 → **8.20's fork** → HALT `blocked`; both ≥2/3 → record the frames and HALT `blocked` (no third hypothesis unattended). The supporting metric is the alpha-bbox `w/h` ratio (standing ≈0.5, supine >1.0) and it has **no authority over the verdict**.

**Why the silent fallback is not fixed here.** A silent demotion does conflict with the no-silent-degradation rule, so it is a real defect. But 13.1 already owns this exact data (`PipelineState.run_warnings`, code `cast_card_fallback`) and explicitly forbids a competing registry — and `_resolve_card_path` **already computes** `asset_fallback` / `fallback_reason`. What is missing is not a producer but a consumer. Opening a second channel here would make 13.1's first task deleting it. So the judgment is "yes, it is a defect; its owner is 13.1", recorded with evidence and nothing more.

**Why (A) closes 11 of 14 and not 14.** `SCP-049-2` still carries the inherited plague-doctor `visual_descriptor` and a masked standing set. Running `--pose sitting` on it would have `generate_cards_from_descriptor` overwrite that column with the authored maskless text — executing unattended the asset replacement 10.6 deferred to Jay's gate — while simultaneously turning the mismatch `deferred-work.md` records as "latent" into a live one. That trades 3 slots for making 지적 15 worse.

## Verification

**Commands:**
- `uv run ruff check src/ scripts/ tests/` — expected: clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/services/test_character_service_generation.py tests/services/test_character_image_provider.py` — expected: 0 failures, including 10.6's negative-suffix test.
- `PYTHONPATH=$PWD/src uv run pytest tests/` — expected: 0 failures (baseline count recorded at run time).
- `uv run python _bmad-output/implementation-artifacts/10-5-live-validation/render_legs.py` — expected: 6 PNGs (2 legs × 3 seeds) plus `measurements.jsonl`; each PNG asserts `alpha=True`.
- `curl -s http://127.0.0.1:8188/queue` — expected: before rendering, no other session's workflow among the running/pending `class_type`s.

**Manual checks:**
- Open each PNG under `10-5-live-validation/` and judge supine against the pre-registered criterion, writing a one-line reason per render into the README — only eye judgment is closing evidence.
- After seeding, assert the four `character_cards` rows and the unchanged `characters.angle_*_path` values with read-only queries.

## Auto Run Result

Status: **done** — partial closure, and the partition is the point: of the 23 defective cast slots, **(B)'s 9 got a measured technique and a wired (default-off) path; (A)'s 14 closed 0** because its premise was falsified by its own probe.

### What was implemented

Structural conditioning for special-pose cards. `pose_guide_key` — produced by `cast_decision`, validated by the parser, backed by six approved guide rasters and a backfilled `characters.pose_conditioning` column since Story 8.20 — had **no consumer at generation time**; the hint reached the model as text only. It now routes to a ControlNet Union (openpose) graph behind `pose_guide_conditioning_enabled` (default `False`), failing closed to the exact pre-10.5 call on every rejection: setting off, unresolvable guide, non-openpose control type, missing guide workflow, or an unreadable/unuploadable guide file.

The evidence is frames, not tests. Pre-registration was committed alone at `aa7289e`, ahead of every pixel. At a shared seed triple with everything else held at 10.6's values: **L2 (guide) 3/3 supine, L1 (IPAdapter anchor at 0.0) 0/3, L0 control (10.6's reused ②-B frames) 0/3** → the pre-registered row "adopt structural conditioning". I viewed the PNGs independently and agree with every per-render judgment. **VRAM: L2 peak 11.16 GiB against a 15.92 GiB ceiling, zero OOM** — 8.20's rejection was measured on a 13.24 GB resident Qwen model and is not a prediction for this SDXL path, which is why it was measured rather than assumed.

(A) was supposed to be the cheap half: `seed_stock_cast.py --pose sitting` needs no code. The pre-registered probe rendered the exact front angle that command would write and it came back **standing, no chair**, with the pose clause verified present in the compiled prompt. Nothing was seeded, per the pre-registered fail branch. Seeding would have produced four *approved* `sitting` rows drawing a standing figure — strictly worse than today's silent fallback, which at least sets `pose_fallback=True`.

### Files changed

- `src/yt_flow/config.py` — `pose_guide_conditioning_enabled: bool = False`, with the live counts and the reason for the default in the comment.
- `src/yt_flow/services/character_image_provider.py` — `pose_guide_path` on `generate()`; guide uploaded before the graph is chosen so a failure degrades instead of costing the card; `_inject_guide_image`; `_inject_reference_image` and `_drop_reference_only_nodes` narrowed to skip the `ytflow:guide_image` node.
- `src/yt_flow/services/character_service.py` — `generate_special_pose_card(..., pose_guide_key=None)` resolves the guide, refuses non-openpose control types and a missing guide workflow with a logged reason, and records `pose_guide` provenance only when the guide was actually applied.
- `src/yt_flow/services/run_service.py` — `_ensure_special_pose_cards` carries the guide key instead of discarding it; dedup keeps the first **non-empty** guide.
- `data/workflows/comfyui_character_pose_guide_api.json` — new; the default graph plus `ControlNetLoader`/`SetUnionControlNetType`/`ControlNetApplyAdvanced` and a titled guide loader. A separate file so the default graph is untouched with the feature off.
- `tests/services/test_character_service_generation.py`, `tests/services/test_run_service_character_provisioning.py` — wiring, every rejection branch, guide-key forwarding, and an end-to-end `generate()` route.
- `_bmad-output/implementation-artifacts/10-5-live-validation/**` — pre-registration, harness, 7 frames, `measurements.jsonl`, results, and an appended corrections section.
- `_bmad-output/implementation-artifacts/deferred-work.md`, `_bmad-output/planning-artifacts/epics.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`, `epic-10-context.md` — hand-offs and outcome, 10-5 entries only.

### Review outcome

9 patches applied (2 high), 4 deferred (1 high), 3 rejected — details in the Review Triage Log. The two high-severity patches were both on the guarded path: an unreadable guide used to kill the card outright, and a `scribble` creature guide would have been fed to a graph pinned to `openpose`.

### Verification

- `uv run ruff check src/ scripts/ tests/` → clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/` → **2691 passed, 1 skipped** (2685 before the review patches; +6 new tests).
- Frames judged by eye by both the implementing pass and this one, independently.
- Live state unmutated, asserted with read-only queries (9 characters, 12 cards, 0 sitting rows, standing paths and descriptor intact) and a filesystem check — **not** with `git status --porcelain assets/`, which `.gitignore:19-20` makes vacuous.

### Residual risks

1. **The flip is a no-op on existing cards.** The special-pose cache key has no guide or setting component, so enabling the flag never regenerates `hint:*` cards that already exist — including the ones measured 7/7 wrong. Deferred with evidence; whoever flips the default owns it.
2. **Only the humanoid/openpose pair has ever been rendered.** Creature guides now fail closed rather than degrade quality, so the closed catalog is effectively half-unproven.
3. **Guided renders can return two figures** (seed 1063). Present with and without the guide, so not caused here, but it is the concrete reason the default stays off.
4. **The guide conclusion leans on reused frames.** L0 vs L2 is the single-variable comparison and L0 is 10.6's leg from ~26 h earlier; `measurements.jsonl` carries no prompt/reference hash to re-verify that premise from the artifacts alone.
5. **(A)'s deferral rests on n=1**, rendered with the standing card as IPAdapter anchor. Enough to stop a live write, not enough to prove a sitting card is unobtainable — the hand-off is worded as new scope, not as impossibility.
