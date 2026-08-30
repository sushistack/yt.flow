# 후보 매칭 축 심사 — Story 14.8 T1 (2026-08-30, GPU 0 · VLM 0 · 렌더 0)

`camera_angle → plate.viewpoint` 정합 축이 실측으로 은퇴했다(스토리 §Context B). Jay 결정 (B)에
따라 **매칭 규칙 자체를 교체**한다. 이 문서가 후보를 심사하고, **통과 조건은 `(b) < (c)` 하나뿐이다** —
축의 우아함·구현 난이도·기대 성능은 심사 기준이 아니다(spec §Boundaries).

- **(a)** 무엇을 재는가
- **(b)** 그 측정의 **재현 오차** — 재산출 가능한 출처 필수
- **(c)** 그 측정의 **허용 폭** — 값이 이만큼 흔들려도 배정 결과가 안 바뀌는 폭. 출처 필수
- 인용 없는 수치는 그 행을 **실격**시킨다.

---

## 0. 심사 결과 요약

| # | 후보 | (b) 재현 오차 | (c) 허용 폭 | (b)<(c) |
|---|---|---|---|---|
| ① | 결정론적 기하 추정기 | **0.56** (동일 이미지, 에지 임계 3설정) | 0.20 (EYE 범주 폭) | **아니오 — 기각** |
| ② | 시점을 안 쓰는 축 (`location_key`) | **0** (닫힌 14값 어휘의 문자열 동등성) | 1 범주 (인접 경계 없음) | **예 — 채택** |
| ③ | 프레이밍 대신 내용 정합 | 미구현 → 미측정 | **정의되지 않음** | **아니오 — 기각** |
| ④ | 연속값 거리 + 폴백 | **0.072** 평균 / 0.12 최대 | **0.010** (키 내부 최소 간격의 중앙값) | **아니오 — 기각** |

**채택 축 = ②.** HALT 조건(통과 후보 0)은 발동하지 않았다.

---

## ① 결정론적 기하 추정기 — **기각**

**(a)** 픽셀에서 에지를 뽑아 소실점/지평선의 세로 위치 `y_h`를 커밋된 알고리즘이 계산한다.
사람·VLM을 배제해 판정자 간 오차를 원천 제거하는 길.

**(b) = 0.56.**
- 주장되는 값은 "파라미터를 고정하면 **구조적으로 0**"이지만, **그런 코드는 이 저장소에 없다.**
  재확인(이 세션): `grep -rniE "vanishing|hough|gradient_vote|edge_threshold" --include='*.py' .`
  는 `compositing_service.py:158`의 **산문 주석** 한 줄과 무관한 히트만 낸다 — 추정기 구현 0건.
  따라서 "0"은 **재산출 가능한 출처가 없는 수치**이고, 이 문서의 인용 규칙에 의해 그 자체로 실격이다.
- 실제로 인용 가능한 유일한 측정치는 그 추정기의 **임시 판본이 남긴 발산**이다:
  `REREAD-2026-08-30.md:43` — `medical-bay/b`에서 **에지 임계 3설정에 y_h 0.93 / 0.97 / 0.41**.
  파라미터 민감도 = **0.56**. 이것이 "파라미터를 고정하면 0"이 아니라 **"어느 파라미터를
  고정하느냐가 답을 정한다"**는 뜻이고, 고정 자체가 판정을 대신한다.

**(c) = 0.20.** EYE 범주 폭(0.40~0.60), `14-1-approved-plate-sets/PREREGISTRATION.md` §2.

**판정: 0.56 > 0.20 → 기각.**

**별개로 남는 두 가지**(재현성과 지각 일치는 다른 질문이다):
1. 파라미터를 고정해 (b)=0을 만들어도 **그 값이 사람 지각과 맞는지는 검증되지 않았다.** 이 축을
   부활시키려면 42장에 대한 사람 판정과의 일치율이 먼저 필요하고, 그 사람 판정이 바로 오차
   0.072짜리 계기다(순환).
2. `medical-bay/b`는 **단일 소실점이 존재하지 않는다**(`REREAD-2026-08-30.md:41-50` — 수동 선쌍이
   376~810px로 흩어지고 매트리스 선쌍이 기하학적으로 불가능한 곳에서 만난다). 이 플레이트 위에서
   추정기의 출력은 **아무것도 측정하지 않는다.** 축과 무관한 **플레이트 품질 결함**이며 별도 기록한다.

---

## ② 시점을 안 쓰는 축 — **채택**

**(a)** `shot.location_key == plate.location_key`. 여기에 기존 필터를 **그대로** 승계한다
(D1 people-free, D2 어포던스 노브, `_UNSERVABLE_ANGLES`). `viewpoint`는 **선택에서 읽지 않는다**
— 자산 메타데이터로는 남되 배정에 참여하지 않는다.

**(b) = 0.**
- 샷 쪽 `location_key`는 시나리오 LLM이 **닫힌 14값 enum**에 써 넣은 **데이터 필드**이지 지각
  측정이 아니다(`src/yt_flow/domain/state.py:247-263`, `LOCATION_KEYS`). 플레이트 쪽은 매니페스트
  키 `<location_key>/<variant>`이자 `location_plates` 행이다.
- 배정 시점의 연산은 **문자열 동등성**이고 픽셀을 읽지 않는다. 같은 체크포인트·같은 매니페스트에
  대해 몇 번을 돌려도 같은 답이 나온다. 재산출: `verify_two_paths.py`(T2).
- ①과 (b)=0의 성질이 다르다: ①은 **측정을 고정**해 0을 만들고 ②는 **측정을 없애서** 0을 만든다.
  후자에는 "그 값이 사람 지각과 맞는가"라는 두 번째 질문 자체가 없다.

**(c) = 1 범주.** 값 공간이 **순서 없는 14개 서로소 값**이라 **경계 근처라는 상태가 존재하지
않는다.** 배정을 바꾸는 최소 차이는 "다른 방"이다. `y_h`가 실패한 방식(폭 0.20짜리 범주에
±0.10 오차)이 이 축에는 구조적으로 없다.

**판정: 0 < 1 → 채택.**

### 채택의 대가 — 시점 불일치를 **수용**하면 화면에서 무엇이 깨지는가 (옛 servable 24 분모 위 실측)

옛 축이 `no_viewpoint_match`로 거절한 **7샷**(`report.md:181`, 재산출
`uv run python .../14-1-approved-plate-sets/replay_coverage.py 4b35c0ed`)이 ②에서는 전부 히트한다.
샷 목록은 그 런의 체크포인트에서 읽었다(읽기 전용, 재산출 명령은 §부록):

| 샷 | key | camera_angle | cast | ②가 주는 것 | 그 풀의 측정 viewpoint |
|---|---|---|---|---|---|
| S00402 | containment-chamber | low-angle | 1 | a/b/c 중 1장 | 전부 **EYE** (0.41 / 0.52 / 0.43) |
| S00803 | containment-chamber | low-angle | 1 | a/b/c 중 1장 | 전부 **EYE** |
| S00902 | observation-room | low-angle | 1 | a/b/c 중 1장 | 전부 **EYE** (0.45 / 0.45 / 0.47) |
| S00404 | corridor | high-angle | 0 | a/b/c 중 1장 | 전부 **EYE** (0.42 / 0.42 / 0.44) |
| S00604 | observation-room | high-angle | 0 | a/b/c 중 1장 | 전부 **EYE** |
| S00904 | observation-room | high-angle | 1 | a/b/c 중 1장 | 전부 **EYE** |
| S00702 | medical-bay | high-angle | 2 | a/b/c 중 1장 | 전부 **EYE** (0.47 / 0.45 / 0.47) |

`viewpoint` 값은 `viewpoint_verdicts.csv` 해당 행. 즉 **7/7이 앙각·부감 프레이밍의 샷에 눈높이
플레이트를 받는다.** servable 히트는 17/24 → **24/24**.

**그 불일치가 픽셀에 닿는 경로는 실재한다.** `camera_angle`은 render-inert가 아니다:
`services/character_service.py:1556`이 이 필드를 샷별 카탈로그에 복사하고 `_select_entity_angles`가
그것으로 **캐스트 카드의 앵글을 고른다**(`pipeline/nodes/scenario_chain.py:520-530`이 프롬프트가
아닌 두 경로를 문서화; `gotcha_camera-angle-reaches-pixels-by-a-second-path`). 위 7샷 중 **cast를
가진 5샷**(S00402·S00702·S00803·S00902·S00904, cast 합 6)은 **부감/앙각용으로 고른 카드를
눈높이 배경 위에 합성**하게 된다.

**이것은 커버리지 숫자가 아니라 시청 판정이다.** 이 문서는 그 대가가 허용 가능하다고 주장하지
않는다 — 크기(7샷·카드 6장)와 경로를 실측으로 적을 뿐이고, 판정은 **Jay의 E2E iteration 5** 몫이다
(`PREREGISTRATION.md` C4′가 이 숫자의 공개를 의무화한다).

**두 번째 대가 — 이미 히트하던 샷의 풀도 넓어진다.** ②는 거절당하던 7샷만 구제하는 것이
아니라, 옛 축이 **시점 필터로 걸러내던 후보를 수요 키 안으로 되돌린다**. 42장 대조 결과 오늘
그것이 실제로 일어나는 키는 **`autopsy-room` 하나**다:

- `autopsy-room/b`는 측정 **HIGH**(`y_h` 0.38, `viewpoint_verdicts.csv`)이고 `autopsy-room`은
  **EYE로만** 수요가 있다(3샷, 전부 cast). 옛 축에서 그 `(autopsy-room, EYE)` 셀의 풀은
  **2장**(`/a`·`/c`)이었다 — 재산출: `plate_meta.json`의 `autopsy-room/{a,b,c}` 3행 중
  `viewpoint == "EYE"`가 둘, `"HIGH"`가 하나(`viewpoint_verdicts.csv` 같은 행). ②에서는
  **3장**이 되고, 이는 `replay_coverage.py 4b35c0ed`가 `autopsy-room … C1'=OK  (3 plate(s))`로
  찍는 수와 같다. 그래서 `S00600`·`S00602`·`S00603`(오늘 전부 `autopsy-room/c`)이 **부감
  플레이트를 받을 수 있게 된다.**
  ⚠️ **인용 정정(14.8 리뷰).** 이 줄은 처음에 `replay_coverage.py`가
  `autopsy-room EYE … C1=OK (2 plate(s))`를 찍는다고 인용했는데 **그런 출력은 존재하지 않는다** —
  현행 스크립트는 C1′를 키 단위로만 찍고 옛 축은 CONTROL 블록에서 셀 **개수**만 낸다(셀별 풀
  크기는 인쇄하지 않는다). 이 문서 자신의 규칙("인용 없는 수치는 그 행을 실격시킨다")에 따라
  **커밋된 파일 행**(`plate_meta.json`)과 **스크립트가 실제로 찍는 줄**로 다시 세웠다. 결론은
  바뀌지 않았다: 2 → 3.
- 나머지 5개 수요 키(containment-chamber · control-room · corridor · medical-bay ·
  observation-room)는 승인 3장이 전부 EYE라 풀 크기가 3 → 3으로 그대로다.
- 코퍼스의 나머지 HIGH 3장(facility-exterior/a · maintenance-tunnel/b · server-room/b)과
  LOW 5장(entrance-checkpoint/c · facility-exterior/b · server-room/c · storage-vault/b·c)은
  전부 수요 밖 키에 있어 이 런에서는 배정되지 않는다.

②는 그 장들을 버리지 않는다 — `viewpoint`는 자산에 남고 **선택기가 안 읽을** 뿐이다.

---

## ③ 프레이밍 대신 내용 정합 — **기각 (허용 폭이 정의되지 않음)**

**(a)** 샷의 `image_prompt`와 플레이트 내용의 정합으로 고른다. 8.17이 버린 것의 다른 형태
(8.17은 키가 `scene_num`이라 `image_prompt`를 통째로 버렸고 배경이 155→41종으로 붕괴했다,
`epics.md:1890`).

**(b)** 측정 불가 — **구현이 없다.** 저장소에 존재하는 유일한 내용-정합 구현은
`replay_coverage.py`의 부분문자열 스캔(`k.replace("-", " ") in s["image_prompt"].lower()`)이고,
그것은 결정론적이지만(b=0) **`location_key`를 다른 경로로 복원할 뿐 독립된 축이 아니다** —
채택된 ②와 같은 것을 덜 정확하게 하는 것이다.

**(c) 정의되지 않음.** 점수 척도도 임계값도 범주 폭도 없다. **⚠️ 이 문서는 8.19의 임베딩
검색층 부재를 인용하지 않고 이 세션에서 직접 확인했다**(과거 문서가 이미 두 번 뒤집혔으므로):
- `src/yt_flow/services/asset_retrieval_service.py` **없음**(`ls src/yt_flow/services/` 전수).
- `grep -rn "asset_retrieval\|embedding\|cosine\|clip_score" src/ tests/ scripts/` →
  히트 2건이 전부이고 **둘 다 무관한 산문**(`prompt_service.py:3`의 "instead of embedding",
  `tests/stubs/fakes.py:342`의 "embedding the stage name").
- `grep -niE "faiss|chroma|sentence.transformers|open.clip|clip|embed" pyproject.toml` → **0건**.

**판정: (c)가 정의되지 않으므로 `(b) < (c)`는 만족될 수 없다 → 기각.** 이것은 통과가 아니라
**이유 있는 기각**이다. (c)를 정의하려면 존재하지 않는 스코어러 위에 임계값을 고르는 수밖에 없고,
그것이 곧 **없는 축을 발명하는 것**이라 Block If가 금지한다.

---

## ④ 연속값 거리 + 폴백 — **기각**

**(a)** 범주 경계를 없애고 `|y_h − target(camera_angle)|` 거리 순으로 키 안에서 랭킹한다.
경계 근처 동전던지기가 사라지는 대신 **폴백 임계값**이 새로 생긴다.

**(b) = 0.072 평균 / 0.12 최대.** `AUGMENTATION-BATCH-2026-08-30.md:45` — 같은 이미지 5장을
독립된 두 블라인드 판정자가 재서 **범주 뒤집힘 2/5 · |Δy_h| 최대 0.12 · 평균 0.072**.
독립된 두 번째 대조도 같은 크기다(`REREAD-2026-08-30.md:33-39`, 코리도 3장 0.07~0.13).

**(c) = 0.010.** 랭킹이 실제로 분해해야 하는 것은 **같은 키 안 후보들 사이의 간격**이다.
재산출:

```
uv run python _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/measure_axis_spread.py
```

- 키 내부 **최소 인접 간격의 중앙값 = 0.010**, 키 내부 산포(max−min) 중앙값 = 0.055.
- 가장 좁은 쌍이 평균 판정자 오차 0.072를 **넘는 키는 14개 중 2개**(facility-exterior 0.140,
  server-room 0.260)뿐이고, **run `4b35c0ed`가 실제로 요구하는 6개 키에서는 0개**다
  (autopsy-room 0.010 · containment-chamber 0.020 · control-room 0.010 · corridor 0.000 ·
  medical-bay 0.000 · observation-room 0.000).

**판정: 0.072 > 0.010 → 기각.** 수요가 있는 모든 키에서 랭킹 순서는 **측정 노이즈**다.

**폴백 임계값도 같은 측정에서 불안정하다.** 재판독을 병기해 보면(`measure_axis_spread.py` 마지막
블록, 원본 `REREAD-2026-08-30.md:20-31`) corridor는 키 **레벨이 +0.100 통째로 이동**하는데 키 내부
산포는 0.020 → 0.040으로 거의 그대로다. 즉 재판독은 **랭킹 안의 순서는 안 바꾸면서 키 전체를
임계값 너머로 옮긴다** — 거리 랭킹과 그 폴백 임계값이 **같은 오차에 동시에 무너진다.**

---

## 부록 — 재산출

| 수치 | 명령 / 출처 |
|---|---|
| 키 내부 산포·최소 간격·경계 거리 | `uv run python .../14-8-plate-reuse-shipping/measure_axis_spread.py` (두 번 실행 바이트 동일) |
| 옛 축의 17/24·7샷 `no_viewpoint_match`·수요 셀 | `uv run python .../14-1-approved-plate-sets/replay_coverage.py 4b35c0ed` |
| 42장 `y_h`·`verdict` | `14-1-approved-plate-sets/viewpoint_verdicts.csv` |
| 판정자 간 오차 0.072/0.12 | `14-1-approved-plate-sets/AUGMENTATION-BATCH-2026-08-30.md:45` |
| 추정기 발산 0.93/0.97/0.41 | `14-1-approved-plate-sets/REREAD-2026-08-30.md:43` |
| EYE 범주 폭 0.20 | `14-1-approved-plate-sets/PREREGISTRATION.md` §2 |
| 7샷의 `shot_id`·`camera_angle`·cast | 체크포인트 읽기 전용 조회 — `replay_coverage.load_scenes`와 같은 로더, `_ANGLE_VIEWPOINT[camera_angle] in {HIGH, LOW}` 필터 |

## 이 문서가 주장하지 않는 것

- **②가 화면을 개선한다고 주장하지 않는다.** ②는 재현 가능한 축이라는 것만 보였고, 그것이
  포기하는 것(7샷의 시점 불일치, 그중 카드 6장)을 실측으로 적었다. 좋고 나쁨은 Jay 시청 판정이다.
- **①·③·④가 영원히 불가능하다고 주장하지 않는다.** ①은 커밋된 구현 + 사람 판정과의 일치율이,
  ③은 스코어러와 임계값의 근거가, ④는 판정자 오차를 0.01 아래로 내리는 방법이 생기면 다시 심사한다.
- **후보 넷이 전부라고 주장하지 않는다.** spec이 "최소한 이 넷"을 요구했고 넷을 다뤘다.
