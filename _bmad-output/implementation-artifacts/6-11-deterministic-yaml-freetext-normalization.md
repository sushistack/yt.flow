---
created: 2026-07-12
baseline_commit: b81479b
story_key: 6-11-deterministic-yaml-freetext-normalization
story_id: "6.11"
epic: 6
previous_story: 6-10-statistical-promotion-gate-repair-robustness
depends_on: []
replaces:
  - 6-7-yaml-syntax-only-repair-path  # this story removes 6.7's LLM `scenario/yaml_syntax_repair` call and replaces it with a deterministic normalizer
related:
  - 6-4-scenario-yaml-output-bounded-retry  # 6.4 switched JSON→YAML and adopted bounded-retry; it explicitly documented that a second YAML-syntax failure propagates (hard-fail). This story removes that hard-fail for the free-text-colon class.
unblocks:
  - 6-3-prompt-cache-hit-optimization   # SCP-049 production baseline intermittently hard-fails on this exact class, blocking a clean gate
  - 6-4-scenario-yaml-output-bounded-retry
evidence: "2026-07-12 live promotion gate (--profile promotion --reps 3): SCP-049 hard-failed once on an unquoted-colon YAML error (`mapping values are not allowed here`) despite `scenario/yaml_syntax_repair` now existing under production — the bounded LLM repair re-emitted the same defect and the re-parse failed again, propagating to a run-killing hard-fail. This is the same failure class Story 6.4 observed on SCP-173 (6-4 story, Run 2: `yaml.YAMLError` survived bounded retry) and explicitly designed to let propagate, and the same class 6.10 logged as an out-of-scope production baseline-robustness follow-up (6-10 story, Review Follow-ups #1; 6-3-6-4-review-metrics-report.md '2026-07-12 Story 6.10'). Root cause (this-session analysis): the scenario chain asks DeepSeek to emit hand-written YAML with free-text values and no hard grammar guarantee — DeepSeek's `response_format=json_object` was tried pre-6.4 and demonstrably did NOT prevent the analogous JSON class either. Every 6.5–6.10 story removed a DIFFERENT crash class (timeout/truncation/coverage-mismatch/judge-crash) or improved measurement; none prevented free-text-colon, and 6.7's only mitigation was itself a free-form LLM call that reproduces the defect. Jay's decision (2026-07-12): replace the LLM repair with a deterministic pre-parse normalizer."
---

# Story 6.11: Deterministic YAML free-text normalization (replace LLM syntax-repair)

Status: done

## Story

As Jay,
I want scenario-stage outputs that fail YAML parsing on a free-text-scalar defect (an unquoted colon, quote, or `#` inside `narration`/`image_prompt`/etc.) to be repaired **deterministically** — by rewriting the offending free-text value as a YAML block literal before re-parsing — instead of by a second free-form LLM call,
so that this recurring hard-fail class is eliminated without stacking another probabilistic LLM recovery layer, and SCP-049's production baseline stops intermittently killing the gate.

## Context

The scenario chain (`scenario_chain.py`) asks DeepSeek to emit YAML with free-text fields in block-literal (`|`) style. When the model instead emits a free-text value **inline** (`narration: 박사가 말했다: 위험해`), the embedded colon makes PyYAML read it as a nested mapping → `mapping values are not allowed here` → `yaml.YAMLError`.

Story 6.7 added `scenario/yaml_syntax_repair`, but that repair is **another free-form LLM YAML call** ("Return ONLY the corrected YAML") — it can, and on 2026-07-12 did, reproduce the same defect, after which the re-parse fails again and the exception propagates (`_call_stage_with_retry`, the `return parse(raw)` after the repair call is not guarded). This is LLM-fixing-LLM-YAML with no convergence guarantee.

The insight this story acts on: **the fix must be deterministic, not another LLM layer.** A YAML block literal (`|-`) takes its indented content verbatim — colons, quotes, `#`, all safe — so converting a known free-text field's inline value to a block literal is a provably-safe, LLM-free repair for this class.

**Why this is safe to implement before the exact failing byte is captured:** the normalizer runs ONLY after a normal parse has already failed (happy path untouched), and acts ONLY on the fixed set of keys that are always free-text-valued (never structural mappings), so its worst case is "still doesn't parse → propagate, same as today" — never a regression of currently-working output. The `-orig`/`-repair` dumps added this session (`tmp/yaml-failures/`, `scenario_chain.py:_dump_bad_output`) will capture a real failing sample; when one lands it is promoted to a regression fixture (AC5).

## Acceptance Criteria

1. **Given** `_call_stage_with_retry` in `scenario_chain.py`, **Then** the `except yaml.YAMLError` branch no longer calls `scenario/yaml_syntax_repair`; it instead calls a new deterministic `_blockify_freetext_scalars(raw)` and re-parses the result. If the re-parse still raises, the exception propagates unchanged (bounded, no third attempt, no LLM). The `except ValueError` (semantic-validation) branch is UNCHANGED — it still feeds the error back into the same stage prompt for exactly one retry.

2. **Given** the deterministic repair, **Then** for a line matching a known free-text key (`narration`, `image_prompt`, `negative_prompt`, `core_identity`, `frozen_descriptor`, `entity_sheet`, `story_logline`, `feedback`) as `{indent}{'- '?}{key}: {non-empty inline value}`, it rewrites the value as a block literal:
   ```
   {indent}{'- '?}{key}: |-
   {content-indent}{value}
   ```
   where `content-indent` is greater than the key's own indentation (accounting for a leading `- ` list-item marker). Lines whose value is already a block scalar (`|`, `|-`, `>`, `>-`), is quoted, or is empty are left unchanged. The transform preserves the value's bytes exactly.

   **Review amendment (2026-07-12, Jay-approved):** the original spec transformed *every* free-text line in the document, which silently corrupted **valid** sibling lines (quoted values gained literal quotes, trailing `# comments` were absorbed, empty `""` became non-empty). The implementation is **mark-targeted** instead: `_blockify_line(text, line_no)` rewrites ONLY the single line PyYAML's `problem_mark` flagged, and `_reparse_repairing_freetext` loops (bounded by line count) re-parsing after each repair so multiple broken lines are still handled. A valid sibling is never touched.

3. **Given** the removal of the LLM repair, **Then** the `scenario/yaml_syntax_repair` prompt fetch, its `prompt_service.PromptFetchError` production/candidate fallback branch, and the associated `label`-dependent logic in `_call_stage_with_retry` are deleted. (The prompt file `prompts/scenario/yaml_syntax_repair.md` may remain on disk unused, or be deleted — Dev Notes records which and why.)

4. **Given** the `-orig`/`-repair` diagnostic dumps added this session (temporary), **Then** they are either (a) kept as-is if still useful for the ValueError/other classes, or (b) removed for the now-deterministically-handled YAMLError path. Dev Notes states the decision. No silent orphan diagnostic code.

5. **Given** unit tests, **Then** regression coverage exists for the three nesting shapes where free-text colons occur: (a) a top-level free-text key (`frozen_descriptor: a: b`), (b) a scene-list `narration` (`  - narration: x: y`), (c) a shot `image_prompt`. Each test asserts: (i) plain `yaml.safe_load` raises `yaml.YAMLError` on the broken input, (ii) `_blockify_freetext_scalars` output parses successfully, (iii) the field value round-trips byte-identical. If a real failing sample has been captured in `tmp/yaml-failures/`, one test uses it as a fixture.

6. **Given** existing tests that assert the LLM-repair behavior (bounded-retry-via-yaml_syntax_repair, PromptFetchError fallback), **Then** they are updated or removed to match the deterministic contract. The full suite passes and `ruff` is clean.

## Tasks

- [x] Task 1: Add `_blockify_freetext_scalars(raw)` to `scenario_chain.py` near `_parse_yaml`/`_normalize_freetext`; define the free-text key set as a module constant (`FREETEXT_KEYS`). (AC:2)
- [x] Task 2: Rewrite the `except yaml.YAMLError` branch of `_call_stage_with_retry` to call the normalizer + re-parse; deleted the `yaml_syntax_repair` call and its `PromptFetchError` fallback. `except ValueError` untouched. (AC:1, 3)
- [x] Task 3: Resolve the diagnostic dumps per AC4 — kept `_dump_bad_output`, now fires only on the `unfixed` case (a YAMLError the normalizer could NOT repair → still-novel class worth capturing under `tmp/yaml-failures/`). The finish_reason=length truncation dump (`tmp/truncations/`) is separate and retained. (AC:4)
- [x] Task 4: Added 7 direct `_blockify_freetext_scalars` tests (three nesting shapes + block-literal-skip + non-freetext-untouched + valid-unchanged guards) and 1 deterministic `_call_stage_with_retry` test; removed the 2 LLM-repair-specific tests and reframed 4 (usage-sink / exhaustion / research-step retry) onto the semantic-ValueError path. **1271 passed, 1 skipped, ruff clean.** (AC:5, 6)
- [ ] Task 5 (out of session / Jay-authorized): re-run the live promotion gate for 6-3/6-4 now that this class is deterministically handled; record whether SCP-049's production baseline still hard-fails on any OTHER class. (AC: live validation — informational, not a promotion decision here.)

## Dev Notes

- **Bounded contract preserved.** The `except ValueError` semantic-retry path is unchanged — this story only replaces the *syntax* repair. There is still exactly one deterministic attempt on the YAMLError path; a second failure propagates, matching 6.4's bounded precedent (just LLM-free now).
- **Scope — this class only.** `hooks` list-item colons (`- hook text: with colon`) parse as a valid-but-wrong-shape list-of-dicts → surface as `ValueError` in validation, NOT `yaml.YAMLError`. That is a distinct class (valid-JSON/YAML-wrong-shape, per 6.4 class 3) and is out of scope. Unquoted quotes/`#` inside a free-text scalar ARE covered incidentally, since block-literal conversion is agnostic to which structural character broke the line.
- **Why not always-normalize / why not keep the LLM as a last-resort fallback.** Always-normalizing touches currently-working output (regression risk); keeping the LLM as a further fallback re-introduces the probabilistic layer this story exists to delete. Deterministic-only, on-failure-only, is the minimal correct design (Jay-approved 2026-07-12).
- **Prompt-file disposition (AC3):** `prompts/scenario/yaml_syntax_repair.md` is **kept on disk, unused** — the code that fetched it is deleted, but removing the file and its Langfuse seed is a separate prompt-hygiene chore deferred to a cleanup pass (no runtime path references it, so it is inert).
- **Review fix (2026-07-12): mark-targeted repair.** Code review found the whole-document normalizer corrupted valid sibling free-text lines on any parse failure (quotes/comment/empty). Reworked to `_blockify_line` (single flagged line) + `_reparse_repairing_freetext` (bounded loop keyed on `YAMLError.problem_mark.line`); `_yaml_text` now shares the fence-strip preprocessing with `_parse_yaml` so mark line indices align. Added `test_repair_does_not_corrupt_valid_siblings` (the regression) and `test_repair_multiple_broken_freetext_lines_in_one_doc` (the loop). See AC2 amendment.
- **Files:** `src/yt_flow/pipeline/nodes/scenario_chain.py` (`_yaml_text`/`_blockify_line`/`_reparse_repairing_freetext` + `_call_stage_with_retry`) and its test module.
- [Source: this-session root-cause analysis; 6-4 story Run 2 YAMLError note; 6-10 Review Follow-up #1; 6-3-6-4-review-metrics-report.md '2026-07-12 Story 6.10']

### Review Findings

_Code review 2026-07-12 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). All 3 layers ran._

- [x] [Review][Decision→Fixed] `_blockify_freetext_scalars` rewrites ALL matching free-text lines, corrupting previously-valid siblings — RESOLVED via mark-targeted repair (Jay chose option a). See AC2 amendment + Dev Notes "Review fix". [src/yt_flow/pipeline/nodes/scenario_chain.py] — On any parse failure the normalizer loops the whole document and unconditionally blockifies every `FREETEXT_KEYS` line, not just the line PyYAML choked on. Empirically confirmed: in a doc broken on one line, a valid quoted sibling gains literal quotes (`"SCP-049: plague doctor"` → value `'"SCP-049: plague doctor"'`), a trailing `# comment` is swallowed into the value, and an empty `image_prompt: ""` becomes `'""'` — flipping a transition marker into a rendered shot with a garbage prompt. Silent, passes validation, flows to video. The docstring claims "byte-preserving" and "a value that parsed fine is never rewritten" — both false (AC2 invariant violated). **Decision needed:** (a) minimal — skip already-quoted values (`val[:1] in ('"', "'", "|", ">")`); kills the quote/escape/empty-`""` class, stays within AC2's line-by-line algorithm, leaves the rarer `#`-comment class; or (b) mark-targeted — repair ONLY the failing line via `MarkedYAMLError.problem_mark.line`; kills every class but deviates from AC2 (needs AC2 amendment). Either way add a test with a valid quoted/comment/empty sibling asserting it is untouched (current tests only feed already-broken lines, so this passed unnoticed).
- [x] [Review][Patch→Fixed] AC3 prompt-file disposition not recorded in Dev Notes — RESOLVED: Dev Notes now states `yaml_syntax_repair.md` is kept on disk, unused, with seed cleanup deferred.
- [x] [Review][Note] Out-of-scope Story 6-12 (A/B gate freeze) changes mixed into the working tree — `scripts/eval_prompts.py`, `tests/test_eval_prompts.py`, `docs/PROMPT_POLICY.md`, `epics.md`, `sprint-status.yaml`. Not a defect (internally consistent, tested); commit separately from 6.11.

## Change Log

- 2026-07-12: Story created from a live SCP-049 unquoted-colon hard-fail during the 6.10 promotion gate. Root-caused this session: 6.5–6.10 each removed a different crash class or improved measurement, but the free-text-colon class was only ever *retried* (6.4 bounded retry) or handed to a free-form LLM repair (6.7) that reproduces it. Jay's decision: replace the LLM syntax-repair with a deterministic block-literal normalizer. Status: backlog.
