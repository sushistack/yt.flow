# Story 14.8 리포트 — 매칭 축 교체 (Phase 2, 2026-08-30)

Phase 1(축 심사 + 사전등록, 커밋 `d797a8a` → `5746918`)의 결론 위에 얹은 Phase 2 측정·출하 기록.
**GPU 0 · VLM 콜 0 · LLM 콜 0 · 렌더 0.** 모든 수치에 재산출 명령이나 커밋된 출처를 붙인다
(`gotcha_a-measurement-without-its-sample-band`).

> ⚠️ **이 리포트는 재도출본이다.** 첫 반복(`cff1559`/`e803873`)은 적대적 리뷰에서 `bad_spec` 3건이
> 나와 `c19d64c`로 되돌려졌다. 무엇이 틀렸는지는 §8에 그대로 적는다 — 지우지 않는다.

---

## 1. 표본 밴드 — 이 리포트의 모든 수치가 유효한 범위

**커버리지 수치를 실제로 만든 입력 셋**(매니페스트 해시 하나로 뭉뚱그리지 않는다 — 재생기는
세 곳에서 읽는다):

| 입력 | 값 | 재산출 |
|---|---|---|
| 승인 플레이트 행 | **42행** (14키 × 3변형), `location_plates WHERE status='approved'` | `sqlite3 yt_flow.db "SELECT count(*) FROM location_plates WHERE status='approved'"` |
| 측정 메타(커밋 스냅샷) | `plate_meta.json` sha256 `e3414aea603826f4e5dc5221…` (42행, 매니페스트 `source.plate_meta`와 42/42 바이트 동일) | `sha256sum .../14-1-approved-plate-sets/plate_meta.json` |
| 라벨 반쪽(라이브) | `assets/manifest.json` sha256 `a094b7c585228c872ce70e3f…`의 `source.label` — **`has_person = label OR plate_meta` 접기의 피연산자** | `sha256sum assets/manifest.json` |
| 시점 판독(참고·C4′) | `viewpoint_verdicts.csv` sha256 `ec53e7e193f7bc762ceb7ea7…` (42행) | `sha256sum .../viewpoint_verdicts.csv` |
| 런 | `4b35c0ed-8a1e-4448-8594-11bd9997376d` (E2E iteration 4) 체크포인트 | `replay_coverage.load_scenes` |
| 샷 | 43 총, **31**이 `location_key` 보유, **24**가 servable | `close-up` 6 + `POV` 1 제외 |
| 어포던스 노브 | `plate_affordance_gate_enabled=False` (이 스토리에서 켜지 않음) | `config.py` |
| 사전등록 | `PREREGISTRATION.md` §1~§6 커밋 **`d797a8a`** — `verify_two_paths.py`(`5746918`)보다 **앞선다** | `git log --oneline --diff-filter=A -- .../PREREGISTRATION.md .../verify_two_paths.py` |

앞선 반복은 표본 밴드에 **매니페스트 sha256만** 적었는데, 커버리지 수치는 `plate_meta.json`과
DB에서도 나온다 — 셋을 다 적어야 재산출이 가능하다. (리뷰 지적)

**이 리포트가 일반화하지 않는 것**: 한 런(43샷)·한 시나리오(SCP-049)·42장 코퍼스. C1′~C4′의 값은
전부 **이 런 위의 값**이고, 다른 시나리오가 다른 키를 요구하면 다시 재야 한다.

---

## 2. 채택 축과 그 심사 (Phase 1 요약, 정본은 `AXIS-CANDIDATES.md`)

통과 조건은 `(b) 재현 오차 < (c) 허용 폭` **하나뿐**이었다.

| # | 후보 | (b) | (c) | 판정 |
|---|---|---|---|---|
| ① 결정론적 기하 추정기 | 0.56 (같은 이미지, 에지 임계 3설정) | 0.20 (EYE 범주 폭) | 기각 |
| ② **시점을 안 쓰는 축 (`location_key`)** | **0** (닫힌 14값 enum의 문자열 동등성) | 1 범주 | **채택** |
| ③ 내용 정합 | 미구현 → 미측정 | 정의되지 않음 | 기각 |
| ④ 연속값 거리 | 0.072 평균 / 0.12 최대 | **0.010** (키 내부 최소 간격 중앙값) | 기각 |

②의 (b)=0은 **측정을 없애서** 얻은 0이다(①의 "측정을 고정해서"와 성질이 다르다):
`location_key`는 시나리오 LLM이 쓰는 닫힌 14값 enum 데이터 필드(`domain/state.py` `LOCATION_KEYS`)이고
플레이트 쪽은 매니페스트 키라, 배정 연산이 **문자열 동등성**이다. 경계 근처라는 상태가 없다.

**⚠️ 심사 형식 자체의 결함을 인계한다**(§9-1): `(b) < (c)` 단일 기준은 **측정을 삭제하는 후보를
구조적으로 우대하고 측정을 시도하는 후보를 구조적으로 벌한다.** ②가 이긴 이유의 일부는 그
형식이다. 이것은 ②를 기각할 근거는 아니지만(다른 셋은 각자의 이유로도 떨어졌다) 다음 리서치
게이트를 설계하는 사람이 알아야 할 방법론 소견이다.

---

## 3. T2 2-경로 검증 — 전체 출력 (Phase 1, `5746918`에서 실행)

`uv run python _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/verify_two_paths.py`

```
-- P1  location_key : structural(4 copies) vs label.matches_location  [GATED] --
  comparable 42/42   disagree 1
  VERDICT: 1/42 = 2.4%  vs band 5.0%  ->  PASS
    interview-room/b         pathA=interview-room  matches_location=False

-- P2  has_person : label(2026-08-02) vs plate_meta(2026-08-25) --
  comparable 0/42   disagree 0
  VERDICT: UNDEFINED (0 comparable rows)

-- P3  depicts_person : plate_meta(2026-08-25) vs label(8.17 labeler) --
  comparable 0/42   disagree 0
  VERDICT: UNDEFINED (0 comparable rows)

-- P4  standing_room(VLM) vs floor_share(human, blind) — contradiction only --
  comparable 42/42   disagree 1
  VERDICT: 1/42 = 2.4%  (reported, not gated — PREREGISTRATION §1)
    server-room/b            standing_room=False  floor_share=0.85  (no room claimed over a floor)
```

**보존되는 반대 결과·판정불가 행 셋** — 지우지 않는다:

1. **P2·P3는 `UNDEFINED (0 comparable rows)`이고 PASS가 아니다**(사전등록 규칙 U).
   `plate_meta`에 `has_person`이 **42/42 부재**, `label`에 `depicts_person`이 **42/42 부재**라
   비교 가능한 행이 한 줄도 없다. **결과적으로 spec의 Design Notes가 한 점에서 반증됐다**:
   그 문서는 `location_service.py:105-112`의 `has_person` OR을 "두 큐레이터가 갈린다는 증거"로
   인용해 2-경로 입력으로 삼으라고 했는데, 이 코퍼스에서 **그 OR은 오늘 피연산자 하나로 돈다.**
   갈릴 두 값이 없다. 인계(§9-4).
2. **P4의 `server-room/b` 모순은 살아 있다** — VLM은 *"no visible floor"*라 `standing_room=False`,
   사람 맹검 판독은 `floor_share 0.85`. 사전등록이 **측정 전에** 고정한 모순 방향 검정에 정확히
   걸린 유일한 행이고, `server-room`은 이 런의 수요 키가 아니라 커버리지에는 영향이 없다.
   **해소하지 않고 기록한다.**
3. **P1의 유일한 불일치 `interview-room/b`** — 구조 경로는 `interview-room`, 8.17 라벨러는
   `matches_location=False`. 1/42 = 2.4% < 밴드 5.0% → PASS. **런타임 필터로 승격하지 않았다**
   (§5.3에 판단 근거).

---

## 4. 커버리지 — 새 기준 판정과 옛 축 대조군

`uv run python _bmad-output/implementation-artifacts/14-1-approved-plate-sets/replay_coverage.py 4b35c0ed`

```
-- selector outcome over the location-keyed shots --
  match                  24
  unservable_framing     7

servable shots (camera_angle maps to a viewpoint): 24  ->  match 24 (100.0%)
cast-bearing hits whose plate lacks standing_room=True: 0

-- demanded cells (C1'/C2': `location_key`, no viewpoint component) --
  autopsy-room           shots= 3 cast= 3 C1'=OK  (3 plate(s))  C2'=OK  (3 with room)
  containment-chamber    shots= 9 cast= 8 C1'=OK  (3 plate(s))  C2'=OK  (3 with room)
  control-room           shots= 1 cast= 1 C1'=OK  (3 plate(s))  C2'=OK  (3 with room)
  corridor               shots= 1 cast= 0 C1'=OK  (3 plate(s))  C2'=-    (3 with room)
  medical-bay            shots= 4 cast= 3 C1'=OK  (3 plate(s))  C2'=OK  (3 with room)
  observation-room       shots= 6 cast= 5 C1'=OK  (3 plate(s))  C2'=OK  (3 with room)

-- pre-registered bars (14-8-plate-reuse-shipping/PREREGISTRATION.md §3) --
  ⚠️ ALL THREE ARE VACUOUS on today's corpus (population sweep, §7 of that file): ...
  C1' key coverage       : PASS (6/6 keys)   [VACUOUS]
  C2' affordance coverage: PASS   [VACUOUS]
  C3' servable share >= 90%: PASS (24/24 = 100.0%)   [VACUOUS]

-- CONTROL: retired 14.1 axis (camera_angle -> plate viewpoint), same inputs --
  C1  cell coverage      : FAIL (5/10 cells)
  C2  affordance coverage: PASS
  C3  servable share >= 90%: FAIL (17/24 = 70.8%)
  control reproduces 14.1's committed verdict {'c1_ok_cells': 5, 'c1_cells': 10,
    'c2_pass': True, 'c3_hits': 17, 'c3_servable': 24} -> VALID
  shots the retired axis rejected as `no_viewpoint_match`: 7
    S00402 containment-chamber camera_angle=low-angle cast=1
    S00404 corridor            camera_angle=high-angle cast=0
    S00604 observation-room    camera_angle=high-angle cast=0
    S00702 medical-bay         camera_angle=high-angle cast=2
    S00803 containment-chamber camera_angle=low-angle cast=1
    S00902 observation-room    camera_angle=low-angle cast=1
    S00904 observation-room    camera_angle=high-angle cast=1
  axis change: servable match 17 -> 24 (70.8% -> 100.0%), C4' cost 7 mismatched hit(s)
```

**대조군의 유효성은 가정이 아니라 단언된다.** 앞선 반복은 커밋 메시지에 *"검사된다"*고 적었지만
코드에는 검사가 없었다. 지금은 재생 실패 시 **exit 4로 죽고 델타를 인쇄하지 않는다** — 망가진
대조군이 "17 → 24"를 증거로 내놓지 못하게.

**로더 동형성이 고쳐졌다(리뷰 지적 3).** 재생기는 `plate_meta.json` 단독으로 읽었고 거기엔
`has_person`이 42/42 부재라, `entrance-checkpoint/b`(`label.has_person=true`, `approved`)가
**재생기에는 people-free · 런타임에는 사람 보유**로 갈렸다. 오늘 수요 키가 아니라 **숫자만 우연히
같았다.** 이제 매니페스트 `source.label`을 병합해 런타임과 같은 OR을 접는다. **효과: C1′의 수치는
변하지 않았다(6/6). 변한 것은 그 수치가 우연이 아니게 된 것이다** — `entrance-checkpoint`가
수요 키가 되는 순간 옛 로더는 3장을, 새 로더는 2장을 보고했을 것이다.

### ⚠️ C1′·C2′·C3′는 **전부 반증 불가**다 — 이것이 이번 재도출의 중심 정정

`PREREGISTRATION.md` §7(이번에 신설한 모집단 대조 절)이 승인 42장 전수로 검사한 결과:

| 기준 | 선언된 실패 경로 | 모집단 대조 | 판정 |
|---|---|---|---|
| C1′ | 수요 키의 3장이 전부 D1에 걸림 | D1에 걸리는 플레이트는 **전 코퍼스 1장**(`entrance-checkpoint/b`, 수요 밖). 사람 판정 부재도 0/42 | **VACUOUS** |
| C2′ | `server-room`에 cast 샷이 키잉됨 | `standing_room is False`는 2장, 둘 다 `server-room`(수요 밖). 게다가 **노브 OFF라 런타임 배정을 못 바꾼다** | **VACUOUS**(이중) |
| C3′ | 3샷이 폴백으로 빠짐 | C1′의 대수적 귀결 — 24/24가 강제된다. **사전등록 §3이 측정 전에 공시** | **VACUOUS** |
| C4′ | 숫자가 리포트에 없는 것 | 실제로 발화: **7/24** | **NOT VACUOUS** |
| B1 | 42행 중 3행 이상 불일치 | 1행이지만 3행 이상이 구조적으로 가능했다 | **NOT VACUOUS** |

**앞선 반복은 여기에 정반대를 인쇄했다** — `config.py`와 `report.md` 둘 다 *"C1′/C2′는 live
failure path를 유지한다"*고 적었고, 그것은 **거짓**이었다. 모집단 대조 없이 사례 하나를 들어
"경로가 있다"고 적은 것이 원인이다(`gotcha_closing-a-class-needs-a-population-sweep`).

**그래서 (a)는 문자 그대로는 충족됐고 증거로는 거의 비어 있다.** 그럼에도 **24와 0.90은 한 글자도
바꾸지 않았다** — 그 둘이 "기준을 낮추지 않았다"의 유일한 고정점이고, 공허성 표기는 기준을
약화하는 것이 아니라 그 기준이 실을 수 있는 **증거의 무게를 0으로 적는** 것이다. 발화 가능한
새 기준을 지금 만들지도 않았다: 그것이야말로 결과를 본 뒤의 기준 신설이다.

### C4′ — 새 축의 대가, 임계값 없는 의무 공개

```
-- C4' viewpoint mismatches among the hits (no threshold, disclosure only) --
  7/24 assigned plates sit at a viewpoint the shot's camera_angle did not ask for
    S00402 camera_angle=low-angle  (wants LOW)  -> containment-chamber/b measured EYE
    S00404 camera_angle=high-angle (wants HIGH) -> corridor/c            measured EYE
    S00604 camera_angle=high-angle (wants HIGH) -> observation-room/b    measured EYE
    S00702 camera_angle=high-angle (wants HIGH) -> medical-bay/c         measured EYE
    S00803 camera_angle=low-angle  (wants LOW)  -> containment-chamber/b measured EYE
    S00902 camera_angle=low-angle  (wants LOW)  -> observation-room/c    measured EYE
    S00904 camera_angle=high-angle (wants HIGH) -> observation-room/c    measured EYE
```

**7/7이 옛 축이 `no_viewpoint_match`로 거절하던 바로 그 샷들이다**(고 4 + 저 3). 그중 **5샷이
cast를 가진다**(S00402·S00702·S00803·S00902·S00904, 카드 합 6). `camera_angle`은 render-inert가
**아니다** — `character_service.py:1556`이 그것을 샷별 카탈로그에 복사하고 `_select_entity_angles`가
카드 앵글을 거기서 고른다(`gotcha_camera-angle-reaches-pixels-by-a-second-path`). 즉 **부감/앙각용
카드가 눈높이 플레이트 위에 합성된다.**

**이 리포트는 그것이 허용 가능하다고 주장하지 않는다.** 크기와 경로를 실측으로 적을 뿐이고,
판정은 Jay의 E2E iteration 5 시청이다. **C1′~C3′가 전부 공허한 지금, C4′는 이 스토리가 낸 유일한
정보성 숫자다.**

**Phase 1의 조건부 예측 3샷은 실현되지 않았다.** `AXIS-CANDIDATES.md`는 `autopsy-room` 풀이
2→3으로 넓어지면서 `S00600`·`S00602`·`S00603`이 부감 플레이트(`autopsy-room/b`, 측정 HIGH)를
받을 **수 있다**고 적었다. 실제로는 sha256 타이브레이크가 셋 모두에 `autopsy-room/a`(EYE)를 줬다.
그래서 C4′는 7이지 10이 아니다 — **이 3은 축의 성질이 아니라 다이제스트의 우연이고, run_id·씬·풀이
바뀌면 뒤집힌다.** 예측을 지우지 않고 이렇게 남긴다.

---

## 5. 코드 변경

### 5.1 선택기 (`src/yt_flow/pipeline/nodes/image.py`)

| 단 | 옛 (14.1) | 새 (14.8) |
|---|---|---|
| 1 프레이밍 | `_ANGLE_VIEWPOINT.get(angle)` → 값 사용 | **멤버십만** — `angle not in _ANGLE_VIEWPOINT` |
| 2 풀 진입 | `"viewpoint" in p` (존재) | **사람 판정 존재** — `has_person`·`depicts_person` 둘 다 `is not None` |
| 3 시점 정합 | `p["viewpoint"] == viewpoint` | **삭제** |
| 4 D1 사람 | `not p.get(...)` (부재=통과) | **`is False` 둘 다** (부재=판정불가, 통과 아님) |
| 5 D2 어포던스 | 노브 + `standing_room is True` | **동일** |
| 6 타이브레이크 | `sha256(run:scene:key:viewpoint:pool)` | `sha256(run:scene:key:pool)` — `viewpoint` 제거 |

**2단과 4단이 이번 재도출에서 추가로 고쳐진 것**(리뷰 패치 지적):

- **센티널이 `viewpoint`에 남아 있었다.** "축은 시점을 안 읽는다"고 독스트링이 주장하면서 후보를
  `"viewpoint" in p`로 걸렀으니 그 주장이 거짓이고, 고정하는 테스트도 없어서 필드 이름이 바뀌면
  **전 플레이트가 조용히 `no_metadata`로** 간다. 센티널을 **축이 실제로 쓰는 필드**로 옮겼다.
- **D1이 부재 키에 fail-open이었다.** `not p.get("has_person")`은 아무도 판정 안 한 플레이트를
  people-free로 셌다 — `is True`를 쓰는 **D2와 정반대 규약**이고, 시점 단계가 사라진 지금 D1은
  플레이트 경로의 **유일한 내용 필터**다(히트 경로가 10.2/14.4 런타임 가드 앞을 `continue`한다).
  **D2 방향으로 통일했다**: 두 큐레이터 모두 `is False`여야 통과, 판정 부재는 충족이 아니라
  `no_metadata`. 방향을 D2 쪽으로 고른 이유는 D1이 이제 마지막 방어선이고, 이 저장소가
  "미판정을 clean으로 세는" 결함을 13.1에서 이미 한 번 고쳤기 때문이다.
  **오늘 코퍼스에서 비용 0** — 42/42가 두 판정을 다 갖는다(`PREREGISTRATION.md` §7.1 표).

**resume 경계**: 다이제스트 구성이 바뀌었으므로 이 커밋을 가로질러 resume한 런은 이미 렌더된
샷은 14.1 배정을, 나머지는 14.8 배정을 갖는다. 사이드카 `stock_plate` 블록에
**`"axis": "location_key"` 마커**를 추가해 사후에 둘을 구별할 수 있게 했다(없으면 시청 판정을
받는 프레임이 두 축의 조용한 혼합이 된다). 같은 블록의 `viewpoint` 주석이 *"why THIS plate"*라고
말하던 것도 정정했다 — 이제 선택 근거가 아니라 **C4′의 입력**이고 D4 resume이 읽는 값이다.

### 5.2 상수 독자 전수조사 — 무엇을 지우지 **않았는가**

| 상수 | 독자 | 처분 |
|---|---|---|
| `_ANGLE_VIEWPOINT` | ① `image._select_plate`(이제 **멤버십만**) ② `replay_coverage.py` — servable 분모 24 **및 C4′** ③ `test_image.py`의 `_CAMERA_ANGLES` 대조 핀 | **값까지 유지 + 값을 고정하는 테스트 신설.** 선택기가 값을 안 써도 C4′가 값을 쓴다 — 지우거나 조용히 바꾸면 **축 교체의 대가를 기록할 수단이 사라진다.** 리뷰가 "값이 어느 테스트에도 안 걸려 있다"를 지적했다 |
| `_UNSERVABLE_ANGLES` | ① 선택기 ② `test_image.py` | **무변** |
| reason 어휘 | 아래 표 | 7 → **5** |

### 5.3 `interview-room/b` (`matches_location=False`) — **필터하지 않기로 명시 결정**

T2가 이 행을 측정했고 앞선 반복은 **아무 조치도 하지 않았다.** 이번에는 결정을 적는다:
**필터하지 않고, 경고도 달지 않는다.** 근거 — 그 라벨은 이 축의 2-경로 검정의 **경로 B**이고,
그 검정은 **측정 전에 커밋된** 밴드 5.0%에 대해 1/42 = 2.4%로 PASS했다. 즉 **이 한 행이 곧 밴드가
받아들인 불일치 그 자체**다. 결과를 보고 그 행만 런타임 하드 필터로 승격하는 것은 게이트를 자기
결과로 다시 재단하는 것이고, 기준을 낮추는 것의 거울상이다. 대신 **보이는 상태로 둔다**:
`verify_two_paths.py`가 매번 인쇄하고, 이 리포트 §3-3이 적고, `deferred-work.md`가 플레이트 승인
큐 담당에게 넘긴다. 그 키는 run `4b35c0ed`에 수요가 없어 오늘 걸리는 것도 없다.
(선택기 독스트링에도 같은 근거가 있다.)

### 5.4 reason 어휘가 움직인 곳 — spec은 **넷**이라고 했으나 실제로는 **다섯**

| # | 위치 | 조치 |
|---|---|---|
| 1 | `image.py` 반환값 | 두 문자열 제거 |
| 2 | `domain/state.py`의 문서 목록 | 5개로 재작성 + 은퇴 사유 명기 |
| 3 | `domain/warnings.py:63-70` 산문 | "seven reasons"·`partial_metadata` 인용 정정 |
| 4 | `replay_coverage.py` 히스토그램 | `Counter` 기반이라 자동 추종(옛 축은 CONTROL 블록으로 이동) |
| 5 | **`tests/domain/test_run_warnings.py:250,261-262`** | **spec이 놓친 곳.** `@parametrize`로 일곱 reason 등록 → 5개 |
| — | `tests/pipeline/test_gates.py:258` | **해당 없음** — warning **code**(`stock_plate_missing`) 등록이지 reason 어휘가 아니다. spec의 지목이 부정확하다 |

### 5.5 스테일 산문 넷 (앞선 반복의 독자 전수조사는 코드 독자만 훑었다)

`config.py`("plate-vs-prompt reconciliation story까지 off") · `domain/state.py`의 `ShotData`
주석("`_select_plate`가 이 필드를 플레이트 viewpoint에 매핑") · `scenario_chain.py`의 같은 주장
+ "Off by default, so today this is latent" · `domain/warnings.py`의 "seven reasons" — 넷 다
정정했다. `image.py`의 `elif` 주석("Not warned when substitution is off … it is the shipped
default")은 **정정 대상이 아니었다**: 기본값이 `False`로 남으므로 그 문장은 여전히 참이다.

### 5.6 테스트

- 순수 함수 블록을 새 축으로 갱신(15조합 교차곱 히트, 은퇴 reason 발화 불가, 센티널 양방향 핀,
  D1 반쪽 판정 거부, 다이제스트에서 viewpoint 제거).
- **결정론 테스트는 새로 만들지 않았다.** 앞선 반복은 sha256 공식을 테스트에서 재구현해 한
  인터프리터 안에서 두 번 부르고 "across processes"라고 이름 붙였다 — 자기 자신에 핀을 박는
  것(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). 이미 `test_image.py`에 세 개의
  `PYTHONHASHSEED`로 **서브프로세스** 3회를 도는 테스트가 있고 그 독스트링이 정확히 이 함정을
  경고한다. 그것을 새 축의 결정론 테스트로 확장했다(픽스처 + 독스트링).
- **`FakeSettings`의 `stock_plate_substitution=False  # mirrors the real Settings default`는
  그대로 둔다** — 코드 기본값이 `False`로 남으므로 그 주석은 참이다. spec의 태스크는 기본값을
  뒤집는 경우를 전제한 것이었다.
- OFF 경로 테스트(플래그 게이팅 파라미터화, 리졸버 미호출)는 무변경으로 통과한다.

---

## 6. 플래그 — **켜지 않았다.** 코드 기본값 `False` 유지, `DECISIONS` 행 없음

`config.py`의 판정 주석에 날짜 붙은 기록만 넣었다(정본은 주석, 규약은 CLAUDE.md):
축이 ②로 교체됐다는 것 / (a)가 **어떤 기준 위에서** 충족됐고 그 셋이 **전부 반증 불가**라는 것 /
남은 것은 (b) 하나이며 **E2E는 env 오버라이드로 돌린다**는 것.

```
uv run python scripts/report_decision_drift.py   # exit 0
  effective-vs-decided 표류: 없음 / env-sourced: 없음 / latent .env.example 핀: 없음
```
`stock_plate_substitution_enabled`는 `DECISIONS`에 없으므로 세 버킷 어디에도 뜨지 않는다.
`.env`·`.env.example` 핀도 없다(`grep -rn 'STOCK_PLATE_SUBSTITUTION' .env .env.example` 빈 출력).

**교착은 존재하지 않았다.** `Settings`가 `env_prefix="YTFLOW_"`이므로
`YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true`로 **E2E 그 한 런만** 켜면 되고, 드리프트 리포트의
`env-sourced` 버킷이 정확히 그런 일시 오버라이드를 보이라고 존재한다. 앞선 반복은 교착을 근거로
기본값을 뒤집었고, 그것은 **자기 사전등록 §5**(*"C1′~C3′ 전부 충족돼도 (b) 없이는 켜지 않는다"*)를
어긴 것이기도 했다.

---

## 7. 미완 — E2E iteration 5 (AC6)

**이 세션에서 돌리지 않았다**(GPU 0 지시, 부모 세션 소관). 절반 런으로 AC6을 주장하지 않는다.
실행 시 지켜야 할 것: `YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true` env 오버라이드(코드 기본값은
건드리지 않는다) · 시작 전 ComfyUI `/queue`의 `class_type`으로 남의 워크플로 점유 확인(HTTP 200은
GPU 여유가 아니다) · 14.9가 in-review이므로 같은 런 선점 여부 확인 · 게이트 5개는 **Jay의 판정
지점이므로 대신 승인하지 않는다** · C4′ 7샷의 프레임을 판정 패킷에 반드시 싣는다.

---

## 8. 앞선 반복이 틀린 세 가지 (지우지 않는다)

1. **(b) 미충족 상태로 출하 기본값을 `True`로 뒤집었고, 정당화한 "교착"이 거짓이었다.**
   → 이번엔 `False` 유지 + `DECISIONS` 행 미추가 + 날짜 기록만. E2E는 env 오버라이드.
2. **새 기준 셋이 전부 반증 불가인데 공허성 공시가 C3′에만 붙었고, `config.py`와 `report.md`가
   *"C1′/C2′는 live failure path를 유지한다"*는 거짓을 인쇄했다.**
   → `PREREGISTRATION.md` §7 모집단 대조 절 신설, 셋 다 `VACUOUS` 표기, 그 위에 어떤 결정도
   세우지 않음.
3. **커버리지를 낸 재생기의 people-free 술어가 런타임과 달랐다**(`plate_meta.json` 단독 vs
   `label OR plate_meta`). 오늘 수요 키가 아니라 숫자만 우연히 같았다.
   → 로더가 `source.label`을 병합한다. 대조군 재현도 이제 **단언**된다(실패 시 exit 4).

부수로 정정된 리포트 오류 셋: `ruff check`는 **clean이 아니다**(아래 §10) · `medical-bay/c`는
3샷이 아니라 **4샷**(S00702 누락)에 배정되고 draft 라벨 플레이트가 닿는 샷은 4가 아니라 **5**
(`observation-room/b` → S00604 포함) · 표본 밴드가 매니페스트 해시만 인용했으나 수치는
`plate_meta.json`과 DB에서도 나온다.

---

## 9. 미해결·인계 (전문은 `deferred-work.md`)

1. **`(b) < (c)` 심사 형식이 결과를 일부 결정했다** — 측정을 삭제하는 후보는 구조적으로 통과하고
   측정을 시도하는 후보는 구조적으로 탈락한다. 다음 리서치 게이트 설계자에게 넘기는 방법론 소견.
2. **14.4의 `background_person_guard_attempts=2`(날짜 붙은 결정)가 플레이트 경로에서 무효화된다**
   — 히트 경로가 `image.py`에서 `continue`로 가드 앞을 빠져나간다. 두 날짜 붙은 결정의 충돌을
   보고하는 계기가 없다.
3. **`_manifest_assets`의 fail-open이 치환 경로 위에 앉았다** — 매니페스트 하나가 깨지면 전 샷이
   샷별 경고만 남기고 생성으로 되돌아간다(집계 신호 없음).
4. **D1의 OR이 피연산자 하나로 돈다** (`plate_meta.has_person` 42/42 부재,
   `label.depicts_person` 42/42 부재). 채우는 비용 = `measure_plates.py --commit` 재실행,
   VLM **84콜**. 오늘의 C1′는 **상한**이다.
5. **`label.decision == "draft"`가 14/42인데 DB 행은 `approved`** — 그중 수요 키에 3장
   (`medical-bay/a`·`medical-bay/c`·`observation-room/b`), **실제 배정은 2장이 5샷에** 닿는다
   (`medical-bay/c` → S00700·S00701·**S00702**·S00703, `observation-room/b` → S00604).
6. **`medical-bay/b`는 단일 소실점이 존재하지 않는다** — 축과 무관한 **플레이트 품질 결함**.
7. **플레이트 경로에 런타임 사람 가드가 없다** — 켜는 것은 가드를 얻는 게 아니라 런타임 가드를
   승인 게이트로 **갈아타는** 것이다.
8. **프롬프트 층 도달 43/43 → 12/43**(14.5 인계).
9. **14.2 노브 미동반 · 증설 draft 5장 미승인** — 축 ②가 요구하지 않는다.

---

## 10. 검증 명령 (전부 이 세션에서 실행)

```
uv run python .../14-1-approved-plate-sets/replay_coverage.py 4b35c0ed   # exit 0, §4
uv run python .../14-8-plate-reuse-shipping/verify_two_paths.py          # exit 0, §3 (Phase 1)
uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_location_service.py \
              tests/test_report_decision_drift.py tests/pipeline/test_gates.py -q   # 243 passed
uv run pytest -q                                                         # 전체 — §10 아래
uv run python scripts/report_decision_drift.py                           # exit 0, 세 버킷 무등장
uv run ruff check                                                        # 아래
git diff --stat assets/ prompts/                                         # 빈 출력
grep -rn 'STOCK_PLATE_SUBSTITUTION' .env .env.example                    # 빈 출력 (exit 1)
```

**`ruff check`는 clean이 아니다 — 기존 2건, 신규 0건.** 앞선 리포트는 "clean"이라고 적었고 그것은
거짓이었다. 두 건 다 이 스토리가 건드리지 않은 파일이다:
`10-1b-live-validation/measure.py:63` E731(람다 대입) · `14-3-art-style-contract/measure_palette.py:148`
F541(플레이스홀더 없는 f-string).

**전체 스위트**: `tests/test_render_pose_guides.py`의 PNG SHA 핀 1건이 실패한다. 이것은 이 스토리의
회귀가 **아니다** — 14.1/14.5/14.6이 이미 기록한 기존 결함이고, `git stash` 후에도 같은 실패임을
확인해 구별했다(절차는 §11).

---

## 11. 전체 스위트 — 기존 실패 1건임의 증명

```
uv run pytest -q
  1 failed, 3455 passed, 1 skipped, 1 xfailed, 1 warning in 380.26s (0:06:20)   # 최종 커밋 상태 재실행
  FAILED tests/test_render_pose_guides.py::test_render_is_deterministic_and_content_pinned[humanoid_lying_supine]
```

**같은 실패가 이 스토리 이전 상태에서도 난다**(작업분 stash → 스토리 이전 커밋 `c19d64c`의
`src`·`tests` 체크아웃 → 같은 테스트):

```
git stash push -u -- src/ tests/ .../14-8-plate-reuse-shipping/report.md
git checkout c19d64c -- src tests
uv run pytest tests/test_render_pose_guides.py -q
  FAILED tests/test_render_pose_guides.py::test_render_is_deterministic_and_content_pinned[humanoid_lying_supine]
  1 failed, 14 passed in 0.53s
  assert '48c55bc289a0…dcb6e06f5d7b0' == 'fbeb030b0753…5d72f28926520'
git checkout HEAD -- src tests && git stash pop
uv run pytest tests/test_render_pose_guides.py -q
  FAILED … [humanoid_lying_supine]
  1 failed, 14 passed in 0.54s
```

**두 상태의 실패 SHA가 같다** → 14.1/14.5/14.6이 기록한 기존 결함이고 이 스토리의 회귀가 아니다.
스위트의 나머지 3455건은 통과한다.
