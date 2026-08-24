---
title: 'Story 14.5: 나레이션 ↔ 배경 정합 — 생성기를 바꾸는 첫 라운드 (사건이 슬롯에 못 앉는다)'
type: 'feature'
created: '2026-08-22'
baseline_revision: '7485e57'
final_revision: ''  # uncommitted
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/PROMPT_POLICY.md'
  - '{project-root}/_bmad-output/planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-4b-live-validation/README.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-13-2-visual-eval-axes.md'
warnings: []
---

<intent-contract>

## Intent

**Problem:** ⑥의 살아 있는 결함은 `visible_event`다 — 프롬프트가 장소·무드·조명·질감을 세우고 **이 문장에서 무슨 일이 일어났는지의 보이는 흔적을 안 담는다**. 10.4b가 이것을 후속으로 넘겼고(README §4b), 세 라운드(10.4 / 10.4b / 13.2)가 전부 **계측기**에 쓰였으며 **생성기를 바꾼 라운드는 0회**다(research §0). 개입 지점 선택은 14.0 §4-3이 닫았다: 샘플러 내부 개입(Attend-and-Excite / Patcher)은 커스텀 노드 신설이 필요하고 설치된 10종·코어 어디에도 없으므로(2026-08-22 라이브 재확인: `custom_nodes` 실물 10종 = `env-snapshot.json`, 코어 `f350a842`, 훅만 `model_patcher.py:442/445/457`), **프롬프트 재작성 층**으로 간다. §3이 그 분기에 붙였던 "Patcher ①단계 입력을 13.2의 DSG가 공짜로 준다"는 논거는 **철회됐다** — §4-5가 그 DSG를 뒤집힌 축으로 실측했다(`state` ρ=−0.174, 판독불가 0.6250 vs 판독가능 0.3895).

두 번째 문제는 기준선 자체다. **84.9%(56/66)는 오늘의 생성기 숫자가 아니다.** 그 프롬프트들은 run `8a9a288b`의 시나리오(2026-08-07 작성)이고, `visual_breakdown.md`는 그 뒤 **2026-08-10에 10.2가 편집**했다(`9d4ec43`, production v14 시딩). 10.4b의 커밋 메시지는 84.9%를 *"현행 프롬프트에서 실측한"* 기준선이라고 적었지만 같은 메시지의 타임라인 절이 그것을 반증한다 — 10.4b 자신의 후보 편집은 `7744af1`로 바이트 동일 되돌림됐으므로, **현행 v14 생성기의 `visible_event`는 측정된 적이 없다.** run `4b35c0ed`(43샷, 2026-08-17)가 v14가 쓴 첫 런이다.

**가설(주장이 아니라 시험 대상)**: 결함은 프롬프트 조립이 아니라 **슬롯 배치**에 있다. `visual_breakdown.md:84`의 슬롯 3은 *"Freeze the most dramatic microsecond of the environment or aftermath, **not a character's pose**"* 인데, ① **이 문장의 사건**에 묶여 있지 않고("가장 극적인 순간"은 아무 순간이어도 된다), ② 문장의 사건 주체가 사람일 때 그 사건이 앉을 슬롯이 사라진다(`:7-21`의 배경 전용 규칙이 신체를 금지하므로 — 그 규칙은 옳고 건드리지 않는다), ③ 남은 슬롯 5·6·7(환경·조명·대기)이 단어 수를 지배하고 `:108`의 *"Show, don't tell"* 이 무드 쪽으로 더 민다. 사전 출력 셀프체크(`:326`)도 "환경 action/state가 **있는지**"만 묻고 그것이 이 문장의 사건인지는 묻지 않는다.

**Approach:** 편집 하나 + 게이트 하나. (1) 먼저 **재기준선** — 10.4b의 judge를 **수정 없이 import**해서 run `4b35c0ed`의 43 프롬프트에 돌린다(같은 모델·같은 judge 텍스트·`temperature 0`, 반복으로 judge 분산까지). 84.9%를 승계하지 않는다. (2) `visual_breakdown.md`의 슬롯 3과 셀프체크를 **이 문장의 사건의 보이는 귀결**로 묶는다 — 사건 주체가 사람이어도 신체가 아니라 **흔적·변위·잔여**를 요구하고, 배경 전용 규칙은 그대로 유지한다. (3) 같은 게이트로 구/신 페어 비교, 판정은 **런 단위 총합**(셀별 다수결 금지 — `gotcha_a-screening-gate-can-fail-on-its-own-threshold`). (4) 회귀는 양방향으로 본다: `present_subject` 100% 유지 + **14.7이 어제 출하한 리뷰어(`scenario/review` v11)가 신 프롬프트 산출물에 `descriptor_violation`을 새로 내지 않는가** — "사건을 그려라"가 신체를 다시 끌어오는 것이 이 편집의 고유 위험이다. (5) 통과하면 production 직승격(DEV MODE) + 런타임 이름으로 확인, **픽셀 판정은 이 스토리가 하지 않는다** — 다음 전체 완주(E2E iteration 5)의 블라인드 `readable`에 태운다.

## Boundaries & Constraints

**Always:**
- **judge는 복사하지 말고 import한다** — `10-4b-live-validation/check_prompt_compliance.py`의 `JUDGE_PROMPT` / `judge()` / `_parse()` / `summarize()`를 그대로 쓴다. 문구를 베끼면 84.9%와의 비교가 무효가 되고, 손으로 베낀 두 벌은 자기검증일 뿐이다(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`).
- **블라인드 by construction 유지**: 콜당 프롬프트 1개 + 문장 1개, 다리 라벨·형제 프롬프트·씬 순서 없음.
- 판정은 **런 단위 총합**과 **분모 동반 보고**(§4-5 ④). 셀당 n=1로 "고쳤다"를 선언하지 않는다(반복 ≥5, `gotcha_measure-densely-before-declaring-a-fix`).
- 측정치는 재산출 스크립트 + 표본 밴드(thread_id·checkpoint_id·샷 수·반복 수·모델·엔드포인트)와 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).
- 리포지토리 파일이 진실. 편집 후 `uv run python scripts/migrate_prompts.py --label production --source prompts`, 그리고 **런타임이 요청하는 이름**으로 확인: `scenario_chain.py:2712`의 `get_prompt("scenario/visual_breakdown")` → `GET {langfuse_host}/api/public/v2/prompts/scenario%2Fvisual_breakdown?label=production`. **슬래시는 퍼센트 인코딩**(생슬래시는 404이고 14.7이 그 오독을 기록했다). 시더가 출력한 이름으로 확인하지 않는다.
- **이 게이트는 텍스트 판정이고 프레임 판정이 아니다**를 리포트 본문에 명시한다. 14.0 §4-4의 대조군이 상한을 실측했다 — 같은 `image_prompt`를 시드만 올려 두 번 뽑았을 때 **5쌍 중 2쌍에서 시점 범주가 뒤집혔다**. 스크리닝 통과는 픽셀 보장이 아니다.

**Block If:**
- 재기준선이 완주하지 못한다 — 비전 키 부재, 또는 43행 중 **5행 초과**가 judge 오류. 부분 분포를 기준선으로 보고하지 않고 HALT.
- 후보가 런 단위 총합에서 재기준선을 못 넘긴다 → 문구를 **한 번** 고쳐 재측정하고, 두 번째도 실패하면 HALT. **같은 문구 재시도는 금지** — 10.4b가 이미 그것을 했고 −2.3pp(무변)였다.
- 후보에서 `present_subject`가 100% 아래로 내려가거나, 14.7 리뷰어가 신 프롬프트에 `descriptor_violation`을 낸다 → 편집 기각(신체가 돌아왔다는 뜻).

**Never:**
- `dsg_score`와 **그 하위 축**을 게이트 입력으로 쓰지 않는다(§4-5: 하위 축이 더 강하게 뒤집혀 있다). `match_score`(3-몰림 29/66)도 쓰지 않는다. **계측기 라운드 4를 만들지 않는다** — §4-5가 명시적으로 승인하지 않았다.
- **프롬프트에서 도출한 예/아니오 체크리스트를 시각 게이트로 쓰지 않는다.** 이 스토리의 게이트는 **프롬프트 텍스트**를 판정하고 이미지를 판정하지 않으므로 그 금지에 걸리지 않는다 — 리포트에서 두 층을 섞어 쓰면 그때 위반이다.
- **매핑에 렌더를 쓰지 않는다**(10.4: 손으로 짠 커버조차 `match`를 못 움직였다). 이 스토리에서 GPU 0, 전용 페어 렌더 A/B 없음.
- `prompts/scenario/visual_breakdown.md:7-21`의 배경 전용 CRITICAL RULE, `:328`의 셀프체크 항목, `:201`의 `negative_prompt` 계약을 **약화하지 않는다** — 10.1e·10.2·14.7이 세운 아키텍처다.
- `negative_prompt`에 절을 누적하지 않는다(`gotcha_negative-prompt-overstuffing`: 두 번 물린 축).
- `prompts/scenario/review.md` 편집 금지(14.7이 어제 v11로 출하했다 — 읽기만 한다). 프롬프트 파일 외 `src/` 변경은 이 스토리 범위 밖.
- **포즈 절반은 이 스토리가 아니다**(Jay 결정 2026-08-22): 나레이션 행위 ↔ 카드 포즈 정합은 §4-1의 "포즈를 자산 축으로 둔다"에 따라 **14.6** 소관이다. 현행 라이브러리는 10.8 비소급 상태이고 `cast_card_fallback` 4건이 자산 부재이므로, 14.6 없이는 측정만 되고 고칠 레버가 없다.
- 샘플러 내부 개입·신규 커스텀 노드·신규 모델 도입(§4-3, §4-1).
- 84.9%를 이 런의 기준선으로 인용하지 않는다.
- `--baseline`·`YTFLOW_ALLOW_AB_GATE`·A/B·골든셋 게이트 실행(DEV MODE에서 무의미 + AI 세션 금지).

## I/O & Edge-Case Matrix

생성기는 LLM이므로 아래는 **스크리닝으로 관측할 셀**이다(반복 ≥5, 판정은 런 단위 총합).

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| 재기준선 | run `4b35c0ed` 체크포인트의 43샷 `image_prompt` + 각 샷 문장 | 오늘의 `visible_event` 비율(분모 명기) + 실패 샷 id 목록. 84.9%와 **다를 수 있고 그것이 이 태스크의 요점** | judge 오류행은 데이터로 기록, 5행 초과면 HALT |
| 사건 주체가 사람인 문장 | 나레이션이 인물의 행위를 서술(예: 연구원이 문을 잠근다) | 신 프롬프트가 **흔적**을 담는다(잠긴 걸쇠·긁힌 자국·떨어진 카드키). 신체·얼굴·의복 서술 0 | `descriptor_violation` 나오면 편집 기각 |
| 사건 주체가 환경인 문장 | 이미 통과하던 aftermath 문장 | `visible_event` 유지 — 살아 있던 셀을 죽이지 않는다 | 하락 시 문구 1회 수정 |
| 사건 없는 문장 | `(정적)` 등 효과·전환 문장 | `image_prompt`가 빈 문자열 → 게이트 대상 아님(분모 제외, 제외 수 보고) | 분모 미보고 금지 |
| 부재를 주어로 삼는 문장 | *"아무것도 보이지 않습니다"* 계열 | `present_subject` **여전히 true** — 10.2가 이미 고쳤고 기준선 100%다 | 100% 미달 시 편집 기각 |
| 리뷰어 회귀 | 신 프롬프트 산출물 → `scenario/review` v11 | `descriptor_violation` **0건**(14.7이 세운 역방향 규칙이 신체 유입을 잡는다) | 1건이라도 나오면 기각 |

</intent-contract>

## Code Map

- `prompts/scenario/visual_breakdown.md:84` -- 슬롯 3 `**Action, pose, or state**`. **주 편집 지점.** "가장 극적인 순간"을 **이 문장의 사건의 보이는 귀결**로 묶고, 사건 주체가 사람일 때의 처방(신체 대신 흔적)을 한 줄로 넣는다.
- `prompts/scenario/visual_breakdown.md:326` -- 셀프체크의 8요소 항목. 현재 "환경 action/state가 있는지"만 묻는다 → **이 문장의 사건과 연결됐는지**를 묻는 항목으로 보강할 지점.
- `prompts/scenario/visual_breakdown.md:7-21` -- 배경 전용 CRITICAL RULE. **읽기 전용 정본.** 이 편집은 이 규칙 안에서 이뤄져야 하고 약화는 14.7의 출하를 되돌리는 것이다.
- `prompts/scenario/visual_breakdown.md:68-104` -- 8슬롯 정의. 슬롯 5·6·7이 단어 수를 지배하는 구조적 근거.
- `prompts/scenario/visual_breakdown.md:106-120` -- `**Show, don't tell the narration:**` 등 구성 원칙. 무드 쪽 편향의 2차 후보 — **먼저 슬롯 3만 건드리고**, 1차 스크리닝이 부족할 때만 여기로 확장한다(한 번에 두 곳을 바꾸면 귀속이 불가하다).
- `prompts/scenario/visual_breakdown.md:201`, `:328` -- `negative_prompt` 계약과 배경 전용 셀프체크. **읽기 전용.**
- `src/yt_flow/pipeline/nodes/scenario_chain.py:2633`, `:2712` -- `visual_breakdown_step`과 `get_prompt("scenario/visual_breakdown")`. 시딩 검증이 맞춰야 할 유일한 이름.
- `_bmad-output/implementation-artifacts/10-4b-live-validation/check_prompt_compliance.py:60-92`(`JUDGE_PROMPT`), `:112`(`judge`), `:94`(`_parse`), `:145`(`summarize`) -- **import 대상.** judge 텍스트는 이미 배경 전용 아키텍처를 알고 있다(*"Do NOT require the people to be shown … judge only whether the environment carries a consequence"*) — 그래서 이 결함은 judge의 오독이 아니라 생성기의 결함이다.
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py` -- `yt_flow.db` 체크포인트에서 run의 `scenes`를 읽는 선례(`load_scenes`). 역직렬화·thread 접두사 해석을 재사용한다.
- `_bmad-output/implementation-artifacts/14-7-prompt-screening/screen_review_prompt.py` -- 리뷰어를 실제로 돌리는 선례. 회귀 측(`descriptor_violation`)을 이 스크립트 형태로 재사용한다.
- `src/yt_flow/config.py:308` `stock_plate_substitution_enabled: bool = False` -- **전제**: 지금은 43/43이 자유생성이므로 `image_prompt` 편집이 전 샷에 닿는다. 14.1이 이 플래그를 켜면 `location_key` 보유 31/43은 `image_prompt`를 생성에 쓰지 않으므로 **이 편집의 도달 범위가 12/43으로 줄어든다** — 리포트에 명시하고 14.1에 인계한다.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/14-5-prompt-screening/screen_visible_event.py` -- 신규. run id를 인자로 받아 `yt_flow.db` 체크포인트에서 `scenes`를 읽고(14.0의 `load_scenes` 형태 재사용), 각 샷의 문장과 `image_prompt`를 10.4b의 `judge()`에 **import해서** 넘긴다. `--reps N`(기본 5), `--leg {baseline,candidate}`, 결과 JSON 캐시·재개, 헤더에 thread_id·checkpoint_id·샷 수·빈 프롬프트 제외 수·모델·엔드포인트를 찍는다. 출력은 **런 단위 총합 + 분모**이고 셀별 다수결 게이트를 만들지 않는다. 역직렬화 실패는 삼키지 않는다. GPU 0.
- [x] **재기준선 실행** — run `4b35c0ed`, `--leg baseline --reps 5`. 오늘의 `visible_event`/`present_subject`를 분모와 함께 기록하고, `visible_event=false` 샷 id를 나열한다. 84.9%와의 차이는 **정정으로 기록**한다(승계 금지).
- [x] `prompts/scenario/visual_breakdown.md:84` + `:326` -- 슬롯 3을 **이 문장의 사건의 보이는 귀결**로 묶는다: 사건 주체가 사람이든 환경이든 프레임에는 그 사건의 **흔적·변위·잔여**가 있어야 하고, 사람일 때는 신체·얼굴·의복이 아니라 그 사람이 남긴 것을 쓴다(배경 전용 규칙은 그대로). 셀프체크에 "이 문장의 사건이 프레임에서 보이는가" 항목을 추가한다. **한 곳만 바꾼다** — `:108`의 구성 원칙은 이번 라운드에서 손대지 않는다(귀속 가능성).
- [x] **후보 스크리닝** — 같은 43문장에 신 프롬프트로 `visual_breakdown_step`을 다시 돌려 `image_prompt`를 재생성하고, `--leg candidate --reps 5`로 동일 게이트에 넣는다. 구/신은 **페어**(같은 문장·같은 씬)로 비교한다. GPU 0.
- [x] **회귀 측** — `14-7-prompt-screening/screen_review_prompt.py` 형태로 신 프롬프트 산출물을 `scenario/review` v11에 통과시켜 `descriptor_violation` 발생 수를 센다. 0건이 아니면 편집 기각.
- [x] `_bmad-output/implementation-artifacts/14-5-prompt-screening/report.md` -- 신규. 표본 밴드, 재기준선 정정(84.9%가 왜 오늘의 숫자가 아닌지 + 타임라인 근거 `9d4ec43`/`7744af1`), 구/신 페어 표(분모 동반), 실패 샷 id의 구/신 대조, 회귀 측 결과, `stock_plate_substitution_enabled` 전제, **"텍스트 게이트는 픽셀 보장이 아니다"** 절(14.0 §4-4 리시드 대조군 2/5 인용). 반대 결과·판정불가 셀을 지우지 않는다.
- [x] 통과 시 `uv run python scripts/migrate_prompts.py --label production --source prompts` → `GET .../prompts/scenario%2Fvisual_breakdown?label=production`으로 신 문구 존재·구 문구 부재 확인. 버전 번호를 리포트에 적는다(직전 v14).
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- 프롬프트 텍스트 고정 2건: (1) 슬롯 3이 "이 문장의 사건" 요구를 담고 있음, (2) 배경 전용 규칙(`:7-21`)과 셀프체크 항목(`:328`)이 **여전히 존재**함(역방향 고정 — 이 편집이 14.7의 출하를 되돌리지 않았다는 증거). 파일 부재는 skip이 아니라 실패.
- [x] `_bmad-output/planning-artifacts/epics.md` Story 14.5 항목 + `sprint-status.yaml` 14-5 행 -- 결과로 갱신. 픽셀 판정이 **E2E iteration 5로 인계**됨을 명시하고, 포즈 절반이 14.6 소관임을 기록한다.

**Acceptance Criteria:**
- Given run `4b35c0ed`의 43샷, when 재기준선을 `--reps 5`로 돌리면, then 오늘의 `visible_event` 비율이 **분모와 함께** 기록되고 84.9%를 승계하지 않으며, judge 오류행이 5 이하다.
- Given 같은 43문장, when 구/신 프롬프트를 동일 게이트로 페어 비교하면, then `visible_event`가 **런 단위 총합에서 상승**한다(셀별 다수결이 아니라 총합 — 저빈도 셀에서 다수결은 노이즈로 뒤집힌다).
- Given 후보 스크리닝 결과, when `present_subject`를 보면, then **100% 유지**다 — 사건을 요구하면서 부재-주어 거동을 되살리지 않았다.
- Given 신 프롬프트 산출물, when `scenario/review` v11로 리뷰하면, then `descriptor_violation`이 **0건**이다 — "사건을 그려라"가 신체를 다시 끌어오지 않았다.
- Given `git diff prompts/`, when 확인하면, then `visual_breakdown.md`의 `:7-21`·`:201`·`:328`이 **변경되지 않았고** `negative_prompt`에 새 절이 추가되지 않았다.
- Given 시딩 후, when `scenario%2Fvisual_breakdown?label=production`을 조회하면, then 신 문구가 존재하고 버전이 v14보다 크다 — 시더 출력만으로 출하를 단정하지 않는다.
- Given `git diff --stat`, when 확인하면, then `src/` 변경이 0이다(프롬프트 + 테스트 + 산출물만).
- Given 이 스토리의 산출물 전체, when 확인하면, then **렌더 0장·GPU 0**이고 픽셀 판정 주장이 어디에도 없다.

## Spec Change Log

- 2026-08-22 초안. 14.0 §4-3 종결(프롬프트 재작성 층 선택) 직후 작성. Jay 결정 2건이 범위를 고정했다: **① 배경·사건 절반만**(포즈는 14.6), **② 판정은 렌더 전 텍스트 게이트 + 픽셀은 다음 E2E**(전용 페어 렌더 A/B 기각 — 10.4가 남긴 "매핑에 렌더를 더 쓰지 마라").

## Design Notes

**왜 슬롯 3인가.** judge의 `visible_event` 문구는 이미 "사람을 보여줄 필요 없다, 환경이 귀결을 담는지만 본다"고 명시한다. 즉 84.9%(→ 재측정 예정)의 실패는 judge가 배경 전용 아키텍처를 오해한 결과가 **아니고**, 생성기가 사건의 귀결을 요구받지 않는 결과다. 슬롯 3이 유일하게 "action/state"를 요구하는 자리인데 그 요구가 문장의 사건에 묶여 있지 않다.

**왜 한 곳만 바꾸나.** `:108`의 "Show, don't tell"도 같은 방향의 후보다. 두 곳을 함께 바꾸면 상승분의 귀속이 불가하고, 이 프로젝트는 성긴 표본으로 선언했다가 뒤집힌 전례가 있다. 1차 스크리닝이 부족하면 그때 확장한다 — 스크리닝 1회는 ~2분이고 GPU 0이다.

**이 스토리가 닫아도 남는 것.** 텍스트 게이트 통과는 픽셀 보장이 아니다(같은 프롬프트·다른 시드로 시점 2/5 뒤집힘, 14.0 §4-4). ⑥의 픽셀 판정은 E2E iteration 5의 블라인드 `readable`이고, 살아 있는 축은 그것 하나다(§4-5 ⑤).

## Review Findings

적대적 3층 리뷰(Blind Hunter / Edge Case Hunter / Acceptance Auditor) 결과 — 전량 반영.
**두 건이 이 스토리의 결론을 바꿨다.**

- [x] [Review][Patch] **shot-id가 프로덕션과 어긋나 §4 결론이 정확히 반대로 나왔다** — 재생성 다리를
  1-based(`S00101…`)로 매겨 0-based 출하 id(`S00100…`)와 직접 비교했다. 문장으로 조인하면 사건 담지
  실패 문장의 교집합은 **7/7**(적어 둔 값은 1/7). 스크립트를 프로덕션과 같은 0-based로 고치고, 저장된
  증거는 재작성하지 않은 채 리포트의 모든 다리 간 비교를 문장 조인으로 다시 계산했다.
- [x] [Review][Patch] **리뷰어 회귀를 2rep만 사고 그 위에 출하 결정을 올렸다** — 5rep 재측정에서
  `entity_in_prompt`가 5→0이 아니라 **3→8**, typed `descriptor_violation`은 **22→31**. 사전등록된
  기각 조건이 발동 → **편집 되돌림 + 재시딩(v16 = v14 텍스트)**.
- [x] [Review][Patch] AC가 이름 붙인 **풀링** `visible_event`가 구→신 **−2.81pp**인데 어느 산출물에도
  없었다 → 리포트·epics·sprint-status에 명시하고, 스크립트가 풀링 델타를 항상 출력하게 했다.
- [x] [Review][Patch] "실패 13샷 중 **8건**이 사건 없는 문장"은 분류기가 아니라 손 카운트였다(분류기는
  **6건**) → 정정, 두 건은 분류기의 알려진 이견으로 기재.
- [x] [Review][Patch] §6이 **rep 1에만** 기대고 있었다 — 문제의 문장은 구 프롬프트에서 이미 4/5 통과.
  "표현 불가 부류가 잔여를 지배한다" 철회, 5rep 전부 실패한 문장이 **0개**임을 근거로 재서술.
- [x] [Review][Patch] `descriptor_violation`을 자유텍스트 버킷으로 대리 측정했다 → 스키마 필드
  (`entry["type"]`)를 직접 세고, 판정을 상대(`new > old`)가 아니라 **절대(신 == 0)**로.
- [x] [Review][Patch] 스펙의 판정-오류 Block If(>5행 HALT) 미구현 → 구현. 생성 실패 씬이 조용히
  사라지던 것 → `attrition` 기록 + 불완전 시 판정 거부.
- [x] [Review][Patch] 가드레일이 "올라가면 안 된다"고 문서화만 되고 통과 조건 밖 → 통과 조건에 포함.
- [x] [Review][Patch] 분류기가 n=1로 분모를 정하고 있었다 → **5표 다수결**(만장일치 43/43) + 프롬프트·
  모델 지문 캐시 무효화 + 부분 분류를 미분류로.
- [x] [Review][Patch] 페어 검정이 위치 id로 페어링 → **문장** 기준으로, 미페어·rep수 불일치 보고,
  검정력 주석("p는 효과 없음의 증거가 아니다")을 산출물에 기록.
- [x] [Review][Patch] 하니스 잡건: `--legs` 오타가 구 텍스트를 재고 exit 0 / 구·신 텍스트 동일 시
  무검출 / concurrency 0 무한대기 / 빈 슬라이스 `KeyError` / 레그 지문 부재 / 리뷰어 스크립트의
  `os.chdir` 누락(`.env` 유실) / `review.md` 청결 미확인 → 전부 수정.
- [x] [Review][Patch] 테스트가 반증된 원인을 주석에 단정하고 줄바꿈 위치를 고정 → 편집이 기각됐으므로
  슬롯-3 핀은 삭제하고, **측정으로 벌어들인 가드 2건**만 남겼다(배경 전용 계약 + 슬롯 3이 몸을 위치
  참조로 부르지 않는지).
- [x] [Review][Patch] 표본 밴드에 분류기 콜 누락, 옵션 (c) 비용이 판정 콜을 빼고 계산됨, 변경 목록
  불완전 → 정정(총 1,038콜).
- [x] [Review][Patch] 채점자 어휘로 개입을 썼다(편집 문구가 judge 루브릭을 되쓴다) → **교란으로 명시**.
- [x] [Review][Defer] 사건은 있으나 환경에 흔적이 없는 문장(소리·지각·부재)에 슬롯 3이 무엇을 요구해야
  하는가 — 기각된 편집은 그 경우에도 흔적을 요구했다. §6이 "표현 불가 부류"를 반증했으므로 열린 설계
  질문으로 남긴다.
- [x] [Review][Defer] 리뷰어가 `visual_descriptions` JSON의 `cast` 메타데이터를 `image_prompt` 본문으로
  오독하는 건 — 14.1/14.7 계열 별건.

## Verification

실행 2026-08-24 · **GPU 0 · 렌더 0 · `src` 변경 0 · 프롬프트 최종 변경 0**. 근거·재산출 전량:
`_bmad-output/implementation-artifacts/14-5-prompt-screening/`.

**결과: 편집 기각.** 스펙의 Block If가 발동했다 — 신 프롬프트 산출물을 라이브 `scenario/review` v11에
5rep 통과시키자 typed `descriptor_violation` **구 22 → 신 31**, `entity_in_prompt` **구 3 → 신 8**이고
신 다리의 지적은 진짜 신체 참조였다(*"where a body had just risen"*, *"the collapsed form"*,
*"where a tall figure stands"*). 편집이 요구한 "사건의 흔적"이 **몸을 위치 참조로 되불러왔고**, 편집
자신의 예시(*"a slumped-empty floor position"*)가 그 문을 열었다. 목표축 이득도 없었다(+2.86pp,
페어 p=0.3877 — 검정력 없음, "효과 없음"의 증거는 아니다).

→ `prompts/scenario/visual_breakdown.md` **되돌림**, 재시딩 후 라이브 `scenario/visual_breakdown`
**v16 = v14 텍스트**(런타임 이름 `scenario%2Fvisual_breakdown`로 확인: 14.5 문구 부재, v14 슬롯-3 복원,
배경 전용 CRITICAL RULE 무사, 리포 파일과 일치). 10.4b가 `7744af1`에서 택한 것과 같은 길이다.

**남는 소득 — 전부 측정 정정이고 편집과 독립이다**

| 측정 | 값 |
|---|---|
| 승계 기준선 84.9%(56/66) | **오늘의 숫자가 아님** — pre-10.2 생성기(run `8a9a288b`) |
| 재기준선 (run `4b35c0ed`, v14) 풀링 | **71.16%** (153/215) |
| 재기준선 사건 담지만 | **76.43%** (107/140) |
| 사건 없는 문장이 분모에 | **15/43** — 풀링하면 지표가 나레이션에 없는 사건의 발명을 보상한다 |
| 재생성 대조군(구 프롬프트 재생성) | 83.57% — **다시 뽑기만으로 +7.14pp** |
| 후보 | 86.43%, Δ +2.86pp, 페어 p=0.3877 |
| **AC가 이름 붙인 풀링 축** | 83.18% → **80.37% (−2.81pp)** |
| `present_subject` | 43문장 **전부 동률 1.0** — 10.2 회귀선 무사 |
| 어려운 문장 집합 | shipped ∩ old-regen **7/7** 재현. 단 5rep 전부 실패한 문장은 **0개** |

**검증**: 전체 스위트 **3212 passed / 1 failed**, 그 1건은
`tests/test_render_pose_guides.py::…[humanoid_lying_supine]`(렌더 PNG의 고정 SHA)이고 **이 스토리의
변경 전량을 `git stash` 한 상태에서도 동일하게 실패**한다(기존 결함, 10.5/14.6 소관). 리뷰 후 재실행:
`test_scenario_chain.py` **855 passed**. ruff clean.

**가드 2건**(측정으로 벌어들인 것만 남겼다): 배경 전용 계약 핀(공백·인용부호 비의존), 그리고 슬롯 3이
**몸을 위치 참조로 부르지 않는지** — 후자가 이 스토리가 실측한 정확한 실패 형태다.
