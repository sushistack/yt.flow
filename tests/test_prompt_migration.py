"""Unit tests for scripts/migrate_prompts.py (Story 1.3).

No live Langfuse: migration is exercised against an in-memory fake client.
"""

import re
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


def test_build_manifest_maps_known_names_and_derives_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "misc/extra_stage.md", "extra {y}")
    manifest = mp.build_manifest(tmp_path)
    # mapped name from SOURCE_TO_NAME
    assert manifest["scenario/research"] == "research {{scp_text}}"
    # derived name for a file not in the map
    assert manifest["misc/extra_stage"] == "extra {{y}}"
    # an alias exists and is compiled from its backing source (mechanism test,
    # not tied to any specific production alias — production has none, see
    # docs/superpowers/specs/2026-07-03-scenario-multistage-design.md)
    assert "my_alias" in manifest and "{{scp_text}}" in manifest["my_alias"]


def test_build_manifest_fails_when_no_prompts(tmp_path):
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_when_alias_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    # only a non-alias file present -> alias backing source is absent
    _write(tmp_path, "misc/only.md", "x {a}")
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_on_reserved_alias_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    # a discovered file deriving to a reserved alias name must not silently overwrite it
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "my_alias.md", "colliding top-level file")  # derives to name "my_alias"
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


# ── The seeder must cover every name the runtime actually fetches ───────────
#
# 2026-08-16 (Story 10.8, round 3). `derive_name` turned
# `prompts/character/vision_enrichment.md` into `character/vision_enrichment`, while
# `character_service.py` fetches `character-vision-enrichment`. Both names existed in
# live Langfuse, so seeding "succeeded" — printed `created` — and the runtime went on
# serving a stale prompt. CLAUDE.md's DEV MODE section names this script as *the* way to
# ship a prompt edit, so the documented workflow silently did nothing for every character
# prompt. Nothing in the suite could catch it, because every existing test here checks
# migrate() against names the test itself supplies.
#
# This one instead reads the names out of the source tree: any `get_prompt("...")` /
# `get_prompt_with_fallback("...")` literal in `src/` is a name a run will ask Langfuse
# for, and the seeder's manifest has to contain it.

def _runtime_prompt_names() -> set[str]:
    """Literal prompt names fetched by `src/`. Dynamic names are handled by the caller."""
    src = Path(__file__).parent.parent / "src"
    pattern = re.compile(r"""get_prompt(?:_with_fallback)?\(\s*["']([^"']+)["']""")
    names: set[str] = set()
    for path in src.rglob("*.py"):
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def test_prompt_seeding_covers_runtime_names():
    manifest = mp.build_manifest(Path(__file__).parent.parent / "prompts")
    missing = sorted(_runtime_prompt_names() - set(manifest))
    assert not missing, (
        "these prompt names are fetched at runtime but the seeder would never create "
        f"them, so editing their repo file cannot reach a run: {missing}"
    )


def test_runtime_name_census_actually_found_something():
    # A regex that silently matches nothing would make the test above vacuously green —
    # the exact failure mode it exists to prevent. Pin the three names whose mismatch
    # started this, so a rename has to come here and be thought about.
    names = _runtime_prompt_names()
    assert len(names) >= 5, f"prompt-name census looks broken, found only: {sorted(names)}"
    assert {"character-generation", "character-vision-enrichment",
            "character-angle-selection"} <= names
