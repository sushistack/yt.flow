# Story 14.0 §4-4 — 앵글 충돌은 없었다 (run `4b35c0ed`, 43샷 실측)

- 측정일: 2026-08-21 · GPU 사용 0 · 렌더 재실행 0
- 재산출: `uv run python _bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py 4b35c0ed`
- 표본 밴드 (스크립트가 헤더에 출력하는 값 그대로):
  - `thread_id 4b35c0ed-8a1e-4448-8594-11bd9997376d`
  - `checkpoint_id 1f19a3de-374f-68db-800f-3033ac398867` — `channel_values["scenes"]`가 비어 있지 않은 **마지막** 체크포인트
  - 접두사가 두 개 이상의 `thread_id`에 걸리면 스크립트는 측정하지 않고 종료코드 3으로 죽는다(런 혼합 금지). 역직렬화 실패 체크포인트는 stderr에 건별로 찍는다 — 이 런에서는 0건.
  - 9씬 / 43샷 전수(표본 추출 없음)
  - **`stock_plate_substitution_enabled = False`** (`src/yt_flow/config.py:308`, 코드 기본값이고 이 런도 그대로). 이 값이 `True`였다면 `location_key`를 가진 샷은 `image_prompt`를 **무시하고** 미리 만든 플레이트를 복사하므로(`image.py:645-668`, `visual_breakdown.md:209`) "본문이 서술하는 시점" 측정 자체가 무의미해진다. 이 런의 43샷 중 `location_key`를 가진 것은 **31샷**이다 — §5의 인계는 이 플래그가 꺼져 있다는 전제에 매달려 있다.

## 1. 결론

**리서치 §4-4와 epics Story 14.0 (4) / Story 14.2가 지목한 "본문이 `camera_angle` 필드를 덮어쓴다"는 전제는 거짓이다.**

| 판정 | 샷 수 |
|------|-------|
| AGREE (필드 == 슬롯-1 앵글) | **43** |
| CONFLICT | **0** |
| UNDECIDABLE (필드 없음 / 슬롯-1 앵글 미검출) | 0 |

값 분포(census): `medium` 10, `close-up` 9, `wide` 9, `high-angle` 6, `low-angle` 4, `over-the-shoulder` 3, `POV` 2 — 43샷 전부가
`prompts/scenario/visual_breakdown.md:215`의 문서 표기와 **바이트 일치**한다(`POV`는 대문자 그대로). 정규화를 도입해도 이 런의 값은 변하지 않는다.

### 일치는 실측 결과이고 구조적 보장이 아니다

두 채널이 같은 LLM 턴에서 나오는 것은 사실이다 — `visual_breakdown.md:72`가 슬롯-1(샷 타입 + 카메라 앵글)을, `:215`가 `camera_type` 필드를 같은 응답에서 요구한다.
그래서 코드가 화해시킬 대상이 없고, 이 스토리는 리컨실러(본문 파싱 → 필드 재도출)를 만들지 않는다: 할 일이 0건인 코드다.

**하지만 "같은 턴이니 어긋날 수 없다"는 주장은 성립하지 않는다.** 같은 턴이 **서로 다른 어휘 두 벌**을 받고 있다. `:72`는 슬롯-1 예시로
`dutch angle`, `extreme close-up`, `slow push-in medium`, `wide establishing`, `sudden POV shift`, `eye-level medium`, `surveillance high-angle`,
`high-angle looking down`, `slow pull-back wide`, `static wide`를 코칭하는데, 이 중 **`camera_type` 7값에 대응물이 없는 것이 여럿**이다
(`dutch angle`이 대표). 모델이 슬롯-1에 `dutch angle`을 쓰고 필드에 아무 값이나 고르면 두 채널은 즉시 어긋난다.
**즉 43/43은 경험적 사실이고, 구조가 보증한 것이 아니다.** 재측정은 런마다 값싸게(GPU 0) 가능하므로 이 결론은 이 런에 한정해서 읽어야 한다.

### 측정된 것은 "어휘 버킷 단위" 일치다

매처는 슬롯-1을 7값 버킷으로 접어서 필드와 비교한다. 그 과정에서 **버킷 밖 수식어는 버려진다**. 이 런의 슬롯-1 머리 43개 중 **14개**가
`camera_type`에 대응물이 없는 수식어를 이미 달고 있다:

| 수식어 | 샷 |
|--------|-----|
| `extreme close-up` (×4) | `S00101` `S00203` `S00503` `S00903` |
| `static wide` / `wide static` (×4) | `S00300` `S00500` `S00700` `S00900` |
| `view down` (×2) | `S00404` `S00702` |
| `wide establishing` | `S00603` |
| `medium two-shot` | `S00502` |
| `overhead view` | `S00504` |
| `slow pull-back` | `S00904` |

버려진 이 수식어가 **어포던스 게이트가 정확히 관심 갖는 정보**다. `extreme close-up`과 `close-up`은 같은 버킷이지만 인물을 세울 수 있느냐는 다르고,
`high-angle overhead view of containment cell floor`(S00504)는 버킷상 `high-angle` 일치인데 실제로는 바닥만 보이는 프레임이다.
**14.2가 물려받는 잠재 결함**: (a) `dutch angle`은 프롬프트가 승인한 슬롯-1 표현인데 대응 필드값이 없고, (b) 위 14건의 수식어는 버킷 일치 판정에서 소실된다.

### 필드가 픽셀에 닿는 경로는 하나 있다

`image.py:212`의 `_inject_prompts`는 포지티브 노드에 `shot["image_prompt"]`를 **대입**만 하므로(`:734-735` 호출부도 `image_prompt`/`negative_prompt`만 넘긴다),
`camera_angle`은 **배경 렌더러의 프롬프트에는 도달하지 않는다.** 그러나 **렌더에 무관(render-inert)한 것은 아니다**:
`character_service.py:1500`이 이 값을 샷별 카탈로그에 복사하고, 그 카탈로그가 `_select_entity_angles`(`character_service.py:1687`) LLM 앵글 선택의 입력이 된다.
선택 결과는 `_ANGLE_FIELD_NAMES`(`character_service.py:79-82`)를 통해 `angle_*_path` 카드 PNG로 매핑되고, 그 PNG는 프레임에 합성된다.
읽는 코드 전수: `character_service.py:1500`(앵글 선택 카탈로그), `run_service.py:116`(API 노출), `scenario_chain`의 R3(cast depth 수리).

즉 필드는 **배경 프롬프트의 라벨이면서 동시에 캐스트 카드 선택의 입력**이다. 라벨을 코드가 재작성하면 안 되는 이유는 "픽셀에 안 닿아서"가 아니라,
(a) 닿는 경로가 있고 (b) 이 런에서 일치가 실측된 채널을 어긋나게 만들기 때문이다.

## 2. §4-4가 인용한 두 사례의 실제 값

### `S00100` — 필드 `medium`, 슬롯-1 `"medium shot"` → **일치**

§4-4는 "medium 선언 vs 부감 렌더"를 필드↔본문 충돌의 증거로 들었다. 본문 첫 두 단어가 이미 `medium shot`이다. 충돌은 필드와 텍스트 사이가 아니라 **텍스트 내부**에 있다:

> medium shot, sterile containment testing chamber, … **the center floor** between two scuff-marked standing positions **lit harshly from above**
> as if staged for a single decisive action, **polished concrete with hairline cracks and a central drain grate** catching a thin film of moisture,
> **twin rows of ceiling-mounted fluorescent tubes** throwing flat white light with hard-edged shadows beneath the table, …

프롬프트 전체 119단어 중 앵글을 말하는 것은 앞의 **2단어**이고, 나머지 **117단어**는 바닥·배수구·천장 형광등을 서술한다. 왜 부감으로 렌더됐는지는 §5에서 두 가설로 갈린다.

### `S00803` — 필드 `low-angle`, 슬롯-1 `"low-angle shot looking up from the floor"` → **일치**

§4-4는 "프롬프트가 *low-angle shot looking up*으로 시작"한다는 것을 필드를 덮어쓴 증거로 읽었지만, 필드도 `low-angle`이다. 두 채널이 같은 말을 하고 있고
본문 125단어도 천장 형광등·상승하는 벽·바닥 반사로 로우앵글과 정합한다. 이 샷은 결함 사례가 아니라 **정상 사례**다.

## 3. 조명 어휘 — 감사 출력이지 필터가 아니다

첫 측정은 다수 샷을 "두 번째 앵글 구절 있음"으로 표시했고 전부 오탐이었다. 재산출 스크립트는 그 어휘를 **프롬프트 전체에 대해 세어 출력한다: 실측 23건 / 20샷.**

**이것은 필터가 아니다.** `detect()`는 `_LIGHTING_DECOYS`를 한 번도 조회하지 않는다(스크립트 `:200`은 출력 목록만 만든다).
이 단어들이 판정을 흔들 수 없는 이유는 명시적 배제가 아니라 **구조적**이다 — `detect()`는 슬롯-1만 읽고, `_SLOT1_PATTERNS`에 이 단어가 하나도 없다.
목록의 용도는 "램프를 카메라 앵글로 세지 않았다"를 **감사 가능하게** 만드는 것뿐이다.

| 구절 | 조명·설비로 읽히는 예 | 실측 |
|------|----------------------|------|
| `overhead` | `overhead surgical lamp`, `overhead fluorescent tubes` | 17샷 |
| `from above` | `lit harshly from above` (명시형 `lit … from above`는 이 구절의 부분집합이므로 별행으로 세지 않는다) | 3샷 |
| `ceiling-mounted` | `twin rows of ceiling-mounted fluorescent tubes` | 3샷 |

합계 23건 / 서로 다른 20샷(`overhead` 17샷 + `from above`가 더하는 `S00100`·`S00904` + `ceiling-mounted`가 더하는 `S00301`).
스토리 1차 패스가 말한 **"15샷"과 이 20샷은 같은 측정이 아니다** — 이 감사 어휘가 더 넓고(`overhead` 단독 17샷), 슬롯-1이 아니라 프롬프트 전체를 센다.
1차 패스 목록은 보존돼 있지 않으므로 두 수의 포함관계는 주장하지 않는다. 0건인 후보(`looking down at`)는 근거 표에서 뺐다 — 실측 0건은 증거가 아니고,
아래 위치 규칙에 따르면 `looking down`은 오히려 프레이밍일 수 있다.

**규칙은 범주가 아니라 위치다.** `overhead`가 항상 조명 기구라는 규칙은 이 런 안에서 **거짓**이다:
`S00504`의 슬롯-1은 문자 그대로 `"high-angle overhead view of containment cell floor"`이고, `S00404`/`S00702`는 `"view down"`을 쓴다 — 진짜 카메라 프레이밍이다.
올바른 규칙: **슬롯-1에 있으면 프레이밍일 수 있고, 프롬프트 뒤쪽에서 램프/설비 명사 옆에 있으면 조명이다.**
(`S00504`가 AGREE인 것은 이 구분과 무관하다 — 필드도 `high-angle`이라 버킷이 맞았다.)
그럼에도 이 구절들을 앵글 신호로 세면 `high-angle` 오탐이 대량 발생하고, 그것이 §4-4의 "충돌" 인상을 만든 것으로 보인다.
**거짓 CONFLICT 1건이 스토리 하나를 잘못된 가지로 보냈으므로**, 스크립트는 애매하면 CONFLICT가 아니라 UNDECIDABLE을 고르도록 비대칭으로 설계했다.

## 4. 매처 주의사항 — 순진한 `"<angle> shot"` 정규식은 22/43을 준다

스크립트는 이 반사실(counterfactual)을 매 실행마다 `naive:` 행으로 함께 출력한다. 주장이 아니라 재산출이다:

```
verdicts: {"AGREE": 43}
naive   : {"AGREE": 22, "UNDECIDABLE(slot-1)": 20, "CONFLICT": 1}
```

순진한 매처가 틀리는 샷은 **21건**(43 − 22)이고 두 종류로 갈린다.

| 실패 유형 | 건수 | 샷 |
|-----------|------|-----|
| `<angle> shot` 바이그램이 슬롯-1에 아예 없음 → UNDECIDABLE | **20** | `S00101` `S00201` `S00203` `S00300` `S00301` `S00302` `S00303` `S00404` `S00502` `S00503` `S00504` `S00601` `S00603` `S00605` `S00702` `S00703` `S00800` `S00801` `S00903` `S00904` |
| 바이그램이 **두 번째** 앵글 단어에 붙어 거짓 CONFLICT | **1** | `S00501` (`low-angle medium shot` → 순진 매처는 `medium`, 필드는 `low-angle`) |

예시: `S00300` `wide static shot`, `S00301` `medium framing of a sparse observation room…`, `S00502` `medium two-shot composition` —
셋 다 앵글 **단어**는 있으나 `<angle> shot` 바이그램이 없다. 그래서 매처는 `shot`을 요구하지 않고 앵글 단어만 찾는다.
`S00501`은 **가장 먼저 등장하는** 앵글을 채택하는 규칙으로 해결되며(동일 위치 동점은 **가장 긴 매치** 우선 — 알파벳 순서가 아니다), 필드 `low-angle`과 일치한다.
두 처리를 합쳐 43/43이 되고, 없으면 22/43으로 잘못 보고된다.

## 5. 14.2 인계 — 후보 가설 둘, 어느 것도 확정 아님

②원근 결함의 개입 지점이 **필드↔텍스트 조립이 아니라 프롬프트 텍스트 내부**라는 것은 위 측정에서 확정됐다(필드↔본문 불일치 0건).
**그 안에서 무엇이 프레이밍을 결정하는지는 확정되지 않았다.** `S00100` 한 샷은 대조군도 없고 용량-반응도 없다(n=1). 후보는 둘이고 **지위가 같다**:

- **(a) 내용 질량 가설** — 슬롯-1이 `medium`이라고 선언해도 뒤따르는 117단어가 바닥·배수구·천장을 서술하면 프레이밍은 그 내용 질량을 따른다.
- **(b) 조명 어휘의 앵글 오독 가설** — 모델이 `lit harshly from above` / `from above` / `ceiling-mounted`를 카메라 프레이밍으로 읽었다.
  `S00100`은 이 런에서 이 셋을 **동시에** 갖는 유일한 샷이다(§3 감사 출력에서 확인 가능). 즉 §3이 "오탐"으로 기각한 어휘가 여기서는 경쟁 가설이다.

두 가설은 `S00100` 하나로는 구분되지 않는다 — 그 샷은 두 조건을 모두 만족한다.

**비용 0의 판별 시험(신규 스토리 불필요).** 렌더된 43장의 시점을 두 가지로 그룹핑해 비교한다:
(i) 바닥/천장 서술 단어 질량 기준, (ii) 조명 어휘 히트 수 기준. 두 그룹핑 모두 이미 커밋된 스크립트 출력에서 도출된다
(조명 히트는 감사 출력 그대로, 내용 질량은 같은 스크립트가 이미 읽고 있는 `image_prompt` 본문에서). 두 축이 갈라지는 샷
(예: `S00901` — `ceiling-mounted`+`overhead`를 갖지만 데스크 서술이 주력, `S00103` — `from above`+`overhead` 111단어)에서 어느 축이 시점을 예측하는지 본다.

인계 사항:
- ②의 개입 지점은 **프롬프트 텍스트 내부**이고, 이 층은 리서치 §4-3의 미탐색 층(프롬프트 재작성)과 **같은 개입 지점을 공유**한다. 이 결론은 (a)/(b) 어느 쪽이 참이어도 성립한다.
- 14.2는 "필드가 무시된다"를 전제로 세우면 안 된다. 필드는 무시되지 않고, 배경 프롬프트 입력은 아니지만 캐스트 카드 선택 입력이다(§1).
- 14.2가 물어야 할 질문: 슬롯-1이 선언한 앵글과 슬롯-2..8의 내용 서술이 **서로를 배반하지 않도록** 어떻게 강제하는가(프롬프트 어포던스 문제).
  버킷 단위 일치로는 안 보이는 §1의 수식어 14건과 `dutch angle` 누락도 여기 소관이다. 프롬프트 변경은 렌더 전 텍스트 스크리닝을 탄다(`gotcha_screen-a-prompt-change-before-you-render-it`).
- **전제 의존성**: 이 인계는 "프롬프트 본문이 서술하는 시점"에 게이트를 거는 것이고, `stock_plate_substitution_enabled`가 켜지는 순간
  `location_key`를 가진 **31/43샷**에서는 `image_prompt`가 생성에 쓰이지 않으므로(표본 밴드 참조) 그 게이트가 무력해진다. 14.1/14.2는 이 플래그와 함께 설계해야 한다.

**이 스토리의 소득은 ②의 절반을 닫은 것이 아니라, ②에서 가장 값싼 가설(필드↔본문 조립 버그)을 GPU 0으로 제거하고 다음 가설 후보 둘을 지목한 것이다.**

## 6. 부수적으로 고친 조립 결함 2건 (측정이 드러낸 것)

측정은 충돌 0건을 확정했지만, 같은 코드 읽기가 실제 결함 2건을 드러냈다.

1. **`camera_angle`은 형제 필드 전부와 달리 무검증이었다.** `camera_movement`/`mood`/`position`/`depth`/`pose`/`location_key`는 모두
   어휘 검증 + 정규화 + 경고를 가지는데 `camera_angle`만 `isinstance(str)` passthrough였다. 결과: `"Over-The-Shoulder"` 같은 미스케이싱 값이
   R3(`scenario_chain.py`, **대소문자 민감 정확일치**)를 조용히 건너뛴다 — 이 런에는 발생하지 않았지만 침묵 경로였다.
   → `_resolve_camera_angle`(어휘 밖이면 경고 + `None`, 부재는 침묵)로 교체.
2. **`_fallback_prompt` 경로는 확정적으로 어긋났다.** 백필 프롬프트는 `"static wide shot"`을 하드코딩하는데 `camera_angle`은 LLM 값을 그대로
   남겼다 — 파이프라인에서 필드↔본문 불일치가 **보장**되는 유일한 지점. 이 런의 43샷 중 이 경로를 탄 샷은 0건이라 실측에는 안 잡혔다.
   → 백필 시 `camera_type`도 `"wide"`로 덮어쓴다.

**두 수정의 렌더 영향(무영향이 아니다).** 필드는 배경 프롬프트에는 안 들어가지만 캐스트 카드 앵글 선택에는 들어간다(§1). 그래서:

- 정규화의 실제 대가: 어휘 밖 `camera_type`(예: `dutch angle`)이 이제 앵글 선택 카탈로그에 **원문 대신 `""`로 도착한다.** 카탈로그는 LLM 프롬프트라
  원문 자유텍스트는 약한 힌트였고, 그 힌트가 사라진다. **이 런에서의 발생 0건이므로 라이브 영향은 0**이지만, "영향 없음"이 아니라 "이 런에서 0건"이다.
  드롭을 유지하는 것은 의도다 — 독자 전수조사 결과 둘뿐이고(R3는 정확일치라 애초에 그런 값과 매칭되지 않았고, 카탈로그는 값으로 분기하지 않는다),
  대소문자 정규화로 얻는 R3 도달이 이 힌트보다 크다(`gotcha_deleting-a-constant-needs-a-reader-census`).
- 백필 덮어쓰기: 백필 샷은 `cast`가 항상 비어 있어 카드 선택이 돌지 않으므로 이 수정의 픽셀 영향은 0이다.

단위 테스트는 `tests/pipeline/nodes/test_scenario_chain.py`의 "camera_angle (Story 14.0…)" 섹션. 어휘 상수 자체는
`test_camera_angles_constant_matches_the_prompt_vocabulary_line`이 `visual_breakdown.md:215` 줄과 집합 동일성으로 고정한다
(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`: 상수를 파라미터로 도는 테스트는 어휘 표류를 볼 수 없다).

## 7. 대조군 / 회귀 근거

- **대조군 = 정규화 이전 값.** 43샷 전부가 이미 문서 표기이므로 정규화 전후 값이 바이트 동일하다. 테스트로 고정:
  `test_build_scenes_camera_angle_documented_spelling_round_trips`(7값 전수 라운드트립).
- **반증 가능성 = 스크립트 종료코드.** 무조건 초록이 나오지 않도록 "판정된 샷이 1건 이상"을 요구한다:
  - `0` — 판정된 샷(AGREE 또는 CONFLICT) ≥ 1 **그리고** CONFLICT 0건. 이 보고서의 주장이 성립하는 유일한 코드.
  - `1` — CONFLICT ≥ 1. 주장 반증.
  - `2` — 사용법 오류(인자 없음).
  - `3` — 측정할 것이 없음: 해당 런 없음 / `scenes` 비어 있음 / 접두사가 여러 `thread_id`에 걸림 / DB 파일 부재 / 43샷 전부 UNDECIDABLE.
    **통과가 아니다** — 판정 0건 위의 "충돌 0건"은 아무것도 증명하지 않는다(이전 버전은 이 경우에도 0을 반환해 게이트가 발화할 수 없었다).
