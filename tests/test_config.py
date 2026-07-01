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
