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
