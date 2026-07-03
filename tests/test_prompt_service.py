"""Unit tests for src/yt_flow/services/prompt_service.py (Story 1.3).

Uses a fake Langfuse client injected via build_client monkeypatch — no live server.
"""

import pytest
from langfuse.api import NotFoundError

from yt_flow.services import prompt_service as ps


class FakePrompt:
    def __init__(self, text):
        self.prompt = text

    def compile(self, **variables):
        out = self.prompt
        for k, v in variables.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out


class FakeClient:
    def __init__(self, prompts):
        self.prompts = prompts
        self.calls = []

    def get_prompt(self, name, label=None):
        self.calls.append((name, label))
        if name not in self.prompts:
            raise LookupError(name)
        return FakePrompt(self.prompts[name])


class FakeLabeledClient:
    """Distinguishes by-label lookups: raises NotFoundError for a missing label
    instead of the generic LookupError FakeClient uses, so get_prompt_with_fallback's
    NotFoundError-only catch can be tested against a real-shaped error."""

    def __init__(self, by_label):
        self.by_label = by_label
        self.calls = []

    def get_prompt(self, name, label=None):
        self.calls.append((name, label))
        if label not in self.by_label:
            raise NotFoundError(body="not found")
        return FakePrompt(self.by_label[label])


def test_get_prompt_returns_prompt_object(monkeypatch):
    client = FakeClient({"scenario": "hello {{scp_text}}"})
    monkeypatch.setattr(ps, "build_client", lambda: client)
    prompt = ps.get_prompt("scenario")
    assert prompt.prompt == "hello {{scp_text}}"
    assert client.calls == [("scenario", None)]


def test_compile_prompt_renders_variables(monkeypatch):
    client = FakeClient({"scenario": "SCP: {{scp_text}}"})
    monkeypatch.setattr(ps, "build_client", lambda: client)
    assert ps.compile_prompt("scenario", scp_text="SCP-173") == "SCP: SCP-173"


def test_get_prompt_passes_label(monkeypatch):
    client = FakeClient({"scenario": "x"})
    monkeypatch.setattr(ps, "build_client", lambda: client)
    ps.get_prompt("scenario", label="production")
    assert client.calls == [("scenario", "production")]


def test_get_prompt_error_includes_name_and_label(monkeypatch):
    client = FakeClient({})  # nothing -> get_prompt raises
    monkeypatch.setattr(ps, "build_client", lambda: client)
    with pytest.raises(RuntimeError) as exc:
        ps.get_prompt("scenario", label="production")
    msg = str(exc.value)
    assert "scenario" in msg and "production" in msg


def test_get_prompt_with_fallback_returns_candidate_when_present(monkeypatch):
    client = FakeLabeledClient({"candidate": "candidate text", "production": "prod text"})
    monkeypatch.setattr(ps, "build_client", lambda: client)
    prompt = ps.get_prompt_with_fallback("scenario/writing", label="candidate")
    assert prompt.prompt == "candidate text"
    assert client.calls == [("scenario/writing", "candidate")]


def test_get_prompt_with_fallback_falls_back_to_production_when_candidate_missing(monkeypatch, caplog):
    client = FakeLabeledClient({"production": "prod text"})  # no "candidate" label seeded
    monkeypatch.setattr(ps, "build_client", lambda: client)
    with caplog.at_level("WARNING"):
        prompt = ps.get_prompt_with_fallback("scenario/writing", label="candidate")
    assert prompt.prompt == "prod text"
    assert client.calls == [("scenario/writing", "candidate"), ("scenario/writing", "production")]
    # fallback must not be silent — otherwise a total fallback looks like a real A/B
    assert any("falling back" in r.message and "scenario/writing" in r.message for r in caplog.records)


def test_get_prompt_with_fallback_wraps_other_errors(monkeypatch):
    class BoomClient:
        def get_prompt(self, name, label=None):
            raise ValueError("boom")

    monkeypatch.setattr(ps, "build_client", lambda: BoomClient())
    with pytest.raises(RuntimeError) as exc:
        ps.get_prompt_with_fallback("scenario/writing", label="candidate")
    msg = str(exc.value)
    assert "scenario/writing" in msg and "candidate" in msg
