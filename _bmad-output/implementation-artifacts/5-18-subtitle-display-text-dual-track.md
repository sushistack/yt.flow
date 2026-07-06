---
created: 2026-07-06
story_key: 5-18-subtitle-display-text-dual-track
story_id: "5.18"
epic: 5
depends_on:
  - 5-4-tts-korean-naturalization   # this story REVERSES its "same text for SRT+TTS" decision
  - 7-5-kinetic-subtitles           # this story RETIRES its karaoke \k path
soft_depends_on:
  - 5-17-chapter-card-content       # shares the bundled Pretendard font (whichever lands first adds data/fonts/)
baseline_commit: eb9e2964860cd183050607a00ffb9b260bee70af
---

# Story 5.18: Subtitle Display Text — Dual Track + Typography-First Static Subtitles

Status: ready-for-dev

## Story

As Jay,
I want subtitles to show the original script text ("SCP-049", "1.9m") as clean static lines with strong typography, while TTS keeps speaking the phoneticized Korean ("에스시피 공사 구", "키 일점 구 미터"),
so that on-screen text reads like professional documentary subtitles instead of a pronunciation guide with a fake word-highlight.

## Context

Context: Jay viewing feedback on E2E baseline 2026-07-06 (run `272b05a4`, SCP-049) — feedback #3. Report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`. Design follows Korean subtitle norms (Netflix Korean timed-text style-guide lineage — **proper nouns and alphanumerics in original orthography**, max 2 lines, ~16 chars/line as line-break guidance) and documentary narration convention (clean static line, not per-word highlight) per Jay's direction (2026-07-06).

**Two deliberate reversals of prior decisions:**
1. **Story 5.4's single-track decision.** 5.4's Context said "Do not implement a separate display subtitle text" and its AC2 mandated "TTS and subtitles use exactly the same text via `SceneState.narration`" — a YAGNI call that was right until a human watched the output: the E2E baseline burned "에스시피 공사 구" into the frame. The dual track is now a demonstrated need.
2. **Story 7.5's karaoke `\k` path is retired** (Jay's call). The highlight was fake anyway — E2E defect D12 showed 100% uniform-timing fallback (all 8 scenes at uniform 55–70cs; `_provisional_timings` is uniform by construction, [src/yt_flow/pipeline/nodes/tts.py:106-122](../../src/yt_flow/pipeline/nodes/tts.py#L106), and even whisperx degraded to segment level, commit `eb9e296`), so it never synced to speech. Per-word highlight is shorts grammar; documentary narration wants a static line. Side effect: **the word-level alignment problem is moot for subtitles** — sentence-level timing from measured audio is all rendering needs, and the spoken-word→display-word mapping question from the dual-track design disappears entirely.

Current single-track flow: `tts_normalize_step` **replaces** `narration` with normalized text ([src/yt_flow/pipeline/nodes/scenario_chain.py:296-310](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L296)), discarding the original; `tts_node` speaks it and derives uniform `word_timings` from it ([tts.py:167, 173](../../src/yt_flow/pipeline/nodes/tts.py#L167)); `subtitle_node` renders those normalized tokens as karaoke `.ass` ([src/yt_flow/pipeline/nodes/subtitle.py:296-313](../../src/yt_flow/pipeline/nodes/subtitle.py#L296)).

## Acceptance Criteria

1. **Dual track exists after scenario.** Given `tts_normalize_step` accepts a scene's normalization, then the scene carries BOTH `narration` (normalized, spoken track — meaning unchanged for TTS/alignment) and a new `display_narration` (the pre-normalization original writing text, preserved **code-side** — the step already holds it; no prompt change, see Dev Notes), and `build_scenes` copies `display_narration` onto `SceneState` ([src/yt_flow/domain/state.py:38-46](../../src/yt_flow/domain/state.py#L38); drift-guard `EXPECTED_FIELDS["SceneState"]` in [tests/domain/test_state_imports.py:20-23](../../tests/domain/test_state_imports.py#L20) updated in the same commit). The 1:1 sentence contract holds across tracks: `split_sentences(display)` and `split_sentences(narration)` counts are equal, so `ShotData.sentence_indices` stay valid against both.
2. **Mismatch fallback mirrors 5.4.** Given a scene where normalization changes the sentence count (5.4's per-scene fallback, [scenario_chain.py:299-307](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L299)), then BOTH tracks keep the original text (display == spoken == original) and the existing WARNING fires — the dual track degrades to single-track, never to desynced tracks.
3. **TTS and alignment stay on the normalized track.** Given `tts_node` and the whisperx aligner run, then they consume `scene["narration"]` exactly as today ([tts.py:167, 173](../../src/yt_flow/pipeline/nodes/tts.py#L167), [subtitle.py:300](../../src/yt_flow/pipeline/nodes/subtitle.py#L300)) — audio and timings must match what is spoken. `tts.py` requires zero changes.
4. **Static .ass with original-orthography display text.** Given `subtitle_node` runs, then it always emits `.ass` (kept for styling control) containing plain `Dialogue` lines — **no `\k` tags anywhere** — whose text comes from the display track: one cue per display sentence, cue timing = that sentence's window on the spoken track (derived by consuming `len(sentence.split())` word-timings per `split_sentences(narration)` sentence — measured audio, no whisperx word alignment needed), wrapped to **max 2 lines** (`\N`) breaking at word boundaries with ~16 chars/line as guidance (soft, not a hard limit — we burn in large type for YouTube); a sentence exceeding what 2 lines comfortably hold (~44 chars soft cap) splits into consecutive cues with its window divided proportionally by character count. "SCP-049" appears; "에스시피" does not. `_validate_segments` monotonic/bounded invariants ([subtitle.py:136-151](../../src/yt_flow/pipeline/nodes/subtitle.py#L136)) still run on the emitted cues.
5. **7.5 kinetic retirement — explicit deletion list.** Given the new renderer, then ALL of the following are removed: karaoke `\k` generation (`build_ass_events`, [subtitle.py:226-238](../../src/yt_flow/pipeline/nodes/subtitle.py#L226)), the word-grouping machinery it fed (`_group_words`/`_word_timings_to_segments`, [subtitle.py:106-133](../../src/yt_flow/pipeline/nodes/subtitle.py#L106)), the karaoke color-swap hack (`_HIGHLIGHT_COLOR`/`_BASE_COLOR` primary/secondary inversion, [subtitle.py:158-165](../../src/yt_flow/pipeline/nodes/subtitle.py#L158)), the `kinetic_subtitles_enabled` config flag ([src/yt_flow/config.py:66-68](../../src/yt_flow/config.py#L66)) and its routing branch ([subtitle.py:306-313](../../src/yt_flow/pipeline/nodes/subtitle.py#L306)), and the `.srt` output path (`format_srt`/`_srt_time`, [subtitle.py:89-103](../../src/yt_flow/pipeline/nodes/subtitle.py#L89)) — `.ass` becomes the only output (consumers checked: the ffmpeg `subtitles=` burn-in filter handles .ass; the artifacts API serializes `subtitle_path` generically ([src/yt_flow/services/run_service.py:121-126](../../src/yt_flow/services/run_service.py#L121)); `edit_artifact` writes raw text format-agnostically ([run_service.py:648-655](../../src/yt_flow/services/run_service.py#L648)); nothing in `src/` or `frontend/src` hardcodes `.srt`). The `{`/`}`/`\` stripping guard (`_escape_ass_word`, [subtitle.py:221-223](../../src/yt_flow/pipeline/nodes/subtitle.py#L221)) is KEPT for dialogue text (override-injection safety). 7.5's tests are replaced per Task 5, not silently dropped.
6. **Typography spec — bundled Pretendard, styled for 1080p burn-in.** Given the `.ass` header ([subtitle.py:192-209](../../src/yt_flow/pipeline/nodes/subtitle.py#L192)), then: font is **Pretendard SemiBold** vendored in-repo at `data/fonts/` (SIL OFL — bundleable; do NOT fetch at runtime; source in Dev Notes), resolved via the ffmpeg `subtitles=` filter's `fontsdir` parameter so rendering never depends on system fonts — both `subtitles='{sub}'` call sites in `_compose_scene` gain `:fontsdir='<escaped data/fonts path>'` ([src/yt_flow/pipeline/nodes/video.py:602, 614](../../src/yt_flow/pipeline/nodes/video.py#L602)) and `_ass_font_family()`'s fc-match chain ([subtitle.py:170-189](../../src/yt_flow/pipeline/nodes/subtitle.py#L170)) is deleted. Style: white fill (`PrimaryColour &H00FFFFFF` — now genuinely the fill, the karaoke swap is gone), black outline `Outline=3`, subtle shadow `Shadow=1`, `Fontsize=60` (PlayResY=1080 → 60px ≈ 1/18 of frame height, inside the directed 56–64 band), `Alignment=2` bottom-center, `MarginV=54` (~5% safe area, up from 30).
7. **Guarded degradation.** Given preconditions fail at subtitle time — `display_narration` absent (old checkpoints: `.get` default), display == spoken, unequal sentence counts across tracks, or `word_timings` token count ≠ `narration.split()` count — then `subtitle_node` renders the SPOKEN text through the same static-.ass pipeline (sentence cues still work on the spoken track alone), logging a WARNING for the count-mismatch cases, never failing the stage. The whisperx-fallback branch (empty `word_timings`) emits the aligner's segments as static `.ass` cues (aligner text = normalized; documented limitation, Saved Questions).
8. **Gate visibility.** Given the scenario artifacts API serializes scenes ([run_service.py:83-100](../../src/yt_flow/services/run_service.py#L83)), then `display_narration` is included (`.get` with fallback to `narration`) so the reviewer can diff spoken vs display text at the gate.
9. **Tests + live validation.** Given the suite runs, then chain/node/drift tests cover ACs 1–8 (Task 5), and a live check renders the `.ass` from a real normalized pair (e.g. original "SCP-049는 키 1.9m의 개체입니다." / spoken "에스시피 공사 구는 키 일점 구 미터의 개체입니다.") over real audio AND burns one frame via the real ffmpeg `subtitles=...:fontsdir=...` filter — confirming original orthography on screen, Pretendard glyphs (no tofu), ≤2 lines, in-bounds timings.

## Tasks / Subtasks

- [ ] **Task 1 — Chain: preserve the original code-side (AC: 1, 2)**
  - [ ] `tts_normalize_step` ([scenario_chain.py:268-310](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L268)): accepted scene → `{**original_scene, "narration": normalized, "display_narration": original_narration}`; fallback scene → `{**original_scene, "display_narration": original_narration}` (both tracks = original). No prompt change — see Dev Notes "Why no prompt change".
  - [ ] `build_scenes` ([scenario_chain.py:363-374](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L363)): `display_narration=str(writing_scene.get("display_narration") or writing_scene["narration"])`.
  - [ ] `state.py`: add `display_narration: str` to `SceneState`; update `EXPECTED_FIELDS` (coordinate with 5.17's `title`/`kicker` additions — guaranteed conflict if parallel).
- [ ] **Task 2 — Subtitle: static sentence-cue renderer (AC: 4, 5, 7)**
  - [ ] Add pure helpers in [subtitle.py](../../src/yt_flow/pipeline/nodes/subtitle.py): (a) `sentence_cues(timings, spoken_text, display_text) -> list[AlignmentSegment]` — sentence windows from the spoken track (consume `len(s.split())` timings per `split_sentences(spoken_text)` sentence; import `split_sentences` from `scenario_chain` — pipeline-node→pipeline-node import is layer-legal, don't duplicate the regex), text from the matching display sentence; guards per AC7 return spoken-track cues + WARNING for count mismatches; (b) `wrap_cue_text(text) -> str` — ≤2 `\N` lines, word-boundary breaks, ~16 chars/line guidance, ~44-char soft cap triggering the proportional cue split of AC4.
  - [ ] Rewrite `format_ass` to take cues (start/end/wrapped text) and emit plain `Dialogue` lines (keep `_ass_time`, keep the `_escape_ass_word`-style brace/backslash stripping applied to cue text).
  - [ ] Apply the AC5 deletion list; rewrite `_ass_header()` with the AC6 style values and the constant Pretendard family name (no fc-match).
  - [ ] `subtitle_node` ([subtitle.py:277-321](../../src/yt_flow/pipeline/nodes/subtitle.py#L277)): timings present → `cues = sentence_cues(timings, scene["narration"], scene.get("display_narration") or scene["narration"])`; timings absent → aligner segments as cues (unchanged aligner call). Validate via `_validate_segments`, always write `scene_{n:03d}.ass`.
- [ ] **Task 3 — Font bundle + burn-in wiring (AC: 6)**
  - [ ] Vendor `data/fonts/Pretendard-SemiBold.otf` (and `Pretendard-Bold.otf` for 5.17's cards, if 5.17 hasn't already) — source/license in Dev Notes; commit the binaries.
  - [ ] [video.py](../../src/yt_flow/pipeline/nodes/video.py): append `:fontsdir='{escaped}'` to BOTH `subtitles='{sub}'` fragments ([video.py:602](../../src/yt_flow/pipeline/nodes/video.py#L602) character chain, [video.py:614](../../src/yt_flow/pipeline/nodes/video.py#L614) background-only — the sound-design branch reuses these chains, verify all built `filter_complex`/`-vf` variants carry it); escape the dir path with the existing `_escape_subtitles_path` ([video.py:357-369](../../src/yt_flow/pipeline/nodes/video.py#L357)).
  - [ ] Verify the exact family/style name libass matches for the SemiBold weight (`fc-scan data/fonts/Pretendard-SemiBold.otf` → family/fullname) and pin that string as the `Fontname` constant; confirm in the AC9 live burn.
- [ ] **Task 4 — Artifacts API (AC: 8)**
  - [ ] Add `"display_narration": s.get("display_narration") or s["narration"]` to the scenario branch of `get_stage_artifacts`.
- [ ] **Task 5 — Tests (AC: 1-8)**
  - [ ] [tests/pipeline/nodes/test_scenario_chain.py](../../tests/pipeline/nodes/test_scenario_chain.py): extend the `tts_normalize_step` block (lines 345–470) — accepted scene carries both tracks; mismatch fallback yields `display_narration == narration == original` (extend `test_tts_normalize_step_falls_back_per_scene_on_sentence_count_mismatch`, line 426); `build_scenes` populates/defaults `display_narration`.
  - [ ] [tests/pipeline/nodes/test_subtitle.py](../../tests/pipeline/nodes/test_subtitle.py): REPLACE the 7.5/karaoke suite — `test_format_srt_*` (107–152), `test_word_timings_to_segments_*`/`test_group_words_*` (156–209), `test_build_ass_events_*` (213–263), kinetic routing tests (`test_subtitle_node_writes_ass_when_flag_on_and_word_timings` etc., 367–406) — with: `sentence_cues` unit tests (window boundaries match spoken sentence spans; display text carried; each AC7 guard → spoken fallback, count-mismatch WARNING via `caplog`); `wrap_cue_text` (≤2 lines, word-boundary breaks, soft-cap cue split with proportional times); `format_ass` has zero `\k` and no `{`-injection from text; header asserts Pretendard/Fontsize 60/Outline 3/MarginV 54; node tests — always `.ass`, contains "SCP-049" and not "에스시피", old-checkpoint scene (no `display_narration`) renders spoken text without error, aligner-fallback path emits static `.ass`.
  - [ ] [tests/pipeline/nodes/test_video.py](../../tests/pipeline/nodes/test_video.py): burn-in tests assert `fontsdir=` present in captured filtergraphs (extend `test_video_node_escapes_subtitle_path`, line 732, and the `filter_complex` character-path tests).
  - [ ] `tests/domain/test_state_imports.py`: `EXPECTED_FIELDS["SceneState"]` += `{"display_narration"}`.
  - [ ] Config: delete the `kinetic_subtitles_enabled` default test; grep `kinetic` repo-wide for stragglers.
  - [ ] Cassettes/fakes untouched (`deepseek_tts_normalize.json` contract unchanged — display track is derived code-side); verify the stub-profile E2E passes.
  - [ ] Run targeted files, then full `uv run pytest -q`.
- [ ] **Task 6 — Live validation (AC: 9)**
  - [ ] Build a real dual-track scene (pair above) with real TTS audio (or reuse `workspace/272b05a4*/audio/scene_001.wav`), run `subtitle_node` for real, inspect the `.ass` (original text, no `\k`, ≤2-line cues, `_validate_segments` passes vs real `audio_duration`), then burn one frame with real ffmpeg using `fontsdir` on a machine path where Noto/system fonts are NOT consulted (e.g. temporarily point fontsdir at `data/fonts` and confirm Pretendard renders). Record evidence; keep artifacts (5.9 review lesson).

## Dev Notes

### Why no prompt change (decision)

The earlier brief assumed the `tts_normalize` prompt would output per-sentence pairs. It doesn't need to: the step's Python code already has the original narration in hand (`original_scene.get("narration")`, [scenario_chain.py:297](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L297)). Echoing the original through the LLM would risk silent mutation in the round-trip, double output tokens, and drag this story through the PROMPT_POLICY cycle for zero information gain. Code-side preservation is strictly safer and Ponytail-minimal. Per-sentence pairing is *derived*: sentence i of `display_narration` pairs with sentence i of `narration` via the `split_sentences` count contract 5.4 already enforces (and falls back on, AC2). If a future story ever wants LLM-emitted pairs, that's when PROMPT_POLICY applies.

### Why static typography-first (and what became moot)

Jay's direction (2026-07-06): the `\k` highlight never actually synced (D12 — uniform provisional timings from [tts.py:106-122](../../src/yt_flow/pipeline/nodes/tts.py#L106); whisperx segment fallback per `spec-subtitle-word-segment-fallback.md`), and per-word highlight is shorts grammar, not documentary narration. Retiring it makes three problems disappear:
- the spoken-word→display-word `\k` mapping (counts differ across tracks) — no words to time;
- D12's word-alignment root-cause investigation — sentence windows from measured audio (`audio_duration` apportioned over spoken tokens) are all subtitles need;
- the karaoke primary/secondary color inversion hack ([subtitle.py:158-165](../../src/yt_flow/pipeline/nodes/subtitle.py#L158)).
Output stays `.ass` (not `.srt`) purely for styling control: font, outline, shadow, margins, deterministic line breaks — none of which `.srt` can carry into the ffmpeg burn.

### Korean subtitle norms applied (line breaking)

Current line logic is `_group_words` greedy ≤40-char single-line cues — dies with the karaoke path. New logic: cue-per-sentence (the natural narration unit; writing_step produces short TTS-friendly sentences per `split_sentences`' own docstring, [scenario_chain.py:29-39](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L29)), wrapped to max 2 `\N` lines. The ~16 chars/line broadcast figure is *guidance* for the break points (we burn 60px type on 1920×1080 — a hard 16 limit would over-fragment); the ~44-char soft cap before splitting into a second cue keeps any single cue readable at that size. Balance the two lines (break nearest the midpoint word boundary) rather than greedy-filling line 1.

### Bundled font — Pretendard (shared with Story 5.17)

- Source: https://github.com/orioncactus/pretendard — SIL Open Font License 1.1 (free commercial use, redistribution/bundling allowed). Vendor `Pretendard-SemiBold.otf` (subtitles) + `Pretendard-Bold.otf` (5.17's cards) into `data/fonts/`; never fetch at runtime.
- Subtitles resolve via ASS `Fontname` + the `subtitles=` filter's `fontsdir` (libass scans that dir first) — rendering no longer depends on system-installed Noto. Delete `_ass_font_family()`'s fc-match chain. 5.17's cards use `drawtext=fontfile=` directly on the bundled file — cross-referenced there; same family = design-system consistency (Jay direction).
- Weight-name gotcha: OTF "SemiBold" may register as family "Pretendard SemiBold" or family "Pretendard" + style — pin whatever `fc-scan` reports and confirm in the live burn (Task 3/6).

### Current vs changed behavior summary

- **Current:** one text field; karaoke `.ass` (fake-timed) or `.srt` shows TTS-phoneticized Korean in fc-matched system Noto at 48px/outline 2/MarginV 30; original writing text destroyed at `tts_normalize_step`.
- **Changed:** `narration` = spoken track (unchanged consumers: TTS, provisional timings, whisperx transcript, eval judge input [src/yt_flow/services/eval_service.py:177](../../src/yt_flow/services/eval_service.py#L177) — judges keep reading what's *heard*); `display_narration` = display track (subtitle rendering, artifacts API); subtitles are static sentence cues in bundled Pretendard SemiBold 60px, original orthography.

### Preserved behavior (do not regress)

- 5.4's per-scene sentence-count fallback + WARNING — extended, not replaced (AC2).
- 1:1 sentence↔shot contract; `sentence_indices` semantics untouched.
- `tts_node` byte-for-byte; whisperx aligner transcript source; `_validate_segments` invariants; `.ass` file naming/location (`subtitles/scene_{n:03d}.ass`).
- Old checkpoints without `display_narration`: static rendering of the spoken text — no KeyError (`run_service._nullify` tts-retry, [run_service.py:556-562](../../src/yt_flow/services/run_service.py#L556), wipes `word_timings`/`subtitle_path` but not narration fields).
- `edit_artifact`'s subtitle raw-text edit path ([run_service.py:648-655](../../src/yt_flow/services/run_service.py#L648)) — format-agnostic, now always edits `.ass` content.

### Scope guardrails (do NOT do)

- Do not touch the `tts_normalize` prompt, `tts.py`, or the whisperx transcript source.
- Do not attempt any word-level display timing — retired with karaoke.
- Do not add config flags (no "static vs kinetic" toggle — kinetic is deleted, not optional; the AC7 guards are the fallback).
- Do not restyle beyond the AC6 spec (no per-mood subtitle colors etc. — typography restraint).

### Testing standards

- `pytest` + `pytest-asyncio`; subtitle node tests use the `_settings` monkeypatch + tmp_path `audio_file` fixture pattern; chain tests use the fake-prompt/DeepSeek seams (label=None → `get_prompt` monkeypatch contract). New helpers are pure — test directly, no mocks. Video burn assertions reuse the `_run_ffmpeg` capture pattern.
- Worktree gotcha: `PYTHONPATH=$PWD/src` ([[worktree-editable-install-shadowing]]).

### Project Structure Notes

- Expected files: `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/pipeline/nodes/subtitle.py`, `src/yt_flow/pipeline/nodes/video.py`, `src/yt_flow/config.py`, `src/yt_flow/domain/state.py`, `src/yt_flow/services/run_service.py`, `data/fonts/Pretendard-SemiBold.otf` (+`-Bold.otf`, new), tests (`test_scenario_chain.py`, `test_subtitle.py`, `test_video.py`, `test_state_imports.py`, config tests).
- **Parallel-session hazards:** 5.17 (same `EXPECTED_FIELDS`, same `data/fonts/`, same `video.py`), 5.16 (same `video.py` join region) — sequence these; `EXPECTED_FIELDS` and `video.py` are guaranteed conflict points ([[project_5-7-review-done]] concurrent-edit history).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.18] — draft scope.
- [Source: _bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md] — feedback #3, D12 uniform timings, J8 score.
- [Source: _bmad-output/implementation-artifacts/5-4-tts-korean-naturalization.md] — the single-track decision reversed; the fallback contract mirrored.
- [Source: _bmad-output/implementation-artifacts/7-5-kinetic-subtitles.md] — the karaoke path retired here.
- [Source: _bmad-output/implementation-artifacts/spec-subtitle-word-segment-fallback.md] — D12 fallback state (now moot for subtitle rendering).
- [Source: src/yt_flow/pipeline/nodes/subtitle.py#L89-L243, #L277-L321; src/yt_flow/pipeline/nodes/tts.py#L106-L173; src/yt_flow/pipeline/nodes/scenario_chain.py#L268-L310; src/yt_flow/pipeline/nodes/video.py#L357-L369, #L598-L618] — the exact seams.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-06: Story created from Jay's viewing feedback #3 on the E2E baseline video (run `272b05a4`): subtitles must show original script text, not TTS phoneticization. Supersedes Story 5.4 AC2's "same text for SRT+TTS" YAGNI decision.
- 2026-07-06: Revised per Jay's direction: karaoke `\k` highlight RETIRED (7.5 kinetic path deleted — it never synced per D12; documentary convention is a static line), replaced by typography-first static `.ass` (bundled Pretendard SemiBold via `fontsdir`, 60px/outline 3/safe-area margins, max-2-line Korean line-breaking, original-orthography display text). Word-level alignment and the spoken→display word-mapping question became moot and were removed from scope.

## Saved Questions / Clarifications

- **Aligner-fallback branch shows normalized text** when `word_timings` are empty (whisperx segments carry the spoken transcript; segments don't respect sentence boundaries, so display mapping has no anchor there). Only reachable via manual state edits today — tts always populates timings. Accepted limitation; revisit if that branch ever fires in practice.
- **`.srt` for YouTube closed captions:** deleted as a pipeline output; if CC upload is ever wanted, regenerate `.srt` from the same sentence cues as an export feature (separate story) — and decide then whether CC text should be display or spoken track.
- **Gate narration edits touch the spoken track only** (`edit_artifact` scenario branch writes `target["narration"]`, [run_service.py:645](../../src/yt_flow/services/run_service.py#L645)); there is no UI edit path for `display_narration`. Fine for now (subtitle text is separately editable as the `.ass` artifact); add a display-track edit path only if gate practice demands it.
- **Should the eval judge read display or spoken text?** Kept on spoken ([eval_service.py:177](../../src/yt_flow/services/eval_service.py#L177)) — J5 scores what's heard. A future subtitle-quality axis should read the display track.
- **Line-length tuning:** the ~16 chars/line guidance and ~44-char cue cap are first values — recalibrate from Jay's next viewing pass at 60px burn size.
