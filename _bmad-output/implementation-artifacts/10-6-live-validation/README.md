# Story 10.6 — live validation (지적 14·15)

Working tree at pre-registration: `25bed30`. Pre-registered 2026-08-11T21:38+09:00,
**before any render in this directory existed** (`git log --diff-filter=A -- '_bmad-output/implementation-artifacts/10-6-live-validation/*'`
shows this README added first).

Recompute everything here with:

```bash
uv run python _bmad-output/implementation-artifacts/10-6-live-validation/render_legs.py
```

---

## PRE-REGISTRATION (written before rendering; not to be edited after seeing pixels)

### ② 지적 14 — is the ugly D-class pose-hint card caused by the missing negative suffix?

Two competing hypotheses for `assets/characters/STOCK-d-class/epoch_2/hint_a40ec9c170_front.png`
(`pose_hint="lying supine on table"`, `pose_hint_key("lying supine on table") == "hint:a40ec9c170"`):

- **H1 — missing suppression.** `generate_special_pose_card` (`character_service.py:949`) calls
  `provider.generate()` with **no `negative_suffix`**, so `STOCK_NEGATIVE` — which names
  `glowing eyes, monster, chibi, child` and which every base STOCK card *does* get
  (`scripts/seed_stock_cast.py:222`) — never reaches this path.
- **H2 — stale chain.** Both bad hint cards predate Story 10.3's 2026-08-09 removal of
  `horror.safetensors` (an SD1.5-layout LoRA whose UNet half was silently discarded), so they are
  artefacts of a chain that no longer exists and today's chain is already clean.

**Legs.** Identical prompt (`generate_special_pose_card`'s exact composition for `STOCK-d-class` /
`"lying supine on table"`), identical reference image (the live standing front card), identical
`ipadapter_weight` (`_ANGLE_IPADAPTER_WEIGHTS["front"]` = 0.2), identical dimensions.
3 renders per leg. `random.seed(s)` is pinned immediately before each `provider.generate()` call so
that leg A render *i* and leg B render *i* draw the **same KSampler seed** from `_inject_seed`'s
`random.randint`. Seed triple: `random.seed(1061)`, `random.seed(1062)`, `random.seed(1063)`.

| Leg | `negative_suffix` |
|---|---|
| ②-A | `None` — today's chain, current production behaviour |
| ②-B | `STOCK_NEGATIVE` verbatim — today's chain, the H1 fix |

**Failure criteria (per render, judged by viewing the PNG).** A render **fails** if ANY of:

- (a) neither eye shows a pupil/iris;
- (b) shoulder-width exceeds ~3× head-width, or the head is otherwise non-human-proportioned;
- (c) neither hand resolves into distinguishable digits.

**Decision table (fixed; no post-hoc tuning).**

| Leg A fails | Leg B fails | Conclusion |
|---|---|---|
| ≥2/3 | ≤1/3 | **H1** — the missing suffix. Ship `negative_suffix` on the special-pose path + a kwarg test. |
| ≤1/3 | ≤1/3 | **H2** — 10.3's LoRA removal already fixed it. **No code change to `character_service.py`.** 지적 14 becomes "regenerate the two stale hint cards", a Jay gate. |
| ≥2/3 | ≥2/3 | **Neither.** Record the frames and HALT `blocked`. Do not invent a third hypothesis unattended. |

**Control leg.** The historical `assets/characters/STOCK-d-class/epoch_2/hint_a40ec9c170_front.png`
(2026-08-07, pre-10.3 chain). It is asserted to fail all three criteria; that assertion is verified by
viewing below and is what makes "today's chain is already clean" falsifiable rather than an absence of
evidence.

### ① 지적 15 — is the plague-doctor look on SCP-049-2 caused by the inherited descriptor?

Same pinned seed (`random.seed(1051)`) for both legs, same chain, same day — so the **descriptor is
the only variable**, not a new seed.

| Leg | descriptor | anchor | negative_suffix | enrich_ban |
|---|---|---|---|---|
| ①-old | `characters.SCP-049.visual_descriptor` verbatim + `"\nA reclassified/duplicate instance of SCP-049."` (the pre-fix rule, `run_service.py:612-615`) | `assets/characters/SCP-049/<epoch>/front_candidate_1.png` (IPAdapter identity lock, the pre-fix rule) | `None` (pre-fix) | `None` (pre-fix) |
| ①-new | `DERIVED_DESCRIPTORS["SCP-049-2"]` (authored, maskless) | `None` | `STOCK_NEGATIVE` | `BANNED_STOCK_TOKEN` (no effect on the render itself — it only scrubs the persisted read-back — recorded for completeness) |

**Pass rule (pre-registered).** ①-new passes iff the rendered head is an **unmasked human head**
(visible face, no beaked mask, no covering) and the figure wears **no hooded coat**; and ①-old is
expected to reproduce the plague-doctor look. If ①-new comes back masked anyway, that is recorded as
a contradiction of the `enrich_ban`/descriptor hypothesis, not re-tuned away.

---

## RESULTS

Rendered 2026-08-11 21:49–22:16 KST, `ComfyUICharacterProvider`, workflow
`data/workflows/comfyui_character_multi_angle_api.json` (AnimagineXL v3.1 +
`darkness_xl_v2` @0.3; `horror.safetensors` absent — removed by Story 10.3 on 2026-08-09).
ComfyUI `/system_stats` returned `200` before and after. All 8 PNGs have an alpha channel
(the script asserts it and prints `alpha=True` per render).

### ② 지적 14 — decision: **H1. The missing negative suffix.**

| Leg | seed 1061 | seed 1062 | seed 1063 | fails |
|---|---|---|---|---|
| ②-A (no suffix) | **FAIL** (c) | pass | **FAIL** (c) | **2/3** |
| ②-B (`STOCK_NEGATIVE`) | **FAIL** (c) | pass | pass | **1/3** |
| control `hint_a40ec9c170` (2026-08-07, pre-10.3) | **FAIL** (a)(b)(c) | — | — | 1/1 |

Decision-table row **`A ≥2/3` + `B ≤1/3` → H1**. Code change shipped:
`character_service.py` now passes a negative suffix on the special-pose path
(`CharacterService._maskless_negative_suffix`), covered by
`tests/services/test_character_service_generation.py::test_generate_special_pose_card_applies_stock_negative_to_maskless_keys`.

**Per-render judgments (written from viewing each PNG, and from 8–10× crops of the eye
and hand regions — the criteria are not decidable at page scale).**

- **control `assets/characters/STOCK-d-class/epoch_2/hint_a40ec9c170_front.png`** —
  (a) **fail**: both eyes are round, wholly white, no pupil and no iris at all.
  (b) **fail**: hulking torso, tiny head, mottled face.
  (c) **fail**: both hands are lumpy mittens with smeared internal lines, no digits.
  Fails all three, exactly as pre-registered. Also standing upright although
  `"lying supine on table"` was requested → hand-off to 10.5 (below).
- **②-A r1 (seed 1061)** — (a) pass: the near eye shows an amber iris under a heavy
  lid. (b) pass. (c) **fail**: the near hand is a smooth pale blob tucked into the suit
  with one stray line, the far hand a mottled patch; neither resolves into digits.
  → **FAIL**
- **②-A r2 (seed 1062)** — (a) pass, (b) pass, (c) pass (the adult's fist shows knuckle
  and finger separations). → **passes the pre-registered criteria**, and yet the frame is
  unusable: it contains **two figures, the second a chibi child** in a matching orange
  jumpsuit, hand in hand. See "what the pre-registration missed" below.
- **②-A r3 (seed 1063)** — (a) pass: both eyes carry a small pupil. (b) pass.
  (c) **fail**: both hands are smooth pale masses with faint mottling, no digit lines —
  the same defect class as the control. → **FAIL**
- **②-B r1 (seed 1061)** — (a) pass: near eye has a navy iris. (b) pass. (c) **fail**:
  near hand a pale blob in the suit, far hand a half-degraded mottled shape. → **FAIL**
- **②-B r2 (seed 1062)** — (a) pass: a thin dark pupil in each white sclera. (b) pass.
  (c) pass: both hands are splayed with clearly separated fingers. → **pass**. Single
  adult figure; the chibi child of ②-A r2 **at the same seed** is gone.
- **②-B r3 (seed 1063)** — (a) pass, (b) pass, (c) pass: both hands show curled fingers
  with distinct separations, against ②-A r3's featureless blobs **at the same seed**.
  → **pass**

**What the pre-registration missed, recorded rather than patched.** Criteria (a)(b)(c)
cover eyes, proportions and hands; they do **not** cover multi-figure or child renders.
The single most dramatic same-seed difference in the whole experiment is therefore
invisible to the rule that decided the experiment: at seed 1062 leg A produced an adult
plus a chibi child and leg B a single adult, and `STOCK_NEGATIVE` names exactly
`2boys, child, 1girl, chibi, character sheet, multiple views`. That is supporting
evidence for the same conclusion, not the basis of it — the decision above stands on the
2/3-vs-1/3 count from the rule as written. Had the rule been the only instrument, it
would have scored that pair as A-pass/B-pass. Next pre-registration of a card-quality
rule should include a figure-count criterion.

**Second recorded surprise: criterion (c) is chronic, not suffix-specific.** Hands failed
in 3 of 6 renders across *both* legs (A: 2, B: 1), and the two ②-B passes are noisy at the
edges. The suffix moved hands at seeds 1062/1063 but not 1061. Suffix or no suffix, this
chain does not reliably draw a hand — a standing gap, not something this story fixes.

**Supporting pixel measurements — and why they do not decide anything.** Bands are fixed
fractions of the alpha bounding box: `head_w` = widest alpha row in the top 10% of the
bbox, `shoulder_w` = widest alpha row in 18–30% of the bbox. Recompute all of them with:

```bash
uv run python - <<'PY'
from PIL import Image
import glob
def m(p):
    a = Image.open(p).convert("RGBA").split()[3]; W, H = a.size; px = a.load()
    ys = [y for y in range(H) if any(px[x, y] > 8 for x in range(W))]
    y0, bh = ys[0], ys[-1] - ys[0] + 1
    w = {y: max(x for x in range(W) if px[x, y] > 8) - min(x for x in range(W) if px[x, y] > 8) + 1 for y in ys}
    band = lambda a_, b_: max((w[y] for y in ys if y0 + a_ * bh <= y < y0 + b_ * bh), default=0)
    h, s = band(0.0, 0.10), band(0.18, 0.30)
    print(f"sh/head={s/h:5.2f}  sh/bbox_h={s/bh:5.3f}  head_w={h:4d} shoulder_w={s:4d} bbox_h={bh:4d}  {p}")
for p in sorted(glob.glob("_bmad-output/implementation-artifacts/10-6-live-validation/leg2*.png")) + [
        "assets/characters/STOCK-d-class/epoch_2/hint_a40ec9c170_front.png",
        "assets/characters/STOCK-d-class/epoch_2/front_candidate_1.png"]:
    m(p)
PY
```

| frame | sh/head | sh/bbox_h |
|---|---|---|
| ②-A r1 / r2 / r3 | 1.47 / 1.57 / 2.34 | 0.251 / 0.277 / 0.268 |
| ②-B r1 / r2 / r3 | 1.58 / 1.86 / 2.40 | 0.262 / 0.338 / 0.270 |
| control `hint_a40ec9c170` (defective) | **3.04** | **0.436** |
| control `front_candidate_1` (healthy, 8.15-approved) | **2.83** | **0.290** |
| `hint_970ede32f4` (the other live hint row) | 2.69 | 0.363 |

`sh/head` separates the two *controls* by only 3.04 vs 2.83 — it is **not a usable
discriminator** for criterion (b), because the band catches hair width at the top and
sleeve width at the shoulders. `sh/bbox_h` does separate them (0.436 vs 0.290, a 1.5×
gap) and is the number worth reusing. Recorded per the epic's own rule that a metric
which fails to move with the viewing verdict is itself a finding; criterion (b) was
judged by viewing in every row above.

### ① 지적 15 — result: the new rule stops producing a second SCP-049

Same pinned seed (1051), same chain, same hour.

**What this pair does and does not establish.** It compares the **whole rule**, not one
variable: ①-old and ①-new differ in the descriptor, the IPAdapter anchor, the negative
suffix, *and* the graph topology (with `ref=None` the provider takes its t2i path instead
of i2i, so the shared RNG seed is not a paired sample either). Dropping the base front card
as an identity anchor could account for the entire difference on its own — an IPAdapter lock
onto SCP-049's own card is a sufficient explanation for a plague doctor coming back. So the
honest claim is "the new rule no longer renders a second SCP-049", which is the story's
requirement. Do **not** upgrade this to "the descriptor was the cause"; that attribution
would need a third leg holding the anchor fixed, which was not run.

- **①-old `leg1-old_inherited-descriptor_seed1051.png`** — a hooded figure in a long dark
  coat with a **white beaked plague-doctor mask** and dark gloves. Same character as
  `assets/characters/SCP-049/epoch_1/front_candidate_1.png`. **Reproduces 지적 15.**
- **①-new `leg1-new_authored-descriptor_seed1051.png`** — an **unmasked human head**,
  visible gaunt face, short dark hair, **no hood and no coat**; a pale sage-green
  surgical wrap gown and bare feet. **Passes the pre-registered ① rule.**

Recorded fidelity gaps in ①-new (the look is distinguishable, which is what the story
needed, but the authored descriptor is not fully honoured): the suture line is barely
legible, the skin reads sallow rather than ashen grey, the eye colour is not clearly grey,
and the scrubs read as a full-length gown rather than *torn* scrubs. Also note the
generation prompt **template** (`prompts/character/generation.md`) contains the string
"an SCP Foundation video" and therefore reached **both** legs equally — the mask attractor
was present in ①-new's prompt and the head still came back bare, so `enrich_ban` did not
have to carry the result. Changing that template is a `docs/PROMPT_POLICY.md` change and
was out of this story's scope.

Live confirmation of the cause, for the record (read-only queries):

```bash
sqlite3 -readonly yt_flow.db "select scp_id, substr(visual_descriptor,1,160) from characters where scp_id in ('SCP-049','SCP-049-2');"
```

returns the **same** plague-doctor descriptor for both keys, `SCP-049-2`'s with
`"\nA reclassified/duplicate instance of SCP-049."` appended — exactly what
`_ensure_derived_entity_cards` used to build. Nothing here was written; the live cards and
DB rows are untouched.

**How that "untouched" claim is actually checked.** `git status --porcelain assets/` is valid
(`assets/` and `assets/manifest.json` are tracked). `git status --porcelain yt_flow.db` is
**not** — `.gitignore:15` matches `yt_flow.db*`, so the file is untracked and that command
returns empty whether or not the DB was mutated. It is vacuous as evidence. The DB claim
rests on this instead, which asserts the pre-story values directly:

```bash
uv run python - <<'PY'
import sqlite3
c = sqlite3.connect("file:yt_flow.db?mode=ro", uri=True)
assert c.execute("select count(*) from characters").fetchone()[0] == 9
assert c.execute("select count(*) from character_cards").fetchone()[0] == 12
d = c.execute("select visual_descriptor from characters where scp_id='SCP-049-2'").fetchone()[0]
assert d == ("SCP-049 plague doctor humanoid, black hooded robe, white beaked plague doctor "
             "mask, dark gloves, full body\nA reclassified/duplicate instance of SCP-049.")
print("DB unmutated: 9 characters, 12 cards, SCP-049-2 still holds the inherited descriptor")
PY
```

Verified passing after implementation. Note what the third assertion means: the **fix is not
retroactive**. `SCP-049-2`'s live row still carries the inherited plague-doctor descriptor and
its live cards are still the masked ones — the new rule only applies the next time a derived
card is provisioned from scratch. Replacing the existing asset is the Jay gate in
`deferred-work.md`, and until it is taken, 지적 15 remains visible in any run that reuses the
current `SCP-049-2` cards.

### D-class base-asset verdict (8.15-approved `epoch_2/*_candidate_1.png`)

Per-frame, from viewing each file. The 지적 14 defect is **없음** in this set — it is not
the approved standing library, it is the ungated pose-hint card.

| frame | 지적 14 defect (blank eyes / inflated torso / blob hands) | other observations |
|---|---|---|
| `front_candidate_1.png` | **없음** — pupils present, `sh/bbox_h` 0.290, hands small but with digit lines. A correct gaunt man in his thirties in an orange numbered jumpsuit. | none |
| `back_candidate_1.png` | **없음** | renders a **frontal** view, not a back view, and reads as a younger, slighter person than the front card — an angle-turn + cross-angle identity issue, 8.15-era, not 지적 14 |
| `side_candidate_1.png` | **없음** | also near-frontal rather than a side profile, **and carries a floating black speech-balloon-shaped blob containing "12" beside the shoulder, inside the sprite's alpha** — a real visible artefact in a live approved asset |
| `three_quarter_candidate_1.png` | **없음** | the cleanest of the non-front angles; a plausible three-quarter turn |

The two non-front findings are not this story's 지적 and were not touched. They belong with
the "regenerate the approved library against today's chain" gate already recorded in
`deferred-work.md` from Story 10.3.

### Usage counts (why the hint card mattered)

`STOCK-d-class` appeared in **19** of the reviewed run's cast slots and the
`hint:a40ec9c170` card was selected for **7** of them; `SCP-049` **41**, `SCP-049-2`
**13**; zero intra-shot duplicate card keys. Control for the "7" is the same query's total
for the same key in the same run (19). Recompute (read-only, run `8a9a288b`):

```bash
uv run python - <<'PY'
import sqlite3, sys
sys.path.insert(0, "src")
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from yt_flow.services.character_service import pose_hint_key
c = sqlite3.connect("file:yt_flow.db?mode=ro", uri=True)
t, b = c.execute("select type, checkpoint from checkpoints where thread_id like '8a9a288b%' "
                 "order by checkpoint_id desc limit 1").fetchone()
scenes = JsonPlusSerializer().loads_typed((t, b))["channel_values"]["scenes"]
keys, hints, tot, hit = {}, {}, 0, 0
for sc in scenes:
    for sh in sc.get("shots", []):
        for m in sh.get("cast") or []:
            k, ph = m.get("card_key"), (m.get("pose_hint") or "").strip()
            keys[k] = keys.get(k, 0) + 1
            if ph: hints[(k, ph, pose_hint_key(ph))] = hints.get((k, ph, pose_hint_key(ph)), 0) + 1
            if k == "STOCK-d-class":
                tot += 1
                hit += ph and pose_hint_key(ph) == "hint:a40ec9c170"
print("cast usage:", keys); print("pose_hints:", hints)
print(f"STOCK-d-class slots={tot}  using hint:a40ec9c170={hit}")
PY
```

Output at the time of writing: `{'STOCK-d-class': 19, 'SCP-049': 41, 'SCP-049-2': 13}`,
`{('SCP-049','extending hand','hint:7031f483b8'): 1, ('STOCK-d-class','lying supine on table','hint:a40ec9c170'): 7, ('SCP-049-2','lying on operating table','hint:475c8a9231'): 1}`,
`slots=19 using hint:a40ec9c170=7`.

### Hand-offs (recorded, deliberately not fixed here)

1. **→ Story 10.5 (지적 6, action state on cards).** Every one of the seven renders that
   was asked for `"lying supine on table"` — the historical control, all three ②-A and all
   three ②-B — came back **standing or seated, never supine** (②-B r2 is the closest: a
   half-seated lean). The pose hint reaches the prompt and the model ignores it. Story
   10.6's Boundaries forbid fixing it; 10.5 owns it.
2. **→ `deferred-work.md`.** Pose-hint cards are auto-approved with no human gate
   (`character_service.py:966` approves the asset and saves the card row in the same
   unattended pass), which is how the 지적 14 frame reached production. Appended there,
   together with the two Jay gates (promote/reject the regenerated `SCP-049-2` look;
   decide the fate of `hint:a40ec9c170` and `hint:970ede32f4`).
3. **`hint_970ede32f4_front.png`, judged for completeness** (it is the other live epoch_2
   D-class hint row): (a) **pass** — blue irises with pupils; (b) borderline pass —
   heavyset, `sh/bbox_h` 0.363 against the healthy 0.290 and the defective 0.436;
   (c) **fail** — both hands are claw-like blobs. It was **not** selected in the reviewed
   run (no `pose_hint` in those scenes resolves to it), so it is not the frame Jay saw.
