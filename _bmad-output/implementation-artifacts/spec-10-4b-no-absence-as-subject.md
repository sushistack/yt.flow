---
title: 'Story 10.4b — never ask the renderer to draw an absence (지적 2)'
type: 'feature'
created: '2026-08-11'
status: 'blocked'
baseline_revision: '9b460d5'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/research/technical-narration-image-semantic-alignment-2026-08-10.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-4-live-validation/README.md'
  - '{project-root}/_bmad-output/implementation-artifacts/13-2-live-validation/README.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** 12 of 66 frames in run `8a9a288b` are unreadable — a viewer cannot say where they are or what happened (Jay's 지적 2). **The recorded cause is half wrong, and this spec corrects it from the row data:** only 5 of the 12 prompts actually make an absence the subject (`vast empty concrete floor`, `a blank wall surface`, `close-up of open air`, `blank wall section … with nothing on it`, `large swath of empty concrete floor`), with S00303 borderline. The other 6 already have concrete subjects — a steel cot frame with loose restraints, a cinder-block wall with contact-wear and a crack, a retracting blast door, a chrome instrument tray, a cracked observation window, a sealed blast door — and are unreadable anyway. What all 12 share is `event: "unclear"`, and 8 of 12 blind-read as "corridor" regardless of what the prompt asked for. `readable` requires place **and** event, so the second half fails on a missing legible event, not on an absence.

**Approach:** One requirement with two halves, expressed as a demand rather than as accumulated prohibitions: a frame's subject must be an **existing** object/surface/**trace**, and the frame must carry at least one legible trace of *this sentence's* event. Both are prompt-side; the prompt currently teaches the opposite in three surviving places. Separately, a sentence with no renderable referent must fold into a neighbouring shot's span instead of minting its own background — the parser already supports an ordered cover, and it is the prompt that forbids it.

## Boundaries & Constraints

**Always:**
- **Control by requirement, not by accumulation.** No new negative-prompt clauses (`gotcha_negative-prompt-overstuffing`: per-defect negatives wrecked renders twice). No regex scrub of `image_prompt` (`gotcha_person-token-regex-is-unusable-on-image-prompt`; Story 10.2 built a clause-scrubber, replayed it on the 313-shot corpus, found it damaged 27, and deleted it — `scenario_chain.py` is byte-identical to baseline on that point).
- **The primary axis is the boolean `readable` from `scripts/score_shot_narration.py`.** Baseline: **12/66 = 18.2 %**.
- **Pre-register the pass/fail rule and the strata before looking at any score** (10.4 §12's discipline). Write it into the evidence README first, then run.
- **Judge the RATE, never the count.** Folding a sentence into a neighbour removes a frame, so an unreadable count falls mechanically while the rate can worsen — 10.4 measured exactly that (16→15 count but 24.2 %→27.3 % rate). Report `n_shots` beside every rate.
- **Report the two strata separately** — the ~5–6 absence-as-subject rows and the ~6 concrete-subject rows. A pooled 12→9 is uninterpretable; stratified, it says which half moved.
- **A same-prompt control leg is mandatory.** 10.4's control moved −0.267 with per-shot sd ≈ 1.4, i.e. the same size as its measured effect. Without a control this story cannot distinguish a fix from a reseed.
- Prompt edits follow `docs/PROMPT_POLICY.md`. DEV MODE is on, so seeding is direct: `uv run python scripts/migrate_prompts.py --label production --source prompts` — **`--source prompts`, never `prompts/scenario`**, or the stage prefix is dropped and a stray `visual_breakdown` prompt is created (Story 8.10).

**Block If:**
- ComfyUI cannot be brought up, or renders fail on more than 10 % of the slate — a partial slate is not a comparison.
- The re-rendered legs cannot be paired by sentence (e.g. `split_sentences` yields a different sentence count for the same narration) — pairing is what makes the two legs comparable at all.

**Never:**
- Do not touch the 6.12 A/B promotion gate, `YTFLOW_ALLOW_AB_GATE`, or the `CLAUDECODE`/`AI_AGENT` guards, and do not run `eval_prompts.py --baseline` (Story 8-12 precedent). Judgement here is the offline axis, not the gate.
- Do not re-open mapping as a semantic-match lever. 10.4 killed it: a hand-authored cover moved `match` by exactly 0.000. Scope ② is narrow — a sentence with **no renderable referent** may fold into a neighbour; it is not general cover freedom, and **no cover-quality gate may be built** (10.4's explicit handoff).
- Do not change the instrument. `scripts/score_shot_narration.py`'s contract was closed by 13.2; use it as-is.
- Do not use `dsg_score` as a gate or invent a threshold for it. It is rank-uncorrelated with the old axis (0.0263), scores *higher* on unreadable frames (0.5694 vs 0.4892), and 48 % of its values sit at 0.0/1.0. Record it for per-proposition attribution only.
- Do not "fix" background source reuse or derive per-shot variants from one plate (Epic 10's background policy — reuse is intent).
- Do not enable `shot_recompose_enabled` (10.1c stays default off; its flip is a separate decision) or `depth_placement_enabled`.
- Edit only the Story 10.4b entries in `epics.md` / `sprint-status.yaml`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Sentence with a renderable referent | "격리실 문이 열리고…" | One shot; subject is an existing object/surface/trace; ≥1 legible trace of this sentence's event | — |
| Sentence whose subject is purely a body/state | "아주 협조적으로요.", "그는 진심으로 보고 있습니다." | Folded into a neighbouring shot's span (`sentence_end` extended). No new background minted, no absence-subject prompt | — |
| Leading referent-less sentence (nothing before it) | Scene's first sentence is referent-less | Handled in the PROMPT, not by new code: the first shot simply opens with a wider span (`sentence_start: 1, sentence_end: 2`), which the ordered cover already accepts. Code keeps its backward-only merge; the only change is that its `_fallback_prompt` text must stop naming an absence | Backfill still fires if the model emits an empty first prompt anyway — recorded, never silent |
| Model emits an absence-subject prompt anyway | `image_prompt` = "vast empty concrete floor…" | Accepted and rendered — no code-side rejection. Detected by measurement, reported as residual non-compliance | Never a regex scrub or a hard reject |
| Model emits more shots than sentences | cover ceiling exceeded | Existing parser raises and the error is fed back via `{{parse_error}}` (unchanged) | Retry, then fail the stage |
| Every shot in a scene referent-less | pathological | Existing `no shots produced after merge` guard still raises | Unchanged |
| Same narration, both legs | control vs candidate | Identical sentence count and identical pairing keys, so every sentence pairs | HALT if pairing breaks |

</intent-contract>

## Code Map

- `prompts/scenario/visual_breakdown.md` (395 lines) — **the whole deliverable for ① and ②.** Three surviving absence-teachers: line **109** (`Don't show "nothing." Show an EMPTY frame that feels WRONG`), lines **114–115** (`Use negative space as a storytelling tool` / `Large empty areas … An empty hallway stretching to a vanishing point. The space where something SHOULD be but isn't`), and line **330** (the self-check *mandates* negative space). Story 10.2 already deleted one bullet here ("A figure small in an enormous space" → an overturned chair); the rest survived. Lines **191–199** already model the correct form (an empty pedestal *with scratch marks*, a blood *trail*, a *marked spot*) and lines **197–199** already half-state the requirement. The 8-slot section **68–104** carries the right BAD/GOOD idiom to promote into a hard rule (slot 2 line 81 `BAD: "an empty chair"`, slot 3 line 85 `BAD: "the room is empty"`). Line **371** ("empty `cast` → write a pure environment/atmosphere shot") is the third leg of the collision. For ②: lines **63**, **65**, **336**, **337** mandate a strict bijection and **340** tells the model to signal a skip with `image_prompt: ""`.
- `_bmad-output/implementation-artifacts/10-4-live-validation/prompt_cover.md` — 10.4's reverted N:M cover wording, preserved. Reuse the parts that worked; **do not** reinstate a general cover mandate.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (2562 lines) — parser side, mostly unchanged. `visual_breakdown_step`:**1873**, its `parse` closure **1890–1949** already enforces the ordered cover (ceiling **1899**, range **1926**, no-backtracking **1931**, full coverage **1943**) and does **no** `image_prompt` content check. `build_scenes`:**2476**; `sentence_indices` expansion **2504–2513**; the empty-prompt seam **2514–2524** merges **backward only** (`shots[-1]`) and otherwise backfills via `_fallback_prompt`:**2460**, whose text ends in `"no visible subject"` — **itself an absence subject, and a member of `_NO_FIGURE_FRAMINGS`:319**. `split_sentences`:**579**. Validators that run over shots (**2543–2545**): `_enforce_camera_variety`:250, `_suppress_cast_on_no_figure_framing`:323 (reads `image_prompt`, vetoes only `cast`), `_enforce_cast_diversity`:381 — none may reject or rewrite a prompt.
- `scripts/score_shot_narration.py` — the instrument, unchanged. `--dsg` writes `<workspace>/<run>/visual_score.json`; `readable` is the boolean, `MIN_MATCH`/`MIN_MATCH_HOOK` unchanged.
- `_bmad-output/implementation-artifacts/10-4-live-validation/run_ab2.py` — the two-leg re-render harness to clone: re-runs `visual_breakdown` per scene, renders fresh plates, scores, and pairs **by sentence** (`--pair-by sentence`), with the old leg read via `git show 3869f95:`.
- `_bmad-output/implementation-artifacts/10-4-live-validation/baseline_v2.json` — the 12 unreadable shot ids and their prompts; the stratum assignment in Intent comes from here.
- `tests/pipeline/nodes/test_scenario_chain.py` (5077 lines) — `test_visual_breakdown_prompt_file_has_required_placeholders`:**220** is the only thing constraining prompt edits (8 placeholders, no content rules). Empty-prompt behaviour is pinned at **2817**, **2872**, **2905**, **2933**, **3499**, **3519**; cover behaviour at **1508–1644** and **2839–2890**.
- `docs/PROMPT_POLICY.md` — DEV MODE banner, Rules 3/4 SUSPENDED, Rules 1/2/5 live. Live `scenario/visual_breakdown` is **v14** per the repo record and equals the current file (10.4's two experiments were rolled back, never seeded).

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/10-4b-live-validation/README.md` -- **write the pre-registered rule and the strata FIRST, before any render or score.** Fix: primary axis (`readable`, paired per sentence), the **paired discordant-pair test** (`b`, `c`, exact binomial over `b+c`) rather than a comparison of two independent rates, the seed/no-seed rule, the two strata with their shot ids, the control leg, and the count-vs-rate trap. -- a rule written after seeing scores is not a rule, and an unpaired rate at n=66 could only see a 6-frame change.
- [x] `prompts/scenario/visual_breakdown.md` -- scope ①: replace the three absence-teachers with one positive requirement in the idiom the file already uses at 191–199 — the frame's subject is always an existing object, surface or trace, and the frame carries at least one legible trace of *this sentence's* event. Delete/rewrite line 109's "show an EMPTY frame", lines 114–115's negative-space bullet, and line 330's checklist item that mandates negative space; promote slot 2/3's BAD/GOOD pairs into the requirement; reconcile line 371. **Net instruction count must not grow** — this replaces text, it does not append to it. -- the renderer cannot draw an absence, so it must never be asked to.
- [x] `prompts/scenario/visual_breakdown.md` -- scope ②: narrow the bijection mandate (63, 65, 336, 337, 340) so that a sentence with **no renderable referent** extends a neighbouring shot's `sentence_end` instead of emitting `image_prompt: ""` or a new background. Keep the shot-count ceiling. Borrow only the parts of `prompt_cover.md` that serve this case; do **not** reinstate a general cover mandate. -- the parser has accepted an ordered cover since 10.4; only the prompt forbids it.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `_fallback_prompt` (2460) currently ends in `"no visible subject"`, which is the exact defect this story removes, and lands the shot in `_NO_FIGURE_FRAMINGS`. Rewrite it to name an existing surface/trace from scene context. **Keep the backward-only merge and do NOT implement forward merge** — it needs a lookahead over shots that are built in order, and the case it serves (a scene's *first* sentence being referent-less, with the prompt now instructed to extend a neighbour's span anyway) is rare enough that the fallback text fix covers it. Mark the ceiling with a `# ponytail:` comment naming forward merge as the upgrade path if the case is ever measured. -- a code-side absence subject would survive every prompt fix.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- extend the prompt-file test (220) to pin the new positive requirement's presence and the absence of the removed absence-teachers, in the style of the existing `assert "pose_hint" in content`. Update the empty-prompt tests (2817, 2872, 2905, 2933) for whatever `_fallback_prompt`/forward-merge decision was made, with the reason in a comment. -- otherwise the next session silently reinstates negative space.
- [x] `_bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py` -- clone `run_ab2.py`: two legs over all 9 scenes of the same SCP-049 narration (old leg via `git show <baseline>:prompts/scenario/visual_breakdown.md`), fresh renders both legs, score with `scripts/score_shot_narration.py --dsg --pair-by sentence`, and emit a per-stratum table plus rate-with-`n_shots`. -- one command must reproduce every number.
- [ ] Live run -- bring ComfyUI up **with `setsid` for full detachment** (`gotcha_comfyui-and-env-operational`; never `pkill -f`), run both legs, then score. Record renders attempted/succeeded. -- the story closes on rendered evidence, not on wired code.
- [ ] `prompts/` seeding -- **only if the pre-registered rule passes**: `uv run python scripts/migrate_prompts.py --label production --source prompts`. If it fails, revert the prompt file to the baseline commit and record the non-promotion, exactly as 10.4 did twice. -- a lost A/B is a result, not a reason to seed.
- [ ] `_bmad-output/planning-artifacts/epics.md` + `_bmad-output/implementation-artifacts/sprint-status.yaml` -- record the outcome in the **Story 10.4b entries only**, and correct the epic's "그 12장의 `image_prompt`는 전부 부재를 주제로 삼는다" claim to the measured 5–6 of 12. -- an overstated premise in the canonical doc will be re-inherited.

**Acceptance Criteria:**
- Given the pre-registered rule written before any scoring, when both legs are scored on the same sentences, then the candidate's `readable` **rate** is reported against the 18.2 % baseline together with `n_shots` for each leg, and the seed/no-seed decision follows the rule as written rather than the result.
- Given the two legs share one narration, when the verdict is computed, then it comes from the **paired** discordant counts (`b` = unreadable→readable, `c` = readable→unreadable) with an exact binomial over `b+c`, not from comparing two independent rates — and `b` and `c` are both reported, so the cost of the change is visible next to its benefit.
- Given the two strata, when results are reported, then the absence-as-subject rows and the concrete-subject rows carry separate rates, so a partial improvement is attributable rather than pooled.
- Given the same-prompt control leg, when its movement is compared to the candidate's, then the candidate's effect is reported as detectable only if it exceeds the control's own movement — and if it does not, that is recorded as "not measurable", not as a failure of the change.
- Given a narration sentence with no renderable referent, when the scenario stage runs, then no new background is minted for it and it appears in a neighbouring shot's `sentence_indices`.
- Given the rendered candidate frames, when `image_prompt` texts are inspected, then residual absence-as-subject prompts are counted and reported as non-compliance rather than scrubbed.
- Given the prompt file after the edit, when the suite runs, then the placeholder test still passes and the new content assertions pin both the added requirement and the removed absence-teachers.

## Spec Change Log

## Review Triage Log

## Design Notes

**The premise correction is the most important thing in this spec.** `epics.md` says all 12 unreadable prompts make an absence the subject. The row data says otherwise:

| stratum | shot ids | prompt subject |
|---|---|---|
| absence-as-subject | S00204, S00300, S00304, S00305, S00805 (+S00303 borderline) | `vast empty concrete floor`, `a blank wall surface`, `close-up of open air`, `blank wall section … nothing on it`, `large swath of empty concrete floor` |
| concrete subject, still unreadable | S00201, S00202, S00400, S00707, S00804, S00900 | steel cot frame + loose restraints; cinder-block wall + contact-wear halo + crack; retracting blast door; chrome instrument tray; cracked observation window; sealed blast door |

The research document was honest about this (its keyword measurement was 29 % vs 11 %, explicitly labelled weak and "a hint, not proof"); the epics summary hardened it into "전부". So **scope ① has a ceiling of about 6 of 12**, and a pooled result would hide that. What all 12 share is `event: "unclear"`, and 8 of 12 blind-read as "corridor" — which is why the requirement has a second half about a legible trace of the event. `S00202` is the clearest case: its prompt already obeys the absence rule perfectly (a wall, a contact-wear halo, a crack) and it still reads as a texture study with no event.

**Why a demand and not a prohibition.** Two prohibitions have already backfired here — per-defect negative clauses (twice) and the regex clause-scrubber (27 of 313 shots damaged, then deleted). The prompt file already contains the working idiom at lines 194–196: *an empty pedestal **with scratch marks where it stood***, *a blood **trail** leading to a corner*, *a **marked spot** on the floor*. Each names an existing thing that carries the absence. Generalising that is the whole of scope ①, and it is a replacement rather than an addition — net instruction count must not grow.

**Scope ② is prompt-side, and its trap is arithmetic.** The parser has validated an ordered N:M cover since 10.4 (ceiling, range, no-backtracking, full coverage) and `build_scenes` already folds an empty-prompt span backward. The prompt is what still commands `sentence_start == sentence_end`. Folding removes frames, so:

```
10.4 PASS B, measured:  unreadable 16 → 15   (count improved)
                        rate      24.2% → 27.3%   (rate worsened — 11 fewer renders)
```

That is why the rule is on the rate. Note also the asymmetry: today's merge is backward-only, so a referent-less sentence that *opens* a scene cannot fold and instead gets `_fallback_prompt`, whose text ends in `"no visible subject"` — a code-side instance of exactly this story's defect.

**The test must be PAIRED, or this round is underpowered like 10.4's.** `readable` is a boolean at n≈66. Comparing two independent rates, the 95 % interval around a baseline of 0.18 is roughly ±0.09 — about ±6 frames — so an unpaired design can only see a change of 6 or more of the 12. That is the trap 10.4 fell into with 15 slots, and it must not be repeated by accident.

The design that escapes it is already available: both legs run the **same narration**, so every sentence appears in both and the comparison is paired. On paired booleans the informative quantity is the **discordant pairs only** — sentences that flipped unreadable→readable versus readable→unreadable — which is McNemar's test, and it ignores the large block of sentences that were readable in both legs. Pre-register it that way:

```
b = unreadable in control, readable in candidate      (the win)
c = readable in control,  unreadable in candidate     (the cost)
report b, c, and the exact binomial p over b+c        # no normal approximation at these counts
```

With `b + c` likely in the teens, an exact binomial is the honest test and a handful of clean flips is already evidence. Pair on the **sentence**, not the shot id — once a cover may fold sentences, two legs share no shot slots (13.2's `--pair-by sentence` exists for exactly this).

## Verification

**Commands:**
- `uv run ruff check src/ scripts/ tests/` -- expected: clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/` -- expected: 0 failures; baseline is **2668 passed, 1 skipped** at `9b460d5`; only the prompt-content and empty-prompt tests should change count.
- `uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py` -- expected: both legs render ≥90 % of the slate, every sentence pairs, per-stratum rates and `n_shots` written to JSON.
- `uv run python scripts/score_shot_narration.py --run <leg-run-id> --dsg --json out.json` -- expected: 0 errored rows; `readable` rate and per-proposition attribution recorded.
- `uv run python scripts/migrate_prompts.py --label production --source prompts` -- **only on a pass.** Expected: `scenario/visual_breakdown` version increments from 14.

**Manual checks (if no CLI):**
- The evidence README's pre-registered rule must be committed (or at least written) **before** the scoring run, and its git/file timestamp should precede the result JSONs. If that ordering cannot be shown, the rule is not pre-registered and the run's verdict is worth less.
- Inspect 3–4 candidate `image_prompt` texts for the previously-absence rows (S00304, S00305, S00805) by eye: the subject should now be a nameable thing.

## Auto Run Result

Status: **blocked**
Blocking condition: **GPU contention — another producer holds ComfyUI, so the live A/B cannot
complete.** 3 of 129 frames rendered in 40 minutes. My plate renders take ~16 s each, but a
character workflow (`IPAdapterAdvanced` + `InspyrenetRembg`) runs continuously on the same
instance at ~306 s per job and my jobs queue behind it. `/queue` sampled three times, 20 s
apart: `running: CHARACTER, pending: plate` every time; `api2` contains neither node type, and
no other process from this checkout is running. The run was stopped rather than left to
contend for ~6 hours.

### What is complete and verified

- **Prompt scope ①** — three surviving absence-teachers removed (the negative-space section,
  "show an EMPTY frame that feels WRONG", the checklist item that *mandated* negative space)
  plus the cast-empty guidance tightened, replaced by one positive requirement: the subject is
  always a nameable object/surface/trace that exists, and the frame carries a legible trace of
  this sentence's event.
- **Prompt scope ②** — the strict bijection narrowed so a referent-less sentence widens a
  neighbour's span; the shot-count ceiling kept.
- **`_fallback_prompt`** — no longer ends in `"no visible subject"` (a code-side absence subject
  that also matched `_NO_FIGURE_FRAMINGS`, so a placeholder phrase silently stripped the shot's
  cast). Forward merge deliberately not implemented; `# ponytail:` marks the ceiling.
- **4 new tests** pinning the added requirement, the *removal* of each absence-teacher by exact
  phrase, the cover instruction with its ceiling, and the fallback text.
- **Pre-registration committed in `25bed30` before any candidate render existed**, so the
  ordering is checkable in git rather than asserted.
- **Harness** `run_absence_ab.py` — resumable at every stage; ~11 min of live DeepSeek
  prompt-writing per leg is already banked on disk.

### The finding that does not need the GPU, and it reframes the story

`old` (baseline prompt, fresh) emitted a perfect 66/66 bijection; `new` emitted **63 shots** —
exactly 3 folds, all on referent-less sentences ("소중한 환자를 대하듯이", "만족스러운 듯이요",
"그는 진심으로 보고 있습니다"), two of which are among the 12 unreadable targets. Scope ② works
and fires selectively.

But counting absence-markers over each leg's prompts:

| leg | shots | prompts opening on an absence |
|---|---:|---|
| `old` (baseline prompt) | 66 | **3** (4.5 %) |
| `new` | 63 | **2** (3.2 %) |

The run this story exists to fix had **5 clear absence-subject prompts among its 12 unreadable
frames alone**. Re-running the same baseline prompt today yields 3 across all 66. So
absence-as-subject is substantially **LLM sampling variance, not a stable property of the
prompt** — and a `readable`-rate A/B at n=66 cannot resolve 3-vs-2. **The lever may be
unmeasurable at this sample size**, which is a question about the story's testability and
should be settled before more GPU time is spent. It is not evidence the change is wrong: it
removes instructions that demonstrably taught the defect, and it is cheap and safe to keep.

### Verification performed

- `uv run ruff check src/ scripts/ tests/ 10-4b-live-validation/` — clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/` — **2675 passed, 1 skipped, 0 failed**.
- Live DeepSeek and Gemini keys both verified working before planning (the earlier empty Gemini
  reply was reasoning tokens eating a 16-token budget, not a broken key).
- ComfyUI health 200; slowness diagnosed from its own log and `/queue`, not inferred.

### Residual risks and what is explicitly NOT claimed

- **No verdict, no seeding.** Live Langfuse `scenario/visual_breakdown` is still **v14**
  (baseline text); the repo file carries the candidate. Runtime reads Langfuse, so leaving the
  edited file in the tree changes no pipeline behaviour until someone seeds it deliberately.
- No claim that unreadable frames dropped. The 18.2 % baseline stands untouched.
- The prompt grew ~10 lines net, against the spec's "must not grow" — the intent (no
  prohibition-piling, no negatives, no regex) was honoured, the letter was not. Recorded in the
  evidence README §5.
- Marker counts are a keyword proxy, not the mechanism — reported as one, and never used to
  scrub or reject a prompt.

### Next step for whoever resumes

Confirm the GPU is genuinely free (`curl -s localhost:8188/queue` → empty or plate-only), then
re-run the single command in the evidence README §0. Before spending those ~6 GPU-hours,
decide whether the measurability finding above changes the plan — a lever that moves 3 prompts
to 2 may need a different design (e.g. many short runs counting absence-prompt incidence
directly) rather than one 66-sentence readable-rate A/B.
