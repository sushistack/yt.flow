---
created: 2026-07-07
story_key: 5-21-tts-voice-clone-wiring
story_id: "5.21"
epic: 5
baseline_commit: e2650dc5c22723c6cd923642c40c7640875a6e45
depends_on:
  - 5-4-tts-korean-naturalization    # text-side contract this story must NOT touch
  - 5-18-subtitle-display-text-dual-track  # dual-track contract this story must NOT touch
---

# Story 5.21: TTS Voice Clone Wiring + Speech Speed

Status: done

## Story

As Jay,
I want narration synthesized with my cloned voice (reference sample `data/voices/sutak.mp3`) when I flip a single config switch — and narration pace configurable with a faster 1.2x default —
so that the channel can use its intended voice identity instead of the stock "Cherry" preset, and the sluggish baseline pacing is fixed, with an honest A/B listening comparison deciding whether the clone actually ships.

## Context

Context: follow-up from E2E baseline 2026-07-06 (run `272b05a4`, SCP-049 — narration confirmed to be the stock voice) + Jay direction 2026-07-07.

`.env` has carried `YTFLOW_QWEN_TTS_CLONE_MODEL=qwen3-tts-vc-2026-01-22` and `YTFLOW_QWEN_TTS_CLONE_VOICE_PATH=data/voices/sutak.mp3` since setup, but these are **dead config**: the `Settings` class (`src/yt_flow/config.py:54-58`) never declares them and nothing in `src/` reads them (verified 2026-07-07: `grep -ri clone src/yt_flow` → zero hits). `tts_node` always synthesizes with `model=qwen3-tts-flash`, `voice="Cherry"` (`src/yt_flow/pipeline/nodes/tts.py:93-94`), so every render to date — including the 2026-07-06 baseline Jay reviewed — used the stock voice.

Jay's direction has two parts, both scoped to the same code area:

1. **Wire the clone properly, but treat quality as an open question.** Cloned voices often lose prosody/naturalness vs heavily-produced stock presets — especially from a short reference sample. The clone must therefore land behind a switch that **defaults OFF** (current behavior unchanged), and the story's definition-of-done is a real side-by-side listening comparison whose verdict — Jay's ear, not an assumption — decides the operational default.
2. **Configurable speech speed, default 1.2x** (scope addition 2026-07-07): baseline narration felt slow. This is a deliberate default change, not 1.0. Applies to both stock and clone modes.

API research (2026-07-07, see Dev Notes → API Research) found: voice cloning is a **one-time enrollment** (`qwen-voice-enrollment` model → persistent voice id, auto-deleted only after 1 year unused, USD 0.01 per creation), and the non-realtime synthesis API has **no numeric speed parameter** — so speed is an ffmpeg `atempo` post-process on each scene wav, applied before duration is measured.

Known risk found during story prep: `data/voices/sutak.mp3` probed (ffprobe, 2026-07-07) at **7.68s, stereo, 48kHz**. The enrollment docs recommend 10–20s and specify mono; the sample may need a mono downmix and its short length is itself a clone-quality risk worth naming in the A/B verdict.

## Acceptance Criteria

1. **Given** the existing dead `.env` vars, **when** this story lands, **then** `Settings` declares typed, defaulted clone fields matching the existing env naming — `qwen_tts_clone_enabled: bool = False`, `qwen_tts_clone_model: str = "qwen3-tts-vc-2026-01-22"`, `qwen_tts_clone_voice_path: str = "data/voices/sutak.mp3"`, `qwen_tts_clone_voice_id: str = ""` — placed in the `qwen_tts_*` block of `src/yt_flow/config.py:51-58`, following its comment conventions; `.env.example` gains the two new vars (`YTFLOW_QWEN_TTS_CLONE_ENABLED`, `YTFLOW_QWEN_TTS_CLONE_VOICE_ID`) alongside the two already present.
2. **Given** `qwen_tts_clone_enabled=false` (the default), **when** `tts_node` synthesizes, **then** the outbound request payload is byte-identical to today's (`model=qwen_tts_model`, `voice=qwen_tts_voice` — `tts.py:93-94`) — asserted by a test so a silent default flip cannot ship unnoticed.
3. **Given** the reference sample and a real API key, **when** `scripts/seed_voice_clone.py` runs, **then** it enrolls `data/voices/sutak.mp3` via the `qwen-voice-enrollment` model (`action=create`, `target_model=<qwen_tts_clone_model>`, base64 data-URI audio), prints the returned voice id plus the exact `YTFLOW_QWEN_TTS_CLONE_VOICE_ID=...` line to paste into `.env`, **and** is idempotent: a re-run finds the existing voice via `action=list` and prints its id without creating a second paid voice.
4. **Given** `qwen_tts_clone_enabled=true` and a non-empty `qwen_tts_clone_voice_id`, **when** `tts_node` synthesizes, **then** the request uses `model=qwen_tts_clone_model` and `voice=qwen_tts_clone_voice_id` against the same endpoint path (`_GENERATION_PATH`, `tts.py:28`) — nothing else about the request, download, or scene-audio contract (8 wavs, `audio_path`/`audio_duration`/`word_timings` per scene) changes.
5. **Given** `qwen_tts_clone_enabled=true` but `qwen_tts_clone_voice_id=""`, **when** `tts_node` runs (non-mock), **then** it fails the stage with a readable error naming `scripts/seed_voice_clone.py` — it must NOT silently fall back to the stock voice (a whole video in the wrong voice, unnoticed, is worse than a failed stage).
6. **Given** any synthesis run, **when** the `tts` span is traced, **then** `_record_trace` metadata includes a `voice_mode` field (`"stock"` or `"clone"`) and the `model`/`voice` fields carry the actually-used values, on both success and error paths (`tts.py:177-183`).
7. **Given** the new `qwen_tts_speed: float` setting (env `YTFLOW_QWEN_TTS_SPEED`, **default 1.2**, validated to 0.5–2.0), **when** `tts_node` writes a scene wav (non-mock), **then** speed ≠ 1.0 post-processes the file with ffmpeg `atempo=<speed>` (pitch-preserving) **before** duration is measured at `tts.py:168`, so `audio_duration`, `word_timings`, subtitle cues, and video scene lengths — all derived from the measured file — adapt automatically; speed == 1.0 spawns no ffmpeg process and produces exactly today's file. Applies identically in stock and clone modes. Mock mode scales the synthetic wav length arithmetically (no subprocess).
8. **Given** an env typo like `YTFLOW_QWEN_TTS_SPEED=12`, **when** `Settings` is constructed, **then** it raises a clear `ValidationError` (pydantic `Field(ge=0.5, le=2.0)`), which inside `tts_node` (`Settings()` is built inside the `try` at `tts.py:154`) surfaces as a readable `stage=tts` error — never chipmunk narration.
9. **Given** the test suite runs in CI, **when** this story's tests execute, **then** no real API call and no real ffmpeg spawn is required: payload assertions mock `httpx.AsyncClient.post` (Story 5.13 pattern), the atempo assertion captures the ffmpeg argv via monkeypatch, config tests follow `tests/test_config.py` conventions (default 1.2; out-of-range raises), and all existing `tests/pipeline/nodes/test_tts.py` tests still pass.
10. **Given** the wiring is complete, **when** the A/B listening comparison (DoD) is prepared, **then** the same scene narration (reuse a scene from baseline run `272b05a4`) is synthesized twice at identical speed — stock (`qwen3-tts-flash`/Cherry) and clone (`qwen3-tts-vc-2026-01-22`/enrolled voice) — and both files placed side by side under `workspace/voice-ab/` (`stock.wav`, `clone.wav`) for Jay's ear judgment. **The story does not presume the clone wins**: prosody/naturalness degradation is a live risk (short 7.68s reference sample). Jay's verdict decides the operational default (the `.env` flip; the code default stays `false`), and the verdict is recorded in Dev Agent Record.
11. **Given** a full regression run, **when** the story completes, **then** `uv run pytest tests/pipeline/nodes/test_tts.py tests/test_config.py -q` and the full suite (`uv run pytest -q`) are green.

## Tasks / Subtasks

- [x] **Task 1 — Live-verify the enrollment API contract before coding (AC: 3)** *(Story 5.13 precedent: throwaway live call before implementing against assumed docs)*
  - [x] Confirm the enrollment endpoint works off the project's existing base host: `POST {qwen_tts_endpoint}/api/v1/services/audio/tts/customization` with `{"model": "qwen-voice-enrollment", "input": {"action": "list", ...}}`. The docs show Beijing (`dashscope.aliyuncs.com`) and a Singapore workspace host (`{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com`) and call the intl domain "legacy" — but the account's existing key already synthesizes fine against `dashscope-intl.aliyuncs.com` (same `/api/v1/services/...` family). Try `dashscope-intl` first; only if it 404s/errors, record the workspace host requirement in Dev Agent Record and use it in the script (still no new Settings field unless the host genuinely diverges from `qwen_tts_endpoint` — ponytail: no config for a value that never varies).
  - [x] Confirm with a cheap `action=list` (free) — do NOT `create` until the script is ready (each create costs USD 0.01).
  - [x] Note: `qwen3-tts-vc-2026-01-22` is documented as requiring a Singapore-region API key — the existing key works against the intl endpoint, which is the Singapore-region international surface; if enrollment rejects the key region, record it and stop for Jay (account-level fix, not code).
- [x] **Task 2 — Settings fields (AC: 1, 7, 8)**
  - [x] Add the four clone fields to the `qwen_tts_*` block in `src/yt_flow/config.py:51-58` with defaults per AC1. Switch design: **explicit `qwen_tts_clone_enabled` bool**, not voice-id-presence — presence-based would activate the clone the instant enrollment fills the id, coupling "enrolled" to "shipped"; the explicit bool keeps enrollment safe, lets Jay flip freely after the A/B verdict, and keeps the id in `.env` even while running stock.
  - [x] Add `qwen_tts_speed: float = Field(1.2, ge=0.5, le=2.0)` (`from pydantic import Field` — one import; the constraint is the whole validation story, AC8).
  - [x] Update `.env.example` (add `YTFLOW_QWEN_TTS_CLONE_ENABLED=false`, `YTFLOW_QWEN_TTS_CLONE_VOICE_ID=`, `YTFLOW_QWEN_TTS_SPEED=1.2` next to the existing lines 12-19 TTS block). `.env` itself is operator-owned — Jay flips it after the verdict.
- [x] **Task 3 — Enrollment script `scripts/seed_voice_clone.py` (AC: 3)**
  - [x] House precedent: `scripts/seed_character_prompts.py` (idempotent, `--dry-run`, docstring with usage). Flow: load `Settings` → `action=list` (page through, find a voice whose id embeds the preferred name `sutak` and whose `target_model` == `qwen_tts_clone_model`) → if found, print id + the exact `.env` line and exit → else `action=create` with `preferred_name="sutak"`, `target_model=settings.qwen_tts_clone_model`, `audio.data` as `data:audio/mpeg;base64,<...>` of `qwen_tts_clone_voice_path` → print `output.voice` + `.env` line. Voice id storage decision: **`.env` var via the `qwen_tts_clone_voice_id` Settings field** — it is one string, `.env` already holds every other TTS knob, and a JSON sidecar next to the mp3 would add a second config surface plus a read path in production code for zero benefit.
  - [x] Preflight the sample: file exists, <10 MB. Probed values (2026-07-07): 7.68s / stereo / 48kHz — docs specify mono and recommend 10–20s. Try enrolling as-is first (the API may downmix); if it rejects stereo, downmix once (`ffmpeg -i data/voices/sutak.mp3 -ac 1 data/voices/sutak_mono.mp3`) and point the path setting at the mono file. Record in Dev Agent Record that the sample is below the recommended length — that caveat belongs next to the A/B verdict (AC10).
  - [x] `--dry-run` prints the create payload (audio field elided) without any write. No new deps: `httpx` + stdlib `base64`/`pathlib`.
- [x] **Task 4 — Clone wiring in `tts_node` (AC: 2, 4, 5, 6)**
  - [x] In `_synthesize` (`tts.py:78-103`): select `model`/`voice` by mode — clone enabled → (`s.qwen_tts_clone_model`, `s.qwen_tts_clone_voice_id`), else (`s.qwen_tts_model`, `s.qwen_tts_voice`). Guard: clone enabled + empty voice id → `RuntimeError("qwen_tts_clone_enabled but YTFLOW_QWEN_TTS_CLONE_VOICE_ID is empty — run scripts/seed_voice_clone.py")` (mirrors the existing missing-api-key guard at `tts.py:87-88`; surfaces via the node's existing except → `stage=tts` error, `tts.py:180-184`). No fallback-to-stock (AC5 rationale).
  - [x] Everything else in `_synthesize` stays: same `_GENERATION_PATH`, same auth header, same `output.audio.url` download (`tts.py:97-103`) — the voice-clone synthesis payload is documented as identical in shape (`input.text` + `input.voice`), only the model/voice values differ.
  - [x] `_record_trace` (`tts.py:125-145`): add a `voice_mode` kwarg (`"clone"` if clone enabled else `"stock"`), pass the actually-used model/voice at both call sites (`tts.py:177-178` success, `tts.py:181-183` error; error path uses `"?"` when settings never constructed, as today). The voice id is an opaque provider handle, not a secret — fine in trace metadata.
- [x] **Task 5 — Speech speed (AC: 7, 8)**
  - [x] API allows no numeric rate param (see API Research) → ffmpeg path. In `tts_node`'s per-scene loop: non-mock, `speed != 1.0` → synthesize to a temp sibling (e.g. `scene_XXX.src.wav`), then `ffmpeg -i src -filter:a atempo=<speed> -c:a pcm_s16le <final>`, unlink the temp — all **before** `_wav_duration(path)` at `tts.py:168`, which is the single point every downstream duration consumer hangs off (provisional timings `tts.py:173`, whisperx alignment, subtitle cues, video scene lengths — all read the measured file, so they adapt with zero changes). `atempo` accepts 0.5–2.0 per filter instance — exactly the validated Settings range, single instance suffices, pitch-preserving.
  - [x] Spawn pattern: reuse `_run_ffmpeg` from `src/yt_flow/pipeline/nodes/video.py:498-508` (same-layer import, generic spawn returning `(returncode, stderr)`) **if** importing `video.py` from `tts.py` is side-effect-free at module load (verify — the font fail-fast lives inside a function, but confirm); otherwise inline the same 6-line `asyncio.create_subprocess_exec` locally. Either way this is `tts.py`'s first subprocess call — keep it to the one invocation. Non-zero returncode → raise with stderr tail (whole-stage failure per NFR-8, same as any synthesis error).
  - [x] Mock mode: no subprocess — scale `_write_mock_wav`'s frame count by `1/speed` (`tts.py:61-75`), keeping mock durations meaningful and tests hermetic.
  - [x] Note the incidental benefit: the ffmpeg re-encode also produces an honest WAV header, but `_wav_duration`'s streamed-header defense (`tts.py:41-58`) stays — the speed=1.0 path still writes the raw streamed file.
- [x] **Task 6 — Tests (AC: 2, 4, 5, 6, 7, 8, 9)**
  - [x] `tests/pipeline/nodes/test_tts.py` — extend the `_settings()` SimpleNamespace helper (`test_tts.py:25-33`) with the new fields, defaulting `clone_enabled=False`, `clone_voice_id=""`, `speed=1.0` so every existing test passes unchanged.
  - [x] New tests: (a) clone enabled → mocked `httpx.AsyncClient.post` receives `model=<clone model>`, `voice=<voice id>` (5.13 pattern: the payload-target assertion that makes a silent revert impossible); (b) default/disabled → payload carries stock model/voice (AC2 regression guard); (c) clone enabled + empty voice id → `stage=tts` error mentioning `seed_voice_clone`; (d) trace captures `voice_mode` in success and error paths (extend `test_trace_receives_metrics` pattern, `test_tts.py:174-192`); (e) speed=1.2 non-mock (fake `_synthesize` writes a wav, monkeypatched spawn captures argv) → `atempo=1.2` present, final wav measured after processing; (f) speed=1.0 → zero ffmpeg spawns; (g) mock mode at speed=2.0 → duration ≈ half of speed=1.0's for the same narration.
  - [x] `tests/test_config.py`: default `qwen_tts_speed == 1.2`; `YTFLOW_QWEN_TTS_SPEED=12` → `ValidationError` (existing `_env_file=None` hermetic pattern); clone defaults (`enabled False`, id `""`).
  - [x] Optionally extend the opt-in live smoke (`YTFLOW_QWEN_TTS_SMOKE=1`, `test_tts.py:251-260`) with a clone-mode variant gated on a non-empty voice id — never runs in CI. No script unit tests: `seed_voice_clone.py` is a live operator tool validated by Task 7, matching the untested `seed_*.py` precedent.
- [x] **Task 7 — Enroll + A/B listening comparison (AC: 3, 10)**
  - [x] Run `scripts/seed_voice_clone.py` live; paste the printed id into `.env`; re-run to prove idempotency (no second voice created — check `action=list` count). Record the voice id and both run outputs in Dev Agent Record.
  - [x] Generate the A/B pair: same narration text (a scene from run `272b05a4`), same `qwen_tts_speed`, two synthesis calls (stock settings vs clone settings — a throwaway snippet reusing `tts._synthesize` with two `Settings`-shaped objects is fine, need not be committed) → `workspace/voice-ab/stock.wav` + `workspace/voice-ab/clone.wav`.
  - [x] Hand to Jay. Record the verdict in Dev Agent Record: which voice ships (i.e. whether Jay flips `YTFLOW_QWEN_TTS_CLONE_ENABLED=true` in `.env`), with the prosody/naturalness assessment and the short-sample caveat. If the verdict is pending at review time, the story still completes — the wiring and evidence files are the deliverable; the code default stays `false` either way.
- [x] **Task 8 — Regression (AC: 11)**
  - [x] `uv run pytest tests/pipeline/nodes/test_tts.py tests/test_config.py -q`, then full `uv run pytest -q`; record counts in Dev Agent Record.

### Review Findings

- [x] [Review][Patch] Keep unrelated sprint/config changes out of the 5.21 commit [`_bmad-output/implementation-artifacts/sprint-status.yaml`, `src/yt_flow/config.py`]
- [x] [Review][Patch] Make clone misconfiguration trace `voice_mode=clone` and allow mock mode without a clone id [`src/yt_flow/pipeline/nodes/tts.py`]
- [x] [Review][Patch] Strip whitespace-only clone voice ids before provider use [`src/yt_flow/pipeline/nodes/tts.py`]
- [x] [Review][Patch] Remove temp/final audio artifacts when ffmpeg speed processing fails [`src/yt_flow/pipeline/nodes/tts.py`]
- [x] [Review][Patch] Make seed dry-run avoid reading/base64-encoding the sample audio [`scripts/seed_voice_clone.py`]
- [x] [Review][Patch] Make existing voice detection robust to provider name fields and pagination without `total_count` [`scripts/seed_voice_clone.py`]
- [x] [Review][Patch] Reject directory and empty-file voice samples before enrollment [`scripts/seed_voice_clone.py`]

## Dev Notes

### API Research (2026-07-07) — Qwen TTS Voice Cloning via DashScope

Sources:
- [Alibaba Cloud Model Studio — Voice cloning (Qwen-TTS)](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-voice-cloning)
- [Alibaba Cloud Model Studio — Qwen voice cloning API reference](https://help.aliyun.com/en/model-studio/qwen-omni-voice-cloning)
- [Alibaba Cloud Model Studio — Qwen-TTS API (non-realtime synthesis)](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-api)
- [Alibaba Cloud Model Studio — Non-real-time speech synthesis](https://www.alibabacloud.com/help/en/model-studio/qwen-tts)

Key facts (all load-bearing for this story's design):

1. **Enrollment is one-time and persistent.** Three-step flow: (1) `POST .../api/v1/services/audio/tts/customization` with `{"model": "qwen-voice-enrollment", "input": {"action": "create", "target_model": "qwen3-tts-vc-2026-01-22", "preferred_name": "sutak", "audio": {"data": "<url or data-URI>"}}}` → response `{"output": {"voice": "<voice-id>", "target_model": ...}}`; (2) the returned voice id is permanent (auto-deleted only after 1 year of zero synthesis use); (3) synthesis calls the **same** `multimodal-generation/generation` path the code already uses (`_GENERATION_PATH`, `tts.py:28`) with `{"model": "qwen3-tts-vc-2026-01-22", "input": {"text": ..., "voice": "<voice-id>"}}`. **The `target_model` set at enrollment must exactly match the synthesis model.** Voice id format example: `qwen-omni-vc-guanyu-voice-20250812105009984-838b` (embeds `preferred_name` — this is what makes the script's list-based idempotency check work). `action=list`/`delete` exist for management.
2. **Audio input accepts a base64 data-URI** (`data:<mediatype>;base64,<data>`; WAV 16-bit / MP3 / M4A) — no public-URL upload step needed for the local `sutak.mp3`.
3. **Reference requirements:** 10–20s recommended (max 60s), ≥3s continuous clear speech, <10 MB, ≥24kHz, **mono**. Our sample: 7.68s / stereo / 48kHz / 185 KB — enrollable length-wise but below recommendation; stereo may need downmix (Task 3).
4. **Endpoints:** docs list Beijing `dashscope.aliyuncs.com` and Singapore `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com`, calling the international domain "legacy". The project's `dashscope-intl.aliyuncs.com` works for synthesis today; Task 1 live-verifies enrollment on it before coding. `qwen3-tts-vc-2026-01-22` requires a Singapore-region key.
5. **Pricing:** USD 0.01 per voice creation (1,000 free in the first 90 days); failed creations not charged. Hence: list-before-create idempotency, and no `create` calls from tests.
6. **No numeric speed parameter.** The non-realtime synthesis input supports only `text`, `voice`, `language_type`, and (Instruct-Flash series only) natural-language `instructions` — no `rate`/`speed`/`pitch` field for either `qwen3-tts-flash` or `qwen3-tts-vc`. This decides AC7's implementation: ffmpeg `atempo` post-processing (option b from Jay's direction), not a request parameter.

### Critical Implementation Guardrails

- **Text side is untouched.** Story 5.4's `tts_normalize` contract (normalization happens in the scenario chain; `tts_node` synthesizes `scene["narration"]` verbatim) and Story 5.18's dual track (`SceneState.narration` = spoken text, `SceneState.display_narration` = subtitle text — `src/yt_flow/domain/state.py:55,64`) are both out of scope. This story changes **which voice speaks and how fast the file plays** — never what text is spoken or displayed.
- **Scene-level audio contract unchanged:** one wav per scene under `workspace/{run_id}/audio/scene_XXX.wav`, `audio_path`/`audio_duration`/`word_timings` populated, whole-stage failure on any scene error (NFR-8, `tts.py:166-167`), node purity (AD-4 — returns new scenes, never mutates input).
- **Speed must land before measurement.** `duration = _wav_duration(path)` at `tts.py:168` is the single source every downstream consumer derives from (provisional timings `tts.py:173`, whisperx alignment in `subtitle.py`, video scene/transition lengths). Post-processing after this line — or anywhere outside `tts_node` — would desync subtitles and transitions.
- **No provider abstraction.** One provider, two modes: an `if` on `qwen_tts_clone_enabled` inside `_synthesize`, not a strategy class (ponytail: no interface with one implementation).
- **Fail fast on misconfiguration** (clone on + no voice id) rather than silently degrading to stock — AC5.
- **AD-10 (tracing non-fatal):** `_record_trace` stays best-effort; the `voice_mode` addition must not change its swallow-everything contract (`tts.py:144-145`).
- **No new dependencies.** `httpx` (existing), stdlib `base64`/`wave`/`asyncio.subprocess`, ffmpeg (already a hard runtime dep via `video_node`).

### Current Code State — Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/tts.py` — the whole file (185 lines). Load-bearing lines: `_GENERATION_PATH` (`:28`), `_settings()` test seam (`:32-34`), `_wav_duration` streamed-header defense (`:41-58`), `_write_mock_wav` (`:61-75`), `_synthesize` payload (`:93-94`) + guard (`:87-88`) + download (`:97-103`), `_record_trace` (`:125-145`), node loop with mock branch (`:163-167`), duration measurement (`:168`), trace calls (`:177-178`, `:181-183`).
- `src/yt_flow/config.py:51-58` — the `qwen_tts_*` block the new fields join; `:80-86` — Story 5.13's `character_vision_*` precedent for adding provider fields with the "stays constructible" comment convention.
- `src/yt_flow/pipeline/nodes/video.py:498-508` — `_run_ffmpeg` spawn helper (Task 5 reuse candidate).
- `tests/pipeline/nodes/test_tts.py` — conventions: SimpleNamespace `_settings` fake (`:25-33`), monkeypatched `_settings`/`_synthesize`/`_record_trace` seams, autouse `_silent_trace` (`:67-69`), opt-in live smoke (`:251-260`). Mock mode writes real WAVs so duration assertions are meaningful.
- `scripts/seed_character_prompts.py` — the seed-script house style (docstring usage block, `--dry-run`, idempotency).
- `.env` / `.env.example` lines 12-19 — the existing TTS env block, including the two dead clone vars whose names the Settings fields must match.

### Testing Standards Summary

Mock-based only in CI (AC9): no live DashScope call, no real ffmpeg spawn, no `action=create` ever from tests (it costs money). Payload assertions via mocked `httpx.AsyncClient.post` (Story 5.13's pattern — it exists precisely because a payload regression once had zero test coverage). Live verification is Task 7's job, not the suite's.

## Project Structure Notes

- Expected new file: `scripts/seed_voice_clone.py`
- Expected modified files: `src/yt_flow/config.py`, `src/yt_flow/pipeline/nodes/tts.py`, `.env.example`, `tests/pipeline/nodes/test_tts.py`, `tests/test_config.py`
- Possible data file: `data/voices/sutak_mono.mp3` (only if enrollment rejects the stereo original — Task 3)
- No changes to: `src/yt_flow/domain/state.py`, `subtitle.py`, `video.py` (unless exporting `_run_ffmpeg` needs a touch — keep it read-only if possible), `scenario_chain.py`, graph wiring, frontend, prompts, DB models.

### References

- E2E baseline report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` (run `272b05a4` — stock-voice narration, slow pacing feedback)
- Text-side contracts preserved: `_bmad-output/implementation-artifacts/5-4-tts-korean-naturalization.md` (AC2 single-source narration → TTS), `5-18-subtitle-display-text-dual-track.md` (display vs spoken split)
- Provider-wiring precedent: `_bmad-output/implementation-artifacts/5-13-character-vision-provider-swap.md` (config fields + payload-target test + live-verify-before-code discipline)
- Architecture: AD-4 (node purity), AD-10 (non-fatal tracing), NFR-8 (whole-stage failure) — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- API docs: see Dev Notes → API Research (four Alibaba Cloud Model Studio URLs, fetched 2026-07-07)

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- 2026-07-07: Activation loaded `bmad-dev-story`; no prepend/append activation steps; no project-context.md present.
- 2026-07-07: Live `action=list` against `https://dashscope-intl.aliyuncs.com/api/v1/services/audio/tts/customization` returned 200 with `output.voice_list`; no workspace-host override needed.
- 2026-07-07: Initial seed script pagination used `page_index=1`; provider returned an empty list for that page, so the first two live script runs created two `sutak` voices. Fixed script to use provider-compatible zero-based pagination (`page_index=0`); final two reruns both printed `found existing voice; no create call made` with voice id `qwen-tts-vc-sutak-voice-20260707211054527-0f76`.
- 2026-07-07: Generated A/B files from baseline run `272b05a4-78c6-4874-89a7-13c7e6df405e` scene 001 ASS text at speed 1.2: `workspace/voice-ab/stock.wav` (18.07s, 867392 bytes) and `workspace/voice-ab/clone.wav` (13.33s, 640124 bytes).
- 2026-07-07: Validation: `uv run pytest tests/pipeline/nodes/test_tts.py tests/test_config.py tests/test_seed_voice_clone.py -q` => 44 passed, 1 skipped. `uv run ruff check src/yt_flow/pipeline/nodes/tts.py scripts/seed_voice_clone.py tests/pipeline/nodes/test_tts.py tests/test_seed_voice_clone.py` => all checks passed. Full `uv run pytest -q` => 799 passed, 1 skipped, 1 warning.

### Completion Notes List

- Added typed clone settings and speed validation while keeping `qwen_tts_clone_enabled` default false and `.env` clone-enabled false.
- Added `scripts/seed_voice_clone.py` with list-before-create behavior, dry-run payload printing, sample preflight, and final verified idempotency on the existing DashScope international host.
- Wired `tts_node` to select stock vs clone model/voice explicitly, fail fast when clone mode lacks a voice id, and record `voice_mode` plus actual model/voice on success and error traces.
- Implemented speed control through ffmpeg `atempo` before duration measurement; mock mode scales WAV frame count without subprocess.
- Code review fixes: clone misconfiguration now records `voice_mode=clone`, mock clone mode remains hermetic without a voice id, whitespace-only voice ids fail fast, ffmpeg failure cleans temp/final audio, and seed enrollment dry-run/idempotency/sample validation are hardened.
- Prepared Jay listening evidence under `workspace/voice-ab/`. Verdict is pending Jay's ear; code default remains stock (`qwen_tts_clone_enabled=false`). Caveat: the reference sample remains 7.68s/stereo, below the recommended 10-20s mono guidance, though enrollment and synthesis succeeded as-is.

### File List

- `.env` (operator config updated with clone id, clone-enabled false, speed 1.2)
- `.env.example`
- `_bmad-output/implementation-artifacts/5-21-tts-voice-clone-wiring.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `scripts/seed_voice_clone.py`
- `src/yt_flow/config.py`
- `src/yt_flow/pipeline/nodes/tts.py`
- `tests/pipeline/nodes/test_tts.py`
- `tests/test_seed_voice_clone.py`
- `tests/test_config.py`
- `workspace/voice-ab/stock.wav`
- `workspace/voice-ab/clone.wav`

## Change Log

- 2026-07-07: Story drafted (create-story workflow) from the E2E baseline 2026-07-06 finding (narration confirmed stock voice; the `.env` clone vars are dead config never declared in `Settings`) + Jay's 2026-07-07 direction. Scope addition same day: configurable TTS speech speed, deliberate 1.2x default. API research resolved the two open design questions: enrollment is one-time/persistent (voice id via `qwen-voice-enrollment`, `action=list` enables an idempotent seed script), and the synthesis API has no numeric speed parameter (→ ffmpeg `atempo` before duration measurement). Clone ships behind `qwen_tts_clone_enabled=false`; Jay's A/B listening verdict — not an assumption — decides the operational default.
- 2026-07-07: Implemented voice clone settings, idempotent enrollment script, stock/clone TTS payload selection, clone misconfiguration fail-fast, trace `voice_mode`, ffmpeg `atempo` speed processing, CI tests, live enrollment verification, and A/B listening files. Story ready for review; Jay verdict on `workspace/voice-ab/stock.wav` vs `workspace/voice-ab/clone.wav` remains pending.
- 2026-07-07: Code review completed and findings patched: trace/mock clone edge cases, ffmpeg cleanup, seed-script dry-run/idempotency/pagination/sample validation, and focused 5.21 commit scope. Story marked done.
