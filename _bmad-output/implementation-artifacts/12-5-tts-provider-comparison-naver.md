---
created: 2026-08-03
story_key: 12-5-tts-provider-comparison-naver
story_id: "12.5"
epic: 12
status: ready-for-dev
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

Status: ready-for-dev

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

- [ ] Task 0: Resolve Naver policy/product feasibility (AC: 1, 2)
  - [ ] Re-check current official API, speaker inventory, auth, request/response, limits, pricing/account quota, and usage policy.
  - [ ] Obtain and record an eligible persisted-audio path; stop safely on `naver-ineligible`.
  - [ ] Record custom-voice availability as documented fact or clearly labeled inference.

- [ ] Task 1: Freeze the representative scene and comparison protocol (AC: 3, 5)
  - [ ] Choose one source scene with the required Korean/number/acronym/pause coverage.
  - [ ] Freeze exact spoken text, hash, provider settings, output format, randomization method, and rubric before synthesis.

- [ ] Task 2: Implement a comparison-only helper and tests (AC: 4, 6, 10)
  - [ ] Reuse the existing Qwen payload, download, ffmpeg speed, and WAV validation patterns without changing `tts_node`.
  - [ ] Add the minimal Naver binary-response client and typed secret-safe configuration required by the helper.
  - [ ] Write mocked tests; no paid/live calls in CI.

- [ ] Task 3: Generate and validate the live A/B/C package (AC: 3, 4, 5)
  - [ ] Preflight both providers and clone ID without logging secrets.
  - [ ] Generate all three raw candidates, apply identical post-processing, and validate each final WAV.
  - [ ] Create neutral filenames, hidden mapping, redacted manifest, and scorecard.

- [ ] Task 4: Obtain Jay's blind listening verdict (AC: 5)
  - [ ] Keep mapping hidden until the scorecard is complete.
  - [ ] Reveal, record one allowed verdict, and explicitly close Story 5.21's pending listening DoD.

- [ ] Task 5A: Close without production integration when verdict is not Naver (AC: 6, 7, 10)
  - [ ] Confirm production TTS and normalization files remain unchanged.
  - [ ] Record the selected Qwen operational mode or the inconclusive next step.

- [ ] Task 5B: Integrate Naver only when verdict is Naver and policy eligible (AC: 8, 9, 10)
  - [ ] Add the minimal provider selector/client seam and secret-safe config.
  - [ ] Preserve all node/state/error/timing/Qwen rollback contracts and add regression coverage.
  - [ ] Run the normalization ablation; change the prompt only with evidence and policy-compliant prompt workflow.
  - [ ] Run focused/full tests, lint, and opt-in live smoke; record results.

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

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story created from draft Epic 12.5 requirements; formal user story and testable acceptance criteria were synthesized because the epic contains rationale and DoD but no formal BDD ACs.
- No same-epic previous story artifact exists. Cross-epic TTS, normalization, clone, and alignment predecessors were analyzed instead.
- Official Naver API/product/policy research was checked on 2026-08-03; the persisted-audio usage-policy conflict is an explicit implementation gate.

### File List

- `_bmad-output/implementation-artifacts/12-5-tts-provider-comparison-naver.md`

## Change Log

- 2026-08-03: Story created and set to ready-for-dev after exhaustive artifact, code, git, official API, and checklist analysis.
