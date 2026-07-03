# scenario stage: multi-stage generation chain

## Context

`scenario_node` (Story 1.5) currently does one DeepSeek call: `scp_text` in, a `{"scenes": [...]}` JSON blob out. A live real-mode run (2026-07-03) surfaced that this single-shot design was never actually validated against real content — the `scenario` Langfuse prompt didn't exist, and even a naively-seeded single-shot prompt produces far lower narrative/visual quality than the user wants.

The user's own earlier Go project (yt.pipe, `/mnt/work/projects/yt.pipe/templates/scenario/`) already contains a carefully authored 5-stage chain (research → structure → writing → visual_breakdown → review, plus a `critic_agent`) that yt.flow never finished porting. A deep-research pass (2026-07-03, workflow `wf_097e3122-735`) confirmed this shape is consistent with published practice: decomposing "text → video scenario" into a narrative stage and a separate shot-breakdown stage is a validated pattern (Reflexion, Self-Refine, ViMax), and a bounded (1-pass), criteria-driven critique loop is worth keeping — unconstrained self-critique is a known failure mode.

Top priority stated by the user: output quality, not implementation simplicity or cost.

## Goal

Replace `scenario_node`'s single DeepSeek call with a multi-stage chain, faithfully reusing yt.pipe's authored prompt content, while keeping the stage's external contract unchanged: one `scenario` gate in the UI, `PipelineState.scenes: list[SceneState]` as the only output the rest of the pipeline sees.

## Chain

```
research → structure → writing → visual_breakdown ×N (one per scene) → review + critic_agent
                ↑____________________ retry, bounded to 1 pass, carries quality_feedback ____________________|
```

All calls run inside the existing `scenario_node` / `scenario` LangGraph node and gate. `StageName` (`scenario|image|tts|subtitle|video`) is unchanged — no new gate-reviewable stages, no DB/frontend/SSE changes.

### Stage contracts

| Stage | Langfuse prompt name | Input variables | Output |
|---|---|---|---|
| research | `scenario/research` | `scp_id`, `scp_fact_sheet`=`scp_text`, `main_text`=`scp_text`, `format_guide` (static), `glossary_section`="" | JSON: `core_identity`, `frozen_descriptor`, `dramatic_beats`, `environment`, `hooks` |
| structure | `scenario/structure` | research output, `frozen_descriptor`, `target_duration`=3 (fixed constant), `format_guide` | JSON array of 8-12 scene objects (`scene_num`, `act`, `synopsis`, `key_points`, `emotional_beat`, `estimated_duration_sec`) |
| writing | `scenario/writing` | structure output, `frozen_descriptor`, `format_guide`, `quality_feedback` (empty on first pass) | JSON: `scp_id`, `title`, `scenes[]` (`scene_num`, `narration`, `location`, `characters_present`, `color_palette`, `atmosphere`) |
| visual_breakdown | `scenario/visual_breakdown` | per scene: narration split into numbered sentences (Python-side splitter), scene metadata, `frozen_descriptor`, `character_visual_context`="" (no character system wired in yet) | per scene JSON: `visual_descriptions[]` (`image_prompt`, `negative_prompt`, `sentence_start`, `sentence_end`, `entity_visible`, `camera_type`); empty `image_prompt` allowed for transition-only sentences |
| review | `scenario/review` | assembled narration + visual descriptions, `scp_fact_sheet`, `frozen_descriptor`, `format_guide` | JSON: `overall_pass`, `coverage_pct`, `issues[]`, `corrections[]`, `storytelling_score`, `storytelling_issues[]` |
| critic_agent | `scenario/critic_agent` | assembled scenario JSON, `format_guide` | JSON: `verdict` (`pass`\|`retry`\|`accept_with_notes`), `feedback` (Korean), `scene_notes[]` |

**Deviation from yt.pipe source**: `01_research.md` originally asks for "structured text with clear section headers." This design changes its output contract to strict JSON so `frozen_descriptor` can be extracted programmatically and threaded into every later stage — every other template is used near-verbatim.

### Retry loop

If `critic_agent.verdict == "retry"` or `review.overall_pass == false`: run **exactly one** retry — re-run `writing` with `quality_feedback` populated from `critic.feedback` + `review.issues`, then re-run `visual_breakdown` for all scenes, then re-run `review` + `critic_agent` once more. Whatever comes out of the second pass is accepted regardless of verdict — no open-ended looping (per deep-research finding: unbounded self-critique degrades rather than improves output).

### Sentence splitting

`visual_breakdown` needs narration pre-split into numbered sentences (it's an input, not something the LLM decides). Implemented as a plain Python regex splitter on Korean sentence-ending punctuation — no new dependency.

### Mapping into `PipelineState.scenes`

For each scene: `narration` = writing stage's narration text. `shots` are built from that scene's `visual_descriptions`:
- Non-empty `image_prompt` → new `ShotData` (`shot_id=f"S{scene_num:03d}{i:02d}"`, `sentence_indices` = 0-based range from `sentence_start`/`sentence_end`, `image_prompt`, `negative_prompt`, `camera_angle=camera_type`, `camera_movement=None` — yt.pipe has no equivalent field).
- Empty `image_prompt` (transition/effect-only sentence) → merge its sentence index into the previous shot's `sentence_indices` instead of creating a new shot, so every sentence stays covered and `ShotData.image_prompt` stays non-empty (yt.flow's `image_node` requires a real prompt per shot; yt.pipe's "skip the image" design doesn't map directly). Edge case: an empty-prompt first sentence falls back to a minimal prompt built from the scene's own `location`/`atmosphere` fields.

### Error handling

Any stage's HTTP call, JSON parse, or validation failure raises immediately; the existing outer `try/except` in `scenario_node` catches it and surfaces `PipelineState.error` exactly as today. No partial-success state, no silent swallowing inside the chain itself. (The separate report that a stage error currently doesn't surface anywhere in the API/UI — `GET /runs/{id}` returned `error: null` after a real scenario failure during this session's live testing — is tracked as its own follow-up, not part of this design.)

### Cost / latency (accepted tradeoff)

Normal pass: 12-16 DeepSeek calls (research 1 + structure 1 + writing 1 + visual_breakdown 8-12 + review 1 + critic 1). With one retry: up to ~20 calls. Expected wall-clock: roughly 1-3 minutes per run. This is a deliberate tradeoff for quality over the previous single-call design's speed.

## Out of scope

- Exposing individual yt.pipe stages as separate gate-reviewable pipeline stages (would require expanding `StageName` and touching DB/frontend/SSE/A-B-comparison code — rejected, see chat history 2026-07-03).
- `image/shot_breakdown` and `image/shot_to_prompt` yt.pipe templates — `visual_breakdown`'s output already satisfies yt.flow's `ShotData` contract directly; the separate two-step image-prompt refinement isn't needed on top of it.
- A real `character_visual_context` (character reference image/description feed into `visual_breakdown`) — defaults to empty until the character system is wired into arbitrary scenario runs.
- Fixing the silent stage-error-swallowing bug found during live testing — separate follow-up.

## Testing

Non-trivial branch: the retry loop and the empty-image_prompt merge logic. Minimum bar: one `test_scenario.py` case per branch (retry triggered vs not; a scene with a transition-only sentence merges correctly) using a stub DeepSeek client per existing test conventions (`tests/stubs/fakes.py`, `tests/fixtures/cassettes/`) — new cassette fixtures needed per stage.
