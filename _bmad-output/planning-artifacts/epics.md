---
stepsCompleted: ["step-01", "step-02", "step-03", "step-04"]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md
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
