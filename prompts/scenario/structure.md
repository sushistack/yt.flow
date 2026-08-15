# Stage 2: Scene Structure Design

## Storytelling Format Guide

Apply the following storytelling principles when designing scene structure, emotional curve, and pacing.

{{format_guide}}

## Structure Requirements

이 에피소드의 서사 아키타입은 **`{{story_archetype}}`** 입니다. Stage 1(리서치)이 원문의 기록
구조를 근거로 이미 선택했습니다. **다시 고르지 마세요. 다른 아키타입으로 바꾸지 마세요.**
아래 가이드가 이 에피소드의 비트 순서·시점·공개 타이밍·결말에 대한 **유일한 권위**입니다.

{{archetype_guide}}

> ⚠️ 위 가이드의 **예시 아웃라인은 비트 순서만 보여주는 발췌**입니다. 씬 일부와 필수 필드
> (`key_points`, `hook_type`, `loops_planted`, `loops_closed`, `pattern_interrupt`,
> `word_budget`, `fact_references`, `mood`, `title`, `kicker`, `estimated_duration_sec`)가
> 생략되어 있고 `scene_num`도 띄어져 있습니다. 예시의 씬 개수·필드 집합을 그대로 따라가지
> 마세요. 실제 출력은 **8~12개 연속 씬**이며 아래 Task 섹션의 스키마와 Retention Contract를
> **모든 씬에서** 충족해야 합니다 — 하나라도 빠지면 아웃라인이 기각되고 런이 실패합니다.

**모든 아키타입에 공통인 것 (위 가이드가 덮어쓰지 않는 부분):**
- 이것은 위키 문서가 아닙니다. 시청자는 분류가 아니라 **일어난 일**에 반응합니다. 어떤
  아키타입이든 분류·등급 낭독으로 시작하지 마세요.
- 정보는 한 번에 쏟지 말고 단계적으로 공개하세요. **어떤 순서로** 공개할지는 위 가이드가 정합니다.
- 격리 절차는 설명 대상이 아니라 "이렇게까지 해야 하는 이유"를 암시하는 장치입니다.
- 마지막 씬은 여운을 남깁니다. **무엇으로** 남길지는 위 가이드의 결말 계약을 따르세요.

You are a YouTube content director structuring a {{target_duration}}-minute SCP horror anime video about {{scp_id}}. Your goal is maximum viewer retention — every scene must earn the next 30 seconds of watch time.

## Research Packet (from Stage 1)
{{research_packet}}

## Visual Identity Profile (Frozen Descriptor)
{{scp_visual_reference}}

{{glossary_section}}

## Task

{{parse_error}}

For each scene (8-12 total), include:

```yaml
scene_num: 1
act: "hook"
synopsis: "Brief description of what happens in this scene"
event:
  who: "야간 근무 경비원 2명"
  what: "격리실 문을 열고 내부를 육안으로 확인했다"
  consequence: "다음 순찰에서 둘 다 목이 꺾인 채 발견됐다"
key_points:
  - "fact or detail to convey"
  - "visual element to show"
emotional_beat: "tension/mystery/horror/revelation/etc"
estimated_duration_sec: 45
hook_type: "shock"
loops_planted:
  - "loop_missing_guards"
loops_closed: []
pattern_interrupt: "none"
word_budget: 45
fact_references:
  - "재단 인원 14명이 목이 꺾인 채 사망했다"
  - "어떤 무기나 외상 흔적도 발견되지 않았다"
mood: "dread/clinical/escalation/revelation"
title: "짧은 한국어 씬 제목"
kicker: "상황을 알리는 한 줄 (스포일러 금지)"
```

### Retention Contract (모든 씬 필수, 기계 검증 대상)

이 다섯 필드는 프로즈가 아니라 **계약**입니다. 아래 규칙을 어기면 파이프라인이 아웃라인을
거부하고 런이 실패합니다 — "대충 분위기상 맞게"가 통하지 않습니다.

**`event: {who, what, consequence}`** — 씬의 사건을 기계가 읽을 수 있게 적으세요. 세 값 모두
비어 있으면 안 됩니다.
- `who`: 행위자/대상 (역할 지칭. "야간 근무 경비원 2명", "D계급 인원 1명", "SCP-173")
- `what`: 실제로 일어난 구체적 사건 ("격리실 문을 열었다", "감시 카메라가 3초간 끊겼다")
- `consequence`: 그 결과로 바뀐 상태 ("둘 다 사망했다", "격리 등급이 유클리드로 상향됐다")
- ❌ 형용사/의도 서술 금지: "긴장을 고조시킨다", "무섭게 만든다", "분위기를 잡는다"는 사건이
  아니라 연출 지시입니다. 이런 값은 유효하지 않습니다.
- `synopsis`는 그대로 유지하세요 — `event`는 그것을 대체하지 않고 기계 판독 가능하게 만듭니다.

**`hook_type`** — `question` / `shock` / `mystery` / `contrast` / `none` (위 Format Guide의
Hook Type Library와 동일한 어휘. 새 유형을 만들지 마세요).
- **Scene 1은 반드시 앞의 네 값 중 하나**를 사용합니다.
- **Scene 2 이후는 전부 `none`** 입니다. 훅은 오프닝에 한 번뿐입니다.

**`loops_planted` / `loops_closed`** — 시청자에게 진 빚의 원장(ledger)입니다. 산문 설명이 아니라
**안정적인 ID 문자열**을 적으세요.
- ID 형식: `loop_[a-z0-9_]+` (예: `loop_missing_guards`, `loop_redacted_page7`)
- 아웃라인 전체에서 **정확히 2~3개**의 루프를 심고, **최소 1개는 Scene 1**에서 심습니다.
- 각 ID는 정확히 한 번 심고(`loops_planted`), **더 뒤의 씬에서** 정확히 한 번 닫습니다(`loops_closed`).
- 같은 씬에서 심고 닫기 금지, 심지 않은 ID 닫기 금지, 중복 금지.
- 마지막 씬이 끝난 시점에 **열려 있는 루프가 하나도 없어야 합니다.**
- ⚠️ **"여운을 남기는 결말"과 혼동하지 마세요.** 마지막 비트는 아키타입 가이드의 결말 계약대로
  열린 함의로 끝나야 합니다. 그건 분위기이지 *추적 대상 약속*이 아닙니다.
  `loops_planted`에 올린 것은 "이 영상 안에서 답을 주겠다"는 약속이므로 반드시 닫습니다.
  결말의 여운은 원장에 올리지 않습니다.

**`pattern_interrupt`** — `none` / `tone_shift` / `pov_shift` / `direct_address` / `format_change`.
위 Format Guide의 Viewer Immersion Devices를 씬 단위 리듬으로 옮긴 것입니다.
- `tone_shift`: 톤 전환 (긴장 → 임상적 건조함, 또는 그 반대)
- `pov_shift`: 시점 전환 (재단 기록 → 피해자 시점 등)
- `direct_address`: 시청자에게 직접 말 걸기 (2인칭/상황 가정)
- `format_change`: 형식 전환 (인터뷰 로그, 실험 기록, 무전 교신 등 낭독 형식 변화)
- **Scene 1의 훅 이후, `none`이 3개 연속되면 안 됩니다.** 최대 2연속까지만 허용됩니다.

**`word_budget`** — 그 씬 나레이션의 목표 어절 수(공백 기준). **정수만** 씁니다 (`true`/`45.0`/`"45"` 모두 무효).
- 씬당 **{{scene_word_budget_min}}~{{scene_word_budget_max}}**, 아웃라인
  **총합 {{total_word_budget_min}}~{{total_word_budget_max}}**. (이 숫자들은 파이프라인이
  목표 길이에서 계산해 여기 주입한 값입니다 — 다른 곳에서 본 밴드가 아니라 이 값을 쓰세요.)
- **균등 배분은 기각 사유입니다.** 총합을 씬 수로 나누지 마세요. 분량은 이야기의 무게를 따라
  갑니다:
  - 오프닝(첫 씬)은 총합의 **{{max_opening_word_pct}}% 이하** — 넘으면 `budget_opening_share`로 기각됩니다.
  - 마지막 씬도 총합의 **{{max_closing_word_pct}}% 이하** — 넘으면 `budget_closing_share`로 기각됩니다.
  - **중심 비트에 가장 큰 분량**을 주세요. 가장 큰 씬은 가장 작은 씬의
    **{{min_budget_spread}}배 이상**이어야 합니다 — 못 미치면 `budget_uniform`으로 기각됩니다.
- ⚠️ `estimated_duration_sec`를 초당 어절 수로 환산해 예산을 계산하지 마세요. 그 값은 연출
  페이싱 힌트일 뿐이고, 어절 예산의 근거는 위 총합뿐입니다. 총합이
  {{total_word_budget_max}}를 넘거나 {{total_word_budget_min}}에 못 미치면 아웃라인이
  거부되고 런이 실패합니다.

### `fact_references` — 라벨이 아니라 사실 문장

Stage 3(나레이션 작성)은 **원문도 리서치 패킷도 받지 못합니다.** 이 아웃라인이 작성자가 보는
유일한 자료입니다. 따라서 `fact_references`는 조회용 키가 아니라 **그 자체로 읽히는 사실 문장**
이어야 합니다.

- 한 항목 = **하나의 구체적 주장**, 리서치 패킷(원문)에서 직접 끌어온 내용만.
- ❌ 라벨·ID·주제어 금지: `"death_count"`, `"카메라"`, `"격리 절차"`, `"항목 3"` — 조회 키를 적으면
  Stage 3은 그것을 풀어낼 사전이 없어 빈 문장으로 때웁니다.
- ✅ 사실 문장: `"재단 인원 14명이 목이 꺾인 채 사망했다"`, `"시선이 닿지 않으면 초당 최대 2미터를 이동한다"`
- 숫자·등급·날짜·인용은 원문 표기 그대로 옮기세요. 원문에 없는 사실을 만들지 마세요.
- 이 씬의 나레이션이 실제로 말해야 할 내용입니다. 씬마다 최소 1개, 비어 있으면 안 됩니다.

`mood` drives the scene's background-music/ambient/stinger audio bed — a separate
4-value axis from `emotional_beat`, not a synonym for it: `dread` (tense unease,
default), `clinical` (calm Foundation-procedural tone), `escalation` (rising
action/containment breach/chase), `revelation` (climax/dramatic reveal).

`title` and `kicker` are the text shown on this scene's chapter card (the card
that plays right before this scene) — a documentary title-card orienting the
viewer after a scene jump, not a wiki label:
- `title`: 한국어, 시청자에게 보여줄 짧은 제목 (최대 약 14자). "hook"/"mystery_expansion" 같은 내부 라벨이 아니라 시청자가 읽을 문구.
- `kicker`: 상황 맥락을 한 줄로 (최대 약 24자, 한 줄). 이 씬에서 무슨 일이 일어나는지 미리 다 밝히지 마세요 — 스포일러 금지, 과한 문장부호 금지.

### Rules:
1. Each scene's `key_points` must reference the Visual Identity Profile verbatim when the entity appears
2. Scenes must cover all Key Dramatic Beats from the research
3. Each fact from the source data should appear in at least one scene's `fact_references` — since every entry is now a full fact statement, this rule is checkable by reading the outline alone
4. **Pacing variation is MANDATORY**: alternate between slower atmospheric scenes (60-90s) and faster incident scenes (30-45s). Never use the same duration for 3+ consecutive scenes.
5. **The first scene must hook within 5 seconds** — use one of the candidate hooks from the research packet, shaped by the selected archetype's opening beat
6. The last scene must satisfy the selected archetype's ending contract (all four leave something unresolved; *what* is left open differs)
7. **Adjacent scenes MUST have different emotional beats** — never repeat the same mood consecutively
8. **Include at least one "viewer immersion" scene** where the narration addresses the viewer directly (2nd person)
9. **`title`/`kicker` are viewer-facing Korean, not internal labels**: no reveal-spoilers, one line each, no reveal of the emotional_beat name itself
10. **The Retention Contract above is mandatory on every scene** — `event`, `hook_type`, `loops_planted`, `loops_closed`, `pattern_interrupt`, `word_budget` are all required fields, not optional extras

### Pre-Output Self-Check (MANDATORY)

- [ ] 모든 씬에 `event.who` / `event.what` / `event.consequence`가 채워져 있고, 셋 다 연출 지시가 아닌 사건 서술인가
- [ ] Scene 1의 `hook_type`이 question/shock/mystery/contrast 중 하나이고, 나머지 씬은 전부 `none`인가
- [ ] 심은 루프 ID가 총 2~3개이고, 그중 최소 1개가 Scene 1에서 심어졌는가
- [ ] 심은 모든 ID가 **더 뒤의** 씬에서 정확히 한 번씩 닫혔고, 마지막 씬 이후 열린 루프가 0개인가
- [ ] `pattern_interrupt: "none"`이 3연속으로 나오는 구간이 없는가
- [ ] 모든 `word_budget`이 {{scene_word_budget_min}}~{{scene_word_budget_max}} 정수이고 총합이 {{total_word_budget_min}}~{{total_word_budget_max}}인가
- [ ] 첫 씬과 마지막 씬이 각각 총합의 {{max_opening_word_pct}}%/{{max_closing_word_pct}}% 이하이고, 가장 큰 씬이 가장 작은 씬의 {{min_budget_spread}}배 이상인가 (균등 배분이면 기각)
- [ ] 모든 `fact_references` 항목이 라벨이 아니라 읽히는 사실 문장인가
- [ ] 씬 순서가 `{{story_archetype}}` 가이드의 비트 문법 순서를 따르고, 마지막 씬이 그 가이드의
      결말 계약을 지키는가 (다른 아키타입의 순서를 섞지 않았는가)
- [ ] 가이드가 "만들지 마세요"라고 명시한 것(없는 날짜, 없는 발언, 없는 시각 표기)을 하나도
      추가하지 않았는가

하나라도 어긋나면 출력 전에 고치세요.

Respond with ONLY valid YAML, no prose, no markdown fences — a top-level `scenes:` list of scene objects as above.
