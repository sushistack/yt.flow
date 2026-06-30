---
title: yt.flow — Python/LangGraph SCP Content Pipeline
status: final
created: 2026-06-30
updated: 2026-06-30
---

## Problem Statement

The existing Go pipeline (`yt.pipe`) produces inconsistent output quality with no way to diagnose root cause. Two structural blind spots block iteration:

1. **Stage observability gap** — when a video has quality issues, there is no way to determine which stage (scenario, image prompt, TTS, subtitle) is responsible.
2. **Prompt management gap** — prompts are embedded in source code; changing a prompt requires a code change and redeploy.

These blind spots make it structurally impossible to improve output quality systematically. The Go implementation is abandoned; this is a clean-cut Python rewrite.

---

## Vision

A local pipeline where any quality issue can be diagnosed to a specific stage and its prompt within 30 minutes, and where prompt variants can be compared automatically — so iterating on content quality is a matter of editing and testing, not debugging and deploying.

---

## Goals & Success Metrics

**Scope principle:** This rewrite exists to enable eval and tracing — not to expand features. Any capability not present in the Go pipeline is out of scope unless it directly enables observability or A/B evaluation.

| Goal | Metric |
|------|--------|
| Fast quality diagnosis | Root-cause stage identifiable via Langfuse traces within **30 minutes** of issue detection |
| Prompt management | Prompt change reflected in next run with **zero code change or redeploy** |
| A/B evaluation | Given the same SCP input, prompt A vs. B produces a scored comparison automatically |
| Pipeline completeness | Full run produces a deliverable video: scenario → image → audio → subtitle → video |
| Performance | End-to-end run completes within **2 hours**; quality takes priority over speed |

**Counter-metrics** (must not regress):

- Langfuse trace overhead must not add >10% to total pipeline run time.
- A/B evaluation must not require manual scoring to reach a verdict.

---

## Features

### F1 — Pipeline Core (LangGraph)

Each stage is a discrete LangGraph node. Node boundaries are the unit of observability and resume.

| ID | Requirement |
|----|-------------|
| FR-1 | Accept SCP article text as input and generate a structured scene scenario via DeepSeek V4 |
| FR-2 | Generate an image prompt per scene from the scenario via DeepSeek V4 |
| FR-3 | Submit image prompts to ComfyUI local HTTP API and retrieve generated images |
| FR-4 | Generate TTS audio per scene via Qwen TTS (latest) |
| FR-5 | Generate subtitles via forced alignment — script text is known from the scenario stage; align timing against TTS audio output |
| FR-6 | Compose scene images, audio, and subtitles into a final video via FFmpeg subprocess |
| FR-7 | Resume from last successful node after failure |
| FR-8 | Support full restart (from FR-1) as an explicit option |
| FR-9 | After each stage completes, pause execution and emit a gate-pending event; proceed only when the user approves via FR-29 |

### F2 — Observability (Langfuse)

Langfuse is self-hosted on homelab-gitops infrastructure.

| ID | Requirement |
|----|-------------|
| FR-10 | Every LangGraph node emits a Langfuse trace span on entry and exit |
| FR-11 | Each LLM call captures: rendered prompt, raw LLM response, latency, token count |
| FR-12 | Trace spans are linked per pipeline run so a full run is inspectable as one trace tree |
| FR-13 | A failed node surfaces error detail in the trace (exception, inputs at failure point) |

### F3 — Prompt Management (Langfuse Prompt Hub)

Existing `.tmpl` files from `yt.pipe/templates/` are migrated to Langfuse Prompt Hub as the first implementation step, before pipeline nodes are built.

| ID | Requirement |
|----|-------------|
| FR-14 | All pipeline prompts stored and versioned in Langfuse Prompt Hub |
| FR-15 | Pipeline nodes fetch prompts from Prompt Hub at runtime (no hardcoded strings) |
| FR-16 | Prompt change takes effect on next run without code change or service restart |
| FR-17 | Prompt version history and change audit available in Langfuse UI |

### F4 — A/B Testing & Evaluation

| ID | Requirement |
|----|-------------|
| FR-18 | Given the same SCP input, execute the pipeline with prompt variant A and variant B |
| FR-19 | LLM-as-judge evaluation: score each output against SCP-specific criteria (atmosphere, narrative coherence, article fidelity) |
| FR-20 | Rule-based evaluation: score each output against structural metrics (scene count, subtitle sync, audio length variance) |
| FR-21 | Combined evaluation result stored in Langfuse as a scored comparison trace |
| FR-22 | A/B result retrievable via API |
| FR-23 | A winner is determined automatically by combined score; no manual scoring step required (see OQ-6 for threshold definition) |

### F5 — API Interface (FastAPI)

Local-only; no authentication required.

| ID | Requirement |
|----|-------------|
| FR-24 | `POST /runs` — trigger a pipeline run with SCP input (`scp_id`, `scp_text`), optional prompt variant config, and optional `extra: dict` (reserved, ignored in v1, for future content-type extensibility) |
| FR-25 | `GET /runs/{id}` — retrieve run status and Langfuse trace URL |
| FR-26 | `GET /runs/{id}/artifact` — return the output video as a file download (HTTP 200 with content-disposition) or redirect to a local file path |
| FR-27 | `POST /runs/{id}/ab` — trigger A/B evaluation for a completed run |
| FR-28 | `GET /runs/{id}/stages/{stage}/artifacts` — return intermediate artifacts for a completed stage (images, audio, text) |
| FR-29 | `POST /runs/{id}/stages/{stage}/gate` — accept `{"action": "approve" \| "reject"}` to release or abort the pipeline at a stage gate |
| FR-30 | `POST /runs/{id}/stages/{stage}/retry` — re-execute a specific stage using current prompt config |
| FR-31 | `GET /runs` — list all runs with status, timestamps, and stage gate state |
| FR-32 | `GET /runs/{id}/progress` — SSE stream emitting stage entry/exit events and gate-pending notifications in real time |
| FR-33 | `GET /scps` — return list of available SCP entries (id, nickname, object_class, rating) read from local SCP facts file; used by UI SCP Picker |
| FR-34 | `PATCH /runs/{id}/stages/{stage}/artifact` — accept edited text body; update LangGraph checkpoint via `graph.update_state()` and rewrite artifact file on disk; valid for `scenario` and `subtitle` stages only |

### F6 — Data & Job Management

| ID | Requirement |
|----|-------------|
| FR-35 | SQLite database stores run metadata (id, status, current_stage, gate_states, prompt_variant, ab_pair_id) as API projection; LangGraph SqliteSaver checkpoint is the authoritative state store |
| FR-36 | Node-level checkpoint persisted after each successful node via LangGraph SqliteSaver (enables FR-7) |

### F7 — Web UI (React SPA)

React SPA served by FastAPI (static build). Each stage pauses at completion and waits for user approval before the pipeline proceeds.

**UI implementation directive:** Use the `frontend-design` skill (Claude AI) for all component design, layout, and visual hierarchy decisions — maximize Claude's design capabilities throughout F7 development.

| ID | Requirement |
|----|-------------|
| FR-37 | Dashboard: list all runs with status, current stage, and gate state (pending approval / approved / rejected / failed) |
| FR-38 | Run detail: real-time stage progress via SSE — each stage shows running / awaiting approval / approved / rejected |
| FR-39 | Stage artifact preview panel — scenario text (readable), generated images (gallery), TTS audio (playable), subtitle file (readable), final video (playable) |
| FR-40 | Stage gate controls — Approve and Reject buttons visible when a stage is awaiting approval; pipeline does not advance until approved |
| FR-41 | Stage retry button — re-execute a specific completed or rejected stage; launches new stage run with current prompt config |
| FR-42 | A/B comparison view — side-by-side display of variant A and B artifacts with evaluation scores (LLM-as-judge + rule-based) and winner indicator |
| FR-43 | Link to Langfuse trace per run (opens in new tab); prompt editing deferred to Langfuse UI |
| FR-44 | Inline text editor for scenario and subtitle stages — "편집" button toggles textarea; "저장" calls FR-34 PATCH endpoint; pipeline does not advance until "승인" is clicked separately |

---

## Non-Functional Requirements

| Concern | Requirement |
|---------|-------------|
| Deployment | Pipeline: local execution. Langfuse: homelab-gitops (self-hosted Docker/k8s) |
| Performance | End-to-end video generation ≤ 2 hours; quality over speed |
| Observability overhead | Langfuse tracing adds ≤ 10% to total run time |
| Storage | SQLite flat file; no external DB |
| Authentication | None — local-only deployment, single operator |
| External dependencies | DeepSeek V4 API, Qwen TTS API, ComfyUI (local HTTP), Langfuse (homelab) |
| Error visibility | Any run failure surfaces the failed node, inputs, and exception in the Langfuse trace |
| Resume granularity | Resume at node level (not scene level) — a mid-stage failure (e.g., TTS fails on scene 8 of 20) restarts that entire stage; accepted trade-off for implementation simplicity |
| Data retention | Runs older than 30 days are eligible for manual cleanup; no automatic deletion. Artifact files (images, audio, video) are not auto-purged |
| Model versioning | DeepSeek and Qwen TTS model identifiers must be pinned in config (not hardcoded); updating a model requires a config change, not a code change |
| Performance bottleneck | The 2-hour ceiling is dominated by ComfyUI image generation time, not LLM or TTS API calls |
| Human gate latency | The 2-hour NFR covers automated processing time only; human approval wait time is excluded |
| UI technology | React SPA; FastAPI serves the static build under `/app`; no separate web server |
| Real-time transport | SSE (Server-Sent Events) for progress and gate notifications; WebSocket not required |

---

## Out of Scope

- Runtime prompt hot-swapping (Langfuse fetch-on-run already covers this)
- Multi-user access or API authentication
- CLI interface — FastAPI REST only; the Go cobra CLI pattern is not carried forward
- Go/Python hybrid or incremental migration — big-bang cutover chosen to avoid maintaining a dual-stack adapter layer
- New pipeline stages beyond: scenario → image → TTS → subtitle → video
- LangSmith or any alternative to Langfuse

---

## Open Items

| ID | Item | Owner | Revisit condition |
|----|------|-------|-------------------|
| OQ-1 | ~~LLM-as-judge criteria~~ — resolved: 3-axis rubric (1–5 integer each), 3-run average. Axes: **Atmosphere** (SCP clinical-horror register), **Narrative coherence** (scene flow + entity consistency), **Article fidelity** (facts, object class, containment accuracy). Chain-of-thought before scoring. Total score = sum of 3 axes (3–15). | — | Closed |
| OQ-2 | ~~ComfyUI workflow/checkpoint config~~ — resolved: baseline is `comfyui_sdxl_anime_lora_workflow_api2.json` (`~/Documents/myWorkflows/`); copy to `data/workflows/` in yt.flow. Stack: `animagineXL_v31.safetensors` + `horror_and_creepy.safetensors` LoRA (0.6) + `darkness_sdxl_v2.safetensors` LoRA (0.5); 1216×832, 30 steps, dpmpp_2m+karras, cfg 7.5. Prompt injection point: node 6 (positive) and node 7 (negative) in workflow JSON. | — | Closed |
| OQ-3 | ~~SQLite schema design~~ — resolved: SQLModel ORM; runs table as API projection; LangGraph SqliteSaver owns checkpoints; single SQLite file | — | Closed |
| OQ-4 | ~~Qwen TTS hosting~~ — resolved: cloud API; rate limits not a throughput concern (ComfyUI dominates) | — | Closed |
| OQ-5 | ~~Future generic pipeline scope~~ — resolved: v1 schema is SCP-specific (`scp_id`, `scp_text`) but designed for forward extension. `POST /runs` accepts an optional `extra: dict` field (ignored in v1, reserved for future content-type metadata). `GET /scps` is SCP-specific; future content types will get their own `GET /{content_type}s` endpoints. No breaking changes needed to add a new content type alongside SCP. | — | Closed |
| OQ-6 | ~~A/B winner threshold~~ — resolved: pairwise comparison (position-bias mitigated via order reversal, 2/3 majority). Tie → rule-based tiebreaker (scene count match, subtitle sync ≤0.5s/word, audio duration variance ≤10%). Minimum quality floor: all 3 axes ≥2/5 required; if both variants fail floor, no winner declared. | — | Closed |
| OQ-7 | ~~LangGraph state schema~~ — resolved: TypedDict; PipelineState with scenes: list[SceneState]; ShotData uses sentence_indices (LLM-Director pattern, CoAgent-style N:M mapping) | — | Closed |
| OQ-8 | ~~Stage gate scope~~ — resolved: every stage requires approval (scenario → image → tts → subtitle → video all gate). Not configurable per-run; simplicity over flexibility. | — | Closed |
