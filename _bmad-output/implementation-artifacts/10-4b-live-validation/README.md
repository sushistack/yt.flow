# 10.4b Live Validation — absence-free prompt vs baseline

**Status: the change is implemented and the A/B is BLOCKED, not lost.** Both legs' prompts
were written by live DeepSeek and are on disk; rendering got 3 of 129 frames in 40 minutes
because another producer holds the GPU (see §3). Nothing about the verdict is reported here,
because no verdict was reached.

The analysis plan is in [`PRE-REGISTRATION.md`](./PRE-REGISTRATION.md), committed in `25bed30`
**before any candidate render existed**. It has not been edited since.

---

## 0. Re-derive / resume with one command

```
uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py
```

Every stage is resumable — existing outputs are reused, so restarting costs only the work in
flight. What is already on disk: `ab_context.json` (the shared context both legs got),
`ab_old_shots.json` / `ab_new_shots.json` (raw `visual_breakdown` output), `ab_old_scenes.json`
/ `ab_new_scenes.json` (assembled, with seeds and the checkpoint's negatives),
`ab_old/` (3 frames). The candidate prompt text is preserved as `prompt_absence_free.md` so the
run stays re-derivable if the prompt file is ever reverted.

The lever is the **prompt text and nothing else**: both legs run the working tree's parser,
assembler and repairers; `old` is `prompts/scenario/visual_breakdown.md` at `9b460d5`, `new` is
the working tree. Held identical: narration, `cast_by_sentence`, scene/entity context (built
once, before either leg), the per-starting-sentence seed, and the checkpoint's `negative_prompt`.

---

## 1. What changed

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

**One code change** — `_fallback_prompt` ended in `"no visible subject"`, a code-side absence
subject that also matched `_NO_FIGURE_FRAMINGS`, so a phrase chosen to mean "placeholder"
silently stripped the shot's cast. It now names the floor. Forward merge was deliberately
**not** implemented (`# ponytail:` marks the ceiling) because the prompt now handles the
leading case by widening the first shot's range, which the cover already accepts.

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

That is a finding about the **measurability of the story**, and it should be settled before
more GPU time is spent. It does not say the prompt change is wrong — the change removes
instructions that demonstrably taught the defect, and it is cheap and safe to keep.

**Marker counts are a weak proxy, stated as one.** A keyword list is not the mechanism (the
same caveat the 2026-08-10 research put on its own 29 %-vs-11 % figure), and it is used here
for reporting only — never to scrub or reject a prompt
(`gotcha_person-token-regex-is-unusable-on-image-prompt`; Story 10.2 built exactly that
scrubber, measured 27 of 313 shots damaged, and deleted it).

## 3. Why the A/B is blocked

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

- **No verdict.** No leg was scored. The pre-registered rule has not been evaluated, and the
  prompt was **not seeded** — live Langfuse `scenario/visual_breakdown` is still **v14**, the
  baseline text. Seeding requires a pass, per `docs/PROMPT_POLICY.md` and the pre-registration.
- No claim that unreadable frames dropped. The 18.2 % baseline is untouched as a reference.
- `dsg_score` was wired into the harness for per-proposition attribution and never as a
  verdict input.
- No cover-quality gate was built (10.4's explicit handoff forbids one).

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
  implementation rather than after.

## 6. Layout

```
PRE-REGISTRATION.md        the analysis plan, committed 25bed30 before any candidate render
run_absence_ab.py          the two-leg harness (resumable at every stage)
prompt_absence_free.md     the candidate prompt text, preserved for re-derivation
ab_context.json            shared context both legs were given
ab_{old,new}_shots.json    each leg's raw visual_breakdown output (9 live DeepSeek calls each)
ab_{old,new}_scenes.json   assembled scenes: sentence_indices, seeds, checkpoint negatives
ab_old/                    3 rendered frames before the run was stopped
README.md                  this file
```
