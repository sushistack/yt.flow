"""Tests for scripts/score_shot_narration.py (Story 10.4 image/narration axis).

Fully offline: the DashScope call is faked at the ``httpx`` seam, exactly as
``tests/test_score_composites.py`` does it. What is asserted here is the decision
rule and the *shape of the measurement* — above all that the blind call is issued
without the narration, since a blind call that leaks the sentence turns the whole
axis into confirmation and every number produced by it into noise.
"""

import asyncio
import importlib.util
import json
import subprocess
import types

import httpx
import pytest

BLIND = {"place": "a tiled examination room", "event": "a bag knocked open", "readable": True}
MATCH = {"match": 4, "evidence": "the scattered instruments", "missing": ""}
NARRATION = "손이 닿는 순간, 그는 죽었습니다. 디 계급 인원이 격리실로 들어옵니다. 두 손이 맞닿았습니다."


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", "scripts/score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def settings(monkeypatch):
    from yt_flow.config import Settings

    monkeypatch.setenv("YTFLOW_CHARACTER_VISION_API_KEY", "k")
    return Settings()  # type: ignore[call-arg]


def _fake_httpx(module, monkeypatch, replies):
    """Queue of reply strings (or Exceptions to raise); returns the sent payloads."""
    payloads: list[dict] = []
    queue = list(replies)

    class FakeResponse:
        def __init__(self, reply):
            self._reply = reply

        def raise_for_status(self):
            if isinstance(self._reply, Exception):
                raise self._reply

        def json(self):
            return {"choices": [{"message": {"content": self._reply}}]}

    class FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, headers=None, json=None):
            payloads.append(json)
            return FakeResponse(queue.pop(0) if queue else '{"readable": true, "match": 3}')

    monkeypatch.setattr(module, "httpx", types.SimpleNamespace(
        AsyncClient=FakeClient, Timeout=httpx.Timeout, HTTPStatusError=httpx.HTTPStatusError,
    ))
    return payloads


def _frame(tmp_path, name="scene_001_S00100.png"):
    frame = tmp_path / name
    frame.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 2048)  # over the 1KB placeholder floor
    return frame


def _state(tmp_path, *, indices=(0,), shots=1, cast=()):
    return {"scenes": [{
        "scene_num": 1, "narration": NARRATION,
        "shots": [{
            "shot_id": f"S001{i:02d}", "sentence_indices": list(indices),
            "image_prompt": "a room", "cast": list(cast),
            "image_path": str(_frame(tmp_path, f"scene_001_S001{i:02d}.png")),
        } for i in range(shots)],
    }]}


def _score(script, settings, state, **kw):
    return asyncio.run(script.score_run(settings, state, "RUN", **kw))


# ── the anchoring control ────────────────────────────────────────────────────


def test_the_blind_call_carries_no_narration_and_runs_first(script, settings, monkeypatch, tmp_path):
    """The axis's whole claim to being a measurement: the frame testifies before the
    sentence exists. A blind request body containing any narration text voids it."""
    payloads = _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)])

    rows = _score(script, settings, _state(tmp_path))

    blind_body, match_body = json.dumps(payloads[0], ensure_ascii=False), json.dumps(payloads[1], ensure_ascii=False)
    for sentence in script.split_sentences(NARRATION):
        assert sentence not in blind_body
    assert "손이 닿는 순간" not in blind_body
    assert "손이 닿는 순간" in match_body  # the match call DOES get it — that is the difference
    assert rows[0]["status"] == "scored"
    assert (rows[0]["readable"], rows[0]["match_score"]) == (True, 4)


# ── sentence resolution ──────────────────────────────────────────────────────


def test_a_multi_sentence_shot_joins_its_sentences_in_order_and_scores_once(
        script, settings, monkeypatch, tmp_path):
    """``build_scenes`` merges an empty-prompt transition sentence into the previous
    shot, so ``sentence_indices`` can cover more than one sentence."""
    payloads = _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)])

    rows = _score(script, settings, _state(tmp_path, indices=(2, 0)))

    assert rows[0]["sentences"] == ["손이 닿는 순간, 그는 죽었습니다.", "두 손이 맞닿았습니다."]
    assert len(payloads) == 2  # one blind + one match, not one call per sentence
    sent = payloads[1]["messages"][0]["content"][0]["text"]
    assert sent.index("손이 닿는 순간") < sent.index("두 손이 맞닿았습니다")


# ── frames that cannot be judged ─────────────────────────────────────────────


@pytest.mark.parametrize("size", [0, 512])
def test_a_missing_or_undersized_frame_is_skipped_not_scored(
        script, settings, monkeypatch, tmp_path, size):
    payloads = _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)])
    state = _state(tmp_path)
    frame = tmp_path / "tiny.png"
    frame.write_bytes(b"x" * size)
    state["scenes"][0]["shots"][0]["image_path"] = str(frame) if size else str(tmp_path / "gone.png")

    rows = _score(script, settings, state)

    assert rows[0]["status"] == "skipped" and rows[0]["reason"]
    assert payloads == []  # never billed for a frame that does not exist
    assert script.summarize(rows)["skipped"] == 1


def test_a_skipped_row_makes_the_script_exit_non_zero(script, settings, monkeypatch, tmp_path):
    """The axis must never report a clean sweep it did not measure."""
    _fake_httpx(script, monkeypatch, [])
    state = _state(tmp_path)
    state["scenes"][0]["shots"][0]["image_path"] = str(tmp_path / "gone.png")
    monkeypatch.setattr(script, "_load_state", _load_state_returning(state))
    args = types.SimpleNamespace(run="RUN", json=None, reps=1, frames="images", limit=None)

    assert asyncio.run(script.run(args)) == 1


def _load_state_returning(state):
    async def fake(run_id, db_path):
        return state
    return fake


# ── reply parsing and score validation ───────────────────────────────────────


def test_prose_wrapped_json_is_parsed(script):
    assert script._parse('Sure!\n```json\n{"legible": 4}\n```\n') == {"legible": 4}


@pytest.mark.parametrize("reply", ["no json here", "{not json}", "[1,2]"])
def test_unparsable_replies_raise(script, reply):
    with pytest.raises(Exception):
        script._parse(reply)


@pytest.mark.parametrize("bad", [None, "high", True, 0, 6, 3.5, {}])
def test_a_score_that_is_not_an_int_in_range_is_rejected(script, bad):
    """``True`` must not pass as 1 — bool is an int subclass — and 6 is not a 5."""
    with pytest.raises(ValueError):
        script._int_score({"match": bad}, "match")


@pytest.mark.parametrize("bad", [None, "yes", "true", 1, 0, 4, {}, []])
def test_readable_that_is_not_a_boolean_is_rejected_never_coerced(script, bad):
    """Iteration 2's instrument change is only worth anything if the boolean is a real
    boolean: coercing ``"yes"`` or ``1`` would manufacture the exact readings this
    axis exists to count."""
    with pytest.raises(ValueError):
        script._bool_field({"readable": bad}, "readable")


@pytest.mark.parametrize("value", [True, False])
def test_a_real_boolean_readable_passes_through(script, value):
    assert script._bool_field({"readable": value}, "readable") is value


def test_a_reply_whose_score_is_out_of_range_marks_the_row_errored(
        script, settings, monkeypatch, tmp_path):
    _fake_httpx(script, monkeypatch, ['{"readable": 9}', '{"readable": 9}'])  # call + its one retry

    rows = _score(script, settings, _state(tmp_path))

    assert rows[0]["status"] == "error"
    # the count AND the cause: "0 usable of 1" alone would not say what killed the row
    assert "readable=9 is not a boolean" in rows[0]["reason"]
    assert script.summarize(rows)["errored"] == 1


def test_one_prose_reply_is_retried_before_the_row_is_lost(script, settings, monkeypatch, tmp_path):
    payloads = _fake_httpx(script, monkeypatch, ["sorry, I cannot", json.dumps(BLIND), json.dumps(MATCH)])

    rows = _score(script, settings, _state(tmp_path))

    assert rows[0]["status"] == "scored" and rows[0]["readable"] is True
    assert len(payloads) == 3


# ── the decision rule ────────────────────────────────────────────────────────


def test_the_hook_is_scene_ones_first_shot_and_only_that_shot(script, settings, monkeypatch, tmp_path):
    _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)] * 2)

    rows = _score(script, settings, _state(tmp_path, shots=2))

    assert [r["hook"] for r in rows] == [True, False]


def test_the_hook_match_threshold_is_stricter_and_readable_binds_every_shot(script):
    """match=3 passes an ordinary shot and fails the hook — that difference is the only
    reason the hook is flagged at all. ``readable`` has no hook variant: it is a
    boolean, so "the hook must be readable" and "every shot must be readable" are the
    same clause."""
    assert script.fail_reason({"hook": False, "readable": True, "match_score": 3}) is None
    assert script.fail_reason({"hook": True, "readable": True, "match_score": 3}) == "match=3<4"
    assert script.fail_reason({"hook": True, "readable": True, "match_score": 4}) is None
    assert script.fail_reason({"hook": True, "readable": False, "match_score": 4}) == "readable=False"
    assert script.fail_reason({"hook": False, "readable": False, "match_score": 2}) == "readable=False, match=2<3"


def test_unreadable_and_mismatched_are_counted_as_different_defects(script):
    """Finding 2 ("무슨 배경인지 모르겠다") and finding 4 ("나레이션과 안 맞는다") are
    different failures; one merged count would hide which one a change fixed."""
    rows = [
        {"status": "scored", "hook": False, "readable": False, "match_score": 4, "fail_reason": "x",
         "shot_id": "a", "scene_num": 1, "sentence_indices": [0]},
        {"status": "scored", "hook": False, "readable": True, "match_score": 1, "fail_reason": "x",
         "shot_id": "b", "scene_num": 1, "sentence_indices": [1]},
        {"status": "scored", "hook": False, "readable": False, "match_score": 1, "fail_reason": "x",
         "shot_id": "c", "scene_num": 1, "sentence_indices": [2]},
    ]
    summary = script.summarize(rows)
    assert (summary["unreadable_only"], summary["mismatch_only"], summary["both"]) == (1, 1, 1)
    assert summary["unreadable"] == 2
    assert summary["worst"][0]["shot_id"] in ("b", "c")


def test_the_summary_reports_the_covers_shot_count_and_density(script):
    """A leg that merged sentences away renders fewer frames; a mean that moved must
    never be read without the shot count that produced it."""
    rows = [
        {"status": "scored", "hook": False, "readable": True, "match_score": 4, "fail_reason": None,
         "shot_id": "a", "scene_num": 1, "sentence_indices": [0, 1, 2]},
        {"status": "scored", "hook": False, "readable": True, "match_score": 4, "fail_reason": None,
         "shot_id": "b", "scene_num": 1, "sentence_indices": [3]},
    ]
    summary = script.summarize(rows)
    assert summary["n_shots"] == 2 and summary["sentences_per_shot"] == 2.0


# ── repetitions ──────────────────────────────────────────────────────────────


def test_reps_take_the_median_and_survive_one_dropped_rep(script, settings, monkeypatch, tmp_path):
    """3 blind reps, the middle one unparsable: the row keeps the majority of the two
    survivors and every sample, including the dead one, stays in the record."""
    _fake_httpx(script, monkeypatch, [
        '{"place": "p", "event": "e", "readable": false}',
        "garbage", "garbage",                                    # rep 2 + its retry
        '{"place": "p", "event": "e", "readable": true}',
        '{"match": 3, "evidence": "x", "missing": ""}',
        '{"match": 5, "evidence": "x", "missing": ""}',
        '{"match": 3, "evidence": "x", "missing": ""}',
    ])

    rows = _score(script, settings, _state(tmp_path), reps=3)

    assert rows[0]["status"] == "scored"
    # an even split breaks to False: a frame earns "readable" only when most looks agree
    assert rows[0]["readable"] is False
    assert rows[0]["match_score"] == 3  # median of [3, 5, 3]
    assert len(rows[0]["blind_samples"]) == 3 and "error" in rows[0]["blind_samples"][1]


def test_reps_take_the_majority_of_the_boolean(script, settings, monkeypatch, tmp_path):
    """2 of 3 say readable → readable, and the losing sample stays in the record."""
    _fake_httpx(script, monkeypatch, [
        '{"place": "p", "event": "e", "readable": true}',
        '{"place": "p", "event": "unclear", "readable": false}',
        '{"place": "p", "event": "e", "readable": true}',
        '{"match": 3, "evidence": "x", "missing": ""}',
    ] + ['{"match": 3, "evidence": "x", "missing": ""}'] * 2)

    rows = _score(script, settings, _state(tmp_path), reps=3)

    assert rows[0]["readable"] is True
    assert [s.get("readable") for s in rows[0]["blind_samples"]] == [True, False, True]


def test_fewer_than_two_usable_reps_is_an_error_not_a_lucky_sample(
        script, settings, monkeypatch, tmp_path):
    _fake_httpx(script, monkeypatch, [
        '{"place": "p", "event": "e", "readable": true}',
        "garbage", "garbage", "garbage", "garbage",
    ])

    rows = _score(script, settings, _state(tmp_path), reps=3)

    assert rows[0]["status"] == "error" and "only 1 usable" in rows[0]["reason"]


# ── the composited cross-check ───────────────────────────────────────────────


def test_frames_shots_reads_the_clip_midpoint_and_skips_a_missing_clip(
        script, settings, monkeypatch, tmp_path):
    """Midpoint, not t=0 — compositing and the parallax move develop over the shot."""
    seen: list[float] = []

    def fake_run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return types.SimpleNamespace(stdout="6.0\n", returncode=0)
        seen.append(float(cmd[cmd.index("-ss") + 1]))
        open(cmd[-1], "wb").write(b"\x89PNG" + b"y" * 2048)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = script.extract_mid_frame(tmp_path / "clip.mp4", tmp_path / "mid.png")
    assert out is not None and seen == [3.0]

    _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)])
    rows = _score(script, settings, _state(tmp_path), frames="shots")
    assert rows[0]["status"] == "skipped" and "no composited clip" in rows[0]["reason"]
    assert rows[0]["frame_source"] == "shots"


# ── the judge prompts themselves ─────────────────────────────────────────────


# ── the sentence pairing (--pair-by sentence) ────────────────────────────────


def _cover_state(cover):
    """One scene of 3 sentences whose shots cover them per ``cover`` = list of index lists."""
    return {"scenes": [{
        "scene_num": 1, "narration": NARRATION,
        "shots": [{"shot_id": f"S001{i:02d}", "sentence_indices": list(idxs)}
                  for i, idxs in enumerate(cover)],
    }]}


def _row(shot_id, indices, match, readable=True, status="scored", hook=False):
    return {"scene_num": 1, "shot_id": shot_id, "sentence_indices": list(indices),
            "status": status, "match_score": match, "readable": readable, "hook": hook}


def test_a_shot_covering_three_sentences_scores_all_three_of_them(script):
    """The merge case: one frame owns sentences 1–3, so all three carry its verdict —
    that is what makes two legs with different shot counts comparable at all."""
    state = _cover_state([[0, 1, 2]])
    rows = [_row("S00100", [0, 1, 2], 4)]

    paired = script.pair_by_sentence(state, rows)

    assert [r["sentence_index"] for r in paired] == [0, 1, 2]
    assert [r["match"] for r in paired] == [4, 4, 4]
    assert all(r["shot_ids"] == ["S00100"] for r in paired)
    assert script.summarize_sentences(paired)["mean_match"] == 4.0


def test_two_shots_splitting_one_sentence_average_into_that_sentence(script):
    """The split case: the viewer hears sentence 2 across both frames, so the sentence
    takes their mean — ``max`` would reward splitting and ``min`` would punish it."""
    state = _cover_state([[0], [1], [1], [2]])
    rows = [_row("S00100", [0], 3), _row("S00101", [1], 5),
            _row("S00102", [1], 2), _row("S00103", [2], 4)]

    paired = script.pair_by_sentence(state, rows)

    assert [r["match"] for r in paired] == [3, 3.5, 4]
    assert paired[1]["shot_ids"] == ["S00101", "S00102"] and paired[1]["n_covering"] == 2
    assert script.summarize_sentences(paired)["split_sentences"] == 1


def test_a_split_sentence_is_unreadable_if_either_of_its_frames_is(script):
    state = _cover_state([[0], [1], [1], [2]])
    rows = [_row("S00100", [0], 4), _row("S00101", [1], 4, readable=True),
            _row("S00102", [1], 4, readable=False), _row("S00103", [2], 4)]

    paired = script.pair_by_sentence(state, rows)

    assert [r["readable"] for r in paired] == [True, False, True]
    assert script.summarize_sentences(paired)["unreadable"] == 1


def test_an_uncovered_sentence_is_recorded_not_averaged_away(script):
    """A sentence no shot claims must show up as a hole in the pairing rather than
    quietly shrinking the denominator of the leg that dropped it."""
    state = _cover_state([[0], [2]])
    rows = [_row("S00100", [0], 5), _row("S00101", [2], 1)]

    paired = script.pair_by_sentence(state, rows)
    summary = script.summarize_sentences(paired)

    assert paired[1]["status"] == "uncovered" and "no shot covers" in paired[1]["reason"]
    assert (summary["sentences"], summary["scored"], summary["uncovered"]) == (3, 2, 1)
    assert summary["mean_match"] == 3.0  # the two that were measured, and only those


def test_a_skipped_frames_sentence_is_unscored_not_uncovered(script):
    state = _cover_state([[0], [1], [2]])
    rows = [_row("S00100", [0], 4), _row("S00101", [1], 0, status="skipped"),
            _row("S00102", [2], 4)]
    rows[1]["reason"] = "no frame at x.png"

    paired = script.pair_by_sentence(state, rows)
    summary = script.summarize_sentences(paired)

    assert paired[1]["status"] == "skipped" and paired[1]["reason"] == "no frame at x.png"
    assert (summary["uncovered"], summary["unscored"]) == (0, 1)


def test_pair_by_sentence_is_opt_in_on_the_report(script, settings, monkeypatch, tmp_path):
    _fake_httpx(script, monkeypatch, [json.dumps(BLIND), json.dumps(MATCH)])
    state = _state(tmp_path)
    rows = _score(script, settings, state)

    shot_only = script.report(rows, settings, "RUN", types.SimpleNamespace(frames="images", reps=1))
    paired = script.report(rows, settings, "RUN",
                           types.SimpleNamespace(frames="images", reps=1, pair_by="sentence"), state)

    assert "sentence_rows" not in shot_only
    assert len(paired["sentence_rows"]) == len(script.split_sentences(NARRATION))
    assert paired["sentence_summary"]["scored"] == 1  # only sentence 1 has a shot


def test_both_prompts_say_absent_people_are_not_a_defect(script):
    """Without this, every cast-bearing shot fails for the wrong reason and the whole
    measurement is void — the plates are unpeopled by design (Epic 8)."""
    for prompt in (script.BLIND_PROMPT, script.MATCH_PROMPT):
        assert "composited" in prompt
        assert "never a mismatch" in prompt or "NEVER a defect" in prompt


# ── DSG instrument (Story 13.2) ──────────────────────────────────────────────
#
# The confound removal is the whole point of this instrument, and it rests on exactly
# one thing: a proposition whose subject is a body must leave the fraction AND must not
# be able to invalidate scenery. Both were caught failing on live data during the smoke
# run (see 13-2-live-validation/README.md §3), so both are pinned here.


def _prop(pid, kind, question="q?", parent=None, about_body=None):
    return {"id": pid, "kind": kind, "question": question, "parent": parent,
            "about_body": kind == "person" if about_body is None else about_body}


def test_propositions_field_accepts_a_well_formed_graph(script):
    props = [_prop("p1", "place"), _prop("p2", "object", parent="p1"),
             _prop("p3", "person")]
    assert script._propositions_field({"propositions": props}) == props


@pytest.mark.parametrize("props,why", [
    ("nope", "not a list"),
    ([], "empty"),
    ([{"kind": "place", "question": "q?", "about_body": False}], "missing id"),
    ([_prop("p1", "place"), _prop("p1", "object")], "duplicate id"),
    ([_prop("p1", "scenery")], "kind not in the closed set"),
    ([_prop("p1", "place", question="  ")], "blank question"),
    ([_prop("p1", "state", parent="p9")], "parent is not an earlier proposition"),
    ([_prop("p2", "state", parent="p2")], "self-referencing parent"),
])
def test_propositions_field_rejects_malformed_graphs(script, props, why):
    with pytest.raises(ValueError):
        script._propositions_field({"propositions": props})
    assert why  # label only, keeps the parametrize table readable


@pytest.mark.parametrize("about_body", [None, "true", 1, 0])
def test_propositions_field_requires_a_real_boolean_about_body(script, about_body):
    """The one field the exclusion depends on. `"true"` and `1` are truthy but fail
    `is True`, so an unvalidated non-bool puts a body straight back in the denominator —
    and a MISSING field is worse still: it degrades `_is_person` to kind-only and reads
    as perfect compliance in `dsg_label_disagreements`."""
    prop = {"id": "p1", "kind": "object", "question": "Is a hand visible?", "parent": None}
    if about_body is not None:
        prop["about_body"] = about_body
    with pytest.raises(ValueError, match="about_body"):
        script._propositions_field({"propositions": [prop]})


def test_propositions_field_caps_a_runaway_decomposition(script):
    """The prompt asks for 3-7 and nothing else enforces it. Every proposition past the
    first costs one paid image call per frame."""
    ok = [_prop(f"p{i}", "place") for i in range(script._MAX_PROPOSITIONS)]
    assert len(script._propositions_field({"propositions": ok})) == script._MAX_PROPOSITIONS
    too_many = [_prop(f"p{i}", "place") for i in range(script._MAX_PROPOSITIONS + 1)]
    with pytest.raises(ValueError, match="not a decomposition"):
        script._propositions_field({"propositions": too_many})


def test_is_person_takes_the_union_of_kind_and_about_body(script):
    """The live decomposer mislabelled `hand`/`robe`/`silhouette` as object/state on 3 of
    3 smoke rows. Either signal alone is enough to exclude: a stray exclusion costs one
    proposition of denominator, a missed one re-imports the confound."""
    assert script._is_person(_prop("p1", "person", about_body=True))
    assert script._is_person(_prop("p1", "object", about_body=True))    # mislabelled kind
    assert script._is_person({"kind": "person"})                        # about_body absent
    assert not script._is_person(_prop("p1", "place", about_body=False))


def test_person_propositions_are_never_asked_and_never_invalidate_scenery(script, settings, monkeypatch):
    """Both halves of the structural fix, in the shape that broke live: the plate has no
    body, so asking about one can only produce a false negative — and under the first
    implementation that false negative propagated to the child scenery proposition
    ("is the cell door open") and silently docked a real measurement."""
    props = [_prop("p1", "person", "Is the person moving?"),
             _prop("p2", "state", "Is the cell door open?", parent="p1")]
    payloads = _fake_httpx(script, monkeypatch, [json.dumps({"answer": True})])

    answers = asyncio.run(script._answer_propositions(settings, props, b"png"))

    # Exactly one call, and it is the scenery question — the person was never asked.
    assert len(payloads) == 1
    assert "cell door" in json.dumps(payloads[0], ensure_ascii=False)
    assert answers[0]["excluded"] is True and answers[0]["answer"] is None
    assert answers[1]["answer"] is True and answers[1]["invalidated"] is False


def test_a_no_parent_invalidates_its_child_without_asking(script, settings, monkeypatch):
    """DSG's advantage over TIFA: "there is no bed" then "the bed is disturbed: yes" is
    the inconsistency independent questions let through."""
    props = [_prop("p1", "object", "Is there a bed?", about_body=False),
             _prop("p2", "state", "Is the bed disturbed?", parent="p1", about_body=False)]
    payloads = _fake_httpx(script, monkeypatch, [json.dumps({"answer": False})])

    answers = asyncio.run(script._answer_propositions(settings, props, b"png"))

    assert len(payloads) == 1                      # the child was never asked
    assert answers[1]["invalidated"] is True and answers[1]["answer"] is False


def test_dsg_score_excludes_person_propositions_from_both_halves(script):
    answers = [
        {"id": "p1", "kind": "place", "about_body": False, "answer": True},
        {"id": "p2", "kind": "state", "about_body": False, "answer": False},
        {"id": "p3", "kind": "person", "about_body": True, "answer": None},
    ]
    score, scored_n, excluded, invalidated, disagreements = script.dsg_score(answers)
    assert (score, scored_n, excluded, invalidated, disagreements) == (0.5, 2, 1, 0, 0)


def test_dsg_score_is_none_not_zero_when_every_proposition_is_a_body(script):
    """"Unscorable" and "the frame shows none of it" are different facts and must not be
    averaged together — a sentence purely about a person gives a plate nothing to check."""
    answers = [{"id": f"p{i}", "kind": "person", "about_body": True, "answer": None}
               for i in range(3)]
    score, scored_n, excluded, _, _ = script.dsg_score(answers)
    assert score is None and scored_n == 0 and excluded == 3


def test_dsg_score_counts_label_disagreements_without_letting_them_change_the_score(script):
    answers = [
        {"id": "p1", "kind": "object", "about_body": True, "answer": True},   # disagrees
        {"id": "p2", "kind": "place", "about_body": False, "answer": True},
    ]
    score, scored_n, excluded, _, disagreements = script.dsg_score(answers)
    assert disagreements == 1
    assert (score, scored_n, excluded) == (1.0, 1, 1)   # the union excluded p1


def test_summarize_dsg_surfaces_qa_errors_and_unscorable_separately(script):
    rows = [
        {"dsg_score": 0.5, "dsg_scored_n": 2, "dsg_excluded_person_n": 1,
         "dsg_invalidated_n": 0, "dsg_label_disagreements": 0, "dsg_qa_errors_n": 1},
        {"dsg_score": None, "dsg_scored_n": 0, "dsg_excluded_person_n": 3,
         "dsg_invalidated_n": 0, "dsg_label_disagreements": 0, "dsg_qa_errors_n": 0},
        {"dsg_error": "RuntimeError: boom"},
    ]
    out = script.summarize_dsg(rows)
    assert out["dsg_rows"] == 3 and out["dsg_scorable"] == 1
    assert out["dsg_errored"] == 1 and out["dsg_unscorable"] == 1
    assert out["mean_dsg"] == 0.5                      # only the scorable row
    # A transient API failure lowers mean_dsg; without this count that is
    # indistinguishable from the frame genuinely not showing the thing.
    assert out["dsg_qa_errors_total"] == 1
    assert out["dsg_excluded_person_total"] == 4 and out["dsg_rows_with_person_prop"] == 2
