---
story_key: 13-3-comfyui-workflow-ops-hardening
story_id: "13.3"
epic: "Epic 13: 품질 관측 & 게이트 성숙"
created: 2026-08-03
source_status_before: backlog
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
---

# Story 13.3: ComfyUI Workflow Ops Hardening — Node-ID Decoupling + Render Provenance

Status: ready-for-dev

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

## Tasks / Subtasks

- [ ] **Task 1 — Resolver (AC: 1)**
  - [ ] Add `resolve_nodes` + a `MANIFEST_PREFIX = "ytflow:"` note to `comfyui_client.py` under a `# ── Workflow node manifest (no HTTP) ──` banner.
  - [ ] Exact match on `node.get("_meta", {}).get("title")`; skip non-dict values while scanning — an API-format workflow may carry top-level non-node keys (`ytflow_verified_iclight: true` is exactly that, once IC-Light is real), and a scan that assumes every value is a node crashes on it.
  - [ ] Error messages: `f"workflow node title {key!r} not found; titles present: {sorted(titles)}"` and a duplicate-title variant.
- [ ] **Task 2 — Retitle committed workflows (AC: 2)**
  - [ ] Set `_meta.title` on each injection target in the four workflows listed in AC2.
  - [ ] Move displaced prose into the matching README (`README-iclight-relight.md`, `README-character-multi-angle.md`; create `README-location-plate.md` and note the base workflow in `data/comfyui/README.md` if no home exists). Verify nothing is dropped.
- [ ] **Task 3 — `image_node` (AC: 3)**
  - [ ] `_load_workflow` → resolve `ytflow:positive_prompt`/`ytflow:negative_prompt`, return `(workflow, node_ids)`; delete the ID-based CLIPTextEncode assertion loop (the resolver supersedes it — keep a `class_type == "CLIPTextEncode"` sanity check on the resolved nodes so a title pasted onto a LoraLoader still fails loudly).
  - [ ] Thread the resolved IDs into `_inject_prompts`; delete `POSITIVE_NODE`/`NEGATIVE_NODE`.
  - [ ] Update the module docstring — it documents nodes `"6"`/`"7"` as the contract (lines 4-5).
- [ ] **Task 4 — Harmonization + plate script (AC: 4)**
  - [ ] `composite_harmonization.py`: resolve `ytflow:card_image`/`ytflow:background_image` in `_load_iclight_workflow`, pass IDs to `_inject_relight_inputs`, delete the two constants.
  - [ ] `seed_location_plates.py`: replace the 11 ID constants with one `resolve_nodes` call near workflow load; update every `workflow[X]["inputs"]` write **and** every `[X, 0]` link literal.
- [ ] **Task 5 — Character provider (AC: 5)**
  - [ ] `_is_negative_node`: exact `ytflow:negative_prompt` title first, keyword fallback second, `_NEGATIVE_NODE_IDS` deleted.
- [ ] **Task 6 — Environment pin (AC: 6)**
  - [ ] Create `data/comfyui/README.md` (refresh command, refresh triggers, provenance link).
  - [ ] Add a snapshot-sha256 read helper (best-effort; missing file → `None`).
  - [ ] Capture and commit `env-snapshot.json` on the GPU host.
- [ ] **Task 7 — Provenance (AC: 7, 8)**
  - [ ] Add `get_system_stats(base_url) -> dict | None` to `comfyui_client.py` (`GET /system_stats`, swallow failures). **Do not change `check_health`'s signature** — ~15 test fakes and `seed_location_plates.py` depend on its current `-> None` shape.
  - [ ] Fetch once in `image_node` before the shot loop (skip entirely in mock mode); pass into `_write_sidecar`.
  - [ ] Extend `_write_sidecar` with the `provenance` object; leave `_existing_complete_shot`'s three compared keys alone.
- [ ] **Task 8 — Tests (AC: 9)**
  - [ ] Resolver unit tests + the data test over `data/workflows/*.json`.
  - [ ] Provenance/mock/failure/resume tests in `test_image.py`.
  - [ ] Update `GOOD_WF` and the harmonization/plate fixtures with titles.
  - [ ] `uv run pytest` + `ruff check` green; report counts.

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

### Debug Log References

### Completion Notes List

### File List
