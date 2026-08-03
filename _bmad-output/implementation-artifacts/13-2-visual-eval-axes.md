---
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
---

# Story 13.2: 평가 축 확장 — 프레임/모션 축 추가

Status: ready-for-dev

## Story

As a **yt.flow 운영자 (Jay)**,
I want **A/B 평가가 나레이션 텍스트 3축만 보는 대신 모션 다양성·아키타입 커버리지·컷 정렬 오차를 규칙 기반으로 함께 채점하고, 그 값이 승자 결정과 UI에 실제로 반영**되도록,
so that **"영상이 조잡해도 평가 점수가 안 변하는" 현재 상태가 끝나고 — LLM judge는 영상을 볼 수 없으니 텍스트 점수는 렌더 품질에 대해 구조적으로 무지하다 — 시각 품질 회귀가 사람 눈보다 먼저 숫자로 잡힌다**.

## Acceptance Criteria

1. **모션 축 2종 — 순수 함수, `camera_movement` enum 분포에서 산출**: `eval_service.py`에 두 개의 rule metric 신설.
   - `motion_archetype_coverage` (0.0–1.0, **높을수록 좋음**): 런 전체 샷에서 실제로 쓰인 `CAMERA_ARCHETYPES` 멤버의 distinct 개수 ÷ `len(CAMERA_ARCHETYPES)`(=5). `camera_movement`가 archetype이 아닌 값(레거시 자유 텍스트) 또는 `None`인 샷은 **분자에 기여하지 않는다**(그 샷의 실제 모션은 `select_effect`의 `_DIRECTION_POOL` 라운드로빈 폴백으로 결정되므로 아키타입이 아님).
   - `motion_repeat_ratio` (0.0–1.0, **낮을수록 좋음**): 런 순서(씬 번호 오름차순 → 씬 내 샷 순서)로 평탄화한 샷 리스트의 인접 쌍 중 모션 키가 같은 쌍의 비율. 정규화 키 = `camera_movement`가 `CAMERA_ARCHETYPES` 멤버면 그 값, 아니면 `"unmapped"` 단일 버킷.
   - **씬 경계를 포함해서 센다** — 이것은 11.2 `_enforce_camera_variety`의 계약(씬 내부 인접만 금지, 씬 경계는 5.16 dip-to-black이 시각 연속성을 끊으므로 의도적 제외)과 **다르며, 다른 것이 맞다**. 씬 내부는 11.2가 이미 0을 보장하므로 씬 내부만 세면 이 메트릭은 상수 0이 되어 평가 축으로 무가치하다. 씬 경계를 포함해야만 에피소드 단위 단조로움이 관측된다. **따라서 이 메트릭의 0이 아닌 값은 11.2 위반이 아니다** — 독스트링에 이 문장을 그대로 기록할 것(후속 세션이 "위반이니 validator를 고치자"로 오독하는 것을 막는다).
   - 샷 총수 < 2면 `motion_repeat_ratio` = 0.0, 샷이 없으면 coverage = 0.0(기존 rule metric의 데이터 없음 → 0.0 폴백 관행 준수).
   - **`video.py`를 import하지 말 것.** 값은 `state["scenes"][*]["shots"][*]["camera_movement"]`에서 직접 읽는다 — `select_effect`/`EffectSpec`를 거치면 `push_in`과 `shake`가 둘 다 `"in-center"`로 붕괴해(video.py:213·229) 아키타입 다양성이 아니라 방향 다양성을 측정하게 되고, 11.3이 shake에 별도 fBm 노이즈를 얹어 실제 렌더는 구분되므로 그 붕괴는 측정 오류다. epics 원문도 "11.2의 닫힌 enum 분포"라고 아키타입 계층을 지정한다. `CAMERA_ARCHETYPES`는 `domain.state`에서 import(이미 `SceneState`/`PipelineState`를 그 모듈에서 import하고 있음).

2. **`cut_alignment_error` 승자 결정 입력으로 승격**: 11.4가 추가하고 독스트링에 `"Regression-detection record ONLY — never a determine_winner tiebreak input"`으로 **명시적으로 차단**해 둔 것을 해제한다. 새 계산을 만들지 말 것 — `_cut_alignment_error()`(eval_service.py:253)는 이미 정확하고, 이 AC는 배선과 독스트링 정정만이다. 해당 마지막 문장을 삭제하고 승격 사유(13.2)를 기록한다.

3. **tiebreak 구현 단일화 — 추가가 아니라 통합(선행 결함 제거)**: 현재 tiebreak 로직이 **두 곳**에 중복돼 있고, **집계 방식 자체가 다르며**, 그래서 서로 다른 승자를 낼 수 있다:
   - `_rule_tiebreak(metrics_a, metrics_b)`(eval_service.py:317) — dataclass 입력, 지표 2종(`avg_subtitle_sync_error`, `audio_duration_variance_pct`), **점수 합산 방식**(각 지표에서 이긴 쪽이 1점, 총점 높은 쪽 승, 동점이면 `"tie"`), 엄격 `<` 비교, pct 스케일. `_pairwise_compare` → `PairwiseResult.final_winner` → **함수 반환값 `EvaluationResult.winner`** 경로.
   - `determine_winner()` step 3(eval_service.py:566) — dict 입력, 지표 3종(+`scene_count_match_rate`), **lexicographic 우선순위 방식**(첫 번째로 유의미하게 갈리는 지표가 즉시 승자 결정), epsilon `> 0.01`, 비율 스케일(variance ÷100). `store_evaluation_results` → **DB에 저장되고 UI가 읽는 `ab_result.winner`** 경로.

   **실제 분기 경로**(테스트로 재현할 것): `_rule_tiebreak`가 1–1 스플릿(A가 sync에서 이기고 B가 variance에서 이김)이면 `"tie"`를 반환한다 → `_pairwise_to_dict`가 `majority_winner="tie"`로 넘기고 → `determine_winner` step 2가 통과시켜 step 3이 실행되고 → lexicographic 방식은 **최우선 지표에서 이긴 A를 승자로 반환**한다. 즉 `EvaluationResult.winner == "tie"`인데 `ab_result.winner == "A"`로 저장된다(현존 잠재 결함). 부수적으로 epsilon(`<` vs `> 0.01`)과 스케일도 다르다.

   새 축을 양쪽에 각각 추가하면 이 분기가 커지므로, **하나의 순수 함수로 통합**한다. 통합 후 `_rule_tiebreak`의 집계는 점수 합산 → **lexicographic으로 바뀐다** — 이는 의도된 동작 변경이며(단일 정의를 갖는 대가), 기존 테스트 `test_rule_tiebreak_prefers_lower_error`(line 326)는 이에 맞춰 갱신하고 1–1 스플릿 케이스를 새로 고정한다:
   - 신규 `_rule_tiebreak_from_dicts(a: dict, b: dict) -> str`(또는 동등한 단일 진입점) — `_rule_metrics_to_dict()` 산출 형태(즉 `ab_result.rule_based_scores`의 형태)를 입력으로 받는 **테이블 주도** lexicographic 체인.
   - `_rule_tiebreak(metrics_a, metrics_b)`는 `_rule_metrics_to_dict()`로 변환해 그 함수에 위임하는 얇은 래퍼로 축소(호출부 무변경).
   - `determine_winner` step 3 전체(현재 3a/3b/3c 하드코딩 블록 3개)를 동일 호출로 교체.
   - 체인은 `(key, lower_is_better)` 튜플 리스트 + 루프로 표현한다 — 하드코딩 블록 6개보다 짧다. epsilon은 `> 0.01`(determine_winner 쪽)로 통일. `_rule_tiebreak`가 pct 스케일을, dict가 비율 스케일(÷100)을 쓰지만 **순서 관계는 동일**하므로 dict 형태로 통일하는 것은 승자 결과를 바꾸지 않는다(epsilon 통일분 제외 — 이는 의도된 변경이며 독스트링에 기록).

4. **tiebreak 체인 순서 — 11.4가 기록한 왜곡을 이 스토리가 닫는다**: 통합된 체인의 순서를 아래로 확정한다.

   | 순서 | 지표 | 방향 | 비고 |
   |---|---|---|---|
   | 1 | `scene_count_match_rate` | 높을수록 좋음 | **쌍 대칭이라 절대 발동하지 않는다**(A와 B가 항상 동일 값 — eval_service.py:286). 하위 호환을 위해 유지하되 "never fires" 주석 필수 |
   | 2 | `cut_alignment_error` | 낮을수록 좋음 | 신규 승격(AC2). 의미 반전이 없는 유일한 타이밍 지표 |
   | 3 | `motion_repeat_ratio` | 낮을수록 좋음 | 신규(AC1) |
   | 4 | `motion_archetype_coverage` | 높을수록 좋음 | 신규(AC1) |
   | 5 | `subtitle_sync_error` | 낮을수록 좋음 | **강등**(기존 2순위 → 최하위권) |
   | 6 | `audio_duration_variance` | 낮을수록 좋음 | 기존 |

   `subtitle_sync_error` 강등 사유: 11.4가 의미를 반전시켰고(provisional=gap-free 균등분할이라 항상 ~0 → 진짜 WhisperX timings는 단어 간 침묵이 있어 nonzero가 정상), 그 결과 "lower=better"가 **폴백된(=열화된) 런을 약하게 선호**한다. 11.4는 이 왜곡을 수용하고 `"redesign lands with the eval-gate unfreeze"`로 기록했으나, 반전되지 않은 지표(`cut_alignment_error`)를 그보다 앞에 두는 것 자체가 그 재설계이므로 이 스토리에서 닫는다. eval_service.py:220-236 독스트링의 왜곡 경고를 **삭제하지 말고** "13.2에서 우선순위 강등으로 완화 — 제거는 아님"으로 갱신할 것.

5. **하위 호환 — 과거 `ab_result` 행이 KeyError로 죽지 않게**: `determine_winner`는 현재 `rule_based_scores["A"]["subtitle_sync_error"]`처럼 **직접 인덱싱**한다. 이 스토리 이전에 저장된 `ab_result` 행에는 신규 키(및 11.4 이전 행은 `cut_alignment_error`도)가 없으므로, 통합 체인은 **모든 키를 `.get(key, default)`로 읽어야** 한다. default는 방향에 따라 tiebreak에 영향을 주지 않는 중립값을 쓸 것 — 즉 **양쪽 모두 키가 없으면 그 단계는 자동으로 동점 처리되어 다음 단계로 넘어간다**(어느 한쪽에만 값이 있는 상황은 pair가 같은 코드로 계산되므로 발생하지 않지만, 방어적으로 동일 default를 쓰면 자연히 성립). `determine_winner`는 순수 공개 함수이고 저장된 행 재평가에 쓰일 수 있으므로 이 계약을 테스트로 고정한다(신규 키가 전혀 없는 dict 입력 → 예외 없이 tie 또는 기존 지표로 판정).

6. **배선 5곳 — 하나라도 빠지면 축이 조용히 사라진다**: 신규 메트릭 2종은 아래 전부에 배선한다. 각 지점은 실제로 서로를 커버하지 않는다.
   - `RuleBasedMetrics` dataclass 필드 추가(eval_service.py:60). **`_compute_rule_metrics`가 위치 인자로 생성**하고 있으므로(eval_service.py:288-293) 필드 순서와 인자 순서를 함께 맞출 것 — 여기서 어긋나면 값이 조용히 뒤바뀐다. 이 스토리에서 키워드 인자로 전환하는 편이 안전하다(ponytail: 4개 필드가 6개가 되는 시점에 위치 생성은 이미 위험).
   - `_compute_rule_metrics()` — 두 런 각각에 대해 계산. 모션 메트릭은 `min_shot_clip_sec` 같은 Settings 입력이 필요 없다(순수 state 소비).
   - `_rule_metrics_to_dict()`(eval_service.py:696) — 두 키 추가. 이것이 `ab_result.rule_based_scores`의 스키마이자 AC3 tiebreak 체인의 입력 형태다.
   - `store_evaluation_results()`의 Langfuse NUMERIC 메트릭 튜플(eval_service.py:669-670) — 두 키 추가. `score_id`가 `f"{variant_run_id}-{metric}_{variant}"`로 결정론적 idempotency 키이므로 별도 처리 불필요.
   - 프론트엔드(AC8).

7. **`AXES`에 넣지 말 것 — 명시적 금지**: 신규 메트릭은 **rule metric이며 LLM judge 축이 아니다.** `AXES = ("atmosphere", "narrative_coherence", "article_fidelity")`(eval_service.py:37)에 추가하면 ① `_score_run`/`_judge_axis`가 존재하지 않는 축으로 LLM judge를 호출하고, ② `AxisScores` 필드/`below_floor()`/`QUALITY_FLOOR` 2.0 스케일(1–5)과 0–1 스케일이 섞이고, ③ `scripts/eval_prompts.py`의 `compare()`(line 676-681)가 AXES 델타로 승격 게이트를 판정하므로 **게이트 의미가 조용히 바뀐다**. 세 축은 그대로 유지한다.

8. **골든셋 리포트에 모션 메트릭 노출 — report-only, 게이트 무변경**: `scripts/eval_prompts.py`의 `_rule_metrics(scenes)`(line 289)에 `motion_archetype_coverage`/`motion_repeat_ratio`를 추가한다. `eval_service`의 순수 함수를 **재사용**할 것(중복 구현 금지 — `_rule_metrics`가 dict 씬을 받고 `eval_service` 함수도 TypedDict=dict를 받으므로 그대로 호출 가능).
   - **`cut_alignment_error`는 추가하지 않는다** — 골든셋은 scenario 스테이지만 실행해 `word_timings`/`audio_duration`이 없고, 그 상태에서 `_cut_alignment_error`는 항상 0.0을 반환해 무의미한 열을 만든다. 이 제외 사유를 코드 주석에 남길 것.
   - 게이트 영향 없음이 **확인됨**: `compare()`는 `AXES` + `total`만으로 verdict를 정하고 `_to_item_result`(line 388)가 나머지를 `rule_metrics`로 자동 수집하므로, 추가는 리포트 열 2개 증가에 그친다. 이 스토리에서 게이트 로직을 건드리지 말 것 — 시각 축을 **게이트에 포함**하는 것은 Story 13.4의 범위다.

9. **프론트엔드 `ab_result` 계약 정정 — 축을 추가해도 안 보이면 이 스토리는 무효**: 현재 프론트엔드와 백엔드의 스키마가 어긋나 A/B 비교 화면의 점수 테이블이 실데이터에서 전부 `—`로 렌더된다. 백엔드가 저장하는 형태(`_rule_metrics_to_dict`/`_axis_scores_to_dict` + `store_evaluation_results`의 `ab_result` 조립)가 authoritative이므로 프론트를 그쪽에 맞춘다.
   - `frontend/src/lib/types.ts`의 `AbResult`: `llm_scores` → `axis_scores`, `rule_scores` → `rule_based_scores`, rule 키를 실제 이름(`scene_count_match_rate`, `subtitle_sync_error`, `audio_duration_variance`, `cut_alignment_error`, + 신규 2종)으로 정정.
   - `frontend/src/pages/RunAbComparisonPage.tsx`의 `RULE_METRICS` 상수(line 28)와 `ScoreTable` 호출부(line 217 `result?.rule_scores?.[variant]`, LLM 축 호출부도 동일 확인)를 정정된 키로 갱신.
   - `RunAbComparisonPage.test.tsx`의 픽스처(line 23-32)가 **프론트 자체 가정 형태를 쓰기 때문에 이 불일치를 마스킹하고 있었다** — 픽스처를 백엔드 실제 출력 형태로 교체하고, 갱신 사유를 테스트 주석에 기록(7.5 교훈). 이 픽스처가 실제 스키마를 반영한다는 사실 자체가 회귀 가드다.
   - `formatScore` 표시 형식은 건드리지 말 것(0–1 비율과 초 단위가 섞이지만 기존 지표도 이미 그렇다 — 단위 표기 개선은 이 스토리 범위 밖).

10. **libcom composite quality score는 이 스토리에서 구현하지 않는다 — 확인된 제외**: epics 원문이 `"8.16이 도입 시 캘리브레이션한 임계값 재사용 — 8.16 미착수 시 이 스토리는 나머지 축만"`으로 조건을 걸었고, **확인 결과 8-16은 `backlog`이고 `libcom`은 `pyproject.toml`/`src/`/`scripts/` 어디에도 없다**(grep 0건). 따라서:
   - libcom 축을 위한 스텁·플래그·설정 필드·빈 메서드를 **만들지 말 것**(ponytail: 미래를 위한 스캐폴딩 금지). 8-16이 임계값을 들고 오면 그때 축 하나를 추가하는 것이 정확히 이 스토리가 만든 배선(AC6의 5개 지점) 위에서 한 번에 끝난다.
   - `ab_result` 스키마에 `composite_quality` 같은 예약 키를 넣지 말 것.
   - 제외 사유를 `eval_service` 모듈 독스트링 또는 rule metric 섹션 주석 한 줄로 기록해 다음 세션이 "누락"으로 오판하지 않게 한다.

11. **테스트 + 회귀 가드**:
   - 신규 순수 함수 단위 테스트: ① 5종 아키타입 전부 사용 → coverage 1.0 ② 단일 아키타입 → coverage 0.2 ③ `None`/레거시 자유 텍스트만 → coverage 0.0 + repeat_ratio가 `"unmapped"` 단일 버킷으로 1.0 ④ 씬 경계 인접 쌍이 실제로 카운트됨을 고정하는 케이스(씬1 마지막 샷과 씬2 첫 샷이 동일 아키타입 → ratio에 반영) ⑤ 샷 0개/1개 경계.
   - tiebreak 통합 테스트: ① `_rule_tiebreak`와 `determine_winner` step 3이 **동일 입력에 동일 승자**를 내는 것을 고정 — 특히 AC3이 지목한 **1–1 스플릿 입력**(A가 한 지표, B가 다른 지표에서 우세)을 반드시 포함할 것. 이 테스트가 이 스토리의 핵심 회귀 가드다 ② `cut_alignment_error`가 `subtitle_sync_error`를 이긴다(순서 고정) ③ 신규 키 없는 legacy dict → 예외 없음(AC5) ④ `scene_count_match_rate`가 대칭이라 발동하지 않음 ⑤ 전 지표 동일 → `"tie"`.
   - 기존 테스트 중 tiebreak epsilon/순서에 의존하는 것(`test_rule_tiebreak_prefers_lower_error`:326, `test_determine_winner_rule_tiebreak_scene_count`:697 및 인접 `determine_winner` 테스트군 640-720)은 **의도된 동작 변경이므로 갱신 필수** — 갱신 사유를 테스트 주석에 남길 것.
   - `test_cut_alignment_error_in_rule_metrics_dict`(line 150)는 신규 키 2종을 포함하도록 확장.
   - 백엔드 전체 스위트 green: `PYTHONPATH=$PWD/src uv run pytest tests/` — **기준선 1569 collected**(baseline_commit 시점 실측). 신규 테스트만 순증해야 하고 기존 실패는 0.
   - 프론트엔드: `cd frontend && npm test` green.
   - `uv run ruff check src/ scripts/ tests/` clean.

12. **실데이터 검증(비-GPU, 기존 산출물 재사용)**: 완료된 A/B 페어가 DB에 있으면 `evaluate_ab`를 실행하지 않고(LLM 비용·비결정성 회피) **체크포인트에서 state를 읽어 신규 순수 함수만 직접 호출**해 실제 런의 coverage/repeat_ratio를 산출하고 Debug Log에 수치를 기록한다. 최소 요구: ① 실제 런의 값이 0.0/1.0 같은 퇴화값이 아님(= 메트릭이 실제로 변별력이 있음) ② `camera_movement`가 archetype으로 채워져 있음을 확인(11.2 배선이 살아 있는지 — 이 확인 자체가 Epic 13의 "조용한 성공 위장" 방어다). A/B 페어가 없으면 단일 완료 런의 체크포인트로 수행하고 그 사실을 기록. **GPU·ComfyUI·재렌더 불필요** — epics 원문 "채점 입력은 기존 런 산출물이라 GPU 재실행 불필요" 그대로.

## Tasks / Subtasks

- [ ] Task 1: 모션 메트릭 순수 함수 (AC: 1, 11)
  - [ ] `eval_service.py`에 `_motion_archetype_coverage(scenes)` / `_motion_repeat_ratio(scenes)` 추가 — `CAMERA_ARCHETYPES`를 `domain.state`에서 import, `video.py` import 금지
  - [ ] 정규화 키 헬퍼(archetype 멤버면 그 값, 아니면 `"unmapped"`) — 두 함수가 공유
  - [ ] 독스트링에 "씬 경계 포함은 의도적이며 nonzero가 11.2 위반이 아님" 문장 명시
  - [ ] 단위 테스트 5케이스(AC11) + 씬 경계 카운트 고정 테스트
- [ ] Task 2: tiebreak 단일화 + 순서 확정 (AC: 2, 3, 4, 5)
  - [ ] `(key, lower_is_better)` 테이블 + 루프로 `_rule_tiebreak_from_dicts` 신설, 모든 키 `.get(key, default)` 읽기
  - [ ] `_rule_tiebreak`를 `_rule_metrics_to_dict` 변환 후 위임하는 래퍼로 축소
  - [ ] `determine_winner` step 3(3a/3b/3c 블록)을 동일 호출로 교체 — step 1(quality floor)/step 2(pairwise majority)는 무변경
  - [ ] `_cut_alignment_error` 독스트링의 `"never a determine_winner tiebreak input"` 삭제 + 승격 사유 기록
  - [ ] `_avg_subtitle_sync_error` 독스트링(220-236)의 왜곡 경고를 "13.2에서 우선순위 강등으로 완화" 로 갱신
  - [ ] 동등성 테스트(`_rule_tiebreak` ≡ `determine_winner` step 3) + legacy dict 무예외 테스트 + 기존 tiebreak 테스트군 갱신
- [ ] Task 3: 배선 5곳 (AC: 6, 7)
  - [ ] `RuleBasedMetrics` 필드 2개 추가 + `_compute_rule_metrics`를 키워드 인자 생성으로 전환
  - [ ] `_rule_metrics_to_dict` 키 2개 추가
  - [ ] `store_evaluation_results` Langfuse 메트릭 튜플에 키 2개 추가
  - [ ] `AXES` 무변경 확인(회귀 가드로 assert 하나 두어도 좋음)
  - [ ] `test_cut_alignment_error_in_rule_metrics_dict` 확장
- [ ] Task 4: 골든셋 리포트 노출 (AC: 8)
  - [ ] `scripts/eval_prompts.py::_rule_metrics`에서 `eval_service`의 순수 함수 재사용해 모션 메트릭 2종 추가
  - [ ] `cut_alignment_error` 제외 사유 주석
  - [ ] `compare()`/게이트 로직 무변경 확인
- [ ] Task 5: 프론트엔드 계약 정정 (AC: 9)
  - [ ] `types.ts` `AbResult` 키 정정(`axis_scores`/`rule_based_scores` + 실제 metric 이름 + 신규 2종)
  - [ ] `RunAbComparisonPage.tsx` `RULE_METRICS` / `ScoreTable` 호출부 갱신
  - [ ] `RunAbComparisonPage.test.tsx` 픽스처를 백엔드 실제 출력 형태로 교체 + 사유 주석
  - [ ] `npm test` green
- [ ] Task 6: libcom 제외 기록 (AC: 10)
  - [ ] 모듈 주석 한 줄로 8-16 의존 축 제외 사유 기록, 스텁/예약 키 생성 없음 확인
- [ ] Task 7: 검증 (AC: 11, 12)
  - [ ] `PYTHONPATH=$PWD/src uv run pytest tests/` — 1569 기준선 + 신규분, 실패 0
  - [ ] `uv run ruff check src/ scripts/ tests/` clean
  - [ ] 실데이터: 완료 런 체크포인트에서 신규 함수 직접 호출 → 수치 + `camera_movement` 채움 확인, Debug Log 기록

## Dev Notes

### 이 스토리가 고치는 것의 정확한 형태

`eval_service`의 judge 입력은 `_artifact_text()`(eval_service.py:204)가 만드는 **씬 나레이션 문자열 연결**이다. 독스트링이 이미 이렇게 인정한다: *"A text LLM can't watch the video or hear the audio, so narration is the faithful stand-in"* + `ponytail: narration-only judge input`. 즉 3축 점수는 렌더 품질에 대해 **구조적으로 무지**하며 프롬프트로 고칠 수 있는 문제가 아니다. 13.2는 LLM을 멀티모달로 바꾸는 대신 **규칙/도구 기반 축**을 추가한다 — 판정에 LLM이 필요 없는 부분은 코드로(12.3과 동일 원칙).

### 데이터 가용성 (GPU 불필요의 근거)

| 축 | 입력 | 출처 | 재렌더 필요 |
|---|---|---|---|
| `motion_archetype_coverage` | `shots[*].camera_movement` | 체크포인트 state (11.2가 채움) | 없음 |
| `motion_repeat_ratio` | 동일 | 동일 | 없음 |
| `cut_alignment_error` | `word_timings`, `narration`, `audio_duration`, `shots` | 체크포인트 state (11.4가 정렬본을 write-back) | 없음 (`plan_shot_clips` 재계산) |
| ~~libcom composite~~ | 합성 프레임 + 8.16 임계값 | **없음 — 8-16 backlog** | AC10에 따라 제외 |

`_load_state()`(eval_service.py:382)가 LangGraph 체크포인트에서 `channel_values`를 그대로 읽으므로 세 축 모두 이미 손에 있다.

### 반드시 읽을 기존 코드 (UPDATE 대상)

- **`src/yt_flow/services/eval_service.py`** — 이 스토리의 주 무대. 현재 상태: LLM 3축(`_score_run`) + rule 4종(`_compute_rule_metrics`) + pairwise 위치편향 완화(`_pairwise_compare`) + **두 개의 tiebreak 경로**(AC3) + Langfuse 점수 ingestion. 보존해야 할 것: quality floor(2.0, 1–5 스케일) 단축로, pairwise A→B/B→A 라벨 반전 로직, `@observe` 스팬 구조, Langfuse 실패 비치명(AD-10), `_load_state`/`_validate_pair`의 사전 검증 순서(AC7 — 어떤 LLM 호출보다 먼저).
- **`src/yt_flow/pipeline/nodes/scenario_chain.py:72-204`** — `CAMERA_PREFERENCES`(mood→아키타입 선호 순서), `_resolve_camera_movement`(무효값은 무드 기본값으로 조용히 폴백 — 그래서 `camera_movement`가 archetype이 아닌 경우가 레거시 런에만 존재), `_enforce_camera_variety`(씬 내부 인접 금지, 씬 경계 의도적 제외). **이 파일은 수정하지 않는다** — 읽는 이유는 메트릭의 기대 분포와 씬 경계 규칙의 근거를 알기 위함이다.
- **`src/yt_flow/domain/state.py:82-113`** — `CAMERA_ARCHETYPES`, `ShotData.camera_movement`(`str | None`, 레거시 자유 텍스트 가능성이 타입 주석에 명시됨), `SceneState.shots`.
- **`src/yt_flow/pipeline/nodes/video.py:196-263`** — `select_effect`. **읽고 나서 쓰지 말 것**: `push_in`/`shake` → 둘 다 `"in-center"`, `locked`/`static` → 1.0→1.005 near-zero drift, 미지값 → `_DIRECTION_POOL[scene_index % n]`. 이 붕괴 때문에 아키타입 계층에서 측정해야 한다(AC1).
- **`scripts/eval_prompts.py:289-320, 612-706`** — `_rule_metrics`(report-only) 와 `compare()`(AXES+total로만 verdict). AC8의 "게이트 무변경"이 성립하는 근거.
- **`frontend/src/lib/types.ts:12-19` + `frontend/src/pages/RunAbComparisonPage.tsx:26-28, 217, 234-256`** — AC9의 스키마 불일치 현장.

### 안티패턴 — 하지 말아야 할 것

1. **`AXES`에 rule metric 추가** → LLM judge가 없는 축을 호출하고 승격 게이트 의미가 바뀐다(AC7).
2. **`video.py`에서 `select_effect`/`EffectSpec`를 import해 모션 측정** → 아키타입 다양성이 방향 다양성으로 붕괴(AC1). 부수적으로 ffmpeg 계층을 서비스로 끌어온다.
3. **모션 메트릭을 새로 구현하며 `_enforce_camera_variety`를 "고치기"** → 11.2 계약은 옳다. nonzero repeat_ratio는 위반이 아니다(AC1).
4. **tiebreak를 두 곳에 각각 추가** → 반환값/저장값 불일치가 커진다. 통합이 정답이며 더 짧다(AC3).
5. **`determine_winner`에서 신규 키를 직접 인덱싱** → 과거 `ab_result` 행 재평가 시 KeyError(AC5).
6. **libcom 스텁/플래그/예약 키 생성** → 8-16 미착수 상태의 죽은 코드(AC10, ponytail).
7. **`RuleBasedMetrics`를 위치 인자로 계속 생성** → 필드 6개에서 값이 조용히 뒤바뀐다(AC6).
8. **`_artifact_text`를 멀티모달로 확장하거나 judge 프롬프트 수정** → 이 스토리 범위 밖. 프롬프트 변경은 `docs/PROMPT_POLICY.md` 절차를 타야 하고, 13.2는 **프롬프트를 전혀 건드리지 않는다**(신규 코드는 전부 결정론적 순수 함수).

### 프롬프트 정책 — 해당 없음

이 스토리는 Langfuse 프롬프트를 만들거나 수정하지 않는다. `DEV MODE`(2026-08-03, 품질 게이팅 OFF) 하에서도 프롬프트 변경이 없으므로 `migrate_prompts.py` 실행이나 승격 절차가 발생하지 않는다. `scripts/eval_prompts.py`를 수정하지만 **게이트 로직이 아니라 리포트 열**이고, `YTFLOW_ALLOW_AB_GATE` 가드(6-12)와 `CLAUDECODE`/`AI_AGENT` 무조건 차단 가드(8-12)는 그대로 둔다 — **AI 세션이 A/B 게이트를 실행하려 시도하지 말 것**.

### Previous Story Intelligence

Epic 13의 첫 스토리 파일이다(13-1은 아직 `backlog`, 파일 없음). sprint-status의 권고 착수 순서는 `13-1 → 12-2 → 12-1 → 12-3 → 12-4`이므로 **13-2는 순서상 앞당겨진 것**이지만, 13-1(조용한 강등 경고 레코드)과 13-2(평가 축)는 코드 접점이 없다 — 13-1은 런타임 state/게이트 페이로드 계층, 13-2는 평가 서비스 계층. 병렬 안전.

의존 스토리에서 상속하는 자산과 교훈:

- **11-2 (done)** — `camera_movement` 하드코딩 `None` 제거 → 닫힌 enum + 무드 매핑 + 인접 금지 validator. 13-2 모션 축의 데이터 소스 전부. `visual_breakdown` candidate가 2026-08-03에 production 승격됨(커밋 344fd5f) → **최근 런에는 archetype이 실제로 채워져 있어야 한다**(AC12가 이것을 확인한다).
- **11-4 (done)** — `cut_alignment_error`를 추가하고 tiebreak 진입을 명시적으로 차단, `avg_subtitle_sync_error` 의미 반전을 문서화하며 재설계를 "eval 게이트 unfreeze 시점"으로 이월. 13-2 AC2/AC4가 그 이월분을 닫는다. 11-4 라이브 게이트에서 관측된 최대 편차 3.8s는 이 메트릭이 퇴화값이 아님을 시사한다.
- **6-13 (done)** — 골든셋 eval 캐싱. `_cache_key = sha256(rendered\0model\0max_tokens)`. 13-2는 `_rule_metrics`만 건드리고 캐시 키는 LLM 호출 단위이므로 **캐시 무효화가 발생하지 않는다**(rule metric은 캐시 대상이 아님).
- **6-8 (done)** — judge 멀티샘플 + 샘플 단위 bounded retry. `_judge_axis`/`_judge_sample` 구조를 건드리지 말 것.
- **8-12 교훈** — AI 세션의 A/B 게이트 우회 시도가 있었고 그 결과 `CLAUDECODE`/`AI_AGENT` 무조건 차단 가드가 추가됐다. 반복하지 말 것.
- **5-12/5-13 교훈** — "코드는 정상, 결과물만 없음"이 이 프로젝트의 반복 사고 패턴(Epic 13의 존재 이유). AC12의 실데이터 확인이 이 스토리 자체가 같은 함정에 빠지는 것을 막는 장치다 — 메트릭 함수가 테스트에서만 통과하고 실런에서 항상 0.0을 내면 축을 추가한 의미가 없다.

### Git Intelligence

`baseline_commit = 7141707`(HEAD, 2026-08-03). 최근 커밋 성격: `13a47ed`/`7141707`은 Epic 12/13 신설·스펙 변경으로 **문서만** 변경, `344fd5f`는 프롬프트 승격 기록, `cc82403`은 DEV MODE 전환. 즉 **baseline 시점에 `eval_service.py`를 건드린 미커밋/최근 코드 변경은 없다** — 마지막 실질 변경은 11-4(`cut_alignment_error` 추가)와 6-13(캐싱)이다. `git status`상 미커밋은 `.serena/`(untracked, 무관)뿐.

커밋 메시지 관례: `fix(story-N.M): 한국어 요약` / `chore(story-N.M): ...` / `docs(epics): ...`.

### Testing Standards

- pytest, `asyncio_mode = "auto"`(`pyproject.toml:39`) — async 테스트에 `@pytest.mark.asyncio` 불필요.
- 실행: `PYTHONPATH=$PWD/src uv run pytest tests/`. 기준선 **1569 collected**.
- `tests/services/test_eval_service.py`(875줄)의 확립된 패턴을 따를 것: `FakeSettings` dataclass, `_Tmpl` 프롬프트 더블, `_wire(monkeypatch, ...)` 헬퍼, `_memdb()` 인메모리 SQLite 픽스처, `_no_trace` 픽스처(Langfuse 무력화), `_cut_shot`/`_cut_scene`(line 101-111) 씬 빌더. **신규 순수 함수 테스트는 이 빌더를 재사용**하고 새 픽스처 계층을 만들지 말 것.
- `tests/services/fixtures/eval_pipeline_states.py`(63줄)에 상태 픽스처가 있다 — 모션 케이스가 이미 표현 가능한지 먼저 확인하고, 필요한 최소분만 추가.
- ruff: `target-version = py312`, `src = ["src", "tests"]`. 기존 코드의 `# noqa: BLE001`(관측성 non-fatal) 관례 유지.
- 프론트엔드: vitest (`cd frontend && npm test`).

### Project Structure Notes

- 신규 파일 없음. 수정 대상: `src/yt_flow/services/eval_service.py`, `scripts/eval_prompts.py`, `tests/services/test_eval_service.py`, `frontend/src/lib/types.ts`, `frontend/src/pages/RunAbComparisonPage.tsx`, `frontend/src/pages/RunAbComparisonPage.test.tsx`. (선택) `tests/services/fixtures/eval_pipeline_states.py`.
- **신규 서비스/모듈 분리 금지** — epics가 13.1에 대해 명시한 "신규 서비스 분리 없음" 원칙이 13.2에도 동일하게 적용된다. 모션 메트릭은 `eval_service.py`의 기존 "Rule-based structural metrics" 섹션(line 214-294) 안에 들어간다.
- `services/` → `pipeline/nodes/` import는 이미 선례가 있다(`eval_service.py:32`의 `plan_shot_clips`, `run_service`의 `image_node`) — 단 AC1에 따라 `video.py`는 예외로 금지.
- `domain/state.py`의 `CAMERA_ARCHETYPES` 배치 사유(생산자 `scenario_chain`과 소비자 `video`가 서로 import하지 않으므로 공용 도메인 모듈에 둔다)는 `eval_service`가 세 번째 소비자가 되어도 그대로 유효하다.

### 아키텍처 준수

- **AD-2 / AD-7** — 평가 입력은 LangGraph 체크포인트가 정본(`runs` 테이블은 status/`ab_pair_id` 검증용). 신규 메트릭도 체크포인트 state에서만 읽는다.
- **AD-6** — `ab_result`는 A/B 두 런 행에 동일하게 기록. `store_evaluation_results`의 기존 루프 유지.
- **AD-10** — Langfuse 실패는 비치명. 신규 score ingestion도 기존 `try/except` 블록 **안**에 두어야 한다(밖에 두면 관측성 실패가 평가를 죽인다).
- **AD-4** — state 객체 in-place 변형 금지. 신규 메트릭 함수는 읽기 전용 순수 함수.
- **Consistency Conventions** — `snake_case` 모듈/함수, 설정은 `config.py` Pydantic `BaseSettings`(이 스토리는 신규 설정 필드가 필요 없다 — 임계값을 만들지 말 것, 메트릭은 기록·비교용이며 절대 기준선이 없다).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 13.2] — 축 3종 정의, 8.16 조건부 제외, GPU 불필요 근거
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 13] — "조용한 성공 위장" 문제 정의(8.17/8.15/11.4 사례)
- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.2] — 카메라 아키타입 enum + 씬 경계 미검사 사유
- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.4] — `cut_alignment_error` rule metric 도입 의도
- [Source: _bmad-output/planning-artifacts/epics.md#Story 13.4] — 시각 축의 **게이트 포함**은 13.4 범위(이 스토리 아님)
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10] — 관측성 실패 비치명
- [Source: src/yt_flow/services/eval_service.py:37, 60-66, 204-294, 317-333, 531-586, 669-703] — 수정 지점 전체
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:72-204] — `CAMERA_PREFERENCES`, variety validator
- [Source: src/yt_flow/domain/state.py:82-113] — `CAMERA_ARCHETYPES`, `ShotData`, `SceneState`
- [Source: src/yt_flow/pipeline/nodes/video.py:209-263] — `select_effect` 아키타입→방향 붕괴
- [Source: scripts/eval_prompts.py:289-297, 612-706] — 골든셋 rule metric, AXES-only 게이트
- [Source: frontend/src/lib/types.ts:12-19] — `AbResult` 스키마 불일치
- [Source: docs/PROMPT_POLICY.md] — DEV MODE 배너(이 스토리는 프롬프트 무변경이라 해당 없음)
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml:214-219] — Epic 13 상태, 8-16 backlog 확인

## Dev Agent Record

### Agent Model Used

_TBD by dev agent_

### Debug Log References

### Completion Notes List

### File List
