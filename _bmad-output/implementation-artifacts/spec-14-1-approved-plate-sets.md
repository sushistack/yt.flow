---
title: 'Story 14.1: 승인된 배경 플레이트 세트 — 샷 단위·프레이밍 정합 재사용'
type: 'feature'
created: '2026-08-25'
status: 'done' # draft | ready-for-dev | in-progress | in-review | done | blocked
baseline_revision: '80ee501c5284deb3f411f71a5310d63c84d3a446'
final_revision: 'e8b8d2f031d3e2e705ec59fb04b1ae9188d66dd6'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-14-context.md'
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** `stock_plate_substitution_enabled` 가 8.17 이후 꺼져 있는 이유는 **재사용이 아니라 배정 규칙**이다. `_plate_variant_index(run_id, scene_num, location_key, count)` 는 **씬**을 키로 삼아 한 씬의 같은-로케이션 샷 전부에 같은 플레이트를 주고, 샷의 `image_prompt` 와 `camera_angle` 을 통째로 버린다(`config.py:304-311` 이 이 스토리를 이름으로 지목한다). 그래서 "기구 트레이 클로즈업"이 wide 방 플레이트를 받는다. 그리고 승인 플레이트 42장에는 **정합에 쓸 메타데이터가 하나도 없다** — `LocationPlate` 는 key/variant/path/status 뿐이고 `resolve_stock_plates` 는 `{variant, path}` 만 낸다.

**Approach:** 42장을 **측정해서** 자산 메타데이터를 붙이고(시점 = 14.0 사전등록 `y_h` 투영기하 규칙 / 설 자리 = 14.2 `plate_has_standing_room` / 그림 속 인물 = 14.4 인계), `resolve_stock_plates` 가 그 메타데이터를 함께 내보내며, `image_node` 가 **샷마다** `camera_angle` 과 cast 유무에 정합하는 플레이트만 고르고 **정합 후보가 없으면 생성으로 폴백**한다. 기본값은 계속 `False`; 이 스토리는 켤 **조건**을 실측으로 정의한다.

## Boundaries & Constraints

**Always:**
- **재사용은 목표다**(`project_stock-plate-reuse-is-intent`). 다양성 수치를 목표로 삼지 말고 한 장에서 변형을 파생하지 마라. 부족은 **세트 증설**로 해결하며, 이 스토리는 *무엇이 얼마나 부족한지*를 실측으로 남기는 데까지 간다.
- 플레이트 측 판정은 **픽셀 측정**이다. 선언된 `VARIANT_CAMERAS` 문구(a=wide/eye, b=corner/low, c=close-detail)는 **사전확률일 뿐 게이트 입력이 아니다** — 14.0 §4-4 가 "시점은 프롬프트 텍스트의 함수가 아니다"를 리시드 대조군 2/5 로 실측했다.
- 판정 스키마·요청 봉투를 새로 만들지 마라. 어포던스는 `vision_check.STANDING_ROOM_PROMPT` + `image_first=True` + `temperature=0` 을 그대로 쓴다(14.2 실측: 봉투가 갈리면 재현이 3/7↔5/7 로 갈린다).
- 메타데이터는 `AssetService.add_asset` **재호출이 아니라** `label_location_plates._record_verdict` 의 load/mutate/save 패턴으로 붙인다 — 재호출은 `status` 를 draft 로 리셋하고 `approved_at` 을 지운다.
- 모든 실측치는 **재산출 스크립트 + 표본 밴드**와 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).
- 새 경고 코드는 3곳 등록이 강제된다: `state.py` `RunWarningCode` 리터럴 / `warnings.py` 카탈로그 행(불일치 시 import raise) / `(code, reason)` 캡.

**Block If:**
- 측정 결과 **이미 승인된 플레이트의 승인을 철회**해야 한다는 판단이 나올 때(예: `depicts_person=true`). 기록·경고·리포트까지만 하고 승인 상태는 건드리지 마라 — 승인 철회는 사람 판단이다.
- `stock_plate_substitution_enabled` 를 `True` 로 올려야 한다는 판단이 나올 때. 플래그 승격은 Jay 의 시청 판정 뒤다(10.1c·10.5·10.1e·14.2 전례).

**Never:**
- **신규 플레이트 렌더 / ComfyUI 기동 금지.** 세트 증설은 GPU 배치 + 사람 승인 게이트이고 후속 몫이다. 이 스토리는 부족분을 (key, viewpoint) 셀 단위로 규정하는 데서 멈춘다.
- `stock_plate_substitution_enabled` 코드 기본값 변경 금지.
- **임베딩·검색 스택 도입 금지.** epics 의 *"8.19의 임베딩 검색층이 후보 랭킹의 기반"* 은 **거짓 전제다** — 8.19 는 Stage 2 를 명시적으로 기각했고 `asset_retrieval_service.py` 도, 매처도, 임계값도, 점수도 존재하지 않는다(8.19 Completion Notes). 후보 랭킹의 기반은 임베딩이 아니라 **측정된 플레이트 메타데이터**다. 이 거짓 전제를 epics 에서 정정한다.
- `_suppress_cast_on_no_figure_framing` 의 마커 어휘 확장 금지(14.2 §3 이 실측으로 금지 — `high-angle` 을 넣으면 정상 5건을 지운다).
- 부정 프롬프트 추가 금지(`gotcha_negative-prompt-overstuffing`, 두 번 물린 축).
- 프롬프트 파일(`prompts/`) 변경 금지 — 이 스토리는 런타임 프롬프트를 건드리지 않는다.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 정합 히트 | 치환 ON, `camera_angle="medium"`, cast 없음, 해당 키에 `viewpoint=EYE` 플레이트 존재 | 그 플레이트를 복사, `provenance.stock_plate` 에 variant + 선택 근거 기록 | 없음 |
| cast 보유 + 설 자리 있음 | 치환 ON, `camera_angle="wide"`, cast 2, EYE 이면서 `standing_room=true` 인 플레이트 존재 | 그 플레이트 복사, 어포던스는 **판정됨**으로 계상(`unjudged` 증가 없음) | 없음 |
| cast 보유 + 설 자리 없음 | 위와 같으나 후보 전부 `standing_room=false` | 후보 0 → **생성 폴백**, `stock_plate_unfit` (`reason=no_standing_room`) | 폴백은 정상 경로 |
| 서비스 불가 프레이밍 | `camera_angle` ∈ {`close-up`, `POV`} | 플레이트를 절대 배정하지 않고 생성 폴백, `stock_plate_unfit` (`reason=unservable_framing`) | 폴백은 정상 경로 |
| 시점 미보유 | `camera_angle="high-angle"`, 해당 키에 `viewpoint=HIGH` 플레이트 없음 | 생성 폴백, `stock_plate_unfit` (`reason=no_viewpoint_match`) | 폴백은 정상 경로 |
| 프레이밍 불명 | `camera_angle` 이 `None` | 생성 폴백, `stock_plate_unfit` (`reason=unknown_framing`) — 추측하지 않는다 | 폴백은 정상 경로 |
| 메타데이터 부재 | 승인 플레이트는 있으나 매니페스트에 `plate_meta` 없음 | 생성 폴백, `stock_plate_unfit` (`reason=no_metadata`). **fail-open** | 매니페스트 읽기 실패도 동일 처리, 스테이지 실패 금지 |
| 승인 플레이트 0 | 키에 승인 플레이트 없음 | 기존 `stock_plate_missing` 그대로(회귀 없음) | 기존 동작 유지 |
| 치환 OFF (출하 기본) | `stock_plate_substitution_enabled=False` | 선택기·매니페스트 읽기 **콜 0**, 경고 0, 오늘과 바이트 동일 | 없음 |
| 사전-14.1 런 resume | 이미 복사된 샷의 사이드카 존재 | 캐시 히트로 **옛 variant 유지**(`provenance` 는 비교 대상 아님), 재복사·재판정 없음 | 규칙 혼재는 리포트에 명시 |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/image.py:514-525` -- `_plate_variant_index`. **교체 지점.** docstring 이 씬 키잉을 "spatial continuity" 로 의도라고 적고 있으니 그 근거도 함께 갱신한다.
- `src/yt_flow/pipeline/nodes/image.py:855-917` -- 스톡 플레이트 분기. 선택기 호출·경고·`provenance.stock_plate` 기록 지점. `:865-878` 의 `affordance_undecidable=True` / `unjudged` 가 *"a copied plate is 14.1's job to pre-judge"* 라고 적힌 훅이다.
- `src/yt_flow/pipeline/nodes/image.py:370-408` -- `_existing_complete_shot`(비교 키 `image_prompt`/`negative_prompt`/`seed` **셋뿐**, `provenance` 제외) + `_sidecar_guard_flag`. 비교 키를 늘리면 기존 캐시 전량 무효 — **늘리지 마라**.
- `src/yt_flow/pipeline/nodes/image.py:308-352` -- `_write_sidecar`. `stock_plate` provenance 확장 지점.
- `src/yt_flow/services/location_service.py:46-51` -- `resolve_stock_plates`. 매니페스트 메타데이터를 합쳐 내보낼 지점. 소비자는 `api/main.py:51` 과 `image.py:856` 둘뿐이고 프론트엔드 소비자는 없다 — **가산 키는 안전**.
- `src/yt_flow/services/asset_service.py:55-85` -- `add_asset`. **재호출 금지 근거**(`status` 리셋 + `approved_at` 삭제). 신규 in-place 갱신 메서드를 여기 둔다.
- `scripts/label_location_plates.py:40-47,52-66,125-140,184` -- `REQUIRED_BOOLS` / `LABEL_PROMPT` / `_record_verdict`(load/mutate/save 선례) / 자동 승인 호출. 14.4 인계 축(`depicts_person`)을 넣을 곳. ⚠️ 이 스크립트는 `[text, image]` + temperature 미지정으로 보낸다.
- `src/yt_flow/services/vision_check.py:80-135` -- `STANDING_ROOM_PROMPT`(5필드: `standing_room`/`floor_fraction`/`camera_distance`/`best_spot`/`reason`) + `plate_has_standing_room(image_bytes, settings) -> bool | None`, `image_first` 키워드 필수. **`background_has_person` 의 `image_first=False` 는 건드리지 마라**(14.2 가 미측정으로 남긴 것).
- `src/yt_flow/domain/state.py:303-325` -- `ShotData`. `camera_angle` 은 image_node 시점에 **존재하고 정규화돼 있다**(14.0 `_resolve_camera_angle`, 43/43 발화).
- `src/yt_flow/domain/state.py:308-315` 와 `src/yt_flow/pipeline/nodes/scenario_chain.py:520-523` -- *"필드는 배경 렌더러에 도달하지 않는다"* 주석. **이 스토리가 세 번째 소비자를 만들어 그 서술을 낡게 만든다** — 정정 지점(`gotcha_camera-angle-reaches-pixels-by-a-second-path`).
- `src/yt_flow/domain/warnings.py:29-92,101,146-187` -- 카탈로그 + import-time 정합 raise + `(code, reason)` 캡. `src/yt_flow/domain/state.py:561-593` 리터럴 동기화.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py:205,220,613` -- 릴라이트 캐시가 `(card_variant, location_key)` 로 페어를 잡고 **첫 샷의 배경**을 쓴다. 샷 단위 선택은 이 결합을 **씬 내부로도** 끌어들인다 — 이 스토리는 고치지 않고 `deferred-work.md` 로 넘긴다(14.3 층).
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/PREREGISTRATION-4-4-hypotheses.md` + `build_viewpoint_sheets.py` + `viewpoint_verdicts.csv` -- 시점 판정 규칙(`y_h` 0.40/0.60 밴드)과 시트 빌더·CSV 스키마의 **재사용 원본**.
- `scripts/seed_location_plates.py:56,133,151,243,690` -- `VARIANTS=("a","b","c")` 와 그 사방의 가정(`assert`, `VARIANTS.index`, CLI `choices`). 증설 시 손대야 할 곳의 목록 — **이 스토리는 읽기 전용 참조**.
- `tests/pipeline/nodes/test_image.py:846-1058,1362,1613-1640` -- 스톡 경로 기존 계약. `:956-971` 이 현 해시 계약을 고정하므로 교체 대상.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/PREREGISTRATION.md` -- 신규. **플레이트를 보기 전에** 작성하고 이후 수정 금지: 시점 판정 규칙(14.0 §4-4 `y_h` 밴드 인용), 정합 맵(아래 Design Notes), "충분한 세트"의 사전 기준(키·시점 셀 커버리지), 그리고 이 기준이 결과를 보고 다시 쓰이지 않는다는 선언. 사전등록이 없으면 커버리지 수치는 사후 합리화다(`gotcha_a-screening-gate-can-fail-on-its-own-threshold` 는 *결과를 보고 기준을 고치지 말라*는 반대 교훈도 함께 준다).
- [x] `scripts/label_location_plates.py` -- `LABEL_PROMPT` 에 **신규 필드 `depicts_person`** 추가(액자·모니터·포스터·해부도·조각상·마네킹 **안**의 인물). 기존 `has_person`(방 안의 실제 인물)의 의미는 **바꾸지 않는다** — 14.4 가 기각한 것은 런타임 가드 확장이지 승인 기준 확장이 아니고, 두 질문을 한 필드에 합치면 `vision_check.CHECK_PROMPT` 가 옳게 답하는 질문을 다시 흐린다. `REQUIRED_BOOLS` 에 `depicts_person: False` 추가(신규 플레이트 자동승인만 차단, 기존 승인은 불변). `temperature: 0` 핀 — 재산출 불가능한 측정은 기록할 수 없다. **part order 는 바꾸지 않는다**(이 질문에 대한 순서 효과는 미측정, `deferred-work.md` 로).
- [x] `src/yt_flow/services/asset_service.py` -- `record_source(key: str, field: str, value: dict) -> None` 추가. **리뷰 루프 1**: 기존 엔트리의 `source` 가 dict 가 아닐 때(`None`/문자열) `setdefault` 가 `TypeError` 를 던져 큐레이션 스윕이 매니페스트 중간에서 죽는다 — 비-dict 는 교체하고 `LookupError` 계약을 지켜라. `_record_verdict` 의 load/mutate/save 를 서비스로 올려 라벨러와 신규 측정 스크립트가 **한 구현**을 쓰게 한다(지금은 스크립트마다 손으로 만든다). 미등록 키는 `LookupError`.
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/measure_plates.py` -- **리뷰 루프 1 정정 4건**: (i) `score_plate` 가 돌려준 **`has_person` 을 버리지 마라** — 2026-08-25 재판정을 `plate_meta` 에 싣는다(그 값이 가장 필요한 `entrance-checkpoint/b` 에서 정확히 버려졌다). (ii) 플레이트별 본문을 예외로 감싸고 `META_PATH` 를 `finally` 에서 써라 — 중간 실패가 매니페스트를 반쯤 쓰고 재실행에 84콜을 다시 물린다. (iii) 콘택트 시트 행 높이가 첫 타일 높이를 가정한다 — 종횡비가 다른 플레이트가 들어오면 판정용 이미지가 깨진다. (iv) `--dry-run`/`--sheets`/`--commit` 3단은 유지.
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/replay_coverage.py` -- **리뷰 루프 1 정정 3건**: (i) 선택기에 **전체 `thread_id` 를 `run_id` 로** 넘겨라 — CLI 접두사(`4b35c0ed`)를 넘기고 있어서 집계(17/7/7·70.8%)는 맞지만 리포트가 이름으로 적은 **샷별 플레이트 배정이 그 런과 재현되지 않는다**. (ii) `depicts_person` 제외를 C1/C2 와 선택기 중 한쪽에만 걸지 마라 — D1 이후 두 쪽이 같은 규칙을 쓴다. (iii) 승인 플레이트 0 인 키는 `no_metadata` 가 아니라 `stock_plate_missing` 으로 세라(런타임과 사유 표가 갈린다), 그리고 미키 샷 비율의 분자가 (샷,키) 조합이라 1 을 넘을 수 있다 — 샷 단위로 세라.
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/viewpoint_verdicts.csv` + `report.md` -- **`marginal` 이 사전등록과 어긋난다.** `PREREGISTRATION.md` 는 `±0.05` 라고 적었는데 CSV 는 사실상 `±0.03` 으로 찍혔다(0.43→1 인데 0.44·0.45·0.55→0). **사전등록을 결과에 맞춰 고치지 말고 CSV 를 사전등록에 맞춰 다시 찍어라** — 그러면 marginal 은 11 행이 아니라 20 행이고, 부족분 5셀 중 `(corridor, HIGH)`·`(medical-bay, HIGH)`·`(observation-room, HIGH)` 가 **리포트 자신이 선언한 측정 노이즈 안**에 든다. 민감도 절과 "최소 5장" 결론을 그 사실 위에서 다시 써라(결론이 "최소 2장"이 될 수 있고, 그렇다면 그것이 답이다).
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/measure_plates.py` (원 태스크 서술) -- 신규. **3단 CLI 로 맹검 순서를 강제**한다: `--sheets` 는 승인 플레이트 42장의 `y_h` 보조선 콘택트 시트만 굽고(14.0 `build_viewpoint_sheets.py` 재사용) VLM 콜 0; 사람/에이전트가 시트를 보고 `viewpoint_verdicts.csv` 를 채운 뒤, `--commit` 이 그 CSV + `vision_check.plate_has_standing_room`(**import 해서** 호출, 문구·봉투 복사 금지) + 확장된 라벨러의 `depicts_person` 을 합쳐 `plate_meta.json` 을 쓰고 `AssetService.record_source(key, "plate_meta", …)` 로 매니페스트에 붙인다. `--dry-run` 은 42장을 열거하고 콜 0. 스크립트 없는 측정치는 무효다(`gotcha_a-measurement-without-its-sample-band`).
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/viewpoint_verdicts.csv` -- 신규. 42행. 시트를 `location_key/variant` 오름차순으로만 보고 `y_h`·`verdict`·`marginal`·`rule` 을 기록한다(14.0 CSV 스키마 동일). **프롬프트·`VARIANT_CAMERAS` 문구를 열람하지 않고 판정**한다.
- [x] `src/yt_flow/services/location_service.py` -- `resolve_stock_plates` 가 `{variant, path, **plate_meta}` 를 내도록 매니페스트를 런당 1회 읽어 병합. 메타데이터 없는 플레이트는 `plate_meta` 키 자체가 없다(빈 dict 아님) — 호출부가 "미측정"과 "측정했는데 부적합"을 구분해야 한다. **리뷰 루프 1**: D1 이 쓸 수 있도록 `source.label.has_person` 도 이 seam 으로 함께 내보낸다(측정 dict 와 라벨 dict 는 매니페스트에서 서로 다른 자리에 있다). fail-open `except` 절은 `assets` 가 dict 가 아니거나 엔트리가 `None`/문자열인 매니페스트에서 `AttributeError` 로 새어나간다 — 그러면 선언한 `no_metadata` 폴백 대신 전 키가 `stock_plate_resolution_failed` 가 된다. 절을 실제 실패 집합에 맞춰라.
- [x] `src/yt_flow/pipeline/nodes/image.py` -- `_plate_variant_index` 를 순수 함수 `_select_plate(shot, plates, run_id, scene_num) -> tuple[dict | None, str]`(선택된 플레이트, 사유)로 교체. 정합 맵 상수는 이 모듈 private. 후보 0 이면 `stock_plate_unfit` 경고 + 생성 폴백. 히트 시 `provenance.stock_plate` 에 `viewpoint`/`standing_room`/`reason` 을 싣는다. 비교 키 3개는 불변. **리뷰 루프 1 이 이 함수에서 결정되지 않은 것 넷을 고정한다 — 아래 D1~D4 를 그대로 구현한다.**
  - **D1 인물 보유 플레이트는 후보에서 뺀다.** 후보 필터에 `has_person`/`depicts_person` 이 참인 플레이트 제외를 추가하고 사유는 `plate_shows_person`. **이것은 승인 철회가 아니다** — 자산 상태(`status='approved'`)는 그대로 두고 그 자산을 *이 샷에* 쓰지 않을 뿐이며, Block If 가 금지한 것은 상태 변경이지 배정 거부가 아니다. 강제 이유: 플레이트 경로는 10.2/14.4 사람 가드를 **`continue` 로 건너뛴다**(그 가드는 생성 경로에만 있다). 필터가 없으면 라벨러 자신이 `has_person: true` 라고 적어둔 `entrance-checkpoint/b`(실측: 경비 부스에 인물 2) 가 cast 샷에 복사되고 그 위에 카드가 합성된다 — 가드가 존재하는 이유인 이중 인물이 **경고 한 줄 없이** 출하된다. 또한 사전등록 C1/C2 가 `depicts_person` 플레이트를 셀에서 제외하는데 선택기가 그것을 쓰면 두 반쪽이 서로 다른 규칙을 갖는다.
  - **D2 어포던스 필터는 `plate_affordance_gate_enabled` 노브를 존중한다.** `standing_room is True` 필터를 노브 조건 뒤에 둔다. 이유: 14.2 는 오탐 1/25 의 **유일한 복구 경로**로 "노브를 내리면 카드가 돌아온다"를 설계했는데, 노브 없는 두 번째 하드 필터는 그 복구를 무효로 만든다. 그리고 노브 OFF 에서 `no_standing_room` 폴백은 **어포던스 판정이 아예 없는** 생성 프레임을 낳으므로, 측정된 나쁨을 거부하고 미측정을 받는 역전이 된다. 노브 OFF 여도 D1 은 계속 건다(인물 유무는 어포던스 축이 아니다).
  - **D3 타이브레이크 키는 실제 후보 풀과 일치해야 한다.** 지금 형태는 modulo 를 cast 필터 **이후** 풀에 걸면서 digest 키에는 cast 유무가 없어, 한 씬·한 키·한 시점에서 cast 샷과 cast-free 샷이 **다른 플레이트**를 받는다(오늘 40/42 가 `standing_room=true` 라 안 터질 뿐). digest 키에 실제로 후보를 갈라놓은 축을 전부 넣거나, 필터 결과가 같은 풀이 되도록 순서를 바꾼다. 어느 쪽이든 docstring 의 "(씬, 시점)당 1장" 주장과 코드가 일치해야 한다.
  - **D4 resume 이 자산 판정을 다시 읽는다.** resume 경로(`:892-918`)는 cast 보유 캐시 샷을 무조건 `affordance_counts["unjudged"]` 로 세는데, 플레이트로 서빙된 샷은 사이드카 `provenance.stock_plate.standing_room` 에 판정이 **적혀 있다**. 그것을 읽어 판정됨으로 계상하라. 안 그러면 14.2 가 없앤 결함(판정 안 된 것과 판정된 것이 집계에서 구분 안 됨)이 방향만 바꿔 되살아나고, `affordance_undecidable` 이 이제 `False` 라 설명 경고조차 없다.
  - **사유 어휘 정정**: 일부만 측정된 키에서 `no_viewpoint_match` 를 내면 "렌더가 필요하다"로 읽히지만 실제 처방은 "기존 플레이트를 측정하라"다 — 부분 측정은 별도 사유로 구분한다. 어휘 밖 `camera_angle`(사전-14.0 체크포인트의 원문 문자열)은 `unservable_framing`(close-up/POV 전용으로 문서화됨)이 아니라 `unknown_framing` 이다.
- [x] `src/yt_flow/domain/warnings.py` + `src/yt_flow/domain/state.py` -- `stock_plate_unfit` 코드 + reason 중립 카탈로그 문안(파괴적 결과를 단언하지 마라 — 폴백은 생성이지 손실이 아니다) + `RunWarningCode` 리터럴. reason 값 5종을 문서화.
- [x] `src/yt_flow/config.py:304-311` -- `stock_plate_substitution_enabled` 주석을 **날짜 붙여 갱신**한다. **리뷰 루프 1: 과대주장 금지** — 원 주석의 블로커는 씬 키잉 **과** 폐기된 `image_prompt` 둘이었고 `_select_plate` 는 `camera_angle`·`cast`·`location_key` 만 읽는다. `image_prompt` 는 여전히 통째로 버려진다. 닫힌 것은 **프레이밍 절반**이라고 적고, 의미 정합(프롬프트 내용 ↔ 플레이트 내용)은 미해결로 남겨라(`epics.md:1980` 의 *"`image_prompt`/`location_key`와의 정합"* 서술도 같은 정정 대상이다). 갱신 내용: 지목된 블로커(씬 키잉 + `image_prompt` 폐기)는 이 스토리가 해소했고, 남은 켜기 조건은 (a) 측정된 커버리지가 사전등록 기준 이상, (b) Jay 의 E2E 시청 판정이다. **기본값 `False` 유지, `.env`/`.env.example` 핀 금지.** 날짜 붙은 *승격* 판정이 아직 없으므로 `DECISIONS` 행은 계속 추가하지 않는다(`config.py:662` 의 기존 서술 유지).
- [x] `src/yt_flow/domain/state.py:308-315` + `src/yt_flow/pipeline/nodes/scenario_chain.py:520-523` -- `camera_angle` 소비자 서술 정정. 이제 배경 **선택**에 도달한다(픽셀 생성 프롬프트에는 여전히 미도달). 원 서술을 지우지 말고 세 번째 경로를 덧붙인다.
- [x] `_bmad-output/implementation-artifacts/14-1-approved-plate-sets/report.md` -- 신규. **리뷰 루프 1 정정 3건**: (a) §7 릴라이트 절과 `deferred-work.md` 항목이 **거짓 발화 조건**을 적었다 — `composite_harmonization.py:613` 의 페어 키는 `(card_variant, location_key)` 로 **씬 성분이 없다**. 따라서 결합은 씬 스코프가 아니라 **런 전체**이고, 이 런에서 이미 발화한다(리포트 자신의 §2 가 `containment-chamber` 를 씬 3·4 `/b` · 씬 8·9 `/c` 로 적는다). "14.1 이전에는 무해했다"도 거짓이다. 방향을 정정하고 ~~**릴라이트 수정을 플래그 켜기 조건 목록에 올려라**(부족분 5장을 렌더하면 9씬 중 4씬이 한 키에 두 플레이트를 갖게 되어 스토리 자신의 해제 조건이 이 결함을 격발한다)~~ — **⚠️ 2026-08-29 Story 14.3 정정 — 이 조건은 성립하지 않는다.** 문제의 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고, 그 함수는 `video.py`가 `composite_harmonization_tier >= 3`에서만 호출한다. 출하 기본값은 **1**이고 tier 3(IC-Light)은 10.1b가 시청 판정으로 기각했다. **그 한 줄로 도달 불가는 성립하고, 그 뒤에 아무것도 필요하지 않다.** ⚠️ 이 정정의 초판은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*이라는 두 번째 다리를 붙였는데, **그것은 불변식이 아니라 run `4b35c0ed`의 관찰이다** — `recompose_run_shots`의 `remaining.pop(shot_key)`는 성공·재진입 분기에서만 실행되므로 `failed`(스윕 중 ComfyUI 사망, 플레이트 판독 실패)나 `skipped`(`card_key`가 `CARD_LOOKS` 밖)로 세어진 샷은 cast를 그대로 들고 오버레이/하모나이제이션 체인에 **진입한다**. 실패가 하나라도 나는 런에서는 0/43이 아니다. **0/43은 관찰로 강등하고, 반증은 `tier >= 3` 하나로 선다.** 이 프로젝트에서 이 형태(기록된 원인이 뒤집힘)는 이번이 **세 번째**이고, 세 번째는 **정정하는 문서 자신이 심은 과장**이었다 — `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. **이 인계 항목의 두 번째 발화 조건 정정이다**, 그래서 원문을 지우지 않고 취소선으로 남긴다(`gotcha_recorded-root-cause-can-be-inverted`). 결합 자체는 **여전히 결함이고 여전히 미수정**이며 tier 3을 켜면 발화한다 — 인계는 유지되고, 끊긴 것은 플래그 해제와의 결합이다. 고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`. 근거: `14-3-art-style-contract/report.md` §6. (b) `server-room/b` 는 사람 판정 `HIGH`(`y_h=0.00`, `floor_share 0.85`)와 VLM 의 `affordance_reason`("바닥이 안 보이는 천장/상부 구조 클로즈업")이 **서로 모순**인 유일한 행이다 — 두 계기를 대조할 수 있는 유일한 지점이므로 모순을 표에 명시하고 C2 PASS 가 이 미반복 계기 위에 서 있다는 것과 함께 적어라. (c) §2·§5 의 샷별 배정 예시는 `replay_coverage.py` 의 `run_id` 정정 후 다시 산출한 값으로 교체하라. 그 밖의 신규 내용. (1) 42장 측정 표(키×variant×viewpoint×standing_room×depicts_person×camera_distance), (2) run `4b35c0ed` 31샷 재생 커버리지(정합 히트 / 폴백 사유별), (3) **부족분을 (location_key, viewpoint) 셀로 규정** — 이것이 "세트를 늘려서 해결"의 실행 가능한 입력이다, (4) `location_key` 미보유 12/43 의 성격(씬 1·5 전체가 None 인데 프롬프트는 containment chamber 를 서술한다 — 어휘 갭이 아니라 발화 갭)과 그 감수 리스크, (5) 8.19 임베딩 전제 반증, (6) 릴라이트 결합 미주장.
- [x] `_bmad-output/planning-artifacts/epics.md` -- Story 14.1 항목의 *"8.19의 임베딩 검색층이 후보 랭킹의 기반"* 을 **반증됨 + 실제 근거(측정된 메타데이터)** 로 정정. 원문을 지우지 말 것(`gotcha_recorded-root-cause-can-be-inverted`: 거짓 원인은 하나만 고치면 다시 인용된다).
- [x] `_bmad-output/implementation-artifacts/epic-14-context.md` -- **반증된 전제가 이 파일에 다시 심겼다.** 본문이 *"connects the existing stock-plate, asset-library, plate-data and **embedding-search** layers"* 라고 적는데, 같은 날짜의 `report.md` §6 과 `epics.md` 정정이 그런 층은 존재한 적이 없음을 확립한다. 그 구절을 제거·정정하라(`gotcha_recorded-root-cause-can-be-inverted`: 한 곳만 고치면 다시 인용된다).
- [x] `src/yt_flow/domain/warnings.py` (문안) -- `stock_plate_unfit` 카탈로그 문안이 **가장 흔한 사유에서 거짓**이다. *"맞는 승인 배경이 없어"* 는 `unservable_framing`(close-up/POV, 런당 7/31, **설계상 영구**)에는 사실이 아니다 — 그 키에는 멀쩡한 승인 배경이 있고 샷이 클로즈업일 뿐이다. 사유 중립 문안으로 바꿔라(14.2 가 같은 교훈을 이미 받았다).
- [x] `tests/` (어휘 동기화) -- `_ANGLE_VIEWPOINT` 는 `scenario_chain._CAMERA_ANGLES` 7값 중 5개를 손으로 베낀 두 번째 사본이고 고정 테스트가 없다(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). 두 집합의 관계를 단정하는 테스트를 넣어라 — 매핑되지 않은 2개(`close-up`/`POV`)는 **의도된 부재**이므로 그 의도까지 테스트가 말해야 하고, 어휘에 값이 추가되면 조용히 `unservable_framing` 이 되는 대신 실패해야 한다.
- [x] `_bmad-output/implementation-artifacts/spec-14-1-approved-plate-sets.md` (이 파일 Code Map) -- `composite_harmonization.py` 경로가 틀렸다: `src/yt_flow/services/` 가 아니라 `src/yt_flow/pipeline/nodes/` 다.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- 2건 등재: (a) 릴라이트 캐시가 씬 내부 다중 variant 를 첫 배경으로 통일하는 문제(14.3 라우팅), (b) `label_location_plates` 의 `[text, image]` 봉투 순서 효과 미측정.
- [x] `tests/pipeline/nodes/test_image.py` + `tests/services/test_location_service.py` + `tests/services/test_asset_service.py` + `tests/domain/test_run_warnings.py` + `tests/test_label_location_plates.py` -- I/O 매트릭스 10행 전부 + `record_source` 가 `status`/`approved_at` 을 보존하는가 + 치환 OFF 에서 매니페스트 읽기 콜 0 + 비교 키 3개 불변(사전-14.1 사이드카 resume 히트).

**Acceptance Criteria:**
- Given 승인 플레이트 42장과 측정 산출물, when `measure_plates.py` 를 재실행하면, then `viewpoint_verdicts.csv` 의 시점 라벨과 `plate_meta.json` 의 어포던스·`depicts_person` 이 report.md 의 표와 **행 단위로 재현**된다(VLM 응답은 `temperature=0` 로 고정).
- Given run `4b35c0ed` 의 31개 `location_key` 보유 샷과 측정된 메타데이터, when 선택기를 그 샷들에 대해 오프라인으로 재생하면, then 정합 히트 수와 폴백 사유별 분포가 report.md 와 일치하고, **`close-up` 6샷과 `POV` 1샷은 전부 생성 폴백**이다.
- Given 같은 씬에 같은 `location_key` 를 가진 서로 다른 `camera_angle` 샷이 둘 이상, when 선택기가 돌면, then 두 샷이 **서로 다른 플레이트를 받을 수 있다**(씬 키잉 폐기 확인) — 단 같은 `camera_angle` 이면 결정적으로 같은 플레이트다(같은 런에서 재실행 시 바이트 동일).
- Given `stock_plate_substitution_enabled=False`(출하 기본), when image_node 가 돌면, then 선택기·매니페스트 읽기 콜 0 이고 경고 0 이며 산출물이 이 스토리 이전과 동일하다.
- Given 14.1 이전에 만들어진 체크포인트와 이미지, when 같은 런을 resume 하면, then `_existing_complete_shot` 이 여전히 히트하고 재복사·재판정이 일어나지 않는다(비교 키 3개 불변).
- Given cast 를 가진 샷이 `standing_room=true` 플레이트로 서빙됐을 때, when 런이 끝나면, then 그 샷은 `affordance_counts["unjudged"]` 에 계상되지 **않고** 사이드카에 `affordance_undecidable` 이 기록되지 않는다(14.2 가 남긴 갭이 닫힌다).
- Given 측정 결과 어떤 승인 플레이트가 `depicts_person=true` 로 나올 때, when 스크립트가 끝나면, then 그 플레이트의 `status` 는 **여전히 `approved`** 이고 report.md 가 사람 판단 대기 목록으로 올린다.
- Given 라벨이 `has_person=true` 인 승인 플레이트가 어떤 샷의 시점·키에 유일한 후보일 때, when 선택기가 돌면, then 그 플레이트는 **선택되지 않고** `stock_plate_unfit(reason=plate_shows_person)` 이 남으며, 그 플레이트의 `status` 는 여전히 `approved` 다.
- Given `plate_affordance_gate_enabled=False` 이고 cast 샷의 유일한 후보가 `standing_room=false` 일 때, when 선택기가 돌면, then 그 플레이트가 **서빙된다**(노브가 내려가면 어포던스 거부도 내려간다 — 14.2 의 복구 경로). Given 같은 상황에서 노브가 `True` 면, then `no_standing_room` 폴백이다.
- Given 한 씬·한 `location_key`·한 시점에 cast 보유 샷과 cast-free 샷이 각각 있고 후보가 둘 이상일 때, when 선택기가 돌면, then 두 샷은 **같은 플레이트**를 받는다(타이브레이크 키가 실제 후보 풀과 일치).
- Given 플레이트로 서빙된 cast 샷의 사이드카가 있을 때, when 같은 런을 resume 하면, then 그 샷은 `affordance_counts["unjudged"]` 에 **계상되지 않는다**(사이드카의 `stock_plate.standing_room` 을 읽는다).
- Given `assets` 가 dict 가 아니거나 엔트리가 `None` 인 손상된 매니페스트, when `resolve_stock_plates` 가 불리면, then 예외가 새어나가지 않고 메타데이터 없는 플레이트 목록이 돌아와 `no_metadata` 폴백이 된다(`stock_plate_resolution_failed` 가 아니다).
- Given `viewpoint_verdicts.csv` 를 사전등록 `±0.05` 규칙으로 다시 찍었을 때, when 민감도 절을 재산출하면, then 부족분 셀 목록과 "최소 N장" 결론이 그 marginal 집합 위에서 다시 유도되고, 노이즈 안에 드는 셀이 그렇다고 표시된다.


## Spec Change Log

- 2026-08-25 **리뷰 루프 1 — `_select_plate` 설계 표면에서 결정되지 않은 것이 넷이었다(bad_spec 4, high 2 / medium 2).**
  **트리거**: 두 리뷰어가 독립적으로 같은 함수를 지목했다. (1) 플레이트 경로는 10.2/14.4 사람 가드를
  `continue` 로 **건너뛰는데** 선택기가 `has_person` 을 보지 않아, 라벨러 자신이 `has_person: true` 로
  적어둔 `entrance-checkpoint/b`(실측 인물 2)가 cast 샷에 서빙 가능하다 — 이 스토리가 14.4 에서
  **인계받은 바로 그 부류**가 측정만 되고 강제되지 않았다. (2) `standing_room` 하드 필터가 노브를
  무시해 14.2 의 유일한 오탐 복구 경로를 무효화하고, 노브 OFF 에서는 "측정된 나쁨을 거부하고
  미측정을 받는" 역전을 만든다. (3) 타이브레이크 digest 키가 cast 필터 **이전** 풀 기준이라 한 씬에서
  cast 샷과 cast-free 샷이 다른 플레이트를 받을 수 있다(오늘 40/42 가 room=true 라 잠복). (4) resume 이
  사이드카에 적힌 자산 판정을 안 읽고 전부 `unjudged` 로 세어, 14.2 가 없앤 결함이 방향만 바꿔
  되살아난다.
  **수정**: Tasks 의 image.py 항목에 **D1~D4 를 명시적 결정으로 고정**하고 대응 AC 4건을 추가했다.
  D1 은 Block If 와 충돌하지 않는다는 근거를 함께 적었다 — **배정 거부는 승인 철회가 아니다.**
  **회피한 알려진-나쁜 상태**: 사람 가드가 없는 경로로 인물 2명짜리 배경을 내보내고 그 위에 카드를
  합성하는 것(경고 0), 그리고 사전등록 C1/C2 와 런타임 선택기가 서로 다른 규칙을 쓰는 두 반쪽 상태.
  **KEEP(재도출 시 반드시 살릴 것)**: `_select_plate` 의 **순수 함수 + `(plate, reason)` 반환** 형태 /
  `_ANGLE_VIEWPOINT` 에서 `close-up`·`POV`·`None` 이 **의도적으로 부재**라는 것과 그 근거 주석 /
  미측정 플레이트는 절대 선택되지 않는 **fail-open `no_metadata`** / `standing_room is True` **동일성
  비교**(판정불가를 room 으로 읽지 않는다) / builtin `hash()` 가 아닌 **sha256** 타이브레이크 /
  `_existing_complete_shot` **비교 키 3개 불변**과 사전-14.1 resume 히트 테스트 / `stock_plate_missing`
  과 `stock_plate_unfit` 의 **분리** / `resolve_stock_plates` 가 `variant`·`path` 를 **마지막에** 써서
  메타데이터가 그것을 가리지 못하게 한 것 / 미측정은 `viewpoint` **키 자체가 부재**(빈 dict 아님) /
  `AssetService.record_source` 가 `status`·`approved_at` 을 보존하고 미등록 키에 `LookupError` /
  코드 기본값 `False` · `.env` 핀 없음 · `DECISIONS` 행 없음 / `background_has_person` 의
  `image_first=False` 미변경 / `prompts/` 무변경 / report §0 의 **"주장하지 않는 것"** 절과 맹검 침해
  자진 기록 / §8 의 승인-42장 중 라벨 `decision=draft` **14건 전수 스윕**.
  **되돌리지 않은 것과 그 이유**: 측정 산출물(`viewpoint_verdicts.csv` 42행 · `plate_meta.json` ·
  `assets/manifest.json` 의 `source.plate_meta` · `sheet_*.jpg` · `PREREGISTRATION.md`)과 그것을 만든
  `scripts/label_location_plates.py` 의 프롬프트 변경은 **되돌리지 않았다**. 시점 판정은 사람이 프롬프트
  비열람 상태에서 한 **일회성 맹검**이라 재도출이 불가능하고(이미 본 뒤에는 다시 맹검일 수 없다),
  되돌리면 84 VLM 콜을 다시 쓰면서 증거의 품질은 **떨어진다**. 되돌린 것은 bad_spec 이 지목한 코드뿐이다:
  `image.py` · `location_service.py` 와 그 둘을 고정하는 테스트 2개.


## Review Triage Log

### 2026-08-25 — Review pass
- intent_gap: 0
- bad_spec: 4: (high 2, medium 2)
- patch: 12: (high 2, medium 6, low 4)
- defer: 2: (medium 2)
- reject: 3
- addressed_findings:
  - `[high]` `[bad_spec]` 플레이트 경로가 10.2/14.4 사람 가드를 건너뛰는데 선택기가 `has_person`/`depicts_person` 을 안 본다 — 라벨이 `has_person: true` 인 `entrance-checkpoint/b`(실측 인물 2, 그럼에도 `approved`)가 cast 샷에 서빙 가능. 14.4 인계 축이 측정만 되고 강제되지 않았고, 사전등록 C1/C2 는 이미 그 축으로 셀을 제외하고 있어 두 반쪽이 어긋난다 → **D1** 로 고정(배정 거부 ≠ 승인 철회).
  - `[high]` `[bad_spec]` 새 `standing_room` 하드 필터가 `plate_affordance_gate_enabled` 를 무시 — 14.2 의 유일한 오탐 복구 경로(노브 내리기)를 무효화하고, 노브 OFF 에서 측정된 나쁨을 거부하고 **판정 자체가 없는** 생성 프레임을 받는 역전을 만든다 → **D2** 로 노브 게이팅 고정.
  - `[medium]` `[bad_spec]` 타이브레이크 digest 키가 cast 필터 이전 풀 기준이라 한 씬·한 시점에서 cast 샷과 cast-free 샷이 다른 플레이트를 받을 수 있다(오늘 40/42 room=true 라 잠복). docstring 의 "(씬, 시점)당 1장" 이 코드와 불일치 → **D3**.
  - `[medium]` `[bad_spec]` resume 이 사이드카의 `stock_plate.standing_room` 을 안 읽고 cast 캐시 샷을 전부 `unjudged` 로 계상 — 14.2 가 없앤 "판정된 것과 안 된 것이 집계에서 구분 안 됨"이 방향만 바꿔 부활하고, `affordance_undecidable=False` 라 설명 경고도 없다 → **D4**.


### 2026-08-29 — Review pass 2
**실행되지 않았다 — Jay 가 중단했다(리뷰 서브에이전트 2개 도구 사용 거부 + "계속 하자").**
루프 1 의 bad_spec 4건(D1~D4)에 대한 재도출과 patch 12건은 전량 자체 검증됐으나
(3329 passed / 1 known pre-existing · ruff clean · 드리프트 exit 0 · 커버리지 재산출 일치)
**독립 리뷰를 받지 않았다.** 그래서 `followup_review_recommended: true` 다 — 루프 1 이
선택기 필터 순서·노브 게이팅·타이브레이크 키·resume 회계·`marginal` 밴드·부족분 결론까지
모두 건드렸고 그 수정들 자체는 검토되지 않았다. (14.2 가 같은 지점에서 같은 처리를 했다.)
- intent_gap: 0
- bad_spec: 0
- patch: 0
- defer: 1
- reject: 0
- addressed_findings:
  - none

## Design Notes

**정합 맵 (사전등록 대상, 보수적으로 고정).** 샷의 `camera_angle` → 요구 플레이트 `viewpoint`:

```
wide, medium, over-the-shoulder  -> EYE
low-angle                        -> LOW
high-angle                       -> HIGH
close-up, POV                    -> (없음: 방 플레이트는 물체 클로즈업·천장 POV 를 서빙할 수 없다)
None                             -> (없음: 추측하지 않는다)
```

`UNREADABLE` 판정 플레이트는 어느 셀에도 들어가지 않는다. 실측 수요(run `4b35c0ed`, 31샷): medium 7 · wide 7 · close-up 6 · high-angle 4 · OTS 3 · low-angle 3 · POV 1 — 즉 **EYE 수요가 17/31 로 지배적**이고 close-up+POV 7/31 은 설계상 영구 폴백이다.

**왜 선언이 아니라 측정인가.** `VARIANT_CAMERAS` 는 a=eye / b=low / c=close 를 *요청*한다. 하지만 14.0 §4-4 가 같은 프롬프트·다른 시드로 시점이 5쌍 중 2쌍 뒤집히는 것을 실측했다 — 요청은 보장이 아니다. 플레이트는 ControlNet 기하 제어로 렌더돼 자유생성보다 신뢰도가 높을 개연이 있지만 **그것도 가설이고, 42장을 재는 비용이 GPU 0 · 몇 분**이다. 측정치와 선언의 불일치 건수는 report.md 에 남긴다(그 자체가 ControlNet 기하 제어의 유효성 증거가 된다).

**어포던스가 런당 비용 0 이 되는 지점.** 14.2 는 런타임에서 확정 렌더 1장당 VLM 1콜을 낸다. 플레이트는 자산이므로 **자산당 1회**면 영구히 답이 산다 — 42콜 한 번으로 31/43 샷의 판정이 공짜가 된다. 이것이 §4-2 (c) 결정의 메타데이터 절반이고, 런타임 절반(자유생성 샷)은 14.2 가 이미 출하했다.

**커버리지가 곧 켜기 조건이다.** 이 스토리는 플래그를 켜지 않는다. 대신 report.md 가 "세트가 충분한가"를 셀 단위로 답해서, 증설 배치가 *무엇을 몇 장* 렌더해야 하는지를 렌더 전에 확정한다. 오늘 세트에 `HIGH` 시점이 한 장도 없다면 high-angle 4샷은 폴백이고, 그 4샷이 켜기를 막는지 아닌지는 사전등록 기준이 답한다.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_image.py -q` -- expected: 기존 전량 통과 + 신규 통과(`:956-971` 은 새 계약으로 교체)
- `uv run pytest tests/services/test_location_service.py tests/services/test_asset_service.py tests/domain/test_run_warnings.py tests/test_label_location_plates.py -q` -- expected: 통과
- `uv run pytest -q` -- expected: `test_render_pose_guides.py` PNG SHA 1건만 실패(14.5 가 기존 결함으로 기록, stash 후에도 동일)
- `uv run ruff check src tests scripts` -- expected: clean
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0, `stock_plate_substitution_enabled` 이 env-sourced 나 latent 핀으로 뜨지 않음
- `uv run python _bmad-output/implementation-artifacts/14-1-approved-plate-sets/measure_plates.py --dry-run` -- expected: 42장 열거, VLM 콜 0
- `git diff --stat prompts/` -- expected: 비어 있음(런타임 프롬프트 불변 계약)

**Manual checks (if no CLI):**
- 픽셀 판정은 이 스토리가 하지 않는다. 치환을 켠 **E2E iteration 5** 에서 배경 정합이 어떻게 보이는지가 판정이고, 그 런 없이 "고쳤다"를 적지 않는다.
- `depicts_person=true` 로 나온 플레이트가 있으면 사람 확인 대기 목록으로만 남긴다(승인 철회 금지).

## Auto Run Result

Status: **done** — 단, **닫힌 것은 배정 규칙과 자산 메타데이터이고, 픽셀 판정과 플래그 승격은 열려 있다.**
`stock_plate_substitution_enabled` 가 `False` 로 남는 것이 그것을 안전하게 만드는 조건이다.

### 구현된 변경

8.17 이 씬을 키로 배경을 배정하면서 샷의 프레이밍을 통째로 버리던 것을, **샷마다 그 샷의
`camera_angle` 을 각 플레이트의 실측 시점과 대조해 고르고, 맞는 후보가 없으면 생성으로
폴백**하도록 바꿨다. 승인 플레이트 42장에는 시점·설 자리·그림 속 인물이 **자산 메타데이터**로
붙었다 — §4-2 결정의 메타데이터 절반이 여기서 닫힌다(런타임 절반은 14.2 가 출하했다).
플레이트당 1회 측정이므로 런당 비용은 0 이다.

### 파일

| 파일 | 한 줄 |
|---|---|
| `src/yt_flow/pipeline/nodes/image.py` | `_plate_variant_index` → 순수 `_select_plate(..., *, affordance_gate)`; 필터 순서 = 프레이밍 → 메타데이터 → 시점 → 인물(D1) → 어포던스(D2); 타이브레이크 digest 가 **후보 풀 자체를 포함**(D3); resume 이 `_sidecar_plate_room` 으로 자산 판정을 되읽음(D4) |
| `src/yt_flow/services/location_service.py` | `resolve_stock_plates` 가 `source.plate_meta` + `source.label.has_person` 을 병합, `variant`/`path` 는 마지막에, 매니페스트 파손에 fail-open |
| `src/yt_flow/services/asset_service.py` | `record_source` — `status`/`approved_at` 보존, 미등록 키에 `LookupError`, 비-dict `source` 교체 |
| `src/yt_flow/domain/warnings.py` · `state.py` | `stock_plate_unfit` + 사유 7종(사유 중립 문안) |
| `src/yt_flow/config.py` | 켜기 조건 3건을 날짜 붙여 명시. **기본값 `False`, `.env` 핀 없음, `DECISIONS` 행 없음** |
| `src/yt_flow/domain/state.py` · `scenario_chain.py` | `camera_angle` 의 **세 번째 소비자** 경로 기록(원 서술 보존) |
| `scripts/label_location_plates.py` | `depicts_person` 필드(14.4 인계) + `temperature: 0` 핀 + `record_source` 위임 |
| `tests/` 5개 | I/O 매트릭스 전행 + AC 전건 + D1~D4 양방향 |
| `14-1-approved-plate-sets/` | 사전등록 · 측정/재생 스크립트 2종 · 42행 CSV · `plate_meta.json` · 시트 7장 · 리포트 10절 |

### 리뷰 결과

**패스 1**: intent_gap 0 · **bad_spec 4**(high 2) · patch 12 · defer 2 · reject 3 → 스펙 수정(D1~D4) + 재도출.
**패스 2**: Jay 가 중단 → 미실행, `followup_review_recommended: true`.

가장 중대한 발견 둘은 **이 스토리 자신의 산출물을 반증했다**:
1. **선택기가 인물이 있는 플레이트를 서빙할 수 있었다.** 플레이트 경로는 10.2/14.4 사람 가드를
   `continue` 로 건너뛰는데, 라벨러 자신이 `has_person: true` 라고 적어둔 `entrance-checkpoint/b`
   (경비 부스에 인물 2, 그럼에도 `approved`)가 후보에서 걸러지지 않았다. 이 스토리가 14.4 에서
   **인계받은 바로 그 부류**를 측정만 하고 강제하지 않은 것이다 → D1.
2. **`marginal` 이 사전등록(±0.05)이 아니라 ±0.03 으로 찍혀 있었다.** 다시 찍으니 11 → **20행**이
   되고, **부족분 결론이 "최소 5장"에서 "최소 2장 + 3셀 재판독"으로 바뀌었다** — HIGH 3셀이
   리포트 자신이 선언한 측정 노이즈 안에 든다. 사전등록은 고치지 않았고 CSV 를 사전등록에
   맞췄다.

그 외: `standing_room` 하드 필터가 14.2 의 유일한 오탐 복구 경로(노브 내리기)를 무효화했고(D2),
타이브레이크 키가 실제 후보 풀과 어긋나 한 씬에서 cast 샷과 cast-free 샷이 다른 배경을 받을 수
있었으며(D3), resume 이 사이드카에 적힌 자산 판정을 안 읽고 전부 `unjudged` 로 셌다(D4).
릴라이트 결합은 **씬 스코프가 아니라 런 전체**이고 이 런에서 이미 발화한다는 것이 밝혀져
플래그 켜기 조건 (c) 로 승격됐다.

### 실측 (재산출: `replay_coverage.py 4b35c0ed`)

42장 = EYE 33 / HIGH 4 / LOW 5, `standing_room` 40 true / 2 false, `depicts_person` 0 true.
**선언 vs 실측: variant `a` 13/14, variant `b` 2/14** — "`b` 를 더 뽑자"는 증설 계획은 성립하지 않는다.
run `4b35c0ed` 31샷: **정합 17 · `unservable_framing` 7(close-up 6 + POV 1, 설계상 영구) ·
`no_viewpoint_match` 7**. servable 24 → **17/24 = 70.8%**. 사전등록 C1 FAIL(5/10) · C2 PASS · C3 FAIL.

### 검증

`uv run pytest -q` → **3329 passed / 1 failed / 1 skipped**. 그 1건은 `test_render_pose_guides.py`
PNG SHA 핀이며 **가정이 아니라 확인**했다(baseline `80ee501` 의 분리된 worktree 에서 동일 실패).
`ruff check` clean · `report_decision_drift.py` exit 0(드리프트 0 · env-sourced 0 · latent 핀 0) ·
`measure_plates.py --dry-run` = 42장/0콜 · `git diff --stat prompts/` 비어 있음.

### 잔여 리스크 — 주장하지 않는 것

- **합성 산출물의 픽셀 판정 0회.** 배경 정합이 시청에서 어떻게 보이는지는 치환을 켠
  **E2E iteration 5** 몫이고, 그 런 없이 "고쳤다"는 문장은 어디에도 없다.
- **패스 2 리뷰 미실행** — 루프 1 의 수정들이 독립 검토를 받지 않았다.
- **`has_person` 재판정이 `plate_meta` 에 없다.** 스크립트는 기록하도록 고쳤으나 `--commit` 을
  다시 돌리지 않았다(84 VLM 콜 + 대체 불가한 측정 블록 덮어쓰기). D1 은 2026-08-02 라벨에 의존한다.
- **HIGH 3셀 재판독 미실행** — 시트를 이미 본 뒤라 맹검이 성립하지 않는다. GPU 0 의 후속 단계로 남겼다.
- **승인 42장 중 14장의 라벨 `decision` 이 `draft`** 이고 그중 3장은 커버된 셀에 있다(리포트 §8).
  승인 철회는 하지 않았다 — 사람 판단이다.
- **플레이트 경로에 런타임 사람 가드가 없다**(D1 은 라벨 기반 부분 완화) → `deferred-work.md`.
