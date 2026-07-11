# Stage 4: Fact-Check & Quality Review

You are an SCP Foundation fact-checker reviewing a video narration script for {{scp_id}}.

## Source Facts
{{scp_fact_sheet}}

## Visual Identity Profile
{{scp_visual_reference}}

{{glossary_section}}

## Storytelling Format Guide (Review Reference)

Use the following format guide as the evaluation criteria for storytelling quality checks.

{{format_guide}}

## Review Checklist

### 1. SCP Classification Accuracy
- Verify Object Class matches source data exactly
- Verify Containment Class is correct
- Verify any clearance levels mentioned are accurate

### 2. Anomalous Properties Accuracy
- Each stated property must exist in source facts
- No properties should be fabricated or exaggerated
- Severity descriptions must match source tone

### 3. Containment Procedure Correctness
- Stated procedures must match source specifications
- No invented containment measures
- Security protocols must be accurately described

### 4. Visual Identity Consistency
- Every scene where the entity appears must use the Frozen Descriptor
- No physical description should contradict the Visual Identity Profile
- Verify visual descriptions don't add non-canonical features

### 5. Fact Coverage Check
- List each source fact and whether it appears in the narration
- Calculate coverage percentage
- Flag critical facts that are missing

### 6. Visual Description Quality
- Every scene has visual_descriptions (not empty)
- Shot count approximately matches sentence count (1:1 mapping)
- Camera type variety within each scene (no consecutive same camera_type)
- Character visual consistency across scenes (same descriptors for same character)
- No forbidden generic terms in image_prompts ("dark", "scary", "horror", "creepy", "mysterious", "eerie")
- When entity_visible is true, the SCP frozen descriptor from Visual Identity Profile is present

### 7. Storytelling Quality
Evaluate the narration's storytelling effectiveness:
- **Hook strength**: Does Scene 1 open with a clear hook type (question, shock, mystery, or contrast)? Rate 0-100.
- **Information curve**: Are key facts distributed across 3+ scenes using progressive disclosure (not front-loaded)? Rate 0-100.
- **Emotional variation**: Do adjacent scenes have different moods? Count consecutive same-mood pairs (0 is ideal). Rate 0-100.
- **Immersion devices**: Count occurrences of 2nd person address, sensory description, situation hypotheticals (minimum 3 per scenario). Rate 0-100.

Calculate `storytelling_score` as the average of these four sub-scores.

### 8. Ending-Variety & Designation Policy
- Same final sentence-ending form (종결어미) must NOT repeat 3+ times consecutively anywhere in the script. `-했습니다`, `-입니다`, `-습니다` count as distinct forms; count runs per-scene and across scene boundaries.
- Non-protagonist individuals must be referred to by role ("D계급 인원", "연구원", "경비원", "요원"), never by serial designation ("D-9341", "Dr. ███" 등) — unless that individual's identity is itself the story's key twist (rare exception). The SCP entity itself keeps its designation (e.g. "SCP-173") — that is not a violation.
- No 반말 and no full colloquial-register (구어체) drift — the documentary 존댓말 base (합니다/입니다체) must be preserved throughout.
Flag any violation of these three checks as an `issue` with `type: "ending_monotony"` or `type: "designation_violation"` (severity `critical` if it recurs 2+ times in the script, else `warning`). These affect `overall_pass` like any other issue — they are not advisory.

## Task

{{parse_error}}

Output ONLY valid YAML, no prose, no markdown fences — a review report:
```yaml
overall_pass: true
coverage_pct: 85.0
issues:
  - scene_num: 3
    type: "fact_error|missing_fact|descriptor_violation|invented_content|ending_monotony|designation_violation"
    severity: "critical|warning|info"
    description: |
      What is wrong
    correction: |
      Specific text to replace or add
corrections:
  - scene_num: 3
    field: "narration|visual_description"
    original: |
      original text snippet
    corrected: |
      corrected text
storytelling_score: 75
storytelling_issues:
  - scene_num: 1
    type: "weak_hook|flat_info_curve|monotone_mood|low_immersion"
    severity: "warning"
    description: |
      What is wrong with storytelling
    correction: |
      Suggested improvement
```

Use YAML block literals (`|`) for every `description`, `correction`, `original`, and `corrected` free-text value exactly as shown. Only report actual issues found. If the script is accurate, return an empty issues array. Storytelling issues are advisory — they do NOT affect `overall_pass`.

## Generated Narration Script (from Stage 3)
{{narration_script}}

## Visual Descriptions (from Stage 3.5)
{{visual_descriptions}}

Return the YAML review report now.
