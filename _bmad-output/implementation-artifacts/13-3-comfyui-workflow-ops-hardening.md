---
story_key: 13-3-comfyui-workflow-ops-hardening
story_id: "13.3"
epic: "Epic 13: 품질 관측 & 게이트 성숙"
created: 2026-08-03
source_status_before: backlog
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
baseline_revision: c2f6b2f
review_loop_iteration: 0
final_revision: ea00d72
followup_review_recommended: true
---

# Story 13.3: ComfyUI Workflow Ops Hardening — Node-ID Decoupling + Render Provenance

Status: done

## Story

As Jay,
I want ComfyUI parameter injection to resolve nodes by a stable declared title instead of by JSON node-ID strings, and every render to record what actually produced it (workflow hash, resolved node map, seed, ComfyUI/torch version, custom-node snapshot),
so that editing a workflow in the ComfyUI UI can no longer silently re-target an injection at the wrong node, and a bad batch of renders can be traced back to the exact environment that made it instead of being re-litigated from memory.

## Context

Epic 13's premise: this pipeline's recurring failure mode is **silent success masquerade**. Two of the named symptoms are this story's:

- **Node-ID coupling.** PRD OQ-2 fixed prompt injection at node `"6"` (positive) / `"7"` (negative), and the code implements exactly that. Re-numbering a node — which the ComfyUI UI does routinely on copy/paste or re-export — either writes the prompt into an unrelated node or, at best, trips `_load_workflow`'s class-type assertion. There is no test the *authored* workflow can fail that reveals a re-target.
- **Zero environment observability.** No file in the repo records which ComfyUI core commit or custom-node versions produce renders. Story 8.7 concluded IC-Light nodes were absent, then that conclusion was reversed — that reversal cost exists purely because nothing was recorded.

Current ID coupling, exhaustively (verified in code at the baseline commit):

| Site | Hardcoded IDs | Risk |
|------|---------------|------|
| [image.py:46-47](src/yt_flow/pipeline/nodes/image.py#L46-L47) `POSITIVE_NODE`/`NEGATIVE_NODE` | `"6"`, `"7"` | blind write into `workflow["6"]["inputs"]["text"]` — the live background path, every shot of every run |
| [composite_harmonization.py:167-168](src/yt_flow/pipeline/nodes/composite_harmonization.py#L167-L168) `CARD_IMAGE_NODE`/`BACKGROUND_IMAGE_NODE` | `"1"`, `"2"` | blind write of uploaded filenames; dormant today (workflow lacks `ytflow_verified_iclight`) but wired |
| [seed_location_plates.py:53-56 + ~300-345](scripts/seed_location_plates.py#L53) | `"3"`,`"5"`,`"6"`,`"7"`,`"11"`,`"20"`,`"23"`,`"30"`,`"31"`,`"32"`,`"33"` | worst offender: 11 IDs, and it **rewires graph links** (`["31", 0]`), so a re-number produces a structurally valid but wrong graph |
| [character_image_provider.py:22](src/yt_flow/services/character_image_provider.py#L22) `_NEGATIVE_NODE_IDS = {"7", "37_neg"}` | `"7"` | mild: everything else there is `class_type`-scanned; but if a re-number lands a *positive* encoder on ID `"7"` it is misclassified as negative and skipped |

The fix is cheap because **the committed workflows already carry `_meta.title` on every injection target** — `"Positive Prompt"`, `"Negative Prompt"`, `"Card Image (character sprite to relight) — uploaded per pair"`, etc. What is missing is (a) a canonical, exact-match key convention and (b) a loader that fails loudly when a key does not resolve.

Story 11.1 already established the sidecar as the place per-render facts live (it put `seed` there). This story extends that sidecar with provenance — **without touching the resume comparison**, which is the one place a careless extension breaks 155 cached backgrounds (see Dev Notes trap #1).

`ponytail:` scope is deliberately capped. Not in scope: any change to sampler parameters, prompt text, LoRA stack, or the 8.7 harmonization tier logic; no new dependency; no restore-automation for the snapshot (a committed artifact + documented refresh command is the whole requirement); no manifest for nodes nothing injects into.

## Acceptance Criteria

1. **Canonical title convention + resolver.** A single helper resolves injection targets by exact `_meta.title` match and returns node IDs (link rewiring needs the ID):
   - Lives in [comfyui_client.py](src/yt_flow/services/comfyui_client.py) under a clearly marked non-HTTP section — every caller (image node, harmonization node, plate script) already imports that module, so no new file. [AD-1: it imports nothing new]
   - `resolve_nodes(workflow: dict, keys: Iterable[str]) -> dict[str, str]` maps manifest key → node ID.
   - **Exact match, never substring.** `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` contains both `"Negative Prompt"` and `"Background Inpaint Negative Prompt (entity exclusion)"`; substring matching would resolve two nodes and pick one arbitrarily.
   - Unresolved key → `ValueError` naming the missing key **and listing the titles actually present** in the workflow (an operator hitting this after a UI edit must be able to fix it without reading code).
   - Duplicate title → `ValueError`. Ambiguity is a defect, not a coin flip.
2. **Committed workflows declare the keys.** Every node that code injects into carries `_meta.title` set to exactly `ytflow:<key>` (`ytflow:` prefix signals "code reads this string — renaming it breaks the pipeline"). Prose currently living in those titles (the IC-Light `UNVERIFIED …` notes, the plate anchor/ControlNet rationale) moves verbatim into the workflow's README — **no explanatory text is lost**. Non-injected nodes' titles are untouched.
   Keys, per workflow:
   - `comfyui_sdxl_anime_lora_workflow_api2.json`: `ytflow:positive_prompt`, `ytflow:negative_prompt`
   - `comfyui_location_plate_api.json` (11 keys, one per ID constant at [seed_location_plates.py:51-57](scripts/seed_location_plates.py#L51-L57)): `positive_prompt`, `negative_prompt`, `sampler`, `latent`, `model`, `style_anchor`, `ipadapter`, `structure_hint`, `scribble`, `controlnet_apply`, `controlnet_loader` (all `ytflow:`-prefixed). Note `model` is node `"11"`, the second `LoraLoader` — the t2i-fallback rewiring targets it, and it has no title today.
   - `comfyui_iclight_relight_api.json`: `ytflow:card_image`, `ytflow:background_image`
   - `comfyui_character_multi_angle_api.json`: `ytflow:positive_prompt`, `ytflow:negative_prompt`
3. **`image_node` resolves by title.** `_load_workflow` resolves both prompt keys once at load (eager — AD-10 puts ComfyUI validation at `image_node` entry) and `_inject_prompts` writes to the resolved IDs. `POSITIVE_NODE`/`NEGATIVE_NODE` constants are deleted, not kept as a fallback: a silent ID fallback is exactly the failure being removed. Existing behavior preserved — deep-copy purity, `BG_NEGATIVE_SUFFIX` on the negative, `class_type == "KSampler"` seed injection (already ID-free, leave it).
4. **Harmonization + plate script resolve by title.** `_load_iclight_workflow` / `_inject_relight_inputs` and `seed_location_plates.py` replace their ID constants with resolved IDs, including the link-rewiring paths (`workflow[apply_id]["inputs"]["image"] = [hint_id, 0]`). The IC-Light `ytflow_verified_iclight` gate and its non-fatal-miss contract are unchanged. The plate script's `--blockout` / anchor-batch / t2i-fallback branches behave identically.
5. **Character provider drops its ID set.** `_is_negative_node` prefers an exact `ytflow:negative_prompt` title, then falls back to the existing keyword heuristic; `_NEGATIVE_NODE_IDS` is deleted. The keyword fallback stays — that function also has to cope with foreign workflows and `_default_workflow()`, which are not manifest-bearing.
6. **Environment pin committed.** `data/comfyui/env-snapshot.json` — a ComfyUI-Manager full snapshot (ComfyUI core commit + every custom-node commit + pip freeze) — is committed, alongside `data/comfyui/README.md` documenting the exact refresh command (`python custom_nodes/ComfyUI-Manager/cm-cli.py save-snapshot --output <repo>/data/comfyui/env-snapshot.json --full-snapshot`), when to refresh (any custom-node install/update), and that its sha256 lands in render provenance. Produced on the GPU host; if unreachable during dev, land the README + loader and mark the snapshot as the one live-validation deliverable (AC9).
7. **Render provenance in the sidecar.** `_write_sidecar` gains a `provenance` object recording: `workflow_path`, `workflow_sha256` (canonical `json.dumps(template, sort_keys=True)` of the loaded template, i.e. before per-shot injection — a hash of the submitted graph would differ per shot and be useless for comparison), the resolved `nodes` map from AC1, `env_snapshot_sha256` (`null` if the file is absent), and a `comfyui` block from `GET /system_stats` (`comfyui_version`, `pytorch_version`, device name — whichever keys the server returns). Best-effort: `system_stats` is fetched **once per run**, and any failure logs and records `null` rather than failing the stage [AD-10]. Mock mode (`comfyui_mock`) writes provenance with `workflow_*`/`comfyui` null — the mock path never loads a workflow.
8. **Provenance must not invalidate resume.** `_existing_complete_shot` compares only `image_prompt` / `negative_prompt` / `seed` and keeps doing so. A sidecar whose `provenance` differs (ComfyUI upgraded, snapshot refreshed) is still a valid cache hit. A regression test asserts this explicitly — this is the one change in the story that could silently trigger a 155-shot re-render.
9. **Tests + validation.**
   - Unit: resolver happy path; missing key error message contains the missing key *and* the present titles; duplicate title raises; exact-match-not-substring proven against the layered_inspyrenet title pair; every committed workflow in `data/workflows/` resolves the keys its consumer needs (a data test — this is what would have caught a UI re-export).
   - Unit: provenance fields written; `system_stats` failure yields `null` and does not fail the stage; mock-mode provenance shape; AC8 resume-unaffected test.
   - Existing fixtures updated: `GOOD_WF` in [test_image.py:22](tests/pipeline/nodes/test_image.py#L22) and the IC-Light / plate-script fixtures need `_meta.title` — they are the only ones (`grep -rl CLIPTextEncode tests/` → one file).
   - Full regression suite green (`uv run pytest`), `ruff` clean.
   - Live: one real ComfyUI render on the GPU host proving injection still lands (image visibly matches the prompt) and provenance is populated. **Not runnable on this machine** — no ComfyUI at `$HOME/workspaces/ComfyUI`; record it as the outstanding live gate if deferred, do not claim it passed.

## Premise Corrections (2026-08-14, verified at HEAD c2f6b2f — do not re-measure)

The story was authored 2026-08-03 against baseline `7141707`. The following premises in the
sections above are **stale or wrong** and are superseded here:

1. **AC9's "Not runnable on this machine — no ComfyUI at `$HOME/workspaces/ComfyUI`" is false.**
   `/home/jay/workspaces/ComfyUI` exists, `custom_nodes/ComfyUI-Manager/cm-cli.py` exists, and the
   server answers on `:8188` (`comfyui_version 0.12.3`, `pytorch 2.11.0.dev+rocm7.1`) with an empty
   queue and ~13.5 GB VRAM free. AC6's env snapshot **must be produced on this machine**; the
   "defer to a GPU host" escape hatch is not available. Live render validation is likewise feasible
   — check `/queue` `class_type`s for a foreign workflow before submitting (HTTP 200 ≠ free GPU).
2. **Story 13.1 modified `image.py` and `composite_harmonization.py` today.** Every line number in
   the tables and tasks above is stale. Locate by symbol, never by line.
3. **The AC2 iclight key list is incomplete.** Beyond `CARD_IMAGE_NODE="1"` / `BACKGROUND_IMAGE_NODE="2"`,
   `composite_harmonization.py` also binds `GREY_MATTE_NODE="20"` and `LIGHT_SOURCE_NODE="22"` in
   `_inject_relight_inputs`'s card-size branch. These are **worse** than the other two: they go through
   `workflow.get(node_id)` + an isinstance guard, so a re-number drops card-size conditioning
   **silently, with no exception**. AC2's iclight keys are therefore four:
   `ytflow:card_image`, `ytflow:background_image`, `ytflow:grey_matte`, `ytflow:light_source`.
4. **Node-ID coupling scope is otherwise exactly as the table says** — `image.py`,
   `composite_harmonization.py`, `seed_location_plates.py` and nothing else. The depth /
   shot_recompose / fusion / pose_guide workflows are `class_type`-scanned; leave them.
   The plate script's 11 IDs match the AC2 list exactly (3·5·6·7·11·20·23·30·31·32·33).
5. **`comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` and `..._layered_api.json` are dead**
   (0 hits across `src/` and `scripts/` — Story 8.3 retired layered generation). Keep the
   inspyrenet file as AC1's substring-trap test fixture, but **do not retitle a dead workflow**.
   They are correctly absent from AC2's four.
6. **AC9's "`grep -rl CLIPTextEncode tests/` → one file" is wrong — there are two:**
   `tests/test_workflow_definitions.py` and `tests/pipeline/nodes/test_image.py`.
7. **`_existing_complete_shot` compares exactly three keys** — `image_prompt`,
   `_effective_negative_prompt(negative_prompt)`, and `seed in seeds`. AC8's landmine is putting
   provenance anywhere near those three. Do not.
8. **`data/comfyui/` does not exist; workflow JSON lives in `data/workflows/`** and six config keys
   point there. AC6's `data/comfyui/` path is followed as specified — see the one-line judgement
   recorded in Completion Notes on whether splitting the directory is right.

## Tasks / Subtasks

- [x] **Task 1 — Resolver (AC: 1)**
  - [x] Add `resolve_nodes` + a `MANIFEST_PREFIX = "ytflow:"` note to `comfyui_client.py` under a `# ── Workflow node manifest (no HTTP) ──` banner.
  - [x] Exact match on `node.get("_meta", {}).get("title")`; skip non-dict values while scanning — an API-format workflow may carry top-level non-node keys (`ytflow_verified_iclight: true` is exactly that, once IC-Light is real), and a scan that assumes every value is a node crashes on it.
  - [x] Error messages: `f"workflow node title {key!r} not found; titles present: {sorted(titles)}"` and a duplicate-title variant.
- [x] **Task 2 — Retitle committed workflows (AC: 2)**
  - [x] Set `_meta.title` on each injection target in the four workflows listed in AC2.
  - [x] Move displaced prose into the matching README (`README-iclight-relight.md`, `README-character-multi-angle.md`; create `README-location-plate.md` and note the base workflow in `data/comfyui/README.md` if no home exists). Verify nothing is dropped.
- [x] **Task 3 — `image_node` (AC: 3)**
  - [x] `_load_workflow` → resolve `ytflow:positive_prompt`/`ytflow:negative_prompt`, return `(workflow, node_ids)`; delete the ID-based CLIPTextEncode assertion loop (the resolver supersedes it — keep a `class_type == "CLIPTextEncode"` sanity check on the resolved nodes so a title pasted onto a LoraLoader still fails loudly).
  - [x] Thread the resolved IDs into `_inject_prompts`; delete `POSITIVE_NODE`/`NEGATIVE_NODE`.
  - [x] Update the module docstring — it documents nodes `"6"`/`"7"` as the contract (lines 4-5).
- [x] **Task 4 — Harmonization + plate script (AC: 4)**
  - [x] `composite_harmonization.py`: resolve `ytflow:card_image`/`ytflow:background_image` in `_load_iclight_workflow`, pass IDs to `_inject_relight_inputs`, delete the two constants.
  - [x] `seed_location_plates.py`: replace the 11 ID constants with one `resolve_nodes` call near workflow load; update every `workflow[X]["inputs"]` write **and** every `[X, 0]` link literal.
- [x] **Task 5 — Character provider (AC: 5)**
  - [x] `_is_negative_node`: exact `ytflow:negative_prompt` title first, keyword fallback second, `_NEGATIVE_NODE_IDS` deleted.
- [x] **Task 6 — Environment pin (AC: 6)**
  - [x] Create `data/comfyui/README.md` (refresh command, refresh triggers, provenance link).
  - [x] Add a snapshot-sha256 read helper (best-effort; missing file → `None`).
  - [x] Capture and commit `env-snapshot.json` on the GPU host.
- [x] **Task 7 — Provenance (AC: 7, 8)**
  - [x] Add `get_system_stats(base_url) -> dict | None` to `comfyui_client.py` (`GET /system_stats`, swallow failures). **Do not change `check_health`'s signature** — ~15 test fakes and `seed_location_plates.py` depend on its current `-> None` shape.
  - [x] Fetch once in `image_node` before the shot loop (skip entirely in mock mode); pass into `_write_sidecar`.
  - [x] Extend `_write_sidecar` with the `provenance` object; leave `_existing_complete_shot`'s three compared keys alone.
- [x] **Task 8 — Tests (AC: 9)**
  - [x] Resolver unit tests + the data test over `data/workflows/*.json`.
  - [x] Provenance/mock/failure/resume tests in `test_image.py`.
  - [x] Update `GOOD_WF` and the harmonization/plate fixtures with titles.
  - [x] `uv run pytest` + `ruff check` green; report counts.

## Dev Notes

### Traps (each has already bitten this repo once)

1. **Resume invalidation.** `_existing_complete_shot` ([image.py:189-202](src/yt_flow/pipeline/nodes/image.py#L189-L202)) reads three named keys via `.get()` — it does **not** compare whole dicts, so adding `provenance` is safe *as written*. It stops being safe the moment someone "tidies" that check into a dict equality or adds `provenance` to the comparison: every ComfyUI upgrade would then re-render every background. AC8's test is the guard.
2. **Substring title matching.** Tempting, and wrong: see AC1's layered_inspyrenet example.
3. **`check_health` signature.** Returning stats from it would be the smaller diff but breaks `tests/stubs/fakes.py:50` and every local `async def ok(...) -> None` monkeypatch. Separate function, best-effort.
4. **IC-Light is a placeholder.** `comfyui_iclight_relight_api.json` lacks `ytflow_verified_iclight: true`, so `_load_iclight_workflow` raises and tier-3 relight degrades to a non-fatal cache miss. Retitling and resolving it is a no-op today by design — do not "fix" the verified flag or the placeholder graph here (8.7's territory).
5. **Plate script rewires links, not just inputs.** `workflow[CONTROLNET_APPLY_NODE]["inputs"]["image"] = [BLOCKOUT_NODE, 0]` at [seed_location_plates.py:222](scripts/seed_location_plates.py#L222) and the t2i-fallback rewiring at ~341-343 embed IDs *as values*. Resolved IDs must flow into those literals too, or the graph goes structurally-valid-but-wrong — the exact silent failure this story exists to remove.
6. **Mock mode never loads a workflow** ([image.py:290](src/yt_flow/pipeline/nodes/image.py#L290): `template = None if s.comfyui_mock else ...`). Provenance code must not assume a template exists. Stock-plate hits also write sidecars ([image.py:329](src/yt_flow/pipeline/nodes/image.py#L329)) with no ComfyUI involvement — same nullability.
7. **Two sidecar writers, one shape.** 11.1's lesson: the plate/mock/generation paths all call `_write_sidecar`, and the resume check runs *before* path selection, so all three must produce a comparable sidecar. Provenance differing between paths is fine (AC8); the three compared keys differing is not.

### Files

**UPDATE**
- [src/yt_flow/services/comfyui_client.py](src/yt_flow/services/comfyui_client.py) — 231 lines, HTTP-only today (`check_health` → `GET /system_stats`, `submit_and_fetch`, `upload_image`, bounded `httpx.TransportError` retry). Gains `resolve_nodes` + `get_system_stats`. Preserve: `ComfyUIError` as the single error type, `_request_with_retry` semantics.
- [src/yt_flow/pipeline/nodes/image.py](src/yt_flow/pipeline/nodes/image.py) — 396 lines. Touch `_load_workflow`, `_inject_prompts`, `_write_sidecar`, the docstring, and the pre-loop section of `image_node`. Preserve: the AD-10 outer `except` returning `PipelineState.error` (never raising), `_shot_seed` sha256 determinism, the lazy/periodic health-check + `_wait_for_comfyui_recovery` flow, stock-plate short-circuit, `{**shot, "image_path": ...}` no-mutation returns [AD-4].
- [src/yt_flow/pipeline/nodes/composite_harmonization.py](src/yt_flow/pipeline/nodes/composite_harmonization.py) — 448 lines, tiered (ffmpeg tiers 1-2, IC-Light tier 3 + `RelightCache` keyed by `style_epoch`). Only `_load_iclight_workflow` / `_inject_relight_inputs` / the two constants change.
- [scripts/seed_location_plates.py](scripts/seed_location_plates.py) — 645 lines. Constants at 50-190, injection at ~220-345, blockout hint at ~497. Preserve the 8.17 tuned values (`strength 0.9/end 0.7`, `1344×768`, variant/camera tables) — untouched.
- [src/yt_flow/services/character_image_provider.py](src/yt_flow/services/character_image_provider.py) — 616 lines. Only `_is_negative_node` + the constant. Everything else there is already `class_type`-scanned (`_inject_dimensions`, `_inject_seed`, `_inject_ipadapter_weight`, `_inject_reference_image`, t2i bypass) — leave it; that scan style is correct for foreign workflows.
- `data/workflows/*.json` (4 files) + their READMEs.
- `tests/pipeline/nodes/test_image.py`, `tests/pipeline/nodes/test_composite_harmonization.py`, `tests/test_seed_location_plates.py`, `tests/services/test_comfyui_client.py`.

**NEW**
- `data/comfyui/README.md`, `data/comfyui/env-snapshot.json`.
- Tests as per Task 8 (extend existing files; no new test module needed).

### Conventions

- `snake_case` modules; `YTFLOW_`-prefixed env via Pydantic `BaseSettings` in `config.py` — **no new config field is needed** (snapshot path is a repo constant, not deployment-varying). [Spine §Consistency Conventions]
- AD-1: `services/` must not import `api/` or `pipeline/`. The resolver in `comfyui_client.py` imports only stdlib — safe. Do not put it in `pipeline/` (the plate script and provider would then import upward). Note `seed_location_plates.py:45` already imports `_wait_for_comfyui_recovery` from `pipeline.nodes.image` — a script, not a service; don't extend that pattern.
- AD-10: observability/environment lookups are non-fatal. Provenance and snapshot reads log and continue.
- `ponytail:` comments mark deliberate simplifications (snapshot as committed artifact with no restore automation; keyword fallback retained in the provider).

### Prior art in-repo

- **Title-based resolution already exists** in `character_image_provider._is_negative_node` (title keywords + ID set) — this story generalizes the good half and deletes the ID half. Do not invent a second convention.
- **Class-type resolution already exists** for KSampler seeding (11.1) and every provider injector. Titles are for *interchange* nodes (which prompt is which); class_type is for *uniform* writes (all samplers get the seed). Keep that split; don't convert KSampler seeding to titles.
- **Story 11.1** put `seed` in the sidecar and accepted a one-time cache invalidation for legacy sidecars. This story must **not** repeat that invalidation — provenance is additive-only (AC8).

### External

- ComfyUI-Manager snapshot: `cm-cli.py save-snapshot [--output PATH] [--full-snapshot]`; full snapshot includes ComfyUI core version + pip packages, node-only otherwise. Snapshots normally land in `<user_dir>/default/ComfyUI-Manager/snapshots/`; `--output` redirects into the repo. Restore is deferred-on-restart (writes `startup-scripts/restore-snapshot.json`) — irrelevant here, we only capture. The HTTP snapshot endpoint path has moved between Manager versions; the CLI is the stable interface, so document the CLI. ([Snapshot Management — DeepWiki](https://deepwiki.com/Comfy-Org/ComfyUI-Manager/6.1-snapshot-management), [cm-cli docs](https://github.com/Comfy-Org/ComfyUI-Manager/blob/main/docs/en/cm-cli.md))
- `GET /system_stats` is already this project's health endpoint; its payload carries `system` (ComfyUI/python/pytorch versions) and `devices` (name, VRAM). Read defensively — key sets differ across ComfyUI versions, which is precisely why we record whatever is returned rather than a fixed schema.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 13.3]
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#OQ-2] — the node 6/7 decision being reversed here
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1, #AD-4, #AD-10, #Consistency Conventions]
- [Source: data/workflows/README-iclight-relight.md] — custom-node inventory at `$HOME/workspaces/ComfyUI/custom_nodes/`, the 8.7 IC-Light absence claim
- [Source: CLAUDE.md#Code Philosophy — Ponytail]

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] (Claude Opus 5, 1M context) — BMAD dev-story implementation agent.

### Debug Log References

- Env snapshot capture (AC6), run from ComfyUI's own directory with ComfyUI's own interpreter:
  `cd $HOME/workspaces/ComfyUI && ./venv/bin/python custom_nodes/ComfyUI-Manager/cm-cli.py save-snapshot --output /mnt/work/projects/yt.flow/data/comfyui/env-snapshot.json --full-snapshot`
  → exit 0, `Current snapshot is saved as env-snapshot.json`. The `--help` flags matched the
  story exactly; the only adaptation was the interpreter (the repo's `uv` env has no `typer`).
- Live gate (AC9): [13-3-live-validation/README.md](13-3-live-validation/README.md),
  [run_probe.py](13-3-live-validation/run_probe.py), [make_grid.py](13-3-live-validation/make_grid.py).
  `/queue` was checked empty (`queue_running 0`, `queue_pending 0`) and 13.5 GB VRAM free before submitting.
- Verification: `uv run ruff check src/ scripts/ tests/` → **All checks passed**;
  `PYTHONPATH=$PWD/src uv run pytest tests/` → **2813 passed / 1 skipped** in 352s
  (baseline 2782/1; +31 new tests). No `--cov`.
- Review fix pass (2026-08-14): `uv run ruff check src/ scripts/ tests/` → **All checks
  passed**; `PYTHONPATH=$PWD/src uv run pytest tests/` → **2838 passed / 1 skipped** in
  354s (+25 tests over the implementation pass). No `--cov`.
- Review fix pass, finding 2 proof (ComfyUI live on `127.0.0.1:8188` throughout):
  with `tests/conftest.py` stashed to its pre-fix state and
  `YTFLOW_COMFYUI_URL=http://127.0.0.1:59999`, `tests/pipeline/test_stub_profile_smoke.py`
  logged `ComfyUI /system_stats unavailable, recording null provenance: All connection
  attempts failed` — i.e. it really dialled out, and passed anyway. After the fix the
  same command logs **0** `system_stats` lines, and the run against the live
  `http://127.0.0.1:8188` is green with the seam asserted directly by
  `test_pytest_stub_profile_rebinds_the_same_comfyui_seams`.

### Completion Notes List

1. **AC6 directory judgement (asked for explicitly).** `data/comfyui/` is the right home; the
   snapshot should NOT live in `data/workflows/`. Reason: `data/workflows/` is *input the
   pipeline submits* — six `Settings` fields point into it and its graphs are hand-edited as
   feature work — whereas the snapshot is *a record of the machine*, regenerated by an external
   tool and belonging to no single workflow. There is also a concrete cost to co-locating them:
   `tests/test_workflow_definitions.py` globs `data/workflows/*.json` and asserts graph structure
   on everything it finds, so a snapshot dropped in there would be parsed as a node graph.
   Recorded in `data/comfyui/README.md`.
2. **AC1's no-fallback rule is the whole design.** `resolve_nodes` raises on a missing key
   (naming the key *and* the titles present) and on a duplicate. Exact match only — the
   `layered_inspyrenet` title pair is the shipped counter-example and is used as the test fixture,
   not retitled (it is dead code, Premise Correction 5).
3. **AD-1 conflict the story did not anticipate.** AC1's rationale — "every caller already imports
   `comfyui_client`" — is false for `composite_harmonization.py`, which explicitly does not, and
   `tests/domain/test_state_imports.py` *enforces* pipeline↛services with a legacy allowlist
   documented as "it must not grow". Resolution: the resolver reaches that module through the
   duck-typed client it is already given (`_load_iclight_workflow(path, resolve_nodes)`, called as
   `comfyui_client.resolve_nodes` in `relight_sprite`). No new file, no new allowlist entry, no
   second convention. `image.py` and `seed_location_plates.py` import it directly, as specified.
4. **Premise Correction 3 confirmed and acted on.** The iclight keys are four. `ytflow:grey_matte`
   and `ytflow:light_source` are now resolved *eagerly at load* alongside the two LoadImages, and
   `_inject_relight_inputs` writes them without the old `.get()` + isinstance guard — that guard was
   the silent-drop mechanism, so keeping it would have preserved the defect behind a title.
5. **`_default_workflow()` needed a title, or AC5 would have regressed.** Its node `"7"` was found
   purely by the deleted id set: its *text* is `"bad quality, blurry"` but it has no `_meta.title`,
   so the retained keyword fallback (which reads titles) could not have caught it, and every
   negative suffix on that path would have been dropped with only a log line. Two lines of
   `_meta` fix it; a regression test pins it.
6. **AC8 is tested, and nothing near it was touched.** `_existing_complete_shot` still compares
   exactly `image_prompt` / `_effective_negative_prompt(negative_prompt)` / `seed in seeds`.
   `test_differing_provenance_is_still_a_resume_hit` seeds three sidecars carrying a *different*
   `workflow_sha256`, `env_snapshot_sha256` and ComfyUI version, and asserts `submit_and_fetch`
   is never called.
7. **The required data test** lives in `test_workflow_definitions.py` as `CONSUMER_KEYS`, which
   reads the key tuples from the consumer modules themselves (`image.POSITIVE_KEY`,
   `PLATE_NODE_KEYS`, `ICLIGHT_NODE_KEYS`, `_NEGATIVE_NODE_TITLE`) rather than retyping them, so
   a key added in code with no title in the JSON fails here rather than in a live render.
8. **Live gate passed — AC9's "not runnable on this machine" was wrong (Premise Correction 1).**
   Three renders at one seed through the shipped path: prompt A vs B RMS **72.78** (injection is
   reaching the sampler), A vs a graph with **every node id shifted +700** RMS **0.00** — pixel
   identical. Position-independence is measured, not argued. Provenance was populated live with
   every field non-null.
9. **Known residue, deliberately not fixed.** Five committed live-validation probe scripts under
   `10-2-`, `10-4-` and `10-4b-live-validation/` pin the old `_load_workflow` / `_inject_prompts`
   signatures and will not re-run as written. They are dated records of what was executed, and
   the story's scope is `src/` + `scripts/`; re-running one needs only the tuple return and the
   `nodes` argument. Flagged rather than silently rewritten.
10. `ponytail:` markers left at the deliberate simplifications this story makes: the snapshot as a
    committed artifact with no restore automation and no config field, and the retained keyword
    fallback in the character provider.

#### Review fix pass (2026-08-14) — 17 findings, all fixed

11. **Provenance now differs per writer path, deliberately (HIGH-1).** The stock-plate branch was
    handing `_write_sidecar` the *generation* provenance object, so a plate copied from the library
    weeks ago claimed this run's `workflow_path`/`workflow_sha256` and today's ComfyUI version.
    `image_node` builds a second object, `plate_provenance = _build_provenance(path, None, None, None)`.
    **Judgement asked for:** `workflow_*` **and** the `comfyui` block are null on that path — the
    plate render involved no ComfyUI invocation at all, so recording the live server's version is
    the same lie in a different field. `env_snapshot_sha256` is kept: it is a fact about the
    checkout that wrote the sidecar, not a claim about the render, and mock mode already records it.
12. **The offline stub suites really were hitting a live ComfyUI (HIGH-2).** `get_system_stats` was
    unpatched in both `tests/conftest.py::stub_profile` and `scripts/run_e2e_stub_server.py`, and
    `check_health` was unpatched in the script too. All three are now bound to
    `fakes.fake_get_system_stats` / `fakes.fake_check_health`. The guard is no longer a hand-kept
    list: `test_every_comfyui_network_function_is_classified` asserts the adapter's public async
    surface equals `_COMFYUI_STUBBED | _COMFYUI_UNREACHED`, so a new HTTP function fails a test
    instead of silently becoming a live call, and two more tests assert the script *and* the pytest
    fixture actually rebind every name in that set. Proof of closure in Debug Log References.
13. **`_inject_prompt` prefers the declared positive title (HIGH-3).** No ids reintroduced (AC5):
    an exact `ytflow:positive_prompt` wins, the existing "first non-negative CLIPTextEncode" scan is
    the fallback. `_POSITIVE_NODE_TITLE` is a module constant now, which is what makes
    `CONSUMER_KEYS`' "sourced from the consumers, not retyped" claim true (finding 17). Residual,
    recorded rather than papered over: a graph that declares *neither* title and puts an untitled
    negative encoder first still mis-injects — the old id set happened to backstop exactly that, and
    AC5 forbids restoring it. Every graph this provider loads (shipped multi-angle, pose-guide,
    `_default_workflow`) declares or keyword-matches, and the test says so explicitly.
14. **The provenance probe no longer borrows the health gate's 120 s budget (MED-4).**
    `comfyui_client.STATS_READ_TIMEOUT = 5.0`; the long configurable read timeout exists so a
    *gate* does not read a mid-prompt stall as a crash, which is not this call's job [AD-10].
    Bounded rather than made lazy: laziness would need a mutable holder threaded through the shot
    loop for a value only sidecar writers read. Tested at the client (`STATS_READ_TIMEOUT` is what
    reaches `httpx.Timeout`, and is below `comfyui_health_read_timeout_sec`) and at the node
    (a fully-resumed run pays for stats at most once).
15. **`ENV_SNAPSHOT_PATH` resolves against `YTFLOW_PROJECT_ROOT` (MED-5)** — the same convention
    `character_image_provider._load_workflow` uses, which exists precisely because the app does not
    always run from the repo root — and a miss now logs the path it tried instead of returning
    `None` in silence.
16. **`_is_negative_node` / `_is_guide_node` read titles through `_node_title` (MED-6),** which
    guards `_meta: null` and non-string titles the way `resolve_nodes` does. Coping with foreign
    workflows is that function's entire remaining job.
17. **IC-Light validates all four nodes at load (MED-7).** `class_type` present and `inputs` a dict,
    for card/background/matte/light alike. A titled dict without `class_type` used to pass load and
    raise `KeyError` inside `_inject_relight_inputs` (which rebuilds the graph filtered on
    `class_type`), and `relight_sprite`'s blanket except turned that back into the silent cache miss
    the validation exists to remove — relocated, not eliminated. Non-dict `inputs` now raises the
    named `ValueError` instead of `AttributeError`.
18. **`/system_stats` is read defensively down to each key (MED-8)** — `system` not a dict, `devices`
    not a list, the payload not a dict at all: all produce nulls rather than an `AttributeError`
    that kills the image stage. Parametrized over four malformed shapes.
19. **The five committed probe scripts run again (MED-9).** Two-line signature fix each
    (`template, nodes = _load_workflow(...)`, `nodes` into `_inject_prompts`) in
    `10-2-live-validation/run_probe.py`, `10-4-live-validation/{run_ab,run_ab2,run_merge_probe}.py`,
    `10-4b-live-validation/run_absence_ab.py`. Nothing else in those dated records was touched and
    nothing ignored in them was deleted; each file byte-compiles.
20. **`README-layered-assets.md` says the recipe hard-fails now (MED-10)** and why the dead workflow
    is deliberately not being retitled (Story 8.3 retired it; it is the shipped substring trap the
    resolver test asserts against).
21. **LOW fixes.** `seed_location_plates.py`'s docstring publishes the eleven manifest keys instead
    of the eleven node ids (11). `test_comfyui_client.py` and `test_seed_location_plates.py` anchor
    their file reads on `Path(__file__)` like `test_workflow_definitions.py` does (12).
    `test_check_health_still_returns_none` — a pinned annotation, self-verification — is replaced by
    `test_check_health_returns_nothing_on_success`, which drives a mock 200 and asserts the return
    value the ~15 fakes imitate (13). `MANIFEST_PREFIX` is **deleted** (14): a key that does not
    match a declared title already raises with the titles listed, so a prefix check rejects nothing
    the resolver accepts — the convention survives as the comment on the banner. `_write_sidecar`'s
    `provenance` is required and positional (15) — three writer paths, three different honest
    objects, and 11.1's `seed` is the lesson about a defaulted sidecar field.
22. **The live-validation README said "byte-identical" and the files are not (LOW-16).** A vs C is
    *pixel*-identical (RMS 0.00, which is what RMS measures); the raws differ by 34 bytes,
    and that delta is the PNG `prompt` tEXt chunk — the only artifact proving ComfyUI executed
    nodes `706`/`707`, in a file the directory gitignores. `make_grid.py` now walks that chunk with
    stdlib `struct` and commits the result to `metrics.json` as `submitted_text_encoders`
    (`{"6": ..., "7": ...}` for A, `{"706": ..., "707": ...}` for C) plus `file_bytes`. The verdict
    is carried by committed evidence, as CLAUDE.md requires.

### File List

**Modified — source**
- `src/yt_flow/services/comfyui_client.py` — `resolve_nodes` under a non-HTTP banner; `get_system_stats` (`check_health` untouched). *Fix pass:* `MANIFEST_PREFIX` deleted (unreferenced); `STATS_READ_TIMEOUT` bounds the provenance probe.
- `src/yt_flow/pipeline/nodes/image.py` — `POSITIVE_KEY`/`NEGATIVE_KEY` replace `POSITIVE_NODE`/`NEGATIVE_NODE`; `ENV_SNAPSHOT_PATH`; `_load_workflow` returns `(workflow, nodes)`; `_inject_prompts` takes the map; `_env_snapshot_sha256` + `_build_provenance`; `_write_sidecar` gains `provenance`; module docstring.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — four `*_KEY` constants + `ICLIGHT_NODE_KEYS`; `_load_iclight_workflow(path, resolve_nodes)` returns `(workflow, nodes)` and validates the canvas pair; `_inject_relight_inputs` takes the map; layer-rule docstring.
- `src/yt_flow/services/character_image_provider.py` — `_NEGATIVE_NODE_IDS` deleted, `_NEGATIVE_NODE_TITLE` added; `_is_negative_node(node)` drops the id parameter; `_default_workflow()` nodes 6/7 titled.
- `scripts/seed_location_plates.py` — 11 id constants → 11 manifest keys + `PLATE_NODE_KEYS`; `_load_workflow` returns `(workflow, nodes)`; `nodes` threaded through `_inject`, `_inject_anchors`, `_bypass_scribble`, `_upload_structure_hint`, `_strip_ipadapter`, `seed_plate`, `generate_anchor_candidates`, `run`.

**Modified — data + docs**
- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (2 titles)
- `data/workflows/comfyui_character_multi_angle_api.json` (2 titles)
- `data/workflows/comfyui_location_plate_api.json` (11 titles; 3 nodes had none)
- `data/workflows/comfyui_iclight_relight_api.json` (4 titles)
- `data/workflows/README-iclight-relight.md` — *Manifest titles* section carrying the four displaced titles verbatim; "Changing this file" step 4 rewritten.
- `data/workflows/README-character-multi-angle.md` — *Manifest titles* section.
- `_bmad-output/planning-artifacts/epics.md` — Story 13.3 completion record.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 13-3 entry → `review`.

**New**
- `data/comfyui/env-snapshot.json` — captured live on this host.
- `data/comfyui/README.md` — refresh command, refresh triggers, provenance link, directory judgement.
- `data/workflows/README-location-plate.md` — the six displaced plate titles verbatim + the manifest table.
- `_bmad-output/implementation-artifacts/13-3-live-validation/` — `README.md`, `run_probe.py`, `make_grid.py`, `title_resolution_grid.jpg`, `metrics.json`, `provenance.json`, `.gitignore` (raw renders ignored).

**Modified — tests**
- `tests/services/test_comfyui_client.py` — resolver unit tests (happy path, id-indifference, missing-key message, duplicate, exact-not-substring against the shipped inspyrenet file, non-node scalars) + `get_system_stats` success/failure/transport + `check_health` signature pin.
- `tests/test_workflow_definitions.py` — `CONSUMER_KEYS` data test; api2 and plate tests re-expressed by title.
- `tests/pipeline/nodes/test_image.py` — `GOOD_WF` titled + `GOOD_NODES`; renumber-resolution and wrong-class tests; provenance shape / null snapshot / stats failure / once-per-run / mock-mode; AC8 resume test; `_fake_system_stats` autouse fixture.
- `tests/pipeline/nodes/test_composite_harmonization.py` — `_titled` helper, `shipped_nodes` fixture, four-key manifest test, renamed-node error test, fixtures retitled, fake client carries `resolve_nodes`.
- `tests/test_seed_location_plates.py` — `_nodes` helper, all id constants → resolved ids, renumber + rename tests.
- `tests/services/test_character_service_generation.py` — manifest-title-after-renumber, keyword-fallback-survives, `_default_workflow` negative-suffix tests.

**Review fix pass (2026-08-14) — additionally modified**

*Source*
- `src/yt_flow/pipeline/nodes/image.py` — `plate_provenance` (null `workflow_*`/`comfyui`) on the stock-plate branch; `ENV_SNAPSHOT_PATH` is a repo-relative `str` resolved against `YTFLOW_PROJECT_ROOT`, and `_env_snapshot_sha256` logs its miss; `_build_provenance` reads `/system_stats` defensively per key; `_write_sidecar`'s `provenance` is required and positional.
- `src/yt_flow/services/comfyui_client.py` — see above.
- `src/yt_flow/services/character_image_provider.py` — `_node_title` helper (guards `_meta: null` / non-str title) used by `_is_negative_node` + `_is_guide_node`; `_POSITIVE_NODE_TITLE`; `_inject_prompt` prefers the declared positive title.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — `_load_iclight_workflow` validates `class_type` + dict `inputs` on all four resolved nodes.
- `scripts/seed_location_plates.py` — module docstring publishes the eleven manifest keys, not the eleven node ids.
- `scripts/run_e2e_stub_server.py` — `check_health` + `get_system_stats` rebound to the fakes.

*Data + docs*
- `data/workflows/README-layered-assets.md` — the `.env` recipe now hard-fails; why the dead workflow stays un-retitled.

*Live-validation records (signature fix only, nothing else touched, nothing deleted)*
- `_bmad-output/implementation-artifacts/10-2-live-validation/run_probe.py`
- `_bmad-output/implementation-artifacts/10-4-live-validation/run_ab.py`, `run_ab2.py`, `run_merge_probe.py`
- `_bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py`
- `_bmad-output/implementation-artifacts/13-3-live-validation/make_grid.py` — extracts `submitted_text_encoders` + `file_bytes` from the PNG `prompt` chunk into `metrics.json`; `README.md` — "byte-identical" corrected to pixel-identical, with the committed chunk proof; `metrics.json` — regenerated.

*Tests*
- `tests/conftest.py` — `stub_profile` patches `get_system_stats`.
- `tests/stubs/fakes.py` — `fake_get_system_stats`.
- `tests/test_run_e2e_stub_server.py` — `_COMFYUI_STUBBED`/`_COMFYUI_UNREACHED` classification + three guard tests.
- `tests/pipeline/nodes/test_image.py` — stock-plate provenance, all-resume stats bound, `YTFLOW_PROJECT_ROOT` snapshot resolution + logged miss, malformed-stats shapes.
- `tests/pipeline/nodes/test_composite_harmonization.py` — titled-but-unusable node rejected at load (4 keys × 2 shapes).
- `tests/services/test_character_service_generation.py` — declared positive title outranks file order; title reads survive foreign `_meta` shapes.
- `tests/services/test_comfyui_client.py` — behavioural `check_health` test replaces the annotation pin; `STATS_READ_TIMEOUT` test; repo-anchored workflow path.
- `tests/test_seed_location_plates.py` — `_REPO_ROOT`/`_plate_workflow_path()` anchoring.
- `tests/test_workflow_definitions.py` — `CONSUMER_KEYS`' multi-angle positive row sourced from `character_image_provider._POSITIVE_NODE_TITLE`.

## Review Triage Log

### 2026-08-14 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 3, medium 7, low 7)
- defer: 2: (high 0, medium 1, low 1)
- reject: 2: (high 0, medium 1, low 1)
- addressed_findings:
  - `[high]` `[patch]` Stock-plate sidecars recorded the background workflow's `workflow_path`/`workflow_sha256` and today's ComfyUI version for an image `shutil.copyfile`'d from the plate library weeks earlier — contradicting `_build_provenance`'s own docstring, Dev Notes trap #6, and the epics record. Fixed: a separate `plate_provenance` with `workflow_*` and `comfyui` null; `env_snapshot_sha256` retained (a fact about the checkout that wrote the sidecar, not a claim about the render). Misleading provenance is worse than absent provenance.
  - `[high]` `[patch]` The offline stub suites had begun contacting a live ComfyUI: neither `tests/conftest.py` nor `scripts/run_e2e_stub_server.py` patched `get_system_stats`, and `comfyui_mock` defaults False, so `test_stub_profile_smoke.py` dialled `127.0.0.1:8188` on this box. Fixed both seams (`check_health` was also unpatched in the script), and replaced the hand-kept guard list with `test_every_comfyui_network_function_is_classified`, which asserts the client's public async surface equals `_COMFYUI_STUBBED | _COMFYUI_UNREACHED`. Reproduced before/after against a dead port.
  - `[high]` `[patch]` Deleting `_NEGATIVE_NODE_IDS` opened a new silent mis-injection: the ID set was also `_inject_prompt`'s guard, so for a manifest-less workflow whose untitled negative encoder comes first in file order, the **positive** prompt was written into it. Fixed without reintroducing IDs (AC5) — `_inject_prompt` now prefers an exact `ytflow:positive_prompt`, scan as fallback. Residual recorded: a graph declaring neither title and keyword-matching neither still mis-injects.
  - `[medium]` `[patch]` The unconditional `get_system_stats` defeated Story 5.14's lazy health check and used `comfyui_health_read_timeout_sec` (120 s), so a fully-resumed run behind a busy GPU stalled up to two minutes for observability alone. Bounded with `STATS_READ_TIMEOUT = 5.0`; a timeout records `null` per [AD-10]. Test added for the all-resume case.
  - `[medium]` `[patch]` `ENV_SNAPSHOT_PATH` was CWD-relative and `_env_snapshot_sha256` swallowed `OSError` with no log — the pin silently stopped pinning outside the repo root. Now resolved against `YTFLOW_PROJECT_ROOT` like `character_image_provider._load_workflow`, and the miss logs the path tried.
  - `[medium]` `[patch]` `_is_negative_node` raised `AttributeError` on `_meta: null` and on non-string titles — shapes `resolve_nodes` explicitly guards, in the one function whose remaining job is foreign workflows. New `_node_title` helper, shared with `_is_guide_node`.
  - `[medium]` `[patch]` The IC-Light canvas pair was validated only for `width`/`height` presence, never that the resolved value was a node: a titled dict without `class_type` passed load and raised `KeyError` at inject, which `relight_sprite`'s blanket `except` turned into a non-fatal cache miss — the silent skip relocated, not removed. All four keys now validated at load; non-dict `inputs` raises the named `ValueError` instead of `AttributeError`.
  - `[medium]` `[patch]` `_build_provenance` assumed `/system_stats` returns `system` as a dict and `devices` as a list; an unexpected shape escaped and failed the whole image stage, the opposite of [AD-10] and of the story's own instruction to read that endpoint defensively. Now per-key defensive, parametrized over four malformed payloads.
  - `[medium]` `[patch]` Five committed probe scripts (`10-2-`, `10-4-`, `10-4b-live-validation/`) pinned the old `_load_workflow`/`_inject_prompts` signatures and would not re-run — CLAUDE.md requires those directories to keep every number-re-deriving script runnable. Two-line signature fix in each; nothing else in those dated records touched.
  - `[medium]` `[patch]` `README-layered-assets.md` documents an `.env` recipe pointing `YTFLOW_COMFYUI_WORKFLOW_PATH` at the layered_inspyrenet graph, which carries no `ytflow:` titles and therefore now raises at load. Note added; the dead workflow stays un-retitled (Story 8.3 retired layered generation).
  - `[low]` `[patch]` `seed_location_plates.py`'s module docstring still published the node-ID map as the contract — the most ID-coupled file in the repo documenting the thing this story removed. Now publishes the eleven manifest keys.
  - `[low]` `[patch]` `test_resolve_nodes_matches_exactly_never_by_substring` opened a CWD-relative path and was the one new test failing from another directory; `tests/test_seed_location_plates.py` shared the fragility. Both anchored on `Path(__file__)`.
  - `[low]` `[patch]` `test_check_health_still_returns_none` pinned a return annotation rather than behaviour, while the stated risk is ~15 fakes depending on the actual return (the `gotcha_pinned-ffmpeg-arg-string-is-not-a-test` anti-pattern). Replaced with a test that drives a mock 200 and asserts the value.
  - `[low]` `[patch]` `MANIFEST_PREFIX` had zero references — scaffolding for later, which Ponytail forbids. Deleted; a key not matching a declared title already raises with the titles listed, so a prefix check would reject nothing the resolver accepts. The convention survives as the banner comment.
  - `[low]` `[patch]` `_write_sidecar`'s `provenance: dict | None = None` default was dead flexibility (both call sites pass it) whose only effect was to let a future writer silently omit provenance — the omission Story 11.1 learned about with `seed`. Now required and positional.
  - `[low]` `[patch]` The live-validation README claimed a "byte-identical" render where it meant pixel-identical (the files differ by 34 bytes), and that 34-byte delta — the PNG `prompt` chunk — was the only proof ComfyUI really executed nodes `706`/`707`, sitting in a gitignored raw. Wording corrected and the proof extracted into committed `metrics.json` (`submitted_text_encoders`), so the committed evidence carries the judgement as CLAUDE.md requires.
  - `[low]` `[patch]` `CONSUMER_KEYS`' docstring claimed the table was sourced from consumers, but the multi-angle positive row was a typed literal because the provider resolved no positive key. The finding-3 fix created `_POSITIVE_NODE_TITLE`; the row now sources from it.

## Auto Run Result

Status: done

### Implemented change

ComfyUI parameter injection no longer addresses nodes by JSON ID. `comfyui_client.resolve_nodes` maps a declared `ytflow:<key>` `_meta.title` to a node ID by **exact match with no ID fallback**, raising `ValueError` — with the missing key *and* the full list of titles present — for a miss or a duplicate. Every ID-coupled site is converted: `image.py` (`"6"`/`"7"`), `composite_harmonization.py` (four nodes, not the two the story listed — `grey_matte`/`light_source` went through `workflow.get()` + an isinstance guard and dropped card-size conditioning *without an exception* on a renumber), `seed_location_plates.py` (eleven IDs including three link-rewrite sites), and `character_image_provider.py` (`_NEGATIVE_NODE_IDS` deleted, keyword fallback retained for manifest-less graphs). Each render's `_done.json` gains a `provenance` object (`workflow_path`, pre-injection `workflow_sha256`, resolved `nodes`, `env_snapshot_sha256`, live `comfyui` block); `_existing_complete_shot`'s three compared keys are untouched and a regression test fixes that, so a ComfyUI upgrade cannot trigger a 155-shot re-render.

### Files changed

**Source**
- `src/yt_flow/services/comfyui_client.py` — `resolve_nodes` (exact title match, no fallback, listing errors) + `get_system_stats` (`check_health`'s `-> None` signature untouched) + `STATS_READ_TIMEOUT`.
- `src/yt_flow/pipeline/nodes/image.py` — title resolution at load, `class_type` check moved onto the *resolved* nodes, provenance build/write, project-root-anchored snapshot hash, separate null-workflow provenance for stock plates.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — four IC-Light keys resolved and fully validated at load.
- `src/yt_flow/services/character_image_provider.py` — `_POSITIVE_NODE_TITLE`/`_NEGATIVE_NODE_TITLE` + shape-safe `_node_title`; ID set deleted.
- `scripts/seed_location_plates.py` — eleven manifest keys threaded through every injector and link rewrite; docstring no longer publishes IDs.

**Data / docs**
- 4 workflow JSONs retitled (19 titles); displaced prose moved **verbatim** into `README-iclight-relight.md`, `README-character-multi-angle.md`, and the new `README-location-plate.md`; `README-layered-assets.md` gained the load-failure note.
- `data/comfyui/env-snapshot.json` (real capture) + `data/comfyui/README.md` (refresh command, triggers, provenance link).

**Tests** — resolver units incl. the substring trap proven against the shipped layered_inspyrenet graph; the `CONSUMER_KEYS` data test asserting each committed workflow resolves what its consumer actually reads; provenance/mock/failure/malformed-payload/resume tests; stub-seam classification guard.

**Bookkeeping** — `epics.md` and `sprint-status.yaml`, 13-3 entry only; `deferred-work.md` +2.

### Review findings breakdown

17 patches applied (3 high, 7 medium, 7 low) — see the triage log. 2 deferred (env-snapshot drift undetected; provenance duplicated per shot). 2 rejected: pose-guide "zero manifest coverage" (that path is keyword-scanned, not `resolve_nodes` — nothing to cover, and it degrades gracefully), and a non-dict guard on the plate workflow JSON (the file is committed and covered by the data test).

### Verification

- `uv run ruff check src/ scripts/ tests/` → **All checks passed** (re-run independently after the fix pass).
- `PYTHONPATH=$PWD/src uv run pytest tests/` → **2838 passed, 1 skipped** (baseline 2782/1; +56). Re-run independently after the fix pass.
- Frontend untouched — vitest not run.
- **Live gate PASSED on this machine.** The story's premise that no ComfyUI existed here was false: `/home/jay/workspaces/ComfyUI` is running (`0.12.3`, torch `2.11.0.dev20260206+rocm7.1`, queue verified empty before submission, ~13.5 GB VRAM free). AC6's snapshot was really captured — `cm-cli.py save-snapshot --full-snapshot` via ComfyUI's own venv → core `f350a84`, 9 custom nodes, 179 pips. Three renders at one seed through the shipped code path: prompt A vs B **RMS 72.78** (injection reaches the sampler), A vs a graph with **every node ID shifted +700** → **RMS 0.00, pixel-identical**, with the PNG `prompt` chunk confirming ComfyUI executed nodes `706`/`707`. Position-independence is measured, not argued. Artifacts: `13-3-live-validation/`.

### Residual risks

- `_inject_prompt`'s remaining hole: a foreign workflow declaring neither manifest title and keyword-matching neither can still take the positive prompt into its negative encoder. AC5 forbids the ID backstop that used to cover it; every graph the provider actually loads now declares or keyword-matches.
- Env-snapshot drift is undetected and provenance is duplicated per shot — both deferred with evidence.
- `data/comfyui/` is a second data directory beside `data/workflows/`. Judged correct: `data/workflows/` is pipeline input pointed at by six `Settings` fields, and `test_workflow_definitions.py` globs `*.json` there asserting graph structure, so a snapshot dropped in would be parsed as a node graph.
- AC1's stated rationale ("every caller already imports `comfyui_client`") was wrong about `composite_harmonization.py`, which does not — and `tests/domain/test_state_imports.py` enforces pipeline↛services with an allowlist marked "must not grow". The resolver reaches it through the duck-typed client already injected (`_load_iclight_workflow(path, resolve_nodes)`). No new file, no allowlist growth.
