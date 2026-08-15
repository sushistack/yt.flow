import pytest
from pydantic import ValidationError


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("YTFLOW_LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("YTFLOW_LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("YTFLOW_LANGFUSE_SECRET_KEY", "sk-test")

    from yt_flow.config import Settings
    s = Settings(_env_file=None)  # env-only: ignore any local .env so the test is hermetic

    assert s.langfuse_host == "https://langfuse.example.com"
    assert s.langfuse_public_key == "pk-test"
    assert s.langfuse_secret_key == "sk-test"


@pytest.mark.parametrize("missing_key", [
    "YTFLOW_LANGFUSE_HOST",
    "YTFLOW_LANGFUSE_PUBLIC_KEY",
    "YTFLOW_LANGFUSE_SECRET_KEY",
])
def test_missing_field_raises_validation_error(monkeypatch, missing_key):
    monkeypatch.setenv("YTFLOW_LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("YTFLOW_LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("YTFLOW_LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv(missing_key)

    from yt_flow.config import Settings
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # ponytail: skip .env to force env-only lookup

    field_name = missing_key.removeprefix("YTFLOW_").lower()
    # Inspect structured errors (version-stable) rather than the formatted message string.
    missing_locs = {loc for err in exc_info.value.errors() for loc in err["loc"]}
    assert field_name in missing_locs


# ── B-3: YTFLOW_LANGFUSE_ENABLED flag + @observe no-op when off ──────────────

def _base_env(monkeypatch):
    monkeypatch.setenv("YTFLOW_LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("YTFLOW_LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("YTFLOW_LANGFUSE_SECRET_KEY", "sk-test")


def test_langfuse_enabled_defaults_true(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YTFLOW_LANGFUSE_ENABLED", raising=False)
    from yt_flow.config import Settings
    assert Settings(_env_file=None).langfuse_enabled is True


@pytest.mark.parametrize("raw,expected", [("false", False), ("0", False), ("true", True)])
def test_langfuse_enabled_env_override(monkeypatch, raw, expected):
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_LANGFUSE_ENABLED", raw)
    from yt_flow.config import Settings
    assert Settings(_env_file=None).langfuse_enabled is expected


def test_sound_design_enabled_defaults_true(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YTFLOW_SOUND_DESIGN_ENABLED", raising=False)
    from yt_flow.config import Settings
    assert Settings(_env_file=None).sound_design_enabled is True


def test_location_plate_defaults(monkeypatch):
    _base_env(monkeypatch)
    for key in (
        "YTFLOW_LOCATION_IPADAPTER_WEIGHT",
        "YTFLOW_LOCATION_PLATE_WORKFLOW_PATH",
        "YTFLOW_LOCATION_ANCHOR_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    assert s.location_ipadapter_weight == 0.4
    assert s.location_plate_workflow_path == "data/workflows/comfyui_location_plate_api.json"
    assert s.location_anchor_dir == "data/anchors/locations"


def test_composite_harmonization_defaults(monkeypatch):
    _base_env(monkeypatch)
    for key in ("YTFLOW_COMPOSITE_HARMONIZATION_TIER", "YTFLOW_ICLIGHT_COMFYUI_WORKFLOW_PATH"):
        monkeypatch.delenv(key, raising=False)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    # Story 11.1 AC4: tier 1 (mood tint + contact shadow) is the default now —
    # research-confirmed quick win; tier 0 remains reachable via env for A/B.
    assert s.composite_harmonization_tier == 1
    assert s.iclight_comfyui_workflow_path == "data/workflows/comfyui_iclight_relight_api.json"


def test_composite_harmonization_tier_is_bounded(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_COMPOSITE_HARMONIZATION_TIER", "4")
    from yt_flow.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_content_language_defaults_ko(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YTFLOW_CONTENT_LANGUAGE", raising=False)
    from yt_flow.config import Settings
    assert Settings(_env_file=None).content_language == "ko"


def test_content_language_env_override(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_CONTENT_LANGUAGE", "en")
    from yt_flow.config import Settings
    assert Settings(_env_file=None).content_language == "en"


def test_qwen_tts_clone_and_speed_defaults(monkeypatch):
    _base_env(monkeypatch)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    # 2026-08-15: Jay 판정으로 클론 음성이 프로덕션 기본값이 됐다. 음성 ID는 5.24에서
    # 이미 등록돼 있었고 이 불리언 하나가 false라 스톡 Cherry가 출하되고 있었다 — 그
    # 침묵이 Story 13.6의 발단이다.
    assert s.qwen_tts_clone_enabled is True
    assert s.qwen_tts_clone_model == "qwen3-tts-vc-2026-01-22"
    assert s.qwen_tts_clone_voice_path == "data/voices/sutak.mp3"
    assert s.qwen_tts_clone_voice_id == ""
    assert s.qwen_tts_speed == 1.2


def test_qwen_tts_speed_out_of_range_raises(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_QWEN_TTS_SPEED", "12")
    from yt_flow.config import Settings
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    errors = {err["loc"][0]: err for err in exc_info.value.errors()}
    assert "qwen_tts_speed" in errors


def test_deepseek_reasoning_defaults_low_and_budget_unchanged(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YTFLOW_DEEPSEEK_REASONING", raising=False)
    monkeypatch.delenv("YTFLOW_DEEPSEEK_MAX_TOKENS", raising=False)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    assert s.deepseek_reasoning == "low"
    assert s.deepseek_max_tokens == 32768


def test_deepseek_reasoning_rejects_unknown_value(monkeypatch):
    """Fail at config load, not mid-run with an API-rejected request field."""
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_DEEPSEEK_REASONING", "off")
    from yt_flow.config import Settings
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "deepseek_reasoning" in {err["loc"][0] for err in exc_info.value.errors()}


def test_observe_is_noop_when_flag_off():
    """With the flag off, the observability seam's @observe runs the fn and
    get_client().update_current_span(...) never raises (no trace emitted).

    observability.py binds the seam at import time from env, so we exercise the
    active branch directly rather than reimporting under a patched env."""
    import yt_flow.observability as obs

    @obs.observe(name="scenario")
    def stage(x):
        obs.get_client().update_current_span(metadata={"k": "v"})
        return x * 2

    # Whichever branch is bound (the suite defaults tracing off; real path if
    # YTFLOW_LANGFUSE_ENABLED=true), the decorated fn must still run and return.
    assert stage(21) == 42

    # Directly assert the no-op client contract regardless of flag state.
    from yt_flow.observability import _NoopClient  # noqa: PLC0415 — test-only introspection
    c = _NoopClient()
    assert c.create_trace_id(seed="abc") == "abc"
    c.update_current_span(metadata={"a": 1})  # must not raise
    with c.start_as_current_observation(name="x", as_type="chain"):
        pass
    c.create_score(name="n", value=1.0)  # arbitrary tracing call → silent no-op


# ── Story 12.2: Gemini block (model split) ──────────────────────────────────


def test_gemini_defaults_are_pinned_stable_ids(monkeypatch):
    _base_env(monkeypatch)
    for key in (
        "YTFLOW_GEMINI_API_KEY", "YTFLOW_GEMINI_BASE_URL",
        "YTFLOW_GEMINI_WRITING_MODEL", "YTFLOW_GEMINI_JUDGE_MODEL",
        "YTFLOW_GEMINI_WRITING_MAX_TOKENS", "YTFLOW_GEMINI_JUDGE_MAX_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)

    # Empty key by default so Settings() stays constructible offline; the call
    # sites fail fast with a provider-specific error instead.
    assert s.gemini_api_key == ""
    assert s.gemini_base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert s.gemini_writing_model == "gemini-3.6-flash"
    assert s.gemini_judge_model == "gemini-3.6-flash"
    assert s.gemini_writing_max_tokens == 16384
    assert s.gemini_judge_max_tokens == 8192
    # A hot-swappable alias would silently change generation quality between runs.
    for model in (s.gemini_writing_model, s.gemini_judge_model):
        assert "latest" not in model and "preview" not in model and "exp" not in model


def test_gemini_models_and_budgets_are_independently_overridable(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YTFLOW_GEMINI_WRITING_MODEL", "gemini-3.6-pro")
    monkeypatch.setenv("YTFLOW_GEMINI_JUDGE_MAX_TOKENS", "4096")
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    assert s.gemini_writing_model == "gemini-3.6-pro"
    assert s.gemini_judge_model == "gemini-3.6-flash"     # untouched by the writing override
    assert s.gemini_judge_max_tokens == 4096
    assert s.gemini_writing_max_tokens == 16384


def test_deepseek_settings_survive_the_split(monkeypatch):
    """The DeepSeek block — including the now-dormant judge model kept as the
    documented zero-new-provider fallback — must not be removed."""
    _base_env(monkeypatch)
    for key in ("YTFLOW_DEEPSEEK_MODEL", "YTFLOW_DEEPSEEK_MAX_TOKENS", "YTFLOW_DEEPSEEK_JUDGE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    from yt_flow.config import Settings
    s = Settings(_env_file=None)
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.deepseek_model == "deepseek-v4-flash"
    assert s.deepseek_max_tokens == 32768
    assert s.deepseek_judge_model == "deepseek-v4-flash"
