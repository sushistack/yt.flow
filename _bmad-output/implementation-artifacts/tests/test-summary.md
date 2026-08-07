# Test Automation Summary — Story 12.4 (Story Archetype Diversification)

Date: 2026-08-07 · Workflow: `bmad-qa-generate-e2e-tests` · Framework: **pytest 9.1.1** (existing)

Story 12.4 has no UI surface (AC8 forbids one), so "E2E" here means the project's
established end-to-end contract: a run driven entirely through the HTTP API against
the offline `stub_profile` seams (`tests/api/test_e2e_stub_run.py`, SYS-E2E-001).
Browser/Playwright E2E is not applicable.

## Gap analysis

Story 12.4 shipped 77 unit tests covering the vocabulary, the pure evidence map,
`research_step` resolution, `structure_step` guide injection, `_nullify`, and the
evaluator. Every one of them **injects** the research packet, the structure seam, the
prompt fake, or the scenario node by hand. The gaps found were therefore all at the
wiring layer — each would have stayed green with the feature functionally dead:

| # | Gap | Would have survived because |
|---|-----|------------------------------|
| 1 | No test proves production wiring resolves an archetype at all, or that the Prompt Hub name it derives is fetchable | unit tests patch `structure_step` / `prompt_service` |
| 2 | The evidence gate was never observed through a whole run — only inside `research_step` | the fallback could fire and still fail the run downstream |
| 3 | `_nullify`'s two new keys were only tested against a fake node's canned dict, never a real checkpoint | the unit test never calls `update_state` on real graph state |
| 4 | `eval_prompts._run_stage_chain` passes the resolved archetype to `structure_step` — untested | the evaluator tests score a fake `scenario_node` output, so the runner could report `discovery_log` while generating incident-first outlines |

## Generated tests

### E2E (API-driven, `tests/api/test_e2e_stub_run.py`)

- [x] `test_stub_run_resolves_the_archetype_and_fetches_only_that_guide` — happy path.
  `POST /runs` → the cassette's `containment_breach_realtime` lands in the LangGraph
  checkpoint (`fallback_used=False`), **exactly one** `scenario/archetypes/*` guide is
  compiled (AC5 no-bloat), the value survives the real sqlite checkpoint as plain JSON
  (AC6), and neither the run payload nor the scenario artifacts payload grew a field
  (AC6/AC8 — the selection stays non-authoritative outside state).
- [x] `test_archetype_without_its_source_evidence_falls_back_mid_run_without_failing` —
  critical error case. The research reply is rewritten in flight to demand
  `interview_testimony` from a source with no interview log: the run still reaches
  `awaiting_approval` with `error=None`, state shows `incident_first` +
  `fallback_used=True`, and the guide actually injected is the fallback's.
- [x] `test_scenario_retry_clears_then_reresolves_the_archetype` — second critical error
  case. Reject → retry re-selects normally; then the prose provider is killed and a
  second retry fails, proving the checkpoint holds the new error with **no** archetype
  beside it (AC8), against real `_nullify` + `update_state`.

### API / runner (`tests/test_eval_prompts.py`)

- [x] `test_stage_chain_hands_the_research_choice_to_structure` (×4, one per catalogue
  value) — the Story 6.2 runner's own chain obeys the same "research owns it" rule.
- [x] `test_stage_chain_defaults_to_the_production_template_without_a_choice` —
  a packet with no selection produces `incident_first`, not a crash.

## Mutation verification

Each test was proven to bite by breaking the code it guards and confirming only that
test fails (sources restored afterwards, `git diff --stat` verified unchanged):

| Mutation | Killed |
|----------|--------|
| `scenario_node` stops passing `story_archetype=` to `structure_step` | test 1 |
| the `missing_archetype_evidence` gate in `research_step` is disabled | test 2 |
| `_nullify` stops clearing the two scenario-owned fields | test 3 |
| `_run_stage_chain` stops passing the resolved archetype | all 5 runner tests |

## Coverage

- **AC coverage after this pass:** AC1–AC6 and AC8 all have at least one test that
  exercises production wiring rather than an injected seam. AC7 (prompt rollout) is an
  operational step, already recorded in the story's Dev Agent Record.
- **Catalogue:** all four archetypes covered — exhaustively in the deterministic
  parser/guide/runner tests, and one (`containment_breach_realtime`) plus the fallback
  (`incident_first`) through the live offline pipeline.
- **Not covered, deliberately:** network LLM calls and a live Langfuse evaluation
  (AC8 explicitly does not require them). Whether DeepSeek reports the evidence
  inventory *honestly* is unfalsifiable offline — it remains Jay's live check.

## Results

```
uv run pytest -q                 → 2336 passed, 1 skipped   (was 2328 → +8)
uv run ruff check <changed>      → All checks passed
```

## Next steps

- Run the suite in CI as-is; no new fixtures, dependencies or markers were introduced.
- The one open live question is unchanged from the story's own notes:
  `uv run python scripts/eval_prompts.py --label production --profile smoke --scp-id SCP-049`
  from the main tree, to see the real observed archetype distribution.
