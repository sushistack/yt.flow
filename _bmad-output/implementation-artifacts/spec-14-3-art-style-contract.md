---
title: 'Story 14.3: 화풍 계약 — 표류를 픽셀에 귀속시키고, recompose에 귀속 경로를 만든다'
type: 'feature'
created: '2026-08-29'
baseline_revision: '2bc7534'
final_revision: 'c75b123'
status: 'done' # draft | ready-for-dev | in-progress | in-review | done | blocked
review_loop_iteration: 1
followup_review_recommended: true
context: []
warnings: [multiple-goals, oversized]
---

> ⚠️ **2026-08-30 전제 정정**: 이 문서의 "GPU 부재" 근거는 **거짓**이다 — `nvidia-smi`로 진단했으나 이 박스는 AMD(gfx1100, 24GB, ROCm)이고 GPU는 정상이다. ComfyUI가 안 떠 있었을 뿐이다. 전문: `GPU-PREMISE-CORRECTION-2026-08-30.md`


<intent-contract>

## Intent

**Problem:** Jay 판정 ⑦ "화풍 유지 안 됨"에 대해 에픽이 적어둔 처방은 **"팔레트·조명·렌더 스타일을 닫힌 어휘로 제약"** 이다. 그런데 run `4b35c0ed` 43샷의 `image_prompt` 전수 스캔 결과 **네온/이질화풍 어휘는 프롬프트에 없다** — 표류 라벨 7건 중 팔레트 어휘 보유는 2건이고 비-표류 36건 중에도 2건이라 판별력이 0이다(둘 다 `LED`, 조명 기구 명사). **지울 단어가 없으므로 어휘 제약으로는 못 고친다.** 그리고 두 번째 층(recompose 배치·접지·척도, 14.2 인계 3건)은 배치 지시가 **이미 프롬프트에 있는데도** 발생한다 — `shot_recompose.py:61-80`이 *"Feet firmly on the ground with a contact shadow, ... rendered in the same illustration style as the background"* 를 매 패스 보낸다. 즉 두 층 다 **텍스트에 없는 원인**이고, 정작 recompose는 **사이드카도 프로비넌스도 트레이스 필드도 쓰지 않아**(`recompose_service.py:318-332`가 PNG만 쓴다) 어떤 결함도 자기 지시에 귀속시킬 수 없다.

**Approach:** 이 스토리는 **화풍을 고치지 않는다 — 고칠 수 있게 만든다.** 셋을 한다. ① 표류를 **픽셀에서** 재현 가능하게 측정하고(GPU 0, VLM 0, 순수 numpy), 그 측정이 **무엇을 못 보는지**까지 사전등록한다. ② 43샷 컨택트 시트로 **Jay가 라벨을 확정**한다 — 이 프로젝트에서 Claude 단독 화풍 라벨은 아직 한 번도 사람 확인을 받지 않았고 14.2에서 같은 종류가 두 번 뒤집혔다. ③ recompose에 **귀속 경로**(사이드카 프로비넌스 + 런 트레이스 필드)를 만들고, 플레이트·카드 워크플로가 선언상 하나의 화풍인지를 **테스트로 계약화**한다. 게이트도, 프롬프트 편집도, LoRA 가중치 변경도 이 런에서는 하지 않는다 — 이 박스에 **GPU가 없어**(`nvidia-smi` 실패, ComfyUI 미기동) 페어 렌더가 불가능하고, 렌더 없이 화풍 기본값을 바꾼 전례가 이 프로젝트에 없다.

## Boundaries & Constraints

**Always:**
- 측정치는 **표본 밴드와 재산출 스크립트를 함께** 남긴다(`gotcha_a-measurement-without-its-sample-band`) — 스레드 ID·체크포인트·리사이즈 크기·채널 정의까지.
- 사전등록은 **라벨을 보기 전에** 고정하고, 결과를 보고 임계값을 다시 쓰지 않는다(`gotcha_a-screening-gate-can-fail-on-its-own-threshold`; 14.2가 FAIL을 FAIL로 기록한 전례).
- 부류를 닫을 때는 사례 열거가 아니라 **모집단 전수 대조**(`gotcha_closing-a-class-needs-a-population-sweep`) — 43/43, 워크플로 3/3.
- 새 경고 코드는 `RUN_WARNING_CATALOG` 행 없이는 import 시 raise한다. `state.py`의 `RunWarningCode` 리터럴과 동기화한다.
- 사이드카 추가 필드는 **가산·비교 제외** — `_existing_complete_shot` 비교 키 3개는 불변이어야 기존 체크포인트가 계속 resume된다(13.3 AC8).
- 결정은 `config.py` 코드 기본값 + 날짜 붙은 근거 주석에만 적는다. `.env`/`.env.example` 핀 금지.

**Block If:**
- 어떤 AC를 닫으려면 **렌더된 프레임이 필요한** 상황 — 이 박스에 GPU가 없으므로 그 AC는 이 런에서 닫히지 않는다. 우회 렌더를 시도하지 말고 HALT.
- `_DEPTH_PHRASE["near"]`·`CARD_LOOKS`·`PLACEMENT` 문구를 바꿔야 AC가 닫히는 상황 — 그 변경은 43-plate 스윕과 10.1e 검증 슬레이트를 무효화한다(`config.py:554-560`). HALT.
- 플레이트/카드 워크플로의 LoRA 가중치를 **실제로 바꿔야** 하는 상황 — 자산 에폭 아카이브 경로가 없어(`asset_service.py:58-61` `# ponytail:`) 기존 42 플레이트·52 카드가 제자리 덮어쓰기된다. HALT.

**Never:**
- `BG_NEGATIVE_SUFFIX`를 늘리지 않는다(`gotcha_negative-prompt-overstuffing` — 두 번 물렸다).
- 화풍 관련 기본값을 ON으로 출하하지 않는다(10.1c·10.5·10.1e·14.2 전례 만장일치: 사람이 프레임을 보기 전엔 OFF).
- `prompts/` 아래 런타임 프롬프트를 건드리지 않는다 — 편집하면 Langfuse 시딩과 이름 검증이 따라붙고(`gotcha_langfuse-prompt-name-families-differ`), 렌더로 검증할 수단이 이 런에 없다.
- 신규 모델·신규 의존성 도입 금지(14-0 §4-1 Jay 결정; MV-CoLight/DAEdit/IC-Light 전부 범위 밖).
- **임계값을 만들지 않는다.** 이 세션의 화풍 라벨은 Claude 단독이고 미확정이므로, 그 라벨에 맞춘 커트는 결함이 아니라 라벨에 적합된다. 게이트는 Jay 라벨 확정 이후의 스토리다.
- "화풍을 고쳤다"고 쓰지 않는다 — 이 런은 렌더 0장이다.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| recompose 성공 | 샷이 recompose되어 `image_path`가 교체됨 | 그 샷의 사이드카에 `recompose` 블록(워크플로 sha256·패스 수·카드 키·position/depth/pose·digest)이 **가산**된다 | 사이드카 쓰기 실패는 런을 죽이지 않고 경고 |
| recompose 미발화 | `shot_recompose_enabled=False` 또는 cast 없음 | 사이드카에 `recompose` 블록 없음, 기존 바이트 불변 | 에러 없음 |
| resume | 사이드카에 `recompose` 블록이 있는 런을 재개 | `_existing_complete_shot`이 **여전히 히트**한다(비교 키 3개 불변) | 블록이 없거나 깨져도 히트 |
| 런 트레이스 | recompose가 돌았다 | `_record_trace`에 `recomposed`/`skipped`/`failed` 3필드가 실린다 | 통계 부재 시 0으로 기록 |
| 화풍 계약 테스트 | 3개 워크플로 JSON | 체크포인트·LoRA 파일명이 동일함을 단언하고, **가중치 불일치는 xfail로 고정**된다(0.5 vs 0.3) | 파일 부재 시 테스트 실패 |
| 팔레트 측정 | 43 PNG | shot별 `sat_mean`/`vivid_frac`/`sat_p95` CSV + 컨택트 시트 | 이미지 손상 시 그 행만 스킵하고 기록 |

</intent-contract>

## Code Map

- `src/yt_flow/services/recompose_service.py:244-345` -- `recompose_run_shots`. `:318-332` 원자적 PNG 쓰기(사이드카 없음), `:334` `image_path` 교체, `:339` `depth_map_path` pop, `:340` cast 맵에서 제거, `:343` 통계 로그. **사이드카 기록 지점은 `:334` 직후**
- `src/yt_flow/pipeline/nodes/shot_recompose.py:61-80` -- `placement_instruction`. 접지·화풍 절이 **이미 있다**. `:119-131` `build_single_pass`, `:138-147` digest 경로
- `src/yt_flow/pipeline/nodes/image.py:328-390` -- `_write_sidecar`. 사이드카 스키마의 유일한 작성자. **recompose는 이 파일을 안 건드린다** — 스키마 확장은 여기, 쓰기는 recompose 쪽
- `src/yt_flow/pipeline/nodes/image.py:~430-455` -- `_existing_complete_shot`. 비교 키 `image_prompt`/`negative_prompt`/`seed∈ladder` **셋뿐**. 늘리면 기존 캐시 전량 무효
- `src/yt_flow/pipeline/nodes/video.py:1169-1235` -- `_record_trace`. `composite_harmonization_tier`·`relit_pairs_*`·`parallax_25d_enabled`는 있고 **recompose 필드가 없다**. 호출 `:2861`
- `src/yt_flow/pipeline/nodes/video.py:2543-2607` -- recompose 블록 + 경고 4종. `:2569` 통계 로그가 트레이스로 안 간다
- `src/yt_flow/pipeline/nodes/composite_harmonization.py:504` `precompute_relights`, `:613` `pairs.setdefault((variant, location_key), …)` -- 14.1이 인계한 결합 결함. **`video.py:2624`가 `tier >= 3`에서만 호출한다**
- `src/yt_flow/config.py:611` -- `composite_harmonization_tier: int = Field(1, ...)`. `:554-560` `_DEPTH_PHRASE["near"]` 기지 결함, `:436-578` recompose 근거 블록(해제 조건 (c) 철회 노트 — 반증은 `tier >= 3` 한 줄이고, 함께 적혔던 "0/43 카드체인 진입"은 불변식이 아니라 run `4b35c0ed`의 관찰로 강등됐다)
- `workspace/<run>/recomposed/<shot>_<digest>.png` -- **출하 프레임 33/43장.** `images/*.png`는 recompose **이전 플레이트**이고 Jay가 본 것은 이쪽이다. 두 면은 별개의 모집단이며 하나로 뭉뚱그리면 라벨과 측정이 서로 다른 픽셀을 가리킨다
- `tests/test_workflow_definitions.py` -- 10.3이 만든 워크플로 계약 테스트(LoRA 허용목록·댕글링 참조·모델 체인). **화풍 계약이 앉을 자리**. `POSE_GUIDE` 상수(`:65`)가 이미 있고 `ALLOWED_LORAS`가 베이스 모델별로 갈린다
- `data/workflows/comfyui_shot_recompose_qwen_api.json` · `comfyui_character_pose_guide_api.json` -- **렌더링 모집단의 나머지 둘.** recompose 그래프는 `shot_recompose_enabled=True`로 **출하 중이고 이 런의 33/43을 그렸다**. Qwen-Image-Edit 계열이라 체크포인트·LoRA가 SDXL 셋과 다르다 — 계약은 계열별로 갈라 단언해야 한다
- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` · `comfyui_location_plate_api.json` · `comfyui_character_multi_angle_api.json` -- 배경·플레이트·카드. 셋 다 AnimagineXL v3.1 + `darkness_xl_v2`, 가중치는 0.5 / 0.5 / **0.3**
- `src/yt_flow/domain/warnings.py:29-88` · `state.py:631-632` -- 경고 카탈로그와 리터럴
- `tests/services/test_recompose_service.py` · `tests/pipeline/nodes/test_video_harmonization.py:699-870` · `tests/pipeline/nodes/test_image.py` -- 회귀 지점

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/14-3-art-style-contract/PREREGISTRATION.md` -- 측정 정의(채널·리사이즈·**`resample`을 명시적으로 `Image.Resampling.BICUBIC`으로 고정** — Pillow 12.3의 `resize()` 기본값이 NEAREST가 아니라 BICUBIC이고, 인자 없이 뽑은 데이터는 BICUBIC이다)·**두 모집단의 정의**(`images/` = 플레이트 43장 / 출하면 = `recomposed/` 33장 + 나머지 플레이트 10장)·표본 밴드·**이 측정이 못 보는 것**(플랫 아이소메트릭 `S00303`은 저채도라 팔레트 지표에 안 잡힌다)·임계값 금지 규칙을 고정. **라벨이 측정보다 먼저 존재했음을 사실대로 적는다** — "라벨을 읽기 전에 얼렸다"고 쓰지 않는다
- [x] `_bmad-output/implementation-artifacts/14-3-art-style-contract/measure_palette.py` -- **두 면 모두** 산출한다(`--surface plate|delivered`, 둘 다 기본 실행). 출하면은 `recomposed/<shot>_*.png`가 있으면 그것을, 없으면 플레이트를 쓴다. CSV 파일명과 행에 **`run_id`를 싣는다**(고정 파일명 금지 — 다른 런으로 돌리면 커밋된 증거를 조용히 덮어쓴다). PIL+numpy만
- [x] `_bmad-output/implementation-artifacts/14-3-art-style-contract/build_style_sheet.py` -- **출하면**으로 컨택트 시트를 만든다(Jay가 판정할 것은 그가 본 프레임이다). 타일은 장변 256px(판정 기준이 렌더 스타일이라 CLAUDE.md의 ~512px 규칙에서 **아래로** 벗어나는 것이 아니라 43타일 시트에서 512px 장변이 73px 썸네일이 되기 때문 — 시트 전체 장변이 아니라 타일 크기를 적는다). **해상도가 섞인 입력**(스톡 1920×1080 vs 자유생성 1216×832)을 늘리지 말고 타일 박스에 레터박스한다. PNG 한 장이 깨져도 나머지로 시트를 만들고 스킵 목록을 찍는다
- [x] `_bmad-output/implementation-artifacts/14-3-art-style-contract/prompt_vocab_scan.py` + `report.md` -- 텍스트 반증의 재산출. **결론을 하드코딩하지 않는다** — 실제 산출된 p와 항목 수로 분기해 문장을 고른다. **스코프를 명시한다**: 이 스캔은 `image_prompt`(플레이트를 그린 텍스트)에 대한 것이고, 출하 프레임 33/43을 그린 텍스트는 `shot_recompose.placement_instruction`이다. 후자에는 화풍 절이 **있다**(리포트 §4가 인용) — 그러므로 "제약할 어휘가 없다"는 **플레이트 생성 층에 한정된** 결론이다. 깨진 사이드카 한 장이 스캔 전체를 죽이지 않게 한다
- [x] `src/yt_flow/services/recompose_service.py` -- 샷 성공 시 사이드카에 `recompose` 블록 기록. **원자적 쓰기**(tmp + `replace`) — 이 파일은 `image_prompt`/`seed`를 들고 있어 찢어지면 그 샷이 재렌더된다. **캐시 히트는 재스탬프하지 않는다**(digest가 워크플로·지시문을 안 덮으므로 현재 sha를 찍으면 안 그린 워크플로에 프레임을 귀속시킨다 — 기존 블록을 보존하거나 digest에 워크플로 sha를 넣는다). **재진입 시 사이드카가 없으면 다시 쓰고, 못 쓰면 경고를 다시 낸다**(현재 설계는 실패한 귀속이 재시도에서 침묵한다 — 이 스토리가 없애려는 침묵 그 자체다). 헬퍼는 `OSError`뿐 아니라 `TypeError`/`ValueError`도 삼킨다
- [x] `src/yt_flow/pipeline/nodes/image.py` -- `_write_sidecar`에 `recompose` **키 리터럴만** 추가한다(`null`로 명시 기록 — 생략과 구분되어야 "14.3 이전 사이드카"와 "이 런은 recompose 안 함"이 갈린다). **인자는 추가하지 않는다** — 호출부가 없다(ponytail: 없는 작성자를 위한 스캐폴딩 금지). `_existing_complete_shot` 비교 키 3개 불변
- [x] `src/yt_flow/pipeline/nodes/video.py` -- `_record_trace`에 `recomposed`/`recompose_skipped`/`recompose_failed` 추가. **에러 경로 호출부에도 통계를 넘긴다**(recompose 성공 후 ffmpeg가 죽으면 0/0/0이 찍혀 "돌았는데 아무것도 안 했다"와 구분이 안 된다 — 이 키가 없애려던 모호함이다). 서비스 경고 수집은 **비-리스트·비-딕트 방어**를 하고, `try` 밖에서 이미 프레임이 교체된 뒤에 preflight 실패로 오보하지 않게 배치한다
- [x] `tests/test_workflow_definitions.py` -- **렌더링 모집단 전수**(배경·플레이트·카드·**recompose**·포즈가이드)를 훑는다. SDXL 셋(배경·플레이트·카드)에 대해 동일 체크포인트·동일 LoRA 파일을 단언하고 **가중치 동일성만 `xfail(strict=True)`**(0.5/0.5/0.3). recompose 그래프는 **다른 베이스 모델 계열**임을 명시적으로 단언한다 — 계약 밖이 아니라 **다른 계약**이다. LoRA 노드가 둘 이상이거나 값이 링크(`["3", 0]`)일 때 임의 노드를 집거나 `TypeError`로 죽지 않게 한다. 값은 바꾸지 않는다(Block If)
- [x] `src/yt_flow/domain/warnings.py` · `state.py` -- `recompose_sidecar_failed` 코드 + 카탈로그 행(stage `video`)
- [x] `tests/services/test_recompose_service.py` · `tests/pipeline/nodes/test_video_harmonization.py` · `tests/pipeline/nodes/test_image.py` -- I/O 매트릭스 전행 + 위에 열거된 엣지(캐시 히트 재스탬프 금지, 재진입 재기록·재경고, 부분 쓰기 후 resume, 비-딕트 통계, 에러 경로 트레이스)
- [x] `src/yt_flow/config.py:304-337` · `epics.md` · `deferred-work.md` · `epic-14-context.md` · `spec-14-1-approved-plate-sets.md` · `14-1-approved-plate-sets/report.md` -- `stock_plate_substitution_enabled` 해제 조건 **(c) 릴라이트 결합 수정**이 잘못된 선행 조건임을 정정. 원문은 취소선 보존(`gotcha_recorded-root-cause-can-be-inverted`)

**Acceptance Criteria:**
- Given run `4b35c0ed`의 43 사이드카, when `prompt_vocab_scan.py`를 돌리면, then 표류 라벨 7건 중 팔레트/화풍 어휘 보유 **2건**·비표류 36건 중 **2건**(발견된 유일 항목은 `LED`)이 재산출되고, 리포트가 그 결론을 **플레이트 생성 층으로 한정**해 적으며 출하 프레임의 지시문(`placement_instruction`)에는 화풍 절이 있음을 같은 절에서 밝힌다
- Given 같은 런, when `measure_palette.py`를 **플레이트 면**으로 돌리면, then `vivid_frac` 상위 3이 `S00501`(0.2187)·`S00301`(0.0890)·`S00605`(0.0578)이고 `S00303`이 `0.0000`이다
- Given 같은 런, when `measure_palette.py`를 **출하 면**으로 돌리면, then 상위 3이 `S00501`(0.1886)·`S00103`(0.0981)·`S00301`(0.0760)이고 표류 라벨 7건의 랭크가 `[0, 2, 6, 9, 11, 16, 29]`이다 — 두 면의 순위가 다르다는 사실 자체가 리포트에 기록된다
- Given 컨택트 시트, when 열어 보면, then 33개 타일이 `recomposed/`에서 왔고 나머지 10개가 플레이트임이 타일 각인으로 구분된다(Jay가 본 것과 같은 픽셀)
- Given recompose가 성공한 샷, when 런이 끝나면, then 그 샷의 `*_done.json`에 `recompose` 블록이 있고 워크플로 sha256과 카드별 position/depth/pose가 **패스 순서로** 들어 있다
- Given 사이드카가 이미 `recompose` 블록을 가진 샷을 **캐시 히트로 재진입**할 때, then 기존 `workflow_sha256`/`recomposed_at`이 **덮어써지지 않는다**(안 그린 워크플로에 귀속 금지)
- Given 사이드카 쓰기가 실패한 샷을 **다음 런에서 재진입**할 때, then 사이드카가 다시 기록되거나 `recompose_sidecar_failed` 경고가 **다시** 발화한다(침묵 금지)
- Given `recompose` 블록이 추가된 사이드카, when 14.3 이전 체크포인트를 resume하면, then `_existing_complete_shot`이 여전히 히트한다(재렌더 0)
- Given recompose가 성공한 뒤 video 단계 후반이 예외로 죽는 런, when 트레이스를 읽으면, then `recomposed` 카운트가 **실제 값**이다(0/0/0 아님)
- Given 렌더링 워크플로 5개, when `tests/test_workflow_definitions.py`를 돌리면, then SDXL 3종의 체크포인트·LoRA 파일 동일성이 통과하고 가중치 동일성이 xfail로 뜨며, recompose 그래프가 **다른 베이스 모델 계열**로 단언된다
- Given `composite_harmonization_tier`가 출하 기본값 `1`, when 코드 경로를 추적하면, then `precompute_relights`가 도달 불가임이 테스트로 고정된다

## Spec Change Log

- 2026-08-29 **리뷰 루프 1 — 측정과 시트가 잘못된 모집단 위에 있었다(적대적 리뷰 #1·#2, 엣지 헌터 동반).** 트리거:
  `images/*.png`는 recompose **이전 플레이트**이고 이 런의 출하 프레임 **33/43**은 `recomposed/`에 있다. 표류
  라벨 7건 중 **6건이 recompose된 샷**이므로 라벨(Jay가 본 영상에서 나온 것)과 측정(플레이트)이 서로 다른
  픽셀을 가리켰다. **독립 재측정으로 확인**: 출하면 상위 3은 `S00501`·`S00103`·`S00301`이고 플레이트면
  상위 3은 `S00501`·`S00301`·`S00605`다. 표류 랭크가 `[0,1,2,4,6,10,28]` → `[0,2,6,9,11,16,29]`로 벌어진다.
  즉 리포트의 대표 증거("라벨 7건 중 6건이 상위 11위 안")는 **플레이트면에서만** 참이다. **수정**: 두 면을
  각각 정의해 **둘 다** 산출하고, Jay 판정 시트는 **출하면**으로 만들며, 두 면의 순위 불일치 자체를 결과로
  기록한다. 회피한 알려진-나쁜 상태: 사람이 본 적 없는 프레임으로 라벨을 확정받고 그 라벨 위에 임계값을
  올리는 것.
- 2026-08-29 **리뷰 루프 1 — 모집단 전수 규칙을 이 스토리 자신이 어겼다(적대적 리뷰 #10).** `STYLE_WORKFLOWS`가
  배경·플레이트·카드 셋뿐이고 **`shot_recompose_enabled=True`로 출하 중이며 이 런의 33/43을 그린 recompose
  그래프**와 포즈가이드가 빠져 있다. 스펙의 Always에 `gotcha_closing-a-class-needs-a-population-sweep`를
  적어놓고 사례 열거를 했다. **수정**: 렌더링 워크플로 전수를 훑되 recompose는 Qwen 계열이므로 **다른 계약**
  으로 단언한다(계약 밖이 아니다).
- 2026-08-29 **리뷰 루프 1 — 귀속 경로 자체에 귀속 구멍 둘(적대적 리뷰 #8·#9, 엣지 #1).** (a) 캐시 히트가
  현재 `workflow_sha256`을 재스탬프하는데 digest는 워크플로·지시문을 **안 덮는다** → 안 그린 워크플로에
  프레임이 귀속된다. (b) 사이드카 쓰기가 실패한 샷은 재진입에서 `skipped`로 `continue`돼 **경고조차 사라진다**
  → 영구 미귀속. 이 스토리의 존재 이유가 침묵 제거인데 새 침묵을 둘 만들었다(13.3이 같은 형태를 겪었다).
  **수정**: 재스탬프 금지 + 재진입 재기록·재경고를 AC로 승격.
- 2026-08-29 **리뷰 루프 1 — 측정 정의가 데이터를 재현하지 못한다(적대적 리뷰 #4, 엣지 #9).** 문서가 리사이즈를
  NEAREST라고 적었으나 Pillow 12.3의 `resize()` 기본값은 **BICUBIC**이고 CSV는 BICUBIC으로 만들어졌다. 적힌
  정의대로 재산출하면 43행 중 29행의 순위가 움직인다 — 이 스펙이 Always로 인용한
  `gotcha_a-measurement-without-its-sample-band` 바로 그 부류다. **수정**: 코드와 문서 양쪽에 `BICUBIC`을
  명시 고정(데이터는 유효하므로 정의를 데이터에 맞춘다, 그 반대가 아니다). 함께 **사전등록 서술 정정** —
  라벨은 측정보다 **먼저** 존재했으므로 "라벨을 읽기 전에 얼렸다"고 쓰지 않는다(리뷰 #5).
- 2026-08-29 **리뷰 루프 1 — 재산출 스크립트가 결론을 하드코딩(적대적 리뷰 #6).** `prompt_vocab_scan.py`가
  임의 `run_id`를 받으면서 "the split does not discriminate"를 무조건 출력한다. 반대 데이터를 넣어도 같은
  문장이 나오므로 재산출 도구가 아니다. **수정**: 실제 p와 항목 수로 분기.
- **KEEP(재도출 시 반드시 살릴 것)**: 릴라이트 결합 인계의 반증(`precompute_relights`는 `tier >= 3`에서만
  도달 가능, 출하 기본값 1, tier 3은 10.1b 시청 기각 — 독립 확인 완료)과 그것을 고정하는 테스트, 그리고
  7곳 취소선 정정 / `_existing_complete_shot` 비교 키 **정확히 3개** 유지 / `recompose` 키를 생략이 아닌
  `null`로 기록해 "14.3 이전"과 "recompose 안 함"을 구분 / `stats["warnings"]`를 비어 있지 않을 때만 추가
  (단 로그 라인이 그 근거를 배신하지 않게) / LoRA 가중치 divergence의 `xfail(strict=True)`와 그 긴 사유 문구 /
  Fisher exact 구현(scipy와 일치 확인)과 `swelled` 속 `led`를 피하는 단어 경계 규칙 / `recompose_sidecar_failed`
  카탈로그 문안이 "프레임은 멀쩡하고 기록만 잃었다"를 말해 오퍼레이터가 정상 샷을 재렌더하지 않게 하는 것.

## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 7: (high 5, medium 1, low 1)
- patch: 16: (high 0, medium 11, low 5)
- defer: 0
- reject: 0
- addressed_findings:
  - `[high]` `[bad_spec]` 팔레트 측정·컨택트 시트·리포트 대표 수치가 **플레이트면**(`images/`)에 있었고 출하 프레임 33/43은 `recomposed/`다 — 독립 재측정으로 순위 이동 확인, 두 면을 분리 정의하고 시트는 출하면으로 재도출
  - `[high]` `[bad_spec]` `STYLE_WORKFLOWS`가 출하 중인 recompose 그래프를 제외 — 모집단 전수로 확대하되 Qwen 계열은 별도 계약으로 단언
  - `[high]` `[bad_spec]` 캐시 히트가 안 그린 워크플로의 sha로 재스탬프 — 재스탬프 금지를 AC로 승격
  - `[high]` `[bad_spec]` 사이드카 쓰기 실패가 재진입에서 침묵 — 재기록·재경고를 AC로 승격
  - `[high]` `[bad_spec]` 측정 정의(NEAREST)가 실제 데이터(BICUBIC)와 불일치 — 정의를 데이터에 맞춰 명시 고정
  - `[medium]` `[bad_spec]` 사전등록 서술이 "라벨보다 먼저 얼렸다"고 주장하나 라벨이 먼저였다 — 사실대로 정정
  - `[low]` `[bad_spec]` 스펙(장변 512px)과 구현(타일 256px) 불일치 — 타일 기준으로 스펙을 정정
  - 16건의 patch(원자적 쓰기, 결론 하드코딩, 죽은 인자, xfail 노드 선택, 비-딕트 통계 방어, 에러 경로 트레이스, CSV 런 식별자, 혼합 해상도 타일, 손상 입력 내성 등)는 코드 재도출에 포함되도록 Tasks·AC로 승격

### 2026-08-29 — Review pass 2
- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 5, medium 11, low 3)
- defer: 3: (high 0, medium 2, low 1)
- reject: 2
- addressed_findings:
  - `[high]` `[patch]` **재도출이 만든 회귀** — 비-딕트 통계 페이로드를 조용히 `{}`로 강등해 프레임 33장을 이미 교체한 뒤 트레이스가 0/0/0을 찍고 경고가 0건이었다("recompose 꺼짐"과 바이트 동일). 이전에는 blanket except가 경고를 냈고 그 주석이 고아로 남아 있었다 → 강등 지점에서 `stats_payload_unreadable` 경고 발화 + 침묵을 고정하던 테스트를 반대로 뒤집음
  - `[high]` `[patch]` 릴라이트 반증의 **둘째 다리가 과대주장**이었다 — "recompose ON이면 0/43이 카드 체인에 진입"은 런 `4b35c0ed` 관측이지 불변식이 아니다(`remaining.pop`이 성공·재진입 분기에서만 일어나므로 `failed`/`skipped` 샷은 cast를 유지한 채 체인에 들어간다). `tier >= 3` 다리만으로 충분하고 건전하다 → 7곳 + 이 스펙 2곳에서 관측으로 강등. **정정 노트 자신이 이 프로젝트의 세 번째 역전된-원인 사례를 심었다**
  - `[high]` `[patch]` 컨택트 시트가 **Jay가 확인할 라벨을 타일에 미리 찍고 있었다**(노란 `*drift?`) — 판정이 가설에 앵커된다. 에픽 컨텍스트가 "게이트 판정은 blind여야 한다"고 못박은 축이다 → 블라인드 시트를 판정 산출물로, 주석본은 기록용 별도 파일로 분리
  - `[high]` `[patch]` 출하면 지표가 **"누가 그렸는가"와 교란**돼 있었다 — recompose 33행 평균 `vivid_frac` 0.0224 vs 플레이트 10행 0.0031(7.2배), 상위 9행 9/9가 recompose다. 표류 라벨 7건 중 6건도 recompose 샷이므로 라벨-지표 연관의 상당 부분이 출처만으로 예측된다 → 층화 비교를 리포트에 싣고 사전등록 "못 보는 것" 목록에 추가
  - `[high]` `[patch]` 인계 3건(`S00504`·`S00803`·`S00105`)이 **`deferred-work.md`에 한 줄도 없었다** — done 스토리가 이름 붙은 결함 셋을 소유한 채 닫힐 뻔했다 → 3행 등재 + `epic-14-context.md`의 "네 부류 상속"·"플레이트 측 팔레트 제약" 범위 서술 정정(이 스토리 자신의 실측이 둘 다 반증한다)
  - `[medium]` `[patch]` `recompose_skipped`가 **의미가 뒤집힌 카운터**를 물려받았다 — 재진입의 `skipped`는 "이미 recompose됨"인데 트레이스 독자는 "recompose 안 됨"으로 읽고 `recompose_shots_degraded` 문안은 "오버레이로 렌더했습니다"라고 거짓을 말한다 → `skipped`/`reentered` 분리
  - `[medium]` `[patch]` 그 외 12건: 워크플로 sha `None`이 캐시히트 `None`과 구분 불가·무로그 / 캐시 채움 경로가 `recomposed_at`을 오늘로 / `.tmp` 잔존 / 귀속 커버리지 미측정(`recomposed=33`을 "33장 귀속"으로 못 읽음) / 명시적 `null`의 근거가 거짓(읽는 코드 없음) / **출하 33/43을 그린 Qwen 그래프의 베이스 모델 격차가 통과 단언에 묻혀 있었다**(0.5-vs-0.3 가중치보다 큰 격차인데 xfail로 드러나지 않는다) / 블록이 지시문 해시 없이 "어느 지시가 그렸는가"를 주장 / 잘못된 키의 경고 행이 샷을 못 지목 / 비-딕트 cast가 전 카드를 조용히 삭제 / 스탬프 예외가 스윕을 중단 / 경고 컨텍스트 `shot_id` 포맷 불일치 / `_stat_count`가 float·숫자문자열을 무로그로 0 처리 / 재진입 digest 파싱의 구분자 부재
  - `[low]` `[patch]` 3건(경고 컨텍스트 분리·불가용 값 로깅·digest 구분자 가드)은 위에 포함

## Design Notes

**왜 게이트를 안 만드는가.** 팔레트 지표는 라벨 7건 중 6건을 상위 11위 안에 놓지만(`vivid_frac` 랭크 0·1·2·4·6·10) 일곱 번째 `S00303`은 랭크 28이다 — 플랫 아이소메트릭 스케치는 **저채도**라 팔레트 축에 원리적으로 안 잡힌다. 그리고 그 라벨들은 **Claude 단독**이다. 14.2에서 같은 종류의 인계 라벨 2건이 전수 판정으로 뒤집혔고(`S00504`·`S00803`), 미검출 1건은 **판정기가 옳고 라벨이 틀린** 경우였다. 라벨이 확정되지 않은 상태에서 임계값을 고르면 그 임계값은 라벨에 적합된 것이지 결함에 적합된 것이 아니다. 10.3 §5가 이 축의 재개 조건과 **방법까지** 사전등록해 뒀다 — *"build it on ComfyUI CLIPVision embeddings of the run's own shot images, scored as distance from the run's own median shot"* — 그리고 그것은 GPU 패스를 요구한다. 이 런은 GPU가 없다.

**릴라이트 결합 인계는 발화 조건이 다시 틀렸다.** 14.1이 14.3으로 넘기며 *"run `4b35c0ed` 재생에서 이미 발화한다"* 고 적었지만, 그 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고 그 함수는 `video.py:2624`의 `composite_harmonization_tier >= 3`에서만 호출된다. 출하 기본값은 `1`이고 tier 3(IC-Light)은 **10.1b가 시청 판정으로 기각**했다. **그 한 줄이 반증의 전부다.** ⚠️ 초안은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*을 붙였는데, 리뷰가 그것을 **관찰의 불변식 격상**으로 반증했다 — `recompose_run_shots`의 `remaining.pop`은 성공·재진입 분기에서만 돌므로 `failed`/`skipped` 샷은 cast를 들고 오버레이 체인에 **진입한다**. 0/43은 run `4b35c0ed`의 관찰로 강등하고 반증은 `tier >= 3` 하나로 선다. `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. 이것이 이 인계 항목의 **두 번째** 발화 조건 정정이다(첫 번째는 14.1 리뷰 루프 1이 "씬 내부"를 "런 전체"로 고친 것) — 그래서 원문을 지우지 않고 취소선으로 남긴다.

**화풍 계약을 산문이 아니라 테스트로 쓰는 이유.** 세 워크플로는 이미 같은 체크포인트(AnimagineXL v3.1)와 같은 LoRA(`darkness_xl_v2`)를 쓴다. 어긋난 것은 **가중치 하나**다 — 배경 0.5 / 플레이트 0.5 / 카드 **0.3**. recompose가 카드를 참조 이미지로 받아 그 화풍을 보존하므로, 카드가 다른 가중치로 렌더된 것은 "찢어붙인 듯"의 **선언 단계 원인 후보**다. 그러나 값을 바꾸면 승인된 42 플레이트·52 카드가 새 렌더와 안 맞고(10.3 §7 잔여 (ii)), 에폭 아카이브 경로가 없어 제자리 덮어쓰기가 된다(`asset_service.py:58-61`). 그래서 **바꾸지 않고 `xfail(strict=True)`로 고정**한다 — 실행 가능한 기록이고, 누군가 값을 맞추면 xpass로 실패해서 결정이 드러난다.

**recompose 귀속이 왜 이 스토리 소관인가.** 층 2의 세 인계 결함(`S00504` 기운 바닥 / `S00803` 척도 / `S00105` 바닥 밖 배치)은 전부 **지시가 이미 있는데도** 난다. `S00803`의 척도는 이미 진단까지 끝나 있다 — `_DEPTH_PHRASE["near"]`의 두 절("close to camera" + "whole body head to feet")이 16:9에서 양립 불가라 모델이 인물을 키워 둘 다 만족시킨다(`config.py:554-560`, Jay가 같은 시청에서 제기). 고치지 않은 이유는 명시적이다: 그 문구를 바꾸면 43-plate 스윕과 10.1e 슬레이트가 무효가 된다. 즉 남은 결함들은 **렌더로만 판별**되는데, 정작 recompose는 자기가 무엇을 지시했는지 디스크에 안 남긴다(파일명의 16-hex digest가 유일한 흔적이고 역산 불가). 어느 프레임이 어떤 지시로 그려졌는지 모르면 다음 GPU 세션의 페어 렌더도 귀속이 안 된다. 그래서 **귀속 경로를 먼저 깐다.**

## Verification

**Commands:**
- `uv run pytest tests/services/test_recompose_service.py tests/pipeline/nodes/test_video_harmonization.py tests/pipeline/nodes/test_image.py tests/test_workflow_definitions.py tests/domain/test_run_warnings.py -q` -- expected: 기존 전량 통과 + 신규 통과, 화풍 가중치 테스트는 **xfail 1건**
- `uv run pytest -q` -- expected: `test_render_pose_guides.py` PNG SHA 1건만 실패(14.5가 기존 결함으로 기록, stash 후에도 동일) + 신규 xfail 1
- `uv run ruff check src tests scripts` -- expected: clean
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0, 신규 필드 없음(이 스토리는 결정 필드를 추가하지 않는다)
- `uv run python _bmad-output/implementation-artifacts/14-3-art-style-contract/prompt_vocab_scan.py 4b35c0ed-8a1e-4448-8594-11bd9997376d` -- expected: 표류 2/7 · 비표류 2/36 재산출
- `uv run python _bmad-output/implementation-artifacts/14-3-art-style-contract/measure_palette.py 4b35c0ed-8a1e-4448-8594-11bd9997376d` -- expected: `vivid_frac` 상위 3 = `S00501` `S00301` `S00605`, `S00303` = 0.0000
- `uv run python _bmad-output/implementation-artifacts/14-3-art-style-contract/build_style_sheet.py 4b35c0ed-8a1e-4448-8594-11bd9997376d` -- expected: 컨택트 시트 JPG **2장** 생성(출하면, 장변 256px 타일) — `style_sheet_delivered_<run>.jpg` 가 **판정 산출물(블라인드, Claude 라벨 미각인)** 이고 `..._annotated_<run>.jpg` 는 기록용이다. 판정 시트에 가설을 각인하면 판정기가 가설에 고정된다

**Manual checks (if no CLI):**
- **픽셀 판정은 이 스토리가 하지 않는다.** 층 1은 컨택트 시트로 Jay가 화풍 이탈 라벨을 확정하고, 층 2의 before/after 페어는 **GPU가 있는 세션**이 같은 매니페스트로 렌더해야 한다. 그 두 개 없이 "화풍을 고쳤다"를 `## Auto Run Result`에 쓰지 않는다.
- 이 박스 상태: `nvidia-smi` 드라이버 통신 실패 · `127.0.0.1:8188` 응답 000. 렌더 0장이 **의도된 범위**이고 실패가 아니다.

## Auto Run Result

Status: **done** — 단, **이 스토리는 화풍을 고치지 않았다. 고칠 수 있게 만들었다.** 렌더 0장이고 Jay 판정은 열려 있다.

### 구현된 변경

에픽이 적어둔 처방(팔레트·조명을 닫힌 어휘로 제약)은 **표적 집합이 비어 있어** 성립하지 않는다 — run `4b35c0ed` 43샷 전수 스캔에서 네온/이질화풍 어휘는 프롬프트에 **없다**(표류 2/7 vs 비표류 2/36, 유일 항목 `LED`, Fisher p=0.118). 층 2도 같은 모양이다: recompose는 *"Feet firmly on the ground with a contact shadow … rendered in the same illustration style as the background"* 를 **매 패스 이미 보내고 있다.** 그래서 이 스토리는 두 층 다 **픽셀에서 측정**하고, recompose에 **귀속 경로**를 깐다 — 지금까지 recompose는 PNG만 쓰고 자기가 무엇을 지시했는지 디스크에 한 글자도 안 남겼다(파일명의 16-hex digest가 유일한 흔적이고 역산 불가).

### 파일

| 파일 | 한 줄 |
|---|---|
| `services/recompose_service.py` | 사이드카 `recompose` 블록(워크플로 sha·지시문 sha·패스 순서 카드·digest) 원자적 기록; 캐시히트 **재스탬프 금지**, 재진입 **재기록·재경고**, `skipped`/`reentered` 분리, `attributed` 커버리지 카운트 |
| `pipeline/nodes/image.py` | `_write_sidecar`가 `recompose` 키를 **명시적 `null`** 로 선언(인자 추가 없음 — 호출부가 없다). 비교 키 **정확히 3개** 불변 |
| `pipeline/nodes/video.py` | 트레이스에 `recomposed`/`skipped`/`reentered`/`failed`/`attributed`; **에러 경로에도** 실제 통계; 비-딕트 통계·비-딕트 cast·불량 경고행 방어 + 각각 경고 발화 |
| `domain/warnings.py` · `state.py` | `recompose_sidecar_failed` — 문안이 "프레임은 정상, 기록만 잃었다"를 말해 정상 샷 재렌더를 막는다 |
| `tests/test_workflow_definitions.py` | 렌더링 워크플로 **전수** 계약. SDXL 3종 체크포인트·LoRA 파일 동일 단언 + 가중치 동일성 **`xfail(strict=True)`**(0.5/0.5/**0.3**), Qwen recompose 그래프는 **다른 계약**으로 명시 |
| `14-3-art-style-contract/` | 사전등록 · 두 면 측정기 · 어휘 스캐너 · **블라인드** 판정 시트 + 주석본 · CSV 2종 · 리포트 |

### 리뷰 결과

패스 1: intent_gap 0 · **bad_spec 7**(high 5) · patch 16 → 코드 전량 되돌리고 스펙 수정 후 재도출.
패스 2: intent_gap 0 · bad_spec 0 · **patch 19**(high 5) · defer 3 · reject 2 → 전건 수정.

가장 중대한 발견 넷은 전부 **이 스토리 자신의 산출물을 반증했다**:
1. **측정이 잘못된 픽셀 위에 있었다** — `images/`는 recompose **이전** 플레이트이고 출하 프레임 33/43은 `recomposed/`다. 표류 라벨 7건 중 **6건이 recompose 샷**이므로 라벨(Jay가 본 영상)과 측정(플레이트)이 서로 다른 면을 가리켰다. 순위가 `[0,1,2,4,6,10,28]` → `[0,2,6,9,11,16,29]`로 벌어진다.
2. **모집단 전수 규칙을 스스로 어겼다** — 계약 테스트가 출하 중인(33/43을 그린) recompose 그래프를 빼놓았다. Always에 `gotcha_closing-a-class-needs-a-population-sweep`를 적어놓고 사례 열거를 했다.
3. **귀속 경로에 귀속 구멍이 둘** — 캐시히트가 안 그린 워크플로 sha로 재스탬프하고, 쓰기 실패한 샷이 재진입에서 침묵했다. 침묵을 없애려는 스토리가 새 침묵을 둘 만들었다(13.3 전례).
4. **재도출이 회귀를 만들었다** — 비-딕트 통계 강등이 경고를 삼켜 0/0/0이 "recompose 꺼짐"과 구분 불가가 됐다.

### 검증

- 336 passed / 1 xfailed (타깃 스위트) · 전체 **3419 passed / 1 failed** — 그 1건은 14.5가 기존 결함으로 기록한 `test_render_pose_guides.py` PNG SHA 핀
- `ruff check src tests scripts` clean · `report_decision_drift.py` exit 0(신규 결정 필드 0)
- `pyright` 3파일 **16 errors = 베이스라인 16**(stash 대조로 확인, 회귀 0)
- 재산출: 플레이트면 상위 3 `S00501` 0.2187 · `S00301` 0.0890 · `S00605` 0.0578, `S00303` 0.0000 / 출하면 상위 3 `S00501` 0.1886 · `S00103` 0.0981 · `S00301` 0.0760 / 어휘 2/7 · 2/36

### 잔여 리스크 · 미주장

- **화풍은 고쳐지지 않았다.** 렌더 0장(이 박스 `nvidia-smi` 실패, ComfyUI 미응답). 층 1 라벨 확정은 블라인드 시트로 **Jay 판정 대기**, 층 2 before/after 페어는 **GPU 세션** 몫이다.
- **라벨 7건은 여전히 Claude 단독**이고 임계값은 만들지 않았다 — 14.2에서 같은 종류가 두 번 뒤집혔다.
- **출하면 지표는 출처와 교란돼 있다**(recompose 0.0224 vs 플레이트 0.0031, 7.2배; 상위 9행 9/9 recompose). 층화 수치를 리포트에 실었고, 이것이 커트를 만들지 않은 **네 번째** 독립 이유다.
- **가장 큰 화풍 격차는 가중치가 아니라 베이스 모델이다** — 출하 33/43을 Qwen-Image-Edit이 그리고 10/43을 SDXL이 그린다. "격차는 가중치 하나"는 10/43 플레이트 면에만 참이다.
- **인계 3건(`S00504`·`S00803`·`S00105`)은 미해결**이고 `deferred-work.md`에 등재했다. `S00803` 척도는 이미 진단까지 끝나 있으나(`_DEPTH_PHRASE["near"]`의 두 절이 16:9에서 양립 불가) 고치면 43-plate 스윕과 10.1e 슬레이트가 무효가 된다.
- **지시문 해시는 재구성 문자열**이다 — 제출된 정확한 바이트가 아니라 같은 어휘로 다시 만든 것이다. 오늘은 갈릴 수 없지만 호출부가 둘이다.
- defer 3건(`.env`가 워크플로 계약 스윕을 우회 / `relit_pairs_computed` 무방비 첨자 / `run_dir` 폴백)은 `deferred-work.md`로.

### 2026-08-30 — Jay 판정 후속 (코드 변경 0)

블라인드 시트 전수 판정으로 **AC의 사람 게이트 절반이 닫혔다.** 결과가 이 스토리의 결론을
바꾸지는 않았고 **강화했다** — 게이트를 만들지 않은 결정이 다섯 번째 이유를 얻었다.

- **17/43** 지목, Claude 라벨 대비 6/7 일치 · `S00105` **반증** · 11건 미탐(기저율 2.4배 오차)
- **17건은 다섯 부류** — 팔레트 7 / 합성 5 / 판독불가 3 / 척도 1 / 배경에 사람 1.
  **⑦로 접수된 것의 59%가 ⑦이 아니다.**
- 지표: 17건 전체 **8/17**(기대 6.7, 무신호) vs 팔레트 부류 **4/7**(기대 1.1) — 축은
  자기 부류에 대해서만 유효하다
- 라우팅: 합성 5 + 척도 1 → E2E iteration 5 / 판독불가 3 → 신규 부류 등재 /
  `S00201` → 14.1 승인 게이트(14.4(b)가 감수 리스크로 기록한 것의 실현)
- **Jay 결정 (B)**: 층 2와 `_DEPTH_PHRASE["near"]` 편집은 E2E iteration 5로

산출물: `14-3-art-style-contract/VERDICT.md`. `deferred-work.md`에 신규 3부류 등재,
`S00105` 행은 전제 약화 표기(지우지 않음 — 14.2 기록과 어긋나므로 다음 런에서 재확인).
