"""Unit tests for src/yt_flow/pipeline/nodes/subtitle.py (Story 1.8, rewritten
Story 5.18, always-on WhisperX alignment Story 11.4).

No live WhisperX / Langfuse: settings and the aligner are monkeypatched.
Tests cover the dual-track sentence-cue renderer (sentence_cues, wrap_cue_text,
format_ass), reconcile_word_timings, the always-align + provisional-fallback
node flow, word_timings write-back, error handling, and purity. No GPU, no
network, no model downloads required.
"""

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.subtitle as subtitle
from yt_flow.pipeline.nodes.scenario_chain import split_sentences
from yt_flow.pipeline.nodes.subtitle import (
    PLAY_RES_X,
    PLAY_RES_Y,
    SUBTITLE_FONT_FAMILY,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_MARGIN_V,
    SUBTITLE_OUTLINE_WIDTH,
    _get_aligner,
    format_ass,
    reconcile_word_timings,
    sentence_cues,
    subtitle_node,
    wrap_cue_text,
)


# ── Fakes / helpers ───────────────────────────────────────────────────────────


def _settings_ns(tmp_path, aligner="whisperx", content_language="ko", qwen_tts_mock=False):
    return SimpleNamespace(
        aligner=aligner,
        aligner_device="cpu",
        workspace_path=str(tmp_path),
        content_language=content_language,
        qwen_tts_mock=qwen_tts_mock,
    )


class _FakeAligner:
    """Returns raw whisperx-style word_segments (Story 11.4 aligner contract).

    Default (no explicit word_segments): synthesizes a 1:1 mapping from the
    transcript at 0.5s per word, so reconcile succeeds like real whisperx would.
    """

    def __init__(self, word_segments: list[dict] | None = None):
        self._segs = word_segments
        self.calls: list[tuple[str, str]] = []

    async def align(self, audio_path: str, transcript: str) -> list[dict]:
        self.calls.append((audio_path, transcript))
        if self._segs is not None:
            return self._segs
        return [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
                for i, w in enumerate(transcript.split())]


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


# ── reconcile_word_timings (Story 11.4 AC:3) ──────────────────────────────────


def test_reconcile_happy_one_to_one():
    segs = [{"word": "격리", "start": 0.1, "end": 0.4},
            {"word": "절차", "start": 0.5, "end": 0.9}]
    out = reconcile_word_timings(segs, "격리 절차", 2.0)
    assert out == [
        {"word": "격리", "start_sec": 0.1, "end_sec": 0.4},
        {"word": "절차", "start_sec": 0.5, "end_sec": 0.9},
    ]


def test_reconcile_count_mismatch_returns_none():
    segs = [{"word": "격리", "start": 0.1, "end": 0.4}]
    assert reconcile_word_timings(segs, "격리 절차", 2.0) is None


def test_reconcile_empty_narration_returns_none():
    assert reconcile_word_timings([], "", 2.0) is None


def test_reconcile_zero_duration_returns_none():
    segs = [{"word": "격리", "start": 0.1, "end": 0.4}]
    assert reconcile_word_timings(segs, "격리", 0.0) is None


def test_reconcile_missing_middle_word_interpolates_between_neighbors():
    segs = [{"word": "하나", "start": 0.0, "end": 1.0},
            {"word": "둘"},  # whole-sentence-unalignable rare case
            {"word": "셋", "start": 2.0, "end": 3.0}]
    out = reconcile_word_timings(segs, "하나 둘 셋", 3.0)
    assert out[1]["start_sec"] == 1.0
    assert out[1]["end_sec"] == 2.0


def test_reconcile_missing_head_clamps_to_zero():
    segs = [{"word": "하나"}, {"word": "둘", "start": 1.0, "end": 2.0}]
    out = reconcile_word_timings(segs, "하나 둘", 2.0)
    assert out[0]["start_sec"] == 0.0
    assert out[0]["end_sec"] == 1.0


def test_reconcile_missing_tail_clamps_to_audio_duration():
    segs = [{"word": "하나", "start": 0.0, "end": 1.0}, {"word": "둘"}]
    out = reconcile_word_timings(segs, "하나 둘", 3.0)
    assert out[1] == {"word": "둘", "start_sec": 1.0, "end_sec": 3.0}


def test_reconcile_sanitizes_overlapping_input_to_monotonic():
    segs = [{"word": "하나", "start": 0.0, "end": 1.0},
            {"word": "둘", "start": 0.5, "end": 1.5}]  # overlaps previous
    out = reconcile_word_timings(segs, "하나 둘", 2.0)
    assert out[1]["start_sec"] >= out[0]["end_sec"]
    assert out[1]["end_sec"] > out[1]["start_sec"]


def test_reconcile_clamps_negative_start():
    segs = [{"word": "하나", "start": -0.3, "end": 0.5},
            {"word": "둘", "start": 0.5, "end": 1.0}]
    out = reconcile_word_timings(segs, "하나 둘", 2.0)
    assert out[0]["start_sec"] == 0.0


def test_reconcile_clamps_last_end_to_audio_duration():
    segs = [{"word": "하나", "start": 0.0, "end": 1.0},
            {"word": "둘", "start": 1.0, "end": 5.0}]
    out = reconcile_word_timings(segs, "하나 둘", 2.0)
    assert out[1]["end_sec"] == 2.0


def test_reconcile_degenerate_beyond_duration_returns_none():
    segs = [{"word": "하나", "start": 5.0, "end": 6.0},
            {"word": "둘", "start": 6.0, "end": 7.0}]
    assert reconcile_word_timings(segs, "하나 둘", 2.0) is None


def test_reconcile_output_never_triggers_apportion_degrade():
    """[AC:3] The whole point of the 1:1 invariant: reconciled output must NEVER
    trip sentence_windows/sentence_cues' count-mismatch degrade (apportion ≈
    uniform split), or Story 11.4 silently un-does itself."""
    narration = "첫 문장 이다. 둘째 문장 이다."
    segs = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
            for i, w in enumerate(narration.split())]
    out = reconcile_word_timings(segs, narration, 5.0)
    assert out is not None
    assert not subtitle._word_timings_mismatch(out, split_sentences(narration))


# ── WhisperXAligner (align-only, model cached — Story 11.4 AC:4) ──────────────


def test_whisperx_aligner_loads_align_model_once_and_skips_asr(monkeypatch):
    """Two _align_sync calls -> one load_align_model. The fake module has NO
    load_model/transcribe at all — the deleted ASR pass would AttributeError."""
    loads: list[str] = []
    align_calls: list[list[dict]] = []

    def load_align_model(language_code, device):
        loads.append(language_code)
        return "MODEL", "META"

    def align(segments, model, meta, audio, device):
        align_calls.append(segments)
        return {"word_segments": [{"word": "hi", "start": 0.0, "end": 0.5}]}

    fake_whisperx = SimpleNamespace(
        load_align_model=load_align_model,
        load_audio=lambda p: [0.0] * 32000,  # 2s @ 16kHz
        align=align,
    )
    monkeypatch.setitem(sys.modules, "whisperx", fake_whisperx)

    aligner = subtitle.WhisperXAligner("cpu", "ko")
    out1 = aligner._align_sync("x.wav", "hi")
    out2 = aligner._align_sync("x.wav", "hi")

    assert loads == ["ko"]  # loaded once, reused across scenes
    assert out1 == out2 == [{"word": "hi", "start": 0.0, "end": 0.5}]
    # alignment span ends at the real audio duration (len/16000), no ASR estimate
    assert align_calls[0][0]["end"] == 2.0


# ── _get_aligner ─────────────────────────────────────────────────────────────


def test_get_aligner_whisperx_returns_instance():
    s = SimpleNamespace(aligner="whisperx", aligner_device="cpu", content_language="ko")
    from yt_flow.pipeline.nodes.subtitle import WhisperXAligner
    aligner = _get_aligner(s)
    assert isinstance(aligner, WhisperXAligner)
    assert aligner._language == "ko"
    assert aligner._device == "cpu"


def test_get_aligner_unknown_raises_value_error():
    s = SimpleNamespace(aligner="fake_unknown", aligner_device="cpu")
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


async def test_subtitle_node_always_calls_aligner_even_with_timings(monkeypatch, tmp_path, audio_file):
    """Story 11.4 reversal of the old test_subtitle_node_uses_word_timings_not_aligner:
    the `if timings:` gate meant tts's always-present provisional timings suppressed
    WhisperX forever. New spec: ALWAYS align; provisional is only the fallback."""
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    wt = _timings(["격리", "절차", "시작"])
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=wt,
                      display_narration="격리 절차 시작")]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out.get("error") is None
    assert len(fake.calls) == 1
    assert fake.calls[0] == (audio_file, "격리 절차 시작")
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


async def test_subtitle_node_writes_back_aligned_timings(monkeypatch, tmp_path, audio_file):
    """[AC:2] The aligned timings must land in the returned scene state — that's
    what video_node's 8.11 per-shot cuts and eval metrics consume."""
    fake = _FakeAligner(word_segments=[
        {"word": "격리", "start": 0.1, "end": 0.4},
        {"word": "절차", "start": 0.6, "end": 0.9},
        {"word": "시작", "start": 1.2, "end": 1.8},
    ])
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    provisional = _timings(["격리", "절차", "시작"])  # uniform split from tts
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=provisional)]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    got = out["scenes"][0]["word_timings"]
    assert [t["start_sec"] for t in got] == [0.1, 0.6, 1.2]
    assert [t["end_sec"] for t in got] == [0.4, 0.9, 1.8]


async def test_subtitle_node_aligner_exception_falls_back_to_provisional(monkeypatch, tmp_path, audio_file, caplog):
    """[AC:1] Alignment failure must NEVER fail the stage — WARNING + provisional."""
    class _BoomAligner:
        async def align(self, audio_path, transcript):
            raise RuntimeError("aligner crashed")

    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _BoomAligner())

    provisional = _timings(["격리", "절차", "시작"])
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=provisional)]
    with caplog.at_level(logging.WARNING):
        out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    assert out["scenes"][0]["word_timings"] == provisional  # write-back on fallback too
    assert out["scenes"][0]["subtitle_path"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("scene 1" in m and "aligner crashed" in m for m in warnings)


async def test_subtitle_node_reconcile_mismatch_falls_back_with_warning(monkeypatch, tmp_path, audio_file, caplog):
    """[AC:1] reconcile None (count mismatch) is the same silent-degrade risk —
    must fall back with a WARNING naming the scene."""
    fake = _FakeAligner(word_segments=[{"word": "hi", "start": 0.0, "end": 0.5}])  # 1 seg vs 3 words
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    provisional = _timings(["격리", "절차", "시작"])
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=provisional)]
    with caplog.at_level(logging.WARNING):
        out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    assert out["scenes"][0]["word_timings"] == provisional
    assert any("scene 1" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


async def test_subtitle_node_fallback_still_renders_display_text(monkeypatch, tmp_path, audio_file):
    """[AC:1] The old segment-level fallback (spoken transcript, no display mapping)
    is gone: even the fallback goes through sentence_cues with display text."""
    class _BoomAligner:
        async def align(self, audio_path, transcript):
            raise RuntimeError("boom")

    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _BoomAligner())

    wt = _timings(["에스시피", "공사", "구는", "개체입니다."], duration=4.0)
    scenes = [_scene(1, "에스시피 공사 구는 개체입니다.", audio_path=audio_file,
                      word_timings=wt, audio_duration=4.0,
                      display_narration="SCP-049는 개체입니다.")]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    text = Path(out["scenes"][0]["subtitle_path"]).read_text(encoding="utf-8")
    assert "SCP-049" in text
    assert "에스시피" not in text


async def test_subtitle_node_mock_tts_skips_alignment(monkeypatch, tmp_path, audio_file, caplog):
    """[AC:8] qwen_tts_mock WAVs are silent — alignment is meaningless and must not
    trigger a 1.2GB model download in mock e2e runs. INFO once, provisional path."""
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path, qwen_tts_mock=True))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    wt1, wt2 = _timings(["하나", "둘"]), _timings(["셋", "넷"])
    scenes = [_scene(1, "하나 둘", audio_path=audio_file, word_timings=wt1),
              _scene(2, "셋 넷", audio_path=audio_file, word_timings=wt2)]
    with caplog.at_level(logging.INFO):
        out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    assert len(fake.calls) == 0
    assert out["scenes"][0]["word_timings"] == wt1
    infos = [r for r in caplog.records if "qwen_tts_mock" in r.getMessage()]
    assert len(infos) == 1  # logged once, not per scene


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
    """Alignment yields nothing AND no provisional timings exist -> the one
    pre-existing permitted failure: zero cues."""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner(word_segments=[]))

    scenes = [_scene(1, "test narration", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "no subtitle cues" in out["error"]


async def test_subtitle_node_aligner_exception_without_provisional_fails_on_empty_cues(monkeypatch, tmp_path, audio_file):
    """Story 11.4: an aligner crash no longer propagates — but with no provisional
    timings either, the stage still fails on the pre-existing zero-cues guard."""
    class _BoomAligner:
        async def align(self, audio_path, transcript):
            raise RuntimeError("aligner crashed")

    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _BoomAligner())

    scenes = [_scene(1, "test", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "no subtitle cues" in out["error"]


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
    assert captured["alignment"] == {"whisperx": 1, "fallback": 0}  # [AC:8, §21]
    assert captured.get("error") is None


async def test_trace_alignment_counts_mixed_aligned_and_fallback(monkeypatch, tmp_path, audio_file):
    """[AC:8] The trace alignment block must count BOTH outcomes — degradation
    to provisional timings has to be visible at the gate, not silent (§21)."""
    class _FlakyAligner(_FakeAligner):
        async def align(self, audio_path, transcript):
            if "폭발" in transcript:
                raise RuntimeError("boom")
            return await super().align(audio_path, transcript)

    captured = {}
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FlakyAligner())
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [_scene(1, "격리 절차", audio_path=audio_file),
              _scene(2, "폭발 발생", audio_path=audio_file, word_timings=_timings(["폭발", "발생"]))]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    assert captured["alignment"] == {"whisperx": 1, "fallback": 1}


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


# ── Story 13.1: WhisperX fallback reaches the gate, not just the log ─────────


class _RaisingAligner:
    async def align(self, audio_path: str, transcript: str) -> list[dict]:
        raise RuntimeError("whisperx model unavailable")


async def test_real_alignment_fallback_warns_per_scene(monkeypatch, tmp_path, audio_file):
    """Story 11.4 made this visible in logs and traces; 13.1 puts it where the
    operator decides. The subtitles are still written — a warning is not a failure."""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _RaisingAligner())

    scenes = [_scene(1, "하나 둘", audio_path=audio_file, word_timings=_timings(["하나", "둘"])),
              _scene(2, "셋 넷", audio_path=audio_file, word_timings=_timings(["셋", "넷"]))]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    assert all(sc["subtitle_path"] for sc in out["scenes"])
    warnings = out["run_warnings"]
    assert [w["code"] for w in warnings] == ["subtitle_alignment_fallback"] * 2
    assert [w["context"]["scene_num"] for w in warnings] == [1, 2]
    assert all(w["stage"] == "subtitle" for w in warnings)
    assert warnings[0]["context"]["detail"] == "RuntimeError: whisperx model unavailable"


async def test_successful_alignment_is_warning_free(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "하나 둘", audio_path=audio_file, word_timings=_timings(["하나", "둘"]))]
    out = await subtitle_node(_state(scenes))
    assert out["run_warnings"] == []


async def test_mock_tts_bypass_is_warning_free(monkeypatch, tmp_path, audio_file):
    """AC2: the explicit qwen_tts_mock bypass is intentional, not a degradation."""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path, qwen_tts_mock=True))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "하나 둘", audio_path=audio_file, word_timings=_timings(["하나", "둘"]))]
    out = await subtitle_node(_state(scenes))
    assert out["run_warnings"] == []


async def test_alignment_warning_merges_with_prior_stage_history(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _RaisingAligner())

    prior = {"code": "stock_plate_missing", "stage": "image", "message": "이전",
             "context": {"scene_num": 1, "shot_id": "S001"}}
    scenes = [_scene(1, "하나 둘", audio_path=audio_file, word_timings=_timings(["하나", "둘"]))]
    out = await subtitle_node({**_state(scenes), "run_warnings": [prior]})
    assert out["run_warnings"][0] == prior
    assert out["run_warnings"][1]["code"] == "subtitle_alignment_fallback"


async def test_the_error_path_keeps_the_warnings_earlier_scenes_earned(monkeypatch, tmp_path, audio_file):
    """`warnings` is declared outside the try for the same reason image_node's and
    video_node's are: scene 2 blowing up must not erase scene 1's fallback."""
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _RaisingAligner())

    scenes = [
        _scene(1, "하나 둘", audio_path=audio_file, word_timings=_timings(["하나", "둘"])),
        _scene(2, "", audio_path=audio_file, word_timings=[]),  # empty narration → raises
    ]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert [w["context"]["scene_num"] for w in out["run_warnings"]] == [1]
