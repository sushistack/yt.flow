---
title: 'Story 10.1d — Recompose runtime-prerequisite preflight (10.1c unblock condition (b))'
type: 'feature'
created: '2026-08-16'
status: 'in-review'
review_loop_iteration: 0
baseline_revision: 'd39037f'
followup_review_recommended: true
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

### 2026-08-16 — Review pass

Both reviewers ran (Blind Hunter + Edge Case Hunter, in parallel, no prior context). Every
high-severity claim was verified against a primary source before patching — ComfyUI's own
`comfy/cli_args.py` / `main.py`, this box's `~/workspaces/ComfyUI/run.sh`, and
`domain/warnings.py`'s `MAX_DETAIL_CHARS`.

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 4, medium 5, low 4)
- defer: 1: (high 0, medium 1, low 0)
- reject: 7: (high 0, medium 1, low 6)
- addressed_findings:
  - `[high]` `[patch]` **The gate passed the exact state it exists to catch.** The flag check
    was token-only, but ComfyUI declares `--cache-lru type=int default=0` (`comfy/cli_args.py:113`)
    and enables the LRU cache only `if args.cache_lru > 0` (`main.py:233`) — so `--cache-lru 0`
    is byte-for-byte the 490 s/shot eviction behaviour, and `_preflight` returned `None` for it.
    A non-empty declared value in `REQUIRED_FLAGS` now means "takes a positive-integer value"
    and is enforced; a present-but-inert flag reports itself as such.
  - `[high]` `[patch]` **The restart command was wrong for the only ComfyUI on this box.**
    `~/workspaces/ComfyUI/run.sh` is `source venv/bin/activate` + `HSA_OVERRIDE_GFX_VERSION=12.0.0`
    + `PYTORCH_HIP_ALLOC_CONF=…` + `python main.py --preview-method auto --cache-lru 10`. An
    operator following `restart with: python main.py …` literally would lose the venv and the
    RDNA-4 override — AC3 ("fix it without reading code") failed against the real environment.
    Message and README now say *add these flags to the launcher you already use*.
  - `[high]` `[patch]` **The actionable half never reached the UI.** `make_warning` truncates
    `context["detail"]` at 200 chars; the composed message is ~370 with the argv repr in the
    middle, so the `add to ComfyUI's launcher` line was cut out of the gate payload entirely.
    `_message` is now headline-first by contract and `video_node` files `splitlines()[0]`.
  - `[high]` `[patch]` **An exception here reproduced the silent skip this story exists to end.**
    `_preflight` read `s.recompose_preflight_min_free_ram_gb` by hard attribute access while the
    sibling gate at `video.py:2558` uses `getattr` precisely because Settings stubs are
    SimpleNamespaces — an `AttributeError` escaped into video_node's blanket `except`, which
    logs a WARNING and files **no** `run_warning`. Now `getattr(..., 12.0)`, and that blanket
    `except` also files a `recompose_preflight_failed` with `reason="resolver_error"`, so a
    raising resolver or a non-dict stats payload can no longer be invisible either.
  - `[medium]` `[patch]` An unreadable `ram_free` bailed `stats_unreadable` **before** the flag
    comparison ran, so a box with two flags absent was told only "payload unreadable" — the one
    thing the operator cannot act on, hiding the one thing they can. Flags are compared first.
  - `[medium]` `[patch]` `get_system_stats`' docstring still claimed "called once per run: this
    is observability, **not a health gate**" — both halves falsified by this story. Amended to
    record the second caller, that `None` is now consequential, and that a busy-but-healthy
    ComfyUI can answer `None` because it stops serving `/system_stats` mid-prompt. Deliberately
    not compensated with retries or a longer timeout.
  - `[medium]` `[patch]` `tests/stubs/fakes.py`'s `fake_get_system_stats` had no `argv` and no
    `ram_free`, so the offline E2E profile would have reported a preflight failure
    indistinguishable from a real one to whoever runs 10.1e. Payload now satisfies the gate.
  - `[medium]` `[patch]` The 12.0 floor is calibrated against the **failure** only; no free-RAM
    reading from a healthy run at `video_node` entry has ever been recorded, and
    `--disable-smart-memory` parks weights in system RAM precisely so a working box may sit
    lower than intuition suggests. The config comment now states the false-bail rate is
    unmeasured and names 10.1e as where it would show up. Value unchanged.
  - `[medium]` `[patch]` Untested branches: `ram_total` absent/non-numeric, flags-missing-with-
    unreadable-RAM ordering, and that the probe is actually pointed at `s.comfyui_url`.
  - `[low]` `[patch]` GiB computed (`2**30`), GB printed. Messages now say GiB and the config
    comment records the unit, since that number is the entire content of the setting.
  - `[low]` `[patch]` The rewritten verdict item (b) had dropped the fp8 text encoder from the
    record even though it is still a prerequisite. Restored as an explicit out-of-reach clause.
  - `[low]` `[patch]` `data/comfyui/README.md` declared itself "not a second source of truth"
    and then restated every flag. Softened to "the code table is authoritative; update both".
  - `[low]` `[patch]` The bail rebuilt `dict(cast_cards)` when `remaining` already held it.
  - `[medium]` `[defer]` A `recompose_preflight_failed` row survives a `video` stage retry via
    `merge_warnings`, so a run whose operator fixed ComfyUI and retried still shows the old
    claim. Pre-existing property of the whole `run_warnings` mechanism (13.1), not of this
    change — recorded in `deferred-work.md`.
  - `[medium]` `[reject]` "(b) CLOSED overstates it — the preflight never runs while the flag is
    off." 10.1c's UNBLOCK wording is "*a runtime-prerequisite guard exists*", not "runs in
    production". The guard existing when the flag is flipped is exactly what (b) asked for, and
    AC9 forbids flipping it here.
  - `[low]` `[reject]` Six speculative or out-of-scope edge cases: the warning fires even when
    no shot would have recomposed anyway (the operator still wants to know ComfyUI is
    misconfigured); `comfyui_mock` opens a socket (the recompose path never honoured mock mode —
    pre-existing, and the bail is now the louder outcome); re-check RAM every N shots mid-loop
    (this is a preflight, not a watchdog); negative/absurd `ram_free`; a required flag token
    appearing as another option's *value*; a floor configured above the box's total RAM (the
    message already prints free **and** total).

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

## Auto Run Result

Status: done

**Implemented.** Story 10.1c's unblock condition (b) — "the path needs ComfyUI started with
`--lowvram --disable-smart-memory` and an fp8 text encoder, and **nothing here detects or
enforces that**" — is now closed. `recompose_run_shots` interrogates the **running** server's
`/system_stats` at its one run-level moment, before the first shot, and refuses the whole path
with a named, actionable failure instead of swap-grinding for twelve minutes. The default flag
is untouched: `shot_recompose_enabled` is still `False`, and (a) legibility and (c) the time
budget remain open, which is 10.1e's call.

Three things the story asked for that the investigation answered differently from its premise:

1. **The fp8 text encoder is not a runtime prerequisite the preflight can check.** It is pinned
   in `comfyui_shot_recompose_qwen_api.json`'s `clip` node — a property of the graph file, absent
   from `argv` and from `/system_stats` — and a missing file fails fast at that node with
   ComfyUI's own error. The requirement table records it as deliberately unchecked rather than
   pretending to verify it, which is what Task 1's second bullet asked for.
2. **`--cache-lru` needed a value check, not a presence check.** ComfyUI declares
   `--cache-lru type=int default=0` and enables the LRU cache only `if args.cache_lru > 0`, so
   `--cache-lru 0` would have passed a presence-only gate while delivering the exact 490 s/shot
   eviction the flag is in the table to prevent. Found in review, verified against ComfyUI source.
3. **The restart command could not be a bare `python main.py …`.** This box starts ComfyUI from
   `~/workspaces/ComfyUI/run.sh`, which activates a venv and exports `HSA_OVERRIDE_GFX_VERSION`
   / `PYTORCH_HIP_ALLOC_CONF` first. The message tells the operator to *append* the flags to the
   launcher they already use — AC3 is about an operator who can act on the line, and a command
   that silently drops the RDNA-4 override fails that test.

**Files changed**
- `src/yt_flow/services/recompose_service.py` — `REQUIRED_FLAGS` (the single declaration:
  flag → required value → why), `_flag_value` / `_gb` / `_message` / `_preflight`, and the
  run-level bail that returns the cast map untouched
- `src/yt_flow/pipeline/nodes/video.py` — +34 lines, one hunk: the preflight bail becomes a
  `recompose_preflight_failed` run_warning, and the pre-existing blanket `except` now files one
  too (`reason="resolver_error"`) instead of only logging
- `src/yt_flow/config.py` — `recompose_preflight_min_free_ram_gb` (12.0 GiB, with the honest
  provenance of the number and its unvalidated false-bail rate); verdict item (b) rewritten to
  record what closed it and what stays out of its reach
- `src/yt_flow/domain/state.py` + `src/yt_flow/domain/warnings.py` — the new code and its Korean
  operator copy, both halves, since the import-time guard fails if only one is edited
- `src/yt_flow/services/comfyui_client.py` — `get_system_stats`' docstring, which claimed "not a
  health gate" and "called once per run" and was falsified by this story on both counts
- `tests/services/test_recompose_service.py` — `_StubClient.get_system_stats` + `PASSING_STATS`
  so the 8 pre-existing tests keep passing, plus the preflight matrix
- `tests/pipeline/nodes/test_video_harmonization.py` — three video_node gate tests
- `tests/stubs/fakes.py` — the offline stub's payload now satisfies the gate
- `data/comfyui/README.md` — "How ComfyUI must be started", with the real launcher body
- `_bmad-output/implementation-artifacts/deferred-work.md` — two entries

**Review findings.** Both reviewers ran in parallel. **13 patched (4 high, 5 medium, 4 low),
1 deferred (medium), 7 rejected.** Every high-severity claim was verified against a primary
source before patching, not taken on the reviewer's word: ComfyUI's `comfy/cli_args.py` and
`main.py` for the `--cache-lru 0` hole, this machine's `run.sh` for the restart command, and
`MAX_DETAIL_CHARS` for the truncation. The sharpest finding was that a hard attribute read of
the new setting would raise into `video_node`'s blanket `except`, which logs a WARNING and files
**no** warning — the story reproducing the exact silent skip it exists to end.

**Verification.** `uv run pytest -q -p no:cacheprovider --ignore=e2e` → **1 failed, 3146 passed,
1 skipped** (6:28). The single failure is
`tests/test_render_pose_guides.py::test_render_is_deterministic_and_content_pinned[humanoid_lying_supine]`,
proven pre-existing by stashing all working-tree changes and re-running at `d39037f`
(`1 failed, 14 passed`) — the baseline commit retuned the supine joint table without updating
that test's pinned raster hash. `uv run ruff check src/ tests/` clean. `git diff d39037f --
video.py` is one hunk at 2559, with no change inside `_build_card_chain`, `_apply_placement`,
`ground_y_expr`, `_occlusion_fragment` or `MotionSource`.

**Residual risks.**
1. **The preflight has never run against a live ComfyUI.** ComfyUI was not up during this
   session, so `/system_stats`' real payload shape was taken from the story's 2026-08-15 live
   capture (`system.argv`) and from `_build_provenance`'s existing reader, not re-observed. The
   defensive reads mean an unexpected shape produces a named bail rather than a crash, but
   whether a correctly-started server *passes* is unproven on hardware. First live exercise is
   10.1e.
2. **The 12 GiB floor is calibrated against the failure only.** No free-RAM reading from a
   healthy run at `video_node` entry exists anywhere, and `--disable-smart-memory` parks weights
   in system RAM precisely so a working box may sit lower than intuition suggests. If the floor
   is too high, every run bails — loudly and with the measurement in the message, which is the
   designed behaviour, but it is a false-bail rate nobody has measured. Recorded in the config
   comment; 10.1e is where it shows up.
3. **A busy-but-healthy ComfyUI can be refused.** `check_health`'s own docstring records that
   ComfyUI stops serving `/system_stats` while a prompt runs, so a concurrent A/B run can make
   the 5-second unretried probe answer `None` → `stats_unavailable`. Deliberately not
   compensated with retries or a longer timeout (both are forbidden by the story); the cost is
   one overlay-path run with a visible warning, and the reasoning is now in the docstring.
4. **Nothing in a production run is protected today**, because `shot_recompose_enabled` is
   `False` and `video.py:2558` is the only reader. That is the story's own constraint, not a
   defect — but the incident that motivated it (`e5ed4b3a`) was the *background* path, which
   stays ungated. Recorded in `deferred-work.md`.
5. `tests/test_render_pose_guides.py`'s pinned hash is still stale from `d39037f`. It belongs to
   whoever owns 10.8, is untouched here, and is the repository's only failing test.
