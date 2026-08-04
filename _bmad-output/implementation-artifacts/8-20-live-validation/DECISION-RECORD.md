# Story 8.20 Task 1 — Adoption Decision Record

**Date:** 2026-08-04
**Host:** AMD Radeon RX 9060 XT, 16 GB (15.92 GB usable per PyTorch), ROCm
**ComfyUI:** core `0.12.3`, torch `2.11.0.dev20260206+rocm7.1`, python 3.12.3
**Verdict:** ⛔ **NO ADOPTION.** The candidate route runs but fails two hard gates.
Story 8.20 cannot be completed on it. Tasks 3–7 must not be built against it.

---

## 1. Outcome summary

| Gate | Requirement | Measured | Verdict |
|------|-------------|----------|---------|
| Runs locally (AC1) | must run on the 16 GB host | runs, but 2/5 attempts OOM | ❌ |
| Peak VRAM (AC1) | must fit 15.92 GB usable | **15.20 – 16.18 GB** | ❌ |
| Structural conditioning (AC6) | guide must control geometry | guide is injected as **content** | ❌ |
| Identity preservation (AC7) | reference is the identity source | mask + non-human anatomy preserved | ✅ |
| Transparent sprite (AC2) | RGBA, not flat RGB | true alpha, 0-background | ✅ |
| Card geometry (AC10) | `832x1216` | ✅ humanoid / ❌ non-humanoid (`1664x928`) | ⚠️ |
| Run budget (AC14) | full run ≤ 2 h | 97–1116 s **per card** | ❌ |

Two independent blockers. Either alone is disqualifying.

---

## 2. Rejected: ComfyUI_VNCCS

Pinned and inspected at rev `1bb732eb89e2738733567c3cde053f0b170c6d7e` (2026-07-26), **MIT**.

- **No extractable API graph.** All 5 shipped workflows are 1–5 node shells wrapping
  monolithic `VNCCS_ControlCenter` / `VNCCS_PoseStudio` / `VNCCS_CharacterGenerator`
  nodes. Graph construction lives in ~28.9k LOC of Python calling
  `nodes.common_ksampler` directly (`nodes/character_creator_v2.py:635`). There is no
  one-pose path to extract, so AC2's "extract only the one-pose path" is impossible.
- **Forbidden runtime dependencies.** `requirements.txt` pins
  `llama-cpp-python>=0.3.16`; models auto-download via `huggingface_hub` at node
  runtime. AC2 forbids both.
- **Qwen is a captioner there, not a generator** (`nodes/qwen_vl.py` is a
  Qwen2.5-VL chat handler). Its generation path is Illustrious/Anima SDXL.
- ✅ **One useful confirmation:** grep for
  `faceid|insightface|instantid|pulid|antelopev2|buffalo_l` returns **0 hits**, so
  AC7's "no real-face identity embedding" premise holds for this codebase.
- ⛔ **Its poseset is unusable as a guide source.** `presets/poses/vnccs_poseset.json`
  (12 COCO-18 poses, MIT) was rendered and inspected: **all 12 are standing
  character-sheet variants** (front/side/three-quarter A-poses). Using one would
  restate the pose the approved card already has — the exact thing AC5 forbids.
  Only its *limb-length ratios* were reused, for the authored guides in Task 2.

## 3. Evaluated and rejected: native Qwen-Image-Edit-2511, guide-as-second-reference

The workflow (`data/workflows/comfyui_qwen_pose_edit_api.json`) passes the approved
card as `image1` and the structural guide as `image2` of
`TextEncodeQwenImageEditPlus`, with no ControlNet.

### 3.1 Blocker A — the guide does not condition geometry, it injects content

`TextEncodeQwenImageEditPlus`'s `image2` is a **reference image**, not a control
signal. Qwen-Edit composes references into the scene, so the guide raster is drawn
as subject matter:

- `049_openpose_kneel.png` — the figure does kneel, but a **literal, anatomically
  clean articulated skeleton** is rendered lying in the frame. That is the COCO-18
  guide raster reproduced as content.
- `682_scribble_lunge.png` — the white silhouette guide became a **literal white
  bear-like animal** superimposed over the SCP-682 reptile, which it partly occludes.

The failure is identical for both the humanoid `coco18` and the non-humanoid
`silhouette` schema, so it is a property of the mechanism, not of the guide art.

**The pose effect is fully confounded.** `049_editonly.png` (no guide at all)
already produced the correct action — arm extended toward the viewer — from the text
instruction alone. So there is **no evidence the guide contributes any structure**,
and clear evidence it contaminates content. Per AC6 this route cannot be reported as
conditioned success.

⚠️ **This overturns the working assumption recorded before measurement.** The prior
note claimed "AC6 got simpler than the story assumed… ONE path, different guide
raster… which dissolves the Edit-2511 × ControlNet Union compatibility risk." That is
disproven. The ControlNet compatibility question is **not** dissolved — it is the only
remaining structural-conditioning candidate, and it is still unproven.

### 3.2 Blocker B — does not fit 16 GB

| case | status | wall | peak VRAM | output |
|------|--------|------|-----------|--------|
| `049_editonly` | OK (cold start) | 1115.8 s | 15.61 GB | 832×1216 RGBA |
| `049_openpose_reach` | **CUDA OOM** | 116.3 s | 15.78 GB | — |
| `049_openpose_kneel` | OK | 345.0 s | 15.60 GB | 832×1216 RGBA |
| `682_scribble_lunge` | OK | 96.8 s | 15.20 GB | **1664×928** RGBA |
| `682_editonly` | **CUDA OOM** | 176.6 s | 16.18 GB | — |

**2 of 5 runs (40%) died of CUDA OOM.** Raw data: `measurements.jsonl`.

The OOM is **not** in diffusion — it is at the `InspyrenetRembg` cutout node, after
sampling succeeds:

> `CUDA out of memory. Tried to allocate 4.50 GiB. GPU 0 has a total capacity of
> 15.92 GiB of which 2.09 GiB is free. Of the allocated memory 11.85 GiB is allocated
> by PyTorch` — node `cutout`, after `["decode","positive","positive_ref","sampler","guide"]`

The 13.24 GB Qwen GGUF stays resident (11.85 GiB allocated) and InSPyReNet then needs
4.50 GiB in the same 15.92 GiB. It succeeds only when ComfyUI happens to evict first,
which is why the failure is intermittent rather than constant. `InspyrenetRembg`
exposes only `torchscript_jit` — there is no device or resolution knob to shrink that
allocation, so AC2's "cutout stage inside the workflow" is not satisfiable at this
model size on this host.

**Q5 is excluded outright.** AC1 said measure Q4 first and Q5 "only if memory allows".
Q4_K_M already peaks at or above the usable ceiling; every Q5 variant is 1.1–2.1 GB
larger on disk.

### 3.3 Budget

Warm renders were 97–345 s; the cold start was 1115.8 s. At
`special_pose_max_per_run=3`, pose cards alone add roughly 5–17 min warm, plus up to
~18 min if the model must load — on top of the existing pipeline. AC14's two-hour
whole-run budget is not demonstrated, and no conservative calculation closes it while
a 40% retry rate is in play.

### 3.4 What did work (keep this for the next attempt)

- **Identity preservation is excellent and is the reason to keep Qwen-Edit-2511.**
  SCP-049's plague-doctor mask, hood, coat, gloves and boots all survived; SCP-682's
  reptile body survived. This is precisely where IPAdapter FaceID / InstantID / PuLID
  / InsightFace fail outright, and it confirms the story's core technique correction.
- **Text-only action instructions work.** The `edit_only` route hit the requested
  action without any guide.
- **The in-graph cutout produces a real sprite** when it does not OOM: corners at
  `alpha=0`, 67.4% fully transparent, median subject alpha 254.
- ⚠️ **Trap for AC10's validator:** InSPyReNet saturates the subject at **254, not
  255** (only 2.07% of the frame is exactly 255). A validator that requires
  `alpha == 255` for subject pixels would reject every card this workflow produces.

---

## 4. Environment pinned during the spike

All artifacts **Apache-2.0** (commercial-use compatible for this monetized channel).

| Kind | File / rev | Size | sha256 | License |
|------|-----------|------|--------|---------|
| custom node | `ComfyUI-GGUF` @ `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` | — | — | Apache-2.0 |
| custom node | `ComfyUI-Inspyrenet-Rembg` @ `87ac452ef1182e8f35f59b04010158d74dcefd06` | — | — | MIT |
| pip (ComfyUI venv) | `gguf` 0.19.0 | — | — | Apache-2.0 |
| diffusion | `qwen-image-edit-2511-Q4_K_M.gguf` | 13.24 GB | `8677bac90627adbbc11efab87b1870e701c4eb3689ee865a3de8ab81b705a723` | Apache-2.0 |
| text encoder | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | 9.38 GB | `cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4` | Apache-2.0 |
| VAE | `qwen_image_vae.safetensors` | 0.25 GB | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` | Apache-2.0 |
| LoRA | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | 0.85 GB | `22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f` | Apache-2.0 |

GGUF hash verified against the `unsloth/Qwen-Image-Edit-2511-GGUF` published LFS
sha256 — byte-exact. Sampler settings for every run above: 4 steps, cfg 1.0, euler /
simple, denoise 1.0, Lightning LoRA at strength 1.0, seed 880020.

---

## 5. Defect found (outside 8.20's scope, blocks AC6/AC14 independently)

**Non-humanoid base cards are unusable as references.** `SCP-682/standing_front` and
`SCP-1471/standing_front` are `status=approved` in `assets/manifest.json` but the
actual files are **1664×928 opaque RGB with no alpha channel**. The 6 humanoid cards
are correct 832×1216 RGBA.

Because this workflow takes its latent from `VAEEncode` of the reference, output
resolution equals reference resolution — which is exactly why
`682_scribble_lunge.png` came out 1664×928 and violated AC10. AC7 needs an approved
card as identity source and AC10 needs 832×1216, so **non-humanoid conditioning
cannot satisfy the card invariants until those base cards are regenerated.** That
regeneration is not in Task 1 or Task 2 and needs its own story.

---

## 6. Recommendation

1. **Do not build Tasks 3–7 on the guide-as-second-reference route.** It is not
   structural conditioning.
2. **The remaining candidate is a real control adapter**
   (InstantX Qwen-Image ControlNet Union, or a DWPose/depth ControlNet). Its
   Edit-2511 compatibility is still unproven — and note that Q4_K_M already peaks at
   the 15.92 GB ceiling *without* any ControlNet loaded, so a ControlNet on this host
   is unlikely to fit. Measure before adopting.
3. **If no structural route fits 16 GB**, the honest options are: ship `edit_only`
   only (text-driven action, no `pose_guide_key` routing, which measurably already
   produces correct actions and preserves identity), or move pose generation off this
   host. Both are scope decisions for Jay, not dev decisions.
4. **The cutout must leave the generation workflow** regardless of route — a 4.5 GiB
   allocation cannot share 15.92 GB with a resident 13 GB model.
5. Story 8.20 stays **incomplete** per AC6's own instruction rather than reporting
   reference-only editing as conditioned success.

## 7. Artifacts

- `measurements.jsonl` — raw per-run measurements
- `049_editonly.png` — reference-only baseline (identity + action OK, no guide)
- `049_openpose_kneel.png` — humanoid guide leaking as a literal skeleton
- `682_scribble_lunge.png` — creature guide leaking as a literal white animal
- `pose-guides-contact.png` — the 6 authored Task 2 guides
