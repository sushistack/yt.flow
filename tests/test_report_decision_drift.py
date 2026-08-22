"""Tests for scripts/report_decision_drift.py (Story 13.6 AC7, via Story 14.4).

Fully offline: no `Settings()` construction, no network, no `.env` from the repo —
every case hands `collect()` an explicit environ dict and temp files, so a real
`.env` on the developer's box cannot make one of these pass or fail.

This report's only job is being believed. What is asserted here is therefore the
provenance claims, not the formatting: which of `os.environ` / `.env` / the code
default WON, that a matching-but-env-sourced value is still named (AC3), that a
latent `.env.example` pin is a separate bucket from effective drift, and that a
field with no decision entry is simply absent instead of a crash (AC7).

`collect()` reads `DECISIONS` from `config.py`, which is the live table — so the
drifted/unclassified cases are built by monkeypatching that dict rather than by
asserting today's repo happens to contain such a row.
"""

import importlib.util
from pathlib import Path

import pytest

from yt_flow.config import Decision


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "report_decision_drift", "scripts/report_decision_drift.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


rdd = _load_script()

# A real field with a decided value that is NOT its code default (`False`), so the
# drift bucket can be exercised without waiting for the repo to actually drift.
DRIFTED = {"camera_noise_enabled": Decision("13.6-test", "2026-08-22", True, "fixture")}
# A real field whose decided value IS its code default.
MATCHING = {"qwen_tts_speed": Decision("14.4-test", "2026-08-17", 1.1, "fixture")}


def _files(tmp_path, env: str = "", example: str | None = None):
    env_file = tmp_path / ".env"
    env_file.write_text(env, encoding="utf-8")
    example_file = tmp_path / ".env.example"
    if example is not None:
        example_file.write_text(example, encoding="utf-8")
    return env_file, example_file


def _findings(found):
    """The four actionable buckets. `all` and `state` are always populated by design —
    they are the report's transparency, not findings."""
    return {k: v for k, v in found.items() if k not in ("all", "state")}


def _only(rows):
    assert len(rows) == 1, rows
    return rows[0]


def test_decided_on_but_shipped_off_is_one_drift_row(monkeypatch, tmp_path):
    monkeypatch.setattr(rdd, "DECISIONS", DRIFTED)
    found = rdd.collect({}, *_files(tmp_path))
    row = _only(found["drift"])
    assert (row["field"], row["decided"], row["default"], row["effective"], row["source"]) == (
        "camera_noise_enabled", True, False, False, "code default")
    assert row["story"] == "13.6-test" and row["date"] == "2026-08-22"
    assert found["env_sourced"] == [] and found["latent"] == [] and found["stale"] == []


def test_an_env_sourced_value_is_named_even_when_it_matches(monkeypatch, tmp_path):
    """AC3: `.env` beating the code default is the recorded hazard, so the source is
    reported whether or not the value happens to agree with the decision."""
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    env_file, example_file = _files(tmp_path, env="YTFLOW_QWEN_TTS_SPEED=1.1\n")
    found = rdd.collect({}, env_file, example_file)
    assert found["drift"] == []
    row = _only(found["env_sourced"])
    assert row["effective"] == 1.1 and row["source"] == str(env_file)
    assert row["effective"] == row["decided"]  # matching-but-env-sourced


def test_os_environ_beats_the_env_file_and_only_the_winner_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    env_file, example_file = _files(tmp_path, env="YTFLOW_QWEN_TTS_SPEED=1.1\n")
    found = rdd.collect({"YTFLOW_QWEN_TTS_SPEED": "1.4"}, env_file, example_file)
    row = _only(found["env_sourced"])
    assert (row["effective"], row["source"]) == (1.4, "os.environ")
    assert _only(found["drift"])["effective"] == 1.4  # 1.4 != decided 1.1


def test_a_latent_example_pin_is_reported_apart_from_effective_drift(monkeypatch, tmp_path):
    """Nothing on this box is wrong yet — a fresh checkout copying the example is."""
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect({}, *_files(tmp_path, example="YTFLOW_QWEN_TTS_SPEED=1.2\n"))
    assert found["drift"] == [] and found["env_sourced"] == []
    row = _only(found["latent"])
    assert (row["example"], row["default"], row["agrees"]) == (1.2, 1.1, False)


def test_an_example_pin_is_latent_even_when_it_agrees(monkeypatch, tmp_path):
    """Review-pass correction: the bucket keys on PRESENCE, not on difference. Comparing
    against the code default was wrong twice over — a pin carrying a STALE default stayed
    silent (the case 13.6 exists for), and a pin carrying the DECIDED value was reported
    as a problem when it was the only thing making that checkout correct. The shipped rule
    is that a decision-bearing value is not pinned there in EITHER direction, so `agrees`
    ranks the row instead of suppressing it.
    """
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect({}, *_files(tmp_path, example="YTFLOW_QWEN_TTS_SPEED=1.1\n"))
    assert _only(found["latent"])["agrees"] is True


def test_a_stale_code_default_pinned_in_the_example_is_still_reported(monkeypatch, tmp_path):
    """The case the old comparison could not see at all: the code default has drifted from
    the verdict and the example file pins that stale default."""
    monkeypatch.setattr(rdd, "DECISIONS", DRIFTED)  # decided True, code default False
    found = rdd.collect({}, *_files(tmp_path, example="YTFLOW_CAMERA_NOISE_ENABLED=false\n"))
    row = _only(found["latent"])
    assert (row["example"], row["default"], row["decided"], row["agrees"]) == (
        False, False, True, False)


def test_a_field_with_no_decision_entry_is_absent_not_a_crash(monkeypatch, tmp_path):
    """AC7: the classification is incremental, so most of `Settings` has no entry —
    an unclassified field must not appear and must not break the report."""
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect(
        {"YTFLOW_POST_FX_ENABLED": "false"},  # a real field, deliberately unclassified
        *_files(tmp_path, example="YTFLOW_SOUND_DESIGN_ENABLED=false\n"),
    )
    assert [r["field"] for r in found["env_sourced"]] == []
    assert found["latent"] == [] and found["stale"] == []


def test_a_decision_naming_a_dead_field_is_stale_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(rdd, "DECISIONS", {
        "field_deleted_in_a_refactor": Decision("13.6-test", "2026-08-22", True, "fixture")})
    found = rdd.collect({}, *_files(tmp_path))
    assert _only(found["stale"])["field"] == "field_deleted_in_a_refactor"
    assert found["drift"] == [] and found["env_sourced"] == []


def test_a_healthy_repo_reports_nothing_at_all(monkeypatch, tmp_path):
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect({}, *_files(tmp_path))
    assert _findings(found) == {"drift": [], "env_sourced": [], "latent": [], "stale": []}
    assert _only(found["all"])["source"] == "code default"


def test_a_missing_env_file_falls_back_to_the_code_default(monkeypatch, tmp_path):
    """`.env` absent is the fresh-checkout case, which is the whole point of the flip."""
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect({}, tmp_path / "nope" / ".env", tmp_path / "nope" / ".env.example")
    assert _findings(found) == {"drift": [], "env_sourced": [], "latent": [], "stale": []}
    assert _only(found["all"])["source"] == "code default"
    # ABSENT, not "present and empty": the printer says NOT CHECKED off this, because a
    # file that was never read must not be reported as a file with nothing in it.
    assert found["state"][0]["env_state"] == "ABSENT"


def test_an_unparseable_pin_is_printed_rather_than_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(rdd, "DECISIONS", MATCHING)
    found = rdd.collect({"YTFLOW_QWEN_TTS_SPEED": "fast"}, *_files(tmp_path))
    assert _only(found["drift"])["effective"] == "fast"


def test_main_always_exits_zero_on_a_successful_read(monkeypatch, tmp_path, capsys):
    """The Boundaries: a report, never a gate. Drift in every bucket, still 0."""
    monkeypatch.setattr(rdd, "DECISIONS", DRIFTED)
    env_file, _ = _files(tmp_path, env="YTFLOW_CAMERA_NOISE_ENABLED=false\n",
                         example="YTFLOW_CAMERA_NOISE_ENABLED=true\n")
    monkeypatch.setattr("sys.argv", ["report_decision_drift.py", "--env-file", str(env_file)])
    assert rdd.main() == 0
    out = capsys.readouterr().out
    assert "DRIFT" in out and "ENV" in out and "LATENT" in out


def test_main_rejects_an_unknown_flag(monkeypatch):
    """The one non-zero exit the Boundaries allow: a usage error, from argparse."""
    monkeypatch.setattr("sys.argv", ["report_decision_drift.py", "--fix"])
    with pytest.raises(SystemExit) as exc:
        rdd.main()
    assert exc.value.code != 0


def test_every_declared_field_is_listed_with_its_winning_source(monkeypatch, tmp_path):
    """AC2 asks the report to name a NON-drifting setting's source, so "no drift" is
    a claim a reader can check rather than take on faith."""
    monkeypatch.setattr(rdd, "DECISIONS", {**DRIFTED, **MATCHING})
    env_file, example_file = _files(tmp_path, env="YTFLOW_QWEN_TTS_SPEED=1.1\n")
    found = rdd.collect({}, env_file, example_file)
    assert [r["field"] for r in found["all"]] == ["camera_noise_enabled", "qwen_tts_speed"]
    assert [r["source"] for r in found["all"]] == ["code default", str(env_file)]


def test_the_repo_pins_no_decision_bearing_value_in_the_example_file(tmp_path):
    """AC: nothing survives pinned in `.env.example`. The manual `grep` in the spec's
    Verification block only covered the guard's own key; this covers every declared
    field, which is how the deepseek revert was missed in the first pass. Reads the
    repo's real example file but a scratch `.env`, so a developer's local pin can
    neither break nor satisfy it.
    """
    found = rdd.collect({}, tmp_path / ".env", _REPO_ROOT / ".env.example")
    assert found["latent"] == [], found["latent"]
    assert found["stale"] == [], found["stale"]
    # No `os.environ`, no `.env`, so every value must come from the code — i.e. every
    # decided value is genuinely the shipped default.
    assert found["drift"] == [], found["drift"]


def test_the_real_table_lists_the_guard_as_code_default(tmp_path):
    """The story's own claim, against the real DECISIONS: the flip reaches pixels from
    the code, not from `.env`. Reads the repo's example file but a scratch `.env`, so a
    local pin cannot make this pass or fail."""
    found = rdd.collect({}, tmp_path / ".env", _REPO_ROOT / ".env.example")
    row = _only([r for r in found["all"] if r["field"] == "background_person_guard_attempts"])
    assert (row["decided"], row["default"], row["effective"], row["source"]) == (
        2, 2, 2, "code default")


def test_every_decision_citation_still_appears_in_config_py():
    """`DECISIONS` is an index into the dated verdict comments and the comment wins when
    they disagree — but nothing detected a citation that had rotted away. Asserts the
    quoted fragment is still in the source, which is the cheap half of that contract
    (six rows share one byte-identical stamp, so this is a presence check, not a
    uniqueness one)."""
    from yt_flow.config import DECISIONS
    source = (_REPO_ROOT / "src/yt_flow/config.py").read_text(encoding="utf-8")
    for name, decision in DECISIONS.items():
        # The citation is "field: `fragment`" or "field: \"fragment\"" — check the quoted part.
        fragment = decision.citation.split(":", 1)[1].strip().strip("`\"")
        head = fragment.split("...")[0].strip()
        assert head in source, f"{name}: citation no longer in config.py — {head!r}"
