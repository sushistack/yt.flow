"""PipelineState fixtures for A/B evaluation tests (Story 4.2).

Deterministic, hand-built states — no pipeline run required. Metrics computed
from these are asserted exactly in test_eval_service.py, so edit with care.
"""

from yt_flow.domain.state import PipelineState, SceneState, WordTiming


def _word(word: str, start: float, end: float) -> WordTiming:
    return {"word": word, "start_sec": start, "end_sec": end}


def _scene(num: int, narration: str, timings, audio_duration: float) -> SceneState:
    return {
        "scene_num": num,
        "narration": narration,
        "shots": [],
        "audio_path": f"scene_{num:03d}.wav",
        "audio_duration": audio_duration,
        "word_timings": timings,
        "subtitle_path": f"scene_{num:03d}.srt",
    }


def state_a(run_id: str = "run-a", scp_text: str = "SCP-173 is a concrete statue.") -> PipelineState:
    return {
        "run_id": run_id,
        "scp_text": scp_text,
        "scenes": [
            # gaps: |1.2-1.0| = 0.2
            _scene(1, "Containment begins.",
                   [_word("a", 0.0, 1.0), _word("b", 1.2, 2.0)], audio_duration=3.0),
            # gaps: |1.5-1.0| = 0.5  → scene mean sync = mean(0.2, 0.5) = 0.35
            _scene(2, "The incident unfolds.",
                   [_word("c", 0.0, 1.0), _word("d", 1.5, 2.5)], audio_duration=5.0),
        ],
        "video_path": "a.mp4",
        "current_stage": "video",
        "gate_states": {},
        "prompt_variant": "A",
        "error": None,
    }


def state_b(run_id: str = "run-b", scp_text: str = "SCP-173 is a concrete statue.") -> PipelineState:
    return {
        "run_id": run_id,
        "scp_text": scp_text,
        "scenes": [
            _scene(1, "Statue contained.",
                   [_word("a", 0.0, 1.0), _word("b", 1.1, 2.0)], audio_duration=4.0),  # gap 0.1
            _scene(2, "Agents respond.",
                   [_word("c", 0.0, 1.0), _word("d", 1.1, 2.0)], audio_duration=4.0),  # gap 0.1
            _scene(3, "Breach resolved.",
                   [_word("e", 0.0, 1.0), _word("f", 1.1, 2.0)], audio_duration=4.0),  # gap 0.1
        ],
        "video_path": "b.mp4",
        "current_stage": "video",
        "gate_states": {},
        "prompt_variant": "B",
        "error": None,
    }
