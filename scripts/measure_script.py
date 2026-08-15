"""Measure a finished run's narration script — length, pacing, density, source use.

Story 12.6 Task 0. Jay's verdict on run ``e5ed4b3a`` was "대본이 너무 짧고 스토리텔링
전개가 부족하다", and neither half had an instrument: AC6 (원문 소진율) and AC8
(baseline 대비 재측정) both name numbers nothing in the repo could produce. This is
that instrument, and it runs before any prompt or constant is touched so every later
claim is judged against a measurement rather than against the story's prose.

**Where the script lives.** In ``yt_flow.db``'s LangGraph ``checkpoints`` table, and
nowhere else, for both target runs — ``c6be1954`` has no workspace directory left,
and ``e5ed4b3a``'s ``scenario/scene_00N.txt`` files are hand-edits from the
narration-edit endpoint rather than pipeline output. So this reads the checkpoint,
via stdlib ``sqlite3`` opened **read-only** (that DB is the only surviving copy of
both runs) plus the checkpointer's own ``JsonPlusSerializer`` — guessing at the BLOB
encoding is how you silently measure the wrong bytes.

Deterministic metrics never touch the network. ``--coverage`` adds exactly ONE LLM
call (``scenario._call_gemini``, the seam the pipeline itself uses) and degrades to
``"coverage": null`` with a printed reason when no key is configured — a missing API
key must never cost you the word counts.

    uv run python scripts/measure_script.py --run e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889
    uv run python scripts/measure_script.py --run <after> --baseline <before> --coverage
    uv run python scripts/measure_script.py --run <after> --scenes-json <dump> \
        --durations-json <seconds>   # WPM for a run that never reached the graph

JSON goes to stdout, the human table to stderr, so ``> report.json`` still shows you
the table while it writes the machine copy.
"""

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402

from yt_flow.config import Settings  # noqa: E402

# 어절 = whitespace-delimited Korean word cluster. The same split the retention
# contract's `word_budget` is denominated in (`structure.md`: "목표 어절 수(공백 기준)"),
# so a measured count and a declared budget are directly comparable.
_EOJEOL = re.compile(r"\S+")
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

_COVERAGE_PROMPT = """다음은 SCP 원문(사실 자료)과, 그 원문으로 만든 영상 나레이션 대본입니다.

원문에서 **독립적으로 확인 가능한 사실 문장**을 모두 뽑아낸 뒤, 각 사실이 대본에
실제로 전달되었는지 판정하세요. 표현이 달라도 내용이 전달되었으면 "used"입니다.
분위기·감각 묘사로만 스쳐가고 사실 내용이 없으면 "dropped"입니다.

원문에 없는 것을 사실로 추가하지 마세요. 원문에 있는 것만 세세요.

## SCP 원문
{scp_text}

## 나레이션 대본
{script}

## 출력
JSON만 출력하세요. 코드펜스도, 설명 문장도 붙이지 마세요.

{{"facts": [{{"fact": "원문에서 뽑은 사실 문장", "status": "used" 또는 "dropped",
  "where": "used면 그 사실이 전달된 씬 번호, dropped면 null"}}]}}
"""


def _load_channel_values(db_path: str, run_id: str) -> tuple[str, dict]:
    """(resolved thread_id, channel_values) of the NEWEST checkpoint for ``run_id``.

    ``run_id`` may be a prefix — every artifact directory and memory note in this
    project names runs by their first 8 hex characters. An ambiguous prefix is an
    error, never a silent pick.

    Ordering is lexical on ``checkpoint_id`` because LangGraph writes UUID6s, which
    sort in creation order by construction; there is no timestamp column to use
    instead.
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        # sqlite says "unable to open database file" for both a missing path and an
        # unreadable one, and names neither. The path IS the diagnosis here — the
        # default comes from Settings.db_path and is resolved against the cwd.
        raise SystemExit(f"cannot open database {db_path!r}: {exc} (pass --db)") from exc
    with con:
        threads = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ?", (run_id + "%",)
            )
        ]
        if not threads:
            raise SystemExit(f"run {run_id}: no LangGraph checkpoint in {db_path}")
        if len(threads) > 1:
            raise SystemExit(f"run {run_id}: prefix matches {len(threads)} threads: {sorted(threads)}")
        row = con.execute(
            "SELECT type, checkpoint, metadata FROM checkpoints WHERE thread_id = ? "
            "ORDER BY checkpoint_id DESC LIMIT 1",
            (threads[0],),
        ).fetchone()
    _warn_if_hand_edited(run_id, row[2])
    checkpoint = JsonPlusSerializer().loads_typed((row[0], row[1]))
    return threads[0], checkpoint.get("channel_values") or {}


def _warn_if_hand_edited(run_id: str, metadata: bytes | None) -> None:
    """Say so when the newest checkpoint was written by ``update_state``, not the graph.

    LangGraph stamps each row's metadata with a ``source``: ``loop`` for a node's
    own output, ``update`` for an out-of-band ``update_state`` — which is what the
    narration-edit endpoint uses. Run ``e5ed4b3a`` genuinely carries ``update``
    rows (steps 44 and 47; its newest row is ``loop``, which is why the committed
    numbers are pipeline output). Without this, the next run whose LAST write is a
    human edit measures hand-written text and reports it as pipeline output.

    Never fatal, and never a reason to pick an older row: the newest state IS the
    run's state. The operator just has to know which one they are reading.
    """
    try:
        source = JsonPlusSerializer().loads_typed(("json", metadata)).get("source")
    except Exception as exc:  # noqa: BLE001 — a metadata read must not cost the metrics
        print(f"[{run_id[:8]}] checkpoint metadata unreadable ({type(exc).__name__}) — "
              "cannot tell pipeline output from a manual edit", file=sys.stderr)
        return
    if source == "update":
        print(
            f"[{run_id[:8]}] WARNING: the newest checkpoint has metadata source='update' — it was "
            "written by update_state (the narration-edit endpoint), not by the graph. These numbers "
            "measure the EDITED script, not what the pipeline produced.",
            file=sys.stderr,
        )


def _load_scenes_json(path: str, durations_json: str | None = None) -> tuple[str, dict]:
    """Same ``(id, values)`` shape from a JSON dump instead of a checkpoint.

    A scenario-stage-only run has no checkpoint — ``scenario_node`` is callable
    without the graph (`eval_prompts._run_scenario` is the precedent) — but AC8 has
    to compare it against the baseline on the SAME metrics. So the loader varies and
    the metric code does not.

    ``durations_json`` fills in the one metric a scenario-stage run cannot carry: WPM
    needs spoken seconds, and speech is a property of the voice, not of the script. It
    is written by ``12-6-live-validation/run_after_tts.py``, which drives ``tts_node``
    over the same scenes, so the durations arrive here already measured off the WAVs.
    """
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if durations_json:
        measured = json.loads(Path(durations_json).read_text(encoding="utf-8"))
        by_scene = {int(num): sec for num, sec in measured["audio_duration_sec"].items()}
        for scene in values.get("scenes") or []:
            # Absent → stays None, so a partial TTS run reports WPM null rather than a
            # rate computed over some of the scenes and all of the words.
            scene["audio_duration"] = by_scene.get(scene.get("scene_num"))
    return values.get("run_id") or Path(path).stem, values


def measure(
    run_id: str, db_path: str, *, scenes_json: str | None = None, durations_json: str | None = None
) -> dict:
    """Deterministic metrics for one run. No network, no filesystem beyond the source."""
    thread_id, values = (
        _load_scenes_json(scenes_json, durations_json)
        if scenes_json
        else _load_channel_values(db_path, run_id)
    )
    scenes = values.get("scenes")
    # Filtered to mappings before anything calls `.get`: a malformed dump whose
    # `scenes` holds strings should give the message below, not an AttributeError
    # from inside the row loop.
    scenes = [scene for scene in scenes if isinstance(scene, dict)] if isinstance(scenes, list) else None
    if not scenes:
        raise SystemExit(f"run {run_id}: source has no 'scenes' — run incomplete or malformed")

    rows = []
    for scene in scenes:
        # `narration` is what TTS spoke; `display_narration` is the pre-normalization
        # writing text the subtitles render. They differ (number spell-out), so both
        # are reported rather than one being quietly chosen as "the" script.
        words = len(_EOJEOL.findall(scene.get("narration") or ""))
        budget = scene.get("word_budget")
        rows.append({
            "scene_num": scene.get("scene_num"),
            "words": words,
            "display_words": len(_EOJEOL.findall(scene.get("display_narration") or "")),
            "audio_duration_sec": scene.get("audio_duration"),
            # Declared budgets are NOT persisted: `structure` is a scenario-node local,
            # and SceneState carries no `word_budget`. Present only if a future state
            # shape starts carrying it — measured as null, never as zero.
            "word_budget": budget if type(budget) is int else None,
            "budget_delta": None if type(budget) is not int else words - budget,
        })
    total_budget = sum(row["word_budget"] or 0 for row in rows)

    total = sum(row["words"] for row in rows)
    counts = [row["words"] for row in rows]
    durations = [row["audio_duration_sec"] for row in rows if isinstance(row["audio_duration_sec"], (int, float))]
    # EVERY scene or none: WPM divides all the words by the seconds, so a partial
    # TTS run (durations for 5 scenes of 8) counts 8 scenes' 어절 against 5 scenes'
    # seconds and overstates the rate by ~60% — a number that looks like a
    # measurement and is not one. The seconds themselves are still reported, so a
    # partial run is visibly partial rather than silently absent.
    audio_sec = round(sum(durations), 2) if durations else None
    complete_audio = len(durations) == len(rows) and audio_sec is not None
    for row in rows:
        row["share_pct"] = round(100 * row["words"] / total, 2) if total else None

    return {
        "run_id": thread_id,
        "scp_id": values.get("scp_id"),
        "scene_count": len(rows),
        "total_words": total,
        "total_display_words": sum(row["display_words"] for row in rows),
        # null, not 0.0: a run measured before TTS has no density, and a zero here
        # would read as "speaks infinitely slowly" in any comparison table.
        "audio_duration_sec": audio_sec,
        "audio_duration_min": round(audio_sec / 60, 2) if audio_sec else None,
        "audio_scene_coverage": f"{len(durations)}/{len(rows)}",
        "wpm": round(total / (audio_sec / 60), 1) if complete_audio else None,
        # The flatness number. 1.0 = every scene the same length, which is exactly
        # what run e5ed4b3a produced and what `format_guide.md:113` already forbade.
        "spread": round(max(counts) / min(counts), 2) if min(counts) else None,
        "max_scene_share_pct": round(100 * max(counts) / total, 2) if total else None,
        "opening_share_pct": round(100 * counts[0] / total, 2) if total else None,
        "closing_share_pct": round(100 * counts[-1] / total, 2) if total else None,
        "declared_budgets_present": any(row["word_budget"] is not None for row in rows),
        "declared_total_word_budget": total_budget or None,
        "declared_budget_spread": (
            round(max(b) / min(b), 2)
            if (b := [row["word_budget"] for row in rows if row["word_budget"]]) and len(b) == len(rows)
            else None
        ),
        "scenes": rows,
        "scp_text_chars": len(values.get("scp_text") or ""),
        "coverage": None,
    }


async def _coverage(values_scp_text: str, script: str, s: Settings) -> dict:
    from yt_flow.pipeline.nodes import scenario

    content, _usage, _finish = await scenario._call_gemini(
        _COVERAGE_PROMPT.format(scp_text=values_scp_text, script=script), s
    )
    # Gemini's OpenAI-compatible layer fences JSON even when told not to
    # (`gotcha_provider-swap-inherits-json-mode-assumption`); strip before parsing.
    data = json.loads(_FENCE.sub("", content.strip()))
    facts = [f for f in data.get("facts") or [] if isinstance(f, dict)]
    dropped = [f for f in facts if str(f.get("status")).lower() != "used"]
    return {
        "fact_count": len(facts),
        "used_count": len(facts) - len(dropped),
        "dropped_count": len(dropped),
        "used_pct": round(100 * (len(facts) - len(dropped)) / len(facts), 1) if facts else None,
        "dropped": [str(f.get("fact") or "") for f in dropped],
        "facts": facts,
    }


def add_coverage(report: dict, db_path: str, s: Settings, *, scenes_json: str | None = None) -> None:
    """One LLM call, in place. Never raises out — a coverage failure leaves the
    deterministic half of the report intact and says why on stderr."""
    _thread, values = (
        _load_scenes_json(scenes_json) if scenes_json else _load_channel_values(db_path, report["run_id"])
    )
    if not s.gemini_api_key:
        print(
            f"[{report['run_id'][:8]}] coverage skipped: YTFLOW_GEMINI_API_KEY is not configured "
            "— deterministic metrics above are unaffected",
            file=sys.stderr,
        )
        return
    scp_text = values.get("scp_text") or ""
    if not scp_text.strip():
        # 소진율 is "how much of the SOURCE reached the script". With no source there
        # is no denominator, and the judge would answer from its own SCP knowledge —
        # a percentage that measures the model, not the run.
        print(
            f"[{report['run_id'][:8]}] coverage skipped: this source carries no `scp_text` "
            "— 소진율 has no denominator without the article",
            file=sys.stderr,
        )
        return
    script = "\n".join(
        f"[씬 {scene.get('scene_num')}] {scene.get('narration') or ''}" for scene in values["scenes"]
    )
    try:
        report["coverage"] = asyncio.run(_coverage(scp_text, script, s))
    except Exception as exc:  # noqa: BLE001 — one call, any failure is the same answer
        print(f"[{report['run_id'][:8]}] coverage failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def _table(reports: list[dict]) -> str:
    head = ["metric"] + [r["run_id"][:8] for r in reports]
    keys = [
        ("scp_id", "SCP"), ("scene_count", "씬"), ("total_words", "총 어절"),
        ("audio_duration_min", "나레이션 분"), ("wpm", "WPM"), ("spread", "분량 spread(max/min)"),
        ("max_scene_share_pct", "최대 씬 비중 %"), ("opening_share_pct", "오프닝 비중 %"),
        ("closing_share_pct", "마지막 비중 %"),
        ("declared_total_word_budget", "선언 총 예산"), ("declared_budget_spread", "선언 예산 spread"),
        ("scp_text_chars", "원문 자수"),
    ]
    lines = [" | ".join(head), "-" * 60]
    for key, label in keys:
        lines.append(" | ".join([label] + [str(r.get(key)) for r in reports]))
    for report in reports:
        shares = " ".join(
            f"{row['words']}({row['share_pct']}%)"
            + ("" if row["budget_delta"] is None else f"[예산{row['word_budget']} {row['budget_delta']:+d}]")
            for row in report["scenes"]
        )
        lines.append(f"{report['run_id'][:8]} 씬별 어절(비중): {shares}")
        if not report["declared_budgets_present"]:
            lines.append(f"{report['run_id'][:8]} declared word_budget: 체크포인트에 없음 (delta 측정 불가)")
        if report["wpm"] is None and report["audio_duration_sec"] is not None:
            lines.append(
                f"{report['run_id'][:8]} WPM: 씬 {report['audio_scene_coverage']} 만 합성됨 — "
                "전 씬이 아니면 속도가 과대평가되므로 null"
            )
        cov = report.get("coverage")
        if cov:
            lines.append(
                f"{report['run_id'][:8]} 원문 소진율: {cov['used_count']}/{cov['fact_count']} "
                f"({cov['used_pct']}%) · 버려진 사실 {cov['dropped_count']}건"
            )
            lines.extend(f"    ✗ {fact}" for fact in cov["dropped"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="run id (or unambiguous prefix) to measure")
    parser.add_argument("--baseline", help="second run id, reported beside --run")
    parser.add_argument("--coverage", action="store_true", help="add one LLM call measuring source-fact usage")
    parser.add_argument("--db", help="path to yt_flow.db (default: Settings.db_path)")
    parser.add_argument(
        "--scenes-json",
        help="read --run's scenes from this JSON dump instead of the checkpoint "
             "(a scenario-stage-only run never reaches a checkpoint)",
    )
    parser.add_argument(
        "--durations-json",
        help="per-scene spoken seconds for --scenes-json (run_after_tts.py's output); "
             "without it a scenario-stage-only run has no WPM",
    )
    args = parser.parse_args()
    if args.durations_json and not args.scenes_json:
        # `_load_scenes_json` is the only reader of the durations file, so alone this
        # flag did nothing at all — and the run it was meant to add WPM to reported
        # `wpm: null` as if no audio had been measured.
        parser.error("--durations-json only applies to --scenes-json (the checkpoint carries its own audio_duration)")

    s = Settings()
    db_path = args.db or s.db_path
    reports = [
        measure(args.run, db_path, scenes_json=args.scenes_json, durations_json=args.durations_json)
    ]
    if args.baseline:
        reports.append(measure(args.baseline, db_path))
    if args.coverage:
        add_coverage(reports[0], db_path, s, scenes_json=args.scenes_json)
        for report in reports[1:]:
            add_coverage(report, db_path, s)

    print(_table(reports), file=sys.stderr)
    print(json.dumps({"runs": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
