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
