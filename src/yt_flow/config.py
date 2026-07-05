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

    # ComfyUI image generation (Story 1.6). Reachability is checked at image_node
    # entry, not app startup. In mock mode the HTTP client is never instantiated.
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: str = "data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json"
    comfyui_mock: bool = False
    # Layered-asset mode (Story 1.6b): emit separate background + transparent character PNGs.
    # Node IDs are the SaveImage nodes in the layered workflow export (bg=9, char=13).
    comfyui_layered: bool = False
    comfyui_background_node: str = "9"
    comfyui_character_node: str = "13"
    # Story 5.11: per-shot flat-image fallback when segmentation errors in layered
    # mode. Reuses the already-shipped plain non-layered workflow — no new asset.
    comfyui_flat_fallback_workflow_path: str = "data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json"

    # Runtime artifact root; stage nodes write under workspace/{run_id}/. [AD-10]
    workspace_path: str = "./workspace"

    # Qwen TTS via Alibaba DashScope (international). Model/voice are config-pinned,
    # never hardcoded in nodes. ponytail: api_key defaults to "" so Settings() stays
    # constructible in tests/tooling; tts_node guards for a missing key at call time.
    qwen_tts_api_key: str = ""
    qwen_tts_endpoint: str = "https://dashscope-intl.aliyuncs.com"
    qwen_tts_model: str = "qwen3-tts-flash"
    qwen_tts_voice: str = "Cherry"
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
    character_image_width: int = 1664
    character_image_height: int = 928

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
