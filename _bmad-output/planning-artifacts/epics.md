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
