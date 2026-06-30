---
type: architecture-review
reviewer: rubric-walker
spine: ARCHITECTURE-SPINE.md
date: 2026-06-30
verdict: CONDITIONAL PASS — spine is structurally sound and covers the PRD well, but three gaps require resolution before implementation begins
---

# Architecture Spine Review — yt.flow

## Verdict

Conditional pass. The spine correctly identifies the major divergence risks (layer boundary violations, LangGraph/DB state desync, gate mechanism, A/B branching anti-pattern, artifact drift) and its rules are specific and enforceable. The PRD's feature surface is substantially covered. Three issues require resolution before implementation begins: version pins are vague for the most critical dependency, a deferred item carries a silent-divergence risk, and the operational envelope is underdescribed.

---

## Rubric Findings

### 1 — Divergence points: PASS with minor gap

All material divergence risks are identified and have rules:
- Layer boundary (AD-1)
- LangGraph vs DB as truth source (AD-2, AD-4)
- Gate mechanism (AD-3)
- A/B branching anti-pattern (AD-6)
- Artifact/state drift after inline edits (AD-8)
- Shot/sentence mapping assumption (AD-5)

**Minor gap:** The spine does not address the divergence risk between the `workspace/` artifact directory and `PipelineState` artifact paths when a run is deleted or its directory is manually cleared. AD-2 and AD-7 say artifact paths live only in `PipelineState` — correct — but there is no rule about orphan workspace directories or what happens if the SQLite file is deleted while `workspace/` remains. This is low-severity for a local single-operator tool but should at minimum be called out as an accepted trade-off.

---

### 2 — Rule enforceability: PASS

Every AD's Rule is specific enough to fail a code review:
- AD-1: import-path directionality is machine-checkable with `import-linter` or `ruff`.
- AD-2: the word "never be the write-authoritative store" is unambiguous.
- AD-3: "calls `interrupt()`" and "API resumes via `graph.astream(Command(resume=...))`" are concrete API calls, not intentions.
- AD-4: the ordering rule ("DB updates happen *after* LangGraph emits the first confirmation event") is checkable in code review.
- AD-5: `sentence_indices: list[int]` is a schema constraint, not prose.
- AD-6: "No graph-level branching" is binary.
- AD-7: "Use `AsyncSqliteSaver` — not the sync `SqliteSaver`" is a named-symbol rule.
- AD-8: "calls `graph.update_state()`… then rewrites the artifact file" — ordering specified.

No findings at this rubric point.

---

### 3 — Deferred items / silent divergence risk: HIGH

**OQ-8 — Stage gate scope** is deferred with the note "logic isolated in `gates.py`." The graph diagram shows gates after *every* stage (`gate_scenario`, `gate_image`, `gate_tts`, `gate_subtitle`, `gate_video`). If OQ-8 resolves to "only selected stages require gates," the graph topology itself changes — not just `gates.py` logic. Two units can diverge silently:

- `pipeline/graph.py` (StateGraph wiring) vs `gates.py` (gate node implementation)
- The `gate_states` dict schema in `PipelineState` (currently implies a key per stage) vs actual gate nodes present in the graph

**Action required:** Before FR-40 implementation, the spine must declare whether the graph topology is fixed (all five gates always present, configurable by skipping the interrupt logic) or variable (gates added/removed from the StateGraph at construction time). The current deferral without this structural constraint allows the two files to diverge silently.

The remaining deferred items (OQ-1, OQ-2, OQ-5, OQ-6, scene-level resume trade-off) are appropriately scoped: they affect implementation details, not structural divergence between units.

---

### 4 — Version pins: MEDIUM

**LangGraph** is pinned as `0.2.x (latest stable)` — this is the most structurally critical dependency and also the vaguest pin.

- `AsyncSqliteSaver` moved from `langgraph.checkpoint.sqlite.aio` to `langgraph_checkpoint_sqlite` as a separate package in LangGraph 0.2. The import path in AD-7 (`langgraph.checkpoint.sqlite.aio`) may be wrong depending on the exact 0.2.x release.
- LangGraph 0.2.x introduced breaking API changes vs 0.1.x; `0.2.x` without a floor pin (e.g., `>=0.2.28`) allows `uv` to resolve to any 0.2 release including early ones that lack `Command(resume=...)` semantics.

**Recommended fix:** Pin a concrete floor, e.g., `langgraph>=0.2.28,<0.3`. Verify the `AsyncSqliteSaver` import path against the actual installed package structure.

Other stack entries are acceptably pinned for a local-only tool: `FastAPI 0.115.x`, `SQLModel 0.0.21`, `React 18.x`. `Langfuse 2.x` and `langfuse Python SDK 2.x` are broad but acceptable given self-hosted.

---

### 5 — Codebase ratification: N/A (greenfield)

No existing codebase conventions to check. The structural seed is internally consistent with the AD rules. The `snake_case`/`PascalCase` naming convention table and UUID-over-autoincrement rule are appropriate for a Python/FastAPI project.

---

### 6 — PRD coverage: PASS with one gap

All F1–F7 features and their key functional requirements are bound or traceable to at least one AD:

| Feature | Covered by |
|---------|------------|
| F1 — Pipeline Core | AD-1, AD-2, AD-3, AD-4, AD-5 |
| F2 — Observability | Conventions table (`@observe`, span names) |
| F3 — Prompt Management | Config convention (`YTFLOW_*`, model identifiers pinned) |
| F4 — A/B Testing | AD-6 |
| F5 — API Interface | AD-3 (gate), AD-4 (SSE), AD-8 (artifact PATCH) |
| F6 — Data & Job Management | AD-2, AD-7 |
| F7 — Web UI | AD-8 (inline edit), SSE events table |

**Gap:** FR-30 (`POST /runs/{id}/stages/{stage}/retry`) has no architectural rule. Retry re-executes a stage on a LangGraph graph that has already passed that stage's gate. The mechanism for rewinding LangGraph state to a previous node is non-trivial (`graph.update_state()` can set the next node, but clearing downstream state requires explicit field nullification). This is not covered by any AD or convention, and two implementors could solve it differently (full graph re-creation vs state rewind vs a separate sub-graph). A rule is needed before F5 implementation.

---

### 7 — Operational/environmental envelope: MEDIUM

The spine describes the local execution model but leaves several operational questions unanswered that could produce divergent implementation choices:

**Not covered:**
- **`workspace/` path configuration**: Is `workspace/` relative to the repo root? Is the path configurable via `YTFLOW_*` env var? Two implementors could place artifact files in different locations.
- **Langfuse connectivity failure behavior**: If the self-hosted Langfuse instance is unreachable, does the pipeline fail, warn, or continue silently? This is an operational boundary condition that AD-2 and the `@observe` convention do not address.
- **ComfyUI availability at startup**: Is ComfyUI availability checked at startup (FastAPI lifespan) or lazily at first image node execution? Failure mode differs.
- **`scps.json` update mechanism**: The spine says the file is "committed to repo" and "loaded into memory at startup." What happens when a new SCP is added — is a restart required? This is documented in the Conventions table but the restart requirement is not explicit.

The deployment model (local + homelab Langfuse) is correctly stated in the PRD and not contradicted by the spine. The "no authentication" constraint is enforced by omission (no auth middleware in the structural seed). These operational gaps are medium severity for a single-operator local tool but should be addressed in config conventions before implementation.

---

## Summary Table

| # | Rubric Point | Status | Severity |
|---|-------------|--------|----------|
| 1 | Divergence points complete | Pass (minor gap: orphan workspace) | Low |
| 2 | Rules are enforceable | Pass | — |
| 3 | Deferred items / silent divergence | Fail: OQ-8 topology ambiguity | High |
| 4 | Version pins are real | Partial: LangGraph import path unverified, no floor pin | Medium |
| 5 | Ratifies codebase conventions | N/A (greenfield) | — |
| 6 | PRD coverage | Partial: FR-30 retry mechanism unspecified | Medium |
| 7 | Operational envelope | Partial: workspace path, Langfuse failure mode, ComfyUI startup check unaddressed | Medium |

---

## Required Actions Before Implementation

1. **[High — OQ-8]** Declare whether gate topology is fixed (always 5 gates) or variable. If configurable, add a rule specifying whether gates are toggled at graph construction time or within the gate node's interrupt logic, and update the `gate_states` schema accordingly.

2. **[Medium — Stack]** Pin LangGraph to a concrete floor version (e.g., `>=0.2.28`) and verify the `AsyncSqliteSaver` import path against the actual package structure in `langgraph_checkpoint_sqlite`.

3. **[Medium — FR-30]** Add an AD or convention for the retry mechanism: specify whether retry rewinds LangGraph state via `graph.update_state()` (nullifying downstream fields) or destroys and recreates the run graph, and which fields must be nullified.

4. **[Low — Ops]** Add a `YTFLOW_WORKSPACE_ROOT` config entry to the Conventions table, and document the Langfuse-unreachable behavior (continue with warning vs fail fast) as an accepted trade-off or a new convention.
