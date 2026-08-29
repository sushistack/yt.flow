"""Story 13.1 — the run-warning contract itself: catalog, shape, merge, dedupe.

These are the guards the rest of the story stands on. If ordering or identity drifts
here, every producer starts appending near-duplicates on retry and the gate list
becomes unreadable — which is the failure mode AC6 exists to prevent.
"""

import json
from typing import get_args

import pytest

from yt_flow.domain.state import RunWarningCode, StageName
from yt_flow.domain.warnings import (
    MAX_DETAIL_CHARS,
    MAX_SAMPLE_RECORDS,
    RUN_WARNING_CATALOG,
    cap_samples,
    make_warning,
    merge,
)


def test_catalog_covers_every_code_with_a_real_stage():
    assert set(RUN_WARNING_CATALOG) == set(get_args(RunWarningCode))
    for code, (stage, message) in RUN_WARNING_CATALOG.items():
        assert stage in get_args(StageName), code
        assert message.strip(), code


def test_make_warning_fills_stage_and_korean_copy_from_the_catalog():
    warning = make_warning("stock_plate_missing", scene_num=3, shot_id="S002", location_key="corridor")
    assert warning["code"] == "stock_plate_missing"
    assert warning["stage"] == "image"
    assert warning["message"] == RUN_WARNING_CATALOG["stock_plate_missing"][1]
    assert warning["context"] == {"scene_num": 3, "shot_id": "S002", "location_key": "corridor"}


def test_unknown_code_is_rejected_at_construction():
    with pytest.raises(KeyError):
        make_warning("not_a_real_code")  # type: ignore[arg-type]


def test_context_is_json_safe_and_bounded():
    class Exploding:
        def __str__(self) -> str:
            return "x" * 5000

    warning = make_warning(
        "cast_resolution_failed", scp_id="SCP-049", detail=Exploding(), pose_hint=None,
    )
    # No exception object, no unbounded provider body, no None-valued identifier.
    assert len(warning["context"]["detail"]) == MAX_DETAIL_CHARS
    assert "pose_hint" not in warning["context"]
    assert json.loads(json.dumps(warning)) == warning


def test_a_warning_with_no_context_omits_the_key():
    assert "context" not in make_warning("subtitle_alignment_fallback")


def test_merge_preserves_first_seen_order():
    a = make_warning("stock_plate_missing", scene_num=1, shot_id="A")
    b = make_warning("stock_plate_missing", scene_num=2, shot_id="B")
    c = make_warning("subtitle_alignment_fallback", scene_num=1)
    assert merge([a], [b, c]) == [a, b, c]
    assert merge(None, None) == []
    assert merge([], [c]) == [c]


def test_merge_deduplicates_by_code_stage_and_identifiers():
    first = make_warning("stock_plate_missing", scene_num=1, shot_id="A", location_key="corridor")
    again = make_warning("stock_plate_missing", scene_num=1, shot_id="A", location_key="corridor")
    assert merge([first], [again]) == [first]
    # A different shot is a different warning — dedupe must not swallow evidence.
    other = make_warning("stock_plate_missing", scene_num=1, shot_id="B", location_key="corridor")
    assert merge([first], [other]) == [first, other]


def test_identity_ignores_exception_text():
    """Two attempts at the same defect produce two different exception strings."""
    first = make_warning("cast_resolution_failed", scp_id="SCP-049", detail="TimeoutError: after 30s")
    retry = make_warning("cast_resolution_failed", scp_id="SCP-049", detail="ConnectError: refused")
    merged = merge([first], [retry])
    assert merged == [first]  # first detail wins; the run is not told about it twice


def test_merge_is_idempotent_over_repeated_runs():
    produced = [
        make_warning("stock_plate_missing", scene_num=1, shot_id="A"),
        make_warning("cast_card_fallback", scene_num=1, shot_id="A", card_key="STOCK-security"),
    ]
    once = merge([], produced)
    assert merge(once, produced) == once
    assert merge(merge(once, produced), produced) == once


@pytest.mark.parametrize("keys", [
    ("failed_count",), ("skipped_count",), ("total_count",),
    ("undecidable_streak", "undecidable_total"),
])
def test_identity_ignores_per_attempt_counters(keys):
    """AC1/AC6: identity is code + stage + identifying context, not a tally.

    A retry that degrades the same way with a different count must converge on the row
    already in the checkpoint instead of appending a near-identical second one.
    """
    first = make_warning("relight_failed", **dict.fromkeys(keys, 3))
    retry = make_warning("relight_failed", **dict.fromkeys(keys, 41))
    assert merge([first], [retry]) == [first]
    # The counts are still on the record the operator reads — only the identity ignores them.
    assert all(first["context"][key] == 3 for key in keys)


def test_cap_samples_bounds_named_rows_and_keeps_the_true_total():
    produced = [
        make_warning("cast_card_missing", scene_num=1, shot_id=f"S{i:03d}", card_key="STOCK-d-class")
        for i in range(40)
    ]
    capped = cap_samples(produced)

    assert capped[:MAX_SAMPLE_RECORDS] == produced[:MAX_SAMPLE_RECORDS]
    assert len(capped) == MAX_SAMPLE_RECORDS + 1
    assert capped[-1]["context"] == {"total_count": 40}
    # Under the cap nothing is added at all.
    assert cap_samples(produced[:MAX_SAMPLE_RECORDS]) == produced[:MAX_SAMPLE_RECORDS]


def test_cap_samples_counts_each_code_separately_and_respects_a_producer_rollup():
    plates = [make_warning("stock_plate_missing", shot_id=f"S{i}") for i in range(20)]
    subtitles = [make_warning("subtitle_alignment_fallback", scene_num=n) for n in range(3)]
    # `_relight_warnings` already samples at the source and rolls its own exact total up,
    # because the pairs it skipped were never materialised as rows to count here.
    relight = [
        *(make_warning("relight_failed", card_variant=f"v{i}") for i in range(MAX_SAMPLE_RECORDS)),
        make_warning("relight_failed", failed_count=900),
    ]
    capped = cap_samples([*plates, *subtitles, *relight])

    codes = [w["code"] for w in capped]
    assert codes.count("stock_plate_missing") == MAX_SAMPLE_RECORDS + 1
    assert codes.count("subtitle_alignment_fallback") == 3
    assert relight == [w for w in capped if w["code"] == "relight_failed"]  # left alone


def test_cap_samples_output_merges_to_itself_across_attempts():
    """The bounded list is deterministic, so a retry re-deriving it does not grow it."""
    produced = [make_warning("cast_card_missing", shot_id=f"S{i}") for i in range(30)]
    once = merge([], cap_samples(produced))
    assert merge(once, cap_samples(produced)) == once


# ── Story 14.2: the affordance code's own contract ──────────────────────────

def test_plate_affordance_unusable_is_an_image_stage_code():
    """The gate lives in image_node and the human gate that reviews the frame is
    image's, so the row must not file itself against video's (where the card would
    otherwise have been composited)."""
    stage, message = RUN_WARNING_CATALOG["plate_affordance_unusable"]
    assert stage == "image"
    # The copy has to be honest for EVERY reason the code carries, and it carries six:
    # `no_standing_room` (+ its `_earlier_run` twin) drops the cast, while
    # `detector_undecidable`, `detector_undecidable_run`, `vision_api_key_missing` and
    # `unjudged_earlier_run` all KEEP it. So the row may not state the destructive
    # outcome as fact — it states the condition and both outcomes conditionally.
    assert "설 자리" in message
    assert "뺐습니다" not in message  # no unconditional "the cast was removed"
    assert "판정하지 못한 샷은 배역을 그대로" in message


def test_the_two_affordance_reasons_are_capped_and_counted_separately():
    """"no standing room" (a card was deleted) and "the detector could not judge this"
    are of very different severity, and per-CODE capping would let the numerous one push
    the severe one into the aggregate — `gotcha_summary-from-a-capped-list-drops-the-
    severest-item`, which is why `_cap_key` is (code, reason)."""
    dropped = [make_warning("plate_affordance_unusable", scene_num=1, shot_id=f"S{i:03d}",
                            reason="no_standing_room")
               for i in range(MAX_SAMPLE_RECORDS + 3)]
    undecidable = [make_warning("plate_affordance_unusable", scene_num=1, shot_id=f"U{i:03d}",
                                reason="detector_undecidable")
                   for i in range(2)]
    capped = cap_samples([*dropped, *undecidable])

    reasons = [w["context"]["reason"] for w in capped if "shot_id" in w["context"]]
    assert reasons.count("no_standing_room") == MAX_SAMPLE_RECORDS
    assert reasons.count("detector_undecidable") == 2
    assert {"reason": "no_standing_room", "total_count": len(dropped)} in [
        w["context"] for w in capped]


def test_a_re_derived_affordance_row_merges_to_the_one_in_the_checkpoint():
    """A RETRY of the same pass re-derives the identical row and must converge on the
    checkpoint's, not append a second one — including the breaker row, whose tallies are
    per-attempt counters and therefore outside identity (AC1/AC6)."""
    shot = make_warning("plate_affordance_unusable", scene_num=1, shot_id="S001",
                        reason="no_standing_room", card_keys="SCP-049")
    assert merge([shot], [shot]) == [shot]
    breaker = make_warning("plate_affordance_unusable", reason="detector_undecidable_run",
                           undecidable_streak=3, undecidable_total=3)
    later = make_warning("plate_affordance_unusable", reason="detector_undecidable_run",
                         undecidable_streak=3, undecidable_total=6)
    assert merge([breaker], [later]) == [breaker]
    # A different shot is different evidence and must survive the merge.
    other = make_warning("plate_affordance_unusable", scene_num=1, shot_id="S002",
                         reason="no_standing_room", card_keys="SCP-049")
    assert merge([shot], [other]) == [shot, other]


def test_the_resume_row_is_a_second_row_by_design_not_a_convergence():
    """The RESUME path does not re-derive the same row: `image_node` files
    `no_standing_room` when it judges the frame and `no_standing_room_earlier_run` when it
    re-applies the verdict from the sidecar, and `reason` is inside `_identity`. So the two
    genuinely coexist — one row saying the gate dropped this card, one saying a later pass
    honoured that. Asserting convergence here would have been a test that never touched
    the resume path at all."""
    judged = make_warning("plate_affordance_unusable", scene_num=1, shot_id="S001",
                          reason="no_standing_room", card_keys="SCP-049")
    resumed = make_warning("plate_affordance_unusable", scene_num=1, shot_id="S001",
                           reason="no_standing_room_earlier_run", card_keys="SCP-049")
    assert merge([judged], [resumed]) == [judged, resumed]
    # And a THIRD resume adds nothing: the resumed row is stable across passes.
    assert merge([judged, resumed], [resumed]) == [judged, resumed]


# ── Story 14.1: stock_plate_unfit ────────────────────────────────────────────


def test_stock_plate_unfit_is_registered_and_owned_by_the_image_stage():
    warning = make_warning("stock_plate_unfit", scene_num=1, shot_id="S001",
                           location_key="corridor", reason="no_viewpoint_match")
    assert warning["stage"] == "image"
    # Reason-neutral copy: the fallback is generation, not a lost shot, and one sentence
    # rides seven reasons. "맞는 승인 배경이 없어" would be FALSE for the commonest of them
    # — `unservable_framing` (7/31 shots, permanent by design) fires on keys whose
    # approved backgrounds are perfectly good; the shot is simply a close-up.
    assert "생성" in warning["message"]
    assert "맞는" not in warning["message"]


@pytest.mark.parametrize("reason", [
    "unknown_framing", "unservable_framing", "no_metadata", "partial_metadata",
    "no_viewpoint_match", "plate_shows_person", "no_standing_room",
])
def test_each_documented_reason_caps_separately(reason):
    """`cap_samples` keys on (code, reason), so a numerous cheap reason cannot push a rare
    severe one out of the 12 named rows (`gotcha_summary-from-a-capped-list-drops-the-severest-item`)."""
    flood = [make_warning("stock_plate_unfit", shot_id=f"S{i:03d}", reason="__flood__")
             for i in range(20)]
    rare = make_warning("stock_plate_unfit", shot_id="S999", reason=reason)
    kept = cap_samples([*flood, rare])
    assert rare in kept
