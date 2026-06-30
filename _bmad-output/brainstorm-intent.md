# Intent: yt.pipe — Python/LangGraph Rewrite

## Source Project Reference

The existing Go implementation being replaced lives at `/mnt/work/projects/yt.pipe`.
Key reference files:
- Architecture & conventions: `/mnt/work/projects/yt.pipe/_bmad-output/project-context.md`
- Prompt templates: `/mnt/work/projects/yt.pipe/templates/`
- Domain models: `/mnt/work/projects/yt.pipe/internal/domain/`
- Pipeline stages: `/mnt/work/projects/yt.pipe/internal/pipeline/`

## Problem Statement

The current Go pipeline produces inconsistent output quality but provides no per-stage observability: it is impossible to pinpoint which stage (scenario, image prompt, TTS, subtitle) is responsible for a quality failure. Prompts are buried in source code, making both design-time auditing (which stage uses which template) and runtime inspection (what was actually rendered and returned) opaque. Without evaluation and tracing infrastructure, iterating on LLM quality is structurally blocked.

## Chosen Direction

- Full rewrite in Python; the existing Go codebase is abandoned
- Orchestration layer: **LangGraph** — models each pipeline stage as a discrete node, providing per-node visibility and control flow
- Observability + prompt management: **Langfuse** (self-hosted via Docker)
  - Prompt Hub for versioned, auditable prompt storage with A/B testing support
  - Runtime tracing to capture rendered prompts and LLM responses at every node
- The two black-box problems are solved together: Langfuse Prompt Hub eliminates the design-time blind spot; LangGraph + Langfuse tracing eliminates the runtime blind spot

## Key Constraints

- LangGraph has no production-ready Go implementation — Python rewrite is the only practical path to LangGraph adoption
- Langfuse must be self-hosted (Docker); no SaaS dependency
- Pipeline semantics are preserved: SCP text → scenario → image generation → TTS → subtitle → video render
- The primary goal is eval/tracing capability, not feature expansion; the rewrite scope is bounded by existing pipeline functionality

## Out of Scope

- Runtime prompt hot-swapping (rejected: not needed for local system)
- LangSmith (Langfuse chosen as the single observability + prompt management platform)
- Incremental migration or Go/Python hybrid — clean cut only
- New pipeline stages or content types beyond the current SCP workflow

## Open Questions

- What is the target Langfuse self-host topology (single Docker Compose, separate infra)?
- Which LangGraph state schema replaces the current Go domain models (project, scene, scenario, manifest, job)?
- How is the existing SQLite store migrated — schema-compatible Python ORM, or redesigned?
- What replaces the current cobra CLI + chi REST dual-interface pattern in Python (FastAPI? Typer? both)?
- What is the FFmpeg integration strategy — subprocess wrapper, or a Python FFmpeg library?
- Are existing prompt templates (`.tmpl` files under `templates/`) migrated into Langfuse Prompt Hub as the first step, or developed in parallel?
- Phasing: big-bang cutover or stage-by-stage node replacement with a temporary adapter layer?
