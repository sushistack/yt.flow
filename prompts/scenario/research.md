# Stage 1: SCP Research & Visual Identity Analysis

## Storytelling Format Guide

Use the following format guide to identify narrative hooks and dramatic structure during research.

{{format_guide}}

You are a creative director preparing materials for a viral SCP YouTube video about {{scp_id}}. You need to identify the most dramatic, visually striking, and emotionally resonant elements.

## Source Data

### SCP Fact Sheet
{{scp_fact_sheet}}

### SCP Full Document
{{main_text}}

{{glossary_section}}

## Task

{{parse_error}}

Analyze the provided SCP data and produce a research packet. Respond with ONLY valid YAML, no prose, no markdown fences:

```yaml
core_identity: |
  Official designation, object class, primary anomalous properties, containment
  summary, discovery/origin context, key incidents — as flowing text.
frozen_descriptor: |
  A single dense physical description covering: Silhouette & Build, Head/Face,
  Body Covering, Hands & Limbs, Carried Items, Organic Integration Note (if
  applicable). This will be reused verbatim across all image prompts for
  visual consistency.
entity_sheet: |
  A compact entity reference DISTINCT from frozen_descriptor — 2-3 sentences
  naming the designation, the single most recognizable visual trait, and one
  environmental/behavioral signature (a smell, sound, mark, or aftermath it
  leaves). Inserted into EVERY shot prompt, even ones where the entity itself
  is off-screen, so the environment stays visually anchored to this entity's
  identity.
story_logline: |
  One or two punchy sentences stating the video's overall dramatic
  premise/hook — the story-level 'what is this video about' anchor. Must stay
  consistent in tone across every scene's shots.
dramatic_beats: "6-10 dramatic moments from the document suitable for video scenes, ordered from introduction to climax, each noting its emotional tone."
environment: "Primary settings/locations, lighting conditions, ambient sounds/environmental factors, overall mood and horror subgenre."
hooks: |
  Opening hook candidates (3, using different hook types: Question/Shock/Mystery/Contrast,
  each a single punchy Korean sentence that does NOT mention SCP classification),
  the mid-video twist, the closing mystery, and a 'what if' moment.
source_evidence:
  incident_log: true
  experiment_log: false
  interview_log: false
  recovery_report: false
  dated_chronology: true
story_archetype: "incident_first"
archetype_rationale: |
  One or two sentences naming the specific evidence in the source document above
  that makes this archetype the right shape for this episode.
```

Every field is a non-empty string, derived only from the SCP source text above. `frozen_descriptor` must not be empty — it is the single source of visual truth for every later stage. `entity_sheet` and `story_logline` must also not be empty — they carry story-level and entity-level context into every `visual_breakdown` shot prompt.

## `source_evidence` — 원문 해부 인벤토리 (사실 보고, 판단 아님)

위 원문에 **실제로 존재하는** addendum/기록 유형만 `true`로 표시하세요. 다섯 키는 고정이며 전부
포함해야 합니다. 이것은 취향이나 계획이 아니라 **원문에 대한 사실 보고**입니다.

| 키 | `true` 조건 |
|----|-------------|
| `incident_log` | 사건 기록/사고 보고(Incident, Addendum: Incident, 격리 위반 기록)가 원문에 있음 |
| `experiment_log` | 실험 기록/시험 로그(Experiment Log, Test Log)가 원문에 있음 |
| `interview_log` | 인터뷰/심문 기록(Interview Log, Interviewed:/Interviewer: 형식)이 원문에 있음 |
| `recovery_report` | 회수/발견 경위 기록(Recovery, Discovery, Acquisition Log)이 원문에 있음 |
| `dated_chronology` | 날짜가 붙은 항목이 2개 이상 있어 시간 순서를 잡을 수 있음 |

- ❌ 원문에 없는데 "있으면 좋겠다"고 `true`로 적지 마세요. 그 한 줄이 뒤 단계에서 **없는 인터뷰나
  없는 연표를 지어내게** 만듭니다.
- ✅ 확실하지 않으면 `false`.

## `story_archetype` — 닫힌 4종 중 하나 (원문 적합도로 선택)

정확히 다음 네 값 중 하나만 쓰세요. 새로 만들거나 조합하지 마세요.

| 값 | 이야기 모양 | 필요한 `source_evidence` |
|----|-------------|--------------------------|
| `incident_first` | 충격적 사건 → 미스터리 확장 → 정체 공개 → 미해결 여운 | 없음 (항상 가능) |
| `discovery_log` | 날짜순 증거 발견 → 가설 변경 → 위험한 함의 → 기록의 공백 | `recovery_report` 또는 `dated_chronology` |
| `interview_testimony` | 증언/정황 → 신뢰성 균열·모순 → 교차 확인된 핵심 사건 → 남는 불확실성 | `interview_log` |
| `containment_breach_realtime` | 안정된 일상 → 촉발 → 압축된 실시간 대응 확대 → 결과/여파 | `incident_log` |

**선택 규칙:**
- 위 표에서 **필요 증거가 `source_evidence`에 `true`인 값들만** 후보입니다. 후보가 여럿이면 원문이
  가장 풍부하게 지지하는 하나를 고르세요.
- 후보가 `incident_first` 하나뿐이면 `incident_first`를 쓰세요. 그것이 정답이며 열등한 선택이
  아닙니다. **다양성보다 사실성이 우선입니다.**
- ❌ 순환/로테이션 금지, 무작위 금지, "이번엔 다른 걸 써보자" 금지. 선택의 근거는 오직 원문입니다.
- 필요 증거가 없는 값을 골라도 파이프라인이 코드로 기각하고 `incident_first`로 되돌립니다 —
  이득이 없고 로그에 남습니다.

`archetype_rationale`은 비어 있으면 안 됩니다. **원문의 어떤 기록을 근거로 골랐는지** 구체적으로
쓰세요 (예: "Addendum 173-2의 회수 경위와 1993/2008 두 날짜 항목이 발견 기록 서사를 지지함").
"더 극적이라서", "시청자가 좋아할 것" 같은 취향 서술은 근거가 아닙니다.
