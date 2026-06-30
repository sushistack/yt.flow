# CLAUDE.md — yt.flow

## Project Overview

Python rewrite of the yt.pipe Go implementation. SCP Foundation YouTube content automation pipeline.
LangGraph orchestration + Langfuse Prompt Hub + runtime tracing.

**Source project reference**: `/mnt/work/projects/yt.pipe`

## Code Philosophy — Ponytail (always active)

This project runs **Ponytail full mode** by default. Follow the ladder on every implementation:

1. **Does this need to exist?** YAGNI — speculative need = skip it
2. **Stdlib does it?** Use it
3. **Native platform feature covers it?** Use it
4. **Already-installed dependency solves it?** Use it. Never add a new one
5. **Can it be one line?** One line
6. **Only then:** the minimum code that works

**Rules:**
- No interface with one implementation
- No boilerplate scaffolding "for later"
- Deletion over addition
- Mark deliberate simplifications with `# ponytail:` comment

## Build & Run

_TBD — fill in after initial project setup_

## Architecture

- **Orchestrator**: LangGraph (Python)
- **LLM tracing + prompt management**: Langfuse (self-hosted Docker)
- **Pipeline stages**: scenario → image → tts → subtitle → video
- **Design details**: see `_bmad-output/brainstorm-intent.md` and PRD

---

# BMAD Method v6.0.4

This project is managed with the BMAD methodology.
Config: `_bmad/_config/` and `_bmad/bmm/`
Artifacts: `_bmad-output/`
