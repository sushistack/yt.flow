---
created: 2026-07-07
baseline_commit: 840123e
story_key: 8-6-asset-library-management
story_id: "8.6"
epic: 8
previous_story: 8-4-on-demand-special-pose-cards
depends_on:
  - 8-2-character-card-sprite-pipeline   # CharacterCard model + get_card/save_card; assets/ is the card home after migration
  - 8-5-stock-location-plates            # 8-6 must PRECEDE 8-5 (epic requirement); 8-5's LocationPlate model lives here so 8-5 starts clean
blocks:
  - 8-5-stock-location-plates            # location_plates table + assets/locations/ directory defined here, consumed by 8-5
related:
  - 5-8 / 5-10                           # _ensure_character_reference writes under workspace/; migration rewires to assets/
  - 3-7-character-management-ui          # character panel loads card images; paths update on migration
---

# Story 8.6: Asset Library Management — Registry, Provenance, Versioning

Status: ready-for-dev

## Story

As Jay,
I want reusable pipeline assets (character cards, location plates, look-dev anchors) stored in a dedicated `assets/` directory with a JSON manifest recording provenance and SHA-256 integrity, a `style_epoch` integer for co-versioning related assets, and a draft→approved→retired lifecycle enforced at the service layer,
so that the library is auditable through git (manifest is committed, binaries are gitignored), past-episode assets are never silently mutated by regeneration (style_epoch), and test workspace pollution from library artifacts is structurally impossible.

## Context

**Context: Jay 지시(2026-07-07), epic draft.** 재사용 자산(캐릭터 카드, 로케이션 플레이트, 룩뎁 앵커)의 체계적 관리가 필요하다. 현재 카드가 run 스크래치 영역(`workspace/`)에 살아 라이브러리와 일회성 산출물이 섞여 있고, 테스트의 workspace 오염 전례(5-8/5-10 session, `workspace_path=str(tmp_path)` 규칙)가 있다. 이 스토리는 Epic 8의 인프라 기반: 8-2의 카드를 `workspace/` → `assets/`로 이주하고, 8-5 플레이트가 처음부터 올바른 경로에서 시작하도록 보장한다. 8-5보다 선행 필수, 8-2/8-3과는 독립(병렬 가능).

**Design decisions embedded in this story (Jay, 2026-07-07):**
- `assets/` 루트는 `workspace/`와 분리 — gitignore 바이너리, `manifest.json`만 커밋
- `style_epoch` 정수: 스타일 앵커 세트 변경 시 +1, 새 epoch 생성, 옛 epoch 보존(과거 에피소드 자산 소급 변경 방지)
- 수명주기: draft → approved(큐레이션 게이트; 파이프라인은 approved만 사용) → retired
- 전역 재사용 불변식: 라이브러리 자산 키는 run/에피소드가 아닌 자산 정체성(`card_key`, `location_key`) — 캐릭터 카드는 연관 에피소드 재등장 시 자동 재사용, `STOCK-*` 고정 출연진 카드는 무조건 전 에피소드 공유, 어떤 run 종료·정리 루틴도 라이브러리 자산을 삭제할 수 없음

## Interfaces (Epic 8 contract — Produces)

This section is the single normative definition for the asset library system. 8-2's cards migrate here; 8-5's plates are created here.

### Directory layout

```
assets/
├── characters/{card_key}/{pose}_{angle}.png   # e.g. assets/characters/SCP-049/standing_front.png
├── locations/{location_key}/{variant}.png     # e.g. assets/locations/isolation-cell/wide.png  (8-5)
├── anchors/                                    # look-dev style anchor images (human-curated)
└── manifest.json                               # committed to git — the audit trail
```

`assets/` root is configurable via `YTFLOW_ASSETS_PATH` (default: `./assets`). All sub-paths relative to that root. `manifest.json` lives at the root, not in a subdirectory — it describes ALL assets so it must be at the top.

### `manifest.json` schema

```json
{
  "style_epoch": 1,
  "assets": {
    "{asset_key}": {
      "path": "characters/SCP-049/standing_front.png",
      "sha256": "abc123...",
      "source": {
        "type": "comfyui_generation | anchor_reference | manual_import",
        "workflow_hash": "sha256_of_workflow_json",    // comfyui_generation only
        "seed": 42,                                      // comfyui_generation only
        "ipadapter_weight": 0.65,                        // comfyui_generation only
        "anchor_ref": "anchors/style-v1-01.png",         // anchor_reference only
        "frontier_model": null                           // manual_import: which frontier model produced this
      },
      "card_key": "SCP-049",        // for characters
      "pose": "standing",            // for characters
      "angle": "front",              // for characters
      "location_key": null,          // for location plates (8-5)
      "variant": null,               // for location plates (8-5)
      "created_at": "2026-07-07T12:00:00Z",
      "approved_at": "2026-07-07T13:00:00Z",
      "status": "approved"
    }
  }
}
```

**Key rules:**
1. `asset_key` is deterministic: characters = `"{card_key}/{pose}_{angle}"`, locations = `"{location_key}/{variant}"`, anchors = `"anchors/{filename}"`. The key is a stable path segment — it does NOT encode `style_epoch`. Epoch changes change the `path` (new subdirectory or epoch suffix), not the key.
2. `sha256` is the hex digest of the file at `path` — computed at save time, verified at load time.
3. `status`: `"draft"` → `"approved"` (pipeline only reads `"approved"`) → `"retired"`.
4. The manifest is append-only in spirit: new assets add entries; regenerated assets (new epoch) are *new entries* under a new `path`, not in-place replacements of old entries. Old entries stay with `status: "retired"` only when explicitly retired.
5. `style_epoch` at the top is the *current* epoch. When a style anchor set changes, it increments. Newly generated cards/plates record the epoch they were created under via their `path` (e.g. `characters/SCP-049/epoch_1/standing_front.png` — see Versioning below).

### DB models

```python
# db/models.py — additive to existing Character + CharacterCard (8.2)

class LocationPlate(SQLModel, table=True):
    __tablename__ = "location_plates"
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    location_key: str = Field(index=True)      # e.g. "isolation-cell"
    variant: str                                # e.g. "wide", "close", "establishing"
    image_path: str                             # relative to assets/ root
    status: str = "draft"                       # draft | approved | retired
    style_epoch: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    __table_args__ = (
        UniqueConstraint("location_key", "variant", name="uq_location_plate"),
    )
```

`CharacterCard` (8.2): this story adds `status: str = "draft"` and `style_epoch: int = 1` columns. The 8.2 story's `save_card` already upserts on `(scp_id, pose, angle)` — this story just adds the new columns (non-breaking: defaults fill existing rows on migration).

### Service layer — `AssetService`

New: `src/yt_flow/services/asset_service.py`. Single-responsibility owner of the manifest + lifecycle + integrity.

```python
class AssetService:
    def __init__(self, assets_path: Path, session: Session) -> None: ...
    
    # Manifest
    def load_manifest(self) -> dict: ...
    def save_manifest(self, manifest: dict) -> None: ...          # atomic write (tmp + rename)
    def add_asset(self, key: str, path: str, source: dict, **meta) -> None: ...
    def get_asset(self, key: str) -> dict | None: ...
    
    # Integrity
    def verify_asset(self, key: str) -> bool: ...                 # sha256 match
    def verify_all(self) -> list[str]: ...                         # returns list of failed keys
    
    # Lifecycle
    def approve_asset(self, key: str) -> None: ...                # draft → approved
    def retire_asset(self, key: str) -> None: ...                 # approved → retired
    
    # Versioning
    @property
    def style_epoch(self) -> int: ...
    def bump_style_epoch(self) -> int: ...                         # returns new epoch
```

### Config

```python
# config.py additions
assets_path: str = "./assets"
style_epoch: int = 1
```

### Migration script

`scripts/migrate_assets.py`: one-shot script to move 8.2-generated cards from `workspace/{card_key}/characters/` to `assets/characters/{card_key}/`, update `Character` angle paths + `CharacterCard` `image_path` fields to the new `assets/`-relative paths, and build the initial `manifest.json`.

## Acceptance Criteria

1. **Directory & config.** Given `Settings` (`config.py`), then `assets_path: str = "./assets"` and `style_epoch: int = 1` exist (env: `YTFLOW_ASSETS_PATH`, `YTFLOW_STYLE_EPOCH`); `.env.example` documents both. `assets/` is gitignored except `assets/manifest.json` (`.gitignore` updated: `assets/*` + `!assets/manifest.json`).
2. **Manifest I/O.** Given `AssetService` (`services/asset_service.py`), then `load_manifest()` returns the parsed `manifest.json` dict (empty skeleton if file missing — `{"style_epoch": 1, "assets": {}}`); `save_manifest()` writes atomically (write to `.tmp` + `os.replace` — no partial writes on crash); `add_asset(key, path, source, **meta)` inserts an entry + recomputes `sha256` from the file at `assets_path / path` and sets `status: "draft"` + `created_at`; `get_asset(key)` returns the entry dict or `None`. `sha256` is computed with `hashlib.sha256()` — stdlib only (AD-1).
3. **Integrity verification.** Given `AssetService.verify_asset(key)`, then it reads the file at the stored `path`, recomputes SHA-256, returns `True` if it matches the manifest entry and `False` otherwise (missing file = `False`). `verify_all()` returns a list of all keys that fail verification.
4. **Lifecycle.** Given `AssetService`, then `approve_asset(key)` sets `status: "approved"` + `approved_at` timestamp (no-op if already approved; raise `ValueError` if retired). `retire_asset(key)` sets `status: "retired"` (no-op if already retired). Pipeline consumers (`character_service.get_card`, 8-5 plate resolver) only return assets with `status == "approved"`; draft assets exist on disk and in manifest but are invisible to the runtime pipeline.
5. **Style epoch.** Given `AssetService`, then `style_epoch` reads the manifest's top-level value; `bump_style_epoch()` increments it + writes the manifest (no asset entries are touched — new assets created after the bump go under `characters/{card_key}/epoch_{new_epoch}/` etc.). The `character_service.save_card` and the 8-5 plate saver write into `assets/characters/{card_key}/epoch_{style_epoch}/{pose}_{angle}.png` — the epoch subdirectory is a single `AssetService.style_epoch` call away at save time.
6. **LocationPlate model.** Given `db/models.py`, then `LocationPlate` exists as specified in Interfaces (additive table — no migration needed, `create_all` picks it up). The model is defined here, consumed by 8-5. A thin `AssetService` wrapper method `add_location_plate(location_key, variant, image_path)` creates the row + adds the manifest entry in one call.
7. **Migration script.** Given `scripts/migrate_assets.py`, then it: (a) scans `workspace/*/characters/` for existing card PNGs (the 8-2 naming pattern: `{angle}_candidate_1.png` for standing, `{pose}_{angle}.png` for non-standing); (b) copies each to `assets/characters/{card_key}/epoch_{style_epoch}/` (preserving the filename); (c) updates the corresponding `Character.angle_*_path` or `CharacterCard.image_path` to the new `assets/`-relative path; (d) builds the initial `manifest.json` with `status: "approved"` (these cards were already through 8-2's human QA) and `source.type: "comfyui_generation"` populated from whatever metadata is available; (e) is idempotent — re-running skips already-migrated assets; (f) logs a summary: N migrated, M skipped, 0 errors.
8. **Card save writes to assets/.** Given 8-2's `CharacterService.generate_candidates_from_reference` and `generate_cards_from_descriptor`, when this story lands, then their save paths change from `workspace/{card_key}/characters/` to `assets/characters/{card_key}/epoch_{style_epoch}/` — a one-line path change in `character_service.py`. The `Character.angle_*_path` and `CharacterCard.image_path` store the `assets/`-relative path (e.g. `characters/SCP-049/epoch_1/standing_front.png`). `AssetService.add_asset` is called at save time so the manifest stays in sync.
9. **Run cleanup never touches assets/.** Given any run termination/cleanup path (currently none exists — `workspace/` is append-only — but this is a structural guarantee), then no code that deletes or prunes `workspace/` may touch `assets/`. Enforced by design: `assets_path` and `workspace_path` are two distinct config keys; no function takes a generic "data root" that could accidentally encompass both.
10. **STOCK-* global sharing.** Given `CharacterService.get_card(scp_id, pose, angle)`, then for `STOCK-*` keys it reads from `assets/characters/{card_key}/` and the `CharacterCard` table without any run-scoping — the same card is returned for every run, every episode. The 5-8 `_ensure_character_reference` provisioning path's `check_existing_character` already returns the same row for any run; this story adds no new gating — just structural assurance that the file backing that row lives in `assets/`, not `workspace/`.
11. **5-8 provisioning still works.** Given 8-2's card pipeline writes to `assets/` and `Character.angle_*_path` holds `assets/`-relative paths, then `_ensure_character_reference` (`run_service.py:367-443`) still reads those paths and skips generation when they exist — the path format change is transparent to it. The 5-8/5-10 regression suite stays green.
12. **Tests.** Given automated verification: `AssetService` unit tests with `tmp_path` — load/save/add/get round-trip, sha256 verification (valid + tampered + missing file), lifecycle transitions (draft→approved→retired, approve-retired raises, retire-retired no-op), `bump_style_epoch` increments, atomic save (no partial file on disk after simulated crash), empty-manifest bootstrap. `LocationPlate` model creation + unique constraint test. Migration script test with a temporary workspace populated with fake cards. Full suite: `uv run pytest tests/services/test_asset_service.py tests/db/ -q` then `uv run pytest -q`. Always use `tmp_path` — no `assets/` written to the repo. The existing `workspace_path=str(tmp_path)` pattern extends to `assets_path=str(tmp_path)`.

## Tasks / Subtasks

- [ ] Task 1 — Config + .gitignore + directory bootstrap (AC: 1)
  - [ ] Add `assets_path: str = "./assets"` and `style_epoch: int = 1` to `Settings` (`config.py`, near `workspace_path`). Document in `.env.example`.
  - [ ] Update `.gitignore`: add `assets/*` + `!assets/manifest.json` (the `!` negation un-ignores the manifest — standard git pattern).
  - [ ] In `api/main.py` lifespan or a `AssetService` constructor, ensure `assets/characters/`, `assets/locations/`, `assets/anchors/` exist (`Path.mkdir(parents=True, exist_ok=True)`). The `manifest.json` is created lazily by `AssetService` on first save.

- [ ] Task 2 — `AssetService` core (AC: 2, 3, 4, 5)
  - [ ] Create `src/yt_flow/services/asset_service.py`: `AssetService.__init__(assets_path, session)`, `load_manifest`, `save_manifest` (atomic: write `.tmp` + `os.replace`), `add_asset`, `get_asset`.
  - [ ] `sha256` computation: `hashlib.sha256(path.read_bytes()).hexdigest()` — stdlib only.
  - [ ] `verify_asset(key)` / `verify_all()` per AC3.
  - [ ] Lifecycle: `approve_asset(key)` / `retire_asset(key)` per AC4. `get_asset` returns `None` for non-approved assets unless an `include_drafts=False` flag is set (pipeline consumers never pass `True`).
  - [ ] `style_epoch` property + `bump_style_epoch()` per AC5.
  - [ ] `add_location_plate(location_key, variant, image_path)` thin wrapper per AC6.

- [ ] Task 3 — `LocationPlate` model (AC: 6)
  - [ ] Add `LocationPlate` to `src/yt_flow/db/models.py` per Interfaces. This is additive — no migration, `create_all` bootstrap handles it.

- [ ] Task 4 — Wire card saves to `assets/` (AC: 8, 9, 10, 11)
  - [ ] In `character_service.py`, change save paths in `generate_candidates_from_reference` and `generate_cards_from_descriptor` from `workspace/{card_key}/characters/` to `assets/characters/{card_key}/epoch_{style_epoch}/`. The `Character.angle_*_path` and `CharacterCard.image_path` now store `assets/`-relative paths.
  - [ ] Call `AssetService.add_asset(...)` after each successful card save so the manifest stays in sync.
  - [ ] In `character_service.get_card` (8.2), only return cards with `status == "approved"` (filter at the `AssetService` level — `get_asset` returns `None` for drafts by default).
  - [ ] Verify that `_ensure_character_reference` (`run_service.py:367-443`) is path-format agnostic — it reads `angle_*_path` and checks file existence; confirm it works with the new `assets/`-relative paths (they are relative to `settings.assets_path`, not `settings.workspace_path`). If `_ensure_character_reference` currently uses `workspace_path` to resolve angle paths, it needs a one-line change to use `assets_path` for character card resolution. Track this down in the code.

- [ ] Task 5 — Migration script (AC: 7)
  - [ ] Create `scripts/migrate_assets.py`: scan `workspace/*/characters/`, copy to `assets/characters/{card_key}/epoch_1/`, update DB paths, build initial manifest. Idempotent — check if destination already has the file (by sha256 or path existence) and skip.
  - [ ] Use `AssetService.add_asset` for manifest entries so the format is consistent.
  - [ ] Run once against the dev DB to migrate existing SCP-049 + any other cards; verify paths resolve in the character management UI (3.7).

- [ ] Task 6 — Tests (AC: 12)
  - [ ] `tests/services/test_asset_service.py`: all AC2-5 coverage.
  - [ ] `tests/db/test_models.py` or extend existing: `LocationPlate` create + unique constraint enforcement.
  - [ ] Update any test fixtures that hardcode `workspace/` paths for character cards — they now use `assets/` paths. Grep for `workspace.*characters` in `tests/`.
  - [ ] Regression: `uv run pytest tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/services/test_run_service_character_provisioning.py -q` stays green.

## Dev Notes

### Architecture compliance

- **AD-1 (layer direction):** `AssetService` lives in `services/`, imports `domain/` and `db/` — clean. `character_service.py` imports `AssetService` — both are `services/` → `services/` (same-layer import, allowed). No `api/` or `pipeline/` imports.
- **AD-2 (LangGraph state):** No state changes. Assets are DB + filesystem, not pipeline state.
- **AD-7 (Single SQLite):** `LocationPlate` is an additive table in the same SQLite file — no new database.
- **AD-10 (Operational envelope):** `YTFLOW_ASSETS_PATH` is configurable (default `./assets`), same pattern as `YTFLOW_WORKSPACE_PATH`.

### Why manifest.json instead of DB-only

The epic explicitly calls for `manifest.json` committed to git: "자산 이력이 git으로 감사 가능." DB rows can be deleted/lost; a committed JSON file is an immutable audit trail. The DB remains the runtime truth (fast queries for card/plate lookup); the manifest is the provenance record. They serve different purposes — no duplication concern.

### Why epoch subdirectories

`style_epoch` versioning means: when the style anchor set changes and cards are regenerated, the old cards must not be overwritten (past episodes rendered with old cards must remain reproducible). The simplest filesystem contract: `characters/{card_key}/epoch_{N}/{pose}_{angle}.png`. The manifest's `path` field captures which epoch each asset belongs to. Old epochs are never deleted — only the current epoch is "active" for new generation.

### Current Code State — files to read before editing

- `src/yt_flow/config.py:4-170` — `Settings` class. Note `workspace_path` at line 56; add `assets_path` + `style_epoch` nearby.
- `src/yt_flow/db/models.py:1-70` — all models. `Character` (23-39), `CharacterCard` (to be added by 8.2 — this story adds `status` + `style_epoch` columns). `LocationPlate` is new here.
- `src/yt_flow/services/character_service.py:542-610` — `generate_candidates_from_reference` (save path at ~600). `generate_cards_from_descriptor` (8.2 — similar save path). The `_UPDATE_ALLOWLIST` (61-65) may need `angle_*_path` entries unchanged — path format change is transparent to the allowlist.
- `src/yt_flow/services/run_service.py:367-443` — `_ensure_character_reference`. Check whether it resolves `angle_*_path` against `workspace_path` or treats it as absolute/relative-to-cwd. If it uses `settings.workspace_path`, it needs to switch to `settings.assets_path` for character card path resolution.
- `src/yt_flow/api/main.py:26` — `app.state.workspace_path` setting. `app.state.assets_path` may need to be set similarly for API-layer path resolution.
- `.gitignore:15` — `workspace/` line. Add `assets/*` + `!assets/manifest.json`.
- `.env.example` — document `YTFLOW_ASSETS_PATH` and `YTFLOW_STYLE_EPOCH`.
- `_bmad-output/implementation-artifacts/8-2-character-card-sprite-pipeline.md#Interfaces` — `CharacterCard` model spec (this story adds columns to it).

### Preserved behavior (do not break)

- **5-8/5-10 auto-provisioning** (`_ensure_character_reference`): must still work after path format change. If it currently resolves `angle_*_path` against `workspace_path`, update to `assets_path`. Its dedup/rollback/non-fatal logic is not touched.
- **3.7 Character Management UI**: loads card images by path. The migration updates DB paths; the UI should resolve against `assets/` after this story. Check `api/routes/characters.py` for any hardcoded `workspace/` path resolution.
- **Stub/mock profiles**: `comfyui_mock` runs skip card generation — but test fixtures that fake card paths need updating.
- **Workspace run isolation**: `workspace/` continues to hold per-run artifacts (scenario texts, audio, subtitles, video). Only character cards + future plates move to `assets/`.

### Testing standards

- `AssetService` is tested with `tmp_path` — every test gets a fresh temp directory for `assets_path`.
- Migration script tested with a fake workspace directory structure populated by the test.
- Mock `CharacterService` and `AssetService` in tests that don't test them directly (existing fakes pattern in `tests/stubs/fakes.py`).
- Always `assets_path=str(tmp_path)` in tests — never write to the repo `./assets/`.

### Ponytail note

One new service module, one new DB model (6 fields), two config keys, one migration script, one `.gitignore` line change. No new dependencies. No speculative features: `style_epoch` starts at 1 and only changes when Jay explicitly runs `AssetService.bump_style_epoch()` (which nothing calls automatically — it's a manual curation step). Lifecycle has exactly 3 states with 2 transitions — no "pending_review" or "archived" unless a real workflow demands them.

## Project Structure Notes

- New: `src/yt_flow/services/asset_service.py`, `scripts/migrate_assets.py`, `tests/services/test_asset_service.py`
- Modified: `src/yt_flow/config.py` (2 new fields), `src/yt_flow/db/models.py` (additive: `LocationPlate`; `CharacterCard` column additions if 8.2 has landed), `src/yt_flow/services/character_service.py` (save path change + AssetService call), `src/yt_flow/services/run_service.py` (possible path resolution fix), `.gitignore`, `.env.example`
- Concurrent-edit hazard: `config.py` and `models.py` are shared with 8-2/8-3/8-4; `character_service.py` is shared with 8-2/8-4. Coordinate merges. The `assets/` directory and `LocationPlate` model are owned by this story alone.

## References

- `_bmad-output/planning-artifacts/epics.md#Story 8.6` — epic draft (Jay 지시, 2026-07-07).
- `_bmad-output/implementation-artifacts/8-2-character-card-sprite-pipeline.md#Interfaces` — `CharacterCard` model spec; `save_card`/`get_card` service methods.
- `_bmad-output/implementation-artifacts/8-5-stock-location-plates.md` — (not yet created; this story precedes it). `LocationPlate` model defined here for 8-5 consumption.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1 through AD-10.
- `src/yt_flow/config.py` — `Settings` class.
- `src/yt_flow/db/models.py` — `Character`, `CharacterCard` (8.2), `LocationPlate` (new here).
- `src/yt_flow/services/character_service.py` — card generation save paths.
- `src/yt_flow/services/run_service.py:367-443` — `_ensure_character_reference`.
- Memory: `project_test-isolation-workspace-pollution` (tmp_path rule), `reference_comfyui_local` (ComfyUI environment).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-07: Story created from Epic 8 architecture decision (Jay 지시). Owns the asset library infrastructure: `assets/` directory, `manifest.json`, `style_epoch`, lifecycle, `LocationPlate` model, migration.

## Saved Questions / Clarifications

1. **`_ensure_character_reference` path resolution.** The dev notes flag this as a code-reading task (Task 4). If it currently resolves `angle_*_path` against `workspace_path`, it needs a one-line switch to `assets_path`. If `angle_*_path` is already absolute or resolved relative to CWD, no change needed. The answer determines whether `run_service.py` is in the modified-files list.
2. **`CharacterCard` column additions.** If 8-2 hasn't landed when this story is implemented, `CharacterCard` doesn't exist yet — the `status` + `style_epoch` columns are added as part of 8-2's model definition (coordinate with the 8-2 implementer). If 8-2 has landed, this story runs an additive migration. Either way, the manifest is the system of record for status/epoch; the DB columns are a cache for query convenience.
3. **Manifest vs DB — single source of truth.** The manifest is authoritative for `sha256`, `source` provenance, `created_at`, and `approved_at`. The DB is authoritative for `status` (runtime queries need it fast) and `image_path` (DB consumers like 3.7 UI read it directly). `AssetService.approve_asset` writes to both atomically (manifest + DB in one transaction). If they ever diverge, `scripts/verify_manifest.py` (a one-liner calling `verify_all`) catches it.
