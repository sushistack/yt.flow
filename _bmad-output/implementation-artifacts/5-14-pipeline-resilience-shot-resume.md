---
created: 2026-07-06
story_key: 5-14-pipeline-resilience-shot-resume
story_id: "5.14"
epic: 5
previous_story: 5-13-character-vision-provider-swap
depends_on:
  - 5-11-segmentation-failure-shot-fallback
baseline_commit: eb9e2964860cd183050607a00ffb9b260bee70af
---

# Story 5.14: Pipeline Resilience — Shot-Level Resume + ComfyUI Health Check

Status: review

## Story

As Jay,
I want the image stage to skip shots whose outputs already exist and are complete when it re-runs, and to health-check ComfyUI with a bounded connection retry before submitting,
so that an infrastructure crash mid-stage (ROCm driver death at shot 39/59) costs minutes on retry instead of a full ~40-minute GPU re-render of all 59 shots.

## Context

Context: E2E baseline 2026-07-06 (run `272b05a4`, SCP-049), defects D6 + D8 (`_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`).

During the baseline's image stage, ComfyUI (ROCm, RX 9060 XT) crashed with a `hipErrorIllegalAddress` core dump after generating 78 images (~39 of 59 shots) — **D6, infra/major**. The pipeline behaved exactly per contract: 5-11's per-shot flat fallback was attempted, ComfyUI was dead so the fallback also failed, and the run failed with a clear chained error. The code defect is what happened next: the stage retry (`POST /runs/{id}/stages/image/retry`, Story 2.4) re-ran `image_node` from shot 1 and **regenerated all 59 shots**, because the per-shot loop (`src/yt_flow/pipeline/nodes/image.py:236-303`) has no skip-existing logic — **D8, moderate**. 78 images / 30-40 minutes of GPU time were thrown away even though the files were sitting on disk under `workspace/{run_id}/images/`.

ROCm instability under sustained load is environmental, not a yt.flow bug (run `eb522cf9` and this baseline both ran >30-minute image stages). The goal of this story is **graceful absorption, not prevention**: ① shot-level resume so a retry starts where the crash left off, ② a lazy ComfyUI health check plus bounded retry on connection-class errors only, and ③ an operator-side crash-restart watchdog for ComfyUI's `run.sh` — documented here, deliberately **not** implemented in this repo (the ComfyUI install lives outside it, at `$HOME/workspaces/ComfyUI/`).

Two facts make file-level skip semantically safe: (a) both shipped workflow JSONs pin their sampler seeds (`data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` node `"3"` seed `0`; `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` nodes `"3"`/`"17"` seeds `0`/`1`), so regenerating with identical prompts is deterministic — skipping loses nothing; (b) what file existence alone *cannot* tell you is whether the file was generated from the **current** prompts — shot filenames are deterministic (`scene_{scene_num:03d}_{shot_id}`), so after a scenario retry (2.4's cascade `_nullify` zeroes state paths but leaves disk files, `src/yt_flow/services/run_service.py:547-556`) stale images would silently collide with the new shots' names. The skip rule therefore includes a tiny per-shot completion sidecar recording the prompts (see Dev Notes).

**Epic 8 forward-compatibility (read before designing):** Epic 8 (drafted the same day, stories 8.1-8.3 in `epics.md`) will REMOVE the segmentation/inpaint layered path entirely and make `image_node` background-only + card compositing in `video_node`. All resume/health-check logic in this story must be expressed at the "shot output files" level so it survives that transition: the layered "background+character pair" completeness rule is the *current-state* rule, and under Epic 8 it collapses to "background file (+ sidecar) exists" with no structural change to the skip mechanism. The health check and connection retry are composition-independent and survive unchanged.

## Acceptance Criteria

1. **Shot-level resume (layered mode).** Given layered real mode (`YTFLOW_COMFYUI_LAYERED=true`, mock off) and a prior image-stage attempt left, for some shots, a complete output set on disk under `workspace/{run_id}/images/` — complete meaning `scene_XXX_{shot_id}.png`, `..._background.png`, and `..._character.png` all exist, background and character are each >1KB, and the shot's completion sidecar (`..._done.json`) exists with `image_prompt`/`negative_prompt` exactly matching the current shot — when `image_node` re-runs for the same run (stage retry 2.4 or resume-from-failure 1.10), then those shots are **skipped with zero ComfyUI submissions**, their `ShotData` paths point at the existing files (`layered_fallback=False`), and every incomplete shot generates through the normal path.
2. **Incomplete or stale outputs regenerate.** Given a shot whose prior attempt left only a background file (mid-shot crash remnant, a 5-11 flat-fallback output, or a legitimate background-only result), or any required file ≤1KB, or a missing sidecar, or a sidecar whose prompts differ from the current shot (retry after a 2.4 prompt edit or scenario re-run), when `image_node` re-runs, then that shot is fully regenerated through the normal layered path — i.e. **fallback-degraded shots get a fresh layered chance on retry**, per the session rule "skip only when BOTH background and character files exist".
3. **Shot-level resume (non-layered mode).** Given non-layered real mode, when `image_node` re-runs and a shot's `scene_XXX_{shot_id}.png` exists >1KB with a matching sidecar, then that shot is skipped (no submission); otherwise it regenerates.
4. **Lazy health check before first submission.** Given real (non-mock) mode, when `image_node` reaches the **first shot that actually needs generation**, then it first verifies ComfyUI reachability (`GET /system_stats` via a new `comfyui_client.check_health`) with the same bounded retry as AC5; if still unreachable, the node fails fast via the AD-10 error contract (`error` string `stage=image run_id=...`, no exception past the node) **without submitting any shot**. Given a re-run where every shot is already complete on disk, then the node completes successfully **even if ComfyUI is down** (no health check, no HTTP). Given mock mode, then no HTTP client is ever instantiated (existing contract preserved).
5. **Bounded retry on connection-class errors only.** Given `POST /prompt` (or the health check) raises a connection-class error (`httpx.TransportError` — connection refused, DNS failure, transport-level timeout), when the client submits, then it retries up to 3 total attempts with a short flat backoff (~2s) before raising `ComfyUIError`; and given a ComfyUI validation rejection (HTTP 400 / `node_errors` — `httpx.HTTPStatusError`) or a generation-timeout (`"produced no image ... within timeout"`, poll budget exhausted), then there is **no retry** — those fail exactly as today.
6. **Preserved behavior.** Given the changes, then: 5-11's per-shot flat-fallback semantics are unchanged (same `ComfyUIError` catch, chained both-errors message when the fallback also fails, `layered_fallback` flag, `fallback_count` metric, fallback path writes **no** sidecar); `request_count` trace metadata stays accurate (skipped shot = 0, layered success = 1, fallback shot = 2; connection retries within one submission and the health check add nothing); a new `skipped_count` appears in `_record_trace` metadata mirroring the existing counter pattern; and the node's AD-10 error contract and state-purity contract (fresh `{**shot, ...}` dicts, no input mutation) are untouched.
7. **Tests.** Given the fix, then the new behaviors are covered by tests in `tests/pipeline/nodes/test_image.py` (resume skip / stale-sidecar regenerate / fallback-remnant regenerate / undersized-file regenerate / all-complete-with-ComfyUI-down success / skipped_count metric / health-check failure fails fast) plus a new offline `tests/services/test_comfyui_client_retry.py` (transport retry succeeds on 3rd attempt, validation error not retried, generation timeout not retried, `check_health` behavior), and the full regression suite stays green.
8. **Watchdog documented, not implemented.** Given this story, then NO watchdog/process-management code, script, or Settings field lands in this repo — the ComfyUI crash-restart loop is an operator instruction for `$HOME/workspaces/ComfyUI/run.sh` recorded in this story's Dev Notes, and the Dev Agent Record notes whether Jay applied it. Zero new config knobs anywhere (module constants only — Ponytail).

## Tasks / Subtasks

- [x] Completion sidecar + skip check in `image_node` (AC: 1, 2, 3) — `src/yt_flow/pipeline/nodes/image.py`
  - [x] Add module constant `MIN_VALID_IMAGE_BYTES = 1024` (integrity floor; matches the baseline gate's deterministic check "0-byte/placeholder ≤1KB" in `e2e-baseline-2026-07-06.md`).
  - [x] Add a sidecar helper: sidecar path = `out_dir / f"{base}_done.json"` (same `base = f"scene_{scene_num:03d}_{shot['shot_id']}"` naming as `_generate_layered_shot`, `image.py:157`); content = `json.dumps({"image_prompt": ..., "negative_prompt": ...})`. Write it **last**, after all image files for the shot, so it doubles as the atomic completion sentinel (current write order in `_generate_layered_shot` is bg → char → img copy, `image.py:182-194`).
  - [x] Write the sidecar on: layered success **with** a character (`char_path is not None`), and every non-layered success. Do NOT write it on the 5-11 flat-fallback path (`_generate_flat_fallback_shot`, `image.py:199-215`) and do NOT write it on layered background-only success (`char_bytes is None`) — both must regenerate on retry per AC2. (Under Epic 8 this collapses to "always write after background" — keep the write site in `image_node`'s loop or a one-line helper, not buried in `_generate_layered_shot`'s branches, so the collapse is a one-line change.)
  - [x] Add a skip check at the **top** of the per-shot loop (`image.py:238`), before prompt injection and before the mode branch decision: a small pure helper, e.g. `_existing_complete_shot(out_dir, scene_num, shot, layered) -> tuple[paths] | None`, that returns the existing paths iff sidecar exists + prompts match + required files exist (layered: img + bg >1KB + char >1KB; non-layered: img >1KB). On skip: append `{**shot, "image_path": ..., "background_path": ..., "character_path": ..., "layered_fallback": False}` (layered) or the non-layered equivalent (`background_path`/`character_path` `None`), increment `image_count`/`background_count`/`character_count` normally plus a new `skipped_count`, and `continue`. No mock/real branch in the check itself — it is a pure file check; all shipped mock fixtures are 67-70 bytes (< the 1KB floor), so mock-mode behavior is effectively unchanged.
  - [x] `logger.info("image stage resume: skipped %d complete shot(s), generating %d", ...)` once after the loop (or at first skip) when `skipped_count > 0` — matches the module's existing logging style (`image.py:250-253`).
- [x] `skipped_count` in trace metadata (AC: 6) — `src/yt_flow/pipeline/nodes/image.py:120-150`
  - [x] Add `skipped_count=0` parameter to `_record_trace` and pass it from both the success and error paths (mirrors `fallback_count`, added by 5-11).
- [x] ComfyUI health check (AC: 4) — `src/yt_flow/services/comfyui_client.py` + `src/yt_flow/pipeline/nodes/image.py`
  - [x] Add `async def check_health(base_url: str) -> None` to `comfyui_client`: `GET /system_stats` with a short timeout (~5s), reusing the same bounded-retry-on-`httpx.TransportError` loop as `_submit` (below); raises `ComfyUIError(f"ComfyUI unreachable at {base_url}: ...")` on final failure.
  - [x] Call it **lazily** in `image_node`: a local `health_checked = False` flag; before the first shot that actually submits (layered or non-layered, real mode only — never in mock), `await comfyui_client.check_health(s.comfyui_url)` then set the flag. A fully-resumed run (all shots skipped) must never touch HTTP — this is the D6 payoff: retry after a crash completes the stage even while ComfyUI is still restarting, if everything is on disk.
  - [x] Update the stale comment at `src/yt_flow/config.py:32-33` ("Reachability is checked at image_node entry") — it describes a check that never existed; make it read "checked lazily before the first ComfyUI submission in image_node" so it's finally true. No new Settings field.
- [x] Bounded connection retry in the client (AC: 5) — `src/yt_flow/services/comfyui_client.py:104-119`
  - [x] Module constants `CONNECT_ATTEMPTS = 3`, `CONNECT_RETRY_DELAY = 2.0` (no config — Ponytail; tests monkeypatch the delay to 0).
  - [x] In `_submit`, retry the `client.post("/prompt", ...)` call on `httpx.TransportError` only (up to `CONNECT_ATTEMPTS` total, `asyncio.sleep(CONNECT_RETRY_DELAY)` between). `httpx.HTTPStatusError` (validation, line 108-110) must NOT be retried — note `HTTPStatusError` is not a `TransportError` subclass, so catching `TransportError` gets this for free. The poll-budget timeouts in `_await_image`/`_await_outputs` (`comfyui_client.py:142,174`) are generation-class — do not touch them; the poll loops already self-heal transient HTTP errors within their budget (lines 122-142, 145-174, documented in their docstrings).
  - [x] Do not add retry to `_download` (`comfyui_client.py:177-189`) — out of scope, see Saved Questions.
  - [x] Note: this retry also benefits `character_image_provider.py:104,111` (the other `submit_and_fetch` caller) for free — acceptable, same failure class.
- [x] Tests (AC: 7)
  - [x] `tests/pipeline/nodes/test_image.py` — follow the file's existing conventions (`FakeSettings` at lines 49-59, `_state()` fixture at 62-93, `monkeypatch.chdir(tmp_path)` + relative `workspace/` isolation, `RGB_PNG`/`RGBA_PNG` synthetic PNGs). Pre-create resume files by writing into `tmp_path / "workspace/run-img-1/images/"` before calling the node; pad fixture bytes past the floor (`RGBA_PNG + b"\x00" * 1024` — trailing bytes after IEND don't matter, only size/existence are checked). New tests:
    - [x] `test_layered_resume_skips_complete_shots` — S001 has img+bg+char (>1KB) + matching sidecar; count `submit_and_fetch_outputs` calls; assert 2 calls (S002/S003 only), S001's paths point at the pre-created files, `layered_fallback is False`, `error is None`.
    - [x] `test_resume_regenerates_on_prompt_mismatch` — sidecar present but with a different `image_prompt` → 3 submissions (stale-after-edit protection).
    - [x] `test_resume_regenerates_background_only_remnant` — only `_background.png` on disk, no char/sidecar (crash remnant or 5-11 fallback output) → shot regenerates (AC2 pair rule).
    - [x] `test_resume_regenerates_undersized_files` — matching sidecar but bg ≤1KB → regenerates.
    - [x] `test_full_resume_completes_with_comfyui_down` — all 3 shots complete on disk; monkeypatch `img.comfyui_client.check_health` AND both submit fns to raise `AssertionError` → node returns success, `skipped_count == 3`, `request_count == 0`.
    - [x] `test_health_check_failure_fails_fast` — no files on disk; `check_health` raises `ComfyUIError` → `out["error"]` set with `stage=image`, submit fns never called (monkeypatch them to `AssertionError`).
    - [x] `test_mock_mode_never_checks_health` — extend the existing `test_mock_mode_never_calls_comfyui` pattern (line 169-177): monkeypatch `check_health` to raise `AssertionError`, assert mock run still succeeds.
    - [x] `test_resume_skipped_count_in_trace` — captured `_record_trace` kwargs include `skipped_count`; `request_count` counts only real submissions (5-11 review-patch accuracy preserved: skipped=0, fallback still 2).
    - [x] Confirm all existing tests pass unmodified — fresh `tmp_path` workspaces mean no test has pre-existing files, and mock fixtures are sub-1KB, so the skip check should be invisible to them. The sidecar write adds `*_done.json` files next to images; no existing assertion globs the directory, but verify.
  - [x] New `tests/services/test_comfyui_client_retry.py` — must be fully **offline** (this matters: the existing `tests/services/test_comfyui_client.py` is network-dependent and excluded from CI runs per project convention — do NOT add these tests there, they'd never run). Drive `_submit`/`check_health` with a stub client object (or `httpx.MockTransport`) and monkeypatch `CONNECT_RETRY_DELAY` to 0:
    - [x] transport error twice then success → succeeds, 3 post calls;
    - [x] transport error persists → `ComfyUIError` after exactly `CONNECT_ATTEMPTS` calls;
    - [x] HTTP 400 validation response → `ComfyUIError` immediately, 1 call, no sleep;
    - [x] `check_health`: reachable → returns; unreachable after retries → `ComfyUIError`.
  - [x] Run: `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_comfyui_client_retry.py -q`, then the full regression per Testing Requirements below.
- [x] Operator watchdog — document only (AC: 8)
  - [x] Nothing lands in this repo. Relay the "Operator Instruction — ComfyUI crash-restart watchdog" block from Dev Notes to Jay in the Completion Notes; record whether it was applied to `$HOME/workspaces/ComfyUI/run.sh`.

## Dev Notes

### Critical Implementation Guardrails

- **Do not restructure 5-11's per-shot `try`/`except`** (`image.py:243-271`). The skip check goes *before* it (top of the shot loop, before `_inject_prompts`); the sidecar write goes *after* a full success. The fallback path (`except ComfyUIError` → `_generate_flat_fallback_shot`) must not write a sidecar — that is precisely what makes fallback shots regenerate on the next retry (AC2), replacing the degraded flat image with a proper layered one when the infra is healthy again.
- **`request_count` accuracy is a patched review finding — do not regress it.** 5-11's review specifically fixed undercounting (failed layered attempt + fallback = 2 real submissions, `image.py:248,255,270-271`; regression-guarded by `test_segmentation_failure_fallback_records_count`, `test_image.py:550-575`). Skipped shots add 0; connection retries inside one `_submit` call are one logical submission, not N; `check_health` is not a submission.
- **The AD-10 error contract is sacred**: `image_node` never raises — every failure becomes `{"current_stage": "image", "error": f"stage=image run_id={run_id}: {exc}"}` via the outer handler (`image.py:314-324`). The health-check `ComfyUIError` simply propagates to that handler; do not add a second error-shaping site.
- **State purity (AD-4)**: skipped shots still append fresh `{**shot, ...}` dicts — never return the input `shot` object or mutate it (`image.py:295` comment; guarded by `test_input_state_not_mutated` / `test_layered_mock_input_state_not_mutated`).
- **Retry classification lives in the client, not the node.** `image_node` must not inspect exception messages to decide retryability. Connection-class = `httpx.TransportError` at the `POST /prompt` boundary (`comfyui_client.py:111-112` currently collapses it into the same `ComfyUIError` as everything else — the retry loop wraps the raw httpx call *before* that wrapping). Validation (`HTTPStatusError`, lines 108-110) and poll-budget exhaustion (lines 142, 174) stay single-attempt. A generation *timeout* is not a connection error: retrying it would double a 3-minute stall for nothing.
- **Zero new Settings fields.** Retry attempts/delay and the 1KB floor are module constants. A health check needs no config (Ponytail rule 1: the knob has no anticipated second value).
- **Sidecar is the completion sentinel AND the staleness guard.** Why not files-only (the session's literal rule)? Because shot filenames are deterministic and 2.4's cascade `_nullify` (`run_service.py:547-556`) zeroes state paths but leaves disk files: after a scenario retry regenerates different prompts for the same `shot_id`s, files-only skip would silently reuse wrong images. The sidecar (prompts json, written last) closes that hole and simultaneously solves write-ordering (bg→char→img→sidecar means a mid-shot crash can never leave a sidecar without complete files). Keep it dumb: exact string equality on `image_prompt`/`negative_prompt`, `json.loads` guarded by `except (OSError, ValueError): return None` (treat unreadable sidecar as incomplete).
- **Why skipping is semantically safe even for a "quality retry"**: both shipped workflows pin sampler seeds (node `"3"` seed `0`; layered also `"17"` seed `1` — verified against `data/workflows/*.json` at baseline commit), so re-running identical prompts reproduces identical images. "Retry to get a different image" was never a real behavior without a prompt edit — and a prompt edit changes the sidecar comparison, forcing regeneration. Caveat for custom operator workflows in Saved Questions.

### Current vs Changed Behavior

| Seam | Current (eb9e296) | After 5.14 |
|---|---|---|
| `image_node` re-run (retry/resume) | regenerates every shot (`image.py:236-303`, no file checks) — D8 | skips shots with complete outputs + matching sidecar; regenerates the rest |
| ComfyUI down at stage start | first shot's submission fails after HTTP error → 5-11 fallback also fails → run fails (~2 failed submissions in) | lazy `check_health` fails fast before any submission; fully-resumed runs don't need ComfyUI at all |
| `POST /prompt` connection blip | single attempt → `ComfyUIError` → (layered) triggers 5-11 flat fallback for that shot | 3 attempts × ~2s backoff absorb the blip; only then the existing failure path |
| Validation error / generation timeout | fails immediately / after poll budget | unchanged — never retried |
| Trace metadata | `request_count/image_count/background_count/character_count/fallback_count` | + `skipped_count` |
| ComfyUI crash mid-run, watchdog applied | n/a | in-flight prompt's history is lost with ComfyUI's queue → poll budget expires (~3min, poll loops already tolerate the restart window per `comfyui_client.py:122-142`) → 5-11 flat fallback resubmits against the restarted server → run completes with 1 degraded shot; the *next* retry regenerates that shot layered (no sidecar was written for it) |

### Epic 8 Forward Compatibility

Epic 8 (stories 8.1-8.3, `epics.md`) removes segmentation/inpaint from `image_node` (background-only generation; characters become video-stage card composites). This story's logic must survive that with edits confined to the completeness rule:

- `_existing_complete_shot` is a pure function of expected output file paths — under Epic 8 the layered branch's rule collapses from "img + bg + char pair + sidecar" to "background file + sidecar", i.e. delete the char-file condition, nothing else.
- The sidecar write site stays in `image_node`'s loop (not inside `_generate_layered_shot`'s branches) so the "write only when char present" condition can be deleted in one line.
- `check_health` and the `_submit` retry live in `comfyui_client` and are completely composition-agnostic.
- Do NOT key the skip logic on `ShotData.layered_fallback`, `character_path`, or any state field — retry re-enters with state paths nulled (`_nullify`), so disk + sidecar are the only truth available. That constraint is what makes this Epic-8-proof.

### Operator Instruction — ComfyUI crash-restart watchdog (NOT in this repo)

`$HOME/workspaces/ComfyUI/run.sh` currently ends with a bare `python main.py --preview-method auto`. To auto-restart after ROCm core dumps (D6 class), replace that final line with:

```bash
while true; do python main.py --preview-method auto; echo "ComfyUI exited (code $?) — restarting in 5s" >&2; sleep 5; done
```

(Keep the existing `HSA_OVERRIDE_GFX_VERSION=12.0.0` / `PYTORCH_HIP_ALLOC_CONF` exports above it.) Pairing with this story: the watchdog turns a mid-run crash into "one shot degrades to flat + ~3min poll stall, run completes"; without it, the run fails cleanly and the operator's stage retry now resumes at the crashed shot instead of shot 1. Either way no GPU time is re-spent on completed shots. This is infra outside the repo — an operator instruction, not code (AC8).

### Current Code State — Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/image.py`
  - `image_node` (218-324): per-scene/per-shot loop 236-303; layered branch 239-282 with 5-11's try/except 243-271; non-layered branch 283-302; counters initialized 223-227; success return 313; outer AD-10 handler 314-324.
  - `_generate_layered_shot` (153-196): naming scheme `base = f"scene_{scene_num:03d}_{shot['shot_id']}"` (157), dests `_background.png`/`_character.png`/`.png` (158-160); real-mode write order bg (182) → char (191) → img copy (194).
  - `_generate_flat_fallback_shot` (199-215): writes `_background.png` + `.png` only — its remnants are exactly the "background-only, regenerate" case.
  - `_record_trace` (120-150): counter-kwargs pattern to extend with `skipped_count`.
  - `_has_alpha` (109-117): NOT needed for the skip check — the sidecar-written-last invariant means the char file already passed alpha validation at generation time.
- `src/yt_flow/services/comfyui_client.py`
  - `ComfyUIError` (18); `submit_and_fetch` (22-37); `submit_and_fetch_outputs` (52-73) — both funnel through `_submit` (104-119), the single seam for the retry loop.
  - `_submit` error taxonomy: `httpx.HTTPStatusError` = validation, no retry (108-110); `httpx.HTTPError` catch-all currently wraps transport errors too (111-112) — the new retry catches `httpx.TransportError` around the raw `client.post` before this wrapping.
  - `_await_image` (122-142) / `_await_outputs` (145-174): poll loops already swallow transient HTTP errors within their 180-poll budget (a prior review fix — read their docstrings); their timeout raise is generation-class. **No changes here.**
  - `_download` (177-189): raises raw httpx errors unwrapped — pre-existing, out of scope (Saved Questions).
- `src/yt_flow/services/run_service.py`
  - `retry_stage` (574-613): `aupdate_state(..., as_node=_RETRY_ENTRY[stage])` re-enters `image_node` on the **same** `run_id`/thread → same `workspace/{run_id}/images/` dir. This is the D8 re-entry path (the baseline used `POST /stages/image/retry` directly, D9).
  - `resume_run_from_failure` (500-511): the other re-entry path (1.10) — same run_id, same workspace.
  - `full_restart_run` (514-541): wipes checkpoints but NOT the workspace dir; with the sidecar rule a restart only reuses a shot if the regenerated prompts are byte-identical (which, with pinned seeds, would reproduce the same image anyway). See Saved Questions.
  - `_nullify` (547-556): proof that state paths are nulled on retry — skip logic can never rely on state, only disk.
- `src/yt_flow/config.py` (32-44): the `comfyui_*` block; line 32-33's "Reachability is checked at image_node entry" comment is currently false — fix the wording, add no fields.
- `tests/pipeline/nodes/test_image.py`: conventions — `FakeSettings` (49-59), `_state()` (62-93, run_id `run-img-1`, 3 shots S001/S002/S003 across 2 scenes), `_wf_file` (96-99), autouse `_quiet_trace` (102-104), `RGB_PNG`/`RGBA_PNG` builders (30-46). 5-11's tests (458-575) are the style template for the resume tests.
- `tests/stubs/fakes.py`: `fake_submit_and_fetch`/`fake_submit_and_fetch_outputs` return 67-byte `TINY_PNG` — the stub e2e profile's images stay below the 1KB floor, so the stub-profile smoke tests (`tests/pipeline/test_stub_profile_smoke.py`, `tests/api/test_e2e_stub_run.py`) never skip and need no changes. Verify, don't assume.

### Previous Story Intelligence

- **5-11 (direct dependency)**: established the per-shot degrade pattern, the `layered_fallback` flag, and — via its code review — the `request_count` accuracy contract and the chained-error message on double failure (`test_image.py:500-524`). This story wraps *around* that machinery without entering it. 5-11's review also deferred "broad `ComfyUIError` catch doubles failure latency on total outage" (`deferred-work.md`) — the lazy health check substantially mitigates the start-dead case (fail fast before any submission); the mid-run-death case keeps the documented bounded worst case.
- **1.10 / 2.4**: resume and retry both re-enter with the same `run_id` — that stability is the entire reason file-level resume works. Nothing in those services changes.
- **E2E baseline (evidence)**: D6 shows the pipeline's failure behavior was already correct ("파이프라인은 계약대로 행동"); D8 is purely about wasted regeneration. The baseline's image-gate deterministic check ("0바이트/플레이스홀더(≤1KB) 없음") is the provenance of the 1KB floor.
- **Memory: worktree editable-install shadowing** — if implementing in a git worktree, run pytest with `PYTHONPATH=$PWD/src` or the main tree's code will be imported instead.

### Testing Requirements

- `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_comfyui_client_retry.py -q`
- Full regression: `PYTHONPATH=$PWD/src uv run pytest -q --ignore=tests/services/test_character_service_generation.py --ignore=tests/services/test_comfyui_client.py --ignore=tests/services/test_image_search.py` (network-dependent exclusions per project convention — confirm still accurate; note `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` had a pre-existing unrelated failure during 5-11, verify against baseline before attributing).
- Live validation (matches 5-8/5-9 rigor): with local ComfyUI up (`$HOME/workspaces/ComfyUI/run.sh`, :8188), start a small real run, kill ComfyUI mid-image-stage (`pkill -f "python main.py"` in the ComfyUI dir simulates D6 without waiting for a real ROCm crash), let the run fail, restart ComfyUI, hit stage retry, and verify from logs/trace metadata that completed shots were skipped (`skipped_count > 0`) and only the remainder regenerated. Also verify the connection-retry path by retrying while ComfyUI is still starting up. If a live pass isn't practical in the session, say so explicitly — the synthetic tests are primary evidence for the control flow, but the kill/restart drill is cheap and directly reproduces the defect scenario, so attempt it.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/pipeline/nodes/image.py`
  - `src/yt_flow/services/comfyui_client.py`
  - `src/yt_flow/config.py` (comment wording only — no new fields)
  - `tests/pipeline/nodes/test_image.py`
  - `tests/services/test_comfyui_client_retry.py` (new, offline-only)
- New runtime artifacts: `workspace/{run_id}/images/scene_XXX_{shot_id}_done.json` sidecars (one per fully-completed shot). They appear under the existing `/files` static mount; the artifact panel reads image paths from state, not by globbing, so no frontend change.
- No new dependencies, no Settings fields, no DB/state-schema changes (`ShotData` untouched), no ComfyUI workflow JSON changes, no frontend changes, nothing in `$HOME/workspaces/ComfyUI/` committed anywhere.

## References

- Evidence: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` — defects D6 (ROCm crash, `hipErrorIllegalAddress`, 39/59 shots) and D8 (no skip-existing → 78 images / 30-40min wasted); image-gate deterministic checks (1KB floor provenance)
- Epic/story source: `_bmad-output/planning-artifacts/epics.md` — "### Story 5.14" draft; "## Epic 8" (forward-compatibility constraint, stories 8.1-8.3)
- Dependency story: `_bmad-output/implementation-artifacts/5-11-segmentation-failure-shot-fallback.md` (fallback semantics, request_count review patch, deferred total-outage-latency item)
- Retry/resume machinery: `src/yt_flow/services/run_service.py` (`retry_stage` 574-613, `resume_run_from_failure` 500-511, `full_restart_run` 514-541, `_nullify` 547-556)
- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1 (client stays an integration adapter in `services/`), AD-4 (node purity), AD-10 (non-fatal degrade / error contract)
- ComfyUI infra: `$HOME/workspaces/ComfyUI/run.sh` (ROCm env, RX 9060 XT), memory note `reference_comfyui_local.md`

## Saved Questions

1. **Sidecar scope creep vs the session's literal rule.** The session rule was "skip when BOTH bg+char files exist (+ >1KB floor)"; this story adds a prompts sidecar because deterministic filenames + 2.4's cascade nullify make files-only skip silently reuse stale images after any scenario retry or prompt edit. If Jay prefers the dumber rule and accepts that risk, delete the sidecar tasks — the pair rule + floor stand alone.
2. **Sidecar doesn't record workflow path/seed.** Swapping the workflow JSON, LoRA, or checkpoint between retries would still skip matching shots. Accepted as operator-level change (workaround: delete `workspace/{run_id}/images/`); recording `comfyui_workflow_path` in the sidecar is a one-key addition if it ever bites.
3. **`full_restart_run` doesn't wipe the workspace dir** — a full restart reuses a shot only if the regenerated prompts are byte-identical (with pinned seeds the image would be identical anyway). Should restart `shutil.rmtree` the run's workspace for strict "no stale artifacts" semantics? Deferred — YAGNI until observed.
4. **Layered background-only successes never skip** under the pair rule (no char file → regenerate every retry). Deliberate per the session rule; moot under Epic 8 when the rule collapses to background-only.
5. **Health-check tolerance (3×~2s) is shorter than a watchdog restart cycle** (~5s + model load). A stage retry issued during the restart window may still fail fast; the next retry resumes with zero waste. Bump attempts only if this bites in practice.
6. **`_download` (GET /view) remains unwrapped/unretried** — raw httpx errors there fail the run via the node's outer handler. Rare (ComfyUI dies between prompt completion and download) and recoverable via retry+resume; out of scope.
7. **Skipped shots are not surfaced in the artifact panel** (unlike `layered_fallback`) — only `skipped_count` trace metadata + an info log. YAGNI until an operator need appears.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5 (Claude Code)

### Debug Log References

- Full regression (`PYTHONPATH=$PWD/src uv run pytest -q --ignore=tests/services/test_character_service_generation.py --ignore=tests/services/test_comfyui_client.py --ignore=tests/services/test_image_search.py`) first run surfaced one failure: `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`. Bisected via `git stash`/`git stash pop` against baseline `eb9e296` — passes on baseline, fails deterministically (3/3 runs) with this story's diff applied. Root cause: the shared `stub_profile` fixture (`tests/conftest.py`) monkeypatches `comfyui_client.submit_and_fetch`/`submit_and_fetch_outputs` but had no fake for the new `check_health`, so any stub-profile test in real (non-mock) mode made a genuine outbound HTTP attempt to the default `comfyui_url`, timing out through the 3× retry and failing the image stage. Fixed by adding `fakes.fake_check_health` and wiring it into `stub_profile` (`tests/conftest.py`, `tests/stubs/fakes.py`) — not a task the story anticipated (it only flagged the skip/sidecar risk to existing tests, not the health check). Re-ran full regression after the fix: 639 passed, 1 skipped, 0 failed.
- Live ComfyUI kill/restart drill (Testing Requirements) was not attempted this session: it requires starting the external GPU service at `$HOME/workspaces/ComfyUI/run.sh` and deliberately killing it mid-run, which felt like the wrong thing to do unattended in an autonomous pass — especially for a story about ROCm crash resilience. The synthetic test suite (AC1-7) is full primary evidence; recommend Jay run the kill/restart drill interactively per the story's Testing Requirements before/while reviewing.

### Completion Notes List

- Shot-level resume implemented via a completion sidecar (`{base}_done.json`, written last) + `_existing_complete_shot` pure file/prompt check at the top of `image_node`'s per-shot loop — layered mode requires img+bg+char (bg/char >1KB) and matching prompts; non-layered requires img >1KB and matching prompts. Fallback-degraded and background-only layered shots never get a sidecar, so they always get a fresh layered chance on retry (AC2).
- `comfyui_client.check_health(base_url)` added (`GET /system_stats`), called lazily in `image_node` only before the first shot that actually needs generation — a fully-resumed retry never touches HTTP, satisfying the D6 payoff (AC4).
- Bounded connection retry (`CONNECT_ATTEMPTS=3`, `CONNECT_RETRY_DELAY=2.0`, module constants) added around `_submit`'s `POST /prompt` and reused by `check_health`, via a small `_request_with_retry` helper that only catches `httpx.TransportError` — validation (`HTTPStatusError`) and generation-timeout paths are untouched (AC5). Also benefits `character_image_provider.py`'s `submit_and_fetch` caller for free, as anticipated.
- `skipped_count` added to `_record_trace` and threaded through both the success and error paths (AC6).
- Fixed a real regression the story didn't anticipate: `tests/conftest.py`'s `stub_profile` fixture needed a `check_health` fake (see Debug Log) — every stub-profile-based test (API e2e, smoke) would otherwise attempt live HTTP. All pre-existing tests in `tests/pipeline/nodes/test_image.py` pass unmodified except for one added autouse fixture (`_no_health_check`) that defaults `check_health` to a no-op so old real-mode tests don't hit live HTTP either; each new health-check-specific test overrides it per-test.
- config.py:32-33's stale "Reachability is checked at image_node entry" comment corrected to describe the actual lazy check (AC4 task item).
- **Operator watchdog (AC8, not implemented in this repo):** relaying the documented instruction to Jay — replace the final line of `$HOME/workspaces/ComfyUI/run.sh` (`python main.py --preview-method auto`) with a `while true; do python main.py --preview-method auto; echo "ComfyUI exited (code $?) — restarting in 5s" >&2; sleep 5; done` loop, keeping the existing `HSA_OVERRIDE_GFX_VERSION`/`PYTORCH_HIP_ALLOC_CONF` exports above it. **Not applied in this session** — ComfyUI wasn't running and this touches infra outside the repo; Jay should apply it manually to `run.sh` when convenient.
- Live kill/restart validation drill: not performed this session (see Debug Log) — flagging for Jay to run interactively.

### File List

- `src/yt_flow/pipeline/nodes/image.py` — sidecar helpers, `_existing_complete_shot` skip check, lazy health-check call site, `skipped_count` threading
- `src/yt_flow/services/comfyui_client.py` — `CONNECT_ATTEMPTS`/`CONNECT_RETRY_DELAY` constants, `_request_with_retry`, `check_health`, retry wired into `_submit`
- `src/yt_flow/config.py` — corrected stale comfyui reachability comment
- `tests/pipeline/nodes/test_image.py` — `_no_health_check` autouse fixture + 8 new Story 5.14 tests (resume skip, prompt-mismatch regenerate, background-only-remnant regenerate, undersized-file regenerate, full-resume-with-ComfyUI-down, health-check-fails-fast, mock-never-checks-health, skipped_count-in-trace)
- `tests/services/test_comfyui_client_retry.py` — new, offline: `_submit` connection retry (succeeds on 3rd attempt / exhausts after `CONNECT_ATTEMPTS` / validation error not retried / generation-timeout path unaffected), `check_health` reachable/unreachable
- `tests/conftest.py` — `stub_profile` fixture now also patches `comfyui_client.check_health` (fix for a regression the story didn't anticipate; see Debug Log)
- `tests/stubs/fakes.py` — added `fake_check_health`

## Change Log

- 2026-07-06: Story created from E2E baseline defects D6/D8 (run `272b05a4`) via create-story; scope = shot-level resume (sidecar-sentinel skip rule), lazy ComfyUI health check + bounded transport retry, operator watchdog documented not implemented. Epic 8 forward-compatibility constraint recorded. Status: ready-for-dev.
- 2026-07-07: Implemented and reviewed by dev-story: shot-level resume (sidecar + skip check), `comfyui_client.check_health`, bounded connection retry, `skipped_count` trace metadata, config.py comment fix. Fixed an unanticipated regression in `tests/conftest.py`'s `stub_profile` fixture (missing `check_health` fake). Full regression green (639 passed, 1 skipped). Live kill/restart drill and operator watchdog application deferred to Jay. Status: review.
