# Story 14.4 live validation — the people-free guard as a shipping default

Date: 2026-08-22 · no GPU, no ComfyUI, no re-run of any pipeline stage. The only
network traffic is 8 DashScope `qwen-vl-plus` calls against PNGs already on disk — 4 in
the first pass, 4 in the review pass, of which 7 were timed (the 8th was spent
confirming the `notes` log line and its timing was not retained). See the cost table.

Story 14.4 flips `background_person_guard_attempts` from `0` to `2` in `config.py`
and deletes the `.env` pin that was carrying it. That flip is a cost/benefit claim,
so both sides of it are measured here rather than asserted, and both re-derive with
one command each (`gotcha_a-measurement-without-its-sample-band`).

```
# BENEFIT side: which rung did each shot of run 4b35c0ed actually land on?
uv run python _bmad-output/implementation-artifacts/14-4-live-validation/derive_guard_rungs.py

# COST side: seconds the vision call adds per shot (<= 4 live calls)
uv run python _bmad-output/implementation-artifacts/14-4-live-validation/probe_vision_latency.py
```

**Not portable.** Both scripts read
`workspace/4b35c0ed-8a1e-4448-8594-11bd9997376d/images/`, which lives on the machine
that rendered it and is not in the repo (raw renders are globbed out by the repo-root
`.gitignore`). `derive_guard_rungs.py` **refuses** to print a tally when that
directory is absent (exit 3) and `probe_vision_latency.py` refuses to print a latency
when there are no frames or no vision key — the numbers below are the portable copy.

## The benefit — what the guard did on 43 real shots

Sample band: thread id (run_id) `4b35c0ed-8a1e-4448-8594-11bd9997376d`, sidecar dir
`workspace/4b35c0ed-8a1e-4448-8594-11bd9997376d/images` (43 `*_done.json`), ladder
length 5 rungs (`BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS + 1`).

Method: the accepted rung is the index of the sidecar's recorded `seed` in
`image._seed_ladder(run_id, scene_num, shot_id)`. That is exact, not inferred —
`_seed_ladder` is a pure function of those three values and the sidecar records the
seed the guard accepted.

| | value |
|---|---|
| shots | **43** |
| accepted on rung 0 (clean first render) | **38** |
| accepted on rung 1 (guard regenerated once) | **5** detector hits — `S00103`, `S00202`, `S00203`, `S00301`, `S00400` |
| accepted on rung 2, 3, 4 | **0** |
| exhausted the ladder (kept a known-populated frame) | **0** |
| seeds on no rung of their own ladder | **0** |
| undecidable verdicts (`guard_unavailable`) | **1** — and it produced **no warning at all**, which is the other half of this story |

## The cost — both halves

| | value |
|---|---|
| pass 1 — 4 calls, `S00100`–`S00103` | 1.46 s / 2.58 s / 1.46 s / 2.52 s |
| pass 2 — 3 timed calls, review pass, same frames | 10.11 s / 2.59 s / 1.48 s |
| per-call seconds, all 7 timed | min **1.46** / mean **3.17** / max **10.11** |
| decided calls | 7 / 7 (`has_person=false` on every one) |
| projected on a 43-shot run | **2.3 min** of vision calls at the mean, **7.2 min** at the observed max — paid always |
| plus one extra render per HIT | 5 hits × ~17 s = **~1.4 min**, paid only on a hit |

**The first pass understated the spread and this is the correction**
(`gotcha_measure-densely-before-declaring-a-fix`). Four calls in one burst looked like
1.46–2.58 s, mean 2.00; three more in the review pass produced a **10.11 s** call on
`S00100` — the same frame that took 1.46 s in pass 1 and 1.48 s later in pass 2. So the
honest figure is a hosted-service latency with a ~7× spread on identical input, not a
~2 s constant.

The spec's Block-If line was **> 30 s** of per-shot detector overhead (which would add
more than ~20 min to a 43-shot run). Observed max is **10.11 s** — still inside it, by
3× rather than by an order — so the flip is not blocked, but the margin is thinner than
the first pass suggested. `probe_vision_latency.py` prints that comparison itself and
projects on the run's own shot count.

The ceiling is 2 extra renders per shot and it was never reached: the flip costs 43
vision calls and 5 extra renders on this run's shape, **not** 43 extra renders.

## Why 2 and not 1

The two live samples disagree, and the disagreement is the value:

- **10.2's single hit needed rung 2** (`10-2-live-validation/`) — rung 1 came back
  populated too, so a budget of `1` would have shipped a populated frame.
- **run 4b35c0ed's five hits all cleared on rung 1** (above).

Observed modal need is 1; observed worst case is 2. `2` is the worst case seen, not a
margin someone liked. `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS` stays 4 — nothing has
ever needed a third rung, and it is a resume contract that may only grow.

## What this sample does NOT say

- **These are 5 detector *hits*, not 5 confirmed contaminations.** Three of the five
  (`S00203` bars, `S00400` tactical figure, `S00301` desk figure) are the plates Jay's
  ⑤ named and the epics record as visibly cleaned. `S00103` is the doubtful one:
  `14-0-angle-conflict/report.md` §8-5, written the same day off the same run, records
  **no person visible in either render** of it, so at least one of the five is probably
  a false positive that cost a real ~17 s render. `S00202` was never eyeballed. A false
  positive is a permanent tax, not a one-off, so the benefit column should be read as
  *3 confirmed + 2 unadjudicated*, and adjudicating them is the cheapest way to learn
  whether the detector's threshold is right.
- **One run, one checkpoint, one SCP.** 43 shots of SCP-049 through
  `comfyui_sdxl_anime_lora_workflow_api2.json`. The 5/43 hit rate is not a population
  rate and it will move with the checkpoint, the prompt corpus and the article.
- **Rung 2 is still justified by n=1.** Every hit in *this* run cleared on rung 1. The
  only evidence a second rung is ever needed is 10.2's single `S00114` hit. If a later
  run also never reaches rung 2, the honest follow-up is to consider lowering the
  budget to 1, not to keep 2 because it is already there.
- **The 7-call latency sample is 7 calls on one account on one day.** It bounds the
  cost inside the Block-If line and nothing finer — and the second pass already showed
  the first pass's band was too narrow, so treat 10.11 s as a floor on the worst case
  rather than the worst case. Every one of the seven came back `has_person=false`, so
  it still says nothing about whether a *positive* verdict is slower.
- **The detector is not deterministic.** `temperature=0` is pinned, but the verdict
  comes from a hosted model (`vision_check` module docstring): a replay can accept a
  different rung and ship a different image even though the renders themselves are
  seed-deterministic. So this rung tally is what happened, not what must happen.
- **`guard_exhausted = 0` is still an unobserved path live.** Same caveat 10.2 already
  recorded: the exhausted branch is handled and tested, and has now been observed
  zero times in 43 + 5 shots.
- **It says nothing about people *depicted* inside frames, monitors or posters.** The
  detector answers `false` for those on purpose, which is right for its duplicate-figure
  job and is not the defect Jay's ⑤ named. That case is 14.1's approval gate — see the
  decision recorded in `epics.md` (Story 14.4) and research §2.
- **The notes channel is now confirmed live**, in the review pass:
  `INFO yt_flow.services.vision_check: background person check: has_person=False,
  notes='The frame depicts an empty industrial environment with no human presence.'`
  That is the string 14.1's approval criterion will accumulate a corpus of, and the one
  that would have described `S00201`'s framed portrait on the first run had it not been
  discarded. Unit-covered by
  `tests/services/test_vision_check.py::test_the_models_note_is_logged_beside_the_verdict`.

## Committed vs ignored here

Scripts and this README only. There is no adjudication image: nothing in this story is
judged by looking at a frame — the benefit is a rung tally derived from sidecars and
the cost is a stopwatch. The raw PNGs both scripts read stay in the workspace, where
the repo-root `.gitignore` already covers them, and are re-readable in place.
