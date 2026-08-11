# Story 10.5 — live validation (지적 6, action state on cards)

Working tree at pre-registration: `d04442f`. Pre-registered **2026-08-12T00:25+09:00**,
before any PNG in this directory existed. This file is committed on its own, ahead of
every render, so `git log --diff-filter=A -- '_bmad-output/implementation-artifacts/10-5-live-validation/*'`
shows the README in an earlier commit than the pixels — not merely earlier in the same
commit's file list (which is how 10.6 recorded it, and which proves nothing about order).

Recompute everything here with:

```bash
uv run python _bmad-output/implementation-artifacts/10-5-live-validation/render_legs.py     # (B)
uv run python _bmad-output/implementation-artifacts/10-5-live-validation/probe_sitting.py   # (A)
```

The defect splits in two and the two halves are judged separately:

- **(A) missing assets** — `STOCK-d-class` and `SCP-049-2` own zero `sitting` cards, so
  `_resolve_card_path` silently fell back to standing for 14 of the 23 bad slots. Nothing
  to invent: `seed_stock_cast.py --pose sitting` already works. One front card is rendered
  here and judged **before** anything is written live.
- **(B) the pose hint conditions nothing** — 9 slots, and 10.6 measured 7/7 renders that
  asked for `"lying supine on table"` coming back standing or seated. Which *pipeline*
  can draw the state at all is settled below, before any technique is wired.

---

## PRE-REGISTRATION (written before rendering; not to be edited after seeing pixels)

### (B) Which pipeline can draw the requested state?

Everything except the named variable is held at 10.6's ② values: card key `STOCK-d-class`,
`pose_hint = "lying supine on table"`, the prompt composed exactly as
`generate_special_pose_card` composes it, reference image = the live standing front card
(`characters.angle_front_path`), `negative_suffix = STOCK_NEGATIVE` (today's production
behaviour since 10.6), `832×1216`, and the seed triple `random.seed(1061/1062/1063)` pinned
immediately before each `provider.generate()` so leg *X* render *i* and leg *Y* render *i*
draw the same KSampler seed from `_inject_seed`'s `random.randint`.

| Leg | `ipadapter_weight` | workflow | guide | renders |
|---|---|---|---|---|
| **L0 control** | 0.2 | `comfyui_character_multi_angle_api.json` | none | **0 new** — reuses 10.6's three ②-B frames verbatim |
| **L1 anchor isolation** | **0.0** | `comfyui_character_multi_angle_api.json` | none | 3 (seeds 1061/1062/1063) |
| **L2 structural conditioning** | 0.2 | `comfyui_character_pose_guide_api.json` | `assets/pose_guides/humanoid_lying_supine.png`, ControlNet Union promax, `type="openpose"`, strength 0.9, start 0.0, end 1.0 | 3 (seeds 1061/1062/1063) |

**Control provenance.** L0 is not re-rendered. It is
`_bmad-output/implementation-artifacts/10-6-live-validation/leg2-B_stocknegative_r{1,2,3}_seed{1061,1062,1063}.png`,
rendered 2026-08-11 on this host with the same chain (AnimagineXL v3.1 + `darkness_xl_v2`
@0.3, no `horror.safetensors`), the same prompt, the same reference and the same seeds.
10.6 judged all three **standing or seated, never supine** (r2 is the closest — a
half-seated lean), so the control's pre-existing supine count is **0/3**. Reusing it costs
zero GPU and keeps the seeds paired; the cost is that it was rendered ~26 h earlier, which
is recorded as the one non-simultaneity in this comparison.

**Why L1 keeps the reference image.** Passing `ref_image_path=None` would make the provider
take its t2i path, changing the graph topology as well as the conditioning — the exact
confound 10.6's ① pair fell into. So the reference stays loaded and only the IPAdapter
weight moves to 0.0. One variable.

**Judging criterion (per render, from viewing the PNG).** A render counts as **supine**
iff **both**:

- (i) the torso's long axis (hip→shoulder) is **horizontal** on screen rather than vertical; and
- (ii) the height difference between the head and the feet is **under one third of the
  figure's body length**.

Anything else — standing, kneeling, seated, half-seated lean — is **not supine**. Each
render gets a one-line reason written below. Partial credit does not exist; the count is
out of `n=3` per leg.

**Decision table (fixed; no post-hoc tuning). Counts are integers 0–3, so `≥2/3` means 2 or 3
and `≤1/3` means 0 or 1 — the four rows are exhaustive.**

| L1 supine | L2 supine | Conclusion |
|---|---|---|
| ≤1/3 | **≥2/3** | **Adopt structural conditioning.** Wire the pose-guide workflow behind `pose_guide_conditioning_enabled = False`. |
| **≥2/3** | ≤1/3 | **The IPAdapter anchor was the cause.** Introduce one pose-card-specific IPAdapter weight constant and nothing else. No ControlNet. |
| ≤1/3 | ≤1/3 | **Neither.** 8.20's fork is live: ship `edit_only` only, or move pose generation off this host — **Jay's scope decision**. HALT `blocked`, no code change beyond (A). |
| **≥2/3** | **≥2/3** | Two sufficient causes, unseparated. Record the frames and HALT `blocked`. Do not invent a third hypothesis unattended. |

**Block-If, independent of the table.** If the L2 (ControlNet) leg OOMs, or its peak VRAM
exceeds the **15.92 GB** usable ceiling this host has, the story ends `blocked` with peak
VRAM, the failing node and renders attempted/succeeded recorded. Peak VRAM is sampled by
polling `/system_stats` every 2 s for the duration of each render and taking
`max(vram_total − vram_free)`; the same figure is recorded for L1 as its control, because a
number without a control is not a measurement. Raw rows land in `measurements.jsonl`.

Note on 8.20's rejection: its 15.20–16.18 GB peaks were **Qwen-Image-Edit-2511 Q4_K_M**
(13.24 GB resident) and its OOM was `InspyrenetRembg` asking for a further 4.5 GB after
sampling. This leg is SDXL/AnimagineXL + IPAdapter + a 2.5 GB ControlNet Union that is
already installed and already driven by `comfyui_shot_recompose_api.json`. 8.20's numbers
are therefore **not** a prediction for this leg — which is why it is measured rather than
assumed, and why a bad measurement goes to Block-If rather than to a workaround.

**Supporting pixel metric, with no authority over the verdict.** The alpha bounding box's
aspect ratio `w/h` at threshold `alpha > 8` (standing sprites run ≈0.5; a supine figure
must exceed 1.0). Band definition: the full alpha bbox, i.e. rows/columns where any pixel
has `alpha > 8`; no sub-band. Alpha is thresholded at `>8` and **254 is treated as
saturation** — InSPyReNet does not emit 255 for subject interiors, so an `alpha == 255`
check would reject every card this chain produces (8.20 §3.4). Recompute:

```bash
uv run python - <<'PY'
from PIL import Image
import glob
def wh(p):
    a = Image.open(p).convert("RGBA").split()[3]; W, H = a.size; px = a.load()
    ys = [y for y in range(H) if any(px[x, y] > 8 for x in range(W))]
    xs = [x for x in range(W) if any(px[x, y] > 8 for y in range(H))]
    w, h = xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1
    print(f"w/h={w/h:5.3f}  w={w:4d} h={h:4d}  {p}")
for p in sorted(glob.glob("_bmad-output/implementation-artifacts/10-5-live-validation/leg*.png")) + \
         sorted(glob.glob("_bmad-output/implementation-artifacts/10-6-live-validation/leg2-B*.png")):
    wh(p)
PY
```

If that number and the viewing verdict disagree on any frame, the **viewing verdict
decides** and the disagreement is written down as a finding.

### (A) Is the `sitting` set safe to seed live?

One `STOCK-d-class` **sitting front** is rendered into this directory first, with no live
write, reproducing exactly what the seeding run's front angle will do:
`_compile_generation_prompt(STOCK_DESCRIPTORS["STOCK-d-class"], angle="front",
angle_description=f"{_ANGLE_DESCRIPTIONS['front']}, {_POSE_DESCRIPTIONS['sitting']}")`,
`negative_suffix=STOCK_NEGATIVE` verbatim, `ipadapter_weight=0.2`, reference =
`assets/characters/STOCK-d-class/epoch_2/front_candidate_1.png` (the same `--anchor` the
seeding command passes).

**Pass rule — all three must hold:**

- (a) **seated**: hips are lowered onto a chair/surface with the thighs roughly horizontal
  and the torso upright. A standing figure fails; so does a figure merely leaning.
- (b) **one adult figure**: no second figure, no child, no chibi. (10.6's pre-registration
  omitted a figure-count criterion and thereby missed the largest same-seed difference in
  its whole experiment. Recorded there as a lesson; applied here.)
- (c) **identity holds**: orange prison jumpsuit, an ordinary unmasked human head with a
  pupil visible in at least one eye.

**Hand quality is deliberately excluded from this rule**, and that exclusion is registered
here rather than discovered later: 10.6 measured hands failing in 3 of 6 renders across
*both* of its legs, i.e. the defect is chronic to this chain and independent of the variable
under test. Gating (A) on hands would block an asset fix on a defect this story does not own.
A hand observation is still written down per render; it just does not decide.

**If the probe passes**, run — with no edit to the script:

```bash
uv run python scripts/seed_stock_cast.py --key STOCK-d-class --pose sitting \
  --anchor assets/characters/STOCK-d-class/epoch_2/front_candidate_1.png
```

and afterwards assert with read-only queries that four
`(STOCK-d-class, 'sitting', {front, side, back, three_quarter})` rows exist with
`status='approved'` and that the four standing `characters.angle_*_path` values are byte
identical to their pre-seed values. `yt_flow.db` is gitignored, so `git status` is vacuous
as DB evidence — the assertions below are the evidence.

**If the probe fails**, nothing is seeded and (A) is reported unclosed with the frame.

**Pre-recorded scope note.** This closes at most **11 of the 14** (A) slots.
`SCP-049-2`'s three are deliberately left: `--pose sitting` on that key would have
`generate_cards_from_descriptor` **overwrite** its `visual_descriptor`, executing unattended
the asset replacement 10.6 handed to Jay's gate, and would put a maskless sitting set beside
a still-masked standing set — turning a hazard `deferred-work.md` records as latent into a
live one. Forbidden by this story's Boundaries.

**Pre-recorded side effect of the seeding command itself.** `generate_cards_from_descriptor`
writes `characters.visual_descriptor = descriptor` before generating, and with `--anchor`
given it skips the vision enrichment re-append. So the live `STOCK-d-class` descriptor will
lose the appended vision read-back (which currently describes the front card as *"a
disproportionately large torso and head… heavyset… short, stubby limbs"*) and revert to the
authored `STOCK_DESCRIPTORS` text alone. That is a real live mutation, it is a property of
the script this story is instructed not to edit, and it is written here **before** the run so
it cannot be presented afterwards as an intended improvement. The before/after values are
recorded in RESULTS.

---

## RESULTS

_(written after rendering; the sections above are frozen)_
