# 사전등록 — Story 14.8: 새 매칭 축(②)의 2-경로 밴드 + 새 커버리지 기준 (2026-08-30)

이 파일은 **`verify_two_paths.py`를 한 번도 실행하기 전에** 작성하고 **커밋한다.** 커밋 해시가
"기준이 측정보다 앞섰다"의 증거다(§6). 결과를 보고 여기를 고치지 않는다.

채택 축은 `AXIS-CANDIDATES.md` ② — **`shot.location_key == plate.location_key`**, 기존 필터
(D1 people-free · D2 어포던스 노브 · `_UNSERVABLE_ANGLES`) 승계, `viewpoint`는 **선택에서 안 읽음**.

---

## 0. ⚠️ 맹검 한계 — 이 문서를 쓸 때 이미 알고 있던 것

14.1의 `PREREGISTRATION.md` §2가 자기 맹검 침해를 결과 전에 적은 전례를 그대로 따른다.
**이 밴드는 맹검이 아니다.** 축을 고르기 위해 `assets/manifest.json`의 **필드 전수조사**를 먼저
돌렸고(모집단 전수 대조, `gotcha_closing-a-class-needs-a-population-sweep`), 그래서 아래를
**이미 알고 있는 상태**로 밴드를 적었다:

- `source.label`은 8개 필드를 갖고 **`depicts_person`이 없다**(그 필드는 14.1이 신설했다).
- `source.plate_meta`는 10개 필드를 갖고 **`has_person`이 없다**(42/42).
- `label.decision == "draft"`가 **14/42**(그럼에도 `status="approved"`).
- `label.matches_location == false`가 **1/42**, `label.has_person == true`가 **1/42**.
- `plate_meta.standing_room is False`가 **2/42**, `plate_meta.depicts_person == true`가 **0/42**.

따라서 §2의 밴드는 **눈감고 고른 숫자가 아니다.** 이 문서의 실효는 (i) 무엇이 PASS/FAIL이고
무엇이 UNDEFINED인지를 **측정 전에** 고정하는 절차적 구속과 (ii) 커버리지 기준을 결과 전에
박는 것이며, **블라인드 사전등록으로 읽으면 안 된다.** 결과가 밴드 안이어도 그것은 재현성의
**상한**으로 읽는다(14.1 §2의 "일치율은 하한이 아니라 상한" 과 같은 형태).

---

## 1. 2-경로 검증의 대상 — 축이 실제로 쓰는 **모든** 술어

②의 배정 결정에 들어가는 술어는 넷이고, 넷 **전부**에 대해 두 경로를 찾아 불일치를 낸다
(한 술어만 보고 "2-경로 검증 완료"라고 적지 않는다):

| # | 술어 | 경로 A | 경로 B | 게이트 |
|---|---|---|---|---|
| P1 | **`location_key`** (축 본체) | **구조**: 매니페스트 엔트리 키 `<key>/<variant>` · `assets[k].location_key` · `path` · `location_plates` 행 | **판정**: `source.label.matches_location` — 8.17 라벨러가 `LOCATION_PROMPTS[key]` 설명을 보여주고 "이 이미지가 그 방인가"를 물은 별개 VLM 콜 | **B1** |
| P2 | D1 `has_person` | `source.label.has_person` (2026-08-02 라벨러) | `source.plate_meta.has_person` (2026-08-25 재판정) | 보고 전용 |
| P3 | D1 `depicts_person` | `source.plate_meta.depicts_person` (2026-08-25) | `source.label.depicts_person` (8.17 라벨러) | 보고 전용 |
| P4 | D2 `standing_room` | `source.plate_meta.standing_room` (VLM `plate_has_standing_room`) | 사람 맹검 `floor_share` (`viewpoint_verdicts.csv`) | 보고 전용 |

**왜 P1만 게이트인가.** 이 스토리가 교체하는 것은 `camera_angle → viewpoint` **매칭 축** 하나다.
P2~P4는 옛 축 아래에서도 이미 출하 중이던 **승계 필터**이고, 그것들의 결함을 축 교체의 통과
조건으로 삼으면 축 교체가 자기보다 오래된 결함의 책임을 지게 된다. 그래서 **보고하되 게이트하지
않는다** — 다만 다음 규칙 U 때문에 "보고 전용"이 "묻어두기"가 되지는 않는다.

**규칙 U (측정 전 고정)**: 어떤 술어의 두 경로 중 한쪽이 42행 **전부에서 값을 쓰지 않았다면**,
그 술어의 불일치율은 `UNDEFINED (0 comparable rows)`로 찍고 **PASS로 계상하지 않는다.**
미판정을 clean으로 세는 것이 13.1이 없애려던 결함이다. UNDEFINED는 리포트의 미해결 항목이자
인계 항목이 되며, 축의 통과·기각과는 무관하다.

**P4의 비교 규칙 (측정 전 고정)**: 두 경로는 **같은 질문이 아니다**(A: 설 자리가 있는가 /
B: 바닥이 보이는가). 그러므로 **모순 방향만** 불일치로 센다:
- `standing_room is True` **그리고** `floor_share == 0.00` → 불일치, 또는
- `standing_room is False` **그리고** `floor_share >= 0.20` → 불일치.
그 외는 불일치가 아니다. `0.20`의 근거: `floor_share`는 손으로 읽은 폴리곤 추정이고 오차가
**±0.03**이므로(`REREAD-2026-08-30.md:50`) 그 6배를 넘는 값은 읽기 오차로 설명되지 않는다.
이 모순 검정은 `report.md:147-158`이 `server-room/b`(사람 `floor_share 0.85` ↔ VLM *"no visible
floor"*)에 이미 적용한 것과 **같은 검정**이다.

## 2. 밴드 B1 — 측정 전에 박는 숫자

> **B1 = 5.0%.** P1의 두 경로 불일치가 승인 42장 중 **≤ 2행**이면 PASS, **≥ 3행**이면 FAIL.

**근거(새 데이터와 무관하게 성립하는 것):** 은퇴한 축은 같은 이미지에 대한 두 판정자의
**범주 뒤집힘이 2/5 = 40%**였다(`AUGMENTATION-BATCH-2026-08-30.md:45`). 교체 축이 채택될 값이
있으려면 재현성이 최소한 한 자릿수 좋아야 한다 — 40%를 한 자릿수(≈8배) 접어 **5%**로 둔다.
42행에서 5.0%는 2.1행이므로 컷은 2행/3행 사이다.

**FAIL 시 처리(고정)**: `Block If`대로 ②를 기각하고 T1으로 1회 복귀한다. 남은 후보 ①③④는
전부 이미 `(b) ≥ (c)`로 기각됐으므로, ②가 FAIL이면 **HALT `no admissible matching axis`** 다.

---

## 3. 새 커버리지 기준 — 옛 C1/C2/C3 각각의 처분

### 낮추지 않는 고정점 (한 글자도 안 바꾼다)

- **servable 분모 = 24샷.** 유도: run `4b35c0ed`의 43샷 중 `location_key` 보유 **31**,
  거기서 `close-up` **6** + `POV` **1** 제외 = **24**. 그 7샷은 방 플레이트가 서빙할 수 없는
  **설계상 영구 폴백**이고 결함이 아니다(`_UNSERVABLE_ANGLES`, `image.py:549-559`).
- **`C3_MIN_SHARE = 0.90`** (`replay_coverage.py:46`).
- **D1은 노브와 무관하게 항상 발화**, **D2 노브(`plate_affordance_gate_enabled`)는 이 스토리에서
  켜지 않는다.**
- `standing_room` **키 부재는 판정불가이지 충족 아님**(14.1 §4 그대로).

### C1 → **C1′ (대체 REPLACED)**

옛 C1: 10개 `(location_key, viewpoint)` 셀 각각에 시점 일치 + `depicts_person != true` 플레이트 ≥1장.

> **C1′**: run `4b35c0ed`의 servable 24샷이 요구하는 **6개 `location_key`** 각각에 대해,
> 그 키의 승인 플레이트 중 **D1(people-free, 두 큐레이터 OR)** 을 통과하는 것이 **≥1장** 있다.

셀에서 `viewpoint` 성분이 빠진 것이 유일한 변경이다. 6키의 유도: `replay_coverage.py 4b35c0ed`의
`-- demanded cells --` 10셀을 키로 접으면 autopsy-room · containment-chamber · control-room ·
corridor · medical-bay · observation-room.

**오늘 데이터에서 실패할 수 있는 경로**: D1의 배제는 **오늘 이미 발화한다** —
`entrance-checkpoint/b`는 `label.has_person=true`인 채 `approved`이고
(`report.md` §2, epics.md:1982) `location_service.py:105-112`의 OR이 그것을 후보에서 뺀다.
수요 키 하나의 3장이 전부 그 플래그를 받으면 C1′는 MISS다. 그리고 **`plate_meta.has_person`이
42/42 부재**(14.1이 `--commit`을 재실행하지 않았다, epics.md:1982)이므로 그 OR은 오늘 **피연산자
하나로** 돌고 있다 — 빠진 쪽이 채워지면 수요 키의 풀은 **줄어들 수만 있고 늘 수 없다.**
**즉 오늘의 C1′ 판정은 상한이다.**

### C2 → **C2′ (유지 RETAINED, 셀만 재범위)**

> **C2′**: cast 샷이 있는 수요 `location_key` 각각에 대해, C1′를 통과한 플레이트 중
> **`standing_room is True`** 인 것이 **≥1장** 있다.

기준 자체는 옛 C2와 같고, 셀 정의가 C1′를 따라 키 단위로 좁아진 것뿐이다.

**오늘 데이터에서 실패할 수 있는 경로**: `server-room/b`·`/c`는 `standing_room=false`다
(`report.md:94-95`). `server-room`에 cast 샷이 키잉되면 `server-room/a` 한 장에 키 전체가 걸리고,
그 한 장이 D1이나 엔드포인트 거부(키 부재 = 판정불가)로 빠지면 C2′는 MISS다. 그 키는 이미
**3장 중 2장이 미달**이다.

### C3 → **C3′ (유지 RETAINED, 한 글자도 안 바꿈)**

> **C3′**: 선택기 오프라인 재생에서 servable **24**샷 중 **≥90%(≥22샷)** 가 `match`.

**⚠️ 공허성을 측정 전에 예고한다.** ②에서 6개 수요 키가 전부 C1′를 통과하면 예측값은
**24/24 = 100%**이고, 그렇다면 **C3′는 run `4b35c0ed`에서 실패할 수 없다.** 이것을 결과를 보고
나서 변명하지 않기 위해 여기 미리 적는다. **그럼에도 낮추지도, 새 임계값으로 갈아치우지도
않는다** — 24와 0.90이 "기준을 낮추지 않았다"의 유일한 고정점이기 때문이다.

**규칙상 살아 있는 실패 경로**(이 런에서는 안 터진다): `no_metadata`(그 키의 승인 플레이트에
`plate_meta`가 한 장도 없음 — 재시딩이 `add_asset`을 타면 `status`가 draft로 돌아가며 실현,
`measure_plates.py:14-16`) · `partial_metadata` · `plate_shows_person`(위 C1′ 경로) ·
`no_standing_room`(노브 ON일 때). **3샷만 이쪽으로 빠지면 21/24 = 87.5%로 FAIL이다.**

**그러므로 C3′ 하나로 "축이 통했다"를 주장하지 않는다.** ②가 실제로 바꾼 것은 전환된 7샷이고,
그 전환의 대가는 커버리지 숫자가 아니라 시청 판정이다 → C4′.

### C4′ (신설 NEW — 공개 의무, 임계값 없음)

> **C4′**: 히트한 샷 중 플레이트의 측정 `viewpoint`가 `_ANGLE_VIEWPOINT[camera_angle]`와
> **다른** 샷의 **수와 전체 목록**을, `report.md`와 Jay의 E2E iteration 5 패킷에 **반드시** 싣는다.

②가 포기하는 것이 정확히 이것이고, 숫자 없이 넘어가면 옛 축이 존재한 이유가 기록에서 사라진다.
예측값: 옛 축이 `no_viewpoint_match`로 거절하던 **7샷**(`AXIS-CANDIDATES.md` ② 표) + `autopsy-room`
풀 확대로 조건부 3샷.

**임계값은 사전등록하지 않는다.** 근거 있는 숫자가 없고, 근거 없는 임계값을 만드는 것은 기준을
낮추는 것의 **거울상**이다. C4′의 실패 모드는 **그 숫자가 리포트에 없는 것**이다.

---

## 4. 옛 기준은 대조군으로 함께 출력한다

Phase 2의 `replay_coverage.py`는 새 기준과 함께 **옛 축의 판정(C1 FAIL 5/10 · C2 PASS ·
C3 FAIL 17/24 = 70.8%)** 을 한 화면에 출력한다. 축 교체의 효과와 대가를 한 눈에 대조할 수 없으면
이 스토리는 자기 결과를 검증할 수 없다.

## 5. 이 사전등록이 **하지 않는** 것

- **플래그를 켜는 조건을 바꾸지 않는다.** `config.py:304-357`의 (a)커버리지 ∧ (b)Jay 시청 판정은
  그대로다. C1′~C3′ 전부 충족돼도 (b) 없이는 켜지 않는다.
- **`plate_meta`·`label`의 기존 값을 덮어쓰지 않는다.** 새 값은 병기한다
  (`REREAD-2026-08-30.md:39`).
- **draft 5장**(`containment-chamber/e`·`corridor/d`·`medical-bay/d`·`observation-room/{d,e}`)을
  승인하지 않는다. ②는 그것들을 요구하지 않는다.
- **14.2 어포던스 노브를 켜지 않는다.**
- **픽셀을 새로 판정하지 않는다.** T2는 이미 매니페스트에 있는 판정만 대조한다(VLM 콜 0, GPU 0).

## 6. 커밋 순서 증명

이 파일은 `verify_two_paths.py` **실행 전에** 커밋한다. 확인:

```
git log --oneline --diff-filter=A -- \
  _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/PREREGISTRATION.md \
  _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/verify_two_paths.py
```

<!-- 사전등록 커밋 해시: 아래 줄은 이 파일이 커밋된 뒤 후속 커밋에서만 채운다. -->
**사전등록 커밋**: `d797a8a` — `verify_two_paths.py`는 이 커밋에 **없었다**(다음 커밋에서 추가됐다). 위 명령의 `--diff-filter=A` 출력이 두 파일의 추가 순서를 보여준다.

---

## 7. 반증 가능성의 모집단 대조 (2026-08-30 추가 — 리뷰 패스 1 이후, Phase 2 재도출 중)

> **이 절은 위의 §1~§6을 한 글자도 고치지 않는다.** 위 텍스트는 측정 전에 커밋된 그대로
> 남고(`d797a8a`), 이 절은 그 위에 **검사 결과**를 얹는다. 무엇이 고쳐졌는지가 기록에서
> 읽히려면 덮어쓰는 게 아니라 덧붙여야 한다.

**왜 필요한가.** §3은 새 기준마다 *"오늘 데이터에서 실패할 수 있는 경로"*를 한 줄씩 적으라는
스펙 요구를 따랐고 C3′에는 공허성을 **미리** 공시했다. 그러나 C1′·C2′에 적은 실패 경로는
**모집단에 대조되지 않은 채로** 적혔고, 리뷰가 대조해 보니 **셋 다 발화 불가**였다. 사례를
하나 들어 "경로가 있다"고 적는 것과 모집단 전수로 "이 경로가 오늘 발화 가능하다"를 보이는 것은
다른 일이다(`gotcha_closing-a-class-needs-a-population-sweep`).

### 7.1 실측 기준선 — 승인 42장 전수 (재산출 명령은 §7.4)

| `location_key` | 승인 | 사람판정 보유 | D1 통과(people-free) | 그중 `standing_room is True` | 이 런의 수요 |
|---|---|---|---|---|---|
| autopsy-room | 3 | 3 | 3 | 3 | **YES** |
| cafeteria | 3 | 3 | 3 | 3 | - |
| containment-chamber | 3 | 3 | 3 | 3 | **YES** |
| control-room | 3 | 3 | 3 | 3 | **YES** |
| corridor | 3 | 3 | 3 | 3 | **YES** |
| entrance-checkpoint | 3 | 3 | **2** | 2 | - |
| facility-exterior | 3 | 3 | 3 | 3 | - |
| interview-room | 3 | 3 | 3 | 3 | - |
| maintenance-tunnel | 3 | 3 | 3 | 3 | - |
| medical-bay | 3 | 3 | 3 | 3 | **YES** |
| observation-room | 3 | 3 | 3 | 3 | **YES** |
| office | 3 | 3 | 3 | 3 | - |
| server-room | 3 | 3 | 3 | **1** | - |
| storage-vault | 3 | 3 | 3 | 3 | - |

파생 사실: **14키 전부 승인 3장씩(42/42)** · `plate_meta.depicts_person == true` **0/42** ·
`label.has_person == true` **1장**(`entrance-checkpoint/b`) · `standing_room is False` **2장**
(`server-room/b`·`/c`) · `plate_affordance_gate_enabled = False`(`config.py`, 이 스토리에서
켜지 않음) · 사람 판정을 **한 장도 빠짐없이** 갖고 있다(42/42, `label.has_person` +
`plate_meta.depicts_person`).

### 7.2 각 기준의 §3 선언 실패 경로 × 모집단 판정

| 기준 | §3이 적은 실패 경로 | 모집단 대조 | 판정 |
|---|---|---|---|
| **C1′** | "수요 키 하나의 3장이 전부 D1에 걸리면 MISS" | D1에 걸리는 플레이트는 **전 코퍼스에 1장**(`entrance-checkpoint/b`)이고 그 키는 **수요 밖**이다. 어떤 키도 3장 중 2장 이상을 잃을 수 없다 → **0 키가 MISS 가능**. 부수 경로 `no_metadata`도 불가(사람 판정 42/42 보유) | **VACUOUS** |
| **C2′** | "`server-room`에 cast 샷이 키잉되면 `server-room/a` 한 장에 걸린다" | `standing_room is False`는 2장뿐이고 **둘 다 `server-room`**, 그 키는 이 런의 수요 밖이다. 게다가 `standing_room` 필터는 **어포던스 노브 뒤**에 있고 노브는 OFF이므로 **런타임 배정을 바꿀 수 없다** — 이 기준이 MISS로 뒤집혀도 어떤 샷의 플레이트도 달라지지 않는다(재생기의 `cast-bearing hits whose plate lacks standing_room=True: 0`이 같은 사실이다) | **VACUOUS** (이중으로) |
| **C3′** | §3이 이미 *"축 ②에서 실패할 수 없다"*를 **측정 전에** 공시 | C1′가 MISS 불가이고 servable 샷에서 발화 가능한 남은 reason이 없으므로(`no_metadata` 불가, `plate_shows_person` 불가, `no_standing_room`은 노브 OFF) 24/24가 **대수적으로 강제**된다 | **VACUOUS** (사전 공시대로) |
| **C4′** | 기준이 아니라 **공개 의무**(임계값 없음). 실패 모드는 "숫자가 리포트에 없는 것" | 실제로 **발화한다**: 7/24(고 4·저 3, cast 5샷·카드 6장). 목록이 `replay_coverage.py`와 `report.md` 양쪽에 있다 | **NOT VACUOUS** — 축 교체의 유일한 정보성 산출 |
| **B1**(§2, 2-경로) | 42행 중 3행 이상 불일치면 FAIL | `label.matches_location == false`가 1/42라 실측은 1행이지만 **3행 이상은 구조적으로 가능**했다(모집단에 상한이 없다) → 발화 가능한 기준 | **NOT VACUOUS** (단 §0의 비맹검 한계는 그대로 적용) |

### 7.3 이 판정이 무엇을 뜻하는가 — 그리고 무엇을 **하지 않는가**

- **VACUOUS로 표기된 기준을 근거로 어떤 결정도 세우지 않는다.** 특히
  `stock_plate_substitution_enabled`의 코드 기본값은 **`False`로 유지**된다. 해제 조건
  (a)∧(b) 중 (a)는 문자 그대로는 충족됐으나 **그 충족이 반증 불가한 세 기준 위에 서 있고**,
  (b)(Jay 시청 판정)는 없다. §5가 이미 *"C1′~C3′ 전부 충족돼도 (b) 없이는 켜지 않는다"*고
  적었고, 그것이 정본이다.
- **기준을 낮추지도, 새 임계값으로 갈아치우지도 않는다.** servable 분모 **24**와
  `C3_MIN_SHARE = 0.90`은 여전히 한 글자도 안 바뀌었다. 공허성 표기는 기준을 **약화**하는 것이
  아니라 그 기준이 실어 나를 수 있는 **증거의 무게를 0으로 적는** 것이다.
- **공허하지 않은 축은 그대로 남는다**: C4′(7/24, 임계값 없음, Jay 판정 대상)와 B1(1/42 PASS).
- 이 절은 **새 기준을 만들지 않는다.** 발화 가능한 C1″를 지금 설계하면 그것이야말로 결과를 본
  뒤의 기준 신설이다. 발화 가능한 커버리지 기준이 필요하다면 그것은 **다른 코퍼스**(수요 키가
  더 넓거나 D1 배제가 실제로 일어나는 런)를 요구하고, 그 판단은 이 스토리 밖이다.

### 7.4 재산출

```
uv run python _bmad-output/implementation-artifacts/14-1-approved-plate-sets/replay_coverage.py 4b35c0ed
uv run python _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/verify_two_paths.py
```

§7.1의 키별 표는 `assets/manifest.json`의 `source.plate_meta` + `source.label`과
`location_plates WHERE status='approved'` 42행을 런타임과 같은 조립
(`has_person = label OR plate_meta`, `location_service.py:105-112`)으로 접은 결과다 —
`replay_coverage.load_plates`가 **같은 조립**을 쓰고, 그 동형성은 이번 재도출에서 고쳐졌다
(이전 판본은 `plate_meta.json` 단독으로 읽어 `entrance-checkpoint/b`를 people-free로 봤다).
