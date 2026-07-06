---
title: 'Subtitle word/segment fallback: fix silent empty return'
type: 'bugfix'
created: '2026-07-06'
status: 'done'
route: 'one-shot'
---

# Subtitle word/segment fallback: fix silent empty return

## Intent

**Problem:** `WhisperXAligner._align_sync` checked truthiness of the raw `word_segments` list before filtering it for usable `start`/`end` keys. If `word_segments` was non-empty but no entry had both keys, the filtered result was `[]` and that empty list was returned directly — the intended `segments`-level fallback was never reached, so a scene could silently end up with zero subtitles.

**Approach:** Extracted the branching logic into a pure `_words_or_segments(aligned: dict)` helper that builds the filtered word list first, then falls back to `segments` only when that filtered list is empty — fixing the fully-empty case and making the logic directly unit-testable without mocking WhisperX. Deferred the remaining "partially-usable word list" edge case to `deferred-work.md` (pre-existing behavior, not a regression from this fix).

## Suggested Review Order

- Entry point: the fixed fallback decision, now based on the filtered result instead of the raw list.
  [`subtitle.py:67-77`](../../src/yt_flow/pipeline/nodes/subtitle.py#L67-L77)

- Direct unit tests for the extracted function, covering fully-usable, fully-unusable, and missing-`word_segments` cases.
  [`test_subtitle.py:265-294`](../../tests/pipeline/nodes/test_subtitle.py#L265-L294)

- New deferred item recording the still-open partial-usable-words edge case found during adversarial review.
  [`deferred-work.md`](./deferred-work.md)
