---
story_key: 12-8-outline-grounding-and-attribution
story_id: "12.8"
epic: "Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트"
created: 2026-08-16
source_status_before: backlog
baseline_commit: e5726d6d07f0886b78357bed1ae60685f4eef669
---

# Story 12.8: 아웃라인 접지 — 주인 없는 날조와 잘못 붙는 청구서

Status: draft

## Story

As Jay,
I want the outline's `fact_references` and `event` fields to be **checked against the source**, and a grounding violation to be **charged to the stage that minted it**,
so that the pipeline stops rewriting narration that was correct, for a fabrication it cannot reach.

## Context

12.7의 ablation(2026-08-16, `12-6-live-validation/ablation.md`)이 문체를 재려다 더 무거운 걸 밟았습니다. **세 arm 전부, 접지 위반 문장은 작성자가 지어낸 게 아니었습니다.**

### 실측 — 귀속 추적

| 나레이션 문장 | 작성자가 받은 곳 |
|---|---|
| B 씬4 *"보고서에 기록된 등급은 유클리드"* | B 씬4 `fact_references`: *"SCP-049는 유클리드 등급의 인간형 개체이며…"* |
| B 씬3 *"그가 요구한 것은 더 많은 수술 도구"* | B 씬3 `event.consequence` 그대로 |
| B 씬8 *"실패한 재활성화 기록"*, *"더 많은 환자를 요구하는 메모"* | B 씬8 `event.what` / `event.consequence` 그대로 |
| control 씬7 · A 씬1 · A 씬6 · B 씬4 *"가면이 융합되어 있다"* (단언) | 각 아웃라인의 `fact_references`가 **원문의 "~로 보인다"를 이미 떨어뜨린 상태**. control 씬7: *"마스크는 착용된 것이 아니라 융합된 것이며…"* |

원문(739자)은 등급을 명시하지 않고, 실패한 재활성화 기록도 수술 도구 요구도 없습니다. 그리고 마스크에 대해 원문이 말하는 건 **"융합된 것처럼 보인다"**까지입니다.

`writing.md`는 작성자에게 *"그 씬의 `fact_references`가 당신이 가진 사실의 전부"*라고 말하고, 리텐션 계약은 *"`event`의 결과를 다른 것으로 바꾸지 마세요"*라고 말합니다. **작성자는 매번 지시대로 했습니다.**

### 결함 1 — 아무도 아웃라인을 원문과 대조하지 않는다

이건 누락이 아니라 **소유권 공백**입니다. `scenario_chain.py:911-913`이 12.1 시점에 명시적으로 미뤘습니다:

> *"Shape only. Whether a statement is actually grounded in the source article is not machine-checkable here — **review/critic** and Story 12.3's deterministic metrics own that."*

그런데 그 review/critic은 **아웃라인을 받지 않습니다.** `review_step`이 받는 건 `scp_fact_sheet` + `narration_script`이고, `critic_step`이 받는 건 `scp_fact_sheet` + `scenario_json`(나레이션+비주얼)입니다. 둘 다 `fact_references`를 본 적이 없습니다. **책임을 넘겨받은 쪽이 볼 수가 없어서, 결과적으로 주인이 없습니다.** Epic 13이 말하는 "조용한 실패"의 전형입니다 — 코드는 정상이고 결과물만 틀립니다.

### 결함 2 — 청구서가 아래층에 붙고, 아래층은 못 고친다

크리틱은 나레이션을 **SCP fact sheet 기준**으로 판정하므로, 아웃라인이 심은 날조를 **작성자의 `ungrounded_claim`으로 보고**합니다. 12.6이 만든 게이트 범주는 정확히 발화하지만 **가리키는 층이 틀렸습니다.**

그리고 그 판정은 고칠 수 없는 곳을 겨냥합니다. `structure_step` 호출은 `scenario.py`에 **정확히 한 번**뿐이고(`grep -c` = 1), 재시도 경로 `_full_rewrite`는 **같은 `structure`를 그대로 다시 넘깁니다**. 즉 아웃라인에서 태어난 날조는 **재시도 루프가 구조적으로 도달할 수 없습니다** — 파이프라인은 이미 옳았던 나레이션을, 틀렸다는 피드백을 받고, 못 고칠 결함을 향해 다시 씁니다. 그게 12.6 라이브 런의 `unresolved_pass2`이고, 이번 ablation 세 arm 전부의 `retry`입니다.

## Acceptance Criteria

1. **`fact_references` 항목은 출처를 들고 다닌다.** 각 항목이 원문에서 그 진술을 지지하는 **축자 인용**을 함께 싣는다. 인용이 원문에 실제로 존재하는지는 **Python 부분문자열 검사**로 결정론적으로 확인되며(LLM 호출 추가 없음), 확인 실패는 아웃라인 기각이다. 선례: `review.md`의 `grounded_contradictions`가 이미 양쪽 인용을 요구하고 인용 불가 항목을 파서가 기각한다.
2. **헤지가 보존된다.** 원문이 *"~로 보인다 / ~인 것으로 추정된다"*로 말한 것을 `fact_references`가 단언으로 올리지 않는다. AC1의 축자 인용이 헤지를 함께 실어오므로, 패러프레이즈가 헤지를 떨어뜨렸는지가 **읽어서 확인 가능**해진다. 12.6이 `critic_agent.md`에 넣은 *"'~로 보인다'를 '~이다'로 올리는 것도 단언"* 규칙이 아웃라인 단계에도 걸린다.
3. **`event.what` / `event.consequence`도 같은 규율을 받는다.** ablation의 날조 4건 중 3건은 `fact_references`가 아니라 `event` 필드였다. 리텐션 계약이 작성자에게 *"consequence를 바꾸지 마라"*고 강제하는 이상, `event`는 `fact_references`와 동급의 사실 주장이다. 현재 `_validate_retention_outline`은 셋 다 **비어 있지 않은 문자열인지만** 본다(`scenario_chain.py:850-855`).
4. **판정이 층을 지목한다.** 접지 위반이 게이트에 실릴 때 **아웃라인 유래 / 나레이션 유래**가 구분된다. 12.6의 `warning.categories`는 `ungrounded_claim`까지만 말하고 어느 단계인지는 말하지 않는다. 조치가 다르므로 구분되어야 한다 — 전자는 아웃라인을 다시 뽑아야 하고 후자는 씬 리페어로 족하다.
5. **못 고치는 재시도가 드러난다.** 위반이 아웃라인 유래로 판정되면, 씬 리페어가 그것을 고칠 수 없다는 사실이 로그와 게이트에 남는다. **세 번째 패스를 추가하지 않는다**(6.5의 1회 재시도 한계는 유지). 이 스토리의 목표는 헛도는 재시도를 **보이게** 만드는 것이지 재시도를 늘리는 게 아니다.
6. **작성자의 눈가림은 그대로다.** 작성자에게 원문을 주는 것으로 해결하지 않는다 — 그건 12.1이 접지를 위해 의도적으로 끊은 연결이고, 되돌리면 8.8의 `article_fidelity -1.00`이 돌아온다. 고칠 곳은 아웃라인이지 작성자의 시야가 아니다.
7. **크리틱을 느슨하게 만들지 않는다.** ablation의 지적은 전부 정확했다 — *"등급은 유클리드"*는 실제로 원문에 없다. 문제는 판정이 틀린 게 아니라 **청구서가 잘못 붙는 것**이다.
8. **재측정.** 같은 SCP로 다시 돌려, 아웃라인 유래 접지 위반 건수를 ablation baseline(control 1건 / A 2건 / B 4건)과 나란히 기록한다. `ablation.md`의 귀속 표가 그대로 재현 가능한 형태여야 한다 — 즉 위반마다 "작성자가 이걸 어디서 받았는지"를 스크립트가 답할 수 있어야 한다.

## Tasks / Subtasks

- [ ] **Task 0 — 귀속 계측기.** 나레이션의 접지 위반을 아웃라인의 `fact_references`/`event`와 대조해 유래를 판정하는 스크립트. ablation의 귀속 표를 손으로 만든 걸 자동화한다. 이게 없으면 AC8을 잴 수 없다.
- [ ] **Task 1 — 축자 인용 계약 (AC: 1, 2)** — `structure.md`의 `fact_references` 스키마 + `_validate_retention_outline`의 결정론적 인용 검증.
- [ ] **Task 2 — `event` 필드 (AC: 3)** — 같은 규율을 `event.what`/`event.consequence`로 확장.
- [ ] **Task 3 — 층 지목 (AC: 4, 5)** — 게이트 페이로드와 로그. 12.6의 `categories` 옆자리.
- [ ] **Task 4 — 재측정 (AC: 8)**
- [ ] **Task 5 — 프롬프트 시딩** — DEV MODE `production` 직승격, 사전 `--dry-run`.

## Dev Notes

### Traps

1. **재시도 루프는 이 결함에 도달할 수 없다.** `structure_step`은 런당 1회이고 `_full_rewrite`는 같은 아웃라인을 재사용한다(`scenario.py:646`, `:669`). 아웃라인을 다시 뽑는 건 이 스토리의 범위 밖이며, 하려면 6.5의 재시도 정책을 다시 여는 별건이다. **AC5는 "보이게 하기"이지 "고치기"가 아니다.**
2. **12.1이 이 검사를 명시적으로 미뤘고, 넘겨받은 쪽은 볼 수가 없다** (`scenario_chain.py:911-913`). 주석이 review/critic을 지목하지만 둘 다 아웃라인을 안 받는다. **주석을 근거로 "이미 누가 한다"고 판단하지 마라** — `gotcha_recorded-root-cause-can-be-inverted`.
3. **축자 인용 검사는 정규화가 전부다.** 공백·줄바꿈·전각 문장부호에서 부분문자열 검사가 깨진다. 그리고 원문이 한국어인지 영어인지에 따라 인용 가능성이 달라진다 — SCP-049 원문은 739자이고, 다른 SCP에서 확인해 보고 정규화 규칙을 정하라.
4. **인용 의무가 과하면 아웃라인이 원문 복붙이 된다.** 12.6이 세운 "허용되는 각색 3범주"는 **작성자** 계약이고, 아웃라인은 원래 사실을 나르는 층이다 — 그래도 인용을 너무 빡빡하게 걸면 `fact_references`가 원문 문장 그대로가 되어 12.6이 연 각색 여지를 뒤에서 닫을 수 있다. 인용은 **근거**로 싣고 진술은 패러프레이즈로 남기는 형태여야 한다.
5. **크리틱 느슨화로 해결하지 마라** (AC7). ablation 지적은 전부 정확했다.
6. **표본 하나로 선언 금지** (`gotcha_measure-densely-before-declaring-a-fix`). ablation은 arm당 1런이고 arm마다 아웃라인이 달랐다.
7. **캡된 리스트에서 요약을 계산하지 마라** — 12.6 리뷰의 high 2건이 그거였다(`gotcha_summary-from-a-capped-list-drops-the-severest-item`). AC4의 층 표시가 같은 함정에 빠지기 쉽다.

### 왜 12.7보다 무거운가 (착수 순서 근거)

12.7은 **읽는 맛**을 고치고, 12.8은 **말하는 내용이 사실인지**를 고칩니다. 12.6이 각색 범주를 선언해 얻은 것도, 12.3이 접지 모순 검사를 붙여 얻은 것도, 아웃라인이 틀린 사실을 내려보내면 아래층에서 전부 무효화됩니다. 다만 Jay가 지금 **듣고 판정할 수 있는 건 12.7 쪽**이라 순서는 판단 사항입니다.

### 내부 참고

- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L911] — 12.1이 접지 검사를 review/critic에 미룬 주석 (넘겨받은 쪽은 아웃라인을 못 본다)
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L850] — `event.who/what/consequence` 비어있지 않음만 검사
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L646] — `structure_step` 런당 유일 호출
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L669] — `_full_rewrite`가 같은 `structure`를 재사용
- [Source: prompts/scenario/review.md] — `grounded_contradictions`의 양쪽 인용 요구 + 인용 불가 항목 파서 기각 (AC1의 선례)
- [Source: prompts/scenario/critic_agent.md] — *"'~로 보인다'를 '~이다'로 올리는 것도 단언"* (12.6이 넣은 규칙, 아웃라인에는 안 걸려 있다)
- [Source: _bmad-output/implementation-artifacts/12-6-live-validation/ablation.md] — 귀속 표, 세 arm 실측
- 프로젝트 메모리: `project_12-6-review-done`, `gotcha_recorded-root-cause-can-be-inverted`, `gotcha_summary-from-a-capped-list-drops-the-severest-item`

## Dev Agent Record
