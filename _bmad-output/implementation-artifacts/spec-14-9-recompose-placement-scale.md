---
title: 'Story 14.9: recompose 배치·척도 — 진단된 한 줄을 고치고, 그 수정이 진짜인지 3-arm으로 증명한다'
type: 'bugfix'
created: '2026-08-30'
baseline_revision: '590db09'
status: 'in-review' # draft | ready-for-dev | in-progress | in-review | done | blocked
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** `_DEPTH_PHRASE["near"]`가 *"in the foreground close to camera"* 와 *"his whole body from head to feet visible in frame"* 를 함께 요구하는데 16:9에서 양립 불가라 모델이 **인물을 키워** 둘 다 만족시킨다. 원인은 `config.py:554-560`에 **이미 진단돼 있고** Jay가 10.1e 시청에서 제기했다. 안 고친 이유는 성능이 아니라 무효화 범위였다 — 그 문구를 바꾸면 43-plate 스윕과 10.1e 검증 슬레이트가 무효가 되고, 어제까지는 "GPU가 없다"는 **거짓 전제**가 그 위에 얹혀 있었다(`GPU-PREMISE-CORRECTION-2026-08-30.md`). GPU는 정상이고 렌더는 장당 12~17초다. 표적은 7샷 — 14.2 인계 3건(`S00105` `S00504` `S00803`)과 Jay 2026-08-30 블라인드 판정의 합성 부류 5건(`S00504` `S00702` `S00800` `S00802` `S00904`)의 합집합이다.

**Approach:** 문구를 고치고, **그 수정이 진짜인지 3-arm 페어로 증명한다** — A(출하된 프레임) / B(현 문구 + 새 시드) / C(수정 문구 + **B와 같은 시드**). B가 없으면 다시 뽑기 노이즈가 편집 공로로 계상된다(`gotcha_regeneration-needs-a-same-prompt-control`, +7.14pp 전례). **B와 C가 시드를 공유하지 않으면 설계가 무너진다.** 판정은 블라인드 시트로 Jay가 한다 — 이 에픽에서 Claude 단독 시각 라벨은 **세 번** 뒤집혔다.

## Boundaries & Constraints

**Always:**
- **B와 C는 같은 시드를 쓴다.** 다르면 C가 프롬프트 효과와 리롤 노이즈를 뒤섞는다.
- 세 arm 전부 **같은 리프레이밍 체인**(`_zoompan_filter(_FUSION_STILL_SPEC, 1.0)`)을 통과시킨다 — 해상도·크롭으로 arm이 식별되면 블라인드가 아니다.
- 블라인드 시트는 **샷마다 타일 순서를 치환**하고 그 치환을 키 파일에 기록한다. 10.1e의 고정 좌/우 배치는 타일 하나를 알면 전부 알게 된다.
- 사전등록은 **점수를 보기 전에** 커밋한다.
- 측정치는 표본 밴드·재산출 커맨드와 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).

**Block If:**
- **arm A의 digest가 재현되지 않을 때** — 카드 경로/배치 필드로 `recompose_digest`를 재계산해 파일명의 16-hex와 대조한다. 안 맞으면 앵글 리졸버가 다른 카드를 골랐다는 뜻이고 **B는 A의 대조가 아니다.** 그 상태로 진행하지 말고 HALT.
- 수정 문구 후보가 **부정 절을 추가**해야만 결함이 사라지는 형태일 때 — `gotcha_negative-prompt-overstuffing`이 두 번 물린 축이고 recompose의 negative는 의도적으로 비어 있다. HALT.
- ComfyUI 프리플라이트가 실패할 때(`--lowvram`/`--cache-lru` 부재, RAM 12GB 미만). HALT.

**Never:**
- **`workspace/<run>/recomposed/` 에 쓰지 않는다** — 그 디렉터리가 arm A의 유일한 사본이다. 새 arm은 이 스토리의 아티팩트 디렉터리로 쓴다.
- `recompose_service.recompose_run_shots`로 B·C를 렌더하지 않는다 — digest 캐시가 **프롬프트도 시드도 해싱하지 않아** 조용한 no-op이 된다(§Design Notes).
- 배치 지시를 **더 넣어** 고치려 하지 않는다 — 접지·화풍 절은 이미 매 패스 전송된다.
- 신규 모델·의존성 도입 금지(14-0 §4-1).
- 사람 판정 없이 "고쳤다"를 쓰지 않는다.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| digest 재현 | arm A 파일명의 16-hex | 깨끗한 플레이트 + 재해결 카드로 재계산한 digest가 **일치** | 불일치 → Block If, HALT |
| arm B 렌더 | 현 문구, 시드 S | `arm_b/<shot>.png` 신규 생성, 캐시 조회 **0회** | 렌더 실패 시 그 샷만 스킵하고 기록 |
| arm C 렌더 | 수정 문구, **같은 시드 S** | `arm_c/<shot>.png`, 지시문 문자열이 B와 **정확히 한 곳** 다름 | 두 곳 이상 다르면 실패 |
| 지시문 프로비넌스 | 각 arm·각 패스 | 실제 전송된 `placement_instruction` 원문과 sha256을 기록 | 기록 실패는 렌더를 무효화 |
| 블라인드 시트 | 3 arm × 7 샷 | 21타일, 샷마다 arm 순서 치환, 라벨은 blind id만 | 치환 키 미기록 시 시트 무효 |
| 프리플라이트 | ComfyUI 상태 | 렌더 전 1회 통과 확인 | 실패 시 HALT |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/shot_recompose.py:52-56` -- `_DEPTH_PHRASE`. **수정 대상은 `"near"` 한 줄뿐**
- `src/yt_flow/pipeline/nodes/shot_recompose.py:61-80` -- `placement_instruction`. 접지·화풍 절이 **이미 있다**
- `src/yt_flow/pipeline/nodes/shot_recompose.py:150` -- `recompose_shot`. **캐시 검사가 없다** — 항상 렌더한다. B·C는 이 함수를 직접 부른다
- `src/yt_flow/pipeline/nodes/shot_recompose.py:88-100` -- `_load_workflow`. 복사본도 `ytflow_verified_recompose_qwen: true` 가 있어야 로드된다(시드 레버가 여기에 걸린다)
- `src/yt_flow/services/recompose_service.py:550-561` -- digest 계산과 `rendered = not out.exists()`. **함정의 위치**
- `src/yt_flow/services/recompose_service.py:32-38` -- `CARD_LOOKS`. 키가 없으면 그 샷은 스킵된다
- `src/yt_flow/services/recompose_service.py:448` -- `_preflight`. 렌더 전 1회 호출
- `data/workflows/comfyui_shot_recompose_qwen_api.json` -- `sampler.seed = 0` 이 **유일한 시드**다. 코드에 시드 파라미터가 없다
- `_bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py:62-69,84,432,595-598` -- 재사용할 조각: 인스트루먼트 임포터 · `_blind_id` · 리프레이밍 체인 · 블라인드 복사
- `scripts/score_shot_narration.py:105,113,256` -- `_CARD_NOTE`가 `BLIND_PROMPT`에 박혀 *"인물 부재는 결함이 아니다"* 라고 말한다 — **접지·척도 질문에 적대적**이므로 쓰지 않는다
- `workspace/4b35c0ed-8a1e-4448-8594-11bd9997376d/images/scene_{n:03d}_{shot}.png` -- 깨끗한 플레이트. 체크포인트의 `image_path`는 **이미 recompose된 프레임**이라 쓸 수 없다
- `_bmad-output/implementation-artifacts/14-3-art-style-contract/VERDICT.md` §3 -- 합성 부류 5건의 출처

## Tasks & Acceptance

**Execution:**
- [x] `.../14-9-recompose-placement-scale/PREREGISTRATION.md` -- 표적 7샷·3 arm 정의·**B와 C의 시드 공유**·판정 질문·성공 기준을 **점수를 보기 전에** 고정. 기준을 결과에 맞춰 다시 쓰지 않는다
- [x] `.../14-9-recompose-placement-scale/candidates.md` -- `_DEPTH_PHRASE["near"]` 후보 2~3개를 **텍스트로 스크리닝**(부정 절 추가 금지, 신체를 위치 참조로 되돌리는 형태 금지 — `gotcha_an-instruction-to-draw-the-trace-brings-the-body-back`). 하나를 고르고 이유를 적는다. GPU 0
- [x] `.../14-9-recompose-placement-scale/run_arms.py` -- 3-arm 하네스. **`recompose_shot`을 직접** 호출(캐시 우회), 출력은 이 디렉터리, `recompose_service._preflight` 1회. arm A는 디스크에서 퍼블리시. 세 arm 모두 `_zoompan_filter(_FUSION_STILL_SPEC, 1.0)` 통과. 각 패스의 `placement_instruction` **원문 + sha256** 기록
- [x] `.../14-9-recompose-placement-scale/run_arms.py` (digest 게이트) -- 렌더 **전에** arm A의 16-hex를 재현 검증. 불일치 시 HALT
- [x] `data/workflows/comfyui_shot_recompose_qwen_seed<S>.json` -- 시드 레버. 원본 복사 + `sampler.seed` 변경 + `ytflow_verified_recompose_qwen: true` 유지. **B와 C가 이 파일 하나를 공유한다**
- [x] `src/yt_flow/pipeline/nodes/shot_recompose.py` -- `_DEPTH_PHRASE["near"]`를 채택 후보로 교체. 그 위에 **날짜 붙은 근거 주석**(무엇이 양립 불가였는지, 무엇으로 검증했는지)
- [x] `src/yt_flow/config.py:554-560` -- "KNOWN DEFECT SHIPPED WITH THIS FLIP"을 **해소로 갱신**하되 원문은 취소선 보존(`gotcha_recorded-root-cause-can-be-inverted`)
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- `S00803` 척도 행을 해소로 갱신. `S00105` 행은 Jay 미지목이므로 이 런의 결과로 판별
- [x] `.../14-9-recompose-placement-scale/blind_sheet.py` -- 21타일 블라인드 시트. **샷마다 arm 순서 치환** + 치환 키를 `sheet_key.json`에 기록. 타일 라벨은 blind id만
- [x] `tests/pipeline/nodes/test_shot_recompose.py` -- 수정된 `near` 문구가 지시문에 실리는지, `mid`/`far`는 **무변**인지 고정. 문구를 테스트에 통째로 박지 마라(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`) — 양립 불가 조건("close to camera"와 "head to feet"가 같은 절에 공존)이 **없음**을 단언한다
- [x] `.../14-9-recompose-placement-scale/report.md` -- 3 arm 결과, digest 재현 여부, 지시문 sha 대조, 10.1e 슬레이트 재검증 상태, **미주장 목록**

**Acceptance Criteria:**
- Given 표적 7샷, when digest 게이트를 돌리면, then 각 샷의 재계산 digest가 arm A 파일명의 16-hex와 **일치**하거나 그 샷이 대조 불가로 **명시 제외**된다
- Given arm B와 arm C, when 지시문 원문을 대조하면, then 두 문자열이 **정확히 `_DEPTH_PHRASE["near"]` 치환 한 곳**에서만 다르고 시드 워크플로 파일이 동일하다
- Given `depth != "near"` 인 샷, when B와 C를 렌더하면, then 두 지시문이 **완전히 동일**하다(그 샷은 이 편집의 무효 대조군이다)
- Given 3 arm × 7 샷, when 블라인드 시트를 만들면, then 21타일의 arm 순서가 샷마다 다르고 `sheet_key.json` 없이는 어느 타일이 어느 arm인지 알 수 없다
- Given 렌더가 끝났을 때, when `workspace/4b35c0ed.../recomposed/` 를 확인하면, then **파일 수와 mtime이 렌더 전과 동일**하다(arm A 무손상)
- Given `uv run pytest tests/pipeline/nodes/test_shot_recompose.py`, when 돌리면, then `mid`/`far` 지시문이 이 스토리 이전과 바이트 동일하다
- Given 사람 판정이 아직 없을 때, when `## Auto Run Result`를 쓰면, then "고쳤다"가 아니라 **"판정 대기"** 로 적힌다

## Spec Change Log

## Review Triage Log

## Design Notes

**digest가 프롬프트도 시드도 해싱하지 않는다 — 이것이 이 스토리 최대의 함정이다.**
`recompose_service.py:550-554`의 digest 입력은 **플레이트 바이트 · 카드 경로 · 배치 필드**
셋뿐이다. 워크플로 파일도, 지시문 텍스트도, 시드도 들어가지 않는다. 그러므로
`recompose_run_shots`로 arm C를 렌더하면 **digest가 A와 같아 캐시 히트가 나고 `recompose_shot`이
아예 호출되지 않는다.** 에러도 로그도 없고 `stats`는 `recomposed: 7`을 찍는다 — 즉 **arm C가
조용히 arm A가 된다.** 그래서 B·C는 캐시 검사가 없는 `shot_recompose.recompose_shot`을 직접
부르고 출력도 `recomposed/` 밖에 쓴다.

**시드 레버가 코드에 없다.** 워크플로 JSON의 `sampler.seed = 0`이 유일한 시드이고
`build_single_pass`는 plate/card/positive만 쓴다(`recompose_shot`의 `salt`는 ComfyUI 업로드
파일명일 뿐 샘플러에 안 닿는다). 그래서 시드를 바꾸려면 **워크플로 파일을 복사**해야 하고,
`_load_workflow`가 `ytflow_verified_recompose_qwen: true`를 요구하므로 복사본에 그 키를 남긴다.

**체크포인트의 `image_path`를 플레이트로 쓰면 안 된다.** run `4b35c0ed`은 recompose가 켜진 채
완주했고 서비스의 제자리 재작성이 체크포인트에 박혔다 — 7샷 전부 `image_path`가
`recomposed/S00xxx_<digest>.png`다. 깨끗한 플레이트는 `images/scene_{n:03d}_{shot}.png`에 있다.

**arm A의 입력을 증명할 방법이 digest 재현뿐이다.** 이 런은 14.3 **이전**에 렌더됐으므로
사이드카에 `recompose` 블록이 없다(40개 사이드카 전수 확인, 0건). 카드 경로는 어디에도
기록돼 있지 않다. 따라서 카드를 재해결해 digest를 재계산하고 파일명과 대조하는 것이
**B가 A의 대조라는 유일한 증거**다. 이것이 Block If인 이유다.

**13.2 인스트루먼트의 `BLIND_PROMPT`를 그대로 쓰지 마라.** 거기 박힌 `_CARD_NOTE`가
*"이것은 배경 플레이트이고 인물 부재는 결코 결함이 아니다"* 라고 말한다 — 모든 프레임에
인물이 있는 접지·척도 질문에 **적대적**이다. 10.1e도 이걸 알고 남겼고 그 사실을 기록했다.

**무효 대조군이 공짜로 붙는다.** 표적 7샷 중 `depth != "near"` 인 샷은 이 편집의 영향을 받지
않아야 하므로 B와 C의 지시문이 **완전히 같아야 한다**. 그 샷들에서 차이가 보이면 그것은
편집 효과가 아니라 렌더 비결정성이고, 그 크기가 곧 이 실험의 노이즈 하한이다.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_shot_recompose.py tests/services/test_recompose_service.py -q` -- expected: 전량 통과, `mid`/`far` 문구 불변
- `uv run pytest -q` -- expected: `test_render_pose_guides.py` PNG SHA 1건만 실패(14.5가 기존 결함으로 기록)
- `uv run ruff check src tests scripts` -- expected: clean
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0
- `uv run python .../14-9-recompose-placement-scale/run_arms.py digest-gate` -- expected: 7/7 재현 또는 명시 제외
- `uv run python .../14-9-recompose-placement-scale/run_arms.py render --arm b --arm c` -- expected: 14장 신규, `recomposed/` 무변
- `uv run python .../14-9-recompose-placement-scale/blind_sheet.py` -- expected: 21타일 시트 + `sheet_key.json`
- `curl -s -m 5 http://127.0.0.1:8188/system_stats` -- expected: 200, argv에 `--lowvram`·`--cache-lru`, `--disable-smart-memory` 없음

**Manual checks (if no CLI):**
- **픽셀 판정은 Jay가 한다.** 블라인드 시트를 내고 `## Auto Run Result`에는 **판정 대기**로 적는다. 이 에픽에서 Claude 단독 시각 라벨은 세 번 뒤집혔다(14.2 인계 2건 · 14.2 미검출 1건 · 14.3 `S00105`).
- `nvidia-smi`를 진단에 쓰지 마라 — 이 박스는 AMD(gfx1100/24GB/ROCm)다.
