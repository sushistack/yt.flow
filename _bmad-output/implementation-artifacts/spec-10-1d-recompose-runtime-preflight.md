---
title: 'Story 10.1d — Recompose runtime-prerequisite preflight (10.1c unblock condition (b))'
type: 'feature'
created: '2026-08-16'
status: 'in-review'
review_loop_iteration: 0
baseline_revision: 'd39037f'
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `shot_recompose_enabled` is `False` partly because the path needs ComfyUI started with specific flags and free system RAM, and **nothing detects that** — on a stock install it swap-grinds instead of failing, and the per-shot `try/except` never fires because nothing raises. Run `e5ed4b3a` (2026-08-15) proved the failure mode first-hand on a *lighter* path: 491 s/shot of which 11 s was sampling, 14 GB RSS / 0 free / 4 GB swap on a 31 GB box, `_wait_for_comfyui_recovery` engaged against a server that was alive and grinding, 90 minutes of diagnosis and two wrong hypotheses.

**Approach:** At recompose entry — the one run-level moment in the path — read the **running server's** `argv` and free RAM from `/system_stats`, compare against a single declared prerequisite table, and on a miss bail the whole run out of recompose with a named `run_warning` plus an error log carrying the observed `argv` and the exact restart command. Every shot keeps its cards and renders through the overlay path, exactly as if the flag were off — but the operator is told, instead of believing recompose ran.

## Boundaries & Constraints

**Always:** `shot_recompose_enabled` stays `False` — this story closes condition (b) only. The preflight is a *run-level* refusal, distinct from 10.1c's *per-shot* skip: on failure `recompose_run_shots` returns `cast_cards` unchanged so all shots stay renderable via the overlay. `pipeline/nodes/shot_recompose.py` stays layer-pure (stdlib + `yt_flow.domain`). A new `RunWarningCode` must be added to **both** `state.py`'s `Literal` and `RUN_WARNING_CATALOG` or import fails by design. `/system_stats` is best-effort by contract (AD-10) and already returns `None` on any failure — never let it raise.

**Block If:** the prerequisite set cannot be decided from `argv` + `/system_stats` alone without adding a new HTTP endpoint call, a new dependency, or an SSH/process probe of the ComfyUI host.

**Never:** Do not flip `shot_recompose_enabled`. Do not widen `comfyui_health_read_timeout_sec` or `comfyui_crash_recovery_timeout_sec` — the short timeout is a symptom of the misconfiguration, not the disease. Do not infer prerequisites from `.env`, `run.sh`, or the client's own `Settings` — ComfyUI may be on another host. Do not generalise `--disable-smart-memory` to other render paths (it offloads to system RAM, the scarce resource here). Do not add a process-level memo cache. Do not touch the overlay path, ground placement, occlusion, contact shadow, 11.5 parallax or 1.9c idle motion. Do not start 10.1e.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Prerequisites met | `argv` holds all required flags, `system.ram_free` ≥ threshold | Preflight silent; the scene loop runs as today | No error expected |
| A flag missing | `argv == ["main.py", "--preview-method", "auto"]` | Zero shots recomposed; `cast_cards` returned unchanged; `stats["preflight_failed"] == "missing_flags"`; `logger.error` names each missing prerequisite, the observed `argv`, and the restart command | Not raised — bail, not crash |
| RAM below threshold | flags all present, `ram_free` = 1.2 GB of 31 GB | Same bail, reason `low_ram`; the message states the measured free/total GB and the threshold | Not raised |
| `/system_stats` unreachable | `get_system_stats` → `None` | Same bail, reason `stats_unavailable`; message says the server did not answer | Not raised |
| Unexpected payload shape | `{}`, `{"system": []}`, `{"system": {"argv": "x"}}`, missing `ram_free` | Same bail, reason `stats_unreadable`, naming which field was unreadable | Read defensively down to each key — never `AttributeError`/`TypeError` |
| Feature off | `shot_recompose_enabled=False` | `_recompose_resolver` is never invoked, so no `/system_stats` request is made and the preflight costs nothing | No error expected |
| Bail surfaces to the gate | preflight failed during `video_node` | `run_warnings` gains one `recompose_preflight_failed` entry with `reason` + bounded `detail`; the gate payload and `ArtifactPanel` render it with no frontend change | No error expected |

</intent-contract>

## Code Map

- `src/yt_flow/services/recompose_service.py:41-48` -- `async def recompose_run_shots(scenes, cast_cards, settings=None) -> tuple[dict, dict]`; lines 45-48 (`s = settings or Settings()`, `workspace`, `remaining`, `stats`) are the **only** run-level code in the path and the preflight's home. Line 23 imports `comfyui_client` as a module (tests monkeypatch the attribute).
- `src/yt_flow/pipeline/nodes/video.py:2543-2563` -- the recompose block; line 2558 is the `getattr(s, "shot_recompose_enabled", False)` gate (the *only* read of the flag in `src/`), line 2560 unpacks `cast_cards, recompose_stats`. A local `warnings` list is in scope here (appended at 2511/2523/2589, merged into `run_warnings` at 2845/2856).
- `src/yt_flow/services/comfyui_client.py:192-214` -- `get_system_stats(base_url) -> dict | None`; short `STATS_READ_TIMEOUT` (5 s), unretried, never raises. Reuse; do not duplicate.
- `src/yt_flow/pipeline/nodes/image.py:277-305` -- `_build_provenance`'s defensive `/system_stats` read; copy this posture (`isinstance` down to each key) verbatim in spirit.
- `src/yt_flow/services/comfyui_client.py:113-120` -- `resolve_nodes`' error contract: `{key!r} not found; titles present: {sorted(...)}`. The model for AC "missing item + what *is* present".
- `src/yt_flow/domain/state.py:554-581` -- `RunWarningCode` `Literal`; `:584-597` `RunWarning` TypedDict (`context` carries narrow identifiers plus at most one bounded `detail`).
- `src/yt_flow/domain/warnings.py:29-73` -- `RUN_WARNING_CATALOG: dict[str, tuple[StageName, str]]` (Korean operator copy); `:75-82` import-time completeness guard; `:107-120` `make_warning`.
- `frontend/src/components/ArtifactPanel.tsx:152-225` -- `RunWarningList` renders `{stage} · {code}` + message generically (no per-code map); `IDENTIFIER_LABELS:191-207` is a per-*context-key* whitelist that already contains `reason` — so no frontend change is needed for a new code, but a new context key name would be silently dropped.
- `src/yt_flow/config.py:314-331` -- the 10.1c verdict comment; `(b)` at :321-324 is what this story closes. `shot_recompose_enabled` at :330 must stay `False`.
- `data/workflows/comfyui_shot_recompose_qwen_api.json` -- the `clip` node pins `qwen_2.5_vl_7b_fp8_scaled.safetensors` with a `_meta.title` explaining why fp8 is required. **The fp8 encoder is a workflow-file property, not a server flag.**
- `tests/services/test_recompose_service.py:23-80` -- `_StubClient` + the `env` fixture. `_StubClient` has only `upload_image`/`submit_and_fetch`; it needs `get_system_stats` or all 8 existing tests break.
- `tests/pipeline/nodes/test_video_harmonization.py:441-459, 673-681` -- the two video_node patterns to copy: "resolver never called" and "resolver outcome becomes a bounded warning" (`_settings_ns`, `_inject_resolver`, `_relight_warnings_for`, `_scene`, `_state`).
- `data/comfyui/README.md` -- the ComfyUI-environment doc created by 13.3; startup requirements belong here.

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/services/recompose_service.py` -- add ONE module-level prerequisite declaration (flag/condition → why required → how observed) and an `async def _preflight(s) -> tuple[str, str] | None` returning `None` when satisfied and `(reason, message)` otherwise, where `reason` is one of exactly four short slugs — `missing_flags`, `low_ram`, `stats_unavailable`, `stats_unreadable` — and `message` is the full operator text -- the requirement exists today only as prose inside a config comment, so a ComfyUI flag rename must have exactly one place to edit. Required entries: `--lowvram` (weights must stream, not resident), `--disable-smart-memory` (10.1c: without it the Qwen graph swap-deadlocks; note it costs *system* RAM), `--cache-lru` (run `e5ed4b3a`: default `cache-classic` evicts the checkpoint on every graph alternation — 490 s vs 14.8 s per shot; recompose adds a third graph to the alternation), and free system RAM ≥ `s.recompose_preflight_min_free_ram_gb`. The table must state that the **fp8 text encoder is not observable from `/system_stats`** — it is pinned in the workflow JSON's `clip` node and a missing file fails fast at the node with ComfyUI's own error, so the preflight deliberately does not check it.
- [x] `src/yt_flow/services/recompose_service.py` -- call `_preflight` in the run-level block at 45-48, before the scene loop; on failure `logger.error(...)` and `return dict(cast_cards), {"recomposed": 0, "skipped": 0, "failed": 0, "preflight_failed": reason, "preflight_detail": message}` -- run-level misconfiguration must not silently degrade 43 shots to the overlay while the operator believes recompose is on. No memoisation: this function is called exactly once per `video_node` invocation, and a process-level cache would outlive the operator's fix and lie on retry.
- [x] `src/yt_flow/config.py` -- add `recompose_preflight_min_free_ram_gb: float = Field(12.0, gt=0)` beside the recompose settings, with a comment stating the number is **not** a model-footprint calculation: it is the floor that catches the known-fatal state (2026-08-15: 0 free / 4 GB swap on 31 GB was already thrashing a lighter path) rounded up so the Q4_K_M unet's 12 GB can load without swap. Amend the 10.1c verdict comment at :321-326 to record that `(b)` is closed by this story, naming the preflight. **Do not flip `shot_recompose_enabled`.**
- [x] `src/yt_flow/domain/state.py` + `src/yt_flow/domain/warnings.py` -- add `recompose_preflight_failed` to the `RunWarningCode` `Literal` (video_node section) and to `RUN_WARNING_CATALOG` as `("video", "ComfyUI 실행 전제가 맞지 않아 샷 재구성을 건너뛰고 오버레이로 렌더했습니다")` -- the import-time guard fails if only one is edited.
- [x] `src/yt_flow/pipeline/nodes/video.py` -- after line 2560, if `recompose_stats.get("preflight_failed")`, append `make_warning("recompose_preflight_failed", reason=recompose_stats["preflight_failed"], detail=recompose_stats.get("preflight_detail"))` to the local `warnings` list -- `reason` is already in the frontend's `IDENTIFIER_LABELS`, so no frontend change; verify that before claiming it is visible, and do not confuse `run_warnings` with the separate `scenario_quality` channel.
- [x] `tests/services/test_recompose_service.py` -- give `_StubClient` a `get_system_stats` returning a passing payload (otherwise the 8 existing tests break), then cover the matrix: each prerequisite missing in isolation names only itself; all present passes through to the loop; `None` / `{}` / `{"system": []}` / `{"system": {"argv": "x"}}` / missing `ram_free` each bail with their own reason and never raise; a bailed run returns `cast_cards` unchanged with zero submits.
- [x] `tests/pipeline/nodes/test_video_harmonization.py` -- two video_node tests beside the relight-resolver pair: with `shot_recompose_enabled` absent/False the injected recompose resolver is never called; with a resolver returning `preflight_failed` stats, `run_warnings` holds exactly one `recompose_preflight_failed` with the expected `reason` and a bounded `detail`.
- [x] `data/comfyui/README.md` -- a "How ComfyUI must be started" section: the required flags with the measured justification, the exact command, and a pointer to `recompose_service`'s declaration as the enforced copy. State explicitly that `--cache-lru` is *pipeline-wide* operational advice but is **enforced only in the recompose preflight** — the ordinary background path has no such gate. Reuse the file's existing verification advice: confirm the **process** (`ss -ltnp` → owner PID → `/proc/<pid>/cmdline`), because HTTP 200 has twice come from an old process that had not died, and `pkill -f`/`pgrep -f` match the operator's own shell.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- one entry: pipeline-wide `--cache-lru` enforcement at `image_node` entry is out of scope here.

**Acceptance Criteria:**
- Given `shot_recompose_enabled=False`, when `video_node` renders a scene, then the recompose resolver is not invoked, no `/system_stats` request is made, and the filtergraph is unchanged from `d39037f`.
- Given the preflight fails for any reason, when the run finishes, then every shot still rendered through the overlay path with its cards intact, and the gate payload carries exactly one `recompose_preflight_failed` warning.
- Given a failing preflight, when an operator reads the log line alone, then they can restart ComfyUI correctly without opening any source file — the missing prerequisites, the observed `argv` and the restart command are all present.
- Given a future ComfyUI release renames a required flag, when a developer greps for the old flag string in `src/`, then it appears in exactly one declaration.
- Given the repository after this story, when `config.py` is read, then `shot_recompose_enabled` is still `False` and its comment records that unblock condition (b) is closed and (a) is not.
- Given the full suite, when `uv run pytest -q -p no:cacheprovider --ignore=e2e` runs, then there are 0 failures and no test that passed at `d39037f` now fails.

## Spec Change Log

## Review Triage Log

## Design Notes

**Why the service and not the node.** `pipeline/nodes/shot_recompose.py` is layer-pure by an enforced test; an HTTP probe cannot live there. `recompose_service.recompose_run_shots` lines 45-48 are the only run-level code in the path, already hold `Settings` and the `comfyui_client` module, and its return type `(cast_cards, stats)` can already express a whole-run bail-out. Splitting a pure `check(argv, ram_free)` helper into the node module buys a test-mocking convenience the existing `monkeypatch.setattr(recompose_service, "comfyui_client", stub)` already provides — skipped.

**Why the bail is `stats`, not an exception.** The call site at `video.py:2559` wraps the resolver in a blanket `except Exception` that logs at WARNING and *keeps the original `cast_cards`*. Raising would produce the right shot outcome but the wrong operator outcome: one warning-level log line, no `run_warning`, indistinguishable from any other AD-10 degradation. A `preflight_failed` key in the stats dict the caller already unpacks reaches the gate with a two-line diff.

**Shape of the error message** (matching `resolve_nodes`' contract — missing item, then what *is* present):

```
Shot recompose preflight failed: ComfyUI is missing --lowvram, --disable-smart-memory.
  observed argv: ['main.py', '--preview-method', 'auto']
  free RAM: 18.4 / 31.2 GB (threshold 12.0)
  restart with: python main.py --lowvram --disable-smart-memory --cache-lru 10
Recompose is skipped for this run; every shot renders through the overlay path.
```

## Verification

**Commands:**
- `uv run pytest tests/services/test_recompose_service.py tests/pipeline/nodes/test_video_harmonization.py -q` -- expected: all pass, including the 8 pre-existing recompose tests
- `uv run pytest tests/domain tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_video_depth_placement.py -q` -- expected: all pass; the catalog/`Literal` completeness guard does not raise at import
- `uv run pytest -q -p no:cacheprovider --ignore=e2e` -- expected: 0 failures
- `rg -n 'lowvram|disable-smart-memory|cache-lru' src/` -- expected: matches only inside the single prerequisite declaration in `recompose_service.py` (config/README prose excluded)
- `rg -n 'shot_recompose_enabled' src/` -- expected: exactly the `config.py` definition (still `= False`) and the `video.py:2558` gate

**Manual checks (if no CLI):**
- `git diff d39037f -- src/yt_flow/pipeline/nodes/video.py` shows only the warning append after line 2560 — no hunk inside `_build_card_chain`, `_apply_placement`, `ground_y_expr`, `_occlusion_fragment` or `MotionSource`.
- The composed failure message is read once as an operator would: does it name every missing prerequisite, the observed `argv`, and a runnable command?
