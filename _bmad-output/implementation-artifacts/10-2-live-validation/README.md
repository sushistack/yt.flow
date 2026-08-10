# Story 10.2 live validation — background must be unpopulated

Date: 2026-08-09 (probe) · 2026-08-10 (confirmation re-run, iteration 2) ·
ComfyUI `http://localhost:8188` (live) · checkpoint workflow
`data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (`AnimagineXL_v31`) ·
detector `qwen-vl-plus` via DashScope, i.e. the exact call the runtime guard makes.

Re-derive with one command:

```
# THE GATE: the real image_node over 5 real shots, guard knob explicitly at 2
uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_gate.py

# scan the corpus for a populated background, then run the guard's ladder on it
uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_probe.py

# re-render the recorded hit and re-run the ladder against it (the confirmation below)
uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_probe.py --replay-hit
```

**Not portable.** Every script here reads its prompts out of
`workspace/c6be1954-da0f-4dee-ab07-a2b4f3bcf21e/images/*_done.json` — the resume
sidecars of the 2026-07-12 full E2E run, which live on the machine that produced
them and are not in the repo. Without that directory nothing below can be
re-derived; the recorded prompts inside `before_verdict.json` / `gate_log.json`
are the only portable copy. The guard knob also ships as **0 (off)**, so both
scripts set the attempt budget themselves (`--attempts`, default 2) rather than
reading `background_person_guard_attempts`.

## Where the probe prompts come from (the sample band)

Not invented text. Every probe prompt is a real `image_prompt` read out of the
resume sidecars of run **`c6be1954-da0f-4dee-ab07-a2b4f3bcf21e`** (the 2026-07-12
full E2E, SCP-049, **155 shots**), rendered through `image._inject_prompts` with
`image._shot_seed`, so the frozen `BG_NEGATIVE_SUFFIX` is applied exactly as in
production. The probe walks the corpus in order from `S00100` and stops at the
first populated frame.

## The closing evidence — the pixel guard

| | value |
|---|---|
| probe set size (backgrounds rendered before a hit) | **15** (`S00100` … `S00114`) |
| hit rate in the probe set | 1 / 15 — see "what this sample does not say" |
| render cost | 16.4–20.8 s per background, 256 s total for the probe set |
| hit | `S00114`, scene 1, attempt-0 seed `3285965459` |
| guard attempt 1 (seed `1753844506`) | `has_person=true` — still populated |
| guard attempt 2 (seed `3292677910`) | `has_person=false` — **accepted** |

- `before.png` / `before_verdict.json` — the attempt-0 render. A full-frame anime
  face fills the shot. This is Jay's finding 5 ("a large female face") reproduced
  on demand.
- `after.png` / `after_verdict.json` — the accepted render on the guard's derived
  retry seed. Wet tiled floor, white wall, light shaft, water droplets: an
  unpopulated background, which is what card compositing assumes.
- `probe_log_guard.json` — every probe verdict, seed and timing.

A budget of `background_person_guard_attempts = 2` is exactly what this shot
needed; a budget of 1 would have kept a populated frame. That is the recommended
value when enabling the knob — it is **not** the shipped default, which is 0.

## Confirmation re-run — 2026-08-10, iteration 2's re-derived guard

Story 10.2 was reverted to `79cb473` and re-derived from the amended spec. The
guard was then replayed against the recorded hit
(`run_probe.py --replay-hit`, `probe_log_confirm.json`):

| rung | seed | verdict |
|---|---|---|
| 0 | `3285965459` | `has_person=true` |
| 1 | `1753844506` | `has_person=true` |
| 2 | `3292677910` | `has_person=false` — **accepted** |

Same three seeds, same three verdicts, and `confirm_before.png` /
`confirm_after.png` are **pixel-identical** to `before.png` / `after.png`. Two
things are therefore verified, not asserted:

- the re-derived `_seed_ladder("c6be1954-…", 1, "S00114")` reproduces iteration
  1's rungs byte-for-byte, so attempt 0 still hashes the pre-10.2 string and
  existing workspaces keep resuming;
- the detector's narrowed `has_person` definition (a body in the scene, NOT a
  poster/diagram/statue/skull) still fires on this frame and still clears rung 2.

`migrate_prompts.txt` records the one step that changes runtime behaviour:
`scenario/visual_breakdown` seeded to Langfuse as **version 14**, label
`production`, with the negative-space bullet's "A figure small in an enormous
space" gone (verified by fetching the live production prompt back).

## The live GATE — 2026-08-10, the real `image_node` (`run_gate.py`)

Everything above was measured by a script that *reimplements* the ladder;
`image_node`'s own guard path had never executed live. `run_gate.py` fixes that:
it calls the shipped node (real workflow, real ComfyUI, real DashScope) with
`Settings(background_person_guard_attempts=2)` and a scratch workspace, taps
`submit_and_fetch` / `background_has_person` only to *save* what passes through
them, and reports the node's own counters. 5 shots, 7 submissions, 126.3 s.

| shot | why it is in the set | rung | seed | node's verdict | outcome |
|---|---|---|---|---|---|
| `S00114` | the recorded hit (prompt from `before_verdict.json`) | 0 | `3285965459` | `has_person=true` | regenerated |
| | | 1 | `1753844506` | `has_person=true` | regenerated |
| | | 2 | `3292677910` | `has_person=false` | **accepted** |
| `S00104` | finding 5·12 handoff shot, never run through the node | 0 | `673840615` | `has_person=false` | accepted, 1 render |
| `S00305` | *depicted* human — "a medical diagram … showing a human body" | 0 | `4095645782` | `has_person=false` | accepted, 1 render |
| `S00403` | finding 5·12 handoff shot, never run through the node | 0 | `2851396408` | `has_person=false` | accepted, 1 render |
| `S00713` | *depicted* human — "a human skull with a student's label" | 0 | `4063513675` | `has_person=false` | accepted, 1 render |

Node counters on the image span (`gate_log.json`):
`guard_regenerated=2, guard_exhausted=0, guard_unavailable=0, guard_unscreened=0`,
`request_count=7`, `image_count=5`, `error=None`. The only two INFO lines the node
emitted are the two `S00114` regenerations; no run-level warning fired, which is
correct — every one of the five backgrounds was actually screened.

- `gate_S00114_a0.png` is **pixel-identical** to `before.png` and
  `gate_S00114_a2.png` to `after.png` (verified as RGB arrays, 1344×768; only PNG
  metadata differs). The node reproduces iteration 1's ladder exactly, so the
  hit/clear pair is now attributable to the shipped code path, not to a script.
- `gate_<shot>_done.json` are the node's own sidecars: `S00114` pins the accepted
  bumped rung `3292677910` with `guard_exhausted: false`.
- A second pass (`run_gate.py --resume`, `gate_log_resume.json`) skipped all 5
  shots with **0 submissions** — the bumped-rung seed resumes, live.

**What the gate shows about the narrowed `has_person` definition** — read this
part sceptically, it is weaker than it looks:

- `S00713` is a real test and it passed: the render put a large framed **painted
  portrait of a masked plague-doctor figure** front and centre, and the detector
  answered `false`. A depiction of a human in the frame did not fire the guard.
  It did *not* render the skull the prompt asked for, so "a skull is not a
  person" remains untested.
- `S00305` is **void as evidence**: the render drew an interview room with blank
  and abstract wall panels and **no anatomical diagram at all**, so there was no
  depicted human for the detector to (not) fire on. `has_person=false` here says
  nothing about the narrowing.
- Against the story: `S00114` rung 1 was called `has_person=true` on the strength
  of a **tiny figure standing inside a camera-lens reflection** that fills the
  centre of the frame — not a body standing in the room. Under the rewritten
  one-rule prompt ("a shadow or reflection whose body is outside the frame" is
  FALSE) that verdict is at best borderline, and it cost one extra 15 s render.
  The verdict is recorded as observed; the prompt was **not** tuned to make it
  come out differently.

## What this sample does NOT say

- **1/15 is a censored rate, not a measured one.** The probe stops at the first
  success, so 15 is where the scan happened to stop — it is a lower bound on the
  denominator, not a population estimate. A future run's `guard_regenerated` /
  `guard_exhausted` counts on the image span are the honest measure.
- **The cause is unproven.** 13 of the 15 probe prompts name no person at all and
  all 13 rendered clean; the one hit, `S00114`, is the only probe whose prompt
  contains the word "human" (its original text was "…something alien in human
  shape"), and one further probe (`S00105`, "face") rendered clean. The tempting
  reading — "the checkpoint's character prior paints people into clean prompts" —
  **is not supported by this data**: no control probe here isolates checkpoint
  prior from prompt semantics, and the only prompt that produced a person is also
  the only one that named one. Treat the attribution as an open question.
- **2 attempts is not shown to be enough in general.** The exhausted case is
  handled (last render kept, `WARNING` + `guard_exhausted` in the sidecar and on
  the image span) but was never observed live — in the gate run, 6 of 7 renders
  came back clean on the first rung.
- **The detector is not deterministic.** The request pins `temperature=0`, but
  the verdict still comes from a hosted model: a replay can accept a different
  rung and ship a different image even though the renders themselves are
  seed-deterministic (Story 11.1).
- **The guard ships OFF** (`background_person_guard_attempts=0`, like
  `stock_plate_substitution_enabled` and `shot_recompose_enabled`). This
  directory is the evidence an operator should read before setting
  `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS=2`; with the knob at 0 every generated
  background is counted as `guard_unscreened` and the run logs one warning saying
  so, which is the intended "a dead guard is not a clean pass" signal.

## Removed evidence (iteration 1's cancelled text-scrub arm)

The `build_scenes`-time text scrub was cancelled before iteration 2 (replayed
over 313 real prompts it damaged 27, and its only live measurement was negative).
Its artifacts — `scrub_before.png`, `scrub_after.png`, their verdicts and
`probe_log_scrub.json` — were deleted with this note, because two of them were
misleading as presented:

- `scrub_after.png` (S00114, seed `3285965459`, scrubbed prompt) was **pixel-
  identical** to `before.png` — same prompt, same seed, same frame. It was
  presented as an independent observation; it was the same observation twice.
  (Verified before deletion: identical RGB arrays, 1344×768; only PNG metadata
  chunks differed.)
- `scrub_before.png` (S00114, seed `3285965459`, **un**scrubbed prompt) read
  `has_person=true`. Removing the person clause and re-rendering the same seed
  still read `has_person=true` — a negative result for the scrub, and the reason
  the layer is gone rather than the reason it shipped.
