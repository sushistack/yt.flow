---
title: 'Story 14.8: 배경 플레이트 재활용을 출하한다 — 판정 가능한 매칭 축 위에서'
type: 'feature'
created: '2026-08-30'
baseline_revision: '3218ab2'
final_revision: 'a7912ae'
status: 'blocked' # draft | ready-for-dev | in-progress | in-review | done | blocked
review_loop_iteration: 1
followup_review_recommended: true
context: ['{project-root}/CLAUDE.md']
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** 에픽 14의 중심 명제(*샷마다 생성하는 대신 승인된 세트에서 고른다*)가 한 번도 출하되지 않았다 — `stock_plate_substitution_enabled=False`라 run `4b35c0ed`은 43/43 자유생성이었고 승인 플레이트 42장을 런타임이 한 장도 쓰지 않는다. 켜지 못한 이유는 세트 부족이 아니라 **매칭 축**이다: 14.1이 쓴 `camera_angle → plate.viewpoint` 정합은 `y_h`라는 지각 측정 위에 서 있는데, 그 측정의 재현 오차가 자기 밴드보다 크다(판정자 간 |Δy_h| 평균 0.072·최대 0.12, 범주 뒤집힘 2/5; 1·2차 재판독 0.07~0.13; 사전등록 밴드 ±0.05; EYE 범주 폭 0.20). 그래서 사전등록 C1은 **현재 정밀도로 판정 가능한 기준이 아니고**, 텍스트로 시점을 만들려는 시도도 20렌더 중 목표 범주 2장으로 실패했다.

**Approach:** Jay의 2026-08-30 결정 (B)에 따라 **매칭 규칙 자체를 교체한다.** Phase 1(GPU 0)은 후보 축들을 `(a) 무엇을 재는가 / (b) 재현 오차 / (c) 허용 폭`으로 적고 **(b) < (c)** 하나만으로 심사하는 리서치 게이트다 — 통과 후보가 없으면 그것이 결론이고 HALT한다. 통과 축은 승인 42장에 대해 **두 독립 경로**로 재현성을 검증하고, 새 커버리지 기준을 **측정 전에** 사전등록한 뒤, `_select_plate`의 시점 단계를 교체하고 커버리지가 충족될 때만 코드 기본값을 켠다.

## Boundaries & Constraints

**Always:**
- **(b) < (c)가 후보의 유일한 통과 조건이다.** 축의 우아함·구현 난이도·기대 성능은 심사 기준이 아니다. (b)와 (c)는 각각 **재산출 가능한 출처**(커밋된 CSV/매니페스트 행, 또는 두 번 돌려 동일함을 보인 명령)를 달고 적힌다.
- **새 기준은 측정 전에 커밋한다**(T3 → T5 순서). 결과를 보고 기준을 고치지 않는다.
- **옛 판정을 덮어쓰지 않는다.** `plate_meta.viewpoint`·`y_h` 42행은 단일 판정자 1회 값이고 그 오차가 §Intent의 근거다. 새 값은 **병기**한다.
- 플래그 OFF 경로는 **바이트 무변**: 선택기·매니페스트·자산 읽기 콜 0, 경고 0, 산출물 동일(`image.py:996`·`:1081`의 두 분기가 유일한 진입점).
- `_select_plate`는 **순수 함수로 유지**한다 — `replay_coverage.py:129-130`이 이것을 그대로 import해 오프라인 재생하므로 I/O·전역·시계가 들어가면 재생이 끊긴다.
- **선택기와 C-규칙은 같은 술어를 봐야 한다.** `replay_coverage.py:97-103`(`_people_free`)·`:164-172`(C1/C2)·`:146-149`(C3)는 선택기와 별도로 재표현된 사본이고 **그 이중화가 이 스토리의 동기화 위험**이다. 축을 바꾸면 양쪽을 같은 커밋에서 움직인다.
- 결정 필드 규약(CLAUDE.md): 판정은 **`config.py` 코드 기본값 + 날짜 붙은 판정 주석**에 도달해야 출하다. `DECISIONS` 행은 색인일 뿐이고 주석이 정본. `.env`/`.env.example` 핀 금지.
- 상수(`_ANGLE_VIEWPOINT`·`_UNSERVABLE_ANGLES`·reason 어휘)의 멤버십을 바꾸기 전에 **독자 전수조사**를 하고, 바꾼 뒤 **전체 스위트**를 돌린다.
- reason 어휘는 네 곳이 함께 움직인다: `image.py`의 반환값, `domain/state.py:588-618`의 문서, `replay_coverage.py`의 히스토그램, `tests/pipeline/test_gates.py:258`의 등록.

**Block If:**
- **(b) < (c)를 만족하는 후보가 하나도 없다** → HALT `blocked`, 조건 `no admissible matching axis`. 없는 축을 발명하지 않는다.
- 채택 축의 **2-경로 불일치율이 사전등록 밴드 밖**이다 → 그 후보를 기각하고 T1으로 1회 복귀; 남은 후보도 전부 소진되면 HALT.
- **커버리지 기준 미달인데 플래그를 켜라는 압력이 생긴다** → 켜지 않는다(AC5). 기준을 다시 쓰지 않는다.
- **E2E iteration 5 시점에 GPU가 남의 워크플로에 점유돼 있다**(`/queue`의 `class_type` 확인, HTTP 200은 여유가 아니다) 또는 14.9의 3-arm 검증이 같은 런을 선점하고 있다 → 런을 시작하지 않고 T6를 미완으로 기록한다. 절반 런으로 AC6을 주장하지 않는다.
- **승인 42장의 픽셀·라벨·`style_epoch`을 바꿔야 결론이 선다** → 그것은 자산 승격이고 이 스토리 밖이다. HALT.

**Never:**
- **반증된 전제 되살리기**: 릴라이트 결합은 해제 조건이 아니다(`precompute_relights`는 `composite_harmonization_tier>=3`에서만 도달, 출하 tier 1, tier 3은 10.1b가 시청 판정으로 기각; `test_precompute_relights_is_unreachable_at_the_shipped_tier`가 고정). 8.19의 임베딩 검색층은 **존재한 적이 없다**.
- `VARIANT_CAMERAS`의 **선언**을 실측으로 취급하기(`b` 선언 LOW는 14장 중 2장, 신설 `d`/`e`는 20장 중 2장). 증설을 "그 변형을 더 뽑자"로 계획하지 않는다.
- 부족을 **한 장에서 변형을 파생**해 메우기. 재사용은 목표이지 다양성 회귀가 아니다.
- **결정값이 기본값과 같은지 단언하는 테스트**를 만들기 — 드리프트 리포트를 게이트로 만드는 우회다. 리포트는 CI 게이트가 아니고 성공 시 항상 exit 0이다.
- 프롬프트 편집으로 시점을 만들려는 재시도(2/20으로 반증됨), 부정 프롬프트 증설(두 번 렌더를 망침).
- draft 상태인 증설 5장(`containment-chamber/e`·`corridor/d`·`medical-bay/d`·`observation-room/{d,e}`)을 이 스토리에서 승인하기 — 새 축이 그것들을 요구하지 않으면 승인은 별개 판정이다.
- `assets/manifest.json`·`yt_flow.db`의 기존 `plate_meta`·`label` 값 덮어쓰기.

## I/O & Edge-Case Matrix

`_select_plate(shot, plates, run_id, scene_num, *, affordance_gate) -> (plate|None, reason)` — 새 축 적용 후.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 정합 히트 | 채택 축의 매칭 조건을 만족하는 people-free 플레이트가 풀에 ≥1 | `(plate, "match")`, 변형 선택은 `sha256(run_id:scene_num:…)` 기반으로 **프로세스 간 결정론적** | 에러 없음 |
| 서빙 불가 프레이밍 | `camera_angle ∈ {close-up, POV}` | `(None, "unservable_framing")` — 설계상 영구 폴백, 결함 아님 | 에러 없음 |
| 프레이밍 미상 | `camera_angle`이 `None`이거나 7-값 어휘 밖 | `(None, "unknown_framing")` — 추측하지 않고 생성으로 폴백 | 에러 없음 |
| 메타데이터 부재 | 그 키의 승인 플레이트에 채택 축의 필드가 한 장도 없음 | `(None, "no_metadata")` — fail open, 생성 | 에러 없음 |
| 부분 측정 | 일부만 측정됨, 그 중 매칭 0 | `(None, "partial_metadata")` — `no_*_match`와 구별 유지 | 에러 없음 |
| D1 사람 배제 | 후보 전부 `has_person` 또는 `depicts_person` 참 | `(None, "plate_shows_person")` — 노브와 무관하게 항상 발화 | 에러 없음 |
| D2 어포던스 | `shot.cast` 비어있지 않고 `plate_affordance_gate_enabled=True`인데 `standing_room is True`가 0장 | `(None, "no_standing_room")` — `standing_room` 키 부재는 **판정불가이지 충족 아님** | 에러 없음 |
| 플래그 OFF | `stock_plate_substitution_enabled=False` | 선택기·리졸버·매니페스트 **콜 0**, 경고 0, `image_prompt`로 생성 | 에러 없음(경고 부재는 의도) |
| 리졸버 미주입 | 플래그 ON, `_location_service is None` | `stock_plate_resolver_unavailable` 경고 후 생성 | 스테이지를 죽이지 않음 |
| 리졸버 예외 | 플래그 ON, 매니페스트 손상 등 | `stock_plate_resolution_failed` 경고 후 생성 | best-effort, 삼키되 경고 |

</intent-contract>

## Code Map

- `src/yt_flow/config.py:358` — `stock_plate_substitution_enabled: bool = False`. **T5 수정 지점.**
- `src/yt_flow/config.py:304-357` — 해제 조건 주석의 **정본**. `:326-335`가 (a)커버리지 ∧ (b)Jay 시청 판정, `:336-350`이 철회된 (c)릴라이트, `:355-357`이 "no `.env` pin, and NO `DECISIONS` row". 축을 바꾸면 이 산문이 **함께** 갱신돼야 자기모순이 없다.
- `src/yt_flow/config.py:707` `class Decision(NamedTuple)` / `:741` `DECISIONS` / `:729-732` "NO DATE, so no row" 목록 — 행을 추가하면 `:729-732`에서 이 필드를 빼야 한다.
- `src/yt_flow/config.py:448` `plate_affordance_gate_enabled: bool = False` — **이 스토리에서 켜지 않는다.** 치환 뒤에 있는 노브라 동반 여부는 명시 결정이고, 14.2가 남긴 33-pair 판정이 선행이다.
- `src/yt_flow/config.py:412` `background_person_guard_attempts` — 플레이트 경로는 이 가드를 `continue`로 건너뛴다(`image.py:1043`). 켜면 그 갭이 실현 범위를 바꾼다.
- `src/yt_flow/pipeline/nodes/image.py:573-656` `_select_plate` — **T4의 유일한 수정 지점.** 필터 사슬 6단(`:630` 프레이밍 → `:638` 메타데이터 → `:641` 시점 → `:644` D1 사람 → `:647` D2 어포던스 → `:654` sha256 타이브레이크). 순수 함수.
- `src/yt_flow/pipeline/nodes/image.py:549-559` `_ANGLE_VIEWPOINT` / `_UNSERVABLE_ANGLES` — 멤버십 변경 전 독자 전수조사(`replay_coverage.py:40`, `test_image.py:1074`가 읽는다).
- `src/yt_flow/pipeline/nodes/image.py:996`·`:1081` — 플래그 두 진입점. `:1082-1085`가 OFF에서 경고를 **안 내는 것이 의도**임을 적어둔 자리.
- `src/yt_flow/pipeline/nodes/image.py:1006-1043` — 히트 경로(파일 복사 + `stock_plate` 사이드카 + `continue`). `:1054-1080` 폴백 3종 경고.
- `src/yt_flow/domain/state.py:588-618` — `stock_plate_unfit`의 reason 어휘 문서(선택기 순서대로). `:302-332` `ShotData`, `:247-263` `LocationKey`(14값), `:308-320` `camera_angle`.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:97` `_CAMERA_ANGLES`(7값 폐쇄 어휘) — 읽기 전용.
- `src/yt_flow/services/location_service.py:70-115` `resolve_stock_plates` — `plate_meta` + `label` 병합. `:105-112`가 `has_person`을 **두 큐레이터의 OR**로 계산(어느 쪽이든 참이면 참). `:113-114`가 `variant`/`path`를 마지막에 써서 메타데이터가 못 가리게 한다.
- `assets/manifest.json` — `"<location_key>/<variant>"` 키. `source.plate_meta`(14.1 측정)와 `source.label`(8.17 자동 라벨러: `matches_location`·`has_person`·`depicts_person`·`has_legible_text`·`confidence`)이 **서로 다른 두 판정 경로**로 이미 기록돼 있다. **T2의 2-경로 입력.**
- `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/PREREGISTRATION.md:95-131` — 옛 C1/C2/C3와 매칭 맵의 정본. **읽기 전용.**
- `.../14-1-approved-plate-sets/report.md:227-244` — 측정된 verdict(C1 FAIL 5/10셀, C2 PASS, C3 FAIL 17/24=70.8%)와 셀별 표. `:308-311` 선언 대 실측 변형표.
- `.../14-1-approved-plate-sets/viewpoint_verdicts.csv` — 42행 `plate,y_h,ceiling_visible,floor_share,verdict,marginal,rule`. **T1 후보 4(연속값 거리) 심사의 재산출 입력.**
- `.../14-1-approved-plate-sets/replay_coverage.py:46,97-103,145-149,154-172` — `C3_MIN_SHARE`, `_people_free`, servable 필터, C1/C2 판정. **T4와 같은 커밋에서 움직일 사본.**
- `.../14-1-approved-plate-sets/measure_plates.py:52-61,124-145` — `META_PATH`, `BOUNDARIES`, `MARGINAL_BAND=0.05`, CSV의 `marginal` 열이 사전등록 밴드와 모순되면 **거부**하는 검사.
- `.../14-1-approved-plate-sets/AUGMENTATION-BATCH-2026-08-30.md:14-46,80-84` — 20렌더 2/20, 판정자 간 뒤집힘 2/5·|Δ| 0.12/0.072, 선택지 (A)~(D).
- `.../14-1-approved-plate-sets/REREAD-2026-08-30.md:20-50` — 6장 재판독 0.07~0.13 불일치, `medical-bay/b` 소실점 부재, "두 판정 병기" 지시.
- `_bmad-output/implementation-artifacts/GPU-PREMISE-CORRECTION-2026-08-30.md` — 이 박스는 AMD ROCm이다. `nvidia-smi`를 GPU 진단에 쓰지 않는다.
- `tests/pipeline/nodes/test_image.py:43` `FakeSettings`(`stock_plate_substitution=False`, 주석이 "mirrors the real Settings default") / `:886` 플래그 게이팅 / `:1056-1260` `_select_plate` 순수 함수 블록 15건 / `:1648` 가드 미발화 / `:2791-2888` D4 resume·판정 계수.
- `tests/services/test_location_service.py:139-216` — 병합·부재키·shadow 금지·OR·fail-open.
- `tests/test_report_decision_drift.py:203` `.env.example` 전수 스윕 / `:228` citation 존재 검사.
- `tests/pipeline/test_gates.py:258` — 경고 코드 등록.

## Tasks & Acceptance

**Execution:**

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/measure_axis_spread.py` -- 신규, GPU 0. `viewpoint_verdicts.csv` 42행을 읽어 **`location_key` 안에서의 `y_h` 산포**(키별 max−min, 전체 분포)와 셀 경계까지의 거리를 낸다. 후보 ④의 (c)는 "같은 키 안 후보들 사이의 간격"이므로 이 수치가 그 후보의 판정을 직접 결정한다(간격 < 판정자 간 오차 0.072면 랭킹이 노이즈다). 두 번 돌려 동일 출력임을 확인한다. -- 후보 ④를 인상이 아니라 실측으로 심사하기 위한 최소 도구이고, 같은 스크립트가 ①의 (c)에도 쓰인다. (AC: 1)

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/AXIS-CANDIDATES.md` -- 신규. 후보 매칭 축을 `(a) 무엇을 재는가 / (b) 재현 오차 + 그 출처 / (c) 허용 폭 + 그 근거 / (b)<(c) 판정`의 4열 표로 적는다. **아래 넷은 반드시 다룬다**(채택하라는 뜻이 아니다): ① 결정론적 기하 추정기(재현 오차는 구조적으로 0이나 커밋된 코드가 **없고**, ad-hoc 판본은 `medical-bay/b`에서 세 설정에 0.93/0.97/0.41로 발산했다 — 사람 지각과의 일치는 별도 검증), ② 시점을 안 쓰는 축(`location_key` + people-free + 어포던스만), ③ 프레이밍 대신 내용 정합(8.17이 버린 `image_prompt` 정합의 다른 형태 — 8.19 임베딩층은 부재), ④ 연속값 거리 + 폴백. 각 행의 (b)와 (c)는 **재산출 명령이나 커밋된 파일 행**을 인용해야 하고, 인용 없는 수치는 그 행을 실격시킨다. 통과 후보가 0이면 그것을 결론으로 적고 **HALT**. -- 이 표가 이 스토리의 산출물 중 유일하게 되돌릴 수 없는 것이다: 축을 잘못 고르면 Phase 2 전체가 다시 은퇴한다. (AC: 1)

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/verify_two_paths.py` -- 신규, GPU 0. 채택 축의 값을 승인 42장에 대해 **두 독립 경로**로 산출하고 불일치율과 불일치 행 전체를 출력한다. 판정자를 새로 부르기 전에 **매니페스트에 이미 있는 두 경로를 먼저 쓴다**: `source.label`(8.17 자동 라벨러)과 `source.plate_meta`(14.1 측정)는 서로 다른 호출·다른 프롬프트로 기록된 별개 판정이다(`location_service.py:105-112`이 `has_person`을 OR로 접는 것이 바로 두 경로가 갈린다는 증거다). 밴드는 **스크립트 실행 전에** T3 문서에 고정한다. 새 판정자가 필요하면 저장소 문서·프롬프트·`VARIANT_CAMERAS` **비열람**이어야 한다. -- 재현성 검증을 새 측정으로 시작하면 이 스토리가 진단한 바로 그 오차를 다시 도입한다. 이미 있는 두 판정의 불일치가 답이면 GPU도 콜도 0이다. (AC: 2)

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/PREREGISTRATION.md` -- 신규. 옛 C1·C2·C3 **각각에 대해 대체/폐기/유지**를 명시하고 새 기준을 적는다. servable 분모(close-up 6 + POV 1 제외 → 24샷)와 `C3_MIN_SHARE=0.90`은 **낮추지 않는다** — 기준 완화 여부를 판별하는 유일한 고정점이다. 새 기준이 현재 데이터에서 **실패할 수 있는 경로**를 각각 한 줄로 적는다(실패할 수 없는 기준은 기준이 아니다). T2의 불일치 밴드도 여기에 **측정 전에** 박는다. 커밋 해시를 남겨 T5의 측정이 이 파일보다 뒤임을 증명한다. -- `gotcha_a-screening-gate-can-fail-on-its-own-threshold`와 14.1의 ±0.05→±0.03 전례가 같은 실패다: 기준은 데이터를 보기 전에 고정돼야 하고, 데이터를 찍을 때도 지켜져야 한다. (AC: 3)

- [x] `src/yt_flow/pipeline/nodes/image.py` -- `_select_plate`의 시점 단계(`:641-643`)를 채택 축으로 교체. 순수 함수·sha256 타이브레이크·D1(사람)·D2(어포던스 노브)·`_UNSERVABLE_ANGLES`는 **유지**. 상수를 지우기 전에 독자 전수조사(`replay_coverage.py:40`, `test_image.py:1074`). reason 어휘가 바뀌면 `domain/state.py:588-618`·`replay_coverage.py`의 히스토그램·`tests/pipeline/test_gates.py:258`을 **같은 커밋에서** 맞춘다. 플래그 OFF 경로는 손대지 않는다. -- 사슬의 나머지 다섯 단은 이번 은퇴와 무관한 축(프레이밍 어휘·사람 유무·서 있을 자리)이고, 그것들까지 흔들면 무엇이 바뀌어서 결과가 달라졌는지 귀속할 수 없다. (AC: 4, 7)

- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/replay_coverage.py` -- C1/C2 판정(`:164-172`)과 셀 구성(`:154-157`)을 새 기준으로 교체하고, `C3_MIN_SHARE`와 servable 필터는 그대로 둔다. `_select_plate`는 계속 import해 재구현하지 않는다. **플레이트 로더가 런타임의 조립과 같아야 한다** — `LocationService.resolve_stock_plates`는 `has_person`을 `label OR plate_meta`로 접는데(`location_service.py:105-112`) 이 스크립트는 `plate_meta.json`만 읽고 그 파일엔 `has_person`이 **42/42 부재**다. 그래서 `entrance-checkpoint/b`(`label.has_person=true`, `approved`)가 재생기에는 people-free, 런타임에는 사람 보유로 갈린다. 로더가 `source.label`을 병합하지 않는 한 `_people_free`의 독스트링(*선택기와 같은 집합을 배제한다*)과 파일 상단 계약은 거짓이다. 옛 축의 출력을 **대조군으로 함께 출력**하되, 대조군이 14.1이 커밋한 수치(C1 5/10 · C3 17/24)를 **재현하는지 단언**하고 옛 축이 거절한 7샷의 **목록도 찍는다** — 재현 실패를 조용히 넘기면 망가진 대조군이 17→24를 증거로 출력한다. -- 이 파일이 C-규칙의 두 번째 사본이라는 것이 알려진 위험이고, 축을 바꾸면서 여기를 안 고치면 리포트가 조용히 옛 기준으로 판정한다. (AC: 4, 5)

- [x] `tests/pipeline/nodes/test_image.py` -- `_select_plate` 순수 함수 테스트를 새 축으로 갱신하고 **OFF 경로 테스트(`:886` 파라미터화, `:940`, 리졸버 미호출)는 그대로 통과해야 한다**. `FakeSettings:43`의 `stock_plate_substitution=False`와 "mirrors the real Settings default" 주석은 코드 기본값을 켜는 순간 거짓이 되므로 **함께 고친다**(같은 파일 `:44-49`가 `guard_attempts`에서 이 함정을 이미 문서화했다). 새 축이 결정론적임을 고정하는 테스트 1건(같은 입력 두 번 → 같은 출력)을 추가한다. -- `test_image.py`의 페이크가 실제 기본값을 미러링한다고 **주석으로만** 주장하고 있어서, 기본값을 뒤집어도 아무 테스트도 실패하지 않는다. (AC: 4, 7)

- [x] `src/yt_flow/config.py` -- **코드 기본값은 `False`로 남긴다.** 해제 규칙은 `config.py:326-335`가 (a)∧(b)로 못박은 AND이고 (b)(Jay 시청 판정)는 아직 없다. 켜야 E2E를 돌릴 수 있다는 교착은 **존재하지 않는다** — `Settings`가 `env_prefix="YTFLOW_"`(`config.py:29-30`)이므로 `YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true`로 그 한 런만 켜면 되고, 드리프트 리포트의 `env-sourced` 버킷이 정확히 그런 일시 오버라이드를 보이게 하려고 존재한다. 따라서 이 스토리는 **축 교체를 출하하고 플래그는 그대로 둔다**: `:304-357` 주석에 날짜 붙은 기록으로 (i) 매칭 축이 ②로 교체됐다는 것, (ii) (a)가 선 기준 셋이 **전부 반증 불가(`VACUOUS`)여서 아무것도 입증하지 않는다는 것**, (iii) 따라서 **(a)도 (b)도 열려 있고** (a)는 실패할 수 있는 기준이 생겨야 닫히며 E2E는 env 오버라이드로 돌린다는 것을 적는다. **`DECISIONS` 행은 추가하지 않는다** — 날짜 붙은 *승격* 판정이 아직 없으므로 `:729-732`의 "NO DATE, so no row" 목록에 남는 것이 맞다. `.env`/`.env.example` 핀 없음. -- 앞선 반복이 (b) 미충족 상태로 기본값을 뒤집었고 그 정당화(교착)가 리뷰에서 반증됐다. 출하 기본값은 이 저장소에서 여러 번 스테일 값으로 픽셀을 망친 축이다. (AC: 4, 5, 8)

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/PREREGISTRATION.md` -- **추가 절: 반증 가능성의 모집단 대조.** 새 기준 각각에 대해 적은 "실패 경로"를 **승인 42장 전수**에 대해 검사하고, 그 경로가 오늘 데이터에서 실제로 발화 가능한지 판정한다. 실측 기준선: 14개 `location_key` **전부가 승인 3장씩**, `depicts_person=true` **0/42**, `label.has_person=true` **1장**(`entrance-checkpoint/b`), `plate_affordance_gate_enabled=False`. 발화 불가로 판명된 기준은 **PASS가 아니라 `VACUOUS`로 표기**하고, 그 기준을 근거로 어떤 결정도 세우지 않는다. -- 사전등록이 C1′/C2′에 "live failure path"가 있다고 적었는데 모집단 대조로 거짓이었다(C1′는 한 키의 승인 3장이 전부 사람 보유여야 MISS인데 그런 키가 없고, C2′는 어포던스 노브가 OFF라 런타임 배정을 못 바꾼다). 실패할 수 없는 기준은 기준이 아니라는 것은 이 스펙이 이미 요구한 바이고, 모집단 대조 없이는 그 요구가 검사되지 않는다(`gotcha_closing-a-class-needs-a-population-sweep`). (AC: 3, 5)

- [x] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/report.md` -- 신규. 표본 밴드(플레이트 42장·런 `4b35c0ed`·servable 24샷·매니페스트 스냅샷 해시), 후보 심사표, 2-경로 불일치 전체 행, 옛/새 기준 대조와 셀별 판정, 플래그 결정과 그 근거, **반대 결과·판정불가 행을 지우지 않고 보존**. `medical-bay/b` 소실점 부재는 축과 무관한 플레이트 품질 결함으로 별도 기록. -- 측정치는 재산출 명령·표본 밴드와 함께여야 유효하다(`gotcha_a-measurement-without-its-sample-band`). (AC: 1, 2, 3, 5)

- [ ] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/e2e-iteration5-live-validation/` -- E2E iteration 5. **`YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true` env 오버라이드로 그 런만 켠다**(코드 기본값은 건드리지 않는다). ⚠️ E2E는 5개 게이트를 실 API로 승인해야 하고 비대화식 모드가 없다 — 게이트는 Jay의 판정 지점이므로 **대신 승인하지 않는다**. 무인 실행이 불가능하면 그 사실을 미완으로 기록한다. 실행 전 ComfyUI **`/queue`의 `class_type`으로 남의 워크플로 점유를 확인**한다(HTTP 200은 GPU 여유가 아니다). 치환이 실제로 발화한 샷 수와 폴백 사유별 분포를 기록하고, Jay가 볼 프레임을 남긴다. 14.9의 recompose 척도 3-arm 판정도 같은 런에 실린다 — **14.9가 in-review이므로 시작 전에 그쪽 상태를 확인**한다. 산출물은 `*-live-validation/` 규약(판정용 이미지만 커밋, 원본 렌더는 루트 `.gitignore`가 처리). -- 조건 (b)는 사람이 보는 것이고, 이 에픽에서 기계 라벨은 사람 판정에 세 번 졌다. (AC: 6)

- [x] `_bmad-output/planning-artifacts/epics.md` Story 14.8 항목 · `_bmad-output/implementation-artifacts/sprint-status.yaml` 14-8 행 · `deferred-work.md` -- 종결 기록으로 갱신하고, 켜면서 인계되는 전제(프롬프트 층 도달 43/43 → 12/43, 플레이트 경로에 런타임 사람 가드 없음, 14.2 노브 미동반, draft 5장 미승인, `medical-bay/b` 품질 결함)를 등재. **14.3/14.9가 같은 파일의 다른 섹션을 동시 소유하므로 14-8 항목만 국소 편집한다.** -- 이 저장소에서 병렬 세션이 같은 파일을 편집한 전례가 있다. (AC: 전부)

**Acceptance Criteria:**

- Given `AXIS-CANDIDATES.md`, when 읽으면, then 네 후보 각각에 (a)/(b)/(c)가 적혀 있고 (b)와 (c)가 **재산출 가능한 출처를 인용**하며, (b)<(c)를 만족하는 후보가 **명시적으로 표시**돼 있다 — 만족 후보가 0이면 그것이 결론으로 적혀 있고 스토리는 HALT로 끝난다.
- Given `measure_axis_spread.py`, when 두 번 실행하면, then 두 출력이 바이트 동일하고, 키 내부 `y_h` 산포가 후보 ④의 (c)로 인용된 값과 일치한다.
- Given `verify_two_paths.py`, when 실행하면, then 승인 42장 전체에 대한 두 경로 값과 불일치 행이 출력되고, 불일치율이 `PREREGISTRATION.md`에 **미리 박힌** 밴드와 대조돼 통과/기각이 판정된다 — 밴드가 실행보다 앞선 커밋에 있음이 해시로 증명된다.
- Given `PREREGISTRATION.md`, when 읽으면, then 옛 C1·C2·C3 각각에 대체/폐기/유지가 적혀 있고, servable 분모 24와 `C3_MIN_SHARE=0.90`이 유지되며, 새 기준마다 **현재 데이터에서 실패할 수 있는 경로**가 한 줄씩 적혀 있다.
- Given 이 스토리가 끝난 시점, when `config.py`를 보면, then `stock_plate_substitution_enabled`의 코드 기본값은 여전히 `False`이고 `DECISIONS` 행이 **없으며**, `:304-357` 주석이 축 교체·(a)의 충족 범위·반증 불가 기준·남은 (b)를 날짜와 함께 기록한다 — (b)가 없는 상태에서 기본값을 뒤집지 않았다.
- Given 새 기준 각각, when `PREREGISTRATION.md`의 모집단 대조 절을 보면, then 실패 경로가 승인 42장 전수에 대해 검사됐고 발화 불가인 기준은 `VACUOUS`로 표기돼 있으며, 그 기준을 근거로 세워진 결정이 없다.
- Given `replay_coverage.py`, when 플레이트 로더를 보면, then `has_person`이 런타임과 같이 `label OR plate_meta`로 접히고, 대조군이 14.1의 커밋 수치(C1 5/10 · C3 17/24)를 재현하지 못하면 조용히 통과하지 않는다.
- Given 커버리지가 하나라도 미달, when 스토리가 끝나면, then 미달분이 셀·샷 단위로 열거돼 있으며 기준을 낮춘 흔적이 없다(`PREREGISTRATION.md` 커밋 해시가 측정보다 앞선다).
- Given `uv run python scripts/report_decision_drift.py`, when 실행하면, then **exit 0**이고 `stock_plate_substitution_enabled`가 effective-vs-decided 표류·env-sourced·latent `.env.example` 핀 어디에도 뜨지 않는다.
- Given 플래그를 `False`로 되돌린 상태, when `uv run pytest tests/pipeline/nodes/test_image.py -q`를 돌리면, then OFF 경로 테스트가 전부 통과하고 선택기·리졸버 호출이 0이다 — 축 교체가 OFF 경로를 건드리지 않았다.
- Given `uv run pytest -q` 전체, when 실행하면, then 이 스토리 이전과 같은 통과 집합이다(`tests/test_render_pose_guides.py`의 PNG SHA 핀 1건은 14.1/14.5/14.6이 기록한 **기존** 결함이므로 이 스토리의 회귀가 아니다 — stash 후에도 동일 실패임을 확인해 구별한다).
- Given 플래그가 켜진 E2E iteration 5 완주, when 산출물을 보면, then 치환 발화 샷 수와 폴백 사유 분포가 기록돼 있고 Jay가 볼 프레임이 남아 있다 — GPU 점유나 14.9 선점으로 런을 못 돌렸다면 그 사실이 미완으로 기록돼 있고 절반 런으로 AC6이 주장되지 않았다.

## Spec Change Log

### 2026-08-30 — 리뷰 패스 2 (루프백 없음, 문구 정정)

**촉발 발견** — 개정된 `config.py` 태스크가 *"(ii) (a)가 어떤 기준 위에서 **충족됐고**… (iii) 남은 것은 (b) 하나"*라고 지시했는데, 같은 문서의 AC는 *"그 기준을 근거로 세워진 결정이 없다"*를 요구한다. 세 기준이 전부 `VACUOUS`인 이상 (a)를 닫는 것 자체가 그 기준 위의 결정이므로 두 문장은 양립하지 않는다. 구현은 태스크 문구를 따랐고 리뷰가 AC 쪽을 근거로 잡았다.

**개정 내용** — 태스크 문구를 AC에 맞춰 "(a)도 (b)도 열려 있고, (a)는 **실패할 수 있는 기준**이 생겨야 닫힌다"로 교체. AC는 원래 옳았으므로 무변. 코드 되돌림 없이 `config.py` 주석만 정정했다(patch) — 2000줄을 재도출해 주석 세 문장을 고치는 것은 비례하지 않고 KEEP 목록의 정확한 작업을 잃는다.

**KEEP 추가** — 리뷰 패스 2가 만든 것 중 재도출에서 살아남아야 할 것: `_fold_verdict`(두 사람 판정을 같은 규칙으로 접고 판정불가는 키 삭제), `location_key` 동등성이 `_select_plate` **안**에 있다는 것, `_SERVABLE_ANGLES`가 어휘에서 파생된다는 것, 재생기 CONTROL의 3-결과 구분(입력 변경/다른 런/진짜 드리프트), C4′의 불일치·미측정 분리.

### 2026-08-30 — 리뷰 패스 1 (bad_spec 3건)

**촉발 발견**
1. `(b)` 미충족 상태로 출하 기본값이 뒤집혔고, 그 정당화("켜지 않으면 E2E를 못 돌린다")가 거짓이다 — `env_prefix="YTFLOW_"`(`config.py:29-30`)로 그 런만 켤 수 있고, 드리프트 리포트의 `env-sourced` 버킷이 바로 그 용도다. 사전등록 §5가 *"C1′~C3′ 전부 충족돼도 (b) 없이는 켜지 않는다"*고 적어둔 것을 같은 런이 어겼다.
2. 새 기준 셋이 **전부 반증 불가**인데 공허성 공시가 C3′에만 붙었다. 실측: 14개 키 전부 승인 3장씩(42/42), `depicts_person=true` **0/42**, `label.has_person=true` **1장**, 어포던스 노브 OFF → C1′는 MISS 불가, C3′는 그 대수적 귀결, C2′는 런타임 배정을 못 바꾼다. `config.py`·`report.md`가 *"C1′/C2′는 live failure path를 유지한다"*는 거짓을 인쇄했다.
3. 커버리지를 낸 재생기의 people-free 술어가 런타임과 다르다 — 런타임은 `label OR plate_meta`(`location_service.py:105-112`), 재생기는 `plate_meta.json` 단독인데 거기에 `has_person`이 42/42 부재다. `entrance-checkpoint/b`가 두 쪽에서 갈린다. 오늘 수요 키가 아니라 숫자만 우연히 같다.

**개정 내용** — `config.py` 태스크를 "코드 기본값 `False` 유지 + `DECISIONS` 행 미추가 + 날짜 기록만"으로 교체, E2E는 env 오버라이드로 실행, `PREREGISTRATION.md`에 **모집단 대조 절**(실패 경로를 42장 전수로 검사, 발화 불가 기준은 `VACUOUS` 표기) 신설, `replay_coverage.py` 태스크에 로더 동형성과 대조군 재현 단언 추가, AC 4·5 교체 및 신규 AC 2건.

**회피한 known-bad 상태** — (b) 없이 뒤집힌 출하 기본값이 남는 것. 이 저장소는 스테일/조기 기본값으로 픽셀을 망친 전례가 여럿이고(`gotcha_env-file-beats-code-default`, `gotcha_a-decision-that-only-reaches-env-never-ships`), 반증 불가한 게이트를 근거로 세운 결정은 `gotcha_a-screening-gate-can-fail-on-its-own-threshold`의 거울상이다.

**KEEP — 재도출에서 반드시 살아남아야 할 것**
- `_select_plate`의 축 교체 자체: 시점 단계(`:641-643`)만 제거하고 나머지 다섯 단(프레이밍·메타데이터·D1·D2·타이브레이크)은 무변, 순수성 유지, 다이제스트에서도 `viewpoint`를 뺀 판단(선택기가 안 읽는 값으로 샷이 갈리지 않게).
- **reason 어휘의 독자는 넷이 아니라 다섯이다.** 스펙이 지목한 `tests/pipeline/test_gates.py:258`은 reason이 아니라 warning **code** 등록이라 무관했고, 실제 독자는 `image.py` · `domain/state.py:588-618` · `domain/warnings.py:63-66` 산문 · `replay_coverage.py` · **`tests/domain/test_run_warnings.py:250,261-262`**(일곱 reason을 `@parametrize`로 등록)였다. 이 전수조사 결과를 다시 발견하게 하지 마라.
- `_ANGLE_VIEWPOINT`를 **값까지 보존**한 판단과 그 근거(선택기는 멤버십만 쓰지만 C4′ 공시가 값을 쓴다).
- C4′ 실측: 옛 축이 거절한 7샷이 전부 눈높이 플레이트를 받고 그중 **cast 5샷(카드 6장)**, 픽셀 도달 경로는 `character_service.py:1556` → `_select_entity_angles`. 이것이 축 ②의 유일한 공시된 대가다.
- `test_render_pose_guides.py` PNG SHA 핀 실패가 **사전 존재**임을 `git stash`로 증명한 절차.
- Phase 1 산출물 4개와 그 커밋 순서(`d797a8a` → `5746918`)는 **되돌리지 않는다**.

## Review Triage Log

### 2026-08-30 — Review pass 2
- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 2, medium 12, low 1)
- defer: 3: (high 1, medium 2, low 0)
- reject: 4
- addressed_findings:
  - `[high]` `[patch]` `location_service.resolve_stock_plates`가 `label.depicts_person`을 병합하지 않아, 풀 진입 센티널이 사람 판정으로 옮겨간 뒤로 **새로 라벨·승인된 플레이트가 영구 `no_metadata`**가 됐다. `_fold_verdict`로 두 필드를 같은 규칙으로 접고 판정불가는 키 삭제로 남김. 명시적 `null`(M6)과 비-bool(M7)도 같은 함수로 닫힘.
  - `[high]` `[patch]` `config.py`가 해제 조건 **(a) 충족**과 "(b)가 유일한 잔여 조건"을 선언 — 같은 스토리가 `VACUOUS`로 표기한 기준 위에 세운 결정이고, 다음 스토리가 증거 없는 (a)를 인용하게 된다. (a)/(b) 둘 다 열림으로 정정. 같은 주석의 프롬프트 도달 수치 **12/43 → 19/43** 정정(12는 `location_key` **부재** 샷 수였고 `report.md` §9-8은 그것을 정반대로 서술했다).
  - `[medium]` `[patch]` 매칭 축이 순수 함수 밖으로 나가 재생기가 축을 재구현 — `location_key` 동등성을 `_select_plate` 안으로 되돌림.
  - `[medium]` `[patch]` 서빙 가능성이 은퇴한 축의 맵 키에 매여 있었다 → `_SERVABLE_ANGLES = _CAMERA_ANGLES − _UNSERVABLE_ANGLES`.
  - `[medium]` `[patch]` `no_metadata` 정본 산문이 코드와 반대("EITHER" vs 실제 BOTH), `warnings.py` 처방이 "재측정"으로 스테일.
  - `[medium]` `[patch]` 재생기: CONTROL이 모든 run id에 무조건 발화(다른 런은 항상 exit 4), 전제(승인 42·노브 OFF) 미단언, C4′가 미측정을 불일치로 계상, 매니페스트 fail-open 부재, cwd 종속.
  - `[medium]` `[patch]` 사전등록 §7이 `partial_metadata` 은퇴를 말없이 누락, B1의 `NOT VACUOUS`가 C1′과 다른 잣대, `interview-room/b` 비필터 근거 3곳이 §0의 비맹검 한계를 잘라내고 인용, `AXIS-CANDIDATES`가 스크립트가 더는 찍지 않는 출력을 인용.
  - `[medium]` `[patch]` `epic-14-context.md`(다음 에픽-14 세션에 주입되는 파일)가 은퇴한 시점 사슬과 14.8 `ready-for-dev`, 불필요해진 draft 5장 작업을 그대로 문서화.
  - `[low]` `[patch]` 사이드카 `axis` 마커가 발생 불가능한 resume 시나리오를 근거로 삼음(치환이 `True`로 출하된 적이 없어 옛 축 사이드카가 0개) → 전방 provenance로 정직하게 재서술.
  - `[medium]` `[patch]` `_SERVABLE_ANGLES`의 `frozenset[Literal] - frozenset[str]` variance 오탐 → `.difference()`.

### 2026-08-30 — Review pass 1
- intent_gap: 0
- bad_spec: 3: (high 3, medium 0, low 0)
- patch: 13: (high 2, medium 8, low 3)
- defer: 4: (high 1, medium 3, low 0)
- reject: 2
- addressed_findings:
  - `[high]` `[bad_spec]` (b) 미충족인데 출하 기본값이 `True`로 뒤집혔고 정당화한 "교착"이 거짓 — `YTFLOW_` env 오버라이드로 E2E만 켤 수 있다. 스펙의 `config.py` 태스크와 AC 4·5를 "기본값 `False` 유지 + `DECISIONS` 행 미추가 + 날짜 기록만"으로 교체, E2E는 env 오버라이드 경로로 개정.
  - `[high]` `[bad_spec]` 새 기준 C1′/C2′/C3′가 전부 반증 불가인데 공허성 공시가 C3′에만 붙었다(14키 전부 승인 3장, `depicts_person=true` 0/42, 어포던스 노브 OFF). `PREREGISTRATION.md`에 모집단 대조 절을 신설하고 발화 불가 기준은 `VACUOUS` 표기하도록 개정.
  - `[high]` `[bad_spec]` 커버리지 재생기의 people-free 술어가 런타임과 다르다(`plate_meta.json` 단독 vs `label OR plate_meta`; `has_person` 42/42 부재). `replay_coverage.py` 태스크에 로더 동형성과 대조군 재현 단언을 추가.

## Design Notes

**왜 심사 기준이 (b)<(c) 하나인가.** 은퇴한 축이 실패한 방식이 정확히 그것이다 — `y_h`는 EYE 범주 폭 0.20 위에서 재현 오차 0.07~0.13으로 측정됐고, 그래서 경계 근처 배정이 동전던지기였다. 축의 설명력이나 구현 비용은 이 실패를 막지 못했다. 그래서 후보를 고를 때 다른 기준을 섞으면 같은 방식으로 또 진다.

**(b)를 0으로 만드는 두 가지 길은 성질이 다르다.** ①(결정론적 추정기)은 **측정을 고정**해 0을 만들고, ②(시점을 안 쓰는 축)는 **측정을 없애서** 0을 만든다. 후자에는 "그 값이 사람 지각과 맞는가"라는 두 번째 질문 자체가 없다 — `location_key`는 시나리오 LLM이 폐쇄 14값 enum으로 쓴 **데이터 필드**이고 플레이트 쪽은 디렉터리 이름이라, 둘의 비교는 문자열 동등성이다. 대신 시점 불일치를 **수용**하게 되므로, 그 수용이 화면에서 무엇을 깨는지는 옛 servable 24샷 위에서 실측으로 보여야 한다(옛 축에서 `no_viewpoint_match` 7샷 = high-angle 4 + low-angle 3이 그 대상이다).

**2-경로 검증을 새 측정으로 시작하지 않는다.** `assets/manifest.json`에는 이미 두 판정이 있다 — 8.17 자동 라벨러의 `source.label`과 14.1의 `source.plate_meta`. `location_service.py:105-112`이 `has_person`을 두 큐레이터의 **OR**로 접는 것 자체가 이 둘이 갈린다는 인정이다. 갈린 행을 세는 것이 곧 불일치율이고, 그러면 T2가 콜 0·GPU 0으로 끝난다. 새 판정자는 이것으로 부족할 때만 부른다.

**실패할 수 없는 기준을 쓰지 않는다.** 시점 필터를 빼면 C1·C3이 구성상 자동 충족될 수 있다 — 모든 demanded key에 승인 플레이트가 3장씩 있기 때문이다. 그래서 `PREREGISTRATION.md`는 각 새 기준마다 "지금 데이터에서 이것이 실패하는 경로"를 적어야 한다. 실제로 남아 있는 실패 경로는 있다: `server-room/b`·`c`는 `standing_room=false`이고, cast 샷이 그 키를 요구하면 C2가 발화한다. servable 분모 24와 90% 임계를 유지하는 것이 "기준을 낮추지 않았다"의 유일한 증거다.

**플래그를 켜는 것이 사람-인-배경 갭을 줄인다.** `S00201`(액자 속 인물)은 14.4(b)가 "자유생성 샷은 승인 게이트에 도달하지 않으므로 감수한다"고 기록한 리스크의 실현이고, 43/43 자유생성이었기 때문에 화면에 나왔다. 부정 프롬프트는 해법이 아니다 — `BG_NEGATIVE_SUFFIX`에 인물 토큰이 이미 있는데도 그려졌다. 단 플레이트 경로는 10.2/14.4 런타임 가드를 `continue`로 건너뛰므로, 켜는 것은 **승인 게이트로 갈아타는 것**이지 가드를 얻는 것이 아니다.

## Verification

**Commands:**
- `uv run python _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/measure_axis_spread.py` -- 두 번 실행해 출력 바이트 동일, exit 0
- `uv run python _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/verify_two_paths.py` -- 42장 전수 출력 + 불일치율, exit 0
- `uv run python _bmad-output/implementation-artifacts/14-1-approved-plate-sets/replay_coverage.py 4b35c0ed` -- 새 기준 판정 + 옛 축 대조군, exit 0
- `uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_location_service.py tests/test_report_decision_drift.py tests/pipeline/test_gates.py -q` -- 전부 통과
- `uv run pytest -q` -- 상수 멤버십을 바꿨으므로 전체 스위트. 기존 실패 1건(`test_render_pose_guides.py` PNG SHA 핀) 외 신규 실패 0
- `uv run python scripts/report_decision_drift.py` -- exit 0, `stock_plate_substitution_enabled`이 세 버킷 어디에도 없음
- `ruff check` -- clean
- `git diff --stat assets/ prompts/` -- 빈 출력(자산·프롬프트 무접촉)
- `grep -rn 'STOCK_PLATE_SUBSTITUTION' .env .env.example` -- 빈 출력

**Manual checks (if no CLI):**
- `PREREGISTRATION.md`의 커밋이 `report.md`의 측정 커밋보다 **앞선다**(`git log --oneline -- <두 파일>`로 순서 확인)
- `config.py:304-357` 주석과 `DECISIONS` 행이 서로 모순되지 않는다(주석이 정본)
- E2E 프레임이 `14-8-plate-reuse-shipping/*-live-validation/` 규약대로 남아 있고, 판정용 이미지만 커밋됐다


## Auto Run Result

Status: **blocked** — 코드·측정·문서는 완료·리뷰 통과. 남은 것은 **AC6(E2E iteration 5)** 하나이고 그것은 사람 게이트다.

Blocking condition: `E2E iteration 5 requires human gate approvals` — 이 저장소의 E2E는 FastAPI(:8000) + ComfyUI(:8188)로 5개 게이트를 **실 API로 승인**해야 완주하고, 비대화식/자동승인 모드가 **없다**(`grep -riE 'auto_approve|skip_gate|GATE_MODE' src/` → 0건). 게이트는 Jay의 품질 판정 지점이므로 대신 승인하지 않았다. GPU·키·ComfyUI는 준비돼 있다(`/queue` running 0 / pending 0).

### 구현 요약

에픽 14의 중심 명제를 막고 있던 것은 세트 부족이 아니라 **매칭 축**이었다. 14.1의 `camera_angle → plate.viewpoint` 정합은 `y_h`라는 지각 측정 위에 서 있었고, 그 측정의 재현 오차(판정자 간 평균 0.072·최대 0.12, 1·2차 0.07~0.13)가 사전등록 밴드 ±0.05와 범주 폭 0.20을 넘어 경계 배정이 동전던지기였다.

**Phase 1(GPU 0)** — 후보 4축을 `(a) 무엇을 재는가 / (b) 재현 오차 / (c) 허용 폭`으로 심사했다. ①결정론적 기하 추정기: 커밋된 구현이 0건이고 인용 가능한 유일한 수치가 `medical-bay/b`의 세 설정 발산 **0.56** > 0.20 → 기각. ③내용 정합: (c)가 **정의되지 않음**(8.19 임베딩층 부재를 직접 확인) → 이유 있는 기각. ④연속값 거리: 키 내부 최소 인접 간격 **중앙값 0.010**(수요 6키는 0.000~0.020)이 판정자 오차 0.072보다 작아 랭킹이 노이즈 → 기각. **②시점 미사용 축 채택** — `location_key`는 닫힌 14값 enum **데이터 필드**라 (b)가 측정의 고정이 아니라 **측정의 부재**로 0이다. 2-경로 검증 P1 **1/42 = 2.4%** vs 사전등록 밴드 5.0% → PASS.

**Phase 2** — `_select_plate`의 시점 단계만 제거(나머지 다섯 단·순수성 유지, 다이제스트에서도 `viewpoint` 제외), reason 어휘 7→5, 새 커버리지 기준을 측정 **전에** 커밋. 결과: servable **17/24 → 24/24**, 대가는 C4′ **시점 불일치 7/24**(cast 5샷·카드 6장; 픽셀 도달 경로는 `character_service.py:1556` → `_select_entity_angles`).

**플래그는 켜지 않았다.** 첫 반복은 켰고 리뷰가 그 정당화("켜야 E2E를 돌린다")를 반증했다 — `env_prefix="YTFLOW_"`로 그 런만 켤 수 있다. 더 결정적으로 **새 기준 셋이 전부 반증 불가(`VACUOUS`)**다: 14개 키 전부 승인 3장씩, `depicts_person=true` 0/42, 어포던스 노브 OFF → C1′는 MISS 불가, C3′는 그 대수적 귀결, C2′는 런타임 배정을 못 바꾼다. 그래서 해제 조건 **(a)도 (b)도 열려 있다**. 기준을 낮추지 않았고(servable 24·`C3_MIN_SHARE=0.90` 바이트 무변), 결과를 본 뒤 새 기준을 만들지도 않았다.

### 파일

- `src/yt_flow/pipeline/nodes/image.py` — `_select_plate` 축 교체, `_SERVABLE_ANGLES`를 어휘에서 파생, 사람 판정 센티널 + D1을 D2와 같은 `is False` 규약으로, 사이드카 `axis` 마커
- `src/yt_flow/services/location_service.py` — `_fold_verdict`로 두 사람 판정을 같은 규칙으로 접음(판정불가는 키 삭제), `location_key` 동봉
- `src/yt_flow/config.py` — 기본값 `False` 유지·`DECISIONS` 행 없음, 날짜 붙은 기록만(축 교체 / 기준 셋의 공허성 / (a)·(b) 둘 다 열림 / E2E는 env 오버라이드)
- `src/yt_flow/domain/{state.py,warnings.py}`, `src/yt_flow/pipeline/nodes/scenario_chain.py` — reason 어휘 5곳 동시 정정 + 은퇴 축을 서술하던 산문 정정
- `.../14-8-plate-reuse-shipping/{AXIS-CANDIDATES.md,PREREGISTRATION.md,measure_axis_spread.py,verify_two_paths.py,report.md}` — 심사표·사전등록(+§7 모집단 대조)·산포 측정·2-경로 검증·리포트
- `.../14-1-approved-plate-sets/replay_coverage.py` — 새 C-규칙, 런타임과 동형인 플레이트 로더, CONTROL 3-결과 구분, C4′ 불일치/미측정 분리, cwd 독립
- `tests/{pipeline/nodes/test_image.py,services/test_location_service.py,domain/test_run_warnings.py}` — 축·센티널·규약·어휘 고정
- `epic-14-context.md`, `epics.md`, `sprint-status.yaml`, `deferred-work.md`

### 리뷰 결과

2패스. **패스 1: bad_spec 3(high 3)** → 코드 되돌림(`c19d64c`) 후 스펙 개정·재도출. (b) 미충족 상태의 기본값 뒤집기 / 반증 불가한 기준 위의 결정 / 런타임과 다른 재생기 술어. **패스 2: bad_spec 0, patch 15(high 2), defer 3, reject 4** — high 둘은 `label.depicts_person` 미병합으로 새 승인 플레이트가 영구 배정 불가가 되는 실제 결함, 그리고 `config.py`가 (a)를 닫아버린 문구(+ 프롬프트 도달 12/43 → 19/43 오류).

### 검증

- `replay_coverage.py 4b35c0ed` exit 0 — C1′ 6/6·C2′·C3′ 24/24 전부 `[VACUOUS]` 표기, C4′ 7 불일치 + 0 미측정, CONTROL이 14.1 커밋값(5/10 · 17/24) 재현 후 VALID
- `verify_two_paths.py` P1 1/42 PASS · P2/P3 `UNDEFINED(0 comparable rows)` · P4 1/42 — 두 번 실행 바이트 동일
- `uv run pytest -q` → **1 failed, 3470 passed** — 유일 실패 `test_render_pose_guides.py` PNG SHA 핀은 14.1/14.5/14.6이 기록한 **기존** 결함(stash로 증명)
- `report_decision_drift.py` exit 0, 세 버킷 전부 비었음 · `ruff check` 만진 파일 0건 · `git diff assets/ prompts/` 빈 출력 · `.env`/`.env.example` 핀 없음

### 잔여 리스크

1. **AC6 미완** — 치환이 실제로 발화한 런이 아직 없다. C4′ 7샷이 화면에서 어떻게 보이는지는 미판정이다.
2. **새 축의 (b)는 한쪽 피연산자만 쟀다** — `shot.location_key`를 시나리오 LLM이 **잘못** 방출할 오차는 미측정이고, 같은 재생기가 12/43 무키 중 **7샷이 `image_prompt`에 방 이름을 쓰고도 필드를 비웠다**고 찍는다. 잘못된 키는 "시점이 어긋난 방"이 아니라 **다른 방**을 준다. deferred 등재.
3. **기준 셋이 공허하다** — (a)를 닫으려면 실패할 수 있는 기준이 필요하고, 그것은 지금 코퍼스로는 만들 수 없다.
4. `matches_location=False`인 `interview-room/b`가 필터 없이 배정 가능(그 행이 곧 밴드가 받아들인 1/42이라 사후 승격을 거부했다). 밴드 자체가 비맹검(사전등록 §0)이라 재현성의 **상한**이다.
5. 플레이트 경로는 10.2/14.4 런타임 사람 가드를 건너뛴다 — 켜는 것은 가드를 얻는 게 아니라 **승인 게이트로 갈아타는 것**이다.
6. 켜면 프롬프트 층 도달이 43/43 → **19/43**로 준다. 이후 프롬프트 측정은 그 분모를 명시해야 한다.

### 다음 행동 (Jay)

```
YTFLOW_STOCK_PLATE_SUBSTITUTION_ENABLED=true  # 그 런만 켠다. 코드 기본값은 건드리지 않는다
```
로 E2E iteration 5를 돌리고 5게이트를 승인한 뒤, C4′ 7샷(`S00402 S00404 S00604 S00702 S00803 S00902 S00904`)을 포함한 프레임을 판정한다. 14.9의 recompose 판정도 같은 런에 실린다(단 `48634dd`에서 14.9는 VETO 판정이 났으므로 상태 재확인 필요). 그 판정이 조건 (b)이고, 통과하면 코드 기본값 뒤집기는 한 줄이다.
