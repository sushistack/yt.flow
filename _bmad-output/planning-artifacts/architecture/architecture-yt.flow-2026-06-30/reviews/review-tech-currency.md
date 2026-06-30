---
type: review
subject: technology-currency
target: ARCHITECTURE-SPINE.md (Stack table + AD-7)
reviewer: tech-currency-agent
date: 2026-06-30
---

# Technology Currency Review — yt.flow Architecture Spine

## Verdict

**FAIL — two critical version mismatches require spine corrections before implementation begins.**

---

## Findings

### CRITICAL — LangGraph version pinned at 0.2.x; current stable is 1.2.x

**Stated:** `LangGraph 0.2.x (latest stable)`
**Actual:** Latest stable is **1.2.6** (released 2026-06-18). The 0.2.x series is over a year old.

The spine's own features — `interrupt()`, `Command(resume=...)`, `AsyncSqliteSaver` — are all present in 1.x and the associated tooling documentation targets 1.x. Pinning to 0.2.x would likely mean those APIs either don't exist or behave differently.

**Action required:** Change the Stack entry to `LangGraph 1.2.x (latest stable)`. Verify that `interrupt()` / `Command` API shapes are unchanged (search results confirm they are present and stable in 1.x).

---

### CRITICAL — SQLModel version pinned at 0.0.21; current stable is 0.0.38

**Stated:** `SQLModel 0.0.21`
**Actual:** Latest release is **0.0.38** (released 2026-04-02). The gap is 17 patch/minor releases.

0.0.21 is a significantly older build of a pre-1.0 library. Pre-1.0 libraries increment their rightmost digit for breaking changes; the probability of silent incompatibilities with Python 3.12 or Alembic 1.x is non-trivial.

**Action required:** Change the Stack entry to `SQLModel 0.0.38`. If the project is not yet started, no migration cost; update the pin now.

---

### HIGH — Langfuse Python SDK 2.x is end-of-life; current is 4.x

**Stated:** `langfuse Python SDK 2.x`
**Actual:** The SDK was rewritten to v4 (released March 2026); current is **4.12.0** (2026-06-25). A v4 migration guide exists, implying breaking changes from 2.x.

The `@observe` decorator pattern described in the Consistency Conventions table is valid in both v2 and v4, so the *pattern* is correct. However, the version pin is wrong and will install an EOL SDK.

**Action required:** Change the Stack entry to `langfuse Python SDK 4.x`. Verify the import path for `@observe` against v4 docs (`langfuse.decorators` module — confirmed available in v4).

Note: The **self-hosted Langfuse server** (`Langfuse (self-hosted) 2.x`) is a separate product version from the Python SDK; that entry was not contradicted by search results and may be correct — verify independently against the Langfuse server release page.

---

### LOW — `langgraph-checkpoint-sqlite` import path in AD-7 confirmed correct

**Stated:** `from langgraph.checkpoint.sqlite.aio` for `AsyncSqliteSaver`
**Actual:** Confirmed correct. `AsyncSqliteSaver` exists in `langgraph-checkpoint-sqlite` under `langgraph.checkpoint.sqlite.aio`. It is a separate installable package (`langgraph-checkpoint-sqlite`), not bundled with the core `langgraph` package — the Stack table label "bundled with LangGraph" is slightly misleading but installation-wise it is a companion package in the same monorepo.

**Action required (minor):** Clarify the Stack note to read `langgraph-checkpoint-sqlite` (separate install, same monorepo) rather than "bundled with LangGraph" to avoid confusion during `pyproject.toml` setup.

Also note: the package documentation explicitly warns that SQLite is not recommended for production workloads due to write-performance limits. For an MVP / local dev pipeline this is acceptable; flag for any production-scale deployment.

---

### LOW — `interrupt()` / `Command` API confirmed available and stable

**Stated:** `interrupt()` and `Command(resume=...)` used throughout AD-3
**Actual:** Both are confirmed present and documented in LangGraph 1.x. The resume flow (`graph.astream(Command(resume="approved"|"rejected"), config)`) matches current documentation exactly. No action required beyond the LangGraph version fix above.

---

## Summary Table

| Item | Stated | Actual | Severity | Action |
|------|--------|--------|----------|--------|
| LangGraph | 0.2.x | 1.2.6 | **CRITICAL** | Pin to 1.2.x |
| SQLModel | 0.0.21 | 0.0.38 | **CRITICAL** | Pin to 0.0.38 |
| langfuse Python SDK | 2.x | 4.12.0 (4.x) | **HIGH** | Pin to 4.x, verify `@observe` import |
| AsyncSqliteSaver availability | bundled | separate package, confirmed exists | LOW | Clarify install note |
| `interrupt()` / `Command` API | assumed present | confirmed present in 1.x | LOW | No action (covered by version fix) |

---

## Sources

- [langgraph · PyPI](https://pypi.org/project/langgraph/)
- [langgraph-checkpoint-sqlite · PyPI](https://pypi.org/project/langgraph-checkpoint-sqlite/)
- [AsyncSqliteSaver reference](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/aio/AsyncSqliteSaver)
- [sqlmodel · PyPI](https://pypi.org/project/sqlmodel/)
- [langfuse · PyPI](https://pypi.org/project/langfuse/)
- [Langfuse Python decorator docs](https://langfuse.com/docs/sdk/python/decorators)
- [LangGraph interrupt() reference](https://reference.langchain.com/python/langgraph/types/interrupt)
