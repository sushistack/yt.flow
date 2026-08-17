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
