# Story 12.1: Retention Schema — Verifiable Hooks, Open Loops, and Pacing

Status: ready-for-dev

## Story

As the **yt.flow channel operator**,
I want **retention intent encoded in the scenario outline as machine-verifiable fields**,
so that **hooks, open loops, pacing changes, and scene-length balance are enforced consistently instead of depending on vague prompt prose**.

## Acceptance Criteria

1. **The Stage 2 outline has an explicit retention contract.** Every structure scene keeps the existing fields (`scene_num`, `act`, `synopsis`, `key_points`, `emotional_beat`, `estimated_duration_sec`, `fact_references`, `mood`, `title`, `kicker`) and adds:
   - `event: {who: str, what: str, consequence: str}` — all three values are non-empty; this is the machine-readable event outline. `synopsis` remains for backward compatibility and downstream summaries.
   - `hook_type: question | shock | mystery | contrast | none` — Scene 1 must use one of the first four values; every later scene must use `none`. The four active values reuse the existing Format Guide vocabulary; do not create a second hook taxonomy.
   - `loops_planted: list[str]` and `loops_closed: list[str]` — stable ledger IDs, not prose descriptions.
   - `pattern_interrupt: none | tone_shift | pov_shift | direct_address | format_change`.
   - `word_budget: int` — a positive integer, with `bool` explicitly rejected even though Python treats it as an `int` subclass.

2. **The outline is event-based, not adjective-based.** `prompts/scenario/structure.md` requires each `event.who`, `event.what`, and `event.consequence` to name the actor/subject, concrete occurrence, and resulting state change. Vague values such as “increase tension” or “make it scary” are invalid examples. The existing `synopsis`, visual identity, title, kicker, act, mood, and pacing instructions remain intact; the fact-reference instructions change only as specified in AC 12.

3. **Hook validation is deterministic and honest about its boundary.** The validator canonicalizes surrounding whitespace and ASCII case, then requires Scene 1's `hook_type` to belong to the four-value library and all later values to equal `none`. It does not claim to prove that the generated Korean sentence is emotionally effective; `writing.md` must explicitly require the first sentence to realize the selected type and the existing review/critic stages continue judging prose quality.

4. **The open-loop ledger is internally consistent and fully settled.** Loop IDs must match `loop_[a-z0-9_]+`, be planted exactly once, and be closed exactly once in a later scene. Unknown closures, duplicate plants, duplicate closures, same-scene plant-and-close, close-before-plant, and malformed/non-list ledger fields are hard violations. The outline must contain **2–3 planted loops**, at least one planted in Scene 1. After the final scene, the active ledger must be empty. An ending may still introduce an atmospheric unresolved implication, but it must not masquerade as a tracked promise the script owes the viewer; all tracked loops must close.

5. **Pattern-interrupt cadence is explicit and checkable.** `MAX_SCENES_WITHOUT_PATTERN_INTERRUPT = 2` is a module constant. Starting after the Scene 1 hook, no run may contain more than two consecutive scenes with `pattern_interrupt: none`; the third is a hard violation. A non-`none` interrupt resets the run. Scene boundaries are authoritative by list position, not untrusted LLM `scene_num`. The closed vocabulary is intentionally small and maps to the Format Guide's existing immersion techniques.

6. **Word budgets are valid planning constraints for the current three-minute pipeline.** Every scene has an integer `word_budget` in the inclusive range **20–90 whitespace-delimited Korean eojeol**, and the outline total is in the inclusive range **180–360**. These bounds are Story 12.1's resolved starting contract for `TARGET_DURATION_MINUTES = 3`; keep them as named constants beside the validator so later live tuning is localized. `writing.md` and `writing_scene_repair.md` must tell the writer to stay within each scene's budget and receive the exact structure entry. Exact post-TTS word-count gating is out of scope because `tts_normalize` may legitimately alter wording while preserving sentence count; Story 12.3 owns deterministic output-length metrics. `max_tokens` remains a truncation fuse, not the length controller.

7. **Retention validation never invokes an LLM or enters the generic semantic-retry path.** Implement a pure `_validate_retention_outline(scenes)` function in `scenario_chain.py`. `structure_step` first uses the existing `_call_stage_with_retry` parser for YAML syntax and base shape, then invokes the retention validator **after that await returns**. Do not call it from the parse callback: a `ValueError` there triggers one LLM regeneration. A retention violation surfaces immediately as a clearly classified error containing a rule code plus scene/loop context and is converted by `scenario_node` into the existing `PipelineState.error` shape. No silent degradation and no invented narrative repair.

8. **Validation is non-destructive and deterministic.** Apart from documented scalar canonicalization on the freshly parsed structure payload, valid input remains byte-equivalent, unknown existing scene fields are preserved, list order is unchanged, and no caller-owned `PipelineState` object is mutated. The same valid input produces the same result; invoking validation twice has the same effect as once. Semantic violations hard-fail rather than rewriting actors, consequences, loops, interrupts, or budgets.

9. **Initial writing and every rewrite retain the same structure contract.** The full writing prompt already receives `scene_structure`; update it to explain how to realize `event`, hook, loop, interrupt, and budget fields. Extend `writing_scene_repair_step` and its prompt to receive the exact positional structure entries for the repaired subset. `_repair_and_review` must pair target indexes with `structure[idx]` and pass that subset without trusting model-reported scene numbers. Full rewrites continue receiving the complete structure. A repair cannot drop a promised loop closure, replace an event consequence, or ignore the scene budget.

10. **No persistent schema, service, stage, API, DB, or UX change is introduced.** Retention metadata is transient Stage 2 context used to direct and validate writing; final `PipelineState.scenes`, `SceneState`, `ShotData`, gates, artifacts, SSE/API payloads, and editable scenario UX remain unchanged. Do not modify `domain/state.py`, create a retention service, or add a LangGraph stage.

11. **Regression coverage proves both rules and orchestration.** Tests cover the exact hook vocabulary; event field types; loop happy path and every ledger violation; 2-loop and 3-loop valid boundaries; cadence runs of two (`valid`) and three (`invalid`); word-budget min/max/total boundaries; rejection of bool/float/string/zero; malformed scenes; non-contiguous or deceptive `scene_num`; deterministic/idempotent/non-destructive behavior; and a deliberately all-invalid fake LLM payload. An integration test proves retention failure makes no second DeepSeek call and prevents writing/visual calls. Repair tests prove the matching structure subset reaches `writing_scene_repair`. A prompt-contract test asserts `structure.md` no longer illustrates `fact_references` with a placeholder-key pattern (e.g. `fact_key_`/`fact_1`) and that `writing.md` and `writing_scene_repair.md` both carry the fact-grounding rule, so a later prompt edit cannot silently reintroduce dangling references. Existing scenario-chain, YAML-repair, title/kicker, camera, cast, TTS-normalization, and full-node tests stay green.

Note the boundary honestly: `fact_references` content is not machine-verifiable against the source article here. `_validate_retention_outline` checks shape (non-empty list of non-empty strings), and the existing review/critic stages plus Story 12.3's deterministic metrics judge whether narration is actually grounded. Do not add an LLM fact-checking call to this story.

12. **`fact_references` carries resolvable source facts, not dangling keys.** `prompts/scenario/structure.md` currently emits opaque placeholder keys (`"fact_key_1"`), and no dictionary mapping those keys to fact bodies exists anywhere: `research.md` emits no discrete fact list, and `writing_step` receives neither the source article nor the research packet. The Stage 3 writer therefore sees fact *labels* with no fact *content* and fills the gap with atmospheric filler — the observed "tone without substance" narration defect. Change `fact_references` to a list of short verbatim-grounded source-fact statements (one concrete claim per entry, derived only from the SCP source text already in the research packet), so the field is self-resolving inside `scene_structure`. This is a prompt-contract change only: no Python code reads `fact_references` (its sole non-prompt occurrence is `tests/fixtures/cassettes/deepseek_structure.json`), so no new prompt variable, no `writing_step` signature change, and no research-schema change is required. `writing.md` must state that each scene's narration realizes its `event` **using** that scene's fact statements and may not assert anything beyond them; vagueness where a fact statement exists is a writing defect. `key_points` remains as-is. If narration still reads under-grounded after this lands, the escalation path is passing `research_packet` into `writing_step` — deliberately deferred here as unnecessary once facts are inline.

13. **Prompt deployment follows current DEV MODE policy.** Repository files remain the source of truth. After local tests, seed the scenario prompts directly to `production` with `uv run python scripts/migrate_prompts.py --label production --source prompts`. Do not run or request A/B, golden-set, baseline, or promotion gating while the DEV MODE banner in `docs/PROMPT_POLICY.md` is active. Update YAML cassettes/fixtures so local tests exercise the new production contract.

## Tasks / Subtasks

- [ ] Task 1: Add the retention schema to the structure prompt (AC: 1–6, 12)
  - [ ] Extend the YAML example in `prompts/scenario/structure.md` with `event`, `hook_type`, loop lists, `pattern_interrupt`, and `word_budget`.
  - [ ] Add consistent rules and examples using only the canonical hook and interrupt vocabularies.
  - [ ] Replace the `fact_references` placeholder-key example (`"fact_key_1"`) with short concrete source-fact statements, and state that each entry must be a single claim traceable to the research packet — never a label, ID, or topic word.
  - [ ] Keep the existing "every source fact appears in at least one scene's `fact_references`" coverage rule; it now becomes checkable by reading the outline alone.
  - [ ] Preserve existing incident-first, fact coverage, visual identity, mood, title/kicker, scene-count, and pacing requirements.
  - [ ] Make the distinction between a closed tracked loop and an unresolved ending implication explicit.

- [ ] Task 2: Implement deterministic retention validation (AC: 3–8)
  - [ ] Add named constants for hook values, interrupt values, loop-ID syntax, cadence, and budget bounds in `scenario_chain.py`; no config knobs or dependency additions.
  - [ ] Add `_validate_retention_outline(scenes)` as a pure, positional validator with rule-coded failures.
  - [ ] Canonicalize only closed scalar values; preserve all other values and fields.
  - [ ] Validate event shape, hook placement, loop ledger order/cardinality/settlement, interrupt cadence, and budget per-scene/total boundaries.
  - [ ] Invoke the validator after `_call_stage_with_retry` returns from `structure_step`, never inside its parse callback.

- [ ] Task 3: Wire retention context through writing and scoped repair (AC: 6, 9, 12)
  - [ ] Update `prompts/scenario/writing.md` so each narration scene realizes the matching event, plant/close obligations, interrupt technique, hook type, and word budget.
  - [ ] Add a fact-grounding rule to `prompts/scenario/writing.md`: narration must build each scene on that scene's `fact_references` statements, must not assert anything absent from them, and must not substitute atmosphere for an available concrete fact. Existing immersion techniques stay mandatory but may not be used as filler in place of a fact statement.
  - [ ] Mirror the same fact-grounding rule in `prompts/scenario/writing_scene_repair.md` so a repair cannot strip the grounded facts out of a scene.
  - [ ] Confirm no new `writing_step`/`writing_scene_repair_step` prompt variable is added — grounding travels inside the existing `scene_structure` payload.
  - [ ] Update `prompts/scenario/writing_scene_repair.md` to receive and obey the matching structure subset.
  - [ ] Extend `writing_scene_repair_step` and `_repair_and_review` signatures/calls with positional structure entries; preserve the existing exact-subset merge, reorder recovery, truncation fallback, and coverage fallback.
  - [ ] Do not change `tts_normalize`, review/critic contracts, `build_scenes`, or final state shapes.

- [ ] Task 4: Add validator and stage tests (AC: 7, 8, 11)
  - [ ] Add a focused retention-validator block in `tests/pipeline/nodes/test_scenario_chain.py`, mirroring the property/boundary/integration style of `_enforce_camera_variety` and `_enforce_cast_diversity`.
  - [ ] Test rule-coded failures and prove a retention failure causes exactly one structure LLM call total (the original call only), with no writing call.
  - [ ] Test valid payload preservation, determinism, idempotence, positional authority, and unknown-field preservation.
  - [ ] Update `tests/pipeline/nodes/test_scenario.py` fixtures and repair orchestration assertions for the structure subset.
  - [ ] Update `tests/fixtures/cassettes/deepseek_structure.json` and any writing/repair fixture whose contract changes. Its current `fact_references` values (`"death_count"`, `"camera_blind_spot"`) are placeholder keys and must become fact statements, since it is the only non-prompt occurrence of the field.
  - [ ] Add the AC 12 prompt-contract assertions (no placeholder-key example in `structure.md`; fact-grounding rule present in both writing prompts).

- [ ] Task 5: Verify and seed prompts (AC: 10, 11, 13)
  - [ ] Run `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py -q`.
  - [ ] Run `PYTHONPATH=$PWD/src uv run pytest -q` and `uv run ruff check src tests`.
  - [ ] Seed repo prompts with `uv run python scripts/migrate_prompts.py --label production --source prompts`; surface any credential/network failure without altering source or claiming success.

## Dev Notes

### Why this story exists

The scenario chain is already multi-stage and close to the desired plan→draft→review architecture. The gap is narrower: retention currently exists as prose such as “hook quickly” and “increase tension,” so the model can omit or contradict it without producing a machine-visible violation. This story adds a contract and cheap deterministic enforcement; it does not redesign the chain.

### The second defect this story closes: fact context never reaches the writer

Jay's 2026-08-03 review reported two distinct symptoms — repeated episode structure and narration that "does not seem to be about anything." They have different causes and only the second belongs to this story. (Repeated structure is Story 12.4: `structure.md`, `writing.md`, and `format_guide.md` each unconditionally force INCIDENT-FIRST.)

Tracing what each stage actually receives in `scenario_chain.py`:

| Stage | source article (`scp_text`) | research packet | what it gets |
| --- | --- | --- | --- |
| `research_step` (:739–741) | yes | — | full document |
| `structure_step` (:781–786) | no | yes | research packet only |
| `writing_step` (:824–829) | no | no | `scene_structure` only |

By Stage 3 the source material is gone. The only fact channel left is each scene's `fact_references`, and `structure.md:50` emits that as placeholder keys (`"fact_key_1"`) while no stage anywhere emits a key→fact dictionary — `research.md` produces `dramatic_beats` as one flowing string, not an addressable fact list. So the writer is asked for three minutes of Korean narration about facts it cannot see, and `writing.md`'s six mandatory immersion techniques become the only material it has. That mechanically produces contentless intensity ("여기서부터 진짜 미쳐돌아갑니다").

AC 12 fixes this at the cheapest point: make `fact_references` self-resolving. `grep -rn fact_references src/ tests/ scripts/` returns exactly one non-prompt hit (`tests/fixtures/cassettes/deepseek_structure.json`), so the field's semantics are prompt-private and free to change. No lookup table, no extra prompt variable, no research-schema change. This pairs with AC 1's `event: {who, what, consequence}`: `event` supplies the concrete occurrence, `fact_references` supplies its source grounding, and together they make the outline sufficient without the article.

Do **not** additionally pass `research_packet` into `writing_step` in this story. It is the documented escalation path if grounding still measures thin under Story 12.3's deterministic text metrics, but adding both at once makes it impossible to tell which change worked, and it duplicates content the outline now carries.

The planning artifacts did not provide a formal user story or numbered ACs. The contract above synthesizes the draft mandate and resolves its missing implementation choices: schema names/types, the pattern-interrupt threshold, loop-ID rules, word-budget ranges, and hard-fail behavior.

### Current-state analysis and required changes

**`src/yt_flow/pipeline/nodes/scenario_chain.py` (UPDATE — primary code change)**

- Current: `structure_step.parse()` only requires a non-empty `scenes` list and, for labeled prompts, non-empty titles. `_call_stage_with_retry` catches a semantic `ValueError` from this callback and performs exactly one DeepSeek retry.
- Change: keep base YAML/shape handling intact, await it, then validate the returned list outside the callback. This ordering is non-negotiable: placing retention validation in `parse()` contradicts the epic's no-LLM-recall requirement.
- Preserve: YAML fence handling, mark-targeted free-text repair, one retry for pre-existing base-schema errors, usage accounting, label routing, prompt cache behavior, error propagation, and all camera/cast parsers and validators.
- Existing pattern: `_enforce_camera_variety` and `_enforce_cast_diversity` demonstrate co-located deterministic logic, fixed iteration order, narrow mutation, explicit logging, and pure-function tests. Reuse their shape, not their “repair everything” semantics; narrative ledger violations cannot be safely invented by code.

**`src/yt_flow/pipeline/nodes/scenario.py` (UPDATE — scoped-repair wiring only)**

- Current: `_write_and_review` passes the complete structure to `writing_step`, but `_repair_and_review` sends only original writing scenes and feedback to `writing_scene_repair_step`.
- Change: pass `[structure[idx] for idx in indexes]` alongside the original subset, preserving positional pairing and `zip(..., strict=True)` merge behavior.
- Preserve: six-stage ordering, concurrent visual breakdown, bounded one-pass repair/full rewrite, truncation and scene-coverage fallbacks, trace metadata/usage totals, TTS normalization ordering, `build_scenes`, and the node's error return shape.

**`prompts/scenario/structure.md` (UPDATE)**

- Current: outputs prose `synopsis`/`key_points`, emotional beat, duration, facts, mood, title, and kicker. Retention requirements are prose-only. `fact_references` (line 50) demonstrates opaque placeholder keys that resolve to nothing downstream.
- Change: add the AC 1 schema and consistent rules/self-check, and convert `fact_references` to concrete source-fact statements per AC 12. Keep invariant/global guidance before variable input blocks to preserve prompt-cache-friendly ordering.
- Preserve: incident-first order, 8–12 scene instruction, frozen descriptor, the fact-coverage rule (line 72), title/kicker constraints, mood taxonomy, and valid-YAML-only response.

**`prompts/scenario/writing.md` (UPDATE)**

- Current: receives the entire structure JSON and owns Korean tone, immersion, designation, sentence rhythm, scene metadata, and hook prose. It has no access to the SCP source text or research packet, and its six mandatory immersion techniques (2인칭, 감각 묘사, 극적 질문, 상황 가정, 리액션) are currently the only material available when the outline is thin.
- Change: state how each new outline field constrains the matching narration, and add the AC 12 fact-grounding rule so those techniques decorate facts instead of replacing them. Do not remove or weaken Story 5.22 Korean register/rhythm rules or Story 5.18 dual-track-compatible sentence structure.
- Preserve: all existing output fields and pre-output self-checks. Keep the immersion techniques mandatory — the defect is missing facts, not excessive technique.

**`prompts/scenario/writing_scene_repair.md` (UPDATE)**

- Current: receives original scenes and reviewer feedback but no structure/retention plan.
- Change: include the exact target structure subset and prohibit a repair from dropping its event outcome, loop obligations, interrupt, word budget, or grounded fact statements.
- Preserve: exact scene coverage and YAML-only output.

**Tests and fixtures (UPDATE)**

- `tests/pipeline/nodes/test_scenario_chain.py`: validator units + `structure_step` no-recall integration.
- `tests/pipeline/nodes/test_scenario.py`: enrich `STRUCTURE` fixtures and assert structure subset reaches scoped repair.
- `tests/fixtures/cassettes/deepseek_structure.json`: include a valid, settled ledger and complete new fields. Update repair fixtures only where the prompt-variable contract is asserted.

**Files that must remain unchanged**

- `src/yt_flow/domain/state.py`: retention metadata is transient outline context; persisting it would expand checkpoint/API/artifact contracts without a consumer.
- DB models/migrations, APIs, services, frontend, graph/gates, and UX documents: no requirement or consumer.
- `tts_normalize.md`, `review.md`, `critic_agent.md`, `visual_breakdown.md`, and `build_scenes`: their input/output responsibilities do not change in this story.
- Dependencies and `pyproject.toml`: stdlib + existing PyYAML are sufficient.

### Validation algorithm guardrails

Use list position as the canonical chronology. `scene_num` may be checked for diagnostics but must not drive ledger ordering; the codebase already treats scene alignment positionally because LLM scene numbers can be duplicated or reordered.

Recommended single pass:

1. Validate each scene is a dict and validate/canonicalize its scalar enum fields.
2. Validate the `event` mapping and budget type/range; accumulate total budget.
3. Track `planted: dict[loop_id, position]`, `closed: set[loop_id]`, and `active: set[loop_id]`.
4. Process plants before closures only for diagnostics, but reject any ID present in both lists so same-scene closure never becomes accidentally legal.
5. Reject unknown/duplicate/early closures immediately with a stable rule code.
6. Track consecutive `none` interrupts after the first scene and reject the third.
7. After the pass, reject plant count outside 2–3, non-empty `active`, or total budget outside 180–360.

Keep failures actionable, for example: `retention[loop_unclosed] loop_reveal planted at position 2 is still active after final scene`. Tests should assert the stable rule code, not a fragile full message.

### Architecture compliance

- **AD-1:** changes remain inside prompts and pipeline nodes; no upward or cross-layer imports.
- **AD-2:** final in-flight media state still lives in `PipelineState`; transient outline metadata need not become a second persistent truth source.
- **AD-4:** scenario nodes remain pure—no DB, SSE, or external side effects from validation.
- **State mutation convention:** `scenario_node` continues returning only replaced fields. Validation operates on the newly parsed structure list, never the incoming state.
- **Prompt contract:** YAML remains the structured-output format; no Pydantic model or new SDK is needed.

### Cross-story context and scope boundaries

- **Story 12.2:** recommended to land first because it changes the writing-provider boundary. This is sequencing guidance, not a functional blocker; base implementation on the latest settled 12.2 code if it lands before development begins.
- **Story 12.3:** owns pass-2 verdict surfacing plus deterministic slop/repetition/final-length metrics. Preserve retention context for its future checks, but do not absorb review/gate changes or exact post-TTS word-count enforcement here. Its metrics are the intended measurement of whether AC 12 actually improved grounding; this story ships the mechanism, not the proof of effect.
- **Story 12.4:** owns the *other* half of Jay's feedback — repeated episode structure, caused by three prompts hard-coding INCIDENT-FIRST. It will add narrative archetypes in the same structure prompt. Every archetype must preserve this retention schema and AC 12's fact-statement contract; 12.4's archetype examples are deliberately source-neutral, so they must not reintroduce placeholder-key `fact_references`. Avoid hard-coding incident-first-only logic into the validator beyond existing fields.
- **Golden datasets are explicitly not the lever for either defect.** The repeated-structure defect is prompt-hard-coded (12.4), and the thin-narration defect is a context-propagation bug (AC 12). Injecting real third-party scripts as few-shot examples would fix neither and risks structural homogeneity plus fact leakage. The legitimate future use of measured reference scripts is calibrating this story's hand-set constants (word-budget 20–90/180–360, 2–3 loops, `MAX_SCENES_WITHOUT_PATTERN_INTERRUPT = 2`) — a separate measurement task, and distinct from the frozen golden-set promotion gate that Story 13.4 owns.
- **Story 12.5:** independent TTS comparison; no overlap.
- **Story 5.17:** preserve viewer-facing `title`/`kicker`.
- **Story 5.22:** preserve Korean narration register, rhythm, and designation rules.
- **Stories 8.18 and 11.2:** direct implementation/test precedents for deterministic validators within `scenario_chain.py`.

### Library and framework requirements

- Python remains `>=3.12,<3.13`; use stdlib `re`, collections, and typing already present.
- Use existing `yaml.safe_load` and `_call_stage_with_retry`; do not add Pydantic, JSON Schema, marshmallow, or an OpenAI SDK for this contract.
- No external API, database migration, GPU, ComfyUI, frontend, or new package is required.
- Architecture version tables are historical; the checked-in `pyproject.toml`/lockfile and current source are authoritative. This story changes no version.
- No web research is materially required: there is no new or upgraded technology. The external papers in the planning research justify the product design but do not create an implementation dependency.

### Testing requirements

- Worktree tests must use `PYTHONPATH=$PWD/src`; a global editable install can otherwise shadow local sources.
- Mirror the existing camera/cast validator pattern: focused helper fixtures, exact boundaries, valid-input preservation, deterministic result, idempotence, logging/error observability, then a full integration test.
- Explicitly test the Python `bool`/`int` trap with `word_budget: true`.
- Explicitly test `structure_step` call count on retention failure. If it equals two, validation was placed inside the generic retry boundary and AC 7 is broken.
- Repair integration must include two non-adjacent scene indexes so positional subset matching cannot pass accidentally.
- Run the two focused files first, then the full suite and Ruff. Do not claim prompt seeding succeeded unless the command actually exits zero.

### Git intelligence

- `fcad36f` (Story 8.18): strongest validator/test precedent—cross-field rules, deterministic/idempotent repair, valid-input preservation, integration coverage.
- `ce4bcef` (Story 11.2): closed vocabulary, fallback behavior, adjacent-item constraint, and direct `build_scenes` integration.
- `b06d4dd`: individually valid enum values can still form invalid combinations; validates the need for ledger cross-field checks.
- `57e6b0b` / `abd9361`: broad deterministic rewrites corrupted healthy siblings; retain mark-targeted/preservation discipline and keep semantic validation outside YAML repair.
- Recent commits actively touch `scenario_chain.py`; keep changes localized and re-read the live file before implementation.

### Project Structure Notes

- No new production file is expected.
- The existing architecture document lists older dependency versions; follow current source and lockfile.
- The working tree already contains user-owned changes in `epics.md` and `sprint-status.yaml`. Preserve them; update only the exact Epic 12/story status scalars and current date during this workflow.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 12.1: 리텐션 스키마 — 훅/오픈루프/페이싱을 검증 가능한 필드로]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#1.1 Pipeline structures that beat single-shot generation]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#1.3 YouTube retention-driven script structure]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#1.5 Practical generation control]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#1.6 Key takeaways for script pipeline redesign]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants & Rules]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency Conventions]
- [Source: prompts/scenario/format_guide.md#A. Hook Type Library]
- [Source: prompts/scenario/format_guide.md#D. Viewer Immersion Devices]
- [Source: prompts/scenario/format_guide.md#E. Scene Count & Pacing Guide]
- [Source: prompts/scenario/structure.md#Task]
- [Source: prompts/scenario/structure.md#Rules]
- [Source: prompts/scenario/structure.md:50] — current placeholder-key `fact_references` example.
- [Source: prompts/scenario/structure.md:72] — existing fact-coverage rule that AC 12 makes outline-checkable.
- [Source: prompts/scenario/research.md] — research output schema; emits no discrete/addressable fact list.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:739] — `research_step` receives the full source document.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:781] — `structure_step` receives the research packet but not the source document.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:824] — `writing_step` receives `scene_structure` only; the fact-context loss point.
- [Source: tests/fixtures/cassettes/deepseek_structure.json:11] — sole non-prompt occurrence of `fact_references`.
- [Source: prompts/scenario/writing.md#Scene Structure (from Stage 2)]
- [Source: prompts/scenario/writing.md#Hook Scene (Scene 1) — 가장 중요]
- [Source: prompts/scenario/writing_scene_repair.md]
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#_call_stage_with_retry]
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#structure_step]
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#_enforce_camera_variety]
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#_enforce_cast_diversity]
- [Source: src/yt_flow/pipeline/nodes/scenario.py#_write_and_review]
- [Source: src/yt_flow/pipeline/nodes/scenario.py#_repair_and_review]
- [Source: tests/pipeline/nodes/test_scenario_chain.py#structure_step tests]
- [Source: tests/pipeline/nodes/test_scenario_chain.py#_enforce_camera_variety tests]
- [Source: tests/pipeline/nodes/test_scenario_chain.py#_enforce_cast_diversity tests]
- [Source: docs/PROMPT_POLICY.md#Prompt Policy]
- [Source: pyproject.toml#project]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- No previous Epic 12 story file exists: Story 12.1 is the first numbered story. Cross-epic implementation intelligence from Stories 8.18 and 11.2 is included instead.
- Latest-technology web research was not needed because this story adds no dependency, API, protocol, or version choice; current repository code and lockfile are authoritative.

### File List

- `_bmad-output/implementation-artifacts/12-1-retention-schema.md` — story context and implementation guide.

## Change Log

- 2026-08-03: Story created and marked ready-for-dev.
- 2026-08-03: Added AC 12 (`fact_references` carries resolvable source facts) after tracing the reported "narration has no context" defect to Stage 3 receiving neither the source article nor the research packet, with `fact_references` emitting keys that no stage resolves. Prompt-only change; former AC 12 renumbered to 13; Tasks 1/3/4 extended. Considered and rejected homing this in Story 12.2 (provider routing only, explicitly no chain changes) and passing `research_packet` into `writing_step` (deferred escalation path).
