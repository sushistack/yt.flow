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

*Workflow baseline: `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (animagineXL_v31 + darkness_xl_v2 LoRA 0.5; 1216×832; prompt injection at nodes 6/7). Copy from `~/Documents/myWorkflows/` before starting. **2026-08-09 (Story 10.3): the `horror` LoRA that used to sit at 0.6 in this stack was removed — it is SD1.5-layout and was silently failing to load against the SDXL checkpoint. Do not re-add it.***

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

2026-07-12 라이브 E2E 런 스크린샷 리뷰(Jay): 카드가 배경 원근/바닥에 안 맞고 공중에 뜬 것처럼 보임(스케일·배치 결함) — 8.7 harmonization(Tier 1/2, 틴트·컨택트섀도)은 색/조명 불일치용이라 이 결함엔 대응 못 함(현재 런은 `composite_harmonization_tier=0` 기본값으로 돌아 Tier 1/2조차 미적용 상태였음도 확인됨). Epic 8 자체를 되돌려 전면 img2img 재생성으로 가자는 제안도 검토했으나, 실제 논문(arXiv 2512.16954 "Lights, Camera, Consistency: A Multistage Pipeline for Character-Stable AI Video Stories") 조사 결과 그 방식도 배치·스케일·오클루전 메커니즘이 전혀 없어(텍스트 설명 + I2I의 암묵적 공간 이해에만 의존) 동일 결함이 재발할 위험이 확인됨. 업계 실무 자료(2026 AI 애니메이션 프로덕션 리포트)도 "캐릭터·배경을 따로 생성해 레이어로 합성"이 동시 생성보다 안정적이라고 명시 — 카드 아키텍처(8.1-8.13) 유지 결정, 대신 다음 두 조각을 추가. **참고**: NVIDIA의 학습-불필요(training-free) 멀티샷 캐릭터 일관성 연구(Video Storyboarding, research.nvidia.com/labs/par/video_storyboarding — self-attention query feature 공유로 identity 유지)도 명시적 배치/스케일/오클루전 제어가 없다는 동일한 한계를 보여 카드 아키텍처 유지 결정을 다시 한번 뒷받침함.
① **깊이 인지 배치**: 배경 생성 직후 monocular depth 모델(예 Depth-Anything, 로컬 실행) 1회 실행 → 바닥면/소실점 추정. `position`/`depth` enum을 고정 좌표표가 아니라 이 depth map 기반 계산값으로 변환해 실제 배경마다 정확한 스케일/앵커를 얻는다. 같은 depth map으로 오클루전 마스크를 만들어 전경 오브젝트가 카드보다 앞이면 카드를 가리게 처리(현재 카드 오버레이엔 오클루전 개념 자체가 없음).
② **IC-Light 재조명**: `ComfyUI-IC-Light-Native`(`iclight_sd15_fbc`, background-conditioned 모델)를 설치해 배경 조명에 맞춰 카드를 재조명 — 기반 논문은 Zhang, Rao & Agrawala, "IC-Light: Scaling In-the-Wild Training for Diffusion-based Illumination Harmonization and Editing by Imposing Consistent Light Transport" (ICLR 2025 oral, github.com/lllyasviel/IC-Light). 8.7 스토리가 "로컬 커스텀 노드 부재로 deferred" 처리한 가정이 최신 조사로는 더 이상 유효하지 않을 가능성이 큼(해당 노드가 실제 존재·문서화됨), 실제 설치·ROCm 안정성(추가 SD1.5 로드가 크래시 빈도에 미치는 영향)은 이 스토리에서 재검증 필요. **라이선스 경고(2026-08-01 리서치)**: IC-Light **v2(Flux 기반)는 비상업 라이선스**이고 SDXL/FLUX용 ComfyUI 래퍼 지원도 미완 — 수익화 채널이므로 v1(SD1.5, `fbc`)만 사용하고 v2로 업그레이드하지 말 것.
③ **마스크드 저-denoise 융합 패스(2026-08-01 리서치 추가)**: relight 후 합성 프레임에 캐릭터+팽창 테두리 영역을 마스크로 한 img2img 패스(denoise ~0.2–0.3) 1–2회 — 지오메트리는 유지하면서 경계 아티팩트를 녹이고 조명 일관성을 밀착시키는, "스티커 룩"을 죽이는 커뮤니티 표준 마감 단계(리서치 문서 Area 3.4 Tier-1 레시피). 무거운 1회보다 가벼운 2회가 낫다는 것이 관행 수렴. 기존 SDXL/SD1.5 체크포인트 재사용, 신규 모델 없음.
④ **libcom 그림자 생성 + 합성 QA 스코어(2026-08-01 리서치 추가)**: pip 설치형 `libcom`(BCMI, github.com/bcmi/libcom)의 shadow generation으로 접지 그림자 생성(현 Tier1 `geq` 타원 그림자보다 원리적 우위 — 배경 광원 방향 반영) + 같은 라이브러리의 **composite quality scoring을 자동 QA 게이트로** 채택해 "재발 방지 AC"를 사람 눈이 아닌 측정값으로 검증. 단 학습 데이터가 포토리얼 기준이라 스타일라이즈드 카드에서의 스코어 신뢰도는 이 스토리에서 소규모 캘리브레이션(정상/결함 합성 각 5장 스코어 분포 확인) 후 임계값 결정.
카드 알파 엣지 페더(하드스냅 제거)는 **11.1 소관**이므로 이 스토리 범위에서 제외하되, 11.1이 선행돼야 ③ 융합 패스의 효과 측정이 깨끗함(착수 순서: 11-1 → 8-16).
Tier 1/2는 IC-Light 비활성/실패 시 폴백으로 유지(별도 스토리로 분리하지 않고 이 스토리의 AC로 흡수) — 폴백 고도화 시 Intrinsic Harmonization for Illumination-Aware Compositing(arXiv 2312.03698)를 참고: 별도 학습 없이 세그먼트된 전경/배경에 대해 albedo 영역 색보정 + 셰이딩 재조명을 자기지도 방식으로 수행하고 depth map도 불필요해, 현재 Tier1/2의 틴트·컨택트섀도보다 원리적으로 더 정교하면서도 IC-Light보다 가벼운 대안이 될 수 있음(단, 포토리얼 소재 기준 논문이라 스타일라이즈드 카드에는 검증 필요). 유사 계열인 Relightful Harmonization(arXiv 2312.06886)은 인물 초상 전용·재조명 모델 자체 학습이 필요해 전신 카드 컴포지팅엔 부적합하다고 판단, 채택 대상에서 제외. 구현은 신규 **`services/compositing_service.py`**로 분리 — `video_node`의 ffmpeg 조립 로직에 depth/relight 호출을 직접 섞지 않고 "카드+배경+메타 → 배치·조명 보정된 합성 이미지"라는 좁은 인터페이스로 캡슐화(복잡도를 파이프라인 핵심부 밖으로 격리). **필수 AC**: D5(앵글 불일치)/D10(인페인트 흉터)/D11(환경 오컷)/D13(무알파 전체 덮음) — 1.6b/5-6/5-7 시절 결함 — 재발 방지를 명시적으로 검증. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.17: 스톡 로케이션 플레이트 실데이터 생성 + AI 자동 라벨링

8.5는 스토리 자체는 "done"이지만 2026-07-12 확인 결과 `location_plates` DB 테이블 행 0개, `assets/locations/`도 빈 디렉토리 — 스키마/서비스/시드스크립트는 완성됐으나 한 번도 실행된 적이 없어 image_node의 STOCK fast-path가 실전에서 전혀 타지 않고 매 런마다 배경을 새로 생성 중이었음("done"의 정의에 산출물 존재 검증이 빠져 있었던 사례). 실행: `scripts/seed_location_plates.py`로 14개 LocationKey × 3배리언트 = 42장 생성(ComfyUI IPAdapter 스타일 앵커, 기존 로직과 완전 독립된 오프라인 배치 — 파이프라인 코드/배선 변경 없음). 라벨링은 전량 수동 대신 이미 배선된 Qwen-VL(5.13 인프라 재사용, HITL 관행)로 1차 자동 검수: location_key 설명 정합성 / 원치 않는 인물·텍스트 여부(배경 프롬프트 순응도, D11류) / 품질을 스코어링해 명확 통과는 auto-approved, 애매한 것만 draft로 남겨 Jay 큐에 노출. Jay는 `scripts/approve_location_plate.py`로 플래그된 것만 최종 검토("나는 최종 검사만"). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.18: cast_decision 출력 결정론적 배치 다양성 validator

8.12(프롬프트 캘리브레이션만)로 분포는 크게 개선됐으나(center 78%→16.8%) "연속 샷 center 반복 금지" 같은 규칙 준수는 여전히 LLM이 프롬프트 지시를 얼마나 잘 따르느냐에만 의존 — 코드 레벨 강제가 없음. 6.7/6.11의 결정론적 repair 패턴을 재사용: cast_decision 출력이 배치 다양성 규칙(연속 N샷 이상 동일 position/depth 금지, camera_angle↔depth 모순 등)을 위반하면 LLM 재호출 없이 결정론적 재배정(round-robin 등)으로 즉시 수정. 순수 함수형 검증/보정 로직이라 별도 서비스로 분리하지 않고 `scenario_chain.py` 내부 함수로 구현 — 서비스 추출은 이 경우 불필요한 인터페이스(ponytail: 1개 구현에 인터페이스 금지). 회귀 테스트: LLM이 의도적으로 전부 동일 값을 낸 fake 케이스로 repair 동작 검증. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 8.19: 자산 재사용 판정 강화 — stdlib/LLM 우선, 임베딩은 최후 수단

5.5(비주얼 정합성, done) 이후에도 이미지-나레이션 불일치가 지속 관찰됨(Jay, 2026-07-12) — 원인은 "STOCK 재사용 vs 자유생성" 판단이 계산된 유사도가 아니라 LLM의 프롬프트 판단에만 의존하기 때문으로 **추정**(8.18과 동일 근본 원인 계열: "잘 부탁하기"에 머물러 있음, 확정된 진단 아님). 업계 선례(arXiv 2307.06940 "Animate-A-Story: Storytelling with Retrieval-Augmented Video Generation" — 텍스트로 기존 자산을 검색하고, 검색 결과가 신규 생성을 가이드하는 하이브리드 구조, CLIP류 임베딩 유사도 기반)가 이 문제 유형에 대응하는 업계 방향성 자체는 뒷받침하지만, 이 프로젝트는 현재 임베딩 모델·라이브러리를 어떤 형태로도 쓰고 있지 않음(pyproject.toml 확인 완료, DeepSeek 연동도 `/chat/completions`뿐 임베딩 엔드포인트 없음) — 신규 의존성 도입 결정이라 사다리를 낮은 단부터 재확인.
**0단계(착수 전제)**: 임베딩 계층을 만들기 전에 최근 이미지-나레이션 불일치 사례 3-5건을 직접 추적해 "STOCK 재사용 판단 실패"가 실제 원인인지부터 확인 — 6.9/6.10에서 추정 원인으로 바로 코드를 고쳤다가 실은 노이즈였던 전례([[project_6-9-done-6-10-created]] 참고) 반복 방지.
**1단계(1차 시도, 신규 의존성 없음)**: 8.18과 동일한 패턴 — `scenario_chain.py` 내부 순수 함수로, LLM에게 STOCK 로케이션/카드 라이브러리 항목 목록을 프롬프트에 명시적으로 제공하고 그중 하나를 고르거나 `None`(자유생성)을 고르도록 구조화 출력 강제. 텍스트 매칭이 더 필요하면 stdlib `difflib.SequenceMatcher`/키워드 집합 overlap으로 임계값 유사도 계산 — STOCK 설명 텍스트는 개발자가 쓴 통제 어휘라 자유문장 임베딩 없이도 상당 부분 커버될 가능성이 높음. 신규 서비스 분리 불필요.
**2단계(에스컬레이션, 조건부)**: 1단계로도 패러프레이즈/동음이의 매칭 실패(예: "취조실" vs "심문 방")가 실측으로 계속 확인되는 경우에만, 그때 신규 **`services/asset_retrieval_service.py`** + CLIP류 임베딩 유사도 계층 도입을 검토 — 이 경우에도 로컬 실행 가능한 경량 임베딩 모델 우선 조사(신규 유료 API 의존 지양). cast_decision과 location 판단이 공유하는 좁은 인터페이스("텍스트 → 최적 매칭 자산 또는 None")는 1단계 함수 시그니처부터 이 형태로 설계해 2단계 확장 시 내부 구현만 교체. (draft — 상세 스토리 파일은 create-story로 별도 생성. `ponytail:` 임베딩은 확정 요구사항 아님, 1단계로 부족함이 실측 확인되면 2단계로 승격)

### Story 8.20: OpenPose 골격 조건화 액션 포즈 생성

2026-07-12 SCP-049 라이브 런 실측: cast 배치 151건 중 pose enum은 standing 105/sitting 46 단 두 값뿐이고, `pose_hint`(자유 텍스트 특수 동작 묘사) 요청은 10건인데 `special_pose_max_per_run=3` 캡 때문에 최대 3건만 실제 카드 생성 가능 — 151건 중 148건이 사실상 동일 정적 스프라이트 반복(Jay: "획일적"). 현재 8.4는 `pose_hint`를 순수 텍스트 프롬프트로만 소비 — 골격/참조 조건화가 없음.
**기법 재판정(2026-08-01 리서치 — 초안의 IPAdapter FaceID 채택을 폐기)**: 초안이 표준기법으로 검토한 IPAdapter FaceID(weight~1.2)·InstantID·PuLID는 전부 **실사 인간 얼굴 인식 임베딩(insightface류) 기반**이라 이 프로젝트의 캐릭터에 부적합 — PuLID는 비실사 얼굴에서 "No face detected"로 아예 실패(github.com/ToTheBeginning/PuLID/issues/123), SCP-049(역병의사 마스크)·682/096(비인간형)·일러스트풍 인간 전원이 정확히 그 실패 케이스. 대체 주 기법: **Qwen-Image-Edit-2511(GGUF Q4 ~14GB, Apache-2.0, 16GB ROCm 적합)** 인스트럭션 편집으로 기존 승인 카드를 참조 삼아 포즈/동작을 파생 — 학습·마스크·얼굴검출 불필요, 정체성 보존이 목적 자체인 모델이며 2025-26 커뮤니티 표준(Mickmumpitz CCC v3.8도 이 모델 기반으로 전환됨, 리서치 문서 Area 3.1). 골격의 명시적 제어가 필요한 경우에 한해 **인간형(D계급/연구원/049)은 OpenPose ControlNet 병용, 비인간형은 depth/lineart/scribble 조건화**(OpenPose는 인간형 골격 전제). IPAdapter는 스타일 앵커 보조로만 사용(정체성 메커니즘 아님 — 정체성 보존력이 약해 다샷에서 드리프트, Area 3.1). InstantID/FaceCrafter 제외 판정은 유지하되 사유를 "보조 옵션 검토 가치"에서 "얼굴 임베딩 기반이라 원천 부적합"으로 정정. 오픈소스 `ComfyUI_VNCCS`(Visual Novel Character Creation Suite) 우선 평가는 유지 — 단 내부적으로 FaceID/insightface에 의존하는지부터 확인(의존 시 동일 사유로 탈락). 채택 시 신규 **`services/pose_service.py`**로 분리(8.4의 온디맨드 트리거 인프라는 재사용, 실제 생성 호출만 텍스트 프롬프트에서 참조+골격 조건화로 교체) — 복잡도를 캐릭터 카드 파이프라인 핵심부 밖으로 격리. Qwen-Edit 도입 시 각도 시트/파생 개체 카드(8.13 메커니즘)도 같은 엔진으로 통합할 수 있어 후속 스토리 후보. **즉시 완화책(스토리 아님, config 변경)**: `special_pose_max_per_run` 캡 상향만으로도 지금 인프라 그대로 반복 즉시 완화 가능. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 9: Localization Config — 콘텐츠 언어 스위치

Jay 결정(2026-07-07): SCP 채널은 한국어로 확정 진행하되, 향후 언어 피벗 가능성에 대비해 "한국어 하드코딩"을 명시적 config 스위치 뒤로 옮긴다. Scope는 스위치 자체뿐 — 실제 다국어 생성(프롬프트 번역, TTS 자연화 규칙, 자막 타이포그래피 재조정)은 이 Epic의 범위가 아니다(YAGNI). 지금 하드코딩된 지점(scenario LLM 프롬프트 5개, TTS 자연화 단계, subtitle.py 타이포 상수)을 건드리지 않고, 새 config 값이 "ko" 외의 값으로 바뀌면 파이프라인이 조용히 깨진 결과물을 만들지 않고 즉시 명확하게 실패하도록 만든다.

### Story 9.1: 콘텐츠 언어 config 스위치

`Settings.content_language`(env `YTFLOW_CONTENT_LANGUAGE`, 기본값 `"ko"`) 신설. `scenario_node` 진입 시 `"ko"`가 아니면 즉시 `NotImplementedError`로 실패(다국어 생성은 미구현임을 명시). 현재 한국어에 암묵적으로 의존하는 지점 전체(scenario 프롬프트 5개, `tts_normalize`, subtitle.py의 Pretendard 타이포/줄바꿈 상수)를 config.py 주석에 한 곳에 모아 문서화 — 실제 동작 변경 없음, 향후 다국어 작업의 체크리스트 역할. (draft — 상세 스토리 파일은 create-story로 별도 생성)

## Epic 10: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰

**슬롯 이력**: 구 Epic 10(서사 구조 다양화)은 2026-08-03 Epic 12로 흡수되었고 Story 10.1은 **Story 12.4로 이동해 done**이다(이력은 Epic 12 참조). 비워진 번호를 이 에픽이 사용한다.

**발의 근거**: 2026-08-08 Jay가 E2E 런 `8a9a288b`(SCP-049, 3분 6초) 시청 후 결함 16건 지적. 이 에픽의 존재 이유는 **"어느 스토리가 어떤 시각 결함을 실제로 없앴는지"를 추적 가능하게 만드는 것**이다 — 직전 세션에서 Epic 8 스토리들을 닫고도 시청 결과에 변화가 없었고, 무엇이 효과가 있었는지 사후에 증명할 수 없었다.

⚠️ **평가 기준선 오염**: 문제의 런은 `depth_placement_enabled=false`로 렌더되어 8.16 지면 배치와 11.5 패럴랙스가 **둘 다 꺼진 상태**였다(오케스트레이터가 처리량 병목을 depth로 오진해 비활성화 — 실제 병목은 GPU DPM이 최저 클럭에 고착된 것). 따라서 지적 3·11번은 "기능이 무효"라는 증거가 아니라 **"기능이 꺼진 채 렌더됐다"**는 사실만 말한다. 10.1이 이 구분을 먼저 짓는다.

**공통 수용 기준(전 스토리)**: 각 스토리는 닫히기 전에 *해당 지적 번호가 실제로 사라졌음*을 산출물로 보여야 한다. 테스트 통과나 코드 배선만으로는 닫지 않는다.

### Story 10.1: 접지·합성 실사 검증 — 카드가 배경에 붙어 있는가 (지적 3·11)

Jay 지적: "배경에 그냥 캐릭터 덩그러니 찢어 붙여놓은 듯", "캐릭터만 둥둥 떠 다님". 8.16(depth 지면 배치)과 11.5(2.5D 패럴랙스)가 정확히 이 결함을 없애려고 만들어졌으나 문제의 런에서는 **꺼져 있었다**. ① 먼저 두 기능을 켠 상태로 동일 SCP-049 재렌더 후 **같은 샷을 나란히 놓고 비교**(off/on 프레임 쌍) — 이것이 이 에픽 전체의 기준선이다. ② 켰는데도 "붙어 보이지 않으면" 그때부터가 실제 스토리 범위: 접지선 계산, 카드 스케일, 접촉 그림자, 색/광 정합(8.7 harmonization tier) 중 어디가 끊겼는지 프레임 단위로 규명. ③ 8.16이 자체 라이브 게이트에서 "추적 3.9px vs 정적 57.2px"를 통과했음에도 시청 체감이 개선되지 않았다면, **게이트 지표가 시청 체감을 대리하지 못한다는 뜻**이므로 그 사실 자체를 기록하고 13.2 시각 평가 축에 반영. 의존: 없음(최우선). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 10.1b: 카드-배경 융합 — harmonization tier 3 (IC-Light) 실가동 (지적 3, 10.1 후속)

10.1이 지목한 끊긴 고리를 잇는다. 판정은 "지적 11(둥둥 뜸)은 8.16이 해결, **지적 3(찢어 붙인 듯)은 미해결**, 남은 원인은 카드와 플레이트가 빛을 공유하지 않는 것"이었다. 그 답이 이미 설계에 있다 — **Story 8.7의 harmonization tier 3 = IC-Light 재조명**이며, 지금까지 한 번도 가동된 적이 없다(런 8a9a288b는 tier 1).

**전제 정정(2026-08-08 실측)**: 이 경로는 하드웨어에 막혀 있지 않다. `~/workspaces/ComfyUI/`에 **kijai `ComfyUI-IC-Light`(@`22811d9`)와 `iclight_sd15_fbc.safetensors`(1.7GB)가 2026-08-02에 이미 설치**되어 있고, fbc가 요구하는 SD1.5 베이스(`cyberrealistic_v90.safetensors`, 2.1GB)도 있다 — **VRAM ~4GB 급**이다. 8.20 DECISION-RECORD의 "16GB 미적합, 5런 중 2 OOM"은 **Qwen-Image-Edit-2511 GGUF(13.24GB)로 카드+포즈가이드에서 새 카드를 만드는 다른 경로**의 수치이므로 이 스토리에 적용되지 않는다. `data/workflows/README-iclight-relight.md`의 "로컬에 IC-Light 노드 없음"은 설치 이전에 쓰인 **스테일 기록**이다.

**코드는 이미 있다**: `composite_harmonization.relight_sprite()` / `precompute_relights()` 구현됨, `video.py:2265`가 tier ≥ 3에서 호출, 캐시 키는 `(card_key, location_key)`라 **66샷이 아니라 카드×장소 조합 수**만 돌고, 실패는 런을 죽이지 않는다(AC:11). 비어 있는 것은 두 가지뿐 — `comfyui_iclight_relight_api.json`의 노드 `"3"`~`"9"`가 **일반 SDXL 체인 껍데기**이고, 안전장치 `"ytflow_verified_iclight": true` 마커가 없어 런타임이 제출을 거부한다.

**범위**: ① 노드 3~9를 실제 IC-Light fbc 그래프(UNet 패치 + FG/BG 조건화 + SD1.5 체크포인트)로 교체 ② 카드+플레이트 **1쌍**으로 라이브 검증(그럴듯한 재조명 PNG가 실제로 돌아오는지) ③ 통과 시에만 마커 부여 ④ README 스테일 기록 정정 ⑤ **10.1의 6샷 슬레이트를 그대로 재사용해 tier 1 vs tier 3 프레임 쌍 판정** — `10-1-live-validation/off/`가 제3의 기준점으로 이미 디스크에 있고 `make_pairs.sh`·`measure.py`가 재산출을 1커맨드로 만들어 두었으므로 판정 비용이 거의 들지 않는다.

**2단계(조건부)**: IC-Light 재조명만으로 지적 3이 닫히지 않으면, 리서치 권고 레시피의 나머지 — **합성 프레임 전체에 마스크된 low-denoise(0.2~0.3) img2img 융합 패스**(엣지·그레인 통일) — 를 이어서 적용한다. 1단계 판정 전에는 착수 금지.

**제약**: IC-Light **v1(`fbc`)만** — v2/Flux는 비상업 라이선스라 수익화 파이프라인에 못 쓴다. Qwen-Image-Edit 경로 재시도 금지(8.20에서 기각). 네거티브 프롬프트 증량 금지(역효과 실증).

**착수 가치**: `YTFLOW_GEMINI_API_KEY` 없이도 진행 가능한 **유일한 Epic 10 스토리**다 — 10.1과 같이 기존 런의 `video` 스테이지만 재실행하면 되므로 신규 런이 필요 없다(10.2/10.3/10.4는 전부 신규 런이 필요해 키가 채워질 때까지 차단). (draft — 상세 스토리 파일은 create-story로 별도 생성)

---

## ⛳ 확정 방향: 카드-배경은 최종적으로 **한 장으로 융합**한다 (Jay, 2026-08-08)

> **이 블록은 방향을 잃지 않기 위한 앵커다. 이 결정에 어긋나는 제안을 하기 전에 반드시 여기부터 읽어라.**
> 2026-08-08 세션에서 담당 세션이 이 방향을 `epics.md`에서 찾지 못해 "기록에 없다"고 잘못 보고하고
> 엉뚱한 재발의를 시도했다. 원인은 방향이 제안 메시지에만 있었고 에픽에 없었다는 것. 그래서 여기 박는다.

**결정**: 카드와 배경을 ffmpeg으로 겹쳐 놓는 것이 최종 산출물이 아니다. **배경과 캐릭터 카드를 입력으로
써서 이미지를 다시 만들어야(재창조) 한다.** Jay의 표현 그대로: *"물리적으로 이어 붙이는 게 아니라"*,
*"아예 1개의 이미지로 합성"*, *"기존 배경 + 캐릭터 카드들을 이용한 이미지의 재창조"*.

### ⛔ 이것이 이 결정의 핵심이다 — "얹어놓기"와 "재창조"의 차이

| | 얹어놓기 (**금지**) | 재창조 (**이것이 방향**) |
|---|---|---|
| 카드의 역할 | **보호 대상** — 원본 픽셀이 결과물에 그대로 남는다 | **참조** — 정체성 근거로만 쓰고 픽셀은 다시 그린다 |
| 카드 정체성을 지키는 방법 | 마스크로 잠금 | **조건화**(IPAdapter) |
| 구도를 지키는 방법 | 카드를 원위치에 붙임 | **조건화**(ControlNet) |
| denoise | 낮음(0.2~0.55) | **높음(0.8~1.0)** — 전 프레임을 새로 그린다 |
| 결과 | 배경 위 카드 + 경계 블러 | 배경과 인물이 함께 그려진 한 장 |

**판별 기준 한 줄**: 결과 이미지의 카드 영역 픽셀이 원본 카드와 거의 같으면 그건 재창조가 아니라 얹어놓기다.

**명시적 금지 (2026-08-08 세션에서 실제로 두 번 저지른 실수다)**:
- ❌ 마스크로 카드 내부를 보호하는 img2img. 카드 내부를 0으로 잠그면 화풍이 **절대** 안 섞이므로
  강도를 아무리 올려도 "얹어놓은 것"으로 남는다. 실측: 마스크 0.75에서 배지는 온전했으나 카드는 여전히
  원본 셀 화풍이고 배경만 딴 방이 됐다 — 다시 그릴 자유가 배경으로만 몰린 결과.
- ❌ "마스크된 low-denoise img2img"라는 **리서치 레시피 문구를 근거로 삼는 것**. 그 문구는 융합 보조 수단을
  가리킨 것이지 이 방향의 정의가 아니다. 문구보다 **의도(재창조)가 우선**한다.
- ❌ 저노이즈 전체 프레임 img2img 단독. 정체성을 붙들 조건화가 없어 강도를 올리면 얼굴·표식이 붕괴한다.
  실측: 무마스크 0.40에서 D계급 배지 `213 5`가 한자 비슷한 글자로 붕괴, 얼굴이 다른 사람이 됨.

### 정본 구조 (재창조)

```
합성 스틸 → 전처리(canny/depth) → ControlNet ─┐  구도·배치 유지
                                              ├→ KSampler(denoise 0.8~1.0) → 재창조된 한 장
캐릭터 카드 → IPAdapter ──────────────────────┘  인물 정체성 유지
```

**마스크 없음.** 전 프레임이 새로 그려지되 구도는 ControlNet이, 정체성은 IPAdapter가 붙든다.
합성 스틸은 최종 픽셀이 아니라 **구도 골격**으로만 쓰인다.

**설치 확인 완료 (2026-08-09)**: `ip-adapter-plus_sdxl_vit-h`(847MB) + `clip_vision_vit_h`(2.5GB),
`ComfyUI_IPAdapter_plus`, `comfyui_controlnet_aux`, 노드(`IPAdapterAdvanced`/`ControlNetApplyAdvanced`/
`CannyEdgePreprocessor`/`DepthAnythingV2Preprocessor`) 전부 서버에 로드됨. **SDXL ControlNet은
Jay 지시로 canny/depth를 추가 도입한다**(기존 `controlnet-scribble-sdxl-1.0`은 구도 유지력이 약하고,
`control_v11f1p_sd15_*`는 SD1.5용이라 SDXL 체크포인트에 못 붙는다).

지적 3("찢어 붙인 듯")을 닫는 것은 **이 재창조 패스**다.

### ⛳ 배경 정책: 소스 재사용은 의도다 — "다양성 붕괴"를 고치지 마라 (Jay, 2026-08-09)

> **이 항목은 기존에 기록된 권고를 뒤집는다.** 아래를 읽지 않고 8.19의 권고만 보면 정확히 반대로 간다.

**결정**: 배경 소스가 여러 샷에 재사용되어 배경 종수가 줄어드는 것은 **버그가 아니라 의도**다.
`c6be1954` 기준 "155샷 → 41종"은 **회귀가 아니라 목표에 가까운 상태**다. 공간 연속성과 에피소드 간
일관성이 채널 아이덴티티이므로, 같은 방은 같은 그림이어야 한다.

**따라서 `stock_plate_substitution_enabled`는 켜는 방향이다** (현재 코드 기본값 `False` — `config.py:246`).

**다양성이 부족하면 소스 수를 늘려라. 한 소스에서 여러 장을 만들지 마라.**
Jay: *"소스가 되는 배경 수를 늘려야지, 하나의 소스로 여러 개를 만들려고 하지 마. 그게 더 이상해져,
일관성 없어지고."* 즉 해법은 **플레이트 라이브러리 확장**(로케이션 키 추가 / 키당 변형 추가로 실제 서로
다른 방을 더 확보)이지, 한 플레이트에서 샷마다 다른 그림을 파생시키는 것이 아니다.

**⛔ 폐기된 권고**: `8-19-embedding-asset-retrieval-layer.md`의
*"blend/condition the plate instead of replacing the prompt"* 와 그에 딸린
*"latent 85% regression in background variety / should be resolved before the next full E2E run"* 는
**이 결정으로 무효**다. 그 문서의 측정(132/155 샷이 플레이트 경로, 18종으로 해석, 런 전체 41종)은
사실로서 유효하지만, **그 사실에 붙은 "회귀다 / 고쳐야 한다"는 해석이 뒤집힌 것**이다.
`image_prompt`가 버려지는 것도 같은 이유로 결함이 아니다 — 샷별 세트 드레싱보다 방의 동일성이 우선한다.

**재창조 패스에 대한 함의(중요)**: 배경이 재사용되는 고정 소스이므로, 재창조는 **배경을 다시 지어내면
안 된다.** ControlNet을 강하게 걸어 플레이트 구도를 붙들고, 다시 그려지는 것은 주로 인물과 그 접합부여야
한다. 샷마다 배경이 달라지면 이 정책이 사려는 일관성을 재창조가 스스로 깨뜨리는 것이다.
(실측 경고: 마스크 img2img denoise 0.75에서 배경이 통째로 다른 방이 됐다 — 그 강도는 이 정책과 양립 불가.)

**⚠️ 착수 순서 (Jay, 2026-08-08): 조명은 보류하고 재창조 패스부터 한다.**
IC-Light 재조명이 라이브에서 기각됐으므로 조명을 더 만지는 데 시간을 쓰지 않는다. 현행 tier 1(틴트+
컨택트섀도+라이트랩) 위에서 곧바로 재창조 패스를 만들어 판정한다. 판정 대조는 **tier1 vs 재창조** 2갈래.
`composite_harmonization_tier` 기본값은 **1을 유지**한다(3으로 올리지 마라). 이번 세션에 만든 IC-Light
그래프·캐시·마커는 폐기하지 않고 남겨둔다 — 동작은 검증됐고 재사용 가능하다.

**폐기된 산출물 (참고용으로만 남긴다, 되살리지 마라)**: `comfyui_fusion_img2img_api.json`의 마스크 경로와
`composite_fusion.py`의 마스크 배선은 위 ⛔ 표의 "얹어놓기"에 해당한다. 프로브 증거는
`10-1b-live-validation/fusion-probe/`(무마스크 0.20/0.30/0.40, 마스크 0.35/0.55/0.75)와
`fusion-slate-055/`(6샷)에 남긴다 — **왜 이 길이 아닌지의 근거**로만 쓴다.
다만 `video.render_composite_still()`(모션 끈 합성 스틸)과 `render_card_coverage_mask()`(검정/흰 배경
2회 렌더로 카드 커버리지를 *측정*)는 재창조에서도 그대로 쓴다: 전자는 ControlNet 구도 입력이 되고,
후자는 카드 영역을 알아야 하는 판정·측정에 쓰인다. 둘 다 배치 수식을 재유도하지 않는다는 점이 핵심이다.

**1단계 라이브 판정 결과 (2026-08-08, Jay 시청)**: ⛔ **기각 — "나빠졌다"**.
tier 3 단독은 카드를 플레이트 광량에 맞춰 어둡게 내리지만 **알파 엣지를 건드리지 못해** 여전히 붙여넣은
것으로 읽힌다. 측정치는 카드-플레이트 색 거리 34.52 → 27.66(−20%)으로 개선을 가리켰으나 **시청 판정이
우선한다**(Epic 10 공통 AC: 지표가 아니라 산출물이 닫는다). 증거·수치·프레임 쌍 전량:
`_bmad-output/implementation-artifacts/spec-10-1b-card-plate-fusion-iclight-tier3.md` 및
`10-1b-live-validation/pairs/`. 이 판정으로 **2단계 착수 조건이 충족됐다.**

**받아들인 대가(명시적)**: 한 장으로 융합하면 카드가 배경과 독립적으로 움직일 수 없다 → **11.5 레이어드
패럴랙스와 캐릭터 idle motion이 사라진다.** 이는 손실이 아니라 **의도된 제거**다 — 접지(8.16)가 맞는데도
"둥둥 떠 보이는" 잔여 원인이 카드와 배경의 **모션 불일치**라는 것이 유력한 진단이기 때문이다. 따라서
아래 1365행 부근의 "레이어 분리 = 우리 아키텍처 고유 이점" 서술은 **이 결정으로 대체된다.**

**금지(재논의 금지 항목)**: IC-Light v2/Flux 계열(비상업 라이선스), 네거티브 프롬프트 증량(2회 역효과 실증).

**⛔ 2026-08-09 폐기 — composite-then-refine 계열 전부 제거한다**

Jay 판정: 아래는 전부 "얹어놓고 고치기"이며 **재창조가 아니다. 되살리지 마라.**

| 폐기 대상 | 무엇이었나 | 라이브 판정 |
|---|---|---|
| harmonization **tier 3 (IC-Light 재조명)** | 카드를 배경 광량에 맞춰 재조명 | Jay 시청 "나빠졌다" — 기각 |
| **마스크 low-denoise img2img 융합** | 카드 픽셀 보호 + 경계만 재생성 | Jay "그냥 얹어놓고 그림자 수정" — 기각 |
| **ControlNet+IPAdapter를 합성 스틸에 적용** | 합성 스틸이 구조소스이자 img2img 시작 latent | 배치를 여전히 ffmpeg 산술이 결정 — 기각 |

**왜 전부 같은 실패인가**: 셋 다 *이미 얹어놓은 결과*를 입력으로 받는다. 그래서 인물의 위치·크기·포즈를
`_POSITION_X_FRAC`/`_DEPTH_SCALE`/`ground_y` 같은 **코드 상수**가 결정하고, 모델은 그 위를 덧칠할 뿐이다.
바닥이 없는 플레이트(예: 벽돌벽 S00202)에서는 어떤 상수도 인물을 세울 수 없어 계속 둥둥 뜬다.

**리서치 근거 (2026-08-09 조사)**: 이 분야는 **composite-then-refine**(구식)과 **generative insertion**
(현행)으로 갈려 있으며(BCMI `Awesome-Generative-Image-Composition` 분류), 2025–2026 연구는 후자로 이동했다.
`Insert In Style`(arXiv 2511.15197)은 **텍스트 프롬프트도 마스크도 없이** 배경+참조만으로 배치·조화를 수행하며,
참조와 배경의 **화풍이 다른 cross-domain**을 정면으로 다룬다 — 우리 상황(셀 카드 × 다른 화풍 플레이트)과 동일.
그 논문이 지적하는 unified-attention의 *concept interference*는 우리가 실측한 현상과 같은 부류다:
IPAdapter가 카드 팔레트를 전 프레임에 밀어 방이 보라색이 됐고(색캐스트 7.4→33.3), attn_mask로 임시 봉합했다.

**⛳ 대체 방향**: **배경 + 캐릭터 카드 + 자연어 배치 지시 → 모델이 배치하고 한 장으로 생성.**
좌표를 코드가 만들지 않는다. 어차피 `position`/`depth`는 이미 `visual_breakdown` LLM이 정하는 값이며
(`CastMember`, `scenario_chain.py`는 검증·보정만 함), 코드는 그것을 3단계 이산값 → 고정 분수로 **깎아** 쓰고 있었다.
자연어로 넘기면 그 정보 손실이 사라진다.

**받아들이는 대가(명시)**: 위치 재현성 하락(같은 프롬프트라도 샷마다 배치가 달라질 수 있음), 카드 정체성이
ControlNet 실루엣 고정 없이 참조 조건화에만 의존, 그리고 **8.16 접지·`_GROUND_Y_MAX` 클램프·오클루전 마스크·
컨택트 섀도·11.5 레이어드 패럴랙스가 전부 무용지물이 된다.** 이는 손실이 아니라 이 결정의 귀결이다.

**⚠️ "Qwen-Image-Edit 재시도 금지"는 무효다.** 8.20의 기각(2026-08-04)은 **다른 버전·다른 용도**였다 —
카드+포즈가이드로 *새 카드*를 만드는 경로, GGUF 13.24GB 기준 "16GB 미적합, 5런 중 2 OOM".
현행 **Qwen-Image-Edit-2511**은 Apache-2.0이고 `Q4_K_M` 기준 **12GB**이며, 2511의 개선점이
*다중 이미지 편집 일관성 / 단일 참조 다각도 생성 / 포즈·화풍 변환 간 얼굴 정체성 보존* 으로 이 용도와 정합한다.
**설치 자산은 이미 전부 존재한다**(8.20 잔여): `models/unet/qwen-image-edit-2511-Q4_K_M.gguf`,
`text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`, `vae/qwen_image_vae.safetensors`,
`loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors`, 노드 `UnetLoaderGGUF`/`TextEncodeQwenImageEditPlus`.
단, 8.20의 **다른** 기각 사유였던 "가이드가 조건화가 아니라 콘텐츠로 주입되어 화면에 그려짐"이 2511에서
해소됐는지는 **버전으로 보장되지 않으므로 라이브로 확인해야 한다.**

**금지 유지**: `stock_plate_substitution_enabled=true`는 위 배경 정책에 따라 오히려 **켜는 방향**이다(오기 정정).

**하드웨어는 막고 있지 않다**: `ComfyUI-IC-Light`(kijai) + `iclight_sd15_fbc.safetensors`(1.7GB) +
`cyberrealistic_v90.safetensors`(SD1.5 베이스) + `ComfyUI_IPAdapter_plus` + `comfyui_controlnet_aux` 모두
2026-08-02 설치 완료. VRAM ~4GB급이다. **8.20의 "16GB 미적합, 5런 중 2 OOM"은 Qwen-Image-Edit-2511
GGUF(13.24GB)로 카드+포즈가이드에서 새 카드를 만드는 완전히 다른 무거운 경로의 수치이며 이 방향에
적용되지 않는다.** 이 혼동은 이미 두 번 발생했다 — 다시 인용하지 마라.

---

### Story 10.1c: 샷 재창조 — 배경+카드+배치지시로 한 장 생성 (지적 3·11, 10.1b 후속)

**10.1b가 기각된 자리에 들어선다.** tier 3(IC-Light)는 실가동·판정까지 갔으나 Jay 시청 결과 "나빠졌다"로
기각됐다. 이유는 프레임이 말해준다 — 재조명은 카드의 **광량**을 플레이트에 맞추지만(카드-플레이트 색거리
34.52→27.66) **알파 엣지를 건드리지 못해** 여전히 붙여넣은 것으로 읽힌다. 조명 문제가 아니었으므로 조명
수정으로는 닫히지 않는다.

**방향**: `얹어놓고 고치기`를 버리고 **배경 + 캐릭터 카드 + 자연어 배치 지시 → 모델이 배치하고 한 장 생성**.
정본은 이 에픽의 "⛳ 확정 방향" 블록이며, composite-then-refine 계열은 거기서 전부 폐기됐다.

**채택 모델**: **Qwen-Image-Edit-2511**(Apache-2.0, `Q4_K_M` 12GB, 자산 이미 전부 로컬 보유).
`TextEncodeQwenImageEditPlus`의 `image1`=플레이트 / `image2,3`=카드 / prompt=배치 지시.
워크플로 `data/workflows/comfyui_shot_recompose_qwen_api.json`.

**라이브로 확정된 사실 (2026-08-09)**:
- **1인 샷 4/4 성공.** 배경 픽셀 보존, 지시대로 배치, 배지 텍스트 `213 5`까지 판독. 바닥이 없는 플레이트에는
  **없던 바닥을 그려서** 세우고 광원 방향과 맞는 그림자를 함께 그린다 — 배치 계층으로는 불가능했던 것.
- **2인 동시 삽입은 실패.** 지시문·카드순서·문구를 바꿔도 첫 인물이 항상 얼굴 클로즈업이 된다.
  → **순차 삽입(far→mid→near, 인물당 1패스)** 으로 해결. `Keep the room and everyone already in it
  exactly as they are`가 앞 패스 인물을 보존한다.
- **속도**: 90~120초/패스. 모델 첫 로딩만 500초대(1회성).
- **필수 환경**: ComfyUI를 `--lowvram`으로 기동해야 한다(10.1e가 `--disable-smart-memory` 요구를 실측으로 철회: 패스당 385~677초 대 108초)(기본 모드에서는 unet 12.3GB +
  텍스트 인코더 8.7GB ≈ 21GB가 VRAM 16GB를 넘겨 스왑 교착 — 12분에 0건). 또한 `run.sh`는 `"$@"`를 전달하지
  않으므로 `main.py`를 직접 호출해야 플래그가 먹는다.
- **텍스트 인코더는 fp8 필수.** GGUF Q4는 비전 타워가 별도 `mmproj`에 있어 `image1/2`를 못 읽고
  `mat1 and mat2 shapes cannot be multiplied`로 전량 실패한다. 크기 절약 목적으로 GGUF로 바꾸지 마라.

**미해결 — 이 스토리의 실제 범위**:
① **플레이트 배치 적합성 판정.** 해치 정면 클로즈업(S00104)처럼 인물이 설 자리가 없는 플레이트에서는
모델이 카메라를 뒤로 빼 **방 전체를 다시 그린다** — 배경 재사용 정책 위반. 이 문제의 정식 명칭은
**Object Placement Assessment(OPA)** 이며 FOPA·Text2Place·"Putting People in Their Place"(CVPR 2023) 등
선행 연구가 있다. **판정기 후보 3종이 이미 반증됐다**: `ground_plane()`은 정답과 **역상관**(최고 성공 샷이
"바닥 없음", 유일한 실패가 "바닥 있음"), 엣지 드리프트는 최하위 성공과 마진 0.012, VLM "바닥이 보이는가"는
**5개 중 2개 오판**(성공 샷을 막는 방향). 원인은 질문이 틀린 것 — 모델은 없던 바닥을 그릴 수 있으므로
"바닥이 보이는가"가 아니라 "카메라를 유지한 채 넣을 수 있는가"를 물어야 한다.
**실패 사례 n=1로는 어떤 판정기도 검증 불가** — 플레이트 43장 스윕으로 실패율·패턴을 먼저 확보한다.
② **플레이트 엄선 로직**(Jay 요청) — 시딩 단계에서 배치 적합성으로 스코어링해 라이브러리가 인물 배치
가능한 플레이트를 충분히 갖도록. `label_location_plates.py`의 Qwen-VL 경로 재사용.
③ 바닥 원형 반점 아티팩트(2샷 재현) ④ 출력 1344×768 → 1920×1080 업스케일
⑤ `image.py`/`video.py` 배선 — 재창조 결과가 샷 이미지가 되고 video 스테이지는 카드 오버레이 없이 Ken Burns만
⑥ ✅ **전체 렌더 완료 (2026-08-09)** — 재창조 51패스, 오류 0건, `video_recompose.mp4`(3:06).
Jay 판정: **재창조 통과**. 증거 `10-1b-live-validation/fullrun/`(`video_recompose.mp4` vs `before/video_overlay.mp4`,
`grid_fullrun.jpg`). S00202는 10.1이 "바닥 없는 벽돌벽"으로 포기했던 샷인데 바닥과 방향광 그림자가 생겼다.
⑥-a ✅ **해결됨**: 2인 샷의 인물 중복 생성. 증상은 "클로즈업"으로 보였으나 실체는 **같은 인물이 두 번 그려진 것**이고,
**1패스에서 이미 발생**했다(순차 삽입 문제가 아니다 — 2패스는 그걸 충실히 보존했을 뿐). 원인은 지시문의
`its camera angle and framing` 절 — S00104의 구도 재프레이밍을 막으려고 끼워 넣은 것이 인물을 한 번 더
그리라는 신호로 작용했다. 그 절은 애초에 불필요했다: 재프레이밍은 라이브러리 플레이트가 아닌 **자유 생성 배경**
에서만 났고 43장 스윕에서 라이브러리 플레이트는 전부 정상이었다. 검증된 짧은 문구로 되돌린 뒤 near+near /
near+mid 두 조건을 캐시 없이 재생성해 **양쪽 모두 중복 없음** 확인. 테스트도 뒤집었다(이제 그 절이 **없어야** 통과).
**방법론 기록**: 이 라운드에서 세운 가설 10건 중 9건이 반증됐다(IC-Light 하드웨어 제약 / 카드 투명영역 /
049 카드 특성 / 첫 참조 지배 / 와이드샷·그림자 문구 / `ground_plane` 판정 / 엣지 드리프트 임계 / VLM "바닥 보이나" /
동일 깊이). 공통점은 **대조군을 세우기 전에 원인을 단정한 것**이다. 맞은 1건조차 중간에 "반증됐다"고 잘못
보고했다가 대조군으로 되찾았다.
⑦ 8.16 접지·`_GROUND_Y_MAX`·오클루전·컨택트섀도·11.5 패럴랙스 코드 정리 — 이 결정의 귀결로 무용지물

**폐기 확정(되살리지 마라)**: `render_composite_still`을 **최종 픽셀의 출발점으로 쓰는 것**. 단, 그 함수와
`render_card_coverage_mask`는 배치 수식을 재유도하지 않고 *측정*하는 도구라 판정·검증 용도로는 유효하다.

**✅ 모션 판정 통과 (Jay, 2026-08-09)**: 3샷을 실제 Ken Burns 클립으로 렌더해 시청 판정.
① **지적 3·11(찢어 붙인 듯 / 허공에 뜸) 사라짐** — 특히 `S00202`는 10.1이 "바닥 없는 벽돌벽"으로
분류해 배치 계층이 포기했던 샷이다. ② **바닥 원형 반점은 모션에서 거슬리지 않음** — 정지 프레임에서는
42장 중 절반가량에 보였으나 움직임 속에서는 문제되지 않는다고 판정. 프롬프트 4갈래로 제거에 실패했고
"원을 그리지 마라"는 오히려 강화시켰으므로(`gotcha_negative-prompt-overstuffing` 재현) **더 투자하지 않는다.**
증거: `10-1b-live-validation/motion-check/`(`recompose_*.mp4` vs `old_*.mp4`).

**해소된 항목**: ① 플레이트 판정기 — **불필요**. 승인된 라이브러리 플레이트 42장 전수 스윕에서 구도 붕괴
**0건**이다. 유일한 실패 사례 S00104는 라이브러리 플레이트가 아니라 **런타임 자유 생성 배경**이었으므로,
`stock_plate_substitution_enabled`를 켜는 것이 해법이고 판정기를 만드는 것이 아니다. ② 엄선 로직 — 같은
이유로 불필요(`assets/locations/**/a.depth.png`는 뎁스맵 캐시 부산물이며 `location_service`는 DB에서
플레이트를 선택하므로 프로덕션 경로가 집어가지 않는다). ③ 반점 — 위 판정으로 종결. ④ 업스케일 — 불필요
(재창조 출력이 입력 플레이트 크기를 따르고 Ken Burns 체인이 어느 쪽이든 1920×1080으로 처리).
⑤ 배선 — 완료. `shot_recompose.py`(도메인) + `recompose_service.py`(오케스트레이션) +
`inject_recompose_resolver` 이음매, 기본 **off**. 마커 `false`일 때 기존 오버레이로 안전 강등되는 것까지 라이브 확인.

**증거**: `_bmad-output/implementation-artifacts/10-1b-live-validation/` — `recompose-qwen/`(프레임·그리드),
`plate-sweep/`(43장 스윕), `blotch-probe/`(반점 4갈래), `motion-check/`(영상 판정). 의존: 없음.

**🔒 마감 (2026-08-11, `spec-10-1c-shot-recompose-qwen.md`)** — 남아 있던 세 건을 닫고 스토리 종료.

① **AD-1 위반 해소.** `recompose_service.py`가 `pipeline.nodes.shot_recompose`를 임포트해 계층 경계
테스트를 깨뜨리고 있었다(저장소 유일 실패). `eval_service.py → shot_timing` 선례와 동일 계약으로
허용목록에 편입하되, **허용목록이 구멍이 되지 않도록** 허용된 노드 모듈 자신이 `api/`·`services/`·`db/`를
임포트하지 않는지 되검사하는 단계를 추가했다(없으면 services→pipeline→services 순환을 세탁한다).
가드가 실제로 문다는 것은 `shot_recompose.py`에 임시로 services 임포트를 넣어 실패시켜 확인.

② **기본 활성화 판단 — OFF 유지.** 켜는 쪽 근거는 실재한다(51패스/오류 0, 3:06 렌더 Jay 모션 판정 통과로
지적 3·11 소멸, 42장 스윕 구도 붕괴 0). 그럼에도 **기본값**으로는 이르다: (a) 하루 뒤 10.4 사후 감사가
재창조본을 원본 플레이트보다 **블라인드 판독성에서 더 나쁘게** 측정했고(unreadable 20% vs 13%,
'corridor' 오독 57% vs 27%) 그 축은 이 에픽 최대 결함군이며 13.2에서 재구축 중이다 — 즉 지금 켜면
한 축의 승리를 다른 축의 회귀와 맞바꾼다. (b) ComfyUI를 `--lowvram`으로 띄우고(10.1e에서 `--disable-smart-memory`는 철회됨)
텍스트 인코더를 fp8로 유지해야 하는데 **코드가 이를 검출하지도 강제하지도 않는다** — 기본 설치에서는
스왑 교착(12분 0건)이고 이건 예외가 아니라 정지라 `try/except` 폴백이 발동하지 않는다. (c) 51패스 ×
90~120초 = 2시간 E2E 예산에 1.3~1.7시간 추가. (d) 에픽 규정 "신규 경로는 기본 off로 들어간다".
**해제 조건**: 13.2의 재구축된 축으로 recompose on/off **짝지은** 세트를 채점해 판독성이 동등 이상이고,
런타임 전제조건 가드가 존재할 때 플립한다.

③ **코드 정리 — 전제가 성립하는 범위에서만.** ⑦의 "무용지물" 목록(8.16 접지·`_GROUND_Y_MAX`·오클루전·
컨택트섀도·11.5 레이어 패럴랙스·1.9c idle motion)은 **재창조가 경로가 되었을 때** 사문화된다. ②로 기본값이
off로 남으므로 지금 지우면 프로덕션 경로를 지우는 것이다 — **삭제하지 않았고, 되살리지도 않았다.**
대신 (i) 재창조 블록을 8.16 접지 리졸버 **앞으로** 옮겨, 켜졌을 때 소비되지 않을 배치를 계산하지 않도록
바이패스를 구조적으로 만들었다(플래그가 off면 동작 동일). (ii) 양쪽 설정 모두에서 죽어 있던
`pipeline/nodes/composite_fusion.py`(기각된 10.1b의 마스크 low-denoise img2img, 임포터 0·테스트 0)를 삭제.
(iii) `render_composite_still`/`render_card_coverage_mask`는 호출자 0이지만 **의도된 보존**이므로 그 사실을
코드에 명시(이후 dead-code 스윕 방지). 목록 자체의 철거는 **플립 커밋의 몫**이다.

④ **파생 결함 1건 수정.** 재창조는 `shot["image_path"]`만 갈아끼우고 `depth_map_path`는 **옛 플레이트의 것**을
남겨, 켜는 순간 11.5가 새 프레임을 옛 깊이맵으로 워프하게 되어 있었다(인물이 제 배경 위에서 미끄러진다 —
재창조가 없애려던 바로 그 증상). 키를 떨궈 `no_depth_map`으로 **기록되는 강등**이 되게 했다. 서비스 계층에
테스트가 전무해 `tests/services/test_recompose_service.py`(6건) 신설.

검증: 전체 스위트 2620 passed / 0 failed(베이스라인 `fae0b98`에서 1 failed).

### Story 10.2: 배경 무인화 강제 — 배경이 이미 사람을 그린다 (지적 5·12)

Jay 지적: 배경 자체에 인물(대형 여성 얼굴, 애니 캐릭터)이 이미 그려져 있고 그 위에 카드가 또 합성됨. 카드 컴포지팅 아키텍처(Epic 8)의 전제는 **배경이 무인**이라는 것이므로, 배경에 인물이 생성되는 순간 합성은 원천적으로 깨진다 — 카드 배치·접지·스케일을 아무리 고쳐도 해결되지 않는 계층의 결함. ① `visual_breakdown`의 배경 프롬프트가 인물·얼굴·실루엣을 생성하지 못하도록 강제(네거티브 강화는 역효과가 실증돼 있으므로 — `gotcha_negative-prompt-overstuffing` — 프롬프트 문구가 아니라 구도 지시로 통제). ② 생성된 배경에 인물이 있는지 **검출**해 재생성하는 결정론 가드(8.18/8.19의 코드 강제 패턴 재사용). ③ 검출은 기존 Qwen-VL 경로 재사용 검토(신규 의존성 금지). 의존: 없음. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 10.3: 화풍 일관성 + LoRA 정합 (지적 10·12)

Jay 지적: "이상한 화풍의 이미지가 나오는 경우가 있음", "갑자기 애니메이션 캐릭터가 나옴". **원인 규명 완료 — 이전에 여기 적혀 있던 귀속은 뒤집혀 있었고 라이브 측정으로 정정한다**(2026-08-09, `10-3-live-validation/`): 범인은 `darkness_xl_v2.safetensors`가 아니라 **`horror.safetensors`** 다. 네 가지 LoRA 조합을 AnimagineXL v3.1에 각각 로드해 로그 윈도를 센 결과 `both` = 342 `lora key not loaded` + 73 `ERROR lora ... invalid for input of size`, `horror_only` = **동일한 342 + 73**, `darkness_only` = **0 + 0**, `none` = 0 + 0. 텐서 shape도 같은 결론이다 — `horror`는 diffusers 명명에 `lora_te_text_model_*` 텍스트 인코더가 하나(SDXL은 `lora_te1`/`lora_te2` 둘)이고 `down_blocks_0`에 어텐션이 있으며(SDXL에는 없음), `lora_unet_up_blocks_0_resnets_0_conv1`이 `down=[16,2560,3,3]`이라 델타가 `[1280,2560,3,3]`(=29,491,200개)로 만들어져 SDXL의 `output_blocks.2.0.in_layers.2.weight` `[1280,1920,3,3]`에 들어가지 못한다 — 로그의 `is invalid for input of size 29491200`이 바로 이것이다. 반면 `darkness_xl_v2`는 sd-scripts 명명의 순정 SDXL UNet LoRA로 `output_blocks_2_0_in_layers_2 down=[4,1920,3,3]`, `output_blocks_3_1...attn1_to_k down=[8,640]`처럼 체크포인트와 정확히 일치하고 미로드 키가 0이다. ① **`horror.safetensors` 로더 노드를 5개 워크플로에서 제거**하고 `darkness_xl_v2`를 체크포인트에 직결(완료). ② 재발 방지는 `tests/test_workflow_definitions.py`의 LoRA 허용목록으로 고정(완료). ③ 화풍 드리프트를 샷 간 비교로 검출하는 축을 13.2에 추가할지 판단. 참고: 제거만으로 느려짐이 해소되지는 않았다(별개 문제였음). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 10.4: 이미지-나레이션 의미 정합 (지적 2·4·7·9·16)

Jay 지적이 가장 많이 몰린 항목: "무슨 배경인지 모르는 배경이 많음", "나레이션과 전혀 맞지 않는 혹은 이해할 수 없는 이미지", "도입부 이미지도 뭘 나타내는 건지 의미를 모르겠음". **판정 축을 먼저 만들어 66샷 전체를 실측했고, 결과는 이 항목의 전제를 상당 부분 반증한다**(2026-08-10, `10-4-live-validation/`). 축은 샷마다 두 번 호출한다 — **블라인드**(프레임만, 문장 비공개 → `place`/`event`/`legible`)를 먼저, 그다음 **매치**(프레임+문장 → `match`/`evidence`/`missing`). 블라인드를 먼저·문장 없이 던지는 것이 이 측정의 유일한 근거다(문장을 먼저 보여주면 VLM은 동의하는 법을 찾는다).

**⚠️ 베이스라인 출처 정정(2026-08-10, 사후 감사)**: 채점된 66프레임 중 **51장은 Jay가 본 프레임이 아니다** — 체크포인트의 `shot["image_path"]`가 10.1c 재창조본(`recomposed/`, 2026-08-09)으로 갈아끼워져 있고 Jay가 시청한 영상은 2026-08-08 렌더다(원본 플레이트는 15장만 채점됨). 방향까지 적자면 재창조본이 더 나쁘다 — unreadable 20% vs 원본 13%, 블라인드가 'corridor'로 읽은 비율 57% vs 27%(n=15로 작다). 아래 서술의 "Jay가 본 그대로"라는 라벨은 이 범위에서 부정확하다. A/B 두 leg는 새로 렌더했으므로 영향 없다.

**실측(런 `8a9a288b`, 66샷, `qwen-vl-plus`, `temperature 0`)**: 임계(`MIN_LEGIBLE=3`/`MIN_MATCH=3`, 훅은 4/4) 대비 **실패율 7.6%(5/66)**, 평균 `match` 3.606, 평균 `legible` 4.303. **`MIN_MATCH` 미만 4샷**(`S00105`/`S00303`/`S00708`/`S00503` — 지적 4), **`MIN_LEGIBLE` 미만 0샷**. 즉 이 계측기로는 **지적 2가 점수로 재현되지 않는다** — `legible` 분포가 {4:46, 5:20}로 4 미만이 하나도 없다(죽은 축). 반면 같은 응답의 블라인드 `event` 자유텍스트는 **9/66(13.6%)**이 `"unclear"`였고 그 9샷 모두 `legible: 4`였다 — 모델이 자기 루브릭과 모순된다. 부수 발견: 블라인드 캡션 **28/66(42%)**이 무인이어야 할 플레이트에서 인물을 읽었다(10.2 지적 5·12의 독립 재현이자 `match`의 교란 요인). 66프레임 전부 md5 대조로 **스톡 플레이트 복사가 아님(0건)**을 확인 — 레버가 `image_prompt`인 것은 맞다. 합성 프레임 교차검증(`--frames shots`, 클립이 있는 4샷)에서 판정은 **전혀 움직이지 않았다**(플레이트≈시청 프레임).

**프롬프트 A/B는 패배 → 승격 안 함.** 씬1(7샷)+씬5(8샷) 15슬롯을 같은 seed·같은 워크플로·같은 네거티브로 30장 렌더해 `--reps 3`로 채점한 결과, 사전등록 규칙(평균 `match` 비하락 + `MIN_MATCH` 미만 건수 비증가 + 훅 4/4) 중 **2개 절이 실패**(평균 3.267→2.933, 훅 5→3; 미만 건수는 2→1로 개선). 프롬프트 파일은 `3869f95`로 되돌렸고 Langfuse는 v14 그대로다. **다만 결론은 "새 프롬프트가 나쁘다"가 아니라 "측정 불가"다** — 동일 프롬프트를 다시 생성만 한 대조군(베이스라인 프레임→old leg)의 평균 이동이 **−0.267**로 A/B 효과 **−0.333**과 같은 크기이고 샷별 sd≈1.4다. 15슬롯·1세대 설계는 자기 노이즈를 못 넘는다.

**이터레이션 2 — 레버를 1:1 매핑으로 바꿔 재측정(같은 날, 미커밋).** Jay 판단: "한 대본 문장에 여러 이미지가 있을 수 있고, 한 이미지에 여러 대본 문장셋이 매핑될 수 있다". ① **계측기 교체 완료**: 죽은 `legible`(1–5)을 **불리언 `readable`**로 바꿔 **보존된 동일 66프레임을 재채점**(`baseline_v2.json`)한 결과 **12/66(18.2%)이 unreadable** — Likert로는 0/66이었고, 그 12장 전부가 `legible: 4`였다. 계측기가 결함을 못 본 게 아니라 **보고할 수단이 없었다**. `mean_match`는 3.621로 불변(=판정자가 아니라 질문이 바뀐 것). ② **N:M 순서 커버 구현 완료**(`ShotData`/`SceneState` 필드 추가 없음 — 이미 있던 `sentence_end`를 활성화): 파서가 전 문장 커버·역행 금지·문장수 상한을 검증하고, 병합 샷은 cast를 합집합으로 가지며, `plan_shot_clips`는 시작점만 분할(`share_n == 1`이면 기존 산술과 바이트 동일). ③ **PASS B(9씬 66문장 전체, 문장 단위 페어링, 부트스트랩 CI, old leg는 프롬프트+파서 모두 `git show 3869f95:`)**: 커버는 실제로 작동해 **66샷 → 55샷(−16.7%)**, 병합 11건·분할 0건, 18개 씬-leg 전부 미커버/역행/역전 0. 그러나 **사전등록 규칙 재차 실패 → 승격 안 함**: 페어드 평균 Δ`match` **−0.152, 95% CI [−0.394, +0.076]**(0을 포함 → **"효과 없음"**이지 "더 나쁨"이 아니다), 문장별 개선 10·악화 19·동일 37. unreadable은 16→15로 "건수"는 줄었지만 **비율은 24.2%→27.3%로 악화**(렌더가 11장 적다). 훅은 양 leg 모두 `readable` true/`match` 3으로 동일 실패. 프롬프트 파일은 `3869f95`로 되돌렸고 Langfuse는 v14 그대로(`migrate_prompts.txt` 의도적 부재), 커버 프롬프트 원문은 `prompt_cover.md`에 보존.

**AC3(반증 가능한 예측)은 반증됐다 — 이 런의 가장 중요한 산출물.** "최악 4개 문장은 그릴 게 없으니 커버가 이웃에 접어넣을 것"이라는 근거 주장은 **0/4**로 틀렸다: `S00105`/`S00303`/`S00708`/`S00503` **전부 단독 샷 유지**, 그중 둘은 오히려 4→3으로 하락. 특히 `S00708`의 문장 "이게 에스씨피 재단입니다"는 **커버 프롬프트가 첫 번째 병합 예시로 그대로 인용한 문장**인데도 모델이 전용 프레임을 줬다. 게다가 **실제 병합된 문장(n=22, Δ −0.136)과 안 된 문장(n=44, Δ −0.159)이 구분되지 않는다** — 병합 자체가 점수를 못 움직였다. 모델의 병합은 내용 판단이 아니라 **위치 습관**(전부 인접 2문장 쌍, 씬 도입부에 몰림)이었다. **따라서 "매핑이 원인이 아니다"라고 말해서는 안 된다 — 가설은 반증된 게 아니라 아직 시험되지 않았다**(모델이 만든 커버가 가설이 상정한 커버와 거의 겹치지 않는다).

**결정적 프로브 — 손으로 병합해도 이득이 없다(매핑 가설 사망).** 위 결과는 "가설이 시험되지 않았다"였으므로, 씬 3·7에 대해 **점수를 보기 전에 규칙을 먼저 확정하고**(어떤 장소·물체/신체·물리적 변화도 지칭하지 않는 문장만 병합) 손으로 커버를 짰다 — 규칙은 목표였던 `S00303`("보입니까, 그 병이?")과 `S00708`("이게 에스씨피 공사구-이입니다")을 지시 없이도 자동 선택했다(총 5문장 병합, 7→5샷·9→7샷). 대조군은 이미 채점된 `ab2_old`(bijection), 재렌더 없음. ① **M1(렌더 0장)** — 병합 대상 문장을 이웃의 **기존 프레임**에 합쳐 결합 텍스트로 재채점: 병합 5문장 평균 Δ **정확히 0.000**(5/5 무변). 대신 **호스트가 −2**(씬3 문장2가 단독일 땐 `match` 5였는데 문장3까지 떠안자 3). 병합은 공짜가 아니다. 부수 검증: 단일 문장 스팬 8개가 대조군 점수를 **8/8 정확히 재현** → `temperature 0` 계측기는 안정적이며 "Δ 0"은 노이즈가 아니라 진짜 무변이다. ② **M2(11장 렌더)** — 커버 범위를 프롬프트에 **강제 지시**해 모델이 "병합 스팬용 image_prompt"를 새로 쓰게 함(양 씬 모두 지시대로 정확히 준수): 병합 문장 Δ **+0.200**인데 **같은 씬의 병합 안 된 문장이 +0.182** — 구분 불가. 즉 M2의 상승은 **씬 전체 재작성/재추첨 효과**이지 병합 효과가 아니다(최대 이동 +2는 병합되지 않은 씬7 문장1). **`S00708`은 3 → 3 → 3으로 양 팔 모두 전혀 안 움직였다.** ⇒ **매핑(1:1 해제)은 `match` 레버로서 사망**. 커버 코드는 유지하되 근거는 **렌더 비용·컷 리듬(66→55, −16.7%)**이지 의미 정합이 아니다. 한계 명시: 병합 n=5·2씬·`--reps 1`이고 +0.200은 PASS B의 문장별 sd 0.98 안에 있다 — "탐지 가능한 이득 없음"과 "호스트 비용은 1회 실측(−2)"까지만 지지하며 "병합이 해롭다"는 주장은 못 한다. 또 `match`는 3에 강하게 몰려 있어(M2 16행 중 11행, M1 16행 중 15행 무변) 이 대역의 해상도가 낮다.

**13.2 인계(갱신)**: `match`는 축으로 채택 권고. `legible`(1–5)은 **폐기 확정, 불리언 `readable`로 대체**(위 12/66 근거). `match`를 게이트로 쓰기 전 **카드 부재 교란(11/66)을 먼저 제거**해야 한다. 실행은 **10.2 가드를 켠 뒤**. **커버 품질 게이트는 만들지 마라** — 위 프로브가 바로 그 실험(손으로 짠 커버 vs bijection)이었고 사람이 고른 병합조차 `match`를 못 움직였다. 남은 후보 레버는 이 스토리가 건드리지 않은 둘이다: 새 불리언이 드러낸 **unreadable 12/66**, 그리고 `match` 자체를 오염시키는 **카드 부재 교란 11/66**. 13.2는 `readable` 배선과 교란 제거를 먼저 하고, 매핑에는 더 이상 런을 쓰지 마라. 6.12 승격 게이트는 건드리지 않는다(13.4). 상세·재현 명령·전 샷 표·페어드 표: `_bmad-output/implementation-artifacts/10-4-live-validation/README.md`.

### Story 10.4b: 부재를 그리라고 시키지 마라 — 판독불가 프레임 제거 (지적 2, 10.4 후속)

10.4가 실측으로 남긴 **unreadable 12/66(18.2%)** 이 지적 2("무슨 배경인지 모르는 배경이 많음")의 실체다. 원인은 프롬프트 품질이 아니라 **요구 자체가 불가능한 것**이었다 — 그 12장의 `image_prompt`는 전부 **없음을 주제로 삼는다**: `close-up of open air in a containment cell`, `vast empty concrete floor stretching across the frame`, `over-the-shoulder view toward a blank wall section`. 실물 확인 결과 `S00304`("open air")는 중첩된 문짝 기하 도형이 됐다 — 렌더러가 틀린 게 아니라 **시킨 대로 아무것도 아닌 것을 그렸다**.

**근거 문헌(상세: `planning-artifacts/research/technical-narration-image-semantic-alignment-2026-08-10.md`)**: 디퓨전 모델은 부재를 실현하지 못한다. "고양이 없는 방"에 5/5 시드가 고양이를 그리며, 텍스트 인코더는 부정을 이해하는데 그 이해가 픽셀로 옮겨가지 않는다(NEGATE, SpaceVLM). 우리 전례와도 일치한다 — `gotcha_negative-prompt-overstuffing`, 그리고 10.2에서 여섯 군데가 사람을 금지했는데도 사람이 그려진 것.

**빈 프롬프트가 나오는 기제 — 우리 규칙 셋의 충돌**: ① `image_prompt`는 배경 전용(Epic 8 카드 구조) ② 문장이 전부 사람 얘기("검은 눈구멍이 초점 없이 공중을 스캔합니다", "아주 협조적으로요") ③ 프롬프트가 여백을 연출로 가르침("Use negative space as a storytelling tool… The space where something SHOULD be but isn't"). 주어를 못 쓰게 하고, 주어뿐인 문장을 주고, 여백이 좋다고 가르치면 "텅 빈 콘크리트 바닥"이 나온다. 10.2가 이 지시의 한 줄을 이미 삭제했고 나머지가 남아 있다.

**범위**: ① `visual_breakdown`이 **부재를 주제로 삼지 못하게** — 통제는 문구 누적이 아니라 "프레임의 주어는 항상 존재하는 사물/표면/흔적"이라는 요구로(네거티브 증량 금지, 정규식 스크럽 금지 — `gotcha_person-token-regex-is-unusable-on-image-prompt`). ② **렌더 가능한 지시대상이 없는 문장은 배경을 새로 만들지 않는다** — 이웃 프레임에 붙이거나(10.4의 커버 코드가 이미 지원) 10.1c 재창조 경로로 넘긴다. ③ 판정은 13.2의 새 계측기로. **착수 조건: 13.2 완료 후** — 3에 몰려 해상도가 없는 점수로 재면 10.4의 라운드를 그대로 반복한다.

**더 깊은 갈림길(이 스토리가 결정하지는 않음)**: 현행 story-visualization 시스템(ViStoryBench·DreamStory·Dialogue Director·Narrative Graph Prompting)은 전부 **인물을 프레임 안에 함께 생성**하고 정체성은 조건화로 지킨다. 배경만 그리고 카드를 얹는 우리 구조가 예외이며 그것이 ①의 뿌리다. 대체 경로는 이미 사내에 있고 라이브 검증도 끝났다 — **10.1c 재창조**이며, 이 에픽의 "⛳ 확정 방향" 앵커가 이미 그쪽을 정본으로 선언했다. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**⏸ 구현 완료·라이브 A/B 차단 (2026-08-11, `spec-10-4b-no-absence-as-subject.md` / 증거 `10-4b-live-validation/`)**

⚠️ **먼저 이 항목의 전제를 정정한다.** 위에 "그 12장의 `image_prompt`는 전부 부재를 주제로 삼는다"고 적혀 있으나 **행 데이터로 확인하면 틀렸다** — 부재가 주어인 것은 **5장**(`S00204`·`S00300`·`S00304`·`S00305`·`S00805`)이고 `S00303`이 경계이며, 나머지 **6장**(`S00201`·`S00202`·`S00400`·`S00707`·`S00804`·`S00900`)은 이미 구체적 사물이 주어다(강철 침대틀+구속구, 접촉마모 후광+균열, 후퇴하는 방폭문, 크롬 기구 트레이, 균열난 관찰창, 밀폐된 문). 조사 문서 자체는 정직했다(키워드 기준 29% vs 11%를 "weak, a hint not proof"로 명시); 요약이 "전부"로 굳혔다. 12장이 **공유하는** 것은 `event: "unclear"`이고 8/12가 블라인드에서 'corridor'로 읽혔다 — `readable`은 장소 **와** 사건을 둘 다 요구하므로 나머지 절반의 기제는 부재가 아니라 **사건이 안 읽히는 것**이다. 따라서 범위 ①의 상한은 12장이 아니다.

**구현(완료)**: ① 살아남아 있던 부재-교사 3곳 제거(네거티브-스페이스 절, "show an EMPTY frame that feels WRONG", 여백을 **의무화**하던 셀프체크 항목) + cast-empty 지시 강화 → 하나의 긍정 요구로 대체("주어는 항상 존재하는 사물/표면/흔적이고, 프레임은 이 문장 사건의 읽히는 흔적을 하나 담는다"). 네거티브 증량 0, 정규식 0 — 10.2가 절-스크럽을 만들어 313샷 중 27개 훼손을 실측하고 삭제한 전례를 반복하지 않았다. ② 엄격 전단사를 좁혀 **지시대상 없는 문장만** 이웃 스팬을 넓히게 함(샷수 상한 유지). 파서는 10.4부터 이미 순서 커버를 검증했고 막고 있던 건 프롬프트였다. ③ `_fallback_prompt`가 `"no visible subject"`로 끝나 **코드 쪽 부재-주어**였고 `_NO_FIGURE_FRAMINGS`에 걸려 자리표시 문구가 조용히 cast를 지우고 있었다 → 바닥면 명명. 테스트 4건으로 추가된 요구와 **제거된 교사를 문구 단위로** 고정. 2675 passed / 0 failed, ruff clean.

**차단 사유**: 렌더가 40분에 129장 중 3장. 내 플레이트는 ~16초인데 같은 ComfyUI에서 캐릭터 워크플로(`IPAdapterAdvanced`+`InspyrenetRembg`)가 ~306초씩 계속 돌아 내 잡이 뒤에 줄섰다(`/queue` 3회 표본 전부 `running: CHARACTER, pending: plate`; `api2`에는 두 노드가 없고 이 체크아웃의 다른 프로세스도 없다). 6시간 경합 대신 중단했고 하네스는 전 단계 resumable이다. **판정 없음·미승격 — Langfuse는 v14 그대로.**

⚠️ **GPU 없이 이미 나온 결과가 이 스토리의 측정가능성을 의심하게 한다.** `old`(기준선 프롬프트 신규 실행)는 66/66 완전 전단사, `new`는 **63샷**(정확히 3건 병합, 전부 지시대상 없는 문장 — "소중한 환자를 대하듯이", "만족스러운 듯이요", "그는 진심으로 보고 있습니다"; 이 중 둘이 대상 12장). **범위 ②는 작동하고 선별적으로만 발동한다.** 그러나 부재-마커를 세면 `old` **3/66(4.5%)** vs `new` **2/63(3.2%)** 이고, 이 스토리가 고치려는 런은 unreadable 12장 **안에서만** 부재-주어가 5건이었다. 즉 **부재-주어는 프롬프트의 안정적 속성이 아니라 상당 부분 LLM 표집 변동**이며, n=66 readable-rate A/B로는 3 대 2를 분해할 수 없다. 재개 전에 설계를 다시 볼 것 — 한 번의 66문장 A/B보다 **짧은 런을 여러 번 돌려 부재-프롬프트 발생률을 직접 세는 쪽**이 이 레버에 맞을 수 있다. (변경 자체가 틀렸다는 근거는 아니다: 결함을 가르치던 지시를 없앤 것은 싸고 안전하며 유지한다.)

**🔚 정정·종결 (2026-08-11, 같은 날 후속 계측 — 증거 `10-4b-live-validation/` §2b)**

**전제가 무효였다.** 렌더 없이 프롬프트 텍스트만 블라인드 judge에 물었더니(`check_prompt_compliance.py`, 129콜 109초, GPU 0) **기준선 프롬프트가 "주어가 물리적으로 존재하는가"에서 66/66 = 100%** 다 — 없앨 부재-주어 거동이 애초에 남아 있지 않았다. 타임라인: 이 프롬프트는 런 이전 **2026-08-01**(11.2)에 마지막으로 손댔고 **10.2가 2026-08-10에 편집**했는데(`"A figure small in an enormous space"` → 뒤집힌 의자, production v14 시딩) 문제의 런 `8a9a288b`의 시나리오는 **2026-08-07**에 쓰였다. ⇒ **unreadable 12장은 10.2 이전 프롬프트의 산물이며, 10.2의 한 줄 편집이 이 스토리가 잡으려던 것을 이미 고쳐 놓았다.** 위 "부재가 주어인 5장" 판정도 그 옛 버전에 대한 것이다.

따라서 **프롬프트 변경은 되돌렸다** — pre-10.4b와 바이트 동일, **미시딩**(Langfuse v14 그대로), 후보 텍스트는 `prompt_absence_free.md`에 보존, 제거를 고정하던 테스트 3건도 함께 제거. **유지한 것은 `_fallback_prompt` 버그 하나**(`"no visible subject"`가 부재를 명명하면서 `_NO_FIGURE_FRAMINGS`에 걸려 자리표시 문구가 조용히 cast를 지우던 독립 결함). 렌더 A/B는 미완료이고 이제 완료할 이유도 없다.

⚠️ **살아 있는 결함은 다른 절이고 이 스토리는 그걸 못 움직였다.** `visible_event`(프롬프트가 **이 문장 사건의 보이는 흔적**을 담는가)가 기준선 **84.9%(56/66)** — 66장 중 ~10장이 장소·무드·조명·질감만 세우고 아무 일도 안 일어난 프레임을 시킨다. 이것이 **unreadable 12장 중 주어가 이미 구체적이던 6장**(`S00201`·`S00202`·`S00400`·`S00707`·`S00804`·`S00900` — 전부 블라인드 `event: "unclear"`)의 실패 기제다. 이 스토리의 문구는 82.5%(−2.3pp = 무변)로 못 움직였으므로 **후속은 같은 문구 재시도가 아니라 다른 개입이 필요하다**.

**후속 스토리에 넘기는 것**: 목표는 **`visible_event` 84.9%를 이기는 것**이고(추론이 아니라 **현행** 프롬프트에서 실측한 기준선이다), `check_prompt_compliance.py`가 그대로 게이트다 — 후보를 **렌더 전 ~2분·GPU 0**으로 스크리닝하고 통과할 때만 `PRE-REGISTRATION.md`의 페어드 `readable` A/B에 GPU를 쓴다. 이번 라운드가 그 순서의 값을 실증했다(109초 게이트가 ~6 GPU-시간을 절약).

한계: 게이트는 **프롬프트 텍스트** 판정이고 프레임 판정이 아니다 — 프롬프트가 존재하는 주어를 명명한다는 것만 말하며 렌더가 판독 가능하다는 뜻이 아니다. judge 1종·프롬프트당 1콜·`temperature 0`·반복 없음이므로 84.9% vs 82.5%는 "무변"으로 읽어야 한다. unreadable 18.2% 자체는 구체적-주어 6장에 대해 여전히 미해명이며 후속 소관이다.

### Story 10.5: 동작 상태가 카드에 반영되지 않음 (지적 6)

Jay 지적: "'그는 그 자리에서 쓰러졌습니다' → 캐릭터가 쓰러져 있는 이미지가 나와야겠지". 현재 카드는 기립 정면 1종이 사실상 전부이므로 나레이션이 서술하는 상태(쓰러짐/앉음/손 뻗음)와 무관하게 항상 서 있다. **8.20이 이 문제를 맡았으나 기법이 라이브 게이트에서 기각됐다**(Qwen-Image-Edit-2511: 가이드가 조건화가 아니라 콘텐츠로 주입되어 화면에 그려짐 + 16GB 미적합, 5런 중 2런 OOM — 상세 `8-20-live-validation/DECISION-RECORD.md`). ① 남은 후보는 실제 ControlNet 경로 또는 `edit_only`(가이드 없이 텍스트만으로 동작 지시 — 베이스라인에서 이미 요청 동작을 달성했다는 실측이 있음) 중 택일. ② 최소 상태 집합(쓰러짐/앉음 정도)만 우선. ③ 8.20 Task 2 산출물(`pose_conditioning` 컬럼, 닫힌 `pose_guide_key`, 가이드 6종)은 이미 있으므로 재사용. 의존: 8.20 결정. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**done (2026-08-12), 부분 종결** — 근거는 렌더 프레임(`_bmad-output/implementation-artifacts/10-5-live-validation/`)이지 통과한 테스트가 아니다. 23개 결함 슬롯 중 **9개(B)에 대한 기법이 확정됐고, 14개(A)는 열린 채로 인계**된다.

- **(B) 확정: 구조 조건화가 원인이자 해법.** 사전등록(커밋 `aa7289e`, 픽셀보다 앞선 단독 커밋)한 3레그를 공유 시드 3개(1061/1062/1063)에서 돌렸다 — 명명된 변인 외 전부 10.6 ②값 고정. **L2(ControlNet Union promax, `type="openpose"`, `humanoid_lying_supine` @0.9) 3/3 supine**, L1(IPAdapter 앵커 0.0) **0/3**, L0 대조군(10.6 ②-B 3장 재사용) **0/3**. 결정표 행 `L1 ≤1/3 + L2 ≥2/3` → 구조 조건화 채택. 즉 8.20이 남긴 `pose_guide_key`·가이드 6종은 **쓸모 있었고 소비자만 없었다**. 배선: `pose_guide_conditioning_enabled`(기본 **False**) → `_ensure_special_pose_cards`가 `pose_guide_key`를 버리지 않고 운반 → `generate_special_pose_card`가 `resolve_pose_guide`로 해석해 provider에 전달, 실패 시 경고 후 pre-10.5 경로로 강등. 그래프는 별도 파일(`comfyui_character_pose_guide_api.json`)이라 기능 off면 기존 그래프가 1바이트도 안 바뀐다.
- **8.20의 VRAM 기각은 이 경로에 적용되지 않는다(실측).** L2 peak **11.16 GiB**(천장 15.92 GiB, 4.76 GiB 여유), OOM 0건, 실패 노드 0건, 무가이드 L1 대비 비용은 VRAM ~1.3–2.5 GiB, 시간은 **웜 ~6초/장 + 첫 장 ~44초 콜드 로드**(L2 68.1/28.8/28.8초 vs L1 24.0/22.3/22.4초 — `special_pose_max_per_run=3` 예산에 첫 장 페널티가 얹힌다). VRAM 수치는 장치 전체 `vram_total − vram_free`를 2초 간격 샘플한 값이라 격리된 per-render 비용이 아니고 비어 있는 GPU에서 잰 것이다. 원자료 `10-5-live-validation/measurements.jsonl`.
- **(A) 전제 반증 — 14슬롯은 자산 부재가 아니라 같은 결함이다.** 스토리는 (A)를 "기법이 아니라 없는 자산 문제"로 놓고 `seed_stock_cast.py --pose sitting`으로 11슬롯을 값싸게 닫을 예정이었다. 라이브 쓰기 전에 front 1장을 프로브했더니 **의자 없이 꼿꼿이 서서** 나왔다(`probeA_sitting_front_seed1071.png`). 프롬프트에 `sitting on a plain simple chair, seated pose`가 축자로 들어간 것을 재산출 스크립트로 확인했으므로 하니스 버그가 아니라 모델이 무시한 것 — (B)가 0/3으로 잰 바로 그 텍스트-온리 실패다. 사전등록한 실패 분기대로 **아무것도 시딩하지 않았다**: 그냥 시딩했다면 서 있는 그림에 `sitting` 딱지가 붙은 승인 카드 4행이 생겨, 최소한 `pose_fallback=True`를 남기는 현행 무성 폴백보다 **더 나빠진다**. (A)는 **0/14** 종결이고, 앉은 자세용 openpose 가이드 저술 + 시딩 경로에 가이드 연결이라는 새 스코프로 `deferred-work.md`에 인계됐다.
- **기본값 off인 구체적 이유**: 가이드 레그의 시드 1063이 **누운 인물 둘**을 그렸고 무가이드 레그의 시드 1062는 3패널 캐릭터 시트였다. 카드는 단일 피사체여야 하므로 둘 다 카드로서 결함이며, 가이드 유무와 무관하게 나타나므로 이번 변경이 원인은 아니지만 기본값을 켜면 함께 출하된다. 사전등록 규칙이 figure-count를 또 빠뜨린 것(10.6에 이어 두 번째)도 규칙 수정 없이 기록만 했다.
- **무성 폴백 판정**: 결함 맞으나 소유자는 **13.1**(`run_warnings`/`cast_card_fallback`). 생산자(`asset_fallback`/`fallback_reason`)는 이미 계산되고 있고 없는 건 소비자다. 두 번째 레지스트리를 만들지 않았다. `SCP-049-2` sitting 3슬롯은 그 키의 10.6 Jay 게이트 이후로 순서를 못박아 인계.
- **라이브 자산·DB 무변경**: read-only 쿼리로 characters 9행 / character_cards 12행 / `STOCK-d-class` sitting 0행 / 기립 `angle_front_path` 원값 / descriptor의 vision read-back 잔존을 단언했고, 파일 쪽은 `find assets/characters -name 'sitting_*'` 무결과 + `assets/characters/STOCK-d-class/epoch_2/` 전 파일이 8월 2·7·8일자(이번 세션 이전)임으로 확인했다. **`git status --porcelain assets/`는 증거가 아니다** — `.gitignore:19-20`이 `assets/*` + `!assets/manifest.json`이라 카드 PNG는 애초에 추적되지 않으며, 그 명령이 증명하는 것은 manifest 무변경뿐이다(같은 함정을 `yt_flow.db`에 대해 10.6이 기록했는데 `assets/`에도 해당된다는 점은 이번에 처음 확인됐다).

### Story 10.6: 캐스트 표시 정합 — D계급 이상·시각적 중복 (지적 14·15)

Jay 지적: "D 계급 요원이 이상하게 나옴", "똑같은 캐릭터가 두 번 찍힘". **실측 확인**: 문제 런의 66샷에서 샷 내 캐스트 키 중복은 **0건**이고 사용 키는 `SCP-049`(41) / `STOCK-d-class`(19) / `SCP-049-2`(13)이다. 즉 15번은 데이터 중복이 아니라 **`SCP-049`와 파생 카드 `SCP-049-2`가 둘 다 흑사병 의사 복장이라 시청자에게 같은 인물로 보이는 문제** — 카드 디자인/파생 규칙 소관이다. ① 파생 카드가 원본과 시각적으로 구분되도록(049-2는 "되살아난 피해자"이므로 복장이 달라야 함) 생성 규칙 정정. ② D계급 카드 품질 재검(8.15가 승인한 STOCK 자산 중 d-class 실물 확인). 의존: 없음.

**done (2026-08-11)** — 근거는 렌더 프레임(`_bmad-output/implementation-artifacts/10-6-live-validation/`), 통과한 테스트가 아니다.
- **①(지적 15) 원인 확정·수정**: `_ensure_derived_entity_cards`가 파생 descriptor를 **베이스 엔티티의 `visual_descriptor` 그대로 + 한 줄**로 만들고 베이스 front 카드를 IPAdapter 앵커로 걸고 있었다. `domain/state.py`에 `DERIVED_DESCRIPTORS`(049-2 = 마스크·후드 없음, 재처럼 창백, 봉합선, 찢긴 수술복)를 저술하고 `anchor_path=None` / `negative_suffix=STOCK_NEGATIVE` / `enrich_ban="SCP Foundation"`로 교체, 미저술 파생 키는 **추측 대신 WARNING 스킵**(`cast_decision.md`의 "잘못된 카드가 카드 없음보다 나쁘다"). 동일 고정 시드(1051)·동일 체인 2-leg: old는 흰 부리 마스크 + 후드 코트 재현, new는 **맨얼굴 + 수술 가운**. 즉 변수는 시드가 아니라 descriptor.
- **②(지적 14) 원인 확정**: 문제 프레임은 8.15 승인 기립 세트가 아니라 **게이트 없는 on-demand pose-hint 카드**(`hint_a40ec9c170`, 19개 D계급 슬롯 중 **7개**에 합성). 사전등록 규칙 + 공유 시드 3쌍 격리에서 **A(서픽스 없음) 2/3 실패 vs B(`STOCK_NEGATIVE`) 1/3 실패 → H1 확정**(H2 "10.3 LoRA 제거로 이미 해결"은 반증). `generate_special_pose_card`가 `negative_suffix`를 안 넘기던 것을 수정 — 단 `STOCK_NEGATIVE`가 `skull mask/helmet/visor`를 억제하므로 **마스크가 정체성인 엔티티 키에는 적용하지 않고** STOCK·저술 파생 키로만 스코프.
- **부산물 기록**: (a) 사전등록 기준(눈/비율/손)이 **figure-count를 안 담아** 최대 차이(시드 1062: A는 성인+치비 아동 2인, B는 성인 1인)를 규칙상 놓쳤다 — 규칙을 고치지 않고 기록. (b) 손 결함은 서픽스와 무관하게 6렌더 중 3회 — 만성. (c) 8.15 승인 D계급 4프레임의 지적 14 결함은 **없음**이나 `side_candidate_1.png`에 **"12"이 적힌 검은 말풍선형 부유물이 알파 안에 포함**되어 있고 `back/side`가 정면으로 렌더된다(10.3 재생성 게이트로 인계).
- **⚠️ 규칙은 고쳤으나 지적 15는 아직 화면에서 사라지지 않았다 — 수정은 소급되지 않는다.** `_ensure_derived_entity_cards`는 `check_existing_character(key) is None`일 때만 생성하고 `SCP-049-2`는 **이미 행이 있다**. 따라서 새 규칙은 이 키에 대해 앞으로도 발동하지 않으며, 라이브 `visual_descriptor`는 여전히 상속된 흑사병 의사 텍스트이고 라이브 카드도 여전히 마스크 쓴 것이다. **현재 자산을 재사용하는 런에서는 지적 15가 그대로 보인다.** 닫힘의 실체는 "규칙 + 동일시드 프레임 증거"까지이고, 화면에서 없애는 것은 자산 교체(= `deferred-work.md`의 Jay 게이트)의 몫이다. 이 에픽이 존재하는 이유가 바로 "스토리를 닫았는데 시청 결과가 안 바뀐" 전례이므로 이 구분을 흐리지 말 것.
- **미해결·인계**: 요청 포즈("lying supine on table")가 7개 렌더 전부에서 무시되어 서 있음 → **10.5(지적 6)**. pose-hint 카드 무게이트 자동승인 + 재생성 승격 판정 2건 → `deferred-work.md`(Jay 게이트). 자산·DB는 한 줄도 변경하지 않았다 — 단 `yt_flow.db`는 `.gitignore:15`에 걸려 있어 `git status`로는 검증되지 않는다(공허한 확인). DB 무변경은 행 수 9/12와 `SCP-049-2` descriptor 원문을 직접 단언하는 read-only 쿼리로 확인했다(`10-6-live-validation/README.md`).

### Story 10.7: 씬 사운드 교체 — 사이렌 (지적 13)

Jay 지적: "이상한 싸이렌 소리 좀 없애줘 (다른 걸로 대체하던가)". 7.1 사운드디자인의 무드→오디오 베드 매핑에서 해당 큐 교체. 작은 작업이나 시청 체감에 직접적이다. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Epic 10 범위 밖으로 보낸 지적

- **지적 1(도입부 나레이션 문장이 이상함 — "손이 닿는 순간, 그는 죽었습니다")**: 대본 품질이므로 **Epic 12 소관**. 다만 이 런은 `deepseek_reasoning=low`로 렌더됐고 나레이션 총량이 2.8분(목표 8분, 베이스라인 `c6be1954` 7.87분)으로 **1/3 수준**이었다는 사실을 함께 넘긴다 — 절단 방지로 넣은 설정이 분량·문장 품질을 동시에 떨어뜨렸을 가능성을 Epic 12에서 검증해야 한다.
- **지적 8(이미 만들어진 셋을 사용하는 게 맞는지 의심스러움)**: 이 런은 `stock_plate_substitution_enabled=false`로 **스톡 플레이트를 의도적으로 쓰지 않았다**(8.17 플레이트 치환이 배경 다양성을 155→41로 붕괴시켜 차단). 즉 "셋 재사용이 안 된 것"이 맞고, 재사용을 되살리려면 플레이트-프롬프트 화해가 선행되어야 한다 — **Epic 8의 별도 스토리**(8.19 리뷰에서 인계된 항목)로 남아 있다.

### Story 10.1d: Recompose 런타임 전제 프리플라이트 (backlog, 2026-08-15 초안)

10.1c 해제 조건 **(b)**. recompose 경로는 ComfyUI를 `--lowvram` + fp8 인코더로 띄워야 하는데(10.1e가 `--disable-smart-memory`를 철회) 그걸 감지·강제하는 코드가 없어, 기본 설치에서 ~12분 스왑 데드락에 빠지고 try/except fallback도 안 걸린다(10.1c 판정 주석). `/system_stats`의 `argv`·RAM으로 진입 시 1회 프리플라이트하고, 실패는 크게·이름 있게·조치 가능하게 낸다. 코드만이고 GPU 불필요하며 **기본값은 건드리지 않는다**. 2026-08-15 라이브 런 e5ed4b3a가 같은 부류를 실증했다 — 플래그 없이 샷당 491초(샘플링은 11초), RSS 14GB+스왑 4GB, yt.flow는 살아 있는 서버를 "죽었다"고 오판. 파일: `10-1d-recompose-runtime-preflight.md`.

### Story 10.1e: Recompose on/off 페어 채점과 기본값 판정 (backlog, 2026-08-15 초안)

10.1c 해제 조건 **(a)**, 10-1d 선행 필수. 같은 샷·같은 시드로 on/off 쌍을 렌더해 13-2의 재구축된 축으로 **블라인드** 채점한다. 미해결 긴장이 실재한다 — Jay의 모션 판정은 PASS였는데 10.4 사후 감사는 재창조 프레임이 판독성에서 더 나빴다고 했다(판독불가 20% vs 13%, 복도 오독 57% vs 27%). 같은 샷을 양쪽으로 잰 적이 없다. 임계값은 채점 전 사전 등록. 플립 시 오버레이 전용 기계(접지·`_GROUND_Y_MAX`·오클루전·접촉그림자·11.5 패럴랙스·1.9c 아이들모션) 폐기 주체를 명시해야 한다. 파일: `10-1e-recompose-default-verdict.md`.

### Story 10.8: 캐스트 포즈·앵글 커버리지 (backlog, 2026-08-15 초안)

라이브 런 e5ed4b3a에서 캐스트 배치 **40건 중 26건이 fallback**(angle 23, asset 3)이고, 실제로 화면에 쓰인 카드는 **전부 `front`** — SCP-049가 21샷 동일 그림이다. Jay 지적: "대부분의 캐릭터들이 그냥 정면 서있는 샷 밖에 없음". 두 층이며 어느 한쪽만 고치면 화면이 안 바뀐다 — ① `cast_decision` 프롬프트가 `pose`를 standing/sitting 둘로 닫고 `pose_hint`는 "대부분 생략하라"고 지시(9씬 전체에 2건) ② 라이브러리에 승인된 `standing` 카드가 어느 앵글에도 없다. 카드 해석 자체는 건강하다(40/40 path 있음) — 리졸버를 손으로 흉내내면 없는 결함이 보인다. 파일: `10-8-cast-pose-angle-coverage.md`.

## Epic 11: 시네마틱 모션 & 프레임 품질 하드닝

2026-08-01 품질 우선 리서치(`_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md`, 코드베이스 정밀 탐색 + 논문/업계 표준 4개 영역 병렬 조사) 발의. Jay의 "조잡함" 지적의 원인 중 Epic 8(카드 컴포지팅 고도화)이 다루지 않는 나머지 절반 — **모션과 이미지 생성 파라미터** — 을 커버한다. 코드에서 확정된 근거: ① 배경 155장 전부 KSampler seed 0 고정(`_inject_prompts`가 노드 6/7만 주입, 워크플로 JSON에 `seed: 0` 하드코딩 — 캐릭터 쪽은 이미 랜덤화 선례 있음 `character_image_provider.py:232`), ② 배경 latent 1216×832(AR 1.462) → `_zoompan_filter`가 세로 ~18%를 크롭 후 업스케일, ③ `composite_harmonization_tier` 기본 0(틴트/컨택트섀도/라이트랩 존재하나 꺼짐), ④ `camera_movement` 하드코딩 `None`(`scenario_chain.py:1079`) → 카메라 방향이 콘텐츠와 무관한 10개 인덱스 라운드로빈, ⑤ "셰이크"가 단일 주파수 사인파("eyeball-tuned; not derived from anything" 주석), ⑥ WhisperX가 사실상 비활성(tts의 균등분할 provisional timings이 항상 존재해 `subtitle.py`의 empty-체크를 통과 못 함) → 8.11 샷 컷이 실제 발화 경계가 아닌 균등분할 위에서 동작. 근거 문헌은 리서치 문서 Area 4(AE wiggle 프랙탈 노이즈 모델, Gavant et al. IEEE 생리학적 카메라 셰이크, Niklaus et al. 3D Ken Burns, DepthFlow, Wan 2.2)에 인용. **착수 순서**: 11.1은 8-16 착수 **전**에 완료(베이스라인 오염 방지), 11.2/11.3은 8-16과 병렬 가능(단 `video.py` 동시 편집 충돌 주의 — 5-14/1-10 전례), 11.5는 8-17(depth map 저장)과 11.3(경로 생성기) 이후.

### Story 11.1: 이미지 생성 파라미터 하드닝 — seed/AR/tier 퀵윈 묶음

반나절 규모 설정·상수 수정 묶음, 신규 아키텍처 없음. ① **per-shot seed 주입**: `image.py _inject_prompts`가 KSampler 노드에 샷별 결정론적 seed(예: `hash(run_id, scene, shot)`)를 주입 — 현재 전 배경이 seed 0을 공유해 구도 다양성이 침식됨. 사이드카 `_done.json` resume 체크에 seed를 포함하도록 확장(현재는 프롬프트 2종만 비교하므로 seed 변경이 캐시를 무효화하지 못함). ② **배경 latent 16:9 네이티브화**: 1216×832 → SDXL 표준 버킷 1344×768로 교체, `_zoompan_filter`의 `scale=1728 → crop=1728:972` 상수를 동기 수정해 세로 18% 크롭-업스케일 제거. 기존 저장 자산과의 호환은 영향 없음(플레이트는 이미 1920×1080 latent). ③ **`composite_harmonization_tier` 기본 0→1**: 이미 구현된 틴트+컨택트섀도를 기본 활성화(8-16의 IC-Light가 오면 그 폴백으로 정착 — 8-16 AC와 정합). ④ **카드 알파 엣지 소프트화**: `_clean_alpha_noise`의 0/255 하드 스냅 제거, 안티에일리어스 엣지 유지 + 2–5px 페더(VFX 표준 — 리서치 Area 3.4). 기존 카드 자산은 재생성 없이 합성 시점 페더로 처리(자산 불변). **회귀 가드**: seed/AR 변경은 골든 렌더 비교가 아닌 파라미터 단위 테스트로 검증(픽셀 비교는 seed 변경 자체로 무의미). (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 11.2: 카메라 모션 아키타입 — 무드 주도 선택 + `camera_movement` 배선

카메라 방향이 샷 인덱스 라운드로빈(`video.py _DIRECTION_POOL`)이라 콘텐츠와 무관한 문제의 해소. ① scenario 체인이 `camera_movement`를 실제로 채우도록 수정(`scenario_chain.py:1079`의 하드코딩 `None` 제거) — 단, LLM 자유 텍스트가 아니라 **닫힌 아키타입 enum**(8.8 `motion_style` 선례): `push_in`(dread/tension/revelation), `pull_back`(isolation/aftermath), `drift`(exposition/calm), `locked`(clinical/oppressive), `shake`(panic/breach). ② 기본값은 무드→아키타입 매핑으로 결정론적 산출(Epic 7 무드 택소노미 재사용 — 7.1이 소유, 7.2 KeyError 불변식 준수), LLM은 매핑을 덮어쓰는 예외만 지정. ③ **연속 샷 동일 아키타입+방향 금지** validator — 8.18과 동일한 결정론적 repair 패턴(LLM 재호출 없이 즉시 재배정), `scenario_chain.py` 내부 순수 함수. ④ 기존 `_DIRECTION_POOL` 라운드로빈은 매핑 실패 시 폴백으로 강등. 근거: 다큐/호러 모션-무드 문법은 업계 관행 수렴(리서치 Area 4.4 — StudioBinder/Doc Film Academy 등), "모든 샷이 같은 모션"이 조잡함의 대표 신호. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 11.3: 프랙탈 노이즈 카메라 경로 — 사인파 상수 대체

`character_motion.py`/`video.py`의 단일 주파수 사인파 + "eyeball-tuned" 상수를 표준 근거 기반 노이즈 모델로 교체. ① **2–3옥타브 fBm(fractional Brownian motion) 노이즈**로 카메라 x/y/rotation/micro-zoom을 동시 구동 — AE `wiggle(freq, amp, octaves)`와 동일한 모델. ② **스펙트럼 2대역 구성**(Gavant et al., IEEE 생리학적 카메라 셰이크 모델): 저주파 sway 0.5–2 Hz @ 프레임폭 0.3–1%(다큐 드리프트)~1–2%(불안 핸드헬드) + 미세 tremor 8–12 Hz(미량). 백색잡음(균등 랜덤)은 금지 — "vibration이 아니라 사람이 든 카메라"가 목표. ③ **trauma 스칼라**(0–1, 시간 감쇠, amplitude=trauma²) 이벤트 셰이크 — 7.1 스팅어 히트와 동기해 스케어 비트에서 셰이크가 유기적으로 램프다운(game-dev 표준 기법). ④ 구현: 순수 파이썬 value-noise fBm ~30줄로 신규 의존성 없이 가능(`ponytail:` opensimplex 도입은 품질 부족이 실측 확인될 때만), per-frame float 변환을 사전 계산해 기존 ffmpeg 표현식에 주입. `MOTION_TABLE_VERSION` 범프. 무드별 노이즈 프로파일(진폭/주파수)은 11.2의 아키타입 테이블에 병합. (draft — 상세 스토리 파일은 create-story로 별도 생성)


**⚠️ 후속 (Jay, 2026-08-09): 이미지 떨림을 아예 없앤다.** 10.1c 전체 렌더를 시청하다 발견 — 핸드헬드
노이즈가 시청 체감에 도움이 되지 않는다. `camera_noise_enabled`(config.py:207) 단일 플래그로 전 스테이지가
분리되며 false면 **pre-11.3 필터 체인과 바이트 동일**하므로 되돌리기 비용이 없다. 다만 끄기 전에 확인할 것:
① `_DIRECTION_POOL`의 `"shake"` 아키타입은 in-center 푸시를 base move로 쓰고 그 위에 fBm을 얹는 구조라
(`video.py:329-332`), 노이즈를 끄면 `shake`가 단순 푸시인과 구분되지 않는다 — 11.2의 무드→아키타입 매핑에서
`shake`를 빼거나 다른 움직임으로 대체할지 판단 필요. ② 스팅어 동기 trauma 셰이크도 같은 플래그에 묶여 있어
함께 사라진다(의도된 것인지 확인). ③ 기본값을 false로 바꿀지, 아니면 아키타입 자체를 정리할지는 ①②의 결론에 따른다.

### Story 11.4: WhisperX 상시 정렬 — 실제 발화 경계 기반 비트 정렬 컷

8.11(per-shot 컷)과 자막 큐가 실제로는 **균등분할 타이밍** 위에서 동작 중인 문제의 해소: Qwen TTS가 타임스탬프를 주지 않아 `tts_node`가 duration을 공백 토큰 수로 균등분할한 `_provisional_timings`를 기록하고(`tts.py:137`), `subtitle.py:376`은 `word_timings`가 비어 있을 때만 WhisperX를 실행하므로 WhisperX가 사실상 한 번도 돌지 않음. 수정: WhisperX 강제 정렬을 **항상** 실행하고 provisional은 WhisperX 실패 시 폴백으로 강등(케이스 로그 필수 — 조용한 강등 금지, 리서치 전략 §21과 정합). 효과: 샷 컷 경계·자막 큐가 실제 문장/절 경계에 정렬 — "나레이션 비트에 맞춘 컷"은 다큐 편집 표준(리서치 Area 4.4). rule metric으로 **컷-정렬 오차**(컷 시점 vs 최근접 발화 경계 편차)를 `eval_service.py` 룰 메트릭에 추가해 회귀 감지. GPU 비용: WhisperX는 런당 1회(에피소드 오디오 전체), `whisperx>=3.8.6`이 pyproject.toml에 이미 있고 `YTFLOW_ALIGNER` 배선(`WhisperXAligner`, device/compute_type 설정 포함)도 완성돼 있어 신규 인프라 없음 — 단 ① `subtitle.py` 모듈 주석 "whisperx is not in pyproject.toml; install it separately"는 스테일(실제로는 의존성 존재), 이 스토리에서 정정, ② 16GB 단일 GPU에서 ComfyUI와 VRAM 경합 주의 — tts→subtitle 구간은 ComfyUI 유휴 시점이므로 순서상 자연 회피되나, 안전하게 `compute_type=int8`/CPU 폴백 검증 포함. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 11.5: DepthFlow 2.5D 패럴랙스 — 배경 플레이트 모션 렌더러 전환

zoompan은 줌+팬만 가능하고(회전·패럴랙스 불가) 좌표 양자화 지터가 유명한 한계(현재 8000px 슈퍼샘플링으로 완화 중) — 모션 렌더링을 ffmpeg 밖으로 옮기고 ffmpeg은 조립/인코딩 전용으로 유지(리서치 Area 4.5 표준 패턴). ① **DepthFlow**(오픈소스, OpenGL 셰이더라 ROCm-무관, ComfyUI 노드팩 존재, 파이썬 스크립터블) 채택 — 배경 플레이트 + Depth-Anything V2 depth map → 2.5D 패럴랙스 프레임 렌더(DOF/비네트 내장), 11.3의 프랙탈 카메라 경로를 DepthFlow 파라미터로 주입. ② depth map은 8-17 시딩 시 플레이트당 1회 생성·저장(8-16 바닥면 추정과 공유)한 것을 소비 — 자유생성 배경은 image_node에서 depth 1회 추가 실행. ③ **레이어드 패럴랙스**: 캐릭터 카드는 플레이트 변위의 60–80%로 별도 이동(카메라-뒤 느낌) — 단일 이미지 한계(변위 1–3% 초과 시 고무줄 아티팩트)를 레이어 분리로 회피(리서치 Area 4.2). **⚠️ 2026-08-08 폐기 예정**: Epic 10 "확정 방향: 카드-배경은 최종적으로 한 장으로 융합한다" 블록이 이 서술을 대체한다 — 카드가 배경과 따로 움직이는 것이 접지가 맞는데도 "둥둥 떠 보이는" 유력한 원인으로 지목됐고, 융합은 이 기능을 의도적으로 제거한다. "레이어 분리 = 고유 이점"을 근거로 융합에 반대하지 마라. ④ 폴백 경로: DepthFlow 도입이 막히면 파이썬 float affine 슈퍼샘플 렌더(PIL/numpy) + ffmpeg 인코딩으로 동일 효과의 축소판. 의존: 11.3(경로 생성기), 8-17(depth map). 성능: 플레이트당 GPU 셰이더 렌더라 ComfyUI 생성 대비 무시 가능한 비용. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 11.6: 히어로 샷 선택적 i2v — Wan 2.2 카메라 컨트롤 (조건부)

**조건부 스토리**: 11.1–11.5 완료 후에도 특정 샷에서 실제 움직임(안개, 호흡, 촛불 깜빡임, 천 흔들림)이 필요하다고 Jay가 판단할 때만 착수. Wan 2.2 A14B i2v GGUF Q5_K_M(디퓨전 모델 ~8.5GB, T5 시스템 RAM 오프로드, peak 12–14GB@720p — 16GB 카드 적합, ComfyUI-ROCm 공식 지원, AMD가 Radeon Wan 튜토리얼 공식 게시)을 **에피소드당 1–3 히어로 샷에만** 적용 — RX 9060 XT에서 클립당 5–15분 예상이라 전 샷 적용은 비현실적. 카메라 제어: Wan2.2-Fun A14B Camera-Control(명시적 pan/zoom 조건 코드) 또는 push-in 모션 LoRA. 합성 순서 주의: i2v 입력은 **합성 완료된 프레임**(카드+플레이트+하모나이제이션 적용 후)이어야 캐릭터가 함께 움직임. 폴백: 호스티드 API(Kling ~$0.10/s, Veo Fast ~$0.15/s — 60샷 전체도 $30–45 수준)를 머니샷 한정으로 검토. (draft — 상세 스토리 파일은 create-story로 별도 생성. `ponytail:` 확정 요구사항 아님 — 11.1–11.5의 효과를 본 뒤 필요성이 실측 확인되면 착수)

## Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트

2026-08-03 발의(Jay). Epic 8/11이 "조잡함"의 **시각** 절반을 다루는 동안 **대본/나레이션** 절반은 스코프에 들어온 적이 없었다 — 2026-08-01 품질 리서치(`research/technical-yt-flow-quality-strategy-research-2026-08-01.md`) Phase 3의 4개 항목 중 아키타입 다변화(구 10.1) 하나만 스토리화돼 있었음. 리서치 판정: **시나리오 체인의 구조는 이미 SOTA에 가깝다**(다단계 + scoped repair). 실제 갭은 ① 리텐션 설계가 프롬프트 산문 속 형용사로만 존재하고 검증 가능한 스키마가 아님, ② writer와 judge가 같은 모델(self-preference bias), ③ 한국어 표면 품질이 DeepSeek 한계에 묶임, ④ pass-2 비평 판정이 계산만 되고 버려짐.

**이 에픽의 전체 스토리는 GPU가 필요 없다** — scenario 체인/프롬프트/평가 계층 작업이라 ComfyUI 박스 없이 진행 가능. Epic 8-16/11-5(GPU 필수)와 완전 병렬. 착수 순서 권고: **12.2 → 12.1 → 12.3 → 12.4**(문장 품질이 먼저 올라가야 리텐션 구조 개선이 체감됨 — 어색한 문장에 좋은 구조를 씌우면 어색함이 먼저 들린다), 12.5는 조건부.

### Story 12.1: 리텐션 스키마 — 훅/오픈루프/페이싱을 검증 가능한 필드로

리서치 Area 1.3(YouTube 리텐션 구조, 실무 합의) + 1.6. 현재 `structure.md`/`writing.md`는 "긴장감 있게", "훅으로 시작" 같은 산문 지시로 리텐션을 요구하고 검증 수단이 없다. 아웃라인 스키마를 확장: **hook type**(질문/충격/미스터리/대비 — `format_guide`의 기존 어휘 재사용), **오픈루프 원장**(씬별 `loops_planted`/`loops_closed` — 심은 루프가 어느 씬에서 닫히는지 추적), **패턴 인터럽트 간격**(연속 서술 톤이 N씬 이상 이어지지 않게), **비트별 단어 예산**(씬 길이 편차를 프롬프트 부탁이 아니라 숫자로). 검증은 LLM 재호출 없는 **결정론적 체크**로 — 8.18/11.2에서 확립된 패턴(`scenario_chain.py` 내부 순수 함수, 위반 시 즉시 재배정 또는 하드 실패). 열린 루프가 끝까지 닫히지 않으면 그 자체가 결함이므로 원장 미청산은 명시적 위반으로 처리. 아웃라인 항목은 형용사가 아닌 **사건 기반**(누가/무엇을/결과)으로 산출하게 프롬프트 수정. 신규 서비스 분리 없음. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 12.2: 모델 분리 — DeepSeek 기획 / Gemini 한국어 문장 + judge

리서치 Area 1.4 + Phase 3 #17. 현재 `_call_deepseek` 하나가 research→structure→writing→review→critic→visual_breakdown→cast_decision→tts_normalize 전 스테이지와 **평가 judge까지** 담당한다. 두 개의 독립된 문제: ① DeepSeek은 구조 설계에는 강하지만 한국어 자연스러움에 문서화된 약점이 있음(5.22 나레이션 문체 스토리가 프롬프트로 싸웠지만 AC6 median 임계값 미달로 끝난 것이 이 한계의 증상), ② writer와 judge가 동일 모델이면 self-preference bias가 재현적으로 관측됨 — 자기 문장을 후하게 채점하므로 게이트가 품질 보증 기능을 상실.

**2026-08-03 Jay 결정 — 2계열 분리**: 기획/구조/파싱 스테이지는 **DeepSeek 유지**(비용, 스키마 순응도, 캐시 히트 최적화 6.3 자산 보존), **최종 한국어 문장 패스와 평가 judge는 둘 다 Gemini**. 신규 의존성이 1개로 줄고(초안의 Claude+Gemini 2개 안 폐기), 한국어 판정에도 한국어 문장을 쓰는 모델의 감각이 붙는다.

**의도적으로 수용한 트레이드오프(기록 필수)**: 이 구성에서는 Gemini가 자기가 쓴 문장을 채점하므로 **self-preference bias가 남는다** — 리서치 Area 1.2/Phase 3 #17이 지목한 문제(현재 writer=judge=DeepSeek)의 형태가 DeepSeek에서 Gemini로 옮겨가는 것이며 제거되지는 않는다. Jay가 이를 알고 채택. 완전 독립이 필요해지면 **0-비용 대안**이 남아 있다: 문장만 Gemini로 넘기고 런타임 `review`/`critic` + 4.2 eval judge는 **DeepSeek에 유지** — 그러면 writer(Gemini)와 judge(DeepSeek)가 서로 다른 계열이 되고 신규 API도 그대로 1개다. 승격 게이트 판정이 의심스러워지는 실측이 나오면 이 옵션으로 전환할 것(6.10 median 게이트의 신뢰도가 judge 독립성에 직접 의존하므로 13.4 게이트 해제 시점에 재검토 필수).

배선은 5.13 선례(character vision 프로바이더 교체 — 메시지 구성/예외 처리 무변경, HTTP 타겟과 config 필드만 교체)를 따르되, 요청/응답 스키마가 다르므로 순수 엔드포인트 스왑은 아님. `config.py`에 스테이지별 모델/키 필드 신설, 4.2 `eval_service` judge 호출을 Gemini로 전환. 주의: `tts_normalize`(5.4/5.18 이중 트랙)와 `writing`은 출력 계약이 얽혀 있어 어느 스테이지까지를 Gemini로 넘길지 경계를 스토리에서 확정할 것. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 12.3: pass-2 판정 활용 + 접지(grounded) 모순 검사

**코드 확인(2026-08-03, 리서치 주장 정정)**: 리서치는 "critic 판정이 기록만 되고 무시됨"이라 했으나 실제로는 **pass-1 판정은 정상 사용된다** — `scenario.py:364`의 `if critic["verdict"] == "retry" or not review["overall_pass"]`가 scoped repair를 트리거함. 무시되는 것은 **pass-2**다: `scenario.py:370`(및 full-rewrite 분기 401/421/426)이 수정 후 재계산한 `review`/`critic`을 같은 변수에 덮어쓰고, 그 뒤로는 아무도 읽지 않고 `scenario.py:432` `tts_normalize`로 직행한다. 즉 재시도 후에도 여전히 `retry` 판정이거나 `overall_pass=False`인 시나리오가 **어떤 신호도 없이** 휴먼 게이트로 넘어간다(6.5의 bounded-retry 계약상 재재시도는 하지 않는 것이 맞으나, 조용히 통과시키는 것은 별개 결함 — AD-10 "조용한 강등 금지"와 불일치).

수정 두 조각: ① **pass-2 판정 표면화** — 재시도 후 판정이 여전히 부정이면 게이트 페이로드에 critic 요약을 첨부해 사람이 알고 승인/거부하게 한다(런을 실패시키지 않음 — 판단은 사람 몫, 13.1과 동일 원칙). ② **접지 모순 검사** — `review` 단계가 `entity_sheet`/`frozen_descriptor`에 대해 나레이션 문장을 인용하며 모순을 지적하도록 확장(현재는 축 점수만). 결정론적 slop/반복/길이 메트릭도 규칙 메트릭으로 추가(LLM 판단 불필요분은 코드로). 6.10 median 게이트와 병존 — 이 스토리는 런타임 경로, 6.10은 프롬프트 승격 경로. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 12.4: 스토리 아키타입 다변화 (구 Story 10.1 — 2026-08-03 Epic 10 흡수로 이동)

고정 INCIDENT-FIRST 4막 외에 2-3개 아키타입 추가(예: 인터뷰/증언 로그식, 봉쇄 실패식, 배치 성공식) — 실제 다큐/크리피파스타 페이싱 기법(콜드 오픈, 신뢰 못 할 화자, 비선형 타임라인) 레퍼런스 반영. SCP별 로테이션 또는 LLM이 소재에 맞게 선택. 아키타입별 골든 예시(few-shot) 1-2개씩 큐레이션해 6.2 golden-set 인프라에 연결, PROMPT_POLICY 절차 준수. **참고 문헌**: Narrative Theory-Driven LLM Methods for Automatic Story Generation and Understanding: A Survey(arXiv 2602.15851) — narratology의 다양한 개념을 LLM 스토리 생성 연구에 매핑한 2026년 서베이. 구체적 아키타입 카탈로그 자체를 제공하진 않으므로 이 서베이를 출발점 삼아 인용된 1차 문헌(예: Propp의 Morphology of the Folktale류 함수 기반 구조)까지 확인해 아키타입 후보를 정의할 것. 리서치 Phase 3 #16은 3–5종을 권고(incident-first / discovery-log / interview-testimony / containment-breach-realtime / researcher-descent)하고 선택 주체를 research 스테이지로 지목.

**2026-08-03 Jay 지적으로 추가된 필수 제약 — 아키타입 선택은 로테이션이 아니라 원문 해부 구조의 함수**: SCP 문서는 정형 해부 구조를 가진다(`Item #` / `Object Class` / `Special Containment Procedures` / `Description` + Addenda: incident log, experiment log, interview log, recovery report). 현행 INCIDENT-FIRST 4막은 그 순서를 **의도적으로 뒤집은** 것이고(`structure.md`가 "This is NOT a wiki article — viewers don't care about classification"으로 명시), Jay가 관찰한 "사례/사건 → 개체 소개 → 다른 사건/실험" 형태가 정확히 이 템플릿이다. 따라서 "아키타입"의 실체는 임의의 이야기 형태가 아니라 **어떤 addendum을 앞세우고 누구 시점으로 가는가**이며, 원문에 그 addendum이 없으면 그 아키타입은 성립하지 않는다(실험 로그식 ← experiment log 풍부, 예 914/294 / 인터뷰·증언식 ← interview log 존재, 예 049/079 / 봉쇄 실패 실시간식 ← incident·breach 기록, 예 173/096 / 발견·회수 기록식 ← recovery report).

**따라서 금지 사항**: SCP별 단순 로테이션이나 LLM 자유 선택으로 아키타입을 배정하지 말 것 — 인터뷰 로그가 없는 SCP에 "인터뷰식"이 배정되면 LLM이 인터뷰를 **날조**하고, 그 손실은 `article_fidelity` 축으로 직행한다(8.8이 SCP-096에서 `article_fidelity -1.00`으로 골든셋 게이트 FAIL 낸 것과 동일 부류의 사고). 구현: **research 스테이지가 원문의 addendum 인벤토리를 산출하도록 스키마 확장**(현행 research 출력은 `core_identity`/`frozen_descriptor`/`entity_sheet`/`story_logline`/`dramatic_beats`/`environment`/`hooks`뿐 — 해부 구조 필드가 없음을 2026-08-03 확인) → 아키타입 후보 집합을 그 인벤토리로 **결정론적으로 제약**하고, 후보가 복수일 때만 LLM이 소재에 맞게 선택. 인벤토리가 INCIDENT-FIRST만 지지하면 그대로 유지(다양성보다 사실성 우선 — 모든 SCP를 다양화할 필요는 없다). 12.1의 결정론 체크와 동일 패턴으로 `scenario_chain.py` 내부에서 검증. (draft — 상세 스토리 파일은 create-story로 별도 생성)

### Story 12.5: TTS 프로바이더 비교 — Naver Clova Voice 검토 (조건부)

2026-08-03 Jay 발의("한국어 현지화가 잘 되어 있으니 네이버가 낫지 않나"). 현행은 Qwen TTS(DashScope 국제 엔드포인트, `qwen3-tts-flash`, 보이스 `Cherry`, `atempo` 1.2 배속, 클론 기본 OFF — `config.py:63-72`). 프로바이더 결합은 얕음(`tts.py:121-126`의 단일 httpx POST + DashScope 페이로드 스키마) — 5.13 선례 규모의 교체지만 요청/응답 형태가 달라 순수 엔드포인트 스왑은 아님.

**판단은 청취로만 가능하다** — 이 스토리는 교체가 아니라 **비교 후 결정**이 산출물. 근거: ① 한국어 원어 엔진의 운율 우위 가능성은 실재하나 측정 없이 단정 불가, ② **클론 보이스가 리스크** — 5.21/5.24가 이미 클론 배선(`sutak.mp3` → voice id 등록, 재등록 `--force`)을 만들어놨고, Naver의 셀프서브 음성 클로닝 지원 여부/조건은 스토리에서 확인 필요(미지원이면 클론 트랙을 버리는 대가), ③ **숨은 결합** — 5.4/5.18의 `tts_normalize` 정규화 규칙은 Qwen의 읽기 습성에 맞춰 튜닝됐다(숫자/영문/지칭 처리). 엔진이 바뀌면 일부 정규화가 불필요해지거나 역효과가 되므로 정규화 프롬프트 재검토가 교체에 딸려온다. ④ word timings는 어느 쪽도 제공하지 않으므로 11.4 WhisperX 정렬은 무관하게 유지(득실 없음).

**DoD**: 동일 씬 1개로 3후보(Qwen 스톡 / Qwen 클론 / Naver) 청취 A/B → Jay 판정. 5.21의 미결 DoD(스톡 vs 클론 청취 비교)를 이 비교에 흡수해 한 번에 정리. 채택 시에만 교체 구현. (draft — 상세 스토리 파일은 create-story로 별도 생성. `ponytail:` 확정 요구사항 아님 — 청취 결과가 교체를 정당화할 때만 코드 변경)


### Story 12.6: 원문에 살을 붙이는 각색 (backlog, 2026-08-15 초안)

Jay가 라이브 런 e5ed4b3a를 보고 지적한 두 가지 — "대본이 너무 짧고, 스토리텔링 전개가 부족하다" — 의 뿌리는 둘 다 **규정을 지킨 결과**다.

① **길이는 스펙에 박혀 있다.** `structure.md:114`가 분량을 *"현재 3분 파이프라인 기준, 총합 180~360어절"*로 못 박고 `scenario_chain.py:65`에 `TARGET_DURATION_MINUTES = 3`이 상수로 있다. 이번 런의 304어절은 규정 한가운데이고, 모델은 지시를 어긴 적이 없다. 그리고 이건 회귀다 — iteration 2(`c6be1954`)는 8분 10초였다. 밀도는 문제가 아니다(클론 음성 151 WPM은 영상 에세이 최고 리텐션대인 145 WPM 부근).

② **각색이 결함으로 취급된다.** 이번 런 크리틱은 "두개골 융합"·"지능이 높다"를 Fact Sheet 미근거로 기각하면서 동시에 씬4를 "보고서 낭독조"라고 지적했다. 정반대 방향의 두 요구를 걸어놓고 어느 쪽 살을 붙여도 되는지는 말하지 않으니, 모델의 안전지대가 곧 "원문 요약을 낭독조로 읽기"가 된다 — 씬4의 `"재단 공식 기록을 낭독합니다"`가 그 산출물이다. 문헌은 이미 factuality 환각과 faithfulness 환각을 나누고 extrinsic 추가를 별도 범주로 두는데, 우리 크리틱은 전부 위반으로 뭉갠다.

**불변 원칙**: 우리는 원문이 있고 거기에 살을 붙여 좋은 영상 대본을 만든다. 자유 창작 허용이 아니라 **허용 범주의 선언**이다 — 원문 사실의 감각적 묘사·장면화·빈칸을 질문으로 열기는 허용, 원문에 없는 새 사실 단언은 계속 금지. 목표 길이 자체는 Jay 판정 사항으로 남긴다. 파일: `12-6-source-grounded-story-expansion.md`.

### Story 12.7: 문체 하네스 — 전체용 할당량을 씬별 배정으로 (backlog, 2026-08-16 초안)

12.6 출하 후 Jay가 산출물을 듣고 지적: **"맥락 없이 상세한 내용만 주저리주저리한다."** 실측이 원인을 짚는다 — 8씬 전부 극적 질문이 정확히 1개씩(총 9), 2인칭은 6/8씬.

**원인은 제약의 양이 아니라 실행 층이다.** `writing.md:38-48`의 할당량은 *"시나리오 전체에서 최소 3회"*처럼 **대본 전체 기준**인데, `writing_step`은 **씬당 LLM 한 번**이고 각 호출은 자기 씬 + 앞뒤 한 줄 요약만 본다(`_writing_scene_brief`). 이미 채워졌는지 셀 수단이 없으니 매 호출이 자기 씬에서 할당량을 채우고, 전체 3회짜리 요구가 8번 실행돼 7회가 된다. 파이프라인은 이 문제를 이미 풀어봤다 — `hook_type`은 아웃라인이 씬 1에만 배정한다. 같은 모양을 몰입 기법에 적용한다.

**라이브 ablation(2026-08-16)이 가설을 확인했다**: 배정을 도입한 arm A에서 질문이 8/8씬 → 2/9씬, 2인칭 6/8 → 2/8로 떨어졌고 **배정 준수 4/4 정확**(배정 안 한 씬에는 하나도 안 나옴). 문장 규칙까지 완화한 arm B는 평균 문장 33.1자 → 42.5자, 앞 씬과 연결하며 시작하는 씬이 0/7 → 7/7. Jay 청취 판정: 둘 다 개선.

**함정 둘**: ① 질문을 요구하는 곳이 **두 군데**다(기법 블록 + 종결어미 리듬 규칙 `writing.md:57-61`) — 하나만 고치면 산출물이 안 변하고 "가설 틀렸다"는 오판이 난다. ② ablation의 접지 위반은 전부 **structure 단계가 만든 것**을 작성자가 지시대로 옮긴 것이다(12.8 소관) — 이 스토리의 회귀로 오독하면 안 된다. 파일: `12-7-prose-harness-device-allocation.md`.

### Story 12.8: 아웃라인 접지 — 주인 없는 날조와 잘못 붙는 청구서 (backlog, 2026-08-16 초안)

12.7의 ablation이 문체를 재려다 더 무거운 걸 밟았다. **세 arm 전부, 접지 위반 문장은 작성자가 지어낸 게 아니라 아웃라인의 `fact_references`/`event`에 이미 있던 것을 지시대로 옮긴 것**이다 — *"등급은 유클리드"*(원문에 등급 없음)는 `fact_references` 그대로, *"더 많은 수술 도구를 요구"*·*"실패한 재활성화 기록"*은 `event.consequence`/`event.what` 그대로, 반복되는 *"가면이 융합되어 있다"* 확실성 상향은 아웃라인이 원문의 **"~로 보인다"를 이미 떨어뜨린** 결과다.

**결함 1 — 소유권 공백.** `scenario_chain.py:911-913`이 12.1 시점에 아웃라인 접지 검사를 *"review/critic이 소유한다"*며 미뤘는데, `review_step`도 `critic_step`도 **아웃라인을 받지 않는다**(각각 fact sheet + 나레이션만). 책임을 넘겨받은 쪽이 볼 수가 없어 결과적으로 주인이 없다 — Epic 13이 말하는 조용한 실패의 전형.

**결함 2 — 청구서가 아래층에 붙고, 아래층은 못 고친다.** 크리틱이 fact sheet 기준으로 판정하므로 아웃라인의 날조가 작성자의 `ungrounded_claim`으로 보고된다. 12.6의 게이트 범주는 정확히 발화하지만 가리키는 층이 틀렸다. 게다가 `structure_step`은 런당 **1회**뿐이고 `_full_rewrite`는 같은 아웃라인을 재사용하므로, 아웃라인에서 태어난 날조는 **재시도 루프가 구조적으로 도달할 수 없다** — 이미 옳았던 나레이션을 못 고칠 결함을 향해 다시 쓴다.

**접근**: `fact_references`가 원문 축자 인용을 함께 싣게 하고 인용 존재 여부를 **Python 부분문자열로 결정론 검증**(LLM 콜 추가 없음, `review.md`의 `grounded_contradictions` 양쪽 인용 요구가 선례). 그러면 헤지 손실이 읽어서 확인 가능해진다. `event` 필드도 동급. 판정은 아웃라인 유래/나레이션 유래를 구분해 게이트에 싣되 **세 번째 패스는 추가하지 않는다**(6.5 유지) — 헛도는 재시도를 고치는 게 아니라 보이게 하는 것이 목표. 파일: `12-8-outline-grounding-and-attribution.md`.



## Epic 13: 품질 관측 & 게이트 성숙 — 조용한 실패 표면화 + 시각 평가 축

2026-08-03 발의(Jay). 리서치 Phase 4 #20/#21 + Phase 2 #13. 이 파이프라인의 반복 사고 패턴은 **조용한 성공 위장**이다 — 8.17이 드러낸 "done인데 `location_plates` 0행"(스키마·서비스·시드 스크립트는 완성, 한 번도 실행 안 됨), 8.15가 드러낸 "2026-07-12부터 모든 vision enrichment가 400 실패 중"(비치명적 설계라 아무도 몰랐음), 11.4가 드러낸 "WhisperX가 사실상 한 번도 안 돌았음". 전부 코드는 정상이고 **결과물만 없었던** 사례이며, 테스트도 git도 이 계층을 못 본다. 이 에픽은 그 사각지대를 구조적으로 닫는다.

**13.1을 제외하면 GPU 의존이 낮다** — 13.2의 채점은 기존 렌더 산출물을 CPU로 읽고, 13.3의 코드 작업은 비-GPU(단 검증은 ComfyUI 필요). 13.1 우선 착수 권고: 가장 싸고 즉시 디버깅 비용을 줄인다.

### Story 13.1: 조용한 강등 표면화 — 게이트에 경고로 노출

AD-10은 "조용한 강등 금지"를 요구하지만 실제로는 여러 경로가 로그만 남기고 통과한다: cast 멤버의 카드가 없어 샷이 배경만으로 렌더되는 경로(8.13이 고친 `no character row for cast member ... skipping` ×10이 정확히 이 부류 — 고친 뒤에도 캡 초과분은 여전히 조용), 로케이션 플레이트 미스(생성 폴백), relight/harmonization 실패(8.7의 per-shot 예외 격리), 세그멘테이션 실패 플랫 폴백(5.11), 특수 포즈 캡 초과(8.4 `special_pose_max_per_run`), enrichment 400(8.15). 각 경로가 **런 단위 경고 레코드**를 쌓고 그것이 게이트 응답/UI에 노출되게 한다 — 런을 실패시키지 않는 비치명적 계약은 유지하고(그 설계는 옳다), "사람이 모른다"만 고친다. 3.5 게이트 컨트롤 UI에 경고 배지 추가. 신규 서비스 분리 없음(기존 state/artifact 경로에 필드 추가). (draft — 상세 스토리 파일은 create-story로 별도 생성)

**Epic 12 회고 반영(2026-08-08)**: 12.3이 이미 시나리오 전용 `scenario_quality`를 checkpoint → gate interrupt → `gate_pending`/artifact → `ScenarioQualityWarning`으로 전달한다. 13.1의 범용 `run_warnings`는 이 계약을 대체하지 않고 **가산적으로** 같은 전달 축을 재사용해야 한다. 특히 scenario gate에서 `scenario_quality`를 보존하고 generic warnings를 함께 실어야 하며, UI도 두 경고 의미를 합치지 않는다.

**🔓 구현 완료 → review (2026-08-14, `implementation-artifacts/13-1-surface-silent-degradations.md`)** — `PipelineState.run_warnings`가 유일한 경고 권위(`NotRequired`, 리듀서 없음, 전달축은 12-3 그대로 재사용하되 두 계약을 합치지 않음). **본론은 새 계측이 아니라 이미 있던 생산자를 연결한 것**이다: `resolve_cast_cards`가 8.3부터 카드별로 계산해 온 `fallback`/`angle_fallback`/`asset_fallback`/`fallback_reason`은 소비자가 트레이스 정수 하나(`fallback_used`)뿐이라 "어느 샷이, 앵글 때문인지 포즈 때문인지"를 말할 수 없었다 → shot별 `cast_card_missing`/`cast_card_fallback`으로 교체(선언된 cast와 해석된 카드를 샷 단위로 대조). 순서·중복은 `(code, stage, context−detail)` 동일성으로 결정론적이며 재시도는 목록을 늘리지 않는다(예외 텍스트는 동일성에서 제외 — 시도마다 달라져 중복을 만든다). 스토리 작성(08-03) 이후 착륙한 강등 경로 4종을 어휘에 추가: `special_pose_guide_unapplied`(10.5), `derived_entity_look_unauthored`(10.6), `character_card_i2i_fallback`, `background_guard_unscreened`(10.2). **경고하지 않기로 한 것**: `background_person_guard_attempts=0`·`stock_plate_substitution_enabled=False`·`composite_harmonization_tier<3` 같은 **설정 비활성 상태**(에픽 공통 기본값 — 매 런 울리는 배지는 배지를 죽인다). 대신 "켜졌는데 못 돌았다"(키 부재/차단기/사다리 소진, 리졸버 미주입)는 런타임 강등으로 경고한다. 5.11 `layered_fallback` UI 잔재는 실재를 확인한 뒤 제거했다 — 8.3이 백엔드를 없앤 뒤 6에픽 동안 절대 렌더되지 않는 표시였다. 적대적 리뷰 18건을 같은 diff 안에서 수정했고(bad_spec 루프백 0), 그중 최대 수확은 **`pose_hint` 미스가 경고를 하나도 안 내고 있었다**는 것 — 폴백 메타데이터를 소비자에 연결하는 것만으로는 부족했고, 생산자 자신이 그 미스를 폴백으로 기록하지 않고 있었다. ⚠️ **정직화**: 출하 기본값(`stock_plate_substitution_enabled=False`, `background_person_guard_attempts=0`, `composite_harmonization_tier=1`)에서 21개 코드 중 **8개는 오늘 발화하지 않는다** — 각 플래그를 켜면 살아나며 활성 경로에 대해 테스트돼 있다. 검증은 전부 로컬(2782 passed/1 skipped, ruff clean, vitest 128, tsc+build); **라이브/GPU 검증 없음**이며 이 스토리는 배선이라 필요하지 않다.

### Story 13.2: 평가 축 확장 — 프레임/모션 축 추가

현재 `eval_service`의 judge는 **나레이션 텍스트만** 채점한다(4.2의 3축: atmosphere/narrative_coherence/article_fidelity) — 즉 영상이 아무리 조잡해도 평가 점수는 변하지 않는다. Jay의 "품질 우선" 요구와 정면으로 어긋나는 갭. 추가할 축은 전부 규칙/도구 기반(LLM 판단 불필요): **libcom composite quality score**(8.16이 도입 시 캘리브레이션한 임계값 재사용 — 8.16 미착수 시 이 스토리는 나머지 축만), **모션 다양성/아키타입 커버리지**(11.2의 닫힌 enum 분포 — 연속 동일 모션 비율), **컷 정렬 오차**(11.4가 이미 추가한 룰 메트릭을 평가 축으로 승격). 채점 입력은 기존 런 산출물(합성 프레임/EffectSpec/타이밍)이라 GPU 재실행 불필요. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**계측기 우선 갱신(2026-08-10, Story 10.4 실측 + 문헌 조사 반영 — 상세: `planning-artifacts/research/technical-narration-image-semantic-alignment-2026-08-10.md`)**: 시각 축을 붙이기 전에 **계측기부터 교체한다**. 10.4가 만든 VLM 1–5 리커트 축은 자기 데이터로 두 번 실패했다 — `legible`은 66프레임 분포가 {4:46, 5:20}로 하한 변동 0(같은 응답의 자유텍스트는 9/66에 `event: "unclear"`를 썼는데도), `match`는 3에 몰려 병합 프로브 16행 중 15행이 무변이었다. 학계는 이미 QG/A 분해로 옮겨갔다: **TIFA**(프롬프트→QA쌍→VQA 정답률), **DSG**(ICLR 2024, 원자 명제 + **의존 그래프** — 선행 명제가 틀리면 후속 답을 무효화해 TIFA의 모순/환각 답을 차단), **VQAScore**(ECCV 2024, *"Does this figure show {text}?"* 의 **"yes" 토큰 확률** — 연속값 1콜, CLIPScore의 구성 취약성과 GQA류의 yes-bias를 모두 회피). **채택 권고는 DSG 계열**이다 — 10.4가 실측한 결함 둘을 동시에 고친다: ① 명제 비율은 연속값이라 3에 몰리지 않고 ② **카드 부재 교란(11/66)**을 사람 명제를 생성하지 않는 것으로 구조적으로 제거하며 ③ 어느 명제가 깨졌는지가 그대로 나온다. VQAScore는 토큰 logprob이 필요하므로 엔드포인트 지원 여부를 먼저 확인해야 하고(가정 금지), DSG는 yes/no만 있으면 되므로 기본값으로 안전하다. 함께: 10.4의 불리언 `readable` 배선(unreadable 12/66이 지적 2의 실체), **매핑에는 런을 더 쓰지 마라**(손으로 짠 커버조차 `match`를 못 움직였다). 한계: DSG/VQAScore의 인간 상관 보고는 일반 T2I 벤치마크 기준이며 한국어 나레이션·합성 전 배경 플레이트에서의 거동은 실측 대상이다.

**🔒 계측기 교체 완료 (2026-08-11, `spec-13-2-visual-eval-axes.md` / 증거 `13-2-live-validation/`)** — 위 갱신이 지시한 순서대로 계측기를 먼저 교체하고, 같은 66프레임에 돌려 리커트와 대조했다.

① **VQAScore는 실측으로 기각.** DashScope compatible-mode에서 `qwen-vl-plus`는 `logprobs: true, top_logprobs: 5`를 보내도 `logprobs: null`(HTTP 200)을 주고, **같은 엔드포인트·같은 키**의 `qwen-plus`는 완전한 `top_logprobs`를 준다. 엔드포인트는 지원하는데 우리 비전 judge가 안 한다 → VQAScore 구현 불가. DSG는 yes/no만 필요하므로 그대로 채택.

② **해상도 결함은 닫혔다.** DSG 명제 분해(`scripts/score_shot_narration.py --dsg`, 원자 명제 + 의존 그래프, 부모가 no면 자식 질문을 던지지 않고 불충족 처리)로 동일 66프레임을 재채점: **distinct value 5 → 9**, v2가 정확히 3에 몰아둔 **29행이 7개 값으로 분산되어 18행이 파일을 벗어났고**, 최대 버킷은 44%(29/66) → 27%(18/66). mean_dsg 0.5038. **단, 연속값이라고 부르면 안 된다** — 사람 명제 제외 후 분모가 행당 2.9개(190/66)라 값이 0·¼·⅓·½·⅔·1 격자에 놓인다. 9 > 5이고 27% < 44%인 것까지가 지지되는 주장이다.

③ **카드 부재 교란은 기록보다 훨씬 컸다.** "11/66"은 재현 불가다 — `missing` 자유텍스트 손계수이고 스크립트도 규칙도 기록되지 않았다(grep + `git log -S` 확인). 폐기하고 명제로 실측: 생성된 353개 중 **163개(46%)가 사람 명제**이며 **66행 중 61행(92%)**이 최소 하나를 안고 있었다. 명제를 생성한 뒤 제외하므로 제거량이 주장이 아니라 수치로 남는다. 참고로 써 둔 규칙 두 개(패턴을 JSON에 기록)로는 `missing`의 사람명사 14/66, 블라인드 `event`의 사람명사 26/66 — 둘 다 자유텍스트 프록시이고 명제 카운트가 실측이다.

④ **착수 전 스모크에서 계측기 결함 2건을 잡았다(이것이 순서를 지킨 이유다).** (a) QG가 `hand`·`robe`·`silhouette`·"human figure"를 `object`/`state`로 오분류 → 3/3행이 사람 명제로 채점되어 **교란이 완전히 재유입**. 수정: `subject` + `about_body`를 명시 단계로 만들고 워크드 예제 2개를 붙였으며, `_is_person`이 `kind`/`about_body`의 **합집합**을 쓴다(질문 텍스트 정규식 금지 — `gotcha_person-token-regex-is-unusable-on-image-prompt`). 잔여 불일치 **42/353(12%)**은 점수를 오염시키지 못하지만 `dsg_label_disagreements`로 **보고**한다. (b) 사람 부모가 no면 정당한 배경 명제를 무효화했다(실례: "사람이 안쪽으로 이동 중인가" no → 자식 "감방 문이 열려 있나" 무효). 즉 **분수에서 제외하는 것만으로는 부족**하고 사람 명제가 배경을 무효화할 수 없어야 한다 → 사람 명제는 **카드층이 공급하므로 충족 처리**하고 질문하지 않는다. (c) 사람을 빼면 분모가 0이 되는 문장이 많아 3행 중 2행이 unscorable → QG에 배경층(장소 + 물리적 흔적)을 필수화(문장이 함의하지 않는 디테일 창작 금지) → **unscorable 0/66**.

⑤ **기대와 반대인 결과 2건 — 그대로 남긴다.** v2 `match`↔v3 `dsg_score` 순위상관이 **0.0263**으로 사실상 무관하다: 한 구성물의 두 캘리브레이션이 아니라 **다른 것을 재고 있다**(v2가 교란됐다는 것과 정합하지만 v3가 옳다는 증거는 아니다 — 인간 검증은 없다). 그리고 mean_dsg가 블라인드가 판독불가라 한 12프레임에서 **더 높다**(0.5694 vs 0.4892). n=12로 약하지만 방향은 기록한다. ⇒ **`readable`과 `dsg_score`는 별개 축으로 유지**(10.4의 지적 2 vs 4 분리와 동일 논거)하고, 이것이 이해되기 전까지 **`dsg_score`를 게이트로 쓰지 않는다**. 임계값도 의도적으로 만들지 않았다 — 첫 분포를 본 자리에서 임계값을 지어내는 것이 10.4가 당한 일이다.

⑥ **축 배선은 두 계층으로 비대칭.** 모션 2종은 state의 순수함수라 항상 계산되므로 **tiebreak 입력**이고, 시각 2종(`unreadable_rate`/`mean_dsg_score`)은 유료 VLM 패스가 있어야 존재하므로 **기록 전용**(`ab_result`/Langfuse/UI)이며 승자결정 포함은 **13.4 소관**이다 — 존재 여부에 승자가 조용히 의존하면 함정이 된다. ⚠️ **모션 축은 판별기가 아니라 회귀 검출기다**: 착수 전 실측에서 coverage는 건강한 런에서 **1.0으로 포화**하고 repeat_ratio는 **0.0154(1/65, 유일한 반복이 `locked`→`locked` 씬 경계)**였다. 11.2가 씬 내부 반복을 이미 0으로 만들기 때문에 도달 가능 범위가 `[0, (씬수-1)/(샷수-1)]` = `[0, 0.123]`뿐이다. `legible` 죽은 축과 같은 형태이며, 이번에는 **구현 전에** 잡아 두 함수 독스트링에 수치째 적었다(후속 세션이 1.0을 고장으로 오독하는 것을 막는다).

⑦ **선행 결함 2건 해소.** tiebreak 이원화 → `_TIEBREAK_CHAIN` 테이블 하나로 통합해 1-1 스플릿에서 `EvaluationResult.winner`="tie"이면서 `ab_result.winner`="A"로 저장되던 불일치를 제거(의도된 변경 2건 기록: 집계가 점수합산→lexicographic, epsilon `>0.01` 통일). 순서는 `scene_count_match_rate`(쌍 대칭·미발동) → `cut_alignment_error`(11.4의 차단 해제, 의미 반전이 없는 유일한 타이밍 지표) → `motion_repeat_ratio` → `motion_archetype_coverage` → `subtitle_sync_error`(**강등** — 11.4 왜곡 경고는 삭제하지 않고 "우선순위 강등으로 완화, 제거 아님"으로 갱신) → `audio_duration_variance`. 전 키 `.get(key, default)`라 레거시 `ab_result` 행 재채점이 예외를 내지 않는다. 프론트 계약도 정정: 백엔드가 한 번도 쓴 적 없는 `llm_scores`/`rule_scores`·`scene_count_match`를 기대해 **실데이터의 모든 점수 셀이 `결과 없음`으로 렌더되던** 결함을 고쳤고, 이를 가리고 있던 픽스처를 백엔드 실출력 형태로 교체해 픽스처 자체가 회귀 가드가 되게 했다.

⑧ **부수 정정 1건.** Langfuse 룰메트릭 발행이 `.get(metric, 0)`이라 **측정하지 않은 `cut_alignment_error`를 0.0으로 발행**하고 있었다. 부재는 이제 키 생략이다 — `unreadable_rate = 0.0`은 "판독불가 프레임 없음"으로 읽히므로 아무도 보지 않은 런에 그 값을 publish할 수 없다. libcom 축은 8-16 backlog라 스텁·플래그·설정필드·예약키를 **만들지 않았다**.

⑪ **리뷰 반영(19건 수정, high 6)** — 전부 이 diff 안에서 해결(bad_spec 루프백 0, intent gap 0). 치명 6건: (a) `e2e/ab-comparison-accessibility.spec.ts`가 vitest 픽스처와 **똑같은** 스키마 버그를 갖고 있어 점수 셀이 전부 플레이스홀더인데도 단정이 통과 — 라이브 실행으로 확인(수정 전 그 파일 2건 실패 → 수정 후 목 테스트 통과, 남은 1건은 실파이프라인 구동 테스트로 수정 전후 동일 실패=선존). (b) `_load_visual_scores`가 최상위 list/str JSON을 그대로 반환해 `evaluate_ab` 스팬 **안에서** AttributeError → 이 파일에 의존하지도 않는 A/B 평가 전체가 죽는 경로. (c) tiebreak이 없는 키를 0.0으로 채워 **미측정 런이 그 단계를 이겼다**(lower-is-better 4종의 최선값이 0.0), 저장된 `null`엔 TypeError, NaN엔 조용히 무승부 → `_comparable`로 비교 불가 단계는 건너뜀. (d) `_cut_alignment_error`의 0.0이 '완벽 정렬'과 '잴 데이터 없음' 둘 다였다 — 11.4의 기록용일 때는 무해했으나 13.2가 체인 2순위 승자입력으로 올리자 **타이밍 데이터가 적은 런이 최우선 tiebreak을 이기는** 구조가 됐다 → `None` 반환·키 생략·단계 건너뜀. 왜곡을 옮기기만 하면 `subtitle_sync_error` 강등으로 없애려던 그 왜곡을 더 높은 우선순위에서 재현하는 셈이었다. (e) `about_body` **미검증** — `"true"`/`1`은 `is True`를 통과 못 해 몸 명제가 분모로 복귀하고, 필드가 **없으면** `_is_person`이 kind-only로 퇴화하는 동시에 `dsg_label_disagreements`가 0(=완벽 준수)으로 읽힌다 → 필수·bool 강제. 라이브 353개 전부 이미 준수하므로 **위 수치는 강화된 검증에서도 그대로 재현된다**(확인함). (f) `--dsg --limit 3`이 `visual_score.json`을 발행 — 하류는 3/66을 66/66과 구분할 수단이 없다(그냥 unreadable÷scored) → 완전 스윕에만 발행(+`--frames shots` 제외), 종료코드에 `dsg_errored` 반영. 그 외 medium 10: 시각 메트릭 타입·범위 검증(문자열 예외/1.0 초과 '비율' 발행), **epsilon을 키별로**(공유 0.01이 4개 단위를 가로질러 pct÷100의 0.6%p 차를 삼켰고 구 dataclass 경로와 실제로 불일치: 8.0% vs 8.6% → 구 점수합산 'A' / 공유-eps dict 'tie'), Langfuse 루프가 AD-10 try 안에서 `float(None)` → 이후 전 스코어(B 전량 포함) 유실 → 키 1개만 스킵, 명제 수 상한 12(무한 유료콜 방지), `dsg_qa_errors_n/total` 신설(API 실패가 mean_dsg를 내리는 것과 프레임이 실제로 못 보여주는 것을 구분 — 이번 런 0), 하네스가 HALT 판정 **전에** 산출물을 쓰던 순서 역전 + null frame 가드 + 종료코드가 판정문과 모순되지 않게, **모션 독스트링 2건이 자기 범위를 틀리게 적고 있었다** — `CAMERA_PREFERENCES`가 무드당 5종 중 **3종**만 노출하고 `_enforce_camera_variety`가 다중샷 씬에 2종 이상을 보장하므로 **0.2는 사실상 도달 불가**이고 단일 무드 건강 하한은 ~0.4–0.6이다(오독을 막으려 쓴 독스트링이 스스로 오독하고 있었다), 게다가 '판별력 없음'이라 써놓고 코드는 3·4순위 승자입력으로 쓰고 있어 coverage 0.2 스텝·repeat 1/65 스텝이 epsilon을 넘는다 → **승리의 의미를 '무드 다양성'·'씬 분할 방식'으로 정정**(모션 품질이 아니다), README §4의 헤드라인(distinct 5→9, 최대버킷 44%→27%)이 **경계 포화를 가리고 있었다 — 32/66(48%)이 0.0/1.0** → 수치 추가 + '귀속(attribution)에는 분명한 개선, 순위(ranking)에는 논쟁적'으로 정직화. low 3: `AbAxis`의 `total`(백엔드 미발행 키를 또 단정 — 고치려던 결함과 동일 부류) 제거, README §5의 '26인데 정확히 28로 재현' 자기모순 정정, §8 신설(런 이후 강화 내역 + 재현성 확인). defer 4: 골든셋 신규 열이 `aggregate_runs`에서 탈락해 **승격 판정 리포트에는 안 보임**(선존), `_motion_repeat_ratio`의 <2샷 0.0이 공허하게 최선값(I/O 계약 명시·현재 도달 불가·독스트링 기록), `determine_winner`의 `["A"]/["B"]` 직접 인덱싱(선존), UI가 방향·단위 표기 없이 8열을 나열(스펙이 명시적으로 범위 밖). 검증 재실행: **2668 passed / 0 failed**(신규 48건), ruff clean, 프론트 119 passed, Playwright 목 테스트 통과.

검증: **2642 passed / 0 failed**(신규 22건), ruff clean, 프론트 **119 passed**, 라이브 66프레임 0 error, `evaluate_ab` 소비 경로를 실제 산출물로 확인(`unreadable_rate` 0.1818 = 12/66, `mean_dsg_score` 0.5038). 재산출 1커맨드: `uv run python _bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py`.

### Story 13.3: ComfyUI 워크플로우 ops 하드닝 — 노드 ID 커플링 제거 + 재현성

리서치 Phase 2 #13. 현재 프롬프트 주입이 워크플로우 JSON의 **노드 ID 문자열 `"6"`/`"7"`에 하드코딩**돼 있다(PRD OQ-2가 그렇게 확정했고 `image.py _inject_prompts`가 그대로 구현) — 워크플로우를 편집해 노드가 재번호되면 조용히 엉뚱한 노드에 주입되거나 실패한다. 수정: **타이틀 기반 파라미터 매니페스트**(노드 `_meta.title`로 조회, ID 무관). 함께: ComfyUI-Manager 스냅샷 + 코어 버전을 git에 핀(현재 커스텀 노드 버전이 어디에도 기록 없음 — 8.7의 IC-Light 노드 부재 판단이 뒤집힌 것도 이 관측성 부재의 증상), **렌더 provenance**(워크플로우 해시/파라미터/시드/torch·ROCm 버전을 사이드카에 기록 — 11.1이 seed를 사이드카에 넣은 것의 확장). 8.6 매니페스트 체계와 동일 철학. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**CLOSED done 2026-08-14 (적대적 리뷰 완료 — 발견 17건 전부 수정, baseline c2f6b2f)** — `13-3-comfyui-workflow-ops-hardening.md`.

① **리졸버.** `comfyui_client.resolve_nodes(workflow, keys)` — `_meta.title` **정확일치**(부분일치 아님), 매니페스트 키 → 노드 ID. **ID 폴백은 의도적으로 없다**: 조용한 오주입이 이 스토리가 제거하는 결함이므로, 미해결 키는 *존재하는 타이틀 전체 목록과 함께* `ValueError`(UI에서 이름을 바꾼 운영자가 코드를 읽지 않고 고칠 수 있어야 한다), 중복 타이틀도 `ValueError`(모호성은 동전던지기가 아니라 결함). 부분일치가 왜 틀린지는 실물이 증명한다 — `layered_inspyrenet`에 `"Negative Prompt"`와 `"Background Inpaint Negative Prompt (entity exclusion)"`이 공존한다.

② **커플링 제거 범위.** image.py `"6"/"7"` → `ytflow:positive_prompt/negative_prompt`(로드 시 1회 즉시 해결, class_type 검사는 *해결된* 노드로 이동해 LoraLoader에 타이틀을 붙여넣어도 크게 실패). composite_harmonization 4개 — 스토리 원안의 2개가 아니라 **4개**였다: `GREY_MATTE`(20)/`LIGHT_SOURCE`(22)는 `workflow.get()`+isinstance 가드를 통과해 재번호 시 **예외 없이 카드 크기 조건화만 사라지는** 최악 경로였고, 이제 로드 시 함께 즉시 해결·검증된다. seed_location_plates 11개 — 링크 재배선 3곳(`[BLOCKOUT,0]`, t2i-fallback의 model/positive/negative) 포함. character_image_provider `_NEGATIVE_NODE_IDS = {"7","37_neg"}` 삭제 — 매니페스트 타이틀 우선 + **키워드 폴백 유지**(외부 워크플로와 `_default_workflow()`는 매니페스트를 갖지 않는다). 단 `_default_workflow()`의 노드 `"7"`은 *타이틀이 아예 없어* 폴백도 못 잡았으므로 매니페스트 타이틀을 부여했다 — 안 했으면 그 경로의 negative suffix가 로그 한 줄만 남기고 조용히 사라졌다.

③ **AD-1 충돌 1건, 스토리 전제와 다르게 해결.** 스토리는 "모든 호출자가 이미 comfyui_client를 import한다"고 적었으나 `composite_harmonization.py`는 **아니다** — `tests/domain/test_state_imports.py`가 pipeline→services import를 실제로 강제하고 그 legacy 허용목록은 "must not grow"다. 리졸버는 이미 주입되고 있는 duck-typed 클라이언트를 통해 전달된다(`_load_iclight_workflow(path, resolve_nodes)`). 허용목록은 자라지 않았고 새 파일도 없다.

④ **provenance(AC7).** `_done.json`에 `workflow_path` / `workflow_sha256`(**주입 전 템플릿**의 canonical 해시 — 제출 그래프 해시는 샷마다 달라 비교 불가) / `nodes`(해결된 맵) / `env_snapshot_sha256` / `comfyui`(버전·torch·device). `get_system_stats`는 `check_health`(`-> None`, 테스트 페이크 ~15개 의존)를 건드리지 않는 별도 함수, **런당 1회**, 실패는 null+로그로 스테이지를 절대 죽이지 않는다[AD-10]. mock/stock 경로는 워크플로를 로드하지 않으므로 null이 정직한 답. **AC8**: `_existing_complete_shot`의 비교 3키는 불변이며, provenance가 다른 사이드카가 여전히 캐시 히트임을 회귀 테스트로 고정했다(ComfyUI 업그레이드마다 155샷 재렌더를 막는 유일한 그물).

⑤ **환경 핀(AC6) — 실제로 캡처했다.** 스토리의 "이 머신엔 ComfyUI 없음, 연기 가능"은 **거짓**이었다. `data/comfyui/env-snapshot.json`은 이 호스트에서 실캡처(`./venv/bin/python custom_nodes/ComfyUI-Manager/cm-cli.py save-snapshot --output <repo>/data/comfyui/env-snapshot.json --full-snapshot` — CLI는 ComfyUI 자체 venv의 typer가 필요하다): ComfyUI 코어 `f350a84`, 커스텀노드 9종(git 7 + registry 2), pip 179종. `data/comfyui/README.md`에 갱신 명령·갱신 시점·provenance 연결·복원 미자동화 이유 기록.

⑥ **라이브 게이트 통과.** 동일 시드 3렌더, 전부 출하 코드 경로(`_load_workflow` → `_inject_prompts` → `submit_and_fetch`): 프롬프트 A(corridor) vs B(autopsy) **RMS 72.78**(주입이 샘플러에 도달), A vs **전 노드 ID +700 재번호 그래프** C **RMS 0.00 — 픽셀 동일**. 위치 비의존성을 논증이 아니라 측정으로 확정했다. 산출물: `13-3-live-validation/`(판정 그리드 + provenance.json + 재산출 2스크립트).

⑦ **데이터 테스트.** `test_workflow_definitions.py`에 소비자별 키 표를 추가 — 커밋된 JSON이 *그 소비자가 실제로 조회하는 키*를 해결하는지 단정한다. ComfyUI UI 재익스포트를 잡는 유일한 그물이며, 키 목록은 소비자 모듈에서 직접 읽어 표가 코드와 어긋날 수 없다.

⑧ **알려진 잔여 1건.** `_bmad-output/implementation-artifacts/10-2·10-4·10-4b-live-validation/`의 probe 스크립트 5개가 옛 `_load_workflow`/`_inject_prompts` 시그니처를 고정하고 있어 그대로는 재실행되지 않는다. 날짜가 박힌 실행 기록이라 의도적으로 손대지 않았다 — 재실행이 필요하면 반환 튜플과 `nodes` 인자만 맞추면 된다.

검증: **2813 passed / 1 skipped**(신규 31건, 기준선 2782/1), `ruff check src/ scripts/ tests/` clean. 프론트 무변경.

### Story 13.4: A/B 승격 게이트 해제 — 품질튜닝 국면 진입

2026-08-03 DEV MODE 전환(품질 게이팅 OFF, `PROMPT_POLICY.md` 배너)의 되돌림 스토리. 파이프라인이 완성되고 품질튜닝 국면에 들어갈 때: `PROMPT_POLICY.md` Rules 3/4의 SUSPENDED 해제, 6.12의 `YTFLOW_ALLOW_AB_GATE` 동결 해제, 6.10 median 게이트로 보류 후보 재평가, 13.2의 시각 축을 게이트에 포함. 6.12와 이 스토리의 관계: 6.12는 "동결한다", 13.4는 "해제한다" — 별개 스토리로 두는 이유는 해제 조건 판단(파이프라인 완성 정의)이 별도 의사결정이기 때문. **착수 조건**: Epic 8/11의 GPU 스토리가 닫히고 E2E 산출물이 Jay 기준을 통과한 뒤. (draft — 상세 스토리 파일은 create-story로 별도 생성)

**Epic 12 회고 반영(2026-08-08)**: 12.2 결과는 Gemini가 한국어 문장과 Epic 4 judge를 함께 소유하므로 self-preference bias를 제거하지 않고 이동시켰다. 13.4가 promotion 권한을 복원하기 전, Gemini judge 유지 또는 DeepSeek judge 분리 중 하나를 실측 근거와 함께 명시적으로 결정해야 한다. 결정 없이 게이트 권한만 복원하는 것은 허용하지 않는다.

### Story 13.5: depth 그래프 노드ID 커플링 제거 (backlog, 2026-08-15 초안)

13.3이 6개 커플링 사이트 중 4개만 전환했고, 남은 하나가 가장 자주 도는 경로다. `compositing_service.py`가 depth 그래프를 `DEPTH_IMAGE_NODE="1"`/`DEPTH_MODEL_NODE="2"`로 주소하고 `depth_placement_enabled`는 기본 True라 **생성 배경마다** 실행된다. 노드 `"1"`은 LoadImage 검사로 크게 실패하지만 `"2"`는 "`inputs` dict 있음"만 봐서 재번호 시 `ckpt_name`/`resolution`이 조용히 엉뚱한 노드로 간다 — 13.3이 harmonization에서 찾은 grey_matte/light_source와 같은 형태. 놓친 이유도 기록해 둘 값어치가 있다: 13.3의 범위 조사가 `workflow["N"]` 리터럴만 grep해서 **상수 뒤에 숨은** 사이트를 못 봤고, 그 결과가 "나머지는 class_type 스캔"이라고 *검증됨*으로 기록됐다. 파일: `13-5-depth-node-id-decoupling.md`.

### Story 13.6: 결정과 출하 기본값의 표류를 드러낸다 (backlog, 2026-08-15 초안)

2026-08-15 Jay가 "결정했는데 적용이 안 된 것 같다"고 지목한 4건 중 3건이 전부 같은 형태였다 — 기능은 구현·리뷰·머지까지 끝났고 **아무도 안 뒤집은 기본값 뒤에 앉아 있었다**: 떨림(`camera_noise_enabled=True`), LLM 재합성(`shot_recompose_enabled=False`), 클론 음성(`.env`에 `false`인데 음성 ID는 5.24에서 이미 등록됨). 승인된 결정이 출하물에 없는 것은 게이트가 초록이고 경고가 비어 있는 채로 일어나는 **조용한 무효화**이며, 13.1이 다룬 조용한 강등의 한 층 위다. 결정 담지 설정을 운영 노브와 구분해 선언하고, 결정값과 실효값의 차이 + 값의 출처(`.env` vs 코드 기본값)를 한 커맨드로 보고한다. 게이트가 아니라 리포트다 — off인 데는 기록된 이유가 있는 것들이 있다. 플래그 플립 자체는 각 기능 스토리 소관. 파일: `13-6-shipping-defaults-match-decisions.md`.

## Epic 14: 시각 자산 층 — 큐레이션된 세트로 전환 (배경·D급·오브젝트)

**2026-08-17 발의(Jay)**, run `4b35c0ed` (SCP-049, 3:20) 시청 판정 직후. 판정 원문 7항목:

> 1. 접지는 어느정도 된 것 같음. 2. 원근감이 제대로 안되는듯. 3. 배경이 일관적이지 못함. 이상한것도 너무 많고, 이거 각잡아서 제대로 배경 셋, D 계급 셋, 오브젝트 셋을 미리 만들어두는게 좋을 것 같음. 4. 말이 아직 너무 빠른것 같음. 지금이 1.2라면 1.1 정도로 줄이도록 5. 아직도 배경에 사람이 그려져 있는 배경이 있음. 6. 나레이션에 대한 적절한 배경 + 캐릭터 포즈가 제대로 되어야함. 7. 화풍 유지 안됨.

**①은 닫혔다** — 10.1e가 recompose를 기본값으로 올린 것이 접지 문제의 답이었고 Jay가 확인했다. **④는 스토리가 아니라 결정**이라 즉시 적용했다(`qwen_tts_speed` 1.2 → 1.1, 코드 기본값과 `.env` 핀 동시 — 한쪽만 고치면 `.env`가 이겨서 출하되지 않는다).

**남은 ②③⑤⑥⑦은 한 덩어리다**, 그리고 ③에 Jay가 적은 처방이 그 덩어리의 답이다: **샷마다 생성하는 대신 승인된 자산 세트에서 고른다.** 일관성(③⑦)은 후보 집합을 사람이 승인하면 구조적으로 확보되고, 배경 인구(⑤)는 승인 시점에 한 번 걸러지며, 원근/어포던스(②)와 나레이션 정합(⑥)은 생성 시점에 추측할 수 없지만 **자산에 부착된 메타데이터로는 질의할 수 있다**.

**이 에픽은 처음이 아니다 — 8.17의 미완 화해다.** `config.py`의 `stock_plate_substitution_enabled` 주석이 이 에픽을 이미 정의해 두고 있다: *"Stays off until a plate-vs-prompt reconciliation story makes plate reuse per-shot and prompt-aware."* 8.17은 플레이트 재사용을 시도했다가 꺼졌는데, 이유가 재사용 자체가 아니라 **키가 `scene_num`이었고 샷의 `image_prompt`를 통째로 버렸다는 것**이다(실측: 배경 155 → 41종, 씬 5의 격리실이 21샷 → 1장). 그리고 `project_stock-plate-reuse-is-intent`는 **재사용이 의도**이며 다양성 붕괴를 "회귀"로 고치지 말라고 기록한다. 즉 목표는 재사용을 되돌리는 것이 아니라 **샷 단위·프롬프트 인식 재사용**이다. Epic 8의 8.5(스톡 로케이션 플레이트)·8.6(자산 라이브러리 관리)·8.17(플레이트 데이터 생성)·8.19(임베딩 검색)가 이 에픽의 기반이고, 새로 만드는 것이 아니라 **잇는다**.

**GPU 비중**: 자산 세트를 채우는 일회성 생성은 GPU를 크게 쓰지만 **런당 비용은 내려간다**(샷마다 배경을 새로 만들지 않으므로). 14.2·14.5의 게이트 로직과 14.7은 비-GPU.

### 실측 근거 (run 4b35c0ed, 이 에픽의 출발 데이터)

- **recompose 33/43샷 발화, 실패 0, 프리플라이트 통과** — 프로덕션 첫 완주. ①이 닫힌 근거.
- **배경 인구 오염**: 무인 가드를 `2`로 켜서 재생성하자 오염 3장 → 0장(`S00203` 창살 뒤 인물, `S00400` 전술복 인물, `S00301` 책상 앞 인물 전부 제거), `never screened` 43 → 0. **가드가 못 잡은 1장은 `S00201`의 액자 속 애니풍 초상화** — 탐지기가 "방 안의 사람"으로 세지 않은 것은 중복 인물 방지 목적에선 옳지만, ⑤의 실체는 그것만이 아니다(`gotcha_person-token-regex-is-unusable-on-image-prompt`의 "그림 속 인물" 구분이 여기서 갈렸다). `undecidable verdict` 1건도 있다.
- **가드는 `.env` 핀 상태다** — `background_person_guard_attempts` 코드 기본값이 여전히 `0`이고, 이번 런은 `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS=2`로 돌았다. 이것은 `gotcha_a-decision-that-only-reaches-env-never-ships`이며 13.6의 소관이다.
- **선언된 `camera_angle`과 렌더 결과가 어긋난다**: `S00100`은 `medium` 선언인데 유리 바닥을 내려다보는 부감으로 렌더됐고, recompose는 그 위에 눈높이 정면 인물을 그렸다 — ②의 기계적 원인. `image_prompt` 본문(예: `S00803`의 *"low-angle shot looking up from the floor"*)이 앵글 필드를 덮어쓴다. **판정 도구가 이미 있다**: `scripts/assess_plate_affordance.py`, 주석에 *"the known S00104-class recompose failure predictor"*.
  - **⚠️ 2026-08-21 반증(Story 14.0 §4-4)**: 뒷문장의 *"본문이 앵글 필드를 덮어쓴다"* 는 **거짓**이다. 이 런 43샷 전부에서 필드와 `image_prompt` 슬롯-1이 (어휘 버킷 단위로) 일치한다(불일치 0). 인용된 두 샷 모두 일치다 — `S00100`은 필드 `medium` + 본문 첫 두 단어 `"medium shot"`, `S00803`은 필드 `low-angle` + 본문 `"low-angle shot looking up from the floor"`. 필드는 **배경 렌더러의 프롬프트에는** 도달하지 않지만(`image.py:212`는 `shot["image_prompt"]`만 대입) **렌더 무관은 아니다** — `character_service.py:1500`이 이 값을 앵글 선택 카탈로그에 실어 `_select_entity_angles`가 고른 `angle_*_path` 카드 PNG가 프레임에 합성된다. **앞문장(선언과 렌더 결과가 어긋난다)은 여전히 참**이고, 개입 지점은 텍스트 내부다: `S00100`은 119단어 중 앵글이 앞 2단어이고 나머지 117단어가 바닥·배수구·천장 형광등을 서술한다. 그 안에서 무엇이 프레이밍을 정하는지는 **n=1로 미확정**이며 후보 둘이 동등하다 — (a) 내용 질량, (b) 조명 어휘(`lit harshly from above`/`from above`/`ceiling-mounted`, 이 런에서 셋을 동시에 가진 유일한 샷이 `S00100`)의 앵글 오독. 근거·재산출: `implementation-artifacts/14-0-angle-conflict/`.
- **화풍 이탈 실측**: 43장 중 네온/사이버펑크 계열 약 6장(`S00501` 마젠타·시안, `S00301`·`S00605`·`S00701` 형광 녹색, `S00105` 핑크·블루, `S00403` 노란 마킹), 완전 이질 화풍 1장(`S00303` 플랫 아이소메트릭 스케치). ⑦.
- **recompose 결과물의 화풍 격차**: 인물은 검은 외곽선 셀셰이딩, 플레이트는 페인터리 렌더. recompose는 *다시 그려서* 이걸 없애는 기법인데 카드 화풍을 너무 충실히 보존했다. 10.1의 "찢어붙인 듯"이 남아 있다. 또 한 프레임 안에서 접지가 불일치한다(`S00100`: 049는 접지 그림자, D계급은 없음).
- **`cast_card_fallback` 4건**(`STOCK-researcher`×2, `STOCK-d-class`, `SCP-049-2` — 사유 `asset` / `asset+pose_hint`) + **`special_pose_cap_exceeded` 1건**. ③의 "D급 셋" 요구가 여기서 실증된다. 10.8이 *"프롬프트 수정은 비소급"* 이라고 남긴 그 상태다.
- **길이는 개선됐다**: 나레이션 961자 → 1,411자(+47%), 영상 2:17 → 3:20. 12.6이 작동했다. ④의 속도 조정은 이 위에서 내린 판정이다.

### Story 14.0: 리서치 게이트 — ②⑤⑥은 자료 없이 착수하지 않는다 (선행 필수)

**Jay 지시(2026-08-17)**: *"2,5,6은 옛날부터 계속 얘기해도 개선이 안되는것 같은데? 왜그런거임?
이거 관련해서 논문을 찾아보던 트랜드를 찾아보던해서, epic story 에 제발 자료먼저 모으고
진행하도록 해줘"*. **14.2·14.3·14.5는 이 스토리가 닫히기 전에 착수하지 않는다.**

1차 수집 완료: `planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md`.
그 문서의 진단이 세 항목의 원인이 **서로 다르다**는 것이다 — ②는 한 번도 작업된 적이 없고(접지
스토리들이 수직 좌표만 쟀다: `ground_y` 43회, 시점 일치 0줄), ⑤는 고쳐졌으나 기본값 `0`으로
출하돼 15일간 안 돌았고, ⑥은 세 라운드(10.4/10.4b/13.2)가 전부 계측기에 쓰이고 **생성기를 바꾼
라운드가 0회**다. 그래서 처방도 서로 달라야 한다.

문헌 1차 소득: ②는 **pose–scene mismatch**라는 이름과 처방 계열이 있다(Kulal CVPR 2023
*Putting People in Their Place* — 씬이 포즈를 결정, InsHuman — 그 계열의 정체성 상실 약점,
MV-CoLight/DAEdit — 조명·그림자·깊이 일관성). ⑥은 **catastrophic neglect**이고 개입 지점이 둘로
갈린다: 샘플러 내부(Attend-and-Excite, Patcher +10.1~16.3%p) vs 프롬프트 재작성(FRAP,
VisualPrompter, GenPilot, Seeing-is-Believing) — **후자가 우리가 한 번도 안 건드린 층**이다.
⑤는 문헌보다 출하 규율 문제이고, **부정 프롬프트는 이 축의 해법이 아님이 두 번 실증됐다**
(오늘 런의 negative_prompt에 사람 토큰이 이미 있는데도 `S00201`에 액자 인물이 그려졌다).

**이 스토리가 닫히는 조건** — 위 문서 §4의 미해결 5건에 답한다:
(1) Kulal/InsHuman 계열의 re-pose와 우리 승인 카드 정체성 제약의 화해,
(2) 어포던스를 런타임 채점 vs 자산 메타데이터 중 무엇으로 둘지,
(3) Patcher/Attend-and-Excite가 우리 ComfyUI SDXL 워크플로에서 구현 가능한지(커스텀 노드 필요 여부),
(4) **`camera_angle` 필드와 `image_prompt` 본문 앵글 서술의 충돌** — 문헌이 아니라 우리 조립
버그일 수 있고 ②의 가장 값싼 절반이다(코드 읽기, GPU 0). **먼저 확인**,
  → **✅ 닫힘 (2026-08-21, 반증). 충돌은 없었다.** run `4b35c0ed` 43샷 실측: 필드↔슬롯-1 일치 43,
  불일치 0, 판정불가 0(어휘 버킷 단위 일치). 두 채널을 **같은 LLM 턴이 함께 쓴다**는 것은 사실이나
  (`visual_breakdown.md:72` 슬롯-1 + `:215` 필드가 한 응답 요구사항) 그것이 일치를 **보장하지는
  않는다** — `:72`가 코칭하는 `dutch angle`·`extreme close-up`·`static wide` 등은 `camera_type` 7값에
  대응물이 없고, 슬롯-1 머리 43개 중 14개가 이미 버킷 밖 수식어를 달고 있다. **43/43은 경험적
  결과이고 구조적 보장이 아니다**(런마다 GPU 0으로 재측정 가능). 리컨실러는 만들지 않았다 — 할 일이
  0건인 코드다. 필드는 배경 렌더러 프롬프트에는 안 들어가지만 **캐스트 카드 앵글 선택
  (`character_service.py:1500` → `angle_*_path` PNG 합성)에는 들어가므로 렌더 무관이 아니다.**
  개입 지점은 **프롬프트 텍스트 내부**로 확정됐고 14.2 소관으로 인계했다 — 단, 그 안의 메커니즘은
  n=1로 미확정이고 (a) 내용 질량 / (b) 조명 어휘 오독 두 가설이 동등하게 열려 있다.
  부수로 조립 결함 2건은 고쳤다(무검증 `camera_angle` → 어휘 정규화, 대가는 어휘 밖 값이 앵글 선택
  카탈로그에 `""`로 도착하는 것 — 이 런 발생 0건; `_fallback_prompt`의 `"static wide shot"`
  하드코딩과 LLM 앵글의 확정 어긋남). GPU 0.
  **(4)이 닫힌 것이 Story 14.0이 닫힌 것은 아니다** — (1)(2)(3)(5)는 미해결이고 14.2/14.3/14.5의
  하드 블로커도 그대로다. 이 항목을 언블록으로 읽지 말 것.
  근거·재산출 스크립트: `implementation-artifacts/14-0-angle-conflict/`.
(5) ⑥ 계측기 검증 — `dsg_score`↔`readable` 무상관(0.0263)과 판독불가 프레임의 높은 DSG를
이해하기 전에는 어떤 축도 게이트로 쓰지 않는다(13.2의 명시 제약).

**✅ 5건 전부 닫힘 (2026-08-21~22) — 이 스토리는 done이고 14.2/14.3/14.5 게이트가 해제된다.**
(4)는 반증(43/43 일치, `implementation-artifacts/14-0-angle-conflict/`, 커밋 fb72654),
(3)(5)는 실측, (1)(2)는 Jay 결정 — 근거·재산출:
`implementation-artifacts/14-0-research-gate-closure/`. 요약:
- **(1) 포즈를 자산 축으로 둔다** — 신규 삽입 모델(Kulal/InsHuman) 미도입. 전제가 이미 바뀌어
  있었다: recompose가 기본값 ON(`config.py:468`)이고 인물을 다시 그린다(33/43샷 발화), 그래서
  질문은 "재포즈 도입"이 아니라 "카드에서 얼마나 벗어나도 되는가"였다. 필요한 포즈의 **승인 카드를
  늘린다**(14.6 소관). 10.5 openpose·8.4 특수 포즈 카드가 이미 기구다. 정체성 하한은 유지 — 14.3은
  이것을 느슨하게 하는 방식으로 화풍 격차를 풀지 않는다.
- **(2) 자산 메타데이터 + 자유생성 샷만 런타임, 판정 스키마는 하나.** run 4b35c0ed는 `location_key`
  31샷 / 자유생성 12샷이라 어느 한쪽만으로는 구멍이 난다. **착수는 14.1 다음** — 세트가 없으면
  붙일 자산이 없어 런타임 전용으로 강제되고, 먼저 하면 런당 VLM 43콜 코드를 쓰고 버린다.
- **(3) 샘플러 내부 개입은 커스텀 노드 신설이 필요하고 미설치다.** 설치 커스텀 노드 10종·코어
  어디에도 A&E 구현이 없다(훅 `set_model_attn2_patch`만 있다). → ⑥의 개입은 **프롬프트 재작성**
  계열로 간다(비-GPU, 렌더 전 텍스트 스크리닝 가능).
- **(5) 계측기는 죽은 축이 아니라 뒤집힌 축이었다.** `state` 하위 축이 ρ=−0.174(판독불가 0.625 vs
  판독가능 0.390)로 집계보다 **더 강하게** 반전돼 있고, 집계 ≈0은 상수축(`place` 79% yes)과 반전축의
  상쇄다. 원인은 프롬프트에서 도출한 질문이 **유도질문**이고 판독불가 프레임에는 반박할 내용이
  없다는 것 — 애매함은 관대하다. **그러므로 하위 축도 게이트로 쓸 수 없고, 14.5의 판정은 블라인드여야
  한다.** 분모 2~3(32/66이 0.0·1.0)과 사건 축이 사라지는 13/66도 가중 요인. 네 번째 계측기 라운드는
  승인하지 않는다 — 다음 라운드는 생성기다.

**규율 둘**: 프롬프트 변경은 렌더 전 텍스트로 스크리닝한다
(`gotcha_screen-a-prompt-change-before-you-render-it` — 109초가 ~6 GPU-시간을 절약했다).
논문의 VRAM·해상도 수치를 이 박스로 옮길 때는 버전·용도를 확인한다
(`gotcha_qwen-image-edit-rejection-was-version-specific` — 같은 오용 3회 전례). 파일: `14-0-visual-asset-research-gate.md`. (draft)

### Story 14.1: 승인된 배경 플레이트 세트 — 샷 단위·프롬프트 인식 재사용

`config.py:297-303`이 이름만 남겨둔 "plate-vs-prompt reconciliation" 스토리. 큐레이션된 플레이트 세트를 만들고, 샷 배정을 **`scene_num` 키가 아니라 샷의 `image_prompt`/`location_key`와의 정합**으로 결정한다. ~~8.19의 임베딩 검색층이 후보 랭킹의 기반.~~ **⚠️ 반증됨(2026-08-25, 14.1 착수 시 확인): 그런 층은 존재한 적이 없다.** 8.19 는 Stage 2 를 **명시적으로 기각**했고(Completion Notes: *"no `SequenceMatcher`, no threshold and no score therefore exist"*, AC12/AC13 검증란 *"No `asset_retrieval_service.py`"*), `src/yt_flow/services/asset_retrieval_service.py` 는 오늘도 없으며 `pyproject.toml`·`config.py` 에 임베딩 의존성이 0 개다(재확인 완료). 8.19 가 실제로 출하한 것은 결정론적 마커 억제 `_suppress_cast_on_no_figure_framing` 하나이고, 그 함수의 어휘 확장은 14.2 가 실측으로 **금지**했다. **후보 랭킹의 실제 기반은 측정된 플레이트 메타데이터다** — 시점(사전등록 `y_h` 투영기하, 프롬프트 비열람), 설 자리(`vision_check.plate_has_standing_room`, 14.2 와 프롬프트·봉투 공유), 그림 속 인물(라벨러 신설 축). 매칭은 점수·임계값이 아니라 `camera_angle → viewpoint` **정합 맵 룩업**이고, 맞는 후보가 없으면 생성으로 폴백한다. 원문을 남겨 두는 이유는 `gotcha_recorded-root-cause-can-be-inverted` — 거짓 전제는 한 곳만 고치면 다시 인용된다. 승인 게이트를 통과한 플레이트만 세트에 들어가므로 ③⑤⑦이 승인 시점에 한 번 걸러진다. **다양성 붕괴를 되돌리는 스토리가 아니다** — `project_stock-plate-reuse-is-intent`대로 재사용은 목표이고, 부족하면 세트를 늘려서 해결하며 한 장에서 변형을 파생하지 않는다. 8.17을 켤 조건이 무엇인지 이 스토리가 정의한다. **⚠️ 2026-08-22 14.4가 소관을 하나 인계했다: 액자·모니터·포스터·해부도·조각상 **안**의 인물("그림 속 인물")은 이 스토리의 승인 게이트 소관이다.** 런타임 가드 확장은 기각됐다(이유는 14.4 항목) — 액자 속 인물은 플레이트 단위 속성이고 사람이 한 번 보면 판정되며, `vision_check.CHECK_PROMPT`의 FALSE 목록(diagram/poster/statue/mannequin/skull/painting)은 오류가 아니라 **다른 질문에 대한 정답**이다(가드는 "합성 카드가 프레임 속 몸과 겹치는가"만 묻는다). 승인 기준에 이 축을 넣어야 한다. **단, 자유생성 샷(이 런 12/43)은 승인 게이트에 도달하지 않으므로 세트가 그 샷들을 덮기 전까지는 감수 리스크다** — 그 갭을 닫는 것도 이 스토리 몫이다. 파일: `14-1-approved-plate-sets.md`.

**✅ 2026-08-29 CLOSED done (e8b8d2f) — 배정 규칙과 자산 메타데이터는 닫혔고 플래그는 여전히 OFF다.** 8.17의 `scene_num` 키잉을 순수 `_select_plate`로 교체했다(필터 순서 = 프레이밍 → 메타데이터 → 시점 → 인물 → 어포던스, 맞는 후보가 없으면 **생성 폴백**). 승인 플레이트 42장에 시점·`standing_room`·`depicts_person`이 자산 메타데이터로 붙어 **§4-2 결정의 메타데이터 절반**이 닫혔다(런타임 절반은 14.2가 출하). 플레이트당 1회 측정이므로 런당 비용은 0이다. **`stock_plate_substitution_enabled`는 `False` 그대로** — 이 스토리는 켤 **조건**만 실측으로 정의했고 ~~셋 다 안 닫혔다: (a) 사전등록 커버리지, (b) Jay의 E2E 시청 판정, (c) **릴라이트 결합 수정**(아래).~~ **(a)·(b) 둘 다 안 닫혔다** — **⚠️ 2026-08-29 Story 14.3 정정 — 이 조건은 성립하지 않는다.** 문제의 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고, 그 함수는 `video.py`가 `composite_harmonization_tier >= 3`에서만 호출한다. 출하 기본값은 **1**이고 tier 3(IC-Light)은 10.1b가 시청 판정으로 기각했다. **그 한 줄로 도달 불가는 성립하고, 그 뒤에 아무것도 필요하지 않다.** ⚠️ 이 정정의 초판은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*이라는 두 번째 다리를 붙였는데, **그것은 불변식이 아니라 run `4b35c0ed`의 관찰이다** — `recompose_run_shots`의 `remaining.pop(shot_key)`는 성공·재진입 분기에서만 실행되므로 `failed`(스윕 중 ComfyUI 사망, 플레이트 판독 실패)나 `skipped`(`card_key`가 `CARD_LOOKS` 밖)로 세어진 샷은 cast를 그대로 들고 오버레이/하모나이제이션 체인에 **진입한다**. 실패가 하나라도 나는 런에서는 0/43이 아니다. **0/43은 관찰로 강등하고, 반증은 `tier >= 3` 하나로 선다.** 이 프로젝트에서 이 형태(기록된 원인이 뒤집힘)는 이번이 **세 번째**이고, 세 번째는 **정정하는 문서 자신이 심은 과장**이었다 — `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. **이 인계 항목의 두 번째 발화 조건 정정이다**, 그래서 원문을 지우지 않고 취소선으로 남긴다(`gotcha_recorded-root-cause-can-be-inverted`). 결합 자체는 **여전히 결함이고 여전히 미수정**이며 tier 3을 켜면 발화한다 — 인계는 유지되고, 끊긴 것은 플래그 해제와의 결합이다. 고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`. 근거: `14-3-art-style-contract/report.md` §6. **실측**(재산출 `14-1-approved-plate-sets/replay_coverage.py 4b35c0ed`): 42장 = EYE 33 / HIGH 4 / LOW 5, `standing_room` 40 true, `depicts_person` 0 true. run `4b35c0ed` 31샷 → **정합 17 · `unservable_framing` 7**(close-up 6 + POV 1, **설계상 영구 폴백** — 방 플레이트는 물체 클로즈업이나 천장 POV를 서빙할 수 없다) **· `no_viewpoint_match` 7** → servable 24 중 **17/24 = 70.8%**. 사전등록 C1 FAIL(5/10) · C2 PASS · C3 FAIL. **⚠️ 이 항목의 전제 하나가 거짓이었다**: 위 본문의 *"8.19의 임베딩 검색층이 후보 랭킹의 기반"* 은 **반증됐다**(문장에 취소선으로 표기) — 8.19는 Stage 2를 명시적으로 기각했고 `asset_retrieval_service.py`도 매처도 임계값도 점수도 존재한 적이 없다. 같은 전제가 `epic-14-context.md`에도 심겨 있어 **두 곳 다** 정정했다(`gotcha_recorded-root-cause-can-be-inverted`). **⚠️ `VARIANT_CAMERAS` 선언은 절반만 지켜졌다** — 선언 vs 실측이 variant `a` 13/14인데 **`b`는 2/14**(선언 LOW, 실측 EYE 9 · HIGH 3)다. **증설 배치를 "`b`를 더 뽑자"로 계획하지 마라.** **적대적 리뷰가 이 스토리 자신의 산출물을 두 번 반증했다**(bad_spec 4, high 2): **(A) 선택기가 인물 있는 플레이트를 서빙할 수 있었다** — 플레이트 경로는 10.2/14.4 사람 가드를 `continue`로 **건너뛰는데**, 라벨러 자신이 `has_person: true`라고 적어둔 `entrance-checkpoint/b`(경비 부스에 인물 2, 그럼에도 `approved`)가 후보에서 안 걸러졌다. 14.4에서 **인계받은 바로 그 부류**를 측정만 하고 강제하지 않은 것이다 → **D1**(배정 거부는 승인 철회가 아니다; 자산은 `approved`로 두고 이 샷에 쓰지 않을 뿐). **(B) `marginal`이 사전등록 ±0.05가 아니라 ±0.03으로 찍혀 있었다** — 다시 찍으니 11 → **20행**이 되고 **부족분 결론이 "최소 5장 렌더"에서 "최소 2장(LOW) + 3셀 재판독(HIGH, GPU 0)"으로 바뀌었다**. HIGH 3셀이 리포트 자신이 선언한 측정 노이즈 안에 들어 있었다. 사전등록은 고치지 않고 **CSV를 사전등록에 맞췄다**(`gotcha_a-preregistered-band-must-be-honored-when-stamping-data`). 그 외 bad_spec: **D2** 어포던스 하드 필터가 노브를 무시해 14.2의 **유일한 오탐 복구 경로**(노브 내리기)를 무효화했고 노브 OFF에서 "측정된 나쁨을 거부하고 **판정 자체가 없는** 생성 프레임을 받는" 역전을 만들었다 / **D3** 타이브레이크 digest 키가 cast 필터 **이전** 풀 기준이라 한 씬에서 cast 샷과 cast-free 샷이 다른 배경을 받을 수 있었다 / **D4** resume이 사이드카에 적힌 자산 판정을 안 읽고 전부 `unjudged`로 셌다. **⚠️ 릴라이트 결합의 발화 조건이 정정됐다 — 14.3이 알아야 한다**: `composite_harmonization.py`의 페어 키 `(card_variant, location_key)`에는 **씬 성분이 없어** 결합은 씬 스코프가 아니라 **런 전체**다. ~~그리고 이 런에서 **이미 발화한다**.~~ "14.1 이전에는 씬당 플레이트가 1장이라 무해했다"는 기록은 거짓이다. ~~부족분을 렌더하면 9씬 중 4씬이 한 키에 두 플레이트를 갖게 되어 **스토리 자신의 해제 조건이 이 결함을 격발한다**.~~ **14.3이 발화 조건을 다시 반증했다(2026-08-29)** — **⚠️ 2026-08-29 Story 14.3 정정 — 이 조건은 성립하지 않는다.** 문제의 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고, 그 함수는 `video.py`가 `composite_harmonization_tier >= 3`에서만 호출한다. 출하 기본값은 **1**이고 tier 3(IC-Light)은 10.1b가 시청 판정으로 기각했다. **그 한 줄로 도달 불가는 성립하고, 그 뒤에 아무것도 필요하지 않다.** ⚠️ 이 정정의 초판은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*이라는 두 번째 다리를 붙였는데, **그것은 불변식이 아니라 run `4b35c0ed`의 관찰이다** — `recompose_run_shots`의 `remaining.pop(shot_key)`는 성공·재진입 분기에서만 실행되므로 `failed`(스윕 중 ComfyUI 사망, 플레이트 판독 실패)나 `skipped`(`card_key`가 `CARD_LOOKS` 밖)로 세어진 샷은 cast를 그대로 들고 오버레이/하모나이제이션 체인에 **진입한다**. 실패가 하나라도 나는 런에서는 0/43이 아니다. **0/43은 관찰로 강등하고, 반증은 `tier >= 3` 하나로 선다.** 이 프로젝트에서 이 형태(기록된 원인이 뒤집힘)는 이번이 **세 번째**이고, 세 번째는 **정정하는 문서 자신이 심은 과장**이었다 — `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. **이 인계 항목의 두 번째 발화 조건 정정이다**, 그래서 원문을 지우지 않고 취소선으로 남긴다(`gotcha_recorded-root-cause-can-be-inverted`). 결합 자체는 **여전히 결함이고 여전히 미수정**이며 tier 3을 켜면 발화한다 — 인계는 유지되고, 끊긴 것은 플래그 해제와의 결합이다. 고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`. 근거: `14-3-art-style-contract/report.md` §6. **미주장**: **픽셀 판정 0회** — 배경 정합의 시청 판정은 **E2E iteration 5** 몫이고 그 런 없이 "고쳤다"는 문장은 없다 / **리뷰 패스 2는 Jay가 중단**해 루프 1의 수정들이 독립 검토를 못 받았다 → `followup_review_recommended: true` / `has_person` 재판정이 `plate_meta`에 없다(`--commit` 미재실행 — 84 VLM 콜 + 대체 불가한 측정 블록 덮어쓰기이므로, D1은 2026-08-02 라벨에 의존한다) / **승인 42장 중 14장이 라벨 `decision=draft`인 채 `approved`**이고 그중 3장은 커버된 셀에 있다 — 승인 철회는 하지 않았다(사람 판단, 리포트 §8이 대기 목록) / **플레이트 경로에 런타임 사람 가드가 없다**(D1은 라벨 기반 부분 완화, `deferred-work.md` 등재). 검증: 3329 passed / 1 failed(`test_render_pose_guides.py` PNG SHA 핀 — baseline worktree에서 동일 실패로 **기존 결함 확인**) · ruff clean · `report_decision_drift.py` exit 0 · `prompts/` 무변경. 근거·재산출: `implementation-artifacts/14-1-approved-plate-sets/`. (done)

### Story 14.2: 플레이트 어포던스 게이트 — 인물이 설 수 있는 플레이트만 캐스트 샷에

②의 직접 처방. `scripts/assess_plate_affordance.py`를 게이트로 승격해, cast가 붙은 샷에는 **서 있는 인물을 놓을 지면과 눈높이 시점이 있는** 플레이트만 배정한다. 부감 바닥·천장 앙각·배수구 클로즈업은 cast-free 샷으로 돌린다. ~~부수 결함으로 **`camera_angle` 필드와 `image_prompt` 본문의 앵글 서술이 충돌하는 문제**를 같이 다룬다(본문이 필드를 덮어쓴다 — `S00100` medium 선언 vs 부감 렌더).~~ **⚠️ 반증됨(14.0 §4-4, 2026-08-21): 충돌 0건 / 43샷 일치 43.** 그러므로 이 스토리는 필드↔본문 화해를 다루지 않는다. 인계된 것은 **개입 지점**이다 — 필드↔텍스트 조립이 아니라 **프롬프트 텍스트 내부**이고, 이는 리서치 §4-3의 미탐색 층(프롬프트 재작성)과 같은 지점을 공유한다. ~~다만 텍스트 내부의 메커니즘은 n=1(`S00100`)로 미확정이고 후보 둘이 동등하다~~ **✅ 판별 완료(2026-08-22, 14.0 §4-4 후속, GPU 0 / `src` 변경 0 — 근거: `14-0-angle-conflict/report.md` §8). (a) 기각 · (b) 미확정 · 두 가설의 공통 전제가 대조군에서 깨짐.** 출하 플레이트 43장을 사전등록 투영기하 규칙(소실점 세로 위치 `y_h`)으로 프롬프트 비열람 판정 → 부감 17 / 눈높이 20 / 앙각 4 / 판독불가 2. **(a) 내용 질량은 방향이 반대다** — 표면 어휘 상위군 부감율 28% vs 하위군 62%(p=0.0505), 그리고 남은 신호는 프롬프트 **길이** 교란이다(100단어당 정규화 시 p=0.1180). **그러므로 바닥/천장 질량 게이트를 만들지 마라.** **(b) 조명 어휘는 주효과만 있다**(히트≥1 63% vs 무히트 23%, p=0.0124) — 용량-반응이 없고(2히트 1/3), 이 문서가 결정적이라 지목했던 두 샷이 **둘 다 (b)에 반한다**(`S00901` 최대용량·눈높이, `S00103` 최대용량·**앙각**), 경계 판정 13건을 빼면 유의성이 사라진다(p=0.25). **결정적 제약 — 시점은 프롬프트 텍스트의 함수가 아니다**: 10.2 가드가 재렌더한 5샷은 시드만 올리고 `image_prompt`는 그대로이므로 같은 프롬프트 두 번 뽑기인데, **5쌍 중 2쌍에서 시점 범주가 뒤집혔다**(`S00202` 앙각→눈높이, `S00301` 눈높이→부감). 따라서 **렌더 전 텍스트 스크리닝으로는 시점을 보장할 수 없고**, 이 부류에 이 프로젝트에서 작동한 유일한 수단은 **탐지 후 재생성**이다(⑤의 10.2 가드; 리서치 §2가 부정 프롬프트에 대해 같은 결론). 시점 게이트도 그 형태여야 한다 — 렌더 후 `y_h`를 재고 밴드 밖이면 시드를 올린다(시드 래더는 이미 있다). **②는 n=1이 아니다 — 검정 목표가 개수로 정의됐다**: 요청하지 않은 부감 **11/35**(경계 판정 전부 제외해도 7건)를 줄이는 것이고, `high-angle` **6/6**·`wide` **8/9**가 회귀 감시선이다. 버킷별 부감율은 `wide` 1/9 · `medium` 6/10 · `close-up` 3/7 · `low-angle` 0/4 · `high-angle` 6/6이며, 읽히는 그림은 "조명 어휘가 카메라를 올린다"보다 **"`wide`에는 수직 앵커가 있고 `medium`에는 없다"**에 가깝다(사후·탐색적 p=0.0413, 경계 제외 0.27 — **확정 아님**, 새 런에서 확인할 후보). 기각된 사후 축도 기록: 슬롯-1의 수평면 명사(p=1.0), 슬롯-1 절 길이(p=1.0). 게이트가 걸러야 할 것은 필드도 프롬프트 본문도 아니라 **렌더된 픽셀의 시점**이다(위 대조군). 버킷 일치로는 안 보이는 수식어 14건과 대응 필드값이 없는 `dutch angle`은 여전히 이 소관이다. 프롬프트를 바꾸는 개입은 렌더 전 텍스트 스크리닝을 타지만, **스크리닝 통과가 시점 보장은 아니다**. **전제**: 이 게이트는 `stock_plate_substitution_enabled`가 켜지면 `location_key`를 가진 31/43샷에서 무력해진다(플레이트 복사 경로는 `image_prompt`를 생성에 쓰지 않는다) — 14.1과 함께 설계해야 한다. 14.1의 세트 방식이면 어포던스는 런타임 채점이 아니라 **자산 메타데이터**가 되어 런당 비용이 0이 된다. 파일: `14-2-plate-affordance-gate.md`.

**✅ 2026-08-24 착수 — §4-2는 재논의하지 않았다. 다시 연 것은 착수 순서 전제 하나다.** §4-2 결정((c) 자산 메타데이터 + 자유생성 샷만 런타임, 판정 스키마 하나)은 2026-08-22 Jay 결정으로 유효하다. 그러나 함께 기록된 *"14-2를 14-1보다 먼저 하면 런당 VLM 43콜을 내고 나중에 버릴 코드를 쓴다"* 의 **이유가 성립하지 않는다** — (c) 하에서 런타임 경로는 버려지는 코드가 아니라 **(c)의 영구 절반**이고(14.1 이후에도 자유생성 12/43에 계속 발화), 14.1이 바꾸는 것은 존재가 아니라 **적용 범위**(43→12)다. 그리고 `stock_plate_substitution_enabled=False`인 오늘은 **43/43이 자유생성**이므로 런타임 절반이 유일하게 돌릴 대상이 있는 절반이다. 정말로 이른 것은 **메타데이터 절반**(붙일 자산도 고를 후보 풀도 없다). → **범위 분할**: 14.2 = 런타임 게이트 + 공유 판정 스키마, 메타데이터 절반은 14.1과 동반. 스펙 `spec-14-2-plate-affordance-gate.md`.

**⚠️ 그리고 착수 전 캘리브레이션이 이 항목의 표적 라벨을 반증했다** (`14-2-affordance-calibration/`, GPU 0 · 렌더 0 · `src` 변경 0, VLM 34콜; run `4b35c0ed` **33쌍 전수** 육안 판정 + 사전등록 라벨 고정 후 판정기 실행 — `PREREGISTRATION.md`). **(1) 위 목표문의 세 부류 중 게이트가 잡아야 하는 것은 클로즈업뿐이다.** "부감 바닥"은 잡으면 **안 된다** — cast 보유 33샷 중 비-눈높이 **17**건인데 사전등록 BROKEN은 4건이고, 극단 부감(§4-4 손라벨 y_h≤0.15) `S00100`·`S00104`·`S00303`·`S00502`·`S00904` **다섯 건 전부가 발 접지·방 보존으로 정상**이다. 부감 게이트는 카드 13장을 지우고 4건을 잡는다. "천장 앙각"은 애초에 사례가 틀렸다(아래). `floor_share`도 예측기가 아니다 — 유일한 플레이트 소실 사례 `S00602`가 **0.70**을 받았다(그 라벨은 시점 판정용이라 테이블 상면을 수평면으로 셌다: **다른 질문에 대한 정답**). `compositing_service.ground_plane()` 역상관(n=5)에 이은 **3·4번째 사례**이고 이번엔 n=33이다. **(2) 인계 라벨 `{S00504, S00803}`은 둘 다 어포던스 부류가 아니다** — 발이 접지돼 있고 바닥이 충분하며 판정기도 독립적으로 `standing_room=true`를 준다. `S00504`는 부감 원근(바닥은 기울고 카드는 정립), `S00803`은 척도(인물이 복도 전경을 지배)이고 **둘 다 14.3 소관**이다. 게이트로 잡으려 하면 오탐을 사서 없는 결함을 고친다. 그리고 `S00803`은 인계 서술 "천장 앙각"과 달리 §4-4 손판정 시점이 **EYE(y_h 0.52)** 다 — 인계 문구가 프롬프트 텍스트를 읽고 쓰였고 픽셀은 다른 말을 한다(§4-4의 리시드 대조군과 같은 갭). **(3) 기저율은 2/33(6%)이 아니라 7/33(21%)**, marginal 포함 8/33 — 임계값 설계의 출발점이 3.5배 틀렸다. 실패 양상은 넷이고 "떠 있는 인물" 하나가 아니다: **플레이트 소실**(`S00602`, 이 런 유일, 2026-08-09 `S00104` 계열) / **없던 바닥 발명**(`S00302`) / 카드가 온몸이 아닌 **떠 있는 흉상**(`S00201`·`S00601`) / 허공에 **앉거나** 무릎에서 잘림(`S00103`·`S00605`). **(4) 사전등록 채점은 문면대로 FAIL** — 재현 5/7 < 6/7, 오탐 **1/25**(`S00901`) ≤ 3/25. 미검출 `S00105`는 **판정기가 옳고 라벨이 틀린** 경우다(플레이트에 바닥이 있고 recompose가 그 위가 아닌 곳에 놓았다 = 배치 오류, `S00504`/`S00803`과 같은 14.3 부류). 규칙 문면으로 교정되는 오적용이므로 그렇게 기록하되 **교정 후 5/5는 다음 런의 가설이고 종결 수치가 아니다**(`gotcha_measure-densely-before-declaring-a-fix` — 이 세션도 8쌍 표본에서 잘못된 부감 가설을 세웠고 33쌍 전수가 그것을 죽였다). **(5) 판정기가 SCP 플레이트 한 부류에서 재현 가능하게 거부된다(신규)** — `S00601`(시트 덮인 시신)은 `data_inspection_failed` 400을 결정적으로 내고, 같은 플레이트를 **10.2 가드**(`vision_check.background_has_person`, 동일 엔드포인트·모델)에 넣으면 `None`이다(확인). 시신·의료·훼손은 이 파이프라인의 상시 산출물이므로 간헐 장애가 아니라 **영구 사각지대**다. **14.4가 원인 없이 기록한 그 런 판정불가 1건의 원인일 개연이 높다** — 14.4는 그것을 가시성 문제로만 닫았고 원인은 미귀속이었다. 그러므로 14.2는 14.4의 undecidable 정책(수용 + 경고, clean 계상 금지)을 승계해야 하고, 판정불가를 "설 자리 없음"으로 처리하면 이 부류에서 cast가 상시 삭제된다. **(6) 새 층을 만들 이유가 없다** — 종단 동작은 8.19 `_suppress_cast_on_no_figure_framing`의 `cast → []`가 이미 하고 있고, 그 함수의 `# ponytail:` 주석이 *"until a diagnosed case justifies a marker with better precision"* 라고 자기 한계를 적어뒀다(이 세션이 그 진단 사례다). 단 **어휘 확장은 금지**가 실측됐다 — `high-angle`을 마커로 넣으면 (1)의 다섯 건을 지운다. 배치 지점도 있다: 10.2 시드 래더가 렌더 후 판정 → 시드 상승 → 소진 시 종단 처리 구조와 사이드카·경고·resume 재발화(14.4)를 이미 갖고 있고, `shot["cast"]`가 그 루프 안에 있다. **인계된 버킷 밖 수식어 14건은 게이트 입력이 아니다** — `S00602` 슬롯-1은 `"medium shot"`, `S00803`은 `"low-angle shot looking up from the floor"` 로 **둘 다 버킷 내**다. 라벨링 사전확률로만 쓴다. `dutch angle`은 이 런에서 필드 발화 **0건**이고 14.0의 `_resolve_camera_angle` 어휘 밖 경고가 발화 시 잡으므로 **확인만 기록하고 코드를 쓰지 않는다**. **미주장**: 라벨은 Claude 단독 판정이며 `pairs_1..6.jpg`로 **Jay 확인 대기**(AC1, 인계 라벨 뒤집기 대조가 먼저), 픽셀 A/B 없음, 임계값 미확정.

**✅ 2026-08-24 CLOSED done (d055de4) — 게이트는 구현됐고 노브는 OFF 로 출하된다.** 8.19의 `cast → []` 를 픽셀 판정으로 확장했고 (그 함수 `# ponytail:` 주석의 해제 조건이 이 캘리브레이션으로 충족됐다), 배치는 10.2 래더 **밖** 확정 렌더 1회이며 판정 스키마는 하나다(오프라인 큐레이터와 런타임이 프롬프트 텍스트와 **요청 봉투**를 함께 공유). **적대적 리뷰가 이 스토리 자신의 주장을 두 번 반증했다.** **(A) 런타임이 캘리브레이션한 설정이 아니었다** — 요청 봉투 `[text, image]` vs `[image, text]` 가 재현 **3/7 ↔ 5/7** 을 가른다(각 3회·2회 반복에서 **뒤집힘 0**이므로 비결정성이 아니라 **결정적 순서 효과**이고, `S00103`·`S00605`가 순서만으로 뒤집힌다). 프롬프트 텍스트를 공유한 이유(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`)가 **봉투에 그대로 적용된다** — 텍스트만 공유하고 봉투가 갈리면 공유의 목적이 사라지고, 5/7 은 출하 설정의 수치가 아니게 된다. → `[image, text]` + `temperature=0` 통일(캘리브레이션 5/7·오탐 1/25 바이트 재현). ⚠️ **10.2 가드도 `[text, image]` 다 — 그 질문에 대한 순서 효과는 미측정이고 `deferred-work.md` 로 넘겼다** (14.4가 실측한 rung 0 38 / rung 1 5 가 그 봉투에서 나온 수치다). **(B) 사전등록 기준 `재현 ≥6/7` 은 구성상 도달 불가였다** — `S00601`은 `data_inspection_failed` 로 **영구 판정 불가**이고 `S00105`는 **판정기가 옳고 라벨이 틀린** 건이므로 최대 달성치가 5/7 이다. 고칠 것은 측정 대상이 아니라 기준이지만(`gotcha_a-screening-gate-can-fail-on-its-own-threshold`, 14.7이 같은 형태를 겪었다) **결과를 보고 기준을 다시 쓰지 않았다** — 교정 분모(5건)와 새 기준은 **AC1 뒤에 재사전등록**하고 fresh 표본(E2E iteration 5)에서 확인한다. 그래서 코드 기본값은 `True` → **`False`** 다(10.1c·10.5·10.1e 전례: 사람이 프레임을 판정하기 전에는 OFF). `.env` 핀 없음, 드리프트 리포트에 `source: code default` 로 보인다. **그 외 bad_spec**: 판정불가·미판정이 사이드카에 없어 **resume 이 깨끗한 어포던스 집계를 보고했다**(13.1이 없애려는 결함 그대로) / 비전 키 부재가 "죽은 판정기"로 계상돼 판정불가 3행 + 거짓 차단기 행을 만들었다 / `unjudged` 가 스톡플레이트·mock·resume 를 안 셌다 / resume 이 노브를 무시해 **오탐 복구 경로가 없었다**(이제 노브를 내리면 다음 패스에 카드가 돌아온다 — 측정된 1/25 의 유일한 복구 수단) / 경고 문안이 판정불가 행에도 "배역을 뺐다"를 단언 / 설정 주석이 `S00601` 을 14.3 부류로 오귀속. **patch 6** — 그중 3건은 진단기가 잡은 pyright 신규다(`{**shot, "cast": []}` 두 곳이 TypedDict 를 `dict[str, Unknown]` 로 넓혀 `_with_depth(shot: ShotData)` 를 깨뜨렸고, `image_bytes` 두 번째 독자가 possibly-unbound). image.py pyright **2건 → 1건**으로 베이스라인보다 하나 적다. **리뷰 패스 2는 Jay 가 중단**했으므로 루프 1의 수정들은 독립 리뷰를 받지 않았다 → `followup_review_recommended: true`. **여전히 미주장**: AC1(Jay 의 33쌍 라벨) 열려 있고 라벨은 **이미 두 번 틀렸다**(인계 2건과 서로소, `S00105`는 판정기가 옳았다) / **픽셀 판정 0회** — 어포던스 부류 7/33 이 몇으로 내려가는지는 **E2E iteration 5** 몫이다. 검증: 238 passed · 전체 3259 passed / 1 failed(그 1건은 14.5가 기존 결함으로 기록한 `test_render_pose_guides.py` PNG SHA 핀, stash 후에도 동일) · ruff clean · `report_decision_drift.py` exit 0. 근거·재산출: `implementation-artifacts/14-2-affordance-calibration/`. (done)

### Story 14.3: 화풍 계약 — 플레이트와 카드가 하나의 렌더 스타일을 공유

⑦. 10.3이 LoRA 정합(`horror.safetensors` SD1.5 레이아웃 제거)을 고쳤지만 화풍 표류는 남았다 — 이번 런에 네온 6장 + 이질 화풍 1장. 두 층을 다룬다: **플레이트 생성 측**(팔레트·조명·렌더 스타일을 닫힌 어휘로 제약, 부정 프롬프트 누적은 금지 — `gotcha_negative-prompt-overstuffing`이 두 번 물린 축) **그리고 recompose 측**(카드 화풍을 그대로 보존해 "찢어붙인 듯"이 남는 문제, 프레임 내 접지 불일치). 14.1의 승인 게이트가 플레이트 측 강제 수단이 된다. 파일: `14-3-art-style-contract.md`. **⚠️ 2026-08-24 14.2의 캘리브레이션이 소관 3건을 인계했다** (`14-2-affordance-calibration/report.md`): `S00504`(부감 원근 — 바닥은 기울고 카드는 정립), `S00803`(척도 — 인물이 복도 전경을 지배), `S00105`(있는 바닥 **위가 아닌 곳**에 배치). 셋 다 플레이트에 온몸이 설 지면이 **충분히 있고** 판정기도 `standing_room=true`를 주므로 **어포던스 게이트가 잡을 수 없다** — recompose 측 배치·접지·척도 문제이고 이 스토리의 두 번째 층(카드 화풍 보존 + 프레임 내 접지 불일치)과 같은 지점이다. `S00504`·`S00803`은 원래 14.2의 표적으로 기록돼 있었고 그 귀속이 틀렸다. (draft)

**✅ 2026-08-30 Jay 판정 — 라벨 확정, 그리고 ⑦은 한 부류가 아니었다.** 블라인드 컨택트 시트(출하면 43타일, `shot_id`+`REC`/`PLATE` 각인만) 전수 판정 결과 **17/43**이 지목됐다. **Claude 라벨 7건 중 6건 일치, `S00105`는 반증**(Jay 미지목), 그리고 **11건 미탐** — 기저율이 7/43(16%) → **17/43(40%)** 로 2.4배 틀렸다. 방향은 14.2와 같고(2/33 → 7/33), 이로써 이 에픽에서 Claude 단독 시각 라벨이 사람 판정에 뒤집힌 것은 **세 번째**다. Claude가 "애매함"으로 올린 것도 두 방향 다 틀렸다(`S00403`은 Jay가 유지, `S00900`·`S00901`은 미지목). **결정적 발견: Jay의 주석이 17건을 다섯 부류로 가른다** — 팔레트·화풍 7(`S00301` `S00303` `S00403` `S00501` `S00502` `S00605` `S00701`) / 합성 5(`S00504` `S00702` `S00800` `S00802` `S00904`, Jay 주석 *"합성문제"*·*"그림자"*·*"환자 캐릭터? 이상함"*) / 판독불가 배경 3(`S00503` `S00801` `S00903`, *"뭔지모르는배경"*) / 척도 1(`S00803`) / 배경에 사람 1(`S00201`, *"배경에 왜 사람이 있는거냐고"*). **즉 ⑦로 접수된 것의 59%가 ⑦이 아니다.** 지표 재채점이 그것을 확증한다 — 17건 전체 대상 상위 17위 안 **8/17**(무작위 기대 6.7, **신호 없음**)이지만 **팔레트 부류 7건만 대상이면 상위 7위 안 4/7**(기대 1.1), 상위 12위 안 6/7이다. 바닥권 5건은 전부 합성·판독불가이고 팔레트 축이 원리적으로 못 보는 것들이다. **그러므로 게이트를 만들지 않을 이유가 다섯째로 늘었다**: 이 축 위의 커트는 ⑦의 41%만 닫고 나머지를 "검사됨"으로 잘못 계상한다. 게다가 팔레트 부류조차 n=7이고 `S00303`(플랫 아이소메트릭 스케치, 랭크 29)이 축 밖이라 실효 표본은 6이다. **라우팅**: 합성 5 + 척도 1 → **E2E iteration 5**(Jay 결정 (B), 아래) / 판독불가 3 → **신규 부류**로 `deferred-work.md` 등재(어느 스토리도 이 축을 안 들고 있었다) / `S00201` → **14.1 승인 게이트** — 14.4(b)가 "그림 속 인물"을 그리로 보내며 *"자유생성 샷은 게이트에 도달하지 않으므로 감수"*라고 기록한 바로 그 리스크가 화면에 실현된 것이다(이 런은 43/43 자유생성). **⚠️ 부류 배정은 Claude가 했다** — Jay가 준 것은 17 ID와 주석 7건이고 나머지 10건의 부류는 추정이며 `S00502`·`S00503`이 가장 약하다. 근거·재산출: `14-3-art-style-contract/VERDICT.md`.

**✅ 2026-08-30 Jay 결정 (B) — 층 2에 지금 GPU를 쓰지 않는다.** `_DEPTH_PHRASE["near"]` 편집(= `S00803` 척도의 확정된 원인, `config.py:554-560`)도 지금 하지 않는다. 한 줄 수정 때문에 43-plate 스윕과 10.1e 검증 슬레이트를 다시 도는 비용이 이득을 넘고, 14.3이 깐 귀속 경로(`recompose` 블록의 `workflow_sha256` + `instruction_sha256` + 패스별 position/depth/pose)가 다음 전체 런에서 프레임을 지시에 귀속시켜 주므로 **E2E iteration 5**에서 함께 판정하는 편이 싸다.

### Story 14.4: 무인 배경을 출하 기본값으로 — 가드 승격 + "그림 속 인물" 처리

⑤. 두 부분이다. (a) ~~`background_person_guard_attempts`의 **코드 기본값**을 정한다 — 이번 런이 `2`에서 오염 3→0을 실측했고 비용은 샷당 비전 콜 1회 + 히트 시 재렌더 ~17초로 측정됐다. 지금은 `.env` 핀이라 출하되지 않은 상태다(13.6과 함께 처리 가능).~~ **→ 2026-08-22 종결, 아래 참조. `.env` 핀은 더 이상 없다.** (b) 가드가 못 잡는 부류를 정의한다 — 액자·모니터·포스터 **안**의 인물은 중복 인물이 되지 않으므로 탐지기 판정이 옳지만, ⑤의 체감 결함이기도 하다. 그 구분을 어느 층이 책임지는지(가드 확장 vs 14.3의 화풍 계약 vs 14.1의 승인 게이트) 결정한다. `undecidable verdict`의 처리 정책도 여기. 파일: `14-4-people-free-background-default.md`.

**✅ 2026-08-22 (a) 종결**: `background_person_guard_attempts` 코드 기본값 `0 → 2`, `.env` 핀 삭제, `.env.example` 잠재 되돌림 **4건** 주석 처리 — 가드 `0` / `CLONE_ENABLED=false` / `SPEED=1.2` / **`DEEPSEEK_MAX_TOKENS=16384`**. 네 번째는 리뷰 패스에서 나왔고 셋보다 나쁘다: 16384는 2026-08-05에 `scenario/structure`를 4/4 절단시킨 **실측 실패값**인데(코드 기본값은 32768) 새 체크아웃이 그것을 첫날 복사했다. 애초에 놓친 이유가 방법론이다 — 첫 패스가 `DECISIONS` 멤버만 훑어서 **이미 보고 있는 곳만** 봤고, 리뷰에서 `.env.example` 전체 39개 대입을 코드 기본값과 대조하고서야 드러났다(그 전수 대조가 이제 `tests/test_report_decision_drift.py`의 테스트다). 또 `CHARACTER_VISION_API_KEY=<YOUR_VISION_API_KEY>` **플레이스홀더도 주석 처리** — 플레이스홀더는 truthy라서 새 체크아웃이 가짜 키로 실제 DashScope를 때리고, 판정불가 3건에 차단기가 죽이고, 정작 발화해야 할 `vision_api_key_missing` 경고는 키가 비어 있지 않아 안 뜬다. 근거는 재산출 스크립트와 함께 `14-4-live-validation/`에 있다 — run `4b35c0ed` 43샷 중 rung 0 38 / rung 1 5(`S00103`·`S00202`·`S00203`·`S00301`·`S00400`) / 소진 0, 비전 콜 실측 **1.46~10.11초**(7콜, 평균 3.17초; Block-If 30초 안쪽이지만 한 자리 배수 차이다). 첫 4콜 버스트는 1.46~2.58초/평균 2.00으로 보였고 리뷰 패스의 3콜에서 **같은 프레임이 10.11초**를 찍었다 — 성긴 표본으로 "~2초 상수"를 선언했던 것을 정정한다(`gotcha_measure-densely-before-declaring-a-fix`). 그리고 그 rung 1 다섯 건은 **탐지기 히트**이고 확인된 오염은 3건이다: `S00103`은 `14-0-angle-conflict/report.md` §8-5가 두 렌더 모두 인물 없음으로 기록했으므로 오탐일 개연이 높고(실제 렌더 한 장을 지불했다), `S00202`는 육안 확인이 없다. `2`는 두 라이브 표본의 **최악값**이다(10.2의 유일한 히트가 rung 2를 필요로 했고, 이 런의 5건은 전부 rung 1에서 해결). 13.6도 부분 충족: AC1(결정 선언 `config.DECISIONS`)·AC2/AC3(`scripts/report_decision_drift.py`)·AC5·AC7. **AC4(렌더 사이드카에 결정 프로비넌스)는 명시적 보류** — 13.3 AC8의 resume 규칙을 건드리므로 `deferred-work.md`로.

**✅ 2026-08-22 (b) 결정 — "그림 속 인물"의 소관은 14.1의 승인 게이트다.** 액자·모니터·포스터·해부도·조각상 안의 인물은 **플레이트 단위 속성**이고, 사람이 그 플레이트를 볼 때 한 번 판정하면 되는 것이다. 14.1의 승인 게이트는 이미 ③⑤⑦의 단일 강제 지점이므로 새 층을 만들지 않는다. **런타임 가드 확장은 기각**, 이유 셋: (i) 탐지기가 좁혀진 목적을 깬다 — 가드는 "합성될 카드가 프레임 안의 **몸**과 겹치지 않게" 존재하고 포스터는 두 번째 몸이 아니다; (ii) `gotcha_person-token-regex-is-unusable-on-image-prompt`가 경고한 구분(카메라·척도·그림 속 인물·부재)을 정확히 다시 연다; (iii) 중복 인물 결함이 아닌 것에 히트마다 렌더 한 장을 영구히 지불하게 되는데, 사람은 플레이트당 한 번만 답하면 된다. 리서치 §2의 "가드 확장은 마지막 선택지"와 일치. **잔여 갭은 명시적 감수 리스크다**: `location_key`가 없는 샷(이 런 12/43 — 그리고 `stock_plate_substitution_enabled=False`인 현재는 사실상 43/43이 자유생성이다)은 승인 게이트에 도달하지 않으므로, 14.1의 세트가 그 샷들을 덮기 전까지 이 결함 부류는 **커버되지 않고 감수**된다(부정 프롬프트는 해법이 아니다 — `BG_NEGATIVE_SUFFIX`에 인물 토큰이 이미 있는데도 `S00201`이 그려졌고, `gotcha_negative-prompt-overstuffing`으로 두 번 실패한 축이다). `deferred-work.md`에 14.1/14.3 라우팅으로 등재.

**✅ 2026-08-22 undecidable 정책 결정.** 판정 불가(키 없음·HTTP 실패·파싱 실패)는 **프레임을 수용하고 사다리 단을 소비하지 않는다** — 정보가 없는 상태에서 재렌더는 ~17초를 써서 아무것도 배우지 않는다. 바뀐 것은 **가시성뿐**: 단발 판정 불가도 이제 샷 단위 경고(`background_guard_unscreened` / `reason=detector_undecidable_shot`, `scene_num`+`shot_id`)를 남긴다. run `4b35c0ed`에는 판정 불가가 정확히 1건 있었고 경고가 **0건**이었다 — 미검사 프레임이 UI에서 검증된 클린 프레임과 구분되지 않았고, 그게 13.1이 없애려던 결함이다. 차단기(연속 3 / 누적 6)와 런 단위 경고 1건은 그대로이고, 그 차단기가 샷 단위 행 수의 상한이다. 노브를 `0`으로 내린 운영자는 여전히 경고받지 않는다(13.1 AC2) — 그건 이제 **기록된 결정으로부터의 이탈**이고, 드러나는 곳은 런 경고가 아니라 `scripts/report_decision_drift.py`다. **내구성도 리뷰에서 고쳤다**: 경고만으로는 `full_restart_run`이 체크포인트를 지우고 이미지를 남기므로 재시작 후 미검사 프레임이 "검증된 클린"으로 돌아왔다 — `guard_undecidable`을 사이드카에 추가(가산·비교 제외, 13.3 AC8 준수)하고 resume에서 `detector_undecidable_earlier_run`으로 재발화한다. 또 `cap_samples`를 (code, reason) 단위로 바꿨다: 판정불가 행이 같은 코드를 공유하는 `ladder_exhausted`(이 계열에서 가장 중대한 행)를 캡 밖으로 밀어내고 있었다(`gotcha_summary-from-a-capped-list-drops-the-severest-item`). (done)

### Story 14.5: 나레이션 ↔ 배경·포즈 정합

⑥. 10.4가 A/B로 사망하고(`project_10-4-blocked-ab-in-noise`) 10.4b가 `visible_event 84.9%`를 살아 있는 결함으로 넘긴 축. **10.4의 교훈을 반복하지 않는다**: 매핑에 렌더를 더 쓰지 말고(손으로 짠 커버조차 `match`를 못 움직였다). ⚠️ **2026-08-22 14.0 §4-5가 제약을 강화했다**: `dsg_score`뿐 아니라 **그 하위 축도** 게이트로 쓸 수 없다 — 사건 축(`state`)이 ρ=−0.174로 집계보다 더 강하게 뒤집혀 있고(판독불가 0.625 vs 판독가능 0.390), 원인은 프롬프트에서 도출한 질문이 유도질문이라 판독불가 프레임이 가장 답하기 쉽다는 것이다. **프롬프트 도출 체크리스트는 시각 게이트가 될 수 없고 판정은 블라인드여야 한다.** 살아 있는 축은 현재 `readable`(12/66) 하나뿐이고 `match_score`는 3-몰림(29/66)이 남아 있다. 또 `visible_event 84.9%`는 블라인드 `event` **존재율**(66/66)이 아니라 나레이션 일치율이므로 두 수를 섞지 말 것. ⑥의 개입 지점은 계측기가 아니라 **생성기**이고, 14.0 §4-3이 샘플러 개입을 배제했으므로 **프롬프트 재작성 층**이다(비-GPU, 렌더 전 스크리닝 가능). 14.1의 세트 방식이 이 축을 바꾼다 — 생성 시점에 정합을 추측하는 문제가, **태깅된 후보 집합에서 고르는 문제**가 된다. 캐릭터 포즈 정합은 10.5의 pose_guide 자산과 8.4의 특수 포즈 카드에 연결된다. 파일: `14-5-narration-plate-pose-match.md`.

**✅ 2026-08-22 스펙 작성 — 범위가 Jay 결정 2건으로 고정됐다**(`spec-14-5-narration-plate-pose-match.md`, 미착수). **① 배경·사건 절반만.** 나레이션 행위 ↔ 카드 포즈 정합은 §4-1의 '포즈를 자산 축으로 둔다'에 따라 **14.6 소관**이다 — 현행 카드 라이브러리는 10.8 비소급 상태이고 `cast_card_fallback` 4건이 자산 부재이므로 14.6 없이는 측정만 되고 고칠 레버가 없다. **② 판정은 렌더 전 텍스트 게이트 + 픽셀은 다음 E2E.** 전용 페어 렌더 A/B는 기각했다(10.4의 '매핑에 렌더를 더 쓰지 마라'); 픽셀 판정은 iteration 5의 블라인드 `readable`에 태운다. ⚠️ **기준선 정정: 84.9%는 오늘의 생성기 숫자가 아니다.** 그 56/66은 run `8a9a288b`의 시나리오(2026-08-07 작성)에서 나왔고 `visual_breakdown.md`는 그 뒤 **2026-08-10에 10.2가 편집**했다(`9d4ec43`, production v14). 10.4b의 커밋 메시지가 그것을 *'현행 프롬프트에서 실측한'* 기준선이라 적었지만 같은 메시지의 타임라인 절이 반증하고, 10.4b 자신의 후보 편집도 `7744af1`로 바이트 동일 되돌림됐다 — 즉 **현행 v14 생성기의 `visible_event`는 측정된 적이 없다.** run `4b35c0ed`(43샷, v14가 쓴 첫 런)에서 10.4b의 judge를 **import해서**(문구 복사는 84.9%와의 비교를 무효화한다) 재기준선부터 잡는다. **가설(시험 대상)**: 결함은 프롬프트 조립이 아니라 **슬롯 배치**다 — `visual_breakdown.md:84`의 슬롯 3이 *'가장 극적인 순간'*을 요구하면서 **이 문장의 사건**에 묶지 않고, 사건 주체가 사람일 때는 배경 전용 규칙(`:7-21`, 옳고 유지) 때문에 그 사건이 앉을 슬롯이 없으며, 셀프체크(`:326`)도 action/state의 **존재**만 묻는다. 처방은 슬롯 3을 **이 문장 사건의 보이는 귀결**(사람이면 신체가 아니라 흔적·변위·잔여)로 묶는 편집 **한 곳**이고, 회귀는 양방향으로 본다 — `present_subject` 100% 유지 + 14.7이 출하한 `scenario/review` v11이 `descriptor_violation`을 새로 내지 않는가('사건을 그려라'가 신체를 다시 끌어오는 것이 이 편집의 고유 위험이다). 판정은 **런 단위 총합**이다(셀별 다수결은 저빈도 셀에서 노이즈로 뒤집힌다 — `gotcha_a-screening-gate-can-fail-on-its-own-threshold`). **전제**: `stock_plate_substitution_enabled=False`라 지금은 43/43이 자유생성이어서 이 편집이 전 샷에 닿지만, 14.1이 그 플래그를 켜면 `location_key` 보유 31/43이 `image_prompt`를 생성에 쓰지 않으므로 도달 범위가 12/43으로 줄어든다.

**✅ 2026-08-24 CLOSED done — 편집은 기각됐고 소득은 측정 정정 셋이다.** 근거·재산출 전량
`implementation-artifacts/14-5-prompt-screening/`. **GPU 0 · 렌더 0 · `src` 변경 0 · 프롬프트 최종 변경 0.**

**기각 — 사전등록된 조건이 발동했다.** 슬롯 3을 *"THIS sentence's event, as a visible trace"*(주체가 사람·개체면 신체가 아니라 흔적)로 묶는 편집을 스크리닝했더니, 신 프롬프트 산출물을 14.7이 출하한 `scenario/review` v11에 **5rep** 통과시킬 때 typed `descriptor_violation`이 **구 22 → 신 31**, `entity_in_prompt` 버킷이 **구 3 → 신 8**이었고 신 다리의 지적은 **진짜 신체 참조**였다 — *"where a body had just risen"*, *"the collapsed form"*, *"where a tall figure stands"*, *"around the doctor's finished work"*. **"사건의 흔적"이 몸을 위치 참조로 되불러왔고, 편집 자신의 예시(*"a slumped-empty floor position"*)가 그 문을 열었다.** 목표축 이득도 없었다(+2.86pp, 문장 페어 부호검정 p=0.3877 — 검정력이 없으므로 "효과 없음"의 증거도 아니다). → **되돌림**, 재시딩, 라이브 `scenario/visual_breakdown` **v16 = v14 텍스트**(런타임 이름 `scenario%2Fvisual_breakdown`로 확인). 10.4b가 `7744af1`에서 택한 것과 같은 길이다.

**① 승계 기준선이 틀렸다 — 정정.** `visible_event` **84.9%(56/66)** 는 오늘의 생성기 숫자가 **아니다**: run `8a9a288b` 시나리오(2026-08-07)이고 `visual_breakdown.md`는 그 뒤 **2026-08-10에 10.2가 편집**(`9d4ec43`, v14), 10.4b 자신의 후보 편집은 `7744af1`로 바이트 동일 되돌림됐다. 10.4b 커밋의 *"현행 프롬프트에서 실측"* 주장은 **같은 메시지의 타임라인 절이 반증한다**. v14 첫 런 `4b35c0ed`(43샷) 실측 = **풀링 71.16%(153/215)** · **사건 담지 76.43%(107/140)** · `present_subject` **100%(215/215)**.

**② 분모에 정답이 false인 행이 15/43 있다.** 문장 자체가 개체의 외형·정체·물성이나 인용 규정문이면 배경 플레이트가 담을 사건이 **없다** — 풀링하면 지표가 **나레이션에 없는 사건의 발명을 보상**한다. 블라인드 문장 분류기(`has_event`, `image_prompt` **비열람**·양 다리 동일·나레이션만 읽음 → §4-5가 금지한 프롬프트 도출 체크리스트가 **아니다**)를 붙였고 **5표 다수결에서 만장일치 43/43**이다. ⚠️ **안정 ≠ 정확**: `S00403`은 알려진 오탐이고 28샷 분모에서 문장 하나가 재분류되면 축이 **3.6pp** 움직인다 — **보고된 +2.86pp는 분류기 자신의 오차 범위 안**이다.

**③ 재생성 노이즈가 편집 효과보다 크다.** 구 프롬프트로 **다시 뽑기만** 해도 **+7.14pp**(76.43% → 83.57%). 대조군 없이 "출하 텍스트 vs 후보"로 쟀다면 +10pp가 나오고 그중 7pp가 다시 뽑기의 공로였다. ⚠️ **어느 문장이 어려운지는 재현된다** — 사건 담지 실패 문장은 shipped ∩ old-regen **7/7**. 바뀌는 건 그 문장이 이번 뽑기에서도 실패하는가이고 **5rep 전부 실패한 문장은 어느 재생성 다리에도 0개**다(old 0/23, new 0/20). 즉 "어려운 문장 집합은 고정, 뽑기마다 일부만 실패".

**⚠️ 이 스토리는 스스로 두 번 틀렸고 두 번 다 적대적 리뷰가 잡았다 — 그 자체가 기록할 값이다.** (a) 재생성 다리 shot-id를 **1-based**로 매겨 프로덕션의 **0-based** 출하 id와 직접 비교했고, 그래서 ③의 교집합을 **1/7**로 적어 *"실패 집합이 재생성마다 갈린다"* 는 **반대 결론**을 냈다(`gotcha_recorded-root-cause-can-be-inverted` 계열). (b) 리뷰어 회귀를 **2rep**만 사서 `entity_in_prompt` **5→0**을 얻고 "위험이 이득으로"를 부수 소득으로 실은 뒤 **시딩 근거로 삼았다** — 5rep에서 3→8로 뒤집혔다. `gotcha_a-screening-gate-can-fail-on-its-own-threshold`를 두 번 인용한 문서가 **자기가 산 가장 작은 표본 위에 출하 결정을 올린 것**이다. (c) AC가 이름 붙인 **풀링** 축이 구→신 **−2.81pp**인데 어느 산출물에도 없었다. (d) 잔여 실패 분석이 **rep 1에만** 기대어 "소리 사건은 표현 불가"를 결론으로 적었으나 그 문장은 **구 프롬프트에서 이미 4/5 통과**한다 → "표현 불가 부류" 철회.

**하니스에 남긴 것**(전부 리뷰 지적 수정): 판정-오류 Block If 구현(>5행 HALT), 생성 실패 `attrition` 기록 + 불완전 시 판정 거부, 가드레일을 통과 조건에 포함, 풀링 델타 상시 출력, 분류기 5표 다수결 + 지문 캐시 무효화, 레그 지문·`--legs` 검증·구신 텍스트 동일 시 HALT, `--retally`(판정 콜 0), 페어 검정을 **문장** 기준으로 + 검정력 주석, 리뷰어 하니스는 typed `descriptor_violation`을 AC 그대로 세고 **모든 지적 원문** 저장·판정을 **절대(신==0)**로·커버리지 동일성 요구·`os.chdir`로 `.env` 유실 방지·실행 전 `review.md` 청결 확인.

**가드 2건**(측정으로 벌어들인 것만): 배경 전용 계약 핀, 그리고 **슬롯 3이 몸을 위치 참조로 부르지 않는지** — 후자가 이 스토리가 실측한 정확한 실패 형태다. 슬롯-3 텍스트 핀은 편집이 기각됐으므로 삭제.

**미주장·인계**: 픽셀 판정 없음(텍스트 게이트는 픽셀 보장이 아니다 — 14.0 §4-4의 리시드 대조군 2/5). ⑥의 픽셀 판정은 **E2E iteration 5의 블라인드 `readable`**. **포즈 절반은 14.6**(Jay 결정 2026-08-22). **교란 명시**: 기각된 편집 문구가 judge 루브릭 어휘를 되썼으므로(*"visible trace"*), 후속이 같은 층을 건드리면 **개입 어휘와 채점 어휘를 분리**해야 한다. **열린 설계 질문**: 사건은 있으나 환경에 흔적이 없는 문장(소리·지각·부재)에 슬롯 3이 무엇을 요구해야 하는가 — 기각된 편집은 그 경우에도 흔적을 요구했다. **전제**: `stock_plate_substitution_enabled=False`라 지금은 43/43 자유생성이지만 14.1이 켜면 도달 범위가 **12/43**으로 준다. (done)

### Story 14.6: D급·오브젝트 자산 세트 + 카드 라이브러리 재생성

**2026-08-29 리뷰 루프 1 재구현 + 루프 2 패치 — 게이트·계약·감사·수요 산정은 닫혔고, 픽셀은 열려 있다.** 증거·재산출: `_bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets/{report.md,reconcile_manifest.py,dryrun_batch.py}`. **렌더 0장 · GPU 0 · VLM/LLM 콜 0 · `bump_style_epoch()` 실행 0회 · `angle_*_path` 쓰기 0회 · `assets/manifest.json` md5 불변**(GPU 부재는 주장이 아니라 4채널 실측으로 리포트 §1에 원문 — 13.3의 거짓 단언 전례 때문).

**닫힌 것 (4가지).**
① **스테이징 게이트 확장.** `_validate_stage_target`의 standing 전용·STOCK 3키 전용 제한을 해제했다. 좁히고 있던 것은 정책이 아니라 승인기의 파일명 조회 한 줄이었다(비-standing은 `{pose}_{angle}.png`). 서비스 계층은 이미 안전했다 — `if not stage:`가 매니페스트·승인·카드행을 전부 막고 `angle_*_path`는 standing에서만 쓴다. 지운 docstring이 경고한 **고립 위험은 실재**하므로 지우지 않고 재서술했다.
② **스프라이트 계약 + `has_alpha` 병립.** `domain/png.py`에 `alpha_profile`/`sprite_contract`(사유 5종: `unreadable`/`no_alpha_channel`/`empty_alpha`/`opaque`/`landscape_canvas`)를 추가하고 승인 게이트에 **`has_alpha`와 함께** 세웠다. 임계는 전 모집단 44장에서 유도 — 실측 밴드 `transparent_fraction` **0.4377~0.8556**, 하한 0.02는 "투명이 아예 없다"만 거른다(front 6장 밴드 0.7055~0.8421에 맞췄다면 **44장 중 18장**이 떨어지고 — 0.4377~0.7051 — 그중 **4장은 standing 카드**다: `SCP-049/standing_three_quarter` 0.4810, `STOCK-researcher/standing_three_quarter` 0.7032, `STOCK-d-class/standing_side` 0.7039, `SCP-096/standing_back` 0.7050. 리뷰 루프 2 정정 — 앞선 반복은 14장이라 적었고 "sitting·hint 카드가 먼저"라고 부류까지 좁혔다. 리포터가 이 반사실을 매 실행 출력한다). 계약은 손상 컨테이너에서 `has_alpha`보다 **약하다**(잘린 PNG·IEND CRC 깨짐을 Pillow가 열어버린다) — 그것을 실행 가능한 주장으로 고정한 테스트가 있다.
③ **원자적 에폭 승격.** `staged_dir`이 `epoch_{style_epoch+1}`이라 스테이징 자리 = 다음 라이브 자리이고, 둘을 가르는 것은 **닫는 `bump_style_epoch()`뿐**이다. 그래서 에폭은 그 안의 모든 키·모든 포즈를 함께 승격하고 **항상** 범프로 닫는다. 리뷰가 재현한 3건(스테이징된 sitting 영구 고립 / 승격 후 `--reject`가 라이브 승인 카드 4장 삭제 + 서술자를 `None`으로 덮고 exit 0 / 재스테이징이 승인 픽셀을 덮어 `verify_asset` 파괴)이 전부 회귀로 고정됐다.
④ **감사와 수요 산정.** 신규 리포터를 만들지 않고 `report_card_coverage.py`를 확장했다(같은 모집단을 둘이 훑으면 갈라진다 — 전례 있음). 실측: 카드 **52** 중 계약 PASS **44** / FAIL **8**(SCP-1471·682, 전부 `no_alpha_channel`) / **오탐 0**. 출처 3버킷 **pre-v5 45 / same-day 4 / post-v5 3**(same-day는 시딩에 타임스탬프가 없어 재생성으로 세지 않는다). 정합은 매니페스트 **52엔트리 전수**(standing 32 포함 — `character_cards` 20행만 돌면 사각) 대조로 정방향 **7행** / 역방향 **0행**. `--demand 4b35c0ed`는 **41 placements / 9 scenes / UNMET 4**이고 4건이 `cast_card_fallback` 4건과 **`(shot_id, card_key)` 단위로** 대응한다(이 런은 8샷이 다중 cast라 `shot_id` 단독 키잉은 한 건을 잃는다). `served`는 계약을 참조한다 — 컬럼이 비어 있지 않은 것만으로 `SCP-682`를 served로 세는 것이 §7이 정정하는 역전이다.

**부수 소득 3건.** (a) **`deferred-work.md:715` 정정**: *"any run whose entity is one of these keys draws them"*은 거짓이고 진실이 더 나쁘다 — `video.py:2528-2542`가 `has_alpha`로 **raise**하므로 1471/682 캐스팅은 나쁜 프레임이 아니라 **죽는 런**이다. 같은 정정이 `has_alpha`의 진짜 사각지대도 뒤집는다(이 8장이 아니라 정반대인 **불투명 RGBA**). 원문 보존 + 반증 주석. (b) **빈-서술자 가드 + 생산자 전수조사**: `angle_*_path`를 쓰는 5경로와 카드 파일을 쓰는 2경로를 전수 열거했고(리포트 §8), 가드는 funnel(`generate_candidates_from_reference`)과 funnel을 지나지 않는 `generate_special_pose_card` **두 곳**에 붙었다. 앞선 반복은 프로덕션 **도달 불가한** 함수에 달고 세 문서에 "닫혔다"고 적었다. 경고 `character_descriptor_missing`은 호출부 실측으로 `scenario` 스테이지이고, `_run_warnings`가 연결된 경로에서 **실제로 발화하는 것**을 테스트가 확인한다. (c) **`_SIDE_GUTTER`**: `hint_475c8a9231_front.png` alpha bbox **(0,821,832,1208) → (8,828,824,1208)**. 프레이밍만 고치고 잘린 해부는 복원하지 못한다.

**열린 것 (코드가 하지 않는 것).** ① §5 재생성 배치의 실제 렌더와 Jay 판정 — 배치는 두 갈래 모두 드라이런으로 exit 코드를 확인했으나(`dryrun_batch.py --residue {reject,promote}`) 픽셀은 만들지 않았다. 10.8 실측 경고를 그대로 인계한다: 같은 명령으로 만든 `STOCK-d-class` sitting 4장 중 3장이 서 있는 인물이었다(텍스트 포즈 지시는 무시된다). ② **pre-v5 45장의 standing 재생성** — 크기만 적고 견적하지 않았다. ③ `SCP-1471`/`SCP-682`의 사람 작성 서술자(둘 다 길이 0, 스펙 Block If로 배치 제외). ④ **오브젝트 세트는 만들지 않았다** — `ShotData`에 오브젝트 축이 없고(`cast`/`location_key`가 전부), `AssetService`에 `kind` 필드 자체가 없어 종류가 추론된다. 소비자 없는 라이브러리는 읽히지 않는 픽셀이다. 필요한 seam 3종을 인계했다. ⑤ `STOCK-d-class/epoch_3/` 스테이징 잔류(2026-08-16, 완전·계약 통과)의 승격/폐기 판정 — 원자적 승격 때문에 **모든 배치의 0단계**다. ⑥ 미등록 디스크 파일 **24개**(마커 3 포함, 21이 아니다)의 GC — 삭제하지 않고 보고만. ⑦ `reconcile_manifest.py --commit` 실행(7행 열거만; `retire_asset`은 역함수가 없다). `special_pose_max_per_run`은 **바꾸지 않았다** — 세트를 채우면 `_ensure_special_pose_cards`가 그 hint를 건너뛰므로 캡이 무의미해진다는 것이 이 스토리의 논지이고, 캡은 세트가 채워진 뒤에 다시 재는 것이 옳다(`config.DECISIONS` 행도 추가 안 함).

**리뷰 루프 2(설계 통과, 패치만) — 인계물이 파괴적 명령을 안전하다고 설명하고 있었다.** ⓐ 리포트 §5의 0단계 **두 선택지 모두** 부수 효과가 있는데 "라이브 무변경"이라고 적혀 있었다: `--reject`는 사이드카로 `visual_descriptor`를 되돌리고 그 사이드카는 라이브 서술자와 **문자 380부터 갈린다**(라이브 701자 구조형 / 사이드카 1600바이트 산문형). 읽기 전용 실측으로 그 라이브 텍스트가 *그 스테이징 자신의 산물*임까지 확인했으나(`updated_at`이 스테이징 front 카드 mtime + 1.7초), 디렉터리 안의 어떤 파일도 그 사실을 말해주지 않으므로 **자동 복원을 중단**했다 — `seed_stock_cast.py`가 `_poststage_descriptor.txt`(스테이징이 남긴 텍스트, `finally`에 기록해 크래시 경로까지 덮는다)를 쓰고, `_reject`는 라이브가 그것도 사이드카도 아니면 크게 경고하고 **복원하지 않는다**. 그리고 다른 선택지(잔류 승격)는 `_retire_special_pose_cards`가 `STOCK-d-class`의 **승인 hint 카드 3장을 폐기**하는데 그중 2장은 §4가 `served yes`로 찍는 카드다(`hint:b0f00082b3`→S00104, `hint:f5a7540b92`→S00103) — 코드는 설계상 옳으므로 두지만, 승인 hint를 비우면 캡 압력이 **줄지 않고 늘어난다**는 점에서 이 스토리의 캡 논지를 hint 축에서 뒤집는다. 둘 다 리포트에 명시했다. ⓑ **크래시한 스테이징이 에폭 전체를 물었다**: `_discover` 블로커가 `--reject`까지 막아 복구가 `assets/` 안의 `rm -rf`가 됐다(5.23 ComfyUI 크래시가 정확히 이 상태를 만든다 — 사이드카는 이미 써졌고 서술자는 이미 교체됐다). 이제 블로커는 승격만 막고, 좁힌 `--key` 거절은 형제 세트가 있어도 허용된다. 곁가지 둘: 빈-서술자 가드보다 `chars_dir.mkdir`이 먼저라 거부 경로가 빈 에폭 디렉터리(=블로커)를 남기고 있었고, 승격 루프 중간 raise가 닫는 `bump_style_epoch()`를 건너뛰어 실패 모드 3을 실패 경로로 재현하고 있었다(이제 `try/finally` + `PARTIAL PROMOTION` 출력). ⓒ **반사실 수치 정정**: front 6장 밴드에 하한을 맞췄을 때 떨어지는 카드는 14장이 아니라 **18장**이고 그중 **4장이 standing**이다 — 리포터가 이제 이 반사실을 매 실행 출력하므로 손으로 옮겨 적은 수가 아니다. ⓓ 나머지 패치: `reconcile_manifest.py`의 행 키가 `_sanitize_scp_id`를 안 거쳐 HALT 검사를 건너뛸 수 있던 것, `--demand`의 `served`가 `_normalize_pose`를 건너뛰어 어휘 밖 포즈를 UNMET으로 오보하던 것, `characters` 테이블이 비면 `--demand`가 조용히 무시되던 것, 출처 축의 `created_at` 부재가 `pre-v5`로 흡수되던 것(→ `unknown` 버킷), 정합 축이 `manifest draft / db approved`를 어느 버킷에도 안 찍던 것, 계약의 `aspect >= 1.0`이 정사각 캔버스를 landscape로 떨구던 것, `_SIDE_GUTTER` 폴백이 캔버스 폭 17~24에서 발화하지 않아 피사체가 1px로 붕괴하던 것, `pose_guide_conditioning_enabled` 승격을 docstring이 13.1로 적어 `config.DECISIONS`의 10.5와 어긋나던 것(커밋 `24b2932`로 10.5·10.6 확정), 테스트 10건이 들여쓰기로 엉뚱한 클래스에 편입돼 있던 것, `assert a, b == c` 형태의 무효 단언, 재스테이징 회귀 테스트가 `seed.run()`을 안 지나던 것.

③의 "D 계급 셋, 오브젝트 셋". 이번 런의 `cast_card_fallback` 4건과 `special_pose_cap_exceeded` 1건이 실증 근거다. ⚠️ **2026-08-22 14.0 §4-1 결정으로 범위가 늘었다 — 포즈도 이 스토리의 자산 축이다.** 씬이 포즈를 결정하게 하는 신규 삽입 모델(Kulal/InsHuman)은 도입하지 않기로 했으므로, 필요한 포즈는 **승인 카드를 늘려서** 공급한다(10.5 ControlNet openpose 3/3 supine·기본 off, 8.4 특수 포즈 카드가 기구). 정체성 하한(승인된 카드 픽셀)은 유지된다. 10.8이 `character-generation` v5를 시딩하면서 남긴 **비소급 상태**를 닫는다 — 현재 라이브러리의 모든 카드는 약한 프롬프트 산물이고 재생성 + 사람 판정 전까지 그대로다. 알려진 개별 결함도 함께: 누운 포즈 카드의 프레임 양끝 클리핑과 흰 소매 정체성 드리프트(10.8 deferred), `SCP-1471`/`SCP-682`의 approved tier-A 카드가 스프라이트가 아닌 것(벽 사진·두 인물·알파 없는 풍경). **주의: `characters.angle_*_path`에 쓰는 것이 곧 출판이다**(`gotcha_standing-cards-have-no-approval-gate`) — 재생성은 승인 게이트 뒤에서. 파일: `14-6-dclass-object-asset-sets.md`. (draft)

### Story 14.7: scenario 리뷰어를 recompose 이후 규칙에 맞춘다

**CLOSED done (2026-08-22).** 스테일이었던 것은 `prompts/scenario/review.md` **두 줄**이고, 생성기 `visual_breakdown.md`는 **이미 옳았다** — 두 프롬프트가 정면으로 모순한 채 라이브에서 돌고 있었다. `:46`("Every scene where the entity appears must use the Frozen Descriptor")은 **적용 범위가 무기재**여서 모델이 `image_prompt`까지 끌어갔고, `:61`("When entity_visible is true, the SCP frozen descriptor … is present")이 주범이었다. `entity_visible`은 `writing.md:219`가 정의한 **씬 단위 나레이션 필드**이고 `visual_breakdown.md`에는 등장조차 하지 않으며 샷 dict에도 그 키가 없다 — 리뷰어가 씬 단위 나레이션 사실을 샷 단위 렌더 지시로 오독했다.

처방은 삭제가 아니라 **역전**이다(frozen descriptor가 `{{scp_visual_reference}}`로 주입되므로 침묵은 규칙 재도출을 허용한다): §4에 적용 범위를 명기하고, `image_prompt`에 개체·인물·SCP 지정자가 **있으면** `descriptor_violation`으로 뒤집고, "보고하지 말 것" 2건((a) frozen descriptor 부재, (b) `negative_prompt`의 사람 배제 토큰)을 아키텍처 근거와 함께 명시했다. 같은 결함 부류의 두 번째 사례인 금지 일반어 격차도 닫았다 — 리뷰어 6개 → 생성기와 동일한 **11개**(`ominous`/`sinister`/`menacing`/`foreboding`/`unsettling` 추가; 그동안 생성기가 금지한 어휘를 리뷰어가 조용히 통과시켰다).

**렌더 전 텍스트 스크리닝 실측**(GPU 0, run `4b35c0ed` 씬 6·8·9 실입력 + 합성 역방향 통제, 구/신 각 **5회 = 40콜 단일 클린 반복**, 전부 파싱 성공, `gemini-3.6-flash`, 전사 `transcript-20260822T134015.jsonl`, **종료코드 0**): frozen-descriptor 오탐(i) **구 6/15 rep → 신 0/15**(전 셀 0). 자기검증도 자기 조건으로 통과했다 — 구 프롬프트가 씬 9에서 **5/5 다수결로 재현**한 뒤에야 신 0을 신뢰한다. `negative_prompt` 삭제 요구(ii) **구 1/15 → 신 0/15**(전사에서 인용 가능). 금지어 지적은 **구 6 → 신 6으로 불변**이고 씬 8은 **구·신 모두 5/5**다(11개 목록은 기존 6개의 진부분집합 확장이라 구조적으로 커버리지가 줄 수 없고, 실측도 줄지 않았다). 개체를 `image_prompt`에 주입한 역방향 통제(다른 샷은 전부 보존)는 **구 0/5, 신 5/5** — 오탐이 침묵으로 사라진 게 아니라 규칙이 방향을 바꿔 살아 있다(구 프롬프트에는 이 방향 검사가 **아예 없었다**). §4 나레이션 진성 모순은 구·신 모두 **5/5**로 약화되지 않았다. **한 번 FALSIFIED가 났고 범인은 게이트 기준이었다**: `--reps 3` 헤드라인에서 씬 6 금지어가 구 2/3 vs 신 1/3이라 셀별 다수결 멤버십 게이트가 "살아 있는 규칙을 죽였다"고 판정했는데, 그 셀의 실제 기저율은 양쪽 다 ~10~25%여서 작은 reps에서 50% 선을 무작위로 넘는다(n=9 진단은 구 1/9 vs 신 2/9로 **방향 역전**, reps 5는 1/5 대 1/5로 동일). `PROMPT_POLICY.md`가 Story 6.10에 기록한 그 형태 — 단일 시행 무관용 기준은 노이즈만으로 통과 불가가 된다 — 이므로 **측정 대상이 아니라 기준을 고쳤다**(런 단위 총합 회귀 + 다수결→0 kill). 프롬프트 문구는 재조정하지 **않았다**: 1/9→2/9 기저율을 쫓는 것은 리뷰어의 탐지 민감도 튜닝이고 스펙 범위 밖이다. 반대 결과 보존: ① 오탐(i) 재현은 씬 의존적이다(씬 9 5/5, 씬 6 1/5, 씬 8 0/5) — 엉뚱한 씬의 3-rep 셀 하나만 봤다면 구 프롬프트가 깨끗해 보였다 ② (ii)는 재현이 희소해 clause (b)는 강한 전후 신호가 아니라 1회 재현 + 아키텍처 기반 예방책이다 ③ `old s9-syn`은 주입된 개체를 "정확한 Frozen Descriptor 문자열이 아니다"라고 지적했다 — 구 프롬프트에 역방향 검사가 없었다는 증거 ④ 어느 폐기된 반복에서 §4가 9/9→8/9로 1 rep 떨어졌는데 더 촘촘한·더 최신 측정 둘 다 노이즈라고 말한다. 분류기 오독 2건은 전사 대조로 잡아 `--selftest`(14케이스)에 고정했고, 앞선 반복들(분류기 2종 혼용, 헤드라인이 자기 각주와 불일치)은 **폐기**했다 — 사실만 남기고 수치는 승계하지 않는다. **오탐의 비용은 정정되었다.** 이 런은 `review_overall_pass: true` / `critic_verdict: retry` / `final_pass_index: 2`이므로 경고 2건이 pass-2를 **유발한 것이 아니다**(`scenario.py:859`는 critic retry로 발화). 오탐이 한 일은 **이미 발화한 수리의 범위 확대**다 — `_retry_scope`(`scenario.py:216-252`)가 review 지적 씬과 critic 노트 씬을 합집합으로 접으므로, critic {1,4,6,7} ∪ review {6,8,9} = **{1,4,6,7,8,9}**이고 오탐이 **씬 8·9를 추가**했다. 단위도 틀렸다: `writing_scene_repair_step`은 인덱스 집합 전체에 대한 **1콜**이고, 씬당 비용은 `_breakdown_for`(`scenario.py:728-740`)의 cast+breakdown **2콜**이다. 단, 상태에 남은 `review_issues`는 **pass-2** 리뷰의 산출물이므로 실제로 `_retry_scope`를 먹인 pass-1 리뷰가 같은 씬을 지목했는지는 **미기록**이다. 증거·재산출: `_bmad-output/implementation-artifacts/14-7-prompt-screening/{report.md,screen_review_prompt.py,headline-run-20260822T134015.txt,transcript-*.jsonl}`.

DEV MODE 직승격 완료(`migrate_prompts.py --label production --source prompts` → `created: scenario/review`), **런타임 요청 이름으로 확인**(`scenario/review` **v11**, labels `[production, latest]`, `background-only`×2·면제 절·correction 채널 절 존재, 스테일 문장 부재). 작업트리와 **바이트 동일은 아니다 — 1바이트 차이이고 원인은 확인되었다**: `migrate_prompts.py:86`이 `.strip()`하므로 후행 개행이 빠진다(`rstrip("\n")` 후 동일). v10 리포트의 "바이트 동일" 주장도 같은 이유로 부정확했다. ⚠️ 스펙의 검증 URL은 틀렸다 — 이름의 슬래시를 퍼센트 인코딩해야 한다(`prompts/scenario%2Freview`); 생슬래시는 **404**라서 출하 성공을 실패로 오독시킨다. 가드 **5건**(`test_scenario_chain.py`): 배경 전용 규칙 6핀 / 스테일 문장 **부재**의 역방향 핀 / 스테일 규칙의 **형태** 핀(`entity_visible` ±120자 안에서 descriptor 요구 문구 금지 — 정확 문자열 핀은 패러프레이즈를 통과시킨다) / **생성기 측** 2핀(리뷰어가 강제하는 계약을 `visual_breakdown.md`가 여전히 발행하는지) / 두 프롬프트 금지어 목록 집합 동일성(따옴표 패턴 확장 + 11개 **하한**, 파일 부재는 skip이 아니라 **실패**). 파일: `14-7-scenario-reviewer-recompose-alignment.md`.


**⚠️ 2026-08-30 재작성 — 매칭 축이 실측으로 은퇴했다.** 초판은 `camera_angle → viewpoint` 정합 맵 위에서 C1/C2/C3를 재판정하는 스토리였는데, **세 개의 독립 측정이 그 축을 판정 불가로 만들었다**: (1) HIGH 후보 6장 블라인드 재판독에서 1·2차가 **0.07~0.13** 어긋남(밴드는 ±0.05), (2) **같은 이미지 5장**을 독립된 두 블라인드 판정자가 재니 **범주 뒤집힘 2/5** · |Δy_h| 최대 **0.12** 평균 0.072, (3) 범주 폭이 0.20인데 오차가 ±0.10 수준이라 **경계 근처 배정이 동전던지기**다. 그리고 **텍스트로 시점을 만들 수도 없다** — 변형 `d`(부감)/`e`(앙각)를 신설해 20장을 렌더했더니 목표 범주 도달 **2/20**, 승인 통과 **1장**이고 `containment-chamber/e`는 앙각 지시에 **네 롤 전부 부감**으로 나왔다(14.1의 `b` 2/14 재현). 부수로 `medical-bay/b`가 **단일 소실점이 없는** 플레이트임이 드러났다. **Jay 결정 (B): 매칭 규칙 자체를 교체한다** — (A) HIGH/LOW 셀 제외는 결과 보고 기준 낮추기라 기각, (C) 판정자 3인 다수결은 2/20 문제를 못 건드려 기각, (D) 영구 OFF는 이르다. 재작성된 스토리는 **Phase 1 리서치 게이트**(후보 축을 열거하고 **재현 오차 < 허용 폭**을 만족하는 것이 있는지 심사, 없으면 그것이 결론이고 HALT) + **Phase 2 출하** 구조다. 기존 42장의 `viewpoint`도 **단일 판정자 1회 값**이므로 새 축이 정해지면 다시 측정한다(덮어쓰지 않고 병기). 근거: `14-1-approved-plate-sets/{AUGMENTATION-BATCH,REREAD}-2026-08-30.md`. (ready-for-dev)

### Story 14.8: 배경 플레이트 재활용을 실제로 출하한다

**에픽의 중심 명제가 아직 한 번도 출하되지 않았다.** *"샷마다 생성하는 대신 승인된 세트에서 고른다"*가 이 에픽의 명제인데 `stock_plate_substitution_enabled: bool = False`(`config.py:358`)라 run `4b35c0ed`은 **43/43 샷이 자유생성**이었다. 승인 플레이트 42장과 14.1이 만든 샷 단위 선택기가 있는데 런타임이 한 장도 쓰지 않는다. 14.1은 8.17의 씬 키잉 붕괴(배경 155→41)를 은퇴시켰고, 남은 것은 켜는 일이다.

**해제 조건은 둘이고 AND다**(`config.py:326-334`가 정본): **(a)** 측정 커버리지가 사전등록 C1/C2/C3 통과 — 2026-08-25 측정에서는 미달, **(b)** 치환을 켠 E2E에 대한 **Jay 시청 판정**(선례 만장일치 — 10.1c·10.5·10.1e·14.2). **(a)의 부족분은 이미 렌더됐다**: `e707482`이 HIGH 3셀을 블라인드 재판독해 42장 중 **HIGH 0장**을 확정하고 증설 명세를 **5장(LOW 2 + HIGH 3)**으로 확정했으며, 그 5장이 지금 `assets/locations/`에 **draft**로 있다(`observation-room/d,e` · `containment-chamber/e` · `medical-bay/d` · `corridor/d`). 이 스토리는 그 5장을 라벨·측정·승인시켜 (a)를 판정하고, 통과하면 플래그를 **코드 기본값으로** 올린 뒤 (b)를 위한 E2E iteration 5를 만든다.

⚠️ **되살리면 안 되는 반증된 전제 둘.** ① **릴라이트 결합은 해제 조건이 아니다** — 14.1의 report·epics·deferred-work·epic-14-context 넷이 *"(c) 릴라이트 결합 수정"*을 실었으나 **14.3이 반증해 철회했다**(`c75b123`): 페어 키를 만드는 `precompute_relights`는 `composite_harmonization_tier >= 3`에서만 도달 가능한데 출하 tier는 1이고 tier 3은 10.1b 시청 기각이다(`test_precompute_relights_is_unreachable_at_the_shipped_tier`가 고정). 결함 자체는 실재하나 **이 플래그와의 연결**이 철회됐다 — 이 프로젝트 세 번째 원인 역전(`gotcha_recorded-root-cause-can-be-inverted`). ② **`image_prompt` 의미 정합은 이 스토리 밖이다** — 선택기는 `camera_angle`·`cast`·`location_key`만 읽고 프롬프트를 통째로 버리며, `location_key`는 방이지 씬이 아니라 한 방 안 서로 다른 두 샷이 구분되지 않는다. 이것은 **선언된 감수 리스크이고 게이트 조건이 아니다**((b)가 판정한다).

**측정 함정 셋**(전부 실측된 것): 재현 오차가 사전등록 밴드보다 크다(corridor 3장에서 1·2차 판독 **0.07~0.13** 차, 밴드는 ±0.05 → **두 판정 병기, 덮어쓰기 금지**); `medical-bay/b`는 **단일 소실점이 존재하지 않는다**(시점 라벨과 별개의 품질 결함); 판독은 **블라인드**여야 한다(주 에이전트가 1차 값을 본 뒤 재판독하면 오염 — `e707482`은 저장소 문서 비열람 판정자를 썼다). 그리고 **기준을 결과에 맞춰 낮추지 마라** — `PREREGISTRATION.md §5`가 *"HIGH 0장이면 기준 도달 불가가 아니라 세트 부족이며 부족분으로 보고한다"*를 미리 적어뒀다.

**인계 전제**: 켜지면 `location_key` 보유 **31/43** 샷이 `image_prompt`를 생성에 쓰지 않으므로 **14.5가 건드린 프롬프트 층의 도달 범위가 43/43 → 12/43**으로 준다(이후 프롬프트 측정은 그 분모를 명시할 것). `close-up` 6샷 + `POV` 1샷은 **설계상 영구 폴백**이고 결함이 아니다(C3 분모 24샷이 그것을 뺀 수). 14.2 어포던스 게이트도 `False`이고 `standing_room` 필터가 그 노브 뒤에 있으므로(14.1 D2) **함께 켤지를 명시적으로 결정**해야 한다 — C2가 존재하는 이유가 그것이다. 파일: `14-8-plate-reuse-shipping.md`.

**2026-08-30 축 교체를 출하했고 플래그는 켜지 않았다(GPU 0·VLM 0·렌더 0).** Phase 1의 심사 기준은 `(b) 재현 오차 < (c) 허용 폭` 하나였고 통과한 후보는 **② 시점을 안 쓰는 축**뿐이다(`location_key` + people-free + 어포던스, `viewpoint`는 선택에서 안 읽음). ①은 커밋된 구현이 없고 임시 판본이 같은 이미지에 **0.93/0.97/0.41**로 발산(민감도 0.56 > 범주 폭 0.20), ③은 스코어러도 임계값도 없어 (c) 미정의, ④는 판정자 간 오차 0.072가 **키 내부 최소 간격 중앙값 0.010**보다 커서 수요 6키 전부에서 랭킹이 노이즈다. **2-경로 P1 = 1/42 = 2.4% < 밴드 5.0% PASS**(밴드는 `d797a8a`에 측정 전 커밋). 커버리지 **C1′ PASS 6/6키 · C2′ PASS · C3′ PASS 24/24 = 100.0%**, 옛 축 대조군은 같은 명령이 한 화면에 찍고 **재현을 단언한다**(C1 FAIL 5/10 · C3 FAIL 17/24 = 70.8%; 재현 실패 시 exit 4로 죽고 델타를 인쇄하지 않는다). servable 분모 **24**와 `C3_MIN_SHARE=0.90`은 한 글자도 안 바꿨다.

⚠️ **그러나 C1′·C2′·C3′는 셋 다 반증 불가다.** 승인 42장 전수 대조(`PREREGISTRATION.md` §7, 이번에 신설): 14키 전부 승인 3장씩, `depicts_person=true` **0/42**, `label.has_person=true` **1장**(수요 밖 키), 어포던스 노브 OFF → C1′ MISS 불가 · C3′는 그 대수적 귀결 · C2′는 런타임 배정을 못 바꾼다. 셋 다 **`VACUOUS`로 표기**하고 그 위에 어떤 결정도 세우지 않는다. **정보성 숫자는 C4′ = 7/24 하나다**: 옛 축이 `no_viewpoint_match`로 거절하던 7샷(고 4·저 3)이 전부 눈높이 플레이트를 받고, 그중 **5샷이 cast**(카드 6장)라 부감·앙각 카드가 눈높이 배경에 합성된다(`camera_angle`은 render-inert가 아니다 — `character_service.py:1556`). **이것은 커버리지 숫자가 아니라 시청 판정이고 Jay의 E2E iteration 5 몫이다.**

**플래그는 `False`로 남는다**(`DECISIONS` 행도 없음). 해제 조건 (a)∧(b) 중 (a)는 문자 그대로 충족됐으나 그 충족이 반증 불가한 기준 위에 서 있고, **(b) Jay 시청 판정이 유일한 잔여 조건**이다. E2E는 `YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true` **env 오버라이드**로 그 한 런만 켠다 — `env_prefix="YTFLOW_"`가 있으므로 "켜야 E2E를 돌린다"는 교착은 **존재하지 않는다**(앞선 반복이 그 거짓 교착으로 기본값을 뒤집었다가 리뷰에서 되돌려졌다). reason 어휘 7 → **5**(`no_viewpoint_match`·`partial_metadata` 은퇴). 부수 수정: 풀 진입 센티널을 `viewpoint`→사람 판정으로 이동, D1을 D2와 같은 `is False` 규약으로 통일(부재=판정불가, 오늘 코퍼스에서 비용 0), 재생기 로더가 런타임과 같이 `label OR plate_meta`를 접도록 수정, 사이드카에 `axis` 마커 추가(resume 경계). ⚠️ **spec이 틀린 두 곳**: reason 어휘 독자는 넷이 아니라 **다섯**(`tests/domain/test_run_warnings.py` 누락, `test_gates.py:258`은 warning code); spec Design Notes가 2-경로 입력으로 지목한 `has_person` OR은 이 코퍼스에서 **피연산자 하나로 돈다**(P2·P3 `UNDEFINED`, PASS 아님). 인계: `(b)<(c)` 게이트 형식 편향, 14.4 가드가 플레이트 경로에서 무효, `_manifest_assets` fail-open, draft 라벨 14/42(**5샷에 실제 배정**), `medical-bay/b` 소실점 부재, 프롬프트 층 43/43 → 12/43. 근거: `14-8-plate-reuse-shipping/{AXIS-CANDIDATES,PREREGISTRATION,report}.md`. **AC6(E2E iteration 5)은 미완이다.** (in-progress)


**2026-08-30 CLOSED.** 축은 교체됐고 **플래그는 켜지 않았다.** Phase 1이 후보 4축을 `(b)<(c)`로 심사해 **②시점 미사용 축**(`location_key` 단독)을 채택했다 — ①기하추정기는 커밋된 구현이 0건이고 인용 가능한 유일한 수치가 0.56>0.20, ④연속거리는 키 내부 간격 중앙값 **0.010**이 판정자 오차 0.072보다 작아 랭킹이 노이즈, ③내용정합은 (c)가 정의되지 않는다. servable **17/24 → 24/24**(4b35c0ed) / **19/19**(780cb8b3, 옛 축 14/19). **그러나 새 커버리지 기준 셋이 전부 반증 불가(`VACUOUS`)** — 14키 전부 승인 3장씩이라 C1′는 MISS가 불가능하고 C3′는 그 귀결이며 C2′는 어포던스 노브 OFF라 배정을 못 바꾼다. 그래서 해제조건 **(a)도 (b)도 열려 있고** 코드 기본값은 `False`, `DECISIONS` 행 없음. 기준은 낮추지 않았다. **E2E iteration 5**(run `780cb8b3`, 3분12초)로 치환이 이 프로젝트에서 **처음 발화**했다(19/41, env 오버라이드). ⚠️ 어떤 기준도 재지 않은 결함이 나왔다: **플레이트 컷과 생성 컷의 화풍이 다르다** — 체크포인트·LoRA는 동일하고 갈리는 것은 조건화(플레이트만 IPAdapter 앵커 0.4 + ControlNet, 프롬프트 출처 상이)이며, 이는 **Story 14.3의 미완 절반**이 치환을 켜는 순간 화면에 나온 것이다(그레이드 이후엔 원본만큼 극단적이지 않다). 리뷰 2패스에서 첫 시도가 (b) 미충족 상태로 기본값을 뒤집었다가 되돌려졌고, 되돌리지 않았다면 이 두-화풍이 출하 기본값으로 나갔다. 남은 것은 **Jay 시청 판정 = 조건 (b)** 하나. 증거 `14-8-plate-reuse-shipping/`.
### Story 14.9: recompose 배치·척도 — 진단된 한 줄을 고치고 3-arm으로 증명한다

②의 recompose 측 절반. 14.3이 닫은 것은 **귀속 경로**였고 결함 자체는 안 고쳤다. `config.py:554-560`이 **13일간 진단을 적어두고 있었다** — `_DEPTH_PHRASE["near"]`가 *"in the foreground close to camera"* 와 *"his whole body from head to feet visible in frame"* 를 함께 요구하는데 16:9에서 양립 불가라 모델이 **인물을 키워** 둘 다 만족시킨다(Jay가 10.1e 시청과 E2E iteration 4에서 두 번 제기). 안 고친 이유는 성능이 아니라 **무효화 범위**였다(43-plate 스윕 + 10.1e 검증 슬레이트). 그 위에 어제까지 *"이 박스에 GPU가 없다"* 는 **거짓 전제**가 얹혀 있었다(`GPU-PREMISE-CORRECTION-2026-08-30.md` — `nvidia-smi`로 AMD 박스를 진단했다). **Jay 결정 (A): 지금 고친다.**

표적 7샷 = 14.2 인계 3건(`S00105` `S00504` `S00803`) ∪ Jay 2026-08-30 블라인드 판정의 합성 부류 5건(`S00504` `S00702` `S00800` `S00802` `S00904`). **수정은 한 줄이고 근접 절만 제거**했다 — 전신 절을 대신 지우는 후보는 `S00403`에서 실측된 얼굴 클로즈업 회귀 때문에, 척도 앵커를 **추가**하는 후보는 이미 접지·조명·화풍 절을 실은 문장에 지시를 더 넣는 형태라 텍스트 스크리닝에서 기각했다.

**3-arm 설계**: A(출하 프레임) / B(현 문구 + 새 시드) / C(수정 문구 + **B와 같은 시드**). B가 없으면 다시 뽑기 노이즈가 편집 공로로 계상된다(`gotcha_regeneration-needs-a-same-prompt-control`, +7.14pp 전례). **최대 함정은 digest였다** — `recompose_service`의 캐시 digest는 플레이트 바이트·카드 경로·배치 필드만 해싱하고 **프롬프트도 시드도 안 넣으므로**, `recompose_run_shots`로 arm C를 렌더하면 캐시 히트가 나고 **arm C가 조용히 arm A가 된다**(에러도 로그도 없이 `stats`는 `recomposed: 7`). 그래서 B·C는 캐시 검사가 없는 `shot_recompose.recompose_shot`을 직접 부르고 출력을 `recomposed/` **밖**에 쓴다. 시드 레버도 코드에 없어(워크플로 JSON의 `sampler.seed`가 유일) 워크플로 파일을 복사했다.

**✅ 2026-08-30 in-review (dcf65b8) — 기계적 부분 종결, Jay 판정 대기.** Block If 셋 전부 통과했고 핵심은 **digest 재현 7/7**이다: 이 런은 14.3 **이전**이라 사이드카에 귀속 블록이 없고(40개 전수, 0건) 카드 경로가 어디에도 없어서, 깨끗한 플레이트 + 재해결 카드로 digest를 재계산해 파일명의 16-hex와 대조하는 것이 *"B가 A의 대조"* 라는 **유일한 증거**였다(불일치했다면 실험 전체가 무의미). 대조 조건 기계 확인: B·C 시드 `20260830` + 워크플로 sha 동일, 처치 패스 **단일치환 4/4**, 비처치 패스 **바이트 동일 7/7**, 무효 대조군 3샷 전 패스 동일. **arm A 무손상**(`recomposed/` 33파일 sha256 렌더 전후 동일). 렌더 14/14, 패스당 ~57초, 총 21.6분. 도중 ComfyUI가 죽어(B 7/7, C 5/7) **B·C를 같은 세션에서 전부 재렌더**했다 — 이어 붙이면 프로세스 간 비결정성이 교란으로 섞인다(이전 산출물은 `*.precrash/`로 보존). 판정 산출물은 **`blind_sheet.jpg`** 21타일이고 **행마다 열 순서를 치환**했다(abc/bac/bca/cab). 사전등록 §6이 SHIP(처치 4샷 중 ≥3) / REVERT(≤1) / UNDECIDED(2)를 렌더 전에 고정했고, **VETO**가 그 위에 있다 — 지시문이 바이트 동일한 무효 대조군 3샷에서 Jay가 B와 C를 2샷 이상 갈라내면 편집 효과가 렌더 비결정성과 같은 급이므로 **"결론 없음"** 이다. **n=4는 유의성이 아니라 스크리닝**이고 SHIP은 "고쳐졌다"가 아니라 "다음 E2E iteration에 태울 근거"를 뜻한다. **미주장**: 사람 판정 0회 / 10.1e 슬레이트 재검증은 다음 E2E 몫 / arm A는 2026-08-17 렌더라 A↔B 차이에는 시드 차이와 스택 변화가 함께 들어 있다(통제된 대조는 **B↔C**). 동반으로 오늘 오전 `VARIANTS` 확장이 낸 회귀 4건(다른 파일 테스트가 "키당 변형 3개"를 하드코딩)도 수정했다. 근거·재산출: `implementation-artifacts/14-9-recompose-placement-scale/`. (in-review)

### Story 14.10: 카드에도 승인 시점 측정 축을 붙인다 — 라벨이 픽셀과 어긋난다

**2026-08-30 신설.** Jay가 `S00504`를 *"위에서 아래를 내려다보는 앵글인데 캐릭터는 앞모습"* 으로 **세 arm 전부 기각**한 것을 좇다가 나왔고, **이 샷 하나의 문제가 아니었다.** 그 샷이 쓴 카드는 `STOCK-d-class/epoch_2/back_candidate_1.png` 인데 **명백한 정면 이미지**다(얼굴, 가슴 `225` 번호판, 중앙 앞지퍼, 정면 부츠 — 주 에이전트 육안 독립 확인). **모델은 카드를 충실히 따랐고 거짓말한 것은 라벨이다.**

**모집단 전수**(파일명·문서 비열람 판정, 판정마다 픽셀 증거 인용): `back_candidate_1.png` **12장 중 4장이 FRONT**(33% 오류) — `SCP-049-2/e1` · `SCP-1471/e1` · `STOCK-d-class/e2` · `STOCK-security/e1`. 대조군 6장도 완전 일치 3 / 부분 불일치 2(`side` 선언인데 three-quarter) / **완전 불일치 1**(`STOCK-d-class/e2/side_candidate_1.png` 이 정면). 덤으로 `SCP-1471/e1` 은 알파 없는 **5인 시트**, `SCP-682/e1` 은 **풍경 장면**이라 애초에 카드가 아니다.

**구조적 갭**: 14.1이 플레이트에는 승인 시점 측정 축(`viewpoint`·`standing_room`·`depicts_person`)을 붙였는데 **카드에는 대응물이 없다** — `approve_stock_cast.py` 가 재는 것은 `has_alpha` + `sprite_contract` 둘뿐이고 둘 다 *"이 PNG가 스프라이트인가"* 를 물을 뿐 *"이 그림이 라벨대로 뒤를 보고 있는가"* 는 **아무도 묻지 않는다**. 그래서 `character_service:1500` → `_select_entity_angles` → `angle_*_path` 로 정면 카드가 뒷모습 요구 샷에 들어가고, recompose가 참조 자세를 보존해 프레임에 그대로 나온다.

**14.9가 인계한 `S00504` 시점 불일치를 이 스토리가 흡수한다** — 라벨 결함이 그 절반을 설명하고 나머지 절반의 크기는 라벨을 고치고 재렌더해야 알 수 있다. AC4가 그 분리를 담당하며 **남는 몫이 0이면 새 층을 만들지 않는 것이 정답**이다. ⚠️ **축을 만들기 전에 판정 가능성부터 심사한다**(14.8이 `viewpoint` 에서 그 검사를 안 하고 시작했다가 축을 은퇴시켰다). 방향은 시점보다 유리할 근거가 있다 — 범주가 이산이고 증거가 국소적이다. **함정**: BACK 8장 중 3장이 **몸은 뒤인데 머리만 돌려 얼굴이 보이므로**, 얼굴 유무로 판정하면 그 셋을 뒤집는다. 판정 규칙은 몸 단서여야 한다. **⚠️ 2026-08-30 E2E iteration 5(`780cb8b3`)가 이 스토리를 두 배로 키웠다.** (1) **원인이 그 5장보다 크다** — 38패스 중 14건이 어긋나고 그중 §A 목록에서 오는 것은 **3건**뿐이다. `three_quarter`/`side` 라벨의 **다른 4장이 정면**이며 `SCP-049/e1/three_quarter` **하나가 6패스**를 몬다. 이 런이 쓴 20장 중 **6장(30%)** 오라벨 = **계통적 결함**이다. **그리고 목록 자체에 오류가 있다** — 두 행이 `epoch_1` 인데 이 런은 `epoch_2` 형제를 썼고 그 둘은 라벨이 옳다. **epoch 없이 인용하면 멀쩡한 카드 둘을 기소한다.** (2) **결함이 둘이다 — 컷아웃 실패 카드가 계약을 통과한다.** 69장 전수 `opaque_fraction`: 정상 56장 중앙값 **0.280**(최대 0.390) vs **배경 박힌 5장 0.443~0.562**, 그 사이가 **비어 있다**. 다섯 장 전부 `sprite_contract` 통과이고 `three_quarter_candidate_1` 의 `alpha_bbox` 는 캔버스를 거의 채운다. **계약의 버그가 아니라 누락된 축이다** — `has_alpha`(선언)와 `sprite_contract`(실측 알파)는 둘 다 **컨테이너**를 재고 **그림의 내용**을 재는 축이 하나도 없다. recompose는 카드를 **참조 이미지**로 받으므로 배경이 박힌 카드는 *"다른 방이 뒤에 붙은 인물"* 을 참조하라는 뜻이고, 그 카드가 6패스를 돌았다(누출 크기는 미측정, AC8이 잰다). 부수: 알파 없는 8장은 계약이 **정확히 거부**하는데 그중 하나가 `angle_back_path` 에 앉아 있다 — 계약이 **비소급**이다. 파일: `14-10-card-orientation-contract.md`. (backlog)
