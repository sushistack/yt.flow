---
stepsCompleted: ["step-01", "step-02", "step-03", "step-04"]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md
  - docs/superpowers/specs/2026-07-04-sound-design-design.md
  - docs/superpowers/specs/2026-07-04-color-grade-postfx-design.md
  - docs/superpowers/specs/2026-07-04-character-parallax-design.md
  - docs/superpowers/specs/2026-07-04-transition-variety-design.md
  - docs/superpowers/specs/2026-07-04-kinetic-subtitles-design.md
---

# yt.flow - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for yt.flow, decomposing the requirements from the PRD, UX Design, and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: Accept SCP article text as input and generate a structured scene scenario via DeepSeek V4
FR-2: Generate an image prompt per scene (shot) from the scenario via DeepSeek V4 using LLM-Director pattern (N:M sentence-to-shot mapping)
FR-3: Submit image prompts to ComfyUI local HTTP API and retrieve generated images
FR-4: Generate TTS audio per scene via Qwen TTS (latest cloud API)
FR-5: Generate subtitles via forced alignment — script text is known from scenario stage; align timing against TTS audio output
FR-6: Compose scene images, audio, and subtitles into a final video via FFmpeg subprocess
FR-7: Resume from last successful node after failure (node-level, not scene-level)
FR-8: Support full restart (from FR-1) as an explicit option
FR-9: After each stage completes, pause execution and emit a gate-pending event; proceed only when the user approves via FR-29
FR-10: Every LangGraph node emits a Langfuse trace span on entry and exit
FR-11: Each LLM call captures: rendered prompt, raw LLM response, latency, token count
FR-12: Trace spans are linked per pipeline run so a full run is inspectable as one trace tree
FR-13: A failed node surfaces error detail in the trace (exception, inputs at failure point)
FR-14: All pipeline prompts stored and versioned in Langfuse Prompt Hub
FR-15: Pipeline nodes fetch prompts from Prompt Hub at runtime (no hardcoded strings)
FR-16: Prompt change takes effect on next run without code change or service restart
FR-17: Prompt version history and change audit available in Langfuse UI
FR-18: Given the same SCP input, execute the pipeline with prompt variant A and variant B
FR-19: LLM-as-judge evaluation: score each output against SCP-specific criteria (atmosphere, narrative coherence, article fidelity)
FR-20: Rule-based evaluation: score each output against structural metrics (scene count, subtitle sync, audio length variance)
FR-21: Combined evaluation result stored in Langfuse as a scored comparison trace
FR-22: A/B result retrievable via API
FR-23: A winner is determined automatically by combined score; no manual scoring step required (see OQ-6 for threshold definition)
FR-24: POST /runs — trigger a pipeline run with SCP input (`scp_id`, `scp_text`), optional prompt variant config, and optional `extra: dict` (reserved, ignored in v1)
FR-25: GET /runs/{id} — retrieve run status and Langfuse trace URL
FR-26: GET /runs/{id}/artifact — return the output video as a file download (HTTP 200 with content-disposition) or redirect to a local file path
FR-27: POST /runs/{id}/ab — trigger A/B evaluation for a completed run
FR-28: GET /runs/{id}/stages/{stage}/artifacts — return intermediate artifacts for a completed stage (images, audio, text)
FR-29: POST /runs/{id}/stages/{stage}/gate — accept {"action": "approve" | "reject"} to release or abort the pipeline at a stage gate
FR-30: POST /runs/{id}/stages/{stage}/retry — re-execute a specific stage using current prompt config
FR-31: GET /runs — list all runs with status, timestamps, and stage gate state
FR-32: GET /runs/{id}/progress — SSE stream emitting stage_entry, stage_exit, gate_pending, run_failed events in real time
FR-33: GET /scps — return list of available SCP entries (id, nickname, object_class, rating) read from local SCP facts file; used by UI SCP Picker
FR-34: PATCH /runs/{id}/stages/{stage}/artifact — accept edited text body; update LangGraph checkpoint via graph.update_state() and rewrite artifact file on disk; valid for scenario and subtitle stages only
FR-35: SQLite database stores run metadata (id, status, current_stage, gate_states, prompt_variant, ab_pair_id) as API projection; LangGraph AsyncSqliteSaver checkpoint is the authoritative state store
FR-36: Node-level checkpoint persisted after each successful node via LangGraph AsyncSqliteSaver (enables FR-7)
FR-37: Dashboard: list all runs with status, current stage, and gate state (pending approval / approved / rejected / failed)
FR-38: Run detail: real-time stage progress via SSE — each stage shows running / awaiting approval / approved / rejected
FR-39: Stage artifact preview panel — scenario text (readable), generated images (gallery), TTS audio (playable), subtitle file (readable), final video (playable)
FR-40: Stage gate controls — Approve and Reject buttons visible when a stage is awaiting approval; pipeline does not advance until approved
FR-41: Stage retry button — re-execute a specific completed or rejected stage; launches new stage run with current prompt config
FR-42: A/B comparison view — side-by-side display of variant A and B artifacts with evaluation scores (LLM-as-judge + rule-based) and winner indicator
FR-43: Link to Langfuse trace per run (opens in new tab); prompt editing deferred to Langfuse UI
FR-44: Inline text editor for scenario and subtitle stages — "편집" button toggles textarea; "저장" calls FR-34 PATCH endpoint; pipeline does not advance until "승인" is clicked separately

### NonFunctional Requirements

NFR-1: Deployment — Pipeline: local execution. Langfuse: homelab-gitops (self-hosted Docker/k8s)
NFR-2: Performance — End-to-end video generation ≤ 2 hours; quality over speed; 2-hour ceiling dominated by ComfyUI image generation time; human approval wait time excluded
NFR-3: Observability overhead — Langfuse tracing adds ≤ 10% to total run time
NFR-4: Storage — SQLite flat file; no external DB; single SQLite file shared by SQLModel tables and LangGraph checkpoints
NFR-5: Authentication — None; local-only deployment, single operator
NFR-6: External dependencies — DeepSeek V4 API (OpenAI-compatible client), Qwen TTS API (cloud, latest), ComfyUI (local HTTP, version pinned in config), Langfuse (homelab, self-hosted)
NFR-7: Error visibility — Any run failure surfaces the failed node, inputs, and exception in the Langfuse trace
NFR-8: Resume granularity — Resume at node level (not scene level); a mid-stage failure (e.g., TTS fails on scene 8 of 20) restarts that entire stage; accepted trade-off for implementation simplicity
NFR-9: Data retention — Runs older than 30 days eligible for manual cleanup; no automatic deletion; artifact files not auto-purged
NFR-10: Model versioning — DeepSeek and Qwen TTS model identifiers pinned in config (YTFLOW_ prefix); updating a model requires a config change, not a code change
NFR-11: UI technology — React SPA; FastAPI serves the static build under /app; no separate web server
NFR-12: Real-time transport — SSE (Server-Sent Events) for progress and gate notifications; WebSocket not required

### Additional Requirements

Architecture / Infrastructure:
- Structural seed defined: yt.flow/ with src/yt_flow/{domain,pipeline,services,db,api}, frontend/, data/, workspace/, pyproject.toml, yt_flow.db
- Package manager: uv
- Stack pinned: Python 3.12, LangGraph 0.2.x, FastAPI 0.115.x, SQLModel 0.0.21, Alembic 1.x, Langfuse 2.x (self-hosted + Python SDK 2.x), React 18.x, shadcn/ui + Tailwind

Layering (AD-1): Import path must follow api → services → (pipeline | db) → domain. Cross-layer imports forbidden. Pipeline nodes never import db/; api/ never imports pipeline/ directly.

State Authority (AD-2): All in-flight pipeline data lives in PipelineState (TypedDict), persisted by AsyncSqliteSaver. runs table is a read-optimised API projection only — never write-authoritative.

Gate Mechanism (AD-3): Every stage node calls interrupt({"stage": stage_name}) at completion. API resumes via graph.astream(Command(resume="approved" | "rejected"), config). services/ updates gate_states mirror after each interrupt.

Service Layer (AD-4): services/ consumes graph.astream() events, updates runs table, and pushes to per-run asyncio.Queue. Pipeline nodes are pure functions — no side-effects to DB or queues.

Shot Mapping (AD-5): ShotData.sentence_indices: list[int] maps each shot to one or more narration sentences (LLM-Director pattern). scenario_node prompts DeepSeek V4 as Director.

A/B Architecture (AD-6): POST /runs/{id}/ab creates a second independent run with same scp_text, prompt_variant="B", ab_pair_id pointing to originating run. No graph-level branching.

Database (AD-7): Use AsyncSqliteSaver (not sync SqliteSaver). Artifact paths live only in PipelineState — no scenes/artifacts table. GET /runs/{id}/stages/{stage}/artifacts reads LangGraph state, not DB.

Artifact Edit (AD-8): PATCH /runs/{id}/stages/{stage}/artifact calls graph.update_state() first, then rewrites artifact file on disk. Valid for scenario and subtitle only.

Conventions:
- Naming: snake_case modules; PascalCase TypedDicts/models; stage literals: scenario, image, tts, subtitle, video
- IDs: UUID v4 strings; never auto-increment integers
- Config: Pydantic BaseSettings; env prefix YTFLOW_
- Langfuse: every node decorated with @observe; span name = stage literal
- SSE: four event types: stage_entry, stage_exit, gate_pending, run_failed
- SCP data: data/scps.json loaded at startup into app.state.scps; no per-request file I/O
- Error shape: FastAPI HTTPException with detail: str; pipeline errors additionally carry stage and run_id

### UX Design Requirements

UX-DR1: Implement Zinc System design tokens — dark mode primary palette (background #1C1C1E, card #2C2C2E, card-hover #323234, border rgba(255,255,255,0.07), foreground #F2F2F7, muted-foreground #8E8E93, subtle-foreground #48484A, primary #0A84FF); light mode swap (background #F2F2F7, card #FFFFFF, primary #007AFF); Tailwind CSS variables wired to shadcn/ui CSS custom properties
UX-DR2: Implement semantic status color pairs — running (#FF9F0A / rgba(255,159,10,0.18)), awaiting (#BF5AF2 / rgba(191,90,242,0.18)), approved (#30D158 / rgba(48,209,88,0.18)), failed (#FF453A / rgba(255,69,58,0.18)); status colors never used as decorative accent
UX-DR3: Implement typography tokens — system-ui/-apple-system body stack (13px/400, lh 1.4, ls -0.01em); Courier New/Consolas/Menlo monospace for SCP IDs and stage tokens; scale: 15px/600 wordmark, 13px body, 12px/700 SCP ID mono, 11px badge/label, 11px muted timestamp
UX-DR4: Implement status-badge component — foreground from status-* token, background from status-*-bg, 11px/500, 6px radius, padding 3px 8px; text + color (never color alone)
UX-DR5: Implement card-row component — card bg, card-hover on hover, border hairline bottom; full-row click → navigate; no nested action buttons
UX-DR6: Implement stage-sidebar-item component — active: 2px primary blue left border, card bg; awaiting: 2px purple left border; inactive: transparent bg; not-yet-reached: muted, not clickable; aria-current="true" on active item
UX-DR7: Dashboard layout — top nav (52px, wordmark + "+ 새 실행" CTA); scrollable card list; awaiting-approval rows sort to top; empty state (centered "실행 없음" + CTA); loading skeleton (4 shadcn Skeleton rows); API error top banner; single column full-width items
UX-DR8: SCP Picker Dialog — shadcn Dialog; search input (debounced 200ms, focused on open); matches: numeric ID ("096" → SCP-096), full ID ("SCP-096"), English nickname (hyphen-normalized descriptive tags, excluding meta tags: _licensebox, scp, _cc, featured, illustrated, rewrite, co-authored, audio); default sort rating desc; row: SCP ID (mono), nickname, object_class, rating (tabular-nums, right-aligned); virtualized list (2000 items); keyboard ↑↓+Enter; role="listbox" + aria-activedescendant; aria-label="SCP 검색" on input
UX-DR9: Run Detail layout — two-column: 240px fixed sidebar + flex-1 main panel; top nav persistent; sidebar scrolls independently; browser history pushed per run, not per stage; back to dashboard via wordmark
UX-DR10: Artifact panel content per stage — scenario: scrollable Korean prose (~65ch width, 1.6 lh); image: 2-col scene grid (image count label); tts: per-scene audio controls (scene index + duration, sorted by scene num); subtitle: SRT in monospace scroll area (subtitle count label); video: full-width video player + download link; not-yet-reached: muted "아직 실행되지 않은 스테이지입니다."; running: spinner + "실행 중…"
UX-DR11: Image lightbox — shadcn Dialog full-screen on image click; ← → keyboard navigation between scenes; Esc closes
UX-DR12: Gate controls — "승인" (cta-primary) + "반려" (outline destructive) in artifact panel footer; visible only when gate_state === 'pending'; disabled + spinner on click; replaced by state label on success; inline error re-enables buttons on API fail
UX-DR13: Retry button — outline "재시도" in panel header (approved, rejected, or failed stages); inline confirmation below button: "이 스테이지를 다시 실행합니까? 확인/취소" with role="alert"; auto-dismiss after 5s of no action; no modal
UX-DR14: Inline text editor — scenario and subtitle stages only; "편집" toggles textarea; "저장" → PATCH artifact endpoint → read mode with updated text; "취소" → read mode no save; unsaved navigate-away: window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")
UX-DR15: SSE progress client — hidden EventSource on /runs/{id}/progress; stage_entry/stage_exit → update sidebar item state; gate_pending → update gate badge (purple border); no toast notifications; all state encoded in sidebar
UX-DR16: A/B comparison view (/runs/{id}/ab) — side-by-side variant A and B artifact display; scores for LLM-as-judge and rule-based metrics; winner indicator
UX-DR17: Accessibility floor — semantic HTML: nav, main, aside, ul/li for sidebar and SCP picker; shadcn focus ring on all interactive elements; color not sole indicator (badge text + color + icon for gate state); native audio controls; aria-current="true" on active stage sidebar item; retry confirmation role="alert"
UX-DR18: Korean UI strings throughout; stage tokens (scenario, image, tts, subtitle, video) displayed in English monospace — they are technical identifiers; operator microcopy: short, active, specific (e.g. "승인 대기" not "파이프라인이 사용자의 확인을 기다리고 있습니다")

### FR Coverage Map

FR-1: Epic 1 — scenario_node: SCP text → structured scene scenario via DeepSeek V4
FR-2: Epic 1 — image_node: shot image prompts via DeepSeek V4 (LLM-Director pattern)
FR-3: Epic 1 — image_node: ComfyUI local HTTP API integration
FR-4: Epic 1 — tts_node: Qwen TTS audio per scene
FR-5: Epic 1 — subtitle_node: forced alignment subtitles
FR-6: Epic 1 — video_node: FFmpeg video composition
FR-7: Epic 1 — resume from last successful node (AsyncSqliteSaver)
FR-8: Epic 1 — full restart option
FR-9: Epic 2 — gate mechanism via LangGraph interrupt()
FR-10: Epic 1 — Langfuse trace span on every node entry/exit (AC in each node story)
FR-11: Epic 1 — LLM call capture: prompt, response, latency, tokens (AC in each node story)
FR-12: Epic 1 — trace spans linked per pipeline run (AC in graph.py story)
FR-13: Epic 1 — failed node surfaces error detail in trace (AC in each node story)
FR-14: Epic 1 — Prompt Hub: migrate all prompts from yt.pipe .tmpl files (Story 1.3, before nodes built)
FR-15: Epic 1 — nodes fetch prompts from Prompt Hub at runtime
FR-16: Epic 1 — prompt change takes effect on next run without code change
FR-17: [no code] — prompt version history visible in Langfuse UI natively; no implementation required
FR-18: Epic 4 — execute pipeline with prompt variant A and B
FR-19: Epic 4 — LLM-as-judge evaluation scoring
FR-20: Epic 4 — rule-based evaluation scoring
FR-21: Epic 4 — combined evaluation result stored in Langfuse
FR-22: Epic 4 — A/B result retrievable via API
FR-23: Epic 4 — automatic winner determination (no manual scoring)
FR-24: Epic 2 — POST /runs
FR-25: Epic 2 — GET /runs/{id}
FR-26: Epic 2 — GET /runs/{id}/artifact
FR-27: Epic 4 — POST /runs/{id}/ab
FR-28: Epic 2 — GET /runs/{id}/stages/{stage}/artifacts
FR-29: Epic 2 — POST /runs/{id}/stages/{stage}/gate
FR-30: Epic 2 — POST /runs/{id}/stages/{stage}/retry
FR-31: Epic 2 — GET /runs
FR-32: Epic 2 — GET /runs/{id}/progress (SSE stream)
FR-33: Epic 2 — GET /scps
FR-34: Epic 2 — PATCH /runs/{id}/stages/{stage}/artifact
FR-35: Epic 1 — SQLite runs table as API projection; AsyncSqliteSaver owns checkpoints
FR-36: Epic 1 — node-level checkpoint persisted after each successful node

FR-37: Epic 3 — Dashboard: run list with status and gate state
FR-38: Epic 3 — Run detail: real-time stage progress via SSE
FR-39: Epic 3 — Stage artifact preview panel (per-stage content)
FR-40: Epic 3 — Stage gate controls (승인/반려)
FR-41: Epic 3 — Stage retry button with inline confirmation
FR-42: Epic 3 — A/B comparison view with scores and winner indicator
FR-43: Epic 3 — Langfuse trace link per run
FR-44: Epic 3 — Inline text editor for scenario and subtitle stages

## Epic List

### Epic 1: Project Foundation & Pipeline Core
Jay가 SCP 텍스트 → 영상까지 Python 모듈로 end-to-end 실행하고 결과물을 얻을 수 있다. Langfuse Prompt Hub에 프롬프트를 먼저 마이그레이션한 후 모든 노드를 구현한다. 각 노드 스토리 AC에 Langfuse @observe span 검증 포함.

**Story sequence:**
1.1 Langfuse 접속 검증 + 환경 설정 [BLOCKER: Langfuse homelab 미접속 시 이후 전체 블로킹]
1.2 프로젝트 스캐폴드 + 도메인 타입 (pyproject.toml, state.py)
1.3 Prompt Hub 마이그레이션 (yt.pipe .tmpl → Langfuse) [depends_on: 1.1]
1.4 LangGraph 그래프 + AsyncSqliteSaver 연결 (graph.py) [depends_on: 1.2, 1.3]
1.5 scenario_node (LLM-Director, ShotData) [depends_on: 1.4]
1.6 image_node [depends_on: 1.5]
1.6b image_node layered assets for character compositing [depends_on: 1.6; unblocks 1.9c]
1.7 tts_node [depends_on: 1.5]
1.8 subtitle_node (YTFLOW_ALIGNER config) [depends_on: 1.7]
1.9 video_node (FFmpeg) [depends_on: 1.8]
1.10 resume (FR-7) + restart (FR-8) + 트레이스 연결 검증 (FR-12)

**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-35, FR-36

---

## Epic 1: Project Foundation & Pipeline Core

Jay가 SCP 텍스트 → 영상까지 Python 모듈로 end-to-end 실행하고 결과물을 얻을 수 있다.

### Story 1.1: Langfuse 환경 검증

As Jay,
I want Langfuse homelab connectivity and all YTFLOW_ environment variables verified before any node is built,
So that Prompt Hub migration and @observe instrumentation have a confirmed foundation.

**Acceptance Criteria:**

**Given** `YTFLOW_LANGFUSE_HOST`, `YTFLOW_LANGFUSE_PUBLIC_KEY`, `YTFLOW_LANGFUSE_SECRET_KEY` are set in `.env`
**When** `python -c "from langfuse import Langfuse; Langfuse().auth_check()"` runs
**Then** returns `True` with no exception

**Given** `config.py` using Pydantic BaseSettings with `YTFLOW_` prefix
**When** the settings object is instantiated
**Then** all Langfuse fields are non-empty and type-validated

**Given** the `.env` file is missing or a key is wrong
**When** `config.py` is loaded
**Then** `ValidationError` is raised with the missing field name

---

### Story 1.2: 프로젝트 스캐폴드 + 도메인 타입

As Jay,
I want the project directory structure, `pyproject.toml`, and all domain TypedDicts initialized,
So that every subsequent story has a consistent import path and shared type system.

**Acceptance Criteria:**

**Given** `pyproject.toml` with `uv` and all pinned dependencies (LangGraph 0.2.x, FastAPI 0.115.x, SQLModel 0.0.21, langfuse 2.x)
**When** `uv sync` runs
**Then** all packages install without conflict

**Given** the Architecture structural seed
**When** `from yt_flow.domain.state import PipelineState, SceneState, ShotData, WordTiming` runs
**Then** all TypedDicts import without error and fields match the Architecture definition exactly

**Given** `src/yt_flow/{domain,pipeline/nodes,services,db,api/routes}/` directories
**When** `find src/yt_flow -type d` runs
**Then** all six directories exist

---

### Story 1.3: Prompt Hub 마이그레이션

As Jay,
I want all pipeline prompts migrated from `yt.pipe/templates/*.tmpl` to Langfuse Prompt Hub,
So that every node fetches prompts at runtime with zero hardcoded strings from day one.

**Acceptance Criteria:**

**Given** `.tmpl` files exist in `/mnt/work/projects/yt.pipe/templates/`
**When** the migration script runs
**Then** Langfuse Prompt Hub contains prompts for: `scenario`, `image_prompt`, and any additional stage prompts found in yt.pipe

**Given** prompts are in Prompt Hub
**When** `langfuse.get_prompt("scenario").compile(scp_text="...")` runs
**Then** returns a non-empty rendered string

**Given** a prompt's text is edited in the Langfuse UI
**When** the next Python process calls `langfuse.get_prompt("scenario")`
**Then** the updated text is returned with no code change or restart required (FR-16)

---

### Story 1.4: LangGraph 그래프 + AsyncSqliteSaver

As Jay,
I want the LangGraph StateGraph compiled with AsyncSqliteSaver and stub nodes in place,
So that checkpoint persistence and the full graph topology are confirmed before real node logic is written.

**Acceptance Criteria:**

**Given** `YTFLOW_DB_PATH` points to `yt_flow.db`
**When** `graph.py` initializes `AsyncSqliteSaver` and compiles `StateGraph`
**Then** no exception; `yt_flow.db` is created on disk

**Given** the Architecture graph structure (scenario → gate_scenario → image → gate_image → tts → gate_tts → subtitle → gate_subtitle → video → gate_video)
**When** `graph.get_graph().nodes` is inspected
**Then** all 10 nodes are present in correct topological order

**Given** a stub run with minimal `PipelineState`
**When** one stub node completes
**Then** `AsyncSqliteSaver.aget_tuple(config)` returns a non-None checkpoint (FR-36)

---

### Story 1.5: scenario_node (LLM-Director)

As Jay,
I want `scenario_node` to produce a structured scene list with shot boundaries from SCP text via DeepSeek V4,
So that downstream nodes receive typed `SceneState` objects with N:M sentence-to-shot mappings.

**Acceptance Criteria:**

**Given** `scp_text` in `PipelineState` and `scenario` prompt in Prompt Hub
**When** `scenario_node` runs
**Then** `PipelineState.scenes` contains ≥1 `SceneState`, each with `narration` (str) and `shots` (list[ShotData] with ≥1 item)

**Given** a `ShotData`
**When** `scenario_node` completes
**Then** `sentence_indices` is a non-empty `list[int]`; `image_prompt` and `negative_prompt` are non-empty strings

**Given** `scenario_node` execution
**When** the LLM call completes
**Then** Langfuse span named `"scenario"` captures: rendered prompt, raw response, latency (ms), input+output token count (FR-10, FR-11)

**Given** DeepSeek V4 returns a malformed response
**When** `scenario_node` attempts to parse it
**Then** `PipelineState.error` is set; Langfuse span captures the exception and inputs at failure point (FR-13)

---

### Story 1.6: image_node

As Jay,
I want `image_node` to submit shot prompts to ComfyUI and write generated images to disk,
So that each `ShotData` has an `image_path` for downstream composition.

*Workflow baseline: `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (animagineXL_v31 + horror_and_creepy LoRA 0.6 + darkness_sdxl_v2 LoRA 0.5; 1216×832; prompt injection at nodes 6/7). Copy from `~/Documents/myWorkflows/` before starting.*

**Acceptance Criteria:**

**Given** ComfyUI running at `YTFLOW_COMFYUI_URL` and workflow JSON in config
**When** `image_node` runs with scenes containing `ShotData.image_prompt`
**Then** each `ShotData.image_path` is set to an existing file under `workspace/{run_id}/images/` (FR-3)

**Given** ComfyUI returns an HTTP error for a prompt
**When** `image_node` encounters it
**Then** `PipelineState.error` is set with `stage="image"` and `run_id`; Langfuse span captures the error detail (FR-13)

**Given** `image_node` execution
**When** it completes
**Then** Langfuse span named `"image"` shows latency and ComfyUI request count (FR-10)

**Given** `YTFLOW_COMFYUI_MOCK=true` in environment
**When** `image_node` runs
**Then** returns fixture images from `tests/fixtures/images/` instead of calling ComfyUI; all downstream AC still pass (test isolation)

---

### Story 1.6b: image_node layered assets for character compositing

As Jay,
I want `image_node` to emit separate background and transparent character image assets per shot,
So that later video effects can animate and composite the character independently from the Ken-Burns background.

**Acceptance Criteria:**

**Given** layered-asset mode is enabled
**When** `image_node` runs for a shot
**Then** `ShotData.background_path` and `ShotData.character_path` point to files under `workspace/{run_id}/images/`, while `ShotData.image_path` remains available for compatibility

**Given** no character layer is available for a shot
**When** `image_node` completes
**Then** `background_path` is set and `character_path` is `None`; downstream rendering can fall back to background-only behavior

**Given** `YTFLOW_COMFYUI_MOCK=true`
**When** `image_node` runs
**Then** mock background and transparent-character fixtures are materialized under the run workspace without calling ComfyUI

**Given** ComfyUI returns an invalid layered output
**When** `image_node` validates outputs
**Then** `PipelineState.error` is set with `stage="image"` and `run_id`; Langfuse records the failure detail

---

### Story 1.7: tts_node

As Jay,
I want `tts_node` to generate per-scene TTS audio via Qwen TTS and capture word timings,
So that each scene has playable audio and timing data for subtitle alignment.

**Acceptance Criteria:**

**Given** `SceneState.narration` for each scene
**When** `tts_node` runs via Qwen TTS cloud API
**Then** `SceneState.audio_path` is set to an existing audio file; `word_timings` is a non-empty `list[WordTiming]` with `word`, `start_sec`, `end_sec` (FR-4)

**Given** Qwen TTS API returns an error
**When** `tts_node` encounters it
**Then** `PipelineState.error` is set with `stage="tts"` and `run_id`; Langfuse span captures the error

**Given** `tts_node` execution
**When** it completes
**Then** Langfuse span named `"tts"` appears with latency and token count (FR-10)

---

### Story 1.8: subtitle_node

As Jay,
I want `subtitle_node` to produce forced-alignment `.srt` files using the audio and known narration text,
So that each scene has a subtitle file with accurate word-level timing.

**Acceptance Criteria:**

**Given** `SceneState.audio_path` and `SceneState.narration` per scene
**When** `subtitle_node` runs forced alignment via `YTFLOW_ALIGNER` config (e.g., `"whisperx"`)
**Then** `SceneState.subtitle_path` is set to an existing `.srt` file with ≥1 subtitle entry (FR-5)

**Given** a different aligner library configured in `YTFLOW_ALIGNER`
**When** `subtitle_node` runs
**Then** it uses the configured aligner without code change (aligner is a config-driven strategy)

**Given** `subtitle_node` execution
**When** it completes
**Then** Langfuse span named `"subtitle"` appears with latency (FR-10)

---

### Story 1.9: video_node

As Jay,
I want `video_node` to compose scene images, audio, and subtitles into a final `.mp4` via FFmpeg,
So that the pipeline produces a deliverable video file.

**Acceptance Criteria:**

**Given** `ShotData.image_path`, `SceneState.audio_path`, and `SceneState.subtitle_path` for all scenes
**When** `video_node` runs FFmpeg subprocess
**Then** `PipelineState.video_path` is set to an existing `.mp4` under `workspace/{run_id}/` (FR-6)

**Given** FFmpeg is not installed or returns non-zero exit code
**When** `video_node` encounters the error
**Then** `PipelineState.error` is set with `stage="video"` and `run_id`

**Given** `video_node` execution
**When** it completes
**Then** Langfuse span named `"video"` appears with latency (FR-10)

---

### Story 1.10: Resume, Restart & Trace Linkage

As Jay,
I want failed runs to resume from the last successful node and full restart to be explicitly supported,
So that I never reprocess already-completed stages and can start clean when needed.

**Acceptance Criteria:**

**Given** a run that failed after `scenario_node` (checkpoint exists in `yt_flow.db`)
**When** the same `run_id` is restarted
**Then** execution resumes from `image_node`; `scenario_node` is not re-executed (FR-7)

**Given** a failed or completed run
**When** the service triggers a full restart
**Then** execution starts from `scenario_node` regardless of existing checkpoint (FR-8)

**Given** a complete pipeline run
**When** the Langfuse trace is inspected
**Then** all five stage spans (`scenario`, `image`, `tts`, `subtitle`, `video`) appear under one parent trace identified by `run_id` (FR-12)

**Given** a resumed run
**When** new spans are created for resumed nodes
**Then** the resumed node spans carry the same Langfuse `trace_id` as the original run; no new root trace is created; all spans are visible under one trace tree in Langfuse (trace continuity, FR-12)

---

## Epic 2: HTTP API & Gate-Controlled Pipeline Execution

Jay가 HTTP API로 파이프라인 실행을 트리거하고, 스테이지별로 아티팩트를 검토한 뒤 승인/반려로 진행을 제어할 수 있다.

### Story 2.1: FastAPI 앱 + SQLModel + 기본 Run CRUD

As Jay,
I want a FastAPI app with the SQLModel `Run` table and basic run management endpoints,
So that I can trigger a pipeline run and query its status via HTTP.

**Acceptance Criteria:**

**Given** FastAPI app startup via lifespan
**When** the app starts
**Then** SQLModel creates the `runs` table in `yt_flow.db` if not exists; `data/scps.json` is loaded into `app.state.scps`

**Given** `POST /runs` with `{"scp_id": "SCP-096", "scp_text": "..."}` (and optionally `"extra": {}`)
**When** called
**Then** returns HTTP 201 with `{"id": "<uuid>", "status": "running", "current_stage": null, ...}` and a row is inserted in the `runs` table; `extra` field is accepted and stored but has no effect in v1 (FR-24)

**Given** `GET /runs`
**When** called
**Then** returns all runs sorted by `started_at` desc with `status`, `current_stage`, `gate_states` (FR-31)

**Given** `GET /runs/{id}` with a valid run_id
**When** called
**Then** returns run metadata including a `langfuse_trace_url` field (FR-25)

**Given** `GET /runs/{id}/artifact` on a completed run
**When** called
**Then** returns HTTP 200 with `Content-Disposition: attachment` header and video file body (FR-26)

**Given** `POST /runs` with `{"scp_id": "SCP-096", "scp_text": "..."}` succeeds
**When** the 201 response is returned
**Then** `asyncio.create_task(run_service.start_run(run_id))` is launched in the background; the task calls `graph.astream()` and drives the pipeline (services layer, AD-4)

**Given** `GET /runs/{id}` with an unknown run_id
**When** called
**Then** returns HTTP 404 with `{"detail": "Run not found"}`

---

### Story 2.2: SSE 인프라

As Jay,
I want a Server-Sent Events endpoint that streams stage and gate events in real time,
So that clients can observe pipeline progress without polling.

**Acceptance Criteria:**

**Given** `GET /runs/{id}/progress` with a valid run_id
**When** connected
**Then** HTTP 200 with `Content-Type: text/event-stream` and `Cache-Control: no-cache` (FR-32)

**Given** a running pipeline stage completes
**When** `services/run_service.py` processes the `graph.astream()` event
**Then** SSE stream emits `event: stage_entry` and `event: stage_exit` with `{"stage": "scenario", "run_id": "..."}` data

**Given** a stage gate triggers `interrupt()`
**When** `services/` processes it
**Then** SSE stream emits `event: gate_pending` with `{"stage": "scenario", "run_id": "..."}`

**Given** a pipeline failure
**When** `services/run_service.py` catches the exception
**Then** SSE emits `event: run_failed` with `{"run_id": "...", "stage": "...", "error": "..."}` before closing; `runs.status` set to `"failed"` (AD-4)

**Given** the SSE client disconnects
**When** the connection drops
**Then** the per-run `asyncio.Queue` is removed from the registry

---

### Story 2.3: Gate 메커니즘

As Jay,
I want stage gates that pause after each stage completion and wait for my explicit approval before the pipeline proceeds,
So that I can review artifacts at every stage before committing to the next.

**Acceptance Criteria:**

**Given** a stage node (e.g., `scenario_node`) completes
**When** the subsequent `gate_scenario` node runs
**Then** `interrupt({"stage": "scenario"})` is called; `runs.status` updates to `"awaiting_approval"`; SSE emits `gate_pending` (FR-9, AD-3)

**Given** `POST /runs/{id}/stages/scenario/gate` with `{"action": "approve"}`
**When** called
**Then** returns HTTP 202 Accepted immediately; `graph.astream(Command(resume="approved"), config)` kicks off in background; SSE `stage_entry` for `image` confirms progression; `gate_states["scenario"]` = `"approved"` in both `PipelineState` and `runs` table (FR-29, AD-3, AD-4)

**Given** `POST /runs/{id}/stages/scenario/gate` with `{"action": "reject"}`
**When** called
**Then** pipeline terminates; `runs.status` = `"failed"`; `gate_states["scenario"]` = `"rejected"`

**Given** `gate_video` node approve completes and the graph reaches END
**When** `run_service` processes the final `graph.astream()` event
**Then** `runs.status` is set to `"complete"`; SSE emits `stage_exit` for `video`

**Given** a gate call on a run not in `awaiting_approval` state
**When** called
**Then** returns HTTP 409 Conflict

---

### Story 2.4: Stage Control — Retry & Inline Artifact Edit

As Jay,
I want to re-run individual pipeline stages and edit stage text artifacts in-place via API,
So that I can correct output without restarting the full pipeline.

**Acceptance Criteria:**

**Given** `POST /runs/{id}/stages/scenario/retry` where `gate_states["scenario"]` is `"approved"`, `"rejected"`, or `"failed"` (error state)
**When** called
**Then** new execution starts from `scenario_node`; SSE emits `stage_entry` for `scenario`; `gate_states["scenario"]` resets to `"pending"` (FR-30)

**Given** `POST /runs/{id}/stages/scenario/retry` where `gate_states["scenario"]` is `"pending"` or the stage has not yet run
**When** called
**Then** returns HTTP 409 Conflict

**Given** `PATCH /runs/{id}/stages/scenario/artifact` with edited text body
**When** called
**Then** `graph.update_state()` persists the edit to the LangGraph checkpoint; artifact file on disk is rewritten; returns HTTP 200 (FR-34, AD-8)

**Given** `PATCH /runs/{id}/stages/video/artifact`
**When** called
**Then** returns HTTP 422 — only `scenario` and `subtitle` are valid patch targets (FR-34)

---

### Story 2.5: Data Access — SCP List & Stage Artifacts

As Jay,
I want to list available SCP entries and retrieve intermediate stage artifacts via API,
So that the UI can populate the SCP picker and display per-stage output.

**Acceptance Criteria:**

**Given** `GET /scps`
**When** called
**Then** returns list from `app.state.scps` (in-memory, loaded at startup) with `id`, `nickname`, `object_class`, `rating`; no per-request file I/O (FR-33)

**Given** `GET /runs/{id}/stages/image/artifacts` on a completed image stage
**When** called
**Then** returns artifact data by reading LangGraph state — not the `runs` table (FR-28, AD-7)

**Given** `GET /runs/{id}/stages/scenario/artifacts` on a stage not yet reached
**When** called
**Then** returns HTTP 404

---

### Story 2.6: 게이트 reject가 image_node의 재개 캐시를 무력화하는 문제 수리

Jay 시청 피드백(2026-07-09) 조사 중 코드로 확정: `POST /stages/{stage}/gate {"action":"reject"}`가 `resume_run`을 거쳐 그래프 조건부 라우팅(`graph.py` `_REJECT_TARGET`)으로 **같은 스테이지 노드를 즉시 재진입**시키는데(`gate 승인/거부` 자체가 재실행을 트리거하는 설계), 이 경로는 `retry_stage`(2.4, `POST /stages/{stage}/retry`)가 하는 `_nullify` 호출을 거치지 않음. 그 결과 image_node의 5.14 재개 캐시(`_existing_complete_shot` — 디스크의 사이드카+PNG가 있고 프롬프트가 그대로면 스킵)가 모든 샷을 "이미 완료됨"으로 보고 **재생성 없이 그대로 통과**시킴 — "이미지가 마음에 안 들어 reject" 해도 바이트 단위로 동일한 결과가 나옴(수동으로 workspace 파일을 지워야만 실제 재생성됨, iteration-1에서 이 방식으로 우회). 두 액션(거부 클릭 vs 재시도 버튼 클릭)이 사용자에겐 동일한 의도("다시 만들어")인데 한쪽만 동작하는 비일관성. 수정: `resume_run`이 `decision == "rejected"`일 때 `retry_stage`와 동일한 `_nullify(stage, ...)` 호출을 거치도록 — 그래프 라우팅이 재진입하는 stage 노드가 실제로 빈 상태에서 시작하게 함. 범위는 image_node뿐 아니라 같은 디스크-캐시 재개 패턴을 쓰는 모든 스테이지(현재는 image만 해당 — video.py는 다른 존재-체크 패턴). (draft — 상세 스토리 파일은 create-story로 별도 생성)

---

## Epic 3: React SPA — Pipeline Control UI

Jay가 브라우저에서 파이프라인 전체를 조작할 수 있다 — 실행 시작, 아티팩트 리뷰, 스테이지 승인, 재시도, 인라인 편집.

### Story 3.1: Zinc 디자인 토큰 + shadcn/ui + Tailwind

As Jay,
I want the React project bootstrapped with Zinc System design tokens and shadcn/ui configured,
So that all subsequent UI components use a consistent, spec-compliant visual foundation.

**Acceptance Criteria:**

**Given** `frontend/` initialized with React 18, Tailwind CSS, shadcn/ui
**When** `npm run build` runs
**Then** build succeeds and output lands in `frontend/dist/`; FastAPI serves it at `/app`

**Given** DESIGN.md dark-mode color tokens
**When** CSS custom properties are defined in `globals.css`
**Then** `--background: #1C1C1E`, `--card: #2C2C2E`, `--primary: #0A84FF` are present; `prefers-color-scheme: light` triggers the light-mode swap (`--background: #F2F2F7`, `--primary: #007AFF`) (UX-DR1)

**Given** status color token pairs
**When** inspecting the CSS
**Then** four status pairs exist: running (`#FF9F0A` / `rgba(255,159,10,0.18)`), awaiting (`#BF5AF2` / `rgba(191,90,242,0.18)`), approved (`#30D158` / `rgba(48,209,88,0.18)`), failed (`#FF453A` / `rgba(255,69,58,0.18)`) (UX-DR2)

**Given** typography tokens in `globals.css`
**When** body text renders
**Then** font is `system-ui, -apple-system` at 13px/400; `font-mono` class resolves to `'Courier New', Consolas, Menlo` (UX-DR3)

---

### Story 3.2: 공통 컴포넌트 (StatusBadge, CardRow, StageSidebarItem)

As Jay,
I want the core shared components built and spec-verified,
So that every screen renders consistently without per-screen duplication.

**Acceptance Criteria:**

**Given** `<StatusBadge status="running" />`
**When** rendered
**Then** amber foreground on amber-tinted background; 11px/500; 6px border-radius; badge text is present (not color-only) (UX-DR4)

**Given** `<CardRow>` item on hover
**When** pointer enters
**Then** background transitions to `#323234`; hairline `rgba(255,255,255,0.07)` bottom border visible (UX-DR5)

**Given** `<StageSidebarItem stage="image" gateState="pending" />`
**When** rendered
**Then** 2px `#BF5AF2` (purple) left border (UX-DR6)

**Given** `<StageSidebarItem stage="scenario" active={true} />`
**When** rendered
**Then** 2px `#0A84FF` left border and `aria-current="true"` attribute (UX-DR6, UX-DR17)

**Given** a stage not yet reached
**When** `<StageSidebarItem>` renders
**Then** item is muted; `pointer-events: none`; not clickable (UX-DR6)

---

### Story 3.3: 대시보드 + SCP Picker Dialog

As Jay,
I want the Dashboard run list and SCP Picker dialog working end-to-end,
So that I can see all my runs at a glance and start a new run by selecting an SCP.

**Acceptance Criteria:**

**Given** runs exist in the API
**When** the dashboard loads at `/`
**Then** runs listed sorted by `started_at` desc; `awaiting_approval` runs float to top (FR-37, UX-DR7)

**Given** no runs exist
**When** the dashboard loads
**Then** centered "실행 없음. 새 실행을 시작하세요." with primary CTA (UX-DR7)

**Given** API is unreachable
**When** the dashboard loads
**Then** top banner: "서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요." (UX-DR7)

**Given** "+ 새 실행" is clicked
**When** the SCP Picker Dialog opens
**Then** search input is focused; list loaded from `GET /scps` sorted by rating desc; rows show SCP ID (mono), nickname, object_class, rating (tabular-nums, right-aligned) (UX-DR8)

**Given** user types `"096"` (debounced 200ms)
**When** filtering runs
**Then** only SCPs with numeric ID `"096"` appear (UX-DR8)

**Given** user navigates with ↑↓ and presses Enter
**When** SCP-096 is confirmed
**Then** `POST /runs` is called; dialog closes; new run row appears at top with "실행 중" badge (UX-DR8)

**Given** SCP list with 2000 items
**When** dialog renders
**Then** list is virtualized — no DOM nodes for off-screen items (UX-DR8)

---

### Story 3.4: 런 상세 레이아웃 + 아티팩트 패널

As Jay,
I want the Run Detail page with sidebar navigation and per-stage artifact panels,
So that I can inspect generated content for any pipeline stage.

**Acceptance Criteria:**

**Given** navigating to `/runs/{id}`
**When** the page loads
**Then** two-column layout: 240px fixed sidebar + flex-1 main panel; top nav persistent; `<nav>`, `<main>`, `<aside>` semantic elements present (FR-38, UX-DR9, UX-DR17)

**Given** `scenario` stage selected in sidebar
**When** artifact panel renders
**Then** scrollable Korean prose at ~65ch line width, 1.6 line-height (UX-DR10)

**Given** `image` stage selected
**When** artifact panel renders
**Then** 2-col scene image grid with image count label; click any image → fullscreen lightbox (UX-DR10, UX-DR11)

**Given** image lightbox is open
**When** ← or → key pressed
**Then** navigates between scene images; Esc closes (UX-DR11)

**Given** `tts` stage selected
**When** artifact panel renders
**Then** per-scene native `<audio controls>` with scene index and duration, sorted by scene number (UX-DR10)

**Given** `video` stage selected
**When** artifact panel renders
**Then** full-width `<video controls>` player + download link below (UX-DR10)

**Given** a stage not yet reached
**When** sidebar item renders
**Then** muted, not clickable; panel shows "아직 실행되지 않은 스테이지입니다." (UX-DR10)

**Given** active SSE connection on `/runs/{id}/progress`
**When** `stage_entry` event fires
**Then** sidebar item state updates in real time without page reload (FR-38, UX-DR15)

---

### Story 3.5: 게이트 컨트롤 + 재시도 + 인라인 에디터 + SSE 클라이언트

As Jay,
I want stage approval controls, retry, and inline text editing wired to the API,
So that I can fully control pipeline progression from the browser.

**Acceptance Criteria:**

**Given** stage `gate_state === "pending"`
**When** artifact panel footer renders
**Then** "승인" (primary) and "반려" (outline destructive) buttons visible (FR-40, UX-DR12)

**Given** "승인" or "반려" clicked
**When** API call in flight
**Then** both buttons disabled with spinner; on success buttons replaced by state label; on API failure buttons re-enable with inline error below (UX-DR12)

**Given** stage `gate_state === "approved"` or `"rejected"`
**When** panel header renders
**Then** "재시도" outline button visible (FR-41, UX-DR13)

**Given** "재시도" clicked
**When** inline confirmation appears below button
**Then** "이 스테이지를 다시 실행합니까? 확인 / 취소" with `role="alert"`; auto-dismisses after 5s of no action (UX-DR13)

**Given** `scenario` or `subtitle` stage panel
**When** "편집" clicked
**Then** textarea replaces read view; "저장" calls `PATCH` and returns to read mode with updated text; "취소" reverts without saving (FR-44, UX-DR14)

**Given** unsaved edits in panel
**When** user navigates to another stage
**Then** `window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")` fires (UX-DR14)

**Given** Langfuse trace link
**When** clicked
**Then** opens in a new browser tab (FR-43)

---

### Story 3.6: A/B 비교 뷰 + 접근성 플로어

As Jay,
I want the A/B comparison view and full accessibility compliance,
So that I can evaluate prompt variants visually and the tool meets keyboard and screen-reader standards.

**Acceptance Criteria:**

**Given** a run with a completed `ab_pair_id`
**When** `/runs/{id}/ab` is loaded
**Then** side-by-side panels show Variant A and B artifacts with LLM-as-judge + rule-based scores and winner indicator (FR-42, UX-DR16)

**Given** any interactive element
**When** focused via keyboard Tab
**Then** shadcn default focus ring is visible (UX-DR17)

**Given** a status badge
**When** rendered
**Then** badge text AND color used — color is never the sole indicator (UX-DR17)

**Given** SCP Picker dialog
**When** open
**Then** `role="listbox"`, `aria-activedescendant` on results list, `aria-label="SCP 검색"` on the search input (UX-DR17)

**Given** retry inline confirmation
**When** it appears
**Then** `role="alert"` so screen readers announce it (UX-DR17)

**Given** all UI labels and buttons
**When** inspected
**Then** all copy is Korean; stage tokens (`scenario`, `image`, `tts`, `subtitle`, `video`) display in English monospace (UX-DR18)

---

### Story 3.8: 컨트롤 UI 결함 수리 (2026-07-06 E2E 베이스라인 발견분)

실제 Playwright 사용자 시뮬레이션에서 발견된 UI 결함 4건. ① **[D9-major]** run failed 상태에서 실패 스테이지의 "재시도" 버튼 클릭이 네트워크 요청을 전혀 발생시키지 않음(아티팩트 GET 404 상태에서 핸들러 무반응) — API `POST /stages/{stage}/retry`는 정상이므로 프론트 배선 문제. ② **[D4]** `/app/runs/{id}` 딥링크 직접 진입 시 404 — static mount SPA fallback 부재. ③ **[D7]** 게이트 승인 후 재개된 장시간 스테이지 동안 `/runs/{id}`가 이전 상태(awaiting_approval/이전 stage)를 반환해 UI가 "승인 대기"로 오표기(재시도 경로는 정상 표기 — 승인-재개 경로 한정). ④ **[D14]** 자막 패널이 내용을 렌더하면서 "자막 0개"로 카운트 표기. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 4: A/B Evaluation

Jay가 동일 SCP 입력으로 두 프롬프트 변형을 자동 비교하고, 수동 채점 없이 승자를 얻을 수 있다.

<!-- OQ-1/OQ-6 resolved in planning session via web research. No story required. PRD Open Items updated. -->

### Story 4.1: A/B 실행 생성

As Jay,
I want to trigger a second independent pipeline run as Variant B for A/B comparison,
So that I can compare two prompt variants against the same SCP input.

**Acceptance Criteria:**

**Given** a completed run `{id}`
**When** `POST /runs/{id}/ab` is called
**Then** returns HTTP 201 with a new run `id`; new run has `scp_text` copied from original, `prompt_variant="B"`, `ab_pair_id` pointing to `{id}` (FR-27, AD-6)

**Given** the new Variant B run
**When** it executes
**Then** uses the same graph and pipeline as any standard run — no graph-level branching (AD-6)

**Given** `POST /runs/{id}/ab` on a run still in `"running"` status
**When** called
**Then** returns HTTP 409 Conflict

**Given** both A and B runs in the `runs` table
**When** `GET /runs` is called
**Then** both appear with `ab_pair_id` linking them (FR-18)

---

### Story 4.2: 평가 서비스 (LLM-as-judge + 규칙 기반)

As Jay,
I want the A/B evaluation service to score both runs using the OQ-1 rubric and OQ-6 pairwise method,
So that the comparison is automated and reproducible without manual scoring.

**Acceptance Criteria:**

**Given** two completed runs linked by `ab_pair_id`
**When** `eval_service.evaluate_ab(run_a_id, run_b_id)` runs
**Then** LLM-as-judge scores each run on 3 axes (Atmosphere, Narrative coherence, Article fidelity) with integer 1–5 scores; each axis evaluated 3 times and averaged (FR-19, OQ-1)

**Given** both runs scored
**When** rule-based evaluation runs
**Then** structural metrics computed: scene count match rate, avg subtitle sync error (seconds/word), audio duration variance (% per scene) (FR-20)

**Given** pairwise LLM comparison
**When** position bias mitigation runs
**Then** A→B order and B→A order both evaluated; contradictory results trigger a 3rd tiebreaker run (OQ-6)

**Given** either run scores < 2/5 on any axis
**When** winner determination runs
**Then** that run is flagged as below quality floor; if both fail, result is `{"winner": null, "reason": "both_below_floor"}` (OQ-6)

**Given** `eval_service.evaluate_ab()` is called
**When** it runs
**Then** total execution completes in ≤5 minutes; each individual LLM judge call has a 30-second timeout with retry-once on timeout

---

### Story 4.3: 결과 저장 + API 조회 + 자동 승자 결정

As Jay,
I want A/B evaluation results stored in Langfuse and retrievable via API with an automatic winner,
So that I can query the outcome programmatically and from the UI.

**Acceptance Criteria:**

**Given** `eval_service` produces scores and pairwise result
**When** results are saved
**Then** a Langfuse trace is created with both runs' scores as observations (FR-21)

**Given** `GET /runs/{id}` where `{id}` is part of an A/B pair
**When** called after evaluation completes
**Then** response includes `ab_result` with axis scores, pairwise winner, rule-based scores, and determined winner (FR-22)

**Given** pairwise yields a clear winner (2/3 majority or rule-based tiebreak)
**When** `GET /runs/{id}` called
**Then** `ab_result.winner` is `"A"` or `"B"` with no manual input required (FR-23)

**Given** both runs pass quality floor but pairwise and rule-based are equal
**When** result is stored
**Then** `ab_result.winner` is `"tie"` — system reports the result rather than forcing a verdict

**FRs covered:** FR-18, FR-19, FR-20, FR-21, FR-22, FR-23, FR-27

## Epic 5: 영상 품질 고도화

**Goal:** 첫 실전 렌더(2026-07-03, run eb522cf9 / SCP-096) 리뷰에서 나온 품질 피드백 5건을 스테이지별로 해소한다. 상세 AC는 각 스토리 파일(`_bmad-output/implementation-artifacts/5-*.md`) 참조.

**권장 순서:** 5.1(즉효) → 5.2(임팩트 최대, 1.6b/1.9c 기구현 코드 활성화) → 5.3 → 5.4 → 5.5(A/B 검증 필요).

### Story 5.1: 장면 전환 개선 — 암전 전환 + 챕터 카드

씬 경계의 크로스페이드(이미지 겹침)를 `fadeblack` 암전으로 교체하고, 씬 사이 1.5~2초 챕터 타이틀 카드를 삽입한다 (`YTFLOW_CHAPTER_CARDS`, 기본 on).

### Story 5.2: 레이어드 에셋 실전 가동

1.6b/1.9c로 구현 완료된 투명 캐릭터 오버레이 파이프라인을 실전 가동한다. 코드가 아니라 에셋+설정 문제: 배경 제거 노드를 포함한 2-출력 ComfyUI 워크플로우 작성 + `YTFLOW_COMFYUI_LAYERED=true` 배선 + 라이브 검증.

### Story 5.3: 모션 강화

Ken Burns zoom/pan 강도를 현행 미세 드리프트(1.0→1.005)에서 체감 3배 이상으로 상향하고, 씬 인덱스 기반 결정적 효과 로테이션(zoom-in/out, pan 방향)으로 단조 반복을 제거한다.

### Story 5.4: TTS 한국어 자연화

scenario 체인 끝에 `tts_normalize` 스테이지를 추가해 오독 유발 표현("한 연구원"→붙여 읽힘)을 낭독 친화적으로 재작성한다. 자막·TTS 동일 텍스트 유지, 문장 수 불변(shot 1:1 계약 보존).

### Story 5.5: 비주얼 정합성

visual_breakdown에 스토리 로그라인 + 씬 역할 + 개체 시각 정의서(entity sheet)를 주입해 이미지-서사 정합성을 높인다 (Phase 1). 불충분 시 SCP 위키 공식 이미지(CC BY-SA)를 IPAdapter 참조로 사용 (Phase 2). 완료 판정은 Epic 4 A/B 평가. ※ 일반 웹검색 이미지 img2img 방식은 저작권/일관성 리스크로 보류 (deferred-work.md 2026-07-03 항목).

### Story 5.6: 레이어드 캐릭터 컷아웃 품질

5.2 라이브 검증(run `bed3b329-b7d1-4cf3-b37f-f40d086765b5`, 2026-07-04)에서 rembg(u2net) 배경 제거가 72/72 샷에서 포맷상 정상(RGBA, alpha 채널 존재)으로 동작함을 확인했으나, 컷아웃 **품질**(알파 경계 halo/톱니, 전신 대비 클로즈업 편중 프레이밍)은 별도로 검증되지 않았다. `data/workflows/README-layered-assets.md`에 이미 후보로 언급된 더 나은 세그멘테이션 노드(ComfyUI-RMBG/BiRefNet, Inspyrenet)와 비교 평가하여 필요 시 교체한다. 5.5(프롬프트 정합성)·5.3(모션 강도)과는 관심사가 달라 별도 스토리로 분리— 이 스토리는 오직 "ComfyUI가 캐릭터를 얼마나 깨끗하게 잘라내는가"만 다룬다.

### Story 5.7: 레이어드 배경 이중노출 제거

5.5 라이브 A/B 리뷰(2026-07-04, SCP-096)에서 발견: 배경과 캐릭터 컷아웃이 동일한 ComfyUI 생성 프레임에서 나와(`data/workflows/README-layered-assets.md`가 "intentional"로 명시), 배경에 개체가 원본 그대로 남은 채로 캐릭터 오버레이가 그 위에 또 그려져 화면에 개체가 두 번 보임. 배경에서 개체를 제거(인페인팅 등)하는 워크플로우 수정.

### Story 5.8: SCP 개체 검색 기반 레퍼런스 자동 생성

1.11~1.13이 이미 구현한 "DuckDuckGo 검색 → Vision LLM 멀티앵글 생성 → LLM 앵글 선택" 파이프라인이 `CharacterModel`이 사전에 존재해야만 동작(`character_service.py::select_character_angles`)하는데, 이 레코드 생성이 Character Management UI(3.7)를 통한 수동 절차라 실제 라이브 run에서 한 번도 자동 발동하지 않았음. 런 시작 시 자동으로 트리거하도록 배선.

### Story 5.9: 전환 구간 오디오 연속성

5.1이 씬 경계를 `fadeblack` 암전으로 바꾸면서 오디오 crossfade(`acrossfade`)를 비디오 전환과 동일 `XFADE_DURATION`으로 묶어 유지했는데, 이로 인해 컷마다 나레이션 오디오 볼륨이 같이 페이드됨. 비디오 전환은 그대로 두고 오디오만 연속 재생 또는 무음 갭으로 분리.

### Story 5.10: 엔티티 레퍼런스 파이프라인 복구 (SCP 위키 우선 + 캐릭터 워크플로우 저작)

5.8 라이브 검증(2026-07-04)에서 발견된 기존 블로커 2건 수리. (1) 1.11의 `image_search.py`가 치는 DuckDuckGo 비공식 스크레이핑 엔드포인트(`i.js`)가 실환경에서 재현 가능하게 `403 Forbidden` — 검색 대신 **SCP 위키 공식 이미지 우선 fetch**(`scp_id`로 페이지 URL 결정적 도출, CC BY-SA 출처 메타데이터 보존)로 교체하고 이미지 검색은 위키에 이미지가 없을 때의 fallback으로 강등. (2) `Settings.character_comfyui_workflow_path` 기본값인 `data/workflows/comfyui_character_multi_angle_api.json`이 **디스크에 존재하지 않고**, `character_image_provider.py`의 내장 `_default_workflow()`도 실제 ComfyUI가 `prompt_outputs_failed_validation`으로 거부 — 1.12의 멀티앵글 캐릭터 생성은 실제 ComfyUI에서 한 번도 성공한 적 없음. 5.7이 레이어드 워크플로우를 검증한 방식대로, 이미 검증된 레이어드 SDXL 워크플로우에서 파생(동일 체크포인트/LoRA 노드 구조)해 레퍼런스 이미지 컨디셔닝(IPAdapter) + 앵글별 프롬프트 주입을 붙인 워크플로우 JSON을 저작하고 실제 로컬 ComfyUI로 4앵글 생성을 검증. DoD: 5.8 AC1의 낙관 경로(레퍼런스 확보 → 멀티앵글 생성 → 앵글 선택 → `character_path` 반영)를 실제 run에서 end-to-end 라이브 재검증. 주의: 5.8 리뷰가 추가한 실패-시-롤백(`delete_character`) 계약과 A/B 동시성 처리를 깨지 말 것. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.11: 세그멘테이션 실패 샷 단위 폴백

5.7 완료 시점에 문서화된 미해결 결합: 레이어드 파이프라인의 세그멘테이션/인페인트 패스가 한 샷에서 실패하면 run 전체가 실패함. 샷 단위 graceful fallback으로 전환 — 실패한 샷만 레이어드를 포기하고 합성 전 플랫 프레임으로 컴포즈, run은 계속 진행, 경고를 state에 기록해 image 게이트 아티팩트 패널에서 사람이 확인 가능하게. AD-10(보조 실패 non-fatal)·5.8의 `fallback: true` 시맨틱과 일관되며, 결과가 마음에 안 들면 기존 2.4 스테이지 retry로 image 스테이지만 재시도하는 운영 흐름을 전제. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.12: 캐릭터 생성 프롬프트 콘텐츠 복구 (Vision 디스크립터 배선 + Langfuse 브레이스 버그)

5.10 라이브 검증(2026-07-05, 신규 `SCP-1471` end-to-end run)에서 발견된, 워크플로우/메커니즘이 아니라 **프롬프트 콘텐츠** 계층의 결함 2건. (1) `CharacterService.enrich_descriptor_from_references`(1.11이 만든 Vision LLM 디스크립터 추출)가 `run_service._ensure_character_reference`(5.8의 자동 트리거)에서 한 번도 호출되지 않음 — 그 결과 자동 생성된 캐릭터의 `visual_descriptor`는 항상 빈 값이고, 캐릭터 정체성은 오직 IPAdapter의 이미지 컨디셔닝에만 의존, 프롬프트 텍스트에는 실제 레퍼런스 이미지에 대한 설명이 전혀 없음. (2) Langfuse Prompt Hub의 `"character-generation"` 프롬프트가 `{angle}` 싱글 브레이스 문법을 쓰는데 Langfuse SDK `TextPromptClient.compile()`은 `{{angle}}` 더블 브레이스만 치환 — 라이브 검증에서 4개 앵글 중 2쌍이 완전히 동일한(치환 안 된) 프롬프트 텍스트를 받아 바이트 단위로 동일한 이미지가 생성되는 것으로 재현 확인. `docs/PROMPT_POLICY.md` 절차(레포 파일이 source of truth, production/candidate 라벨만, Langfuse UI 직접 편집 금지)를 따라 프롬프트 콘텐츠를 수정. 선택 확장: DDG 폴백 후보 중 올바른 캐릭터를 Vision LLM으로 선별하는 단계(1.13의 앵글 선택 LLM과 유사) 추가 검토 — 위키가 주 소스가 된 이후 DDG는 폴백 경로일 때만 트리거되므로 낮은 우선순위. 5.10의 가드레일과 동일하게 `select_character_angles`의 tri-state 계약과 5.8의 롤백/동시성 계약은 건드리지 않음. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.13: 캐릭터 Vision LLM 프로바이더 교체 (DeepSeek → Qwen-VL)

5.12 라이브 재검증(2026-07-05, 신규 `SCP-682`)에서 발견: `CharacterService.enrich_descriptor_from_references`(1.11)가 호출은 정상적으로 되지만(5.12가 배선 완료), 실제 DeepSeek 호출이 `400 Bad Request: unknown variant "image_url", expected "text"`로 실패 — 계정에 등록된 모델(`deepseek-v4-flash`, `deepseek-v4-pro`, `/models`로 라이브 확인)이 둘 다 텍스트 전용이며, DeepSeek 공식 호스팅 API 자체가 비전(이미지 입력) 엔드포인트를 제공하지 않음. 모델 이름 교체로 해결 불가 — 비전 지원 프로바이더로 교체 필요. 이 프로젝트가 Qwen TTS용으로 이미 보유한 DashScope 계정/키(`YTFLOW_QWEN_TTS_API_KEY`, `qwen_tts_endpoint` 패턴)로 Qwen-VL을 붙이면 신규 계정 없이 해결 가능. 범위는 `enrich_descriptor_from_references`의 HTTP 호출 + 모델/엔드포인트 설정에 한정 — ComfyUI/IPAdapter 캐릭터 생성 경로, `run_service._ensure_character_reference`의 배선(5.12에서 이미 완료), Langfuse 프롬프트 콘텐츠(5.12에서 이미 수정)는 건드리지 않음. DoD: 실제 레퍼런스 이미지로 `visual_descriptor`가 실제로 채워지는 것을 라이브로 검증 — 5.12가 프로바이더 결함으로 끝까지 확인하지 못했던 AC1 경로의 마지막 조각. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.14: 파이프라인 복원력 — 샷 단위 재개 + ComfyUI 헬스체크

2026-07-06 E2E 베이스라인(run `272b05a4`) 결함 D6/D8. ① `image_node` 재시도 시 이미 온전히 생성된 샷(배경+캐릭터 쌍 존재) 스킵 — ROCm 크래시(`hipErrorIllegalAddress`, 39/59샷 지점) 재시도에서 78장(~40분 GPU 시간)이 전량 재생성됨. ② ComfyUI 요청 전 헬스체크 + 연결 계열 에러 한정 짧은 대기 후 2~3회 재시도. ③ 짝으로 ComfyUI `run.sh`에 크래시 자동 재기동 와치독(인프라, repo 밖). Epic 8 전환 이후에도 유효한 복원력 작업. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.15: mood 배선 수정 — writing 자유형 mood가 Epic 7 다양성을 무력화

2026-07-06 E2E 베이스라인 결함 D1(major)/D2. structure 프롬프트는 mood enum(dread/clinical/escalation/revelation)을 강제하지만 `scenario_chain.py:372`가 **writing 출력**에서 mood를 읽음 — writing이 자유형 mood("shock", "mystery", "awe mixed with dread"...)를 재발명해 8/8씬 전부 유효값이 아니었고 → `resolve_mood` 폴백으로 전 씬 dread 수렴 → 7-1 BGM/7-2 그레이드/7-4 전환의 mood 다양성이 라이브에서 관찰 불가. 수정: mood를 structure 출력에서 읽거나 체인에서 enum 정규화(+비유효값 로깅). 부수: 아티팩트 API scene 직렬화에 mood 노출(D2)해 게이트에서 사람이 검수 가능하게. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.16: 전환 경계 무결성 — 오버랩 제거 + 검은 공백

2026-07-06 베이스라인 영상 Jay 시청 피드백 #2. xfade 기반 조인이 이전 세그먼트의 마지막 `XFADE_DURATION`을 다음 씬과 **겹쳐 소비**해 전환 직전 이미지와 나레이션 끝이 잘려 보임/들림(5-9의 adelay+amix 오디오도 동일 오프셋을 공유). 오버랩 계열 전환을 폐기하고 **페이드아웃 → 검은 홀드(짧은 공백) → 페이드인** + 오디오 무겹침(나레이션 완전 재생 후 전환 시작)으로 교체. `_join_with_xfade`의 running_offset 산식이 단순 concat 계열로 단순화되는 부수 효과. 주의: 7-4(mood별 xfade 타입 다양화)와 정면 충돌 — 검은 공백 구조 안에서 mood 변주를 유지할지(페이드 길이/커브 변주 등) 7-4 축소·재정의를 이 스토리에서 결정해야 함. 챕터 카드가 있는 경계는 카드 자체가 검은 공백 역할이므로 이중 공백이 생기지 않게 통합. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.17: 챕터 카드 콘텐츠 — 씬 제목 + 상황 한 줄

2026-07-06 베이스라인 영상 Jay 시청 피드백 #4. 현재 챕터 카드는 검은 화면에 "- N -" 숫자뿐이라 씬이 바뀔 때 이야기 전개가 뜬금없음. 카드에 **씬 제목 + 상황 설명 한 줄**(예: "첫 면담 — 개체가 입을 열다")을 drawtext로 렌더. 텍스트 산출은 scenario 단계 소관: structure 출력이 이미 씬 구조를 알고 있으므로 씬별 `title`(+한 줄 요약) 필드를 SceneState에 추가하고 카드 렌더러가 소비. 프롬프트 변경은 PROMPT_POLICY 준수. 5-16(전환 경계)과 같은 코드 영역(카드 세그먼트 생성)을 만지므로 5-16 직후 착수 권장. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.18: 자막 원문 표기 — 표시 텍스트/TTS 텍스트 이중 트랙

2026-07-06 베이스라인 영상 Jay 시청 피드백 #3. 자막이 TTS 발음 정규화문("에스시피 공사 구", "키 일점 구 미터")을 그대로 보여줌 — 자막은 **원문 표기(SCP-049, 1.9m)**여야 함. 5-4가 YAGNI로 선택했던 "SRT/TTS 동일 텍스트" 결정을 명시적으로 뒤집는 스토리: 문장 단위 이중 트랙 도입 — `tts_normalize` 단계가 정규화문과 함께 **원문을 보존**하고(문장 1:1 계약 유지), TTS/정렬은 정규화문을, 자막(.ass/.srt)은 원문을 사용. 추가 결정(Jay, 2026-07-06): **가라오케 단어 하이라이트(7-5) 은퇴** — D12 균일 타이밍 폴백으로 동기화가 어차피 가짜였고, 다큐 나레이션 관행은 정적 라인 + 강한 타이포그래피. 대신 자막 폰트/스타일 업그레이드: Pretendard Bold(OFL, repo 번들 `data/fonts/` + ffmpeg `fontsdir`), 흰 채움 + 검은 아웃라인 + 섀도, 크기 상향, 최대 2줄. 부수 효과로 발화↔표시 어절 매핑 문제와 whisperx 단어 정렬 의존이 소멸. 5-17 카드 타이틀도 동일 폰트 패밀리로 통일. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.19: DDG 이미지 검색 폴백 수리 — vqd 획득 경로 갱신

2026-07-07 라이브 재현 테스트로 원인 규명: 5-8/5-10에서 재현된 `i.js` 403은 환경 차단이 아니라 **vqd 토큰 획득 방식이 구식**이어서임. yt.pipe(Go)와 yt.flow(`image_search.py`) 모두 duckduckgo.com 홈페이지에서 vqd를 긁는데, 현재 DDG는 홈페이지에 vqd를 내려주지 않음 — **쿼리 페이지**(`/?q=<query>&iax=images&ia=images`)에서 vqd 획득 + 브라우저 UA + `Referer: https://duckduckgo.com/` 헤더 조합으로 `i.js`가 200 + 실제 결과를 반환함(이 환경에서 실측 확인). 수정 범위: `_acquire_vqd`의 대상 URL 변경 + Referer 헤더 추가 + 회귀 테스트(MockTransport 패턴). 효과: 위키 미스 시 폴백 경로 복구, 8-5 스타일 앵커 소싱 자동화 옵션 확보. 비공식 엔드포인트라 재파손 가능성은 상수 — 폴백 지위 유지(위키 우선 불변). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.20: CC BY-SA 크레딧 자동화 — 엔딩 카드 + 설명란 텍스트

SCP 콘텐츠 상업화(수익화)의 라이선스 준수 자동화(Jay, 2026-07-07). SCP 위키 콘텐츠는 CC BY-SA — 원작 표기 + 동일 라이선스 고지 의무. ① video_node 마지막에 **엔딩 크레딧 카드**(2~3초): "Based on 'SCP-XXX' from the SCP Foundation Wiki / CC BY-SA 3.0" + 문서 URL, 5-17 카드 렌더러·Pretendard 재사용. ② run 산출물에 **`description.txt` 아티팩트**: 유튜브 설명란용 표기 블록(문서 링크, 라이선스 링크, 파생물 고지, 사용된 위키 이미지 출처 — 5-10이 이미 CC BY-SA 출처 메타데이터를 보존함) — 게이트에서 복사해가면 됨. 저자명은 위키 페이지에서 확보 가능하면 포함, 불가하면 문서 링크로 충분(위키 관례). 비치명적 — 크레딧 생성 실패가 run을 죽이지 않음. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.21: TTS 보이스 클론 배선 + 배속 설정

Jay 지시(2026-07-07). `.env`의 클론 변수(`CLONE_MODEL`/`CLONE_VOICE_PATH`)가 Settings에 선언조차 없는 죽은 설정임을 베이스라인 후속 확인에서 발견 — 나레이션은 스톡 보이스(Cherry)로 나가고 있었음. ① 클론 배선: DashScope 보이스 등록(1회성·영구 voice id, `scripts/seed_voice_clone.py` idempotent)+ `qwen3-tts-vc` 합성, 명시적 `clone_enabled` 스위치(기본 OFF — 켰는데 voice id 없으면 시끄럽게 실패, 무음 폴백 금지). ② **배속**: API에 숫자 배속 파라미터 부재 확인 → ffmpeg `atempo` 후처리, `YTFLOW_QWEN_TTS_SPEED` 기본 **1.2**(범위 검증 0.5~2.0), duration 측정 전 적용이라 자막·전환·씬 길이 자동 적응. DoD: 동일 나레이션 스톡 vs 클론 A/B 청취를 Jay가 판정(클론 우위를 전제하지 않음 — 운율 저하 리스크 명시). ⚠️ 현재 레퍼런스 `sutak.mp3`가 7.68초/스테레오(권장 10~20초/모노 미달) — 재녹음 필요 가능성. (2026-07-07 create-story 완료 — 상세는 스토리 파일)

### Story 5.22: 나레이션 문체·지칭 규칙 — writing 프롬프트

Jay 시청 피드백(2026-07-09, iteration 1 #1/#7). ① **종결어미 리듬**: "~했습니다/~입니다" 연속 반복이 단조로움 — 동일 종결 연속 금지, 의문·도치·명사 종결 혼용, 클라이맥스 단문 등 리듬 규칙을 writing 프롬프트에 추가. 단 다큐 톤 기조("-습니다" 존댓말)는 유지 — 리듬만 다양화, 반말·구어체 금지(채널 정체성). ② **지칭 규칙**: 주연이 아닌 인물은 고유 번호 대신 역할명("D계급 인원", "연구원", "경비원") — D-9341 같은 번호는 TTS도 "디 구삼사일"로 어색하게 읽음. 전제 작업: `scenario/writing` 프롬프트의 repo 파일이 부재(레거시 yt.pipe `templates/scenario/03_writing.md`가 최초 시딩 소스) — PROMPT_POLICY 규칙 1에 맞게 `prompts/scenario/writing.md`를 현행 production 버전으로 먼저 확립 후 수정. candidate 시딩→golden-set 게이트→승격. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.23: ComfyUI 지속부하 크래시 완화 — 배치 중간 헬스 폴/프리엠티브 재기동

베이스라인(39샷)·iteration 1(42샷)에서 재현 확인: ROCm(RX 9060 XT) ComfyUI가 이미지 스테이지 도중 hipErrorIllegalAddress로 core dump — 두 런 모두 ~40샷 근방에서 발생, 지속 부하 누적 패턴으로 보임. 5.14의 크래시 **복구** 경로(샷 재개+`retry` 엔드포인트)는 라이브 검증 완료(정상 동작)이지만, 매 장편 런마다 사람이 크래시를 감지하고 재시작·retry를 눌러야 함 — 완전 자동 완주가 안 됨. 드라이버 버그 자체는 근치 불가(ROCm 소관, 이 프로젝트 범위 밖)이므로 완화만: ① N샷(config, 기본값은 관측된 크래시 임계 이하로 — 예 `YTFLOW_COMFYUI_HEALTH_POLL_EVERY_N_SHOTS`)마다 `check_health` 호출, 응답 없으면 image_node가 **자체적으로** 짧은 대기 후 1회 자동 retry(사람 개입 없이) — 5.14 헬스체크 인프라 재사용, 새 호출 지점만 추가. ② 대안/추가책: N샷마다 ComfyUI 프로세스 자체를 프리엠티브 재기동(subprocess 관리 범위 확장 필요, 비용/복잡도 더 큼 — Jay 판단 필요). 우선 ①만 구현, ②는 ①로 부족할 때 후속. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 5.24: TTS 클론 보이스 재등록 지원 — 샘플 교체 시 강제 재생성

Jay가 `data/voices/sutak.mp3`를 7.68초(스테레오, 권장 미달)에서 12.93초로 재녹음(5.21 DoD 대기 항목 해소)했으나, `scripts/seed_voice_clone.py`의 `_find_existing`이 **이름("sutak")만으로 매칭**해 재실행 시 옛 샘플로 만든 voice id를 그대로 반환하고 끝남(재등록 없음) — API에 `action=delete`가 존재하는데(5.21 Dev Notes 기록) 스크립트에 구현이 없어서 재녹음이 실제로 반영될 길이 없음. 수정: `--force` 플래그 추가 — 기존 voice를 `action=delete`로 지운 뒤 `action=create`로 새 샘플 재등록(재등록도 유료 $0.01이므로 플래그 뒤에 명시적으로 숨김, 기본 동작은 현행 유지). 완료 후 실행해 새 `YTFLOW_QWEN_TTS_CLONE_VOICE_ID`를 `.env`에 반영하고, 5.21 DoD(스톡 vs 클론 A/B 청취)를 마침내 실제 12.9초 샘플로 수행 가능하게 함. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책

**Goal:** 앞으로의 품질 개선이 전부 프롬프트 반복(iteration)으로 수렴하므로, 프롬프트 변경을 "버전 + 라벨 + 평가 게이트 승격" 프로토콜로 운영한다 (업계 표준 prompt-management 패턴; Langfuse 네이티브 기능 — labels, protected labels, Datasets, trace↔version 연동 — 을 그대로 사용, 자체 인프라 구축 없음). 상세 AC는 스토리 파일 참조.

**발의 배경 (2026-07-03):** 정책 논의 중 배선 갭 발견 — `prompt_variant="B"`가 프롬프트 fetch에 연결돼 있지 않아 현재 A/B run은 두 변형이 동일한 production 프롬프트로 실행됨. Epic 4의 프롬프트 A/B가 실동작하려면 6-1이 필수.

**순서 제약:** 6-1은 프롬프트를 수정하는 Epic 5 스토리(5-4, 5-5)보다 선행.

### Story 6.1: 프롬프트 정책 문서 + variant→label 배선

1페이지 정책(`docs/PROMPT_POLICY.md`: repo가 SoT, production/candidate 라벨, 변경 프로토콜, 골든셋 게이트, UI 직접편집 금지) + CLAUDE.md 참조 + scenario 체인의 variant→label 배선(candidate 부재 시 production 폴백으로 부분 실험 지원) + 시드 스크립트 라벨 옵션.

### Story 6.2: 골든셋 + 오프라인 프롬프트 회귀 평가 러너

고정 SCP 2~3개를 Langfuse Dataset으로 시딩, scenario 체인만 실행(풀 파이프라인 없이 ~3분/몇십 원)해 Epic 4 평가 축으로 채점, dataset run에 버전별 점수 기록. `--baseline production` 비교 모드가 승격 판단 근거를 출력. 창작 파이프라인의 골든셋은 정답 출력이 아니라 "고정 입력 + 루브릭 + 점수 추이"라는 원칙.

### (미발의 후보) 승격 자동화

candidate가 골든셋+A/B를 통과하면 production 라벨을 자동 이동하는 스크립트/CI. 수동 승격(라벨 이동은 Langfuse UI 클릭 1회)의 빈도가 부담이 될 때만 발의 — YAGNI.

### Story 6.3: DeepSeek 프롬프트 캐시-히트 최적화 + 토큰/비용 관측성

**발의 배경 (2026-07-10):** Jay가 "LLM 호출이 생각보다 많이 발생한다"고 지적, 조사 결과 `scenario_node` 1회 실행이 정상 패스 `6+2N`(N=씬 수, 보통 8-12 → 22-30콜), 재시도 1회 시 `9+4N`(41-57콜)의 DeepSeek 호출을 발생시킴을 확인(8.10의 `cast_decision_step` 분리 + 5-4의 `tts_normalize_step` 추가가 설계 문서 `2026-07-03-scenario-multistage-design.md`의 추정치(정상 12-16, 재시도 최대 ~20)를 이미 낡게 만든 상태였음). A/B 실행은 여기서 다시 ×2.

호출 수 자체를 줄이는 재병합(cast_decision+visual_breakdown 통합)은 8.10에서 이미 시도했다가 되돌린 회귀(deepseek-v4-flash가 복합 호출에서 `entity_visible` 구 스키마로 퇴행, 8.1에서 0/125 샷 재현)라 다시 시도하지 않는다. 대신 업계 표준 비용 절감 기법 중 이 파이프라인에 안전하게 적용 가능한 것 하나만 적용: **DeepSeek Context Caching on Disk**(자동 활성화 기능, 코드 변경 없이도 동작하지만 프롬프트 구조가 캐시 친화적이어야 효과가 남 — 일치하는 프롬프트 접두사는 1/10 가격, `prompt_cache_hit_tokens` $0.014/M vs `prompt_cache_miss_tokens` $0.14/M, 최대 90% 절감)을 극대화하도록 프롬프트 템플릿을 재배치하고, 현재 전혀 관측되지 않는 토큰/캐시 사용량을 트레이스에 노출한다.

**AC1**: `prompts/scenario/*.md` 각 템플릿에서 씬/런 전체에 걸쳐 불변인 블록(시스템 지시문, `format_guide`, `frozen_descriptor`/`scp_visual_reference`, `entity_sheet`, `story_logline`)을 씬별로 변하는 블록(`scene_num`, `narration`, `numbered_sentences`, `cast_by_sentence` 등)보다 앞으로 재배치. 프롬프트 지시 내용 자체는 변경 없음 — 순서만 조정. `docs/PROMPT_POLICY.md` 절차 준수(candidate 라벨 선행 검증 후 production 승격).
**AC2**: `_call_stage`(`scenario_chain.py:153-174`)가 현재 버리는 `_call_deepseek`의 `usage` dict(`scenario.py:50-66`)를 스테이지별로 수집해 `_record_trace`의 stage 메타데이터에 `prompt_tokens`/`completion_tokens`/`prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`로 기록.
**AC3**: 실 SCP 1건 라이브 실행으로 재배치 전/후 캐시-히트 토큰 비율을 비교해 개선을 정량 증거로 남김(특히 씬 반복 호출인 cast_decision/visual_breakdown에서 히트율 증가 기대).
**AC4 (문서화, 구현 아님)**: 호출 수 자체를 줄이는 방향(씬 배치 통합 호출, 씬 단위 부분 재시도)은 이번 스토리 범위 밖 — 재병합은 8.10 회귀 이력 때문에 위험하고, 부분 재시도는 `writing_step`이 전 씬을 한 콜로 재작성하는 현재 계약과 상충해 별도 재설계가 필요함을 근거와 함께 `deferred-work.md`에 기록.

### Story 6.4: 시나리오 체인 YAML 출력 전환 + 스테이지 단위 bounded 재시도

**발의 배경 (2026-07-10):** Jay가 골든셋 게이트 3회 실행 중 `scenario` 스테이지에서 간헐적 `json.JSONDecodeError`(`Expecting ',' delimiter` 등, 매번 다른 offset)를 재현·캡처. 라이브 재현 조사 결과 `finish_reason`은 항상 `stop`이었고(즉 truncation이 원인이 아님), 실패 유형이 최소 3가지로 분리됨을 확인: (1) truncation(`finish_reason=length`, 원인·해법 기지 — `deepseek_max_tokens` 기본값 8192가 `scripts/eval_prompts.py`에 `_RISKY_DEFAULT_MAX_TOKENS`로 이미 문서화된 위험값), (2) 순수 JSON 문법 깨짐(`Expecting ',' delimiter` 등 — candidate 라벨 스테이지에서만 관측, 한국어 나레이션/대사 인용문의 따옴표·개행 이스케이프 실패로 추정되나 원문 바이트 단위 확증은 비용 문제로 보류), (3) valid JSON이지만 스키마 위반(`visual_breakdown`이 `visual_descriptions`를 리스트가 아닌 값으로 반환 등 — 포맷과 무관한 별도 신뢰성 문제).

DeepSeek의 `response_format: {"type": "json_object"}` 모드가 이 세 실패 중 어느 것도 막지 못하는 것으로 실측되어(순수 문법 에러가 실제로 재현됨 — 하드 grammar-constrained decoding이 아니거나 최소한 완전하지 않음), "JSON 강제 모드니까 안전하다"는 전제가 성립하지 않음. 그렇다고 YAML 전환만으로 세 실패 유형이 다 고쳐지는 것도 아님(truncation·스키마 위반은 포맷 무관) — 그래서 이번 스토리는 두 가지를 함께 적용: ① 자유 텍스트 필드(나레이션, `image_prompt` 등)에서 따옴표/개행 이스케이프 문제 자체를 구조적으로 없애는 YAML(block literal `|`) 출력 전환, ② 세 실패 유형 전부에 걸쳐 효과가 있는 **스테이지 단위 bounded 1회 재시도**(파싱/스키마 검증 실패 시 에러를 프롬프트에 넣어 해당 스테이지만 1번 더 호출) — 이미 5-23/5-11의 bounded-retry 선례와 동일한 패턴. `deepseek_max_tokens` 기본값 상향은 별도 사안으로 이번 스토리 범위 밖(재발 시 별도 스토리).

부수 발견: `scripts/migrate_prompts.py`가 소스로 기대하는 `prompts/scenario/format_guide.md`가 이 repo에 실존하지 않음(Langfuse에만 존재) — PROMPT_POLICY.md 룰 1("repo가 source of truth") 기존 위반, 이번 프롬프트 일괄 수정 전 선행 복구 필요.

**AC1**: `prompts/scenario/format_guide.md`를 Langfuse `production` 라벨의 현재 내용으로 복구해 repo에 커밋 — 이후 모든 프롬프트 편집의 전제조건(PROMPT_POLICY 룰 1 준수 회복).
**AC2**: `prompts/scenario/{research,structure,writing,cast_decision,visual_breakdown,review,critic_agent,tts_normalize}.md` + `format_guide.md`의 "Output ONLY a JSON object" 계열 지시를 YAML 출력 지시로 교체, 나레이션/`image_prompt`/`core_identity`/`frozen_descriptor`/`entity_sheet`/`story_logline`/`hooks`/`feedback` 등 자유 텍스트 필드는 block literal(`|`) 예시로 명시. 지시 내용(스키마 자체)은 불변 — 직렬화 방식만 교체.
**AC3**: `scenario.py`의 `_call_deepseek`에서 `response_format: {"type": "json_object"}` 제거(YAML 자유 생성과 양립 불가) — 나머지 호출 시그니처/반환 shape 불변.
**AC4**: `scenario_chain.py`의 모든 `json.loads(raw)` 호출(8곳)을 공용 YAML 파싱 헬퍼로 교체 — 모델이 지시를 어기고 \`\`\`yaml 코드펜스로 감싸 반환해도 방어적으로 스트립 후 파싱.
**AC5**: `_call_stage`를 감싸는 신규 `_call_stage_with_retry` 도입 — 파싱(`yaml.YAMLError`) 또는 기존 스키마 검증(`ValueError`) 실패 시, 직전 에러 메시지를 `{{parse_error}}` 변수로 채운 동일 프롬프트로 해당 스테이지만 정확히 1회 재호출. 8개 템플릿 전부에 `{{parse_error}}` 플레이스홀더 추가(평소엔 빈 문자열 — 기존 `glossary_section` 패턴과 동일). 재시도도 실패하면 예외는 그대로 전파(기존 `scenario_node`의 `PipelineState.error` 서페이싱 동작 불변).
**AC6**: 변경된 8개 템플릿은 `docs/PROMPT_POLICY.md` 기존 절차(candidate 라벨 시딩 → `scripts/eval_prompts.py` 골든셋 게이트 통과) 없이 production 승격 불가 — 이번 스토리가 정책/게이트 자체를 바꾸지 않음.
**AC7**: `tests/fixtures/cassettes/deepseek_*.json`의 `choices[0].message.content`를 YAML 텍스트로 갱신 + bounded 재시도(1회차 실패→2회차 성공, 양쪽 실패→에러 전파, 코드펜스 방어 스트립) 회귀 테스트 추가.

관련: [Story 6.3](#story-63-deepseek-프롬프트-캐시-히트-최적화--토큰비용-관측성)이 **동일한 8개 프롬프트 파일**을 재배치 중(uncommitted, ready-for-dev) — 두 스토리를 병렬로 건드리면 diff 충돌 확실, 순차 진행 권장(먼저 착수한 쪽의 결과 위에 나머지가 리베이스).

### Story 6.5: 재시도 신 단위 부분 수정

현재 review/critic이 재시도를 요구하면 writing + 모든 신의 cast/visual + review/critic을 전부 반복한다. review issues와 critic scene_notes의 유효한 신 번호를 합져 해당 신만 한 번의 배치 writing repair로 고친 뒤 cast/visual을 재생성하고, 나머지 신은 그대로 재사용한다. 재시도 추가 호출을 `3+2N`에서 `3+2k`(k=문제 신 수)로 줄이며, 유효한 신을 식별할 수 없을 때만 기존 전체 재작성을 bounded fallback으로 유지한다. 상세 AC와 merge/trace 가드레일은 스토리 파일 참조.

### Story 6.6: 계층형 프롬프트 평가 게이트

개발 내부 루프와 production 승격 게이트를 분리한다. `smoke`는 고정 canary SCP-049 1개로 빠른 건강성 피드백을 제공하지만 승격 권한이 없고, `promotion`만 기존 3개 candidate-vs-production zero-regression 기준을 유지한다. 즉 3개 검증을 매 편집마다 돌리지 않고 production 직전 1회로 빈도를 줄이며, 단일 smoke PASS가 production 승격으로 오용되지 않게 CLI/아티팩트/정책에 명시한다.

### Story 6.7: YAML 문법 전용 경량 repair 경로 분리

**발의 배경 (2026-07-11):** 6.6의 타임아웃 픽스(600s→1200s) 적용 후 6-3/6-4 promotion 게이트를 재실행했으나 여전히 FAIL. SCP-173에서 `yaml.YAMLError`(`mapping values are not allowed here`)가 `_call_stage_with_retry`의 bounded 1회 재시도까지 소진하고 실패로 전파됨 — 상세는 `6-3-6-4-review-metrics-report.md`의 "2026-07-11 full 3-item promotion re-attempt" 절 참조.

근본 원인 둘: (1) `review.md`/`critic_agent.md`의 자유 텍스트 하위 필드(`issues[].description`/`correction`, `corrections[].original`/`corrected`, `storytelling_issues[].description`/`correction`, `scene_notes[].issue`/`suggestion`)가 6.4의 AC2 block-literal(`|`) 목록에서 누락되어 plain scalar로 남아 있음 — 콜론이 든 문장이 그대로 YAML 파싱을 깬다. (2) `_call_stage_with_retry`가 `yaml.YAMLError`(순수 문법 오류)와 `ValueError`(스키마/내용 검증 실패)를 구분 없이 동일하게 처리 — 어느 쪽이든 전체 스테이지 프롬프트를 처음부터 재생성(`visual_breakdown`은 4-9만 토큰)하는 값비싸고 부정확한 재시도 1회로 취급한다. 순수 문법 오류라면 내용을 다시 쓸 필요 없이 "문법만 고쳐라"는 훨씬 좁고 싼 요청으로 해결될 가능성이 높다.

**AC1**: `review.md`/`critic_agent.md`의 위 자유 텍스트 필드를 block-literal(`|`) 예시로 전환(6.4 AC2가 놓친 필드 마무리) + `scenario_chain.py`의 `_normalize_freetext` 적용 대상 키 목록 확장.
**AC2**: `_call_stage_with_retry`가 `parse()`에서 발생한 예외 타입으로 분기 — `yaml.YAMLError`는 신규 경량 syntax-repair 경로(작은 전용 프롬프트: 깨진 raw 텍스트 + 에러 위치 + "내용/스키마는 그대로, YAML 문법만 고쳐라")로, `ValueError`(스키마 위반)는 기존 전체 재생성 경로로 라우팅. 양쪽 다 bounded 1회 — 무한 재시도 아님.
**AC3**: 신규 syntax-repair 프롬프트는 `docs/PROMPT_POLICY.md` 절차(candidate 시딩 → 게이트 통과) 준수.
**AC4**: SCP-173류 실패를 로컬에서 재현하는 회귀 테스트 추가(고의로 콜론 포함 plain scalar를 반환하는 페이크 호출 → syntax-repair 경로 진입 확인, `ValueError` 케이스는 기존 경로 유지 확인).

### Story 6.8: judge 채점 bounded retry — 단일 malformed 응답이 항목 전체를 죽이는 문제 해소

**발의 배경 (2026-07-11):** 6-3/6-4 promotion 게이트 재시도 1차 런에서 SCP-049 `candidate`가 "unparseable judge response"로 전체 실패. 원인 확인: `eval_service.py`의 judge 채점은 이미 축(axis)당 `REPS_PER_AXIS=3`회 동시 호출 후 평균을 내고 있음(Story 4.2, OQ-1) — "judge를 여러 번 샘플링해 노이즈를 줄이자"는 애초 구상은 이미 구현되어 있어 불필요. 진짜 갭은 `_judge_axis`가 3개 호출을 `asyncio.gather`로 묶는데, `_post_chat`/`_parse_score`가 파싱 실패(예: judge가 낸 JSON 문자열 값에 이스케이프 안 된 리터럴 개행이 섞여 `json.loads` 실패)를 재시도 없이 즉시 `EvalJudgeError`로 던진다는 것 — `gather`가 3개 중 1개 실패만으로 즉시 전체를 실패시켜, 축 하나·항목 하나의 평가 전체가 죽는다. scenario 체인에는 이미 있는 bounded-retry 철학(5-23, 6.4)이 judge 채점 경로에는 없다.

2차 런의 SCP-049 `narrative_coherence` -0.33 단일 축 회귀는 이미 3회 평균낸 값끼리의 차이라, judge 노이즈보다는 매 실행마다 실제로 조금씩 달라지는 시나리오 생성 자체의 편차일 가능성이 높다 — 이건 judge 쪽을 고쳐도 없어지지 않고, 없애려면 전체 시나리오 생성 자체를 항목당 여러 번 반복해야 하는데 이는 6.6이 비용을 줄이려 만든 tiered gate 취지에 반하므로 이번 스토리 범위 밖으로 명시적으로 제외한다.

**AC1**: judge 호출(`_post_chat`을 통한 개별 axis 판정 1회)이 파싱 실패(`EvalJudgeError`)를 내면, 그 1개 호출만 정확히 1회 재호출(bounded) — 나머지 성공한 호출/축에는 영향 없음.
**AC2**: 재시도까지 실패하면 해당 axis의 해당 1개 sample만 결측 처리하고 나머지 성공한 sample들의 평균으로 axis 점수를 낸다(예: 3개 중 2개 성공 시 2개 평균). 3개 중 2개 이상 실패하면 기존처럼 항목 실패로 전파(무한정 관대하게 만들지 않음).
**AC3**: `--profile smoke`/`--profile promotion` 둘 다 이 bounded retry 혜택을 받는다(judge 로직은 프로파일 무관 공통 경로).
**AC4**: 회귀 테스트 — 3개 중 1개 파싱 실패→재시도 성공, 3개 중 1개 파싱 실패→재시도도 실패(2개 평균으로 폴백), 3개 중 2개 이상 실패(기존처럼 항목 실패) 케이스 커버.
**AC5 (범위 제외, 문서화만)**: 생성 자체의 실행 간 편차(narrative_coherence류)는 이 스토리로 해소되지 않음 — 해소하려면 항목당 전체 시나리오 생성을 반복해야 하며 비용이 6.6의 취지와 상충함을 근거와 함께 명시.

### Story 6.9: writing_scene_repair truncation 근본원인 + SCP-173/096 축 회귀 조사·수정

**발의 배경 (2026-07-11):** 6.7/6.8 통합 코드리뷰 게이트(`6-3-6-4-review-metrics-report.md`의 "2026-07-11 Story 6.7/6.8 review gate" 절)에서 6-3/6-4 promotion이 세 번째로 FAIL — 이번엔 6.7/6.8이 고친 문제(YAML 문법 파싱, judge 응답 파싱)와 무관한 두 가지 새 사유: (1) `scenario/writing_scene_repair`가 promotion 강제 하한인 16000 토큰에서도 truncation(`finish_reason=length`), (2) SCP-173가 atmosphere/narrative_coherence 각 -0.33, SCP-096이 article_fidelity -0.33(atmosphere는 +1.67 개선에도 불구) 회귀.

truncation 관련 코드 확인 결과: `_repair_and_review`(`scenario.py:252-266`)가 `writing_scene_repair_step`에 넘기는 `originals`는 `_retry_scope`(`scenario.py:110-141`)가 review.issues + critic.scene_notes에서 모은 유효 scene_num 전체이며, **배치 크기 상한이 없다** — review/critic이 씬 대부분을 동시에 flag하면 한 콜에서 그만큼의 씬 전체 narration을 재작성해야 해 16k에서도 부족할 수 있음(각 씬 프롬프트 자체는 짧음, `prompts/scenario/writing_scene_repair.md` 참조). 이것이 실제 원인인지는 미확증 — truncation 발생 시점의 실제 `len(indexes)`를 아직 관측하지 못함(라이브 재현 필요).

축 회귀 관련: 6.3 AC1(프롬프트 재배치, 지시내용 불변 선언)과 6.4 AC2(JSON→YAML 직렬화 전환, 스키마 불변 선언)가 둘 다 "내용은 그대로, 형식만 변경"을 전제했으나, 실측 결과 atmosphere/narrative_coherence/article_fidelity가 SCP별로 갈려서 하락 — 직렬화 방식 변경 자체가 모델의 실제 서술 스타일에 영향을 줬을 가능성(예: block-literal 지시가 문체를 건조하게 만듦)과, 단순 실행 편차(6.8이 SCP-049 narrative_coherence -0.33을 범위 제외로 문서화한 것과 동일 패턴) 두 가설을 구분해야 함 — 아직 어느 쪽인지 미확증.

**AC1**: 실 SCP-049 golden-set 케이스로 writing_scene_repair가 truncate되는 상황을 라이브 재현하며 `len(indexes)`(동시 repair 대상 씬 수)와 실제 사용 토큰 수를 계측·기록 — 배치 크기가 원인인지, 아니면 소수 씬에서도 발생하는지 확정.
**AC2**: AC1 결과가 배치 크기 무상한을 원인으로 지목하면, 곧바로 상한 도입으로 가지 말고 이 문제 유형("N개 구조화 항목인데 한 콜 출력 예산이 부족")에 대한 업계 표준 대응(map-reduce식 청크 분할 호출, truncation 지점에서 이어쓰기하는 continuation 프롬프트, 상한+저비용 폴백 위임 등)을 최소 2가지 이상 비교한 뒤 이 프로젝트의 기존 bounded-retry 선례(6.4/6.7/6.8)와의 정합성 기준으로 택일 — 채택 사유를 문서화. 상한 미도입이 근거로 부적절하면(예: 소수 씬에서도 재현) 대안 원인(예: repair 프롬프트가 `original_scenes` 원문을 그대로 반복 출력하려는 경향)을 조사해 별도 수정.
**AC3**: SCP-173/096 축 회귀가 (a) 6.3/6.4의 직렬화 방식 변경 자체에 의한 실질적 문체 회귀인지, (b) 6.8이 이미 범위 제외로 문서화한 것과 같은 실행 간 생성 편차인지, 단일 전후비교가 아니라 반복시행 비교(동일 candidate를 golden item당 최소 3회 재실행 — 이 프로젝트의 judge 채점 `REPS_PER_AXIS=3` 선례와 동일한 근거)로 구분. (a)로 확인되면 원인이 된 구체적 프롬프트 변경(어느 파일의 어느 지시문)을 특정하되 수정안을 하나로 단정하지 않고 최소 2가지 대안(해당 블록 되돌리기 vs 지시문 문구 조정 vs 문체 가드레일 추가 등)을 비교해 채택 사유를 기록. (b)로 확인되면 6.8의 선례를 따라 이번 스토리 범위에서 제외하고 문서화.
**AC4**: 두 수정(또는 조사로 확정된 범위 제외) 반영 후 `scripts/eval_prompts.py --profile promotion` 3-item 게이트를 재실행 — PASS 시 `docs/PROMPT_POLICY.md` 절차대로 6-3/6-4 candidate를 production으로 승격, 여전히 FAIL이면 사유를 `6-3-6-4-review-metrics-report.md`에 추가 기록(승격 강행 금지, 기존 정책 불변).
**AC5**: 회귀 테스트 — AC2에서 배치 상한/청크 로직을 구현했다면 대상 씬 수가 상한을 넘는 경우의 청크 분할(또는 fallback 위임) 동작을 검증하는 단위 테스트 추가.

### Story 6.10: 통계적 promotion 게이트 + SCP-049 scoped-repair 견고성 (6-3/6-4 언블록)

**발의 배경 (2026-07-11):** 6.9의 AC3/AC4 라이브 3회 멀티트라이얼(`6-3-6-4-review-metrics-report.md`의 "2026-07-11 Story 6.9 — AC3/AC4 live multi-trial" 절)로 6-3/6-4가 승격 못 하는 **진짜 원인이 재정의**됨. 크래시성 원인(타임아웃/YAML/judge/truncation)은 6.6~6.9로 전부 제거됐고, SCP-173/096 축 회귀는 **실질 회귀가 아니라 run-to-run 생성 편차(VARIANCE)**로 확정(4개 데이터포인트 어느 (항목,축) 셀도 음수 유지 못 함). 그럼에도 게이트가 매번 FAIL한 이유는 **측정/정책 문제**다: zero-tolerance 게이트(음수 델타 하나 = FAIL, 6.6의 의도적 정책)를 3항목×3축=9칸 비교에 적용하면 생성 노이즈가 매 런 어딘가 음수를 만들어, production과 통계적으로 동등한 후보도 확률적으로 매번 FAIL한다 — **구조적으로 통과 불가**. 부수적으로 SCP-049의 scoped `writing_scene_repair`가 간헐적으로 하드 실패(원 게이트=truncation, run2=`scene coverage mismatch`)해 채점 자체가 안 되는 별도 견고성 버그도 노출됨. Jay 결정(2026-07-11): 두 문제를 한 스토리로 묶어 통계 게이트 + repair 견고성을 함께 해결.

**AC1**: `scripts/eval_prompts.py --profile promotion`의 zero-tolerance 판정을 **통계적 기준으로 교체** — 동일 candidate/production을 golden item당 N회(N≥3, `REPS_PER_AXIS=3` 선례) 재생성해 항목별 델타의 **median(중앙값)**으로 PASS/FAIL을 판정(음수 노이즈 단일 셀이 전체를 죽이지 않도록). 단순 mean이 아니라 median/best-of-N을 택하는 이유(간헐 하드실패 런이 mean을 오염시키는 문제, AC3의 SCP-049 사례)를 Dev Notes에 기록. `docs/PROMPT_POLICY.md`의 승격 기준 문구도 함께 개정(zero-tolerance → 통계적 게이트), 6.6이 zero-tolerance를 도입한 근거와의 관계를 명시.
**AC2**: N회 재실행 중 **일부 아이템이 하드 실패(에러로 미채점)해도** 게이트가 무너지지 않도록 — 성공한 런들의 median으로 판정하고, 특정 아이템이 과반 런에서 실패하면 그 아이템만 FAIL로 격리(전체 게이트 크래시 금지). 실패 런 수/사유를 리포트에 로깅(무성 절단 금지).
**AC3**: SCP-049 scoped `writing_scene_repair`의 `scene coverage mismatch` 견고성 수정 — repair가 요청한 씬 집합과 다른 순서/구성으로 반환할 때(예: 요청 `[3,2,4,1,5,6]` → 반환 `[1,2,3,4,5,6]`) 하드 실패 대신 복구(정렬 무관 매칭으로 커버리지 검증, 또는 truncation과 동일하게 full-rewrite fallback 위임). 6.9의 narrow-recovery 계약(truncation만 fallback)과의 정합성을 유지하며 어떤 repair 실패 클래스를 복구 대상에 추가할지 명시.
**AC4**: AC1~AC3 반영 후 새 통계 게이트로 6-3/6-4 candidate를 N회 재실행 — median 판정 PASS 시 `docs/PROMPT_POLICY.md` 절차대로 production 승격, 6-3/6-4를 done으로 종결. 여전히 FAIL이면 사유를 `6-3-6-4-review-metrics-report.md`에 기록.
**AC5**: 회귀 테스트 — (a) median 게이트 판정(노이즈 단일 음수 셀이 PASS를 막지 않음 / 일관된 음수는 여전히 FAIL), (b) 아이템 하드실패 격리(1개 실패가 전체 게이트를 죽이지 않음), (c) SCP-049 coverage-mismatch 복구 경로.

### Story 6.12: A/B 승격 게이트 동결 + 6-3/6-4 후보 승격 보류

**발의 배경 (2026-07-12):** 6.10의 통계 게이트로 baseline은 비교 가능해졌으나 corrected paired-delta 게이트가 여전히 FAIL(SCP-049 total −1.00, SCP-173 art_fidelity −0.33, SCP-096 total −0.83) — majority hard-fail 없이 순수 품질 델타 음수. 즉 블로커가 "측정 노이즈"에서 "**후보 프롬프트가 production보다 실제로 낮음**"으로 확정됨. Jay 결정: (1) 6-3/6-4는 **코드가 완성**됐으므로 done 처리하고, 후보 프롬프트의 production 승격만 이 스토리로 분리·보류. (2) 지금은 개발 단계로 **파이프라인 완성도(Epic 8 등)**가 우선이며, A/B 승격 게이트는 production 품질 튜닝 국면에서만 의미가 있고 토큰을 크게 소모하므로, **파이프라인 완성 전까지 자동/수동 어디서도 쓸데없이 돌지 않게 동결**한다.

**AC1**: `scripts/eval_prompts.py`에서 `--baseline`이 붙은 실행(= candidate-vs-production A/B; `--profile promotion` 포함)은 `YTFLOW_ALLOW_AB_GATE=1` override 없이는 즉시 hard-error(argparse error). 단일 라벨 실행(`--label X`, `--baseline` 없음)과 `--profile smoke`는 진단용으로 계속 허용. **구현 완료(2026-07-12).**
**AC2**: `docs/PROMPT_POLICY.md`에 동결 배너 추가(사유·override·해제 조건 명시). **구현 완료.**
**AC3**: 회귀 테스트 — override 없을 때 `--baseline`/`--profile promotion` 차단, override 있을 때 통과, 단일 라벨은 미차단. **구현 완료(test_eval_prompts.py 3건 + autouse 인증 픽스처).**
**AC4 (보류/후속)**: 파이프라인 완성 후 품질 튜닝 국면 재개 시 게이트를 un-freeze하고 median 통계 게이트로 6-3/6-4(및 Epic 8에서 보류된 8-5/8-8 등 candidate)를 재평가·승격. 이 AC는 이 스토리 범위 밖의 미래 작업 트리거로만 기록.

### Story 6.13: 골든셋 평가 스테이지 단위 캐싱

**발의 배경 (2026-07-12):** Jay가 프롬프트 수정이 여러 스테이지 파일에 걸쳐 산발적으로 일어나는 와중에, 하나만 고쳐도 `scripts/eval_prompts.py`가 골든셋 3개 SCP × 8개 스테이지(research/structure/writing/cast_decision/visual_breakdown×N/review/critic_agent/tts_normalize) 전체를 처음부터 재실행하는 낭비를 지적 — 6-3/6-4/6-7~6-11이 반복 지불한 라이브 게이트 비용/타임아웃(`6-3-6-4-review-metrics-report.md`)이 정확히 이 문제의 증상. 업계 표준(promptfoo) 확인: 로컬 디스크 캐시(`~/.promptfoo/cache`)에 결과를 저장하고 캐시 키에 버전 식별자를 포함시켜 프롬프트가 바뀌면 해당 항목만 자동 무효화하는 패턴이 표준. Langfuse Datasets/Experiments는 결과 기록·비교용 관측 도구이지 memoization 저장소가 아니므로(Epic 6 목표 "Langfuse native 기능만 재사용, 별도 인프라 없음"과도 상충) 이번 캐시는 Langfuse가 아닌 로컬 파일로 구현한다. 캐싱 단위는 SCP 항목이 아니라 **스테이지**(`_call_stage`) — 3개 항목이 전부 같은 8개 스테이지를 통과하므로, 항목 단위 캐싱은 프롬프트 하나만 바뀌어도 항목 전체가 무효화돼 지금과 동일한 효과 없음. DeepSeek 자체 prefix-cache(6-3, 호출은 하되 싸게)와는 다른 레이어(호출 자체를 스킵)로 상호보완적이며 서로 변경하지 않는다.

**AC1**: `scenario_chain.py`의 `_call_stage`(6-3에서 `usage_sink` out-parameter가 추가된 동일 함수) 호출 지점에 스테이지 단위 캐시를 적용 — 캐시 키는 `hash(prompt name + label + Langfuse prompt object의 version + compiled variables + model)`. 캐시 히트 시 DeepSeek 호출을 스킵하고 캐시된 `(raw, usage)`를 그대로 반환.
**AC2**: 캐시는 로컬 JSON 파일(`tmp/eval-prompts/cache/` 하위, git-ignored) — 신규 의존성 없이 stdlib `hashlib`/`json`/`pathlib`만 사용.
**AC3**: `scripts/eval_prompts.py`에 `--no-cache` 플래그 추가(promptfoo 컨벤션과 동일한 이름) — 캐시 우회가 필요할 때 강제 재실행.
**AC4**: 이 캐시는 `scripts/eval_prompts.py`의 골든셋 실행 경로에만 적용 — `run_service`/`scenario_node`의 실제 파이프라인 실행 경로는 건드리지 않음(운영 트래픽 캐싱이 아니라 회귀 게이트 전용).
**AC5**: 회귀 테스트 — (a) 동일 버전 재실행은 캐시 히트로 DeepSeek 호출이 발생하지 않음, (b) 프롬프트가 재시딩되어 버전이 오르면 해당 스테이지만 캐시 미스로 재실행되고 나머지 스테이지는 여전히 캐시 히트, (c) `--no-cache`는 전체 스테이지를 무조건 재실행.

**Out of scope**: 6-12가 동결한 A/B promotion 게이트(`--baseline`) 자체의 재개 여부 — 이 스토리는 게이트가 얼마나 도는지와 무관하게, 돌 때 드는 비용을 줄이는 것만 다룸.

## Epic 7: 영상 프로덕션 밸류 II — 사운드·후처리·패럴랙스·트랜지션·자막

**Goal:** Epic 5(2026-07-03 첫 실전 렌더 리뷰 피드백)와는 별도로 발의된 "영상미 개선" 확장 이니셔티브 5건을 처리한다. 전부 새 LangGraph 노드 없이 `video_node`/`_compose_scene`(또는 `subtitle.py`)을 확장하는 순수 필터·에셋 추가라 하나의 에픽으로 묶는다. 상세 설계는 각 스토리가 참조하는 `docs/superpowers/specs/*.md` 참조.

**발의 배경 (2026-07-04):** 사운드 디자인/후처리 필터/패럴랙스/트랜지션 다양화/키네틱 자막 5개 설계 문서가 순차 커밋됨(4924c65, 5054066, 2bd5675, 58fe998, b8f5b6a). 패럴랙스 스펙은 `deferred-work.md`의 "5-3 motion-intensity 라이브 QA (2026-07-04)" 디퍼럴(배경 확대 시 고정 크기 캐릭터가 상대적으로 가까워 보이는 우발적 효과)을 재고해 의도적 기능으로 만든 것.

**순서 제약:** 7.1(사운드 디자인)이 `SceneState.mood` 필드를 신설하는 오너이므로 7.2/7.4보다 반드시 선행. 7.3/7.5는 mood 비의존이라 순서 무관하지만, 7.1/7.2/7.3/7.4 네 스토리 전부 `video.py`를 건드리므로(오디오 믹싱/필터체인/모션 수식/`_join_with_xfade` 시그니처 변경) 병렬 세션 진행 시 파일 충돌 위험 — 순차 진행 권장.

### Story 7.1: 사운드 디자인 (BGM + 앰비언트 + SFX 스팅어)

씬 mood(dread/clinical/escalation/revelation, `SceneState.mood` 신설)에 따라 배경음악/앰비언트 루프/전환 스팅어를 사이드체인 컴프레션으로 내레이션 아래 덕킹해 믹스한다. 새 모듈 `pipeline/nodes/sound_design.py`, `video_node._compose_scene` 확장, 신규 파이프라인 노드/게이트 없음. 설정: `YTFLOW_SOUND_DESIGN_ENABLED`. 상세: [2026-07-04-sound-design-design.md](../../docs/superpowers/specs/2026-07-04-sound-design-design.md)

### Story 7.2: 후처리 필터 (색보정 + 비네트 + 필름 그레인)

[depends_on: 7.1] mood별 색보정(`eq`)을 씬·챕터카드에 적용하고, 비네트·그레인은 mood 무관 고정 강도로 전 프레임에 적용한다. 자막은 그레인/비네트 이후(번인 전) 별도 처리해 가독성을 유지한다. 새 모듈 `pipeline/nodes/color_grade.py` — mood 판정은 `sound_design.resolve_mood` 재사용, 중복 정의 없음. 설정: `YTFLOW_POST_FX_ENABLED`. 상세: [2026-07-04-color-grade-postfx-design.md](../../docs/superpowers/specs/2026-07-04-color-grade-postfx-design.md)

### Story 7.3: 진짜 패럴랙스 (배경/캐릭터 속도 분리)

`deferred-work.md`의 5-3 라이브 QA 디퍼럴을 해소 — 캐릭터(근경)가 배경(원경)과 동일 방향으로 `CHAR_DEPTH_FACTOR` 배 증폭되어 움직이도록 만들어 우발적 아티팩트를 의도적 다중평면 뎁스 연출로 전환한다. 기존 `video.py`의 `EffectSpec`/`select_effect`/`_zoompan_filter` 시스템을 그대로 확장(신규 파일 없음). **필수 수정사항**: 캐릭터 줌 증폭을 반영해 `CHAR_MAX_W`/`CHAR_MAX_H` 세이프 박스를 축소하지 않으면 캐릭터가 프레임을 벗어남 — 이 스펙의 핵심 정합성 요구사항이지 부가 개선이 아님. 10개 방향 전체에 대해 팬 방향 부호를 라이브 렌더로 검증 필수(머지 전). 설정: `YTFLOW_PARALLAX_ENABLED`. 상세: [2026-07-04-character-parallax-design.md](../../docs/superpowers/specs/2026-07-04-character-parallax-design.md)

### Story 7.4: 트랜지션 다양화 (mood 기반 xfade 타입)

[depends_on: 7.1] 씬 경계 전환 타입(`fadeblack` 고정 → mood별 `MOOD_XFADE_MAP`)을 mood로 결정한다. 전환 길이(`XFADE_DURATION`)는 불변, 타입만 변화. 챕터카드가 걸린 경계는 예외적으로 항상 `fadeblack` 유지. `_join_with_xfade`의 `segments` 튜플에 전환 타입 요소를 추가한다. 설정: `YTFLOW_TRANSITION_VARIETY_ENABLED`. 상세: [2026-07-04-transition-variety-design.md](../../docs/superpowers/specs/2026-07-04-transition-variety-design.md)

### Story 7.5: 키네틱 자막 (단어 단위 가라오케 하이라이트)

`SceneState.word_timings`의 단어별 타이밍을 활용해 SRT 대신 ASS(libass, 신규 의존성 없음) `\k` 카라오케 태그로 발화 중인 단어를 하이라이트한다. mood 비의존, 신규 모듈 없이 `subtitle.py`에 함수 추가(`build_ass_events`/`format_ass`, 큐 그룹핑은 기존 `_word_timings_to_segments` 재사용). 단어 단위 타이밍이 없는 경우(정렬 fallback)는 기존 SRT로 자동 강등 — 없는 데이터를 지어내지 않는다. 설정: `YTFLOW_KINETIC_SUBTITLES_ENABLED`. 상세: [2026-07-04-kinetic-subtitles-design.md](../../docs/superpowers/specs/2026-07-04-kinetic-subtitles-design.md)

## Epic 8: 이미지 합성 아키텍처 전환 — 배경 + 캐릭터 카드 컴포지팅

2026-07-06 E2E 베이스라인(run `272b05a4`, SCP-049, `e2e-baseline-2026-07-06.md`)에서 Jay가 확정한 아키텍처 결정. 현행 "개체 포함 프레임 생성 → 세그멘테이션 컷아웃 → 배경 인페인트"(1.6b/5-6/5-7 계열)를 폐기하고, **배경은 배경 묘사만으로 생성 + 캐릭터는 레퍼런스 기반 카드(RGBA 스프라이트)를 합성**하는 구조로 전환한다. 캐릭터 불필요 샷은 배경만. 근거 결함: D5(앵글 라벨 불일치), D10(인페인트 흉터), D11(환경 샷 오컷), D13(무알파 풀프레임 카드가 전 샷을 덮음 — critical). 전환 시 5-6/5-7 문제는 계급적으로 소멸. 권장 순서 8.1 → 8.2 → 8.3 → 8.4 (8.1/8.2는 병렬 가능, 8.4는 셋 모두 이후); 8.6(자산 관리)은 8.5(플레이트)보다 선행 필수이며 둘 다 iteration 1(8.3 DoD A/B) 결과 확인 후 착수.

### Story 8.1: 샷별 cast 메타데이터 + 배경 전용 프롬프트

visual_breakdown이 샷별로 `cast` 목록(등장 캐릭터 키: 개체/`STOCK-*` 고정 출연진/파생 개체)과 카드별 **배치 메타데이터**(position/scale/z-order — 대략적 좌우·원근 수준), 그리고 **개체 묘사를 제거한 배경 전용 image_prompt**를 출력하도록 프롬프트+파서+ShotData 스키마 확장. cast 빈 목록 = 배경만(D11 해소). 프롬프트 변경은 PROMPT_POLICY 절차(candidate→A/B→승격) 준수. D3(리터럴 SCP 토큰)도 cast 참조로 흡수.

### Story 8.2: 캐릭터 카드 스프라이트 파이프라인 + 고정 출연진 시드

카드 산출물을 **투명 RGBA 스프라이트**로 표준화: 단색/스튜디오 배경으로 캐릭터 생성 → 컷아웃(깨끗한 배경이라 세그멘테이션 신뢰 가능) → 스프라이트 저장. D5 해소: 앵글별 IPAdapter weight 조정 또는 앵글 프롬프트 강화로 실제 프로필/후면 카드 확보, 포즈 배리에이션(서있기/앉기 등) 검토. SCP 세계관 고정 출연진(D계급, 연구원, 경비요원)을 `STOCK-*` 예약 scp_id로 사전 생성·캐싱(CharacterModel 스키마 변경 불요), 파생 개체(예: 049-2) 카드화 포함. 에피소드 간 시각 일관성이 채널 아이덴티티가 되는 부수 효과.

### Story 8.3: image_node 배경 전용 생성 + video_node 다중 카드 합성

image_node에서 세그멘테이션/인페인트 경로 제거 — 배경 전용 프롬프트로 배경만 생성(플랫 경로 일원화). video_node는 cast×배치 메타 기반 **다중 카드 오버레이**(N장, scale/position/z-order 반영, RGBA 검증 — 무알파 카드는 명시 에러), 카드별 독립 아이들 모션/패럴랙스(1.9c/7-3 재사용). 1.13 앵글 선택은 "전 샷 오버라이드"에서 "cast에 개체 있는 샷만"으로 게이팅(D13 해소). 완료 판정: SCP-049 재렌더 A/B로 베이스라인 대비 J2/J3/J4 개선 확인.

### Story 8.4: 온디맨드 특수 포즈 카드

2026-07-06 Jay 승인 포즈 차원(업계 표준 스프라이트 라이브러리 티어링: 기본 포즈 사전 생성 + 특수 포즈는 씬별 키 아트로 온디맨드 생성)의 온디맨드 티어. visual_breakdown이 cast 멤버에 선택적 자유 텍스트 `pose_hint`를 출력할 수 있게 확장 — 닫힌 pose enum(standing/sitting, 8.1)은 그대로, 별도 옵션 필드. pose_hint가 있고 캐시된 카드가 없으면 **시나리오 게이트 승인 시점**의 런타임 프로비저닝이 1회성 특수 포즈 카드를 생성(5-8/5-10 `_ensure_character_reference` 비치명 패턴 재사용 — 생성 실패 시 기본 포즈로 폴백, 런은 절대 실패하지 않음), 결정적 키(scp_id+pose_hint 해시 → 8.2 `character_cards`의 `hint:*` pose 키)로 캐싱해 런 간 재사용. 비용 가드레일: 런당 신규 생성 캡(기본 3장), mock 모드 스킵. 8.1/8.2/8.3 의존.



### Story 8.5: 스톡 로케이션 플레이트 — 배경 세트 사전 제작·재사용

Jay 제안(2026-07-07), 업계 표준(애니메이션 배경 미술 라이브러리/비주얼 노벨 로케이션 세트) 대응. SCP 다큐의 장소 어휘는 머리가 두꺼움 — 격리실/관찰실/복도/면담실/부검실/제어실/시설 외경 등 10~15개 정형 로케이션이 샷 대부분을 커버. 카드 시스템(8-1~8-4)과 대칭 설계: visual_breakdown이 닫힌 `location_key`(STOCK 로케이션) 또는 자유 배경 프롬프트(개체 고유 환경, 현행 런타임 생성)를 샷별로 선택 → image_node는 STOCK이면 플레이트 복사(생성 0회), 아니면 생성. 로케이션당 앵글/구도 변형 2~3장(단조로움 완화, Ken Burns 크롭 변주와 결합), mood 조명 변형은 플레이트를 늘리지 않고 7-2 그레이드가 렌더 타임 처리. 시드 스크립트 + 인간 큐레이션 게이트(플레이트 품질은 사람이 승인 — CC0 오디오 소싱 선례). **생성 방법론(Jay, 2026-07-07)**: 스타일 앵커 1회 큐레이션 — 사람이 앵커 레퍼런스 3~5장을 선정하고(배경은 캐릭터와 달리 저작권 부담이 낮음(Jay, 2026-07-07): 일반 시설 사진의 스타일·구도 참조 + 산출물은 생성 이미지 → 소스 제약 완화, 위키/무료 스톡/이미지 검색 무엇이든 인간 큐레이션으로 선정. 단 2026-07-03에 보류한 '캐릭터·개체 샷별 img2img'는 별개 사안으로 보류 유지. 검색 자동화가 필요해지면 현행 DDG 스크레이퍼는 403 미해결 상태(5-10은 위키 우선으로 우회한 것)라 ddgs 교체/SearXNG가 후보) IPAdapter 스타일 컨디셔닝(낮은 weight)으로 전 플레이트를 생성 → 라이브러리 전체가 단일 화풍. 같은 앵커를 8-2 카드 생성에도 공유하면 카드-배경 화풍 통일로 콜라주 룩 리스크(deferred 2026-07-07 #1) 직접 완화. 스타일이 그래도 흔들리면 v2 에스컬레이션: 자체 플레이트로 스타일 LoRA 학습. **룩뎁/프로덕션 분리(Jay, 2026-07-07 — 업계 표준 프로토콜, 8-2 AC14와 동일 규칙)**: 큐레이션 단계에서 대표 로케이션 2~3종을 frontier 이미지 모델로 뽑아 로컬 SDXL과 나란히 비교(수동, 파일 드롭, 통합 불요) → 이기는 클래스는 frontier 산출물을 플레이트로 직접 채택하거나 로컬 물량 생성의 스타일 앵커로 사용. **런타임/물량 생성은 어느 쪽이든 ComfyUI 고정** (비용, 호러 콘텐츠 필터, 시드 재현성). 결정 기록 필수. 기대 효과: 씬 내 공간 연속성(현재 같은 씬 샷마다 다른 방이 생성되는 숨은 결함 해소), 배경 프롬프트 순응도 리스크(deferred-work 2026-07-07 #2) 원천 차단, 에피소드 간 채널 아이덴티티, 이미지 스테이지 생성 비용 대폭 감소. **착수 시점: iteration 1(8-3 DoD A/B) 결과 확인 후** — 콜라주 룩 등 실측 우선순위와 함께 배치. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.6: 자산 라이브러리 관리 체계 — 레지스트리·출처·버저닝

Jay 지시(2026-07-07): 재사용 자산(캐릭터 카드, 로케이션 플레이트, 룩뎁 앵커)의 체계적 관리. 현재 카드가 run 스크래치 영역(`workspace/`)에 살아 라이브러리와 일회성 산출물이 섞여 있음(테스트의 workspace 오염 전례 있음). 정리: ① **저장 분리** — `assets/` 루트 신설(`characters/{card_key}/{pose}_{angle}.png`, `locations/{location_key}/{variant}.png`, `anchors/`), 바이너리는 gitignore하되 **`assets/manifest.json`은 커밋**(키→경로·sha256·출처: 앵커 참조/워크플로우 해시/시드/weight/생성일/승인일) → 자산 이력이 git으로 감사 가능. ② **카탈로그** — 조회는 DB 진실 유지(`characters`/`character_cards` + 신규 `location_plates` 테이블), 매니페스트는 출처·무결성 담당(파일↔행 정합 검증 스크립트 포함). ③ **버저닝** — `style_epoch` 정수: 스타일 앵커 세트 변경 시 +1, 재생성은 새 epoch, 옛 epoch 보존(과거 에피소드 자산의 소급 변경 방지). ④ **수명주기** — draft→approved(큐레이션 게이트, 파이프라인은 approved만 사용)→retired. ⑤-α **전역 재사용 불변식(Jay, 2026-07-07)**: 라이브러리 자산의 키는 run/에피소드가 아니라 자산 정체성(`card_key`, `location_key`) — 캐릭터 카드는 연관 에피소드 재등장 시 자동 재사용(5-8 `check_existing_character` 경로가 생성 스킵), **STOCK-* 고정 출연진 카드는 무조건 전 에피소드 공유**(시드 idempotent, run별 사본 금지), 어떤 run 종료·정리 루틴도 라이브러리 자산을 삭제할 수 없음. ⑤ **이주** — 8-2가 기존 경로로 만든 카드 라이브러리를 assets/로 일괄 이주(소비자 경로 일원화: character_service·8-3 resolver·3.7 UI). 8-5 플레이트는 처음부터 이 체계에서 시작 — **8-5보다 선행 필수, 8-2/8-3과는 독립**. (draft — 상세 스토리 파일은 create-story로 별도 생성)


### Story 8.7: 합성 조화(콜라주 룩 해소) — 표준 컴포지팅 사다리

deferred-work(2026-07-07 #1)의 콜라주 룩 리스크를 업계 표준 기법 사다리로 스토리화(Jay, 2026-07-07; 착수 게이트: iteration 1에서 콜라주 룩 실측 확인 시). 2D 합성 표준 기법을 비용 순으로: **Tier 1 (ffmpeg 수준, 저비용)** — ① mood별 스프라이트 틴트(장면 광원과 톤 일치 — 게임 2D 라이팅 관행의 gradient tint), ② **컨택트 섀도**(카드 발밑 타원 그림자 — 접지감이 최대 리얼리즘 신호), ③ 그레이드·그레인을 합성 **후** 전체 프레임에 적용해 통일(8-3이 이미 post-fx last 순서 보장 — 검증만). **Tier 2** — 라이트 랩(배경색이 스프라이트 가장자리로 번지는 VFX 표준). **Tier 3 (AI, ComfyUI 네이티브)** — **IC-Light 배경 조건 리라이팅**: 카드를 플레이트 광원에 맞춰 리라이트. 핵심 최적화: STOCK 카드 × STOCK 플레이트 조합은 유한하므로 **리라이트 결과를 (card, location) 쌍으로 사전 계산해 8-6 라이브러리에 캐싱** — 런타임 비용 0. Tier 1부터 적용하고 A/B로 각 티어의 기여를 측정, 충분해지면 상위 티어 중단(YAGNI). 참고: IC-Light ComfyUI 노드, DreamLight, harmonization diffusion 계열. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.8: 캐릭터 마이크로 모션 기법 선택 — 닫힌 enum + procedural overlay

Jay 지시(2026-07-08): 캐릭터의 역동성을 위한 떨림 등 다양한 업계 표준 기법을 추가. 1.9c/7.3의 고정 sway/bob/parallax를 확장하되, LLM이 자유 숫자나 자유 텍스트를 만들지 않도록 cast 멤버에 닫힌 `motion_style`/`motion_energy` enum을 추가한다. 후보 스타일: `hold`, `breath`, `sway`, `tremble`, `pulse`, `glitch`; 강도: `low|medium|high`. 구현은 새 workflow stage가 아니라 기존 `visual_breakdown` cast schema 확장 + `scenario_chain.parse_cast` lenient normalization + `video_node`의 FFmpeg per-frame overlay/scale expression 소비. 업계 표준 근거: game animation의 state/blend-tree식 제어 파라미터, motion graphics의 procedural wiggle, 2D animation의 secondary motion/follow-through를 이 프로젝트 비용 구조에 맞게 정적 RGBA 카드 변환으로 근사. 8.9와 분리 — 이 스토리는 제자리 생동감/secondary motion만 담당.

### Story 8.13: 파생 개체 카드 온디맨드 생성 — `<scp_id>-<n>`

Jay 결정(2026-07-09, iteration 1 시청 피드백 후속): SCP-049 런에서 `cast_decision`이 자신이 가르친 어휘(`<scp_id>-<n>`, 예 `SCP-049-2`)대로 파생 개체를 10샷에 배정했는데, 그 카드가 자산 라이브러리에 없어 video_node가 전부 스킵(`no character row for cast member SCP-049-2, skipping` ×10) — "이 개체들은 SCP-049-2로 분류됩니다" 나레이션에 빈 방이 나옴. Jay가 어휘 제한 대신 **온디맨드 생성**을 선택 — 049류처럼 파생 개체가 서사 핵심인 SCP에서 화면 표현력을 지키기 위함. 런타임 트리거는 8.4의 선례(post-scenario, `run_service._ensure_special_pose_cards` 패턴 — cast를 스캔해 없는 카드를 발견하면 캡 걸고 생성)를 따르되, 실제 생성 호출은 8.4의 `generate_special_pose_card`가 아니라 8.2의 **`CharacterService.generate_cards_from_descriptor(card_key, descriptor, anchor_path=...)`**를 재사용 — 이 함수가 이미 `card_key`에 대해 `Character` 행이 없으면 `_ensure_character`로 새로 만들고, `anchor_path`로 기존 개체의 승인 카드를 IPAdapter 레퍼런스 삼아 4앵글을 생성함(family 유사성은 이 파라미터로 이미 지원됨 — 8.4의 `generate_special_pose_card`는 반대로 "기존 identity 필수"라 파생체엔 못 씀). 신규 워크플로 스테이지 없음. 트리거 조건: cast_decision이 참조한 `card_key`가 `check_existing_character`로 안 잡히면 base 개체(`<scp_id>` 부분)의 승인된 front 카드 경로를 `anchor_path`로, visual_breakdown 사이드카의 파생체 묘사를 `descriptor`로 넘겨 생성. 8.6 자산 레지스트리에 `draft` 상태로 등록, run 승인 없이 approved 직행(8.6의 파이프라인 자동생성 카드 선례와 동일 취급). 비용: 파생 개체 1종당 4앵글 ComfyUI 생성 — 런당 캡으로 무한 생성 방지. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.9: 캐릭터 이동·블로킹 — screen-space locomotion enum

Jay 지시(2026-07-08): 캐릭터 이동에 대한 업계 표준 기법 추가. 8.8과 분리해 이동/블로킹 전용 안전 문제(클리핑, 자막 침범, depth 변화, z-order 안정성)를 다룬다. cast 멤버에 닫힌 `movement_mode`/`movement_direction`/`movement_pace` enum을 추가한다. 후보 모드: `anchored`, `drift`, `enter`, `exit`, `cross`, `approach`, `retreat`; 방향: `none|left|right|in|out`; 속도: `slow|medium|fast`. 구현은 새 workflow stage가 아니라 기존 `visual_breakdown` cast schema 확장 + `video_node` screen-space transform curve 소비. `position`/`depth`는 안정된 composition contract로 유지하고, movement enum은 카드가 그 위치에 도착/이탈/접근/후퇴하는 방식을 기술한다. 진짜 walk-cycle/rigging/generated video는 명시적 non-goal — 필요 시 별도 아키텍처 결정. **(2026-07-09 iteration 1 시청 피드백 #4로 우선순위 상향 — 8.11 이후 착수, 8.11 없이는 씬당 1컷이라 이동이 체감되지 않음.)**

### Story 8.11: per-shot 컷 어셈블리 — video_node 샷 단위 서브클립

Jay 시청 피드백(2026-07-09, iteration 1 run `d55a265b` #5/#6). 근본 원인 코드로 확정: `video.py _compose_scene`이 씬당 "image_path 있는 첫 샷" 1장만 배경으로 사용(`video.py:745`) — visual_breakdown이 샷별 정합 이미지 87장을 만들어도 8장(씬당 1장)만 화면에 나가고, 씬의 모든 나레이션 문장이 첫 문장용 그림 위에 흐름 → "나레이션과 뜬금없는 영상" 체감. 해소: 씬 세그먼트를 **샷 단위 서브클립**으로 분해. 타이밍 재료는 전부 기존 state에 있음 — `ShotData.sentence_indices` + `SceneState.word_timings`(whisperx) + `subtitle.py sentence_cues`의 문장 윈도우 로직 재사용. 샷 경계 = 해당 샷 문장들의 첫 시작~마지막 끝. 구조 권장: ① 샷별 무음 비주얼 클립(zoompan+카드 합성+하모나이즈, `select_effect(shot, …)`는 이미 per-shot 시그니처) → ② concat → ③ 씬 레벨에서 나레이션 오디오+자막 burn+사운드 디자인+그레이드(오디오·자막은 씬 단위 유지, 컷만 증가). 지나치게 짧은 샷(예: "겨우 0.1초." 1.2s)은 최소 컷 길이 미달 시 이전 샷에 병합(config 노브). 8.9(이동)·8.12(배치 캘리브레이션)의 체감 전제 조건 — 이 스토리가 최우선. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.12: cast_decision 배치·스케일 캘리브레이션 — 프롬프트 전용

Jay 시청 피드백(2026-07-09 #2/#3). iteration 1 실측: position 분포 center 65/right 10/left 8 — 코드는 3분할 배치를 지원하는데 LLM이 center로 도피; depth 분포 near 37/mid 44/far 2 — 사실상 전부 크게 뽑혀 "크기가 우연히 맞은 느낌". 코드 변경 없음, `prompts/scenario/cast_decision.md` 규칙 추가: ① rule-of-thirds 배분 원칙 + 연속 샷 center 반복 금지(관찰/대화/이동 구도는 좌우 슬롯), ② camera_angle↔depth 정합 규칙(wide↔far/mid, close-up↔near 등 표), ③ few-shot 예시를 분포 교정용으로 교체. 파생 개체(`<scp_id>-<n>`) 어휘는 이 스토리에서 건드리지 않음(049-2 카드 갭은 별도 결정 대기). 배경 구도 다양화(오프센터 앵글)는 visual_breakdown 프롬프트에 1줄 — center 편향의 절반은 중앙 소실점 배경이 원인. PROMPT_POLICY 준수: candidate 시딩→golden-set 게이트→승격. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.15: STOCK 캐릭터 얼굴 마스크 편향 수정

2026-07-12 라이브 E2E 런(SCP-049, run `c6be1954`) 리뷰 중 Jay가 스크린샷으로 발견: `assets/characters/STOCK-d-class/epoch_1/front_candidate_1.png`, `STOCK-researcher/epoch_1/front_candidate_1.png` 둘 다 SCP-049 본인과 동일한 해골 마스크+빨간 눈 얼굴로 렌더링됨 — 일반인 얼굴이어야 할 D계급/연구원(STOCK-researcher 서술 자체가 "researcher **or doctor**"라 "의사"는 별도 롤 아님)이 개체와 구분이 안 감. `scripts/seed_stock_cast.py`의 `STOCK_DESCRIPTORS`엔 옷차림·체형만 있고 얼굴 언급이 전혀 없음 — 캐릭터 생성 LoRA/체크포인트가 SCP 마스크 쪽으로 편향돼 얼굴 미지정 시 그리로 붕괴하는 것으로 추정. STOCK-security도 같은 원인 가능성 있어 동일 검수 대상에 포함. 수정: `STOCK_DESCRIPTORS`에 명시적 얼굴 지침("ordinary human face, no mask, no glowing eyes, plain forgettable features") + negative prompt 보강, epoch_2로 3종 전원 재생성, Jay 승인 게이트. 서비스 분리 불필요(기존 `seed_stock_cast.py` 콘텐츠 수정). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.16: 깊이 인지 배치 + IC-Light 재조명 — 카드 컴포지팅 고도화

2026-07-12 라이브 E2E 런 스크린샷 리뷰(Jay): 카드가 배경 원근/바닥에 안 맞고 공중에 뜬 것처럼 보임(스케일·배치 결함) — 8.7 harmonization(Tier 1/2, 틴트·컨택트섀도)은 색/조명 불일치용이라 이 결함엔 대응 못 함(현재 런은 `composite_harmonization_tier=0` 기본값으로 돌아 Tier 1/2조차 미적용 상태였음도 확인됨). Epic 8 자체를 되돌려 전면 img2img 재생성으로 가자는 제안도 검토했으나, 실제 논문(arXiv 2512.16954 "Lights, Camera, Consistency: A Multistage Pipeline for Character-Stable AI Video Stories") 조사 결과 그 방식도 배치·스케일·오클루전 메커니즘이 전혀 없어(텍스트 설명 + I2I의 암묵적 공간 이해에만 의존) 동일 결함이 재발할 위험이 확인됨. 업계 실무 자료(2026 AI 애니메이션 프로덕션 리포트)도 "캐릭터·배경을 따로 생성해 레이어로 합성"이 동시 생성보다 안정적이라고 명시 — 카드 아키텍처(8.1-8.13) 유지 결정, 대신 다음 두 조각을 추가:
① **깊이 인지 배치**: 배경 생성 직후 monocular depth 모델(예 Depth-Anything, 로컬 실행) 1회 실행 → 바닥면/소실점 추정. `position`/`depth` enum을 고정 좌표표가 아니라 이 depth map 기반 계산값으로 변환해 실제 배경마다 정확한 스케일/앵커를 얻는다. 같은 depth map으로 오클루전 마스크를 만들어 전경 오브젝트가 카드보다 앞이면 카드를 가리게 처리(현재 카드 오버레이엔 오클루전 개념 자체가 없음).
② **IC-Light 재조명**: `ComfyUI-IC-Light-Native`(`iclight_sd15_fbc`, background-conditioned 모델)를 설치해 배경 조명에 맞춰 카드를 재조명 — 8.7 스토리가 "로컬 커스텀 노드 부재로 deferred" 처리한 가정이 최신 조사로는 더 이상 유효하지 않을 가능성이 큼(해당 노드가 실제 존재·문서화됨), 실제 설치·ROCm 안정성(추가 SD1.5 로드가 크래시 빈도에 미치는 영향)은 이 스토리에서 재검증 필요.
Tier 1/2는 IC-Light 비활성/실패 시 폴백으로 유지(별도 스토리로 분리하지 않고 이 스토리의 AC로 흡수). 구현은 신규 **`services/compositing_service.py`**로 분리 — `video_node`의 ffmpeg 조립 로직에 depth/relight 호출을 직접 섞지 않고 "카드+배경+메타 → 배치·조명 보정된 합성 이미지"라는 좁은 인터페이스로 캡슐화(복잡도를 파이프라인 핵심부 밖으로 격리). **필수 AC**: D5(앵글 불일치)/D10(인페인트 흉터)/D11(환경 오컷)/D13(무알파 전체 덮음) — 1.6b/5-6/5-7 시절 결함 — 재발 방지를 명시적으로 검증. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.17: 스톡 로케이션 플레이트 실데이터 생성 + AI 자동 라벨링

8.5는 스토리 자체는 "done"이지만 2026-07-12 확인 결과 `location_plates` DB 테이블 행 0개, `assets/locations/`도 빈 디렉토리 — 스키마/서비스/시드스크립트는 완성됐으나 한 번도 실행된 적이 없어 image_node의 STOCK fast-path가 실전에서 전혀 타지 않고 매 런마다 배경을 새로 생성 중이었음("done"의 정의에 산출물 존재 검증이 빠져 있었던 사례). 실행: `scripts/seed_location_plates.py`로 14개 LocationKey × 3배리언트 = 42장 생성(ComfyUI IPAdapter 스타일 앵커, 기존 로직과 완전 독립된 오프라인 배치 — 파이프라인 코드/배선 변경 없음). 라벨링은 전량 수동 대신 이미 배선된 Qwen-VL(5.13 인프라 재사용, HITL 관행)로 1차 자동 검수: location_key 설명 정합성 / 원치 않는 인물·텍스트 여부(배경 프롬프트 순응도, D11류) / 품질을 스코어링해 명확 통과는 auto-approved, 애매한 것만 draft로 남겨 Jay 큐에 노출. Jay는 `scripts/approve_location_plate.py`로 플래그된 것만 최종 검토("나는 최종 검사만"). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.18: cast_decision 출력 결정론적 배치 다양성 validator

8.12(프롬프트 캘리브레이션만)로 분포는 크게 개선됐으나(center 78%→16.8%) "연속 샷 center 반복 금지" 같은 규칙 준수는 여전히 LLM이 프롬프트 지시를 얼마나 잘 따르느냐에만 의존 — 코드 레벨 강제가 없음. 6.7/6.11의 결정론적 repair 패턴을 재사용: cast_decision 출력이 배치 다양성 규칙(연속 N샷 이상 동일 position/depth 금지, camera_angle↔depth 모순 등)을 위반하면 LLM 재호출 없이 결정론적 재배정(round-robin 등)으로 즉시 수정. 순수 함수형 검증/보정 로직이라 별도 서비스로 분리하지 않고 `scenario_chain.py` 내부 함수로 구현 — 서비스 추출은 이 경우 불필요한 인터페이스(ponytail: 1개 구현에 인터페이스 금지). 회귀 테스트: LLM이 의도적으로 전부 동일 값을 낸 fake 케이스로 repair 동작 검증. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.19: 임베딩 기반 자산 재사용 판정 계층

5.5(비주얼 정합성, done) 이후에도 이미지-나레이션 불일치가 지속 관찰됨(Jay, 2026-07-12) — 원인은 "STOCK 재사용 vs 자유생성" 판단이 계산된 유사도가 아니라 LLM의 프롬프트 판단에만 의존하기 때문으로 추정(8.18과 동일 근본 원인 계열: "잘 부탁하기"에 머물러 있음). 업계 선례(arXiv 2307.06940 "Animate-A-Story: Storytelling with Retrieval-Augmented Video Generation" — 텍스트로 기존 자산을 검색하고, 검색 결과가 신규 생성을 가이드하는 하이브리드 구조, CLIP류 임베딩 유사도 기반) 적용. 신규 **`services/asset_retrieval_service.py`**로 분리 — 샷의 image_prompt/narration 세그먼트를 임베딩하고 STOCK 로케이션/카드 라이브러리 항목(설명 텍스트)과 유사도 계산 → 임계값 이상이면 재사용(8.16의 depth/relight로 해당 배경에 맞게 추가 보정), 미만이면 자유생성 후 8.6 라이브러리에 신규 draft로 등록(라이브러리가 런을 거듭할수록 자기 성장). cast_decision과 location 판단 양쪽이 공유하는 좁은 인터페이스("텍스트 → 최적 매칭 자산 또는 None")로 설계 — 복잡도를 별도 서비스로 격리. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.20: OpenPose 골격 조건화 액션 포즈 생성

2026-07-12 SCP-049 라이브 런 실측: cast 배치 151건 중 pose enum은 standing 105/sitting 46 단 두 값뿐이고, `pose_hint`(자유 텍스트 특수 동작 묘사) 요청은 10건인데 `special_pose_max_per_run=3` 캡 때문에 최대 3건만 실제 카드 생성 가능 — 151건 중 148건이 사실상 동일 정적 스프라이트 반복(Jay: "획일적"). 업계 선례 조사: OpenPose ControlNet + IPAdapter FaceID(weight~1.2 권장) 조합이 정체성 95%+ 유지하며 포즈를 바꾸는 표준 기법인데, 현재 8.4는 `pose_hint`를 순수 텍스트 프롬프트로만 소비 — 골격 조건화가 없음. 오픈소스 `ComfyUI_VNCCS`(Visual Novel Character Creation Suite — 캐릭터 정체성 유지하며 포즈/표정 다양화가 목적으로 이미 존재)를 자체 구현 전에 우선 평가. 채택 시 신규 **`services/pose_service.py`**로 분리(8.4의 온디맨드 트리거 인프라는 재사용, 실제 생성 호출만 텍스트 프롬프트에서 골격 조건화로 교체) — 복잡도를 캐릭터 카드 파이프라인 핵심부 밖으로 격리. **즉시 완화책(스토리 아님, config 변경)**: `special_pose_max_per_run` 캡 상향만으로도 지금 인프라 그대로 반복 즉시 완화 가능. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 9: Localization Config — 콘텐츠 언어 스위치

Jay 결정(2026-07-07): SCP 채널은 한국어로 확정 진행하되, 향후 언어 피벗 가능성에 대비해 "한국어 하드코딩"을 명시적 config 스위치 뒤로 옮긴다. Scope는 스위치 자체뿐 — 실제 다국어 생성(프롬프트 번역, TTS 자연화 규칙, 자막 타이포그래피 재조정)은 이 Epic의 범위가 아니다(YAGNI). 지금 하드코딩된 지점(scenario LLM 프롬프트 5개, TTS 자연화 단계, subtitle.py 타이포 상수)을 건드리지 않고, 새 config 값이 "ko" 외의 값으로 바뀌면 파이프라인이 조용히 깨진 결과물을 만들지 않고 즉시 명확하게 실패하도록 만든다.

### Story 9.1: 콘텐츠 언어 config 스위치

`Settings.content_language`(env `YTFLOW_CONTENT_LANGUAGE`, 기본값 `"ko"`) 신설. `scenario_node` 진입 시 `"ko"`가 아니면 즉시 `NotImplementedError`로 실패(다국어 생성은 미구현임을 명시). 현재 한국어에 암묵적으로 의존하는 지점 전체(scenario 프롬프트 5개, `tts_normalize`, subtitle.py의 Pretendard 타이포/줄바꿈 상수)를 config.py 주석에 한 곳에 모아 문서화 — 실제 동작 변경 없음, 향후 다국어 작업의 체크리스트 역할. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 10: 서사 구조 다양화

2026-07-12 Jay 시청 피드백(SCP-049 E2E 런) 발의. `prompts/scenario/structure.md`가 "INCIDENT-FIRST 4막 구조"(사건으로 시작→미스터리 확장→정체 공개→미해결 결말)를 모든 SCP에 강제하는 유일한 고정 템플릿임을 확인 — 서사 구조 다양성이 지금까지 스코프에 들어간 적이 없어 매 에피소드가 같은 패턴으로 반복되는 것으로 체감됨.

### Story 10.1: 스토리 아키타입 다변화

고정 INCIDENT-FIRST 4막 외에 2-3개 아키타입 추가(예: 인터뷰/증언 로그식, 봉쇄 실패식, 배치 성공식) — 실제 다큐/크리피파스타 페이싱 기법(콜드 오픈, 신뢰 못 할 화자, 비선형 타임라인) 레퍼런스 반영. SCP별 로테이션 또는 LLM이 소재에 맞게 선택. 아키타입별 골든 예시(few-shot) 1-2개씩 큐레이션해 6.2 golden-set 인프라에 연결, PROMPT_POLICY 절차 준수. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**운영 잡일 (스토리 번호 없음, 2026-07-12 Jay 시청 피드백)**: ① 챕터 카드 표시 시간 2배 — `MIN_CARD_DURATION`(1.5→3.0)/`MAX_CARD_DURATION`(2.5→5.0), `video.py`. ② 씬 경계 음성 fade/오버랩 원인 조사 — 5.9/5.16 코드는 나레이션 무가공 통과를 보장하므로(재확인 완료) 실제로 들리는 현상의 원인은 7.1 사이드체인 릴리즈 "숨쉬기" 또는 Qwen TTS 발화 꼬리 중 하나로 추정, 실제 파형 분석 후 원인 확정 필요.
