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
    deepseek_max_tokens: int = 8192
    # A/B evaluation judge (Story 4.2). Same OpenAI-compatible endpoint; the model is
    # config-pinned so the judge can be swapped independently of the content generator.
    deepseek_judge_model: str = "deepseek-v4-flash"

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

    # Forced alignment for subtitle generation (Story 1.8). Strategy is config-driven;
    # swap the aligner name without touching subtitle_node. whisperx is not in
    # pyproject.toml — install separately before using the real aligner.
    aligner: str = "whisperx"
    aligner_model: str = "base"
    aligner_device: str = "cpu"
    aligner_compute_type: str = "int8"

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

    # Vision LLM descriptor enrichment (Story 5.13). DashScope Qwen-VL — the DeepSeek
    # account has no vision-capable model at all (text-only), so this is a distinct
    # provider from deepseek_*, not just a different model on the same account.
    # ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling;
    # enrich_descriptor_from_references guards for a missing key at call time.
    character_vision_model: str = "qwen-vl-plus"
    character_vision_api_key: str = ""

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

    # Composite harmonization (Story 8.7): tiered collage-look resolution ladder.
    # 0=off (byte-for-byte pre-8.7 output), 1=mood tint+contact shadow,
    # 2=+light wrap, 3=+IC-Light re-lighting. Default stays off until a real
    # tier-0 vs tier-1 A/B run confirms the visual win.
    composite_harmonization_tier: int = Field(0, ge=0, le=3)
    iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"

    # Per-shot cut assembly (Story 8.11): a shot's clip window shorter than this
    # merges into the previous shot's clip (first shot merges forward). 0.0
    # disables merging entirely.
    min_shot_clip_sec: float = Field(2.0, ge=0.0)
