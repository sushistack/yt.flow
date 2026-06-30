# Story 1.5: scenario_node (LLM-Director)

Status: ready-for-dev

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created. -->

## Story

As Jay,
I want `scenario_node` to produce a structured scene list with shot boundaries from SCP text via DeepSeek V4,
so that downstream nodes receive typed `SceneState` objects with N:M sentence-to-shot mappings.

## Acceptance Criteria

1. Given `scp_text` in `PipelineState` and a `scenario` prompt in Langfuse Prompt Hub, when `scenario_node` runs, then `PipelineState.scenes` contains at least one `SceneState`, each with non-empty `narration: str` and `shots: list[ShotData]` containing at least one shot.
2. Given any emitted `ShotData`, when `scenario_node` completes, then `sentence_indices` is a non-empty `list[int]`, `image_prompt` is a non-empty string, and `negative_prompt` is a non-empty string.
3. Given `scenario_node` execution, when the DeepSeek LLM call completes, then a Langfuse span named `scenario` captures the rendered prompt, raw response, latency in milliseconds, and input/output token counts. This covers FR-10 and FR-11.
4. Given DeepSeek V4 returns malformed, empty, truncated, or schema-incompatible content, when `scenario_node` attempts to parse it, then the node returns `PipelineState.error` with stage/run context and the Langfuse span captures the exception and inputs at the failure point. This covers FR-13.
5. Given the graph topology from Story 1.4, when `scenario_node` returns successfully, then it sets `current_stage` to `scenario` and does not call `interrupt()` itself; gate behavior remains in `gate_scenario`.
6. Given the Architecture AD-5 rule, when shots are emitted, then `sentence_indices` are 0-based references into the narration sentence list and represent N:M mapping: one sentence may map to multiple shots, and multiple sentences may map to one shot.

## Tasks / Subtasks

- [ ] Implement `src/yt_flow/pipeline/nodes/scenario.py` as a pure async node. (AC: 1, 5)
  - [ ] Accept and return `PipelineState`-compatible dict updates; do not mutate the incoming state in place.
  - [ ] Read `run_id`, `scp_text`, and optional `prompt_variant` from state.
  - [ ] Return only changed fields: `scenes`, `current_stage`, and `error` as needed.
- [ ] Fetch and render the `scenario` prompt from Langfuse Prompt Hub at runtime. (AC: 1, 3)
  - [ ] Use the prompt migrated in Story 1.3; do not hardcode pipeline prompt text in source.
  - [ ] Compile with `scp_text` and any prompt variables established by Story 1.3.
  - [ ] If A/B labels already exist, map `prompt_variant` to Langfuse labels in the smallest established project pattern; otherwise leave variant behavior for Epic 4.
- [ ] Call DeepSeek through the OpenAI-compatible client using config-pinned model settings. (AC: 1, 3, 4)
  - [ ] Read API key/base URL/model name from `Settings` with `YTFLOW_` prefix; do not hardcode model identifiers.
  - [ ] Prefer `response_format={"type": "json_object"}` and ensure the rendered prompt explicitly instructs the model to output JSON.
  - [ ] Set a reasonable `max_tokens` from config or prompt config to avoid truncated JSON.
- [ ] Parse and validate the LLM response into the existing domain TypedDict shape. (AC: 1, 2, 4, 6)
  - [ ] Produce `SceneState` with `scene_num`, `narration`, `shots`, `audio_path=None`, `audio_duration=None`, `word_timings=[]`, and `subtitle_path=None`.
  - [ ] Produce `ShotData` with `shot_id`, `sentence_indices`, `image_prompt`, `negative_prompt`, `camera_angle`, `camera_movement`, and `image_path=None`.
  - [ ] Validate scene numbering, non-empty narration, non-empty shots, non-empty prompt strings, and non-empty integer `sentence_indices`.
  - [ ] Reject out-of-range sentence indices relative to the narration sentence list, unless an established earlier story intentionally defines a different indexing source.
- [ ] Add Langfuse observability around the node and generation call. (AC: 3, 4)
  - [ ] Decorate the stage node with `@observe(name="scenario")` or the established project wrapper.
  - [ ] Capture rendered prompt, raw response text, model name, latency, usage/token counts, and prompt metadata/version when available.
  - [ ] Treat Langfuse transport failures as non-fatal per AD-10; the pipeline should log and continue if only tracing fails.
- [ ] Add focused tests. (AC: 1-6)
  - [ ] Unit test successful parse into `PipelineState.scenes` using mocked Langfuse prompt fetch and mocked DeepSeek response.
  - [ ] Unit test malformed JSON sets `error` and does not emit partial scenes as successful output.
  - [ ] Unit test empty scenes/shots/prompts and bad `sentence_indices` fail validation.
  - [ ] Unit test node purity: input state object is not mutated.
  - [ ] Unit test Prompt Hub/runtime prompt fetch is used; no hardcoded scenario prompt path is required by the node.

## Dev Notes

### Story Dependencies

- This story depends on Stories 1.2, 1.3, and 1.4.
- Required prior artifacts:
  - `src/yt_flow/domain/state.py` containing `PipelineState`, `SceneState`, `ShotData`, and `WordTiming`.
  - `src/yt_flow/config.py` using Pydantic `BaseSettings` with `YTFLOW_` prefix.
  - `src/yt_flow/pipeline/graph.py` with the fixed topology `scenario -> gate_scenario -> image`.
  - Langfuse Prompt Hub prompt named `scenario`.
- If these files or prompt entries do not exist, do not invent incompatible replacements inside this story. Complete the prerequisite story contracts first, then implement this node.

### Architecture Guardrails

- Preserve dependency direction: `pipeline/` may import `domain` and `config`, but must not import `db`, `api`, or `services`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1`]
- `PipelineState` is the source of truth for in-flight scenes and artifact paths. Do not add `scenes` or `artifacts` database tables. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2`]
- Stage nodes are pure functions of `PipelineState`. No DB writes, no SSE queues, no gate state writes, and no `interrupt()` calls in `scenario_node`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4`]
- `gate_states` are written only by gate nodes in `gates.py`; this node should set `current_stage="scenario"` and return scenario artifacts. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-3`]
- Use UUID string `run_id` already present in state. Do not introduce auto-increment IDs or separate scene IDs outside state.
- `ShotData.sentence_indices` must be 0-based and support the LLM-Director N:M mapping pattern. `camera_angle` and `camera_movement` should be populated when available; `None` is allowed only when the LLM omits them. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-5`]
- `PipelineState` fields are replaced wholesale per node return; do not rely on reducers or in-place mutation. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]

### Expected Domain Shape

Use the Architecture shape unless Story 1.2 has already refined it in code:

```python
class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None
    image_path: str | None

class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None

class PipelineState(TypedDict):
    run_id: str
    scp_text: str
    scenes: list[SceneState]
    video_path: str | None
    current_stage: str
    gate_states: dict[str, str]
    prompt_variant: str | None
    error: str | None
```

[Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState-OQ-7-resolved`]

### File Structure Requirements

- Primary implementation: `src/yt_flow/pipeline/nodes/scenario.py`.
- Expected supporting imports:
  - `src/yt_flow/domain/state.py` for TypedDicts.
  - `src/yt_flow/config.py` for `YTFLOW_` settings.
  - Any existing Langfuse/LLM helper established by Stories 1.1-1.4. Reuse it if present.
- Expected tests: follow the repository's established test layout after Story 1.2. If no pattern exists, use `tests/pipeline/nodes/test_scenario.py`.
- Do not copy prompt templates from `/mnt/work/projects/yt.pipe/templates/` into this node. Story 1.3 owns migration to Langfuse Prompt Hub.
- The source project reference is `/mnt/work/projects/yt.pipe`, but no `*.tmpl` files were discoverable at `/mnt/work/projects/yt.pipe/templates/` during story creation. Verify the actual migration source from Story 1.3 before implementation.

### LLM Output Contract

The node should ask DeepSeek for a JSON object that can be deterministically transformed into `list[SceneState]`. A minimal acceptable model-side structure is:

```json
{
  "scenes": [
    {
      "scene_num": 1,
      "narration": "Korean narration text...",
      "sentences": ["Sentence 1", "Sentence 2"],
      "shots": [
        {
          "shot_id": "S001",
          "sentence_indices": [0],
          "image_prompt": "visual prompt...",
          "negative_prompt": "negative prompt...",
          "camera_angle": "wide",
          "camera_movement": "static"
        }
      ]
    }
  ]
}
```

Implementation may omit storing `sentences` in `PipelineState`; it is a validation aid for `sentence_indices`. If the final prompt created in Story 1.3 uses another schema, adapt the parser only if it still maps cleanly to the architecture's `SceneState` and `ShotData`.

### Error Handling Requirements

- On malformed JSON, missing fields, invalid types, empty content, or truncated response, return a state update with `error` set to a readable string containing `stage=scenario` and `run_id=<id>`.
- Do not raise validation errors past the node unless the established graph error policy in Story 1.4 requires exceptions. The acceptance criteria require `PipelineState.error` to be set.
- Preserve enough raw response context in Langfuse metadata/output for diagnosis, but avoid logging secrets or entire `.env` values.
- If only Langfuse tracing fails, log and continue per AD-10. If Prompt Hub fetch fails and no cached/fallback prompt exists from Story 1.3, fail the node with `error`; do not silently use a hardcoded prompt.

### Latest Technical Notes Verified 2026-07-01

- DeepSeek's current docs list `deepseek-v4-flash` and `deepseek-v4-pro`; older `deepseek-chat` and `deepseek-reasoner` names are marked for deprecation on 2026-07-24. Keep model names config-pinned and prefer the current V4 identifier. Source: <https://api-docs.deepseek.com/>
- DeepSeek JSON output requires `response_format={"type": "json_object"}` and explicit prompt instructions to output JSON; without prompt instruction, generation may appear stuck or produce unusable whitespace. Source: <https://api-docs.deepseek.com/guides/json_mode>
- Langfuse Python SDK v4 is the current SDK generation. Use `get_client()`/`get_prompt()` for Prompt Management and `@observe` or `start_as_current_observation()` for tracing, following the existing project pattern once established. Sources: <https://langfuse.com/docs/observability/sdk/overview>, <https://langfuse.com/docs/prompt-management/get-started>
- Langfuse Prompt Management caches prompts client-side and can serve stale prompts while revalidating. Story AC says prompt changes should affect the next run; if immediate freshness is required, configure cache TTL or label behavior explicitly in the Prompt Hub helper from Story 1.3. Source: <https://langfuse.com/docs/prompt-management/features/caching>
- `langgraph-checkpoint-sqlite` provides `AsyncSqliteSaver` via `langgraph.checkpoint.sqlite.aio`; recent package docs recommend strict msgpack configuration for checkpoint deserialization safety. This story should not touch checkpoint setup, but tests should not assume sync `SqliteSaver`. Source: <https://pypi.org/project/langgraph-checkpoint-sqlite/>

### Testing Requirements

- Use mocked DeepSeek and Langfuse clients for unit tests; no live API calls in default test runs.
- Assert the node output matches the TypedDict contract exactly enough for downstream `image_node` to consume `scenes[*].shots[*].image_prompt`, `negative_prompt`, and `sentence_indices` without optional branching.
- Include malformed cases:
  - Invalid JSON.
  - Valid JSON with no scenes.
  - Scene with narration but no shots.
  - Shot with empty prompt strings.
  - Shot with non-int, negative, or out-of-range `sentence_indices`.
- Include observability behavior at the boundary practical for unit tests: the wrapper/helper is invoked and receives rendered prompt/raw response/usage data. Do not require a live Langfuse server in CI.

### Previous Story Intelligence

- Existing lower-number Epic 1 story files found at story creation time: `1-1-langfuse-env-verification.md`, `1-2-project-scaffold-domain-types.md`.
- No files were found for Stories 1.3 and 1.4 during this story run, so Prompt Hub and graph contracts must be verified before implementation starts.
- Recent git history contains planning-only commits:
  - `2390ead` initialized sprint status tracking.
  - `4be98ee` added epic breakdown and readiness report.
  - `6db2416` added UX design specs and mockups.
  - `ca2fb1d` added architecture design and review docs.
  - `b9dc0b0` added the PRD.
- There are no established code implementation patterns in this repository yet. Follow `CLAUDE.md` Ponytail rules: avoid speculative abstractions, use installed dependencies, and keep the minimum code that satisfies the contract.

### Project Context Reference

- Persistent fact glob `**/project-context.md` resolved to no files during story creation.
- Primary context sources loaded:
  - `_bmad-output/planning-artifacts/epics.md`
  - `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
  - `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
  - `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
  - `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`
  - `CLAUDE.md`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
