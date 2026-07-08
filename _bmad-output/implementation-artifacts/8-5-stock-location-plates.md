---
created: 2026-07-07
baseline_commit: 840123e
story_key: 8-5-stock-location-plates
story_id: "8.5"
epic: 8
previous_story: 8-4-on-demand-special-pose-cards
depends_on:
  - 8-3-bg-only-generation-multicard-compositing   # iteration 1 A/B results — 착수 전제조건 (epic-level gate)
  - 8-6-asset-library-management                   # 8-5보다 선행 필수 — assets/ root + manifest.json + location_plates table
blocks: []
related:
  - 8-1-shot-cast-metadata-bg-prompts              # visual_breakdown extension point for location_key
  - 8-2-character-card-sprite-pipeline             # shared IPAdapter style anchor
  - 7-2-post-fx-color-grade                        # mood lighting on plates is render-time, not more plate variants
  - 1-6-image-node                                 # image_node STOCK-plate fast path
  - 5-19-ddg-image-search-fallback-repair          # DDG image search for anchor reference sourcing
---

# Story 8.5: Stock Location Plates — Pre-Built Background Set Library

Status: review

## Story

As Jay,
I want a curated library of pre-generated background plates for the 10–15 canonical SCP facility locations (containment chamber, observation room, corridor, interview room, autopsy room, control room, facility exterior, server room, storage vault, medical bay, etc.), each with 2–3 angle/composition variants — all generated under a single curated IPAdapter style anchor and validated through a human curation gate — so that visual_breakdown can select `location_key: "containment-chamber"` and image_node copies the plate file instead of generating one (zero ComfyUI time), delivering scene-to-scene spatial continuity, eliminating background-prompt-compliance risk (deferred-work 2026-07-07 #2), and giving the channel a consistent visual identity across episodes.

## Context

**Context: iteration 1 gate (2026-07-07)** — the epic draft (`epics.md#Epic 8`) gates 8.5 and 8.6 behind "iteration 1(8.3 DoD A/B) 결과 확인 후". The architecture decision is made but both stories wait until Jay has seen an SCP-049 re-render through the new compositing pipeline and confirmed the collage-look risk is manageable. 8.6 (asset library management) must also precede 8.5 — plates need the `assets/` root, the `location_plates` table, and `manifest.json` provenance tracking that 8.6 builds.

**Jay's design (2026-07-07):** the SCP documentary location vocabulary is thick but finite — the same 10–15 room types cover most shots. This is standard practice in animation background art libraries and visual-novel location sets. The plate library mirrors the character card system (8.1–8.4) in symmetry: visual_breakdown emits a closed `location_key` (STOCK location) or a free-text background prompt (entity-specific environment, today's runtime generation). image_node branches: STOCK → copy plate file (generation count zero), otherwise → generate. Mood lighting (cold containment vs warm interview) is handled by 7.2's color grade at render time — NOT by generating more plate variants per mood.

**Style anchor (Jay, 2026-07-07):** one-time human curation — 3–5 reference images selected by Jay (background sourcing has lower copyright burden than character sourcing: general facility photos as style/composition reference, output is generative). These anchor images feed an IPAdapter at low weight for ALL plate generation → the entire plate library shares one art style. The SAME anchor set is shared with 8.2's card generation → card-background style unification, directly mitigating the collage-look risk (deferred 2026-07-07 #1). If style consistency still drifts in v1, the v2 escalation is a style LoRA trained on the plates themselves.

**Lookdev vs production split (Jay, 2026-07-07 — industry-standard protocol, same rule as 8.2 AC14):** during curation, 2–3 representative locations are generated with a frontier image model and compared against local SDXL (manual, file-drop, no integration needed). The winning class either supplies plates directly (frontier wins) or serves as the style anchor for bulk ComfyUI generation (local wins). Decision must be recorded. **Runtime/bulk generation always uses ComfyUI** regardless — cost, horror-content filter safety, and seed reproducibility are non-negotiable.

**Expected effects:**
- **Spatial continuity** — the same containment chamber looks like the same room across shots and scenes (today the same scene's shots generate different rooms — a hidden defect the plate library eliminates structurally).
- **Background prompt compliance** — "dark containment chamber" in a prompt means the plate was curated for that exact room; no more hoping SDXL interprets the words correctly (deferred-work 2026-07-07 #2).
- **Channel identity** — consistent facility aesthetic across episodes.
- **Image stage cost** — free for STOCK shots (majority of runtime), generation budget reserved for unique entity environments.

## Interfaces (Epic 8 contract — Produces)

This story owns the location-plate data contract. Stories that consume it are bound by these rules.

### Domain types — `src/yt_flow/domain/state.py`

```python
# Story 8.5 — closed location key vocabulary
LocationKey = Literal[
    "containment-chamber",   # primary SCP holding cell — cold, concrete, reinforced
    "observation-room",      # scientists viewing through reinforced glass/ monitors
    "corridor",              # facility hallway — dim utilitarian, pipes/ conduits
    "interview-room",        # interrogation / interview — table, two chairs, bare walls
    "autopsy-room",          # medical/ autopsy suite — stainless steel, drain channels
    "control-room",          # monitoring stations, banks of screens, consoles
    "facility-exterior",     # outside the Site — brutalist architecture, fences, night
    "server-room",           # data center rows, blinking lights, climate control
    "storage-vault",         # high-security artifact storage — lockers, cages, dim
    "medical-bay",           # infirmary / treatment room — bed, IV stands, clinical
    "cafeteria",             # mess hall — empty, fluorescent, unsettlingly normal
    "office",                # researcher office / desk work
    "maintenance-tunnel",    # below-grade service access — pipes, steam, grates
    "entrance-checkpoint",   # security screening / airlock entry
]
# ponytail: 14 locations — Jay can prune or add during curation. The vocabulary
# is closed because an LLM emitting unknown keys degrades to free-text prompt,
# which is the existing safe behavior.

# ShotData extension (this story adds one field to the 8.1+8.4 schema):
class ShotData(TypedDict):
    ...existing fields...
    location_key: LocationKey | None   # STOCK location to use instead of image_prompt generation.
                                       # None / missing = use image_prompt (existing behavior).
                                       # Non-None image_node copies the plate file; image_prompt
                                       # is still stored for the gate human to read but ignored
                                       # for generation.
```

### DB model — `location_plates` table (created by 8.6, consumed here)

```python
# src/yt_flow/db/models.py  (story 8.6 owns the table creation; this story consumes it)
class LocationPlate(SQLModel, table=True):
    __tablename__ = "location_plates"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    location_key: str = Field(index=True)          # LocationKey value
    variant: str                                   # "a" | "b" | "c" — angle/composition variant
    file_path: str                                 # assets/locations/{location_key}/{variant}.png
    sha256: str                                    # file integrity hash (matches manifest.json)
    style_epoch: int = 0                           # 8.6 style_epoch — which anchor set generated this
    status: str = "draft"                          # "draft" | "approved" | "retired" (8.6 lifecycle)
    workflow_hash: str | None = None               # ComfyUI workflow hash at generation time
    seed: int | None = None                        # ComfyUI seed for reproducibility
    anchor_set: str | None = None                  # which anchor references were used (e.g. "v1")
    prompt: str | None = None                      # prompt used to generate this plate (for audit)
    created_at: str
    approved_at: str | None = None
```

### Resolution rule — `image_node` branch

image_node, per shot, after 8.3's background-only path is in place:

```python
if shot.get("location_key"):
    plate = location_service.get_approved_plate(shot["location_key"])
    if plate:
        # Pick a variant (round-robin per scene or random from available variants).
        # Copy plate file → workspace/{run_id}/images/scene_{n:03d}_{shot_id}.png
        # Set image_path → generated_count unchanged (this is NOT a generation)
        # Log: "shot S001 using STOCK plate containment-chamber variant b"
    else:
        # No approved plate for this key — degrade to generation path
        logger.warning("location_key %r has no approved plates, falling back to generation",
                       shot["location_key"])
        # Fall through to normal generation path
# else: normal generation path (today's behavior)
```

Variant selection: for determinism within a run, use `hash(f"{run_id}:{scene_num}:{location_key}") % available_variant_count` — same run always picks the same variant for the same scene (spatial continuity), different runs get different variants naturally (run-to-run variety). Jay is not shown variant options; the gate approves plates, not shot assignments.

### visual_breakdown extension

The `visual_breakdown.md` prompt (post-8.1 rewrite) gains a `location_key` field per shot — optional, from the closed `LocationKey` vocabulary. Rules:
- `location_key` emitted when the shot's environment is a standard facility room → image_prompt is still populated (for the gate human) but image_node ignores it for generation.
- `location_key` omitted → image_prompt drives generation (today's behavior, entity-specific environments).
- LLM taught to prefer `location_key` for canonical rooms and omit it only for truly entity-specific environments (inside-entity spaces, anomaly-distorted rooms, dream/hallucination sequences).
- Prompt receives the full `LocationKey` vocabulary as template input (same pattern as 8.1's STOCK_CAST_KEYS).
- Lenient parse: unknown `location_key` → `None` + warning (degrade to generation); non-string → `None`; missing → `None`. Never fail the scenario stage on a location_key taxonomy violation (D1 lesson).

## Acceptance Criteria

1. **LocationKey vocabulary.** Given `src/yt_flow/domain/state.py`, then `LocationKey` exists as a `Literal` with the 14 values listed in Interfaces, and `ShotData` gains `location_key: LocationKey | None`. (The Literal narrows the type for static analysis; at runtime the lenient parse in AC4 is what matters.) `tests/domain/test_state_imports.py` `EXPECTED_FIELDS["ShotData"]` gains `"location_key"` and the drift guard stays green.
2. **Seed script — plate generation.** Given `scripts/seed_location_plates.py`, then it: loads `Settings()` (for ComfyUI URL / workflow path / anchor paths); for each `LocationKey` value and each variant (`a`, `b`, `c` — 3 per key = 42 plates): builds a prompt from a curated `LOCATION_PROMPTS` dict (one descriptive English sentence per location_key, e.g. `"containment-chamber": "A cold concrete containment cell, reinforced walls, dim emergency lighting, heavy blast door, surveillance camera mounted in corner, utilitarian SCP Foundation facility"`), injects into the ComfyUI workflow with IPAdapter style anchor (node injection: positive prompt node 6 + IPAdapter reference image from `data/anchors/locations/` — the anchor images are manually placed there, not downloaded by the script); submits to ComfyUI; saves to `assets/locations/{location_key}/{variant}.png`; and upserts a `LocationPlate` row with `status="draft"`, sha256, seed, workflow_hash. Uses the 5-14 bounded retry pattern (3 attempts, 2s backoff, TransportError only). Mock mode (`YTFLOW_COMFYUI_MOCK=true`): copies a fixture placeholder and still writes the DB row — so tests can verify the full pipeline without a real ComfyUI. Total script is ~200 lines; `# ponytail:` one script, no framework.
3. **IPAdapter style anchor.** Given `data/anchors/locations/` (manually populated — 3–5 reference images selected by Jay per the lookdev gate), then the seed script reads all `*.png`/`*.jpg` files from that directory and passes them as IPAdapter reference inputs to the ComfyUI workflow at a low weight (0.3–0.5, configurable via `YTFLOW_LOCATION_IPADAPTER_WEIGHT` env default 0.4). The ComfyUI workflow (`data/workflows/comfyui_location_plate_api.json`) is a new workflow JSON exported from ComfyUI that includes an IPAdapter node wired to the reference images. No reference → script fails with a clear message (the anchor is load-bearing; without it plates drift into different styles).
4. **Location service.** Given `src/yt_flow/services/location_service.py` (new module), then `LocationService` provides: `get_approved_plate(location_key: str) -> LocationPlate | None` (returns the first approved plate for the key, ordered by variant, or None — a None return means "fall back to generation" in image_node); `get_approved_plates(location_key: str) -> list[LocationPlate]` (all approved variants for round-robin/random selection); `approve_plate(plate_id: str) -> LocationPlate` (curation gate — sets status to "approved", approved_at to now); `reject_plate(plate_id: str) -> LocationPlate` (sets status to "draft" so the seed script can overwrite on re-run); and `list_plates(location_key: str | None = None, status: str | None = None) -> list[LocationPlate]`. Standard service-layer pattern — session injection, no AD-1 violations.
5. **image_node STOCK fast path.** Given `src/yt_flow/pipeline/nodes/image.py` (post-8.3 background-only rewrite), then per shot, before the normal generation path: if `shot.get("location_key")` is truthy, call `location_service.get_approved_plate(location_key)` (injected via the same seam pattern as `inject_angle_selector` — `video.py:38-48` precedent); on hit: variant-select via `hash(f"{run_id}:{scene_num}:{location_key}") % count`, copy the plate file → `workspace/{run_id}/images/scene_{n:03d}_{shot_id}.png`, set `image_path`, `continue` (skip generation for this shot, generation_count not incremented). On miss: `logger.warning` → fall through to normal generation (the plate library is best-effort; a missing plate never fails the stage — AD-10). The plate-copy path runs for mock mode too (mock fixture → copy like today). `_record_trace` gains `stock_plate_count` metadata.
6. **visual_breakdown extension.** Given `prompts/scenario/visual_breakdown.md` (post-8.1 rewrite), then the per-shot output schema gains an optional `location_key` field (from the closed `LocationKey` vocabulary, values listed), the prompt body teaches: "for shots in standard facility rooms, emit `location_key` from the closed vocabulary; `image_prompt` still describes the environment for human review but will not be used for generation; for entity-specific environments (inside-anomaly spaces, distorted rooms, dream sequences) omit `location_key` entirely so `image_prompt` drives generation as before." The pre-output self-check gains "`location_key` values are from the allowed vocabulary or absent; `image_prompt` is always populated" and `LOCATION_KEYS` is passed as a template variable from `visual_breakdown_step` (same pattern as `STOCK_CAST_KEYS` in 8.1). Rollout follows `docs/PROMPT_POLICY.md` exactly as 8.1 AC8 — `candidate` seed via `scripts/migrate_prompts.py`, golden-set gate via `scripts/eval_prompts.py`, promotion is Jay's move. The parser (AC7) must work against both prompt versions.
7. **Lenient parser.** Given 8.1's `build_scenes` (`scenario_chain.py`), then `ShotData` construction gains: `location_key=parse_location_key(raw_shot.get("location_key"))` where `parse_location_key` is a pure function: valid `LocationKey` string → that value; string not in `LocationKey` → `None` + `logger.warning("visual_breakdown emitted unknown location_key %r, falling back to generation", value)`; non-string/None/missing → `None` (no warning — absence is normal). Never raises; never fails the stage; old-prompts without `location_key` work identically. Add to the same test table pattern as `test_parse_cast` (8.1 AC2/AC10).
8. **Gate visibility.** Given the scenario stage artifact endpoint (`run_service.get_stage_artifacts`), then the per-shot serialization includes `"location_key": sh.get("location_key")` (None → `null` in JSON). A human at the scenario gate sees which shots use STOCK plates and can verify the location_key is appropriate before approving. The serializer test asserts this passes through (same D2-prevention pattern as 8.1 AC7 and 8.4 AC9).
9. **Human curation gate (operational, not code).** The seed script produces `status="draft"` plates. Curation is manual: Jay reviews the generated plates (file browser or a future admin UI — not this story's scope), runs `uv run python scripts/approve_location_plate.py --key containment-chamber --variant a` (a thin CLI that calls `LocationService.approve_plate`), and optionally re-runs the seed script for rejected variants (re-running with the same location_key+variant overwrites the draft). Only `status="approved"` plates are used by image_node. This is the same approval pattern as the CC0 audio sourcing precedent (7.1) and the 8.2 card QC gate.
10. **Lookdev decision record.** The seed script logs the decision (`frontier` or `local` + the frontier model used + the 2–3 test location screenshot paths) to `data/anchors/locations/LOOKDEV_DECISION.md` (created manually by Jay during the lookdev gate; the seed script verifies it exists before generating, and fails with a message pointing to it if absent — the decision must be recorded before bulk generation spends GPU hours). This is a process gate, not a code gate — the script reads the file only for the decision key; all other content is free-text documentation.
11. **Config.** Given `src/yt_flow/config.py`, then `Settings` gains: `location_ipadapter_weight: float = 0.4` (used by the seed script and documented in `.env.example`); `location_plate_workflow_path: str = "data/workflows/comfyui_location_plate_api.json"` (path to the IPAdapter-equipped workflow); and `location_anchor_dir: str = "data/anchors/locations"`. No runtime flags — the plate fast path is always enabled when plates exist (the existence check is the toggle; Ponytail: dead flexibility avoided).
12. **Tests.** Given automated verification: `test_location_key_parse` table tests (valid keys, invalid key → None + warning, missing → None, non-string → None); `LocationService` unit tests (get_approved_plate returns approved only, approve/reject lifecycle, list filtering); `test_image.py` plate fast-path tests (STOCK hit → copy + skip generation count, STOCK miss → fall through to generation, mock-mode copy); `test_scenario_chain.py` `build_scenes` + parser tests; `test_state_imports.py` drift guard updated; `test_config.py` new fields present; stub-profile smoke and e2e-stub tests pass unmodified (location_key absent in stubs → normal generation path). `uv run pytest tests/domain tests/pipeline/nodes/test_image.py tests/services/test_location_service.py tests/pipeline/nodes/test_scenario_chain.py -q`, then full `uv run pytest -q` green. Seed script tested via mock mode: `YTFLOW_COMFYUI_MOCK=true uv run python scripts/seed_location_plates.py` → 42 rows + 42 fixture-copy files.
13. **Plate validation.** The seed script, after each ComfyUI render, validates: file exists, size > 1KB, is a valid PNG, and dimensions match the workflow's expected output (read from the workflow JSON's SaveImage node or a config constant — `LOCATION_PLATE_WIDTH=1920`, `LOCATION_PLATE_HEIGHT=1080` as module constants in the seed script). A failed validation logs the error and continues to the next plate (non-fatal per plate; the operator re-runs for failed ones). This is batch-job resilience, not pipeline resilience — the run won't exist yet.

## Tasks / Subtasks

- [x] Task 1 — Domain types + drift guard (AC: 1)
  - [x] Add `LocationKey` Literal (14 values per Interfaces) and `location_key: LocationKey | None` to `ShotData` in `src/yt_flow/domain/state.py` (near `CastPose`, before `CastMember`). Pure stdlib typing.
  - [x] Update `tests/domain/test_state_imports.py` `EXPECTED_FIELDS["ShotData"]` and the Literal-names list.
- [x] Task 2 — Location service (AC: 4)
  - [x] Create `src/yt_flow/services/location_service.py` with `LocationService` class per AC4. Uses the 8.6 `LocationPlate` model (import from `db.models` — the table exists from 8.6). Pure service-layer pattern: session injection, no AD-1 violations.
  - [x] Wire into `api/main.py` lifespan for the image_node injection seam (same pattern as `inject_angle_selector` and 8.3's `inject_cast_resolver`).
- [x] Task 3 — ComfyUI workflow (AC: 3)
  - [x] Export `data/workflows/comfyui_location_plate_api.json` from ComfyUI: SDXL + IPAdapter (reference → CLIP vision → IPAdapter apply, weight ~0.4) + standard positive/negative CLIPTextEncode nodes 6/7 + SaveImage. Canvas 1920×1080. The workflow must accept: positive prompt injection at node 6, negative at node 7, IPAdapter reference image path(s). Document the node IDs in a comment at the top of the seed script.
- [x] Task 4 — Seed script (AC: 2, 3, 13)
  - [x] Create `scripts/seed_location_plates.py` per AC2. `LOCATION_PROMPTS` dict built into the script (one sentence per key — these are curated by Jay during lookdev, the script ships with sensible defaults). Mock mode support per AC13. Non-fatal per-plate loop (error on one plate doesn't stop the batch). Uses the 5-14 bounded retry for ComfyUI calls.
  - [x] IPAdapter anchor loading: reads `data/anchors/locations/*.png` / `*.jpg`, passes all to the workflow. No anchor files → `sys.exit("No anchor images found in data/anchors/locations/ — run the lookdev gate first (see LOOKDEV_DECISION.md)")`.
  - [x] Lookdev decision gate: checks for `data/anchors/locations/LOOKDEV_DECISION.md` existence; if absent, prints instructions and exits. Does not parse the markdown beyond checking the file exists.
- [x] Task 5 — CURATION CLI (AC: 9)
  - [x] Create `scripts/approve_location_plate.py`: `--key <location_key> --variant <a|b|c>` → calls `LocationService.approve_plate` on the matching draft row. Prints before/after state. Thin CLI — argparse + service call only.
  - [x] (Optional, Ponytail-gated) `scripts/reject_location_plate.py` — evaluated and skipped: AC9's re-run-the-seed-script flow already overwrites a draft cleanly (verified live), so a paired reject CLI would be unused code. `LocationService.reject_plate` exists for a future curation UI if one is ever built.
- [x] Task 6 — image_node fast path (AC: 5)
  - [x] Add `_location_service` injection seam to `image.py` (match video.py:38-48 pattern exactly).
  - [x] Per-shot, before generation: `location_key` truthy → `get_approved_plate` → on hit: variant-select → copy → `continue`. On miss: warning → fall through. Mock mode: same copy path with fixture.
  - [x] Wire injection in `api/main.py` lifespan.
  - [x] `_record_trace` gains `stock_plate_count`.
- [x] Task 7 — visual_breakdown prompt (AC: 6, 8)
  - [x] Add `location_key` to the per-shot output schema in `prompts/scenario/visual_breakdown.md` (post-8.1 rewrite). Add the location_key teaching section per AC6. Pass `LOCATION_KEYS` as template variable from `visual_breakdown_step` (`scenario_chain.py`).
  - [x] Add `"location_key": sh.get("location_key")` to the scenario artifact serializer (`run_service.py`) — same line as 8.1 AC7. Extend the serializer test.
  - [x] Prompt rollout per PROMPT_POLICY: repo file edited → `candidate` seed via `scripts/migrate_prompts.py --label candidate --source prompts` (done, confirmed "created: scenario/visual_breakdown"). Golden-set gate + promotion left to Jay's move, per the story's own framing and precedent (5.17/6.1 prompt rollouts).
- [x] Task 8 — Parser (AC: 7)
  - [x] Add `parse_location_key(raw: object) -> LocationKey | None` to `scenario_chain.py` per AC7. Wire into `build_scenes` `ShotData(...)` construction.
  - [x] Table-driven unit tests in `test_scenario_chain.py`.
- [x] Task 9 — Config (AC: 11)
  - [x] Add `location_ipadapter_weight`, `location_plate_workflow_path`, `location_anchor_dir` to `config.py` Settings class.
  - [x] Add corresponding lines to `.env.example`.
- [x] Task 10 — Tests + regression (AC: 12)
  - [x] Per AC12: `test_location_key_parse`, `test_location_service.py`, `test_image.py` plate fast-path, `test_scenario_chain.py` build_scenes+parser, `test_state_imports.py`, `test_config.py`.
  - [x] Mock-mode seed script test: `YTFLOW_COMFYUI_MOCK=true uv run python scripts/seed_location_plates.py` → verified 42 rows + 42 files (live-ran in an isolated tmp DB/assets root).
  - [x] Confirm stub-profile smoke and e2e-stub API tests pass unmodified.
  - [x] Full suite: `uv run pytest -q` green (1013 passed, 1 skipped).

## Dev Notes

### Why plates aren't mood-colored

7.2 (`color_grade.py`) applies mood-driven color grading (eq + vignette + noise) at render time per scene. Generating plates per mood (cold containment, warm interview, clinical autopsy) would multiply the library 3–5× for nothing — the grade handles atmosphere variance identically to how it handles generated backgrounds today. The plate is the room's *structure*; the grade is the room's *lighting*. Same plate, different mood grade = different feel. `# ponytail:`

### Why 3 variants per location, not 2 and not 4

Two variants risk back-to-back shots using the same angle (the Ken Burns zoom/pan provides motion variety but the static composition is visibly identical). Four variants is +33% generation cost with diminishing variety returns — three hits the sweet spot where round-robin across a typical 3–5 shot scene never repeats. The variant hash (`run_id + scene_num + location_key`) ensures different runs get different starting variants without any state-tracking machinery.

### Why the seed script is a script, not a pipeline node

Plate generation is a one-time (per style_epoch) curation batch, not per-run. It runs once when Jay sets up the library and again only when the style anchor changes (8.6 style_epoch bump). Making it a pipeline node would mean every run checks for plates it will never need to generate. A script with mock-mode support is testable and auditable without entangling it in the LangGraph state machine. `# ponytail:`

### The IPAdapter weight tuning

The 0.4 default is a starting point from SDXL community practice for "style reference without content leakage." The actual weight will be tuned during the lookdev gate (Task 3 of the pre-dev manual steps). If the anchor images bleed content (a specific chair from a reference photo appears in every room), lower the weight. If the style isn't holding (rooms look like different buildings), raise it. The config field exists so tuning doesn't require a code change.

### Current Code State — files to read before editing

- `src/yt_flow/domain/state.py` — `ShotData` TypedDict (post-8.1: has `cast`, post-8.3: `background_path`/`character_path` removed); `SceneState`; module header AD-1/AD-2 rules.
- `src/yt_flow/pipeline/nodes/image.py` — post-8.3 background-only path; the injection seam pattern to copy (from `video.py:38-48`); `_record_trace`; mock path.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `visual_breakdown_step` (prompt variable dict), `build_scenes` `ShotData(...)` construction (post-8.1 cast kwarg).
- `src/yt_flow/pipeline/nodes/video.py:38-48` — the injection seam pattern (`_angle_selector` / `inject_angle_selector`). Copy this structure verbatim for `_location_service` / `inject_location_service`.
- `src/yt_flow/services/run_service.py:83-100` — scenario artifact serializer (where `location_key` must appear).
- `src/yt_flow/api/main.py:14,33,35` — injection wiring site.
- `src/yt_flow/config.py` — Settings class, character settings block (~73-88) as placement precedent.
- `src/yt_flow/db/models.py` — `LocationPlate` table (created by 8.6; this story imports and queries it). Check that 8.6 has landed before writing queries against it.
- `src/yt_flow/services/character_service.py` — service-layer pattern reference (session injection, DB queries via SQLModel).
- `src/yt_flow/services/comfyui_client.py` — `submit_and_fetch` / `submit_and_fetch_outputs` signatures for the seed script.
- `prompts/scenario/visual_breakdown.md` — post-8.1 rewrite; the output schema and self-check sections to extend.
- `scripts/seed_character_prompts.py` — seed script pattern reference (CLI structure, Settings() usage, mock mode).
- `tests/pipeline/nodes/test_image.py` — existing test structure + mock fixture paths.
- `tests/domain/test_state_imports.py` — drift guard.
- `tests/stubs/fakes.py` — stub fixtures that may need `location_key=None` additions.

### Preserved behavior (do not break)

- **No plates = today's behavior:** when no location plates exist or none are approved, every shot falls through to generation — byte-identical to post-8.3 behavior.
- **Old checkpoints:** pre-8.5 checkpoints without `location_key` → `None` → generation path. No resume breakage.
- **Mock mode:** `YTFLOW_COMFYUI_MOCK=true` image_node still copies fixture per shot; plate-copy path copies fixture too.
- **A/B pairs:** variant-A and variant-B runs get different plate variants naturally (different `run_id` in the hash) but the same spatial continuity guarantee within each run.
- **Prompt variants:** the `location_key` prompt extension is in `visual_breakdown.md` — follows the same `candidate`→`production` rollout as all other prompt changes. Existing `production` prompt continues to work (no `location_key` emitted → generation path).

### Architecture compliance

- AD-1: `LocationKey` in `domain/`; `LocationService` in `services/`; injection seam in `pipeline/nodes/image.py` uses the same pattern as `video.py`'s `inject_angle_selector`. No new cross-layer imports.
- AD-2: `location_key` is a plain string-or-None in checkpoint state — JSON-serializable, no DB references in state.
- AD-4: image_node returns state updates only; location_service lives behind the injection seam.
- AD-10: plate lookup failure → warning + generation fallback (non-fatal). Only ComfyUI errors on the generation path fail the stage.

### Testing standards

- Pure-function tests for `parse_location_key` (table-driven, `test_scenario_chain.py` convention).
- Service tests with fake DB session (SQLite in-memory, `tests/services/` convention).
- image_node tests via `fake_run_ffmpeg`/mock ComfyUI (existing `test_image.py` convention).
- Seed script test: mock mode end-to-end (`YTFLOW_COMFYUI_MOCK=true`).
- No real ComfyUI in unit tests.

### Ponytail note

Fourteen string constants, one optional TypedDict field, one service class (~60 lines), one injection seam (copy-paste from video.py), one `if` branch in image_node, one parser function (~10 lines), one prompt section, one seed script (~200 lines), one CLI (~30 lines). No new pipeline node, no new LangGraph state branch, no per-run configuration (dead flexibility avoided), no plate quality scoring/judging LLM, no automatic variant selection UX (Jay doesn't pick variants — the hash does), no WebUI for curation (CLI only — the 3.7 character management precedent was a full SPA feature; plate curation is one-time with 42 items, not worth a UI). The ComfyUI workflow is the only new asset file. `# ponytail:` mark every deliberate simplification.

## Project Structure Notes

- New: `src/yt_flow/services/location_service.py`, `scripts/seed_location_plates.py`, `scripts/approve_location_plate.py`, `data/workflows/comfyui_location_plate_api.json`, `data/anchors/locations/` (directory + `.gitkeep` for anchor images, `.gitignore` for generated `.png` files — the seed script writes into `assets/locations/` per 8.6 layout).
- Modified: `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/services/run_service.py` (serializer line), `src/yt_flow/api/main.py`, `src/yt_flow/config.py`, `.env.example`, `prompts/scenario/visual_breakdown.md`, tests (`test_state_imports.py`, `test_scenario_chain.py`, `test_image.py`, `test_config.py`, `fakes.py`), plus new test files (`test_location_service.py`).
- Dependency sequencing: 8.3 must be done (iteration 1 A/B results); 8.6 must be done (assets/ root + `location_plates` table + manifest.json). The `LocationPlate` model import and the `assets/locations/` write path assume 8.6 has landed.
- Concurrent-edit hazard: `state.py`, `scenario_chain.py`, `image.py`, `run_service.py`, and `api/main.py` are shared hot files with 8.1/8.3/8.4 — coordinate or rebase (memory: repeated sprint-status collisions).

## References

- `_bmad-output/planning-artifacts/epics.md#Story 8.5` — epic draft (Jay design: location vocabulary, IPAdapter anchor, lookdev split, 8.6 prerequisite).
- `_bmad-output/implementation-artifacts/8-1-shot-cast-metadata-bg-prompts.md#Interfaces` — CastMember schema + parser pattern to mirror.
- `_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md` — post-rewrite image_node structure (background-only generation path — the code surface this story extends).
- `_bmad-output/implementation-artifacts/8-6-asset-library-management.md` — `LocationPlate` table, `assets/` root, `manifest.json` — this story consumes all three.
- `src/yt_flow/pipeline/nodes/video.py:38-48` — injection seam pattern (`inject_angle_selector` → `inject_location_service`).
- `src/yt_flow/pipeline/nodes/color_grade.py` — 7.2 mood grading (why plates don't need mood variants).
- `_bmad-output/implementation-artifacts/7-1-sound-design.md` — CC0 asset sourcing + curation gate precedent.
- `docs/PROMPT_POLICY.md` — prompt change protocol (AC6 rollout).
- `src/yt_flow/services/character_service.py` — service-layer pattern for LocationService.
- `scripts/seed_character_prompts.py` — seed script pattern.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5 (bmad-dev-story)

### Debug Log References

- `PYTHONPATH=$PWD/src uv run pytest -q` → 1013 passed, 1 skipped, 212.81s.
- `uv run ruff check` on every touched file → all clean.
- `YTFLOW_COMFYUI_MOCK=true uv run python scripts/seed_location_plates.py` against an isolated tmp DB/assets root → 42 rows, 42 files, 42 manifest entries; re-run for one draft overwrote cleanly (no unique-constraint violation); re-run after approving skipped without `--force`, regenerated with `--force`.
- `uv run python scripts/migrate_prompts.py --label candidate --source prompts` → `created: scenario/visual_breakdown` (candidate seeded to Langfuse; reachability confirmed against `langfuse.eli.kr`).

### Completion Notes List

- **Interfaces/actual-schema deviation.** The story's Interfaces section speculatively described a `LocationPlate` table with `file_path`, `sha256`, `workflow_hash`, `seed`, `anchor_set`, `prompt`, `approved_at`. Story 8.6 (landed since) actually shipped a leaner table — `id`, `location_key`, `variant`, `image_path`, `status`, `style_epoch`, `created_at` — with `sha256`/provenance living in `AssetService`'s `manifest.json` instead (same pattern as `CharacterCard`). `LocationService` and the seed script were built against the real 8.6 schema, not the speculative Interfaces one. Seeds/renders still record a per-plate seed for ComfyUI reproducibility, but it isn't persisted anywhere (no column, no manifest kwarg support in 8.6's `add_location_plate`) — out of scope to extend 8.6's already-closed `AssetService` for this.
- **Seed-script upsert logic.** `AssetService.add_location_plate` always inserts a fresh row, which would violate the `(location_key, variant)` unique constraint on re-run. The seed script handles this itself: looks up an existing row first, skips if `status="approved"` (unless `--force`), otherwise deletes it before regenerating — this is what makes AC9's "re-running overwrites the draft" true in practice.
- **Multi-anchor IPAdapter wiring.** ComfyUI's `LoadImage` loads one file; 3–5 curated anchors are combined into one batched IMAGE tensor via chained `ImageBatch` nodes, injected dynamically per anchor count rather than baked into the static workflow JSON (`_inject_anchors` in the seed script).
- **Task 5's optional reject CLI was not created** — AC9's re-seed flow already covers rejection (verified live); `LocationService.reject_plate` exists in case a future curation UI needs it.
- **Prompt rollout stopped at candidate seeding** — the golden-set A/B gate and `production` label promotion are Jay's move per the story's own text and precedent (5.17/6.1).
- **Concurrent-edit note:** another session was actively modifying `sprint-status.yaml`, `scripts/eval_prompts.py`, `tests/test_eval_prompts.py`, `.gitignore`, and `8-4a-special-pose-prompt-gate-decomposition.md` during this session (Story 8.4a). None of those files were touched here; only this story's own `sprint-status.yaml` entry was updated.

### File List

- `src/yt_flow/domain/state.py` — `LocationKey` Literal + `LOCATION_KEYS`, `ShotData.location_key`
- `src/yt_flow/services/location_service.py` — new: `LocationService`
- `src/yt_flow/pipeline/nodes/image.py` — `_location_service`/`inject_location_service` seam, STOCK fast path, `stock_plate_count` trace metadata
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `parse_location_key`, `location_key` wired into `build_scenes`, `location_keys` template variable
- `src/yt_flow/services/run_service.py` — scenario artifact serializer gains `location_key`
- `src/yt_flow/api/main.py` — `inject_location_service` wiring
- `src/yt_flow/config.py` — `location_ipadapter_weight`, `location_plate_workflow_path`, `location_anchor_dir`
- `.env.example` — matching env var documentation
- `prompts/scenario/visual_breakdown.md` — `location_key` output field + teaching section + self-check line
- `data/workflows/comfyui_location_plate_api.json` — new: IPAdapter-equipped location plate workflow
- `data/anchors/locations/.gitkeep`, `data/anchors/locations/.gitignore` — new: anchor image directory (binaries gitignored)
- `scripts/seed_location_plates.py` — new: plate generation seed script
- `scripts/approve_location_plate.py` — new: curation CLI
- `tests/domain/test_state_imports.py` — `location_key` drift guard + `image.py` AD-1 injection allowlist
- `tests/services/test_location_service.py` — new: `LocationService` unit tests
- `tests/pipeline/nodes/test_image.py` — STOCK fast-path tests
- `tests/pipeline/nodes/test_scenario_chain.py` — `parse_location_key` + `build_scenes` location_key tests
- `tests/api/test_stage_artifacts.py` — scenario artifact `location_key` serializer tests
- `tests/test_config.py` — location plate config defaults test

## Change Log

- 2026-07-07: Story created from Epic 8. Owning the location-plate domain contract (`LocationKey` vocabulary, `location_key` on `ShotData`, `LocationService`, `LocationPlate` consumption from 8.6), the IPAdapter style-anchor seed pipeline, the image_node STOCK fast-path, and the visual_breakdown prompt extension. Gated behind 8.3 iteration 1 A/B + 8.6 prerequisite per epic draft. Lookdev/production split per Jay's 2026-07-07 industry-standard protocol.
- 2026-07-09: Implemented all 13 ACs. Adapted `LocationService`/seed script to 8.6's actual (leaner) `LocationPlate` schema rather than the story's speculative Interfaces draft (see Completion Notes). Candidate prompt seeded to Langfuse; golden-set gate + promotion deferred to Jay. Full suite green (1013 passed, 1 skipped), ruff clean. Status → review.

## Saved Questions / Clarifications

1. **LocationKey vocabulary finalization.** The 14 keys are a starting set. Jay will likely prune or add during the lookdev gate when he sees which rooms his SCP scenarios actually use. The Literal is not a runtime constraint — `parse_location_key` degrades unknown values to `None` — so this can iterate without code changes. Consider a follow-up story to trim unused keys after 3–5 real episodes.
2. **Plate resolution granularity.** A scene has N shots, all with the same `location_key` (e.g. "containment-chamber"). Variant selection is deterministic per-shot, so a 3-shot scene gets variants a, b, c. If the scene has 4+ shots, variant a repeats — the Ken Burns zoom/pan provides motion variety, but the background composition is identical. Acceptable for v1; if it bothers Jay, increase variants per location to 4 or add a `variant` hint to `ShotData` (scope creep — new story).
3. **IPAdapter reference count.** 3–5 anchor images is the target. ComfyUI's IPAdapter implementation may have a maximum reference count — verify during workflow export (Task 3) and cap accordingly in the seed script.
4. **Frontier model vs local — who runs the lookdev?** The epic says frontier model for lookdev, ComfyUI for bulk. But the seed script only drives ComfyUI. The frontier lookdev pass is manual (Jay generates 2–3 plates on a frontier service, saves the images, compares, decides, records in `LOOKDEV_DECISION.md`). The seed script only verifies the decision file exists — it does not call frontier APIs. If Jay wants automated frontier lookdev, that's a separate story.
5. **Plate approval UX.** Currently CLI-only (`scripts/approve_location_plate.py`). If Jay wants a browser-based curation view (thumbnail grid, click to approve/reject), that's a frontend story — the `LocationService` CRUD already supports it, and the `GET /location-plates` API endpoint would be trivial. Deferred until the CLI flow actually hurts.
6. **Plate regeneration after style_epoch bump.** When 8.6's `style_epoch` increments (new anchor set), all plates need regeneration. The seed script is re-runnable and `status="approved"` plates from the old epoch are preserved (8.6 rule: old epochs stay for past episodes). New runs pick up the new epoch's approved plates via `LocationService.get_approved_plate` (which filters by `status="approved"` — the new epoch's drafts aren't visible until approved, and old epoch's approved plates stay queryable for old episodes). The script overwrites `status="draft"` rows for the new epoch; it never touches `approved` rows. This means Jay must manually retire old plates after approving the new epoch's — or 8.6's lifecycle management covers this. Clarify with 8.6's dev.
