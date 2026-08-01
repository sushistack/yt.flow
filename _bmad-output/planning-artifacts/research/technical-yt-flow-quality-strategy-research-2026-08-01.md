---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'research'
lastStep: 1
research_type: 'technical'
research_topic: 'yt.flow quality-first improvement strategy: LLM script generation, ComfyUI workflow structuring, source-set based character/background compositing, motion quality'
research_goals: 'Ground the pipeline in industry standards and published research; produce a quality-first improvement strategy covering (1) LLM script quality/structure, (2) ComfyUI workflow structuring and efficiency, (3) source-set based angle diversification / background variation / character-background compositing feasibility, (4) camera motion & shake quality'
user_name: 'Jay'
date: '2026-08-01'
web_research_enabled: true
source_verification: true
---

# Research Report: technical

**Date:** 2026-08-01
**Author:** Jay
**Research Type:** technical

---

## Research Overview

[Research overview and methodology will be appended here]

---

## Technical Research Scope Confirmation

**Research Topic:** yt.flow quality-first improvement strategy (LLM script, ComfyUI workflows, source-set compositing, motion quality)
**Research Goals:** Ground the pipeline in industry standards and published research; produce a quality-first improvement strategy.

**Technical Research Scope:**

- Architecture Analysis - current yt.flow pipeline state vs. reference architectures for AI video pipelines
- Implementation Approaches - LLM long-form script generation structures (outline/draft/critique), ComfyUI workflow modularization
- Technology Stack - character-consistency techniques (LoRA, IPAdapter, ControlNet, multi-view), relighting/compositing (IC-Light etc.), image-to-video motion
- Integration Patterns - when/how to invoke ComfyUI efficiently from LangGraph orchestration
- Performance Considerations - quality-first tradeoffs, generation cost vs. asset reuse (source-set strategy)

**Research Methodology:**

- Current web data with rigorous source verification
- Multi-source validation for critical technical claims
- Confidence level framework for uncertain information
- Codebase inspection to ground findings in actual pipeline state

**Scope Confirmed:** 2026-08-01 (scope taken verbatim from Jay's kickoff message; autonomous run)

---

## Area 1 — LLM Long-Form Script Generation (research findings)

### 1.1 Pipeline structures that beat single-shot generation

Literature is unanimous: beyond ~1–2k words, **hierarchical plan→draft→revise with explicit state/memory beats single-shot**, in both human preference studies and coherence metrics.

**Canonical lineage (2022–2024):**
- **Plan-and-Write** (Yao et al., AAAI 2019): outline-first improves plot coherence. Confidence: High.
- **Re3** ([arXiv:2210.06774](https://arxiv.org/abs/2210.06774)): Plan → Draft (per outline section) → Rewrite (rerank candidates) → Edit (contradiction fix via entity attribute tracking). Dramatically more coherent than rolling-window single-shot in human eval. High.
- **DOC** ([arXiv:2212.10077](https://arxiv.org/abs/2212.10077)): fine-grained hierarchical outline + adherence controller; beat Re3. Key lesson: **outline granularity is the main lever** — one outline bullet ≈ one drafting unit. High.
- **RecurrentGPT** ([arXiv:2305.13304](https://arxiv.org/abs/2305.13304)): per-step paragraph + short-term memory summary + long-term retrieved memory + next-step plan. High.
- **Weaver** ([arXiv:2401.17268](https://arxiv.org/abs/2401.17268)): style alignment is a separate problem from planning; generic LLMs write "AI-flavored" prose. Medium.

**2024–2026 SOTA:**
- **Agents' Room** (DeepMind, ICLR 2025, [arXiv:2410.02603](https://arxiv.org/abs/2410.02603)): specialized planning agents (character/plot/setting/conflict) + writing agents. Expert evaluators preferred it over single-agent **at equal total compute** — specialization itself adds quality. High.
- **DOME** ([arXiv:2412.13575](https://arxiv.org/html/2412.13575)): don't fully expand outline upfront; dynamically expand next node while drafting, temporal knowledge-graph memory. Reduces contradictions. High.
- **StoryWriter** ([arXiv:2506.16445](https://arxiv.org/abs/2506.16445)): outline/planning/writing agents; **event-based outlines** (who/what/consequence) beat prose outlines; dynamic history compression. Medium-High.
- **Learning to Reason for Long-Form Story Generation** ([arXiv:2503.22828](https://arxiv.org/abs/2503.22828)): explicit reasoning/plan step before each chapter measurably helps. High (finding).
- Survey: [EMNLP Findings 2025](https://aclanthology.org/2025.findings-emnlp.750.pdf); paper index: [Awesome-Story-Generation](https://github.com/yingpengma/Awesome-Story-Generation).

**Writer/critic/editor loops — revise works only with grounded feedback:**
- Intrinsic self-correction (free-form "improve this") often fails or degrades output; bottleneck is error *detection* ([Confidence vs. Critique](https://arxiv.org/pdf/2412.19513)). Models have a self-correction blind spot for their own output. High.
- What works: rubric/checklist critic; localized evidence-cited findings (quote the offending line); **separate critic model from writer**; bounded 1–2 iterations. High.
- Re3/DOC-style contradiction detection against tracked entity attributes is the most reliable editor design (feedback is verifiable). High.

### 1.2 LLM-as-judge quality gates

- **Reliability ceiling**: best zero-shot judge ≈ **73% agreement with humans** on creative pairwise ([LitBench](https://arxiv.org/pdf/2507.00769)); trained reward models ≈ 78%. Gates block regressions; they are not ground truth. High.
- **Failure modes** (all replicated): self-preference bias ([arXiv:2410.21819](https://arxiv.org/html/2410.21819v2)) — never judge with the writer's model family; verbosity bias — length-normalize and log length; position bias — swap order and aggregate; fluency/language bias when judging Korean with English-centric judges ([arXiv:2601.13649](https://arxiv.org/pdf/2601.13649)). High/Medium-High.
- **Pairwise vs rubric**: pairwise aligns better with humans and discriminates finer; rubric better for debugging and longitudinal monitoring. Hybrid (EQ-Bench pattern): analytic rubric with narrow criteria + pairwise Elo + deterministic "slop"/repetition/length metrics ([eqbench.com](https://eqbench.com/creative_writing.html), [eugeneyan.com](https://eugeneyan.com/writing/llm-evaluators/)). High.
- Median-of-N judge calls reduces variance (matches yt.flow Story 6.10 finding). High.

### 1.3 YouTube retention-driven script structure (practice consensus, Medium-High)

- **Hook (0–15s)**: cold-open on the most dramatic concrete moment/question; never preamble. For SCP horror: open mid-incident or on the most disturbing property, then rewind.
- **Retention bridge (15–45s)**: promissory open loop ("영상 끝에 왜 Keter로 분류됐는지 알게 된다").
- **Open loops**: plant 2–3; close each before opening the next or stack for horror tension; withhold one flagged detail until the final act.
- **Pattern interrupts every ~30–90s**: tone/POV shift, direct address, format change — SCP containment-log format is a natural built-in interrupt.
- **8–12 min narrated-story beat sheet**: cold-open hook → setup/normalcy → escalating incidents (loop close + new loop each) → midpoint reveal/reframe → darkest point → resolution ending on unresolved implication → soft CTA folded into outro.
- **Pipeline implication**: these are **checkable structural constraints** (question in first N sentences, open-loop ledger, max span without register change) — they belong in the outline schema and rubric gate, not vague prompt adjectives.

### 1.4 Model choice (creative + Korean)

- English/general creative (mid-2026): Claude Opus-class leads [EQ-Bench Creative Writing](https://eqbench.com/creative_writing.html); DeepSeek is strongest open-weight narrative option. Medium.
- **Korean**: Claude Sonnet-class scores highest on Korean 글쓰기/nuance sub-scores (LogicKor ~9.85/10 writing); DeepSeek noticeably weaker in Korean naturalness (Chinese-influenced calques, stiff register). Medium (under-benchmarked).
- **Implication for yt.flow (DeepSeek-based)**: keep DeepSeek for outline/planning; route **final Korean prose pass to a Claude-class model**; judge with a non-writer family; verify with small in-house Korean A/B. Medium.

### 1.5 Practical generation control

- **Chunked per-scene drafting is the standard** for 8–12 min scripts (~8–12k Korean chars); full-doc single-shot only competitive below ~1k words. High.
- **Chunk contract**: global premise + style sheet, this scene's event outline, compressed history summary, structured entity/state sheet, last 1–2 paragraphs verbatim for voice continuity. High.
- **Runaway generation** (matches Story 6.9 root cause): `max_tokens` is a fuse, not a length controller. Per-chunk word budgets in the prompt; max_tokens ≈ 2× expected chunk; mandatory `finish_reason` check with regenerate-on-length; tail n-gram repetition detector before accepting a chunk; structured output for outlines only — constrained decoding degrades prose ([arXiv:2604.06066](https://arxiv.org/pdf/2604.06066)). High.
- **Cross-scene consistency**: machine-readable state sheet (characters, entity properties, revealed/unrevealed facts, open loops planted/closed) updated per accepted chunk + contradiction-checker pass quoting offending lines ([SCORE](https://arxiv.org/pdf/2503.23512v1), [DOME](https://arxiv.org/html/2412.13575)). Simple YAML suffices at 10-min scale. High.

### 1.6 Key takeaways for script pipeline redesign

1. **4-stage scenario pipeline**: premise + retention plan (hook choice, open-loop ledger, beat sheet with per-beat word budgets) → event-based hierarchical outline → per-scene drafting with compressed history + state sheet → verification (contradiction + structural checks) + one bounded rubric revision pass.
2. **Retention structure lives in the outline schema**, enforced as deterministic/cheap-judge checks, not prose adjectives.
3. **Gate design**: pairwise vs production baseline with order-swap; evidence-cited rubric for debugging; median-of-N; judge ≠ writer family; deterministic slop/repetition/length metrics alongside.
4. **Grounded critique only**: quote offending lines vs state sheet/rubric; 1–2 iterations max.
5. **Model split**: planner (DeepSeek ok) / Korean stylist (Claude-class) / judge (third family).
6. **Chunk-level runaway control**: word budgets, 2× fuse, finish_reason check, repetition detector.

---

## Area 2 — ComfyUI Workflow Engineering & Serving (research findings)

### 2.1 Workflow engineering for automation

- **API-format JSON is the contract**: keep UI-format graph for editing, regenerate API-format export as the deployable artifact; never hand-edit both. Commit the **API-format** JSON to git (layout-free, diffs semantically). ([apatero production guide](https://apatero.com/blog/comfyui-workflow-to-production-api-deployment-guide-2025)) High.
- **Never hardcode node IDs**: resolve nodes at runtime by stable `_meta.title` (e.g. `PARAM_positive_prompt`), or add a small YAML manifest per workflow (`param name → node title → input key`) validated at load. High.
- **Branching lives in the orchestrator, not the graph**: production pattern is many small single-purpose workflows selected by application code — maps directly onto LangGraph routing. Resist the mega-graph. High.
- **Subgraphs** (official since Aug 2025, [blog.comfy.org](https://blog.comfy.org/p/subgraph-official-release)): authoring/maintenance win for shared fragments (e.g. "load SDXL + LoRA stack"); API JSON is flattened at execution, so not an API abstraction. High.
- **Environment pinning**: ComfyUI-Manager **snapshot JSON** = de-facto lockfile (custom nodes at exact commits + pinned pip packages); `cm-cli restore-snapshot` reproduces headlessly. Commit alongside workflows. Pin ComfyUI **core** version too — 2025/26 memory-management changes shipped regressions ([ComfyUI#12541](https://github.com/Comfy-Org/ComfyUI/issues/12541)). High.
- Run provenance: record `(workflow file hash, params, seed, torch/ROCm versions)` per render — git captures instructions, not results. High.

### 2.2 Serving patterns

- Core loop: `POST /prompt` → WS progress tracking → confirm via `GET /history` (poll fallback if WS drops). `GET /system_stats` as liveness+VRAM probe; exponential backoff; queue depth as backpressure metric. High. (Matches yt.flow Story 5.14/5.23 work.)
- **16GB VRAM management**: smart memory (default) evicts least-needed models only when needed — alternating SDXL/segmentation/video mostly works, eviction cost on switch. `POST /free {"unload_models":true,"free_memory":true}` only on OOM recovery or forced model-family swaps, never per-job. High.
- **Alternatives**: ComfyDeploy/ViewComfy/serverless — irrelevant for fixed single self-hosted GPU. ComfyScript turns workflows into diffable Python (JSON→Python transpiler) — consider if JSON templating gets painful. **Don't bypass ComfyUI with diffusers yet**: diffusers+torch.compile pays off only for frozen single-model batch pipelines (and 2–3× claims are NVIDIA-benchmarked); multi-model evolving pipelines are ComfyUI's strong case. Medium-High.

### 2.3 "Use only when needed" GPU efficiency

- **Content-addressed asset cache** in the orchestrator: key = hash(workflow-template-version + params + seed + model/LoRA ids + torch/ROCm versions); skip render on hit. Seeds reproducible on one fixed box but NOT across GPU/torch upgrades — stamp stack versions into keys. High.
- **Resolution laddering**: generate low-res candidates → pick winners (gate/judge) → upscale winners only; two-stage latent upscaling also reduces high-res hallucination ([arXiv:2511.10629](https://arxiv.org/html/2511.10629v2)). High.
- **Batch by model family**: group same-checkpoint jobs back-to-back to amortize load; warm resident server is the biggest latency saver (model load = 30–60s of a cold start). High.

### 2.4 Model families on 16GB ROCm (RX 9060 XT / RDNA4)

| Family | 16GB fit | 2026 position |
|---|---|---|
| SDXL (+Juggernaut/RealVis) | Comfortable fp16 | Workhorse; deepest LoRA/ControlNet/IPAdapter ecosystem; most mature on ROCm |
| FLUX.1-dev/schnell | Tight (fp8/GGUF) | Best prompt adherence of older gen; dev = non-commercial weights |
| Qwen-Image-Edit-2511 | GGUF Q4 ~14GB | **Notable for character consistency**: instruction-driven edits preserving identity, ≤3 reference images, Apache-2.0; ROCm quirks — validate |
| Illustrious XL / Pony V6 / NoobAI | Comfortable (SDXL-based) | Stylized/anime leaders; relevant if SCP art direction is illustrated |
| SD3.5 / Z-Image-Turbo | fp8 / fits | Leapfrogged / draft-ladder speed option |

ROCm notes: RX 9060 XT (gfx1200) officially supported since ROCm 7.0.x; expect ~70–85% of equivalent NVIDIA speed; rely on PyTorch SDPA (`--use-pytorch-cross-attention`), not xformers. High/Medium.

### 2.5 Node ecosystem for character+background

- **IPAdapter Plus (cubiq)**: the standard for style/character conditioning on SDXL; FaceID Plus v2 at weight ~0.7–0.8 is the consensus recipe; historically brittle across updates — snapshot-pin. High.
- **InstantID**: SDXL-only, strong identity lock, needs CFG ~4–5; face-centric. High. **PuLID**: FLUX-era identity; FLUX+PuLID tight on 16GB. Medium.
- **2025–26 shift**: practitioners moving from IPAdapter/ControlNet stacking to **instruction-edit models (Qwen-Image-Edit, FLUX Kontext)** for character consistency — one hero render, then edit-model derivations for poses/expressions. Medium.
- **IC-Light**: relighting works but **SD1.5-only**; V2 non-commercial, SDXL/FLUX wrapper support never landed — don't plan relighting architecture around it; usable as an SD1.5 relight pass with license check. High.
- **Upscalers**: Ultimate SD Upscale = automation default (tiled, low-VRAM); SUPIR best quality but ~12–15GB for 2× — hero frames only. High.

### 2.6 Key takeaways for pipeline restructuring

1. Each workflow = versioned parameterized function: API-JSON in git + title-based param manifest + Manager snapshot + core version pin + render provenance.
2. Routing in LangGraph; graphs small and single-purpose (char ref gen / derived pose / background / segmentation / upscale).
3. Schedule by model family on 16GB; `/free` only on OOM/family swap.
4. Efficiency ladder: content-addressed cache → low-res candidates → upscale winners only.
5. SDXL(-based, incl. Illustrious) remains the right base; **Qwen-Image-Edit-2511 GGUF as derivation engine** for identity-preserving pose/angle/expression variants (directly addresses derived-card gap).
6. Don't bypass ComfyUI; ComfyScript optional later.

---

## Area 3 — Source-Set Asset Strategy: Character Consistency, Angle Diversification, Compositing (research findings)

### 3.1 Character consistency — the 2025–26 standard shifted

- **Instruction-edit models first, LoRA second**: Flux.1 Kontext dev and **Qwen-Image-Edit 2509/2511** now re-render a canonical character in new poses/angles/scenes with no masks, no training; 2511 ships multi-image consistency, multi-angle re-shoot from a single reference, identity preservation ([docs.comfy.org](https://docs.comfy.org/tutorials/flux/flux-1-kontext-dev), [Next Diffusion 2511](https://www.nextdiffusion.ai/tutorials/qwen-image-edit-2511-multi-angle-ai-image-editing-comfyui)). High.
- **Two-stage bootstrap (emergent standard)**: (1) edit model derives 15–30 variations (angles/expressions/lighting/poses) from one canonical hero image → curated source sheet ([Weird Wonderful AI](https://weirdwonderfulai.art/comfyui/qwen-image-edit-can-create-character-consistent-lora-dataset/)); (2) **train a character LoRA on the curated sheet** for cheap high-volume per-shot generation composing with style LoRAs + ControlNet. Mickmumpitz "Consistent Character Creator" v3.8 — the most-adopted public implementation — is now built around Qwen-Image-Edit-2511 ([RunComfy](https://www.runcomfy.com/comfyui-workflows/consistent-character-creator-3-8-in-comfyui-hyperrealistic-consistent-ai-characters)). High.
- **LoRA training specifics**: 10–30 images, sweet spot ~15–20; documented template = **18 images: 1 frontal, 5 body angles, 4 face angles, 4 expressions, 4 lighting**, 1024² ([Rishi Desai](https://www.rishidesai.org/posts/character-lora/)). Structured captions; **don't caption constant features** (bind to trigger word); caption only what varies, one LLM one session. Rank 16–64, alpha=rank/2, ~1000 steps. SDXL/Illustrious LoRA trains locally on 16GB; Flux LoRA = one-off cloud job. High.
- **IPAdapter**: preserves style/vibe more than identity, drifts across many shots — use as style anchor, not identity mechanism. High.
- **PuLID/InstantID NOT applicable to stylized/non-human**: PuLID's face detector fails on non-realistic faces ([PuLID#123](https://github.com/ToTheBeginning/PuLID/issues/123)); both assume humanoid real faces. For SCP entities/illustrated humans: skip face-ID adapters; LoRA + edit-model derivation is the identity mechanism. High.
- **Pose control**: character LoRA + ControlNet OpenPose (humanoids) / depth-lineart-scribble from rough pose sketch (creatures). High.

### 3.2 Angle diversification — three routes

| Route | 16GB maturity | Verdict |
|---|---|---|
| A. Edit-model angle re-shoot (Qwen-Edit multi-angle; 96 documented camera perspectives) | High (GGUF Q4 ~14GB) | **Winner for 2D stylized** |
| B. Multi-view diffusion (MV-Adapter ICCV'25, CharacterGen SIGGRAPH'24) | Medium, research-grade | Canonical turnarounds only |
| C. 3D-ify (Hunyuan3D 2.1 Apache-2.0, ~3–6GB) then render | Medium; loses illustration fidelity | Only if free camera moves needed later |

Strategy: **generate an angle sheet upfront and cherry-pick into the asset library** — derivation is a library-time concern with quality gating, not per-shot ephemeral generation. High.

### 3.3 Background variation from source plates

- **Day/night/mood restyle keeping location identity = instruction-edit task**: Qwen-Image-Edit relight workflow preserves structure without ControlNet scaffolding ([comfy.org relight workflow](https://comfy.org/workflows/image_qwen_image_edit_2509_relight-f6e9d07c02fd/)). High.
- Fallback: SDXL img2img + depth ControlNet, denoise 0.4–0.6. Mature. High.
- Deterministic relight without regeneration: [comfyui-relight](https://github.com/EnragedAntelope/comfyui-relight) (positionable lights, normal-map aware). Medium.
- Architecture: canonical asset = **plate + depth map + prompt metadata**; mood variants = cache entries keyed by (plate, mood, time-of-day) — matches existing LocationPlate design.

### 3.4 Character–background compositing (feasibility: YES, with a defined recipe)

**Tier 1 (recommended production recipe)** — kills the "sticker" look:
1. Cutout (InSPyReNet — already have) → place/scale on plate.
2. **IC-Light v1 background-conditioned relight** (`iclight_sd15_fbc`: FG + BG → BG's illumination applied to subject) ([IC-Light](https://github.com/lllyasviel/IC-Light), [OpenArt workflow](https://openart.ai/workflows/risunobushi/relight-with-ic-light-and-background-as-lighting-source/UPKc0ak0YJibwbDff85i)). SD1.5, cheap. **v2/Flux is non-commercial — use v1 in monetized pipeline.**
3. **Masked low-denoise img2img fuse pass** (denoise ~0.18–0.3, character + dilated border): "smarter filter — keeps geometry, nudges lighting coherence"; two light passes beat one heavy. High.
4. **Classic VFX comp finish** (cheap, deterministic): edge feather 2–5px, **light wrap**, black/white point match between layers, **grain match last over unified frame** ([Digital Anarchy](https://digitalanarchy.com/light-wrap-fantastic/), [Rebelway](https://www.rebelway.net/compositing-vfx-nuke/)). Existing 7.2 grade over the *composited* frame gives free tone unification.

**Tier 2**: [libcom](https://github.com/bcmi/libcom) (pip-installable) — image/painterly harmonization, **shadow generation for inserted objects** (the gap in Tier 1), and **composite quality scoring → automated QA gate**. High (exists), Medium (stylized quality).

**Tier 3 (not recommended primary)**: AnyDoor/ObjectStitch regenerate the subject → identity drift; superseded by Qwen-Edit multi-image ("put character X into scene Y").

**Tier 0 alternative for hero shots**: Qwen-Edit-2511 multi-image (character ref + plate ref → one integrated image) — most integrated result, less deterministic placement, costlier. Medium-High.

### 3.5 Real-world reference pipelines

- **Neural Viz (The Monoverse)** — closest published analog: persistent asset universe, "assets persist across episodes rather than being spent upon publication"; canonical high-res stills generated once, all downstream animation starts from them. Medium (secondary writeups).
- **Mickmumpitz CCC v3.8** institutionalizes character sheet → dataset → LoRA → scene generation with dataset export. High.
- Studio-scale first-person postmortems are thin — this space is documented via creator-tool writeups. High.

### 3.6 Key takeaways: recommended source-set architecture

1. **Canonical layer (created once, human-gated)**: per character — hero image + 18-image structured sheet (Qwen-Edit derived, cherry-picked). Per location — hero plate + depth map. Only layer where taste/curation happens.
2. **Trained layer**: character LoRA per main character (structured captions, trigger-word binding). SDXL/Illustrious local; Flux cloud one-off. No PuLID/InstantID.
3. **Derived layer (on-demand, cached)**: per-shot poses via LoRA+ControlNet; new angles via Qwen-Edit multi-angle **derived into the library**, not per-shot; plate mood variants cached by (plate, mood).
4. **Compositing = paste + relight + fuse + comp finish** (+ libcom shadow gen and composite-QA scorer); Qwen-Edit in-scene generation for hero shots.
5. **Licensing**: IC-Light v2 non-commercial → v1 only; Hunyuan3D Apache-2.0; check Flux dev license.
6. Everything fits 16GB ROCm except full-precision Qwen-Edit (use GGUF) and local Flux LoRA training (cloud).

---

## Area 4 — Cinematic Motion for Still-Image Video (research findings)

### 4.1 Camera shake done right

- **Consensus**: white-noise jitter reads as "broken"; coherent (Perlin/fractal) noise reads as handheld — real motion has inertia ([Roystan](https://roystan.net/articles/camera-shake/)). High.
- **AE `wiggle()` reference model**: fractal noise `wiggle(freq, amp, octaves)`; subtle handheld ≈ **1 Hz, 10–25 px @1080p, 2–3 octaves**; wiggle **position + rotation + slight zoom together**; rotation small (≤1°). High pattern / Medium exact numbers.
- **Physiological grounding** (Gavant et al., IEEE): hand tremor ~8–12 Hz low amplitude; ~99% of postural movement power below 2 Hz → realistic handheld = dominant low-freq sway (0.3–2 Hz) + faint high-freq tremor layer. 2–3-octave fractal noise approximates this 1/f falloff naturally. High.
- **Game-dev refinement**: "trauma" scalar (0–1) decaying over time, amplitude = trauma², 3 independent noise channels (x, y, rot) — event-driven shake for stinger hits that ramps down organically. Rotational shake sells more per pixel than translational.
- Implementation: `x(t)=A·fbm(t·f)` etc., A ≈ 0.3–1% frame width (documentary drift) to 1–2% (nervous handheld); Python `noise`/`opensimplex`; precompute per-frame transforms.

### 4.2 2.5D parallax / depth-based Ken Burns

- Foundational: **3D Ken Burns** (Niklaus et al., SIGGRAPH Asia 2019, [arXiv:1909.05483](https://arxiv.org/abs/1909.05483)): depth → point cloud → camera path → disocclusion inpainting.
- Depth backbone standard: **Depth Anything V2** (fast, fine detail, ComfyUI-native, trivial on 16GB). High.
- **Off-the-shelf tool: [DepthFlow](https://github.com/BrokenSource/DepthFlow)** — open-source image+depth → 2.5D parallax GLSL renderer (8K@50fps on midrange GPU), DOF/vignette/lens-distortion built in, preset motions, Python-scriptable, **ComfyUI node pack exists**, OpenGL = ROCm-agnostic. "The Ken Burns 2.0 component". High.
- Artifact limit: keep single-image displacement ~**1–3% of frame width**; blur/dilate depth edges; DOF+motion hide imperfections. Medium (craft consensus).
- **yt.flow-specific advantage**: pipeline already has true layers (character cutout vs plate) — layered 2.5D (plate parallax via DepthFlow, character moved at different rate) sidesteps single-image disocclusion almost entirely. High.

### 4.3 Image-to-video models (the alternative)

- Landscape mid-2026: **Wan 2.2 A14B** (community workhorse, biggest LoRA ecosystem), **HunyuanVideo 1.5** (targets 14GB), **LTX-2** (Apache-2.0, cleanest commercial story), SVD/CogVideoX legacy. Medium-High.
- 16GB feasibility: Wan 2.2 GGUF Q5_K_M ~8.5GB model, peak 12–14GB @720p, 2–4 min/clip on NVIDIA; **ROCm officially supported** (AMD publishes Wan/LTX Radeon tutorials) but no RX 9060 XT benchmark — plausibly **5–15 min per 5s clip**. Verdict: **selective hero shots only, not 50–90 shots/episode**. Medium.
- **Camera control is the quality unlock**: Wan2.2-Fun Camera-Control model (explicit pan/zoom condition codes, [ComfyUI tutorial](https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-camera)); motion LoRAs (push-in dolly). High.
- Hosted for hero shots: Kling ~$0.10/s, Runway ~$0.15/s, Veo 3.1 Fast ~$0.15/s. 60-shot episode fully hosted ≈ $30–45 — viable for hero-only. Medium.

### 4.4 Cinematic language for documentary/horror narration (Medium-High)

- **Shot length**: narrated documentary baseline **6–10 s/shot**, tighten to 2–4 s in escalation, one deliberate 15 s+ hold before a scare beat.
- **Cut on narration beats, not a timer**: cuts at sentence/clause boundaries of VO (~135–170 wpm → beat every 4–8 s). TTS timing makes this automatable.
- **Motion-to-mood grammar**: slow push-in = dread/tension/revelation; pull-back = isolation/aftermath; lateral drift = calm exposition; locked static = clinical/oppressive surveillance; shake amplitude = panic; whip = breach/incident only.
- **Variety is itself the quality signal**: the "crude slideshow" tell is every shot getting the same motion. Rotate 4–6 archetypes keyed to the existing Epic 7 mood taxonomy; never two consecutive shots with same archetype+direction.

### 4.5 Implementation: ffmpeg vs a renderer

- **zoompan quantization is confirmed-famous**: rounds x/y/zoom per frame → stair-step jitter. Workaround: supersample 4–8× first. Even fixed, zoompan = zoom+pan only — no rotation, no parallax, no proper easing. **ffmpeg is the wrong layer for motion; keep it as assembler/encoder.** High.
- Recommended: motion rendering in **DepthFlow** (or Python per-frame float affine at supersampled res piped to ffmpeg); ffmpeg stays for concat/audio/subtitles/grade/encode; selective Wan i2v via existing ComfyUI for 1–3 hero shots/episode.

### 4.6 Key takeaways for motion overhaul (priority per effort)

1. Fractal-noise camera paths (x/y/rot/micro-zoom, two spectral bands, trauma scalar for stingers) — ~30 lines of Python, kills the "crude" look.
2. Beat-aligned cuts + mood-driven motion archetypes (reuse mood taxonomy).
3. DepthFlow parallax on background plates (layered composite advantage).
4. Selective Wan 2.2 i2v hero shots (Wan-Fun camera control).

---

## Area 5 — Current Pipeline State (codebase ground truth, 2026-08-01)

Full map from repo inspection; quality-relevant facts only.

### 5.1 Scenario
- Already a **multi-stage chain** (research → structure → writing → cast_decision → visual_breakdown → review → critic → tts_normalize), `scenario.py:311`, steps 4–5 concurrent per scene.
- **Single model everywhere**: `deepseek-v4-flash` for all chain steps AND the judge (`config.py:27,31`); no temperature set for chain steps.
- Critique loop bounded to **one retry** (scoped scene repair, full-rewrite fallback); pass-2 verdict recorded but never acted on.
- **Only one narrative template**: `structure.md` INCIDENT-FIRST 4-act forced on every SCP (Epic 10 backlog acknowledges).
- `camera_movement` **hardcoded `None`** (`scenario_chain.py:1079`) — the LLM's camera intent never reaches video.
- Eval judge scores **narration text only**; no axis for images/compositing/motion/final video. A/B promotion gate frozen (`YTFLOW_ALLOW_AB_GATE=1` required).
- Every taxonomy violation degrades to default with a warning; nothing fails the stage.

### 5.2 Image generation
- Backgrounds: per-shot sequential ComfyUI calls (155 for sample run); prompts injected into **hardcoded node IDs "6"/"7"**; **KSampler seed never injected — hardcoded 0 for every background**.
- Latent **1216×832 (AR 1.462)** → video pipeline center-crops ~18% of height and upscales from 1728-wide to 1920×1080.
- Base model AnimagineXL v3.1 + horror/darkness LoRAs.
- Character consistency = pre-generated RGBA card library (41 approved assets) + **IPAdapter self-referencing chain** (front card t2i → other angles reference it, weights 0.2–0.5) + text descriptor re-enrichment. No per-character LoRA.
- Cutout at card-gen time (InSPyReNet on studio bg); `_clean_alpha_noise` **snaps alpha to hard 0/255** — binary, non-antialiased edges.
- Card prompt explicitly requests "no cast shadow, no dramatic lighting" — flat studio light over any plate.

### 5.3 Asset library
- Character cards populated (5 SCPs + 3 STOCK); **location plates EMPTY (0 rows)** → every background regenerated every run (Story 8.17 documents this); look-dev anchors empty; relit sprites never produced.
- On-demand provisioning at scenario-gate approval (special-pose cap 3/run, derived-entity cap 2/run); failures degrade silently to background-only.
- Known defects already filed: 8.15 (STOCK faces inherit SCP-049 mask — descriptors have zero face terms), 8.16 (cards "float" — no ground-plane/depth awareness), 8.18 (cast diversity prompt-only), 8.20 (148/151 placements are effectively the same static sprite).

### 5.4 Video assembly & motion
- Compositing = pure ffmpeg `overlay`; vertical anchor **always dead-center** `(main_h-overlay_h)/2`; depth = fixed 3-value scale table; **harmonization tier default 0 = OFF** (tier 1 tint+ellipse shadow, tier 2 light wrap exist; tier 3 IC-Light gated on a flag absent from the workflow → never fires).
- Camera motion: `zoompan` Ken Burns; **direction = 10-entry round-robin by shot index, unrelated to content** (hint path exists but `camera_movement` is always None; "static" never fires). Supersampling to 8000px already present.
- "Shake" = deterministic fixed-amplitude sinusoids (`tremble` = breath + 3px@6rad/s x/y), single per-card phase offset 2.1·k — constants documented in-code as "eyeball-tuned; not derived from anything". Not random jitter, but spectrally wrong (single frequency, no 1/f structure) and identical curve per style.
- Transitions: every scene boundary = fade→black→fade, no variety (7.4's mood xfade map retired by 5.16); audio passes through cuts untouched.
- Kinetic subtitles (7.5) retired → static sentence cues; **word timings = uniform whitespace split unless WhisperX runs** (Qwen TTS gives no timestamps) → Story 8.11's beat-aligned shot cuts are actually driven by uniformly-apportioned timings in practice.
- Post-fx grade: per-mood eq + constant vignette + constant grain, applied pre-subtitle-burn.

### 5.5 Orchestration
- LangGraph 5 stages × human gates; gates are the only runtime quality control; **all degradation paths produce a silently lesser video** (cast-resolution failure → "background only", plate miss → regenerate, etc.).
- Gates are per-stage, not per-shot; no image-level accept/reject granularity.
- No workflow versioning/pinning discipline (no Manager snapshot, no core version pin, no render provenance records).

---

# Synthesis & Strategy

## Gap analysis — Jay's concerns vs. research vs. code

| # | Concern | Ground truth | Research verdict |
|---|---|---|---|
| 2 | LLM script quality poor; structure may need change | Chain shape is already near-SOTA (multi-stage, scoped repair). Real gaps: one forced 4-act template for every SCP; single model for writer AND judge (self-preference bias); retention structure lives in prose prompts, not schema; pass-2 critic verdict ignored; Korean surface quality limited by DeepSeek | **Structure doesn't need replacement — it needs 4 targeted upgrades** (template diversity, model split, retention schema, grounded gate) |
| 3 | ComfyUI structuring/efficiency | Node-ID hardcoding, background seed stuck at 0, no env pinning, 155 sequential regens/run because plate library is empty, AR mismatch wasting 18% of every image | Industry pattern = small single-purpose workflows + title-based param manifest + snapshot pinning + orchestrator-side cache. "필요한 시점에만" = plates + content-addressed cache + resolution ladder |
| 4 | Source-set based production | Card library is a proto-version of exactly this; location plates never seeded; IPAdapter self-referencing chain is the weak link | **Jay's intuition = the 2025–26 industry standard** (canonical → trained → derived 3-layer). Upgrade derivation to Qwen-Image-Edit-2511; compositing is feasible with a validated recipe |
| 5 | Crude look: pasted character, fake shake | Root causes located precisely: harmonization tier defaults to 0; vertical anchor always dead-center; binary alpha edges; cards prompted for flat studio light; camera direction = index round-robin; "shake" = single-frequency sinusoids | Every cause has a standard fix: relight+fuse+comp-finish recipe; depth-aware placement; fractal-noise camera paths; mood-driven motion archetypes |
| 6 | Not grounded in standards/papers | Motion constants marked "eyeball-tuned; not derived from anything"; no visual QA | This document grounds each subsystem in papers/industry practice (see Areas 1–4 citations) |
| 7 | Quality-first output | Judge scores narration text only; all failure paths silently degrade the video | Extend judging to the frame (libcom composite scorer, motion variety checks); convert silent degradations to surfaced warnings/gates |

## Strategy — four phases, ordered by impact per effort

Priority rationale: Jay's dominant pain is **visual crudeness**, and the script chain is structurally sound — so the frame comes first.

### Phase 1 — De-crude the frame (compositing + motion) — no new architecture

**Quick wins (config/one-liner tier):**
1. Inject a per-shot seed into the background KSampler (all 155 backgrounds currently share seed 0).
2. Fix background latent AR: 1216×832 → 16:9-native SDXL size (e.g. 1344×768); stop cropping 18% of every image.
3. Default `composite_harmonization_tier` ≥ 1 (tint + contact shadow + light wrap already exist, just off).
4. Soften card edges: stop snapping alpha to 0/255 in `_clean_alpha_noise`; keep anti-aliased edge + 2–5px feather.
5. Populate `camera_movement` from the scenario chain (field exists, hardcoded None) and route it into `_HINT_MAP`.
6. Run WhisperX unconditionally so shot cuts align to real speech, not uniform splits.

**Story-sized:**
7. **Story 8.16 implementation, per validated recipe**: Depth-Anything V2 on the plate → floor-line/scale-aware placement + occlusion mask (kills "floating"); IC-Light v1 `fbc` background-conditioned relight (v2 is non-commercial); masked low-denoise (~0.2–0.3) img2img fuse pass; light wrap + black/white-point match; grain last over unified frame; libcom shadow-generation + its composite-QA score as an automated gate.
8. **Motion module rewrite**: replace index round-robin + single-frequency sines with (a) mood→motion-archetype mapping (push-in=dread, pull-back=isolation, drift=exposition, locked=clinical, shake=panic — reuse Epic 7 mood taxonomy), (b) 2–3-octave fractal-noise camera paths (low-freq sway 0.5–2 Hz @0.3–1% frame width + faint 8–12 Hz tremor; trauma scalar for stingers), (c) no two consecutive shots with same archetype+direction, (d) shot pacing 6–10s baseline / 2–4s escalation / one long pre-scare hold.
9. **DepthFlow adoption** for background-plate parallax (ComfyUI nodes or Python lib; OpenGL = ROCm-safe); character layer moved at 60–80% of plate displacement. ffmpeg remains assembler/encoder only.

### Phase 2 — Complete the source-set economy

10. **Seed the location plate library (Story 8.17)** — largest single waste: every run regenerates every background. Canonical asset = plate + depth map + prompt metadata; mood/time variants cached by (plate, mood).
11. **Adopt Qwen-Image-Edit-2511 (GGUF Q4, ~14GB) as the derivation engine**: replaces the weak IPAdapter self-referencing chain for angle sheets (96 documented camera perspectives), derived entities (049-2 gap), pose variants (8.20), expression sets. Derive into the library with curation, not per-shot.
12. Per-character **LoRA for top recurring characters** (18-image structured sheet: 1 frontal/5 body/4 face/4 expressions/4 lighting; constant features uncaptioned → trigger word; SDXL/Illustrious trains locally). Skip PuLID/InstantID — wrong tool for stylized/non-human.
13. **Workflow ops hardening**: title-based param manifest (kill node-ID "6"/"7" coupling); ComfyUI-Manager snapshot + core version pin in git; render provenance (workflow hash, params, seed, torch/ROCm versions); content-addressed render cache; batch jobs by model family.
14. Fix STOCK face descriptors (8.15) + deterministic cast-diversity validator (8.18).

### Phase 3 — Script quality upgrades (structure stays, four changes)

15. **Retention schema in the outline**: hook type, open-loop ledger (planted/closed per scene), pattern-interrupt cadence, per-beat word budgets — enforced as deterministic checks, not prose adjectives. Event-based outline items (who/what/consequence).
16. **Template diversity (Epic 10)**: 3–5 narrative templates (incident-first, discovery-log, interview/testimony, containment-breach realtime, researcher-descent) selected per SCP by the research step.
17. **Model split**: DeepSeek stays planner/structural; **final Korean prose pass → Claude-class model** (leads Korean writing benchmarks; DeepSeek has documented Korean naturalness deficits); **judge → third family** (self-preference bias is replicated; current judge = writer = same model).
18. **Grounded gate**: contradiction checker quoting lines against the entity/state sheet; act on pass-2 verdict (currently recorded and ignored) — escalate to the human gate with the critic summary attached; keep median-of-N (6.10) and add deterministic slop/repetition/length metrics.

### Phase 4 — Hero shots + eval maturity

19. **Selective i2v**: Wan 2.2 GGUF (12–14GB peak, ROCm-supported) for 1–3 hero shots/episode with Wan2.2-Fun camera control; expect 5–15 min/clip on this card — never the per-shot default. Hosted (Kling/Veo Fast ~$0.10–0.15/s) as a fallback for money shots.
20. **Eval expansion**: add visual axes (libcom composite score, motion-variety/archetype-coverage checks, cut-alignment error) alongside narration axes; then unfreeze the A/B promotion gate (6-12) once the pipeline is stable enough to compare like-for-like.
21. Convert silent degradation paths (cast-resolution failure → background-only, plate miss, relight miss) into surfaced run warnings visible at gates.

## Anti-scope (deliberately NOT doing — ponytail)

- **No 3D-ification** of characters (Hunyuan3D/TripoSR): loses illustration fidelity; only worth it if free-camera moves become a requirement.
- **No per-shot novel-view generation**: angles are a library-time concern (derive → curate → reuse).
- **No PuLID/InstantID**: real-face embeddings fail on stylized/non-human entities.
- **No diffusers bypass of ComfyUI**: multi-model evolving pipeline is ComfyUI's strong case.
- **No AnyDoor-class generative insertion** as primary compositing: regenerates the subject → identity drift.
- **No mega-workflow**: branching stays in LangGraph; graphs stay small and single-purpose.

## Suggested story mapping

- Phase 1 quick wins → one hardening story (new); #7 = existing 8.16; #8–9 = new motion-overhaul story (supersedes eyeball-tuned constants); WhisperX = fold into 8.11 follow-up.
- Phase 2 → 8.17 (plates), new Qwen-Edit derivation story (supersedes/extends 8.13 mechanism, addresses 8.15/8.20), new workflow-ops story, 8.18.
- Phase 3 → Epic 10 (10.1 template diversity) + new "retention schema" story + new "model split" story + 6-x gate story.
- Phase 4 → new hero-shot story + 6-12 unfreeze + eval-axes story.
