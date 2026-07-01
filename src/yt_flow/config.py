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
    # Node IDs match the SaveImage nodes in the layered workflow export.
    comfyui_layered: bool = False
    comfyui_background_node: str = "9"
    comfyui_character_node: str = "10"

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
