# Story 12.8 재측정 — 아웃라인 접지와 귀속

2026-08-16. SCP-049, 시딩된 `production` 프롬프트, **두 번의 완전 라이브 런**.
아무것도 고정하지 않았습니다 — 이 스토리가 바꾼 것이 아웃라인이므로 아웃라인을 고정하면
측정 대상을 고정하는 셈입니다. 12.7의 드라이버와 다른 점은 그것뿐입니다.

```
uv run python .../run_outline.py --run-id 12-8-run1 --out .../run1_scenes.json
uv run python .../run_outline.py --run-id 12-8-run2 --out .../run2_scenes.json

uv run python .../calibrate.py                       # 임계값을 고른 분포
uv run python .../attribute.py --baseline            # ablation.md 귀속 표의 기계 재현
uv run python .../attribute.py .../run2_scenes.json --sentence '…' --sentence '…'
```

실제 DeepSeek(research/structure) + Gemini(writing/review/critic). TTS·GPU 없음 —
이 스토리는 텍스트만 다룹니다.

## 0. 한 줄

**아웃라인이 원문을 인용하기 시작했고, 인용은 26/26 전부 원문에서 찾아졌으며, 세 arm 전부를
관통했던 "appears fused → 융합되어 있다" 단언은 두 런 모두에서 사라졌습니다.** 남은 접지 위반은
런2의 두 건이고, 그중 하나는 스크립트가 아웃라인 `event.what`으로 정확히 되짚어 줍니다.

## 1. 축자 인용 (AC1) — 26/26

| | run1 | run2 | ablation baseline |
|---|---|---|---|
| 씬 수 | 8 | 9 | control 8 / A 9 / B 8 |
| `fact_references` 항목 | 15 | 11 | control 16 / A 12 / B 18 (전부 인용 없음) |
| `quote_verified: true` | **15 / 15** | **11 / 11** | 해당 없음 (인용 필드가 없었음) |
| `quote_not_found` 노트 | 0 | 0 | — |
| structure LLM 호출 | 2 | 2 | 1 |

두 런 모두 **교정 재시도를 한 번 썼습니다** (`stages`의 structure LLM 호출이 2회).
> 측정 당시엔 `event_unsupported`도 교정 대상이어서 "sink에 노트가 남았다 = 두 번째 시도까지
> 갔다"로 읽었지만, 리뷰 수정으로 `event_unsupported`는 재시도를 사지 않습니다. 두 런이 재시도를
> 쓴 이유가 인용이었는지 `event`였는지는 이 덤프로 여전히 나눌 수 없습니다(§5).

**세 번째 패스는 없습니다**: `stages`가
두 런 모두 `research → structure → writing → … → writing_scene_repair → … → tts_normalize`이고
`structure`는 한 번뿐입니다. 재시도 후 인용 실패는 0건이었습니다 — 재시도가 실제로 고쳤습니다.

## 2. 헤지 보존 (AC2) — ablation의 arm-독립 결함이 사라졌다

`ablation.md:288`은 control 씬7 · A 씬1 · A 씬6 · B 씬4가 전부 원문의 `appears`를 떨어뜨리고
*"가면이 융합되어 있다"*로 단언했다고 기록합니다. 두 런 모두 **`hedge_dropped` 0건**이고,
아웃라인이 헤지를 문장에 그대로 싣고 있습니다:

```
run2 씬1·씬2  statement: "SCP-049는 후드 달린 검은 로브와 얼굴에 융합된 것으로 보이는 도자기 가면을 쓰고 있다"
              quote    : "wearing a hooded black robe and a ceramic mask that appears fused to the being's head"

run2 씬9      statement: "그의 도자기 가면은 얼굴에 융합된 것으로 보이지만 그 이유는 모른다"
              quote    : "a ceramic mask that appears fused to the being's head"
```

`appears` ↔ `~것으로 보이는`. 이건 한 표본이 아니라 두 런 × 여러 씬에서 같은 문장으로 반복되며,
`_check_fact_evidence`의 헤지 검사가 아니라 **프롬프트 규칙**이 만든 결과입니다(검사는 0건을
보고했을 뿐입니다). 다만 두 런 다 같은 SCP·같은 문장이므로 일반화는 여기까지입니다.

## 3. `event` 지지 (AC3) — 노트 6건, 손으로 판정하면 절반이 오탐

재시도 후에도 남아 게이트에 실린 노트 전부:

| 런 | 씬 | 필드 | 값 | 그 씬의 fact statement | 판정 |
|---|---|---|---|---|---|
| 1 | 8 | consequence | 그 병이 무엇인지는 관찰자에게 보이지 않는다 | 그가 치료하려는 '대역병'은 오직 그만이 볼 수 있다고 믿어진다 | **오탐** — 같은 사실의 반대편 서술 |
| 2 | 1 | consequence | 그는 곧 사망했다 | SCP-049의 맨손 접촉은 살아있는 인간을 죽음에 이르게 한다 | **오탐** — 죽음/사망 동의어 |
| 2 | 2 | what | 격리실 내부를 관찰했다 | (가면·로브 서술뿐) | 경계 — 씬의 사실 범위 밖이지만 연출 행위 |
| 2 | 7 | what | 격리실 안에 수용되어 있다 | 시신이 SCP-049-2로 재생된다 | 경계 — 원문엔 있으나 **이 씬의** 사실엔 없음 |
| 2 | 7 | consequence | 그 존재는 계속해서 움직이며 불안을 유발한다 | 〃 | **정탐** — "불안을 유발한다"는 사건이 아니라 연출 지시 |
| 2 | 8 | consequence | 그의 진짜 환자가 누구인지 의문이 생긴다 | SCP-049는 자신만이 인식하는 대역병을 치료하려 한다고 믿는다 | **정탐** — 시청자 효과 서술 |

오탐 2 / 경계 2 / 정탐 2. `calibrate.py`가 예고한 그대로입니다 — 문자 트라이그램은 한국어
동의어(죽음/사망)를 못 넘습니다. 정탐 2건은 공교롭게도 `structure.md`가 이미 금지한
*"형용사/의도 서술"*이고, 접지 검사가 그 규칙의 첫 기계 집행자가 됐습니다.

**놓친 것도 있습니다.** run2 씬9의 `event.what` *"SCP-049에 대한 추가 조사를 중단했다"*는
원문에 없는 재단의 행정 결정인데 **노트가 나가지 않았습니다**: overlap 0.238로, 씬의 fact
statement가 `SCP-049`라는 개체명을 공유한다는 이유만으로 임계값 0.03을 한참 넘깁니다.
그리고 아래 §4에서 보듯 **그것이 이 런에서 실제로 나레이션까지 내려간 위반**입니다.
`calibrate.py`가 "3건 중 1건"이라고 적어 둔 재현율이 라이브에서 그대로 재현됐습니다.

## 4. 귀속 (AC4/AC5/AC8) — 아웃라인 유래 위반 수

| | control | A | B | **run1** | **run2** |
|---|---|---|---|---|---|
| 아웃라인 유래 접지 위반 (`attribute.py`) | 1 | 2 | 4 | **0** | **1** |
| 손으로 센 baseline (`ablation.md:283-288`) | 1 | 2 | 4 | — | — |
| `attribute.py --baseline`이 센 값 | 0 | 2 | 5 | — | — |

baseline 열의 두 줄이 다른 이유를 먼저 적습니다. `ablation.md`의 표는 **행**을 세고
스크립트는 **문장**을 셉니다: B의 4행 중 씬8 행이 두 문장(`실패한 재활성화 기록` /
`더 많은 환자를 요구하는 메모`)이라 5가 되고, control의 1행은 유일하게 임계값 아래로 떨어지는
문장(overlap 0.045, `calibrate.py`가 이미 기록한 그 한 건)이라 0이 됩니다. 즉 표의
control 1 / A 2 / B 4는 사람이 센 값이고, 0 / 2 / 5는 같은 문장들에 같은 규칙을 적용한
기계값입니다. 두 baseline을 나란히 둡니다 — 어느 한쪽으로 맞추려고 임계값을 움직이지 않았습니다.

`--baseline`은 **손으로 지목한 문장만** 셉니다(`channels=False`). 세 덤프에도 크리틱
`ungrounded_claim` 노트가 있지만 그중 둘(A 씬6 · B 씬3)은 손으로 센 표와 **같은 위반**이라,
두 채널을 함께 세면 같은 건을 두 번 세고 `ablation.md`와 비교할 수 없게 됩니다.

### run2의 두 건, 기계가 답한 출처

```
씬 5  [writing]  overlap 0.093 (threshold 0.1)
  narration : 실험 기록 공사구 공일, "대상이 손끝을 움직여, 곧바로 시신에 집도를 시작함."
  최고 일치  : fact_references[1] (0.093) 대상 사망 후 SCP-049는 시신에 수술을 집도하고, 이를 SCP-049-2로 재생시킨다

씬 9  [outline]  overlap 0.290 (threshold 0.1)
  narration : 그 혼란스러운 물음 끝에, 재단은 추가 조사를 중단했습니다.
  최고 일치  : event.what (0.290) SCP-049에 대한 추가 조사를 중단했다
```

위 두 줄은 나레이션 문장을 손으로 `--sentence`에 넣어 얻은 것입니다. 리뷰 수정 이후에는
**같은 판정을 코드가 스스로 내립니다** — 아래 §5 참조.

씬5의 *"실험 기록 049-01"*은 아웃라인에 없는 형식을 작성자가 만든 것이고, 씬9의
*"재단은 추가 조사를 중단했습니다"*는 **아웃라인 `event.what`을 그대로 실행한 것**입니다.
스토리의 주장이 그대로 재현됐습니다: 크리틱은 두 건 모두 작성자에게 청구했고, 한 건은
씬 리페어로 고칠 수 있으며 다른 한 건은 고칠 수 없습니다.

### 게이트가 실제로 뭐라고 말했나 (측정 당시)

```
run1  categories: descriptor_violation, outline_grounding, report_tone
      outline_originated: {"scenes": [8], "note": "…씬 리페어로는 고칠 수 없습니다 — 아웃라인 재생성이 필요합니다"}
run2  categories: descriptor_violation, outline_grounding, report_tone, ungrounded_claim
      outline_originated: {"scenes": [1, 2, 7, 8], …}
```

**이 두 줄은 리뷰에서 결함으로 판정됐습니다.** `outline_originated`가 귀속된 항목이 아니라
*접지 노트가 언급한 모든 씬*을 담고 있었기 때문입니다. run1의 [8]은 §3 표가 스스로 **오탐**이라고
적어 둔 `event_unsupported` 한 건이고(죽음/사망 동의어), run2의 [1,2,7,8]도 전부
`event_unsupported`입니다 — 즉 두 런 모두 "아웃라인을 재생성하라"는 지시가 트라이그램 잡음
위에서 발화했습니다. 수정 후의 값은 §5에 있습니다.

로그에도 같은 문장이 남았습니다(AC5의 "로그 AND 게이트"):

```
scenario: scene(s) [1, 2, 7, 8] carry OUTLINE-originated grounding findings — the scene repair
that just ran could not have fixed them (structure_step runs once per run and the full-rewrite
fallback reuses the same outline). Regenerating the outline is the only path.
```

## 5. 리뷰 이후 — 커밋된 덤프에서 다시 뽑은 귀속

**측정 당시 `origin` 스탬프는 라이브에서 한 번도 발화하지 않았습니다.** 스펙이 귀속을 붙인
채널은 review의 `grounded_contradictions`인데, 두 런 모두 `review_overall_pass: true`에
`grounded_contradictions: []`였습니다. 실제로 접지 위반을 잡아낸 쪽은 **크리틱의
`ungrounded_claim` 씬 노트**이고, 그 채널에는 `origin` 필드가 아예 없었습니다
(`project_12-2-review-done`: 라이브 증거가 닿지 않은 경로부터 파라).

리뷰에서 그 채널까지 스탬프를 확장했고, **새 라이브 런은 쓰지 않았습니다.** 아래는 커밋된
`run1_scenes.json` / `run2_scenes.json`에 새 경로를 그대로 돌린 결과입니다:

```
uv run python .../attribute.py .../run1_scenes.json .../run2_scenes.json   # --sentence 없이
```

| | run1 | run2 |
|---|---|---|
| 플래그된 항목 (두 채널 합) | 0 | 2 (둘 다 `critic.ungrounded_claim`) |
| `origin: outline` | **0** | **1** — 씬9, overlap 0.198 vs `event.what` |
| `origin: writing` | 0 | 1 — 씬5, overlap 0.085 |
| 새 `outline_originated.scenes` | **없음** | **[9]** |

§4에서 사람이 `--sentence`로 얻은 판정(run1 0 / run2 1, 씬9만 아웃라인 유래)과 **정확히
같습니다** — 이번엔 스크립트가 아니라 런타임과 같은 입력·같은 규칙으로 나온 값입니다.
바뀐 것 두 가지:

- 매칭은 `issue` **한 필드만** 씁니다. `issue + suggestion`을 합치면 씬5가 0.085 → 0.132로
  올라가 아웃라인 유래로 뒤집힙니다 — `suggestion`은 크리틱이 제안하는 *고쳐 쓴 문장*이라
  구조상 접지돼 있기 때문입니다. 이 한 건이 그 선택의 유일한 증거이고, 표본은 2건입니다.
- 옛 `outline_originated`(§4의 [8] / [1,2,7,8])는 전부 `event_unsupported` 노트에서 왔고
  이제는 그 코드가 이 줄을 채우지 못합니다. 새 값은 위 표대로 **없음 / [9]** 입니다.

## 6. 이 측정이 답하지 못하는 것

- **한 SCP, 두 런.** 아키타입도 두 번 다 `incident_first`였습니다. 인용 26/26은 표본이
  넉넉하지만 헤지 보존은 같은 문장(`appears fused`)의 반복이고, `event_unsupported` 6건은
  6건일 뿐입니다 (`gotcha_measure-densely-before-declaring-a-fix`).
- **귀속 표본은 2건입니다.** 크리틱 채널의 `ungrounded_claim` 노트 두 개 — 하나는 아웃라인,
  하나는 작성자. 두 판정 모두 손으로 센 값과 일치하지만, 2건은 2건입니다.
- **재시도 피드백은 여전히 500자에서 잘립니다.** 리뷰 수정으로 예산이 규칙 문장 대신 문제된
  인용 텍스트로 갑니다. 두 런 모두 옛 압축 목록만으로도 인용을 전부 고쳤으므로, **새 피드백이
  더 낫다는 라이브 증거는 없습니다** — 노트가 여러 건인 아웃라인에서 잘림이 어디서 일어나는지도
  재지 않았습니다.
- **헤지 문맥 창(32자)과 인용 최소 길이(12자)는 이 26개 인용에 대해 무증상이라는 것만 압니다.**
  창을 40자로 넓히면 이 표본에서 오탐이 1건 생기고, 라이브 최단 인용은 28자입니다. 두 상수 모두
  "관측된 오탐 0" 위에 서 있을 뿐 분리도가 측정된 값이 아닙니다.
- **`event_unsupported`가 재시도를 사지 않게 된 뒤의 재시도 횟수는 재지 않았습니다.** 두 런의
  재시도 원인이 인용이었는지 `event`였는지 이 덤프로는 나눌 수 없습니다(첫 시도의 노트는
  기록되지 않습니다). 이제 `event`는 재시도를 살 수 없으므로 호출 수가 줄 수 있지만, 그건
  다음 라이브 런에서 확인할 일입니다.

## 7. 작성자의 눈가림 (AC6) — 기계 확인

```
run1  quotes: 15  narration으로 새어 나간 것: 0   나레이션 속 영문 단어: 0
run2  quotes: 11  narration으로 새어 나간 것: 0   나레이션 속 영문 단어: 0
```

두 경계(`_writing_scene_brief`, `writing_scene_repair`의 `subset_structure`)는 단위 테스트로
직접 고정돼 있고, 위 숫자는 그 결과를 산출물 쪽에서 다시 확인한 것입니다.

## 산출물

| | run1 | run2 |
|---|---|---|
| 덤프 | `run1_scenes.json` | `run2_scenes.json` |
| 씬 / 아웃라인 / RAW 노트 / 게이트 페이로드 | 전부 그 안에 | 〃 |

`calibrate.py`(임계값), `attribute.py`(귀속), `run_outline.py`(드라이버), `seeding.md`(시딩)
가 이 문서의 모든 숫자를 재산출합니다.
