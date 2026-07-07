---
created: 2026-07-07
story_key: 5-19-ddg-image-search-fallback-repair
story_id: "5.19"
epic: 5
depends_on:
  - 5-10-entity-reference-pipeline-repair   # established wiki-first, DDG-fallback architecture
  - 5-8-automatic-entity-reference-generation # original DDG search integration in _ensure_character_reference
soft_depends_on: []
baseline_commit: afb8f16
---

# Story 5.19: DDG Image Search Fallback Repair — vqd Acquisition Path Update

Status: done

## Story

As Jay,
I want the DuckDuckGo image search fallback to actually return results when the SCP Wiki has no article image,
so that the wiki-first-then-DDG-fallback pipeline (5.10) works end-to-end, and Story 8.5's stock location plate sourcing has a viable automated option.

## Context

2026-07-07 live reproduction test: the `i.js` 403 error seen in 5.8/5.10 live verification is **not** environmental blocking — the **vqd token acquisition method is stale**. Both yt.pipe (Go) and yt.flow (`image_search.py`) scrape vqd from the `duckduckgo.com` homepage, but DDG no longer serves vqd on the homepage. The fix, verified live in this environment:

1. **Change the vqd source URL** from the homepage (`https://duckduckgo.com`) to the **query results page** (`/?q=<query>&iax=images&ia=images`) — the query page still includes the vqd token in its HTML.
2. **Add a `Referer: https://duckduckgo.com/` header** — missing in the current implementation, required by DDG for the `i.js` request to succeed.
3. Combined with the existing browser UA (`_USER_AGENT`), this triplet (query-page vqd + Referer + browser UA) makes `i.js` return 200 with real results — confirmed live.

**Effect:** When the SCP Wiki has no article image, the DDG fallback path is restored — 8.5's stock location plate sourcing gains an automated option. The vqd endpoint is unofficial; re-breakage probability is a constant. Wiki-first priority is unchanged — this story fixes the fallback, not the architecture.

## Acceptance Criteria

1. **vqd acquired from query page, not homepage.** Given `_acquire_vqd` is called with a search query, then it sends a GET (not POST) to `https://duckduckgo.com/?q=<url-encoded query>&iax=images&ia=images` with the browser `User-Agent` header, extracts the vqd token from the response HTML via the existing `_VQD_RE` regex, and returns it. The old homepage POST (`data={"q": "test"}`) is removed. Retry behavior (exponential backoff, max `_VQD_MAX_RETRIES` attempts) is preserved.

2. **Referer header added to i.js request.** Given `search()` calls `i.js` after acquiring vqd, then the GET request to `https://duckduckgo.com/i.js` includes `Referer: https://duckduckgo.com/` in its headers. The `i.js` request returns 200 with real image results (confirmed live in this environment).

3. **search() passes query through to vqd acquisition.** Given `search("SCP-096", max_results=5)` is called, then the real query string `"SCP-096"` (not a hardcoded placeholder like `"test"`) is used for the vqd acquisition page URL, and the returned results are the top `max_results` `SearchResult` objects.

4. **Wiki-first contract unchanged.** Given `ScpWikiImageFetch.fetch()` succeeds (wiki has an article image), then DDG search is never invoked. Given `ScpWikiImageFetch.fetch()` returns `None` (any miss — 404, no image, unrecognized structure, connection error), then DDG search is attempted as fallback. This contract is preserved byte-for-byte — this story only fixes the fallback path's HTTP mechanics.

5. **Existing error handling preserved.** Given vqd acquisition fails after all retries, then `RuntimeError("VQD acquisition failed after 3 attempts")` is raised (same exception class and message pattern). Given `i.js` returns a non-2xx status, then `resp.raise_for_status()` raises `httpx.HTTPStatusError` (unchanged). VQD acquisition retries only catch `httpx.HTTPError | RuntimeError` (unchanged).

6. **Tests use MockTransport pattern.** Given the test suite runs, then:
   - The vqd acquisition test verifies the GET is sent to the correct query-page URL with the query in the path
   - The search test verifies the `Referer` header is present on the `i.js` request
   - The retry test verifies exponential backoff across `_VQD_MAX_RETRIES` attempts (existing pattern preserved)
   - The full integration test (`test_search_with_mock_transport`) returns real `SearchResult` objects through the fixed path
   - The regression test suite (`test_image_search.py` + any test exercising `_ensure_character_reference` via stub profile) passes green

## Tasks / Subtasks

- [x] **Task 1 — Fix `_acquire_vqd` URL and method (AC: 1, 3)**
  - [x] Change signature: `_acquire_vqd(self, client: httpx.AsyncClient, query: str)` — add `query` parameter
  - [x] Change the request from `client.post("https://duckduckgo.com", data={"q": "test"}, ...)` to `client.get(f"https://duckduckgo.com/?q={quote(query)}&iax=images&ia=images", headers=self._headers, follow_redirects=True)`
  - [x] URL-encode the query: `from urllib.parse import quote` (already imported at top of file)
  - [x] Keep retry loop, `_VQD_RE` extraction, `RuntimeError` raise, and `_VQD_MAX_RETRIES` — zero changes to these

- [x] **Task 2 — Wire query through `search()` and add Referer (AC: 1, 2, 3)**
  - [x] In `search()`: change `vqd = await self._acquire_vqd(client)` → `vqd = await self._acquire_vqd(client, query)`
  - [x] Add `"Referer": "https://duckduckgo.com/"` to the headers of the `client.get("https://duckduckgo.com/i.js", ...)` call. The cleanest approach: build a merged headers dict `{**self._headers, "Referer": "https://duckduckgo.com/"}` for that single request — do NOT mutate `self._headers` (shared state, concurrent access risk)
  - [x] Remove the `data={"q": "test"}` that was passed to the old homepage POST

- [x] **Task 3 — Update tests (AC: 6)**
  - [x] `tests/services/test_image_search.py` — `TestDuckDuckGoImageSearch`:
    - [x] **`test_vqd_regex_extracts_token`**: unchanged (regex is invariant)
    - [x] **`test_search_with_mock_transport`**: updated — now drives the real `search()` code path (via a monkeypatched `httpx.AsyncClient` transport injector) so it exercises `_acquire_vqd` and the `i.js` call for real; handler checks GET to query page with encoded query and asserts the `Referer` header on `i.js`
    - [x] **`test_max_results_limit`**: same real-path update
    - [x] **Added `test_vqd_retry_on_failure`**: 2 failures then success, verifies retry across the new GET path; added `test_vqd_retry_exhausted_raises` for AC5 exhaustion behavior; added `test_acquire_vqd_sends_get_to_query_page` for AC1 method/URL/query assertions
    - [x] **`Referer` header assertion**: folded into `test_search_with_mock_transport`'s `i.js` handler branch
  - [x] `tests/services/test_image_search.py` — `TestScpWikiImageFetch`: **zero changes** — wiki fetch is untouched
  - [x] Run `uv run pytest tests/services/test_image_search.py -q` → all green (12 passed)
  - [x] Run `uv run pytest -q` (full regression) → no new failures

- [x] **Task 4 — Live verification (AC: 1, 2, 4)**
  - [x] Picked SCP-173 — confirmed live to have no wiki article image (`ScpWikiImageFetch().fetch("SCP-173")` → `None`)
  - [x] Called `DuckDuckGoImageSearch().search("SCP-173", max_results=3)` with real network
  - [x] Confirmed: 3 real `SearchResult` objects returned, each with a non-empty `url`; no HTTP errors — the `i.js` 403 is resolved
  - [x] Confirmed wiki-first flow: `ScpWikiImageFetch().fetch("SCP-049")` → hit (real article image URL returned); DDG is only invoked on the miss path (SCP-173), never on the hit path
  - [x] Evidence recorded in Dev Agent Record → Completion Notes below

## Dev Notes

### What changed and why (DDG mechanics)

DuckDuckGo's vqd (visual query data) token is a CSRF-like parameter required by the `i.js` image search endpoint. Historically, the token was embedded in the homepage HTML. Sometime between the original yt.pipe implementation and 2026-07-07, DDG stopped including vqd on the bare homepage. However, the **query results page** — specifically the image tab (`/?q=<query>&iax=images&ia=images`) — still embeds it.

Additionally, DDG's `i.js` now checks the `Referer` header; without it, the request is rejected (403) even with a valid vqd. The browser UA was already present — the triplet is what works now.

### Why GET not POST

The homepage form submission (`POST` with `data={"q": "test"}`) was the old approach for extracting vqd. The query page is navigated via `GET` — it's a standard search URL, not a form submission. DDG returns the vqd in the HTML of that page. We're scraping, not submitting.

### Why pass the real query

The old code used a hardcoded `"test"` query for vqd acquisition because the homepage didn't need a specific query to serve vqd. Now that we're hitting the query page, we must use the actual search query — the page URL structure matters, and using a different query for vqd vs `i.js` risks mismatched tokens or blocks.

### Scope guardrails (do NOT do)

- **Do NOT change the wiki-first architecture.** `ScpWikiImageFetch` and its callers (`_ensure_character_reference` in `run_service.py`) are untouched.
- **Do NOT touch `ScpWikiImageFetch`** — zero changes.
- **Do NOT add config flags.** No `YTFLOW_DDG_ENABLED` toggle — the fallback either works or it doesn't.
- **Do NOT add a new dependency.** `httpx` and stdlib only.
- **Do NOT mutate `self._headers`.** The `Referer` is request-scoped, not instance-scoped. Build a merged dict per-request.
- **Do NOT change error handling semantics.** Same exception classes, same retry envelope, same log messages.
- **Do NOT add a `transport` seam to `DuckDuckGoImageSearch`** (unlike `ScpWikiImageFetch` which has one). The existing test pattern — constructing `httpx.AsyncClient(transport=...)` externally and passing it through `client` parameter of `_acquire_vqd` / `search` — works for MockTransport testing and is the Ponytail-minimal approach. If this becomes painful in practice, add the seam in a separate cleanup story.

### Preserved behavior (do not regress)

- VQD retry loop: exponential backoff (1s, 2s, 4s), max `_VQD_MAX_RETRIES` (3) attempts, catches `httpx.HTTPError | RuntimeError`
- `RuntimeError("VQD acquisition failed after 3 attempts")` on exhaustion
- `_VQD_RE` regex extraction — unchanged (vqd token format is stable: `vqd=<hex-or-hyphenated>`)
- `search()` returns `list[SearchResult]`, URL/thumbnail/title fields populated from `i.js` JSON
- `max_results` slicing (`data["results"][:max_results]`)
- `_TIMEOUT`, `_USER_AGENT` constants unchanged

### Testing standards

- `pytest` + `pytest-asyncio`; `httpx.MockTransport(handler)` pattern (already established in `test_image_search.py`)
- Handler functions receive `request: httpx.Request` → assert URL path, query params, headers, method → return `httpx.Response`
- The `_acquire_vqd` retry test follows the pattern: handler raises on first N calls, succeeds on N+1
- Test the `Referer` header by asserting `request.headers.get("referer")` in the `i.js` handler — case-insensitive per HTTP spec
- Worktree gotcha: `PYTHONPATH=$PWD/src` ([[worktree-editable-install-shadowing]])

### Project Structure Notes

- **Files touched:** `src/yt_flow/services/image_search.py` (~15 lines changed), `tests/services/test_image_search.py` (~30 lines changed)
- **Zero frontend impact.** This is a backend fallback fix only.
- **No new files.**
- **No config changes.**
- **No prompt changes** — PROMPT_POLICY.md not triggered.
- **Layer compliance (AD-1):** `services/image_search.py` imports from `domain/state.py` only — downstream-legal. No `pipeline/` or `api/` imports.

### Architecture invariants (from ARCHITECTURE-SPINE.md)

- AD-1: `services/` → `domain/` only — preserved (already compliant)
- AD-10: Langfuse tracing failures are non-fatal — irrelevant to this story (no tracing in image search)
- Convention: `snake_case` modules — preserved; `PascalCase` classes — preserved

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.19] — draft scope: vqd acquisition path update
- [Source: src/yt_flow/services/image_search.py#L118-L199] — DuckDuckGoImageSearch implementation (current broken state)
- [Source: tests/services/test_image_search.py#L19-L115] — existing test patterns (MockTransport)
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md] — AD-1 layer rules, conventions
- [Source: src/yt_flow/services/image_search.py#L60-L115] — ScpWikiImageFetch (wiki-first contract, unchanged)
- [Source: _bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md] — wiki-first + DDG-fallback architecture established
- [Source: _bmad-output/implementation-artifacts/5-8-automatic-entity-reference-generation.md] — original DDG integration in `_ensure_character_reference`

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

None — no test failures or blockers encountered during implementation. Full regression suite required patience (services dir alone takes ~2:47 due to pre-existing slow tests in `test_character_service_generation.py`), and a transient batch of `tests/pipeline/nodes/test_video.py` failures observed mid-session traced to an unrelated concurrent session's in-flight WIP on `video.py` — confirmed via `git stash`/`git diff --stat` that this story's diff never touches `video.py`, and the failures were gone on the next full run once that session's edits settled.

### Completion Notes List

- `_acquire_vqd` now GETs the query results page (`https://duckduckgo.com/?q=<query>&iax=images&ia=images`) instead of POSTing to the homepage, per AC1. Retry loop, `_VQD_RE` extraction, and `RuntimeError` on exhaustion are byte-for-byte preserved.
- `search()` passes the real query through to `_acquire_vqd` and adds a per-request `Referer: https://duckduckgo.com/` header to the `i.js` call via a merged dict (`self._headers` is never mutated), per AC2/AC3.
- `ScpWikiImageFetch` untouched — zero diff. Wiki-first contract (AC4) verified unchanged both by code inspection and live call.
- Tests updated to exercise the real production code path: `test_search_with_mock_transport` and `test_max_results_limit` now call `DuckDuckGoImageSearch().search(...)` directly, with `httpx.AsyncClient` monkeypatched (module-level, precedent in `test_eval_service.py`) to inject the `MockTransport` — no transport seam was added to the production class, per the story's scope guardrail. Added `test_acquire_vqd_sends_get_to_query_page`, `test_vqd_retry_on_failure`, and `test_vqd_retry_exhausted_raises` for AC1/AC5/AC6 coverage.
- Live verification (real network, no mocks): `ScpWikiImageFetch().fetch("SCP-049")` → hit (wiki-first path, DDG not invoked); `ScpWikiImageFetch().fetch("SCP-173")` → miss; `DuckDuckGoImageSearch().search("SCP-173", max_results=3)` → 3 real `SearchResult` objects with valid URLs, no HTTP errors. The 403 root cause from 5.8/5.10 is resolved.
- Noted but out of scope: `ScpWikiImageFetch().fetch("SCP-096")` returns `None` on the live wiki today (confirmed via `git stash` that this predates this story's change) — the wiki page's image-extraction heuristic may need a follow-up story if this SCP's page structure changed; not touched here per the "do NOT touch ScpWikiImageFetch" guardrail.
- Full regression suite: 709 collected, 708 passed, 1 skipped, 0 failed. `ruff check` clean on both changed files.

### File List

- `src/yt_flow/services/image_search.py` (modified)
- `tests/services/test_image_search.py` (modified)

## Change Log

- 2026-07-07: Story created from live reproduction test — DDG image search 403 root cause identified as stale vqd acquisition method. Fix: query-page URL + Referer header.
- 2026-07-07: Implemented and verified — `_acquire_vqd` switched from homepage POST to query-page GET, `Referer` header added to `i.js`, tests rewritten to exercise the real `search()`/`_acquire_vqd` path via a monkeypatched `AsyncClient` transport injector, live verification confirmed DDG fallback works end-to-end (SCP-173) alongside the unchanged wiki-first hit path (SCP-049). Full regression suite green (708 passed, 1 skipped). Status → review.
- 2026-07-07: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) — 4 patch findings fixed (vqd-page GET switched to `params=` for consistent encoding, redundant header-merge removed, retry-exhaustion test now interpolates `_VQD_MAX_RETRIES`, retry-backoff test now asserts the actual `[1, 2]` sleep sequence closing the AC6 gap), 6 findings deferred (pre-existing or inherent scraping risk, logged in deferred-work.md), 6 dismissed as noise. Full regression suite green (726 passed, 1 skipped), ruff clean. Status → done.

### Review Findings

- [x] [Review][Patch] `_acquire_vqd`'s vqd-page GET manually builds its URL via `quote(query)` f-string while `i.js` uses httpx's `params=` dict — different encoding for spaces (`%20` vs `+`); switch to `params=` for consistency [src/yt_flow/services/image_search.py:142-146]
- [x] [Review][Patch] Redundant `**self._headers` spread in the `i.js` request's `headers=` — httpx already merges client-default headers with per-request headers, `self._headers` is applied twice for no effect [src/yt_flow/services/image_search.py:176-180]
- [x] [Review][Patch] `test_vqd_retry_exhausted_raises` hardcodes "3 attempts" in its `match=` string instead of interpolating `_VQD_MAX_RETRIES` [tests/services/test_image_search.py]
- [x] [Review][Patch] AC6 gap: `test_vqd_retry_on_failure` verifies retry count but not exponential backoff — `_no_sleep` discards the `wait` argument instead of recording it [tests/services/test_image_search.py]
- [x] [Review][Defer] No validation for empty/whitespace `query` in `search()`/`_acquire_vqd` — deferred, pre-existing gap, no current caller passes an empty query
- [x] [Review][Defer] `i.js` request omits `iax`/`ia` image-tab params present on the vqd-page GET — deferred, pre-existing (unchanged by this diff)
- [x] [Review][Defer] vqd regex could match the wrong tab's token if the query page embeds multiple `vqd=` occurrences — deferred, unofficial-endpoint risk already documented in this story as a constant, live-verified working today
- [x] [Review][Defer] Test fixtures (`_fake_vqd_html`) are minimal/synthetic vs real DDG markup, and no automated test catches future DDG markup drift — deferred, established project test pattern; live verification is this story's manual process, not the automated suite
- [x] [Review][Defer] No test coverage for non-5xx failure modes (timeouts, malformed JSON, missing `results` key) — deferred, not required by AC5 (exception-type/message preservation only), pre-existing gap
- [x] [Review][Defer] DDG anti-bot/fingerprint risk on the new GET path is undetected and untested — deferred, inherent third-party scraping risk, story already frames re-breakage probability as constant
