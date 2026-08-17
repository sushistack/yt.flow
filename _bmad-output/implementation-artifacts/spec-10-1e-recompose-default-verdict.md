---
title: 'Story 10.1e — Recompose on/off paired scoring and default verdict (10.1c unblock condition (a))'
type: 'feature'
created: '2026-08-16'
status: 'done'
review_loop_iteration: 0
baseline_revision: 'ac6434d'
final_revision: '0d6ad40'
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `shot_recompose_enabled` stays `False` mainly on claim (a): 10.4's audit scored recomposed frames worse on blind legibility (unreadable 20% vs 13%, misread-as-corridor 57% vs 27%). That claim is **not a treatment measurement** — screening the committed `baseline_v2.json` shows the 51 "recomposed" rows and the 15 "plate" rows are **disjoint shot sets**, and the split is byte-identical to splitting the same 66 rows by *cast presence* (all 15 plate rows have `cast == []`, all 51 recomposed rows have cast). Arm and cast-presence are 100% collinear, so the number cannot separate "recompose hurt legibility" from "shots containing characters read as corridors". Nobody has scored the same shots both ways.

**Approach:** Render **the same 33 recompose-eligible shots of run `e5ed4b3a`** twice from the same plates and the same resolved cast cards — once through the shipped overlay path (`render_composite_still`, which drives the production `_build_card_chain`) and once through `recompose_run_shots` — then score both arms with 13-2's instrument, blind axis first, under a decision rule written and committed **before** any score is read. Measure the per-pass cost on a correctly-started ComfyUI. Write the verdict into `config.py` whichever way it falls.

## Boundaries & Constraints

**Always:** Both arms use identical shots, identical plates, and one **frozen** cast manifest resolved exactly once (`resolve_cast_cards` makes an LLM angle call per key — resolving twice would make the arms differ in cards). The ON arm goes through `recompose_run_shots`, not `recompose_shot`, so the 10.1d preflight is exercised live for the first time. The OFF arm carries production `ground_y`/`occlusion_mask` from the same ground resolver `api/main.py` injects — a bottom-anchored card set is the pre-8.16 look and would understate the incumbent. `PREREGISTRATION.md` is written **and committed** before the scorer runs. Every reported number is re-derivable from committed `results.json` + the committed harness. ComfyUI's original argv is restored when the render finishes.

**Block If:** ComfyUI's `/queue` is non-empty with another session's workflows and does not go idle — restarting it would kill work this run does not own; HALT blocked `comfyui occupied by another session`. Or the preflight cannot be satisfied after a correct restart (free RAM stays under `recompose_preflight_min_free_ram_gb`) — HALT blocked with the observed reading, since a false-bail on a healthy box is itself 10.1d's recorded residual risk #2 and its resolution is a human call on the floor value. Or `YTFLOW_CHARACTER_VISION_API_KEY` is absent.

**Never:** Do not choose or amend the threshold after seeing a score. Do not retire the overlay-only machinery here (ground placement, `_GROUND_Y_MAX`, occlusion, contact shadow, 11.5 parallax, 1.9c idle motion) even if the default flips — that is a follow-up with its own evidence, and AC7 is answered by saying so, not by deleting. Do not re-run 10.4's `run_baseline.py` default mode (it `KeyError`s on the removed `legible` field). Do not compare against bare plates. Do not widen the preflight, the health timeouts, or `REQUIRED_FLAGS` to make the render start. Do not modify `score_shot_narration.py`'s prompts or thresholds — a changed instrument is not 13-2's instrument. Do not publish `visual_score.json` into the run workspace from this harness.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Screening | committed `10-4-live-validation/baseline_v2.json` | `screen` emits the arm×cast-presence contingency table proving collinearity; 51/15 disjoint, 0 overlap | No error expected; no network, no GPU |
| Manifest | e5ed4b3a checkpoint | `pairs.json`: 33 shots × {plate, cast[path,position,depth,pose], sentences}; 40 recompose passes | A shot whose card `path` fails to resolve is dropped from **both** arms and listed with its reason |
| OFF arm | manifest + ground resolver | 33 PNGs at 1920×1080 in `off/` | `render_composite_still` returns `None` → shot dropped from both arms, recorded |
| ON arm | manifest, ComfyUI started correctly | 33 PNGs in `on/`, per-pass wall-clock recorded | A pass returning `None` drops that shot from both arms and counts toward the ≥5-failure veto |
| Preflight bails | ComfyUI missing a flag / low RAM | Harness stops before any render and prints the preflight message verbatim | Not a crash — the message is the artifact; fix ComfyUI and re-run |
| Arm sizes differ | ON still is plate-sized (1344×768), OFF is 1920×1080 | ON stills scaled to 1920×1080 before scoring, so frame size never identifies the arm | Recorded in the report |
| Scoring | `blind/<opaque-id>.png` | Blind `readable`/`place`/`event` per frame (image bytes only, no sentence, no filename in prompt) + DSG per frame (sentence-fed, secondary) | A `dsg_error` row is excluded from the DSG mean and counted; it never affects the blind axis |
| Verdict | `results.json` + `PREREGISTRATION.md` | `b − c` applied mechanically; both directions reported | If discordant pairs are 0 in both directions the rule yields FLIP (b−c = 0 ≤ 1); report the zero-power caveat rather than inventing a tiebreak |

</intent-contract>

## Code Map

- `src/yt_flow/services/recompose_service.py:205` -- `recompose_run_shots(scenes, cast_cards, settings) -> (remaining, stats)`; mutates `shot["image_path"]` in place, writes `<run_dir>/recomposed/<shot_id>_<digest16>.png`. `_preflight` at `:126`, `REQUIRED_FLAGS` at `:63`, `CARD_LOOKS` at `:32` (the eligibility gate). No subset parameter — pass a hand-built `scenes` list.
- `src/yt_flow/pipeline/nodes/video.py:1420` -- `render_composite_still(shot, cards, out_path, *, mood, composite_harmonization_tier)`. Caller-less **by decision**, kept as a measurement tool; drives the production `_build_card_chain` so scale/anchor/`ground_y`/occlusion/tint/shadow/z-order all come from the shipped implementation. Returns `None` (never raises) and refuses an empty `cards` list. Output 1920×1080.
- `src/yt_flow/api/main.py:100-120` -- how the three resolvers are built and injected (`_precompute_relights`, `_recompose_shots`, `_resolve_grounds`); the harness copies this wiring rather than reimplementing placement.
- `src/yt_flow/services/eval_service.py:763` -- `_load_state(run_id, db_path)`; open the DB read-only (`file:yt_flow.db?mode=ro`) — other sessions run concurrently.
- `scripts/score_shot_narration.py` -- 13-2's instrument. `BLIND_PROMPT:113` (frame-only, the deciding axis), `ask(settings, prompt, image_bytes):293`, `_score_dsg(settings, row, sentences, image_bytes):545` (in-place, never raises), `dsg_score():510`, `summarize_dsg():709`. Import it; do not edit it and do not use `score_run` (it is run-id/checkpoint driven and publishes `visual_score.json`).
- `_bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py:47-55,201` -- the frame-list-driven scoring idiom to copy (`ROOT = parents[3]`, `os.chdir(ROOT)`, per-frame `_score_dsg`).
- `_bmad-output/implementation-artifacts/10-4-live-validation/baseline_v2.json` -- the incumbent data; `README.md:47-50` the incumbent table.
- `_bmad-output/implementation-artifacts/10-1b-live-validation/.gitignore` -- the `.gitignore` header style CLAUDE.md says to copy.
- `src/yt_flow/config.py:314-368` -- the 10.1c verdict comment; item (a) REWRITTEN by this story at `:332`; `shot_recompose_enabled:369` — flipped to `True` by this story on Jay's viewing verdict; the 10.1d RAM-floor comment gains this story's first live reading at `:382`, `recompose_preflight_min_free_ram_gb:391` unchanged at 12.0.
- `_bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py` -- the harness. `cmd_screen:96`, `cmd_manifest:168`, `cmd_render_off:328`, `cmd_render_on:379`, `cmd_publish_on:479` (recovers frames a killed `render-on` strands), `cmd_score:539`, `cmd_report:657`, `cmd_grid:875` (falls back to a partial sheet when `verdict.json` is absent).
- `data/comfyui/README.md` -- "How ComfyUI must be started"; the launcher is `~/workspaces/ComfyUI/run.sh` (venv + `HSA_OVERRIDE_GFX_VERSION` + `PYTORCH_HIP_ALLOC_CONF`), currently `main.py --preview-method auto --cache-lru 10`.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py` -- ONE harness with subcommands `screen | manifest | render-off | render-on | score | report`, each writing its own JSON so a stage can be re-run without redoing the one before it -- five separate scripts would duplicate the manifest schema five times, and every stage boundary here is a place the run can legitimately stop (GPU busy, key missing).
- [x] `.../10-1e-live-validation/screening.json` + `PREREGISTRATION.md` -- run `screen` first (free, no GPU, no network) and record the collinearity table; then write the decision rule VERBATIM as below and **`git commit` both before running `score`** -- pre-registration that is not timestamped by something outside the author's control is not pre-registration.
- [x] `.../10-1e-live-validation/pairs.json` -- `manifest`: read the `e5ed4b3a` checkpoint read-only, keep the 33 eligible shots, resolve cast cards **once** through the production resolver, freeze `{shot_id, scene_num, plate, sentences, cast:[{card_key,path,position,depth,pose,ground_y,occlusion_mask}]}` -- both arms must consume the identical card set or the treatment is confounded with angle selection.
- [x] ComfyUI restart -- confirm `/queue` running+pending is 0 (check `class_type`s to be sure nothing belongs to another session), then restart via `setsid` from `~/workspaces/ComfyUI` with `--lowvram --disable-smart-memory` appended to the existing launcher line, verify with `/system_stats` that `argv` and `ram_free` now satisfy `REQUIRED_FLAGS`, and **restore the original argv after `render-on` finishes** -- `pkill -f` matches the caller's own shell; a background task dies with its parent, so `setsid` is mandatory.
- [x] `render-off` -- `render_composite_still` per shot into `off/<shot_id>.png`, with `ground_y`/`occlusion_mask` from the injected ground resolver and `mood`/`composite_harmonization_tier` read from `Settings()`.
- [x] `render-on` -- call `recompose_run_shots(scenes, cast_cards)` on the manifest-derived scenes; record per-pass wall-clock and the returned `stats`; copy each `recomposed/*.png` to `on/<shot_id>.png` scaled to 1920×1080 -- going through the service (not `recompose_shot`) is what exercises the 10.1d preflight live, which has never run against a real server.
- [x] `score` -- build `blind/<opaque-id>.png` (`sha256(shot_id|arm|salt)[:12]`) with the mapping written to `pairs_key.json` in the parent directory, score every frame with `BLIND_PROMPT` via `ask()`, then DSG via `_score_dsg` using the manifest sentences; emit `results.json` with per-frame rows and both arms' summaries -- the VLM sees bytes only, so it is blind by construction; the opaque ids exist so the human reading the grids cannot see the arm either.
- [x] `report` -- apply the committed rule mechanically, emit `README.md` with: the screening table, n and per-arm counts and every axis's coordinates, the `b`/`c` discordant table with the per-shot list, secondary axes **in both directions**, the measured cost, and the verdict -- a measurement without its sample band is unreproducible.
- [x] `.../10-1e-live-validation/pairs_grid.jpg` (+ per-shot pair sheets for every discordant shot) -- downscale to ~512 px long edge; these are the adjudication images the verdict cites.
- [x] `.../10-1e-live-validation/.gitignore` -- ignore `off/`, `on/`, `blind/` raw PNGs with a header naming what regenerates them (`run_pairs.py render-off|render-on` against run `e5ed4b3a` + `pairs.json`) and warning that `workspace/e5ed4b3a-.../recomposed/` is the only copy of the ON arm's source renders.
- [x] `src/yt_flow/config.py` -- rewrite verdict item (a) with the outcome, the date, n, and the measured numbers; state plainly whether (a) is closed PASS or closed FAIL, and that the incumbent 20%/13%/57%/27% figures are withdrawn as arm-confounded-with-cast-presence. If the default flips, the flip is a separate line in the same commit with AC7's answer beside it; if it does not, record what failed.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- one entry answering AC7 explicitly: the overlay-only machinery retirement is a follow-up story, not this commit, with the reason and the list of what would be deleted.

**Acceptance Criteria:**
- Given the committed `baseline_v2.json`, when `screen` runs, then it reports 51 recomposed rows / 15 plate rows / 0 shot overlap and the identical unreadable and corridor counts under both the arm split and the cast-presence split — the collinearity is shown, not asserted.
- Given `PREREGISTRATION.md`, when `git log` is read, then its commit precedes the commit that first adds `results.json`.
- Given the ON arm rendered, when `pairs.json` and `results.json` are compared, then every scored `on/` frame has an `off/` frame for the same `shot_id` and vice versa, and the frames counted per arm are equal.
- Given a failing preflight during `render-on`, when the harness stops, then no frame was rendered, the ComfyUI message is reproduced verbatim in the run output, and the original launcher argv is still restored.
- Given `results.json`, when the pre-registered rule is applied by hand, then it yields the same verdict the report prints.
- Given the repository after this story, when `config.py:314-337` is read, then item (a) names this story's measurement and date, no threshold in `PREREGISTRATION.md` differs from the one applied, and `shot_recompose_enabled`'s value matches the verdict.
- Given the full suite, when `uv run pytest -q -p no:cacheprovider --ignore=e2e` runs, then no test that passed at `ac6434d` now fails (`tests/test_render_pose_guides.py::…[humanoid_lying_supine]` is a known pre-existing failure from `d39037f`).

## Spec Change Log

_No bad_spec loopback occurred. The 2026-08-17 review produced 0 intent_gap and 0 bad_spec._

## Review Triage Log

### 2026-08-17 — Review pass

Both reviewers ran in parallel with no prior context (Blind Hunter + Edge Case Hunter). Every
high-severity claim was verified against a primary source before patching — `run.sh`,
`video.py`'s tier gates, `ImageChops.difference` on the frames themselves, `pairs.json.dropped`,
and `comfyui_render_on.log`. Two findings were about the implementer's own factual errors and
both were confirmed.

- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 7, medium 9, low 5)
- defer: 3: (high 0, medium 3, low 0)
- reject: 6: (high 0, medium 2, low 4)
- addressed_findings:
  - `[high]` `[patch]` **The shipped default was inert on the machine it shipped from.**
    `~/workspaces/ComfyUI/run.sh` passes `main.py --preview-method auto --cache-lru 10` — no
    `--lowvram`. The resolver is injected unconditionally, so every run would reach the
    preflight, bail `missing_flags`, and render the overlay while `config.py` said recompose
    was on: `gotcha_a-decision-that-only-reaches-env-never-ships`, one story after the same
    lesson. `run.sh` updated (backup `run.sh.bak-pre-10-1e`), `data/comfyui/README.md`
    rewritten from "what run.sh is still missing" to REQUIRED, and `api/main.py`'s comment —
    which said "Gated off by default" — corrected.
  - `[high]` `[patch]` **The clips Jay judged handicapped the incumbent on exactly the two
    features the verdict cites.** `cmd_viewing` hardcoded `composite_harmonization_tier=0`,
    and `video.py:1577`/`:1650` gate `build_sprite_tint` AND `build_contact_shadow` on
    `tier >= 1`; the *scored* OFF arm used production tier 1. Now reads
    `Settings().composite_harmonization_tier`; clips re-rendered at tier 1. Recorded in
    `VERDICT_OVERRIDE.md` with an explicit note that the verdict was formed on the tier-0
    build and re-watching is the cheap confirmation.
  - `[high]` `[patch]` **"Frames are not bit-reproducible" was false, and it was the
    implementer's own claim.** The md5s differ only in the PNG `tEXt` chunk. On pixels,
    `ImageChops.difference(...).getbbox()` is `None` for all 8 re-rendered pairs. Recompose
    is deterministic at `seed=0` across the flag change, which also makes the 358 s
    S00101/S00102 re-render a no-op. Residual risk 2 rewritten as WITHDRAWN.
  - `[high]` `[patch]` **The veto input carried the identical cache-blindness that had
    already faked the cost figure**, and `PREREGISTRATION.md` applies the veto FIRST.
    `passes_failed = attempted − published` reads 0 on any warm-cache re-run, so the
    `>=5 failed => STAY OFF` gate could never fire. Documented at the computation site.
  - `[high]` `[patch]` **The cost fallback silently opened the gate it was written to
    guard.** `per_pass = … if npass else (seconds_per_pass_mean or 0)`, and the corrected
    `render-on` writes `None` on an all-cache-hit run, so `None or 0` -> 0.0 h -> FLIP.
    `report` now refuses and exits 2 rather than defaulting.
  - `[high]` `[patch]` **The AC7 retirement premise was backwards.** It argued the overlay
    stays live because 10 of 43 shots are ineligible; all 10 are ineligible for an EMPTY
    CAST (`pairs.json.dropped` 10/10) and `_build_card_chain` is only entered for a non-empty
    card list, so under the flip **0 of 43 shots exercise card compositing**. Corrected in
    `config.py` and `deferred-work.md`: retirement is more owed, not less.
  - `[high]` `[patch]` **Partial recompose degradation was unreportable in production.** With
    the flag now True, "preflight passed then some shots fell back" is a live state, and the
    only recompose row that existed was the all-or-nothing preflight bail. Added
    `recompose_shots_degraded` (both `state.py` and `warnings.py`, or the import guard
    fails), filed for `failed`/`skipped` counts and for `resolver_not_injected` — the latter
    covering every entry point that is not the API lifespan.
  - `[medium]` `[patch]` `FORBIDDEN_FLAGS` added and checked first: removing
    `--disable-smart-memory` from REQUIRED_FLAGS left a launcher that still passes it sailing
    into the measured-fatal config, whose only symptom is slowness.
  - `[medium]` `[patch]` The removed flag was still mandated in five places outside `src/`
    (10.1d's verification `rg` only covered `src/`): `epics.md` x3, the workflow JSON's node
    title, this directory's own `.gitignore`, and `render_on_blocked.json:to_resume[1]`,
    which instructed the next operator to recreate the fatal config.
  - `[medium]` `[patch]` The flag's headline before/after is **confounded** — four SDXL
    prompts from a concurrent session ran between pass 1 and passes 2-3
    (`Requested to load SDXL`, not the "Inspyrenet Rembg progress lines"
    `render_on_blocked.json` claimed). Caveat added at all three claim sites; the
    unconfounded datum is the 40-pass run without the flag.
  - `[medium]` `[patch]` `report` regenerated a README and `verdict.json` that both said
    `shot_recompose_enabled = False`, contradicting the shipped code with no record of the
    override. `verdict.json` now emits `shot_recompose_enabled_per_rule` plus
    `human_override`, and `report` appends `VERDICT_OVERRIDE.md` — recorded alongside, never
    folded into, what the rule alone concluded.
  - `[medium]` `[patch]` `p = 1.00` and the CI `[-7.2, +13.3]` were asserted in prose and
    derivable from nothing, against a promise that every number re-derives with `report`.
    Now computed there (`exact_mcnemar_p_two_sided`, `unreadable_difference_ci95_pp`) with a
    `power_note` stating that the CI contains the incumbent's own 7 pp claim.
  - `[medium]` `[patch]` "All three discordant shots name the `place` correctly in both arms"
    is contradicted by `results.json` — S00501 is OFF "a sterile laboratory" vs ON "a tiled
    examination room", and no artifact holds a ground truth. Reworded to what the rows show:
    all three split on `event: unclear`.
  - `[medium]` `[patch]` The `107.9 s/pass` mtime estimator included two cross-invocation
    deltas (S00101/S00102, re-rendered ~4 min after the sweep). Quantified rather than
    hand-waved: 107.9 vs 106.9 s/pass, 1.199 h vs 1.188 h, both over the line. A 3x-median
    guard added for the case it was written for (a run resumed the next day), with a comment
    stating it drops nothing on this run.
  - `[medium]` `[patch]` `cmd_viewing`'s `_write` clobbered the hand-added
    `read_once_observations` that `config.py` cites, so the documented regeneration deleted
    the section the flip rationale points at. Now preserved across re-renders.
  - `[medium]` `[patch]` `report` would happily read a preflight-bail `on.json` — zero
    frames, no cost data — and print FLIP for a run that rendered nothing. Guarded.
  - `[medium]` `[patch]` `publish-on` does not refresh `on.json`, so a recovered partial arm
    was invisible to cost, veto and pass accounting. Deliberately still does not overwrite
    it (a partial recovery is not a measured sweep) but now says so, in the file and on
    stdout.
  - `[medium]` `[patch]` Nothing pinned the new default in either direction — a stale `.env`
    pin or a silent revert would be invisible (`gotcha_env-file-beats-code-default`).
    `tests/test_config.py::test_recompose_defaults` added.
  - `[low]` `[patch]` 11.5 parallax silently degrades to `NO_DEPTH` for all 33 recomposed
    shots (recompose pops `depth_map_path`) while `parallax_25d_enabled` stays True; stated
    in `config.py` as shipped behaviour rather than left as retirement bookkeeping.
  - `[low]` `[patch]` Three different pass counts for one claim ("4 passes", "37 passes",
    40 published). Normalised to the 40 of the 2026-08-17 sweep.
  - `[low]` `[patch]` Two spec statements and two `deferred-work.md` entries still asserted
    the flip had not happened.
  - `[low]` `[patch]` `viewing/*.mp4` gitignored with a regeneration note that pointed at
    `off/`+`on/`, themselves ignored and GPU-dependent; header corrected, and the identity
    sheets (the committed adjudication images) called out as what survives.
  - `[medium]` `[defer]` `S00405` — the only `c` shot in the viewing package — has no shipped
    clip and plays at the 4.0 s fallback, i.e. non-production zoom velocity, which is what a
    floating judgement reads. Also `duration_source` is computed as `dur != VIEW_FALLBACK_SEC`,
    so a genuine 4.00 s clip would be mislabelled.
  - `[medium]` `[defer]` `score`'s resume key is the `blind_id` alone, so frames re-rendered
    after a scoring run inherit the previous run's `readable` and DSG values. Needs a pixel
    digest in the row.
  - `[medium]` `[defer]` The preflight remains a one-shot entry check on a quantity a
    co-tenant can consume mid-run; with the flag gone the mechanism is no longer reachable
    by a shipped configuration, but nothing detects it.
  - `[medium]` `[reject]` "The pre-registered cost formula was replaced after it was seen to
    produce FLIP." The substitution corrects a measurement error (a denominator counting
    skipped work), not a threshold, and the pre-registered thresholds are untouched. Recorded
    at the computation site and in `deferred-work.md` rather than hidden — but calling it a
    rule change misstates what changed.
  - `[medium]` `[reject]` "`PREREGISTRATION.md` falsifier 2 (blind-package leak check) has no
    recorded result." It does, in the spec's manual checks, and the reviewer independently
    confirmed the resolution half is neutral (both arms derive from 1344x768).
  - `[low]` `[reject]` Four speculative harness edges on inputs no committed artifact can
    produce (vacuous collinearity from a `baseline_v2.json` missing its own keys; absolute
    `YTFLOW_WORKSPACE_PATH` outside ROOT; `ffprobe` returning NaN; `CARD_LOOKS` edited
    between `manifest` and `report`).

## Design Notes

**The pre-registered rule** (copy verbatim into `PREREGISTRATION.md` before scoring):

> Deciding axis: blind `readable` (13-2's `BLIND_PROMPT`, frame bytes only), over the paired shots.
> Let **b** = shots readable OFF and unreadable ON; **c** = unreadable OFF and readable ON.
> **FLIP** the default iff `b − c ≤ 1`. **STAY OFF** iff `b − c ≥ 2`.
> Veto, applied first: if ≥5 of the 40 recompose passes fail, STAY OFF regardless of scores.
> Cost does not enter this decision — it is 10.1c's item (c). If (a) passes but the measured
> added time exceeds 1.0 h on a 43-shot run, the verdict is "(a) closed PASS, (c) still blocks"
> and the flag stays `False` with that stated.
> Secondary axes (mean DSG, corridor-misread rate, `place`/`event` unclear split) are
> record-only and never override the deciding axis, in either direction.
> Retirement (AC7): a follow-up story, never this commit.

`b − c ≤ 1` is "neutral-or-better with one shot of slack" — 10.1c's UNBLOCK wording. Exact McNemar on n=33 has no power for small effects, so a p-value would be theatre; the slack is stated instead of hidden.

**Why the OFF arm is a composited still and not a bare plate, and not a clip frame.** The bare plate is the confound this story exists to remove. A frame extracted from `shots/*.mp4` carries the zoompan start-zoom, the t=0 shake term and a yuv420p round-trip. `render_composite_still` is the shipped tool built for exactly this comparison and is motionless by construction.

## Verification

**Commands:**
- `uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py screen` -- expected: 51/15/0-overlap, both splits identical
- `curl -s http://127.0.0.1:8188/system_stats` -- expected before `render-on`: `argv` contains `--lowvram --disable-smart-memory --cache-lru 10`, `ram_free` ≥ 12 GiB; expected after the run: back to `main.py --preview-method auto --cache-lru 10`
- `uv run pytest -q -p no:cacheprovider --ignore=e2e` -- expected: only the known `humanoid_lying_supine` failure
- `rg -n 'shot_recompose_enabled' src/` -- expected: the `config.py` definition and the `video.py:2558` gate, and its value matches the verdict
- `git log --oneline -- .../10-1e-live-validation/PREREGISTRATION.md .../results.json` -- expected: the pre-registration commit is older

**Manual checks (if no CLI):**
- `pairs_grid.jpg` read once with the key hidden: is the arm guessable from framing, resolution or border artifacts alone? If yes, the blind package leaks and the scores are suspect.
- The rewritten `config.py` item (a) read cold: does it state the outcome, n, the date, and that the old 20%/13% figures are withdrawn and why?
</content>
</invoke>

## Auto Run Result

Status: done

**FINAL VERDICT: FLIPPED — `shot_recompose_enabled = True`, on Jay's viewing verdict.**

The pre-registered rule resolved to *"(a) closed PASS, (c) still blocks"* and would have kept
the default `False`:

| gate | reading | outcome |
|---|---|---|
| veto, ≥5 of 40 passes fail | 0 failed | not triggered |
| deciding axis — blind `readable`, paired, n=33 | b=2, c=1, **b−c=1** ≤ slack 1 | FLIP |
| cost line, >1.0 h added to a 43-shot run | 107.9 s/pass × 40 = **1.2 h** | BLOCKS |

Jay then watched the paired motion clips (`viewing/all_pairs.mp4`, built for the axis the
score never read) and ruled: *"recompose 무조건 해야하고"* — recompose is a must. That is a
**human override of the cost line**, authorised by this epic's own closure standard ("a
viewing verdict overrides a favorable measurement", and symmetrically an unfavorable one),
and the 1.2 h is now a price paid on every run. It is recorded as an override in
`config.py`, not as the numbers having said yes.

`OFF` unreadable 3/33 (9.1%), corridor 27.3%, mean DSG 0.4443. `ON` unreadable 4/33
(12.1%), corridor 30.3%, mean DSG 0.4615. 28 shots readable in both arms, 2 in neither,
3 discordant — all three name `place` correctly in both arms and split only on `event`.

**One defect ships with the flip**, raised by Jay on the same viewing: `depth: "near"`
figures are drawn oversized for the room. `_DEPTH_PHRASE["near"]` asks for "in the
foreground close to camera, **his whole body from head to feet visible in frame**" — two
clauses that cannot both hold for a 1.9 m figure in a 1344×768 frame, so the model inflates
the figure against the room's scale cues instead of moving the camera. Not fixed here: the
current phrasing is what the 43-plate sweep was verified on, and this module has already
been burned once by adding a framing clause (it made pass 1 draw the character twice).
Recorded in `deferred-work.md` with candidate rewordings and the screening order.

**Retirement is now owed, and it is NOT this commit** (AC7). The overlay stack stays live
production code: `recompose_service` skips any shot with an empty cast or a `card_key`
outside `CARD_LOOKS` — 10 of 43 on run `e5ed4b3a` — and those still render through
`_build_card_chain` with ground placement, occlusion, contact shadow, parallax and idle
motion intact. This is a deliberate two-path system until that story lands.

**Item (a) is closed by measurement, and its incumbent numbers are withdrawn.** The
figures that kept the default off — unreadable 20% vs 13%, corridor 57% vs 27% — were
never a treatment measurement: in the same committed `baseline_v2.json` the 51
`recomposed/` rows and 15 `images/` rows are disjoint shot sets (0 overlap), and splitting
those 66 rows by *cast presence* selects byte-identical sets and reproduces every count.
Arm and cast-presence are 100% collinear there. Established for free, from data already in
the repo, before any GPU was spent.

**How thin the FLIP half is, stated because the rule was fixed in advance.** b−c=1 is the
rule's exact boundary; one shot the other way reads STAY OFF. Three discordant pairs carry
no statistical power. The honest claim is "no evidence recompose is worse on legibility",
not "recompose is better".

**Three things the investigation answered differently from the story's premise**

1. **The incumbent number was not a comparison at all** — see above. The story assumed (a)
   was a measurement to redo more carefully.
2. **`--disable-smart-memory` was the cost problem, not a prerequisite.** It sat in
   `REQUIRED_FLAGS` on 10.1c's older-ComfyUI report that "the Qwen graph swap-deadlocks
   without it". On 0.12.3 the deadlock does not reproduce (37 passes, 0 hangs), and the
   flag was actively fatal here: the graph's weights total 22.6 GB (12.6 unet + 8.95 fp8
   encoder + 0.81 LoRA + 0.24 VAE) against 16 GB VRAM, so `--lowvram` streams them from
   system RAM and that flag then unloaded them after every prompt. Same box, same shots —
   **with**: 385.66 → 677 → 609 s/pass, `ram_free` 19.35 → 5.46 GiB, swap 8185/8191 MiB,
   halted. **Without**: 107.9 s/pass, RAM flat ~17 GiB, 40/40 passes, 0 failures. The
   preflight was refusing the only configuration that works. Removed, with the measurement
   in the table; `--lowvram` and `--cache-lru > 0` stay.
3. **10.1d's recorded residual risk was inverted.** It expected a false-bail rate from the
   12 GiB floor being too high. Measured: zero false bails, and the real gap is that the
   floor is a one-shot *entry* check on a value a run can destroy — which is what the
   removed flag did.

**Review pass (2026-08-17).** Both reviewers in parallel: **21 patched (7 high, 9 medium,
5 low), 3 deferred (medium), 6 rejected.** `followup_review_recommended: true` — the pass
changed shipped behaviour (a new `run_warning` code, a `FORBIDDEN_FLAGS` gate, the machine's
launcher) and corrected two of the implementer's own factual claims, which is more than a
few localized fixes. The two sharpest findings:

1. **The default shipped inert.** `run.sh` had no `--lowvram`, so every run would have
   bailed the preflight and rendered the overlay while `config.py` said recompose was on —
   `gotcha_a-decision-that-only-reaches-env-never-ships`, one story after that lesson was
   recorded.
2. **The clips Jay judged handicapped the incumbent** on two of the three things the flip
   rationale cites (`composite_harmonization_tier=0` switches off sprite tint *and* contact
   shadow), while the scored OFF arm used production tier 1.

**Verification after the review patches.** `uv run pytest -q -p no:cacheprovider
--ignore=e2e` → **1 failed, 3153 passed, 1 skipped** (6:40); the failure is the pre-existing
`humanoid_lying_supine` pinned raster hash from `d39037f`. `uv run ruff check src/ tests/
run_pairs.py` clean. `Settings().shot_recompose_enabled is True`, now pinned by
`tests/test_config.py::test_recompose_defaults`.

**Files changed**
- `src/yt_flow/services/recompose_service.py` — `--disable-smart-memory` removed from
  `REQUIRED_FLAGS` with the measured before/after in the declaration
- `src/yt_flow/config.py` — items (a) and (c) rewritten with the measurement, the
  withdrawal, the thinness caveat, the one number that must not be cited
  (`seconds_per_pass_mean`), the override record, and AC7's answer; the 10.1d RAM-floor
  comment gains the first healthy-run readings. `shot_recompose_enabled` **flipped to
  `True`**
- `data/comfyui/README.md` — flag table corrected; the removed flag kept struck-through
  with its measurement so the claim is not re-derived from scratch later
- `tests/services/test_recompose_service.py`, `tests/stubs/fakes.py` — flag matrix and
  offline stub argv follow `REQUIRED_FLAGS`
- `_bmad-output/implementation-artifacts/10-1e-live-validation/` — `run_pairs.py`
  (+`publish-on`, cache-immune cost, partial-grid fallback, `_rel`), `PREREGISTRATION.md`,
  `screening.json`, `pairs.json`, `off.json`, `on.json`, `results.json`, `verdict.json`,
  `pairs_key.json`, `render_on_blocked.json`, `comfyui_render_on.log`, `README.md`,
  `.gitignore`, `pairs_grid.jpg`, `pair_sheets/` (3 discordant shots)
- `_bmad-output/implementation-artifacts/deferred-work.md` — four entries: AC7's answer,
  the preflight entry-check gap, the remaining budget call, and the cache-inflated
  throughput mean

**Two harness defects found by their own consequences, both fixed**
- `cmd_render_on`'s publish step crashed on `Path.relative_to(ROOT)` for paths that are
  already repo-relative (cwd is ROOT) — *after* all 33 renders were paid for. Now one
  `_rel` helper, used by both publish paths.
- `seconds_per_pass_mean = total / passes_published` reported **7.8 s/pass** for a re-run
  that rendered 3 of 40 (the rest content-addressed cache hits), and `report` cited it: the
  cost line read 0.09 h, passed, and printed **FLIP → `shot_recompose_enabled = True`**.
  The honest 107.9 s/pass comes from the recomposed files' own mtimes, which a cache hit
  leaves untouched. `report` now takes the cost from `per_shot_from_mtime` and records
  `seconds_per_pass_source` in `verdict.json`; `render-on` emits `null` rather than a
  fabricated mean when it rendered nothing.

**Residual risks**
1. **The FLIP half rests on 3 discordant pairs, and reading them weakens b further.**
   Repeating the scoring pass would not add power; more shots would. Nothing here licenses
   "recompose is better" — but nothing licenses reading b=2 as composition damage either.
   On `pair_sheets/S00501_b_*.jpg` the OFF arm has the figure standing **on top of a lab
   bench** beside a glowing sheet, which the blind judge read as an event ("a glowing
   substance is present on the table"); the ON arm puts the same figure on the floor,
   correctly grounded, and scored `event: unclear`. All three discordant shots name `place`
   correctly in both arms and split only on `event`, so what the axis is separating here is
   partly "is something happening" rather than "is the frame legible" — 10.4b's
   `visible_event` cluster, arriving inside the deciding axis.
2. ~~**Frames are not bit-reproducible.**~~ **WITHDRAWN — the opposite is true.** The
   original claim came from comparing md5 sums, which differ only in the PNG `tEXt`
   metadata chunk. Compared on pixels (`ImageChops.difference(...).getbbox()`), all 8
   re-rendered frames are **identical**: 4 probe-vs-sweep pairs and both
   `pre_flagfix/` pairs. Recompose output is deterministic at `seed=0` on this hardware,
   across the `--disable-smart-memory` change, which also means the 358 s re-render of
   S00101/S00102 was a no-op. Originals preserved at
   `workspace/e5ed4b3a-.../recomposed/pre_flagfix/` regardless.
3. **1.2 h is measured on a shared box and is now being paid on every run.** A desktop
   session held ~6.6 GB throughout; an exclusive box would be faster. Nobody has measured
   that, and the flip means the E2E budget absorbs the unmeasured version.
4. **The removed flag's original deadlock is unfalsified in general** — only on 0.12.3, on
   this graph, over 37 passes. If it returns it belongs back in `REQUIRED_FLAGS` *with the
   version it was seen on*.
5. `workspace/e5ed4b3a-.../recomposed/` (including `pre_flagfix/`) holds the only copies of
   the ON arm's source renders; `on/` is re-framed derivatives and is gitignored. Do not
   `git clean` or blanket-delete either path.

6. **The viewing package understates the incumbent.** `viewing/` excludes 11.5 depth
   parallax (it needs the injected 2.5D renderer; without it both arms fall back to legacy
   Ken Burns), and parallax is an OFF-arm-only motion layer. Jay's verdict was formed on
   clips where the overlay arm was missing one of its motion layers. Stated in
   `viewing.json`, not hidden.

**Note for whoever runs the next live gate:** `pgrep -f 'run_pairs.py score'` matches the
watching shell's own command line, and reported "score running" for five minutes while the
process had never started. Count real processes instead: `ps -eo args | grep -c '[r]un_pairs.py score'`.
