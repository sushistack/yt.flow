---
created: 2026-07-10
baseline_commit: 79543855e99b8b6305a24abf3c93d147d8a073a1
story_key: 6-4-scenario-yaml-output-bounded-retry
story_id: "6.4"
epic: 6
previous_story: 6-3-prompt-cache-hit-optimization
depends_on:
  - 6-1-prompt-policy-variant-label-wiring   # candidate/production label + fallback wiring this story's re-seeded templates go through
  - 6-2-golden-set-offline-eval              # promotion gate this story's re-seeded templates must pass before touching production
related:
  - 6-3-prompt-cache-hit-optimization        # touches the SAME 8 prompt files (section reordering, uncommitted/ready-for-dev) — see Coordination Hazard below
evidence: "2026-07-10 live repro investigation (Jay + session): golden-set gate runs (3x) and isolated repro scripts against SCP-173/SCP-049 captured intermittent scenario-stage failures. Confirmed 3 distinct failure classes, not one: (1) truncation (finish_reason=length, already-documented risky default — scripts/eval_prompts.py:_RISKY_DEFAULT_MAX_TOKENS=8192), (2) pure JSON syntax breakage (json.JSONDecodeError, e.g. \"Expecting ',' delimiter: line 44 column 21\") reproduced ONLY on candidate-labeled stages with finish_reason=stop (i.e. not truncation), (3) valid-JSON-wrong-shape (visual_breakdown returned visual_descriptions as a non-list) reproduced live against SCP-173 in this session. DeepSeek's response_format={\"type\":\"json_object\"} demonstrably does not prevent (2), ruling out the assumption that JSON mode is a hard grammar guarantee on this API."
---

# Story 6.4: Scenario Chain YAML Output + Bounded Stage-Level Retry

Status: in-progress

## Story

As Jay,
I want the scenario chain's DeepSeek stage calls to emit YAML (block-literal style for free-text fields) instead of JSON, and any stage whose output fails to parse/validate to get exactly one self-correcting retry with the error fed back into the same prompt,
so that intermittent malformed-output failures stop silently failing an entire `scenario_node` run that otherwise cost 22-57 DeepSeek calls to produce.

## Context

Live repro this session (see `evidence` above) found three independent scenario-stage failure classes, not one:

1. **Truncation** (`finish_reason == "length"`) — already understood and already has an explicit guard (`scenario_chain.py`'s `_call_stage` raises a clear "response truncated" `ValueError`). `deepseek_max_tokens` defaults to `8192`, which `scripts/eval_prompts.py` already flags via `_RISKY_DEFAULT_MAX_TOKENS` as truncation-prone. **Raising this default is explicitly out of scope for this story** (Jay's call) — it's a separate, already-diagnosed lever.
2. **Pure JSON syntax breakage** — `json.JSONDecodeError` (`Expecting ',' delimiter`, etc.) reproduced live against `SCP-173`/`SCP-049` on `candidate`-labeled stages specifically, always with `finish_reason == "stop"` (the model itself believes it finished cleanly). This rules out truncation as the cause. Byte-exact root cause (unescaped quote vs. literal newline inside a free-text field) was **not** confirmed — several live repro attempts to capture the raw broken payload were inconclusive/flaky and capturing it reliably would cost more DeepSeek calls than justified, so this story does not gate on that confirmation. What IS confirmed: DeepSeek's `response_format: {"type": "json_object"}` does **not** prevent this class of failure on this API — so "we already have a hard JSON grammar guarantee" is not a real constraint standing in this story's way.
3. **Valid JSON, wrong shape** — reproduced live this session: `visual_breakdown_step` raised `visual_breakdown: expected 1:1 sentence-to-shot mapping (8 sentences), got non-list` — i.e. the JSON parsed fine but `visual_descriptions` wasn't a list. This is a schema-adherence problem, not a serialization-format problem; YAML does not fix it.

Given (1) is already understood/out of scope and (3) is orthogonal to serialization format, the only lever left that YAML plausibly helps is (2) — and even there, only via removing the *need* to escape quotes/newlines inside JSON string values (YAML block-literal scalars, `|`, take raw text verbatim, no escaping). Since neither serialization format alone fixes (1) or (3), and DeepSeek's `json_object` mode isn't preventing (2) as advertised, the actual fix that improves reliability across **all three** classes is a **bounded stage-level retry**: catch the parse/validation failure, feed the exact error back into the same prompt, and re-call that one stage exactly once before giving up. This mirrors the project's existing bounded-retry precedent (5-23 ComfyUI crash mitigation's single post-recovery retry, 5-11's segmentation-failure shot fallback) — never open-ended, always exactly one extra attempt, then let the original failure surface unchanged.

**Incidental finding, must be handled before touching prompt content**: `scripts/migrate_prompts.py`'s `SOURCE_TO_NAME` mapping expects `prompts/scenario/format_guide.md` as the seed source for `scenario/format_guide` — but that file **does not exist** in this repo (confirmed via `find`). The prompt currently served in Langfuse under `production`/`candidate` was never committed, an existing violation of `docs/PROMPT_POLICY.md` Rule 1 ("repo is source of truth"). It exists at `/mnt/work/projects/yt.pipe/templates/scenario/format_guide.md` in the reference Go project, but that may not match the actual current Langfuse `production` content byte-for-byte (Langfuse content is the ground truth for what's *currently running* — see Task 1).

## Acceptance Criteria

1. **Given** `prompts/scenario/format_guide.md` does not exist in this repo, **Then** it is created by pulling the current `production`-label content from Langfuse via `prompt_service.get_prompt("scenario/format_guide")` (`.prompt`/raw text, not `.compile()`'d) and committing it verbatim — restoring PROMPT_POLICY Rule 1 compliance before any further edit. If the pulled content differs meaningfully from `yt.pipe`'s reference version, keep the Langfuse (currently-live) version — it's what's actually running.
2. **Given** each of `prompts/scenario/{format_guide,research,structure,writing,cast_decision,visual_breakdown,review,critic_agent,tts_normalize}.md`, **Then** the "Output ONLY a JSON object..." instruction and its fenced ` ```json ` schema example are replaced with an equivalent YAML instruction and a fenced ` ```yaml ` example, using block-literal (`|`) style for every free-text field (`narration`, `image_prompt`, `negative_prompt`, `core_identity`, `frozen_descriptor`, `entity_sheet`, `story_logline`, each `hooks` entry, `feedback`, `chain_of_thought`-shaped text where present). The underlying schema (field names, types, nesting) is **unchanged** — only the serialization instructions and examples change. Existing content additions from other in-flight work (e.g. 5-22's ending-variety/designation rules in `writing.md`/`review.md`) must be preserved, not reverted.
3. **Given** `scenario.py`'s `_call_deepseek`, **Then** the request body's `"response_format": {"type": "json_object"}` key is removed entirely (defaults to plain-text completion on DeepSeek's OpenAI-compatible endpoint) — no other part of `_call_deepseek`'s signature or return shape (`content, usage, finish_reason`) changes.
4. **Given** every `json.loads(raw)` call site in `scenario_chain.py` (all 8: `research_step`, `structure_step`, `writing_step`, `cast_decision_step`, `visual_breakdown_step`, `review_step`, `critic_step`, `tts_normalize_step`), **Then** each is replaced by a single shared helper (e.g. `_parse_yaml(raw: str) -> object`) that (a) strips a leading/trailing ` ```yaml `/` ``` ` fence if present (defensive — the prompt says not to emit one, but models sometimes do anyway), then (b) calls `yaml.safe_load`. `yaml.YAMLError` is not swallowed here — it propagates to the caller exactly like `json.JSONDecodeError` did before.
5. **Given** any `*_step` function's existing parse-then-validate logic, **Then** it is refactored so the parse+validate sequence is a local closure passed to a new shared wrapper, e.g. `_call_stage_with_retry(prompt_name, variables, s, call_deepseek, parse, *, label=None)`, which: calls `_call_stage` with `variables | {"parse_error": ""}`; runs `parse(raw)`; on `(yaml.YAMLError, ValueError)`, re-renders the **same** prompt with `variables | {"parse_error": f"<previous error message>. Output ONLY valid YAML, no prose, no markdown code fences."}` and calls `_call_stage` + `parse` exactly one more time; if that second attempt also raises, the exception propagates unchanged (no swallowing — `scenario_node`'s existing outer `try/except` still surfaces it as `PipelineState.error`, same as today). Every `*_step`'s existing validation error messages/wording are preserved verbatim — only where the raw text comes from changes.
6. **Given** all 9 prompt templates from AC2, **Then** each gets a new `{{parse_error}}` placeholder inserted once, near the top of the "## Task" section, rendered as an empty string on a normal (first) call — same convention as the existing always-present-but-usually-empty `{{glossary_section}}` variable.
7. **Given** the 9 changed prompt templates, **Then** they follow `docs/PROMPT_POLICY.md`'s unchanged change protocol in full: edit → seed under `candidate` (`uv run python scripts/migrate_prompts.py --label candidate --source prompts`) → pass `uv run python scripts/eval_prompts.py --label candidate --baseline production` → promote by moving the `production` label. This story does not modify the policy or the gate script itself.
8. **Given** `tests/fixtures/cassettes/deepseek_*.json`, **Then** each cassette's `choices[0].message.content` is updated to hold YAML text (not JSON) matching the new output contract, and new regression tests cover: (a) a stage's first attempt raising `yaml.YAMLError`/`ValueError` followed by a successful second attempt (bounded retry succeeds, `parse_error` populated on the retry call's variables), (b) both attempts failing still raises/surfaces the original second-attempt error unchanged (bounded, not infinite — no third call), (c) ` ```yaml `-fenced model output still parses via the stripping helper.
9. **Given** one real SCP executed live end-to-end against the `candidate` label after all prior ACs land, **Then** the run is recorded as evidence in this story's Dev Agent Record (pass/fail, whether the bounded retry fired, on which stage if so) — this cannot prove the flaky bug is gone for good, but it confirms the new contract works at least once live before promotion.

## Tasks / Subtasks

- [x] Task 1: Pull current `scenario/format_guide` production content from Langfuse and commit as `prompts/scenario/format_guide.md`. (AC:1)
- [x] Task 2: Add PyYAML as a **direct** dependency (`uv add pyyaml`) — it's currently only a transitive dependency (present in `uv.lock` via other packages, not declared in `pyproject.toml`). (AC:4)
- [x] Task 3: Add `_parse_yaml(raw: str) -> object` helper to `scenario_chain.py` (fence-strip + `yaml.safe_load`), replace all 8 `json.loads(raw)` call sites. (AC:4)
- [x] Task 4: Add `_call_stage_with_retry` to `scenario_chain.py`; refactor each `*_step`'s parse+validate block into a local `parse` closure and route it through the new wrapper instead of calling `_call_stage` + inline parse directly. (AC:5)
- [x] Task 5: Remove `response_format` from `_call_deepseek`'s request body in `scenario.py`. (AC:3)
- [x] Task 6: Edit all 9 prompt templates — YAML output instructions/examples (block-literal for free-text fields) + `{{parse_error}}` placeholder. Preserve unrelated recent content (5-22's ending-variety/designation rules, etc.). (AC:2, 6)
- [x] Task 7: Update `tests/fixtures/cassettes/deepseek_*.json` cassette content to YAML; add bounded-retry-succeeds / bounded-retry-exhausts / fenced-output tests. (AC:8)
- [ ] Task 8: Seed `candidate` label, run golden-set gate, iterate until it passes; do not promote to `production` until it does. (AC:7) — **partially done, see Completion Notes**: seeded 3x, ran gate live, found+fixed 2 real bugs the gate caught. Left unchecked because the combined 3-SCP gate has not cleanly PASSed (one item, SCP-173, is a borderline noisy FAIL) and `production` was NOT promoted — Jay's explicit direction to stop spending live-API budget chasing what looks like judge-scoring noise. Promotion decision deferred to Jay.
- [x] Task 9: Live-run one SCP against `candidate`; record pass/fail and whether the retry fired in Dev Agent Record. (AC:9)

### Review Findings

- [x] [Review][Patch] Route malformed YAML scene/shot items through bounded retry [`src/yt_flow/pipeline/nodes/scenario_chain.py`]
- [x] [Review][Patch] Validate sentence coverage and boolean `overall_pass` before accepting YAML [`src/yt_flow/pipeline/nodes/scenario_chain.py`]
- [x] [Review][Patch] Sanitize and cap model-derived validation feedback before retry [`src/yt_flow/pipeline/nodes/scenario_chain.py`]
- [x] [Review][Patch] Add focused regression coverage for review fixes [`tests/pipeline/nodes/test_scenario_chain.py`]
- [ ] [Review][Decision] Exact first-attempt YAML parse-error/retry rate is unavailable in historical evidence; no new live calls were made to manufacture a denominator.
- [ ] [Review][Decision] Full three-item golden gate and production promotion remain incomplete under the token-minimization direction.

## Dev Notes

### Source Context

- Epic 6 goal: prompt lifecycle is versioned + labeled + eval-gated using Langfuse's native features only. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- This story's own epics.md entry has the full failure-class breakdown and the coordination-hazard note vs. 6.3. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.4: 시나리오 체인 YAML 출력 전환 + 스테이지 단위 bounded 재시도`]
- Original 6-stage chain design (still the current shape — this story does not restructure the chain, only each stage's serialization + a wrapping retry): [Source: `docs/superpowers/specs/2026-07-03-scenario-multistage-design.md`]
- `docs/PROMPT_POLICY.md` — the unchanged change protocol this story's prompt edits must follow (candidate → gate → promote), and Rule 1 (repo is source of truth) that Task 1 restores compliance with.

### Existing Code To Reuse / Modify

- `_call_stage` (`scenario_chain.py` — fetches/compiles the Langfuse prompt, calls DeepSeek, raises on truncation) stays as the low-level primitive; do not duplicate its truncation-check logic in the new retry wrapper — call `_call_stage` twice (bounded), don't reimplement it.
- Every `*_step` function (`research_step`, `structure_step`, `writing_step`, `cast_decision_step`, `visual_breakdown_step`, `review_step`, `critic_step`, `tts_normalize_step`) already has its own hand-written schema validation (`ValueError` with a descriptive message) immediately after `json.loads(raw)` — reuse that logic verbatim inside each stage's new `parse` closure, just swap `json.loads` for `_parse_yaml`.
- `prompt.compile(**variables)` is Langfuse's mustache-style `{{var}}` substitution — passing an extra `parse_error` variable that a template doesn't yet reference is harmless; the template edit (AC6) is what actually surfaces it. Mirrors the existing `glossary_section` pattern (`_call_stage` variables dicts already always include it, usually empty).
- `docs/PROMPT_POLICY.md`'s `scripts/migrate_prompts.py --label candidate --source prompts` is the only path to seed changed prompts — never hand-edit in the Langfuse UI (Rule 5).

### Coordination Hazard — Story 6.3

[Story 6.3](_bmad-output/implementation-artifacts/6-3-prompt-cache-hit-optimization.md) is `ready-for-dev` and **uncommitted** — it reorders sections in the same 8 `prompts/scenario/*.md` templates (moving invariant blocks like `format_guide`/`frozen_descriptor`/`entity_sheet`/`story_logline` ahead of per-scene blocks), without changing wording. This story changes wording (JSON→YAML instructions) without changing order. These are compositionally compatible but will diff-conflict if implemented in parallel on separate branches/worktrees. **Do not implement both at once in isolated worktrees and merge separately** — whichever lands second must rebase its change on top of the first's, in the same working tree. If picking one to do first, either order is fine; there's no dependency, only a sequencing hazard.

### Why Not Just Raise `deepseek_max_tokens`?

That's a real, already-diagnosed fix for failure class (1) (truncation) alone — `scripts/eval_prompts.py` already warns about the current `8192` default via `_RISKY_DEFAULT_MAX_TOKENS`. It's explicitly out of scope here per Jay's direction; this story is scoped to classes (2) and, incidentally via the retry mechanism, a mitigant for (3). If truncation-class failures are still a problem after this story ships, that's a separate, smaller follow-up (bump one config default), not a reason to reopen this one.

### Why YAML Doesn't Need Its Own New Failure-Recovery Design

The bounded retry (AC5) is format-agnostic — it activates on *any* `yaml.YAMLError` (e.g. an indentation mistake the model makes) or `ValueError` (schema violation) from the `parse` closure, regardless of cause. This is deliberate: rather than trying to make YAML generation bulletproof up front (e.g. a separate Pydantic-model-repair pass, considered and rejected as premature — YAGNI), the one bounded retry is the single mechanism that catches indentation errors, syntax errors, and schema violations alike. If bounded retry alone proves insufficient after live use, escalate then — don't build the heavier repair pipeline speculatively now.

### Project Structure Notes

- New file: `prompts/scenario/format_guide.md` (Task 1).
- Modify: `prompts/scenario/*.md` (all 8 existing + the new `format_guide.md` — 9 total), `src/yt_flow/pipeline/nodes/scenario_chain.py` (`_parse_yaml`, `_call_stage_with_retry`, all 8 `*_step` functions), `src/yt_flow/pipeline/nodes/scenario.py` (`_call_deepseek`'s request body), `pyproject.toml`/`uv.lock` (PyYAML direct dependency), `tests/fixtures/cassettes/deepseek_*.json`, `tests/pipeline/nodes/test_scenario_chain.py`.
- No new Settings fields, no new module files beyond the one prompt template.

### Out Of Scope

- Raising `deepseek_max_tokens`'s default (truncation-class fix) — separate, already-diagnosed lever, deliberately not bundled here.
- Reducing DeepSeek call count — unrelated axis, covered (or not) by Story 6.3.
- A Pydantic-schema-repair or multi-pass validation pipeline for the YAML output — the bounded single retry is the chosen mitigation; a heavier repair pipeline is explicitly deferred unless the bounded retry proves insufficient in practice.
- Confirming the exact byte-level cause of the original JSON syntax failures (unescaped quote vs. literal newline vs. something else) — inconclusive after live repro attempts this session, not required to justify the YAML block-literal approach (block literals structurally avoid the entire class of escaping mistakes regardless of which specific character triggered any one incident).

### References

- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py] — `_call_stage`, all 8 `*_step` functions, all current `json.loads` sites
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L44-L66] — `_call_deepseek`, the `response_format` removal site
- [Source: docs/PROMPT_POLICY.md] — unchanged change protocol this story's prompt edits must follow
- [Source: scripts/eval_prompts.py#L57-L58,L471-L475] — `_RISKY_DEFAULT_MAX_TOKENS` truncation warning (context for what's explicitly out of scope)
- [Source: tests/fixtures/cassettes/README.md] — cassette conventions to preserve when converting content to YAML

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5

### Debug Log References

- Live golden-set gate runs (this session, `scripts/eval_prompts.py --label candidate --baseline production`, `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 --timeout 900`): full 3-SCP run, then isolated `--scp-id` re-checks for SCP-096 and SCP-173. Logs were written to a scratch dir, not persisted in-repo (ephemeral eval-prompts runs already write per-item artifacts under `tmp/eval-prompts/` on failure per the existing script convention).
- Standalone live probe script (ad hoc, not committed) calling `research_step`/`structure_step`/`writing_step` directly against the `candidate` label for SCP-096 — used to inspect raw parsed `narration` text and confirm the embedded-newline hypothesis (`"\n" in narration` → `True`).

### Completion Notes List

- **Incidental second Rule-1 gap found (beyond AC1's `format_guide.md`)**: `prompts/scenario/critic_agent.md` was also never committed — same `docs/PROMPT_POLICY.md` Rule 1 violation, undetected by the story's own evidence-gathering. Pulled current `production` content from Langfuse the same way as AC1 (differs from `yt.pipe`'s reference only in mustache vs. `{var}` placeholder syntax and trailing newline — not meaningful; kept the Langfuse version) and committed it.
- **Coordination hazard with Story 6.3 materialized live, not just theoretically**: 6-3 was implemented concurrently in the same working tree during this session, reordering `prompts/scenario/{cast_decision,visual_breakdown,research,structure,writing,review}.md` and extending `_call_stage`/`_call_stage_with_retry`/every `*_step` with a `usage_sink` parameter for token/cache observability. The extension was additive and non-breaking (6-3's session read this story's `_call_stage_with_retry` and threaded `usage_sink` through both the first and retry call, preserving the bounded-retry contract exactly). One live collision did surface: 6-3's reorder of `cast_decision.md` briefly dropped the `{{scene_num}}` header placeholder that a pre-existing test asserted on; resolved when the 6-3 session itself updated that test's requirement (not reverted by this story).
- **Two real bugs found only by running the actual golden-set gate live, not by local tests**:
  1. `_parse_yaml`'s fence-strip regex only recognized ` ```yaml `/bare ` ``` ` fences. Without `response_format: json_object` (removed per AC3, applies to *every* call regardless of label), DeepSeek's `production`-label calls (still running the pre-YAML JSON prompts) started fencing their JSON output as ` ```json `, which the narrower regex didn't strip — `yaml.safe_load` then choked on the leading backtick. This broke `production` immediately on the first gate run. Fixed by widening the fence regex to accept any language tag (or none).
  2. YAML `|` block-literal fields let DeepSeek write one sentence per physical line (something a JSON string value structurally prevented) — proven live via a standalone probe against SCP-096's `writing_step`. The embedded literal newlines read as "choppy" to the review/critic LLM judge and measurably regressed `narrative_coherence`/`atmosphere`/`article_fidelity` scores on the golden-set gate even though sentence content was unchanged. Fixed with `_normalize_freetext` (collapse whitespace runs to single spaces) applied to every AC2-listed block-literal free-text field (`narration`, `image_prompt`, `negative_prompt`, `core_identity`, `frozen_descriptor`, `entity_sheet`, `story_logline`, `hooks`, `feedback`) across `research_step`, `writing_step`, `visual_breakdown_step`, `critic_step`, and `tts_normalize_step`; also softened the `narration` field's prompt wording in `writing.md`/`tts_normalize.md` to explicitly ask for one continuous line.
- **Golden-set gate status (AC7 / Task 8)**: after both fixes, isolated `--scp-id` re-checks: SCP-049 PASS (+0.67, first run before either fix was even needed), SCP-096 PASS (+2.67, confirms fix #2). SCP-173 stayed a "regressed" verdict across two re-checks, but the failing axis and sign flipped between runs (-0.67/-0.33 → +0.00/+0.67) while `total_delta` flipped from -0.67 to **+0.33** — consistent with LLM-judge scoring noise given the gate's zero-tolerance "any single negative axis = FAIL" rule, not a reproducible code defect. Did not re-run the combined 3-SCP gate or promote `candidate` → `production` — Jay's explicit call to stop spending live-DeepSeek/judge budget chasing what presents as noise. `candidate` label remains seeded with all fixes; promotion is deferred to Jay's judgment (Task 8 left unchecked).
- **AC9 live evidence**: every live run this session (SCP-049, SCP-096 ×2, SCP-173 ×2, all against `candidate`) completed the full `scenario_node` multi-stage chain without an unhandled exception — the YAML+bounded-retry contract held structurally on every attempt. Bounded retry firing was not directly observable (no retry-specific log line exists in `_call_stage_with_retry`); the standalone SCP-096 probe (research/structure/writing) succeeded on the first attempt each time, no retry triggered. No live run after the fence-stripping fix landed hit a `yaml.YAMLError`/malformed-shape failure.
- Full regression suite green throughout (1175 passed, 1 pre-existing skip); `tests/pipeline/nodes/test_scenario_chain.py` alone: 188 passed, including 9 new tests for `_parse_yaml`/`_call_stage_with_retry`/bounded-retry semantics and 5 new tests for the whitespace-normalization fix. `ruff check` clean on all touched files.

### File List

- `prompts/scenario/format_guide.md` (new — Task 1, AC1)
- `prompts/scenario/critic_agent.md` (new — incidental second Rule-1 gap, same treatment as AC1)
- `prompts/scenario/research.md` (modified — YAML instructions, `{{parse_error}}`, free-text normalization awareness)
- `prompts/scenario/structure.md` (modified — YAML instructions, `{{parse_error}}`)
- `prompts/scenario/writing.md` (modified — YAML instructions, `{{parse_error}}`, narration continuous-line wording)
- `prompts/scenario/cast_decision.md` (modified — YAML instructions, `{{parse_error}}`)
- `prompts/scenario/visual_breakdown.md` (modified — YAML instructions, `{{parse_error}}`, few-shot examples converted)
- `prompts/scenario/review.md` (modified — YAML instructions, `{{parse_error}}`)
- `prompts/scenario/tts_normalize.md` (modified — YAML instructions, `{{parse_error}}`, narration continuous-line wording)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (modified — `_parse_yaml`, `_normalize_freetext`, `_call_stage_with_retry`, all 8 `*_step` functions refactored to closures)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified — `response_format` removed from `_call_deepseek`)
- `pyproject.toml` / `uv.lock` (modified — PyYAML promoted to a direct dependency)
- `tests/fixtures/cassettes/deepseek_{research,structure,writing,cast_decision,visual_breakdown,review,critic,tts_normalize}.json` (modified — content converted from JSON to YAML)
- `tests/pipeline/nodes/test_scenario_chain.py` (modified — new tests for `_parse_yaml`, `_call_stage_with_retry` bounded-retry semantics, and free-text newline normalization)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — story status)

## Change Log

- 2026-07-10: Implemented JSON→YAML conversion + bounded stage-level retry (AC1-6, AC8-9). Live golden-set gate testing surfaced and fixed 2 real bugs beyond the story's original scope: a fence-strip regex gap that broke the `production` label, and a YAML block-literal newline-embedding defect that hurt judge scores across `narrative_coherence`/`atmosphere`/`article_fidelity`. Task 8 (AC7) left open — candidate seeded and iterated 3x, but one golden-set item (SCP-173) shows a noisy borderline gate result; per Jay's direction, did not spend further live-API budget chasing it and did not promote to `production`. Deferred to Jay's judgment.
