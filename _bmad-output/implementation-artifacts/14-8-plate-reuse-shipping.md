---
story_key: 14-8-plate-reuse-shipping
story_id: "14.8"
epic: "Epic 14: 시각 자산 층 — 샷마다 생성하는 대신 승인된 세트에서 고른다 (배경·D급·오브젝트)"
created: 2026-08-30
source_status_before: backlog
baseline_commit: e70748263fbe25994bb3f5d94dcb1bbb14aeb06d
---

# Story 14.8: 배경 플레이트 재활용을 실제로 출하한다

Status: ready-for-dev

## Story

As Jay,
I want the approved background plates to actually be chosen at render time instead of every shot generating a fresh background,
so that backgrounds stop drifting shot to shot and the per-run GPU spent on backgrounds drops to zero.

## Context

**에픽 14의 중심 명제가 아직 한 번도 출하되지 않았다.** 명제는 *"샷마다 배경을 새로 생성하는 대신 사람이 승인한 세트에서 고른다"* 인데, `stock_plate_substitution_enabled: bool = False`(`config.py:358`)라서 run `4b35c0ed`은 **43/43 샷이 자유생성**이었다. 승인된 플레이트 42장은 디스크에 있고 선택기도 있는데 런타임이 한 장도 쓰지 않는다.

14.1이 절반을 닫았다 — `_select_plate`가 샷의 `camera_angle`을 각 플레이트의 **실측** viewpoint와 대조해 샷 단위로 고르고, 맞는 후보가 없으면 `stock_plate_unfit`을 남기고 생성으로 폴백한다. 8.17의 씬 키잉 붕괴(155개 배경 → 41개)는 이것으로 은퇴했다. 남은 것은 **켜는 것**이고, `config.py:326-334`가 조건 둘을 **AND**로 못박아 뒀다:

- **(a)** 측정된 커버리지가 사전등록 기준(C1/C2/C3)을 통과한다 — 2026-08-25 측정에서는 **미달**이었다
- **(b)** 치환을 켠 E2E 런에 대한 Jay의 시청 판정 — 선례가 만장일치다(10.1c, 10.5, 10.1e, 14.2: 시각 기본값은 사람이 프레임을 보기 전에 뒤집지 않는다)

**(a)의 부족분은 이미 렌더됐다.** `e707482`이 HIGH 3셀을 블라인드 재판독해 42장 중 HIGH가 **0장**임을 확정했고, 증설 명세를 **5장(LOW 2 + HIGH 3)**으로 확정했다. 그 5장이 지금 `assets/locations/`에 **draft**로 있다:

| 파일 | **의도한** 셀 |
|---|---|
| `observation-room/d`, `observation-room/e` | HIGH 1 + LOW 1 |
| `containment-chamber/e` | LOW |
| `medical-bay/d`, `corridor/d` | HIGH |

⚠️ **이 표는 렌더 명세이지 측정 결과가 아니다.** 어떤 장이 어느 셀을 채우는지는 T2의 **블라인드 판독**이 정한다 — 의도한 셀을 판독자에게 주면 그것이 곧 앵커다. 14.0 §4-4가 **같은 프롬프트·다른 시드로 시점이 5쌍 중 2쌍 뒤집히는 것**을 실측했고, 42장 중 HIGH 0장이 나온 것도 `VARIANT_CAMERAS`가 `b=low angle`을 *요청*했는데 픽셀이 따르지 않았기 때문이다. **요청은 보장이 아니다.** 의도한 셀이 안 채워졌으면 그것은 미달이고, 라벨을 의도에 맞추는 것이 아니다.

이 스토리는 그 5장을 라벨·측정·승인시켜 (a)를 판정하고, 통과하면 플래그를 코드 기본값으로 올린 뒤 (b)를 위한 E2E를 만든다.

## Acceptance Criteria

1. **Given** `assets/locations/`의 draft 플레이트 5장, **when** `scripts/label_location_plates.py`를 돌리면, **then** 각 장이 `REQUIRED_BOOLS` 전부와 quality·confidence를 통과해 `approved`가 되거나 사유와 함께 draft로 남고, 판정이 매니페스트 `source.label`에 기록된다.
2. **Given** 승인된 신규 플레이트, **when** `measure_plates.py --sheets` → 블라인드 시점 판독 → `--commit`을 돌리면, **then** `viewpoint_verdicts.csv`와 `plate_meta.json`이 사전등록 **±0.05** marginal 밴드로 찍히고, 판독자는 프롬프트·`VARIANT_CAMERAS`·저장소 문서를 **열람하지 않은** 상태로 판정한다.
3. **Given** 갱신된 `plate_meta`, **when** `replay_coverage.py`를 run `4b35c0ed`에 대해 재생하면, **then** C1(10셀 커버리지) · C2(cast 보유 9셀 어포던스) · C3(servable 24샷 중 ≥22 정합 히트) 각각의 충족 여부가 **셀 단위로** 출력된다.
4. **Given** C1·C2·C3가 **전부** 충족될 때, **when** 플래그를 승격하면, **then** `config.py`의 **코드 기본값**이 `True`가 되고 그 위에 **날짜 붙은 판정 주석**이 달리며 `DECISIONS`에 행이 추가되고, `.env`/`.env.example`에는 핀이 **없다**.
5. **Given** C1·C2·C3 중 하나라도 미달일 때, **when** 스토리가 끝나면, **then** 플래그는 `False`로 남고 미달분이 **(location_key, viewpoint, 필요 장수)**로 열거되며, **기준을 낮추지 않는다**.
6. **Given** 플래그가 켜진 상태, **when** E2E iteration 5를 완주하면, **then** 치환이 실제로 발화한 샷 수와 폴백 사유별 분포가 기록되고 Jay의 시청 판정을 받을 프레임이 남는다.
7. **Given** 플래그가 `False`인 경로, **when** image_node가 돌면, **then** 선택기·매니페스트 읽기 콜이 0이고 산출물이 이 스토리 이전과 동일하다(회귀 없음).
8. **Given** `report_decision_drift.py`, **when** 돌리면, **then** exit 0이고 `stock_plate_substitution_enabled`가 env-sourced나 latent `.env.example` 핀으로 뜨지 않는다.

## Tasks / Subtasks

- [ ] **T1 — 신규 5장 라벨·승인** (AC: 1)
  - [ ] `uv run python scripts/label_location_plates.py` (VLM 콜 5회, GPU 0). 자동 승인은 `REQUIRED_BOOLS` 5개 + quality `good` + confidence ≥ 0.8 전부 통과할 때만
  - [ ] 통과 못 한 장은 **draft로 남긴다** — 기준을 완화하지 않는다. 그 장이 채우려던 셀은 미달로 계상
- [ ] **T2 — 시점·어포던스 측정** (AC: 2)
  - [ ] `measure_plates.py --sheets`로 `y_h` 보조선 콘택트 시트만 굽는다 (VLM 콜 0)
  - [ ] **블라인드 판정**: 판정자는 `LOCATION_PROMPTS`/`VARIANT_CAMERAS`/`PREREGISTRATION` 이외 저장소 문서를 열람하지 않는다. `e707482`이 앵커링 회피를 위해 쓴 방식을 그대로 재사용
  - [ ] `viewpoint_verdicts.csv`에 `y_h`·`verdict`·`marginal`·`rule` 기록. **marginal 밴드는 ±0.05** — 14.1 리뷰가 CSV를 ±0.03으로 찍은 것을 잡았다
  - [ ] `--commit`으로 `plate_meta.json` + `AssetService.record_source`
- [ ] **T3 — 커버리지 재판정** (AC: 3, 5)
  - [ ] `replay_coverage.py`를 전체 `thread_id`로 재생(접두사 금지 — 14.1 리뷰 지적)
  - [ ] C1/C2/C3를 셀 단위로 출력. 미달이면 (location_key, viewpoint, 필요 장수)로 열거
- [ ] **T4 — 14.2 어포던스 게이트와의 상호작용 결정** (AC: 4, 6)
  - [ ] `plate_affordance_gate_enabled`도 현재 `False`다. `_select_plate`의 `standing_room` 필터가 그 노브 뒤에 있다(14.1 D2)
  - [ ] 치환을 켤 때 이 노브를 **함께 켜는지 여부를 명시적으로 결정**하고 근거를 리포트에 남긴다. C2가 존재하는 이유가 정확히 "세트가 켜기를 지탱하는가"다
- [ ] **T5 — 플래그 승격 또는 미달 보고** (AC: 4, 5, 8)
  - [ ] 통과 시: `config.py`의 기본값 `True` + 날짜 판정 주석 + `DECISIONS` 행. `.env`/`.env.example` 핀 금지
  - [ ] 미달 시: `False` 유지 + 부족분 열거. 이것도 **정상 종료**다
  - [ ] `report_decision_drift.py` exit 0 확인
- [ ] **T6 — E2E iteration 5** (AC: 6)
  - [ ] 치환 ON으로 완주. 치환 발화 샷 수 / `stock_plate_unfit` 사유별 분포 / `close-up`·`POV` 영구 폴백 수를 기록
  - [ ] Jay 시청 판정용 프레임 확보. **이 스토리는 판정하지 않는다**
- [ ] **T7 — 기록** (AC: 전부)
  - [ ] `_bmad-output/implementation-artifacts/14-8-plate-reuse-shipping/report.md` 신규
  - [ ] `epics.md` Story 14.8 항목 + `sprint-status.yaml` 갱신. **닫힌 것과 열린 것을 분리**해 적는다

## Dev Notes

### 🚫 하지 말 것 — 반증된 전제를 되살리지 마라

- **릴라이트 결합을 블로커로 다시 넣지 마라.** 14.1의 report·`epics.md`·`deferred-work.md`·`epic-14-context.md` 넷이 *"(c) 릴라이트 결합 수정"*을 해제 조건으로 실었고, **14.3이 반증해 철회했다**(`c75b123`). 근거 한 줄: 페어 키를 만드는 `precompute_relights`는 `composite_harmonization_tier >= 3`에서만 도달 가능한데 출하 tier는 **1**이고 tier 3은 10.1b 시청에서 기각됐다. `test_precompute_relights_is_unreachable_at_the_shipped_tier`가 고정한다. 결함 자체는 실재하나 **이 플래그와의 연결이 철회된 것**이다. (`gotcha_recorded-root-cause-can-be-inverted` — 이 프로젝트에서 세 번째 역전이다.)
- **`image_prompt` 의미 정합을 이 스토리에서 풀지 마라.** 선택기는 `camera_angle`·`cast`·`location_key`만 읽고 `image_prompt`를 통째로 버린다. `location_key`는 **방이지 씬이 아니라서** 한 방 안에서 서로 다른 것을 요구하는 두 샷이 선택기에게 구분되지 않는다. 이것은 **선언된 감수 리스크이지 게이트 조건이 아니다** — `config.py:326-334`가 조건을 (a)(b) 둘로 명시했고 (b)가 이것을 판정한다. 리포트에 리스크로 적고 넘어간다.
- **기준을 결과에 맞춰 고치지 마라.** `PREREGISTRATION.md §5`가 미리 적어뒀다 — *"HIGH가 0장이면 그것은 기준이 도달 불가한 게 아니라 세트 부족이며, 기준을 낮추지 않고 부족분으로 보고한다."*
- **배경 다양성 감소를 "회귀"로 고치지 마라.** 소스 재사용은 의도다(`project_stock-plate-reuse-is-intent`). 후보가 모자라면 **세트를 늘린다** — 한 플레이트에서 변형을 파생시키지 않는다.

### ⚠️ 측정 함정 — 이 스토리가 밟기 쉬운 것

- **재현 오차가 사전등록 밴드보다 크다.** `e707482`이 corridor 3장에서 1차·2차 판독이 **0.07~0.13** 어긋나는 것을 발견했다. marginal 밴드는 ±0.05다. **두 판정을 병기하고 덮어쓰지 마라.** 신규 5장도 같은 위험을 갖는다.
- **`medical-bay/b`는 단일 소실점이 존재하지 않는다**(추정기 발산). 시점 라벨과 **별개의 플레이트 품질 결함**이므로 섞지 마라. 신규 `medical-bay/d`도 같은 방이다.
- **앵커링 회피**: 주 에이전트가 1차 값을 본 뒤 재판독하면 판정이 오염된다. `e707482`은 저장소 문서를 읽지 않는 별도 판정자에게 사전등록 규칙과 이미지만 줬다. 그 형태를 유지하라.
- **`replay_coverage.py`에 접두사가 아니라 전체 `thread_id`를 넘겨라** — 14.1 리뷰가 잡았다. 집계는 맞고 **샷별 플레이트 배정이 재현되지 않는다**.
- **`marginal` 행은 미달 판정을 뒤집을 수 있다.** 14.1 리뷰에서 ±0.05로 다시 찍자 marginal이 11행 → 20행이 되고 부족 5셀 중 3셀이 측정 노이즈 안에 들어갔다. 민감도 절을 반드시 다시 쓴다.

### 켜면 같이 바뀌는 것 — 다른 스토리에 인계할 전제

- **14.5 인계**: 치환이 켜지면 `location_key` 보유 **31/43** 샷이 `image_prompt`를 생성에 쓰지 않는다. 즉 프롬프트 층 개입의 도달 범위가 **43/43 → 12/43**으로 준다. 이 플래그 이후의 프롬프트 측정은 **그 분모를 명시**해야 한다.
- **설계상 영구 폴백**: `close-up` 6샷 + `POV` 1샷(run `4b35c0ed` 기준 7/31)은 방 플레이트가 서빙할 수 없다. C3의 분모 24샷이 그것을 뺀 수다. 이 7샷이 폴백인 것은 **결함이 아니다**.
- **14.2 게이트의 inert 구간**: 어포던스 게이트는 플레이트 복사 샷에 대해 자산 메타데이터로 판정하고, 자유생성 샷에 대해서만 런타임 VLM을 쓴다. 치환이 켜지면 런당 VLM 콜이 **31콜 줄어든다** — 그게 14.1이 설계한 이득이다.

### 소스 트리 — 손댈 것과 읽기 전용

| 경로 | 역할 |
|---|---|
| `src/yt_flow/config.py:304-358` | **수정 지점.** 플래그 + 두 조건 주석. 이 주석이 정본이고 `DECISIONS` 행은 색인일 뿐 |
| `scripts/label_location_plates.py` | **실행만.** `REQUIRED_BOOLS`(`:40-55`), `temperature: 0` 핀 |
| `_bmad-output/.../14-1-approved-plate-sets/measure_plates.py` | **실행만.** `--dry-run`/`--sheets`/`--commit` 3단 |
| `_bmad-output/.../14-1-approved-plate-sets/replay_coverage.py` | **실행만.** C1/C2 규칙이 선택기와 동일해야 한다 |
| `_bmad-output/.../14-1-approved-plate-sets/PREREGISTRATION.md` | **읽기 전용 정본.** §5가 C1/C2/C3 |
| `src/yt_flow/pipeline/nodes/image.py:574` `_select_plate` | 읽기 전용. 필터 우선순위: framing → `no_metadata` → viewpoint → `plate_shows_person` → `no_standing_room`(노브 뒤) |
| `src/yt_flow/services/location_service.py:70` `resolve_stock_plates` | 읽기 전용. `has_person`은 `label`과 `plate_meta`의 **OR** |

### 테스트

- `tests/pipeline/nodes/test_image.py` — 스톡 경로 기존 계약. 플래그를 켜면 **OFF 경로 테스트가 여전히 통과해야 한다**(AC7)
- `tests/test_report_decision_drift.py` — `DECISIONS` 행을 추가하면 `.env.example` 전수 스윕이 그것을 본다
- **핀 금지**: 결정값이 기본값과 같은지 단언하는 테스트를 만들지 마라 — 리포트를 게이트로 만드는 우회다(CLAUDE.md)

### References

- [Source: src/yt_flow/config.py#L304-L358] — 두 해제 조건의 정본, 그리고 (c) 철회 근거
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/PREREGISTRATION.md#5] — C1/C2/C3
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/report.md] — 42장 측정표, 부족 셀, 8.19 임베딩 전제 반증
- [Source: _bmad-output/implementation-artifacts/14-1-approved-plate-sets/REREAD-2026-08-30.md] — HIGH 3셀 블라인드 재판독, 증설 5장 확정
- [Source: _bmad-output/implementation-artifacts/14-3-art-style-contract/report.md#6] — 릴라이트 결합 반증
- [Source: _bmad-output/implementation-artifacts/epic-14-context.md] — 에픽 제약(재사용은 목표이지 회귀가 아니다 / 시점은 프롬프트의 함수가 아니다)
- [Source: CLAUDE.md#Decision-bearing settings] — 코드 기본값 + 날짜 판정 주석, `.env` 미핀

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
