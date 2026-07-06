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

## Deferred from: 5-2 layered-assets-activation 라이브 검증 (2026-07-04)

5-2 완료 후 실제 API 게이트 흐름으로 SCP-096 run(`bed3b329-b7d1-4cf3-b37f-f40d086765b5`)을 처음부터 실행해 image 스테이지를 검증. 스토리의 "구조/포맷" 기준(AC1/AC3/AC4)은 **완전 충족**: 72개 샷 전부 `*_background.png`(color type 2, opaque) + `*_character.png`(color type 6, RGBA) 생성, `_has_alpha()` 통과율 100%, 배경 제거 실패로 인한 background-only 폴백은 이번 run에서 0건.

다만 **컷아웃 품질**은 별도 축이며 이번 5-2 스토리 범위 밖(Dev Notes에 "품질 나쁘면 문서화만 하고 범위 확장 금지"로 명시)이라 여기 기록만 하고 넘어감:

- **프레이밍 편중** — 5-2 세션의 단발 검증 렌더(포즈/구도를 지시하지 않은 제네릭 프롬프트 "masterpiece, best quality")에서 rembg가 얼굴/상반신 클로즈업만 남기고 전신을 못 살린 사례 관찰. 원인은 rembg 자체가 아니라 base 이미지의 구도 — 프롬프트가 "full body"/"wide shot" 등 구도를 명시하지 않으면 캐릭터 클로즈업으로 쏠릴 수 있음. **이 항목은 Story 5.5 AC4(shot composition/camera framing을 프롬프트에 명시)로 이미 커버됨 — 5.5 구현 시 참고 근거로만 사용, 별도 스토리 불필요.**
- **알파 경계/세그멘테이션 정확도 미검증** — 이번 라이브 검증은 "RGBA 포맷인가"(바이트 레벨)만 확인했고, 컷아웃 경계에 배경색 halo나 톱니 아티팩트가 있는지, 배경 제거가 캐릭터 실루엣을 정확히 따라가는지는 픽셀 단위로 확인하지 않았다. `data/workflows/README-layered-assets.md`가 이미 후보로 언급한 `1038lab/ComfyUI-RMBG`(BiRefNet/SAM 계열, 더 정확하지만 무거움) 및 `john-mnz/ComfyUI-Inspyrenet-Rembg` 대비 현재 채택된 rembg(u2net, 가장 가벼움)의 실측 품질 비교가 없음. **→ Story 5.6(레이어드 캐릭터 컷아웃 품질)로 승격**, epics.md에 항목 추가 완료. 사람 눈 A/B 비교(현재 rembg vs 대안 노드 1개 이상, 동일 SCP/동일 시드)로 교체 여부 결정 필요.

## Deferred from: 5-3 motion-intensity 라이브 QA (2026-07-04)

5.3 완료 후 5-2 라이브 검증 run(`bed3b329`)의 실제 layered asset(배경+캐릭터)으로 `video_node`를 재렌더링해 AC3/AC4/AC7을 라이브로 확인하는 과정에서 관찰:

- **배경 확대 시 고정 크기 캐릭터 오버레이가 상대적으로 커 보이는 현상** — 배경은 Ken Burns로 최대 1.15까지 확대되지만 캐릭터 오버레이(`_overlay_filter()`)는 크기 애니메이션이 없는 고정 크기 sway/bob만 적용됨(Story 1.9c부터의 기존 설계). 결과적으로 씬이 진행될수록 캐릭터가 배경 대비 점점 "가까워 보이는" 시차(parallax) 유사 효과가 생김. 버그는 아니고 배경 zoompan과 캐릭터 오버레이가 의도적으로 독립적이라 생기는 자연스러운 결과(5.3 AC7 스펙 그대로)이지만, 5.3에서 `ZOOM_IN_MAX`를 1.08→1.15로 올리면서 이 효과가 이전보다는 더 눈에 띌 수 있음. 픽셀 단위로 "어색해 보이는" 정도를 판단하려면 사람 눈 리뷰가 필요하며, 현재는 어떤 스토리의 스코프에도 안 들어가 있음(5.3은 배경 모션 강도만, 5.6은 컷아웃 세그멘테이션 품질만, 5.5는 프롬프트/구도만 다룸). **재고 조건**: 5.2+5.3이 합쳐진 실제 렌더를 사람이 리뷰했을 때 이 시차 효과가 거슬린다는 피드백이 나오면, 캐릭터 오버레이에 배경과 연동된 미세 스케일 애니메이션을 추가하는 별도 스토리로 검토(현재는 추측성 개선이라 스토리화 안 함).

## Deferred from: code review of 5-4-tts-korean-naturalization (2026-07-04)

- **`_step` 함수들의 리스트 요소가 dict가 아니면 `AttributeError`** ([src/yt_flow/pipeline/nodes/scenario_chain.py](src/yt_flow/pipeline/nodes/scenario_chain.py)) — LLM이 `scenes` 리스트에 dict가 아닌 요소(문자열/숫자 등)를 반환하면 `.get()` 호출에서 처리되지 않은 `AttributeError`가 발생하며, 의도된 `ValueError`("malformed output") 계약을 우회함. `tts_normalize_step` 신규 코드뿐 아니라 `research_step`/`structure_step`/`writing_step`/`visual_breakdown_step`/`review_step`/`critic_step` 전부에 동일하게 존재하는 기존 패턴이라 이번 스토리 범위 밖으로 보류. **재고 조건**: 체인 전체에 걸친 방어적 파싱 강화가 필요하다고 판단되면 별도 스토리로 일괄 처리.
- **`str(x or "")` narration coercion이 비문자열 LLM 출력을 조용히 문자열화** ([src/yt_flow/pipeline/nodes/scenario_chain.py:263](src/yt_flow/pipeline/nodes/scenario_chain.py#L263)) — `tts_normalize_step`이 정규화된 narration을 `str(normalized_scene.get("narration") or "")`로 강제 변환하는데, 이는 `writing_step`이 이미 쓰는 것과 동일한 패턴이며 문장 수 폴백이 빈 값/None의 실질적 사례는 대부분 걸러냄. 이론상 리스트/딕셔너리의 `str()` 표현이 우연히 원본과 같은 문장 수를 가지면 통과할 수 있으나 실측 가능성은 낮음. **재고 조건**: 실제 라이브 run에서 이런 오염된 narration이 관측되면 타입 검증 추가.
- **스토리 문서 자체의 `--source prompts/scenario` 마이그레이션 명령이 잘못된 프롬프트 이름을 생성** ([scripts/migrate_prompts.py](scripts/migrate_prompts.py), [docs/PROMPT_POLICY.md](docs/PROMPT_POLICY.md)) — `SOURCE_TO_NAME`의 키가 소스 루트를 `prompts/`로 가정하는데 문서/스토리는 `prompts/scenario`를 소스로 지정해 `scenario/` 접두사가 벗겨진 이름(`research`, `tts_normalize` 등)이 생성됨. 5.4 구현자가 이미 사전-존재 이슈로 확인·기록(`research.md`/`structure.md`도 동일하게 영향받음, 5.4가 도입한 문제 아님). `--source prompts`로 우회해 정상 이름으로 candidate 라벨 시딩 완료. **재고 조건**: 다음에 prompt 마이그레이션 문서/스크립트를 만질 때 `SOURCE_TO_NAME` 키 규칙과 문서의 `--source` 예시를 함께 고친다.
- **(정보용, 코드 수정 대상 아님) candidate 라벨 시딩 시 무관한 프롬프트 5개에 부수효과** — 위 워크어라운드(`--source prompts`)가 `character/angle_selection`, `character/generation`, `character/vision_enrichment`, `evaluation/judge`, `evaluation/pairwise`에 이전에 없던 `candidate` 라벨 버전을 생성함(내용은 현재 리포 소스와 동일해 기능적으로는 no-op). `production` 라벨은 건드리지 않았음. Langfuse(`langfuse.eli.kr`)에서 필요 시 정리 여부는 사용자 판단.

## Deferred from: 5-5 visual-story-alignment 라이브 A/B 시도 (2026-07-04)

- **`scenario/tts_normalize`에 `production` 라벨이 전혀 없음** — Story 5.4가 이 프롬프트를 `candidate` 라벨로만 시딩했고 (위 5.4 리뷰 항목 참고) `production`으로 승격하는 단계가 실행된 적이 없음. 그 결과 `prompt_variant=None`(Variant A/베이스라인) 경로조차 `scenario_node`가 `tts_normalize_step`에서 `Langfuse prompt fetch failed: name='scenario/tts_normalize' label=production`으로 즉시 실패함 — Story 5.4는 오프라인 카세트 테스트만 통과했고 실제 API로 엔드투엔드 라이브 검증된 적이 없었다는 뜻. 5.5의 Phase 1 A/B 검증(AC13/15)을 라이브로 실행하려다 발견함; 5.5의 범위가 아니라(5.5는 `scenario/research`/`scenario/visual_breakdown`만 변경) 여기 기록만 하고 라이브 A/B는 보류함. **재고 조건**: `scenario/tts_normalize` candidate v1을 PROMPT_POLICY 변경 절차(에러 없는 A/B 실행 확인 후 Langfuse UI에서 `production` 라벨 이동)에 따라 승격하는 별도 픽스가 선행되어야 5.5든 다른 스토리든 실 API 라이브 런이 가능함.
  - **2026-07-04 코드 리뷰 추가 메모 — 심각도 상향**: 이 gap은 A/B 검증에만 국한되지 않고 **variant 무관 모든 실 API 라이브 run**을 즉시 실패시킨다(오프라인 카세트 테스트는 전부 통과하므로 CI로는 감지 안 됨). `sprint-status.yaml`은 여전히 `5-4-tts-korean-naturalization: done`으로 아무 표시 없이 남아 있음. 다음 스토리 착수 전 우선순위로 승격 권장.
  - **✅ 2026-07-04 해결**: `Langfuse.update_prompt(name="scenario/tts_normalize", version=1, new_labels=["production"])` 실행 완료. SDK는 라벨을 교체가 아니라 추가하는 방식이라 v1은 이제 `["production", "candidate", "latest"]`를 모두 가짐(버전이 이거 하나뿐이라 문제 없음) — `get_prompt("scenario/tts_normalize", label="production")`로 재조회해 정상 반환 확인. Variant A/None의 `tts_normalize_step` 즉시 실패는 해소됨. **남은 일**: AC13/14/15의 실제 라이브 A/B run + Epic 4 평가는 아직 미실행 — PROMPT_POLICY 변경 절차상 정식 A/B 비교 없이 production을 승격한 것이므로, 골든셋 회귀(Story 6.2)가 아직 없다면 다음 라이브 run에서 결과를 눈으로 확인 권장.

## Deferred from: code review of 5-5-visual-story-alignment (2026-07-04)

- **candidate 라벨 오시딩 정리가 라벨만 제거하고 버전은 남김** — 5.5 구현 중 `migrate_prompts.py --source prompts/scenario`가 잘못된 이름(`research`, `visual_breakdown` 등)으로 candidate 버전 4개를 만든 뒤 `client.update_prompt(name=..., version=1, new_labels=[])`로 라벨만 지웠음. 버전 자체는 Langfuse(`langfuse.eli.kr`)에 orphan 상태로 남아있어 프롬프트 히스토리가 오염됨. 코드 변경이 아니라 Langfuse 관리 콘솔에서의 수동 정리 필요. **재고 조건**: Langfuse UI 정리 작업 시 일괄 삭제.
- **`scripts/migrate_prompts.py`의 `derive_name()` 버그가 3번째로 재발** — `--source`에 상대적으로 이름을 도출하는 동일 버그가 5.4 리뷰에서 이미 기록됐음에도(위 항목 참고), 5.5 구현 중에도 재확인 없이 같은 명령을 실행해 다시 재현됨(사후에 `--source prompts`로 우회). `docs/PROMPT_POLICY.md` 자체의 예시 명령도 깨진 형태를 그대로 담고 있어 다음 스토리도 같은 실수를 반복할 가능성이 높음. **재고 조건**: `SOURCE_TO_NAME`/`derive_name()` 로직과 `docs/PROMPT_POLICY.md`의 예시 명령을 함께 고치는 별도 픽스.
- **라이브 검증용 로컬 프로세스가 세션 종료 후에도 방치됨** — ComfyUI(`$HOME/workspaces/ComfyUI`)와 yt.flow API 서버가 재기동 편의를 위해 `/tmp/comfyui_boot.log`, `/tmp/ytflow_boot2.log`로 로그를 남긴 채 백그라운드에 계속 실행 중으로 남음. 코드 이슈는 아니지만 공유 개발 환경에서의 운영 위생 문제. **재고 조건**: 다음 작업자가 필요 없으면 `pkill -f "main.py --preview-method auto"` / `pkill -f "uvicorn yt_flow.api.main:app"`로 정리.

## Deferred from: code review of 5-6-character-cutout-quality (2026-07-04)

- **InSPyReNet 첫 실행 체크포인트 다운로드가 오해성 timeout으로 표면화될 수 있음** — `ComfyUI-Inspyrenet-Rembg`의 첫 `Remover()` 호출이 `~/.transparent-background`로 체크포인트를 내려받는데, 이것이 `comfyui_client.py`의 폴링 예산(`max_polls=180 × poll_interval=1.0s`)을 초과하면 실제 원인(모델 다운로드 지연/오프라인)이 아니라 `ComfyUIError("... produced no image ... within timeout")`으로 뜸. 현재 `README-layered-assets.md`에 "warm this once" 지침으로 문서화돼 있어 운영상 회피 가능. 코드 레벨에서 다운로드-지연과 노드-무출력을 구분하는 처리는 후속. **재고 조건**: 오프라인/콜드 환경에서 첫 실행 타임아웃이 반복 발생하면 폴링 로직에 진행-중 신호 구분 추가.

## Deferred from: code review of 5-9-transition-audio-continuity (2026-07-04)

- **`amix duration=longest` assumes each segment's embedded audio duration exactly matches its declared `dur` float** — `_join_with_xfade()`'s duration-parity guarantee (video and audio streams landing on the same combined length) relies on the segment file's actual audio track length matching the `dur` value used for the video xfade offset math. If a segment's audio track is even slightly shorter/longer than `dur` (encoder padding, TTS/video length mismatch), the amix output's length (governed by `duration=longest`) could diverge from the video stream's length with no explicit trim/pad or `-shortest` fallback. This assumption predates Story 5.9 — Story 5.1's duration accounting already relied on segment audio/video durations matching — so it's not newly introduced by this diff, but the adelay/amix mechanism doesn't add any new safety net either. **재고 조건**: if a real run ever shows audio/video duration drift beyond the expected AAC frame-quantization gap (~40ms), add an explicit duration assertion or `-shortest`/pad step per segment.
- **No automated test measures actual audio sample levels/clipping during the overlap window** — Story 5.9's Completion Notes explicitly accept that two full-amplitude narration tracks summed via `amix=normalize=0` could clip during the ~0.5s overlap window (no gain compensation). The only verification method used is manual RMS waveform inspection during live validation (AC5), not an automated regression test. **재고 조건**: if clipping is ever audibly reported from a real render, add either a peak-level test fixture or a gentle `alimiter`/gain-duck on the overlap window specifically (not a broad fade, which would reintroduce the volume-dip bug this story fixes).
- **`amix=inputs=n` scaling with large scene counts is untested beyond n=2/3** — the new join constructs one `amix` node with all `n` segment audio streams as simultaneous inputs (replacing the previous pairwise sequential `acrossfade` chain). No test exercises a realistic full-length video's scene count (e.g. 10-20+ scenes). **재고 조건**: if a real long-form video's join fails or produces unexpected results, add a test with a higher segment count.

## Deferred from: code review of 7-1-sound-design (2026-07-05)

- **✅ 2026-07-05 해결**: `sound_design_enabled` 기본값 `True`에 CC0 에셋이 없던 문제 — Jay 요청으로 Freesound에서 `license:"Creative Commons 0"` 필터로 12개 파일 전부 소싱·트림·커밋 완료(`data/audio/README.md`에 출처/저작자/라이선스 기록). `_compose_scene`을 실제 ffmpeg로 4개 무드 전부 재검증(정확한 길이로 완료, 행 없음). **남은 일**: 파일 선택이 제목/태그 메타데이터 기준이라 아직 아무도 직접 들어보지 않음 — 사람 귀로 듣는 Live Validation(스토리 7.1 태스크)이 여전히 필요.
- **`amix` 전에 bgm/ambient/stinger/narration 간 `aformat`/`aresample` 정규화가 없음** — 서로 다른 소스에서 가져올 CC0 파일들의 샘플레이트/채널 레이아웃이 다를 경우 `amix`가 실패하거나 예기치 않게 동작할 수 있음. 현재는 각 파일이 실제로 존재하지 않아 검증 불가능하고, 이미 블록된 Live Validation "by ear tuning" 태스크의 일부로 다뤄질 사안. **재고 조건**: AC6 에셋이 실제로 소싱되면 Live Validation 단계에서 실제 인코딩을 확인하고 필요 시 `aformat`/`aresample` 추가.
- **최종 `amix ... normalize=0`가 리미터 없이 클리핑 위험을 안고 있음** — narration을 감쇠 없이 유지하려는 의도(`normalize=0`)는 맞지만, ducking이 완전히 걸리기 전(release=300ms) 구간이나 무음 구간에서 bgm+ambient+stinger 합산 레벨이 0dBFS를 넘을 수 있음. 실제 CC0 에셋의 실측 레벨이 없어 지금 판단 불가하며, 같은 by-ear 튜닝 태스크에 포함됨. **재고 조건**: 실 에셋으로 Live Validation 시 클리핑이 들리면 `alimiter`를 후단에 추가하거나 볼륨 상수 재조정.

## Deferred from: code review of story-5-11-segmentation-failure-shot-fallback (2026-07-05)

- **Broad `ComfyUIError` catch treats a transient/hung-ComfyUI timeout the same as a segmentation-specific failure** [src/yt_flow/pipeline/nodes/image.py:243-269] — `image_node`'s per-shot fallback catches the generic `ComfyUIError` type with no discrimination on cause. A total/hung ComfyUI outage (not just a segmentation crash) now makes a failing shot poll up to `max_polls × poll_interval` (180s) for the layered attempt, then retry and poll again for the fallback before the run finally fails — nearly doubling failure latency for an outage that has nothing to do with segmentation. This is a pre-existing, explicitly-accepted design tradeoff per this story's own Dev Notes ("no need to distinguish sub-cases in code," "document it but do not try to optimize it away" re: the two sequential submissions). **재고 조건**: if a real total-outage run's failure latency becomes an operational problem, add a way to distinguish transport/timeout `ComfyUIError`s from segmentation/alpha-validation ones (e.g. a subclass or error code) so only the latter triggers the flat fallback.
- **Opaque-character sub-case discards an already-successfully-rendered background and pays for a redundant full render** [src/yt_flow/pipeline/nodes/image.py:177-215] — in `_generate_layered_shot`, the background PNG is written to disk *before* the opaque-character alpha check raises `ComfyUIError`. The caller's fallback then does a brand-new ComfyUI submission and overwrites that same background path with an unrelated re-render, discarding a background that was actually fine — wasted GPU compute specific to this one sub-case (a true segmentation-node crash has no usable background to preserve, so it doesn't waste anything extra). Fixing this needs to special-case "background succeeded, only character failed alpha validation" to reuse the existing background — which reintroduces the sub-case distinction this story's Dev Notes explicitly said was unnecessary. **재고 조건**: if the opaque-character sub-case turns out to be common enough that the redundant render cost matters (GPU time/cost budget), special-case it to keep the already-rendered background and only regenerate a flat image if no background exists.

## Deferred from: code review of 5-10-entity-reference-pipeline-repair (2026-07-05)

- **SCP Wiki "first image in `#page-content`" heuristic may grab a decorative/unrelated image** [src/yt_flow/services/image_search.py — `ScpWikiImageFetch.fetch`] — the regex takes whichever `local--files/` image appears first in the article body; live-validated against 6 real pages (scp-096, scp-3007, scp-173, scp-682, scp-1471, scp-2521) but not exhaustively robust against every wiki page layout (rating widgets, licensing icons, related-SCP thumbnails can all precede the actual portrait on some pages). Revisit if a live run surfaces a wrong-image regression.
- **Wiki path always returns exactly 1 reference candidate vs. DDG's N** [src/yt_flow/services/character_service.py — `_do_search_and_download`] — now that wiki is the primary source for most SCPs, the Character Management UI's multi-candidate manual-selection flow effectively never has more than one option to choose from on the wiki-hit path. Needs a product decision on whether the wiki path should also surface multiple candidates (e.g. other images on the same page) before it's worth implementing.
- **`comfyui_client._upload`'s `resp.json()` isn't wrapped against malformed-JSON responses** [src/yt_flow/services/comfyui_client.py:94,111] — matches the identical, pre-existing gap in `_submit`'s own `resp.json()` call, untouched by this diff. Fix both together in a single consistency pass rather than one-off patching the new function.
- **No explicit size cap when reading `ref_image_path` bytes before ComfyUI upload** [src/yt_flow/services/character_image_provider.py:98] — not a new risk: the file is already bounded by `_download_reference_image`'s existing 10 MB download cap before it ever reaches disk. Revisit only if a new caller can supply `ref_image_path` from an unbounded source.
- **`ScpWikiImageFetch`'s slug derivation diverges from `_sanitize_scp_id`'s filesystem normalization on non-hyphenated `scp_id` input** [src/yt_flow/services/image_search.py:86] — e.g. `"SCP 096"` (space) would `quote()` into a URL guaranteed to 404. Pre-existing: `character_service._validate_create` never enforced a canonical `scp_id` format. Degrades safely to the existing DDG fallback on the 404 miss, so no crash risk — but the wiki attempt is silently wasted for any character created with a non-canonical ID.

## Deferred from: code review of story-7.2 (2026-07-06)

- **Pre-existing duplication in `_compose_scene`'s no-sound-design/no-character branch** [src/yt_flow/pipeline/nodes/video.py] — `video_chain` (built once per call) and the `else` branch's `vf` recompute the identical `{zp_chain}{post_frag},subtitles=...` expression. Predates Story 7.2 (inherited from the 7.1 `-vf`/`-filter_complex` mutual-exclusivity split); 7.2 only threaded `post_frag` through both copies consistently rather than introducing the duplication. Worth collapsing into one computed string if `_compose_scene` is revisited.

## Deferred from: code review of story-7.3 (2026-07-06)

- **`_character_spec` does not runtime-clamp the derived character zoom to `CHAR_MAX_ZOOM`** [src/yt_flow/pipeline/nodes/video.py:169] — the off-frame box invariant (`CHAR_MAX_W/H`) is sized assuming `bg_spec.end_zoom <= ZOOM_IN_MAX`. Today `select_effect` guarantees that ceiling, so it is safe. If a future direction/config ever raises the background zoom above `ZOOM_IN_MAX` without updating the box math, the amplified character zoom would exceed `CHAR_MAX_ZOOM` and silently overflow the motion-safe frame with no runtime guard. Add an `assert`/clamp in `_character_spec` if the background zoom ceiling is ever made variable. [sources: blind B7 + edge E4]

## Deferred from: code review of story-7.4 (2026-07-06)

- ~~**`preceded_by_card = chapter_cards_enabled and i > 0` assumes every scene but the first is preceded by a card whenever `chapter_cards_enabled` is true**~~ **(Resolved 2026-07-06: `preceded_by_card` removed entirely as part of the AC5 amendment — cards no longer get a fadeblack exemption, so this assumption no longer exists in the code.)**

## Deferred from: code review of subtitle word/segment fallback fix (2026-07-06)

- **Partial-usable `word_segments` still drops words instead of falling back** [src/yt_flow/pipeline/nodes/subtitle.py `_words_or_segments`] — this fix (see spec-subtitle-word-segment-fallback.md) only closes the fully-empty case (no word has usable `start`/`end`). If even one word lacks `start`/`end` while others have it, `usable` is non-empty/truthy so the function returns the partial word list, silently dropping the unusable words rather than falling back to the presumably-complete `segments`. Pre-existing behavior (identical filter logic existed before this fix), not a regression, but still untested and still live. Reproduce only with a live WhisperX model; narrow further if a real run surfaces missing words mid-cue.

## Anticipated next bottlenecks — 의도적으로 아직 스토리화하지 않음 (2026-07-07, E2E 베이스라인 스토리 10건 완성 시점)

베이스라인發 10개 스토리(5-14~5-18, 3-8, 8-1~8-4)가 완성돼도 아래는 남을 것으로 예측된 리스크. **재고 조건: 8-3의 DoD(SCP-049 재렌더 A/B, iteration 1) 결과에서 실제 결함으로 확인되면 그때 스토리화** — 예측만으로 미리 만드는 건 YAGNI.

1. **콜라주 룩 (확률 최고)**: 스튜디오 조명에서 생성된 RGBA 카드를 씬 조명의 배경에 합성하면 "배경 위에 스티커 붙인 느낌"이 날 수 있음. 현재 유일한 통일 장치는 7-2 전체 프레임 그레이드. 업계 해법 후보(그때 가서 선택): 카드 가장자리 림 라이트/섀도 합성, 배경-카드 공동 컬러 매칭, mood별 카드 톤 프리셋.
2. **배경 프롬프트 순응도**: SDXL이 배경 전용 프롬프트를 따르는 정도는 Epic 8이 보장 못 함 (베이스라인 S00202: "격리실 관찰창" → 추상 건축물). 개체 분리로 프롬프트가 단순해져 개선 여지는 있으나 미검증. 해법 후보: visual_breakdown 배경 프롬프트 최적화(6-2 골든셋 A/B), 배경 특화 LoRA.
3. **연기의 한계**: "시신이 일어난다" 같은 서사 순간은 카드 포즈(서기/앉기/특수 3장 캡)로 표현 불가 — 정적 다큐 문법으론 수용 가능하나 "3~5배 역동적" 원목표 대비 부분 달성. 해법 후보(비용 큼): i2v(이미지→비디오) 모션 클립, 컷 리듬 고속화.
4. **귀 판정 미검증 축**: TTS 억양, BGM 믹스 밸런스 — judge가 텍스트/측정 프록시로만 채점 중. Jay 시청 판정과의 캘리브레이션이 iteration 1의 병행 과제.
