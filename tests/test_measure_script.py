"""Tests for scripts/measure_script.py (Story 12.6 Task 0 — the instrument).

Fully offline. The script's whole job is to produce numbers a story's verdict is
read off, so what is asserted here is the cases where it must REFUSE to produce
one: a WPM computed over a partial TTS run, a 소진율 with no source article, a flag
that silently did nothing. A wrong number from a measurement tool is worse than a
missing one — it looks like evidence.
"""

import importlib.util
import json
import sqlite3

import pytest


def _load_script():
    spec = importlib.util.spec_from_file_location("measure_script", "scripts/measure_script.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ms = _load_script()


def _scenes_dump(tmp_path, count=4):
    values = {
        "run_id": "unit-run",
        "scp_id": "SCP-049",
        "scp_text": "원문",
        "scenes": [
            {"scene_num": n, "narration": " ".join(["어절"] * 10), "display_narration": "x"}
            for n in range(1, count + 1)
        ],
    }
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    return path


def _durations_dump(tmp_path, seconds: dict):
    path = tmp_path / "durations.json"
    path.write_text(json.dumps({"audio_duration_sec": seconds}), encoding="utf-8")
    return path


# ── WPM only over a COMPLETE set of scene durations ──────────────────────────


def test_wpm_is_null_when_the_durations_cover_only_some_scenes(tmp_path):
    """A partial TTS run counts every scene's 어절 against some scenes' seconds and
    overstates the rate. Reporting that number as WPM is a fabricated measurement."""
    scenes = _scenes_dump(tmp_path, 4)
    durations = _durations_dump(tmp_path, {"1": 5.0, "2": 5.0})
    report = ms.measure("unit-run", "unused.db", scenes_json=str(scenes), durations_json=str(durations))
    assert report["wpm"] is None
    assert report["audio_scene_coverage"] == "2/4"
    # The seconds are still reported — a partial run must look partial, not absent.
    assert report["audio_duration_sec"] == 10.0
    assert report["total_words"] == 40


def test_wpm_is_reported_when_every_scene_has_a_duration(tmp_path):
    scenes = _scenes_dump(tmp_path, 4)
    durations = _durations_dump(tmp_path, {"1": 15.0, "2": 15.0, "3": 15.0, "4": 15.0})
    report = ms.measure("unit-run", "unused.db", scenes_json=str(scenes), durations_json=str(durations))
    assert report["audio_scene_coverage"] == "4/4"
    assert report["wpm"] == 40.0  # 40 어절 / 1.0 min


def test_partial_coverage_is_named_in_the_human_table(tmp_path):
    scenes = _scenes_dump(tmp_path, 4)
    durations = _durations_dump(tmp_path, {"1": 5.0})
    report = ms.measure("unit-run", "unused.db", scenes_json=str(scenes), durations_json=str(durations))
    assert "1/4" in ms._table([report])


# ── flags that must not be silently ignored ──────────────────────────────────


def test_durations_json_without_scenes_json_is_a_usage_error(monkeypatch, capsys):
    """It was read only by `_load_scenes_json`, so alone it did nothing at all and
    the run it was meant to add WPM to reported `wpm: null` anyway."""
    monkeypatch.setattr(
        "sys.argv", ["measure_script.py", "--run", "x", "--durations-json", "d.json"]
    )
    with pytest.raises(SystemExit) as excinfo:
        ms.main()
    assert excinfo.value.code == 2
    assert "--durations-json only applies to --scenes-json" in capsys.readouterr().err


# ── guards: the failure must name its cause ──────────────────────────────────


def test_missing_database_names_the_path(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        ms.measure("e5ed4b3a", str(tmp_path / "nope.db"))
    assert str(tmp_path / "nope.db") in str(excinfo.value)


def test_unreadable_database_names_the_path_too(tmp_path):
    db = tmp_path / "locked.db"
    db.write_bytes(b"")
    db.chmod(0)
    with pytest.raises(SystemExit) as excinfo:
        ms.measure("e5ed4b3a", str(db))
    assert str(db) in str(excinfo.value)


def test_malformed_scenes_give_the_intended_message_not_an_attributeerror(tmp_path):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({"scenes": ["씬 1 나레이션", "씬 2"]}), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        ms.measure("unit-run", "unused.db", scenes_json=str(path))
    assert "has no 'scenes'" in str(excinfo.value)


def test_coverage_is_skipped_when_the_source_text_is_empty(tmp_path, capsys, monkeypatch):
    """소진율 is a fraction OF the source. With no source there is no denominator, and
    the judge would answer from its own SCP knowledge — a number about the model."""
    values = {"run_id": "unit-run", "scp_text": "", "scenes": [{"scene_num": 1, "narration": "가 나"}]}
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")

    class _S:
        gemini_api_key = "gm-test"

    def _never(*args, **kwargs):
        raise AssertionError("the coverage LLM call must not be issued without a source")

    monkeypatch.setattr(ms.asyncio, "run", _never)
    report = {"run_id": "unit-run", "coverage": None}
    ms.add_coverage(report, "unused.db", _S(), scenes_json=str(path))
    assert report["coverage"] is None
    assert "no `scp_text`" in capsys.readouterr().err


# ── a hand-edited newest checkpoint is not pipeline output ───────────────────


def _checkpoint_db(tmp_path, rows):
    """Minimal LangGraph `checkpoints` table. `metadata` is plain JSON bytes — the
    shape verified read-only against the real yt_flow.db before this was written."""
    db = tmp_path / "cp.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, "
        "parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, metadata BLOB)"
    )
    serde = ms.JsonPlusSerializer()
    for checkpoint_id, source, values in rows:
        type_, blob = serde.dumps_typed({"channel_values": values})
        con.execute(
            "INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)",
            ("run-aaaa", "", checkpoint_id, None, type_, blob,
             json.dumps({"source": source, "step": 1, "parents": {}}).encode()),
        )
    con.commit()
    con.close()
    return db


_VALUES = {"scp_id": "SCP-049", "scp_text": "원문", "scenes": [{"scene_num": 1, "narration": "가 나 다"}]}


def test_newest_checkpoint_written_by_a_manual_edit_is_flagged(tmp_path, capsys):
    db = _checkpoint_db(tmp_path, [("0001", "loop", _VALUES), ("0002", "update", _VALUES)])
    report = ms.measure("run-aaaa", str(db))
    assert report["total_words"] == 3  # the metrics still come out
    err = capsys.readouterr().err
    assert "source='update'" in err
    assert "measure the EDITED script" in err


def test_newest_checkpoint_from_the_graph_is_not_flagged(tmp_path, capsys):
    # Exactly run e5ed4b3a's shape: `update` rows exist (steps 44/47) but the newest
    # row is `loop`, which is why its committed numbers ARE pipeline output.
    db = _checkpoint_db(tmp_path, [("0001", "update", _VALUES), ("0002", "loop", _VALUES)])
    ms.measure("run-aaaa", str(db))
    assert "update" not in capsys.readouterr().err
