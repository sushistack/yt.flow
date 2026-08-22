# Story 14.7 — screening the Stage-4 reviewer against the recompose architecture

Spec: `_bmad-output/implementation-artifacts/spec-14-7-scenario-reviewer-recompose-alignment.md`
Re-derive (headline): `uv run python _bmad-output/implementation-artifacts/14-7-prompt-screening/screen_review_prompt.py 4b35c0ed --reps 5`
Classifier self-check (no LLM, no DB): `… screen_review_prompt.py --selftest 0`

## 1. Sample band

| | |
|---|---|
| run | `4b35c0ed` |
| thread_id | `4b35c0ed-8a1e-4448-8594-11bd9997376d` |
| checkpoint_id | `1f19a3de-374f-68db-800f-3033ac398867` (last checkpoint carrying a non-empty `scenes`) |
| checkpoint provenance | `final_pass_index: 2`, `retry_scope: "scene"`, `review_overall_pass: true`, `critic_verdict: "retry"` |
| scp_id | `SCP-049`, 9 scenes |
| scenes screened | 6, 8, 9 — the three the run's 4 gate warnings landed on — plus one synthetic reverse-direction control (`9-syn`) |
| prompt versions | `old` = `git show 003045c:prompts/scenario/review.md` (the spec's `baseline_revision`), `new` = working tree |
| reps | **5 per (version, scene) cell, one replication = 40 text-only LLM calls, 0 GPU.** Verdicts are STRICT majority (`hits * 2 > reps_ok`), so an even `--reps` tie is not a majority |
| model | `gemini-3.6-flash`, `max_tokens` 16384 — the real review provider (`scenario._call_gemini`; `_GEMINI_STAGES` includes `review`) |
| renderer | `TextPromptClient.compile` — the same object `scenario_chain._call_stage` renders through |
| parser | `scenario_chain._parse_yaml` — the same one `review_step` uses |
| transcript | `transcript-20260822T134015.jsonl` (headline run), one JSONL line per call: version, cell, rep, raw text or parse error, every parsed entry, assigned bucket |
| date | 2026-08-22 |

### Fidelity: what is a replay and what is not

The screening does **not** replay the live call byte-for-byte, and the list of
divergences is the honest version of that claim (the code comment in
`variables()` carries the same list):

| # | divergence | why |
|---|---|---|
| 1 | **`scp_visual_reference` reconstructed** | `research_step` output, never persisted. Rebuilt from the `characters` rows for `SCP-049`/`SCP-049-2` — the roster this run's own cards were cut from. |
| 2 | **`entity_sheet` reconstructed** | same origin, same rebuild. |
| 3 | **`entity_visible` injected** (`--entity-visible`, default `true`) | scene-level `writing_step` field (`writing.md:219,236-238`); `writing_step`'s dict is not persisted and the checkpoint's `SceneState` has no such key. This is the field clause (a) is *entirely about* — without it clause (a)'s literal trigger is never exercised. `true` is on the record: the run's own warnings quote "entity_visible is set to true for Scene 8" and "Scene 9 has entity_visible set to true". |
| 4 | **`display_narration` substituted into `narration`** | the persisted `narration` is TTS-normalized ("에스씨피 공사구"); `tts_normalize_step` runs *after* review. `display_narration` is the pre-normalization text the reviewer actually saw. Only one spelling is sent. |
| 5 | **scenes and shots field-trimmed** | the checkpoint scene has gained `audio_path`/`audio_duration`/`subtitle_path`/`word_timings` and each shot has gained `image_path` from stages that ran after the reviewer; the scene has *lost* `fact_tags`/`location`/`characters_present`/`color_palette`/`atmosphere`. |
| 6 | **wrapper is `{"scp_id": …, "scenes": [scene]}`** | live it is `{**writing, "scenes": [scene]}`, so the live call also carries `writing`'s siblings. |
| 7 | **`_call_stage_with_retry` + `_make_parse` bypassed** | rendered text equals the live **first attempt** (hence `parse_error: ""` injected here). Tallies are therefore **pre-filter**: they include findings the live evidence check would have dropped, and they do not include the corrective second attempt. |

Both prompt versions receive the **identical** dict in every cell, which is what
makes old-vs-new comparable even where the input is not a byte replay.

**Provenance caveat (stated, not buried).** `final_pass_index: 2` means the
scenes in this checkpoint are **post-repair** text: the narration screened here was
already rewritten in response to these very warnings. The screening measures
whether the two prompt versions disagree about *this* text, which is sound; it does
not reproduce the pass-1 input that produced the original warnings.

## 2. What was stale (two lines, one file)

`prompts/scenario/review.md` contradicted `prompts/scenario/visual_breakdown.md`
head-on, live, for weeks. **The generator was correct**; only the reviewer was stale.

| | old (`review.md` @ `003045c`) | generator (`visual_breakdown.md`, read-only source of truth) |
|---|---|---|
| `:46` §4 | "Every scene where the entity appears must use the Frozen Descriptor" — **no scope stated**, so the model applied it to `image_prompt` | `:142-148` "**`image_prompt` is background-only.** … NEVER described in `image_prompt` prose … no bare SCP designator token … They exist in the shot only through the pre-made cards the video stage composites on top" |
| `:61` §6 | "When entity_visible is true, the SCP frozen descriptor from Visual Identity Profile is present" | `:201` "Because `image_prompt` is background-only, also append person-exclusion terms … `\"person, human figure, character, silhouette of a person\"`" |
| `:60` §6 | forbidden generic terms — **6** | `:136` — **11** (`ominous`, `sinister`, `menacing`, `foreboding`, `unsettling` were missing from the reviewer) |

`entity_visible` is defined in `writing.md:219,236-238` as a **scene-level
narration** field ("the SCP is mentioned/appears in this scene's narration"). It
does not appear in `visual_breakdown.md` at all, and no shot dict in this run
carries the key. The reviewer read a scene-level narration fact as a shot-level
render instruction.

The fix is a **reversal, not a deletion**: the reviewer is handed the frozen
descriptor in `{{scp_visual_reference}}` and the prompts in
`{{visual_descriptions}}`, so silence leaves it free to re-derive the same rule
from §4 or from common sense — which is exactly what run 4b35c0ed's scene-9
finding did when it demanded a `negative_prompt` edit no line of the prompt had
asked for. The new text therefore:

- **`:45-50` §4** — states its scope positively and for *every* bullet: judged on the **narration** and on a shot's `cast` array (the one field where a shot declares a figure), **never** on `image_prompt`/`negative_prompt`. Scoping only the first bullet left "No physical description should contradict the Visual Identity Profile" and "Verify visual descriptions don't add non-canonical features" pointing straight back at `image_prompt` — and `visual_descriptions` is literally the variable name of the shots JSON.
- **`:63` §6** — reports `descriptor_violation` when the entity/person **IS** in `image_prompt`.
- **`:64` §6** — **exempts depicted and inanimate figures** (photograph, poster, painting, pictogram, anatomical diagram, mannequin, dummy, statue), **unworn garments used as props** (a lab coat on a hook, a discarded jumpsuit) and **camera vocabulary** (`over-the-shoulder view`, `POV`, `eye-level`, `from behind`). Without this, the positive rule creates a brand-new false-positive class — the same trap `gotcha_person-token-regex-is-unusable-on-image-prompt` records (person tokens catch pictures-of-people, mannequins, scale references and camera phrasing), and Story 14.4 decided on 2026-08-22 that pictures-of-people are the **plate-approval gate's** business, not a runtime detector's.
- **`:66-69` §6** — names the two states it must **not** report, with the architectural reason attached. Clause (b) now exempts person-exclusion terms in `negative_prompt` **generally** (the four canonical terms are examples, not the boundary) and says the mandated anatomy prefix (`extra limbs`, `deformed hands`, `bad anatomy`, `mutated`, `extra fingers`) is likewise never a defect. An enumerated closed list licenses the next false positive.
- **`:71` §6** — the new rule's fix has **no channel in the output schema**: `corrections[].field` is `"narration|visual_description"` and an `image_prompt` channel was not added (`REVIEW_ISSUE_TYPES` and the `type:`/`field:` enum lines are frozen). So the reviewer is told to carry an `image_prompt` fix inline in the issue's own `correction` field and emit no `corrections[]` entry for it.

## 3. Old vs new — one clean replication

Counts are **reps in which the bucket appeared**, out of `reps_ok` — not entry
counts, so three quotations of "dark" in one rep still counts 1. Buckets are
**mutually exclusive** (`negative_fp` takes precedence; see the classification note
below). `corrections[]` and `grounded_contradictions[]` entries are bucketed
alongside `issues[]`.

Headline run: `--reps 5`, 8 cells, **40 text-only LLM calls, 0 GPU, 0 failures**,
transcript `transcript-20260822T134015.jsonl`, **exit code 0**.

| cell | reps_ok | frozen_fp (i) | negative_fp (ii) | forbidden (iii) | entity_in_prompt (reverse) | narration | other |
|---|---|---|---|---|---|---|---|
| **old** s6 | 5 | **1/5** | 0/5 | 1/5 | 0/5 | 5/5 | 5/5 |
| **new** s6 | 5 | **0/5** | 0/5 | 1/5 | 0/5 | 5/5 | 5/5 |
| **old** s8 | 5 | 0/5 | 0/5 | **5/5** | 0/5 | 0/5 | 5/5 |
| **new** s8 | 5 | 0/5 | 0/5 | **5/5** | 0/5 | 0/5 | 0/5 |
| **old** s9 | 5 | **5/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| **new** s9 | 5 | **0/5** | **0/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| **old** s9-syn | 5 | 0/5 | 0/5 | 0/5 | **0/5** | 0/5 | 0/5 |
| **new** s9-syn | 5 | 0/5 | 0/5 | 0/5 | **5/5** | 0/5 | 0/5 |

- **False positive (i) — frozen descriptor / `entity_visible`: `old` 6/15 reps over the three live scenes → `new` 0/15.** Zero in every cell. The self-check passed on its own terms: `old` reproduced class (i) by **strict majority on scene 9 (5/5)**, so the harness demonstrated it can detect the thing the edit removed before crediting `new = 0`.
- **False positive (ii) — the `negative_prompt` removal demand — `old` 1/15 → `new` 0/15.** Quotable from the transcript: *"…their `negative_prompt` fields contain \"person, human figure, character, silhouette of a person\", which conflicts with casting the entity"* → correction *"…and remove character-excluding terms from negative_prompt when SCP-049 is present."* Low frequency, so this clause is justified by one reproduction plus the architecture, not by a strong before/after signal.
- **The forbidden-term rule did not move: `old` 6 hits → `new` 6 hits** over the live cells, with scene 8 at **5/5 on both** versions (every rep names `S00801` and quotes "soft dark blur"). The 11-term list is a strict superset of the old 6, so the axis cannot lose coverage by construction; this measures that it did not lose it in practice either.
- **The reverse-direction rule is real, and it is new**: on the synthetic input (entity prose + `SCP-049` designator injected into `S00900.image_prompt`, **every other shot untouched**) `old` flagged it **0/5**, `new` **5/5**. The false positive did not vanish by the rule going silent — the rule flipped. Before this edit the pipeline had **no** check in *either* direction against an entity leaking into a background plate.
- **§4's narration teeth: 5/5 on both versions.** The live narration-vs-descriptor contradiction (narration says SCP-049 has "장갑도 끼지 않은" bare fingers; frozen descriptor says "dark gloves") fires in every rep of both versions after §4 was scoped to narration + `cast`. An earlier replication showed a 9/9 → 8/9 dip; at reps 5 there is none, so that dip was sampling noise.
- **`other`** is invented-content / certainty-escalation findings about the ceramic mask, plus narration `corrections[]` entries. Not this story's axis.

### The forbidden-term gate criterion was wrong, and that is what FALSIFIED once

An earlier headline run at `--reps 3` exited **1 (FALSIFIED)** claiming the edit
killed the forbidden-term rule on scene 6 (`old` 2/3 = majority, `new` 1/3 = not).
It had not. The gate compared **per-cell strict-majority membership**, and scene 6's
true detection rate is roughly 10–25% on *both* versions, so at small `reps` it
crosses the 50% line at random — the denser n=9 diagnostic below read the same cell
as `old` 1/9 vs `new` 2/9, direction reversed. This is the same finding
`PROMPT_POLICY.md` records for Story 6.10: a single-trial zero-tolerance criterion
makes a gate un-passable by noise alone, and the fix is to change the criterion, not
the thing being measured.

The gate now tests the axis at its real unit — **the run-level hit total must not
regress**, plus a cell that goes from a majority to a flat **zero** is still a kill.
At reps 5 that reads `old 6 → new 6`, and scene 8 holds its majority on both sides.
No prompt wording was re-tuned to clear the gate: chasing a 1/9→2/9 base rate would
be tuning the reviewer's detection *sensitivity*, which this story's spec puts out of
scope.

### Denser diagnostic on scene 6 (n=9)

Because the only FALSIFIED gate was a 1-rep difference at n=3, scene 6 was
re-measured at `--reps 9` (`--scenes 6`, 36 calls, 0 failures, transcript
`transcript-20260822T132905.jsonl`). This is a diagnostic, not the headline:

| cell | reps_ok | frozen_fp | negative_fp | forbidden | entity_in_prompt | narration |
|---|---|---|---|---|---|---|
| old s6 | 9 | **3/9** | 0/9 | **1/9** | 0/9 | 9/9 |
| new s6 | 9 | **0/9** | 0/9 | **2/9** | 0/9 | 9/9 |
| old s6-syn | 9 | 3/9 | 0/9 | 4/9 | **0/9** | 8/9 |
| new s6-syn | 9 | 0/9 | 0/9 | 0/9 | **9/9** | 9/9 |

At n=9 the forbidden-term finding on scene 6 is **1/9 old vs 2/9 new** — a
low-base-rate detection on *both* versions, `new` marginally higher. The n=3
FALSIFIED verdict was noise on that base rate, not a killed rule. The diagnostic
also reproduces class (i) at 3/9 on `old`/0/9 on `new` and the reverse-direction
control at 0/9 → 9/9 on a second scene. Its own exit code is **3 (inconclusive)**
by design: scene 9 was not in this run, and 3/9 is not a strict majority, so the
harness refused to call it a pass.

### Superseded replications (kept, not deleted)

Four screening replications were run in total. **Three are superseded and none of
their numbers appear above.** Two earlier replications (R1/R2, 2026-08-22 morning)
and a third (R3) ran with two *different* classifier versions, and their aggregated
`/9` table published a `old s9` figure of 5/9 in the headline while its own caveat
said 6/9 — a summary that disagreed with its own footnote. They are recorded as
having happened and are not carried forward.

The fourth, `transcript-20260822T132325.jsonl`, is the **same script** as the
headline run with an earlier classifier. Its 24 samples were re-tallied with the
shipped classifier and agree with the headline: `old` s9 frozen_fp 3/3 → `new` 0/3;
`old` s8 negative_fp 1/3 → `new` 0/3; `new` s9-syn entity_in_prompt 3/3 vs `old`
0/3; `new` s8 forbidden 3/3. One cell had `reps_ok` 2 (`new` s6, one
`YAML ScannerError`), which is why it is not the headline run.

### Classification note (two blind spots this screening itself found)

The classifier was corrected twice, both times because a transcript entry
disagreed with its bucket — which is the entire reason the transcript is written:

1. **Polarity was read off the remedy.** "…the `image_prompt` contains explicit
   entity prose … `image_prompt` must remain background-only and **free of** entity
   details" is a *presence* finding whose own sentence prescribes an absence. It
   dropped 2 of 3 reverse-control reps into `other` and made the control look 1/3
   when it was 3/3. Polarity is now measured on the claim fields only
   (`description`/`explanation`/`original`), with prescriptive clauses (`must`,
   `should`, `needs to`, …) stripped.
2. **"none of the image prompts include the descriptor"** was not an absence
   phrase, so a real class-(i) false positive was tallied as the reverse-direction
   finding — the exact confusion of the defect the edit removes with the finding it
   adds. `none of` / `neither` are now absence patterns.

Both are pinned in `_selftest()` with the real transcript strings (14 cases,
`--selftest`, no LLM). Two known residual imprecisions, stated rather than fixed:
`old s9 rep3`'s `corrections[]` entry, which *adds* the descriptor to
`image_prompt`, buckets as `entity_in_prompt` (it is the false positive's remedy,
not the reverse finding) — it lands on `old`, and the reverse-direction gate reads
`new` only; and a class-(i) false positive phrased *purely* as a prescription would
degrade to `other`, which errs toward inconclusive rather than toward a pass.

## 4. The run's original 4 warnings, adjudicated

All four were `type: descriptor_violation`, `severity: warning`, and all four are
the **pass-2** review's output (see §6).

| # | scene | original text (run 4b35c0ed) | verdict | under new prompt (headline run) |
|---|---|---|---|---|
| 1 | 6 | image prompts for shots 3, 4, 6 contain forbidden term "dark" ("dark red-black fluid", "dark smear pattern", "dark smear dragging") | **GENUINE** | 1/5 new, 1/5 old — identical. A weak detection on **both** versions (n=9 diagnostic: 2/9 new vs 1/9 old). Not lost, never strong — §5 |
| 2 | 8 | "entity_visible is set to true for Scene 8, but the stage 3.5 image prompts omit the required SCP-049 frozen descriptor" | **FALSE POSITIVE** | **0/5 on new.** The old prompt did not reproduce it on scene 8 in this run either (0/5) — it reproduced the same class on scene 9 (**5/5**) and on scene 6 (1/5, and 3/9 at n=9) |
| 3 | 8 | image prompt 2 contains forbidden term "dark" ("soft dark blur") | **GENUINE** | **5/5 on new**, 5/5 on old — every rep of both versions names S00801 and quotes "soft dark blur" |
| 4 | 9 | "Scene 9 has entity_visible set to true, but the visual prompts … omitted the SCP-049 Frozen Descriptor … and included character terms in negative_prompt", correction demanding "remove 'person, human figure, character, silhouette of a person' from negative_prompt" | **FALSE POSITIVE** | **0/5 on new, on both halves.** `new s9` emitted **zero entries at all** in all 5 reps. The old prompt reproduced the frozen half **5/5** and the `negative_prompt` half 1/5 |

## 5. Contrary and inconclusive results (kept, not deleted)

- **A previous headline run exited 1 (FALSIFIED) and the gate criterion, not the
  edit, was at fault.** At `--reps 3` scene 6's forbidden-term cell read `old` 2/3 vs
  `new` 1/3 and the per-cell majority gate called it a killed rule. The n=9 diagnostic
  inverts it (`old` 1/9, `new` 2/9) and the reps-5 headline reads them equal (1/5 each)
  — the cell's base rate is ~10–25% on both versions, so a 3-rep majority comparison
  there is a coin flip. The criterion was replaced (run-level total regression + a
  majority→zero kill) and the run now exits 0. **No prompt wording was re-tuned to
  clear it** — that would be tuning detection sensitivity, which the spec excludes.
  Both the original FALSIFIED transcript and the fix are kept; this is a case where
  the harness lied and the prompt did not.
- **Class (i)'s reproduction is scene-dependent.** In the headline run the old prompt
  produced it on scene 9 at 5/5 and on scene 6 at only 1/5, never on scene 8 (0/5); at
  n=9 it produced it on scene 6 at 3/9. A single 3-rep cell on the wrong scene would
  have shown the old prompt clean and made the fix look like it fixed nothing — which
  is exactly what the harness's own inconclusive exit exists to refuse.
- **Class (ii) is barely reproducible: 1/3 of old-prompt scene-9 reps** (and 1/3
  in the superseded fourth replication, on scene 8). It fired once in the live run
  and rarely here, and never on the new prompt. It is a low-frequency elaboration of
  (i), consistent with the spec's diagnosis that the demand came from *missing
  architectural information* rather than from any rule in the prompt — no line of the
  old prompt asked for it. Honest consequence: **clause (b) is justified by a
  reproduction plus reasoning, not by a strong before/after signal.** Clause (a) is
  justified by measurement.
- **`old s9-syn` scored 1/3 frozen_fp and 0/3 on the reverse finding.** Handed a
  plate that *does* name the entity, the old prompt complained that the prose
  "paraphrases SCP-049's appearance rather than using the exact Frozen Descriptor
  string" — i.e. it read the injected defect as insufficient compliance. That is the
  absence of any reverse-direction check before this edit, and it is a standing
  finding about the old prompt, not about this fix.
- **§4's narration finding did not weaken**: 5/5 on both versions in the headline
  run, 3/3 at n=3, 9/9 at n=9. Scoping §4 to narration + `cast` did not cost the
  live rule. One superseded replication showed 9/9 → 8/9; the denser and the newer
  measurements both say that was sampling noise.

## 6. Cost of a false positive — the mechanism, corrected

The first version of this section claimed the two false positives "bought two
rewrite passes". **That is falsified by the run's own record**, which says
`review_overall_pass: true`, `critic_verdict: "retry"`, `final_pass_index: 2`.
`scenario.py:859` reads `if critic["verdict"] == "retry" or not review["overall_pass"]`,
so warning-severity issues under a passing review **cannot trigger the repair at
all**. The pass-2 repair was bought by the **critic**.

What the false positives actually did is **widen an already-triggered repair's
scope**, which is a different and stronger claim:

- `_retry_scope` (`scenario.py:216-252`) folds `review["issues"][].scene_num`
  into the repair index set **alongside** `critic["scene_notes"][].scene_num`.
- The critic's notes named scenes **1, 4, 6, 7**. The review issues named scenes
  **6, 8, 9**. The union is **{1, 4, 6, 7, 8, 9}**.
- So the two false positives added **scenes 8 and 9** — two scenes that were fine
  got their narration regenerated and *all* their shots re-derived.

The unit was wrong too: `writing_scene_repair_step` is **one** call over the whole
index subset, not one per scene, so a widened scope does not buy "a rewrite pass".
The per-scene cost is `_breakdown_for` (`scenario.py:728-740`), which runs
`cast_decision_step` + `visual_breakdown_step` **per added index** — two LLM calls
per spurious scene, plus that scene's regenerated narration flowing into the
pass-2 review and critic.

**What is unrecorded:** the persisted `review_issues` are the **pass-2** review's
output (`_repair_and_review` reassigns `review` before the state is written), so
whether the pass-1 review — the one that actually fed `_retry_scope` — named the
same scenes 8 and 9 is not on the record. The scene-8/9 warnings survived into
pass 2 unchanged, which is consistent with the pass-1 review having carried them,
but consistency is not evidence and this is not asserted.

## 7. Shipping

- Headline run: 24/24 screening calls returned parseable payloads; no cell was
  dropped or estimated. Diagnostic run: 36/36.
- Seeded via the DEV MODE path:
  `uv run python scripts/migrate_prompts.py --label production --source prompts` →
  `created: scenario/review` (1 created, 19 skipped, 0 failures).
- Verified **by the name the runtime asks for**, not the name the seeder printed:
  `scenario_chain.py:3025` is the only `get_prompt("scenario/review")` literal, and
  `prompt_service.get_prompt("scenario/review")` returns **version 11, labels
  `['production', 'latest']`**, carrying `background-only` ×2, the `Exempt from that
  rule` clause, the `Do NOT report` clause and the correction-channel clause, and
  **not** carrying the stale sentence.
- **Not byte-equal, by one byte, and the reason is known**: `migrate_prompts.py:86`
  `.strip()`s the file, so the shipped body is the repo file minus its trailing
  newline. Equality holds after `rstrip("\n")`. (Version 10's report claimed
  "byte-equal"; it was not, for the same reason.)
- **Correction to the spec's verification command**:
  `GET {host}/api/public/v2/prompts/scenario/review?label=production` returns
  **404** — the slash in the prompt name must be percent-encoded. Use
  `…/api/public/v2/prompts/scenario%2Freview?label=production`. A raw-slash 404
  read as "not seeded" would have been the mirror image of
  `gotcha_langfuse-prompt-name-families-differ`: a true ship reported as a failure.

## 8. Guards added

`tests/pipeline/nodes/test_scenario_chain.py`:

1. `test_review_prompt_carries_the_background_only_contract` (6 pins) — the rule, the exemption, the `descriptor_violation` token, the `entity_visible` definition.
2. `test_review_prompt_dropped_the_pre_recompose_descriptor_rule` — the **reverse** pin: the stale sentence must be absent.
3. `test_review_prompt_has_no_paraphrase_of_the_stale_descriptor_rule` — a **shape** pin. Wherever `review.md` mentions `entity_visible` within ~120 chars of the frozen descriptor, the window must not carry requirement phrasing (`must`/`should`/`verify`/`… is present`). An exact-string pin passes against any paraphrase, and a prompt is prose.
4. `test_visual_breakdown_still_issues_the_contract_the_reviewer_enforces` (2 pins) — the **generator side**. The reviewer now enforces a contract only `visual_breakdown.md` issues; deleting it there would leave the reviewer policing an instruction nothing produces, and until now no test would have noticed.
5. `test_the_two_prompts_forbid_the_same_generic_terms` — parses the forbidden-term line out of **both** files and asserts set equality, with a floor of 11 rather than an equality (an honest 12th term added to both files must not fail) and a quoted-term pattern that no longer goes blind on a hyphenated, capitalised or non-ASCII term. A missing file **fails** instead of skipping, and the path comes from `_prompt_text` rather than a second hand-rolled copy: a rename that turns the story's only cross-file guard green is the same defect class as the drift itself.

Plus `screen_review_prompt.py --selftest`: 14 assert-based classifier cases,
including every bucket, the double-assigning class-(ii) string, and a compliance
statement phrased as negated presence.

## 9. 이 스토리가 검증하지 않은 것

- **신규 양성 규칙(`:63`)의 오탐률.** 측정은 이 런의 씬 6·8·9와 합성 통제뿐이다. 같은 런의
  **나머지 6개 씬은 스크리닝하지 않았다** — 배경 전용 위반을 새로 보고하기 시작한 규칙이
  그 6개 씬에서 몇 건을 만드는지는 미측정이다.
- **`:64` 면제 절 자체가 미측정.** 사진 속 인물·마네킹·미착용 의복·카메라 어휘가 들어간
  `image_prompt`을 합성해 신 프롬프트가 침묵하는지 확인하지 않았다. 면제는 문헌(
  `gotcha_person-token-regex-is-unusable-on-image-prompt`)과 14.4의 2026-08-22 결정에
  근거한 예방책이고, 실측이 아니다.
- **clause (a)는 주입된 `entity_visible`에서만 시험되었다.** 체크포인트에 그 필드가 없어
  `--entity-visible true`로 재구성했다. 라이브 `writing_step` dict의 실제 값·형태와
  바이트 단위로 같다는 보장은 없다.
- **pass-1 리뷰의 지적 목록.** §6의 마지막 단락 — 실제로 `_retry_scope`를 먹인 pass-1
  리뷰가 씬 8·9를 지목했는지는 상태에 남아 있지 않다.
- **라이브 재실행.** 신 프롬프트로 전체 시나리오 체인을 돌린 런은 아직 없다. 스크리닝은
  렌더 전 텍스트 판정이고 그것이 이 스토리의 범위다(GPU 0).
