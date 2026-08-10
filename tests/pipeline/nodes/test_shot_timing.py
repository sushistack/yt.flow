"""Unit tests for src/yt_flow/pipeline/nodes/shot_timing.py (Story 8.11).

Pure functions, no ffmpeg/aligner — covers normal derivation, gap-attachment,
merge-below-minimum (incl. first-shot-merges-forward), first/last stretch,
unclaimed sentences, and the no-usable-timings degrade path.
"""

import logging

from yt_flow.pipeline.nodes.shot_timing import ShotClip, plan_shot_clips


def _shot(shot_id: str, sentence_indices: list[int], image_path: str | None = "img.png") -> dict:
    return {
        "shot_id": shot_id,
        "sentence_indices": sentence_indices,
        "image_prompt": "p",
        "negative_prompt": "n",
        "camera_angle": None,
        "camera_movement": None,
        "image_path": image_path,
        "cast": [],
        "location_key": None,
    }


def _timings(words: list[str], duration: float) -> list[dict]:
    step = duration / len(words)
    return [{"word": w, "start_sec": round(i * step, 3), "end_sec": round((i + 1) * step, 3)}
            for i, w in enumerate(words)]


# ── normal derivation ─────────────────────────────────────────────────────────


def test_plan_shot_clips_normal_three_shots():
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."  # 3 sentences, 9 words
    wt = _timings(narration.replace(".", "").split(), duration=9.0)  # 1.0s/word
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    assert [c.shot["shot_id"] for c in plan] == ["S1", "S2", "S3"]
    assert plan[0].start == 0.0 and plan[0].end == 3.0
    assert plan[1].start == 3.0 and plan[1].end == 6.0
    assert plan[2].start == 6.0 and plan[2].end == 9.0


# ── gap attachment ────────────────────────────────────────────────────────────


def test_plan_shot_clips_multi_sentence_shot_uses_first_and_last_window():
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=9.0)
    # S1 covers sentences 0 and 1, S2 covers sentence 2 alone.
    shots = [_shot("S1", [0, 1]), _shot("S2", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    assert len(plan) == 2
    assert plan[0].start == 0.0 and plan[0].end == 6.0  # gap-attach: extends to S2's start
    assert plan[1].start == 6.0 and plan[1].end == 9.0


def test_plan_shot_clips_unclaimed_sentence_inherits_previous_shot():
    """Sentence index 1 isn't claimed by any shot — it must fall into shot 1's
    span (the preceding shot), not create a hole."""
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=9.0)
    shots = [_shot("S1", [0]), _shot("S2", [2])]  # sentence 1 unclaimed

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    assert len(plan) == 2
    assert plan[0].start == 0.0 and plan[0].end == 6.0  # absorbs the unclaimed middle sentence
    assert plan[1].start == 6.0 and plan[1].end == 9.0


# ── first/last stretch ────────────────────────────────────────────────────────


def test_plan_shot_clips_stretches_first_and_last_to_full_audio_duration():
    narration = "첫 문장 이다. 둘째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=6.0)
    shots = [_shot("S1", [0]), _shot("S2", [1])]

    # Real audio runs slightly longer than the last sentence window (e.g. trailing silence).
    plan = plan_shot_clips(shots, wt, narration, audio_duration=6.5, min_shot_clip_sec=0.0)

    assert plan[0].start == 0.0
    assert plan[-1].end == 6.5


# ── merge below minimum (incl. first-shot-merges-forward) ────────────────────


def test_plan_shot_clips_merges_short_clip_into_previous():
    narration = "첫 문장 이다. 짧다. 셋째 문장 이다."  # middle sentence ~0.33s span if evenly split
    wt = _timings(narration.replace(".", "").split(), duration=7.0)  # 7 words, 1.0s/word
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=7.0, min_shot_clip_sec=2.0)

    # S1: 0-3 (3 words=3s, kept). S2: 3-4 (1 word=1s < 2.0 → merges into S1). S3: 4-7 (3s, kept).
    assert [c.shot["shot_id"] for c in plan] == ["S1", "S3"]
    assert plan[0].start == 0.0 and plan[0].end == 4.0
    assert plan[1].start == 4.0 and plan[1].end == 7.0


def test_plan_shot_clips_first_shot_merges_forward():
    narration = "짧다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=7.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=7.0, min_shot_clip_sec=2.0)

    # S1: 0-1 (1 word=1s < 2.0, first shot) → merges FORWARD into S2.
    assert [c.shot["shot_id"] for c in plan] == ["S2", "S3"]
    assert plan[0].start == 0.0 and plan[0].end == 4.0
    assert plan[1].start == 4.0 and plan[1].end == 7.0


def test_plan_shot_clips_zero_min_disables_merging():
    narration = "첫 문장 이다. 짧다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=7.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=7.0, min_shot_clip_sec=0.0)

    assert [c.shot["shot_id"] for c in plan] == ["S1", "S2", "S3"]


# ── degrade: no usable timings ────────────────────────────────────────────────


def test_plan_shot_clips_empty_timings_falls_back_to_single_clip(caplog):
    shots = [_shot("S1", [0]), _shot("S2", [1])]
    with caplog.at_level(logging.WARNING):
        plan = plan_shot_clips(shots, [], "첫 문장. 둘째 문장.", audio_duration=4.0)

    assert len(plan) == 1
    assert plan[0].shot["shot_id"] == "S1"
    assert plan[0].start == 0.0 and plan[0].end == 4.0
    assert any("no usable sentence windows" in r.message for r in caplog.records)


def test_plan_shot_clips_empty_narration_falls_back_to_single_clip():
    shots = [_shot("S1", [0])]
    plan = plan_shot_clips(shots, _timings(["a"], 1.0), "", audio_duration=2.0)
    assert len(plan) == 1
    assert plan[0].end == 2.0


def test_plan_shot_clips_no_rendered_shots_returns_empty():
    shots = [_shot("S1", [0], image_path=None)]
    plan = plan_shot_clips(shots, _timings(["a"], 1.0), "문장.", audio_duration=1.0)
    assert plan == []


def test_plan_shot_clips_word_timings_mismatch_apportions_by_character_length():
    """AC:7 — mismatched word_timings count degrades to the same
    character-length apportioning sentence_cues uses, staying consistent."""
    narration = "첫 문장 이다. 둘째 문장 이다."
    wt = _timings(["a", "b", "c"], duration=3.0)  # only 3 timings, spoken has 6 words
    shots = [_shot("S1", [0]), _shot("S2", [1])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=3.0, min_shot_clip_sec=0.0)

    assert len(plan) == 2
    assert plan[0].start == 0.0
    assert plan[-1].end == 3.0
    prev_end = 0.0
    for c in plan:
        assert c.start >= prev_end - 1e-9
        assert c.end > c.start
        prev_end = c.end


def test_shot_clip_duration_property():
    assert ShotClip(_shot("S1", [0]), 1.0, 3.5).duration == 2.5


# ── unclaimable sentence_indices (review fix) ─────────────────────────────────


# ── Story 10.4: several shots may start on the same sentence (an ordered cover) ──


def test_plan_shot_clips_splits_one_sentence_between_two_shots():
    """Before 10.4 both shots got the identical window, the gap loop gave the first a
    duration of 0 and ``_merge_short_clips`` deleted it — a rendered frame silently
    never reached the video. The start (and only the start) now divides the sentence."""
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=9.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [1]), _shot("S4", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    assert [c.shot["shot_id"] for c in plan] == ["S1", "S2", "S3", "S4"]
    assert (plan[0].start, plan[0].end) == (0.0, 3.0)
    assert (plan[1].start, plan[1].end) == (3.0, 4.5)  # first half of sentence 2
    assert (plan[2].start, plan[2].end) == (4.5, 6.0)  # second half
    assert (plan[3].start, plan[3].end) == (6.0, 9.0)


def test_plan_shot_clips_three_way_split_divides_the_window_evenly_and_covers_it():
    narration = "첫 문장 이다. 둘째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=6.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [1]), _shot("S4", [1])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=6.0, min_shot_clip_sec=0.0)

    assert [round(c.start, 3) for c in plan] == [0.0, 3.0, 4.0, 5.0]
    assert plan[-1].end == 6.0
    assert all(c.duration > 0 for c in plan)  # nothing collapses to a zero-length clip


def test_plan_shot_clips_covers_the_scene_continuously_when_a_sentence_is_split():
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=9.0)
    shots = [_shot("S1", [0, 1]), _shot("S2", [2]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    assert plan[0].start == 0.0 and plan[-1].end == 9.0
    for earlier, later in zip(plan, plan[1:]):
        assert earlier.end == later.start  # no hole, no overlap


def test_plan_shot_clips_pre_cover_checkpoint_is_byte_identical():
    """The real check on the start-offset change: a checkpoint written before 10.4 has
    exactly one shot per sentence, so ``share_n == 1`` and the arithmetic must be the
    one that shipped — an old run has to keep rendering."""
    narration = "첫 문장 이다. 둘째 문장 이다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=9.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=9.0, min_shot_clip_sec=0.0)

    # the exact values pinned by test_plan_shot_clips_normal_three_shots at 3869f95
    assert [(c.start, c.end) for c in plan] == [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)]


def test_plan_shot_clips_split_clips_below_the_minimum_still_merge():
    """Splitting a short sentence produces short clips; ``_merge_short_clips`` is not
    bypassed, so the cut rhythm floor still holds."""
    narration = "첫 문장 이다. 짧다. 셋째 문장 이다."
    wt = _timings(narration.replace(".", "").split(), duration=7.0)
    shots = [_shot("S1", [0]), _shot("S2", [1]), _shot("S3", [1]), _shot("S4", [2])]

    plan = plan_shot_clips(shots, wt, narration, audio_duration=7.0, min_shot_clip_sec=2.0)

    assert [c.shot["shot_id"] for c in plan] == ["S1", "S4"]
    assert plan[0].start == 0.0 and plan[-1].end == 7.0


def test_plan_shot_clips_warns_and_drops_shot_with_out_of_range_indices(caplog):
    """A shot whose sentence_indices don't land in [0, n_sentences) must be
    dropped with a WARNING, not silently vanish from the render."""
    narration = "첫 문장 이다. 둘째 문장 이다."  # 2 sentences
    wt = _timings(narration.replace(".", "").split(), duration=6.0)
    shots = [_shot("S1", [0]), _shot("S2", [5])]  # S2's index is out of range

    with caplog.at_level(logging.WARNING):
        plan = plan_shot_clips(shots, wt, narration, audio_duration=6.0, min_shot_clip_sec=0.0)

    assert [c.shot["shot_id"] for c in plan] == ["S1"]
    assert any("S2" in r.message and "dropped from clip plan" in r.message for r in caplog.records)
