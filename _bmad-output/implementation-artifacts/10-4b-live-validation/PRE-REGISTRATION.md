# Story 10.4b — pre-registered analysis plan

**Written 2026-08-11, BEFORE any candidate render existed and before any score was read.**
Committed separately from the results so the ordering is checkable in git. Nothing in this
file may be edited once scoring starts; corrections go in the results README as amendments.

This exists because Story 10.4 lost two pre-registered A/Bs and the value of those rounds
came entirely from the rule having been fixed in advance. A rule written after seeing the
distribution is not a rule.

---

## 1. What is being tested

`prompts/scenario/visual_breakdown.md` was changed in two ways:

1. **Scope ①** — the subject of an `image_prompt` must be an existing object/surface/trace,
   and the frame must carry at least one legible trace of *this sentence's* event. Three
   surviving absence-teachers were removed (the negative-space section, "show an EMPTY frame
   that feels WRONG", the checklist item that *mandated* negative space) and the cast-empty
   guidance was tightened.
2. **Scope ②** — a sentence with no renderable referent widens a neighbouring shot's span
   instead of minting its own background. (The parser has accepted an ordered cover since
   10.4; only the prompt forbade it.)

Plus one code change: `_fallback_prompt` no longer ends in `"no visible subject"`.

## 2. Primary axis — and it is the boolean, not a Likert

`readable` from `scripts/score_shot_narration.py` (the blind call: frame alone, narration
withheld; `readable` is true only if a viewer could say **both** where they are and what
happened). Baseline on run `8a9a288b`: **12 of 66 = 18.2 %** unreadable.

`match` is **not** the axis — it collapsed onto 3 in 10.4 (29 of 66 rows) and its merge probe
moved 15 of 16 rows by nothing. `dsg_score` is **not** the axis and gets no threshold: it is
rank-uncorrelated with `match` (0.0263), scores *higher* on unreadable frames (0.5694 vs
0.4892), and 48 % of its values sit at 0.0/1.0. It is recorded for **per-proposition
attribution only** — i.e. to say *which* proposition failed, never to decide the verdict.

## 3. Design — paired, because unpaired is underpowered at this n

Both legs run the **same SCP-049 narration**, all 9 scenes:

- **control leg** — the baseline prompt, read via `git show <baseline>:prompts/scenario/visual_breakdown.md`, re-rendered fresh
- **candidate leg** — the edited prompt, rendered fresh

A same-prompt control is mandatory: 10.4's control leg moved −0.267 with per-shot sd ≈ 1.4,
the same size as its measured effect, which is how that round became unmeasurable.

Comparing two independent rates at n≈66 has a 95 % interval of roughly ±0.09 (±6 frames), so
it could only detect a change of 6 or more of the 12 — that is exactly the trap 10.4 fell
into with 15 slots. Since every sentence appears in both legs, the comparison is **paired**
and the informative quantity is the **discordant pairs only**:

```
b = unreadable in control → readable in candidate     (the win)
c = readable in control   → unreadable in candidate   (the cost)
verdict statistic: exact binomial two-sided p over b + c, H0: p = 0.5
```

Concordant sentences (readable in both, unreadable in both) carry no information about the
change and are excluded from the test, though they are reported.

**Pairing key is the SENTENCE, not the shot id.** Once a cover may fold sentences the two
legs share no shot slots, so a per-shot pairing is undefined (`--pair-by sentence` exists for
this). A sentence covered by several shots is unreadable if **any** covering frame is.

## 4. The pre-registered decision rule

Seed the prompt to `production` **only if all three hold**:

1. **b > c** — strictly more sentences became readable than became unreadable.
2. **exact binomial p ≤ 0.05** over `b + c`.
3. The unreadable **rate** does not increase: `unreadable_candidate / n_shots_candidate <= 0.182`.

Otherwise: **do not seed.** Revert `prompts/scenario/visual_breakdown.md` to the baseline
commit, record the result, and close the story on the measurement. A lost A/B is a result.

**Rate, never count.** Folding sentences removes frames, so an unreadable count can fall while
the rate rises — 10.4 measured exactly this (16→15 count, 24.2 %→27.3 % rate). Every rate is
reported with its `n_shots`.

## 5. Strata — fixed now, from the baseline row data

The recorded premise ("all 12 unreadable prompts make an absence the subject") is **wrong**,
and the strata are fixed here so the result cannot be pooled into an uninterpretable number.
Assignment is from `10-4-live-validation/baseline_v2.json`, by reading each `image_prompt`:

| stratum | n | shot ids |
|---|---:|---|
| **A — absence was the subject** | 5 | `S00204`, `S00300`, `S00304`, `S00305`, `S00805` |
| **A′ — borderline** | 1 | `S00303` (a real window, but framed "facing the wall as if answering") |
| **B — subject already concrete, unreadable anyway** | 6 | `S00201`, `S00202`, `S00400`, `S00707`, `S00804`, `S00900` |

Scope ① targets stratum A (+A′). **Its ceiling is therefore ~6 of 12, not 12 of 12.**
Stratum B fails for a different reason — every one of the 12 had `event: "unclear"`, and 8 of
12 blind-read as "corridor" — which is what the second half of the requirement (a legible
trace of the event) addresses, less directly.

`b` and `c` are reported **per stratum as well as pooled**. A pooled improvement that comes
entirely from stratum B would mean scope ① did nothing and something else moved.

## 6. Stated in advance as NOT evidence

- Any improvement in `match` (dead axis for this purpose).
- Any change in `dsg_score` used as a verdict rather than attribution.
- A drop in the unreadable **count** unaccompanied by a drop in the rate.
- Residual absence-as-subject prompts in the candidate leg are reported as **non-compliance**
  and never scrubbed, regex'd, or hand-edited.
- A "cover quality" judgment of any kind. 10.4's handoff forbids building one, and mapping is
  dead as a `match` lever — scope ② is justified here only by not minting a subjectless frame.

## 7. Known limits, before the fact

- One SCP, one narration, `--reps 1`, one judge (`qwen-vl-plus`). The judge is the instrument,
  not an oracle.
- `b + c` will likely be in the teens, so the exact binomial is the honest test and the
  confidence interval will be wide. A clean 6–1 split is evidence; a 4–3 split is not.
- The candidate leg re-runs `visual_breakdown`, so the LLM re-draws every prompt in the scene,
  not only the 12 targets. Prompt-level reseeding is inseparable from the intended change —
  that is what the control leg is for, and it bounds the claim to "this prompt version beats
  that one", not "this clause caused it".
- 51 of the 66 baseline frames were 10.1c recompositions (10-4 README §0), so baseline
  *absolute* rates describe the checkpoint's frames. Both legs here render fresh plates, so the
  comparison is unaffected; the 18.2 % reference carries that caveat.
