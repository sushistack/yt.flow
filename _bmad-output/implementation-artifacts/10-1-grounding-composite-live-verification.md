---
baseline_commit: ab0b7568
epic: 10
story: 1
story_key: 10-1-grounding-composite-live-verification
findings: [3, 11]
---

# Story 10.1: Grounding & Compositing Live Verification — Are the Cards Attached to the Plate? (findings 3·11)

Status: review

<!-- Epic 10 gives scope prose, not a formal user story or numbered BDD ACs. The Story and ACs below are derived implementation contracts grounded in the epic entry, Jay's 2026-08-08 custom instructions, the 8.16/11.5/8.7 code as it exists at `ab0b7568`, and live inspection of the running services and of run `8a9a288b`. -->

> **THIS STORY IS NOT A CODING STORY.** The body of the work is *rendering paired frames and adjudicating them*. Code changes begin ONLY IF the paired comparison shows "features enabled and the cards still look pasted on" — and then only on the specific broken link the frames identify. **A dev session that opens an editor before it has an off/on frame pair on disk is going the wrong way.**

## Story

As Jay,
I want the same SCP-049 shots re-rendered with depth-aware ground placement (8.16) and 2.5D parallax (11.5) actually **on**, placed side by side against the frames I watched with them **off**,
so that findings 3 ("characters look torn out and pasted onto the background") and 11 ("characters float") are settled with evidence instead of guesswork — either the features fix them, or the frames name which link in the grounding chain is broken.

## Context: why this story exists

Jay watched run `8a9a288b-800f-4c73-88a2-25ae6b5a4d7d` (SCP-049, 3:06) on 2026-08-08 and raised 16 defects. Findings 3 and 11 are the ones 8.16 and 11.5 were built to remove.

**That run was rendered with the features off.** Verified live, not assumed — the running API unit's `ExecStart` literally carries `YTFLOW_DEPTH_PLACEMENT_ENABLED=false` (commit `19c4cf1`, which gated depth injection to stop a per-shot reload stall). `src/yt_flow/api/main.py:70` and `:106` gate **both** the depth resolver *and* the 8.16 ground resolver on that one flag; and with no `depth_map_path` on any shot, `parallax_service.render_motion_clip` takes its `NO_DEPTH` rung (`parallax_service.py:571-572`) so 11.5 was muted too.

So findings 3/11 are **not** evidence that the features are ineffective. They establish only that the video was rendered without them. This story draws that distinction first, and only then — if warranted — opens real scope.

This is also Epic 10's ground truth exercise: the epic exists because the previous session closed Epic 8 stories while the watched video stayed the same and nobody could prove afterwards what had any effect.

## Acceptance Criteria

### AC1 — Off-state evidence is preserved BEFORE anything re-renders

**Given** run `8a9a288b`'s `shots/*.mp4`, `seg_*.mp4` and `video.mp4` are the only surviving record of the features-off render,
**when** any re-render of that run is initiated,
**then** the off-state frames and clips for every shot chosen for adjudication are already copied into `_bmad-output/implementation-artifacts/10-1-live-validation/off/`,
**and** `workspace/8a9a288b-.../video.mp4` is backed up outside the run directory,
**and** this happens before the first re-render call is made.

> **This is destructive-by-default.** `video.py:1885` unlinks *every* `shots/scene_NNN_*.mp4` before re-rendering a scene, and the segment/final concat overwrite in place. A re-render with no prior copy destroys the off-state permanently and makes this story unclosable.

### AC2 — A controlled off/on pair from the SAME shots (primary evidence)

**Given** the grounding question is "do these cards sit on this plate", which is only answerable when the plate and the card are held constant,
**when** the on-state is produced,
**then** it is produced by re-running **only the `video` stage** of run `8a9a288b` with `depth_placement_enabled=true` — same 66 plates, same cards, same script, same shot ids,
**and** at least **6 shot pairs** are captured, spanning all three card depth bands (`far` / `mid` / `near`) and at least two `position` values,
**and** each pair is one PNG frame extracted at the same timestamp from the same `shots/scene_NNN_SNNNNN.mp4` off and on,
**and** each pair is also written as one side-by-side composite image for adjudication.

*Why this and not a fresh run:* the shot seed is `_shot_seed(run_id, scene_num, shot_id)` (`image.py:131`, run_id in the hash) and the scenario is regenerated per run — **a new run on SCP-049 produces different backgrounds, different shot lists and different narration.** Those frames cannot be paired with `8a9a288b`'s. A new run answers "does the finished video look better", not "did grounding attach the card".

*Why this is legal right now, verified live:* run `8a9a288b` is `status=complete` (in `_MUTABLE_STATES`) with `gate_states.video=approved` (in `_RETRYABLE`), so `POST /runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/stages/video/retry` is accepted, and it invalidates the video stage only — nothing upstream (`run_service.py:840-883`).

*Why 8.16 works without re-running the image stage:* `compositing_service.resolve_placements` computes its own depth map from each shot's `image_path` via the content-addressed cache (`compositing_service.py:551-556`). It does not read `depth_map_path` from state. Ground placement is therefore fully available in a video-only re-render.

### AC3 — The on-state is proven on, not assumed on

**Given** a flag flip that silently no-ops is exactly the failure Epic 13 exists to catch,
**when** the on-state render completes,
**then** evidence that placement actually ran is recorded — the resolved `ground_y` values for the adjudicated shots (non-null, differing per depth band) and the depth-map/provenance sidecars that were produced,
**and** the API process's effective `depth_placement_enabled` at render time is captured,
**and** if `ground_y` came back null/absent for a shot, that shot is reported as *not covered by this experiment* rather than counted as an on-state sample.

### AC4 — 11.5 parallax coverage is stated honestly

**Given** `video.py:707` reads `shot.get("depth_map_path")` from checkpoint state, and `8a9a288b`'s image stage ran with the depth resolver **not** injected, so no shot carries that key,
**when** the video-only re-render runs,
**then** the dev session records explicitly that AC2's pair isolates **8.16 ground placement + contact shadow + 8.7 harmonization**, with **11.5 parallax still on its `NO_DEPTH` fallback**,
**and** the parallax fallback counters/log lines from the render are captured as proof of which rung was taken,
**and** the session states plainly whether findings 3/11 were resolved by placement alone, or whether a parallax-on comparison is still owed.

> Reporting "11.5 was on" because the flag was on would be a false claim. `parallax_25d_enabled` defaults `True`, but the renderer degrades to `NO_DEPTH` without a per-shot depth map.

### AC5 — Full both-on watchable render (Jay's directive) with its confound stated

**Given** Jay asked for a fresh SCP-049 run with the feature enabled and all 5 gates auto-approved,
**when** the environment permits it (see AC7's abort rule),
**then** a new SCP-049 run is created against an API started with `YTFLOW_DEPTH_PLACEMENT_ENABLED=true` and run to `complete`, gates auto-approved after an artifact sanity check,
**and** `stock_plate_substitution_enabled` stays `false` (8.17 substitution collapsed background diversity 155→41 and would contaminate the comparison),
**and** its `video.mp4` is recorded for Jay to watch,
**and** the story states that this run's frames are **not shot-matched** to `8a9a288b` and are supporting evidence, not the controlled pair,
**and** if the run is abandoned under AC7, that is recorded with the measured reason and AC2's controlled pair stands as the story's evidence.

### AC6 — A recorded verdict, at frame level

**Given** the off/on pairs,
**when** they are adjudicated,
**then** exactly one verdict is written into this story file's Dev Agent Record:

- **GROUNDED** — cards now read as standing in the scene. Story closes; findings 3/11 attributed to the features having been off.
- **STILL FLOATING** — and then the frames must name **which link is broken**, one of:
  - **ground line** — feet land at the wrong height / not on the plate's floor (`compositing_service._place`, `ground_plane`, `frame_fraction`)
  - **card scale** — card is the wrong size for its depth band (`_CARD_HEIGHT_FRAC = {"far": 0.379, "mid": 0.516, "near": 0.688}`, `compositing_service.py:182`)
  - **contact shadow** — absent, detached, or wrong shape under the feet (`build_contact_shadow`, tier ≥ 1)
  - **harmonization** — card colour/light does not match the plate (`composite_harmonization_tier`, default `1` = tint + contact shadow; 2 adds light wrap; 3 adds IC-Light)
  - **occlusion** — plate geometry nearer than the card is not masking it (`_card_occlusion_mask`)

**And** the named link is the scope of follow-up work — proposed as tasks or a follow-up story, **not implemented inside this story** unless it is a one-line constant with frame evidence on both sides of the change.

### AC7 — 8.16's gate metric vs. perception, fed to 13.2

**Given** 8.16 passed its own live gate at "3.9px max tracking error vs 57.2px for a static anchor",
**when** the verdict is STILL FLOATING (or the perceived result is unchanged despite placement provably running),
**then** the story records the explicit finding that **the 8.16 gate metric does not proxy viewer perception**,
**and** that finding is handed to Story 13.2 (visual eval axes) — appended to `13-2-visual-eval-axes.md` or logged in sprint-status against 13-2,
**and** if the verdict is GROUNDED, the story records instead that the metric *did* proxy perception on this axis, which is equally useful to 13.2.

### AC8 — Exit criterion: frames or nothing

**Given** Epic 10's common acceptance criterion,
**when** closing this story is considered,
**then** it closes ONLY with off/on frame evidence present in this story file (paths into `10-1-live-validation/` plus the verdict),
**and** it does NOT close on passing tests, on code wiring, or on "the flag is now true",
**and** if visual adjudication turns out to be impossible (services down, GPU unavailable, DPM not `high`, ComfyUI wedged), the story is **escalated to Jay and left open** — it is not flipped to done.

### AC9 — No scope drift

**Given** the epic's other six stories cover adjacent defects,
**when** the frames reveal problems outside grounding,
**then** they are recorded as observations and routed to their owning story — background populated by people → 10.2, art-style/LoRA drift → 10.3, image/narration mismatch → 10.4, standing-pose-vs-narration → 10.5, cast identity → 10.6, siren → 10.7,
**and** none of them is fixed here,
**and** the 2–3 minute narration length is **not** addressed (`reasoning=low`, Epic 12's territory).

## Tasks / Subtasks

- [x] **Task 0 — Environment preflight, before touching anything (AC8)**
  - [x] `cat /sys/class/drm/card*/device/power_dpm_force_performance_level` → must be `high`. If `auto`, the GPU clock sticks at 52MHz and generation goes 15s→500s. Needs root, resets on reboot: **escalate to Jay, do not attempt to set it**. (Verified `high` at story-creation time.) — **`high` on all cards, no escalation needed.**
  - [x] `systemctl --user status ytflow-api ytflow-comfy` — both active. **Both active; api up 2h09m, comfy 2h19m.**
  - [x] `journalctl --user -u ytflow-comfy | grep "Prompt executed" | tail` — establishes the completion history that distinguishes "wedged" from "loading". ComfyUI cold start is ~8m30s; **a stall threshold shorter than that kills a healthy loading ComfyUI.** — **warm: 21–25 s prompts as recently as 16:50, so no cold-start allowance was needed.**
  - [x] `curl -s localhost:8000/runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d` — confirm `status=complete`, `video` gate `approved`. **Both confirmed; all 5 gates approved.**

- [x] **Task 1 — Preserve the off-state (AC1). Do this before Task 3.**
  - [x] `mkdir -p _bmad-output/implementation-artifacts/10-1-live-validation/{off,on,pairs}` — plus a `.gitignore` holding `*.mp4` so the clips stay out of git by construction rather than by memory.
  - [x] Use the **pre-verified shot slate** below (already checked against this run: cast-bearing, clip present, all three depth bands, three positions, one- and two-card cases). Substitute only if a clip turns out unreadable. — **all six verified present in `shots/` and their depth/position re-confirmed against the scenario artifacts; no substitution needed.**
  - [x] For each: `ffmpeg -i workspace/8a9a288b-.../shots/scene_NNN_SNNNNN.mp4 -ss <t> -frames:v 1 .../off/scene_NNN_SNNNNN_t<t>.png`. Use a mid-clip timestamp (Ken Burns drift is largest away from t=0 — that is where a static anchor visibly slides off the floor). — **t = duration/2 rounded to 0.1 s. `-nostdin` is required: without it ffmpeg consumes the loop's stdin and silently skips every other shot.**
  - [x] Copy `video.mp4` to `.../off/video_off.mp4` (56 MB — keep it out of git; note the path, do not commit the mp4). — **done, plus the six source clips.**
  - [x] Record the chosen shot list + timestamps in the story so the on-state extraction is identical. — **recorded in the Frame Pairs table and encoded in `make_pairs.sh`, which is what actually re-extracted the on-state.**

- [x] **Task 2 — Restart the API with depth on (AC3, AC5)**
  - [x] The unit is **transient** (`/run/user/1000/systemd/transient/ytflow-api.service`) — `systemctl --user restart` re-uses the same `ExecStart` and would keep `depth=false`. It must be stopped and re-created:
    ```
    systemctl --user stop ytflow-api
    systemd-run --user --unit=ytflow-api --working-directory=/mnt/work/projects/yt.flow \
      --property=Restart=always --property=RestartSec=5s \
      /bin/bash -lc 'set -a; . /mnt/work/projects/yt.flow/.env; set +a; \
        export LANGFUSE_PUBLIC_KEY="$YTFLOW_LANGFUSE_PUBLIC_KEY" \
               LANGFUSE_SECRET_KEY="$YTFLOW_LANGFUSE_SECRET_KEY" \
               LANGFUSE_HOST="$YTFLOW_LANGFUSE_HOST" \
               PYTHONPATH=/mnt/work/projects/yt.flow/src \
               YTFLOW_DEEPSEEK_MAX_TOKENS=32768 \
               YTFLOW_DEPTH_PLACEMENT_ENABLED=true; \
        exec uv run uvicorn yt_flow.api.main:app --host 127.0.0.1 --port 8000'
    ```
    (Copy the current `ExecStart` verbatim from `systemctl --user cat ytflow-api` and change only the one flag — the LANGFUSE re-exports and `PYTHONPATH` are load-bearing.) — **done. Extra step the story did not anticipate: `systemctl --user stop` leaves the transient unit loaded, so `systemd-run` fails with "Unit was already loaded or has a fragment file". `systemctl --user reset-failed ytflow-api` after the stop is required before re-creating it.**
  - [x] Confirm the new process actually sees it before rendering anything (log line, or a one-off `Settings().depth_placement_enabled` under the same env). — **there is no log line at the injection sites, so confirmed three independent ways instead: the new unit's `ExecStart`, `/proc/<pid>/environ` for both the bash wrapper and the uvicorn child, and `Settings().depth_placement_enabled` under the same env.**
  - [x] `.env` carries **no** depth/parallax pins (checked), so the process env is the only lever. Do not add pins to `.env` — a stale pin silently overriding a code default is a repeat failure mode in this repo. — **re-verified; no pins added.**

- [x] **Task 3 — The controlled on-state render (AC2, AC3, AC4)**
  - [x] `POST /runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/stages/video/retry`. **Only `video`.** Retrying `image` calls `_delete_image_artifacts` (`run_service.py:870-871`) and destroys all 66 rendered images — a previous session did exactly this. — **202 at 18:24:27 KST. `image` gate stayed `approved` throughout; all 66 plates intact.**
  - [x] Watch it: 66 depth-map estimations (~1.2s each once the depth model is resident) then the composite/render. No SDXL image generation happens in this stage, so the checkpoint-eviction cost that motivated `19c4cf1` does not apply here. — **32 estimations, not 66: the content-addressed cache already held the repeats. 0.72–1.69 s each, ~35 s total. The `19c4cf1` stall did not reproduce, as predicted.**
  - [x] Extract the on-state frames at the **same** shot ids and timestamps as Task 1 → `.../on/`.
  - [x] Capture proof-of-on: resolved `ground_y` per adjudicated shot (non-null, and ordered `far < mid < near` in card height), depth sidecars written, and the parallax renderer's fallback reason/counters (expect `no_depth_map` — record it, do not hide it). — **0 nulls / 73 cards; band means order far < mid < near; `no_depth_map` logged for every shot and recorded rather than hidden. Also caught what the task did not ask for: `_GROUND_Y_MAX` clamps 34% of all cards and 85% of the near band.**

- [x] **Task 4 — Build the pairs and adjudicate (AC2, AC6)**
  - [x] For each shot: `ffmpeg -i off.png -i on.png -filter_complex hstack .../pairs/scene_NNN_SNNNNN_pair.jpg` (label OFF/ON with `drawtext` so the pair is self-describing months from now). — **use `drawtext=font=sans`, not `fontfile=$FONT`: this repo's shell is zsh, where `$FONT:text=` applies the `:t` (basename) history modifier and silently mangles the filter string.**
  - [x] **Look at each pair.** Read the images. Judge: do the feet meet a surface? Does the card size agree with its depth band? Is there a shadow where the feet touch? Do card and plate share a colour/light cast? — **all six read, plus 2× zoom crops on the contact regions. The shadow question could not be settled by eye — my first reading of "no contact shadow" was wrong and a numeric frame diff corrected it.**
  - [x] Write the verdict per AC6 into the Dev Agent Record, with the specific broken link named if STILL FLOATING. — **STILL FLOATING → `harmonization`, with the near-band clamp and contact-shadow strength recorded as measured contributors.**

- [x] **Task 5 — Full both-on run (AC5)** — **attempted and abandoned; blocked, not skipped. See "Task 5 abandoned" in the Dev Agent Record.**
  - [x] `POST /runs` with `{"scp_id": "SCP-049"}`; auto-approve each of the 5 gates via `POST /runs/{id}/stages/{stage}/gate {"action":"approve"}` after checking that stage's artifacts are non-empty and plausible. — **run `f52607c9` created (201) and failed 6 s later in `scenario` on `YTFLOW_GEMINI_API_KEY is not configured`. No gate was ever reachable to approve.**
  - [x] **Measure the first 3 shots of the image stage.** The ~500s/shot reload attributed to depth-vs-SDXL VRAM eviction (`api/main.py:58-70`) is **contested** — the custom instructions state the real cause was the GPU DPM at its lowest clock, which is now `high`. Do not assume either way. If per-shot time exceeds ~60s, **abort this run**, record the measurement, and let AC2's controlled pair stand as the evidence (AC5 permits this). — **not measurable; the image stage was never entered. The contested claim stays contested for the image stage and is explicitly NOT resolved by this story. What was measured is adjacent and narrower: in a video-only re-render, 32 depth estimations cost ~35 s total with no reload stall at all.**
  - [x] Do not change `stock_plate_substitution_enabled` (stays `false`). — **verified `False` at render time; unchanged.**
  - [x] If a stage fails: retry **that** stage, never an upstream one. `POST /runs/{id}/resume` resumes from checkpoint after an API restart. — **not applicable: retrying `scenario` would fail identically until the credential exists. No upstream stage was ever retried, on either run.**

- [x] **Task 6 — Write up (AC6, AC7, AC8, AC9)**
  - [x] Fill the Dev Agent Record: verdict, pair paths, ground_y table, parallax rung, and the environment measurements.
  - [x] Record the 8.16-metric-vs-perception finding and hand it to 13.2 (AC7). — **appended a dedicated hand-off section to `13-2-visual-eval-axes.md` (four candidate axes with this story's measurements as calibration data, plus the paired-diff method) and logged it against 13-2 in sprint-status.**
  - [x] Route any non-grounding observations to 10.2–10.7 as notes; fix none of them (AC9). — **six routed, none fixed.**
  - [x] `_bmad-output/implementation-artifacts/10-1-live-validation/README.md` — what each file is, following the `8-9-live-validation/README.md` precedent.
  - [x] Commit the PNGs and README; **do not commit the mp4s.** — **`10-1-live-validation/.gitignore` holds `*.mp4`, so exclusion is structural rather than a thing to remember at `git add` time.**

## Dev Notes

### Pre-verified adjudication slate (AC2)

Derived live from `GET /runs/8a9a288b-.../stages/scenario/artifacts` ∩ `ls workspace/8a9a288b-.../shots/`. Use these six:

| clip | cards (key / depth / position) | why it is in the slate |
|---|---|---|
| `scene_001_S00102` | SCP-049 / far / right | only readable `far` case with a clip — smallest card, most sensitive to a wrong ground line |
| `scene_001_S00101` | STOCK-d-class / mid / left | the modal case (27 of 31 cast-bearing clips are `mid`) |
| `scene_002_S00203` | SCP-049 / mid / center | centre position — isolates `_X_FRAC` from the ground line |
| `scene_002_S00202` | SCP-049 / near / right | largest card; contact shadow and harmonization are most visible here |
| `scene_001_S00104` | SCP-049 / near / right **+** STOCK-d-class / mid / left | two cards, **two different depth bands in one frame** — `_CARD_HEIGHT_FRAC` ordering and ground-line ordering are checkable inside a single image |
| `scene_004_S00403` | SCP-049 / near / right **+** STOCK-d-class / near / left | two cards, same band — they must share a ground line |

**Only 42 of the 66 images have a clip in `shots/`** (8.11 per-shot cut assembly merges/drops shots), and 31 of those 42 carry cast. A shot with no clip cannot be adjudicated — always intersect against `ls shots/` before picking. Card `depth`/`position` come from each shot's `cast` entries in the **scenario** artifacts (`CastEntry`, `state.py:130-131`), not from the video artifacts.

### The one-flag blast radius

`depth_placement_enabled` gates three things, not one (`api/main.py`):

| Line | Gated on the flag | Effect when off |
|---|---|---|
| `:70` | `inject_depth_resolver` → image stage writes `depth_map_path` | shots carry no depth companion |
| `:106` | `inject_ground_resolver` → 8.16 `resolve_placements` | cards keep the pre-8.16 frame-centre anchor |
| (indirect) | 11.5 parallax needs `depth_map_path` | `render_motion_clip` → `NO_DEPTH` rung → 7.3/11.3 zoompan |

`parallax_25d_enabled` has its **own** switch and is `True` by default — but it is inert without a depth map. That asymmetry is the whole reason AC4 exists.

### Grounding chain, in the order a frame reveals it

1. **Depth map** — `compositing_service.depth_map_file` / content-addressed cache keyed on source SHA + estimator identity + contract (`depth_map_cache_path`, `verify_depth_pair`). Default checkpoint `depth_anything_v2_vits.pth` (Apache-2.0; Large/Giant are CC-BY-NC and refused unless `depth_allow_noncommercial_model`).
2. **Ground band** — `ground_plane(depth_map, position, depth)` → plate-space floor fraction; falls back to `_DEFAULT_GROUND[depth]` when unreadable.
3. **Plate→frame correction** — `frame_fraction(plate_aspect, plate_fraction)` (`compositing_service.py:563-580`). Generated plates are 1344×768 (AR 1.75), narrower than 16:9, so the Ken Burns `scale…crop` shifts the floor; without this correction the ground line sits a few px low on *every* generated plate. Stock plates are 1920×1080 and pass through. **Two plate resolutions coexist — a frame that looks fine on stock and wrong on generated points here.**
4. **Card box** — `card_box(...)` with `_CARD_HEIGHT_FRAC = {"far": 0.379, "mid": 0.516, "near": 0.688}` (`:182`, `:455-461`). Card is bottom-anchored: bottom edge = feet.
5. **Overlay anchor** — `video.py` `_overlay_filter` with `ground_y_expression` (`:472-507`, `:765-811`). The *expression* form tracks the plate under Ken Burns; the plain `ground_y` float form does not. `ground_y` is clamped to `_GROUND_Y_MAX` and non-numeric values are dropped with a warning back to the centre anchor (`:1345-1357`) — **a dropped `ground_y` looks like "placement did nothing", so check the warnings before blaming the algorithm.**
6. **Contact shadow** — tier ≥ 1; a static `geq` ellipse. Note the existing caveat at `video.py:1465`: the ellipse has no time terms, so under a moving `ground_y_expr` the shadow and the feet can disagree over the clip. **If the pairs show a shadow that drifts off the feet, this is the named link — and it is a known structural limitation, not a mystery.**
7. **Occlusion** — `_card_occlusion_mask` writes a per-(plate, card, position, depth) mask beside the plate; absent mask is a valid outcome, never fatal.
8. **Harmonization** — `composite_harmonization_tier` default `1` (tint + contact shadow), `2` light wrap, `3` IC-Light. Tier 0 was the confirmed "cheap collage" cause; 11.1 raised the default to 1.

### Why a fresh run cannot be the controlled evidence

- `_shot_seed(run_id, scene_num, shot_id)` (`image.py:131-141`) — run_id is in the hash, so **every background differs** between runs by design (11.1 AC1, deliberately, to kill the seed-0 monoculture).
- The scenario stage regenerates: different narration → different scene/shot decomposition → the shot ids do not even correspond.
- The `8a9a288b` sidecars all carry `seed` (verified: 66/66), so its images are reproducible *for that run id* — which is exactly what the video-only re-render exploits.

### Destructive operations — the exact list

- `POST /stages/image/retry` → `_delete_image_artifacts(run_id, scenes)` deletes the rendered PNGs. **Never for this story.**
- Video re-render → `for stale in shots_dir.glob(f"scene_{n:03d}_*.mp4"): stale.unlink()` (`video.py:1885`) plus segment/final overwrite. **This is why AC1 comes first.**
- `retry` on any stage cascades `_nullify` to all downstream stages.

### Environment facts (verified at story creation, 2026-08-08)

- GPU DPM: `high`. ✅
- `ytflow-api` and `ytflow-comfy` both active as **transient** systemd user units — `systemctl --user restart` will NOT pick up a new env var.
- `.env` contains no `YTFLOW_DEPTH_*` / `YTFLOW_PARALLAX_*` / harmonization / stock-plate pins. Config defaults apply except where the unit's `ExecStart` overrides.
- Current unit pins: `YTFLOW_DEEPSEEK_MAX_TOKENS=32768`, `YTFLOW_DEPTH_PLACEMENT_ENABLED=false`.
- Run `8a9a288b`: `complete`, all 5 gates approved, 66 images + 66 sidecars (all with `seed`), 42 shot clips in `shots/`, 9 segments, `video.mp4`.

### Anti-patterns for this story specifically

- ❌ Writing code before a pair exists on disk.
- ❌ Claiming 11.5 parallax was exercised because its flag was true (AC4).
- ❌ Pinning the flag into `.env` — process env only; a stale `.env` pin silently overriding a code default has bitten this repo before.
- ❌ Retrying `image` to "refresh" anything.
- ❌ Closing on green tests. This story has no meaningful unit-test surface; if code changes do appear under AC6, they carry their own tests, but tests never substitute for the frames.
- ❌ Fixing the narration length, the siren, the LoRA, or populated backgrounds (AC9).

### Testing

No new test surface is expected — this story's deliverable is evidence, not code. If AC6 lands on a code fix, the existing suites that cover the touched area are `tests/` for `compositing_service` / `video.py`, and `tests/api/test_lifespan_injection_gates.py` (currently uncommitted in the working tree) already asserts the resolver-injection gating this story depends on. Run the focused module tests plus `ruff` for any such change; do not run a full-suite sweep as a proxy for the visual verdict.

### Project Structure Notes

- Evidence: `_bmad-output/implementation-artifacts/10-1-live-validation/{off,on,pairs}/` + `README.md` — mirrors `8-9-live-validation/` and `8-20-live-validation/`.
- Commit PNGs and the README; keep mp4s out of git (reference workspace paths instead).
- No new modules, services, or dependencies. `ffmpeg` and `ffprobe` are already on the box and are all Task 1/4 need.
- Sprint-status is concurrently edited by other sessions — stage `sprint-status.yaml` partially rather than wholesale (recurring collision in this repo).

### References

- Epic entry: `_bmad-output/planning-artifacts/epics.md#Story 10.1` (and the Epic 10 preamble on baseline contamination + the common "show the finding is gone" AC)
- Jay's directive: `_bmad-output/story-automator/10-1-custom-instructions.md`
- Previous session record: `_bmad-output/story-automator/orchestration-8-20260803-100738.md`
- 8.16 spec: `_bmad-output/implementation-artifacts/spec-8-16-depth-aware-placement-iclight.md`
- 11.5 story (depth contract, licensing, renderer ladder): `_bmad-output/implementation-artifacts/11-5-depthflow-25d-parallax.md`
- 8.7 harmonization tiers: `_bmad-output/implementation-artifacts/8-7-composite-harmonization.md`
- Downstream consumer of AC7: `_bmad-output/implementation-artifacts/13-2-visual-eval-axes.md`
- Code: `src/yt_flow/api/main.py:58-110` · `src/yt_flow/config.py:248-300` · `src/yt_flow/services/compositing_service.py:182,455-461,524-613` · `src/yt_flow/services/parallax_service.py:100-107,536-612` · `src/yt_flow/pipeline/nodes/video.py:472-507,680-730,765-811,1345-1357,1389-1465,1880-1912` · `src/yt_flow/pipeline/nodes/image.py:131-141,361` · `src/yt_flow/services/run_service.py:840-883` · `src/yt_flow/api/routes/stages.py:20-27` · `src/yt_flow/api/routes/runs.py:61-134`
- Comparison target: `workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/` (66 images, `video.mp4` 3:06)
- Older baseline for reference only: `workspace/c6be1954-.../` (8:10, 155 images)

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] (Claude Code dev-story session, 2026-08-08)

### Debug Log References

- Off-state preservation (AC1): `10-1-live-validation/off/` — 6 PNG frames + 6 source clips + `video_off.mp4`, all copied at 18:22 KST, **before** the 18:24:27 retry.
- Controlled re-render (AC2): `POST /runs/8a9a288b-.../stages/video/retry` → 202 at 18:24:27 KST. Video stage only; `image` never touched, all 66 plates and sidecars intact.
- Ground evidence (AC3): replicated video_node's own chain read-only — `CharacterService.resolve_cast_cards` then `compositing_service.resolve_placements` against the same checkpoint (`yt_flow.db`, thread_id = run id).
- Parallax rung (AC4): `journalctl --user -u ytflow-api` — `shot SNNNNN fell back to legacy zoompan (no_depth_map)`, every shot.
- Clamp measurement: `_GROUND_Y_MAX` from `video.py:1332` against the resolved values.

### Environment Measurements

| Item | Value |
|---|---|
| GPU DPM at render time | `high` (all 4 `card*/device/power_dpm_force_performance_level`) — verified before Task 1 |
| API `depth_placement_enabled` at render time | **true** — three independent reads: unit `ExecStart`, `/proc/1977885/environ` and `/proc/1977895/environ`, and `Settings().depth_placement_enabled` under the same env |
| Other flags at render time | `parallax_25d_enabled=True`, `composite_harmonization_tier=1`, `stock_plate_substitution_enabled=False` (AC5's no-contamination requirement holds) |
| Depth estimations run (count / mean seconds) | 32 ComfyUI prompts, 0.72–1.69 s each (mean ≈ 1.1 s). Fewer than 66 because the content-addressed cache (`workspace/cache/depth`, 302 entries) already held the repeats — exactly the behaviour `depth_map_cache_path` documents. Estimator: `depth_anything_v2_vits.pth` (Small, Apache-2.0). |
| Depth cost vs. the `19c4cf1` premise | ~35 s of depth work total for the whole 66-shot run. The ~500 s/shot stall that motivated gating depth off does **not** reproduce in a video-only re-render — no SDXL checkpoint is resident to evict. |
| ComfyUI state | active, warm; `Prompt executed` history continuous through the render |
| Image-stage per-shot time, first 3 shots (Task 5) | **not measurable — the run never reached the image stage.** See "Task 5 abandoned" below. The contested ~500 s/shot claim from `19c4cf1` therefore remains **unsettled for the image stage**; this story only disproves it for a video-only re-render. |

### Ground Placement Evidence (AC3)

Resolved through the same code path the render used. **Zero null `ground_y` across all 73 cards in 51 shots** — placement ran on every card, so no shot is excluded from the experiment under AC3's null rule.

| shot_id | card | depth band | position | ground_y (on) | occlusion mask | notes |
|---|---|---|---|---|---|---|
| 1:S00101 | STOCK-d-class | mid | left | 0.8688 | — | plate has an unambiguous floor line |
| 1:S00102 | SCP-049 | far | right | 0.8560 | — | smallest card; off-state float was largest here |
| 1:S00104 | SCP-049 | near | right | **0.9772** → clamped 0.9421 | ✅ | two-band frame |
| 1:S00104 | STOCK-d-class | mid | left | 0.8888 | ✅ | ordering vs. the near sibling holds pre-clamp |
| 2:S00202 | SCP-049 | near | right | **0.9642** → clamped 0.9421 | — | plate is a wall, no floor at the card's x |
| 2:S00203 | SCP-049 | mid | center | **0.9603** → clamped 0.9421 | ✅ | top-down corridor plate |
| 4:S00403 | SCP-049 | near | right | **0.9672** → clamped 0.9421 | — | same-band pair |
| 4:S00403 | STOCK-d-class | near | left | **0.9652** → clamped 0.9421 | — | same-band pair |

Band ordering across the whole run (means): **far 0.8052 < mid 0.8538 < near 0.9470** (n = 8 / 38 / 27). The depth band ordering AC3 asks for is satisfied, and all plates are 1344×768 (AR 1.75), so `frame_fraction`'s plate→frame correction was active on every one.

**Measured side-finding — the clamp eats the near band.** `_GROUND_Y_MAX = 0.9421` (`video.py:1332`). Across the run:

| band | n | clamped | mean excess over the ceiling |
|---|---|---|---|
| far | 8 | 0 (0%) | — |
| mid | 38 | 2 (5%) | 17.5 px |
| near | 27 | **23 (85%)** | 29.4 px |
| **total** | **73** | **25 (34.2%)** | |

For 85% of near-band cards the depth map's answer is discarded and replaced by one constant. Live confirmation in the render log: `Clamped ground_y 0.972 to 0.942 so the card's motion stays in frame`. Whether 29 px matters is a question for the frames, not for the arithmetic — see the verdict.

### Parallax Rung (AC4)

- **renderer fallback reason observed:** `no_depth_map` — logged verbatim once per shot, e.g. `shot S00101 fell back to legacy zoompan (no_depth_map)`. Observed for every shot in the render, not a sample.
- **11.5 exercised in the controlled pair? NO.** `depth_map_path` is absent on **0 of 66** shots in the checkpoint (measured, not assumed): the image stage that produced them ran with `inject_depth_resolver` gated off, and a video-only re-render does not re-enter the image stage, so nothing writes that key. `parallax_25d_enabled` was `True` the whole time and was inert — precisely the asymmetry AC4 exists to prevent misreporting.
- **Therefore the controlled pair isolates 8.16 ground placement + contact shadow + 8.7 harmonization (tier 1) only.** A parallax-on comparison is still owed and is *not* delivered by this story; it requires re-running the **image** stage with depth on, which would destroy this run's 66 plates and with them the shot-matched pairing. It belongs in a story that can afford a fresh run.

### Frame Pairs (AC1, AC2)

All six slate shots captured. Paths relative to `_bmad-output/implementation-artifacts/10-1-live-validation/`. Off and on frames are the same shot id at the same timestamp; the plate's Ken Burns chain is unchanged between them, so the backgrounds get identical treatment and every meaningful difference in a pair is the card, its shadow, or its mask. They are two separate h264 encodes, so background-only regions carry a **~0.87 mean luminance noise floor** — every measurement below is stated against a control band inside the same pair, never as an absolute.

| shot_id | t | cards (depth/position) | off | on | side-by-side | feet moved down |
|---|---|---|---|---|---|---|
| scene_001_S00102 | 1.5 s | far/right | `off/scene_001_S00102_t1.5.png` | `on/scene_001_S00102_t1.5.png` | `pairs/scene_001_S00102_pair.jpg` | ~220 px |
| scene_001_S00101 | 1.5 s | mid/left | `off/scene_001_S00101_t1.5.png` | `on/scene_001_S00101_t1.5.png` | `pairs/scene_001_S00101_pair.jpg` | ~112 px |
| scene_002_S00203 | 2.4 s | mid/center | `off/scene_002_S00203_t2.4.png` | `on/scene_002_S00203_t2.4.png` | `pairs/scene_002_S00203_pair.jpg` | ~220 px |
| scene_002_S00202 | 3.1 s | near/right | `off/scene_002_S00202_t3.1.png` | `on/scene_002_S00202_t3.1.png` | `pairs/scene_002_S00202_pair.jpg` | ~125 px |
| scene_001_S00104 | 1.2 s | near/right + mid/left | `off/scene_001_S00104_t1.2.png` | `on/scene_001_S00104_t1.2.png` | `pairs/scene_001_S00104_pair.jpg` | ~110 px both |
| scene_004_S00403 | 1.2 s | near/right + near/left | `off/scene_004_S00403_t1.2.png` | `on/scene_004_S00403_t1.2.png` | `pairs/scene_004_S00403_pair.jpg` | ~105 px both |

Close-reading crops (2× zoom on the contact region, generated for adjudication):
`pairs/_zoom_S00101_feet.jpg` · `pairs/_zoom_S00202_shadow.jpg` · `pairs/_zoom_S00203_card.jpg`

Rebuild command: `10-1-live-validation/make_pairs.sh` (re-extracts `on/` and rebuilds `pairs/`; `off/` is never touched).

### VERDICT (AC6)

- [ ] GROUNDED
- [x] **STILL FLOATING** → broken link: **`harmonization`** (primary — the defect that survives on every frame), plus **`occlusion`** as a *new regression the on-state introduces*, a measured secondary defect on the **`ground line`** (near-band clamp), and a contributing weakness in **`contact shadow`** strength.

**Reasoning (citing the pairs):**

The two findings this story was asked to settle do not have the same answer, and the verdict follows the one that is still open.

**Finding 11 ("characters float") is substantially fixed by 8.16, and the frames prove it.** In `scene_001_S00102_pair.png` the `far` card hovers 280 px above the debris floor with the flag off; with it on it lands at the base of the slope and reads as standing on it. In `scene_004_S00403_pair.png` both `near` cards drop from a ledge in mid-frame onto the reflective floor and share one ground line, which is exactly what two same-band cards should do. In `scene_001_S00104_pair.png` both cards land on the container's bottom lip and the `near` card stays 57 px below its `mid` sibling — depth ordering preserved inside one frame. Four of six shots read as standing where none did before. This is not a placebo: every card's `ground_y` resolved non-null, the band means order correctly, and the drop measured in the pixels matches the resolved value (`scene_002_S00202` on-state feet land at y = 1018, against the clamped 0.9421 × 1080 = 1017).

**Finding 3 ("torn out and pasted onto the background") is not fixed, and that is why the verdict is STILL FLOATING.** Grounding moved the cards to the right height; it did nothing about their being cutouts. `scene_004_S00403_pair.png` is the clearest case — the two cards now stand *on* a mirror-polished floor that reflects every object in the plate and reflects neither of them. `scene_001_S00101_pair.png` keeps a flat saturated orange jumpsuit against a desaturated grey-green plate with no shared light. The alpha edges stay hard at every card boundary in all six pairs. `composite_harmonization_tier` was `1` (tint + contact shadow) for this render; tier 2 (light wrap) and tier 3 (IC-Light relight) exist in the code and were not exercised. **The link the frames name is harmonization** — what remains after grounding is precisely "card and plate do not share light".

Two measured contributors, both real, neither sufficient to be the primary:

1. **Ground line, near band — the clamp discards the depth answer 85% of the time.** `_GROUND_Y_MAX = 0.9421` (`video.py:1332`) truncates 23 of 27 near-band cards, mean excess 29.4 px, live-logged as `Clamped ground_y 0.972 to 0.942 so the card's motion stays in frame`. The near band's ground line is therefore a near-constant, not a measurement. Visible consequence in `scene_001_S00104_pair.png`: the near/mid separation is compressed from the resolved 95 px to 57 px. The clamp is doing its documented job (keeping idle motion in frame) — this is a **conflict between two correct requirements**, not a bug, and resolving it needs a decision, not a patch.
2. **Contact shadow is present and correctly tracked, but too weak to read as contact.** My first pass through the frames called it absent; measuring proved that wrong and the measurement is the record. Signed luminance difference between the off and on frames of `scene_002_S00202` (identical backgrounds, so this isolates the overlay): the ON-shadow-only band under the feet is **+15.7** darker than off, against **+0.05** and **−0.02** in two control bands at the same y away from the card, with 78% of the band's pixels shifted by more than 8 levels. The ellipse is where the card is, at the y the card is anchored to. It is `boxblur=12:1` over a 64/255 alpha, and at that strength it does not sell contact on a lit plate.

**A regression the on-state introduces: the occlusion mask erases heads.** This is the one thing in this experiment that makes a frame *worse* than the off-state, and it was found by zooming into `scene_002_S00203` — see `pairs/_zoom_S00203_card.jpg`. Off, SCP-049 is whole. On, the plague-doctor mask and the top of the hood are gone; a hard-edged notch is cut out of the silhouette and what remains is a headless coat. `_card_occlusion_mask` decided the plate's geometry sits in front of the card's head and masked it out.

Measured across the whole run, not extrapolated from the one frame:

| | count | share |
|---|---|---|
| cards carrying an occlusion mask | 14 / 73 | 19.2% |
| masks cutting >30% of the card's top quarter (the head/shoulders region) | **3 / 14** | 4.1% of all cards |

The three: `S00203` SCP-049 center/mid (57% of the top quarter cut), `S00506` STOCK-d-class right/near (35%), and the worst, `S00704` SCP-049-2 right/mid — **69% of the top quarter and 54% of the entire card removed**. The other eleven masks are benign or empty, so the feature is not uniformly wrong; it fails on plates whose depth map reads a near wall or grating at head height. Off-state frames never show this because with no ground resolver injected no card carries an `occlusion_mask` key at all — **this defect only exists when the feature under test is on.** Routed as its own follow-up; not fixed here, per AC6's scope rule.

**What the frames say about the two plates that could not answer the question at all:** `scene_002_S00202` is a brick wall with no floor anywhere near the card's x, and `scene_002_S00203` is a top-down corridor whose floor is in the opposite corner from the card. No ground-placement algorithm can put a figure on a floor a plate does not contain; in `S00203` the correct ground line pushes the card to the bottom frame edge, which reads worse than the wrong one did. These two are **plate-content defects, routed to 10.2/10.4** (see AC9), and they are the reason the slate's six shots yield four usable grounding verdicts rather than six.

**Scope consequence (AC6's rule):** the named link is *not* implemented here. `harmonization` means raising `composite_harmonization_tier` and validating tiers 2/3 on frames — a change with its own render cost and its own before/after gate, not a one-line constant. The near-band clamp is likewise a design decision (motion headroom vs. ground fidelity) that needs Jay's call. Both are proposed as follow-ups below, and this story ships the evidence that justifies them.

### 8.16 Gate Metric vs Perception (AC7)

**Finding: the 8.16 gate metric does not proxy viewer perception, and this run shows the specific way it fails.**

8.16 passed at "3.9 px max tracking error vs 57.2 px for a static anchor". That metric measures whether the card's anchor *follows the plate under Ken Burns*. This story confirms it is honest about what it measures — the on-state cards track and land where the resolver said they would, to the pixel. But it is silent on all four things that actually decide whether a viewer sees a person in a room:

1. **Whether the plate has a floor at all.** Two of six slate plates do not. The tracking metric scores them exactly as well as the four that do.
2. **Whether the ground answer survived the clamp.** 85% of near-band values are replaced by a constant *after* placement resolves. Tracking error is measured against the clamped anchor, so the clamp is invisible to it — the metric reports 3.9 px on a value the depth map did not choose.
3. **Whether the card and the plate share light.** Unmeasured; it is the defect that survived this whole experiment.
4. **Whether a contact cue is readable.** The shadow is present at +15.7 luminance and correctly tracked, so a "shadow drawn / shadow tracks" check passes while the frame still reads as a cutout.

**Handed to 13.2** in the section appended to `13-2-visual-eval-axes.md`, as four concrete candidate axes with the measurements above as their first calibration data: *plate affords a ground plane* (binary, pre-check), *ground answer survived clamping* (ratio, cheap and already computable), *card/plate light agreement*, *contact cue readable*. The first two are computable today from data this story already produced; the last two need the visual eval 13.2 exists to build.

Also worth 13.2's attention: a paired off/on frame diff with identical backgrounds turned out to be a **precise instrument** — it isolated the contact shadow to ±0.05 luminance in the controls and settled a question my eyes got wrong. Any axis 13.2 defines over composited overlays can be calibrated this way without a new metric harness.

### Task 5 abandoned — no new run can be created on this box (AC5)

AC5's full both-on watchable run was attempted and **failed 6 seconds in, before reaching the image stage**. AC5 explicitly permits this outcome provided the reason is measured and recorded, so it is recorded here in full.

```
POST /runs {"scp_id": "SCP-049"}          → 201, run f52607c9-4b42-43fd-b86c-ee14f58119f3, 18:44:23
GET  /runs/f52607c9-...                    → status=failed, gate_states={"scenario": "failed"}, 18:44:29
error: stage=scenario run_id=f52607c9-...: YTFLOW_GEMINI_API_KEY is not configured
```

**Cause, verified rather than inferred:** `scenario.py:143-144` fail-fasts on a missing `gemini_api_key`; `config.py:65` defaults it to `""`; and this box's `.env` contains **no `YTFLOW_GEMINI_API_KEY` and no occurrence of the string "gemini" at all** (40 lines, checked). This is Story 12.2's Gemini model-split credential, and 12.2's own record already flagged it as handed to Jay ("풀 golden-SCP 런은 워크트리 .env 부재로 Jay 인계").

**This is not caused by the API restart in Task 2.** The re-created unit sources the same `.env` with the same `set -a` block and differs from the original in exactly one character sequence, the depth flag — confirmed by diffing against `systemctl --user cat ytflow-api` before the restart. A key absent from `.env` was absent for the original process too.

**Why run `8a9a288b` exists at all, then:** its scenario stage completed 2026-08-07T16:18 UTC, under an older long-lived API process running pre-12.2 code. The current master code plus the current `.env` cannot start a new run.

**Operational consequence worth surfacing beyond this story: no new pipeline run can be created on this machine until Jay adds `YTFLOW_GEMINI_API_KEY` to `.env`.** That blocks every Epic 10 story that needs fresh renders (10.2, 10.3, 10.4 all do), and it blocks the parallax-on comparison AC4 leaves owed. I did not invent or substitute a credential.

**Per AC5, AC2's controlled pair stands as this story's evidence** — and it is the stronger evidence anyway, since a fresh run's frames are not shot-matched to `8a9a288b` and could not have been paired with the off-state at all.

### State left behind — needs Jay's decision

Two things about this box are not what they were before this session, both deliberate, neither reverted unilaterally:

1. **`ytflow-api` is currently running with `YTFLOW_DEPTH_PLACEMENT_ENABLED=true`.** The unit is transient, so a reboot drops it back to the code default. Whether depth placement should be on in production is exactly what this story's verdict argues against doing *yet* — the head-erasure regression hits ~4% of cards. Reverting is one command (stop, `reset-failed`, re-run `systemd-run` with the flag `false`); I left it on so the state matches the evidence on disk and Jay can inspect it live. **Jay's call.**
2. **Run `8a9a288b`'s video gate is `pending`, not `approved`, and the run reads `awaiting_approval` instead of `complete`.** The retry reset it, and `workspace/8a9a288b-.../video.mp4` is now the **depth-on** 3:06 render (rebuilt 18:42, backed up as `10-1-live-validation/on/video_on.mp4`). The off-state video Jay originally watched survives only as `10-1-live-validation/off/video_off.mp4`. I did **not** re-approve the gate: approving it would assert this render is good, which contradicts the STILL FLOATING verdict above.

### Observations Routed Elsewhere (AC9)

Recorded, not fixed here.

| Observation | Evidence | Routed to |
|---|---|---|
| Plates are populated with large painted human figures that the cards are then composited over — an anime woman's face and torso fills `scene_001_S00104` and `scene_004_S00403`, and a second figure sits behind the bars in `scene_002_S00203`. This is the defect that makes grounding unanswerable on those plates. | `pairs/scene_001_S00104_pair.jpg`, `pairs/scene_004_S00403_pair.jpg`, `pairs/_zoom_S00203_card.jpg` | **10.2** |
| Art style differs sharply between plate and cards, and between plates — `scene_001_S00104` is soft anime illustration, `scene_002_S00202` is photographic, the cards are flat cel shading throughout. | all six pairs | **10.3** |
| Two of six plates do not depict the space the shot needs: `S00202` is a featureless brick wall, `S00203` is a top-down corridor with no floor at the subject's position. Neither affords a place for a character to stand. | `pairs/scene_002_S00202_pair.jpg`, `pairs/scene_002_S00203_pair.jpg` | **10.4** |
| Every card is the standing front pose; `resolve_cast_cards` logged `no sitting card for STOCK-d-class angle=front, falling back to standing` six times in this render. | API log, 18:24:37 | **10.5** |
| `resolve_cast_cards: invalid JSON from LLM: ''` — an empty completion, the `content==""` signature of DeepSeek reasoning-token truncation. It fell back safely, so nothing broke, but the cast-decision call is running truncated. | API log, 18:24:37 | **10.6** |
| No card casts a reflection on `scene_004_S00403`'s mirror-polished floor, where every plate object does. | `pairs/scene_004_S00403_pair.jpg` | folded into this story's **harmonization** follow-up |

Not addressed, per AC9: narration length (Epic 12), the siren (10.7).

### Follow-ups Proposed (AC6 scope rule — named, not implemented)

1. **Harmonization tier ≥ 2 on frames.** Raise `composite_harmonization_tier` and adjudicate tier 1 vs 2 vs 3 on this same shot slate. The off/on paired-frame method used here transfers directly, and `off/` is already on disk as a permanent third reference point.
2. **Near-band ground line vs. motion headroom.** `_GROUND_Y_MAX = 0.9421` overrides the depth answer for 85% of near-band cards. Options: shrink the idle-motion excursion for near cards, let the anchor exceed the ceiling and clip the card's lower edge, or accept the constant and stop paying for depth estimation on that band. **Needs Jay's decision — it is a requirements conflict, not a defect.**
3. **Contact shadow strength.** Present and correctly tracked at +15.7 luminance; the question is whether 64/255 under `boxblur=12` is the right strength. Cheap to A/B on the existing slate.
4. **A parallax-on comparison** remains owed (AC4) and needs a fresh run, since turning the depth resolver on for the image stage destroys this run's shot-matched plates.
5. **Occlusion mask head-erasure — the highest-severity item here.** 3 of 14 masks remove the head; the worst removes 54% of the card. Unlike the others this is a *regression* that only appears with the feature on, so shipping depth placement without addressing it trades a float for a decapitation on ~4% of cards. Candidate fixes worth evaluating: refuse a mask that would cut the card's top quarter beyond a threshold (the cheapest guard, and the mask is already written as a file that can be inspected before use), or restrict occlusion to plate geometry below the card's shoulder line. Evidence: `pairs/_zoom_S00203_card.jpg`, `pairs/_mask_S00203.jpg`.

### Completion Notes List

**This story shipped evidence, not code. Zero production files were changed.** That was the intended outcome: AC6's scope rule opens code work only for a one-line constant with frame evidence on both sides, and nothing here met that bar — every named link is a design decision with a render cost.

What was produced:

- **The controlled off/on pair the story was built around** (AC1, AC2): 6 shot pairs from the same run, same plates, same cards, same script, same shot ids, differing in one flag. Off-state preserved before the first destructive call.
- **Proof the on-state was actually on** (AC3): `depth_placement_enabled` verified three independent ways; 0 null `ground_y` across 73 cards; band ordering far < mid < near; pixel-level agreement between resolved and rendered anchor.
- **An honest negative on 11.5** (AC4): `depth_map_path` absent on 0/66 shots, `no_depth_map` logged for every shot. The parallax flag was `True` and inert the whole time. A parallax-on comparison is still owed.
- **A verdict with the broken link named** (AC6): STILL FLOATING → `harmonization`, plus a newly-found `occlusion` regression, the near-band clamp, and contact-shadow strength.
- **Three measurements that did not exist before**: the `_GROUND_Y_MAX` clamp rate (34.2% of all cards, 85% of the near band), the contact-shadow strength (+15.7 luminance against a +0.05 control), and the occlusion head-cut rate (3 of 14 masks; worst removes 54% of a card).
- **AC7 handed to 13.2** as four candidate axes with this story's numbers as their first calibration data.

Three things worth carrying forward beyond this story:

1. **The verdict is split across the two findings it was asked to settle, and saying so is the point.** Finding 11 (float) is substantially fixed — the frames show it. Finding 3 (pasted-on) is not. Reporting a single "it works" would have been the exact failure Epic 10 exists to prevent.
2. **My first reading of the frames was wrong and a measurement caught it.** I judged "no contact shadow" by eye on two plates; the shadow is present, correctly positioned, and 78% of the band's pixels move. On composited overlays, eyes are not an instrument — a control band in the same frame pair is.
3. **The experiment surfaced a regression the feature itself introduces.** The occlusion mask erases heads on ~4% of cards, and that defect exists *only* when the feature under test is on. It would not have been found by any test, only by looking at frames.

**Tests:** no production code changed, so no new tests were written. `tests/api/test_lifespan_injection_gates.py` (2 passed) was run because this story's whole premise rests on the resolver-injection gating it asserts; it is a verification of the premise, not a proxy for the visual verdict, which per AC8 tests can never substitute for.

**Two AC-permitted gaps, both blocked on Jay, both stated rather than papered over:** AC5's full both-on run (missing `YTFLOW_GEMINI_API_KEY` — blocks all new runs on this box) and AC4's parallax-on comparison (needs a fresh run, so it inherits the same blocker).

### Change Log

| Date | Change |
|---|---|
| 2026-08-08 | Story 10.1 executed. Off-state preserved, video-only re-render with `depth_placement_enabled=true`, 6 off/on frame pairs adjudicated. Verdict **STILL FLOATING → `harmonization`**, with a new `occlusion` head-erasure regression (3/14 masks), the near-band `_GROUND_Y_MAX` clamp (85% of near cards), and contact-shadow strength recorded as measured contributors. AC4 recorded honestly: 11.5 parallax not exercised (`no_depth_map`, 0/66 shots carry a depth map). AC7 handed to Story 13.2. AC5 attempted and abandoned on a missing `YTFLOW_GEMINI_API_KEY`. **No production code changed.** |

### File List

**Added — evidence (this story's deliverable):**

- `_bmad-output/implementation-artifacts/10-1-live-validation/README.md`
- `_bmad-output/implementation-artifacts/10-1-live-validation/.gitignore`
- `_bmad-output/implementation-artifacts/10-1-live-validation/make_pairs.sh`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_001_S00101_t1.5.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_001_S00102_t1.5.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_001_S00104_t1.2.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_002_S00202_t3.1.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_002_S00203_t2.4.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/off/scene_004_S00403_t1.2.png`
- `_bmad-output/implementation-artifacts/10-1-live-validation/on/` — same six filenames, on-state
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_001_S00101_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_001_S00102_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_001_S00104_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_002_S00202_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_002_S00203_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/scene_004_S00403_pair.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/_zoom_S00101_feet.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/_zoom_S00202_shadow.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/_zoom_S00203_card.jpg`
- `_bmad-output/implementation-artifacts/10-1-live-validation/pairs/_mask_S00203.jpg`

**Modified — documents:**

- `_bmad-output/implementation-artifacts/10-1-grounding-composite-live-verification.md` (this file — task checkboxes, Dev Agent Record, Change Log, Status)
- `_bmad-output/implementation-artifacts/13-2-visual-eval-axes.md` (AC7 hand-off section + reference)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (10-1 → review; AC7 hand-off logged against 13-2)

**Not committed (gitignored, referenced by path):**

- `10-1-live-validation/off/video_off.mp4` — 56 MB, the only surviving copy of the render Jay watched
- `10-1-live-validation/off/*.mp4` — the six off-state source clips
- `10-1-live-validation/on/video_on.mp4` — 56 MB, the depth-on 3:06 render

**Production source files changed: none.**
