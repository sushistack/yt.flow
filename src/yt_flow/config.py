from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YTFLOW_",
        env_file=".env",
        extra="ignore",
    )

    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str
    # B-3: when false, @observe/get_client no-op (see observability.py). Does NOT
    # disable Prompt Hub fetching. env YTFLOW_LANGFUSE_ENABLED.
    langfuse_enabled: bool = True

    # Single SQLite file shared by LangGraph checkpoints and future SQLModel tables. [AD-7]
    db_path: str = "yt_flow.db"

    # DeepSeek (OpenAI-compatible) — model names are config-pinned, never hardcoded in nodes.
    # ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling;
    # nodes guard for a missing key at call time and fail with a readable error.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    # Measured 2026-08-05 over 6 live run attempts (SCP-999, SCP-049): 8192 was the
    # shipped default while .env already carried 16384, and 16384 truncates
    # scenario/structure 4/4 (finish_reason=length). 32768 passes structure cleanly.
    # 65536 stops truncation everywhere, but the all-scenes scenario/writing call was
    # still outstanding after 29 minutes with zero artifacts — so the fix for writing
    # was batching it one scene per call (scenario_chain.writing_step), not more
    # budget. This value is sized for the largest single call that remains,
    # structure, with headroom over its measured 16384 failure / 32768 pass.
    deepseek_max_tokens: int = 32768
    # ROOT CAUSE of the 2026-08-05/06 truncation class (finish_reason=length,
    # content=="", the whole budget spent inside discarded reasoning_content).
    # Batching stages per scene treated the symptom — live run 4c85f66d had
    # writing already at one call PER SCENE and still burned all 32768 tokens on
    # 67k–77k characters of reasoning for a single scene, re-roll included.
    # Probed directly against api.deepseek.com (deepseek-v4-flash), measuring
    # completion_tokens_details.reasoning_tokens:
    #   baseline (no field)             -> 26
    #   "reasoning_effort": "low"       -> 16
    #   "thinking": {"type":"disabled"} -> 0
    # So reasoning depth is the real lever. Mapped to a request field in
    # scenario._REASONING_BODY: low/medium/high -> reasoning_effort,
    # "disabled" -> thinking (the only mechanism that reached 0), "default" ->
    # send neither field. Literal so an unknown value fails at config load.
    deepseek_reasoning: Literal["low", "medium", "high", "disabled", "default"] = "low"
    # A/B evaluation judge (Story 4.2). Same OpenAI-compatible endpoint; the model is
    # config-pinned so the judge can be swapped independently of the content generator.
    # Kept after the Story 12.2 split moved judging to Gemini: it is the zero-new-provider
    # fallback if Gemini-writes-and-judges self-preference bias makes results suspect.
    deepseek_judge_model: str = "deepseek-v4-flash"

    # Gemini (Story 12.2 model split). Owns every prose-producing/prose-judging call:
    # scenario writing + scene repair, the runtime review/critic judges, and the Epic 4
    # axis/pairwise judges. DeepSeek keeps research/structure/cast/visual/tts_normalize.
    # ponytail: same empty-key default as DeepSeek above so Settings() stays constructible
    # in tests/tooling; the call sites fail fast with a provider-specific error.
    gemini_api_key: str = ""
    # Google's OpenAI-compatibility endpoint. Callers append `/chat/completions`, exactly
    # like deepseek_base_url — so no new transport, just a second base URL + key.
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # Exact stable IDs only, never a `-latest`/preview alias: `latest` can be hot-swapped
    # under a running pipeline, which would silently change output quality and destroy
    # quality attribution between runs.
    # SCOPE, because the names undersell it: the *writing* pair below serves every
    # scenario-chain stage Gemini owns — writing, scene repair AND the runtime
    # review/critic judges — because they all share one injected seam
    # (scenario._call_gemini). The *judge* pair serves the Epic 4 A/B judge only
    # (eval_service). Deliberate: Story 12.2 Task 2 suggested putting runtime
    # review/critic on the judge budget, but the 2026-08-06 live probe measured
    # ~2-5k thinking tokens per Gemini call, and review/critic are the two stages
    # that already truncated live at 16k (run 370666ba) — capping them at 8192 would
    # buy nothing and re-introduce a known failure. Per-stage model plumbing is the
    # thing to add if a *different* runtime judge model is ever actually wanted.
    gemini_writing_model: str = "gemini-3.6-flash"
    gemini_judge_model: str = "gemini-3.6-flash"
    # Writing is batched one scene per call (scenario_chain.writing_step), so it needs
    # far less than deepseek_max_tokens' whole-outline budget. Independently pinned so
    # an A/B-judge budget change can't perturb generation.
    gemini_writing_max_tokens: int = 16384
    gemini_judge_max_tokens: int = 8192

    # ComfyUI image generation (Story 1.6). Reachability is checked lazily before
    # the first ComfyUI submission in image_node (Story 5.14), not app startup —
    # a fully-resumed retry never touches HTTP. Mock mode never instantiates the
    # HTTP client.
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: str = "data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json"
    comfyui_mock: bool = False

    # Sustained-load crash mitigation (Story 5.23): two independent runs crashed
    # ComfyUI (hipErrorIllegalAddress, ROCm RX 9060 XT) near shot ~40 under load.
    # A periodic re-check catches a crash before submit_and_fetch itself would;
    # the bounded wait-and-recheck window covers a manual restart-and-retry.
    comfyui_health_poll_every_n_shots: int = Field(20, ge=1)
    comfyui_crash_recovery_poll_sec: float = Field(15.0, gt=0)
    comfyui_crash_recovery_timeout_sec: float = Field(300.0, gt=0)

    # Read timeout for the /system_stats health probe. ComfyUI's server is
    # single-threaded on the GPU: while it executes a prompt it does not answer
    # /system_stats at all. Measured 2026-08-06 (run fdd69699): 28/28 prompts
    # succeeded at ~20s each, yet the old 5s probe timeout misread the
    # healthy-but-busy server as crashed and stalled the image stage after
    # 1/68 shots. So this must tolerate at least one full generation. Crash
    # detection does NOT depend on it — a dead server fails at connect
    # (5s, see comfyui_client.HEALTH_CONNECT_TIMEOUT), not at read.
    comfyui_health_read_timeout_sec: float = Field(120.0, gt=0)

    # Per-generation poll budget for submit_and_fetch*. Measured 2026-08-04 on
    # RX 9060 XT / ROCm: a cold character card (SDXL + LoRA + IPAdapter +
    # CLIPVision + InspyrenetRembg) completes at ~400s. The old hardcoded 180s
    # budget timed out mid-generation, the caller retried, and each retry
    # enqueued another prompt — queue 3 -> 6 pending with 0 completed history.
    comfyui_generation_timeout_sec: float = Field(900.0, gt=0)
    comfyui_poll_interval_sec: float = Field(1.0, gt=0)

    # Runtime artifact root; stage nodes write under workspace/{run_id}/. [AD-10]
    workspace_path: str = "./workspace"

    # Reusable asset library root (character cards, location plates, look-dev
    # anchors) — distinct from workspace_path so run cleanup can never touch
    # library assets (Story 8.6). [AD-10]
    assets_path: str = "./assets"
    # Current style-anchor generation; AssetService's manifest is the persisted
    # source of truth once it exists — this is only the bootstrap seed.
    style_epoch: int = 1

    # Qwen TTS via Alibaba DashScope (international). Model/voice are config-pinned,
    # never hardcoded in nodes. ponytail: api_key defaults to "" so Settings() stays
    # constructible in tests/tooling; tts_node guards for a missing key at call time.
    qwen_tts_api_key: str = ""
    qwen_tts_endpoint: str = "https://dashscope-intl.aliyuncs.com"
    qwen_tts_model: str = "qwen3-tts-flash"
    qwen_tts_voice: str = "Cherry"
    qwen_tts_clone_enabled: bool = False
    qwen_tts_clone_model: str = "qwen3-tts-vc-2026-01-22"
    qwen_tts_clone_voice_path: str = "data/voices/sutak.mp3"
    qwen_tts_clone_voice_id: str = ""
    qwen_tts_speed: float = Field(1.2, ge=0.5, le=2.0)
    qwen_tts_mock: bool = False

    # Forced alignment for subtitles + shot cuts (Story 1.8; always-on Story 11.4).
    # Strategy is config-driven; swap the aligner name without touching
    # subtitle_node. whisperx>=3.8.6 ships in pyproject.toml. Align-only (no ASR
    # pass), so no model/compute_type knobs — just the device.
    aligner: str = "whisperx"
    aligner_device: str = "cpu"

    # Image search provider (Story 1.11). DuckDuckGo is the default; no API key needed.
    image_search_provider: str = "duckduckgo"

    # Character image generation (Story 1.12). Provider-specific character image
    # generation for multi-angle character portraits.
    character_image_provider: str = "comfyui"  # "comfyui" or "qwen"
    character_comfyui_workflow_path: str = "data/workflows/comfyui_character_multi_angle_api.json"
    character_qwen_model: str = "qwen-image-max"
    character_qwen_api_key: str = ""
    character_image_width: int = 832
    character_image_height: int = 1216
    special_pose_max_per_run: int = 3

    # Derived-entity on-demand cards (Story 8.13): a cast_decision `<scp_id>-<n>`
    # duplicate/offshoot gets a full card generated the first time it's referenced.
    derived_entity_max_per_run: int = 2

    # Vision LLM descriptor enrichment (Story 5.13). DashScope Qwen-VL — the DeepSeek
    # account has no vision-capable model at all (text-only), so this is a distinct
    # provider from deepseek_*, not just a different model on the same account.
    # ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling;
    # enrich_descriptor_from_references guards for a missing key at call time.
    character_vision_model: str = "qwen-vl-plus"
    character_vision_api_key: str = ""
    # Own knob, not deepseek_max_tokens: qwen-vl-plus rejects max_tokens > 8192 with a
    # 400, so borrowing the text model's budget silently killed every enrichment call
    # once YTFLOW_DEEPSEEK_MAX_TOKENS went to 16384. An enriched descriptor is a
    # paragraph, so 2000 is already generous.
    character_vision_max_tokens: int = Field(2000, gt=0, le=8192)

    # Chapter-card transitions (Story 5.1). Cards insert between scenes when true;
    # video_node clamps duration to the accepted 1.5-2.0s range.
    chapter_cards: bool = True
    chapter_card_duration_sec: float = 1.75

    # Sound design (Story 7.1): mood-driven BGM/ambient/stinger, ducked under
    # narration. Opt out if the data/audio asset library isn't populated yet.
    sound_design_enabled: bool = True

    # Post-processing filters (Story 7.2): mood-driven color grade + constant
    # vignette/film-grain on every scene and chapter card.
    post_fx_enabled: bool = True

    # Character parallax (Story 7.3): couple the near-plane character's zoom/pan to
    # the background's EffectSpec, amplified by CHAR_DEPTH_FACTOR, for a real
    # multiplane depth cue. When false, character reverts to fixed-size sway/bob only.
    parallax_enabled: bool = True

    # Camera noise (Story 11.3): fBm handheld camera stage (sway/tremor/rot/
    # micro-zoom + stinger-synced trauma shake) on every composited shot.
    # When false, no stage is attached — the pre-11.3 filter chain, byte-identical.
    camera_noise_enabled: bool = True

    # Content language (Story 9.1): single seam for a future language pivot. The
    # pipeline is Korean-only today — changing this to anything else makes
    # scenario_node fail fast rather than silently mixing languages. Touchpoints
    # that would need real work before this value does anything: the WhisperX
    # aligner language (subtitle.py, already wired), SUBTITLE_FONT_FAMILY +
    # line-wrap constants tuned for Hangul density (subtitle.py), CARD_FONT_PATH
    # (video.py), and the scenario-chain prompt templates in prompts/scenario/
    # (research/structure/visual_breakdown/tts_normalize here, plus
    # writing/review/critic_agent/format_guide which live only in Langfuse's
    # production label / the sibling yt.pipe repo). `qwen_tts_voice` is also
    # coupled to language — swapping this without picking a matching voice
    # would silently mis-synthesize; no mapping exists yet.
    content_language: str = "ko"

    # CC BY-SA attribution (Story 5.20): ending credit card + description.txt for
    # every monetized SCP video. Off for dry-runs/non-SCP content where the license
    # doesn't apply — skips both outputs entirely, no HTTP calls, no file writes.
    cc_attribution: bool = True

    # Stock location plates (Story 8.5): IPAdapter style-anchor weight for the
    # seed script's bulk plate generation. Tunable without a code change if the
    # anchor bleeds content (lower) or the style doesn't hold (raise).
    location_ipadapter_weight: float = Field(0.4, ge=0.0, le=1.0)
    location_plate_workflow_path: str = "data/workflows/comfyui_location_plate_api.json"
    location_anchor_dir: str = "data/anchors/locations"
    # Curated structure references (Story 8.17): one real photo per
    # (location_key, variant), written by scripts/fetch_location_refs.py and read
    # back by the seed script as the ControlNet hint. Same shape as the anchor dir
    # above so tests and operators can redirect it with one env var.
    location_refs_dir: str = "data/refs/locations"
    # Gate for the Story 8.17 STOCK plate substitution in image_node. OFF: the
    # substitution discards the shot's image_prompt entirely and is keyed on
    # scene_num, so every shot of a scene gets ONE identical background —
    # measured run-wide collapse from 155 distinct backgrounds to 41 (85% of
    # shots; scene 5's containment chamber went 21 shots -> 1 image). Stays off
    # until a plate-vs-prompt reconciliation story makes plate reuse per-shot and
    # prompt-aware. ON reproduces 8.17 behaviour exactly.
    stock_plate_substitution_enabled: bool = False
    # Story 10.1c — regenerate each shot from plate + cards + a placement instruction
    # instead of compositing cards onto the plate. Off by default until the full-run
    # viewing verdict lands; the overlay path stays intact behind it.
    shot_recompose_enabled: bool = False
    shot_recompose_workflow_path: str = "data/workflows/comfyui_shot_recompose_qwen_api.json"

    # Composite harmonization (Story 8.7): tiered collage-look resolution ladder.
    # 0=off (byte-for-byte pre-8.7 output), 1=mood tint+contact shadow,
    # 2=+light wrap, 3=+IC-Light re-lighting. Default 1 since Story 11.1: the
    # 2026-08-01 quality research (§Phase 1 quick-win 3) identified tier 0 as a
    # confirmed "cheap collage" cause; tier 1 stays the fallback once 8-16's
    # IC-Light (tier 3) lands.
    composite_harmonization_tier: int = Field(1, ge=0, le=3)
    iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"

    # Depth-aware card placement (Story 8.16): stand a card's feet on a ground
    # plane estimated from the plate's monocular depth map instead of frame
    # centre, with the contact shadow derived from the same value, and mask the
    # card where the plate is nearer than it.
    #
    # ON after live verification (2026-08-03): rendered a real control-room plate
    # with a real card through real ffmpeg and measured the composited feet row
    # against the plate's own floor on every frame of a 1.15x push-in — 3.9px max
    # error tracking, versus 57.2px for a static anchor by the last frame. Ground
    # lines measured across all 41 readable library plates: strictly ordered
    # far<=mid<=near on 41/41. With no depth map (ComfyUI down, mock mode) the
    # resolver hands back the measured fallback ground and the run completes.
    depth_placement_enabled: bool = True
    depth_comfyui_workflow_path: str = "data/workflows/comfyui_depth_anything_v2_api.json"

    # Depth estimator identity (Story 11.5 AC3). Pinned HERE, not inside the
    # workflow JSON, because the depth cache key and provenance sidecar have to
    # record what actually produced a map — a checkpoint swapped inside the JSON
    # used to serve every previously cached map unchanged.
    # Depth-Anything-V2 *Small* is Apache-2.0; Base/Large/Giant weights are
    # CC-BY-NC-4.0 and are refused below on a potentially monetized output path.
    # Story 8.16 shipped `depth_anything_v2_vitl.pth` (Large, non-commercial);
    # this default is the AC3 correction.
    depth_model_ckpt: str = "depth_anything_v2_vits.pth"
    depth_model_resolution: int = Field(1024, gt=0)
    # Explicit, logged opt-in for a non-commercial checkpoint (research renders
    # only). Off means depth estimation refuses to run one at all — AC3's "not
    # *silently* used" needs a real gate, not a warning nobody reads.
    depth_allow_noncommercial_model: bool = False

    # ── 2.5D parallax (Story 11.5) ──────────────────────────────────────────
    # Kill switch (AC9): off → no depth/parallax renderer is called at all and
    # the Story 7.3/11.3 zoompan behaviour is preserved byte-for-byte.
    parallax_25d_enabled: bool = True
    # Visible plate displacement as a fraction of frame WIDTH. AC6 bounds this
    # to the 1-3% band single-image displacement can hide disocclusion inside;
    # the Field bounds make an out-of-band env var a startup error, not a
    # rubber-edged render nobody traces back to config.
    parallax_displacement_frac: float = Field(0.02, ge=0.01, le=0.03)
    # DepthFlow (AGPL-3.0) is an EXTERNAL runtime in its own virtualenv, never a
    # yt.flow dependency — see docs/PARALLAX_RUNTIME.md for the compliance
    # decision and install steps. Off until spiked on the target host (AC11);
    # the depth-warp renderer below it in the ladder needs no extra runtime.
    depthflow_enabled: bool = False
    depthflow_python: str = ""  # interpreter of the isolated DepthFlow venv
    depthflow_timeout_sec: float = Field(180.0, gt=0)

    # Per-shot cut assembly (Story 8.11): a shot's clip window shorter than this
    # merges into the previous shot's clip (first shot merges forward). 0.0
    # disables merging entirely.
    min_shot_clip_sec: float = Field(2.0, ge=0.0)
