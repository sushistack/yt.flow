---
title: 'Story 14.0 §4-4: 앵글 충돌 확인 — 필드↔프롬프트는 일치했고, 진짜 원인은 다른 층이다'
type: 'bugfix'
created: '2026-08-21'
baseline_revision: '40868d6'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** 리서치 문서 §4-4와 epics Story 14.2가 *"`image_prompt` 본문이 `camera_angle` 필드를 덮어쓴다"* 를 ②원근 결함의 기계적 원인으로 지목하고 **"먼저 확인할 것"** 을 지시했다. 확인 결과 그 전제는 거짓이다 — run `4b35c0ed` 43샷 전부에서 필드와 `image_prompt` 슬롯-1 서술이 **일치**하고(불일치 0건), 필드는 애초에 렌더러에 도달조차 하지 않는다(`image.py:212`는 `shot["image_prompt"]`만 대입한다). 거짓 원인을 그대로 두면 14.2가 그 위에 세워진다.

**Approach:** 측정을 재산출 가능한 스크립트로 남기고, 거짓 전제를 planning 문서와 코드 주석에서 제거하고, 코드 읽기가 실제로 드러낸 조립 결함 **2건만** 고친다 — (a) `camera_angle`이 형제 필드 전부와 달리 무검증·무정규화 free string이라 대소문자 민감 소비자(R3)를 조용히 건너뛸 수 있다, (b) `_fallback_prompt`는 `"static wide shot"`을 하드코딩하면서 `camera_angle`은 LLM 값을 그대로 둬 **확정적으로** 어긋난다. 렌더와 프롬프트 파일은 건드리지 않는다(GPU 0).

## Boundaries & Constraints

**Always:**
- 새 어휘 상수는 `prompts/scenario/visual_breakdown.md:215`의 7값과 표기까지 바이트 일치(`POV`는 대문자다 — 순진한 `.lower()`는 라운드트립하지 않는다).
- 어휘 밖 값은 스테이지를 실패시키지 않고 **경고 후 `None`** — `_resolve_camera_movement`/`resolve_mood`가 이미 확립한 철학(AD-10 no-silent-degradation).
- 부재(`None`/비문자열)는 결함이 아니므로 경고하지 않는다. 경고는 **존재하지만 어휘 밖**일 때만.
- 측정치는 재산출 스크립트·대조군과 함께 커밋한다(`gotcha_a-measurement-without-its-sample-band`).
- 정정한 planning 문서는 원래 주장을 지우지 말고 **반증으로 표시**한다.

**Block If:**
- 결함을 닫으려면 렌더를 다시 돌려야 한다는 판단이 서면 HALT — 이 스토리의 계약은 GPU 0이다.
- `camera_angle`을 ComfyUI 포지티브 프롬프트에 주입해야 한다는 결론에 도달하면 HALT — 그것은 렌더 변경이고 14.2/14.3 소관이며 프롬프트 사전 스크리닝 규율을 탄다.

**Never:**
- `camera_angle`을 이미지 생성 프롬프트에 주입하지 않는다.
- `image_prompt` 본문에서 앵글을 파싱해 필드를 덮어쓰는 리컨실러를 만들지 않는다 — **측정 결과 할 일이 0건**인 코드다.
- 프롬프트 파일(`prompts/**`)을 수정하지 않고 Langfuse에 시딩하지 않는다.
- `negative_prompt`, 스톡 플레이트 배정(`image.py:650-668`), recompose 프롬프트를 건드리지 않는다 — 각각 14.4/14.1·14.2/14.3 소관.
- R3의 인라인 리터럴 3개를 7값 어휘로 확장하지 않는다 — 부분집합인 것이 설계다.

## I/O & Edge-Case Matrix

`_resolve_camera_angle(raw: object) -> str | None`:

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 정상 어휘 | `"wide"`, `"POV"` | 문서 표기 그대로 반환 | No error expected |
| 미스케이싱·공백 | `"Wide"`, `" pov "`, `"Close-Up"` | 문서 표기로 정규화 → `"wide"`, `"POV"`, `"close-up"` | 경고 없음(정규화가 처리) |
| 어휘 밖 문자열 | `"dutch angle"`, `"bird's eye"` | `None` | `logger.warning` 1건, 스테이지 계속 |
| 부재 / 비문자열 | 키 없음, `None`, `3` | `None` | 경고 없음 — 부재는 결함이 아니다 |
| fallback 프롬프트 발동 | 씬 첫 문장 `image_prompt`가 비어 있고 병합할 앞 샷이 없음 | `camera_angle == "wide"`, `"static wide shot"` 하드코딩과 일치 | No error expected |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/scenario_chain.py:3287` -- `camera_angle`의 **유일한 생산자**, `isinstance(str)` 무검증 passthrough. 수정 지점.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:315-328` -- `_resolve_camera_movement`. 따라야 할 형제 패턴(유효값 승리 / 존재하나 무효면 경고 + 폴백).
- `src/yt_flow/pipeline/nodes/scenario_chain.py:83` -- `_LOCATION_KEY_CANONICAL`. 대소문자 혼재 어휘의 canonical-map 선례.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:3218`, `:3271-3276` -- `_fallback_prompt`("static wide shot" 하드코딩)와 그 호출부의 `raw_shot` 사본 생성 지점. (b) 수정 지점.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:475` -- R3 docstring의 거짓 전제 *"camera_angle is baked into the rendered background"*. 정정 지점.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:535-549` -- R3. `"wide"`/`"close-up"`/`"over-the-shoulder"` **대소문자 민감 정확일치** 소비자 = 정규화의 수혜자.
- `src/yt_flow/domain/state.py:308-309` -- `ShotData.camera_angle`(주석 없음) vs `camera_movement`(어휘 주석 있음). 비대칭이 전제 오해를 오래 살려둔 원인.
- `src/yt_flow/services/character_service.py:1500` -- angle-selection LLM 카탈로그로 값을 넘기는 비분기 소비자(정규화된 라벨의 수혜자).
- `src/yt_flow/pipeline/nodes/image.py:212`, `:734-735` -- 포지티브 프롬프트는 `shot["image_prompt"]` **대입**뿐. 필드가 픽셀에 도달하지 않는다는 증거.
- `prompts/scenario/visual_breakdown.md:72`(슬롯-1 의무), `:215`(7값 어휘) -- **읽기 전용 참조**, 변경 금지.
- `_bmad-output/planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md:122-125` -- 반증 대상 §4-4.
- `_bmad-output/planning-artifacts/epics.md` Story 14.0 §4-4 항목 / Story 14.2 -- 같은 거짓 전제를 두 번 더 담고 있다.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py` -- 신규. `yt_flow.db` 체크포인트에서 한 런의 `scenes`를 읽어 샷별 `camera_angle` ↔ `image_prompt` 슬롯-1 앵글 구절을 대조하고, 일치/불일치/판정불가와 오탐 후보를 표로 출력한다. 런 id를 인자로 받는다 -- 측정치는 재산출 스크립트 없이는 무효.
- [x] `_bmad-output/implementation-artifacts/14-0-angle-conflict/report.md` -- 신규. run `4b35c0ed` 43샷 실측(일치 43, 불일치 0), 정규식 오탐 목록(`overhead`/`from above`/`looking down`은 **조명·설비 어휘**이고 카메라 프레이밍이 아니다), 그리고 §4-4가 인용한 두 사례의 실제 값(`S00100` 필드 `medium` + 본문 `"medium shot"`, `S00803` 필드 `low-angle` + 본문 `"low-angle shot looking up from the floor"` — **둘 다 일치**). `S00100`을 근거로 진짜 메커니즘을 14.2에 인계: 슬롯-1 앵글 토큰 2단어 대 나머지 ~85단어의 **내용 질량**(바닥·천장·부감 조명 서술)이 프레이밍을 결정한다 -- 14.2가 거짓 원인 위에 세워지는 것을 막는다.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- `_LOCATION_KEY_CANONICAL` 곁에 7값 canonical map 상수를 추가하고 `_resolve_camera_angle`을 `_resolve_camera_movement` 바로 옆에 정의한다. `:3287`을 그 함수 호출로 교체. fallback 경로(`:3271-3276`)의 `raw_shot` 사본에 `"camera_type": "wide"`를 추가. `:475` docstring의 거짓 전제를 실측으로 교체(필드는 프롬프트 텍스트의 충실한 라벨이지만 픽셀에는 도달하지 않으며, R3가 depth만 고치는 이유는 그것이 아니라 8.12 분포 보존이다) -- 형제 필드 전부가 가진 검증을 유일한 예외에 부여하고, 확정 어긋남 하나를 없애고, 다음 사람이 같은 오해를 물려받지 않게.
- [x] `src/yt_flow/domain/state.py:308` -- `camera_angle`에 어휘 출처 한 줄 주석 -- `camera_movement`와의 비대칭이 오해를 살려둔 원인.
- [x] `_bmad-output/planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md` 와 `_bmad-output/planning-artifacts/epics.md` -- §4-4 항목(리서치 §4의 미해결 4번, epics Story 14.0의 (4), Story 14.2의 "부수 결함" 문장) 세 곳을 정정한다. 원래 주장을 지우지 말고 **반증됨 + 실측 근거 + 실제 메커니즘 + 후속 소관(14.2)** 을 덧붙인다. 리서치 §5의 착수 권고 1번("§4-4 앵글 확인")은 완료로 표시하고 다음 순번을 남긴다 -- 거짓 원인이 두 문서에 세 번 적혀 있어 하나만 고치면 다시 인용된다(`gotcha_recorded-root-cause-can-be-inverted`).
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- I/O 매트릭스 5행 전부에 대한 단위 테스트 추가(정상·미스케이싱·어휘밖+경고·부재·fallback 경로의 `camera_angle == "wide"`) -- 경고 여부까지 단정한다(`caplog`).

**Acceptance Criteria:**
- Given run `4b35c0ed`의 체크포인트, when `measure_angle_agreement.py`를 그 런 id로 실행하면, then 43샷 중 필드↔슬롯-1 불일치 0건을 출력하고 report.md의 수치와 일치한다.
- Given 어휘 밖 `camera_type`을 담은 LLM 응답, when `build_scenes`가 돌면, then 스테이지는 성공하고 해당 샷의 `camera_angle`은 `None`이며 경고 로그 1건이 남는다.
- Given 대소문자만 다른 `camera_type`(예: `"Over-The-Shoulder"`), when `build_scenes`가 돌면, then `camera_angle`은 `"over-the-shoulder"`가 되고 R3가 그 샷에 대해 발화한다(정규화 이전에는 조용히 건너뛰었다).
- Given 기존 43샷 실측 입력, when 정규화를 적용하면, then 43샷의 `camera_angle` 값이 정규화 이전과 **바이트 동일**하다(회귀 없음 — 이 런은 이미 전부 문서 표기였다).
- Given planning 문서 정정 후, when 리서치 문서 §4-4와 epics Story 14.0/14.2를 읽으면, then 원래 주장이 삭제되지 않은 채 **반증됨**으로 표시되고 실제 메커니즘과 후속 소관(14.2)이 적혀 있다.

## Spec Change Log

## Review Triage Log

### 2026-08-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 18: (high 1, medium 10, low 7)
- defer: 2: (high 0, medium 2, low 0)
- reject: 6: (high 0, medium 2, low 4)
- addressed_findings:
  - `[high]` `[patch]` "`camera_angle`은 픽셀에 도달하지 않는다"가 거짓 — `character_service.py:1500` → `_select_entity_angles` → `_ANGLE_FIELD_NAMES` → `angle_*_path` PNG 합성 경로가 있고, 원래 docstring의 *"and entity angle selection"* 절이 옳았는데 이 변경이 그것을 지웠다. 코드 docstring·`state.py` 주석·report §1/§6·epics·research 다섯 곳 전부 "배경 렌더러 프롬프트에는 미도달, 캐스트 카드 앵글 선택에는 도달"로 정정. 정규화의 실제 대가(어휘 밖 값이 카탈로그에 `""`로 도착; 이 런 0건)도 명시.
  - `[medium]` `[patch]` "진짜 메커니즘 = 내용 질량"이 n=1·대조군 0·경쟁가설 미검토로 확정 선언돼 있었다. `S00100`은 조명 어휘 3종을 모두 가진 유일한 샷이므로 (b) 조명 어휘 앵글 오독이 동등한 후보다. report §5·epics 14.2·research 블록인용을 동등 지위 두 가설 + 판별 시험 제안으로 강등.
  - `[medium]` `[patch]` report §4 반사실이 ~7× 틀렸다(순진 정규식 40/43 주장 → 실측 22/43, 미검출 3건 주장 → 20건 + 거짓 CONFLICT 1건). 스크립트가 `naive:` 행을 매 실행 출력하도록 바꿔 재산출 가능하게 만들고 표를 실패 유형별로 분리.
  - `[medium]` `[patch]` report §3이 코드와 규칙 둘 다 과장했다. `_LIGHTING_DECOYS`는 `detect()`가 조회하지 않는 감사 출력이고, `overhead`가 항상 조명이라는 범주 규칙은 `S00504` 슬롯-1 *"high-angle overhead view"*·`S00404`/`S00702` *"view down"* 이 반증한다. 위치 의존 규칙으로 재서술.
  - `[medium]` `[patch]` 반증 게이트가 발화 불가였다 — CONFLICT 0이면 항상 exit 0이라 전량 UNDECIDABLE·0샷도 초록. 종료코드 분리(0 판정 성립+무충돌 / 1 충돌 / 2 사용법 / 3 측정 불가)와 report §7 문서화.
  - `[medium]` `[patch]` 표본 밴드가 스크립트 출력으로 재현 불가였다(`except Exception: continue`가 역직렬화 실패를 삼키고, 실제 사용한 thread/checkpoint를 안 찍고, 접두사 다중 매치를 검사 안 함). 헤더에 thread_id·checkpoint_id 출력, 스킵 건별 stderr, 다중 매치는 측정 거부.
  - `[medium]` `[patch]` `_CAMERA_ANGLES`가 프롬프트 파일에서 손으로 베낀 리터럴인데 고정 테스트가 없었다(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). `visual_breakdown.md`의 어휘 줄을 파싱해 집합 동일성을 단정하는 테스트 추가(파일 부재 시 skip).
  - `[medium]` `[patch]` `epic-14-context.md`가 반증된 전제를 기술 결정으로 그대로 담고 있었다 → 같은 방식으로 취소선 + 반증 주석.
  - `[medium]` `[patch]` "같은 LLM 턴이니 어긋날 수 없다"는 구조적 주장이 성립하지 않는다 — `visual_breakdown.md:72`가 `dutch angle` 등 `camera_type` 대응물 없는 슬롯-1 표현을 코칭한다. 43/43은 경험적 사실로 격하하고, 어휘 버킷 밖 수식어 14/43(목록 포함)과 `dutch angle`을 14.2 인계 잠재 결함으로 기록.
  - `[medium]` `[patch]` 인계가 매달린 전제가 미기재였다 — `location_key` 31/43 + `stock_plate_substitution_enabled=False`. 이 플래그가 켜지면 31샷은 `image_prompt`를 무시하므로 §5 인계가 무력화된다. 표본 밴드와 §5·epics 14.2에 명시.
  - `[medium]` `[patch]` report §1이 측정한 것은 어휘 버킷 단위 일치인데 "두 채널이 같은 말"로 서술돼 있었다 → 버킷 granularity 절 신설.
  - `[low]` `[patch]` `_resolve_camera_angle` docstring이 `_resolve_camera_movement`와 "동일 철학"이라 주장했으나 그 형제는 `3`/`[]`/`""`에도 경고한다 → 의도적 분기와 이유를 문서화.
  - `[low]` `[patch]` 어휘 밖 테스트가 "one warning"을 이름에 걸고 비어있지 않음만 단정 → 정확히 1건 단정.
  - `[low]` `[patch]` 테스트 섹션 헤더에 spec 경로 포인터 추가(AC3/AC4 참조 해소).
  - `[low]` `[patch]` `detect()`의 `min()`이 동일 위치에서 앵글 이름 알파벳순으로 동점 처리 → 최장 매치 우선.
  - `[low]` `[patch]` 조명 어휘 표의 중복 계수(`lit from above` ⊂ `from above`), 0건 증거행(`looking down at`), 15 vs 20 불일치 정리.
  - `[low]` `[patch]` epics 항목 (4) 삽입 블록의 매달린 쉼표 → 마침표.
  - `[low]` `[patch]` `# ponytail:` 주석이 "다른 독자는 분기하지 않는다"고만 적어 같은 모듈의 R3가 실제로 비교한다는 사실을 빠뜨렸다 → 모듈 내 비교 소비자 존재를 명시.
  - `[medium]` `[patch]` epics 항목 (4)에 "이 항목이 닫힌 것이 14.0이 닫힌 것은 아니다((1)(2)(3)(5) 미해결, 14.2/14.3/14.5 게이트 유지)" 절 추가 — 로드맵 포인터 오독 방지.

## Design Notes

**왜 리컨실러를 만들지 않는가.** 착수 전 가설은 "본문이 필드를 덮어쓴다"였고, 그렇다면 처방은 본문에서 앵글을 파싱해 필드를 재도출하는 것이었다. 실측이 그 코드를 죽였다 — 43/43이 이미 일치한다. 두 채널이 어긋나지 않는 이유는 조립이 잘 돼서가 아니라 **같은 LLM 턴이 둘을 함께 쓰기 때문**이고(`visual_breakdown.md:72`가 슬롯-1을, `:215`가 필드를 같은 응답에서 요구한다), 그래서 코드로 화해시킬 대상이 없다.

**그렇다면 `S00100`은 왜 부감으로 렌더됐는가.** 필드도 `medium`, 슬롯-1도 `"medium shot"`이다. 나머지 프롬프트가 바닥과 천장을 서술한다 — *"the center floor between two scuff-marked standing positions lit harshly from above"*, *"polished concrete with hairline cracks and a central drain grate"*, *"twin rows of ceiling-mounted fluorescent tubes"*. SDXL은 앞의 두 단어보다 뒤의 85단어를 따른다. 즉 ②의 원인은 **필드↔텍스트 불일치가 아니라 텍스트 내부의 내용↔프레이밍 불일치**이고, 이것은 어포던스 문제이므로 14.2의 소관이며 프롬프트 재작성 층(리서치 §4-3의 미탐색 층)과 같은 개입 지점을 공유한다. 이 스토리의 실제 소득은 ②의 절반을 끝낸 것이 아니라 **②에서 가장 값싼 가설을 GPU 0으로 제거하고 다음 가설을 지목한 것**이다.

**오탐 주의.** 첫 측정은 15샷을 "두 번째 앵글 구절 있음"으로 표시했다. 전부 오탐이었다 — `overhead surgical lamp`, `lit from above`, `overhead fluorescent tubes`는 조명 서술이다. 재산출 스크립트는 이 구절들을 앵글 신호로 세지 않아야 하고, report.md는 왜 세지 않는지를 적어야 한다.

```python
# 형태 예시 (구현이 이 형태를 따를 필요는 없다)
_CAMERA_ANGLES = ("wide", "medium", "close-up", "low-angle", "high-angle", "over-the-shoulder", "POV")
_CAMERA_ANGLE_CANONICAL = {a.lower(): a for a in _CAMERA_ANGLES}  # POV가 대문자라 map이 필요하다
```

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q` -- expected: 신규 5건 포함 전부 통과
- `uv run python _bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py 4b35c0ed` -- expected: 43샷, 불일치 0, report.md 수치와 동일
- `uv run pytest tests/ -q -k "scenario or state_imports"` -- expected: 회귀 없음

**Manual checks (if no CLI):**
- `git diff prompts/` 가 비어 있는지 확인 -- 이 스토리는 프롬프트를 바꾸지 않는다는 계약.

## Auto Run Result

Status: done — **전제 반증**. Story 14.0 §4-4는 "충돌 확인 후 조립 버그면 수정"이었고, 확인 결과 충돌은 없었다.

### 구현한 변경

1. **측정(GPU 0)** — run `4b35c0ed` 43샷 전수: `camera_angle` 필드 ↔ `image_prompt` 슬롯-1 앵글 **일치 43 / 불일치 0 / 판정불가 0**(7값 어휘 버킷 단위). 재산출 스크립트가 매 실행마다 순진-정규식 반사실(22/43)과 조명 어휘 감사 목록을 함께 출력한다.
2. **조립 결함 2건 수정** — (a) `camera_angle`이 형제 필드 전부와 달리 무검증 free string이라 미스케이싱 값이 R3의 대소문자 민감 정확일치를 조용히 건너뛸 수 있었다 → `_resolve_camera_angle`(7값 정규화 / 어휘 밖 경고 + None / 부재는 침묵). (b) `_fallback_prompt`가 `"static wide shot"`을 하드코딩하면서 `camera_angle`은 LLM 값을 남겨 **확정적으로** 어긋났다 → 백필 시 `wide`로 통일.
3. **거짓 전제 제거** — 같은 주장이 네 문서에 네 번 적혀 있었고(리서치 §4-4, epics 실측근거 bullet, epics 14.0 (4), epics 14.2, + 이번 세션에 만든 `epic-14-context.md`) 전부 원문 보존 + 반증 주석 처리. 리서치 §5 착수순서 1번 완료 표시.
4. **14.2 인계** — ②의 개입 지점은 필드↔텍스트 조립이 아니라 **프롬프트 텍스트 내부**로 확정. 그 안의 메커니즘은 n=1로 미확정이며 후보 둘(내용 질량 / 조명 어휘 앵글 오독)을 동등 지위로 넘기고 판별 시험을 제안했다. 잠재 결함 둘도 함께 인계: `dutch angle`은 프롬프트가 승인한 슬롯-1 표현인데 `camera_type` 대응물이 없고, 슬롯-1 머리 43개 중 14개가 버킷 밖 수식어를 이미 달고 있다(어포던스 게이트가 정확히 관심 갖는 정보).

### 변경 파일

- `src/yt_flow/pipeline/nodes/scenario_chain.py` — 7값 canonical map + `_resolve_camera_angle`, 생산 지점 배선, fallback 경로 `camera_type="wide"`, R3 docstring의 거짓 전제 정정.
- `src/yt_flow/domain/state.py` — `ShotData.camera_angle`에 어휘 출처 + 도달 경로 주석(배경 렌더러 미도달 / 캐스트 카드 앵글 선택 도달).
- `tests/pipeline/nodes/test_scenario_chain.py` — 21건 추가: I/O 매트릭스 5행, 미스케이싱이 이제 R3에 닿는다는 회귀 테스트, 프롬프트 파일 어휘 고정 테스트.
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py` — 재산출 스크립트(종료코드 0/1/2/3, 표본 밴드 출력, 반사실 동시 출력).
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/report.md` — 증거 보고서.
- `_bmad-output/planning-artifacts/epics.md`, `.../research/technical-perspective-population-narration-match-2026-08-17.md`, `_bmad-output/implementation-artifacts/epic-14-context.md` — 반증 기록.

### 리뷰 결과

intent_gap 0 · bad_spec 0 · **patch 18 적용**(high 1, medium 10, low 7) · defer 2 · reject 6. HIGH 1건은 이 변경 자신이 만든 거짓 주장이었다 — "`camera_angle`은 픽셀에 도달하지 않는다"가 캐스트 카드 앵글 선택 경로를 놓쳤고, 원래 docstring이 갖고 있던 옳은 절을 지웠다. 반증 스토리가 새 거짓 주장을 다섯 곳에 심을 뻔했다.

### 검증

- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q` → **842 passed**
- `uv run pytest tests/ -q -k "scenario or state_imports"` → **1024 passed**, 2152 deselected
- `uv run python .../measure_angle_agreement.py 4b35c0ed` → 43샷 / AGREE 43 / naive 22 / exit **0**; 없는 런 → exit **3**(게이트 발화 확인)
- `uv run ruff check src tests` → clean · `git diff --stat prompts/` → 빈 출력(프롬프트 무변경 계약 유지)
- pyright 신규 경고 0건(보고된 것은 전부 baseline `40868d6`에 이미 존재)

### 잔여 리스크

- **43/43은 이 런 하나의 경험적 사실**이고 구조적 보장이 아니다. `visual_breakdown.md:72`가 `camera_type` 대응물 없는 슬롯-1 표현을 코칭하므로 다음 런에서 어긋날 수 있다. 재측정은 GPU 0이므로 런마다 값싸게 가능하다.
- **§5의 인계는 `stock_plate_substitution_enabled=False`에 매달려 있다.** 켜지면 `location_key`를 가진 31/43 샷이 `image_prompt`를 무시하므로 "본문이 서술하는 시점" 접근이 그 샷들에 무력해진다. 14.1/14.2가 이 플래그를 켜는 스토리다.
- **정규화는 앵글 선택 LLM의 입력을 바꾼다** — 어휘 밖 값이 free text 대신 `""`로 도착한다. 이 런 발생 0건이라 라이브 영향은 없었으나 렌더 무영향은 아니다. 독자 전수조사(R3 + 카탈로그 2명) 후 의도적으로 남긴 선택.
- **②는 닫히지 않았다.** 이 스토리의 소득은 가장 값싼 가설을 GPU 0으로 제거하고 다음 가설을 지목한 것이다. 14.0의 미해결 (1)(2)(3)(5)는 그대로이고 14.2/14.3/14.5 게이트도 유지된다.
