---
created: 2026-07-05
baseline_commit: c1e94d1
story_key: 5-10-entity-reference-pipeline-repair
story_id: "5.10"
epic: 5
previous_story: 5-9-transition-audio-continuity
depends_on:
  - 5-8-automatic-entity-reference-generation
  - 1-11-character-domain-reference-search
  - 1-12-multi-angle-character-generation
---

# Story 5.10: 엔티티 레퍼런스 파이프라인 복구 (SCP 위키 우선 fetch + 캐릭터 워크플로우 저작)

Status: ready-for-dev

## Story

As Jay,
I want the two real blockers found during Story 5.8's live validation fixed — DuckDuckGo's search endpoint returning 403, and the character multi-angle generation workflow file being missing/invalid,
so that Story 5.8's automatic entity-reference provisioning can actually succeed end-to-end instead of always falling through to its non-fatal fallback.

## Context

Story 5.8 wired `_ensure_character_reference()` into `run_service.start_run` (already merged, `src/yt_flow/services/run_service.py:366-427`) so every run auto-provisions a search-informed, multi-angle character reference before the graph starts. Its own live validation (2026-07-04, run `29447904-3556-4bb2-a296-c46c1190fc18`) proved the wiring and the non-fatal fallback both work correctly — but could not prove the **optimistic happy path** (search hits → real angle-selected image ends up as `character_path`) because two pre-existing, out-of-scope blockers fired:

1. **`DuckDuckGoImageSearch.search()`** (`src/yt_flow/services/image_search.py`) hits DuckDuckGo's unofficial scraped `i.js` endpoint, which returned a reproducible `403 Forbidden` for every real query in this environment (confirmed by a direct, isolated re-test outside the app).
2. **`Settings.character_comfyui_workflow_path`** (`src/yt_flow/config.py:69`) defaults to `data/workflows/comfyui_character_multi_angle_api.json`, which **does not exist on disk** — only the three layered/background workflow JSONs from Stories 1.6b/5.2/5.6/5.7 exist in `data/workflows/`. `ComfyUICharacterProvider._load_workflow()`'s own fallback-to-default-path check also misses, so it falls through to `_default_workflow()` (a built-in minimal SDXL workflow) — the real local ComfyUI server rejects this with `prompt_outputs_failed_validation`. Story 1.12's multi-angle character generation has therefore **never been exercised successfully against a real ComfyUI server**.

Both blockers sit entirely inside code Stories 1.11/1.12 own; Story 5.8's own wiring and non-fatal contract are correct and must not be touched or re-litigated here (see `_bmad-output/implementation-artifacts/5-8-automatic-entity-reference-generation.md`'s Dev Agent Record and Saved Questions for the full evidence trail — this story exists because that file recommended exactly this follow-up).

## Acceptance Criteria

**Blocker 1 — SCP Wiki official image as primary reference source**

1. **Given** a `scp_id` (e.g. `SCP-096`), **when** reference image lookup runs for a character with no existing references, **then** the system first attempts to fetch the SCP Wiki's official page image at a URL deterministically derived from `scp_id` (e.g. `https://scp-wiki.wikidot.com/scp-096` — lowercase, hyphenated slug), before attempting the DuckDuckGo image search fallback.
2. **Given** the wiki page has no usable image (404, no image element found, or the page structure doesn't match), **when** reference lookup runs, **then** it falls back to today's `DuckDuckGoImageSearch.search()` behavior unchanged — DuckDuckGo image search is demoted to fallback, not removed.
3. **Given** a wiki-sourced image is downloaded, **when** the `ReferenceImage` record is persisted, **then** CC BY-SA source-attribution metadata (at minimum the wiki page URL) is preserved so provenance is traceable later — do not silently discard it.
4. **Given** the existing SSRF/content-type/size safety checks in `CharacterService._download_reference_image` (private-IP blocking, no-redirect-follow, content-type allowlist, 10 MB max), **when** downloading from the wiki, **then** the same checks apply — reuse the existing download path, do not build a second unguarded HTTP client.

**Blocker 2 — Real, valid character multi-angle ComfyUI workflow**

5. **Given** `Settings.character_comfyui_workflow_path`'s default value, **when** `ComfyUICharacterProvider._load_workflow()` loads it, **then** the file exists on disk at `data/workflows/comfyui_character_multi_angle_api.json` and is a valid ComfyUI API-format workflow.
6. **Given** the new workflow file, **when** compared to the already-validated layered SDXL workflows, **then** it reuses the same checkpoint/LoRA node structure (`AnimagineXL_v31.safetensors` + `horror.safetensors` + `darkness_xl_v2.safetensors`) rather than inventing a new model stack — consistent with how Story 5.7 derived its inpaint fix from the existing baseline workflow instead of starting over.
7. **Given** a reference image path, **when** `generate()` is called for i2i, **then** the workflow conditions generation on the reference via IPAdapter (the already-installed `ComfyUI_IPAdapter_plus` custom node + `ip-adapter-plus_sdxl_vit-h.safetensors` + `clip_vision_vit_h.safetensors`, confirmed present in the local ComfyUI install), not a raw VAEEncode-based img2img denoise.
8. **Given** each of the 4 canonical angles (`front`, `back`, `side`, `three_quarter`), **when** the workflow is submitted to the real local ComfyUI instance with that angle's prompt injected, **then** it completes successfully and produces an image — no `prompt_outputs_failed_validation`, for all 4 angles.
9. **Given** `character_image_provider.py`'s existing t2i fallback path (`_remove_i2i_input`, used when i2i submission raises), **when** the workflow shape changes to IPAdapter conditioning, **then** the fallback logic is re-verified (or reworked) to actually produce a valid t2i graph for the new node shape — do not assume the existing latent-reconnection logic is still correct for an IPAdapter workflow (see Dev Notes: it may not be — IPAdapter conditions the model/cross-attention, not the sampler's starting latent, so "removing i2i" for this workflow shape more likely means bypassing the `IPAdapter` node's output rather than reconnecting `KSampler.latent_image`).

**DoD — Story 5.8's optimistic path, live re-validated**

10. **Given** a fresh `scp_id` with no existing `CharacterModel` row, **when** a real run starts end-to-end, **then** `_ensure_character_reference` succeeds via the real wiki-fetch-or-DDG-fallback path AND the real ComfyUI multi-angle generation, and at least one entity-visible shot's `character_path` resolves to a real angle-selected reference-grounded image — not a same-frame segmentation cutout.
11. **Given** Story 5.8's existing contracts, **when** this story's changes land, **then** they must not be broken: the failure-rollback behavior (`delete_character` on total provisioning failure), the concurrent-run dedup guard (unique constraint race handling), and the `select_character_angles` tri-state contract (`None`/`{}`/`dict`) all continue to behave exactly as Story 5.8 left them.

## Tasks / Subtasks

- [ ] **Task 1 — SCP Wiki fetch (AC: 1-4)**
  - [ ] Add a wiki-image fetch path. Suggested seam: a new method on `ImageSearch`/a small helper in `image_search.py` (e.g. `ScpWikiImageFetch`) that derives the page URL from `scp_id` (`scp-{number}` lowercase slug — confirm exact wikidot slug convention against a real page before hardcoding, e.g. hyphenation/padding for `SCP-096` vs `SCP-3007`), fetches the page HTML, and extracts the main article image URL.
  - [ ] Wire it as the **first** attempt in `CharacterService._do_search_and_download` (or a new caller), falling back to the existing `DuckDuckGoImageSearch` call unchanged on any failure (no image found, fetch error, parse error).
  - [ ] Reuse `CharacterService._download_reference_image` for the actual download (already has SSRF/content-type/size checks) — do not write a second download path.
  - [ ] Persist attribution: extend how `ReferenceImage` records the source (check `db/models.py::ReferenceImage` for whether a new field is warranted vs. reusing the existing `url` field for provenance — prefer the smaller change).
  - [ ] Write unit tests mocking the wiki HTTP fetch (same `httpx.MockTransport` pattern as `tests/services/test_image_search.py`), covering: wiki hit, wiki miss → DDG fallback, wiki fetch error → DDG fallback.
- [ ] **Task 2 — Author + validate the character multi-angle workflow (AC: 5-9)**
  - [ ] Start from `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`'s generation branch (checkpoint `4` → LoRAs `10`/`11` → `CLIPTextEncode` `6`/`7` → `KSampler` `3` → `VAEDecode` `8`) — reuse the model stack, don't reinvent it.
  - [ ] Add an IPAdapter conditioning chain: `LoadImage` (reference) → `IPAdapterUnifiedLoader` → `IPAdapter` (apply) feeding the model into `KSampler`. `IPAdapterUnifiedLoader` auto-resolves the clip vision + ipadapter model files already on disk (`models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors`, `models/clip_vision/clip_vision_vit_h.safetensors`) — confirm the preset name it needs against the installed node's actual signature before hardcoding.
  - [ ] Single output: one `SaveImage` node (unlike the layered workflow's two branches — this workflow only needs one character portrait per angle, no background/inpaint pass).
  - [ ] Update `character_image_provider.py` if the new node shape breaks any assumption: `_inject_reference_image` (finds `LoadImage` nodes, sets `.inputs.image`) should still work unchanged since IPAdapter also needs a `LoadImage` node for the reference. `_remove_i2i_input`'s t2i fallback (currently reconnects `KSampler.latent_image` to `EmptyLatentImage`) is the one to scrutinize — verify whether it's a no-op with this workflow shape (latent_image may already point at `EmptyLatentImage` since IPAdapter doesn't touch the latent) and, if so, rework the fallback to instead bypass the `IPAdapter` node (reconnect `KSampler.model` to the LoRA/checkpoint output directly).
  - [ ] Validate directly against ComfyUI (same procedure as `data/workflows/README-layered-assets.md`'s "Direct ComfyUI validation procedure" section): submit the workflow JSON to `POST /prompt`, poll `/history/{prompt_id}`, confirm output for all 4 angle prompts, no `node_errors`.
  - [ ] Update `data/workflows/README-layered-assets.md` (or add a sibling `README-character-multi-angle.md`) documenting the new workflow file, its node IDs, required models, and the IPAdapter install/model paths — follow the existing README's documentation style (node ID table, `.env` vars, validation procedure).
- [ ] **Task 3 — Live end-to-end re-validation (AC: 10-11)**
  - [ ] Start a real run for a fresh `scp_id` (no existing `CharacterModel`) with both fixes in place.
  - [ ] Confirm in logs/DB: wiki fetch attempted first; a real reference image downloaded; all 4 angles generated via the new workflow without falling to `_default_workflow()`; `character_path` for at least one shot resolves to the angle-selected reference image.
  - [ ] Run the full regression suite Story 5.8 used as its gate: `uv run pytest tests/services/test_run_service_character_provisioning.py tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/pipeline/nodes/test_image.py tests/services/test_run_service_gate.py tests/services/test_run_service_resume.py tests/pipeline/test_stub_profile_smoke.py -q` plus the new tests from Tasks 1-2 — full suite must stay green.
  - [ ] Record the run ID and outcome in Dev Agent Record.

## Dev Notes

### Critical Implementation Guardrails

- **Do not touch `run_service._ensure_character_reference`'s control flow, rollback, or dedup logic** (`src/yt_flow/services/run_service.py:366-427`) — Story 5.8's code review already hardened this against three real failure modes (settings-init ordering, permanent-failure poisoning, concurrent-creation race). This story only needs its two callees (`search_references` → this story's wiki-first change, `generate_candidates_from_reference` → this story's workflow change) to actually succeed more often; the orchestration around them is out of scope and already correct.
- **`select_character_angles`'s tri-state contract is load-bearing** (`character_service.py:795-830`; consumed at `video.py:618-650`) — `None` = no character, `{}` = character exists but no shots need one, `dict` = selections. Nothing in this story should change that contract; the new workflow just needs to make the `dict` branch (with real, non-fallback angles) actually reachable in practice.
- **`CANONICAL_ANGLES` / `_ANGLE_DESCRIPTIONS`** (`character_service.py:48-55`) are the single source of truth for angle names — do not introduce a second list.
- The wiki fetch is new code, not a reuse of anything already in yt.flow — grep confirms nothing in `src/yt_flow` currently fetches from `scp-wiki.wikidot.com`; `scp_text` today is supplied by the caller (`api/routes/runs.py` resolves it from `app.state.scps`, a preloaded list), not scraped at runtime. Model the new fetch after `DuckDuckGoImageSearch`'s existing `httpx.AsyncClient` pattern (timeout, user-agent, `follow_redirects` posture) for consistency, not a new HTTP style.
- yt.pipe (the Go predecessor, `/mnt/work/projects/yt.pipe`) references `https://scp-wiki.wikidot.com/%s` and test fixtures use `https://scp-wiki.net/scp-173` — confirm the live, current canonical domain/slug format against a real page fetch before hardcoding (both `scp-wiki.wikidot.com` and `scp-wiki.net` appear to resolve to the same site; pick one and verify redirects don't get blocked by `follow_redirects=False` if you reuse `CharacterService._download_reference_image`'s no-redirect posture for the page fetch itself — the page HTML fetch and the image download are two different requests with potentially different redirect needs).
- **IPAdapter is already installed locally** — `~/workspaces/ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/` exists with `models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors` and `models/clip_vision/clip_vision_vit_h.safetensors` already downloaded. No new installation step is needed before live validation, unlike Story 5.6's InSPyReNet which required a fresh git-clone install.
- Node class names available in the installed `ComfyUI_IPAdapter_plus`: `IPAdapterUnifiedLoader` (simplest loader — resolves clip vision + ipadapter checkpoint from a preset name), `IPAdapter` (the basic apply node: `model + ipadapter + image + weight → model`). Prefer these two over the lower-level `CLIPVisionLoader`/`IPAdapterModelLoader`/`IPAdapterAdvanced` combination unless the simple pair proves insufficient for angle-consistent generation quality.
- `submit_and_fetch` (`comfyui_client.py:21-36`) returns the **first output image's bytes** — this workflow needs exactly one `SaveImage` node (no layered background/character split like the 5.2/5.6/5.7 workflows), so no `submit_and_fetch_outputs`/node-ID-keyed variant is needed here.

### Current Code State — Files To Read Before Editing

- `src/yt_flow/services/image_search.py` — `ImageSearch` ABC + `DuckDuckGoImageSearch` (VQD token + `i.js` scrape, currently 403 in this environment). This story adds a wiki-fetch path that runs *before* this, not a replacement — `DuckDuckGoImageSearch` stays as the fallback implementation, untouched.
- `src/yt_flow/services/character_service.py` — `_do_search_and_download` (lines 292-326, the internal search+download orchestrator called by both `search_references` and `research_references`) is the natural insertion point for "try wiki first, fall back to `self._image_search.search(...)`". `_download_reference_image` (lines 328-380) already has the safety checks to reuse for the wiki image download.
- `src/yt_flow/services/character_image_provider.py` — `ComfyUICharacterProvider._load_workflow`/`_inject_prompt`/`_inject_dimensions`/`_inject_reference_image`/`_remove_i2i_input`/`_default_workflow` (lines 112-234). `_load_workflow`'s fallback-path check (`Path("data/workflows/comfyui_character_multi_angle_api.json")`, line 117) becomes correct once Task 2's file exists — but confirm it isn't shadowed by a stale relative-path assumption (this fallback path is relative to CWD, not project root, unlike other code in this file that uses `YTFLOW_PROJECT_ROOT`; verify this doesn't silently miss when the app runs from a different CWD).
- `src/yt_flow/config.py:69` — `character_comfyui_workflow_path` default. No config change needed; the file just needs to exist at the path already configured.
- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` and its README (`data/workflows/README-layered-assets.md`) — the template to derive Task 2's workflow from, and the documentation style to match.
- `_bmad-output/implementation-artifacts/5-8-automatic-entity-reference-generation.md` — full Dev Agent Record + Saved Questions documenting exactly why this story exists; read before starting.

### Architecture Compliance

- AD-1 (`services/` imports `domain`/`db`, never `pipeline`/`api`) — both `image_search.py` and `character_service.py` are already `services/`-layer files; the wiki fetch stays there too, no new cross-layer import.
- AD-10 (non-fatal auxiliary failures / operational envelope) — the wiki-fetch-fails-fall-back-to-DDG behavior (AC2) and the overall "entity reference provisioning must not fail the run" contract from Story 5.8 both fall under this — a wiki fetch error must degrade gracefully at every level (wiki→DDG, and the whole provisioning→run-continues from 5.8), never raise into `run_service.start_run`.
- No new pipeline stage, no new LangGraph node — this story only touches `services/` and a workflow JSON asset, consistent with Story 5.8's AC6 constraint (which still applies transitively, since this story doesn't reopen the trigger-point decision).

### Testing Requirements

- Follow `tests/services/test_image_search.py`'s `httpx.MockTransport` pattern for the new wiki-fetch tests — no real network calls.
- Follow `tests/stubs/fakes.py`'s `patch_character_reference_seams()` pattern if any shared test fixture needs updating for the new wiki-fetch seam (check whether `_do_search_and_download`'s new wiki-first branch needs its own fake wired into `stub_profile`/`test_run_service_gate.py`/`test_run_service_resume.py` the same way Story 5.8 had to wire three fakes into those three places).
- **Known trap, not this story's to fix but avoid stepping in it**: `tests/services/test_character_service_generation.py` constructs `Settings()` without `workspace_path` in several tests (lines ~283-303) and writes real files into the repo's `./workspace/` — don't copy this pattern into any new test; always pass `workspace_path=str(tmp_path)`.
- A real live ComfyUI validation is required (Task 2 + Task 3) — this cannot be fully proven by mocked unit tests, matching Story 5.8's own precedent of a mandatory live-validation task.

## Project Structure Notes

- Expected modified/new files:
  - `src/yt_flow/services/image_search.py` or `src/yt_flow/services/character_service.py` (wiki fetch — exact file depends on Task 1's seam design)
  - `data/workflows/comfyui_character_multi_angle_api.json` (new)
  - `src/yt_flow/services/character_image_provider.py` (only if the IPAdapter workflow shape requires fallback-logic changes, per AC9)
  - `data/workflows/README-layered-assets.md` or a new sibling README documenting the character workflow
  - Corresponding test files under `tests/services/`
- No `db/models.py` schema change expected unless Task 1's attribution persistence (AC3) needs a new field — prefer reusing `ReferenceImage.url` if it's sufficient.

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Story 5.10`
- Direct predecessor: `_bmad-output/implementation-artifacts/5-8-automatic-entity-reference-generation.md` (Dev Agent Record + Saved Questions — this story's whole reason for existing)
- Related: `1-11-character-domain-reference-search.md`, `1-12-multi-angle-character-generation.md`, `5-6-character-cutout-quality.md` (precedent for swapping/validating a ComfyUI custom node), `5-7-layered-background-double-exposure-fix.md` (precedent for deriving a modified workflow JSON from a validated baseline + live-validating against real ComfyUI)
- Workflow template + validation procedure: `data/workflows/README-layered-assets.md`
- Architecture: AD-1, AD-10 — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- yt.pipe (Go predecessor) SCP wiki references: `/mnt/work/projects/yt.pipe/internal/service/assembler.go` (CC BY-SA notice template, wiki URL format), `/mnt/work/projects/yt.pipe/internal/workspace/scp_data_test.go` (fixture URL format)
- Local ComfyUI environment (memory: `reference_comfyui_local`): `~/workspaces/ComfyUI/`, custom nodes confirmed installed: `ComfyUI_IPAdapter_plus`, `ComfyUI-Inspyrenet-Rembg`, `rembg-comfyui-node`; models confirmed present: `models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors`, `models/clip_vision/clip_vision_vit_h.safetensors`

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-05: Story created via create-story workflow, from Story 5.8's Saved Questions follow-up recommendation. Root cause for both blockers pre-confirmed via Story 5.8's live validation (DuckDuckGo 403, missing/invalid character workflow file) — this story's job is fixing both, not re-diagnosing.
