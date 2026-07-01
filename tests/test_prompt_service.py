"""Unit tests for src/yt_flow/services/prompt_service.py (Story 1.3).

Uses a fake Langfuse client injected via build_client monkeypatch — no live server.
"""

import pytest

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
