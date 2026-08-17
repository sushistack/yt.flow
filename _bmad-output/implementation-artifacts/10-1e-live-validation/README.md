# Story 10.1e — recompose ON/OFF paired scoring, and the default verdict

Run `e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889`, scored 2026-08-17T17:06:28+0900. Every number below is re-derivable from `results.json` + `pairs.json` + `on.json` with `run_pairs.py report`.

## VERDICT: **(a) closed PASS, (c) still blocks** — `shot_recompose_enabled = False`

Deciding axis (blind `readable`, paired, n=33): **b=2, c=1, b−c=1** against the pre-registered `b−c ≤ 1` ⇒ FLIP.  
Veto (≥5 of 40 passes fail): 0 failed ⇒ not triggered.  
Cost: 107.9s/pass (mtime deltas over 32 shots / 39 passes) × 40 passes = 1.2 h added to a 43-shot run ⇒ over the 1.0 h line in 10.1c item (c).

## 1. Screening — why 10.4's claim (a) is not a treatment measurement

`baseline_v2.json`'s 66 rows, split two ways:

| split | n | unreadable | blind `place` = corridor |
|---|---:|---:|---:|
| frame is `recomposed/` | 51 | 10 (19.6%) | 29 (56.9%) |
| frame is `images/` (plate) | 15 | 2 (13.3%) | 4 (26.7%) |
| shot cast is non-empty | 51 | 10 (19.6%) | 29 (56.9%) |
| shot cast is empty | 15 | 2 (13.3%) | 4 (26.7%) |

Shot-id overlap between the two arms: **0**. Contingency `{'recomposed_x_cast_present': 51, 'recomposed_x_cast_empty': 0, 'plate_x_cast_present': 0, 'plate_x_cast_empty': 15}`. The two splits select byte-identical shot sets (`splits_identical: True`).

> arm and cast-presence are 100% collinear in baseline_v2.json: the two splits select byte-identical shot sets, so no arithmetic on these 66 rows can separate 'recompose hurt legibility' from 'shots containing characters read as corridors'. 10.4's 20%/13% and 57%/27% are not treatment measurements.

## 2. The paired set

- 43 shots in the run, 33 recompose-eligible, **33 paired**, 40 recompose passes.
- Cast cards resolved **once** (`pairs.json`) and consumed by both arms, so angle selection is held constant.
- OFF: `render_composite_still` → `_build_card_chain` (harmonization tier 1, production `ground_y`/`occlusion_mask` from `compositing_service.resolve_placements`), 1920×1080.
- ON: `recompose_run_shots`, one call, preflight live — `{'recomposed': 33, 'skipped': 0, 'failed': 0}`; frames re-framed through the OFF arm's own `_zoompan_filter` chain so resolution and crop cannot identify the arm.
- Scored blind (frame bytes only) with 13-2's `BLIND_PROMPT`, then DSG. Judge `qwen-vl-plus`, QG `qwen-plus`, temperature 0, reps 1.

## 3. Deciding axis — blind `readable`, paired

| | ON readable | ON unreadable |
|---|---:|---:|
| **OFF readable** | 28 | **b = 2** |
| **OFF unreadable** | **c = 1** | 2 |

`b − c = 1`. Pre-registered: FLIP iff `b − c ≤ 1`, STAY OFF iff `b − c ≥ 2` ⇒ **FLIP**.

- b (readable OFF, unreadable ON): `S00501`, `S00600`
- c (unreadable OFF, readable ON): `S00405`

Per-arm marginals (record-only — the paired table above is the decision):

| arm | scored | readable | unreadable | `place`=corridor | `place` unclear | `event` unclear | mean DSG |
|---|---:|---:|---:|---:|---:|---:|---:|
| OFF (overlay) | 33 | 30 | 3 (9.1%) | 9 (27.3%) | 0 | 3 | 0.4443 |
| ON (recompose) | 33 | 29 | 4 (12.1%) | 10 (30.3%) | 0 | 5 | 0.4615 |

**Both directions, as the rule requires.** Secondary axes never override the deciding axis; they are printed here so a reader can see which way each one points, including the ones that point against the verdict:

- corridor misread: OFF 27.3% vs ON 30.3% (ON worse)
- mean DSG: OFF 0.4443 vs ON 0.4615 (ON better or equal); DSG errored OFF 1 / ON 1, QA errors OFF 0 / ON 0 (a nonzero QA-error count biases that arm's mean DOWN and is not a frame defect)
- `event` unclear: OFF 3 vs ON 5

## 4. Cost (10.1c item (c), record-only for the (a) decision)

- ON arm wall clock: **312.5s** for 40 completed passes across 33 shots ⇒ **107.9s/pass**.
- Projected onto this run's 40 passes: **1.2 h** added to a 43-shot run.
- ComfyUI argv during the render: `['main.py', '--preview-method', 'auto', '--cache-lru', '10', '--lowvram']`.

## 5. Per-shot rows

| shot | OFF readable | ON readable | OFF place | ON place | OFF DSG | ON DSG |
|---|---|---|---|---|---:|---:|
| `S00101` | True | True | a tiled examination room | a tiled examination room | 0.3333 | 0.5 |
| `S00102` | True | True | a concrete corridor with a pool of | a metallic containment pool | 0.3333 | 0.3333 |
| `S00103` | True | True | a dimly lit industrial room | a dimly lit industrial room | 0.5 | 0.5 |
| `S00104` | True | True | a circular room with a tiled floor | a circular room with a ceiling lig | 0.0 | 0.0 |
| `S00200` | False | False | a concrete corridor | a concrete corridor | 0.0 | 0.0 |
| `S00202` | True | True | a barred cell in a detention facil | a barred cell in a corridor | 1.0 | 1.0 |
| `S00203` | True | True | a dimly lit corridor with filing c | a dimly lit corridor with filing c | 0.5 | 0.5 |
| `S00204` | True | True | a corridor with walls covered in p | a corridor with walls covered in p | 0.5 | 0.5 |
| `S00300` | True | True | a tiled examination room | a concrete corridor | 0.3333 | 0.3333 |
| `S00301` | True | True | a laboratory | a tiled examination room | 0.5 | 0.6667 |
| `S00302` | False | False | a high-tech control room | a high-tech control room | 0.25 | 0.6 |
| `S00303` | True | True | a tiled examination room | a tiled examination room | 0.3333 | 0.3333 |
| `S00402` | True | True | a tiled examination room | a tiled examination room | 0.0 | 0.0 |
| `S00404` | True | True | a tiled examination room | a dimly lit corridor with tiled fl | 0.3333 | 0.3333 |
| `S00405` **c** | False | True | a high-tech control room | a high-tech observation room | 0.0 | 0.5 |
| `S00501` **b** | True | False | a sterile laboratory | a tiled examination room | 1.0 | 0.0 |
| `S00502` | True | True | a tiled examination room | a medical examination room | 0.3333 | 0.3333 |
| `S00503` | True | True | a tiled examination room | a tiled examination room | 1.0 | 1.0 |
| `S00504` | True | True | a concrete corridor | a tiled corridor | 0.0 | 0.6667 |
| `S00505` | True | True | a damaged corridor | a damaged corridor | None | None |
| `S00600` **b** | True | False | a tiled examination room | a tiled examination room | 0.3333 | 0.3333 |
| `S00601` | True | True | a high-tech laboratory | a high-tech laboratory | 0.8 | 0.75 |
| `S00602` | True | True | a dimly lit examination room | a dimly lit examination room | 0.0 | 0.0 |
| `S00603` | True | True | a circular, tunnel-like structure | a circular, futuristic chamber | 0.0 | 0.3333 |
| `S00700` | True | True | a concrete corridor | a dimly lit, industrial-style room | 0.5 | 0.3333 |
| `S00702` | True | True | a tiled examination room | a sterile examination room | 0.6667 | 0.6667 |
| `S00703` | True | True | a tiled examination room | a tiled examination room | 1.0 | 0.6667 |
| `S00704` | True | True | a cracked and damaged room | a dimly lit room with cracked wall | 0.5 | 1.0 |
| `S00800` | True | True | a concrete corridor | a dimly lit corridor with a green  | 0.0 | 0.0 |
| `S00801` | True | True | a tiled examination room | a dimly lit room with tiled floor | 1.0 | 0.6667 |
| `S00802` | True | True | a high-tech observation room | a high-tech examination room | 1.0 | 0.75 |
| `S00901` | True | True | a tiled examination room | a tiled examination room | 0.5 | 0.5 |
| `S00903` | True | True | a dimly lit corridor with paneled  | a dimly lit corridor with paneled  | 0.6667 | 0.6667 |

## 6. Re-derive

```
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py screen
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py manifest
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py render-off
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py render-on
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py score
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py report
uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py grid
```

`off/`, `on/` and `blind/` are gitignored raw renders — see this directory's `.gitignore` for what regenerates them and what must never be blanket-deleted.

## 7. Sample band

Every rate above is over the **33 paired shots** of run `e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889` (scenes [1, 2, 3, 4, 5, 6, 7, 8, 9]), one blind call per frame at temperature 0, `qwen-vl-plus`. The blind prompt is 13-2's `BLIND_PROMPT` unchanged, including its `_CARD_NOTE` sentence — which tells the judge the frame is a background plate whose people are composited later. That sentence is wrong for BOTH arms here (both carry figures) and is deliberately left in: changing it would make this not 13-2's instrument, and it biases both arms identically.


## HUMAN OVERRIDE

# Human override of the pre-registered verdict — 2026-08-17

`verdict.json` records what the **rule** concluded: `"(a) closed PASS, (c) still blocks"`,
i.e. `shot_recompose_enabled_per_rule = false`. The shipped default is `true`.

**What overrode it.** Jay watched `viewing/all_pairs.mp4` — the paired OFF|ON motion clips
built for the axis the score never read — and ruled: *"recompose 무조건 해야하고"*
("recompose is a must"). The epic's closure standard authorises this: *"a viewing verdict
overrides a favorable measurement"*, and symmetrically an unfavorable one. The override is
against the **cost line only**; the deciding legibility axis had already resolved to FLIP.

**What is therefore now paid on every run:** the measured 1.2 h, over the pre-registered
1.0 h line.

**What the override does NOT do.** It does not make the measurement stronger. The deciding
axis resolved FLIP on 3 discordant pairs (exact McNemar p = 1.00; 95% CI on the unreadable
difference [-7.2, +13.3] pp, which contains the incumbent's own 7 pp claim). n=33 rules out
a catastrophe and nothing finer. And `b=2` does not survive looking at the frames — see
`viewing.json:read_once_observations`.

**Known limits of the evidence the override was formed on** — recorded because they were
found in review, after the verdict:

1. **The first build of the viewing clips handicapped the incumbent.** It hardcoded
   `composite_harmonization_tier=0`, which switches off `build_sprite_tint` AND
   `build_contact_shadow` (`video.py:1577` / `:1650`, both gated on `tier >= 1`) — exactly
   the two features the flip rationale cites as the ON arm's advantage — while the *scored*
   OFF arm used production tier 1. `cmd_viewing` now reads
   `Settings().composite_harmonization_tier`, and the clips were re-rendered at tier 1 on
   2026-08-17. **Jay's verdict was formed on the tier-0 build.** Re-watching the tier-1
   clips is the cheap confirmation; the override stands until he says otherwise.
2. **11.5 depth parallax is excluded from both arms** (it needs the injected 2.5D renderer;
   without it `build_motion_source` falls back to legacy Ken Burns). Parallax is an
   OFF-arm-only motion layer, so the clips still understate the incumbent on motion.
3. **`S00405` — the one `c` shot in the package — has no shipped clip**, so it plays at the
   4.0 s fallback duration rather than production zoom velocity, and velocity is what a
   "does it float" judgement reads.

**Consequence that follows from the flip and is owed as a separate story:** under the
default, the card-compositing machinery is exercised by **no** shot of run `e5ed4b3a` — the
10 ineligible shots are ineligible for having an *empty cast*, and `_build_card_chain` is
only entered for a non-empty card list. See `deferred-work.md`.
