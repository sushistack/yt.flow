---
story_key: 12-6-source-grounded-story-expansion
story_id: "12.6"
epic: "Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트"
created: 2026-08-15
source_status_before: backlog
baseline_commit: f803a0dc9e0a4a9e8c0ba0e4c81dca2ba9c8a3f1
---

# Story 12.6: 원문에 살을 붙이는 각색 — 짧고 밋밋한 대본의 두 뿌리

Status: done

## Story

As Jay,
I want the pipeline to treat the SCP article as **material to dramatise**, not as a quota to summarise,
so that a video stops being a two-minute recitation of the source and becomes a story built out of it — while still never claiming anything the source does not support.

## Context

Jay watched run `e5ed4b3a` (2026-08-15, SCP-049) and named two things: **대본이 너무 짧고, 스토리텔링 전개가 부족하다.** Both are real, and neither is a bug in the usual sense — the pipeline did exactly what it was told.

### Root cause 1 — the length is written into the spec

| 실측 (run e5ed4b3a) | 값 |
|---|---|
| 씬 | 9 |
| 총 어절 | **304** |
| 규정 (`structure.md:114`) | 총합 **180~360** |
| 나레이션 길이 | 2.01분 (클론) / 2.60분 (스톡) |
| 발화 밀도 | 151 WPM (클론) / 117 WPM (스톡) |

`prompts/scenario/structure.md:114`는 분량을 *"현재 3분 파이프라인 기준"*이라 못 박고, `scenario_chain.py:65`에 `TARGET_DURATION_MINUTES = 3`이 상수로 박혀 있습니다. **304어절은 규정 한가운데입니다.** 모델은 지시를 어긴 적이 없습니다.

그리고 이건 회귀입니다 — E2E iteration 2(`c6be1954`)는 **8분 10초**였습니다. 어느 시점에 3분으로 조여졌고, 그 결정이 지금의 "너무 짧다"입니다.

밀도 자체는 나쁘지 않습니다. 영상 에세이 리텐션 분석은 **145 WPM 부근**을 최고 리텐션대로, **165 WPM 초과**에서 8분 이후 유의한 이탈을 보고합니다. 클론 음성의 151 WPM은 그 대역 안입니다. **문제는 속도가 아니라 총량과 전개입니다.**

### Root cause 2 — 각색이 결함으로 취급된다

이번 런의 크리틱은 `retry` 판정과 함께 이런 것들을 지적했습니다:

- 씬4·9 *"두개골에 완전히 융합되어"* → **Fact Sheet에 없는 단언**
- 씬7 *"지능이 높고"* → **Fact Sheet에 없는 단언**
- 씬4 *"재단 공식 기록을 낭독합니다"* → 보고서 낭독 톤

앞의 둘과 마지막 하나는 **정반대 방향의 지적**입니다. 앞의 둘은 "원문에 없는 걸 쓰지 마라"이고, 마지막은 "원문처럼 읽지 마라"입니다. 지금 시스템은 두 요구를 동시에 걸어놓고 **어느 쪽 살을 붙여도 되는지는 말해주지 않습니다.** 모델이 안전하게 도달하는 지점이 곧 "원문 요약을 낭독조로 읽기"이고, 그게 씬4에서 실제로 나왔습니다.

이 구분은 문헌에 이미 있습니다. LLM 환각 연구는 **factuality hallucination**(세상과 어긋남)과 **faithfulness hallucination**(주어진 소스와 어긋남)을 나누고, 후자 중 *extrinsic* 추가 — 소스에 명시되진 않았지만 사실로서 문제없는 것 — 을 별도 범주로 둡니다. 각색은 정확히 그 범주에서 일어납니다. 지금 우리 크리틱은 extrinsic을 전부 위반으로 처리합니다.

### 절대 흔들리면 안 되는 것

**우리는 원문이 있고, 거기에 살을 붙여 좋은 영상 대본을 만드는 게 목표입니다.** 이 스토리는 "자유 창작 허용"이 아닙니다. 원문이 뼈대이고, 붙이는 살은 **어떤 종류가 허용되는지 선언된** 것이어야 합니다. 원문이 말하지 않은 사실을 새로 주장하는 것과, 원문이 말한 사실을 감각적으로 연출하는 것은 다릅니다 — 지금은 그 둘이 구분되지 않아 후자까지 막혀 있습니다.

SCP 원문 자체의 힘도 여기에 있습니다: 재단 문서는 **의도적 은폐(obfuscation)**로 "알 수 있으면서 알 수 없는" 상태를 만듭니다. 그 빈칸은 각색이 채우라고 있는 자리이지, 침묵해야 할 자리가 아닙니다.

## Acceptance Criteria

1. **허용되는 각색의 종류가 선언된다.** 원문 사실을 (a) 감각적으로 묘사하기, (b) 시점·장면화하기, (c) 원문이 남긴 빈칸을 질문으로 열어두기 — 이런 범주가 명시적으로 허용되고, "원문에 없는 새 사실을 단언하기"는 계속 금지된다. 크리틱은 두 범주를 **다르게** 판정해야 하며, 지금처럼 하나의 `fact_reference` 위반으로 뭉뚱그리지 않는다.
2. **금지의 반대말이 제공된다.** 씬4의 `"재단 공식 기록을 낭독합니다"`는 모델이 안전지대로 후퇴한 결과다. 프롬프트는 "보고서처럼 쓰지 마라"에 더해 **무엇으로 대체하는지**를 예시와 함께 준다.
3. **목표 길이가 결정으로서 선언되고, 한 곳에서 온다.** `TARGET_DURATION_MINUTES`(코드 상수)와 `structure.md`의 "180~360 / 3분 파이프라인 기준"이 지금 두 곳에 나뉘어 있다. 길이 목표를 바꾸면 둘 다 따라와야 하며, 어긋나면 드러나야 한다. 목표값 자체는 Jay 판정 사항 — iteration 2가 8:10이었다는 사실을 근거 자료로 제시하되, 이 스토리가 임의로 정하지 않는다.
4. **길이가 늘어도 밀도는 유지된다.** 145 WPM 부근을 목표대로 삼고, 165 WPM 초과가 8분 이후 리텐션을 떨어뜨린다는 보고를 근거로 **총 길이와 WPM을 분리해 관리**한다. 길이를 늘리는 방법이 "빨리 말하기"가 되어서는 안 된다.
5. **전개가 구조로 강제된다.** 지금 씬은 균질하다 — 9씬 모두 비슷한 길이에 비슷한 밀도. 리텐션 구조 연구는 (a) 5초 안에 시청 결정, (b) 최대 이탈이 첫 30초, (c) 30초를 70% 이상 넘기면 배포가 개선된다고 보고한다. 오프닝 훅은 결과 먼저 보여주기 / 반직관적 단언 / 구체적 통증 지목 중 하나여야 하고, 중반 비트는 짧게 균질하게가 아니라 **분량이 배분**되어야 한다(`format_guide.md`의 "오프닝 ~15%, 중심 비트에 최대, 마지막 ~15%"가 이미 그렇게 말하고 있으나 실측은 균질했다 — 규정이 지켜지는지부터 측정한다).
6. **원문 소진율을 측정한다.** 이번 런은 SCP-049 원문(739자)에서 9씬을 만들었다. 원문의 어떤 요소가 대본에 반영되고 어떤 게 버려졌는지 측정 가능해야 한다 — "살을 붙인다"는 목표는 **원문을 더 많이 쓰는 것**과 **쓴 것을 더 깊게 다루는 것** 둘 다를 포함하고, 어느 쪽이 부족한지 수치 없이는 못 고친다.
7. **크리틱의 판정이 게이트에서 구분되어 보인다.** 지금은 `unresolved_pass2` 하나로 뭉쳐 `scenario_quality.warning`에 실린다(프론트 `ArtifactPanel`이 렌더). 각색 위반과 사실 위반은 조치가 다르므로 게이트에서도 달라야 한다.
8. **회귀 방지.** 길이 목표를 올린 뒤 다시 측정해, 어절 수·WPM·씬별 분량 배분·원문 소진율을 이번 런의 baseline(9씬 304어절 151WPM 균질)과 나란히 기록한다.

## Tasks / Subtasks

- [ ] **Task 0 — 측정 먼저.** 이번 런과 iteration 2(`c6be1954`, 8:10)의 대본을 같은 지표로 재라: 씬 수, 어절, WPM, 씬별 분량 분포, 원문 소진율. 무엇이 언제 조여졌는지는 추측이 아니라 두 대본의 차이로 답한다.
- [ ] **Task 1 — 각색 범주 선언 (AC: 1, 2)** — `writing.md` / `critic_agent.md` / `review.md`. 허용 범주와 금지 범주를 나누고, 금지에는 반드시 대체 예시를 붙인다.
- [ ] **Task 2 — 길이 목표의 단일 출처 (AC: 3, 4)** — `TARGET_DURATION_MINUTES`와 `structure.md`의 word_budget 규정을 한 결정으로 묶는다.
- [ ] **Task 3 — 전개 구조 (AC: 5)** — 훅 유형과 분량 배분이 실제로 지켜지는지 검증 가능한 형태로.
- [ ] **Task 4 — 소진율·판정 분리 (AC: 6, 7)**
- [ ] **Task 5 — 재측정 (AC: 8)**
- [ ] **Task 6 — 프롬프트 시딩** — CLAUDE.md DEV MODE대로 `production` 직승격. 사전에 repo↔Langfuse 대조로 무관한 드리프트가 동반 승격되지 않게 할 것(2026-08-15 기준 `character/angle_selection`·`character/generation`이 이미 드리프트 상태).

## Dev Notes

### Traps

1. **"각색 허용"이 "사실 자유"가 되면 8-8의 `article_fidelity -1.00` 부류가 돌아온다.** 12.4가 닫은 어휘 통제(닫힌 vocabulary + 코드 측 기각)가 여기서도 모델이다 — 허용을 **열거**하고, 열거 밖은 계속 막는다.
2. **크리틱을 느슨하게 만드는 것으로 해결하지 마라.** 이번 런의 크리틱 지적은 셋 다 정확했다. 문제는 판정이 틀린 게 아니라 **범주가 하나뿐**이라는 것이다.
3. **길이를 늘리면 6.9의 절단이 다시 온다.** 이번 런에서도 `writing_scene_repair`가 절단돼 1회 재롤했다. 절단은 `content==""` + `reasoning_content` 소진이지 폭주가 아니다(`gotcha_deepseek-reasoning-truncation`) — 분량을 늘리기 전에 그 예산을 확인하라.
4. **`location`/`color_palette`/`atmosphere`는 writing_step 필드다**(`gotcha_location-is-a-writing-field-not-a-structure-field`) — 스키마를 만질 때 어느 단계 소유인지 먼저 확인.
5. **프롬프트 변경은 렌더 전 텍스트로 스크리닝**(`gotcha_screen-a-prompt-change-before-you-render-it`).
6. **길이가 늘면 영상 렌더 시간도 는다.** 8분 대본이면 샷이 100개를 넘길 수 있고, ComfyUI 기동 조건이 안 맞으면 샷당 490초가 된다(`gotcha_comfyui-cache-classic-evicts-on-workflow-alternation`).

### 외부 참고

- **Faithfulness vs factuality hallucination**, extrinsic 추가가 별도 범주라는 정리 — [LLM Hallucinations: A Comprehensive Survey](https://arxiv.org/html/2510.06265v2), [A review of faithfulness metrics for hallucination assessment in LLMs](https://arxiv.org/pdf/2501.00269)
- **소스 접지 장문 생성** (다중 소스 사실 접지 + 서사 파편화 완화) — [Deep-Reporter: Deep Research for Grounded Multimodal Long-Form Generation](https://arxiv.org/html/2604.10741v1)
- **장문 일관성: 세계 상태 추적 / 캐릭터 접지 다중 에이전트** — [Narrative World Model](https://arxiv.org/pdf/2607.05577), [From Personas to Plot](https://arxiv.org/abs/2607.00918)
- **스토리 평가 리워드 모델** (13-2의 축과 이어짐) — [StoryAlign](https://arxiv.org/pdf/2605.04831), [EvolvR](https://arxiv.org/pdf/2508.06046)
- **LLM의 서사 선호가 내용보다 문체로 기운다는 측정** — [Style over Story](https://arxiv.org/pdf/2510.02025)
- **리텐션 구조**: 5초 판단 / 첫 30초 최대 이탈 / 30초 70% 통과의 배포 효과, 훅 3유형 — [YouTube Script Writing 2026: 6-Part Structure](https://outlierkit.com/resources/youtube-script-writing/), [Better Retention 2026 Guide](https://frameo.ai/blog/engaging-youtube-video-script/), [YouTube Script Writing Best Practices 2026](https://ytzolo.com/blog/youtube-script-writing-best-practices-2026/)
- **145 WPM 최고 리텐션대 / 165 WPM 초과 시 8분 이후 이탈** — [How to Write and Record a Video Essay (2026)](https://teleprompter.works/blog/how-to-create-video-essays/)
- **SCP의 은폐·낯설게하기 서사 기법** — [Seeing SCP as a Narrative Protocol](https://sceneswithsimon.com/p/seeing-scp-as-a-narrative-protocol), [SCP Foundation (Wikipedia)](https://en.wikipedia.org/wiki/SCP_Foundation)

### 내부 참고

- [Source: prompts/scenario/structure.md#L114] — "총합 180~360 (현재 3분 파이프라인 기준)"
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L65] — `TARGET_DURATION_MINUTES = 3`
- [Source: prompts/scenario/format_guide.md#L113] — 분량 배분 규정(오프닝 ~15% / 중심 최대 / 마지막 ~15%)
- [Source: _bmad-output/implementation-artifacts/12-4-*.md] — 닫힌 어휘 + 코드 측 기각 패턴
- 프로젝트 메모리: `project_e2e-iteration3-done`(이번 런 실측), `project_e2e-iteration2-done`(8:10 회귀 비교 대상), `gotcha_deepseek-reasoning-truncation`

## Dev Agent Record
