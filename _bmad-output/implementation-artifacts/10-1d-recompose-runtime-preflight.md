---
story_key: 10-1d-recompose-runtime-preflight
story_id: "10.1d"
epic: "Epic 10: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰"
created: 2026-08-15
source_status_before: backlog
baseline_commit: 4769608b4b1c05b7129ed716f087e22fdcb15495
---

# Story 10.1d: Recompose 런타임 전제 프리플라이트 — 10.1c 해제 조건 (b)

Status: draft

## Story

As Jay,
I want the shot-recompose path to verify at entry that ComfyUI is actually started the way that path requires — and to refuse loudly instead of swap-deadlocking for twelve minutes when it is not,
so that `shot_recompose_enabled` can be turned on without the operator having to remember an undocumented startup incantation, and so the one blocker that is pure code stops holding the whole feature hostage.

## Context

Story 10.1c shipped the recompose path (plate + cards + placement instruction → regenerated shot) and then **deliberately left `shot_recompose_enabled = False`**. The verdict comment at [config.py:293-307](../../src/yt_flow/config.py#L293) names three reasons, of which exactly one is a coding problem:

> (b) the path needs ComfyUI started with `--lowvram --disable-smart-memory` and an fp8 text encoder, and **nothing here detects or enforces that**: on a stock install it swap-deadlocks for ~12 minutes and the try/except fallback never fires

That comment also states the unblock condition:

> UNBLOCK: when 13-2's rebuilt evaluation axes score a paired recompose-on/off set, flip if legibility is neutral-or-better **AND a runtime-prerequisite guard exists**.

13-2 is `done`, so condition (a) is now runnable. **This story closes (b), the other half.** It deliberately does NOT flip the default — that is the sibling story's call, and it needs (a)'s scoring first.

### Why now, and why this is not speculative

The 2026-08-15 E2E run `e5ed4b3a` hit the *same class* of failure on the ordinary background path, which makes the failure mode first-party evidence rather than a remembered warning:

- ComfyUI was started with stock flags. Each background shot took **491 seconds**, of which **11 seconds was sampling** — the remaining 480s was re-uploading a 6.5 GB checkpoint to the GPU because the default `cache-classic` drops it whenever a different graph (depth) runs in between.
- ComfyUI RSS reached **14.0 GB of 31 GB**, with **4 GB swap** in use and 0 free RAM.
- yt.flow could not tell this apart from a crash: `comfyui_health_read_timeout_sec` (120s) and `comfyui_crash_recovery_timeout_sec` (300s) are both **shorter than a single prompt** in that state, so `_wait_for_comfyui_recovery` engaged against a server that was alive and grinding. The stage eventually failed with `ComfyUI produced no image ... within timeout (900 polls)`.
- Diagnosis took roughly 90 minutes and produced two wrong hypotheses (a "deadlock" read off a stale PID; a `--cache-none` attribution disproved by reverting it) before the real cause surfaced. See [gotcha记録](#references).

Recompose is *more* memory-hungry than that path, not less. Without a preflight the operator's first symptom is a run that appears hung.

## Acceptance Criteria

1. **Preflight runs once, at recompose entry, and only when the feature is on.** When `shot_recompose_enabled` is False the check is never performed and costs nothing. Given the feature is on, When the recompose resolver is first invoked in a run, Then the runtime prerequisites are verified exactly once and the result reused for the rest of the run.
2. **The check reads the server, not a config file.** `GET /system_stats` already returns `argv` (verified live: `["main.py", "--preview-method", "auto"]`), which is the authoritative record of how ComfyUI was actually started. Given ComfyUI reports an `argv` lacking a required flag, Then the preflight fails. Do not infer prerequisites from `.env`, from a local `run.sh`, or from the client's own settings — the server may be on another host.
3. **Failure is loud, named, and actionable.** The error names (a) which prerequisite is missing, (b) the observed `argv`, and (c) the exact command to restart ComfyUI with. An operator must be able to fix it without reading code. This mirrors `resolve_nodes`' error contract from Story 13.3 (missing key + the titles actually present).
4. **Failure does not silently degrade to the overlay path.** 10.1c's contract is that a shot the resolver could not recompose keeps its cards and renders through the overlay — that is correct for a *per-shot* failure. A missing runtime prerequisite is a *run-level* misconfiguration, and silently overlaying all 43 shots while the operator believes recompose is on is exactly the "silent success masquerade" Epic 13 exists against. Emit a `run_warning` (Story 13.1's mechanism) so the gate shows it, and record the decision in the trace.
5. **Memory headroom is part of the check, not just flags.** Given available system RAM below a documented threshold at recompose entry, Then the preflight fails with the measured figure. Run `e5ed4b3a` establishes the shape of the number: 14 GB resident + 4 GB swap on a 31 GB box was already fatal for a *lighter* path. `/system_stats` returns `ram_total`/`ram_free`, so this needs no new dependency.
6. **The required-flag list is one declaration, not scattered literals**, and each entry carries the reason it is required. Today the requirement exists only as prose inside a config comment; a future ComfyUI upgrade that renames a flag must have exactly one place to edit.
7. **`--cache-lru` is part of the requirement set.** Not from the 10.1c comment — from run `e5ed4b3a`. yt.flow alternates graphs within a stage (background ↔ depth; recompose adds a third), and ComfyUI's default `cache-classic` evicts the checkpoint on every alternation. Measured: **490s vs 14.8s per shot**, i.e. 4.8 hours vs 15 minutes across 43 shots. This is a prerequisite for the *whole pipeline*, so state explicitly whether the preflight demands it for recompose only or warns pipeline-wide.
8. **Tests.** Unit: each prerequisite missing in isolation produces its own named failure; all present passes; `/system_stats` unreachable or shape-unexpected is non-fatal-but-reported (AD-10), never a crash — see Story 13.3's `_build_provenance` defensive-read tests for the shape to follow. A test asserts the check does not run when the feature is off.
9. **No default flip, no GPU gate.** This story is code-only and must not change `shot_recompose_enabled`. Closing it means condition (b) is satisfied; the sibling scoring story decides the default.

## Tasks / Subtasks

- [ ] **Task 1 — Requirement declaration (AC: 6, 7)**
  - [ ] One module-level table: flag/condition → why required → how observed. Include the 10.1c three (`--lowvram`, `--disable-smart-memory`, fp8 text encoder) plus `--cache-lru` with its measured justification.
  - [ ] Decide and document whether the fp8 encoder is observable from `/system_stats` at all; if it is not, say so in the table rather than pretending to check it.
- [ ] **Task 2 — Preflight (AC: 1, 2, 3, 5)**
  - [ ] Read `argv` + `ram_free`/`ram_total` from `comfyui_client.get_system_stats` (added in 13.3, already best-effort and non-raising).
  - [ ] Once per run, memoised; skipped entirely when the feature is off.
  - [ ] Error message: missing prerequisite, observed `argv`, remediation command.
- [ ] **Task 3 — Surface, don't swallow (AC: 4)**
  - [ ] `run_warning` via `make_warning`; add the code to `RUN_WARNING_CATALOG` with its Korean operator message.
  - [ ] Confirm the gate payload carries it (13.1 wired `run_warnings`; check the UI actually renders a new code before claiming it is visible — the `scenario_quality` channel is *separate* and it is easy to assume the wrong one).
- [ ] **Task 4 — Tests (AC: 8)**
- [ ] **Task 5 — Docs**
  - [ ] `data/comfyui/README.md` (created by 13.3) is the natural home for "how ComfyUI must be started" — it already documents the env-snapshot refresh command. Add the startup requirements there and link the preflight to it.

## Dev Notes

### Traps

1. **`argv` is the only honest source.** ComfyUI may run on another host; `.env`/`run.sh` describe the *operator's intent*, not the running process. Verified live 2026-08-15: `/system_stats` → `system.argv`.
2. **HTTP 200 is not readiness.** Recorded twice in this repo, and re-lived on 2026-08-15: a `curl /system_stats` returning 200 came from an *old process that had not died*, so a restart appeared successful when the new instance had actually exited on a port conflict. Verify the **process**, not the port: `ss -ltnp` for the owner PID, then `/proc/<pid>/cmdline`.
3. **`pkill -f` / `pgrep -f` match your own shell** — recorded in project memory and hit again on 2026-08-15, killing the wrong PID. Take the PID from the listening socket.
4. **Do not "fix" this by widening the timeouts.** `comfyui_health_read_timeout_sec` being shorter than a prompt is a *symptom* of the misconfiguration, not the disease. Widening it hides the 12-minute deadlock instead of refusing it.
5. **`--disable-smart-memory` is not a general-purpose memory fix.** It offloads models to *system RAM*, which is the scarce resource on this box. It is required by the recompose graph specifically; do not generalise it to other paths. (Proposed as a fix on 2026-08-15 for the background path and it was the wrong lever.)

### Files

**UPDATE**
- [src/yt_flow/config.py](../../src/yt_flow/config.py) — the 10.1c verdict comment at ~293-307 should be amended to record that (b) is closed. Do not flip the flag.
- `src/yt_flow/pipeline/nodes/shot_recompose.py` — recompose entry.
- [src/yt_flow/services/comfyui_client.py](../../src/yt_flow/services/comfyui_client.py) — `get_system_stats` exists (13.3); reuse, do not duplicate.
- [src/yt_flow/domain/warnings.py](../../src/yt_flow/domain/warnings.py) — new code in `RUN_WARNING_CATALOG`.
- `data/comfyui/README.md` — startup requirements.

### References

- [Source: src/yt_flow/config.py#L293-307] — the 10.1c verdict and its UNBLOCK condition, verbatim
- [Source: _bmad-output/implementation-artifacts/10-1c-shot-recompose-qwen.md]
- Project memory: `gotcha_comfyui-cache-classic-evicts-on-workflow-alternation` (the 490s→14.8s measurement and diagnosis method), `gotcha_comfyui-and-env-operational`, `gotcha_comfyui-health-200-is-not-a-free-gpu`
- [Source: _bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md] — `run_warnings` mechanism
- [Source: _bmad-output/implementation-artifacts/13-3-comfyui-workflow-ops-hardening.md] — `get_system_stats`, defensive-read tests, error-message contract

## Dev Agent Record
