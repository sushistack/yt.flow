"""Unit tests for scripts/migrate_prompts.py (Story 1.3).

No live Langfuse: migration is exercised against an in-memory fake client.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import migrate_prompts as mp


# ── Placeholder conversion (AC5) ────────────────────────────────────────────

@pytest.mark.parametrize("src,expected", [
    ("{scp_id}", "{{scp_id}}"),
    ("Write about {scp_text} now", "Write about {{scp_text}} now"),
    ("{a}{b}", "{{a}}{{b}}"),
    ("{{already}}", "{{already}}"),            # already double: untouched
    ('{"key": "value"}', '{"key": "value"}'),  # JSON object: untouched
    ("{ }", "{ }"),                            # blank braces: untouched
    ("cost is {5}", "cost is {5}"),            # not an identifier: untouched
])
def test_convert_placeholders(src, expected):
    assert mp.convert_placeholders(src) == expected


# ── Source discovery (AC1) ──────────────────────────────────────────────────

def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_discovery_accepts_md_and_tmpl(tmp_path):
    _write(tmp_path, "scenario/01_research.md", "hi {scp_text}")
    _write(tmp_path, "legacy/old.tmpl", "legacy {x}")
    _write(tmp_path, "notes.txt", "ignored")
    files = {p.relative_to(tmp_path).as_posix() for p in mp.iter_source_files(tmp_path)}
    assert files == {"scenario/01_research.md", "legacy/old.tmpl"}


def test_build_manifest_maps_known_names_and_derives_unknown(tmp_path):
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "misc/extra_stage.md", "extra {y}")
    manifest = mp.build_manifest(tmp_path)
    # mapped name from SOURCE_TO_NAME
    assert manifest["scenario/research"] == "research {{scp_text}}"
    # derived name for a file not in the map
    assert manifest["misc/extra_stage"] == "extra {{y}}"
    # required runtime aliases exist and are compiled from their backing source
    assert "scenario" in manifest and "{{scp_text}}" in manifest["scenario"]
    assert "image_prompt" in manifest and "{{shot}}" in manifest["image_prompt"]


def test_build_manifest_fails_when_no_prompts(tmp_path):
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_when_alias_source_missing(tmp_path):
    # only a non-alias file present -> alias backing source is absent
    _write(tmp_path, "misc/only.md", "x {a}")
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_on_reserved_alias_collision(tmp_path):
    # a discovered file deriving to a reserved alias name must not silently overwrite it
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "scenario.md", "colliding top-level file")  # derives to name "scenario"
    with pytest.raises(SystemExit, match="collides"):
        mp.build_manifest(tmp_path)


# ── Idempotent migration (AC4) ──────────────────────────────────────────────

class FakePrompt:
    def __init__(self, text):
        self.prompt = text


class FakeClient:
    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.created = []

    def get_prompt(self, name, label=None):
        if name in self.existing:
            return FakePrompt(self.existing[name])
        raise LookupError(name)

    def create_prompt(self, *, name, type, prompt, labels):
        self.created.append(name)
        self.existing[name] = prompt


def test_migrate_creates_when_absent():
    client = FakeClient()
    results = mp.migrate(client, {"scenario": "body"}, "production")
    assert results["scenario"] == "created"
    assert client.created == ["scenario"]


def test_migrate_skips_when_unchanged():
    client = FakeClient(existing={"scenario": "body"})
    results = mp.migrate(client, {"scenario": "body"}, "production")
    assert results["scenario"] == "skipped"
    assert client.created == []


def test_migrate_creates_new_version_when_changed():
    client = FakeClient(existing={"scenario": "old"})
    results = mp.migrate(client, {"scenario": "new"}, "production")
    assert results["scenario"] == "created"
    assert client.created == ["scenario"]
