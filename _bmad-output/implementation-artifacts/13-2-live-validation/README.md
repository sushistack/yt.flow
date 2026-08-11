# 13.2 Live Validation — instrument replacement: 1–5 Likert → DSG proposition fraction

Evidence for Story 13.2, scope item ①. Measured 2026-08-11 on the **same 66 preserved
frames** `10-4-live-validation/baseline_v2.json` scored (run
`8a9a288b-800f-4c73-88a2-25ae6b5a4d7d`, SCP-049, 9 scenes / 66 shots), same judge
`qwen-vl-plus` via DashScope, same `temperature: 0`. Nothing was re-rendered, no GPU
was touched, `baseline_v2.json` was not modified.

> **Verdict: the resolution defect is fixed and the confound was far larger than
> recorded.** v2's `match` had 5 distinct values with **29 of 66 rows (44 %) piled on
> exactly 3**; v3's proposition fraction has **9 distinct values**, and that 29-row pile
> spreads across **7** of them, moving **18 rows** off it. The card-absence confound,
> which 10.4 recorded as an unreproducible "11/66", actually touches **61 of 66 rows**
> and **163 of 353 propositions (46 %)**.
>
> **Two results run against expectation and are reported as findings, not smoothed:**
> the v2↔v3 rank correlation is **0.0263** — the two instruments essentially do not
> agree — and mean DSG is **higher** on frames the blind judge called unreadable
> (0.5694) than on readable ones (0.4892). Neither is a reason to keep the Likert, and
> neither licenses using `dsg_score` as a gate yet. See §5.
>
> **And one caveat on the resolution claim itself:** 48 % of rows land on 0.0 or 1.0.
> The gain is real for *attribution* — you learn which proposition failed — and only
> arguably real for *ranking*. See §4.

---

## 0. Re-derive with one command

```
uv run python _bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py
#   -> baseline_v3.json, instrument_v2_vs_v3.json      (~6 min, 0 renders)
#   --limit N  scores only the first N v2 rows (smoke test)
```

The harness imports and drives `scripts/score_shot_narration.py` — the axis is shipped
code, not a copy living in the harness. Frame paths come from `baseline_v2.json`'s
`frame` field rather than from re-resolving `shot["image_path"]`, because that field has
already been repointed once (`recompose_service`; see 10-4 README §0) and re-resolving
would silently score a different frame set. Every number below is computed by that
script into a JSON file in this directory; none was typed by hand.

The axis alone, on any run:

```
uv run python scripts/score_shot_narration.py --run <run-id> --dsg --json out.json
#   also writes <workspace>/<run-id>/visual_score.json, which is where
#   eval_service.evaluate_ab reads unreadable_rate / mean_dsg_score from
```

**Provenance caveat, inherited and restated:** 51 of these 66 frames are Story 10.1c
recompositions (2026-08-09), not the frames Jay watched (2026-08-08). That is recorded
in `baseline_v3.json` under `provenance`. It does not affect the v2↔v3 comparison — both
instruments read the identical files — but it does mean absolute rates here describe the
checkpoint's current frames.

---

## 1. Why the Likert was replaced, and why not with VQAScore

Story 10.4's own data condemned its axis twice: `legible` (1–5) was dead (66 frames
produced `{4: 46, 5: 20}`, nothing below 4, while the *same replies* wrote
`event: "unclear"` on 9), and `match` clusters at 3 hard enough that the §12 merge probe
left 15 of 16 rows unmoved. The literature moved to question-generation/answering years
ago ([TIFA](https://arxiv.org/abs/2303.11897),
[DSG](https://arxiv.org/pdf/2310.18235) ICLR 2024,
[VQAScore](https://arxiv.org/abs/2404.01291) ECCV 2024).

**VQAScore was ruled out by measurement, not assumption** — it scores one question by the
probability of the "yes" token, so it needs token logprobs from the judge:

| model | endpoint | request | `choices[0].logprobs` |
|---|---|---|---|
| `qwen-vl-plus` (our vision judge) | DashScope compatible-mode | `logprobs: true, top_logprobs: 5` | **`null`** (HTTP 200, content `'Yes.'`) |
| `qwen-plus` (text, **same endpoint, same key**) | same | same | full `content[0].top_logprobs` |

The endpoint supports logprobs; the vision model does not return them. So VQAScore is not
implementable against this judge. DSG needs no logprobs at all — only yes/no answers —
which is exactly why the research named it the safer default.

---

## 2. What the instrument is

Three calls per shot, the first two unchanged from v2 so the numbers stay comparable:

1. **BLIND** — the frame alone, sentence withheld → `{place, event, readable}`.
2. **MATCH** — frame + sentence → `{match, evidence, missing}`. Carried forward from
   `baseline_v2.json` rather than re-asked (`temperature 0`, same frame, same judge; 10.4
   §12 verified this instrument reproduces itself 8/8 on repeat).
3. **DSG** (new) — question generation on the sentence alone (`qwen-plus`, text-only, no
   image), then one yes/no VLM call per non-person proposition.

`dsg_score` = satisfied ÷ scored over the **non-person** propositions. Person-kind
propositions are generated, then excluded from numerator *and* denominator, and counted.

Two structural rules, both load-bearing:

- **Dependency invalidation** (DSG's advantage over TIFA): a proposition whose parent
  answered *no* is counted unsatisfied and its own question is never asked. "There is no
  bed" followed by "the bed is disturbed: yes" is the inconsistency independent questions
  let through. 32 propositions were invalidated this way.
- **Person propositions count as SATISFIED for dependency purposes** and are never asked.
  This is the research's "marked as satisfied by the card layer" and it is not an
  optimisation — see §3.

---

## 3. Two defects found in the smoke test, before the real run

Both were caught on a 3-row / 13-proposition smoke run and would have invalidated the
whole measurement. Recorded because the fix is the reason the numbers below mean anything.

**(a) The decomposer mislabelled bodies as scenery.** With the first QG prompt,
`qwen-plus` labelled *"Is there a hand visible in the frame?"* as `object`, *"Is a human
figure present inside the containment cell?"* as `object`, and a black robe's length as
`state`. On 3 of 3 rows the score was therefore driven almost entirely by body
propositions a background plate is not supposed to contain — **the card-absence confound
fully re-imported through mislabelling.** Fixes: the QG prompt now makes the body test an
explicit per-proposition step (`subject` + `about_body`) and carries two worked examples
built from exactly these failures; and `_is_person` takes the **union** of `kind ==
"person"` and `about_body is True`, so a disagreement can never put a body back into the
denominator. No regex over the question text —
`gotcha_person-token-regex-is-unusable-on-image-prompt` is the recorded cost of that
shortcut. The residual is measured, not hidden: **42 of 353 propositions (12 %)** still
disagree between the two fields (`qg_label_disagreements_total`), and the union absorbed
all of them.

**(b) A missing person invalidated real scenery.** Even with correct labels, a `person`
parent answered *no* invalidated its children. Live example: *"is the person moving toward
the interior"* → no → invalidated its child *"is the cell door open"*, which is a genuine
plate proposition. Excluding person propositions from the fraction is therefore **not
sufficient on its own**; they must also be unable to invalidate scenery. Hence the
satisfied-for-dependency rule.

**(c) A third adjustment, made for coverage.** With bodies excluded, sentences that are
purely about a person left a denominator of zero — 2 of the first 3 rows came back
*unscorable*. The QG prompt now requires the background layer explicitly ("what PLACE
does this happen in, and what PHYSICAL TRACE would the event leave there"), with an
instruction not to invent detail the sentence does not imply. After that change,
**0 of 66 rows are unscorable**. This is the same question v2's `MATCH_PROMPT` already
asked ("grade the place and the event's physical consequence"), now asked one proposition
at a time.

---

## 4. Result — resolution

`instrument_v2_vs_v3.json`, 66 frames joined on `shot_id`, 0 errored, 0 unscorable.

| | v2 `match` (1–5 Likert) | v3 `dsg_score` (fraction) |
|---|---|---|
| distinct values | **5** | **9** |
| distribution | `{1:2, 2:1, 3:29, 4:22, 5:12}` | `{0.0:14, 0.1667:1, 0.25:3, 0.3333:9, 0.4:3, 0.5:12, 0.6667:5, 0.8:1, 1.0:18}` |
| mean | 3.621 | 0.5038 |
| largest single bucket | 29 / 66 (44 %) | 18 / 66 (27 %) |
| **rows on an extreme value** | 14 / 66 (21 %; `match` 1 or 5) | **32 / 66 (48 %; 0.0 or 1.0)** |

That last row is stated because the two headline figures above do not show it: v3 moves
mass off a *single interior* value but piles 48 % of rows onto the two **endpoints**, which
are the values a denominator of 2–4 reaches most easily. "Distinct values 5→9" and
"largest bucket 44 %→27 %" are both true and both flatter the result. Whether 48 % at the
extremes is better than 44 % on one interior value depends on what you need the score for:
it is clearly better for *attribution* (you can see which proposition failed) and only
arguably better for *ranking*.

**The 3-pile, opened up.** Of the 29 rows v2 scored exactly 3, v3 assigns **7 distinct
values**; the largest v3 bucket among them holds 11, so **18 rows moved off the pile**.
That is the defect this story existed to fix, and it is fixed.

**Stated limit: the fraction is coarse.** 353 propositions over 66 rows, minus 163
person-kind, leaves **190 scored propositions — 2.9 per row**. A denominator of 2–4
produces exactly the observed lattice (0, ¼, ⅓, ½, ⅔, 1). 9 distinct values beats 5, and
27 % beats 44 %, but this is not a continuous score and should not be described as one.
Raising the denominator means asking for more background propositions per sentence, which
costs calls; not attempted here.

---

## 5. Result — the confound, and two findings that go the wrong way

**The card-absence confound was much larger than 10.4 recorded.**

| quantity | value |
|---|---|
| propositions generated | 353 |
| person-kind, excluded from scoring | **163 (46 %)** |
| rows carrying ≥ 1 person proposition | **61 of 66** |
| propositions actually scored | 190 (2.9 / row) |
| dependency-invalidated (inside the denominator) | 32 |

10.4's "11/66" is not reproducible — it was a hand count of `missing` free text with no
script or rule ever recorded (confirmed by grep and `git log -S`), so it must not be
carried forward as a baseline. Two written-down rules, applied to `baseline_v2.json` and
reported with their patterns in `instrument_v2_vs_v3.json`:

- person-nouns in v2's `missing` → **14 of 66** (`person_noun_rule`)
- person-nouns in v2's blind `event` caption → **26 of 66** (`blind_body_rule`). The same
  rule run against iteration 1's `baseline.json` gives **28**, which is the figure 10.4
  §2.3 reported — so the *rule* is the one 10.4 used, and the 26-vs-28 gap is the two
  scoring passes differing on two rows, not a discrepancy in the rule. 26 is the
  v2-comparable number and the one to quote.

Both are proxies over free text. The proposition count is the real measurement, and it
says the confound was touching **92 % of rows**, not 17 %.

**Finding A — the two instruments do not agree.** Spearman rank correlation between v2
`match` and v3 `dsg_score` is **0.0263**. Essentially zero. They are not two calibrations
of one construct; they measure different things. That is consistent with v2 being
confounded (46 % of what v3 now excludes was inside v2's single opaque integer) but it is
*not* evidence that v3 is right — only that v3 is different. Nothing here validates
`dsg_score` against human judgment.

**Finding B — DSG is higher on frames a viewer cannot read.** mean `dsg_score` is
**0.5694** on the 12 frames v2's blind boolean called unreadable, versus **0.4892** on the
54 readable ones. Backwards from expectation. n=12, so this is weak, but the direction is
recorded rather than dropped. Two readings are available and this sample cannot separate
them: an unreadable frame may satisfy narrow propositions ("is there a concrete surface")
while failing to convey any place; or the QG questions may be too easy on abstract frames.
**Consequence: `readable` and `dsg_score` must stay separate axes** — exactly the finding-2
vs finding-4 separation 10.4 insisted on — and `dsg_score` must not become a gate until
this is understood. Gate inclusion is Story 13.4's decision anyway.

---

## 6. What this does NOT establish

- **No human validation.** DSG's published correlation with human judgment is on general
  T2I benchmarks — not Korean narration, not SCP horror, and not background plates whose
  subject is composited afterwards. Nobody has scored these 66 frames by hand.
- **No threshold.** `dsg_score` deliberately has no `MIN_*` constant. You cannot calibrate
  a threshold before seeing a distribution, and this is the first distribution.
  `fail_reason` still turns on `readable` and `match` only.
- **`--reps 1`.** Each proposition was asked once. QG was not resampled either, so
  decomposition variance is unmeasured — a second run may produce a different proposition
  set for the same sentence.
- **One run, one judge.** 66 frames from one SCP, scored by `qwen-vl-plus`. The judge is
  the instrument, not an oracle.
- **The 12 % label disagreement is unexplained.** The union rule makes it harmless to the
  score, but a decomposer that contradicts itself on 42 of 353 propositions is not a
  solved component.

---

## 8. Hardening applied after the run (adversarial review), and why the numbers still hold

Review found defects that would let a *future* run publish a wrong number. All were fixed
after the measurement above; none of them changes it, and that was checked rather than
assumed:

- **`about_body` is now required and must be a real `bool`.** Previously unvalidated, so a
  reply omitting it would silently degrade `_is_person` to `kind`-only — the §3(a) failure
  mode — while `dsg_label_disagreements` read `0`, i.e. perfect compliance. **Checked
  against this run's data: all 353 propositions carry a real boolean, so the tightened
  validator would have accepted every row and the figures above reproduce unchanged.**
- **Proposition count is capped at 12.** The prompt asks for 3–7 and nothing enforced it;
  each extra proposition is one paid image call per frame. No row here exceeded 12.
- **`dsg_qa_errors_total` is now reported.** A QA call that dies after its retry counts
  unsatisfied, so DashScope flakiness lowers `mean_dsg` in a way that was previously
  indistinguishable from the frame genuinely not showing the thing. This run: **0**.
- **A partial sweep is no longer published to `visual_score.json`.** `--dsg --limit 3`
  used to write the consumer artifact, and nothing downstream could tell 3 scored frames
  from 66 — `_unreadable_rate` just divides `unreadable` by `scored`. The write is now
  gated on a complete sweep of the plates, and `--frames shots` is excluded as a different
  population. The harness applies the same rule and evaluates the HALT thresholds *before*
  writing anything, rather than warning after the file is already on disk.
- **`cut_alignment_error` returns `None`, not `0.0`, with no data.** It became a tiebreak
  input at position 2 in this story, and under 11.4's "0.0 with no data" convention that
  value meant both "every cut lands on a word boundary" and "there were no timings to
  check" — so lower-is-better would have handed the top-priority tiebreak to whichever run
  had *less* data. Absence is now omitted and the tiebreak skips what it cannot compare.
- **The tiebreak skips uncomparable values instead of defaulting them.** `null` raised
  `TypeError` out of `determine_winner`; NaN was worse, silently tying a step so a later
  metric decided with nobody told. Epsilon is now per key, because the six metrics are not
  in one unit — a single absolute `0.01` swallowed a 0.6-percentage-point audio-variance
  gap that the old dataclass path decided.
- **Both motion docstrings were factually wrong about their own ranges.**
  `CAMERA_PREFERENCES` exposes only 3 of 5 archetypes per mood and
  `_enforce_camera_variety` guarantees ≥2 distinct per multi-shot scene, so coverage's
  healthy floor is ~0.4–0.6 for a single-mood episode and **0.2 is effectively
  unreachable** — the docstring had claimed 0.2 as the collapse value. Both are still
  tiebreak inputs and both *can* decide a winner (coverage's step is 0.2, repeat_ratio's is
  1/65), so what they actually reward is **mood variety** and **how scenes are cut up**,
  not motion quality. Corrected in place, since a docstring written to stop a misreading
  that itself misreads the metric is worse than none.
- **The Playwright mock had the same schema bug as the vitest fixture.**
  `e2e/ab-comparison-accessibility.spec.ts` still used `llm_scores`/`rule_scores`, so its
  score-table assertion passed while every cell rendered the not-measured placeholder.
  Verified by running it: **before the fix both tests in that file failed; after, the
  mocked one passes.** The remaining failure in that file drives a real pipeline run and
  fails at `approveStage` with and without this change — pre-existing.

---

## 9. Layout

```
run_dsg_rescore.py           the harness — clone of 10-4's `--rescore` mode, frames taken
                             from baseline_v2.json rather than re-resolved
baseline_v3.json             66 rows: v2's readable/match/place/event/evidence/missing
                             carried forward + propositions/proposition_answers/dsg_*,
                             plus the QG model and both new prompts verbatim
instrument_v2_vs_v3.json     the comparison: both distributions, distinct-value counts,
                             the 3-pile breakup, rank correlation, and every confound count
README.md                    this file
```

Both new prompts (`qg_prompt`, `qa_prompt`) and the QG model are stored verbatim inside
`baseline_v3.json`, same convention as v2's `blind_prompt`/`match_prompt`.
