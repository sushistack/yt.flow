## Deferred from: code review of story-1.1/1.2 (2026-07-01)

- Layer-boundary guard test only covers `domain/state.py`. AC4's full AD-1 chain (`pipeline` must not import `db`, `api` must not import `pipeline`) is not actively tested because those layers are currently empty package markers. Extend `tests/domain/test_state_imports.py` (or add a dedicated import-boundary test) once pipeline/api modules contain real code. **(Resolved in stories 1.5–1.7: `test_pipeline_imports_no_db` and `test_api_imports_no_pipeline` added to `tests/domain/test_state_imports.py`.)**
- `pytest-asyncio` is declared as a dev dependency but no `asyncio_mode` is configured in `[tool.pytest.ini_options]`. Under the plugin's STRICT default, async test functions added without `@pytest.mark.asyncio` are collected but not awaited (silent false-pass). Set `asyncio_mode = "auto"` (or mark tests explicitly) when the first async test lands in story 1.4. **(Resolved in story 1.4: `asyncio_mode = "auto"` added to pyproject.toml.)**

## Deferred from: code review of story-1.3 (2026-07-01)

- **`_unchanged` conflates fetch errors with "prompt absent"** [scripts/migrate_prompts.py] — any Langfuse fetch exception is treated as "not present yet", so a transient outage during a live run creates a spurious prompt version instead of skipping. Acceptable for a manual, rerun-safe migration script (idempotent on rerun); marked with a `ponytail:` comment. Narrow to the SDK's not-found exception type if this ever runs unattended.
- **Live migration ACs (AC1/AC2/AC5) not system-verified** — unit tests use fakes only; the end-to-end run against real source templates + self-hosted Langfuse was never executed here because `/mnt/work/projects/yt.pipe/templates/` is absent on this machine. Run manually before trusting those ACs:
  - `uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates`
  - `uv run python -c "from yt_flow.services.prompt_service import compile_prompt; print(compile_prompt('scenario', scp_text='hello')[:80])"`

## Deferred from: code review of story-1.4 (2026-07-01)

- **AD-3 `pending` gate state is unobservable** [src/yt_flow/pipeline/gates.py] — AD-3 requires each gate node to write `{"gate_states": {stage: "pending"}}` on interrupt entry, but LangGraph discards a node's return value when `interrupt()` pauses (the node re-runs from the top on resume). Empirically verified: at pause `gate_states == {}`, so `pending` never appears. Making it observable requires a pre-gate writer (e.g. the stage node emits `pending` for its own gate), which conflicts with AD-3's "gate node is the sole writer of `gate_states`" rule. This is an architecture reconciliation, not a mechanical fix — resolve it in the story that first consumes `gate_states` (services/ DB projection). No consumer exists in the current stub, so there is no functional impact today.
- **`gate_states` has no LangGraph reducer** [src/yt_flow/pipeline/gates.py] — it is a plain dict field. The current topology is strictly sequential so gates never run concurrently, but if future parallel-stage topology or `Send` is introduced, last-write-wins will silently drop a gate decision. Add an `Annotated[dict, merge]` reducer when parallel gates are introduced.

## Deferred from: code review of 1-8-subtitle-node (2026-07-01)

- **Partial alignment silent empty return** [subtitle.py:64] — `word_segments` non-empty but all tokens unaligned silently returns `[]`, bypassing the segment fallback path. Reproduce only with a live WhisperX model; narrow the guard when testable.
- **WhisperX model reloaded on every scene** [subtitle.py:48] — `load_model` is called inside `_align_sync` each time, so model weights reload per scene. Cache on `WhisperXAligner` instance if throughput matters.
- **Error format flat string, not structured dict** [subtitle.py:208] — `PipelineState.error` is a freeform string embedding `stage=subtitle run_id=...`. API/UI layers that need structured error fields must parse it. Revisit if story 2.4 error handling requires a structured contract.
- **Overlapping input word_timings not pre-validated** [subtitle.py:108] — `_word_timings_to_segments` trusts TTS-provided `WordTiming.end_sec` is not overlapping. Add a pre-validate step if the TTS node ever emits overlapping timings.
- **Empty scenes list is a valid no-op without a downstream guard** [subtitle.py:180] — `subtitle_node` succeeds with `scenes=[]`; `video_node` likely assumes ≥1 scene. Add a guard in the video integration story. **(Resolved in story 1.9: `video_node` raises `ValueError("no scenes to render")` on empty scenes.)**
- **run_id path traversal** [subtitle.py:176] — `Path(workspace)/run_id` is unvalidated. Internal CLI state keeps risk low; add sanitisation if `run_id` ever comes from an HTTP boundary.

## Deferred from: code review of story-1.5/1.6/1.7 (2026-07-01)

- **Real stage nodes are not wired into the graph** [src/yt_flow/pipeline/nodes/__init__.py] — `STAGE_NODES` still binds the Story 1.4 stubs for `scenario`/`image`/`tts`; the real `*_node` callables are only exercised by direct unit tests, not through the compiled graph. This is a deliberate, consistent deferral across all three stories (rewiring now would regress the Story 1.4 stub-graph tests). No story-1.5/1.6/1.7 AC requires graph reachability (all ACs are phrased "when X_node runs"). Rewire `STAGE_NODES` to the real nodes in the integration story that owns end-to-end graph execution (candidate: 1.10).
- **`sentence_indices` bounds are unenforceable when the LLM omits `sentences`** [src/yt_flow/pipeline/nodes/scenario.py `_parse_indices`] — the story explicitly permits omitting the optional `sentences` array; when absent, out-of-range indices pass validation. Deriving a bound from `narration` splitting was rejected as a fragile heuristic that could reject valid output. Revisit if the image/subtitle stages start dereferencing indices against narration sentences.
- **Synthesized ComfyUI workflow JSON is unverified against a real export** [data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json] — the real source file was absent at implementation time, so the asset was synthesized from the story's prose. `_load_workflow` proves internal self-consistency (nodes "6"/"7" are CLIPTextEncode with `inputs`) but NOT correctness against a live ComfyUI node pack. **Must be verified/replaced against a real ComfyUI API export before any non-mock (`YTFLOW_COMFYUI_MOCK=false`) run.**

## Deferred from: code review of 1-6b-image-layered-assets (2026-07-01)

- **`image_node` hardcodes `Path("workspace")` instead of `s.workspace_path`** [image.py:204] — pre-existing from Story 1.6; new layered path inherits the same root. Fix together with the Story 1.6 workspace_path cleanup whenever `YTFLOW_WORKSPACE_PATH` support is needed. **(Resolved 2026-07-01: now uses `Path(s.workspace_path)`, consistent with tts/subtitle/video nodes.)**
- **`_await_outputs` returns on first node found, not all requested nodes** [comfyui_client.py:138] — assumes ComfyUI writes all outputs atomically. Spec allows background-only (AC2), so this is compliant. Add per-node wait if a future story requires guaranteeing both layers succeed.
- **`_has_alpha` does not detect tRNS-chunk palette transparency** [image.py:113] — color_type 3 (indexed PNG) with a tRNS chunk would be rejected as opaque. ComfyUI SaveImage outputs RGBA (color_type 6), so this edge case is non-applicable in practice.

## Deferred from: code review of 1-9b-video-effects-kenburns-transitions (2026-07-01)

- **Per-scene vs per-shot motion** [src/yt_flow/pipeline/nodes/video.py `_compose_scene`] — only the first image-bearing shot per scene is rendered; multi-shot scenes silently drop the remaining shots. This departs from AC1's per-shot framing but is inherited from Story 1.9's single-segment-per-scene timing model, which 1.9b was told to reuse ("do not invent a new timing model"). Needs a product decision on whether scenes should emit one segment per shot (splitting `audio_duration` across shots) before implementing.
- **Declared `audio_duration` drives xfade offsets while actual segment length is `-shortest` (real audio)** [video.py `_join_with_xfade` / `_compose_scene`] — if the stored `audio_duration` differs from the real audio file length, xfade offsets and the burned-subtitle timeline drift. Fixing requires deriving durations via `ffprobe` at render time, which is out of 1.9b scope. Revisit when the timing model is reworked.
- **Sub-`XFADE_DURATION` scenes break the crossfade** [video.py `_join_with_xfade`] — a scene shorter than 0.5s yields a negative xfade offset / acrossfade underflow and ffmpeg fails. Not reachable for multi-second TTS narration; a `# ponytail:` comment documents the assumption and the per-pair min-duration-clamp upgrade path if short scenes ever become real.

## Deferred from: code review of stories 2-3/2-4/2-5 (2026-07-01)

- **Gate node cannot persist `pending` into `PipelineState`** [src/yt_flow/pipeline/gates.py] — LangGraph discards a node's return value when `interrupt()` pauses, so `pending` only reaches the runs-table projection (via `services/`), never the checkpoint. Spec-acknowledged (AD-3) and documented in `gates.py`; no functional impact. Same root cause as the story-1.4 deferral above. Resolve as an architecture reconciliation, not a mechanical fix. (Story 2.3)
- **Artifact edit single-scene selector + scenario file path** [src/yt_flow/services/run_service.py `edit_artifact`] — edits one scene via `?scene=N` (default 1) and writes scenario to `scene_{n:03d}.txt`, both deliberate ponytail simplifications diverging from AC-4's single-`body` contract / AD-8's `scenario.txt` path. Upgrade to a scene→text map + canonical path if bulk scenario editing is needed. (Story 2.4)
- **Retry/resume recovery after a server restart** [src/yt_flow/services/run_service.py] — the per-run `_configs` map is in-memory; after a restart `retry_stage`/`resume_run` rebuild a bare config and `astream(None)` on a cold thread has no pending interrupt to resume. Belongs to Story 1.10 (resume-restart-trace-linkage), which owns checkpoint-backed recovery. (Stories 2.3/2.4) **(Resolved in story 1.10: every recovery path falls back to `{"configurable": {"thread_id": run_id}}` and reads the pending interrupt / last checkpoint from the on-disk `AsyncSqliteSaver`, so a cold thread after restart resumes correctly. The original "no pending interrupt on a cold thread" concern was mistaken — the interrupt is persisted in the checkpoint, not in `_configs`.)**
- **`get_stage_artifacts` builds a throwaway graph per request** [src/yt_flow/services/run_service.py `get_stage_artifacts`] — opens a fresh read-only graph + SQLite connection each call instead of reusing the persistent injected `_graph` installed by Story 2.3's `init()`. Low severity, functionally correct (AD-7 upheld); documented with a `ponytail:` comment. Switching requires reworking the 9 tests that mock `build_graph`. Fold into the persistent-graph cleanup when convenient. (Story 2.5) **(Resolved 2026-07-01: now reuses the injected `_graph.aget_state()`; the 9 tests route through one `_mock_graph` helper, so the switch was a single-line test change.)**

## Deferred from: code review of 1-9c-video-character-idle-motion (2026-07-01)

- **Later shots' `character_path` silently dropped + unvalidated** [video.py `_compose_scene` / `_validate_scene_assets`] — only the first image-bearing shot per scene is rendered, so a `character_path` on shots[1:] never appears and is never validated. Same root cause as the 1.9b "per-scene vs per-shot motion" deferral (single-segment-per-scene timing model); 1.9c widens the blast radius because character presence is now a per-shot field. Resolve together with the per-shot timing-model decision.

## Deferred from: code review of stories 3-1/3-2 (2026-07-01)

- **Light-mode `@media` block only swaps 6 of ~17 Zinc tokens** [frontend/src/globals.css:26-36] — `--card-hover`, `--subtle-foreground`, `--primary-foreground`, and all `--status-*` tokens fall through to their dark values under `prefers-color-scheme: light`, so hover rows, stage tokens, and the 18%-alpha status fills render with dark-tuned colors on a white surface. AC2 and DESIGN.md enumerate only the six swaps that are implemented, and dark mode is the primary target, so this is a spec-intent gap rather than an AC violation. Fixing it needs light-mode values that the design spec does not define — resolve with a design decision (candidate: the Story 3.6 accessibility/A-B polish story, or a dedicated light-mode pass). No functional impact on the primary dark surface. (Story 3.1)

## Deferred: prompts/ → Langfuse Prompt Hub 이관 (2026-07-01)

프롬프트는 Langfuse Prompt Hub에서 관리하기로 결정됨 (Story 1-3). 로컬 프롬프트 파일과 시드 스크립트는 Langfuse로 완전 이관 후 제거. 현재 런타임 코드는 Langfuse에서 직접 프롬프트를 가져오도록 되어 있으므로, 로컬 `prompts/` 디렉토리는 시드/레퍼런스 용도로만 존재함.

### 제거 대상

| 경로 | 설명 |
|------|------|
| `prompts/evaluation/judge.md` | LLM-as-judge 평가 프롬프트 → Langfuse `evaluation/judge` |
| `prompts/evaluation/pairwise.md` | Pairwise 비교 프롬프트 → Langfuse `evaluation/pairwise` |
| `prompts/character/angle_selection.md` | 캐릭터 앵글 선택 프롬프트 |
| `prompts/character/generation.md` | 캐릭터 생성 프롬프트 |
| `prompts/character/vision_enrichment.md` | Vision enrichment 프롬프트 |
| `scripts/seed_eval_prompts.py` | evaluation 프롬프트 Langfuse 시드 스크립트 |
| `scripts/migrate_prompts.py` | yt.pipe → Langfuse 마이그레이션 (Story 1-3 완료, 일회성) |

### 이관 절차

1. ~~모든 로컬 프롬프트가 Langfuse Prompt Hub에 최신 버전으로 존재하는지 확인~~ **부분 완료 (2026-07-02)**: `evaluation/judge`, `evaluation/pairwise`, `character-vision-enrichment`, `character-generation`, `character-angle-selection` 5개를 `langfuse.eli.kr` Prompt Hub에 production 라벨 v1으로 시드 완료. `scenario`는 로컬 소스가 없어(yt.pipe 템플릿 필요, 이 머신에 부재) **미완**.
2. 런타임 코드가 Langfuse에서만 프롬프트를 가져오는지 확인 — **미완**: `character_service`는 Langfuse 실패 시 `prompts/` 로컬 파일 폴백이 있음. `prompts/`를 지우려면 이 폴백부터 제거해야 함.
3. `prompts/` 디렉토리 삭제 — 1·2 완료 후.
4. `scripts/seed_eval_prompts.py`, `scripts/migrate_prompts.py` 삭제 — 1·2 완료 후.

**남은 블로커**: (a) `scenario` 프롬프트 소스 확보(yt.pipe 템플릿 접근), (b) `character_service`의 로컬-파일 폴백 제거.

## Deferred from: CI pipeline setup (2026-07-02)

- **첫 full burn-in 수동 실행** — `.github/workflows/test.yml`의 `burn-in-full` job(전체 스위트 10회 반복)을 Actions 탭에서 `workflow_dispatch`로 1회 실행해 flaky 베이스라인을 확인할 것. 이후에는 주간 cron(일요일 02:00 UTC)이 자동 수행하므로 급하지 않음. 실행: `gh workflow run test.yml` 또는 GitHub Actions UI.

## Deferred from: QA E2E test generation, character management journey (2026-07-03)

All bugs found while wiring the SYS-E2E-003 character management journey were fixed in-session rather than deferred (see `_bmad-output/implementation-artifacts/tests/test-summary.md` for the full list, including two — `character_service.py`'s `result.url`/TypedDict crash and `delete_character()` orphaning instead of deleting candidates — that were only caught because the E2E spec runs real generation over real HTTP against a persistent dev db, not pytest's in-memory/mocked path). Nothing remains open from this session.

## Deferred from: code review of eval-ab-trigger-wiring (2026-07-03)

- **`evaluate_ab()` has no idempotency guard** [src/yt_flow/services/eval_service.py `store_evaluation_results`] — it unconditionally overwrites `ab_result` on both runs. Now that `run_service._trigger_ab_eval_if_variant_b` fires on every `status="complete"` write, retrying/restarting an already-evaluated Variant B (both `retry_stage` and `full_restart_run` allow this — `complete` is in `_MUTABLE_STATES`) re-triggers a second, possibly divergent evaluation and duplicate Langfuse score writes. Add a check-before-evaluate (skip if `Run.ab_result` is already populated) if operators are expected to retry stages on evaluated A/B runs.
- **Narrow evaluation-lost race** [src/yt_flow/services/run_service.py `_trigger_ab_eval_if_variant_b`] — if Variant A is mid-retry (status != `"complete"`) at the exact moment Variant B completes, `_validate_pair` raises `ValueError`, which `_run_ab_eval` logs and drops (correct per AD-10 non-fatal) — but nothing ever retries the evaluation afterward, so the pair silently never gets scored. Very narrow (requires manually retrying an already-complete A while B happens to finish), and `evaluate_ab()` has no other production call site to retry from anyway. Revisit alongside the idempotency fix above if this class of gap needs closing.

## Deferred from: B-1/B-3 dev-dependencies review (2026-07-02)

- **`fake_run_ffmpeg`가 출력 경로를 `args[-1]`로 가정** ([tests/stubs/fakes.py](tests/stubs/fakes.py)) — 현재 `video._run_ffmpeg` 호출 규약에서는 출력이 마지막 인자라 스모크 테스트가 통과하지만, ffmpeg 호출 규약이 바뀌면(옵션이 출력 뒤에 붙는 등) 페이크가 엉뚱한 파일에 쓰고도 `(0, "")`을 반환해 조용히 잘못될 수 있음. QA가 SYS-E2E-001용으로 이 seam을 확장할 때 출력 경로를 위치가 아니라 명시적으로 파싱하도록 강화할 것. (테스트 전용, 저위험)
- **langfuse enable 플래그는 import 시점에 1회 바인딩됨** ([src/yt_flow/observability.py](src/yt_flow/observability.py)) — 프로세스 단위 config 플래그로는 정상 동작(런타임 토글 불필요). 테스트 스위트는 이제 `tests/conftest.py`에서 기본 OFF로 설정해 오프라인/무소음이지만, 향후 실제 `@observe` 경로를 테스트로 검증하려면 per-test env override가 아니라 하위 프로세스/재import가 필요함을 유의. (설계상 수용, 참고용)

## Deferred from: 첫 실전 렌더 품질 리뷰 (2026-07-03)

- **DuckDuckGo 검색 이미지 + LoRA img2img 변형 방식 보류** — 이미지-스토리 정합성 개선안으로 제안되었으나 보류. 이유: (a) 검색 이미지 저작권 통제 불가 — 유튜브 수익화 시 실제 리스크, (b) 매 shot 원본 스타일이 제각각이라 영상 전체 스타일 일관성이 현행보다 악화될 가능성, (c) 검색 결과 품질을 파이프라인이 통제 못 함. 축소판(SCP 위키 공식 이미지만 CC BY-SA 준수 하에 IPAdapter 참조로 사용)은 Story 5-5 Phase 2에 반영됨. **재고 조건**: 5-5 Phase 1(프롬프트 컨텍스트 강화) + Phase 2(위키 참조)로도 정합성이 부족하다고 A/B 평가로 확인되면 재검토.

## Deferred from: code review of 5-4-tts-korean-naturalization (2026-07-04)

- **`_step` 함수들의 리스트 요소가 dict가 아니면 `AttributeError`** ([src/yt_flow/pipeline/nodes/scenario_chain.py](src/yt_flow/pipeline/nodes/scenario_chain.py)) — LLM이 `scenes` 리스트에 dict가 아닌 요소(문자열/숫자 등)를 반환하면 `.get()` 호출에서 처리되지 않은 `AttributeError`가 발생하며, 의도된 `ValueError`("malformed output") 계약을 우회함. `tts_normalize_step` 신규 코드뿐 아니라 `research_step`/`structure_step`/`writing_step`/`visual_breakdown_step`/`review_step`/`critic_step` 전부에 동일하게 존재하는 기존 패턴이라 이번 스토리 범위 밖으로 보류. **재고 조건**: 체인 전체에 걸친 방어적 파싱 강화가 필요하다고 판단되면 별도 스토리로 일괄 처리.
- **`str(x or "")` narration coercion이 비문자열 LLM 출력을 조용히 문자열화** ([src/yt_flow/pipeline/nodes/scenario_chain.py:263](src/yt_flow/pipeline/nodes/scenario_chain.py#L263)) — `tts_normalize_step`이 정규화된 narration을 `str(normalized_scene.get("narration") or "")`로 강제 변환하는데, 이는 `writing_step`이 이미 쓰는 것과 동일한 패턴이며 문장 수 폴백이 빈 값/None의 실질적 사례는 대부분 걸러냄. 이론상 리스트/딕셔너리의 `str()` 표현이 우연히 원본과 같은 문장 수를 가지면 통과할 수 있으나 실측 가능성은 낮음. **재고 조건**: 실제 라이브 run에서 이런 오염된 narration이 관측되면 타입 검증 추가.
- **스토리 문서 자체의 `--source prompts/scenario` 마이그레이션 명령이 잘못된 프롬프트 이름을 생성** ([scripts/migrate_prompts.py](scripts/migrate_prompts.py), [docs/PROMPT_POLICY.md](docs/PROMPT_POLICY.md)) — `SOURCE_TO_NAME`의 키가 소스 루트를 `prompts/`로 가정하는데 문서/스토리는 `prompts/scenario`를 소스로 지정해 `scenario/` 접두사가 벗겨진 이름(`research`, `tts_normalize` 등)이 생성됨. 5.4 구현자가 이미 사전-존재 이슈로 확인·기록(`research.md`/`structure.md`도 동일하게 영향받음, 5.4가 도입한 문제 아님). `--source prompts`로 우회해 정상 이름으로 candidate 라벨 시딩 완료. **재고 조건**: 다음에 prompt 마이그레이션 문서/스크립트를 만질 때 `SOURCE_TO_NAME` 키 규칙과 문서의 `--source` 예시를 함께 고친다.
- **(정보용, 코드 수정 대상 아님) candidate 라벨 시딩 시 무관한 프롬프트 5개에 부수효과** — 위 워크어라운드(`--source prompts`)가 `character/angle_selection`, `character/generation`, `character/vision_enrichment`, `evaluation/judge`, `evaluation/pairwise`에 이전에 없던 `candidate` 라벨 버전을 생성함(내용은 현재 리포 소스와 동일해 기능적으로는 no-op). `production` 라벨은 건드리지 않았음. Langfuse(`langfuse.eli.kr`)에서 필요 시 정리 여부는 사용자 판단.
