import pytest
from pydantic import ValidationError


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("YTFLOW_LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("YTFLOW_LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("YTFLOW_LANGFUSE_SECRET_KEY", "sk-test")

    # Re-import to pick up monkeypatched env (Settings reads at instantiation)
    from yt_flow.config import Settings
    s = Settings()

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
    assert field_name in str(exc_info.value).lower()
