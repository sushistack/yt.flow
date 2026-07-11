# Scene-Scoped Writing Repair

You are repairing a validated subset of a Korean SCP narration. Preserve the input order and return exactly one output scene for every input scene. Keep every `scene_num` unchanged. Do not add, remove, duplicate, or reorder scenes. Change only narration and scene metadata needed to resolve the supplied feedback. Output YAML only.

Use Korean narration, retain factual fidelity, and follow the storytelling guide. Narration must be a single flowing paragraph even when represented with YAML block syntax.

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

## Visual Identity Profile

{{scp_visual_reference}}

Return one YAML object with a single `scenes` list. Each scene must retain its original `scene_num` and contain non-empty `narration`.
