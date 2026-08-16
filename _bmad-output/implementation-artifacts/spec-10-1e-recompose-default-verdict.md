---
title: 'Story 10.1e — Recompose on/off paired scoring and default verdict (10.1c unblock condition (a))'
type: 'feature'
created: '2026-08-16'
status: 'in-progress'
review_loop_iteration: 0
baseline_revision: 'ac6434d'
followup_review_recommended: false
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
- `src/yt_flow/config.py:314-337` -- the 10.1c verdict comment (item (a) at :319-322, the UNBLOCK sentence at :331-333, the retirement sentence at :334-336) and `shot_recompose_enabled:337`.
- `data/comfyui/README.md` -- "How ComfyUI must be started"; the launcher is `~/workspaces/ComfyUI/run.sh` (venv + `HSA_OVERRIDE_GFX_VERSION` + `PYTORCH_HIP_ALLOC_CONF`), currently `main.py --preview-method auto --cache-lru 10`.

## Tasks & Acceptance

**Execution:**
- [ ] `_bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py` -- ONE harness with subcommands `screen | manifest | render-off | render-on | score | report`, each writing its own JSON so a stage can be re-run without redoing the one before it -- five separate scripts would duplicate the manifest schema five times, and every stage boundary here is a place the run can legitimately stop (GPU busy, key missing).
- [ ] `.../10-1e-live-validation/screening.json` + `PREREGISTRATION.md` -- run `screen` first (free, no GPU, no network) and record the collinearity table; then write the decision rule VERBATIM as below and **`git commit` both before running `score`** -- pre-registration that is not timestamped by something outside the author's control is not pre-registration.
- [ ] `.../10-1e-live-validation/pairs.json` -- `manifest`: read the `e5ed4b3a` checkpoint read-only, keep the 33 eligible shots, resolve cast cards **once** through the production resolver, freeze `{shot_id, scene_num, plate, sentences, cast:[{card_key,path,position,depth,pose,ground_y,occlusion_mask}]}` -- both arms must consume the identical card set or the treatment is confounded with angle selection.
- [ ] ComfyUI restart -- confirm `/queue` running+pending is 0 (check `class_type`s to be sure nothing belongs to another session), then restart via `setsid` from `~/workspaces/ComfyUI` with `--lowvram --disable-smart-memory` appended to the existing launcher line, verify with `/system_stats` that `argv` and `ram_free` now satisfy `REQUIRED_FLAGS`, and **restore the original argv after `render-on` finishes** -- `pkill -f` matches the caller's own shell; a background task dies with its parent, so `setsid` is mandatory.
- [ ] `render-off` -- `render_composite_still` per shot into `off/<shot_id>.png`, with `ground_y`/`occlusion_mask` from the injected ground resolver and `mood`/`composite_harmonization_tier` read from `Settings()`.
- [ ] `render-on` -- call `recompose_run_shots(scenes, cast_cards)` on the manifest-derived scenes; record per-pass wall-clock and the returned `stats`; copy each `recomposed/*.png` to `on/<shot_id>.png` scaled to 1920×1080 -- going through the service (not `recompose_shot`) is what exercises the 10.1d preflight live, which has never run against a real server.
- [ ] `score` -- build `blind/<opaque-id>.png` (`sha256(shot_id|arm|salt)[:12]`) with the mapping written to `pairs_key.json` in the parent directory, score every frame with `BLIND_PROMPT` via `ask()`, then DSG via `_score_dsg` using the manifest sentences; emit `results.json` with per-frame rows and both arms' summaries -- the VLM sees bytes only, so it is blind by construction; the opaque ids exist so the human reading the grids cannot see the arm either.
- [ ] `report` -- apply the committed rule mechanically, emit `README.md` with: the screening table, n and per-arm counts and every axis's coordinates, the `b`/`c` discordant table with the per-shot list, secondary axes **in both directions**, the measured cost, and the verdict -- a measurement without its sample band is unreproducible.
- [ ] `.../10-1e-live-validation/pairs_grid.jpg` (+ per-shot pair sheets for every discordant shot) -- downscale to ~512 px long edge; these are the adjudication images the verdict cites.
- [ ] `.../10-1e-live-validation/.gitignore` -- ignore `off/`, `on/`, `blind/` raw PNGs with a header naming what regenerates them (`run_pairs.py render-off|render-on` against run `e5ed4b3a` + `pairs.json`) and warning that `workspace/e5ed4b3a-.../recomposed/` is the only copy of the ON arm's source renders.
- [ ] `src/yt_flow/config.py` -- rewrite verdict item (a) with the outcome, the date, n, and the measured numbers; state plainly whether (a) is closed PASS or closed FAIL, and that the incumbent 20%/13%/57%/27% figures are withdrawn as arm-confounded-with-cast-presence. If the default flips, the flip is a separate line in the same commit with AC7's answer beside it; if it does not, record what failed.
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- one entry answering AC7 explicitly: the overlay-only machinery retirement is a follow-up story, not this commit, with the reason and the list of what would be deleted.

**Acceptance Criteria:**
- Given the committed `baseline_v2.json`, when `screen` runs, then it reports 51 recomposed rows / 15 plate rows / 0 shot overlap and the identical unreadable and corridor counts under both the arm split and the cast-presence split — the collinearity is shown, not asserted.
- Given `PREREGISTRATION.md`, when `git log` is read, then its commit precedes the commit that first adds `results.json`.
- Given the ON arm rendered, when `pairs.json` and `results.json` are compared, then every scored `on/` frame has an `off/` frame for the same `shot_id` and vice versa, and the frames counted per arm are equal.
- Given a failing preflight during `render-on`, when the harness stops, then no frame was rendered, the ComfyUI message is reproduced verbatim in the run output, and the original launcher argv is still restored.
- Given `results.json`, when the pre-registered rule is applied by hand, then it yields the same verdict the report prints.
- Given the repository after this story, when `config.py:314-337` is read, then item (a) names this story's measurement and date, no threshold in `PREREGISTRATION.md` differs from the one applied, and `shot_recompose_enabled`'s value matches the verdict.
- Given the full suite, when `uv run pytest -q -p no:cacheprovider --ignore=e2e` runs, then no test that passed at `ac6434d` now fails (`tests/test_render_pose_guides.py::…[humanoid_lying_supine]` is a known pre-existing failure from `d39037f`).

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
