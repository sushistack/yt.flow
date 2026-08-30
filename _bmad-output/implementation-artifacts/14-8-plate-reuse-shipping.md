---
story_key: 14-8-plate-reuse-shipping
story_id: "14.8"
epic: "Epic 14: 시각 자산 층 — 샷마다 생성하는 대신 승인된 세트에서 고른다 (배경·D급·오브젝트)"
created: 2026-08-30
rewritten: 2026-08-30
source_status_before: ready-for-dev
baseline_commit: dcf65b8
---

# Story 14.8: 배경 플레이트 재활용을 출하한다 — 단, 판정 가능한 매칭 축 위에서

Status: ready-for-dev

> **⚠️ 이 문서는 2026-08-30에 재작성됐다.** 초판은 `camera_angle → viewpoint` 정합 맵 위에
> C1/C2/C3를 재판정하는 스토리였다. 그 축이 **실측으로 은퇴했다**(§Context B). 초판의 T1~T3는
> 이미 실행됐고 결과가 `206c505`에 있다 — 그대로 두면 아는 답을 다시 발견한다.
> 목표("재활용을 실제로 출하한다")는 유효하고, 바뀐 것은 **그 앞의 매칭·판정 축**이다.

## Story

As Jay,
I want approved background plates to actually be chosen at render time instead of every shot generating a fresh background,
so that backgrounds stop drifting shot to shot and the per-run GPU spent on backgrounds drops to zero —
**and I want the rule that picks them to be one a second person can reproduce.**

## Context

### A. 에픽의 중심 명제가 아직 한 번도 출하되지 않았다

*"샷마다 배경을 새로 생성하는 대신 사람이 승인한 세트에서 고른다"* 가 에픽 14의 명제인데
`stock_plate_substitution_enabled: bool = False`라서 run `4b35c0ed`은 **43/43 샷이 자유생성**
이었다. 승인 플레이트 42장이 디스크에 있고 선택기도 있는데 런타임이 **한 장도 쓰지 않는다.**
14.1이 배정 규칙을, 14.2가 어포던스 게이트를 닫았고, 남은 것은 켜는 것이다.

### B. ⚠️ 매칭 축이 실측으로 은퇴했다 — 이 재작성의 이유

**세 개의 독립된 측정이 같은 말을 한다: `viewpoint`는 이 정밀도로 판정 가능한 축이 아니다.**

1. **재판독 대조**(`REREAD-2026-08-30.md`) — HIGH 후보 6장을 저장소 문서 비열람 판정자가
   다시 재니 코리도 3장에서 1차와 **0.07~0.13** 어긋났다. 사전등록 marginal 밴드는 **±0.05**다.
2. **판정자 간 대조**(`AUGMENTATION-BATCH-2026-08-30.md` §2) — **같은 이미지 5장**을 독립된 두
   블라인드 판정자가 쟀더니 **범주 뒤집힘 2/5**, |Δy_h| 최대 **0.12** 평균 **0.072**.
3. 범주 폭은 **0.20**(EYE = 0.40~0.60)인데 오차가 ±0.10 수준이다 → **경계 근처 범주 배정은
   동전던지기**이고, C1("이 셀에 측정 viewpoint가 일치하는 승인 플레이트가 ≥1장 있는가")은
   **현재 정밀도로 판정 가능한 기준이 아니다.**

그리고 **텍스트로 시점을 만들 수도 없다**: 변형 `d`(부감)/`e`(앙각)를 신설해 5셀 × 4롤 = 20장을
렌더했더니 목표 범주 도달 **2/20**, 승인 기준까지 통과 **1장**이다. `containment-chamber/e`는
앙각을 지시했는데 **네 롤 전부 부감**으로 나왔다 — 부족이 아니라 반대 방향이다(셀별 4롤의
`y_h` 산포가 0.01~0.03이라 리롤이 분포를 못 흔든다). 14.1이 변형 `b`에서 본 2/14의 재현이다.

**부수 발견**: `medical-bay/b`는 **단일 소실점이 존재하지 않는다** — 추정기가 세 설정에서
발산하고 선쌍이 범주 폭을 넘겨 흩어지며 매트리스 선쌍이 기하학적으로 불가능한 곳에서 만난다.
승인 42장 중 최소 1장이 일관된 3D 공간을 그리지 않는다(시점 라벨과 별개의 품질 결함).

**Jay 결정 (2026-08-30): (B) 매칭 규칙 자체를 교체한다.** (A) HIGH/LOW 셀을 수요에서 빼는 안은
결과를 보고 기준을 낮추는 것이라 기각, (C) 판정자 3인 다수결은 두 번째 문제(2/20)를 못 건드려
기각, (D) 영구 OFF는 이르다고 기각.

### C. 기존 42장의 메타데이터도 단일 판정자 1회 값이다

`plate_meta.viewpoint` 42행은 전부 **한 판정자가 한 번** 읽은 값이다. §B-2가 보여준 오차가
그 42행 전체에 적용된다. **이 스토리는 그 값을 덮어쓰지 않는다** — 두 판정을 병기하고,
새 축이 정해지면 그 축으로 다시 측정한다.

## Acceptance Criteria

**Phase 1 — 리서치 게이트(GPU 0). 이걸 통과하지 못하면 Phase 2는 시작하지 않는다.**

1. **Given** §B의 세 측정, **when** 후보 매칭 축을 열거하면, **then** 각 후보에 대해
   **(a) 무엇을 재는가 (b) 그 측정의 재현 오차 (c) 범주/허용 폭** 이 적히고, **(b) < (c)** 를
   만족하는 후보가 **명시적으로 표시**된다. 만족하는 후보가 없으면 그것이 이 스토리의 결론이다.
2. **Given** 채택 후보, **when** 그 축으로 승인 42장을 측정하면, **then** **독립된 두 판정
   경로**(사람/판정자 둘, 또는 결정론적 추정기 + 판정자 하나)가 **같은 42장**에 대해 산출한
   값의 **불일치율이 사전등록 허용 폭 안**에 든다. 밖이면 그 후보도 기각이고 §AC1로 돌아간다.
3. **Given** 채택 축, **when** 커버리지 기준을 다시 쓰면, **then** C1/C2/C3에 대응하는 새 기준이
   **측정을 보기 전에** 사전등록되고, 옛 기준과의 관계(대체/폐기/유지)가 명시된다.

**Phase 2 — 출하(Phase 1 통과 시에만).**

4. **Given** 새 축의 커버리지 판정, **when** 전부 충족되면, **then** `config.py`의 **코드 기본값**이
   `True`가 되고 날짜 붙은 판정 주석 + `DECISIONS` 행이 붙으며 `.env`/`.env.example` 핀은 **없다**.
5. **Given** 하나라도 미달이면, **when** 스토리가 끝나면, **then** 플래그는 `False`로 남고 미달분이
   열거되며 **기준을 낮추지 않는다**.
6. **Given** 플래그가 켜진 상태, **when** E2E iteration 5를 완주하면, **then** 치환이 실제로 발화한
   샷 수와 폴백 사유별 분포가 기록되고 Jay의 시청 판정을 받을 프레임이 남는다.
7. **Given** 플래그가 `False`인 경로, **when** image_node가 돌면, **then** 선택기·매니페스트 읽기
   콜이 0이고 산출물이 이 스토리 이전과 동일하다(회귀 없음).
8. **Given** `report_decision_drift.py`, **when** 돌리면, **then** exit 0이고
   `stock_plate_substitution_enabled`가 env-sourced나 latent `.env.example` 핀으로 뜨지 않는다.

## Tasks / Subtasks

- [ ] **T1 — 후보 축 열거와 판정 가능성 심사** (AC: 1) · GPU 0
  - 각 후보를 (a)측정 대상 / (b)재현 오차 / (c)허용 폭 셋으로 적는다. **(b) < (c)가 유일한 통과 조건.**
  - 최소한 아래 넷은 다뤄라(채택하라는 뜻이 아니다):
    - **결정론적 기하 추정기** — 사람·VLM을 빼고 커밋된 알고리즘이 `viewpoint`를 정의한다.
      재현 오차가 **구조적으로 0**이 되는 대신, 그 값이 사람 지각과 맞는지는 별도 검증이다
      (`AUGMENTATION-BATCH`의 판정자가 임시로 만든 그래디언트 방향 투표 추정기가 출발점).
    - **시점을 안 쓰는 축** — `location_key` + `depicts_person` + 어포던스만으로 고르고
      시점 불일치를 **수용**한다. 그러면 무엇이 깨지는지 실측으로 보여라(옛 C3 분모 24샷에 대해).
    - **프레이밍 대신 내용 정합** — 8.17이 버린 `image_prompt` 정합을 다른 형태로 되살린다.
      ⚠️ 8.19가 임베딩 검색을 명시 기각했고 그 층은 **존재한 적이 없다**.
    - **연속값 거리 + 폴백** — 범주 경계를 없애고 거리 순 랭킹으로 바꾼다. 경계 근처
      동전던지기가 사라지는 대신 임계값이 새로 생긴다.
  - **Block If**: (b) < (c)를 만족하는 후보가 없으면 **HALT** 하고 그것을 결론으로 적어라.
    없는 축을 발명하지 마라.
- [ ] **T2 — 채택 축의 2-경로 검증** (AC: 2) · GPU 0
  - 승인 42장을 **두 독립 경로**로 측정하고 불일치율을 낸다. 밴드는 **측정 전에** 고정한다.
  - 판정자를 쓰면 저장소 문서·프롬프트·`VARIANT_CAMERAS` **비열람**이어야 한다
    (`gotcha_a-prompt-derived-question-is-a-leading-question`).
- [ ] **T3 — 새 커버리지 기준 사전등록** (AC: 3)
  - 옛 C1/C2/C3 각각에 대해 **대체/폐기/유지**를 적고, 새 기준을 측정 **전에** 커밋한다.
- [ ] **T4 — 선택기 교체** (AC: 4, 7)
  - `image.py:_select_plate`의 필터 사슬에서 시점 단계를 새 축으로 교체. 순수 함수 유지
    (`replay_coverage.py`가 오프라인 재생할 수 있어야 한다). 플래그 OFF 경로는 **바이트 무변**.
- [ ] **T5 — 커버리지 재판정과 플래그 결정** (AC: 4, 5, 8)
- [ ] **T6 — E2E iteration 5** (AC: 6) — 14.9의 recompose 척도 판정도 이 런에 함께 실린다
- [ ] **T7 — 기록** (AC: 전부)

## Dev Notes

### 🚫 하지 말 것 — 반증된 전제를 되살리지 마라

- **릴라이트 결합은 해제 조건이 아니다.** 페어 키가 `precompute_relights` 안에 있고 그 함수는
  `composite_harmonization_tier >= 3`에서만 호출된다. 출하 기본값은 **1**이고 tier 3(IC-Light)은
  10.1b가 시청 판정으로 기각했다. 이 인계는 **두 번** 발화 조건이 틀리게 기록됐다.
  고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`.
- **8.19의 임베딩 검색층은 존재한 적이 없다.** `asset_retrieval_service.py`도 임계값도 점수도 없다.
- **`VARIANT_CAMERAS`의 선언을 실측으로 믿지 마라** — `b`의 선언 LOW는 14장 중 2장, 신설 `d`/`e`는
  20장 중 2장만 지켰다. **증설 배치를 "그 변형을 더 뽑자"로 계획하지 마라.**
- **재사용은 목표이지 회귀가 아니다**(`project_stock-plate-reuse-is-intent`). 부족하면 세트를
  늘려서 해결하고 한 장에서 변형을 파생하지 않는다.

### ⚠️ 측정 함정

- **판정자 간 오차가 밴드보다 크다**(§B). 두 판정을 **병기**하고 덮어쓰지 마라 — 덮어쓰면
  이 불일치가 사라진다.
- **사전등록 밴드는 데이터를 찍을 때도 지켜라** — 14.1이 ±0.05를 ±0.03으로 찍었다가 부족분
  결론이 "5장"에서 "2장"으로 바뀐 전례(`gotcha_a-preregistered-band-must-be-honored-when-stamping-data`).
- **기준을 결과에 맞춰 다시 쓰지 마라**(`gotcha_a-screening-gate-can-fail-on-its-own-threshold`).
  새 기준은 **측정 전에** 고정한다(T3).
- **모집단 전수 대조**로 부류를 닫아라, 사례 열거가 아니라(`gotcha_closing-a-class-needs-a-population-sweep`).

### 켜면 같이 바뀌는 것 — 다른 스토리에 인계할 전제

- **14.5 인계**: 치환이 켜지면 `location_key` 보유 **31/43** 샷이 `image_prompt`를 생성에 쓰지
  않는다. 프롬프트 층 개입의 도달 범위가 **43/43 → 12/43**으로 준다. 이후 프롬프트 측정은
  **그 분모를 명시**해야 한다.
- **설계상 영구 폴백**: `close-up` 6샷 + `POV` 1샷은 방 플레이트가 서빙할 수 없다. **결함이 아니다.**
- **14.2 게이트**: 치환이 켜지면 어포던스가 런타임 VLM이 아니라 자산 메타데이터로 판정돼
  런당 VLM 콜이 **31콜 줄어든다** — 14.1이 설계한 이득이다.
- **플레이트 경로에 런타임 사람 가드가 없다** — 10.2/14.4는 생성 경로 전용이고 플레이트 분기는
  `continue`로 건너뛴다. Jay가 2026-08-30 판정에서 `S00201`(액자 속 인물)을 지목했고, 그것이
  14.4(b)가 "감수 리스크"로 기록한 갭의 실현이다. 치환을 켜는 것이 그 갭을 **줄이는** 방향이다.

### 소스 트리 — 손댈 것과 읽기 전용

| 경로 | 역할 |
|---|---|
| `src/yt_flow/config.py:304-358` | **수정 지점.** 플래그 + 조건 주석. 이 주석이 정본이고 `DECISIONS` 행은 색인일 뿐 |
| `src/yt_flow/pipeline/nodes/image.py:574` `_select_plate` | **T4의 수정 지점.** 순수 함수 유지 |
| `scripts/label_location_plates.py` | 실행만. `REQUIRED_BOOLS`, `temperature: 0` 핀 |
| `.../14-1-approved-plate-sets/measure_plates.py` · `replay_coverage.py` | 실행만. C 규칙이 선택기와 같아야 한다 |
| `.../14-1-approved-plate-sets/PREREGISTRATION.md` | **읽기 전용.** 옛 C1/C2/C3의 정본 |
| `src/yt_flow/services/location_service.py:70` | 읽기 전용. `has_person`은 `label`과 `plate_meta`의 OR |

### 테스트

- `tests/pipeline/nodes/test_image.py` — 플래그를 켜도 **OFF 경로 테스트가 통과해야 한다**(AC7)
- `tests/test_report_decision_drift.py` — `DECISIONS` 행을 추가하면 `.env.example` 전수 스윕이 본다
- **핀 금지**: 결정값이 기본값과 같은지 단언하는 테스트를 만들지 마라 — 리포트를 게이트로 만드는 우회다
- 상수(`VARIANTS` 등)의 **크기·멤버십**을 바꾸면 커밋 전 **전체 스위트**를 돌려라 —
  길이를 하드코딩한 다른 파일 테스트 4건이 이 이유로 깨진 전례가 오늘 있다

### References

- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/AUGMENTATION-BATCH-2026-08-30.md] — **20렌더 2/20, 판정자 간 뒤집힘 2/5, 선택지 (A)~(D)**
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/REREAD-2026-08-30.md] — HIGH 재판독, 1·2차 0.07~0.13 불일치
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/report.md] — 42장 측정표, 부족 셀, 8.19 전제 반증
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/PREREGISTRATION.md#5] — 옛 C1/C2/C3
- [Source: src/yt_flow/config.py#L304-L358] — 해제 조건의 정본, (c) 철회 근거
- [Source: _bmad-output/implementation-artifacts/14-3-art-style-contract/VERDICT.md] — Jay 17/43 판정, 다섯 부류
- [Source: _bmad-output/implementation-artifacts/GPU-PREMISE-CORRECTION-2026-08-30.md] — 이 박스는 AMD다. `nvidia-smi`를 진단에 쓰지 마라
- [Source: _bmad-output/implementation-artifacts/epic-14-context.md] — 에픽 제약
- [Source: CLAUDE.md#Decision-bearing settings] — 코드 기본값 + 날짜 판정 주석, `.env` 미핀

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
