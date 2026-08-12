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

Rendered 2026-08-12 00:23–00:33 KST, `ComfyUICharacterProvider`, AnimagineXL v3.1 +
`darkness_xl_v2` @0.3 (the same chain 10.6's control was rendered on). ComfyUI 0.12.3,
torch 2.11.0.dev+rocm7.1, AMD Radeon RX 9060 XT 16 GB. The queue was read before every
render and was empty each time (the 10-4b session was not using the GPU). All 7 PNGs
carry an alpha channel; the script asserts it and prints `alpha=True` per render.

### (B) Decision: **adopt structural conditioning** (L1 0/3, L2 3/3, control 0/3)

| Leg | seed 1061 | seed 1062 | seed 1063 | **supine** |
|---|---|---|---|---|
| **L0 control** (10.6 ②-B, `ipadapter 0.2`, no guide) | not supine | not supine | not supine | **0/3** |
| **L1** (`ipadapter 0.0`, no guide) | not supine | not supine | not supine | **0/3** |
| **L2** (`ipadapter 0.2`, openpose guide @0.9) | **supine** | **supine** | **supine** | **3/3** |

Decision-table row **`L1 ≤1/3` + `L2 ≥2/3` → adopt structural conditioning.** The row is
robust to the one ambiguous frame: even scoring L2 r1 as *not* supine leaves L2 at 2/3,
which is the same row.

**Per-render judgments, written from viewing each PNG.**

- **L1 r1 (seed 1061)** — a single man standing upright, hands behind his back, torso
  vertical, feet on the ground. Fails (i) outright. → **not supine**
- **L1 r2 (seed 1062)** — a three-panel character sheet: a full-body standing figure, a
  large bust close-up, and a third partial figure. No panel is horizontal. → **not supine**
- **L1 r3 (seed 1063)** — a single man standing upright, arms at his sides, the cleanest
  standing render in the set. → **not supine**
- **L2 r1 (seed 1061)** — the figure lies on its back, head at frame left, torso
  horizontal across the frame, face upward. (i) passes clearly. (ii) is **ambiguous**:
  one leg extends right (its boot sits at roughly head height) while the other is bent
  with the lower leg dropping toward the bottom of the frame, about 350 px below the
  head against a ~810 px body length (≈0.43, over the one-third bound) — so (ii) passes
  on the extended leg and fails on the bent one. Called **supine** on the body's
  principal axis, and the ambiguity is recorded rather than resolved by rewriting the
  rule. It changes no conclusion (see above).
- **L2 r2 (seed 1062)** — flat on the back, head at frame left, feet at frame right,
  arms out, head and feet at effectively the same height. Unambiguous on both (i) and
  (ii). → **supine**
- **L2 r3 (seed 1063)** — **two** figures, both lying flat on their backs, one above the
  other, heads at frame left. Both satisfy (i) and (ii). → **supine** under the rule as
  written, with the figure count recorded as a defect below.

**Supporting metric (alpha-bbox `w/h`, threshold `alpha > 8`, full bbox).** It agrees
with every viewing verdict, so there is no disagreement to report as a finding — but note
it is *not* independent evidence of quality, only of horizontality:

| frame | `w/h` | w × h |
|---|---|---|
| L0 control r1 / r2 / r3 | 0.319 / 0.574 / 0.309 | 365×1143 / 656×1143 / 353×1143 |
| L1 r1 / r2 / r3 | 0.368 / 0.708 / 0.297 | 421×1143 / 809×1143 / 340×1143 |
| **L2 r1 / r2 / r3** | **1.280 / 2.090 / 1.351** | 832×650 / 832×398 / 832×616 |

Ceiling on the metric, recorded: every L2 frame is exactly 832 px wide because
`_normalize_subject_scale` fits an over-wide subject to the canvas width, so `w` saturates
and `w/h` **understates** how horizontal a supine figure is. It separates the classes with
a 1.8× gap regardless (0.708 max standing vs 1.280 min supine), but it could not be used
as a threshold for anything finer.

**VRAM — the Block-If did not trigger.** Ceiling 15.92 GiB (`vram_total` = 17,095,983,104 B).
Sampled every 2 s during each render, `max(vram_total − vram_free)`; raw rows in
`measurements.jsonl`.

| Leg | renders attempted | succeeded | wall (s) | **peak VRAM (GiB)** |
|---|---|---|---|---|
| L1 (no ControlNet — the control for this number) | 3 | 3 | 24.0 / 22.3 / 22.4 | 9.90 / 7.20 / 7.15 |
| **L2 (ControlNet Union promax)** | **3** | **3** | 68.1 / 28.8 / 28.8 | **11.16 / 9.62 / 9.66** |

Zero OOM, zero failed nodes. The ControlNet leg's worst peak is **11.16 GiB, 4.76 GiB
under the ceiling**; its cost over the unguided leg is ~1.3–2.5 GiB and ~6 s per render
(the 68.1 s first render includes the one-time 2.5 GB ControlNet load). This is the
measurement 8.20 recommendation 2 asked for and it does **not** reproduce 8.20's numbers —
as pre-registered, those were Qwen-Image-Edit-2511 Q4_K_M (13.24 GB resident) with
`InspyrenetRembg` asking for a further 4.5 GB, an entirely different resident model.

**Findings the pre-registered (B) rule does not cover — recorded, not patched in.**

1. **Figure count.** L1 r2 came back as a three-panel character sheet and L2 r3 as two
   supine men. The (B) criterion asks only about body orientation, so it scores both on
   pose alone and is blind to this. It is a real defect in a card (a card must be one
   subject) and it appears **with and without** the guide, so it is not caused by the
   change adopted here — but shipping the guide on by default would ship it too. That is
   the concrete reason `pose_guide_conditioning_enabled` stays **off**. Note this is the
   *second* consecutive story whose pre-registration missed a figure-count defect; the
   rule was not amended mid-flight, but a card-quality pre-registration that omits it
   again is a repeat of a known miss.
2. **Hands.** Chronic, as 10.6 recorded: hands are blobs or fused in several of these
   frames in both legs. Unchanged by the guide, not this story's defect.
3. **The guide dictates the whole silhouette, not just the axis.** L2's figures reproduce
   the guide skeleton's arm and leg placement closely. That is what "structural
   conditioning" means and it is why the guide catalog is closed — one guide raster is
   one pose, not a family of them.

**What is wired, and what it takes to actually fire.** `pose_guide_conditioning_enabled`
(default `False`) → `run_service._ensure_special_pose_cards` now carries `pose_guide_key`
through instead of discarding it → `generate_special_pose_card` resolves it with
`asset_service.resolve_pose_guide(key, character.pose_conditioning)` and passes
`pose_guide_path` to the provider, or warns and takes the pre-10.5 path. **The setting is
not sufficient on its own**: `resolve_pose_guide` requires the character's
`pose_conditioning` profile to accept the guide's schema, and the model default
`edit_only` accepts nothing. Today's live rows are already backfilled — `STOCK-d-class`,
`SCP-049`, `SCP-049-2`, `STOCK-researcher`, `STOCK-security`, `SCP-096` are `openpose`,
`SCP-682` is `scribble`, `SCP-1471` and `SCP-999` are `edit_only` — so the humanoid keys
would resolve and the last two would degrade with a warning. Verify with:

```bash
sqlite3 -readonly yt_flow.db "select scp_id, pose_conditioning from characters;"
```

### (A) Probe: **FAILED (a) — nothing was seeded**

`probeA_sitting_front_seed1071.png`, one render, `alpha=True`.

- (a) **fail** — the figure is **standing bolt upright**: hips high, thighs vertical, both
  boots flat on the ground, no chair anywhere in the frame. The prompt asked for
  `"sitting on a plain simple chair, seated pose"`.
- (b) pass — one adult male figure, no child, no chibi, no second figure.
- (c) pass — orange jumpsuit, unmasked ordinary human head, both eyes show pupils. (The
  stencil renders as a literal "1.30" placard and the collar reads as a cowl rather than
  a jumpsuit collar; neither is part of the rule.)
- hands (excluded from the rule, observed anyway): both hands are pale blobs without
  digits — the chronic defect again.

Per the pre-registered fail branch: **nothing was seeded, and (A) closes 0 of the 14 slots
rather than 11.** `characters` and `character_cards` are untouched (asserted below).

**The instrument was checked before accepting the fail**, because a harness bug would look
identical. The compiled prompt does contain the pose clause verbatim —
`Angle: front — front view, facing camera, full body, feet visible, sitting on a plain
simple chair, seated pose` — so the text reached the model and the model ignored it.

```bash
uv run python - <<'PY'
import sys, os; from pathlib import Path
ROOT = Path(".").resolve(); sys.path[:0] = [str(ROOT/"src"), str(ROOT/"scripts")]
os.environ.setdefault("YTFLOW_PROJECT_ROOT", str(ROOT))
from seed_stock_cast import STOCK_DESCRIPTORS
from yt_flow.services.character_service import _ANGLE_DESCRIPTIONS, _POSE_DESCRIPTIONS, CharacterService
print(CharacterService._compile_generation_prompt(
    visual_descriptor=STOCK_DESCRIPTORS["STOCK-d-class"], angle="front",
    angle_description=f"{_ANGLE_DESCRIPTIONS['front']}, {_POSE_DESCRIPTIONS['sitting']}",
    scp_id="STOCK-d-class"))
PY
```

**This is the same defect as (B), and it falsifies the premise (A) was written on.** The
spec treated (A) as "missing assets, not a missing technique" — but the technique that
would have produced those assets is the same text-only pose instruction that (B) just
measured at 0/3. `seed_stock_cast.py --pose sitting` runs, and it would have written four
approved `sitting` card rows; three of the four angles were never even sampled here, and
the one that was came back standing. Seeding would have replaced a silent standing
fallback with a *labelled* `sitting` card that is also standing — strictly worse, because
the fallback at least logs `pose_fallback=True`.

Counter-evidence held on record rather than suppressed:
`assets/characters/SCP-049/epoch_1/sitting_front.png` (2026-07-07) **is** correctly seated
on a chair, so this recipe has produced a seated card before. That card is 832×1216 opaque
RGB on a grey background — no alpha, a pre-cutout chain — so it does not establish that
today's chain can, and it was not re-rendered here.

**Consequence, and what it is not.** The honest reading is that (A) and (B) are one defect
with one cause, and the fix that worked for (B) is the candidate for (A) as well: a seated
openpose guide. The closed catalog has no sitting guide (`humanoid_reaching_forward`,
`humanoid_lying_supine`, `humanoid_kneeling`, `humanoid_collapsed`, `creature_prone_lunge`,
`creature_rearing`), so authoring one plus a guided seeding path is new scope, was not
pre-registered here, and is **not** being decided unattended. Handed off, not fixed.

### DB and live-asset state (read-only assertions, since `git status` is vacuous here)

`yt_flow.db` matches `.gitignore:15`, so `git status --porcelain yt_flow.db` returns empty
whether or not the DB changed. The claim rests on this instead:

```bash
uv run python - <<'PY'
import sqlite3
c = sqlite3.connect("file:yt_flow.db?mode=ro", uri=True)
assert c.execute("select count(*) from characters").fetchone()[0] == 9
assert c.execute("select count(*) from character_cards").fetchone()[0] == 12
assert c.execute("select count(*) from character_cards where scp_id='STOCK-d-class' and pose='sitting'").fetchone()[0] == 0
assert c.execute("select angle_front_path from characters where scp_id='STOCK-d-class'").fetchone()[0] \
    == "characters/STOCK-d-class/epoch_2/front_candidate_1.png"
d = c.execute("select visual_descriptor from characters where scp_id='STOCK-d-class'").fetchone()[0]
assert "disproportionately large torso" in d, "the vision read-back is still appended (no seeding ran)"
print("DB unmutated: 9 characters, 12 cards, 0 sitting rows, standing paths and descriptor intact")
PY
```

`git status --porcelain assets/` is valid (`assets/` is tracked) and is empty: no live card
file was written. The pre-registered side effect of the seeding command — the
`visual_descriptor` losing its vision read-back — **did not occur**, because the command
was never run.

### Corrections after review (appended 2026-08-12; the PRE-REGISTRATION above is untouched)

1. **`git status --porcelain assets/` was the wrong instrument and its blank output proved
   less than claimed.** `.gitignore:19-20` is `assets/*` with only `!assets/manifest.json`
   unignored, so card PNGs are untracked and that command is blank whether or not one was
   written — the same vacuousness this file correctly flagged for `yt_flow.db`, and it
   applies to `assets/` too. The conclusion (nothing was seeded) still holds, on evidence
   that can actually fail: `find assets/characters -name 'sitting_*'` returns nothing, and
   every file in `assets/characters/STOCK-d-class/epoch_2/` is dated 2026-08-02/07/08,
   i.e. before this session. The read-only DB assertions above are unaffected.
2. **The single-variable comparison for the guide is L0 vs L2, not L1 vs L2.** L1 moves
   `ipadapter_weight` *and* drops the guide, so it differs from L2 in two variables; it
   exists to isolate the anchor hypothesis, and it answers that question (0/3). The
   guide's own effect rests on L0 (0.2, no guide) vs L2 (0.2, guide) — and L0 is the
   reused 10.6 leg, so the guide conclusion depends on frames rendered ~26 h earlier.
   That reuse was pre-registered and disclosed above; it is restated here because the
   decision table's row names L1 and L2 and could be read as the comparison.
   `measurements.jsonl` records no prompt/reference hash, so the "same prompt, same
   reference" premise for the reuse cannot be re-verified from the artifacts alone.
3. **Timing was reported warm-only.** L2's first render was 68.1 s against 28.8/28.8 s for
   the other two: ~44 s of one-time ControlNet load that a run paying
   `special_pose_max_per_run=3` will meet on its first guided card.
4. **(A)'s probe is n=1 and used the standing card as its IPAdapter anchor** (weight 0.2),
   which is the confound the story hypothesized for pose lock — so a standing result is
   partly what that setup predicts. L1's 0/3 at weight 0.0 is evidence against the anchor
   being the cause, but it was measured on the supine hint, not the sitting one. The probe
   also wrote no `measurements.jsonl` row and did not wait on the GPU queue. It is
   sufficient to *stop* a live write, which is what it was for; it is not sufficient to
   conclude "a sitting card can never be produced on this chain", and the deferred entry
   is worded as new scope rather than as a proven impossibility.
