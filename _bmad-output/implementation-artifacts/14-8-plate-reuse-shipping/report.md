# Story 14.8 리포트 — 플레이트 재활용 출하 (Phase 2, 2026-08-30)

Phase 1(축 심사 + 사전등록, 커밋 `d797a8a`/`5746918`)의 결론 위에 얹은 Phase 2 측정·출하 기록.
**GPU 0 · VLM 콜 0 · 렌더 0.** 모든 수치에 재산출 명령이나 커밋된 출처를 붙인다
(`gotcha_a-measurement-without-its-sample-band`).

---

## 1. 표본 밴드 — 이 리포트의 모든 수치가 유효한 범위

| 항목 | 값 | 출처 / 재산출 |
|---|---|---|
| 승인 플레이트 | **42장** (14 키 × 3 변형) | `location_plates WHERE status='approved'` |
| 매니페스트 스냅샷 | `sha256 a094b7c585228c872ce70e3f656ff9e61aad51f51c8e2ab593a71831b0c14dd6` | `sha256sum assets/manifest.json` |
| 런 | `4b35c0ed-8a1e-4448-8594-11bd9997376d` (E2E iteration 4) | `replay_coverage.load_scenes` |
| 샷 | 43 총, **31**이 `location_key` 보유, **24**가 servable | `close-up` 6 + `POV` 1 제외 |
| 어포던스 노브 | `plate_affordance_gate_enabled=False` (이 스토리에서 켜지 않음) | `config.py:448` |
| 사전등록 | `PREREGISTRATION.md`, 커밋 **`d797a8a`** — 측정보다 **앞선다** | `git log --oneline --diff-filter=A -- .../PREREGISTRATION.md .../verify_two_paths.py` |

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
`location_key`는 시나리오 LLM이 쓰는 닫힌 14값 enum 데이터 필드(`domain/state.py:247-263`)이고
플레이트 쪽은 매니페스트 키라, 배정 연산이 **문자열 동등성**이다. 경계 근처라는 상태가 없다.

---

## 3. T2 2-경로 검증 — 전체 출력

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
   갈릴 두 값이 없다. 이것은 고쳐지지 않았고 인계된다(§8).
2. **P4의 `server-room/b` 모순은 살아 있다** — VLM은 *"no visible floor"*라 `standing_room=False`,
   사람 맹검 판독은 `floor_share 0.85`. 사전등록이 **측정 전에** 고정한 모순 방향 검정
   (`False ∧ floor_share ≥ 0.20`)에 정확히 걸린 유일한 행이고, `server-room`은 이 런의 수요 키가
   아니라 커버리지에는 영향이 없다. **해소하지 않고 기록한다.**
3. **P1의 유일한 불일치 `interview-room/b`** — 구조 경로는 `interview-room`, 8.17 라벨러는
   `matches_location=False`. 수요 키가 아니다. 1/42 = 2.4% < 밴드 5.0% → PASS.

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
  C1' key coverage      : PASS (6/6 keys)
  C2' affordance coverage: PASS
  C3' servable share >= 90%: PASS (24/24 = 100.0%)   [vacuity disclosed in advance, PREREGISTRATION §3]

-- CONTROL: retired 14.1 axis (camera_angle -> plate viewpoint), same inputs --
  C1  cell coverage      : FAIL (5/10 cells)
  C2  affordance coverage: PASS
  C3  servable share >= 90%: FAIL (17/24 = 70.8%)
  axis change: servable match 17 -> 24 (70.8% -> 100.0%), C4' cost 7 mismatched hit(s)
```

**대조군의 유효성은 가정이 아니라 검사됐다.** `replay_coverage.py`가 다시 표현한 은퇴 축은
14.1이 커밋한 수치(`14-1-approved-plate-sets/report.md:227-244` — C1 FAIL 5/10, C2 PASS,
C3 FAIL 17/24 = 70.8%)를 **그대로 재생한다.** 재생하지 못하는 대조군은 고장난 대조군이다.

### ⚠️ C3′의 공허성 — 사전등록이 **측정 전에** 예고한 것

`PREREGISTRATION.md` §3은 축 ② 아래에서 **C3′가 이 런의 데이터로는 실패할 수 없다**고
측정 전에 적었다(6개 수요 키가 전부 C1′를 통과하면 예측값 24/24). 실제 결과가 정확히 그것이다.
따라서 **C3′ PASS는 이 스토리의 증거로 계상되지 않는다** — 사후 변명이 아니라 사전 공시다.
그럼에도 **24와 0.90은 한 글자도 바꾸지 않았다**: 그 둘이 "기준을 낮추지 않았다"의 유일한
고정점이기 때문이다.

**실제로 하중을 받는 판정은 C1′/C2′이고, 둘 다 살아 있는 실패 경로를 가진다**:
- C1′: `entrance-checkpoint/b`는 `label.has_person=true`인 채 `approved`이고 D1이 그것을
  후보에서 뺀다. 어느 수요 키의 3장이 전부 그 플래그를 받으면 C1′는 MISS다.
- C2′: `server-room/b`·`/c`는 `standing_room=false`다. `server-room`에 cast 샷이 키잉되면
  `server-room/a` 한 장에 키 전체가 걸린다.
- 규칙상: `no_metadata` 3샷만 나면 21/24 = 87.5%로 C3′도 FAIL이다.

### C4′ — 새 축의 대가, 임계값 없는 의무 공개

```
-- C4' viewpoint mismatches among the hits (no threshold, disclosure only) --
  7/24 assigned plates sit at a viewpoint the shot's camera_angle did not ask for
    S00402 camera_angle=low-angle (wants LOW) -> containment-chamber/b measured EYE
    S00404 camera_angle=high-angle (wants HIGH) -> corridor/c measured EYE
    S00604 camera_angle=high-angle (wants HIGH) -> observation-room/b measured EYE
    S00702 camera_angle=high-angle (wants HIGH) -> medical-bay/c measured EYE
    S00803 camera_angle=low-angle (wants LOW) -> containment-chamber/b measured EYE
    S00902 camera_angle=low-angle (wants LOW) -> observation-room/c measured EYE
    S00904 camera_angle=high-angle (wants HIGH) -> observation-room/c measured EYE
```

**7/7이 옛 축이 `no_viewpoint_match`로 거절하던 바로 그 샷들이다**(고 4 + 저 3, `AXIS-CANDIDATES.md` ②).
그중 **5샷이 cast를 가진다**(S00402·S00702·S00803·S00902·S00904, 카드 합 6). `camera_angle`은
render-inert가 **아니다** — `character_service.py:1556`이 그것을 샷별 카탈로그에 복사하고
`_select_entity_angles`가 카드 앵글을 거기서 고른다(`gotcha_camera-angle-reaches-pixels-by-a-second-path`).
즉 **부감/앙각용 카드가 눈높이 플레이트 위에 합성된다.**

**이 리포트는 그것이 허용 가능하다고 주장하지 않는다.** 크기와 경로를 실측으로 적을 뿐이고,
판정은 Jay의 E2E iteration 5 시청이다.

**Phase 1의 조건부 예측 3샷은 실현되지 않았다.** `AXIS-CANDIDATES.md`는 `autopsy-room` 풀이
2→3으로 넓어지면서 `S00600`·`S00602`·`S00603`이 부감 플레이트(`autopsy-room/b`, 측정 HIGH)를
받을 **수 있다**고 적었다. 실제로는 sha256 타이브레이크가 셋 모두에 `autopsy-room/a`(EYE)를
줬다. 그래서 C4′는 7이지 10이 아니다 — **이 3은 축의 성질이 아니라 다이제스트의 우연이고,
run_id·씬·풀이 바뀌면 뒤집힌다.** 예측을 지우지 않고 이렇게 남긴다.

---

## 5. 코드 변경 — `_select_plate`와 그 사본

### 5.1 선택기 (`src/yt_flow/pipeline/nodes/image.py`)

시점 단계(옛 `:641-643`)만 제거했다. 사슬의 나머지는 그대로다.

| 단 | 옛 (14.1) | 새 (14.8) |
|---|---|---|
| 1 프레이밍 | `_ANGLE_VIEWPOINT.get(angle)` → 값 사용 | **멤버십만** — `angle not in _ANGLE_VIEWPOINT` |
| 2 메타데이터 | `"viewpoint" in p` (존재) | **동일** — 존재 검사, 값 미비교 |
| 3 시점 정합 | `p["viewpoint"] == viewpoint` | **삭제** |
| 4 D1 사람 | `has_person`/`depicts_person` | **동일** |
| 5 D2 어포던스 | 노브 + `standing_room is True` | **동일** |
| 6 타이브레이크 | `sha256(run:scene:key:viewpoint:pool)` | `sha256(run:scene:key:pool)` — `viewpoint` 제거 |

- **`viewpoint`가 다이제스트 키에서 빠진 이유**: 남겨두면 한 방 안 두 샷이 *선택기가 더 이상 읽지
  않는 값* 때문에 다른 플레이트를 받는다 — 은퇴한 측정에 대한 숨은 의존이고 14.1보다 나쁜 연속성이다.
  살아남는 주장: **(run, scene, location_key, candidate set)당 한 장.**
- **`no_metadata`의 fail-open은 유지**된다. `"viewpoint" in p`는 여전히 읽지만 **값이 아니라
  존재**이고, `resolve_stock_plates`가 문서화한 대로 미측정 플레이트는 `viewpoint` 키 자체가 없다.
  이 게이트가 없으면 라벨 안 된 플레이트가 **부재 필드 때문에** D1을 그냥 통과한다(8.17 재현).

### 5.2 상수 독자 전수조사 — 무엇을 지우지 **않았는가**

`gotcha_deleting-a-constant-needs-a-reader-census`. 지우기 전에 저장소 전체를 훑었다.

| 상수 | 독자 | 처분 |
|---|---|---|
| `_ANGLE_VIEWPOINT` | ① `image._select_plate`(이제 **멤버십만**) ② `replay_coverage.py:40` — servable 분모 24 **및 C4′** 계산 ③ `test_image.py`의 `_CAMERA_ANGLES` 대조 핀 | **값까지 그대로 유지.** 선택기가 값을 안 써도 C4′가 값을 쓴다 — 지우면 **축 교체의 대가를 기록할 수단이 사라진다.** 게으른 diff가 지우는 diff가 아닌 경우. |
| `_UNSERVABLE_ANGLES` | ① 선택기 ② `test_image.py:1088` | **무변**. close-up/POV는 시점 축과 무관한, 설계상 영구 폴백이다. |
| reason 어휘 | 아래 표 | 7 → **5**. `no_viewpoint_match`·`partial_metadata` 은퇴. |

**은퇴한 두 reason이 발화 불가임의 증명**: 시점 단계가 없으므로 메타데이터 단계 뒤에 매칭 단계가
없다 → 비어 있지 않은 `measured` 풀은 곧 비어 있지 않은 후보 풀이다. 발화할 수 없는 reason을
남겨두면 **은퇴한 축이 출하 중인 것처럼 문서화된다.**

### 5.3 reason 어휘가 움직인 곳 — spec은 **넷**이라고 했으나 실제로는 **다섯**이다

| # | 위치 | 조치 |
|---|---|---|
| 1 | `image.py` 반환값 | 두 문자열 제거 |
| 2 | `domain/state.py`의 문서 목록 | 5개로 재작성 + 은퇴 사유 명기 |
| 3 | `replay_coverage.py` 히스토그램 | `Counter` 기반이라 자동 추종(옛 축은 CONTROL 블록으로 이동) |
| 4 | `tests/pipeline/test_gates.py:258` | **해당 없음** — 거기 있는 것은 warning **code**(`stock_plate_missing`) 등록이지 reason 어휘가 아니다. spec의 지목이 부정확하다. |
| 5 | **`tests/domain/test_run_warnings.py:250,261-262`** | **spec이 놓친 곳.** `@parametrize`로 일곱 reason을 하나씩 등록하고 있었다. 5개로 축소하고, 다섯 곳이라는 사실을 그 자리에 주석으로 남겼다. |
| 6 | `domain/warnings.py:63-66` (산문) | "seven reasons"·`partial_metadata` 인용을 정정 |

### 5.4 `replay_coverage.py` — C-규칙 사본

같은 커밋에서 움직였다(이 파일이 C-규칙의 두 번째 사본이라는 것이 알려진 동기화 위험이다).
`C3_MIN_SHARE = 0.90`과 servable 필터는 **바이트 무변**. 셀만 `(key, viewpoint)` → `key`.
C4′ 블록과 은퇴 축 CONTROL 블록을 신설.

---

## 6. 플래그 — 켰다

`stock_plate_substitution_enabled: bool = True` (`config.py`), 날짜 붙은 판정 주석 + `DECISIONS` 행,
`.env`·`.env.example` 핀 **없음**.

```
uv run python scripts/report_decision_drift.py   # exit 0
     stock_plate_substitution_enabled = True  (decided True by story 14.8, 2026-08-30)  source: code default
```
세 버킷(effective-vs-decided 표류 / env-sourced / latent `.env.example` 핀) 어디에도 뜨지 않는다.

**켜면서 함께 갱신한 산문**: `config.py`의 해제 조건 (a) 항목(옛 C1/C2/C3가 왜 미달이었고 그것이
세트 부족이 아니라 축의 문제였는지), 그리고 `:355-357`의 *"no `.env` pin, and NO `DECISIONS` row"*
문장, `:729-732`의 *"NO DATE, so no row"* 목록에서 이 필드 제거. 주석이 정본이고 `DECISIONS` 행은
색인이라는 규약이 자기모순에 빠지지 않도록 셋을 한 커밋에서 맞췄다.

**결정값이 기본값과 같은지 단언하는 테스트는 만들지 않았다** — CLAUDE.md가 금지한다(드리프트
리포트를 게이트로 만드는 우회). `test_image.py`의 `FakeSettings`는 `False`로 남기되 주석을
*"mirrors the real Settings default"*에서 **"의도적으로 다르다"**로 고쳤다(같은 파일이
`guard_attempts`에서 이미 쓰는 형식).

---

## 7. ⚠️ 이 스토리 안에서 서로 모순되는 두 지시 — 조용히 고르지 않고 기록한다

| 문서 | 말하는 것 |
|---|---|
| `PREREGISTRATION.md` §5 (Phase 1, 커밋 `d797a8a`) | *"플래그를 켜는 조건을 바꾸지 않는다. (a)커버리지 ∧ (b)Jay 시청 판정은 그대로다. **C1′~C3′ 전부 충족돼도 (b) 없이는 켜지 않는다.**"* |
| spec `## Tasks & Acceptance` + AC | *"커버리지 전부 충족 시에만: 기본값 `True` … (b) Jay 시청 판정은 E2E iteration 5에서 받는다는 잠정성을 적고"* / *"Given 새 축의 커버리지가 전부 충족, when 스토리가 끝나면, then `config.py`의 코드 기본값이 `True`"* |

**둘 다 지킬 수는 없다.** 교착의 실체: spec의 E2E 태스크가 *"플래그가 켜진 경우에만"* 조건부라
**(b)를 얻으려면 먼저 켜야 한다.** 그래서 spec을 따랐고, 그 선택과 이유를 `config.py` 주석 안에
**판정 자체와 같은 자리에** 적었다. **이것은 기준을 낮춘 것이 아니다** — C1′/C2′/C3′의 임계값,
servable 분모 24, `C3_MIN_SHARE=0.90`은 전부 무변이다. 바뀐 것은 (b)를 **언제** 받느냐다.

되돌리는 비용은 한 줄이다: `config.py`의 기본값을 `False`로, `DECISIONS` 행 삭제. Jay가
사전등록 쪽 해석을 택하면 그렇게 하면 된다.

---

## 8. 미해결·인계 (전문은 `deferred-work.md`)

1. **`plate_meta.has_person` 42/42 부재 · `label.depicts_person` 42/42 부재** → D1의 OR이 오늘
   **피연산자 하나로** 돈다. 빠진 쪽이 채워지면 수요 키의 풀은 **줄어들 수만 있다** — 즉 오늘의
   C1′ 판정은 **상한**이다. `measure_plates.py --commit` 재실행에 VLM 84콜이 들고 한 번도 안 했다.
2. **`label.decision == "draft"`가 14/42인데 DB 행은 `status="approved"`** — 어느 C-규칙도 이
   필드를 안 읽는다. 그중 **3장이 수요 키에 있고**(`medical-bay/a`·`medical-bay/c`·
   `observation-room/b`), 그중 **둘은 이 런에서 실제로 배정된다**(`medical-bay/c` → S00700·S00701·
   S00703, `observation-room/b` → S00604). 즉 **draft 라벨이 붙은 플레이트가 화면에 나간다.**
3. **`medical-bay/b`는 단일 소실점이 존재하지 않는다** — 추정기가 세 설정에 0.93/0.97/0.41로
   발산하고 수동 선쌍이 기하학적으로 불가능한 곳에서 만난다(`REREAD-2026-08-30.md:41-50`).
   **축과 무관한 플레이트 품질 결함**이고 이 스토리에서 고치지 않았다.
4. **플레이트 경로는 10.2/14.4 런타임 사람 가드를 건너뛴다**(`image.py:1043`의 `continue`).
   켜는 것은 **런타임 가드를 승인 게이트로 갈아타는 것**이지 가드를 하나 더 얻는 것이 아니다.
5. **프롬프트 층 도달 43/43 → 12/43** — 이후 모든 프롬프트 측정은 그 분모를 명시해야 한다(14.5 인계).
6. **14.2 어포던스 노브는 동반하지 않았다**(`plate_affordance_gate_enabled=False` 유지). 선행 조건인
   14.2의 33-pair 판정이 미충족이다.
7. **증설 draft 5장은 승인하지 않았다** — 축 ②가 그것들을 요구하지 않는다. 승인은 별개 판정이다.
8. **E2E iteration 5는 이 세션에서 돌리지 않았다** (GPU 0 지시). 부모 세션 소관.

---

## 9. 검증 명령 (전부 이 세션에서 실행)

```
uv run python .../14-1-approved-plate-sets/replay_coverage.py 4b35c0ed   # §4
uv run python .../14-8-plate-reuse-shipping/verify_two_paths.py          # §3
uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_location_service.py \
              tests/test_report_decision_drift.py tests/pipeline/test_gates.py -q
uv run pytest -q                                                         # 전체
uv run python scripts/report_decision_drift.py                           # exit 0, 세 버킷 무등장
ruff check
git diff --stat assets/ prompts/                                         # 빈 출력
grep -rn 'STOCK_PLATE_SUBSTITUTION' .env .env.example                    # 빈 출력
```
