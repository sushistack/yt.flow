---
created: 2026-08-03
baseline_commit: 878bad6f2e17131baa5778eaf39cf071dc1083a8
story_key: 12-5-tts-provider-comparison-naver
story_id: "12.5"
epic: 12
status: done
depends_on:
  - 5-21-tts-voice-clone-wiring
  - 5-24-voice-clone-force-reseed
related:
  - 5-4-tts-korean-naturalization
  - 5-18-subtitle-display-text-dual-track
  - 11-4-whisperx-always-on-beat-cuts
workflow_decision: "Run a policy-cleared, blind A/B/C listening comparison first. Change the production TTS provider only after Jay records a Naver adoption verdict."
---

# Story 12.5: TTS Provider Comparison — Naver CLOVA Voice

Status: done

## Story

As Jay,
I want to compare the same Korean narration scene rendered by Qwen stock, Qwen clone, and Naver CLOVA Voice,
so that I can decide from listening evidence whether Naver's Korean prosody justifies a provider change and its capability and policy trade-offs.

## Context and Decision Boundary

This is a **decision story**, not a pre-authorized Naver migration. Its first deliverable is a reproducible, blinded three-candidate listening package and Jay's recorded verdict. It also closes the unresolved stock-versus-clone listening DoD from Story 5.21.

The implementation has two strictly ordered phases:

1. **Comparison phase (always):** verify Naver usage eligibility, generate one A/B/C package, conduct blind listening, and record the verdict.
2. **Adoption phase (conditional):** modify the production TTS path only if the verdict is `naver` and the policy/capability gate passed. For `qwen-stock`, `qwen-clone`, or `inconclusive`, leave production provider code and defaults unchanged.

Do not describe the three candidates as equivalent voice-cloning options. Qwen clone uses Jay's enrolled `sutak` voice; the public Naver Cloud API currently exposes a fixed speaker inventory and no public self-service voice-enrollment endpoint. Naver is therefore a **stock-voice candidate** unless official account-specific documentation proves otherwise.

## Acceptance Criteria

1. **Policy and product feasibility is resolved before persisted Naver audio is generated.**
   - Given the comparison helper would save and post-process the returned Naver audio,
   - when the developer checks the current official Naver API, usage-policy, and CLOVA Dubbing documentation,
   - then `_bmad-output/implementation-artifacts/12-5-tts-provider-comparison-naver.md` records the dated evidence and one of these approved paths:
     - written/account-specific confirmation that the CLOVA Voice API output may be saved and processed for this YouTube workflow; or
     - a CLOVA Dubbing Premium export whose plan permits download/editing for the intended content use.
   - The current documentation conflict must not be resolved by assumption: the API reference returns binary WAV/MP3 and includes save examples, while the usage policy says CLOVA Voice is real-time-only and generated voice files may not be saved, edited, or reused. If neither approved path is available, record `naver-ineligible`, do not call the API or persist its output, do not claim the three-way DoD passed, and report the blocker to Jay.

2. **Naver capability and trade-offs are recorded.**
   - The evidence report records endpoint, auth headers, request content type, selected speaker, format/sample rate, current pricing/quota facts available to the account, and whether custom voice cloning is available to this account.
   - Public-doc inference must be labeled as inference: the official API index lists only TTS, and the request accepts a fixed `speaker`; no public create/list/delete voice-enrollment API is documented. The Naver Cloud CLOVA Dubbing product also states that Voice Maker is not supported there.
   - If no supported Naver clone path exists, the report explicitly states that Naver adoption gives up the current Qwen cloned-voice identity and preserves the Qwen clone assets/scripts for rollback.

3. **One representative source scene is frozen before synthesis.**
   - The exact `SceneState.narration` spoken-track text is used byte-for-byte for all three candidates; `display_narration` is not used.
   - The scene contains natural Korean plus the Qwen-normalization-sensitive cases this decision could expose: an SCP identifier or Roman acronym, a number or unit, and at least one comma/breath boundary.
   - The comparison manifest records the text, SHA-256, source run/scene (or a clear manually curated source), generation time, and current `tts_normalize` prompt/version provenance.
   - No provider-specific spelling, punctuation, number expansion, or other text edit is permitted in the primary comparison.

4. **The comparison helper produces three correctly labeled candidates.**
   - A narrow operator helper such as `scripts/compare_tts_providers.py` generates:
     - current configured Qwen stock (`qwen3-tts-flash` / `Cherry` unless config changed before the manifest is frozen),
     - current configured Qwen clone (`qwen3-tts-vc-2026-01-22` and the current enrolled voice from the 12.93-second `data/voices/sutak.mp3` lineage), and
     - one official Korean Naver stock speaker (`nara` is the reproducible baseline; an alternate may be used only if Jay selects and the manifest freezes it before candidate generation).
   - All candidates receive the same current post-synthesis speed factor (`1.2`) and the same deterministic output conversion. Final files are readable PCM WAV with identical sample rate, channel count, bit depth, and a documented loudness-normalization rule so format/volume does not reveal the provider.
   - Naver uses `POST https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts`, the two NCP API-key headers, `application/x-www-form-urlencoded`, `format=wav`, and a supported WAV sampling rate. It handles a binary response, not DashScope's JSON-plus-download-URL contract.
   - Raw provider outputs, normalized blind files, and a non-secret manifest are written under a new run-specific directory such as `workspace/tts-provider-comparison/<timestamp>/`; the helper does not overwrite the absent/stale Story 5.21 `workspace/voice-ab/` paths.

5. **The listening package is blind and auditable.**
   - Candidate filenames exposed to Jay are neutral (`A.wav`, `B.wav`, `C.wav`), with a randomized mapping stored separately and not revealed until scores are finalized.
   - The scorecard captures 1–5 ratings for Korean naturalness, pronunciation of normalization-sensitive tokens, prosody/breathing, pace, voice fit for SCP documentary-horror, and artifacts/noise, plus free-form notes and an overall preference.
   - The final verdict is exactly one of `qwen-stock`, `qwen-clone`, `naver`, or `inconclusive`; it includes Jay's name/date, the revealed mapping, and the reason. Do not force a winner on a tie or low-confidence result.

6. **The comparison phase does not mutate production behavior.**
   - Before the verdict, do not edit `src/yt_flow/pipeline/nodes/tts.py`, `prompts/scenario/tts_normalize.md`, graph/state/API/UI files, the Qwen clone enrollment, or the production provider default.
   - The helper may add typed Naver comparison settings to `src/yt_flow/config.py`, placeholders to `.env.example`, and mocked tests, but secrets remain only in the operator-owned `.env`/environment and never appear in manifests, logs, errors, traces, test fixtures, or commits.
   - CI/tests make no live or paid provider calls and never create/delete a cloned voice.

7. **A non-Naver or inconclusive verdict closes without provider integration.**
   - For `qwen-stock`, `qwen-clone`, or `inconclusive`, the story records the result, confirms `tts.py` and `tts_normalize.md` are unchanged, and records the operational Qwen choice separately if Jay wants stock/clone default configuration changed.
   - A Qwen-clone verdict may change operator configuration only after Jay's explicit decision; it must not re-enroll or delete the voice as part of this story.

8. **A Naver verdict conditionally integrates the provider without breaking the pipeline.**
   - Only after AC5 records `naver` and AC1 is eligible, add a closed, validated provider selector and Naver config fields. Keep Qwen as a supported rollback path; do not delete Qwen clone settings, `scripts/seed_voice_clone.py`, or `data/voices/sutak.mp3`.
   - Preserve the TTS node contract: sorted per-scene processing; `scene["narration"]` input; PCM-readable `.wav` at `workspace/{run_id}/audio/scene_NNN.wav`; speed processing before duration measurement; measured `audio_duration`; provisional timings only as WhisperX fallback; upstream scene fields unchanged; no in-place state mutation; whole-stage failure with no partial `scenes`; `stage=tts`/`run_id` error context; non-fatal tracing.
   - Provider-specific request/response handling is isolated behind a small synthesis seam. Do not build a strategy-class hierarchy or change `PipelineState`, graph topology, DB, API contracts, or frontend for two providers.
   - Config pins provider/endpoint/speaker; invalid provider or missing credentials fails clearly. Trace metadata records provider/model-or-service/speaker/mode without secrets.

9. **Naver adoption includes a normalization ablation before changing the prompt.**
   - The primary A/B/C comparison keeps current Qwen-tuned `tts_normalize` output fixed.
   - If Naver wins, compare Naver reading of current normalized text against the corresponding pre-normalization writing text, focusing on numbers/units, acronyms, SCP designations, spacing, and breath punctuation.
   - Change `prompts/scenario/tts_normalize.md` only when the ablation provides concrete evidence, while preserving the dual-track and one-to-one sentence-count contracts and following `docs/PROMPT_POLICY.md`. Otherwise leave the prompt unchanged and record why.

10. **Tests and live evidence prove the delivered branch.**
    - Mocked comparison-helper tests assert exact provider target/headers/body, identical source text and speed, deterministic output format, blind mapping completeness, manifest redaction, missing-credential preflight, cleanup/no misleading partial manifest on failure, and zero network calls in dry-run/unit tests.
    - Existing TTS/config/clone tests remain green.
    - If Naver is adopted, add regression tests for selector/default behavior, exact Naver binary-response handling, WAV validation/conversion, HTTP failure/no-partial-output, trace metadata, and preservation of every existing Qwen stock/clone test. Add an opt-in live Naver smoke test gated by an explicit environment flag; skip it by default.
    - Completion notes include the focused test and lint commands/results, evidence directory, manifest path, scorecard/verdict, and whether the conditional adoption/normalization branches ran.

## Tasks / Subtasks

- [x] Task 0: Resolve Naver policy/product feasibility (AC: 1, 2)
  - [x] Re-check current official API, speaker inventory, auth, request/response, limits, pricing/account quota, and usage policy.
  - [x] Obtain and record an eligible persisted-audio path; stop safely on `naver-ineligible`. → **`naver-ineligible`**, stopped safely.
  - [x] Record custom-voice availability as documented fact or clearly labeled inference.

- [x] Task 1: Freeze the representative scene and comparison protocol (AC: 3, 5)
  - [x] Choose one source scene with the required Korean/number/acronym/pause coverage.
  - [x] Freeze exact spoken text, hash, provider settings, output format, randomization method, and rubric before synthesis.

- [x] Task 2: Implement a comparison-only helper and tests (AC: 4, 6, 10)
  - [x] Reuse the existing Qwen payload, download, ffmpeg speed, and WAV validation patterns without changing `tts_node`.
  - [x] ~~Add the minimal Naver binary-response client~~ — **not built**: AC1 returned `naver-ineligible`, so a Naver client would be code that policy forbids running. No Naver config field added either (nothing to configure).
  - [x] Write mocked tests; no paid/live calls in CI. → **30 tests**, all mutation-verified (17 on 2026-08-07, +12 E2E from the QA pass, +1 from the 2026-08-08 review).

- [x] Task 3: Generate and validate the live A/B package (AC: 3, 4, 5) — 2 candidates, not 3 (Naver ineligible)
  - [x] Preflight both providers and clone ID without logging secrets.
  - [x] Generate both raw candidates, apply identical post-processing, and validate each final WAV.
  - [x] Create neutral filenames, hidden mapping, redacted manifest, and scorecard.

- [x] Task 4: Obtain Jay's blind listening verdict (AC: 5) — **verdict `qwen-clone`, Jay, 2026-08-08**
  - [x] Keep mapping hidden until the scorecard is complete.
  - [x] Reveal, record one allowed verdict, and explicitly close Story 5.21's pending listening DoD. → 5.21's stock-vs-clone DoD, open since 2026-07-07, is **closed**: clone wins.

- [x] Task 5A: Close without production integration when verdict is not Naver (AC: 6, 7, 10)
  - [x] Confirm production TTS and normalization files remain unchanged. → verified: zero diff vs `878bad6`.
  - [x] Record the selected Qwen operational mode or the inconclusive next step. → listening preference is **clone**; production stays on **stock** (`qwen_tts_clone_enabled=False`) pending a separate explicit Jay authorization. See "Task 5A" note below.

- [x] Task 5B: ~~Integrate Naver~~ — **UNREACHABLE.** AC8 is gated on "AC5 records `naver` AND AC1 is eligible". AC1 is `naver-ineligible`, so this branch is closed and its subtasks are void.
  - [x] ~~Add the minimal provider selector/client seam and secret-safe config.~~
  - [x] ~~Preserve all node/state/error/timing/Qwen rollback contracts and add regression coverage.~~
  - [x] ~~Run the normalization ablation (AC9); change the prompt only with evidence.~~ — prompt left unchanged, reason recorded below.
  - [x] ~~Run focused/full tests, lint, and opt-in live smoke; record results.~~

## Dev Notes

### Critical Guardrails

- **Do not implement Naver first and justify it afterward.** The listening verdict and policy eligibility are gates, not documentation chores.
- **Do not reuse Epic 4's automated prompt A/B feature.** This is a one-time, human, three-way provider-selection experiment; it does not satisfy or modify the product's prompt-variant evaluation contract.
- **Do not compare different text.** Provider-specific normalization in the primary experiment invalidates the result.
- **Do not silently discard clone capability.** Naver stock and Qwen clone are operational alternatives with different identity capabilities.
- **Do not put NCP or DashScope credentials in CLI arguments, committed files, manifests, error messages, or traces.** Use environment-backed settings and redact provider identifiers where they could be sensitive.
- **Do not treat provider word timings as a benefit or regression.** Neither comparison path supplies alignment-quality word timings; WhisperX remains authoritative.
- **Do not trust an `.wav` extension.** Naver must request WAV or be converted, and the final file must pass the existing PCM reader/validation contract.

### Current Code State — UPDATE/PRESERVE Map

- `src/yt_flow/pipeline/nodes/tts.py` — **PRESERVE during comparison; UPDATE only on Naver adoption.** Today `_voice_config` selects Qwen stock/clone, `_synthesize` posts DashScope JSON then downloads a URL, `_apply_speed` runs ffmpeg `atempo`, `_wav_duration` validates/bounds PCM duration, and `tts_node` preserves purity/no-partial-output. Keep the node loop and contracts; isolate only provider-specific synthesis if adopted. [Source: `src/yt_flow/pipeline/nodes/tts.py:43`, `:80`, `:102`, `:110`, `:191`]
- `src/yt_flow/config.py` — **UPDATE minimally for comparison settings; extend selector only on adoption.** All model/service identifiers belong in `Settings` with `YTFLOW_` prefix. Secret defaults stay empty so tests/tooling remain constructible. [Source: `src/yt_flow/config.py:60`]
- `.env.example` — **UPDATE** with placeholders only. `.env` is operator-owned and must never be copied into evidence.
- `scripts/compare_tts_providers.py` — **NEW recommended comparison boundary.** It must not import or invoke the whole LangGraph run merely to render one scene.
- `tests/test_compare_tts_providers.py` — **NEW.** Mock both providers and ffmpeg; assert the decision package, not audio quality.
- `tests/pipeline/nodes/test_tts.py`, `tests/test_config.py` — **UPDATE only as required** by config/adoption; preserve all Qwen clone, speed, error, trace, purity, and WAV guards.
- `scripts/seed_voice_clone.py`, `tests/test_seed_voice_clone.py`, `data/voices/sutak.mp3` — **PRESERVE.** The current sample was re-enrolled by Story 5.24; `--force` is destructive/billed and is not needed here.
- `prompts/scenario/tts_normalize.md` and its scenario-chain call site — **PRESERVE in the primary comparison; conditional UPDATE after Naver wins and ablation proves a change.** It currently owns spoken-form spacing, breath punctuation, number/unit, and acronym rewrites while preserving meaning/order/counts. [Source: `prompts/scenario/tts_normalize.md:1`]
- `src/yt_flow/domain/state.py`, `subtitle.py`, graph, services, DB, API, frontend — **PRESERVE.** Existing generic audio artifacts and WhisperX alignment already support either provider.

### Existing Behavior That Must Survive Adoption

- TTS remains a pure pipeline node with no DB/SSE/gate writes and wholesale state replacement. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- Model/service identifiers are config-pinned, never hardcoded in the node. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional-Requirements`]
- `narration` is the spoken/alignment track; `display_narration` stays the subtitle display track. [Source: `_bmad-output/implementation-artifacts/5-18-subtitle-display-text-dual-track.md#Acceptance-Criteria`]
- The current 1.2 speed factor is applied before duration measurement; failed post-processing removes partial output. [Source: `_bmad-output/implementation-artifacts/5-21-tts-voice-clone-wiring.md#Completion-Notes-List`]
- WhisperX is always attempted downstream; provisional timings are fallback only. [Source: `_bmad-output/planning-artifacts/epics.md#Story-11.4-WhisperX-always-on-alignment`]

### Previous Story and Git Intelligence

- No Story 12.1–12.4 implementation artifact exists; all are backlog. Do not assume an Epic 12 predecessor was implemented.
- Story 5.21 created Qwen stock/clone selection and the 1.2 speed path but left listening judgment open. Its old `workspace/voice-ab/` evidence is absent and must be regenerated.
- Story 5.24 re-enrolled the current Qwen clone from the improved 12.93-second sample. Do not use the obsolete enrollment or trigger destructive `--force` reseeding.
- Story 5.13 is the provider-swap precedent: pin configuration, change the HTTP boundary only, assert the exact outbound target/payload, preserve errors, and live-verify after mocked tests.
- Recent commits (`7141707`, `13a47ed`, `344fd5f`, `cc82403`, `76da474`) are planning/policy/asset work and add no newer TTS implementation pattern. Relevant TTS patterns remain the narrow Story 5.21/5.24 commits.

### Library and Framework Requirements

- Python `>=3.12,<3.13`; use the existing async HTTP client already imported by runtime code (`httpx` 0.28.1 in the lock), stdlib `wave`/`pathlib`/`hashlib`/`json`, and the existing ffmpeg subprocess pattern. Add no TTS SDK or audio library for one form-encoded POST.
- Current authoritative pins include Pydantic Settings 2.14.2, pytest 9.1.1, and ruff 0.15.20. Architecture-spine version rows are older than the lock/manifest; code and lock win.
- Naver's documented request is form-encoded and response is binary. Do not send DashScope JSON or attempt to parse a Naver JSON success body.

### Testing Requirements

Recommended focused verification:

```bash
uv run pytest tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py tests/test_config.py tests/test_seed_voice_clone.py -q
uv run ruff check scripts/compare_tts_providers.py src/yt_flow/config.py src/yt_flow/pipeline/nodes/tts.py tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py tests/test_config.py
```

Then run `uv run pytest -q`. Live smoke/generation requires explicit environment flags and real credentials; it is never part of the default suite. Audio quality remains a human evidence requirement and cannot be claimed from mocked tests.

### Latest Official Naver API Information (checked 2026-08-03)

- CLOVA Voice Premium: `POST /tts`, fixed `speaker`, UTF-8 `text`, form-encoded request, binary MP3/WAV response; Korean input limit 2,000 characters; WAV supports 8/16/24/48 kHz. Speed is `-5..10` with provider-specific semantics, so use provider-native speed `0` and apply the same existing post-process factor to all candidates. [Official TTS API](https://api.ncloud-docs.com/docs/en/ai-naver-clovavoice-ttspremium)
- Auth requires `X-NCP-APIGW-API-KEY-ID` and `X-NCP-APIGW-API-KEY`; the application must have CLOVA Voice Premium enabled. [Official API overview](https://api.ncloud-docs.com/docs/en/ai-naver-clovavoice)
- API limits include 2,000 Korean characters per call, symbols/parenthetical text may not be read, and sampling rate selection is WAV-only. [Official prerequisites](https://guide.ncloud-docs.com/docs/clovavoice-spec)
- Usage-policy warning: CLOVA Voice is documented as real-time API use and says generated voice files cannot be saved/edited/reused; CLOVA Dubbing is directed for saved/editable content. This conflicts with API save examples, so eligibility requires explicit resolution before live evidence or adoption. [Official usage policy](https://guide.ncloud-docs.com/docs/en/clovavoice-policy)
- Naver Cloud CLOVA Dubbing supports downloadable content under plan terms but says Voice Maker is not supported in the Naver Cloud Platform product. [Official CLOVA Dubbing product](https://www.ncloud.com/api-cms/service-product/static/clovaDubbing)

### Project Structure Notes

- Keep experiment outputs under `workspace/`; it is the configured runtime artifact root and is gitignored. Commit only non-secret textual evidence required for review.
- Do not add a DB model, API endpoint, UI screen, LangGraph node, provider package, or reusable service for this one-scene decision experiment.
- The PRD originally names Qwen in FR-4 and as an external dependency. Epic 12's 2026-08-03 decision authorizes comparison, but only Jay's recorded Naver verdict supersedes the Qwen-only operational choice. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1-Pipeline-Core-LangGraph`; Source: `_bmad-output/planning-artifacts/epics.md#Story-12.5-TTS-provider-comparison-Naver-Clova-Voice-review-conditional`]

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-12-script-and-narration-quality-retention-structure-model-split-grounded-gate`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Story-12.5-TTS-provider-comparison-Naver-Clova-Voice-review-conditional`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1-Pipeline-Core-LangGraph`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10-Operational-envelope`]
- [Source: `_bmad-output/implementation-artifacts/5-21-tts-voice-clone-wiring.md`]
- [Source: `_bmad-output/implementation-artifacts/5-24-voice-clone-force-reseed.md`]
- [Source: `_bmad-output/implementation-artifacts/5-18-subtitle-display-text-dual-track.md`]
- [Official Naver CLOVA Voice TTS API](https://api.ncloud-docs.com/docs/en/ai-naver-clovavoice-ttspremium)
- [Official Naver CLOVA Voice usage policy](https://guide.ncloud-docs.com/docs/en/clovavoice-policy)

## Dev Agent Record

### Agent Model Used

GPT-5.4

### Debug Log References

#### AC1 / AC2 — Naver eligibility evidence (re-checked 2026-08-07)

**Verdict: `naver-ineligible`.** The story framed the API-vs-policy contradiction as unresolved. It is not: the
usage policy states the restriction directly and names the alternative product, in both language editions.

Primary sources fetched 2026-08-07:

| Source | Verbatim finding |
|---|---|
| [Usage policy (KO)](https://guide.ncloud-docs.com/docs/clovavoice-policy) | `파일 다운로드 \| X` · `음성/영상 편집 서비스 제작 \| X` · "CLOVA Voice 는 반드시 실시간 API 호출 방식으로 이용해야 합니다" · "파일을 저장하거나, 편집하여 재사용하려면 CLOVA Dubbing 서비스를 이용해 주십시오" · "CLOVA Voice API 또는 생성된 음성 파일을 재판매할 수 없습니다" |
| [Usage policy (EN)](https://guide.ncloud-docs.com/docs/en/clovavoice-policy) | "You cannot resell the CLOVA Voice API or the generated voice files. To save, edit, and reuse the files, please use the CLOVA Dubbing service." · "CLOVA Voice must be used as a live API call." · Download file = ✗ |
| [TTS Premium API](https://api.ncloud-docs.com/docs/en/ai-naver-clovavoice-ttspremium) | `POST https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts`; headers `X-NCP-APIGW-API-KEY-ID` + `X-NCP-APIGW-API-KEY`; `application/x-www-form-urlencoded`; params `speaker`(req), `text`(req), `volume/speed/pitch/alpha/end-pitch` −5..5 (speed −5..10), `emotion` 0–3, `emotion-strength` 0–2, `format` mp3\|wav, `sampling-rate` 8000/16000/24000/48000; **binary** audio response; Korean limit 2,000 chars; Korean speakers include `nara`, `jinho`, `mijin`, `nbora`, `ndaeseong`, `ngoeun`, `vyuna`, `vmikyung` (70+) |
| [API overview](https://api.ncloud-docs.com/docs/en/ai-naver-clovavoice) | **Exactly one** documented endpoint (TTS). No create/list/delete voice-enrollment API. Quota misconfiguration surfaces as HTTP 429. |

**Why this workflow is not eligible.** yt.flow's TTS stage saves the response to
`workspace/{run_id}/audio/scene_NNN.wav`, *edits* it (ffmpeg `atempo` speed change), and *reuses* it (muxed into a
published YouTube video). That is precisely save + edit + reuse, which the policy assigns to CLOVA Dubbing, not to
the Voice API. This is a categorical mismatch, not a tunable one.

Neither AC1-approved path is open:
- **Path (a) — account-specific written confirmation:** unavailable. There is no NCP account in this project at
  all: no `YTFLOW_NCP_*` / `NAVER_*` / `CLOVA_*` key exists in the main tree `.env` (24 keys, checked; TTS keys are
  DashScope-only). With no account there is no counterparty to issue an exception.
- **Path (b) — CLOVA Dubbing Premium export:** unavailable and structurally unsuitable. Dubbing is a separate
  subscription web product, not an API, so it cannot be driven by `scripts/compare_tts_providers.py` and could not
  serve a per-run pipeline stage even if a one-off export were obtained for the comparison.

**AC2 — capability trade-off.** Custom voice cloning is **not available to this account**, stated at two levels of
confidence: *documented fact* — the public API index exposes only TTS with a fixed `speaker`, and no voice
create/list/delete endpoint is documented; *labeled inference* — NAVER markets a "Voice Maker" speaker-adaptation
offering (~40 min of recorded audio), but it appears as an enterprise/contract offering with no public
self-service API, and Naver Cloud's CLOVA Dubbing product page states Voice Maker is not supported there. So had
Naver been adopted, it would have **given up the Qwen cloned-voice identity** (`sutak`) entirely. Rollback assets
are preserved untouched: `scripts/seed_voice_clone.py`, `data/voices/sutak.mp3`, and all `qwen_tts_clone_*`
settings.

**Consequences applied.** Per AC1: the API was never called, no Naver audio was persisted, the three-way DoD is
**not** claimed, and no Naver client, config field, or `.env.example` placeholder was added. AC8 and AC9 (Task 5B)
are unreachable because both are explicitly gated on AC1 eligibility. `prompts/scenario/tts_normalize.md` is
therefore unchanged — the AC9 ablation only triggers on a Naver win.

#### Corrections to the story's Dev Notes (verified against primary sources)

1. **"Story 5.21's `workspace/voice-ab/` evidence is absent"** — stale. It **exists** in the main tree
   (`clone.wav` 640 KB, `stock.wav` 867 KB, both dated 2026-07-07); it is absent only from this worktree. It must
   still be regenerated, but for a different reason than recorded: the clone was **re-enrolled on 2026-07-10 by
   Story 5.24**, so that `clone.wav` was rendered by the now-obsolete enrollment. The helper writes to
   `workspace/tts-provider-comparison/<timestamp>/` and does not touch those files.
2. **"No Story 12.1–12.4 implementation artifact exists; all are backlog"** — stale. 12.1–12.4 are all `done` and
   committed (`2f28e2c`, `f95427d`, `3b974a0`, `878bad6`). This does not affect 12.5's TTS surface.
3. **`tts_normalize.md` provenance** — the frozen scene predates a later edit to that file, so this was checked
   rather than assumed: `342d6af` (2026-07-11) changed only the **output format** (JSON → YAML) and the
   `{{parse_error}}` retry hook. The normalization **rules** are unchanged since `bac6f2b` (Story 5.4,
   2026-07-04), so the frozen text is representative of current normalizer behaviour.

### Completion Notes List

**2026-08-07 — dev-story run. Tasks 0/1/2 delivered; Tasks 3/4 blocked; Task 5B closed as unreachable.**

*Task 0 (AC1, AC2)* — Verdict `naver-ineligible`; full dated evidence table in Debug Log above. This is the
story's own designed stop condition, not a failure to implement.

*Task 1 (AC3, AC5)* — Frozen scene: `data/tts-comparison/scene.txt`, SHA-256
`8c6b8399ebf9352277a169d34552c100194af892bdc129999da4a6918afec1f0`, 585 bytes / 243 chars, no trailing newline so
it is byte-for-byte the `SceneState.narration` value. Source: the **`narration`** field (not `display_narration`)
of scene 4 of completed run `53bceeaf-eed5-443b-b185-34d8b8522055` (SCP-096, 2026-07-04, status `complete`),
extracted from the LangGraph checkpoint. AC3 coverage is real, not asserted — a test pins each case:
SCP identifier `에스씨피-096` (digits + hyphen survive normalization), number + unit `이점삼팔 미터`, and 6 comma
breath boundaries in natural documentary-horror Korean.

Selection note: this is a July run rather than the newest one on purpose. Every scene in the most recent run
(`6a9a49d9`, SCP-999, 2026-08-06) was scanned and **none** retains an SCP identifier or Roman acronym — the
normalizer had spelled them all into plain Korean. 190 unique narrations across every checkpoint in the dev DB
were scanned to find one that keeps the normalization-sensitive tokens AC3 requires.

*Task 2 (AC4, AC6, AC10)* — `scripts/compare_tts_providers.py`: renders the frozen text through Qwen stock and
Qwen clone, identical post-processing for both
(`atempo=1.2,loudnorm=I=-16:TP=-1.5:LRA=11 -ar 24000 -ac 1 -c:a pcm_s16le`), writes
`workspace/tts-provider-comparison/<timestamp>/` with `raw/`, `listen/{A,B}.wav` + `scorecard.md`,
`reveal/mapping.json`, and a redacted `manifest.json`. Design decisions worth flagging:
- Each candidate's voice mode is **forced** via `Settings.model_copy(update=...)` rather than inherited from
  ambient `.env` — otherwise a machine with `YTFLOW_QWEN_TTS_CLONE_ENABLED=true` would silently render two clones
  and the "comparison" would compare nothing. Regression-tested.
- The reveal lives in a **sibling** directory to the listening files, so Jay can open `listen/` without seeing the
  mapping. Blinding by directory layout, not by honour system alone.
- A post-hoc check fails the run if the two finals differ in sample rate / channels / bit depth, since format
  drift would let Jay identify the provider by ear-independent means.
- Failure deletes the whole package directory: a half-built comparison that still contains a manifest reads as a
  valid one.
- Zero new dependencies; reuses `tts._synthesize`, `tts._run_ffmpeg`, `tts._wav_duration` unchanged.

*Tests* — `tests/test_compare_tts_providers.py`, 17 tests at this point in the story (30 after the later QA and review passes), no network (a dedicated test proves the dry-run path
calls neither synthesis nor ffmpeg, and that dry-run needs no credentials). The suite was **mutation-verified**
rather than merely observed green: seven independent defects were injected into the helper and each was caught by
the intended test — leaking the clone voice id into the manifest, moving `mapping.json` into the listening dir,
removing preflight, removing failure cleanup, letting the stock candidate inherit the env clone flag, dropping
`loudnorm`, and printing the label→candidate pair to stdout. One vacuous assertion (`... or True`) written during
the first pass was found and replaced.

*Verification (measured, not assumed)*
```
uv run pytest tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py \
              tests/test_config.py tests/test_seed_voice_clone.py -q   → 72 passed, 1 skipped
uv run pytest -q                                                       → 2356 passed, 1 skipped, 0 failed (300s)
uv run ruff check scripts/compare_tts_providers.py tests/test_compare_tts_providers.py \
              src/yt_flow/config.py src/yt_flow/pipeline/nodes/tts.py  → All checks passed
uv run python scripts/compare_tts_providers.py --dry-run               → full manifest, no network
uv run python scripts/compare_tts_providers.py                         → live, 2 billed DashScope calls
```
Test-count note: this run adds exactly +17 (2340 collected pre-existing → 2357 with the new file). The 12-4 note's
recorded 2328 does not match the measured pre-existing 2340 — baseline drift, the same pattern 12-3's review
already flagged. The +17 delta is the reliable figure.

*AC6 — comparison phase did not mutate production.* Verified by diff against baseline `878bad6`, not by
inspection: `src/yt_flow/pipeline/nodes/tts.py`, `prompts/scenario/tts_normalize.md`, `src/yt_flow/config.py`,
`src/yt_flow/domain/state.py`, `scripts/seed_voice_clone.py`, `data/voices/`, and `.env.example` are **all
byte-identical**. No graph/state/API/UI file was touched. No secret appears in any manifest, log, test fixture, or
committed file, and no clone voice was created or deleted.

**2026-08-07 (later) — Task 3 executed live under Jay's explicit authorization.**

Operator credentials from `/mnt/work/projects/yt.flow/.env` were loaded into the process (24 variables, values
never printed) and `scripts/compare_tts_providers.py` was run from this worktree. Two billed DashScope calls, one
per candidate. Naver was not called.

Package: `workspace/tts-provider-comparison/20260807T151209Z/` (5.5 MB)
```
listen/A.wav  listen/B.wav  listen/scorecard.md     <- what Jay opens
reveal/mapping.json                                  <- sibling dir, unopened
raw/qwen-stock.wav  raw/qwen-clone.wav               <- provider-named originals
manifest.json
```
Verified (each item checked programmatically, not by inspection): `listen/` contains exactly A/B/scorecard and no
mapping file; `reveal/mapping.json` is a bijection onto both candidates; both finals are readable PCM at
identical 24000 Hz / 1 ch / 16-bit; both carry real content, not silence stubs; manifest text is byte-identical to
the frozen scene with matching SHA-256; manifest contains no key material and the clone voice id is redacted;
`manifest.outputs` (label-keyed) names no candidate and `manifest.candidates` (candidate-keyed) names no label, so
the pairing is not reconstructable from the manifest; no key material anywhere under the package tree; production
files still byte-identical to `878bad6`.

**Defect found and fixed during the live run (blinding leak).** The first live attempt printed
`A.wav <- qwen-stock` as progress output. The operator who generates the package is normally also the listener, so
terminal scrollback defeats the blind test before it starts — and here that output landed in a transcript Jay
reads. That first package was **deleted, not shipped**, the progress line was changed to name no candidate, a
regression test (`test_stdout_never_reveals_the_mapping`) was added and mutation-checked against the old
behaviour, and the package above was regenerated from scratch.

**Disclosure — the pace axis is no longer fully blind.** The discarded run's output paired durations with engine
names (stock ≈ 28.5 s, clone ≈ 22.7 s for this text), and that pairing is now in the transcript. The shipped
package's per-label durations are A = 23.079 s and B = 30.93 s, so the shorter file can be inferred to be the
clone. Regenerating does not repair this: for this frozen text the duration signature is public. Two honest
consequences:
1. Jay should score **timbre, prosody, naturalness, and artifacts by ear** and treat pace/length as separately
   known data rather than a blind signal. Those four axes remain genuinely blind — nothing in the transcript
   identifies which voice sounds like what.
2. The ~34 % speaking-rate gap is itself a **finding, not just a leak**, and it is decision-relevant: at the same
   `atempo=1.2`, the clone reads the same text markedly faster than stock. Across a full ~8-minute video that is a
   multi-minute difference in narration length and changes scene pacing and shot-timing budgets. This deserves a
   line in the verdict regardless of which voice wins on tone.

**BLOCKED — Tasks 4 and 5A require Jay.**

1. *Task 4 (blind verdict)* — a human listening gate by definition; no score has been recorded and none may be
   inferred or fabricated. Open `workspace/tts-provider-comparison/20260807T151209Z/listen/`, play `A.wav` and
   `B.wav`, fill in `scorecard.md`, and only then open `../reveal/mapping.json`. Record exactly one of
   `qwen-stock` / `qwen-clone` / `inconclusive` — `naver` is no longer selectable, and `inconclusive` is a
   legitimate result since AC5 forbids forcing a winner on a tie. Note the pace-axis disclosure above.
2. *Task 5A* — closes once Task 4 records a verdict; its production-unchanged half is already verified.

**2026-08-08 — dev-story re-entry. No new implementation; state re-verified, still blocked at the same gate.**

Re-ran the workflow against the uncommitted 2026-08-07 tree. Nothing was implementable: every remaining unchecked
box (Task 4, and Task 5A's second subtask which is downstream of it) needs Jay's ears, and AC5 forbids inferring a
verdict. `listen/scorecard.md` in the shipped package is still blank — confirmed by reading it, so no verdict was
recorded out-of-band since.

Re-measured this session (not carried over from the previous run's notes):
```
uv run pytest tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py \
              tests/test_config.py tests/test_seed_voice_clone.py -q   → 73 passed, 1 skipped
uv run pytest -q                                                       → 2356 passed, 1 skipped, 0 failed (312s)
uv run ruff check scripts/compare_tts_providers.py tests/test_compare_tts_providers.py \
              src/yt_flow/config.py src/yt_flow/pipeline/nodes/tts.py  → All checks passed
git diff 878bad6 -- <production TTS/normalization/config/state/clone-asset paths>  → empty
```
The focused count is 73, not the 72 recorded on 2026-08-07: `test_stdout_never_reveals_the_mapping` was added
after that line was written. Full-suite total is unchanged at 2356. The blind package
`workspace/tts-provider-comparison/20260807T151209Z/` is intact (listen/A.wav, listen/B.wav, listen/scorecard.md,
reveal/mapping.json, raw/, manifest.json) and was not regenerated — regenerating would cost two more billed
DashScope calls and change nothing about the gate.

Story stays `in-progress`. Step 9 cannot run: it requires every task checkbox `[x]`, and marking Task 4 without a
recorded human verdict would be exactly the "no lying or cheating" failure the workflow forbids.

**2026-08-08 — Tasks 4 and 5A closed. Verdict: `qwen-clone`.**

*Task 4 (AC5) — human gate satisfied.* Jay completed the blind listening and the verdict is transcribed in
`workspace/tts-provider-comparison/20260807T151209Z/listen/scorecard.md`:

| Field | Value |
|---|---|
| Preferred file | `A.wav` |
| Revealed mapping | `A = qwen-clone`, `B = qwen-stock` |
| Verdict | **`qwen-clone`** |
| By / date | Jay / 2026-08-08 |
| Reason | Blind candidate A was clearly preferred — "A 너무 좋은데?!" — and the reveal identifies A as the clone. |

Two honesty notes kept on the record rather than smoothed over:
- **The 1–5 axis table is blank and was left blank.** Jay gave an overall preference, not per-axis scores. AC5 asks
  for the six axes; they were not provided, so they are **not inferred** — a fabricated score table would be worse
  evidence than an admitted gap. The verdict itself (preference + reveal + reason + name + date) is complete and is
  what AC5 gates on.
- **The pace axis was not blind** for this package (disclosed above: the discarded run leaked the
  duration↔engine pairing). The verdict rests on the axes that stayed blind — timbre, prosody, naturalness,
  artifacts — which is where "A 너무 좋은데?!" lands.

The verdict is internally consistent: it was checked against `reveal/mapping.json`, which independently reads
`{"A": "qwen-clone", "B": "qwen-stock"}`.

**Story 5.21's DoD is closed.** The stock-vs-clone listening judgment left open on 2026-07-07 now has an answer:
the clone is preferred. That was the one deliverable of 5.21 still outstanding.

*Task 5A (AC6, AC7, AC10) — closed with no production integration.* The verdict is not `naver`, so AC7 governs and
AC8/AC9 stay unreachable.

- **Production defaults are unchanged, deliberately.** Code default is `qwen_tts_clone_enabled: bool = False`
  (`src/yt_flow/config.py:115`) and the operator `.env` also sets it `false`, so **the pipeline currently renders
  narration with Qwen stock — the candidate Jay did not prefer.** AC7 permits an operator-configuration change
  "only after Jay's explicit decision", and a listening preference is not that authorization. Nothing was flipped.
- **To adopt the clone**, Jay sets `YTFLOW_QWEN_TTS_CLONE_ENABLED=true` in the operator `.env`
  (`YTFLOW_QWEN_TTS_CLONE_VOICE_ID` is already populated from Story 5.24's enrollment). That is a one-line operator
  action requiring no code change, and it is explicitly out of this story's scope.
- **Before flipping, weigh the pace finding.** At the same `atempo=1.2` the clone reads this text ~34 % faster
  (23.1 s vs 30.9 s). Enabling the clone shortens narration across a whole video by minutes and shifts scene
  pacing and shot-timing budgets. That is a real downstream consequence of the preferred voice, not a footnote.
- **No enrollment was touched.** No voice created, deleted, or re-enrolled; `scripts/seed_voice_clone.py`,
  `data/voices/sutak.mp3`, and every `qwen_tts_clone_*` setting are byte-identical to `878bad6`, as is
  `prompts/scenario/tts_normalize.md`.

*Verification at closure (measured at the time of the 2026-08-08 closure):* focused 73 passed / 1 skipped; full
suite 2356 passed / 1 skipped / 0 failed; `ruff check` clean; production-path diff vs `878bad6` empty. Not
committed, per instruction. **Superseded** by the QA E2E pass (+12) and the review pass (+1) — the current
measured figures are in the Senior Developer Review section below: focused 86 passed / 1 skipped, full 2369
passed / 1 skipped.

**What Jay should decide.** The story's premise — "네이버가 한국어 현지화 잘됨" — could not be tested, because
Naver's own usage policy forbids the *only* way this pipeline can consume TTS. The remaining open question is
narrower but still worth the two API calls: **Qwen stock vs. Qwen clone**, which is Story 5.21's DoD that has been
open since 2026-07-07. If Naver's Korean prosody is still wanted, the viable route is CLOVA Dubbing as a separate
manual product evaluation, which is a different story and not a provider swap.

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story created from draft Epic 12.5 requirements; formal user story and testable acceptance criteria were synthesized because the epic contains rationale and DoD but no formal BDD ACs.
- No same-epic previous story artifact exists. Cross-epic TTS, normalization, clone, and alignment predecessors were analyzed instead.
- Official Naver API/product/policy research was checked on 2026-08-03; the persisted-audio usage-policy conflict is an explicit implementation gate.

### File List

New:
- `scripts/compare_tts_providers.py`
- `tests/test_compare_tts_providers.py`
- `data/tts-comparison/scene.txt`

Modified:
- `_bmad-output/implementation-artifacts/12-5-tts-provider-comparison-naver.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/tests/test-summary.md` — QA E2E pass (2026-08-08)

Evidence artifacts (gitignored under `workspace/`, not committed — paths recorded for review):
- `workspace/tts-provider-comparison/20260807T151209Z/listen/{A.wav,B.wav,scorecard.md}` — scorecard now carries Jay's verdict
- `workspace/tts-provider-comparison/20260807T151209Z/reveal/mapping.json`, `raw/{qwen-stock,qwen-clone}.wav`, `manifest.json`
  — note: the shipped package predates the review's blinding fix, so its `raw/` still sits at the package root.
  Packages generated from now on write `reveal/raw/`. The existing package was not regenerated (two more billed
  DashScope calls, and the verdict is already recorded and revealed).

Deliberately unmodified (AC6, verified byte-identical vs `878bad6`):
- `src/yt_flow/pipeline/nodes/tts.py`, `src/yt_flow/config.py`, `src/yt_flow/domain/state.py`,
  `prompts/scenario/tts_normalize.md`, `scripts/seed_voice_clone.py`, `data/voices/sutak.mp3`, `.env.example`

## Senior Developer Review (AI)

**Reviewer:** Jay (automated adversarial review) · **Date:** 2026-08-08 · **Outcome:** Approve (all findings fixed)

Baseline re-verified rather than taken from the notes: production paths byte-identical to `878bad6`, the verdict
in `listen/scorecard.md` matches `reveal/mapping.json` independently, and the frozen scene still hashes to
`8c6b8399…`. Seven findings; all fixed in this pass. No CRITICAL.

### HIGH

1. **The package leaked its own blind mapping through `raw/`.** `raw/qwen-stock.wav` and `raw/qwen-clone.wav` sat
   as a *sibling* of `listen/`, at the same level as the `reveal/` directory the listener is told not to open —
   but with no such warning attached. They are playable, so matching a voice to `A.wav` needs no arithmetic at
   all; and even without playing them, raw duration is exactly the blind file's × 1.2. `reveal/` was doing the
   blinding by convention while an unguarded second reveal sat beside it. This is the same defect class as the
   stdout leak this story already found and fixed mid-run — the fix there closed the terminal channel but left
   the filesystem one open. Raw originals now land in `reveal/raw/`, so every engine-identifying artifact is
   behind the one boundary the scorecard names. New regression test
   `test_nothing_outside_reveal_can_identify_an_engine` pins the whole outside-of-`reveal/` file list and
   forbids playable audio there; mutation-verified by restoring the old path (2 tests fail).
   [`scripts/compare_tts_providers.py:184`]

### MEDIUM

2. **A non-WAV render raised a bare `wave.Error` instead of the readable-error contract.** `_wav_format(final)`
   was evaluated before `tts._wav_duration(final)` inside the same dict literal, so a render that is not a WAV
   surfaced as `wave.Error: file does not start with RIFF id` — bypassing the `ValueError("… is not a readable
   WAV …")` that `tts._wav_duration` exists to provide (`tts.py:57`, added after a live format-drift bug). The
   story's own guardrail is "Do not trust a `.wav` extension." Duration is now measured first. The existing test
   asserted the wrong exception and has been tightened to `ValueError, match="not a readable WAV"`;
   mutation-verified by restoring the old order. [`scripts/compare_tts_providers.py:194`]
3. **Test counts in the story were stale in three places** — Task 2 said 16, Completion Notes said 17, the file
   holds 30. Corrected, with the provenance of each increment.
4. **"Verification at closure" recorded focused 73 / full 2356**, which the later QA changelog entry (85/2368)
   already contradicted; a reader taking the Completion Notes as current got numbers two passes out of date.
   Marked superseded and pointed at the current measurement.
5. **File List omitted `_bmad-output/implementation-artifacts/tests/test-summary.md`**, which git shows modified
   and the Change Log references. Added.
6. **The Change Log's last entry said "Story remains `in-progress` pending Jay's listening verdict"** — it
   post-dates the closure entry and contradicts both it and the `review` status, so the newest line read as the
   current state. Re-dated in place as the earlier same-day entry it actually is.

### LOW

7. `--seed` help text still said "blind A/B/C shuffle"; there have been two candidates since AC1 returned
   `naver-ineligible`. [`scripts/compare_tts_providers.py:130`]

### Accepted gaps (not defects)

- **The six-axis 1–5 table is blank.** Jay gave an overall preference, not per-axis scores. AC5 asks for the
  axes; inferring them would fabricate evidence. The gating element of AC5 — one allowed verdict with preference,
  reveal, reason, name and date — is complete. Left as recorded.
- **The pace axis was not blind** for this package, disclosed in the Completion Notes. The verdict rests on the
  four axes that stayed blind.
- **The shipped package was not regenerated** after finding 1. Regenerating costs two billed DashScope calls and
  cannot un-reveal a mapping Jay has already, correctly, revealed.

### Verification (measured this session, not carried over)

```
uv run pytest tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py \
              tests/test_config.py tests/test_seed_voice_clone.py -q   → 86 passed, 1 skipped
uv run pytest -q                                                       → 2369 passed, 1 skipped (304s)
uv run ruff check scripts/compare_tts_providers.py tests/test_compare_tts_providers.py \
              src/yt_flow/config.py src/yt_flow/pipeline/nodes/tts.py  → All checks passed
git diff 878bad6 -- src/ prompts/ scripts/seed_voice_clone.py data/voices/ .env.example  → empty
```

AC6 still holds after the fixes: every change is confined to `scripts/compare_tts_providers.py` and its test file.

## Change Log

- 2026-08-03: Story created and set to ready-for-dev after exhaustive artifact, code, git, official API, and checklist analysis.
- 2026-08-07: Task 0 resolved AC1 as **`naver-ineligible`** — official Naver usage policy (KO+EN) forbids saving/editing/reusing generated files and mandates real-time-only API use, directing CLOVA Dubbing instead; neither AC1-approved path is available (no NCP account exists; Dubbing is a non-API subscription product). No Naver API call was made and no Naver audio was persisted. AC8/AC9 (Task 5B) are consequently unreachable and closed.
- 2026-08-07: Tasks 1–2 delivered — frozen comparison scene (`data/tts-comparison/scene.txt`, SHA-256 `8c6b8399…`) plus `scripts/compare_tts_providers.py`, a blind Qwen stock-vs-clone listening-package generator, with 16 mutation-verified mocked tests. Full suite 2355 passed / 1 skipped / 0 failed; ruff clean. Production TTS and normalization files verified unchanged.
- 2026-08-07: Task 3 executed live under Jay's explicit authorization — operator `.env` loaded into the process without printing values, two billed DashScope calls, Naver not called. Blind package at `workspace/tts-provider-comparison/20260807T151209Z/`, verified programmatically (layout, mapping bijection, identical 24 kHz/mono/16-bit PCM, frozen-text SHA-256 match, no secrets, manifest does not reveal the pairing). Blinding leak found and fixed mid-run: progress output named the engine behind each label, so that first package was deleted and regenerated after adding `test_stdout_never_reveals_the_mapping`. Suite now 2356 passed / 1 skipped / 0 failed (+17), ruff clean.
- 2026-08-07: Tasks 4/5A remain open — the listening verdict is a human gate and no score has been recorded or inferred. Story stays `in-progress`.
- 2026-08-08: **Story closed to `review`.** Task 4 human gate satisfied — Jay's blind listening verdict is `qwen-clone` (preferred `A.wav`; reveal confirms A = qwen-clone; reason "A 너무 좋은데?!"). Per-axis 1–5 scores were not provided and are explicitly not inferred. Story 5.21's stock-vs-clone listening DoD, open since 2026-07-07, is closed. Task 5A closed with **no production integration**: verdict is not `naver`, so AC7 governs and AC8/AC9 stay unreachable; `qwen_tts_clone_enabled` remains `False` in code and `false` in the operator `.env`, so production still renders with Qwen stock pending a separate explicit Jay authorization (`YTFLOW_QWEN_TTS_CLONE_ENABLED=true`, no code change needed). No voice created/deleted/re-enrolled. Flagged for that decision: the clone reads the frozen text ~34 % faster at the same `atempo=1.2` (23.1 s vs 30.9 s), which shifts scene pacing across a full video. Verified at closure: focused 73 passed/1 skipped, full 2356 passed/1 skipped/0 failed, ruff clean, production paths byte-identical to `878bad6`. Not committed.
- 2026-08-08: `bmad-qa-generate-e2e-tests` run — **+12 tests, no production change.** The shipped 17 tests faked *both* `tts._synthesize` and `tts._run_ffmpeg`, so they asserted the helper's intent (argument strings, file layout) and never its effect. Added E2E coverage through the real seams: the HTTP transport below `_synthesize` (exact DashScope target/headers/bodies per candidate — AC10's first named requirement, previously covered only in `test_tts.py`; per-candidate download; a tripwire that no outbound URL is Naver — AC1), and the real `ffmpeg` binary (unequal raws converge to readable 24 kHz/mono/16-bit PCM with `atempo=1.2` actually applied). Plus the untested failure and integrity paths: ffmpeg non-zero exit, a `.wav` that is not a WAV, preflight leaving no directory, `listen/` holding only neutral files, manifest `outputs`↔`candidates` non-joinability, `--seed` driving the mapping (six seeds), `--out-root` honored with `voice-ab/` untouched (AC4), and byte-for-byte text through whitespace. All 12 mutation-verified 11/11 by injection; the real-ffmpeg test additionally proven to catch an ffmpeg-invalid filter that its mocked counterpart accepts. Focused 85 passed/1 skipped (was 73), full 2368 passed/1 skipped (was 2356), ruff clean, production paths still byte-identical to `878bad6`. Summary: `_bmad-output/implementation-artifacts/tests/test-summary.md`. Also deleted a duplicated two-line comment in `scripts/compare_tts_providers.py` (no behaviour change).
- 2026-08-08 (earlier, before the verdict — this entry was previously misfiled at the end of the log and read as the current state): dev-story re-entry — no code changed. Scorecard confirmed still blank at that point, so Task 4 was unmoved; re-measured 73 passed/1 skipped focused, 2356 passed/1 skipped/0 failed full, ruff clean, production files byte-identical to `878bad6`. Blind package intact and not regenerated. Story was `in-progress` pending Jay's listening verdict — **since closed**, see the closure and review entries above/below.
- 2026-08-08: **Adversarial code review — 7 findings, all auto-fixed, 0 CRITICAL. Status → `done`.** HIGH: the blind package leaked its own mapping through `raw/`, which sat beside `listen/` holding *playable* provider-named originals (and duration = blind file × 1.2) while only `reveal/` carried a do-not-open warning — the same defect class as the stdout leak fixed mid-run, one channel closed and the filesystem one left open. Raw originals now write to `reveal/raw/`; new mutation-verified test `test_nothing_outside_reveal_can_identify_an_engine` pins the outside-`reveal/` file list and forbids playable audio there. MEDIUM: a non-WAV render raised a bare `wave.Error` because `_wav_format` was evaluated before `tts._wav_duration` in the same dict literal, bypassing the readable-`ValueError` contract `tts.py` added after a live format-drift bug (order swapped; the test asserted the wrong exception and was tightened); three stale test counts (16/17 recorded, 30 actual); "Verification at closure" figures two passes out of date (73/2356) and already contradicted by the QA entry; File List missing `tests/test-summary.md`; Change Log's newest line contradicting the closure. LOW: `--seed` help text still said "A/B/C". Accepted gaps kept on the record, not papered over: the six-axis score table stays blank (Jay gave an overall preference; inferring axes would fabricate evidence, and AC5's gating element is complete), the pace axis was not blind, and the shipped package was not regenerated — two more billed calls cannot un-reveal an already-revealed mapping. Measured: focused 86 passed/1 skipped, full 2369 passed/1 skipped, ruff clean, production diff vs `878bad6` empty. All changes confined to `scripts/compare_tts_providers.py` + its test file, so AC6 still holds. Not committed.
