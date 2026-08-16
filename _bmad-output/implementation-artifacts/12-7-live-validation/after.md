# Story 12.7 — 재측정: 배정된 장치만 쓰는 대본 (라이브)

**설계:** 12.6 control(`12-6-live-validation/after_scenes.json`)이 쓴 **바로 그 아웃라인을 고정**하고 writing 이후만 다시 돌렸습니다. Ablation은 arm마다 체인 전체를 굴려 아웃라인이 달라졌고(control 8씬 / arm A 9씬), 어절·WPM 비교가 그 교란을 벗어나지 못했습니다(`12-6-live-validation/ablation.md`, Trap 4). 여기서는 아웃라인이 같습니다.

- 드라이버: `run_writing_only.py` — `scenario.structure_step`을 고정 아웃라인 반환으로 대체하고 그 위에 **출하 코드** `scenario_chain._allocate_devices`를 `structure_step`과 똑같이 적용합니다. 배정은 복사본이 아니라 프로덕션 함수입니다.
- **아직 고정되지 않은 것:** research 단계는 매 런 라이브로 돕니다 — `frozen_descriptor` / `entity_sheet` / `story_logline` / `story_archetype` 넷 다 writing 입력입니다. 아웃라인 교란은 없앴지만 런이 밀폐된 것은 아닙니다. 그래서 이 넷을 덤프의 `research` 키에 함께 기록해 이후에 확인할 수 있게 했습니다(세 런 모두 `story_archetype: incident_first`).
- 음성: control과 같은 클론 보이스(`qwen-tts-vc-sutak-…`, speed 1.2). 다른 보이스로 재면 WPM 비교가 무효입니다.

```
uv run python …/12-7-live-validation/run_writing_only.py --out …/12-7-live-validation/after_scenes.json
uv run python …/12-6-live-validation/run_after_tts.py --scenes …/after_scenes.json --out …/after_durations.json --run-id 12-7-after
uv run python …/12-6-live-validation/count_devices.py control=12-6-live-validation/after_scenes.json after=12-7-live-validation/after_scenes.json
uv run python …/12-7-live-validation/first_sentences.py after=12-7-live-validation/after_scenes.json
uv run python scripts/measure_script.py --run 12-7-after --scenes-json …/after_scenes.json --durations-json …/after_durations.json
```

## 세 번 돌렸고, 커밋된 산출물은 세 번째입니다

프롬프트가 두 번 바뀌었고 **바뀔 때마다 다시 쟀습니다** — 재지 않은 프롬프트를 출하하지 않기 위해서입니다. 세 런 모두 같은 아웃라인·같은 SCP·같은 보이스입니다.

| | pass 1 | pass 2 | **pass 3 (커밋됨)** |
|---|---|---|---|
| 프롬프트 | ablation arm B 문구 그대로 | + 리뷰 지적 가드절 6개 | + 연결 문장 접지 강화 |
| 질문 (총 / 사용 씬) | 2 / 2of8 | 2 / 2of8 | **2 / 2of8** |
| 2인칭 | 3 / 2of8 | 2 / 2of8 | **2 / 2of8** |
| 평균 문장 길이 | 41.9자 | 45.9자 | **41.2자** |
| WPM | 158.5 | 148.1 | **146.9** |
| 앞 씬과 연결하며 시작 | 6/7 | 7/7 | **7/7** |
| 배정 밖 장치 (손 분류 후) | 리액션 1건 | 가정 1건 | **리액션 1건** |
| `review_overall_pass` | false | false | **true** |

pass 2가 만든 문제와 그 수정이 이 표의 핵심입니다: **연결 문장 규칙(AC6)이 앞 씬의 관찰 결과를 이 씬에서 확정 사실로 다시 단언하게 만들었습니다.** pass 2 씬 8이 *"마스크가 곧 피부였던 그 존재의 진료는 끝났지만…"*으로 열었고, 씬 8의 `fact_references`에는 마스크 이야기가 없습니다. 규칙을 **"앞 씬이 남긴 상태·시간·감정을 짚되, 앞 씬이 밝혀낸 사실을 다시 단언하지 말 것"**으로 좁히고 그 문장을 ❌ 예시로 박았습니다. pass 3의 여덟 개 도입부는 전부 상태·시간형입니다("그 섬뜩한 순간이 지난 뒤", "통제된 허가가 떨어진 직후", "그 기이한 형체가 드러난 뒤에도").

WPM이 158.5 → 146.9로 내려간 것도 읽어야 합니다: **문장이 길어진다고 빨라지지 않습니다.** pass 2는 pass 1보다 문장이 길었는데 WPM은 10 낮았습니다. arm B에서 관찰된 "긴 문장 → 빠른 발화" 관계는 세 런에서 재현되지 않았고, 165 상한은 세 번 다 여유 있게 통과했습니다.

## 배정 (아웃라인 고정, `_allocate_devices` 산출)

| 씬 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| `pattern_interrupt` | none | direct_address | none | format_change | tone_shift | direct_address | pov_shift | none |
| 배정 | question | 2인칭·가정 | — | — | 리액션 | 2인칭 | 리액션 | question |

마지막 씬(8)이 장치를 받았고(ablation arm A의 구멍 ①), `hypothetical`이 자기 슬롯을 받았습니다(구멍 ②).

## 결과 (control vs pass 3)

| | control (12.6) | after (12.7) |
|---|---|---|
| 극적 질문 (총 / 사용 씬) | 9 / **8of8** | 2 / **2of8** |
| 2인칭 (총 / 사용 씬) | 7 / 6of8 | 2 / 2of8 |
| 상황 가정 (총 / 사용 씬) | 5 / 4of8 | 2 / 2of8 (손 분류 후 **1 / 1of8**) |
| 리액션 (총 / 사용 씬) | 9 / 6of8 | 8 / 5of8 (손 분류 후 **3 / 3of8**) |
| 평균 문장 길이 | 33.1자 | 41.2자 |
| 문장 수 | 52 | 45 |
| 앞 씬과 연결하며 시작 | **0/7** | **7/7** |
| 총 어절 | 417 | 445 |
| 오디오 | 168.93s | 181.75s |
| **WPM** | 148.1 | **146.9** (상한 165) |
| 어절 spread (max/min) | 2.03 | 1.32 |
| `word_budget` 준수 | — | 8/8 씬 ±20% 이내 (최대 +17.5%) |
| `review_overall_pass` | true | true |
| `critic_verdict` | retry | retry |

**배정 준수:** 계기 출력 그대로 질문 `배정 [1,8] = 실제 [1,8]`, 2인칭 `배정 [2,6] = 실제 [2,6]`. 배정 없는 씬 3·4는 네 장치 모두 0입니다.

`first_sentences.py`가 pass 3 도입부 여덟 줄을 그대로 찍습니다 — "앞 씬과 연결하며 시작 7/7"은 그 출력에 대한 사람의 판정이고, 계기가 아니라 판정임을 명시합니다. control 쪽 같은 출력에서는 씬 2~8 중 앞 씬 상태를 짚고 여는 것이 하나도 없습니다(0/7).

### 리액션·가정은 계기를 손으로 다시 읽어야 합니다 (AC9)

`count_devices.py`는 **서술자 태도어와 대상 형용사를 구분하지 못합니다**(스크립트 docstring이 밝힌 한계). 배정 밖으로 잡힌 히트를 문장째 꺼내 분류했습니다:

| 씬 | 히트 | 문장 | 판정 |
|---|---|---|---|
| 1 | 기괴 | "…목숨을 빼앗은 이 **기괴한** 의사는…" | 대상 형용사 |
| 2 | 섬뜩 | "그 **섬뜩한** 순간이 지난 뒤…" | 대상 형용사 |
| 2 | 놀랍게 | "**놀랍게도**, 이 개체는 … 말을 건넸습니다." | **서술자 태도 — 진짜 이탈 1건** |
| 5 | 기괴 | "…완전히 죽지도 않은 **기괴한** 상태였습니다." | 대상 형용사 |
| 6 | 기괴 | "시체가 일어선 그 **기괴한** 광경 뒤로…" | 대상 형용사 |
| 8 | (가정) | "…보지 못하는 쪽이 **우리라면**, … 의사일까요?" | 조건절 `라면` 오검출 — 배정된 질문 안 |

즉 **서술자 리액션은 배정된 씬 5·7에 각 1회**(control은 8씬 중 6씬), **상황 가정은 배정된 씬 2에 1회**(control 5회)가 실제 값이고, 이탈은 **씬 2의 "놀랍게도" 1건**입니다. 이 어휘는 pass 1에서도 배정 밖 씬에서 나왔습니다 — 문장 첫머리 부사 `놀랍게도`가 자기검사를 잘 빠져나갑니다. 남은 결함으로 기록합니다.

### 접지 — 두 부류를 구분해서 (AC8)

writing 단계가 **새로** 만든 접지 위반은 **0건**입니다. 크리틱·리뷰가 잡은 사실 지적은 씬 7 하나이고, 아웃라인이 만든 것을 작성자가 지시대로 옮긴 것입니다.

| 씬 | 지적 | 아웃라인 원문 | 귀속 |
|---|---|---|---|
| 7 | 마스크가 "융합된 것으로 **보인다**"인데 "완전히 융합되어 있었죠 / 외형 전체가 하나의 해부학적 구조"로 단언 (critic `ungrounded_claim` + review `invented_content`) | `event.consequence` = "마스크가 융합된 것이며 … 해부학적 구조임이 **드러났다**", `key_points` = "마스크는 착용이 아니라 융합", "외형 전체가 해부학이다" — `fact_references`만 "…로 보인다"를 지킴 | **structure** (12.8) |

ablation이 세 arm 모두에서 기록한 헤지 손실 패턴 그대로입니다(`ablation.md` 귀속 표). control도 같은 씬에서 같은 지적을 받았습니다. 이 스토리의 회귀가 아닙니다.

pass 2에서 이 위반이 씬 8까지 번졌던 것은 **이 스토리가 만든 것**이 맞고, 위에서 규칙을 좁혀 닫았습니다.

### 남은 흠 — 축소하지 않고 적습니다

1. **"놀랍게도" 1건** (씬 2, 배정 밖 리액션). pass 1에서도 같은 어휘가 샜습니다.
2. **문장 길이 규칙이 여전히 초과됩니다.** 프롬프트는 "기본 15~25자, 연결 구문은 40자까지, 40자급은 한 씬에 두세 개"인데 pass 3은 씬 1·2에서 4개씩, 최장 75자입니다. 다만 control도 씬 1·2·3에서 3~4개(최장 53자)로 옛 규칙(15~25자)을 어겼습니다 — 이 프롬프트의 문장 길이 항목은 예나 지금이나 상한이 아니라 성향 조절입니다. WPM·예산이 다 통과했으므로 완화 폭은 조이지 않았습니다.
3. **자막 큐가 더 쪼개집니다.** `subtitle.py:182`의 `_CUE_CHAR_SOFT_CAP = 44`를 넘는 문장이 control 8/52 → pass 3에서 더 많습니다. 설계된 분할 경로라 결함은 아니지만, 화면 리듬이 달라지는 것은 사실이고 이 스토리는 재지 않았습니다.
4. **씬 4의 `report_tone`은 그대로입니다.** control도, 세 런 모두 같은 씬에서 같은 지적을 받았습니다 — 격리-절차 비트 자체의 문제이지 배정이 만든 것이 아닙니다.
5. **런당 1표본입니다** (`gotcha_measure-densely-before-declaring-a-fix`). 배정 준수는 결정론이라 1런으로 충분하지만, 문장 길이·WPM·연결 비율은 세 런의 값이며 그 폭(41.2~45.9자, 146.9~158.5 WPM)이 곧 이 지표들의 관측된 변동입니다.
