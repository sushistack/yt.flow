---
created: 2026-07-06
story_key: 5-17-chapter-card-content
story_id: "5.17"
epic: 5
depends_on:
  - 5-1-scene-transitions-chapter-cards
  - 7-1-sound-design
soft_depends_on:
  - 5-16-transition-boundary-integrity  # shared video.py card region; 5.16 gives cards their ambient bed
  - 5-15-mood-wiring-fix                # shares the structure→build_scenes plumbing seam
  - 5-18-subtitle-display-text-dual-track  # shares the bundled Pretendard font (whichever lands first adds data/fonts/)
baseline_commit: eb9e2964860cd183050607a00ffb9b260bee70af
---

# Story 5.17: Chapter Card Content — Scene Title + One-Line Kicker, Stinger-Synced

Status: ready-for-dev

## Story

As Jay,
I want each chapter card to show the upcoming scene's title plus a one-line kicker, punctuated by the mood stinger on card entry,
so that story jumps between scenes don't feel abrupt — the card orients the viewer the way a documentary title card does.

## Context

Context: Jay viewing feedback on E2E baseline 2026-07-06 (run `272b05a4`, SCP-049) — feedback #4. Report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` ("챕터 카드는 검은 화면에 '- N -' 숫자만"). Design follows the standard documentary title-card spec per Jay's direction (2026-07-06): **title + one-line kicker, 1.5–2.5s duration, synchronized with a sound punctuation (the 7-1 mood stinger) on card entry, typography restraint** (two lines max — horror pacing; cards must not over-explain).

Today `_card_label` ([src/yt_flow/pipeline/nodes/video.py:406-417](../../src/yt_flow/pipeline/nodes/video.py#L406)) always falls back to `f"- {scene_num} -"` because `SceneState` has no `title` field — the function even carries a forward-compat shim (`if "title" in SceneState.__annotations__`) waiting for exactly this story. The text is scenario-stage work: the **structure** step already designs each scene's `act`/`synopsis`/`emotional_beat` ([prompts/scenario/structure.md:39-50](../../prompts/scenario/structure.md#L39)), so it is the natural producer of per-scene `title` + `kicker` (e.g. "첫 면담 — 개체가 입을 열다"). On the audio side, the 7-1 stinger currently fires at *scene start* (baked one-shot from t=0, [src/yt_flow/pipeline/nodes/sound_design.py:75](../../src/yt_flow/pipeline/nodes/sound_design.py#L75)) — i.e. ~2s *after* the card appears; the convention wants the hit ON the card.

This includes a prompt change → `docs/PROMPT_POLICY.md` candidate→eval→promote protocol applies.

## Acceptance Criteria

1. **Structure prompt emits title + kicker.** Given the structure stage runs, when a scene object is produced, then it includes `"title"` (short Korean scene title, ≤ ~14 chars) and `"kicker"` (ONE line of Korean situation context, ≤ ~24 chars, no reveal-spoilers) — added to the JSON schema and rules of [prompts/scenario/structure.md](../../prompts/scenario/structure.md). Repo file is source of truth; new version seeded under `candidate` and promoted to `production` only via the PROMPT_POLICY protocol (A/B run + `scripts/eval_prompts.py --label candidate --baseline production` exits 0 + label move).
2. **Tolerant validation, label-aware.** Given `structure_step` parses the payload ([src/yt_flow/pipeline/nodes/scenario_chain.py:97-116](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L97)), when `label` is set (candidate — the prompt version that promises the fields), then a scene missing a non-empty `title` raises `ValueError`; when `label is None`, missing `title`/`kicker` is tolerated silently — mirroring `research_step`'s label-conditional pattern ([scenario_chain.py:84-93](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L84)). `kicker` is optional under both labels.
3. **SceneState carries the fields.** Given `build_scenes` assembles scenes, then `SceneState` gains `title: str` and `kicker: str` ([src/yt_flow/domain/state.py:38-46](../../src/yt_flow/domain/state.py#L38)), populated positionally from the structure scene at the same index (the 5.15/`_write_and_review` positional rule, [src/yt_flow/pipeline/nodes/scenario.py:111-125](../../src/yt_flow/pipeline/nodes/scenario.py#L111)), defaulting to `""` when missing/non-dict — never a crash. The drift-guard `EXPECTED_FIELDS["SceneState"]` in [tests/domain/test_state_imports.py:20-23](../../tests/domain/test_state_imports.py#L20) is updated in the same commit.
4. **Card renders title + kicker with typography restraint.** Given a scene with a non-empty `title`, when its chapter card is composed ([video.py:666-712](../../src/yt_flow/pipeline/nodes/video.py#L666)), then the card shows exactly two text elements max: the title centered at `CARD_FONT_SIZE` (72) and, when `kicker` is non-empty, the kicker below at a smaller size (new constant `CARD_KICKER_FONT_SIZE = 40`). Newlines in LLM-produced text are stripped to a single line each (restraint is enforced in code, not just prompted). Both use the existing `textfile=`-based `drawtext` pattern (text written to a file; only the *path* escaped via `_escape_subtitles_path` — [video.py:686-694](../../src/yt_flow/pipeline/nodes/video.py#L686)) so Korean text/quotes/`%`/`:` never hit ffmpeg inline-text escaping.
5. **Bundled typography.** Given card text renders, then `drawtext` uses the repo-bundled **Pretendard Bold** (`fontfile=` pointing at `data/fonts/Pretendard-Bold.otf` — same family Story 5.18 adopts for subtitles; design-system consistency) instead of the fc-match system-font lookup; `_drawtext_font()`'s fc-match chain ([video.py:377-403](../../src/yt_flow/pipeline/nodes/video.py#L377)) is retired (the bundled font removes the system-dependency problem it existed to solve). Whichever of 5.17/5.18 lands first adds the font files (see Dev Notes for source/license).
6. **Card duration matches the convention.** Given the documentary spec of 1.5–2.5s, then `MAX_CARD_DURATION` is raised 2.0 → 2.5 ([video.py:90](../../src/yt_flow/pipeline/nodes/video.py#L90)); `MIN_CARD_DURATION` 1.5 and the `chapter_card_duration_sec` config default (1.75, [config.py:93](../../src/yt_flow/config.py#L93)) stay — cards now carry text, so Jay can raise the config toward 2.5 without a code change.
7. **Stinger synced to card entry.** Given `sound_design_enabled=true` and chapter cards on, then the upcoming scene's mood stinger plays at the CARD's t=0 (mixed into the card's audio alongside the ambient bed 5.16 gives cards, `STINGER_VOLUME`, reuse `MOOD_ASSET_PATHS`/`validate_mood_assets`), and the immediately following scene suppresses its own baked scene-entry stinger (new `include_stinger: bool = True` seam through `build_sound_design_args`/`build_sound_design_filter`, [sound_design.py:49-82](../../src/yt_flow/pipeline/nodes/sound_design.py#L49)) so the boundary gets exactly ONE hit — on the card, not 2s later. With cards off or sound design off, scene stinger behavior is unchanged.
8. **Fallback preserved.** Given a scene whose `title` is empty/absent (old checkpoints, pre-promotion production prompt, LLM omission), then the card renders exactly today's `"- N -"` label with no kicker line — `_card_label`'s `__annotations__` shim is replaced by a direct `scene.get("title")` read.
9. **Gate visibility.** Given the scenario artifacts API serializes scenes ([src/yt_flow/services/run_service.py:83-100](../../src/yt_flow/services/run_service.py#L83)), then `title` and `kicker` are included (`.get(..., "")`, old-checkpoint-safe like the `layered_fallback` precedent at run_service.py:108) so the reviewer vets card text at the scenario gate.
10. **Tests + live validation.** Given the suite runs, then chain/node/drift tests cover ACs 2–9 (Task 6), and one live `_compose_chapter_card` render with real ffmpeg confirms a Korean title+kicker card frame (Pretendard glyphs, no tofu) and — with sound design on — a stinger transient at card start in the waveform.

## Tasks / Subtasks

- [ ] **Task 1 — Prompt change under PROMPT_POLICY (AC: 1)**
  - [ ] Edit [prompts/scenario/structure.md](../../prompts/scenario/structure.md): add `"title"`/`"kicker"` to the scene JSON schema (lines 39–50) with rules — Korean, viewer-facing (not internal labels like "hook"), title ≤ ~14 chars, kicker one line ≤ ~24 chars, no reveal-spoilers, no punctuation-heavy prose.
  - [ ] Seed candidate: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` (NOT `--source prompts/scenario` — that strips the `scenario/` prefix; pre-existing bug recorded in Story 5.4's Dev Agent Record).
  - [ ] Promotion (may complete after code merges; code tolerates the old prompt per AC2): A/B run → eval gate exits 0 → move `production` label → commit rationale.
- [ ] **Task 2 — Chain: validation + SceneState population (AC: 2, 3)**
  - [ ] `structure_step`: label-conditional `title` check per AC2 (copy `research_step`'s loop shape, scenario_chain.py:88-93).
  - [ ] `build_scenes` ([scenario_chain.py:320-375](../../src/yt_flow/pipeline/nodes/scenario_chain.py#L320)): read `title`/`kicker` from `structure[idx]` (`str(entry.get(...) or "").strip()`, first line only). **Coordinate with Story 5.15:** it already adds the `structure: list[dict]` parameter to `build_scenes` plumbed from [scenario.py:183](../../src/yt_flow/pipeline/nodes/scenario.py#L183); reuse it if landed, else add the identical parameter exactly as 5.15's Task 1 specifies so the stories merge cleanly.
  - [ ] `state.py`: add `title: str`, `kicker: str` to `SceneState`; update `EXPECTED_FIELDS` in `tests/domain/test_state_imports.py`.
- [ ] **Task 3 — Card renderer + bundled font (AC: 4, 5, 6, 8)**
  - [ ] `_card_label`: replace the `__annotations__` shim with `title = str(scene.get("title") or "").strip(); return title or f"- {scene['scene_num']} -"`.
  - [ ] `_compose_chapter_card`: accept `kicker: str`; write `card_{i:03d}_kicker.txt` and chain a second `drawtext` when non-empty. Suggested layout: title `y=(h-text_h)/2-40`, kicker `y=(h-text_h)/2+60` (tune by eye); keep the card's fade in/out LAST in the chain so text fades with the card. `video_node` passes `scenes[i + 1].get("kicker") or ""` at the call site ([video.py:891-900](../../src/yt_flow/pipeline/nodes/video.py#L891)).
  - [ ] Font: add `data/fonts/Pretendard-Bold.otf` (if 5.18 hasn't already; see Dev Notes) and point both `drawtext` calls at it (`fontfile=` with `_escape_subtitles_path`-escaped absolute path resolved from the repo/data root); delete `_drawtext_font()` and its fc-match machinery.
  - [ ] `MAX_CARD_DURATION = 2.5` ([video.py:90](../../src/yt_flow/pipeline/nodes/video.py#L90)); update `_chapter_card_duration` clamp test expectations.
- [ ] **Task 4 — Stinger sync (AC: 7)**
  - [ ] `sound_design.py`: add `include_stinger: bool = True` to `build_sound_design_args` (omit the stinger `-i` when False) and `build_sound_design_filter` (2-input `bgmix` variant; keep index math consistent — the class of hazard its docstring already warns about).
  - [ ] `_compose_chapter_card`: with sound design on, mix `MOOD_ASSET_PATHS[mood]["stinger"]` (volume `STINGER_VOLUME`, one-shot from t=0, `apad`/`-t` to card duration) with the card's ambient bed (5.16's AC3 change — if 5.16 hasn't landed, mix stinger over `anullsrc` and rebase when it does).
  - [ ] `_compose_scene`/`video_node`: pass `include_stinger=False` for scenes immediately preceded by a card (`chapter_cards_enabled and i > 0` — the same adjacency fact the old 7.4 guard used); first scene and cards-off keep the scene-entry stinger.
- [ ] **Task 5 — Artifacts API (AC: 9)**
  - [ ] Add `"title": s.get("title", "")` / `"kicker": s.get("kicker", "")` to the scenario branch of `get_stage_artifacts` ([run_service.py:83-100](../../src/yt_flow/services/run_service.py#L83)).
- [ ] **Task 6 — Tests (AC: 2-9)**
  - [ ] [tests/pipeline/nodes/test_scenario_chain.py](../../tests/pipeline/nodes/test_scenario_chain.py): `structure_step` candidate-label-requires-title (mirror `test_research_step_candidate_label_requires_entity_sheet`, line 114) + label=None tolerance; `build_scenes` title/kicker positional population, `""` defaults, newline stripping.
  - [ ] [tests/pipeline/nodes/test_video.py](../../tests/pipeline/nodes/test_video.py): `_card_label` title-vs-fallback; card tests (`test_chapter_cards_enabled_creates_card_segments`, line 1723) extended — two `drawtext` chains when kicker present / one when absent, written textfiles contain the exact Korean strings (assert file contents — that's the point of textfile), `fontfile=` points at the bundled Pretendard path; clamp test for 2.5; stinger tests — card ffmpeg args include the stinger input + card-following scene's filtergraph lacks the stinger input while scene 0's keeps it; `include_stinger=False` filter/args unit tests in the sound-design test module.
  - [ ] `tests/domain/test_state_imports.py`: `EXPECTED_FIELDS["SceneState"]` += `{"title", "kicker"}` (coordinate with 5.18's `display_narration` addition).
  - [ ] Cassette/fakes: add `title`/`kicker` to [tests/fixtures/cassettes/deepseek_structure.json](../../tests/fixtures/cassettes/deepseek_structure.json) scene objects (5.15 touches the same cassette for `mood` — coordinate); update `tests/fixtures/cassettes/README.md`.
  - [ ] Run targeted files, then full `uv run pytest -q`.
- [ ] **Task 7 — Live validation (AC: 10)**
  - [ ] Real-ffmpeg `_compose_chapter_card` with Korean title+kicker: frame-sample mid-card (Pretendard renders, both lines legible at 1080p, quotes/punctuation intact) and, with sound assets present, verify the stinger transient at card t≈0 vs silence-level ambient after. Record frame + waveform evidence; keep artifacts.

## Dev Notes

### Current vs changed behavior

- **Current:** cards show `"- N -"` ([video.py:417](../../src/yt_flow/pipeline/nodes/video.py#L417)); structure output never reaches `PipelineState`; stinger fires at scene start (≈2s after the card appears); card fonts resolved from system fonts via fc-match; MAX card duration 2.0.
- **Changed:** structure emits `title`+`kicker` → `SceneState` → card renders both in bundled Pretendard Bold; stinger moves to card entry (one hit per boundary); MAX duration 2.5; artifacts API exposes the text at the gate.
- **Why structure, not writing:** structure knows the scene's narrative role, and it's the enum-precedent stage (5.15 moves mood reading here for the same reason — writing free-forms fields it isn't constrained on).

### Typography restraint (convention, enforced in code)

Documentary title-card spec: one title line + one kicker line, nothing else — horror pacing means cards must not over-explain. Enforce in `build_scenes` (strip to first line) and by construction in the renderer (exactly two `drawtext` elements max). Do not add a third text element, act numbers, or decorative rules without a new Jay decision.

### Bundled font — Pretendard (shared with Story 5.18)

- Source: https://github.com/orioncactus/pretendard (SIL OFL 1.1 — free commercial use, bundleable). Vendor `Pretendard-Bold.otf` (cards) — 5.18 also vendors `Pretendard-SemiBold.otf` (subtitles) — into `data/fonts/`, committed to the repo. Do NOT fetch at runtime.
- Cards use `drawtext=fontfile=<path>` (direct file path — no fontconfig involvement); subtitles (5.18) use the ASS `Fontname` + `fontsdir` mechanism. Same family both places = design-system consistency (Jay direction 2026-07-06).
- Delete `_drawtext_font()` ([video.py:377-403](../../src/yt_flow/pipeline/nodes/video.py#L377)): its whole reason to exist was "never hardcode a machine-specific path" against *system* fonts; a repo-relative bundled path is portable by construction. Fail fast if the file is missing (repo corruption, not an environment condition).

### drawtext hazards (why textfile, not text=)

Inline `drawtext=text='...'` requires escaping `'`, `%`, `:`, `\` and commas at two parser levels — a known Korean/quote footgun. 5.1 already solved this with `textfile=` ([video.py:686-689](../../src/yt_flow/pipeline/nodes/video.py#L686)); keep it for both lines; never inline LLM text into the filtergraph.

### Stinger sync feasibility (checked)

The stinger is a per-scene baked one-shot: `build_sound_design_args` adds it as a plain `-i`, `build_sound_design_filter` volumes+`apad`s it from t=0 ([sound_design.py:49-82](../../src/yt_flow/pipeline/nodes/sound_design.py#L49)). Moving the hit to the card = (a) card mixes the stinger itself (card already knows the upcoming mood — it grades by it, [video.py:893](../../src/yt_flow/pipeline/nodes/video.py#L893)), (b) the following scene omits its stinger input via the new `include_stinger` seam — otherwise the boundary double-hits 2s apart. `video_node` already knows card adjacency at the call site. This is the minimal-change path; restructuring stinger timing inside scenes is NOT needed.

### Relationship to 5.16 (write-after, not hard-depend)

5.16 rewrites the join and swaps card audio from `anullsrc` to the mood ambient bed; this story adds the kicker drawtext + stinger into the same `_compose_chapter_card`. Implement after 5.16 merges to avoid `video.py` conflicts; if implemented first, mix the stinger over `anullsrc` and let 5.16 rebase the ambient in.

### Preserved behavior

- `"- N -"` fallback for empty titles (AC8) — old checkpoints and pre-promotion prompt keep rendering today's cards (minus system-font dependency).
- Card duration clamp shape, self-fades (`CARD_FADE_DURATION`), 7.2 mood grading, silent cards when `sound_design_enabled=false`.
- Sentence 1:1 shot mapping; all non-card `video_node` behavior; scene-entry stinger when cards are off.

### Ponytail

- No new config flags: titled cards aren't a toggle; the empty-title fallback is the off-switch. `include_stinger` is a function parameter, not a setting.
- `title`/`kicker` as two plain `str` fields — no card-content object, no styling options.
- Deletions: the `__annotations__` shim, `_drawtext_font()` fc-match machinery.

### Testing standards

- `pytest` + `pytest-asyncio`; card tests monkeypatch `video._run_ffmpeg` and inspect captured args + written textfiles (`_capture_ffmpeg_calls`, test_video.py:1703). Chain tests use the fake-prompt/DeepSeek seams (label=None → `get_prompt` monkeypatch contract — don't break it).
- Worktree gotcha: `PYTHONPATH=$PWD/src` ([[worktree-editable-install-shadowing]]).

### Project Structure Notes

- Expected files: `prompts/scenario/structure.md`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/pipeline/nodes/sound_design.py`, `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/video.py`, `src/yt_flow/services/run_service.py`, `data/fonts/Pretendard-Bold.otf` (new, if not vendored by 5.18 first), tests (`test_scenario_chain.py`, `test_video.py`, `test_sound_design.py`, `test_state_imports.py`), `tests/fixtures/cassettes/deepseek_structure.json` (+README).
- **Parallel-session hazards:** 5.15 (same `build_scenes`/cassette), 5.16 (same `video.py` card block), 5.18 (same `EXPECTED_FIELDS`, same font bundle) — sequence, don't parallelize ([[project_5-7-review-done]] concurrent-edit history).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.17] — draft scope.
- [Source: _bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md] — bare-card observation + feedback #4.
- [Source: _bmad-output/implementation-artifacts/5-1-scene-transitions-chapter-cards.md] — card creation contract.
- [Source: _bmad-output/implementation-artifacts/5-15-mood-wiring-fix.md] — structure→build_scenes plumbing (its Task 1).
- [Source: src/yt_flow/pipeline/nodes/sound_design.py#L17-L82] — stinger/ambient assets, volumes, per-scene mix.
- [Source: docs/PROMPT_POLICY.md] — change protocol for the structure prompt.
- [Source: src/yt_flow/pipeline/nodes/video.py#L377-L417, #L666-L712, #L876-L901] — font resolution, `_card_label`, card renderer, call site.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-06: Story created from Jay's viewing feedback #4 on the E2E baseline video (run `272b05a4`): "- N -" cards give no story orientation; scene jumps feel abrupt.
- 2026-07-06: Revised per Jay's editing-conventions direction: documentary title-card spec (title + one-line kicker, 1.5–2.5s, typography restraint enforced in code), stinger synced to card entry with scene-stinger suppression, and bundled Pretendard Bold typography shared with 5.18 (fc-match `_drawtext_font()` retired).

## Saved Questions / Clarifications

- **Card typography beyond title+kicker** (separator rule, act numbering like "제2장") — explicitly out of scope per the restraint spec; iterate only from Jay's next viewing pass.
- **Kicker as YouTube chapter-marker/description text** — structure now produces the data; exporting is a separate story if wanted.
- **Prompt promotion timing:** code merges with tolerant validation (AC2); the candidate structure prompt is evaluated/promoted asynchronously — live cards show titles only after promotion (or on variant-B A/B runs).
- **Stinger asset length vs card length:** if a mood's stinger file is longer than the card (1.5–2.5s), it truncates at the card cut — acceptable (stingers are sub-2s hits); revisit assets, not code, if it clips badly.
