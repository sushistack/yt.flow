# Story 7.5: 키네틱 자막 (단어 단위 가라오케 하이라이트)

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a SCP YouTube content producer,
I want the burned-in subtitle to highlight each word as it is spoken (karaoke-style),
so that videos gain a production-value typography upgrade at zero extra data or dependency cost, using the per-word timing the pipeline already computes but currently discards.

## Acceptance Criteria

1. When `kinetic_subtitles_enabled` is true **and** a scene has real per-word `word_timings`, `subtitle_node` writes a `.ass` file (SubStation Alpha) instead of `.srt` for that scene, with one `{\k<cs>}word ` karaoke run per word.
2. Each word's `\k` duration equals `round((end_sec - start_sec) * 100)` centiseconds.
3. Cue boundaries (which words share one on-screen line) are **identical** to the existing SRT path (`_word_timings_to_segments` grouping, ≤40 chars per cue) — grouping logic is reused, not reimplemented.
4. The `.ass` header declares `PlayResX`/`PlayResY` matching the compositor resolution (1920×1080, i.e. `COMP_W`×`COMP_H`) so libass does not rescale.
5. The style's `\k` sweep colors the currently/already-spoken word amber (`&H0000D7FF`) and the not-yet-spoken word white (`&H00FFFFFF`) — see the **critical color-mapping gotcha** in Dev Notes.
6. Graceful fallback (no fabricated data): when the flag is off, **or** a scene has no per-word `word_timings` (aligner segment-level fallback), that scene writes plain `.srt` exactly as today. Both cases funnel to the same existing SRT path — one fallback, not two.
7. `build_ass_events` and `format_ass` are pure functions (no I/O, no settings access).
8. Font family for the ASS style is resolved via `fc-match` (family name, not file path), consistent with `video.py`'s existing font resolution; hard-fail if unresolvable rather than silently rendering an unstyled default.
9. `video.py` requires **no changes** — `subtitles='{path}'` auto-detects `.srt` vs `.ass` by extension, and `_escape_subtitles_path` escapes the path (not content), so it is format-agnostic.
10. No new pip dependency (libass ships with the ffmpeg already linked). No new pipeline node or gate.
11. All existing `subtitle_node` tests still pass, and new unit tests cover: `\k` duration math, cue-boundary parity with `_word_timings_to_segments`, header `PlayResX/Y`, flag-off → `.srt`, and no-word-timing → `.srt`.

## Tasks / Subtasks

- [ ] **Task 1 — Add config flag** (AC: 1, 6)
  - [ ] Add `kinetic_subtitles_enabled: bool = True` to `Settings` in [config.py](src/yt_flow/config.py), grouped near the aligner/chapter settings with a one-line comment. Env var is auto-derived: `YTFLOW_KINETIC_SUBTITLES_ENABLED` (prefix `YTFLOW_`).

- [ ] **Task 2 — Factor out shared cue-grouping helper** (AC: 3)
  - [ ] Extract the batching loop inside `_word_timings_to_segments` into `_group_words(timings, max_chars=40) -> list[list[WordTiming]]` (returns the word groups, not joined text).
  - [ ] Rewrite `_word_timings_to_segments` to call `_group_words` then map each group to an `AlignmentSegment` (`start_sec` = group[0], `end_sec` = group[-1], `text` = joined words). Behavior must be byte-identical to today — the existing grouping tests are the guard.

- [ ] **Task 3 — ASS/karaoke utilities in subtitle.py** (AC: 1,2,4,5,7,8)
  - [ ] `SUBTITLE_FONT_SIZE=48`, `SUBTITLE_OUTLINE_WIDTH=2`, and the two colors from the design (module-level constants).
  - [ ] `_ass_font_family() -> str` (cached with `@functools.lru_cache(maxsize=1)`): `fc-match --format=%{family}` for `"Noto Sans CJK KR"` then `"DejaVu Sans"`; raise `RuntimeError` if neither resolves. Mirror the try/except/timeout structure of `video.py:_drawtext_font()` but return `%{family}` not `%{file}`.
  - [ ] `_ass_header() -> str`: `[Script Info]` with `PlayResX: 1920` / `PlayResY: 1080`, plus `[V4+ Styles]` with one `Style` line. **Map colors per AC:5 gotcha** (PrimaryColour = amber highlight, SecondaryColour = white).
  - [ ] `build_ass_events(timings, max_chars=40) -> str`: call `_group_words`, emit one `Dialogue:` line per group; within each, concatenate `{\k<cs>}word ` runs where `<cs> = round((wt["end_sec"] - wt["start_sec"]) * 100)`. Dialogue `Start`/`End` = group start/end formatted as ASS time `H:MM:SS.cc`.
  - [ ] `format_ass(timings, max_chars=40) -> str` = `_ass_header() + build_ass_events(...)`.

- [ ] **Task 4 — Wire subtitle_node** (AC: 1, 6)
  - [ ] In the per-scene loop, after computing `timings`/`segments`: if `s.kinetic_subtitles_enabled` **and** `timings` (word-level present) → write `format_ass(timings)` to `scene_{n:03d}.ass`. Else → existing `format_srt(segments)` to `scene_{n:03d}.srt`.
  - [ ] `_validate_segments` still runs on `segments` in both branches (timing sanity is format-independent).
  - [ ] `subtitle_path` gets whichever path was written.

- [ ] **Task 5 — Tests** (AC: 11)
  - [ ] Add `kinetic_subtitles_enabled=True` to the `_settings_ns` helper in [test_subtitle.py](tests/pipeline/nodes/test_subtitle.py) so existing node tests don't break on the new attribute access. (See regression note in Dev Notes.)
  - [ ] Unit tests for `build_ass_events`/`format_ass`: `\k` cs == `round((end-start)*100)`; group boundaries == `_group_words`/`_word_timings_to_segments` for the same input; header has `PlayResX: 1920`/`PlayResY: 1080`.
  - [ ] Node test: flag on + word_timings → `.ass` file written, `subtitle_path` ends `.ass`.
  - [ ] Node test: flag on + empty word_timings (aligner path) → `.srt` (no fake per-word invented).
  - [ ] Node test: flag off + word_timings → `.srt`.

## Dev Notes

### 🔴 CRITICAL GOTCHA — ASS color mapping (do NOT map by variable name)
ASS `\k` transitions a word **from `SecondaryColour` to `PrimaryColour`**. For "the spoken word lights up amber", the **swept/highlight** color must be the Style's **`PrimaryColour`** and the **not-yet-spoken** color must be **`SecondaryColour`**. The design-doc variable names are the *opposite* of the ASS field names and will mislead a naive mapping:

- Style `PrimaryColour` field ← amber `&H0000D7FF` (the design calls this `SUBTITLE_HIGHLIGHT_COLOR`)
- Style `SecondaryColour` field ← white `&H00FFFFFF` (the design calls this `SUBTITLE_PRIMARY_COLOR`)

Name the constants for what they *are* (`_HIGHLIGHT_COLOR`, `_BASE_COLOR`) to avoid the trap. Color format is `&HAABBGGRR` (alpha-blue-green-red); `&H0000D7FF` = RGB(255,215,0) amber, `&H00FFFFFF` = white. ✅

### Reuse, do not reinvent
- **Cue grouping**: the ≤40-char batching already exists in `_word_timings_to_segments` ([subtitle.py:99](src/yt_flow/pipeline/nodes/subtitle.py#L99)). Factor it into `_group_words` and have both paths call it — AC:3 requires identical boundaries. Do NOT write a second grouping loop.
- **Font resolution**: `video.py:_drawtext_font()` ([video.py:278](src/yt_flow/pipeline/nodes/video.py#L278)) is the canonical `fc-match` pattern (Noto Sans CJK KR → DejaVu Sans, timeout=5, hard-fail). Copy its shape but request `%{family}` (ASS styles reference fontconfig *family names*, SRT/drawtext use file paths). Do not import `_drawtext_font` — different return contract; keep the small duplication local to `subtitle.py` to preserve the layer rule (see below).
- **`WordTiming`** TypedDict = `{word, start_sec, end_sec}` ([state.py:19](src/yt_flow/domain/state.py#L19)). Already imported in `subtitle.py`.

### Resolution constants (AC:4)
`COMP_W=1920`, `COMP_H=1080` live in `video.py` ([video.py:45](src/yt_flow/pipeline/nodes/video.py#L45)). **Do not import them from `video.py`** — that pulls the whole video/ffmpeg/subprocess module into the subtitle layer and risks import-time cost. Define local `PLAY_RES_X = 1920`, `PLAY_RES_Y = 1080` module constants in `subtitle.py` with a `# ponytail: must match video.COMP_W/COMP_H (compositor resolution)` comment. The test asserts they equal 1920×1080; if the compositor resolution ever changes, that test flags the drift.

### Layer rule (AD-1) — must preserve
`subtitle.py` imports **domain + config only** — no `db/`, `api/`, `services/`. There is an enforcing test (`test_no_db_api_service_imports`, [test_subtitle.py:415](tests/pipeline/nodes/test_subtitle.py#L415)). Adding `import functools`/`import subprocess` for `fc-match` is fine (video.py already does). Do not add a `video.py` import.

### Fallback discipline (AC:6) — no fabricated timing
`subtitle_node` has two data sources per scene ([subtitle.py:192-197](src/yt_flow/pipeline/nodes/subtitle.py#L192-L197)):
- `scene["word_timings"]` populated by `tts_node` → **real per-word** → eligible for ASS.
- aligner fallback (`aligner.align(...)`) → returns segment-level `AlignmentSegment` with **no per-word granularity** → SRT only.

The ASS branch keys strictly on `timings` (the `word_timings` list) being non-empty. When the aligner path runs, `timings` is empty → SRT. **Never** synthesize per-word `\k` durations from a segment. This is a graceful capability drop, not an error: some scenes get karaoke, some don't, depending on the alignment data that actually existed.

### 🟡 Regression risk — test settings helper
`subtitle_node` will read `s.kinetic_subtitles_enabled`. The unit tests inject a `SimpleNamespace` via `_settings_ns` ([test_subtitle.py:28](tests/pipeline/nodes/test_subtitle.py#L28)) that does **not** have this field → every node test would `AttributeError`. Add `kinetic_subtitles_enabled=True` (default-ish) to `_settings_ns` as part of this story, or the node's read will break the whole suite. (Prefer a real attribute over `getattr(..., True)` in production code so a missing setting surfaces loudly; the fix belongs in the test helper.)

### video.py — genuinely no changes (AC:9)
Verified: the caller passes `subtitles='{sub}'` with the path from `subtitle_path` ([video.py:466](src/yt_flow/pipeline/nodes/video.py#L466), [video.py:480](src/yt_flow/pipeline/nodes/video.py#L480)); the `subtitles=` filter auto-detects format by extension. `_escape_subtitles_path` ([video.py:257](src/yt_flow/pipeline/nodes/video.py#L257)) escapes `\`, `'`, `:` in the *path* — format-agnostic. `_validate_scene_assets`'s subtitle check is an existence check (extension-agnostic). Do not touch `video.py`.

### ASS time format
Dialogue timestamps use `H:MM:SS.cc` (centiseconds, single-digit hour, e.g. `0:00:01.25`) — distinct from SRT's `HH:MM:SS,mmm`. Write a small `_ass_time(sec)` helper; don't reuse `_srt_time`.

### Minimal ASS skeleton (reference, adapt exactly)
```
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,<family>,48,&H0000D7FF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,{\k50}격리 {\k100}절차
```
(Alignment `2` = bottom-center. Field order in `Style:`/`Dialogue:` must match the `Format:` line exactly — libass is positional.)

### Project Structure Notes
- Files touched: `src/yt_flow/config.py` (1 line), `src/yt_flow/pipeline/nodes/subtitle.py` (new pure functions + node branch), `tests/pipeline/nodes/test_subtitle.py` (helper fix + new tests). **No new files, no new dependency, no new node/gate.**
- Naming: `scene_{n:03d}.ass` mirrors the existing `scene_{n:03d}.srt` convention ([subtitle.py:203](src/yt_flow/pipeline/nodes/subtitle.py#L203)).
- Epic 7 ordering: 7-5 is **mood-independent** and touches only `subtitle.py`/`config.py` — no collision with 7-1..7-4 (which all modify `video.py`). Safe to implement independently of the other Epic 7 stories.

### Testing standards
- Pytest, async tests already enabled (existing node tests are `async def` without explicit markers). No GPU/network/model — settings and aligner are monkeypatched. New ASS tests are pure-function assertions (no fixtures needed beyond string checks).
- Run: `PYTHONPATH=$PWD/src pytest tests/pipeline/nodes/test_subtitle.py -q` (worktree editable-install shadowing caveat if run outside main tree).

### References
- [Source: docs/superpowers/specs/2026-07-04-kinetic-subtitles-design.md] — full design (ASS rationale, `\k` semantics, fallback, settings, testing, error handling)
- [Source: _bmad-output/planning-artifacts/epics.md#Story 7.5] — story definition & Epic 7 ordering constraints
- [Source: src/yt_flow/pipeline/nodes/subtitle.py] — SRT path, `_word_timings_to_segments`, `subtitle_node` loop
- [Source: src/yt_flow/pipeline/nodes/video.py] — `_drawtext_font` (fc-match), `_escape_subtitles_path`, `COMP_W/COMP_H`, `subtitles=` usage
- [Source: src/yt_flow/domain/state.py#L19] — `WordTiming` / `SceneState`
- [Source: src/yt_flow/config.py] — `Settings` (`env_prefix="YTFLOW_"`)

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
