---
baseline_commit: e7c5ebfb438e426729a5f8f68aea48f475faa1f0
---

# Story 7.4: Transition Variety (mood-driven xfade type)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a video pipeline maintainer,
I want the scene-to-scene transition **type** to be chosen from the upcoming scene's `mood` (instead of a single hardcoded `fadeblack`),
so that a transition visually announces the mood shift the same way the sound-design stinger and the color-grade chapter card already do — one rule, three features.

## ⛔ BLOCKING DEPENDENCY — READ FIRST

**This story depends on Story 7.1 (sound design), which is NOT yet implemented.** The `mood` machinery this story consumes does not exist in the codebase today. Verify before starting:

```bash
grep -n "mood" src/yt_flow/domain/state.py            # SceneState.mood must exist
grep -rn "resolve_mood\|MOOD_VALUES\|DEFAULT_MOOD" src/yt_flow/pipeline/nodes/sound_design.py
```

Confirmed absent as of story creation (2026-07-04): there is **no** `SceneState.mood` field ([src/yt_flow/domain/state.py:37](../../src/yt_flow/domain/state.py#L37) `SceneState` has only `scene_num, narration, shots, audio_path, audio_duration, word_timings, subtitle_path`) and **no** `sound_design.py` module. If 7.1 has not landed:

- **Do not stub or re-define `mood`/`resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD` in this story.** 7.1 is the sole owner of that taxonomy (per epics.md "순서 제약"). Duplicating it is the exact reinvention this workflow exists to prevent.
- **HALT and report** that 7.1 must be completed first, unless the user explicitly authorizes proceeding.

This story's contract with 7.1 (from [2026-07-04-sound-design-design.md](../../docs/superpowers/specs/2026-07-04-sound-design-design.md)):
- `SceneState.mood: str` — one of `MOOD_VALUES`
- `MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")`
- `DEFAULT_MOOD = "dread"`
- `resolve_mood(mood: str | None) -> str` — unknown/missing/empty → `DEFAULT_MOOD` (lenient, already unit-tested by 7.1's suite)

## Acceptance Criteria

1. **`MOOD_XFADE_MAP` + `resolve_transition`** exist in [video.py](../../src/yt_flow/pipeline/nodes/video.py). Map: `dread→fadeblack`, `clinical→fadeblack`, `escalation→wipeleft`, `revelation→fadewhite`. `resolve_transition(mood: str | None) -> str` returns `MOOD_XFADE_MAP[resolve_mood(mood)]` (delegates fallback to `resolve_mood`; unknown/`None` mood → `dread` → `fadeblack`).
2. **Only the transition type varies by mood.** `XFADE_DURATION = 0.5` stays constant for every boundary regardless of mood. Do **not** add duration-by-mood variation.
3. **`_join_with_xfade` takes per-segment transition types.** The `segments` list becomes `list[tuple[Path, float, str]]`; the third element is the transition to use *entering* that segment. Boundary `i` uses `segments[i+1][2]` ("next segment announces its own cut-in"). The offset math is unchanged (still `Σ(dur_0..i) − (i+1)·XFADE_DURATION`) and the acrossfade audio behavior is unchanged.
4. **`video_node` builds the tuples.** Each scene tuple carries its mood-resolved transition; each chapter-card tuple carries `"fadeblack"`.
5. **Chapter-card boundaries are always `fadeblack`** — any boundary touching a card (scene→card or card→scene) uses `fadeblack`, never a mood-driven type. See the Dev Notes "Card-adjacency correctness" section — this is a **non-obvious correctness requirement**, not automatically satisfied by the naive construction.
6. **Config flag `transition_variety_enabled: bool = True`** added to [config.py](../../src/yt_flow/config.py) `Settings` (env `YTFLOW_TRANSITION_VARIETY_ENABLED`). When `False`, every scene-to-scene boundary uses `"fadeblack"` — byte-for-byte today's behavior.
7. **Existing `_join_with_xfade` tests still pass** after being updated to the 3-tuple shape (they currently pass 2-tuples and will break otherwise). New tests cover `resolve_transition` mapping (all 4 moods + `None`/unknown fallback), the per-boundary transition name in the filtergraph, the card-adjacency `fadeblack` guarantee, and the `enabled=False` all-`fadeblack` path.

## Tasks / Subtasks

- [x] **Task 0 — Verify 7.1 landed (AC: blocking dep)**
  - [x] Run the two `grep` checks in the Blocking Dependency section. If `mood`/`sound_design` absent → HALT and report.
- [x] **Task 1 — Config flag (AC: 6)**
  - [x] Add `transition_variety_enabled: bool = True` to `Settings` in [config.py](../../src/yt_flow/config.py), near the Chapter-card block (lines 75–78), with a one-line comment referencing Story 7.4.
- [x] **Task 2 — `resolve_transition` + `MOOD_XFADE_MAP` (AC: 1, 2)**
  - [x] Add `MOOD_XFADE_MAP: dict[str, str]` and `def resolve_transition(mood: str | None) -> str` to [video.py](../../src/yt_flow/pipeline/nodes/video.py), beside the existing `XFADE_TRANSITION`/`XFADE_DURATION` constants (lines 60–62).
  - [x] Import `resolve_mood` from `yt_flow.pipeline.nodes.sound_design` (7.1's module). Follow the existing top-of-file import style at [video.py:22-23](../../src/yt_flow/pipeline/nodes/video.py#L22).
  - [x] Keep `XFADE_TRANSITION = "fadeblack"` — it remains the card transition and the `enabled=False` fallback value. Do not delete it.
- [x] **Task 3 — `_join_with_xfade` 3-tuple signature (AC: 3)**
  - [x] Change signature to `segments: list[tuple[Path, float, str]]`.
  - [x] In the loop, unpack the third element and use `transition = segments[i + 1][2]` for boundary `i` (the entering segment announces its cut-in). Replace the hardcoded `XFADE_TRANSITION` in the `xfade=transition=...` f-string with this per-boundary value.
  - [x] Update the `for path, _ in segments` input-args loop to `for path, _, _ in segments`.
  - [x] Preserve the running-offset math and the acrossfade line **exactly** — this is the #1 xfade bug source (see the docstring at [video.py:541-548](../../src/yt_flow/pipeline/nodes/video.py#L541)).
- [x] **Task 4 — `video_node` builds tuples with card-adjacency guard (AC: 4, 5, 6)**
  - [x] In the `else` branch that builds `join_segments` ([video.py:674-683](../../src/yt_flow/pipeline/nodes/video.py#L674)), change to 3-tuples.
  - [x] Gate on the config flag: when `transition_variety_enabled` is `False`, every scene tuple's transition is `XFADE_TRANSITION` ("fadeblack").
  - [x] Apply the card-adjacency rule (see Dev Notes): a scene tuple that is immediately preceded by a card must use `"fadeblack"`, not its mood transition. Card tuples are always `"fadeblack"`.
- [x] **Task 5 — Tests (AC: 7)**
  - [x] Update the 5 existing `_join_with_xfade` tests in [tests/pipeline/nodes/test_video.py](../../tests/pipeline/nodes/test_video.py) (lines ~296–375) to pass 3-tuples `(path, dur, "fadeblack")`.
  - [x] Add `test_resolve_transition_*`: all 4 moods map correctly + `None`/`"garbage"` → `"fadeblack"` (via `dread`).
  - [x] Add a test asserting a mood-varied scene boundary produces its expected transition name in `filter_complex` (e.g. an `escalation` scene → `transition=wipeleft`).
  - [x] Add a card-adjacency test: with chapter cards enabled and scenes of varied moods, every `transition=` token in the filtergraph is `fadeblack`.
  - [x] Add an `enabled=False` test: mood-varied scenes, flag off → all boundaries `fadeblack`.
  - [x] Run: `PYTHONPATH=$PWD/src python -m pytest tests/pipeline/nodes/test_video.py -q`

## Dev Notes

### What exists today (files this story modifies — READ before editing)

- **[video.py:60-62](../../src/yt_flow/pipeline/nodes/video.py#L60)** — `XFADE_TRANSITION = "fadeblack"` (single hardcoded constant, carries a `# ponytail:` note about "single crossfade type until a second is actually wanted" — this story is that second type), `XFADE_DURATION = 0.5`.
- **[video.py:537-598](../../src/yt_flow/pipeline/nodes/video.py#L537) `_join_with_xfade`** — currently `segments: list[tuple[Path, float]]`. Iterates building a chained `xfade`+`acrossfade` filtergraph with cumulative `running_offset`. The transition name is hardcoded at [video.py:569](../../src/yt_flow/pipeline/nodes/video.py#L569). This is the primary function to change. **Preserve** the offset accumulation and the acrossfade line — they are unrelated to transition type and must not regress.
- **[video.py:674-683](../../src/yt_flow/pipeline/nodes/video.py#L674) `video_node`** — the `else` (2+ scenes) branch builds `join_segments` and interleaves chapter cards between scenes when `chapter_cards_enabled`. Sequence when cards on: `scene0, card, scene1, card, scene2, …`; when off: `scene0, scene1, scene2, …`. This is where scene/card tuples are constructed.
- **[config.py:75-78](../../src/yt_flow/config.py#L75)** — `Settings(BaseSettings)`, `env_prefix="YTFLOW_"`, existing `chapter_cards`/`chapter_card_duration_sec` — copy this pattern for the new flag.
- **`_settings()`** accessor at [video.py:272](../../src/yt_flow/pipeline/nodes/video.py#L272); `video_node` already holds `s = _settings()` at [video.py:654](../../src/yt_flow/pipeline/nodes/video.py#L654) — read `s.transition_variety_enabled` from there.

### Card-adjacency correctness — the non-obvious part (AC: 5)

The design's "next segment announces its own cut-in" rule (`segments[i+1][2]`) does **not** automatically honor the "card→scene stays fadeblack" exemption if you naively give every scene tuple `resolve_transition(mood)`. Walk it:

With cards on, sequence is `scene0, card, scene1, card, scene2`. Boundaries and the segment that announces each:
- `scene0→card` → announced by `card` → `fadeblack` ✓
- `card→scene1` → announced by `scene1` → **would be `resolve_transition(mood)`** ✗ (design requires `fadeblack`)

**Resolution (recommended, minimal):** a scene is mood-driven only when it is *not* preceded by a card. When `chapter_cards_enabled` is true, every scene after `scene0` is preceded by a card, so it must be `fadeblack`. `segments[0][2]` is never read (nothing precedes the first segment). Net effect — clean and matching the design's intent ("only scene-to-scene boundaries are mood-driven"; with cards on there are none):

```python
# in video_node's else branch
variety = s.transition_variety_enabled
join_segments: list[tuple[Path, float, str]] = []
for i, (seg_path, duration, _, _) in enumerate(segs_with_specs):
    preceded_by_card = chapter_cards_enabled and i > 0
    if variety and not preceded_by_card:
        transition = resolve_transition(scenes[i].get("mood"))
    else:
        transition = XFADE_TRANSITION  # "fadeblack": card-adjacent, or variety off
    join_segments.append((seg_path, duration, transition))
    if chapter_cards_enabled and i < len(segs_with_specs) - 1:
        label = _card_label(scenes[i + 1])
        card_path = await _compose_chapter_card(label, i + 1, run_dir, card_duration)
        join_segments.append((card_path, card_duration, XFADE_TRANSITION))  # cards always fadeblack
        card_count += 1
await _join_with_xfade(join_segments, output)
```

Use `scenes[i].get("mood")` (not `scenes[i]["mood"]`) — `resolve_mood` is deliberately lenient about missing/invalid mood, and a `KeyError` here would defeat that. `SceneState` is a `TypedDict`, so `.get()` is valid at runtime.

### `resolve_transition` / map (Task 2)

```python
# video.py, beside XFADE_TRANSITION / XFADE_DURATION
MOOD_XFADE_MAP: dict[str, str] = {
    "dread": "fadeblack",       # unchanged — Story 5.1 found plain "fade" overlapped both images
    "clinical": "fadeblack",    # keep the calmer moods on the proven default
    "escalation": "wipeleft",   # directional/kinetic — tune by eye against a live render
    "revelation": "fadewhite",
}

def resolve_transition(mood: str | None) -> str:
    return MOOD_XFADE_MAP[resolve_mood(mood)]
```

All 4 values are ffmpeg built-in `xfade` transition names — **zero new dependencies**, just a different string in a filter ffmpeg already runs. No new failure modes: every map value is a valid `xfade` name and `resolve_mood` covers missing/invalid mood.

### Scope guardrails (do NOT do)

- Do not vary `XFADE_DURATION` by mood (AC: 2). One axis of variation per feature — same reasoning as color-grade's "only hue varies."
- Do not add a second mapping table for card boundaries — cards are a flat `"fadeblack"` (design decision: not worth the complexity for a rare boundary type).
- Do not touch the audio (`acrossfade`) path — transition type is video-only.
- Do not redefine the mood taxonomy — import it from 7.1's `sound_design`.
- The `escalation`/`revelation` picks (`wipeleft`/`fadewhite`) are illustrative and meant to be tuned by eye on a live render — but ship them as-is; retuning is a follow-up, not this story.

### Testing standards

- Framework: `pytest` (+ `pytest-asyncio` — the node tests are `async def`). Tests live in `tests/pipeline/nodes/test_video.py`.
- Existing xfade tests monkeypatch `video._run_ffmpeg` with an `async _capture` that grabs the `-filter_complex` arg — reuse that exact pattern for new filtergraph assertions ([test_video.py:296-330](../../tests/pipeline/nodes/test_video.py#L296)).
- `_settings_ns(tmp_path, chapter_cards=..., ...)` fake-settings helper at [test_video.py:34](../../tests/pipeline/nodes/test_video.py#L34) defaults cards **off**; extend it with a `transition_variety_enabled` kwarg (default matching whatever the video_node-level tests need) if you add node-level (not just `_join_with_xfade`-level) tests.
- **Worktree gotcha** (recorded, [[worktree-editable-install-shadowing]]): if implementing in a git worktree, the global editable install shadows the worktree's `src`; run pytest with `PYTHONPATH=$PWD/src`.

### Ponytail

`resolve_transition` is a one-line pure function; `_join_with_xfade` grows one tuple element and one lookup — no new module, no abstraction, no dependency. This is the minimum diff that adds a second transition type. Mark nothing new as `# ponytail:` except: the existing `XFADE_TRANSITION` ponytail comment at [video.py:59-61](../../src/yt_flow/pipeline/nodes/video.py#L59) can be updated/removed since the "second type" it deferred now exists.

### Project Structure Notes

- No new files. Changes confined to `video.py`, `config.py`, `test_video.py`. Aligns with the epic constraint: "전부 새 LangGraph 노드 없이 `video_node`를 확장하는 순수 필터·에셋 추가."
- **Parallel-session hazard** (epics.md "순서 제약"): stories 7.1/7.2/7.3/7.4 all touch `video.py`. 7.4 changes the `_join_with_xfade` signature and `video_node`'s `join_segments` block; 7.1 adds `_compose_scene` audio mixing; 7.3 changes the zoompan/effect math. If any of those are in flight concurrently, expect merge conflicts in `video.py` and coordinate/rebase — do not resolve blindly. This project has a history of parallel-session file collisions ([[project_3-3-dashboard-picker-done]]).

### References

- [Source: docs/superpowers/specs/2026-07-04-transition-variety-design.md] — full design (map, `_join_with_xfade` change, card exemption, settings, testing).
- [Source: docs/superpowers/specs/2026-07-04-sound-design-design.md#L98-L118] — the `resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD` contract this story imports (owned by Story 7.1).
- [Source: _bmad-output/planning-artifacts/epics.md — Epic 7 / Story 7.4] — epic goal, ordering constraint (7.1 precedes 7.4), depends_on: 7.1.
- [Source: src/yt_flow/pipeline/nodes/video.py#L537-L598] — `_join_with_xfade` current implementation.
- [Source: src/yt_flow/pipeline/nodes/video.py#L674-L683] — `video_node` join-segment / chapter-card construction.
- [Source: src/yt_flow/domain/state.py#L37] — `SceneState` (mood field to be added by 7.1).
- [Source: tests/pipeline/nodes/test_video.py#L296-L375] — existing xfade tests requiring 3-tuple migration.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- `PYTHONPATH=$PWD/src python -m pytest tests/pipeline/nodes/test_video.py -q` → 131 passed
- `PYTHONPATH=$PWD/src python -m pytest -q` (full regression) → 669 passed, 1 skipped (pre-existing ffmpeg-integration skip), 193s
- `ruff check src/yt_flow/pipeline/nodes/video.py src/yt_flow/config.py tests/pipeline/nodes/test_video.py` → All checks passed

### Completion Notes List

- Blocking dependency verified: Story 7.1 landed (`SceneState.mood`, `sound_design.resolve_mood/MOOD_VALUES/DEFAULT_MOOD` all present) — proceeded without HALT.
- Implemented exactly per Dev Notes recommended code: `MOOD_XFADE_MAP`/`resolve_transition` beside the existing xfade constants, `_join_with_xfade` migrated to 3-tuples with `segments[i+1][2]` as the per-boundary transition, `video_node`'s `join_segments` construction gated on `transition_variety_enabled` with the card-adjacency guard (`preceded_by_card = chapter_cards_enabled and i > 0`).
- `resolve_mood` was already imported in video.py (added by 7.2/7.3 for other mood-driven features), so no new import was needed.
- The story's Task 5 said "5 existing tests" needed 2-tuple→3-tuple migration; actual count was 7 call sites across 7 test functions (including one integration test gated on `ffmpeg`/`ffprobe` availability) — all updated.
- Updated the `# ponytail:` comment on `XFADE_TRANSITION` (video.py) since the "second type until wanted" it deferred now exists via `MOOD_XFADE_MAP`.
- `_settings_ns` test helper extended with `transition_variety_enabled` kwarg (default `False`, matching the existing off-by-default pattern for pre-7.4 tests) per Dev Notes testing-standards guidance.
- Added 4 new node-level/unit test groups: `resolve_transition` mapping (4 moods + None/garbage fallback), per-boundary transition in `_join_with_xfade`'s filtergraph, card-adjacency all-fadeblack guarantee, and `transition_variety_enabled=False` all-fadeblack path — plus the `Settings.transition_variety_enabled` default-true config test.
- No scope deviations: no new files, no duration-by-mood variation, no second card mapping table, audio path untouched.

### File List

- `src/yt_flow/config.py` — added `transition_variety_enabled: bool = True`
- `src/yt_flow/pipeline/nodes/video.py` — added `MOOD_XFADE_MAP`/`resolve_transition`; migrated `_join_with_xfade` to 3-tuple segments; updated `video_node`'s `join_segments` construction with card-adjacency guard; updated `XFADE_TRANSITION` ponytail comment
- `tests/pipeline/nodes/test_video.py` — migrated 7 existing `_join_with_xfade` call sites to 3-tuples; extended `_settings_ns` with `transition_variety_enabled`; added `resolve_transition`/`MOOD_XFADE_MAP` import; added tests for mood mapping, per-boundary filtergraph transition, card-adjacency guarantee, variety-disabled path, and config default

### Review Findings

Reviewed via Blind Hunter (diff-only adversarial), Edge Case Hunter (diff + project read), and Acceptance Auditor (diff + spec). No AC violations found — all 7 ACs traced and satisfied.

- [x] [Review][Patch] `MOOD_XFADE_MAP[resolve_mood(mood)]` has no guard tying its key set to `sound_design.MOOD_VALUES` — same class of bug already fixed once in Story 7.2's `color_grade.MOOD_GRADE_PARAMS`; a future taxonomy change would raise an uncaught `KeyError` mid-render instead of degrading gracefully [src/yt_flow/pipeline/nodes/video.py]
- [x] [Review][Patch] `test_join_with_xfade_per_boundary_transition` only asserts substring containment (`"xfade=transition=wipeleft" in fc`), not positional order — a bug that swapped which boundary gets which transition would still pass [tests/pipeline/nodes/test_video.py]
- [x] [Review][Patch] No test exercises two distinct mood-driven boundaries in the same multi-scene `video_node` run — the only config where mood-driven transitions actually surface (`chapter_cards` off) had just one such boundary covered [tests/pipeline/nodes/test_video.py]
- [x] [Review][Defer] `preceded_by_card = chapter_cards_enabled and i > 0` assumes a card is inserted before every scene but the first whenever `chapter_cards_enabled` is true; nothing enforces this if card insertion ever becomes conditional (e.g. skipped for scenes under `MIN_CARD_DURATION`) — no such conditional exists today, pre-existing structural assumption, not caused by this change [src/yt_flow/pipeline/nodes/video.py]

Dismissed as noise (9): feature is a no-op whenever the also-default-on `chapter_cards` is enabled — this is the spec's own stated design intent (Dev Notes: "with cards on there are none"), not a defect, flagged to Jay separately as a product note; `resolve_transition` missing a docstring (one-line pure function, self-documented by the dict above it); `revelation → fadewhite` mapping lacking inline rationale (illustrative pick, spec says "ship as-is, tune later"); segments tuple growing 2→3 without a `NamedTuple` (matches existing plain-tuple style, no new abstraction per Ponytail); general "this is speculative complexity" critique (directly spec-mandated AC1-7, zero new dependencies); `variety` local variable naming (cosmetic); scattered indexing-convention comments across 3 places (each comment is locally correct, not a defect); `transition_variety_enabled` defaulting `True` on introduction (matches existing precedent for `sound_design_enabled`/`post_fx_enabled`/`parallax_enabled`, spec AC:6 mandates default `True`); dead `resolve_transition` call for `segments[0]` (harmless — becomes moot once the `MOOD_XFADE_MAP`/`MOOD_VALUES` invariant guard above is added).

## Change Log

- 2026-07-06: Implemented Story 7.4 (mood-driven xfade transition type). All 7 tasks complete, all ACs satisfied. Full regression suite green (669 passed, 1 pre-existing skip). Status → review.
- 2026-07-06: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). No AC violations. 3 patches applied: `MOOD_XFADE_MAP`↔`MOOD_VALUES` invariant guard, positional assertion in the per-boundary xfade test, a multi-boundary `video_node` test. 1 item deferred (pre-existing card-insertion assumption). Full regression green (680 passed, 1 pre-existing skip), ruff clean. Status → done.
