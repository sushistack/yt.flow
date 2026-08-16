# Story 10.1e — pre-registration

**Committed before any frame of either arm was scored.** `git log` on this file and on
`results.json` is the timestamp; nothing in this document may be edited after that commit,
and `run_pairs.py report` applies the rule below mechanically from constants that are in
the same commit as this file (`FLIP_SLACK = 1`, `VETO_FAILED_PASSES = 5`,
`COST_BUDGET_HOURS = 1.0`).

Written 2026-08-16, after `screen` (which reads only the already-committed
`10-4-live-validation/baseline_v2.json` and touches no frame of this experiment) and
before `manifest`, `render-off`, `render-on` and `score`.

## The rule

> Deciding axis: blind `readable` (13-2's `BLIND_PROMPT`, frame bytes only), over the paired shots.
> Let **b** = shots readable OFF and unreadable ON; **c** = unreadable OFF and readable ON.
> **FLIP** the default iff `b − c ≤ 1`. **STAY OFF** iff `b − c ≥ 2`.
> Veto, applied first: if ≥5 of the 40 recompose passes fail, STAY OFF regardless of scores.
> Cost does not enter this decision — it is 10.1c's item (c). If (a) passes but the measured
> added time exceeds 1.0 h on a 43-shot run, the verdict is "(a) closed PASS, (c) still blocks"
> and the flag stays `False` with that stated.
> Secondary axes (mean DSG, corridor-misread rate, `place`/`event` unclear split) are
> record-only and never override the deciding axis, in either direction.
> Retirement (AC7): a follow-up story, never this commit.

`b − c ≤ 1` is "neutral-or-better with one shot of slack" — 10.1c's UNBLOCK wording. Exact
McNemar on n=33 has no power for small effects, so a p-value would be theatre; the slack is
stated instead of hidden.

## Operationalisation (also written before any render or score)

These fix the meaning of each term in the rule so that applying it is arithmetic, not
judgement. None of them is a threshold and none may be revised after a score is read.

1. **Paired shot.** A shot with a `status == "scored"` row in *both* arms. A shot that
   failed to render, or whose blind call errored after its retry, in *either* arm is
   excluded from both — never counted as unreadable in one arm only.
2. **`readable`.** The boolean the judge returns to 13-2's `BLIND_PROMPT`, one call per
   frame at `temperature: 0`, reps 1, judge `qwen-vl-plus` (the same instrument and the
   same rep count `baseline_v2.json` was produced with). `_bool_field` is used, so a
   non-boolean answer is an errored row, never coerced.
3. **"a recompose pass fails."** A pass is one card insertion; the manifest's
   `recompose_passes` is the total (one per resolved cast card). `recompose_shot` abandons
   a shot at the first pass that returns no usable image, so failures are counted
   conservatively as `passes_attempted − passes_completed`, i.e. **every pass of a shot
   that produced no ON frame counts as failed**. This is the direction that triggers the
   veto more easily, chosen deliberately.
4. **Cost.** `total wall clock of the single `recompose_run_shots` call ÷ completed
   passes` × this run's total passes, expressed in hours, compared against 1.0 h.
   The wall clock is measured on a ComfyUI started with the flags
   `recompose_service.REQUIRED_FLAGS` requires; a run on a misconfigured server is not a
   cost measurement and is reported as a preflight bail instead.
5. **Corridor misread.** Case-insensitive substring `corridor` in the blind `place`
   reading. This rule reproduces 10-4 README §0's 29/4 counts exactly off
   `baseline_v2.json` (`screening.json`), so it is the incumbent's own rule, restated.
6. **Blindness.** Frames are copied to `blind/<sha256(shot_id|arm|salt)[:12]>.png` and
   scored in ascending blind-id order; the judge receives image bytes and a prompt that
   names no arm, no filename and no shot. ON frames are re-framed through the OFF arm's
   own `_zoompan_filter` chain first, so resolution and crop cannot identify the arm.
7. **Instrument.** `scripts/score_shot_narration.py` is imported unmodified. Its
   `BLIND_PROMPT` contains `_CARD_NOTE` ("this is a BACKGROUND PLATE … a plate with nobody
   in it is CORRECT"), which is untrue of both arms here. It is left alone on purpose: a
   reworded prompt is not 13-2's instrument, and the sentence biases both arms identically.

## What would falsify the setup rather than the hypothesis

Recorded now so that reading them later is not a rescue:

- Fewer than 25 paired shots survive — the deciding axis is then under-powered even for
  the slack this rule grants, and the result is reported as inconclusive, not as FLIP.
- The blind grid (`pairs_grid.jpg`) read with the key hidden makes the arm guessable from
  framing, resolution or border artifacts alone — the package leaks and the scores are
  suspect.
- `b == c == 0`. The rule then yields FLIP (`b − c = 0 ≤ 1`) and that outcome is reported
  **with its zero-power caveat**: no discordant pair means the axis saw no difference at
  this n, not that recompose was shown to be better.
