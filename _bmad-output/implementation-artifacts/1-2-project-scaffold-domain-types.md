# Story 1.2: Project Scaffold + Domain Types

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want the project directory structure, `pyproject.toml`, and all domain TypedDicts initialized,
so that every subsequent story has a consistent import path and shared type system.

## Acceptance Criteria

1. Given `pyproject.toml` managed by `uv` with pinned runtime dependencies, when `uv sync` runs, then all packages install without conflict.
2. Given the Architecture structural seed, when `from yt_flow.domain.state import PipelineState, SceneState, ShotData, WordTiming` runs, then all TypedDicts import without error and fields match the Architecture definition exactly.
3. Given `src/yt_flow/{domain,pipeline/nodes,services,db,api/routes}/` directories, when `find src/yt_flow -type d` runs, then all required directories exist.
4. Given the layered architecture rule, when import checks or tests run, then `domain` has no imports from upper layers, `pipeline` does not import `db`, and `api` does not import `pipeline` directly.
5. Given this is scaffold-only foundation work, when implementation is complete, then no API route, LangGraph graph, node logic, SQLModel table, frontend app, external service call, or Langfuse prompt migration is implemented in this story.

## Tasks / Subtasks

- [x] Create Python package scaffold. (AC: 2, 3, 4)
  - [x] Create `src/yt_flow/__init__.py`. (already present from Story 1.1; preserved)
  - [x] Create `src/yt_flow/domain/__init__.py` and `src/yt_flow/domain/state.py`.
  - [x] Create empty package markers for `pipeline`, `pipeline/nodes`, `services`, `db`, `api`, and `api/routes`.
  - [x] Create runtime roots `data/` and `workspace/` if absent; keep `workspace/` ignored if runtime artifacts should not be committed.
- [x] Define domain state types in `src/yt_flow/domain/state.py`. (AC: 2)
  - [x] Define `StageName = Literal["scenario", "image", "tts", "subtitle", "video"]`.
  - [x] Define `GateState = Literal["pending", "approved", "rejected", "n/a"]`.
  - [x] Define `WordTiming(TypedDict)` with `word: str`, `start_sec: float`, `end_sec: float`.
  - [x] Define `ShotData(TypedDict)` with `shot_id`, `sentence_indices`, `image_prompt`, `negative_prompt`, `camera_angle`, `camera_movement`, and `image_path`.
  - [x] Define `SceneState(TypedDict)` with `scene_num`, `narration`, `shots`, `audio_path`, `audio_duration`, `word_timings`, and `subtitle_path`.
  - [x] Define `PipelineState(TypedDict)` with `run_id`, `scp_text`, `scenes`, `video_path`, `current_stage`, `gate_states`, `prompt_variant`, and `error`.
- [x] Create or extend `pyproject.toml` for a `src` layout package. (AC: 1)
  - [x] Set project name to `yt-flow`, package import name to `yt_flow`, and Python requirement to Python 3.12 if not already set by Story 1.1.
  - [x] Preserve Story 1.1's config/Langfuse dependencies and add or correct pins to the stack in "Latest Technical Information" below.
  - [x] Add pytest and Ruff as dev dependencies only.
  - [x] Configure Ruff for Python 3.12 and the `src` package layout.
- [x] Add focused scaffold tests. (AC: 1, 2, 3, 4)
  - [x] Add `tests/domain/test_state_imports.py` proving the four exported TypedDicts import.
  - [x] Add assertions that required directories exist.
  - [x] Add a lightweight guard that `yt_flow.domain.state` imports no project layer modules other than stdlib typing helpers.
  - [x] Add an import smoke test that `typing.get_type_hints` works for every domain TypedDict.
- [x] Verify locally. (AC: 1, 2, 3)
  - [x] Run `uv sync`. (all pins resolved, no conflict)
  - [x] Run `uv run pytest`. (8 passed)
  - [x] Run `uv run ruff check .`. (all checks passed)
  - [x] Run `uv run python -c "from yt_flow.domain.state import PipelineState, SceneState, ShotData, WordTiming; print(PipelineState, SceneState, ShotData, WordTiming)"`.

## Dev Notes

### Scope Boundary

This story is foundation only. Build the minimum substrate that later stories need, then stop. Story 1.1 owns `src/yt_flow/config.py`, Langfuse env validation, `.env.example`, and any minimal dependency substrate needed for config tests. If Story 1.1 is implemented first, extend its existing `pyproject.toml` and package root instead of replacing them. Do not create `pipeline/graph.py`, real node files, `gates.py`, SQLModel models, FastAPI routes, React frontend, Langfuse clients, Prompt Hub migration scripts, or ComfyUI/Qwen/DeepSeek integrations. Those are covered by later stories.

Story 1.1 now has a ready-for-dev story file, but no implementation source was present when this story was created. Keep this story independent from real Langfuse credentials and external services; config and auth smoke behavior remain Story 1.1's responsibility.

### Architecture Guardrails

- Dependency direction must remain `api -> services -> (pipeline | db) -> domain`. `domain` is pure shared type substrate. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`]
- `PipelineState` is the single source of truth for in-flight pipeline data. Later SQLModel `runs` rows are only a read-optimized API projection. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2-LangGraph-state-is-the-single-source-of-truth`]
- Artifact paths belong in `PipelineState`, not in a scenes/artifacts table. Do not introduce any DB schema in this story. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7-Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`]
- State mutation convention for later nodes is whole-field replacement per node return, no reducers. This should influence type shapes now: use simple JSON-serializable fields. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]

### Domain Type Contract

Implement `src/yt_flow/domain/state.py` to match this contract exactly:

```python
from typing import Literal, TypedDict

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
GateState = Literal["pending", "approved", "rejected", "n/a"]
PromptVariant = Literal["A", "B"]


class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float


class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None
    image_path: str | None


class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None


class PipelineState(TypedDict):
    run_id: str
    scp_text: str
    scenes: list[SceneState]
    video_path: str | None
    current_stage: StageName
    gate_states: dict[StageName, GateState]
    prompt_variant: PromptVariant | None
    error: str | None
```

The architecture text types `current_stage` as `str` and `gate_states` as `dict[str, str]`, but the same document also fixes the allowed stage and gate literals. Use the narrower aliases above for stronger developer feedback while preserving the same JSON shape. Do not use dataclasses or Pydantic models here; the architecture explicitly calls for `TypedDict`.

`ShotData.sentence_indices` is 0-based and maps one shot to one or more narration sentences. It is the future image-generation unit, not a scene index. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-5-Shot-is-the-image-generation-unit-NM-sentence-mapping-LLM-Director-pattern`]

### File Structure Requirements

Required scaffold after this story:

```text
src/yt_flow/
  __init__.py
  domain/
    __init__.py
    state.py
  pipeline/
    __init__.py
    nodes/
      __init__.py
  services/
    __init__.py
  db/
    __init__.py
  api/
    __init__.py
    routes/
      __init__.py
data/
workspace/
tests/
  domain/
    test_state_imports.py
pyproject.toml
```

Do not create placeholder modules with speculative interfaces. Empty `__init__.py` files are enough for package boundaries. This follows the repo's Ponytail rule in `CLAUDE.md`: no boilerplate "for later"; deletion over addition. [Source: `CLAUDE.md#Code-Philosophy-Ponytail-always-active`]

### Library / Framework Requirements

The epic AC still mentions stale pins: LangGraph 0.2.x, SQLModel 0.0.21, and Langfuse SDK 2.x. Treat those as superseded by the architecture review and current package research. Use current safe pins in `pyproject.toml`:

- Python: `>=3.12,<3.13`
- `langgraph==1.2.7` (PyPI latest released 2026-06-30)
- `langgraph-checkpoint-sqlite==3.1.0` (separate package required for `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`)
- `fastapi==0.138.2`
- `sqlmodel==0.0.39`
- `alembic==1.*` or an exact current 1.x pin if `uv add` resolves one cleanly
- `langfuse==4.12.0`
- `pydantic-settings==2.14.2`
- Dev dependencies: `pytest==9.1.1`, `ruff==0.15.20`

Latest technical sources checked on 2026-07-01:

- PyPI lists `langgraph 1.2.7`, released 2026-06-30: https://pypi.org/project/langgraph/
- PyPI lists `langgraph-checkpoint-sqlite 3.1.0`, released 2026-05-12: https://pypi.org/project/langgraph-checkpoint-sqlite/
- PyPI lists `fastapi 0.138.2`, released 2026-06-29: https://pypi.org/project/fastapi/
- PyPI lists `sqlmodel 0.0.39`, released 2026-06-25: https://pypi.org/project/sqlmodel/
- PyPI lists `langfuse 4.12.0`, released 2026-06-25, and notes the Python SDK was rewritten in v4 in March 2026: https://pypi.org/project/langfuse/
- Langfuse latest SDK docs identify the current docs as the latest SDK docs and mark legacy Python SDK v3 separately: https://langfuse.com/docs/observability/sdk/overview
- PyPI lists `pydantic-settings 2.14.2`, released 2026-06-19: https://pypi.org/project/pydantic-settings/
- PyPI lists `pytest 9.1.1`, released 2026-06-19: https://pypi.org/project/pytest/
- PyPI lists `ruff 0.15.20`, released 2026-06-25: https://pypi.org/project/ruff/

Security guardrail: do not pin `langgraph-checkpoint-sqlite` below 3.0.1 or `langgraph` below 1.0.10. 2026 advisories reported checkpointer vulnerabilities patched at those minimums; the pins above are beyond the patched floor.

### Testing Requirements

Minimum tests for this story:

- Import smoke test for `PipelineState`, `SceneState`, `ShotData`, and `WordTiming`.
- Type-hint shape test using `typing.get_type_hints` so future accidental field renames fail quickly.
- Directory scaffold test for the six required architecture directories.
- Import-boundary smoke test proving `yt_flow.domain.state` has no project-layer imports.

Do not write tests for LangGraph execution, AsyncSqliteSaver persistence, FastAPI routes, Langfuse auth, SQLModel tables, or frontend behavior in this story. Those belong to Stories 1.1, 1.4, 2.x, and 3.x.

### Previous Story Intelligence

Story 1.1 (`_bmad-output/implementation-artifacts/1-1-langfuse-env-verification.md`) is ready for dev and owns the minimal config foundation:

- `src/yt_flow/config.py` with `pydantic_settings.BaseSettings`, `SettingsConfigDict(env_prefix="YTFLOW_", env_file=".env", extra="ignore")`, and required non-empty Langfuse fields.
- A minimal `pyproject.toml` sufficient for Python 3.12, `uv`, `langfuse`, `pydantic-settings`, `pydantic`, `pytest`, and dotenv loading.
- `.env.example` with Langfuse placeholders and tests for settings validation.
- Unit tests that avoid requiring a live Langfuse server; real `auth_check()` remains a manual smoke check.

Actionable implications for Story 1.2:

- Do not duplicate or redesign `config.py`; only preserve it if already present.
- If `pyproject.toml` already exists from Story 1.1, update it in place to add scaffold-wide dependencies, Ruff config, and package/test settings.
- If `src/yt_flow/__init__.py` already exists, keep it and add the domain/layer directories around it.
- Keep real external service calls out of Story 1.2 tests.

Recent git history still contains planning artifacts only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epics and implementation readiness.
- `6db2416` added UX specs and HTML mockups.
- `ca2fb1d` added architecture spine and review docs.

There are no committed implementation code patterns yet beyond `CLAUDE.md`, Story 1.1's intended config substrate, and the planning artifacts.

### Project Structure Notes

Current repository state at story creation has sprint/story context files being generated, but no committed `src/`, `tests/`, `pyproject.toml`, frontend package, or Python package scaffold was detected during analysis. If Story 1.1 is implemented before Story 1.2 starts, treat `src/yt_flow/__init__.py`, `src/yt_flow/config.py`, `tests/test_config.py`, `.env.example`, and `pyproject.toml` as existing UPDATE files to preserve and extend.

The source reference project `/mnt/work/projects/yt.pipe` is structural context only. Do not copy Go code patterns or CLI/Cobra architecture into this Python rewrite; the PRD explicitly rejects Go/Python hybrid migration and CLI scope. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Out-of-Scope`]

### References

- `_bmad-output/planning-artifacts/epics.md#Story-12-프로젝트-스캐폴드--도메인-타입`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural-Seed`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState-OQ-7-resolved`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/reviews/review-tech-currency.md`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1--Pipeline-Core-LangGraph`
- `CLAUDE.md#Code-Philosophy-Ponytail-always-active`

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (bmad-dev-story workflow)

### Debug Log References

- `uv sync` → resolved full stack cleanly (langgraph 1.2.7, langgraph-checkpoint-sqlite 3.1.0, fastapi 0.138.2, sqlmodel 0.0.39, alembic 1.x, langfuse 4.12.0, pydantic-settings 2.14.2; dev: pytest 9.1.1, ruff 0.15.20). Env installed Python 3.12 per `<3.13` pin.
- `uv run pytest -q` → 8 passed (Story 1.1 config: 4; scaffold: 4).
- `uv run ruff check .` → All checks passed.
- Import smoke → `OK PipelineState SceneState ShotData WordTiming`.

### Completion Notes List

- Extended Story 1.1's existing `pyproject.toml` and `src/yt_flow/__init__.py` in place rather than replacing them (per Scope Boundary / Previous Story Intelligence).
- `domain/state.py` matches the Architecture contract exactly, using narrowed `StageName`/`GateState`/`PromptVariant` Literal aliases while preserving the same JSON shape. TypedDict (not Pydantic/dataclass) per AD-2.
- Layer-boundary rule enforced as an executable test: AST-parses `state.py` and asserts zero `yt_flow.*` imports (AC4). Field-shape test uses `typing.get_type_hints` against exact expected field sets so future renames fail fast.
- Env constraint (langfuse/deepseek/qwen/comfyui integration unavailable) did not affect this story: scaffold-only, no external service calls or imports at runtime/test time. Dependencies are declared for later stories but never invoked here.
- Ponytail: empty `__init__.py` markers only — no speculative placeholder modules or interfaces. `data/.gitkeep` added so the runtime root is tracked; `workspace/` left gitignored.

### File List

- `src/yt_flow/domain/__init__.py` (new)
- `src/yt_flow/domain/state.py` (new)
- `src/yt_flow/pipeline/__init__.py` (new)
- `src/yt_flow/pipeline/nodes/__init__.py` (new)
- `src/yt_flow/services/__init__.py` (new)
- `src/yt_flow/db/__init__.py` (new)
- `src/yt_flow/api/__init__.py` (new)
- `src/yt_flow/api/routes/__init__.py` (new)
- `tests/domain/__init__.py` (new)
- `tests/domain/test_state_imports.py` (new)
- `data/.gitkeep` (new)
- `pyproject.toml` (modified — added stack pins, Ruff config, Python `<3.13` bound)
- `uv.lock` (modified — regenerated by `uv sync`)

## Change Log

| Date       | Change                                                                 |
| ---------- | ---------------------------------------------------------------------- |
| 2026-07-01 | Story 1.2 implemented: package scaffold, domain TypedDicts, dependency pins, Ruff config, scaffold tests. All ACs verified; status → review. |

## Review Findings

Code review (2026-07-01, epic 1 story 1.1~1.2 adversarial review — Blind Hunter / Edge Case Hunter / Acceptance Auditor).

Domain TypedDict field sets verified byte-for-byte against the Architecture Domain Type Contract; layer isolation (AC4), scaffold-only constraint (AC5), and directory structure (AC3) all confirmed compliant. No patch-level defects in this story's code.

- [x] [Review][Defer] Layer-boundary guard only AST-checks `domain/state.py`; AC4's `pipeline↛db` and `api↛pipeline` clauses are vacuously true (those layers are empty `__init__.py`) [tests/domain/test_state_imports.py] — deferred, no code to violate yet; extend the guard when pipeline/api gain modules
- [x] [Review][Defer] `pytest-asyncio>=0.24` declared but `[tool.pytest.ini_options]` has no `asyncio_mode`; async tests added later would be silently collected without running under STRICT mode [pyproject.toml] — deferred until story 1.4 adds the first async (AsyncSqliteSaver) test

Dismissed as noise: alembic range pin (story explicitly permits `alembic==1.*` range), `parents[1]`/`get_type_hints`/`read_text` frozen-install fragilities (speculative, dev tree only), fastapi-vs-spine version mismatch (spec-internal doc note, code matches the story's authoritative pin table), `workspace/` dir marker (gitignored empty dir — Ponytail-correct to not track).
