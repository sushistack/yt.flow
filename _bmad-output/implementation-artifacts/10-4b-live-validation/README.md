# 10.4b Live Validation — the defect was already fixed, and the change was reverted

**Status: CLOSED on a measured negative. The prompt change is reverted; one code bug fix
survived.** Measured 2026-08-11 against run `8a9a288b` (SCP-049, 9 scenes / 66 sentences).

> **Verdict: 10.4b's premise rests on frames from a prompt version that no longer exists.**
> A blind text judge scored the **baseline** prompt at **66/66 = 100 %** on "is the subject
> physically present" — there was no absence-as-subject behaviour left to remove. Story 10.2's
> prompt edit on **2026-08-10** had already killed it, and the run whose 12 unreadable frames
> motivated this story had its scenario written on **2026-08-07**, three days earlier.
>
> The clause that *is* still live is the other half: **`visible_event` sits at 84.9 % (56/66)
> in the baseline** — about 10 of 66 prompts establish a place with no event in it — and that
> maps onto the 6 of 12 unreadable frames whose subjects were already concrete. **This story's
> wording did not improve it** (82.5 %, −2.3 pp, noise). So the prompt change was reverted and
> the remaining defect is handed on as its own scope.
>
> The render A/B was never run. The 109-second text gate below made it unnecessary and saved
> ~6 GPU-hours on a comparison that would have measured nothing.

## What survived, what was reverted

| | outcome |
|---|---|
| `prompts/scenario/visual_breakdown.md` (scope ① + ②) | **REVERTED** to the pre-10.4b text, byte-identical. Never seeded — live Langfuse is still v14. The candidate text is preserved as `prompt_absence_free.md`. |
| the 3 tests pinning the prompt rewrite | removed with it |
| `_fallback_prompt` no longer ends in `"no visible subject"` | **KEPT** — an independent code defect: it named an absence *and* matched `_NO_FIGURE_FRAMINGS`, so a phrase chosen to mean "placeholder" silently stripped the shot's cast. Pinned by `test_fallback_prompt_names_a_surface_not_an_absence`. |
| the premise correction, the strata, and both measurements | kept as the story's deliverable |

---

## 0. Re-derive with one command

The finding that closed this story needs no GPU and takes under two minutes:

```
uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/check_prompt_compliance.py
#   -> prompt_compliance.json   (129 text calls, no renders)
```

The render A/B harness is also here and still resumable, though there is now no reason to run
it — see §2b and §3:

```
uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py
```

Because the prompt file was reverted, that harness reads its candidate leg from
`prompt_absence_free.md` (the preserved text) rather than from the working tree — the fallback
exists for exactly this situation. On disk: `ab_context.json` (the shared context both legs
got), `ab_{old,new}_shots.json` (raw `visual_breakdown` output), `ab_{old,new}_scenes.json`
(assembled, with seeds and the checkpoint's negatives), `ab_old/` (3 frames),
`prompt_compliance.json` (the gate).

The lever was the **prompt text and nothing else**: both legs ran the same parser, assembler and
repairers. Held identical: narration, `cast_by_sentence`, scene/entity context (built once,
before either leg), the per-starting-sentence seed, and the checkpoint's `negative_prompt`.

---

## 1. What the change was (now reverted)

**Scope ①** — one requirement replacing three absence-teachers:

| removed | why it was there |
|---|---|
| `Use negative space as a storytelling tool` + `Large empty areas in the frame create unease` / `An empty hallway stretching to a vanishing point` / `The space where something SHOULD be but isn't` | taught emptiness as craft; Story 10.2 deleted only one bullet of this block and the rest survived |
| `Don't show "nothing." Show an EMPTY frame that feels WRONG` | the stronger of the two teachers |
| checklist `- [ ] Negative space or depth layering … is used` | *mandated* it at self-check time |
| `write a pure environment/atmosphere shot` (cast-empty guidance) | the third leg of the collision |

Replaced by: the subject is always a nameable object/surface/**trace** that exists, and the
frame carries **at least one legible trace of this sentence's event**. Stated once in the
composition principles, once in slots 2–3 (promoting the BAD/GOOD pairs already there), and
twice in the self-check. Net instruction count grew by ~10 lines rather than shrinking — a
deviation from the spec's "must not grow", recorded in §5.

**Scope ②** — the strict bijection (`sentence_start == sentence_end`, `Total shot count ==`)
is narrowed: a sentence with **no renderable referent** widens a neighbour's span instead of
minting its own background. The shot-count ceiling survives. The parser already validated an
ordered cover (Story 10.4); only the prompt forbade it.

**One code change — the only part that survived.** `_fallback_prompt` ended in
`"no visible subject"`, a code-side absence subject that also matched `_NO_FIGURE_FRAMINGS`, so
a phrase chosen to mean "placeholder" silently stripped the shot's cast. It now names the floor.
Forward merge was deliberately **not** implemented (`# ponytail:` marks the ceiling).

Everything above this paragraph was reverted after the §2b measurement. It is recorded because
the *reasoning* was sound and someone will propose it again: the removed lines really do teach
absence, and re-adding them would be a regression — but Story 10.2 had already removed the one
that mattered, so removing the rest bought nothing measurable.

## 2. What the prompts alone already show — and it reframes the story

This needed no renders, and it is the most useful thing this round produced.

**Scope ② works, and it fires selectively.** `old` emitted a perfect bijection (66 shots /
66 sentences). `new` emitted **63 shots** — exactly 3 folds, and all 3 land on sentences with
no renderable referent:

| scene | shot | folded sentences |
|---|---|---|
| 3 | S00305 | "그는 진심으로 보고 있습니다." + "당신만 못 볼 뿐, 그 병이 여기 있다는 겁니다." |
| 6 | S00602 | "시체를 반듯하게 눕혔습니다." + "소중한 환자를 대하듯이." |
| 7 | S00706 | "에스씨피 공사구가 가면을 기울여 바라봅니다." + "만족스러운 듯이요." |

Two of those are among the 12 unreadable targets (`S00305`, and `S00707`'s sentence folded
into `S00706`). This is not general cover freedom — 3 folds in 66 sentences — which is what
was asked for.

**But the effect this story can possibly have is much smaller than the premise implies.**
Counting a fixed absence-marker list (`open air`, `vast empty`, `blank wall`, `empty floor`,
`nothing on`, `featureless`, `devoid of`, `no visible subject`) over each leg's prompts:

| leg | shots | prompts opening on an absence |
|---|---:|---|
| `old` (baseline prompt, fresh) | 66 | **3** (4.5 %) — `S00100`, `S00705`, `S00708` |
| `new` (absence-free prompt) | 63 | **2** (3.2 %) — `S00302`, `S00905` |

The run this story exists to fix had **5 clear absence-subject prompts among its 12 unreadable
frames alone**. Re-running the *same baseline prompt* today produces 3 across all 66. So
absence-as-subject is substantially **LLM sampling variance, not a stable property of the
prompt** — which means:

- the ceiling on scope ① is not 6 of 12; on a fresh run it is closer to **3 of 66**, and
- a `readable`-rate A/B at n=66 cannot resolve a 3-vs-2 difference. The pre-registered exact
  binomial needs discordant pairs; this lever may simply not produce enough of them.

That was the first sign the story's target had moved. §2b settled it: the baseline prompt scores
**100 %** on "the subject is physically present", so absence-as-subject is not a live defect of
the current prompt at all, and these 3 marker hits are incidental phrasing rather than the
failure mode. The remaining 5-of-12 premise belongs to the pre-10.2 prompt.

**Marker counts are a weak proxy, stated as one.** A keyword list is not the mechanism (the
same caveat the 2026-08-10 research put on its own 29 %-vs-11 % figure), and it is used here
for reporting only — never to scrub or reject a prompt
(`gotcha_person-token-regex-is-unusable-on-image-prompt`; Story 10.2 built exactly that
scrubber, measured 27 of 313 shots damaged, and deleted it).

## 2b. The 109-second gate that closed the story (no GPU)

`check_prompt_compliance.py` asks a **text-only** judge two booleans per already-written prompt
— the two halves of the requirement 10.4b added — and never looks at an image:

* `present_subject` — is the subject a physically present object/surface/trace, not an emptiness?
* `visible_event` — does the prompt put a visible mark/displacement/residue of *this sentence's*
  event in the frame?

Blind by construction: one prompt and one sentence per call, no leg label, no siblings, so the
judge cannot tell candidate from control. `qwen-plus` on the DashScope endpoint, `temperature 0`.

| clause | `old` (baseline prompt) | `new` (candidate) | Δ |
|---|---|---|---|
| `present_subject` | **66/66 = 100 %** | **63/63 = 100 %** | 0.0 |
| `visible_event` | 56/66 = **84.9 %** | 52/63 = **82.5 %** | **−2.3 pp** |

Two readings, and both matter:

1. **The absence clause had nothing to act on.** 100 % compliance in the *control*. The crude
   marker count in §2 agreed (3/66, all incidental). Cross-checked against the timeline: this
   prompt was last edited before the run on 2026-08-01 (Story 11.2), then by **Story 10.2 on
   2026-08-10** — which replaced *"A figure small in an enormous space"* with an object — while
   run `8a9a288b`'s scenario was written **2026-08-07**. The 12 unreadable frames are artefacts
   of the pre-10.2 prompt. 10.4b was chasing a defect that had already been fixed by a
   one-line edit in a different story.
2. **The live gap is `visible_event`, and this story did not move it.** ~10 of 66 baseline
   prompts establish a place, a mood, lighting and texture with nothing indicating anything
   happened — which is exactly the failure mode of the 6 of 12 unreadable frames that had
   concrete subjects and `event: "unclear"`. The candidate scored 2.3 pp *lower*; at n≈65 that
   is noise, not harm, but it is certainly not an improvement.

This is a **diagnostic gate, not the pre-registered verdict** — `PRE-REGISTRATION.md` fixes the
verdict on rendered frames, and that verdict was never reached. The gate is what made reaching
it pointless.

Re-derive:
```
uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/check_prompt_compliance.py
#   -> prompt_compliance.json   (~110 s, 129 text calls, no GPU)
```

---

## 3. Why the render A/B was never completed

ComfyUI was down and the GPU idle when this started, so it was brought up with `setsid`
(`gotcha_comfyui-and-env-operational`). Then:

- my plate renders take **~16 s** each (`comfyui_sdxl_anime_lora_workflow_api2.json`, 30 steps
  at ~2.5 it/s — verified in the ComfyUI log)
- but a **character workflow** (`IPAdapterAdvanced` + `InspyrenetRembg` + `LoadImage`) runs
  continuously on the same instance at **~306 s** per job, and my jobs queue behind it

Sampled `/queue` three times, 20 s apart: `running: CHARACTER, pending: plate(api2)` every
time. `api2` contains no IPAdapter and no Rembg (checked), so those jobs are not mine, and no
other process from this checkout is running. Net throughput: **3 frames in 40 minutes** against
a 129-frame slate — roughly 6 hours, and contending with someone else's work the whole way.

The run was stopped rather than left to fight for the GPU. `kill <pid>`, not `pkill -f`
(`gotcha_comfyui-and-env-operational`).

**To resume:** confirm the GPU is actually free (`curl -s localhost:8188/queue` should show an
empty or plate-only queue), then re-run the one command in §0. The ~11 minutes of DeepSeek
prompt-writing per leg is already banked.

## 4. Not done, and not claimed

- **No rendered verdict.** No leg was scored on frames; the pre-registered rule was never
  evaluated. The prompt was **not seeded** and is now reverted — live Langfuse
  `scenario/visual_breakdown` is still **v14**.
- No claim that unreadable frames dropped. The 18.2 % baseline is untouched as a reference.
- **The gate is a prompt-text judgement, not a frame judgement.** It says the written prompts
  name a present subject; it does not say the renders are readable. Those are different claims
  and only the render A/B could settle the second — which is precisely why the `visible_event`
  gap is handed on rather than declared fixed.
- One judge, `temperature 0`, one call per prompt, no repeats — so the 84.9 % / 82.5 % pair has
  unmeasured judge variance and the −2.3 pp difference should be read as "no movement", not as
  a small regression.
- `dsg_score` was wired into the harness for per-proposition attribution and never as a
  verdict input.
- No cover-quality gate was built (10.4's explicit handoff forbids one).

## 4b. What the next story should take

The live defect is **`visible_event`: ~10 of 66 baseline prompts establish a place, a mood,
lighting and texture with nothing indicating that anything happened.** That is the failure mode
of the 6 of 12 unreadable frames whose subjects were already concrete (`S00201`, `S00202`,
`S00400`, `S00707`, `S00804`, `S00900` — every one of them scored `event: "unclear"` blind).

Two things make that a better-shaped story than this one was:

- it has a **live baseline to beat** (84.9 %), measured on the current prompt rather than
  inferred from a superseded one, and
- `check_prompt_compliance.py` is already the gate for it — a candidate can be screened in ~2
  minutes with no GPU before anything is rendered, and only then does the paired `readable` A/B
  in `PRE-REGISTRATION.md` become worth its cost.

This story's wording (`"at least one legible trace of THIS sentence's event"`, stated in the
composition principles, slot 3 and the self-check) moved it by −2.3 pp, i.e. not at all. So the
next attempt needs a different intervention, not a re-run of this one.

## 5. Deviations from the spec, recorded

- **"Net instruction count must not grow" was not met** for scope ①: the prompt grew by ~10
  lines net. The *intent* of that constraint was "do not fix this by piling on prohibitions",
  and that was honoured — the change replaces the absence-teachers with one positive demand,
  adds no negative-prompt clauses, and adds no regex. But the letter of the constraint says
  shrink-or-flat, and it did not. The growth is the requirement being restated in the two
  places that previously taught the opposite (the self-check and the cast-empty guidance),
  which is where a model actually reads it.
- The spec's I/O matrix said a leading referent-less sentence "folds **forward**". It is instead
  handled prompt-side by widening the first shot's range; the matrix row was corrected before
  implementation rather than after. (Moot now — that prompt text is reverted.)
- The spec planned to judge on rendered frames only. The prompt-text gate in §2b is an addition,
  introduced when the marker counts in §2 suggested the target might not exist. It is labelled a
  diagnostic and never substituted for the pre-registered rule — but it is the thing that
  actually closed the story, so the plan was better for having been deviated from.

## 6. Layout

```
PRE-REGISTRATION.md        the analysis plan, committed 25bed30 before any candidate render
run_absence_ab.py          the two-leg harness (resumable at every stage)
prompt_absence_free.md     the candidate prompt text, preserved for re-derivation
ab_context.json            shared context both legs were given
ab_{old,new}_shots.json    each leg's raw visual_breakdown output (9 live DeepSeek calls each)
ab_{old,new}_scenes.json   assembled scenes: sentence_indices, seeds, checkpoint negatives
ab_old/                    3 rendered frames before the run was stopped
check_prompt_compliance.py the no-GPU gate that closed the story (§2b)
prompt_compliance.json     its per-prompt rows and per-leg rates
README.md                  this file
```
