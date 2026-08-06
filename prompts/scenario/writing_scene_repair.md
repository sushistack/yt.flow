# Scene-Scoped Writing Repair

You are repairing a validated subset of a Korean SCP narration. Preserve the input order and return exactly one output scene for every input scene. Keep every `scene_num` unchanged. Do not add, remove, duplicate, or reorder scenes. Change only narration and scene metadata needed to resolve the supplied feedback. Output YAML only.

Use Korean narration, retain factual fidelity, and follow the storytelling guide. Narration must be a single flowing paragraph even when represented with YAML block syntax.

## 사실 접지 규칙 (Fact Grounding) — 최우선

수리 대상 씬마다 Stage 2 구조 항목이 함께 제공됩니다. 그 항목의 `fact_references`가 이 씬에서
당신이 가진 사실의 전부입니다 (원문도 리서치 패킷도 제공되지 않습니다).

- 수리된 나레이션도 그 씬의 `fact_references` 문장들을 재료로 삼아야 합니다. **수리하면서 원래
  들어 있던 구체적 사실을 빼고 분위기 문장으로 대체하지 마세요.**
- `fact_references`에 없는 사실(숫자·등급·날짜·사건·능력)을 새로 단언하지 마세요.
- 몰입 기법은 사실을 꾸미는 도구이지 사실을 대체하는 도구가 아닙니다. 다른 SCP 영상에 그대로
  붙여넣어도 말이 되는 문장이면 접지에 실패한 것입니다.

## 리텐션 계약 준수

수리는 그 씬의 구조 계약을 깨뜨릴 수 없습니다:

- `event.consequence`를 다른 결과로 바꾸지 마세요.
- `loops_planted`에 있는 질문은 여전히 열어둔 채로, `loops_closed`에 있는 질문은 여전히 이 씬에서
  답해야 합니다. 약속된 회수를 누락하면 안 됩니다.
- `pattern_interrupt`가 `none`이 아니면 그 기법을 계속 사용하세요.
- `hook_type`이 `none`이 아니면 (Scene 1) 첫 문장은 계속 그 훅 유형이어야 합니다.
- `word_budget`(공백 기준 어절 수)을 ±20% 안에서 유지하세요.

## Storytelling Format Guide

{{format_guide}}

{{glossary_section}}

## Task

{{parse_error}}

Repair these scenes for {{scp_id}} using the feedback below.

## Scene Feedback

{{scene_feedback}}

## Original Scene Objects

{{original_scenes}}

## Scene Structure (from Stage 2)

같은 순서로 짝지어진 구조 항목입니다 — 첫 번째 구조 항목은 첫 번째 원본 씬의 계획입니다.

{{scene_structure}}

## Visual Identity Profile

{{scp_visual_reference}}

Return one YAML object with a single `scenes` list. Each scene must retain its original `scene_num` and contain non-empty `narration`.
