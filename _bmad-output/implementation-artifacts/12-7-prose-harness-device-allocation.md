---
story_key: 12-7-prose-harness-device-allocation
story_id: "12.7"
epic: "Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트"
created: 2026-08-16
source_status_before: backlog
baseline_commit: c4ab38bcabad8e9945d045f4b5d1480797f9a455
---

# Story 12.7: 문체 하네스 — 전체용 할당량을 씬별 배정으로

Status: draft

## Story

As Jay,
I want the immersion techniques to be **assigned to specific scenes** instead of demanded of every scene,
so that the narration stops firing the same device eight times in a row and reads as connected prose rather than a stack of facts — without loosening a single grounding rule.

## Context

12.6이 길이와 전개를 고친 뒤 Jay가 산출물을 듣고 지적한 두 가지: **"맥락 없이 상세한 내용만 주저리주저리한다"**, **"대본 사이에 여백이 없어 계속 얘기하니까 피곤하다"**. 두 번째는 오디오 층이라 별건이고(아래 범위 밖), 첫 번째의 뿌리가 이 스토리다.

### 실측 — 장치가 씬마다 시계처럼 찍힌다

`12-6-live-validation/after_scenes.json`(SCP-049, 8씬 417어절)에서:

| 씬 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 합계 |
|---|---|---|---|---|---|---|---|---|---|
| 극적 질문 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | **9 (8/8씬)** |
| 2인칭 | 1 | 1 | 2 | 1 | 1 | 0 | 0 | 1 | 7 (6/8씬) |

**8씬 전부 질문이 정확히 1개씩입니다.** 이건 우연이 아니라 구조입니다.

### 원인 — 전체용 할당량을 눈 감은 작성자가 N번 실행한다

`writing.md:38-48`의 할당량은 **대본 전체 기준**입니다: *"2인칭: 시나리오 전체에서 최소 3회"*, *"상황 가정: 최소 1회"*. 그런데 `writing_step`(`scenario_chain.py:1780`)은 **씬당 LLM 한 번**이고, 각 호출이 받는 건 자기 씬 하나 + 앞뒤 씬의 한 줄 요약뿐입니다(`_writing_scene_brief`, `scenario_chain.py:1746`). 원문도, 다른 씬의 나레이션도 못 봅니다.

그래서 각 호출은 "최소 3회"를 읽고 **이미 채워졌는지 확인할 수단이 없어 자기 씬에서 채웁니다.** 전체 3회짜리 요구가 8번 독립 실행되어 7회가 되고, 개수 제한이 없는 질문은 8회가 됩니다. **제약이 과한 게 아니라, 전체용 규칙을 부분만 보는 작성자가 실행하는 것**이 문제입니다.

파이프라인은 이 문제를 이미 한 번 풀어본 적이 있습니다 — `hook_type`은 아웃라인이 씬 1에만 배정하고 나머지 씬은 전부 `none`입니다. 같은 모양을 몰입 기법에도 적용하면 됩니다.

### Ablation 결과 (2026-08-16, `12-6-live-validation/ablation.md`)

동일 SCP로 두 arm을 라이브 실행했습니다. Arm A = 장치 배정, Arm B = A + 문장 규칙 완화.

| | control | A | B |
|---|---|---|---|
| 질문 (총/사용 씬) | 9 / **8of8** | 2 / **2of9** | 2 / **2of8** |
| 2인칭 (총/사용 씬) | 7 / 6of8 | 2 / 2of9 | 2 / 2of8 |
| 평균 문장 길이 | 33.1자 | 33.9자 | **42.5자** |
| 앞 씬과 연결하며 시작 | 0/7 | 3/8 | **7/7** |
| 총 어절 / WPM | 417 / 148.1 | 432 / 144.9 | 494 / **158.1** |
| 리텐션 계약 | pass | pass | pass |
| review_overall_pass | true | true | **false** |

**배정 준수는 4/4 정확** — 배정한 씬에만 나오고 배정 안 한 씬에는 하나도 안 나왔습니다. Jay 청취 판정: **A·B 둘 다 개선**.

### 이 스토리가 건드리지 않는 것

Ablation이 밝힌 가장 중요한 사실: **세 arm 모두, 접지 위반 문장은 작성자가 지어낸 게 아니라 아웃라인의 `fact_references`/`event`에 이미 있던 것을 지시대로 옮긴 것**입니다. 원문의 *"융합된 **것처럼 보인다**"* 헤지를 `fact_references`가 떨어뜨리고, 크리틱은 fact sheet 기준으로 판정하므로 **structure 단계의 날조를 writing 단계의 것으로 보고합니다**. 이건 별도 스토리(12.8 예정)이고, **이 스토리에서 고치려 들면 안 됩니다** — 문체 프롬프트를 아무리 고쳐도 안 고쳐집니다.

## Acceptance Criteria

1. **몰입 기법이 대본 전체에 배정된다.** 배정은 아웃라인 **전체를 보는 Python**이 결정하고(`_writing_scene_brief`는 이미 `structure` 전체를 받는다), 각 씬 호출에는 **그 씬 몫만** 전달된다. `hook_type`이 씬 1에만 배정되는 것과 같은 모양이다. LLM 호출을 추가하지 않는다.
2. **프롬프트가 "전부 사용"에서 "배정된 것만"으로 바뀐다.** `writing.md:38`의 *"필수 몰입 기법 (전부 사용)"* 블록은 배정을 읽어 쓰도록 바뀌고, **배정되지 않은 기법은 쓰지 말 것**이 명시된다.
3. **질문을 요구하는 두 곳이 함께 고쳐진다.** `writing.md:38-48`의 기법 블록 외에 `writing.md:57-61`의 **종결어미 리듬 규칙**도 씬마다 의문형을 섞으라고 요구한다 — 이건 씬 단위라 그것만으로 질문 1.0/씬이 고정된다. **기법 블록만 고치면 산출물이 안 변하고 "가설이 틀렸다"는 잘못된 결론이 난다.** 종결어미 규칙의 의문형 항목은 배정된 씬에서만 적용되도록 바뀌어야 하며, 배정 없는 씬은 나머지 종결형으로 다양성을 만족시킬 수 있어야 한다.
4. **배정에 구멍이 없다.** Ablation arm A의 실패 둘을 닫는다 — ① 마지막 씬에 장치가 하나도 안 배정됐다(마지막 루프가 9씬 중 7씬에서 닫혀서). ② `상황 가정`이 `2인칭` 슬롯에 접혀 통째로 사라졌다(총 0회). 배정 규칙은 **마지막 씬이 반드시 장치 하나를 받고**, **각 기법이 최소 1회 배정**되도록 총체적이어야 한다.
5. **문장 규칙이 연결을 허용한다.** `writing.md:52`의 *"문장 길이 15~25자"*는 인과·역접 종속절을 못 쓰게 만들어 문장들이 서로 안 이어지게 한다 — Jay의 "주저리주저리"의 직접 원인. 평균 지향으로 바꾸고 연결 문장을 허용하되, **드라마틱 포즈(단문 끊기)는 임팩트 비트에 남는다**. 짧은 문장이 금지되는 게 아니라 균일 강제가 풀리는 것이다.
6. **각 씬은 앞 씬과의 연결을 세우고 사실로 들어간다.** control은 0/7이었고 arm B는 7/7이었다. 첫 문장이 맨 사실로 시작하지 않는다.
7. **밀도가 상한을 넘지 않는다.** arm B는 158.1 WPM으로 165 상한에 근접했다 — 긴 문장은 쉼이 적어 빨라진다. 12.6이 세운 `TARGET_WPM`/총량 분리를 유지하면서 **실측 WPM ≤ 165**여야 한다. 넘으면 문장 완화 폭을 조인다.
8. **접지 무회귀.** `fact_references` 의무, 그 밖 단언 금지, 허용되는 각색 3범주 — 전부 그대로다. 재측정에서 writing 단계가 새로 만든 접지 위반이 **0건**이어야 한다(아웃라인에서 유래한 것은 12.8 소관이며 이 스토리의 회귀가 아니다 — 두 부류를 **구분해서** 보고할 것).
9. **장치 카운트가 계측된다.** `12-6-live-validation/count_devices.py`가 이미 존재한다. 재측정은 이 계기로 하고, control/이번 산출물을 나란히 기록한다. 리액션 계수는 **서술자 태도어(솔직히·소름·놀랍게)와 대상 형용사(기괴한·섬뜩한)를 구분**해야 한다 — ablation에서 이 구분 없이는 배정 준수가 위반으로 오독됐다.

## Tasks / Subtasks

- [ ] **Task 1 — 배정 로직 (AC: 1, 4)** — `scenario_chain.py`의 `_writing_scene_brief` 주변. 아웃라인 전체에서 결정론적으로 배정하고 씬 몫만 브리프에 싣는다. `hook_type` 스코핑이 모델.
- [ ] **Task 2 — 프롬프트 두 곳 (AC: 2, 3)** — `writing.md:38-48` 기법 블록 + `writing.md:57-61` 종결어미 규칙. **둘 다 고쳐야 한다.**
- [ ] **Task 3 — 문장·연결 규칙 (AC: 5, 6)** — `writing.md:52` 및 씬 도입 규칙. ablation arm B가 쓴 문구가 출발점(`ablation.md`에 기록됨).
- [ ] **Task 4 — 재측정 (AC: 7, 8, 9)** — `count_devices.py` + `scripts/measure_script.py`로 control 대비 기록. 접지 위반은 writing 유래 / structure 유래로 나눠 보고.
- [ ] **Task 5 — 프롬프트 시딩** — CLAUDE.md DEV MODE대로 `production` 직승격. 사전 `--dry-run`으로 무관한 드리프트 동반 승격 차단.

## Dev Notes

### Traps

1. **기법 블록만 고치면 아무 일도 안 일어난다.** 질문 요구는 두 곳에 있다(AC3). Ablation은 둘 다 중화하고 나서야 질문이 8→2로 떨어졌다.
2. **배정을 프롬프트에 맡기지 마라.** 작성자는 씬 하나만 본다 — "전체에서 2회"를 자기가 셀 수 없다. 그게 이 결함의 원인 그 자체다. 배정은 반드시 **아웃라인 전체를 보는 Python**에서 나와야 한다.
3. **접지 위반을 이 스토리의 회귀로 오독하지 마라.** 재측정에서 `ungrounded_claim`이 뜨는 건 정상이다 — control에도 있었고 출처는 structure다(`ablation.md`의 귀속 표). writing 단계가 **새로** 만든 것만 회귀다.
4. **arm마다 체인 전체를 다시 굴리면 아웃라인이 달라진다.** ablation의 어절·소진율 비교는 이 교란을 벗어나지 못했다. 장치 카운트만 교란에서 자유롭다. 재측정 설계 시 같은 아웃라인에 writing만 다시 돌리는 쪽을 검토하라.
5. **arm당 1런은 표본이 아니다** (`gotcha_measure-densely-before-declaring-a-fix`). 배정 준수(4/4)는 결정론적이라 1런으로 충분하지만, 문장 길이·WPM은 아니다.
6. **프롬프트 변경은 렌더 전 텍스트로 스크리닝** (`gotcha_screen-a-prompt-change-before-you-render-it`).

### 범위 밖 (별건으로 추적)

- **호흡/여백** — Jay 피드백 2번. 씬 경계가 `plain concat`이라 무음이 0이다(`video.py:2334`, 5.9의 볼륨 딥 제거 설계의 대가). 클립 꼬리 실측 -30~-33dB로 디지털 무음이 아니다. 오디오 층 별건.
- **structure 단계의 헤지 손실** — 12.8 예정. `fact_references`가 원문의 "~로 보인다"를 떨어뜨리고, 크리틱이 그 결과를 writing에 귀속시킨다.

### 내부 참고

- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L1746] — `_writing_scene_brief`, 아웃라인 전체를 받는다
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L1780] — `writing_step`, 씬당 1콜 `asyncio.gather`
- [Source: prompts/scenario/writing.md#L38] — 필수 몰입 기법 (전부 사용)
- [Source: prompts/scenario/writing.md#L52] — 문장 길이 15~25자
- [Source: prompts/scenario/writing.md#L57] — 종결어미 리듬 규칙(의문형 요구, 두 번째 출처)
- [Source: _bmad-output/implementation-artifacts/12-6-live-validation/ablation.md] — 두 arm 라이브 결과·귀속 분석·arm B가 쓴 대체 문구
- [Source: _bmad-output/implementation-artifacts/12-6-live-validation/count_devices.py] — 장치 계측기
- 프로젝트 메모리: `project_12-6-review-done`, `gotcha_measure-densely-before-declaring-a-fix`

## Dev Agent Record
