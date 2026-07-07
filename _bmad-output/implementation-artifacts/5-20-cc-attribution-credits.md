---
created: 2026-07-07
story_key: 5-20-cc-attribution-credits
story_id: "5.20"
epic: 5
depends_on:
  - 5-17-chapter-card-content   # _compose_chapter_card renderer + bundled Pretendard reuse
  - 5-10-entity-reference-pipeline-repair  # ScpWikiImageFetch.WikiImage.page_url for attribution
soft_depends_on:
  - 5-18-subtitle-display-text-dual-track  # Pretendard already bundled in data/fonts/
baseline_commit: c6f2778
---

# Story 5.20: CC BY-SA Attribution Credits — Ending Card + description.txt

Status: done

## Story

As Jay,
I want every monetized SCP video to automatically include the CC BY-SA attribution the license requires,
so that I never publish a video without proper credit and never have to compose the YouTube description block by hand.

## Context

SCP Foundation wiki content is licensed under **CC BY-SA 3.0** — attribution (original author + source link) and share-alike notice are legal obligations for derivative works, including monetized YouTube videos. This is not just best practice; it is a license requirement. Jay (2026-07-07): automate it so credit is never forgotten.

Two outputs, both non-fatal (AD-10 — auxiliary failures never kill the run):

1. **Ending credits card** — a final 2.5s black card appended after the last scene, reusing 5.17's `_compose_chapter_card` renderer + bundled Pretendard Bold. Shows the attribution line + wiki page URL.
2. **`description.txt` artifact** — a text file written to the run directory containing the full YouTube description block: article link, license link, derivative-work notice, and any wiki image sources (5.10's `ScpWikiImageFetch.WikiImage.page_url` already provides the source page URL).

Both are wrapped in independent `try/except` blocks — a credit-generation failure logs a warning and continues; the run itself must never fail on attribution.

The SCP wiki URL convention is deterministic: `https://scp-wiki.wikidot.com/{lowercase-hyphenated-scp-id}` (e.g. `scp-049`, `scp-682`). Wikidot slugs strip zero-padding and use hyphens — confirmed live by 5.10. The `PipelineState.scp_id` already carries the canonical ID (e.g. `"SCP-049"`); slugification is a one-liner.

## Acceptance Criteria

1. **Config toggle defaults on.** Given `Settings` loads, then `cc_attribution: bool = True` (env `YTFLOW_CC_ATTRIBUTION`) is defined in `config.py`. When `False`, both the ending card and `description.txt` are skipped entirely — no HTTP calls, no file writes. (For testing, dry-runs, or non-SCP content where CC BY-SA doesn't apply.)

2. **Ending credits card appended to video.** Given a run with `cc_attribution=True` and 2+ scenes reach the video stage, when `video_node` completes, then the output video ends with a 2.5s black card rendering:
   - **Line 1** (title, `CARD_FONT_SIZE=72`): `"Based on 'SCP-XXX' from the SCP Foundation Wiki"` — centered, white, Pretendard Bold
   - **Line 2** (kicker, `CARD_KICKER_FONT_SIZE=40`): `"CC BY-SA 3.0 — scp-wiki.wikidot.com/scp-xxx"` — centered below
   The card uses `_compose_chapter_card` with the attribution text as `label` and the URL line as `kicker`. It gets the same mood grading (post_fx, sound-design ambient bed) as chapter cards. Duration: 2.5s (`MAX_CARD_DURATION`, already raised by 5.17). Single-scene runs (len(scenes)==1) also get the ending card — the "chapter cards require 2+ scenes" guard only gates chapter cards, not the ending credit.

3. **description.txt artifact written.** Given a run with `cc_attribution=True`, when the video stage completes (after the ending card, or when the card generation is skipped), then `workspace/{run_id}/description.txt` contains a UTF-8 text block:

   ```
   [SCP-XXX] TITLE — SCP Foundation Wiki
   https://scp-wiki.wikidot.com/scp-xxx

   Licensed under CC BY-SA 3.0
   https://creativecommons.org/licenses/by-sa/3.0/

   This video is a derivative work based on "SCP-XXX" from the SCP Foundation Wiki.

   ---
   Image source: https://scp-wiki.wikidot.com/scp-xxx
   ```

   Where:
   - `SCP-XXX` is the run's `scp_id`
   - `TITLE` is the SCP entry's `nickname` from `data/scps.json` (e.g. "Plague Doctor"), if available; omitted with `—` stripped when not found
   - The wiki URL uses the slugified scp_id
   - Author name: if the wiki page HTML contains an author credit (`.creditRate` or `.printuser` — Wikidot's standard author byline), it is extracted and listed; otherwise the page link alone is sufficient (wiki community convention)

4. **Wiki image source attribution in description.txt.** Given `ScpWikiImageFetch.fetch(scp_id)` succeeded during the run's image search phase (5.10), and the resulting `WikiImage.page_url` is available, then the description.txt includes at minimum the wiki page URL as the image source. If no wiki image was used (search fell back to DDG, or the character had no reference image), the "Image source:" line still links to the wiki article page (the article itself is CC BY-SA even if its page image wasn't used).

5. **Both outputs are non-fatal.** Given `cc_attribution=True`, if ending card ffmpeg fails, then a warning is logged with the run_id and exception, and the video is delivered without the ending card — the run status remains `"complete"`, not `"failed"`. Given `cc_attribution=True`, if `description.txt` write fails (disk full, permissions), then a warning is logged and the run continues — the run status remains `"complete"`. Both try/except blocks are independent — a card failure does not prevent description.txt from being written, and vice versa.

6. **Gate visibility.** Given the video stage completes with `cc_attribution=True`, then the video gate artifacts API (`GET /runs/{id}/stages/video/artifacts`) includes:
   - `"ending_credit": true` (boolean — card was attempted)
   - `"ending_credit_error": null | "str"` (null on success, error message on failure)
   - `"description_txt_path": "workspace/{run_id}/description.txt"` (path, even on failure — the API reports the expected path)
   This lets the reviewer confirm credit presence at the video gate before downloading.

7. **No new prompt changes.** This story is purely code — no Langfuse prompts are modified or created. `docs/PROMPT_POLICY.md` is not triggered.

8. **No new dependencies.** stdlib `re` + `httpx` (already installed for `image_search.py`) + existing `_compose_chapter_card` + existing `Settings`. Zero new packages.

9. **Tests.** Given the test suite runs, then:
   - `tests/pipeline/nodes/test_video.py`: ending card appended (ffmpeg args include the card segment after the last scene's dip-to-black join, card textfiles contain the attribution strings), card skipped when `cc_attribution=False`, card failure non-fatal (monkeypatched `_run_ffmpeg` raises → run completes, error logged, `ending_credit_error` in trace metadata)
   - `tests/services/test_video_credits.py` (new): description.txt contents match template (SCP-049 → nickname "Plague Doctor", SCP-999 → nickname "The Tickle Monster"), slugification, missing-nickname tolerance, wiki-author extraction (mock HTML), write-failure non-fatal, toggle-off skips
   - `tests/pipeline/nodes/test_video.py`: `_record_trace` metadata includes `ending_credit`/`ending_credit_error` fields
   - Full regression suite green, ruff clean

## Tasks / Subtasks

- [x] **Task 1 — Config toggle + SCP nickname lookup (AC: 1, 3)**
  - [x] `config.py`: add `cc_attribution: bool = True` (env `YTFLOW_CC_ATTRIBUTION`)
  - [x] Slug helper: `_scp_wiki_slug(scp_id: str) -> str` — `scp_id.strip().lower()` (e.g. `"SCP-049"` → `"scp-049"`). The Wikidot convention strips zero-padding: `"SCP-096"` → `"scp-096"`, confirmed live by 5.10.
  - [x] Nickname lookup: read `data/scps.json` (load once at module level or accept the dict as parameter — ponytail: load on first call, cache). Return `None` when scp_id not found (tolerant).

- [x] **Task 2 — Ending credits card (AC: 2, 5)**
  - [x] New function `_compose_ending_credit(scp_id: str, out_dir: Path, *, mood: str | None = None, post_fx_enabled: bool = False, sound_design_enabled: bool = False) -> Path | None` in `video.py`.
    - `label = f"Based on '{scp_id}' from the SCP Foundation Wiki"`
    - `kicker = f"CC BY-SA 3.0 — scp-wiki.wikidot.com/{_scp_wiki_slug(scp_id)}"`
    - Delegates entirely to `_compose_chapter_card(label=label, kicker=kicker, index=0, out_dir=out_dir, duration=MAX_CARD_DURATION, mood=mood, post_fx_enabled=post_fx_enabled, sound_design_enabled=sound_design_enabled)` — the card number is always `0` (there's only one ending card per run, file naming uses a different stem)
    - **CRITICAL**: use a distinct output filename from chapter cards — `credit_ending.mp4`, NOT `card_NNN.mp4`. Chapter cards use `card_{i:03d}.mp4` indexed by scene position; the ending card must never collide.
    - Wrap in try/except — returns `None` on failure, logs warning (AC5)
  - [x] Integrate into `video_node`: after the `_join_with_fades` segment loop, if `cc_attribution=True`, call `_compose_ending_credit` with the last scene's mood, append the returned path (when non-None) to `join_segments` before `_join_with_fades`, and set `ending_credit_error` in the trace metadata. The ending card always gets `fade_in=0.0, fade_out=0.0` in the join — it self-fades internally via `_compose_chapter_card`'s own fade chain (same contract as chapter cards).
    - Single-scene path: when `len(segs) == 1` (no join), compose the ending card, then join `[scene, credit]` with `_join_with_fades` instead of the direct `replace`. The ending card is the only reason to use the join code path for single-scene runs.
    - When the ending card returns `None` (failure), the join proceeds without it — the last segment is the last scene.

- [x] **Task 3 — description.txt artifact (AC: 3, 4, 5)**
  - [x] New module `src/yt_flow/services/video_credits.py` — pure function, no class. Separated from `video.py` because description.txt is a post-video artifact, not a video composition concern.
  - [x] `def build_description_text(scp_id: str, *, scp_nickname: str | None = None, wiki_page_url: str | None = None) -> str` — returns the description.txt template populated with the given values.
    - `wiki_page_url` default: `f"https://scp-wiki.wikidot.com/{_scp_wiki_slug(scp_id)}"`
    - Title line: `f"[{scp_id}] {scp_nickname} — SCP Foundation Wiki"` when nickname is available, `f"[{scp_id}] — SCP Foundation Wiki"` when not (strip ` —` and re-add)
  - [x] `async def write_description_artifact(run_dir: Path, scp_id: str) -> Path | None` — wraps `build_description_text` + file write. Async only for consistency with `video_node`'s call site; the actual I/O is `run_dir.mkdir(parents=True, exist_ok=True)` + `Path.write_text()`. Returns the written path or `None` on failure. Wrap in try/except — logs warning, returns `None` (AC5).
  - [x] Integrating into `video_node`: after the join completes (both the `if len(segs)==1` and the `else` branch), call `write_description_artifact(run_dir, s.run_id_metadata["scp_id"])` when `cc_attribution=True`. Nickname: look up from `data/scps.json` at call time (ponytail: the video node already has access to `Settings`). Wiki page URL: the ending card already computes the slug; reuse.

- [x] **Task 4 — Gate artifact exposure (AC: 6)**
  - [x] `run_service.py::get_stage_artifacts`: in the `"video"` branch, add `"ending_credit": ..., "ending_credit_error": ..., "description_txt_path": ...` by reading from the LangGraph checkpoint's trace metadata (or by computing the expected `description.txt` path from `run_id`). The `video_node` sets these in `PipelineState` via its return dict.

- [x] **Task 5 — PipelineState metadata (AC: 6)**
  - [x] Add `ending_credit_error: str | None` to `PipelineState` in `domain/state.py` (or use a separate key in the return dict — ponytail: TypedDict addition is explicit; the cleanest approach is to add `"ending_credit_error": ending_credit_error` to the `video_node` return dict as an extra key. PipelineState is a TypedDict with `total=False` behavior on reads).
  - [x] `_record_trace` in `video.py`: add `ending_credit: bool` and `ending_credit_error: str | None` fields to the metadata.

- [x] **Task 6 — Tests (AC: 9)**
  - [x] `tests/pipeline/nodes/test_video.py`:
    - [x] `test_ending_credit_appended`: with `cc_attribution=True` and 2+ scenes, ffmpeg args include a `credit_ending.mp4` segment after the last chapter card, card textfiles contain the SCP-049 attribution string and CC BY-SA URL, card duration is `MAX_CARD_DURATION` (2.5)
    - [x] `test_ending_credit_single_scene`: with 1 scene + `cc_attribution=True`, the join path is used (not direct replace), join includes scene + ending card
    - [x] `test_ending_credit_skipped_when_disabled`: `cc_attribution=False` → no credit segment, no textfiles
    - [x] `test_ending_credit_failure_non_fatal`: monkeypatch `_run_ffmpeg` to raise on the ending card call → video completes, `ending_credit_error` is set, `ending_credit` is `False`
    - [x] `test_trace_metadata_includes_credit_fields`: `_record_trace` called with `ending_credit=True/False` and `ending_credit_error=None/"msg"`
  - [x] `tests/services/test_video_credits.py` (new):
    - [x] `test_build_description_with_nickname`: SCP-049 → includes "Plague Doctor"
    - [x] `test_build_description_without_nickname`: unknown scp_id → no nickname, "— SCP Foundation Wiki" still present
    - [x] `test_build_description_slug`: SCP-049 → URL is `scp-049`, SCP-682 → `scp-682`
    - [x] `test_build_description_includes_license_links`: CC BY-SA 3.0 + creativecommons.org URL
    - [x] `test_write_description_artifact`: file written to run_dir, content matches template, path returned
    - [x] `test_write_description_artifact_failure_non_fatal`: mock `Path.write_text` to raise OSError → returns None, no exception escapes
    - [x] `test_write_description_artifact_skipped_when_toggle_off`: not called when `cc_attribution=False`
  - [x] `tests/domain/test_state_imports.py`: add `ending_credit_error` to `EXPECTED_FIELDS["PipelineState"]` if a new PipelineState key is added (otherwise no change if using a return-dict extra key).
  - [x] Full regression: `uv run pytest -q` green, `uv run ruff check` clean on all touched files.

- [x] **Task 7 — Live validation**
  - [x] Run a short pipeline (e.g. SCP-999, 2 scenes, mock ComfyUI/TTS) with `cc_attribution=True` → inspect the final `video.mp4` — the last 2.5s is the black ending card with the attribution text. Verify Pretendard glyphs render (no tofu), both lines visible, quotes intact.
  - [x] Verify `workspace/{run_id}/description.txt` exists and contains the correct template populated with SCP-999's nickname ("The Tickle Monster").
  - [x] Run with `YTFLOW_CC_ATTRIBUTION=false` → no ending card, no description.txt, run completes normally.
  - [x] Keep artifacts (frame sample + description.txt) for evidence.

## Dev Notes

### Current vs changed behavior

- **Current:** video ends after the last scene — no attribution. No `description.txt` artifact. The operator must manually compose YouTube descriptions and remember CC BY-SA credit.
- **Changed:** video ends with a 2.5s black credit card (reusing the chapter-card renderer). `description.txt` is written to the run directory with the full YouTube description block. Both are toggled by `YTFLOW_CC_ATTRIBUTION` (default on).
- **Why `_compose_chapter_card` and not a new renderer:** 5.17 already built the exact card composition we need — black background, centered white Pretendard text (title + kicker), self-fading edges, mood grading, ambient audio bed. The ending credit IS a chapter card, just with different text and always last.

### SCP wiki URL determinism

The Wikidot slug format is `scp-xxx` (lowercase, hyphenated) — confirmed live by `ScpWikiImageFetch` in 5.10. No zero-padding: `SCP-049` → `scp-049`, `SCP-096` → `scp-096`. This is already tested in `test_image_search.py`. We reuse the same convention.

### Author name extraction (optional, best-effort)

Wikidot pages include author credit in HTML like:
```html
<span class="printuser">AuthorName</span>
```
or via the credit rate block. Extracting this is best-effort — if the regex doesn't match, the page link alone is sufficient (SCP wiki community convention: attribution via link is acceptable when author is not trivially extractable). Do NOT make this a hard requirement — a missing author name must never block description.txt generation.

### Non-fatal contract (AD-10)

Both the ending card and description.txt follow the same non-fatal pattern already established in the codebase:
- `_ensure_character_reference` (5.8): best-effort, logged+swallowed
- `enrich_descriptor_from_references` (5.12): its own try/except, separate from the search/generation path
- Langfuse tracing (AD-10): setup and teardown both guarded

The ending card and description.txt each get their own independent `try/except` — one failing must not prevent the other.

### Ponytail

- No new classes — `_compose_ending_credit` is a function, `build_description_text` is a pure function, `write_description_artifact` is a plain async function
- No new config objects — one bool on existing `Settings`
- No interface/abstraction — the ending card is a thin wrapper over `_compose_chapter_card`
- `description.txt` content is a template string, not a Jinja2 template — stdlib only
- Deletions: none
- Mark deliberate simplifications with `# ponytail:` — e.g. author extraction as best-effort regex

### Preserved behavior (do not regress)

- Chapter card rendering, count, labels, stinger sync — all unchanged
- `_compose_chapter_card` signature and behavior — unchanged (ending credit is a new caller, not a modification)
- Single-scene path without credits — unchanged (direct `replace` still used when `cc_attribution=False`)
- `_join_with_fades` contract — unchanged (ending card is just another segment in the list)
- `_record_trace` existing fields — unchanged (new fields are additive)
- All non-video pipeline stages — zero impact

### Scope guardrails (do NOT do)

- **Do NOT add a Langfuse prompt** for the credit text — the credit is boilerplate, not LLM-generated
- **Do NOT fetch the wiki page at video time** — the slug is deterministically computable from `scp_id`; the page URL is known without an HTTP call. The author extraction (if implemented) fetches the page; if it fails, the page link alone is sufficient.
- **Do NOT add `description.txt` to the runs DB table** — it's a file artifact in the workspace, same as `video.mp4`
- **Do NOT add a `credit_duration` config** — 2.5s (`MAX_CARD_DURATION`) is the accepted card duration ceiling per 5.17
- **Do NOT create a new LangGraph node or gate** — the credit is part of `video_node`, not a separate pipeline stage
- **Do NOT add a frontend component** — the video gate artifact panel already shows video metadata; `ending_credit`/`ending_credit_error` in the API response is consumed by the existing panel pattern

### Testing standards

- `pytest` + `pytest-asyncio`; card tests use the existing `_capture_ffmpeg_calls` monkeypatch pattern (`test_video.py`)
- `test_video_credits.py` is a plain unit-test module — no LangGraph runtime, no DB, no async except `write_description_artifact` which just does `Path.mkdir` + `Path.write_text`
- Worktree gotcha: `PYTHONPATH=$PWD/src` ([[worktree-editable-install-shadowing]])

### Project Structure Notes

- **Files touched:** `src/yt_flow/config.py` (~1 line), `src/yt_flow/domain/state.py` (~1 line, optional), `src/yt_flow/pipeline/nodes/video.py` (~50 lines — new function + integration), `src/yt_flow/services/video_credits.py` (new, ~60 lines), `src/yt_flow/services/run_service.py` (~5 lines — gate artifact exposure)
- **New files:** `src/yt_flow/services/video_credits.py`, `tests/services/test_video_credits.py`
- **Zero frontend impact.**
- **No prompt changes** — PROMPT_POLICY.md not triggered.
- **No new dependencies.**
- **Layer compliance (AD-1):** `video_credits.py` is in `services/` (not `pipeline/`) because `description.txt` is a post-pipeline artifact, not a composition step. It imports from `domain/` only — downstream-legal. `video.py` is in `pipeline/nodes/` — stage node, imports from `domain/` and `services/video_credits.py` (legal: pipeline → services is the allowed upward direction? No — AD-1 says `api → services → (pipeline | db) → domain`. Pipeline cannot import services. So `video_credits.py` must be importable by `pipeline/`. Options: put it in `pipeline/nodes/` alongside `video.py`, or make it a domain-level utility. Ponytail: the simplest approach is to inline the `build_description_text` logic directly in `video.py` (it's 15 lines of template) and write the file from `video_node` itself — no new module needed. This also eliminates the cross-layer import concern entirely.)

### Architecture invariants (from ARCHITECTURE-SPINE.md)

- AD-1: `pipeline/` never imports `services/` — if `description.txt` generation stays in `video.py` (ponytail inline), no cross-layer import
- AD-2: PipelineState is the single source of truth — `ending_credit_error` goes in the return dict
- AD-10: Non-fatal auxiliary failures — ending card and description.txt both follow this
- Convention: `snake_case` modules, `PascalCase` TypedDicts, `YTFLOW_` env prefix

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.20] — draft scope: ending card + description.txt, non-fatal, 5.17 renderer reuse
- [Source: src/yt_flow/pipeline/nodes/video.py#L668-L750] — `_compose_chapter_card` (the renderer to reuse)
- [Source: src/yt_flow/pipeline/nodes/video.py#L79-L80] — `CARD_FONT_SIZE=72`, `CARD_KICKER_FONT_SIZE=40`
- [Source: src/yt_flow/services/image_search.py#L52-L56] — `WikiImage` NamedTuple with `page_url` for attribution
- [Source: src/yt_flow/services/image_search.py#L30] — `_WIKI_BASE_URL = "https://scp-wiki.wikidot.com"`
- [Source: src/yt_flow/domain/state.py#L93-L107] — `PipelineState` (scp_id, scenes, video_path)
- [Source: src/yt_flow/config.py#L90-L91] — `chapter_cards`, `chapter_card_duration_sec` config
- [Source: data/scps.json] — SCP entries with `id` and `nickname` fields
- [Source: _bmad-output/implementation-artifacts/5-17-chapter-card-content.md] — card renderer contract, Pretendard bundling
- [Source: _bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md] — wiki-first fetch architecture, `WikiImage.page_url`
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md] — AD-1 layer rules, AD-10 operational envelope, structural seed

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Live validation script: real ffmpeg (no mocks), 2 scenes × 2s + card-less hold + 2.5s ending
  card = 6.85s total for `cc_attribution=True`; 4.34s for `cc_attribution=False` (no card, no
  hold-less regression). Last frame extracted via `ffmpeg -sseof -1` and visually inspected —
  Pretendard renders both lines cleanly, quotes intact, no tofu glyphs.
- `description.txt` for SCP-999 correctly resolved nickname "The Tickle Monster" from
  `data/scps.json` and used the deterministic `scp-999` wiki slug for both the URL and the
  image-source line.

### Completion Notes List

- **Deviated from the task list's `services/video_credits.py` module (Task 3)** in favor of
  the story's own Dev Notes / Project Structure Notes resolution: `build_description_text` /
  `_write_description_artifact` are inlined into `pipeline/nodes/video.py` instead of a new
  `services/` module. Reason: AD-1 forbids `pipeline/` importing `services/`, and the story's
  own "Project Structure Notes" section already reasoned through this and landed on inlining
  ("the simplest approach is to inline... This also eliminates the cross-layer import concern
  entirely"). Tests for these functions therefore live in `tests/pipeline/nodes/test_video.py`,
  not a new `tests/services/test_video_credits.py`.
- **Wiki-author-byline extraction (AC:3's optional "Author name:" bullet) is not implemented.**
  The story's own scope guardrails rule out fetching the wiki page at video time ("Do NOT fetch
  the wiki page at video time — the slug is deterministically computable"), and `build_description_text`'s
  given signature (`scp_id`, `scp_nickname`, `wiki_page_url`) has no author parameter. The
  documented fallback — "the page link alone is sufficient" — is therefore always the active
  path; this is the deliberate, guardrail-compliant reading, not an oversight.
  `# ponytail:` noted at the `build_description_text` docstring.
- **`ending_credit`'s boolean semantics reflect success, not mere attempt.** AC:6's prose says
  "card was attempted", but Task 6's own test spec (`test_ending_credit_failure_non_fatal`)
  requires `ending_credit is False` after a card-composition failure. Implemented the latter
  (`ending_credit = ending_credit_path is not None`) since it's the concrete, testable
  behavior and is more useful to a reviewer at the gate (did the card actually make it into the
  video?). `ending_credit_error` still distinguishes "not attempted" (key absent — cc_attribution
  was off) from "attempted and failed" (key present, non-null message).
- `_compose_ending_credit` does not internally swallow its own ffmpeg failure (deviates from
  Task 2's literal "wrap in try/except" placement) — the try/except lives in `video_node`
  instead, because AC:5 requires the warning to include `run_id`, which `_compose_ending_credit`'s
  given signature has no reason to carry. Matches the existing pattern of `_compose_chapter_card`/
  `_compose_scene`/`_compose_black_hold`, which all raise and let their caller decide.
- Consolidated the duplicate `scp_id = state.get("scp_id", "")` (previously read only inside the
  angle-selector branch) to the top of `video_node` so it's available unconditionally for the
  ending-credit/description.txt calls.
- All 7 tasks complete. Full regression suite green (780 passed, 1 skipped), `ruff check` clean
  on all touched files. Live-validated with real ffmpeg per Task 7 (see Debug Log References).

### File List

- `src/yt_flow/config.py` — `cc_attribution: bool = True` (env `YTFLOW_CC_ATTRIBUTION`)
- `src/yt_flow/domain/state.py` — `PipelineState.ending_credit_error: str | None`
- `src/yt_flow/pipeline/nodes/video.py` — `_scp_wiki_slug`, `_scp_nickname` (+ module cache),
  `build_description_text`, `_write_description_artifact`, `_compose_ending_credit`;
  `video_node` integration (ending-credit composition + join wiring + description.txt write);
  `_record_trace` gains `ending_credit`/`ending_credit_error` fields
- `src/yt_flow/services/run_service.py` — `get_stage_artifacts`'s `"video"` branch exposes
  `ending_credit`/`ending_credit_error`/`description_txt_path`; `_initial_state` seeds
  `ending_credit_error: None`
- `tests/domain/test_state_imports.py` — `EXPECTED_FIELDS["PipelineState"]` gains `ending_credit_error`
- `tests/pipeline/nodes/test_video.py` — `_settings_ns` gains `cc_attribution` param; new tests
  for slug/nickname/description-text/write-artifact/ending-credit composition, join wiring
  (multi- and single-scene), non-fatal failure, toggle-off, and trace metadata
- `tests/api/test_stage_artifacts.py` — new tests for the video-stage artifact endpoint's
  attribution fields (success, failure, not-attempted)

### Review Findings

- [x] [Review][Patch] `_initial_state` always seeds `ending_credit_error: None`, breaking the AC6 "presence = attempted" gate contract — every run (including `cc_attribution=False` ones) reports `ending_credit: true` and a `description_txt_path` at the gate, even when nothing was ever attempted [src/yt_flow/services/run_service.py:222] — fixed: `_initial_state` no longer seeds the key; `PipelineState.ending_credit_error` changed to `NotRequired[str | None]`
- [x] [Review][Patch] `_compose_ending_credit`'s join-segment tuples record `card_duration` (the configured, possibly-clamped duration) while the file itself always renders at `MAX_CARD_DURATION` — currently inert (fade_in/fade_out are both 0 for card segments) but a latent landmine if `_join_with_fades` ever starts trusting the declared duration [src/yt_flow/pipeline/nodes/video.py:1109,1153] — fixed: both join-segment tuples now declare `MAX_CARD_DURATION`
- [x] [Review][Patch] `_scp_nickname`'s module cache is built with a raw dict comprehension (`{e["id"]: e["nickname"] for e in entries}`) — one entry in `data/scps.json` missing `id`/`nickname` raises, and the broad `except Exception` then silently caches `{}` for the rest of the process lifetime with no log line, unlike `_write_description_artifact`'s warning-on-failure pattern [src/yt_flow/pipeline/nodes/video.py:435] — fixed: per-entry tolerant comprehension + warning log on failure
- [x] [Review][Patch] `cc_attribution = bool(s.cc_attribution)` is a no-op cast — `Settings.cc_attribution` is already `bool` — ponytail cleanup [src/yt_flow/pipeline/nodes/video.py:1090] — fixed: cast removed
- [x] [Review][Patch] AC9 test-coverage gap: no test asserts `_record_trace` receives `(ending_credit=False, ending_credit_error="<msg>")` — the real card-failure path (`test_ending_credit_failure_non_fatal`) never monkeypatches `_record_trace` to check its kwargs, so that field combination is untested [tests/pipeline/nodes/test_video.py] — fixed: assertions added to `test_ending_credit_failure_non_fatal`
- [x] [Review][Defer] `state.get("scp_id", "")` defaulting to empty string would produce a dead wiki URL/blank attribution text if `scp_id` were ever missing — pre-existing pattern from Story 1.13's angle-selector code, not introduced by 5.20 [src/yt_flow/pipeline/nodes/video.py:1021] — deferred, pre-existing
- [x] [Review][Defer] `run_id` is interpolated directly into a filesystem path in `get_stage_artifacts`/`_initial_state` with no format validation — pre-existing pattern used identically throughout `run_service.py` (e.g. the scenario-artifact path), not introduced by 5.20 [src/yt_flow/services/run_service.py:145] — deferred, pre-existing

Dismissed as noise (7): `_scp_wiki_slug` docstring says "hyphenated" but only lowercases — no functional impact, `scp_id` is always pre-hyphenated at the source (`data/scps.json`); ending-credit's `card_000.mp4` intermediate filename "collision" with a real chapter card — false alarm, real chapter cards are indexed from `i+1` (1..N), index 0 is never used by a scene card; `build_description_text`'s "Image source" line attributing the wiki URL even when the run's actual reference image came via DDG fallback — this is AC4's explicit, literal requirement, not a bug; `description_txt_path` returned without checking the file exists on disk — AC6 explicitly requires the expected path be reported "even on failure"; a reported `NameError` risk from `Path`/`_settings` usage in `run_service.py` — both are already imported/defined at module scope; the Dev Agent Record's reinterpretation of `ending_credit` as success-not-attempted — already a deliberate, documented, and reasonable call (strictly more informative to a gate reviewer), not a bug; `cc_attribution` defaulting to `True` "contradicting" the config comment's dry-run/non-SCP rationale — the comment describes an available opt-out, not an auto-detected default; AC1 explicitly specifies the default as `True`.

## Change Log

- 2026-07-07: Story created from epic draft — CC BY-SA attribution automation: ending credit card (5.17 renderer reuse) + description.txt artifact, both non-fatal, toggled by `YTFLOW_CC_ATTRIBUTION`.
- 2026-07-07: Implemented — ending credit card + description.txt, both non-fatal, gate-visible via `GET /runs/{id}/stages/video/artifacts`. Full regression green, ruff clean, live-validated with real ffmpeg. Status → review.
- 2026-07-07: Code review complete — 5 patches applied (critical: `_initial_state` unconditionally seeded `ending_credit_error`, breaking AC6's presence-signals-attempted gate contract for every `cc_attribution=False` run; plus a duration-mismatch landmine, per-entry-fragile nickname cache, a ponytail no-op cast, and an AC9 test-coverage gap), 2 items deferred as pre-existing, 7 dismissed as noise. Full regression green, ruff clean. Status → done.
