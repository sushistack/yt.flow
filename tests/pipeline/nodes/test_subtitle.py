"""Unit tests for src/yt_flow/pipeline/nodes/subtitle.py (Story 1.8, rewritten Story 5.18).

No live WhisperX / Langfuse: settings and the aligner are monkeypatched.
Tests cover the dual-track sentence-cue renderer (sentence_cues, wrap_cue_text,
format_ass), the aligner-fallback path, subtitle_node happy path + guards, error
handling, and purity. No GPU, no network, no model downloads required.
"""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.subtitle as subtitle
from yt_flow.pipeline.nodes.subtitle import (
    AlignmentSegment,
    PLAY_RES_X,
    PLAY_RES_Y,
    SUBTITLE_FONT_FAMILY,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_MARGIN_V,
    SUBTITLE_OUTLINE_WIDTH,
    _get_aligner,
    format_ass,
    sentence_cues,
    subtitle_node,
    wrap_cue_text,
)


# ── Fakes / helpers ───────────────────────────────────────────────────────────


def _settings_ns(tmp_path, aligner="whisperx", content_language="ko"):
    return SimpleNamespace(
        aligner=aligner,
        aligner_model="base",
        aligner_device="cpu",
        aligner_compute_type="int8",
        workspace_path=str(tmp_path),
        content_language=content_language,
    )


class _FakeAligner:
    def __init__(self, segments: list[AlignmentSegment] | None = None):
        self._segs = segments if segments is not None else [{"start_sec": 0.0, "end_sec": 1.5, "text": "hello world"}]
        self.calls: list[tuple[str, str]] = []

    async def align(self, audio_path: str, transcript: str) -> list[AlignmentSegment]:
        self.calls.append((audio_path, transcript))
        return self._segs


def _timings(words: list[str], duration: float = 2.0) -> list[dict]:
    step = duration / len(words) if words else duration
    return [{"word": w, "start_sec": round(i * step, 3), "end_sec": round((i + 1) * step, 3)}
            for i, w in enumerate(words)]


def _scene(scene_num: int, narration: str, *, audio_path: str | None = None,
           word_timings=None, audio_duration: float | None = 2.0,
           display_narration: str | None = None, **over) -> dict:
    base = {
        "scene_num": scene_num,
        "narration": narration,
        "shots": [],
        "audio_path": audio_path,
        "audio_duration": audio_duration if audio_path else None,
        "word_timings": word_timings if word_timings is not None else [],
        "subtitle_path": None,
    }
    if display_narration is not None:
        base["display_narration"] = display_narration
    base.update(over)
    return base


def _state(scenes: list, run_id: str = "run-001", **over) -> dict:
    base = {
        "run_id": run_id,
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": scenes,
        "video_path": None,
        "current_stage": "tts",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture
def audio_file(tmp_path) -> str:
    """Dummy audio file; subtitle_node only checks existence, not format."""
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    return str(p)


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: None)


# ── wrap_cue_text ─────────────────────────────────────────────────────────────


def test_wrap_cue_text_short_stays_one_line():
    assert wrap_cue_text("짧은 문장") == "짧은 문장"


def test_wrap_cue_text_single_word_never_breaks():
    long_word = "가" * 30
    assert wrap_cue_text(long_word) == long_word


def test_wrap_cue_text_wraps_to_two_lines_at_word_boundary():
    text = "이것은 상당히 길어서 줄을 나눠야 하는 문장입니다"
    out = wrap_cue_text(text)
    assert out.count("\\N") == 1
    line1, line2 = out.split("\\N")
    assert line1 and line2
    # word-boundary break: no word is split across the two lines
    assert set((line1 + " " + line2).split()) == set(text.split())


def test_wrap_cue_text_never_produces_more_than_two_lines():
    text = "가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차"
    assert wrap_cue_text(text).count("\\N") <= 1


# ── sentence_cues ─────────────────────────────────────────────────────────────


def test_sentence_cues_single_sentence_uses_full_word_span():
    wt = _timings(["에스시피", "공사", "구는"], duration=3.0)
    cues = sentence_cues(wt, "에스시피 공사 구는.", "SCP-049는.")
    assert len(cues) == 1
    assert cues[0]["start_sec"] == 0.0
    assert cues[0]["end_sec"] == 3.0
    assert cues[0]["text"] == "SCP-049는."


def test_sentence_cues_multiple_sentences_window_per_sentence():
    spoken = "첫 문장 입니다. 둘째 문장 이다."
    display = "첫 문장이다. 둘째다."
    wt = _timings(spoken.split(), duration=6.0)  # 6 words total -> 1.0s each
    cues = sentence_cues(wt, spoken, display)
    assert len(cues) == 2
    assert cues[0]["text"] == "첫 문장이다."
    assert cues[0]["start_sec"] == 0.0
    assert cues[0]["end_sec"] == 3.0  # first sentence consumes 3 words
    assert cues[1]["text"] == "둘째다."
    assert cues[1]["start_sec"] == 3.0
    assert cues[1]["end_sec"] == 6.0


def test_sentence_cues_original_orthography_appears_not_phoneticized():
    spoken = "에스시피 공사 구는 키 일점 구 미터의 개체입니다."
    display = "SCP-049는 키 1.9m의 개체입니다."
    wt = _timings(spoken.split(), duration=4.0)
    cues = sentence_cues(wt, spoken, display)
    assert "SCP-049" in cues[0]["text"]
    assert "에스시피" not in cues[0]["text"]


def test_sentence_cues_no_timings_returns_empty():
    assert sentence_cues([], "문장.", "문장.") == []


def test_sentence_cues_no_spoken_sentences_returns_empty():
    assert sentence_cues(_timings(["a"]), "", "문장.") == []


def test_sentence_cues_display_absent_falls_back_to_spoken_silently(caplog):
    wt = _timings(["문장", "입니다"], duration=2.0)
    with caplog.at_level(logging.WARNING):
        cues = sentence_cues(wt, "문장 입니다.", "")
    assert cues[0]["text"] == "문장 입니다."
    assert not caplog.records  # AC:7 — absent display is expected, not a warning case


def test_sentence_cues_display_equals_spoken_no_warning(caplog):
    wt = _timings(["문장", "입니다"], duration=2.0)
    with caplog.at_level(logging.WARNING):
        cues = sentence_cues(wt, "문장 입니다.", "문장 입니다.")
    assert cues[0]["text"] == "문장 입니다."
    assert not caplog.records


def test_sentence_cues_sentence_count_mismatch_falls_back_with_warning(caplog):
    spoken = "첫 문장. 둘째 문장."
    display = "합쳐진 문장 하나뿐."  # 1 sentence vs spoken's 2 -> mismatch
    wt = _timings(spoken.split(), duration=4.0)
    with caplog.at_level(logging.WARNING):
        cues = sentence_cues(wt, spoken, display)
    assert len(cues) == 2
    assert cues[0]["text"] == "첫 문장."  # fell back to spoken text
    assert cues[1]["text"] == "둘째 문장."
    assert any("sentence-count mismatch" in r.message for r in caplog.records)


def test_sentence_cues_word_timings_count_mismatch_apportions_with_warning(caplog):
    spoken = "첫 문장 이다. 둘째 문장 이다."  # 6 words total
    display = spoken
    wt = _timings(["a", "b", "c"], duration=3.0)  # only 3 timings, not 6
    with caplog.at_level(logging.WARNING):
        cues = sentence_cues(wt, spoken, display)
    assert len(cues) == 2
    assert cues[0]["start_sec"] == 0.0
    assert cues[-1]["end_sec"] == 3.0
    # proportional split by character length, not a crash
    prev_end = 0.0
    for c in cues:
        assert c["start_sec"] >= prev_end - 1e-6
        assert c["end_sec"] > c["start_sec"]
        prev_end = c["end_sec"]
    assert any("word_timings count" in r.message for r in caplog.records)


def test_sentence_cues_word_timings_count_mismatch_falls_back_to_spoken_text(caplog):
    """[AC:7] Word-timings-count mismatch degrades to SPOKEN text, not just re-apportioned
    windows — the prior implementation kept rendering display text here, missed because
    the sibling test above passes display == spoken."""
    spoken = "첫 문장 이다. 둘째 문장 이다."  # 6 words total
    display = "SCP-1 첫 문장. SCP-2 둘째 문장."  # different text, same sentence count
    wt = _timings(["a", "b", "c"], duration=3.0)  # only 3 timings, not 6 -> word-count mismatch
    with caplog.at_level(logging.WARNING):
        cues = sentence_cues(wt, spoken, display)
    assert len(cues) == 2
    assert cues[0]["text"] == "첫 문장 이다."
    assert cues[1]["text"] == "둘째 문장 이다."
    assert "SCP-1" not in cues[0]["text"]
    assert any("word_timings count" in r.message for r in caplog.records)


def test_sentence_cues_long_sentence_splits_into_multiple_cues_proportionally():
    long_display = "가나다라마바 사아자차카타 파하가나다라 마바사아자차 카타파하가나 다라마바사아 자차카타파하"  # > 44 chars
    spoken = "짧은 대응 문장 입니다."
    wt = _timings(spoken.split(), duration=4.0)
    cues = sentence_cues(wt, spoken, long_display)
    assert len(cues) > 1  # soft-cap split into consecutive cues [AC:4]
    prev_end = 0.0
    for c in cues:
        assert c["start_sec"] >= prev_end - 1e-6
        assert c["end_sec"] > c["start_sec"]
        prev_end = c["end_sec"]
    assert prev_end == 4.0
    reconstructed = " ".join(c["text"].replace("\\N", " ") for c in cues)
    assert reconstructed.split() == long_display.split()


def test_sentence_cues_escapes_brace_and_backslash():
    spoken = "문장 입니다."
    display = "위험{한}\\문장."
    wt = _timings(spoken.split(), duration=2.0)
    cues = sentence_cues(wt, spoken, display)
    assert "{" not in cues[0]["text"].replace("\\N", "")
    assert "}" not in cues[0]["text"]
    assert "\\문장" not in cues[0]["text"]


# ── format_ass ─────────────────────────────────────────────────────────────────


def test_format_ass_header_has_play_res_and_typography():
    out = format_ass([])
    assert f"PlayResX: {PLAY_RES_X}" in out
    assert f"PlayResY: {PLAY_RES_Y}" in out
    assert PLAY_RES_X == 1920 and PLAY_RES_Y == 1080
    assert SUBTITLE_FONT_FAMILY in out
    assert f"{SUBTITLE_FONT_SIZE}" in out
    assert f",{SUBTITLE_OUTLINE_WIDTH}," in out
    assert f",{SUBTITLE_MARGIN_V}," in out


def test_format_ass_has_no_karaoke_tags():
    cues = [{"start_sec": 0.0, "end_sec": 1.0, "text": "SCP-049는."}]
    out = format_ass(cues)
    assert "\\k" not in out
    assert "Dialogue:" in out
    assert "SCP-049는." in out


def test_format_ass_empty_cues_no_dialogue_lines():
    out = format_ass([])
    assert "Dialogue:" not in out


def test_format_ass_multiple_cues_in_order():
    cues = [
        {"start_sec": 0.0, "end_sec": 1.0, "text": "첫 번째"},
        {"start_sec": 1.0, "end_sec": 2.0, "text": "두 번째"},
    ]
    out = format_ass(cues)
    assert out.index("첫 번째") < out.index("두 번째")


# ── _words_or_segments (WhisperX word/segment fallback) ───────────────────────


def test_words_or_segments_prefers_usable_words():
    aligned = {
        "word_segments": [{"start": 0.0, "end": 0.5, "word": "hi"}],
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi there"}],
    }
    out = subtitle._words_or_segments(aligned)
    assert out == [{"start_sec": 0.0, "end_sec": 0.5, "text": "hi"}]


def test_words_or_segments_falls_back_when_words_lack_start_end():
    aligned = {
        "word_segments": [{"word": "hi"}, {"word": "there"}],
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi there"}],
    }
    out = subtitle._words_or_segments(aligned)
    assert out == [{"start_sec": 0.0, "end_sec": 1.0, "text": "hi there"}]


def test_words_or_segments_falls_back_when_no_words_at_all():
    aligned = {"segments": [{"start": 0.0, "end": 1.0, "text": "hi there"}]}
    out = subtitle._words_or_segments(aligned)
    assert out == [{"start_sec": 0.0, "end_sec": 1.0, "text": "hi there"}]


def test_words_or_segments_empty_when_nothing_usable():
    assert subtitle._words_or_segments({}) == []


# ── _get_aligner ─────────────────────────────────────────────────────────────


def test_get_aligner_whisperx_returns_instance():
    s = SimpleNamespace(aligner="whisperx", aligner_model="base",
                        aligner_device="cpu", aligner_compute_type="int8",
                        content_language="ko")
    from yt_flow.pipeline.nodes.subtitle import WhisperXAligner
    aligner = _get_aligner(s)
    assert isinstance(aligner, WhisperXAligner)
    assert aligner._language == "ko"


def test_get_aligner_unknown_raises_value_error():
    s = SimpleNamespace(aligner="fake_unknown", aligner_model="x",
                        aligner_device="cpu", aligner_compute_type="int8")
    with pytest.raises(ValueError, match="Unsupported YTFLOW_ALIGNER"):
        _get_aligner(s)


# ── subtitle_node: happy path ─────────────────────────────────────────────────


async def test_subtitle_node_always_writes_ass(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    wt = _timings(["에스시피", "공사", "구는", "키", "일점", "구", "미터의", "개체입니다."], duration=4.0)
    scenes = [_scene(1, "에스시피 공사 구는 키 일점 구 미터의 개체입니다.",
                      audio_path=audio_file, word_timings=wt, audio_duration=4.0,
                      display_narration="SCP-049는 키 1.9m의 개체입니다.")]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    path = Path(out["scenes"][0]["subtitle_path"])
    assert path.exists()
    assert path.suffix == ".ass"
    text = path.read_text(encoding="utf-8")
    assert "SCP-049" in text
    assert "에스시피" not in text
    assert "\\k" not in text


async def test_subtitle_node_uses_word_timings_not_aligner(monkeypatch, tmp_path, audio_file):
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    wt = _timings(["격리", "절차", "시작"])
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=wt,
                      display_narration="격리 절차 시작")]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out.get("error") is None
    assert len(fake.calls) == 0
    assert out["scenes"][0]["subtitle_path"]


async def test_subtitle_node_calls_aligner_when_no_timings(monkeypatch, tmp_path, audio_file):
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    scenes = [_scene(1, "격리 절차", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out.get("error") is None
    assert len(fake.calls) == 1
    assert fake.calls[0] == (audio_file, "격리 절차")


async def test_subtitle_node_aligner_fallback_emits_static_ass(monkeypatch, tmp_path, audio_file):
    """No word_timings -> whisperx segments, still static .ass (no \\k). [AC:7]"""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(
        subtitle, "_get_aligner",
        lambda s: _FakeAligner(segments=[{"start_sec": 0.0, "end_sec": 1.5, "text": "격리 절차 시작"}]),
    )

    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    path = Path(out["scenes"][0]["subtitle_path"])
    text = path.read_text(encoding="utf-8")
    assert path.suffix == ".ass"
    assert "\\k" not in text
    assert "격리 절차 시작" in text.replace("\\N", " ")


async def test_subtitle_node_old_checkpoint_without_display_narration_renders_spoken(monkeypatch, tmp_path, audio_file):
    """Old checkpoint scene has no display_narration key at all -> spoken text, no error. [AC:7]"""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    wt = _timings(["격리", "절차", "시작"])
    scene = _scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=wt)
    assert "display_narration" not in scene
    out = await subtitle_node(_state([scene]))

    assert out.get("error") is None
    path = Path(out["scenes"][0]["subtitle_path"])
    text = path.read_text(encoding="utf-8")
    assert "격리" in text.replace("\\N", " ")


async def test_subtitle_node_updates_subtitle_path(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [
        _scene(1, "narration one", audio_path=audio_file),
        _scene(2, "narration two", audio_path=audio_file),
    ]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    for sc in out["scenes"]:
        assert sc["subtitle_path"] and Path(sc["subtitle_path"]).exists()


async def test_subtitle_node_scenes_in_order(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    # Intentionally out of order
    scenes = [_scene(2, "two", audio_path=audio_file), _scene(1, "one", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    nums = [s["scene_num"] for s in out["scenes"]]
    assert nums == [1, 2]
    assert out["scenes"][0]["subtitle_path"].endswith("scene_001.ass")
    assert out["scenes"][1]["subtitle_path"].endswith("scene_002.ass")


async def test_subtitle_node_input_not_mutated(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    state = _state([_scene(1, "hello", audio_path=audio_file)])
    snapshot = json.loads(json.dumps(state))
    await subtitle_node(state)
    assert state == snapshot  # AD-4 purity


async def test_subtitle_node_preserves_upstream_fields(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    shot = {"shot_id": "S001", "sentence_indices": [0], "image_prompt": "p",
            "negative_prompt": "n", "camera_angle": None, "camera_movement": None, "image_path": None}
    scenes = [_scene(1, "hello", audio_path=audio_file, word_timings=[])]
    scenes[0]["shots"] = [shot]
    out = await subtitle_node(_state(scenes))

    assert out["scenes"][0]["shots"] == [shot]
    assert out["scenes"][0]["narration"] == "hello"


# ── subtitle_node: error paths ────────────────────────────────────────────────


async def test_subtitle_node_missing_audio_path(monkeypatch, tmp_path):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test", audio_path=None)]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out["error"]
    assert "stage=subtitle" in out["error"]
    assert "run-001" in out["error"]
    assert "scenes" not in out or not out.get("scenes")


async def test_subtitle_node_audio_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test", audio_path="/nonexistent/audio.wav")]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]


async def test_subtitle_node_empty_narration(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "narration" in out["error"]


async def test_subtitle_node_bad_aligner_config(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path, aligner="bad_aligner"))

    scenes = [_scene(1, "test", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "Unsupported" in out["error"] or "bad_aligner" in out["error"]


async def test_subtitle_node_non_ko_content_language_fails_fast(monkeypatch, tmp_path, audio_file):
    """A retried/resumed subtitle stage must fail on its own, independent of scenario_node."""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path, content_language="en"))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "content_language" in out["error"]


async def test_subtitle_node_aligner_returns_no_segments(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner(segments=[]))

    scenes = [_scene(1, "test narration", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "no subtitle cues" in out["error"]


async def test_subtitle_node_aligner_exception(monkeypatch, tmp_path, audio_file):
    class _BoomAligner:
        async def align(self, audio_path, transcript):
            raise RuntimeError("aligner crashed")

    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _BoomAligner())

    scenes = [_scene(1, "test", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "aligner crashed" in out["error"]


# ── observability ─────────────────────────────────────────────────────────────


async def test_trace_receives_metrics(monkeypatch, tmp_path, audio_file):
    captured = {}
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: captured.update(kw))

    await subtitle_node(_state([_scene(1, "hello", audio_path=audio_file)]))

    assert captured["run_id"] == "run-001"
    assert captured["scene_count"] == 1
    assert isinstance(captured["latency_ms"], int)
    assert captured.get("error") is None


async def test_trace_captures_error_on_failure(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [_scene(1, "test", audio_path=None)]
    await subtitle_node(_state(scenes))
    assert captured.get("error") is not None


def test_record_trace_is_non_fatal(monkeypatch):
    monkeypatch.setattr(
        subtitle, "get_client",
        lambda: (_ for _ in ()).throw(RuntimeError("langfuse down"))
    )
    subtitle._record_trace(run_id="r", scene_count=1, latency_ms=10)


# ── layering guard ────────────────────────────────────────────────────────────


def test_no_db_api_service_imports():
    """AD-1: subtitle.py must not import db, api, or services layers."""
    import yt_flow.pipeline.nodes.subtitle as mod
    import sys
    for name in ("yt_flow.db", "yt_flow.api", "yt_flow.services"):
        assert name not in sys.modules or mod.__name__ != name, (
            f"subtitle module must not depend on {name}"
        )
    # Check source imports directly
    source = Path(mod.__file__).read_text()
    for forbidden in ("from yt_flow.db", "from yt_flow.api", "from yt_flow.services",
                      "import yt_flow.db", "import yt_flow.api", "import yt_flow.services"):
        assert forbidden not in source, f"subtitle.py must not import {forbidden}"
