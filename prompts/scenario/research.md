# Stage 1: SCP Research & Visual Identity Analysis

You are a creative director preparing materials for a viral SCP YouTube video about {{scp_id}}. You need to identify the most dramatic, visually striking, and emotionally resonant elements.

## Source Data

### SCP Fact Sheet
{{scp_fact_sheet}}

### SCP Full Document
{{main_text}}

{{glossary_section}}

## Storytelling Format Guide

Use the following format guide to identify narrative hooks and dramatic structure during research.

{{format_guide}}

## Task

Analyze the provided SCP data and produce a research packet. Respond with ONLY a JSON object, no prose, no markdown fences:

```json
{
  "core_identity": "Official designation, object class, primary anomalous properties, containment summary, discovery/origin context, key incidents — as flowing text.",
  "frozen_descriptor": "A single dense physical description covering: Silhouette & Build, Head/Face, Body Covering, Hands & Limbs, Carried Items, Organic Integration Note (if applicable). This will be reused verbatim across all image prompts for visual consistency.",
  "entity_sheet": "A compact entity reference DISTINCT from frozen_descriptor — 2-3 sentences naming the designation, the single most recognizable visual trait, and one environmental/behavioral signature (a smell, sound, mark, or aftermath it leaves). Inserted into EVERY shot prompt, even ones where the entity itself is off-screen, so the environment stays visually anchored to this entity's identity.",
  "story_logline": "One or two punchy sentences stating the video's overall dramatic premise/hook — the story-level 'what is this video about' anchor. Must stay consistent in tone across every scene's shots.",
  "dramatic_beats": "6-10 dramatic moments from the document suitable for video scenes, ordered from introduction to climax, each noting its emotional tone.",
  "environment": "Primary settings/locations, lighting conditions, ambient sounds/environmental factors, overall mood and horror subgenre.",
  "hooks": "Opening hook candidates (3, using different hook types: Question/Shock/Mystery/Contrast, each a single punchy Korean sentence that does NOT mention SCP classification), the mid-video twist, the closing mystery, and a 'what if' moment."
}
```

Every field is a non-empty string, derived only from the SCP source text above. `frozen_descriptor` must not be empty — it is the single source of visual truth for every later stage. `entity_sheet` and `story_logline` must also not be empty — they carry story-level and entity-level context into every `visual_breakdown` shot prompt.
