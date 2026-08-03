---
created: 2026-08-03
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
story_key: 8-19-embedding-asset-retrieval-layer
story_id: "8.19"
epic: 8
previous_story: 8-18-cast-decision-diversity-validator
depends_on:
  - 8-6-asset-library-management
  - 8-17-location-plate-data-generation
related:
  - 8-18-cast-decision-diversity-validator
  - 13-1-surface-silent-degradations
workflow_decision: "Diagnosis first. If reuse-selection failure is confirmed, improve constrained LLM selection and add only a conservative stdlib matcher in scenario_chain.py. Embeddings and asset_retrieval_service.py remain a separately justified escalation, never default scope."
completion_note: "Ultimate context engine analysis completed - comprehensive developer guide created"
---

# Story 8.19: Asset-Reuse Selection — stdlib/LLM First, Embeddings Last

Status: done

## Story

> The epic entry is a draft and contains no verbatim user-story statement. The following is a faithful synthesis of its intent.

As Jay,
I want STOCK character and location reuse decisions to be evidence-backed and constrained to known asset keys, with a safe free-generation outcome,
so that narration and imagery stay aligned without adding an embedding stack unless simpler matching is demonstrably insufficient.

## Context and Decision Ladder

Image–narration mismatch continued to be observed after Story 5.5, but the proposed cause—incorrect STOCK-reuse versus free-generation selection—is explicitly a hypothesis, not a confirmed diagnosis. The epic requires this ladder:

1. **Stage 0 — prove the cause:** trace 3–5 recent mismatches end-to-end before changing code.
2. **Stage 1 — no new dependency:** give the LLM explicit key/description choices plus `None`, validate the structured result, and use conservative stdlib text matching only where the evidence requires it.
3. **Stage 2 — conditional escalation:** only measured residual semantic misses after Stage 1 may open a separate decision to add a local embedding implementation.

> **This paragraph's premise was FALSE and is corrected here at source (review, 2026-08-03).** The
> story context asserted "the current checkout cannot complete Stage 0: `yt_flow.db` has no `run` rows
> and `workspace/` contains no per-run scenario/image/video artifacts." Re-verified independently
> during review: **172 `run` rows, 2,075 checkpoints, 260 `workspace/` directories**, including
> complete runs with rendered video. Stage 0 was fully executable and was executed — see Dev Agent
> Record → Diagnostic Evidence. Nothing downstream of this paragraph relied on the false claim.

Historical evidence identifies other root causes: Story 8.11 found that a whole scene displayed only its first shot; iteration 1 had ten empty-background shots because `SCP-049-2` cards were missing; and all `location_key` values in that run were `None` because the prompt was not live. Do not reuse those cases as proof of this story's hypothesis.

## Acceptance Criteria

1. **Blocking diagnosis gate.** Before production-code or prompt edits, document 3–5 traceable, recent image–narration mismatch cases. Each row records: run ID, scene/shot, narration sentence, `image_prompt`, emitted `cast`/`location_key`, eligible approved asset key(s), final asset source (STOCK or generated), expected decision (`key` or `None`), observed frame, and root-cause classification. Classifications distinguish at least selection failure, missing/unapproved asset, prompt/parser failure, generation noise, and downstream composition/substitution failure. Evidence must come from real artifacts/checkpoints/logs; it must not be reconstructed or invented.
2. **Honest stop condition.** If fewer than 3 traceable cases are available, or the evidence does not support reuse-selection failure as a material cause, stop without changing runtime code, prompts, dependencies, or configuration. Record the result and recommended owning story in this file's Dev Agent Record. This evidence-backed no-code outcome satisfies the story; do not implement speculative retrieval.
3. **Stage-1 scope gate.** Only if AC1 supports the hypothesis, implement the smallest affected namespace demonstrated by the evidence—location selection first unless cast selection is independently proven. Do not generalize arbitrary SCP or derived `<scp_id>-<n>` identity keys into fuzzy STOCK-character matching.
4. **Constrained LLM selection.** For each affected namespace, the relevant repo prompt receives a compact controlled catalog of allowed key plus description/aliases and requires exactly one catalog key or the existing no-reuse outcome (`None`/omission; empty cast where applicable). Returned keys remain subject to the current strict/lenient parser contracts: hallucinated or malformed keys never become asset identities and safely degrade to the existing fallback.
5. **Narrow pure matcher.** If Task 0 demonstrates that structured catalog selection alone is insufficient, add a total, deterministic pure helper with the conceptual contract `text + typed candidates -> unique best key or None`. It uses controlled aliases/keyword overlap first and may use `difflib.SequenceMatcher` only as a lexical tie aid. It never raises, never queries DB, never mutates input state, and never crosses asset namespaces.
6. **Precision-first fallback.** The matcher returns `None` for empty input/catalog, anomaly-specific environments, below-threshold scores, ambiguous ties, or insufficient winner margin. Thresholds and margin are calibrated on diagnosed positive and negative examples—not copied from a generic documentation example. A false STOCK match is worse than the existing free-generation fallback.
7. **Preservation rules.** A valid explicit catalog key and an explicit no-reuse decision are not rewritten by weak fuzzy evidence. Matcher integration is mark-targeted: unrelated shots and all non-selection fields (`image_prompt`, `negative_prompt`, cast placement/motion, camera fields, sentence indices) remain byte-identical. Existing 1:1 sentence coverage, bounded retry, `_enforce_camera_variety`, `_enforce_cast_diversity`, and derived-entity provisioning remain unchanged.
8. **Runtime consumption remains approved-only.** Scenario code does not query asset tables. `LocationService` and existing character resolution remain the authorities that expose approved assets; a missing lookup continues to warn and fall back non-fatally to normal generation. No asset lifecycle, manifest, style epoch, path, DB schema, image-node copy logic, or cleanup behavior changes.
9. **Decision evidence.** Stage-1 evaluation records, at minimum in diagnostic/test evidence and structured logs, the candidate namespace, selected key/`None`, match method, score/reason, threshold, and ambiguity result. This story does not add UI or gate-warning plumbing; Story 13.1 owns visible run-level degradation warnings.
10. **Stage-1 verification.** Automated tests cover exact key/alias, Korean controlled synonyms, keyword overlap, lexical near-match, unrelated negative, ambiguity/tie, empty input/catalog, Unicode normalization, determinism, idempotence, valid-key/no-reuse preservation, hallucinated-key fallback, and `build_scenes` integration. Existing cast, location parser, camera/cast validator, stub-profile, and free-generation tests remain green.
11. **Prompt deployment follows current policy.** Repo prompt files remain the source of truth. In current DEV MODE, any prompt change is seeded directly with `uv run python scripts/migrate_prompts.py --label production --source prompts`; no A/B, golden-set, promotion gate, `--baseline`, or `YTFLOW_ALLOW_AB_GATE` action is required or permitted as completion evidence.
12. **Embedding escalation is not part of Stage 1.** If Stage 1 resolves the diagnosed cases, `pyproject.toml`, `config.py`, and `src/yt_flow/services/asset_retrieval_service.py` do not change. Only if documented Stage-1 replay still fails on semantic paraphrase/homonym cases may the developer stop and propose Stage 2 with research covering Korean retrieval quality, commercial license, local footprint, determinism, and dependency impact. Do not install or stub an embedding model in this story without that evidence and an explicit scope decision.
13. **No graph or product-surface changes.** The LangGraph topology remains `scenario → image → tts → subtitle → video`; no new node, API, DB table, UI, asset-generation path, curation flow, compositing behavior, or paid retrieval API is added.
14. **Quality gates.** For a Stage-1 implementation, run `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q`, all directly affected test files, `uv run pytest -q`, and Ruff on changed Python files. Repository coverage remains at least 80%.

## Tasks / Subtasks

- [x] Task 0: Execute the blocking diagnosis (AC: 1, 2)
  - [x] Obtain 3–5 recent run artifacts/checkpoints/logs from the actual runtime environment; this checkout alone is insufficient.
  - [x] Build the evidence table with the fields and classifications in AC1.
  - [x] Decide `SUPPORTED` or `NOT SUPPORTED`, citing every case.
  - [x] If `NOT SUPPORTED` or evidence is unavailable, record the redirect/no-code conclusion and stop.
- [x] Task 1: Define Stage-1 candidate scope from evidence (AC: 3, 8)
  - [x] Select `location`, `cast`, or both only when separately supported.
  - [x] Identify a runtime-safe source for compact controlled descriptions/aliases; do not import `scripts/seed_*` from production code and do not duplicate generation prompts blindly.
  - [x] Assert catalog coverage against `LOCATION_KEYS` and/or `STOCK_CAST_KEYS` for any namespace implemented.
- [x] Task 2: Strengthen structured LLM selection (conditional on Task 0) (AC: 4, 7, 11)
  - [x] Update only the affected repo prompt(s) and template variables.
  - [x] Preserve existing output counts, schemas, and explicit no-reuse semantics.
  - [x] Seed repo prompts directly to `production` under current DEV MODE after tests pass.
- [~] Task 3: Add the stdlib matcher only if diagnosed cases require it (conditional) (AC: 5–7) —
  **NOT APPLICABLE, gate resolved false.** Task 3's deliverable is AC5's `text + typed candidates ->
  unique best key or None` matcher, and it is conditional on "structured catalog selection alone is
  insufficient". Task 0 measured **0** mis-keyed or hallucinated keys in any run (re-verified in
  review across all 134 runs holding scenes), so that condition is false and no matcher was built.
  The helper that *was* built (`_suppress_cast_on_no_figure_framing`) is a different mechanism and is
  recorded under Task 2/4, not here — leaving this task's boxes unchecked is the honest record.
  - [ ] Implement the narrow pure helper in `scenario_chain.py` near the existing normalization/repair helpers.
  - [ ] Normalize controlled text deterministically; apply alias/keyword logic before any `SequenceMatcher` tie aid.
  - [ ] Calibrate threshold and winner margin on the Task-0 examples plus hard negatives.
  - [x] Preserve valid explicit keys/no-reuse outcomes unless the evidence-backed integration rule explicitly requires otherwise.
- [x] Task 4: Add regression and integration coverage (conditional) (AC: 9, 10, 14)
  - [x] Add the matcher, prompt-placeholder, parser, and `build_scenes` tests listed in AC10.
  - [x] Assert unrelated selection namespaces and all non-selection fields remain unchanged.
  - [x] Replay the diagnosed cases through Stage 1 and record before/after decisions.
- [x] Task 5: Close or escalate honestly (AC: 12, 13)
  - [x] If Stage 1 succeeds, verify no embedding/service/config/dependency changes exist.
  - [x] If semantic misses remain, document them and stop with a Stage-2 proposal; do not silently broaden this implementation.

## Dev Notes

### Current State of Files Potentially Updated

- `src/yt_flow/pipeline/nodes/scenario_chain.py`
  - **Today:** `cast_decision_step` gives DeepSeek only comma-joined STOCK cast keys and strictly parses one cast list per sentence. `visual_breakdown_step` gives it only comma-joined location keys. `parse_cast` normalizes known STOCK/SCP casing while preserving derived identities; `parse_location_key` performs exact case-insensitive canonicalization and unknown keys become `None`. `build_scenes` writes both fields and then runs the existing camera/cast deterministic repairs.
  - **Conditional change:** add catalog rendering and, only if required, one stdlib-only pure matcher at the existing normalization boundary.
  - **Preserve:** 1:1 coverage, retry/error behavior, current parsers, arbitrary SCP/derived identity handling, camera/cast repairs, and every non-selection field.
- `prompts/scenario/visual_breakdown.md`
  - **Today:** asks the LLM to choose one of 14 bare `location_key` names or omit the field; it does not receive the controlled meaning/aliases of those keys.
  - **Conditional change:** provide a compact key→description/alias catalog and sharpen key-or-omit output rules.
  - **Preserve:** background-only prompt contract, populated `image_prompt`, 1:1 shot schema, cast attachment, camera rules, and anomaly-specific free generation.
- `prompts/scenario/cast_decision.md`
  - **Today:** lists the run entity and three bare STOCK cast keys, while supporting derived entity keys.
  - **Conditional change:** only if Task 0 independently proves cast-role selection failures, add controlled role descriptions/aliases.
  - **Preserve:** the run entity and derived identities as exact opaque keys; empty cast remains valid.
- `src/yt_flow/domain/state.py`
  - **Today:** owns the canonical three `STOCK_CAST_KEYS`, 14-value `LocationKey`, and `LOCATION_KEYS` tuple.
  - **Conditional change:** only if centralizing a small pure catalog here prevents key/description drift; no state schema change is expected.
- `tests/pipeline/nodes/test_scenario_chain.py`
  - **Today:** covers prompt placeholders, cast decision parsing, `parse_location_key`, `build_scenes` location attachment, and the 8.18 deterministic repair pattern.
  - **Conditional change:** add the AC10 matrix and integration tests alongside those blocks.

Files that must remain unchanged in Stage 1 unless Task 0 exposes a separate defect: `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/services/location_service.py`, DB models, API/frontend code, video/compositing code, `config.py`, and `pyproject.toml`.

### Implementation Shape and Guardrails

- Clone Story 8.18's proven shape: pure, total, deterministic, idempotent, mark-targeted, INFO-logged, no LLM re-call, and integration-tested through `build_scenes`.
- Keep candidate namespaces typed and separate. A location query must never return a character key; arbitrary SCP/derived character identities must never fuzzy-collapse to a `STOCK-*` key.
- Use the narrowest evidence-bearing text: current shot narration plus scene location and/or current `image_prompt`. Whole-scene narration can mention several locations and is unsafe as a single query.
- Do not compare Korean narration directly against English generation prose and call the result semantic retrieval. Controlled Korean aliases are required for Korean lexical matching.
- `SequenceMatcher.ratio()` is lexical, may depend on argument order, and is not a semantic or cross-language model. If used, fix argument ordering, normalize text, set/test `autojunk` deliberately, and calibrate on project examples.
- Precision beats recall: `None` preserves the mature, non-fatal ComfyUI generation path; a false STOCK match produces a confidently wrong frame.
- Keep observability scoped: diagnostic/log evidence belongs here; gate/UI warning transport belongs to Story 13.1.

### Architecture Compliance

- **AD-1:** import direction remains `api → services → (pipeline | db) → domain`; `scenario_chain.py` must not import DB or service catalog queries.
- **AD-2/AD-4:** scenario helpers operate on freshly constructed data and return JSON-serializable keys/`None`; they do not write DB, emit SSE, or mutate asset records.
- **AD-5:** shot remains the image-generation and matching unit; do not decide once per scene when shots can occupy different locations.
- **AD-10:** unknown, ambiguous, or unavailable reuse degrades visibly to `None`/free generation; no silent forced match.
- No new pipeline stage. Approved-only asset consumption and deterministic plate variant selection stay downstream.

### Library and Framework Requirements

- Actual project pins: Python `>=3.12,<3.13`, LangGraph `1.2.7`, FastAPI `0.138.2`, SQLModel `0.0.39`, Langfuse `4.12.0`, pytest `9.1.1`, Ruff `0.15.20`.
- Stage 1 uses only the standard library; the repository currently has no embedding/CLIP dependency and DeepSeek is used through chat completions only.
- Do not add an OpenAI-compatible embedding assumption: the configured DeepSeek path has no project embedding contract.

### Testing Requirements

- Run worktree code with `PYTHONPATH=$PWD/src`; a global editable installation may otherwise shadow it.
- Test `None` and hard negatives as first-class success cases, not only positive matches.
- Include real Korean aliases and intentionally confusable pairs; do not label a hand-written easy example as semantic retrieval proof.
- Verify current fallback end-to-end: unknown/ambiguous choice → `location_key=None` → existing image generation path, with no new exception.
- If Task 0 ends the story without code, verification is the completed evidence table plus a clean diff proving no runtime/prompt/dependency files changed.

### Previous Story Intelligence

- Story 8.18/commit `fcad36f` is the template: an inline deterministic post-LLM repair with no service, no config, no prompt re-call, and exhaustive pure/integration tests.
- Its review caught a repair that displaced a healthy later sibling. Apply the same lesson here: weak evidence must not rewrite a healthy explicit decision or unrelated shot.
- Story 8.17 proved all 42 location plates are approved and the STOCK fast path fires. Code/schema existence is not evidence of correct selection; this story must inspect actual post-8.17 decisions.
- Story 8.13 fixed the documented SCP-049-2 empty-frame mismatch. Do not misclassify missing derived-card provisioning as STOCK retrieval.

### Git Intelligence

- Relevant recent commits: `fcad36f` (Story 8.18 deterministic cast validator), `76da474` (42/42 location plates approved), `eb17118` (8.17 review fixes), `b5a2b35`/`8ae36a6` (real plate generation and labeling).
- `scenario_chain.py`, its tests, and `sprint-status.yaml` are recurring edit hotspots. Preserve unrelated worktree changes and stage status edits surgically.

### Latest Technical Information

- Python 3.12 `difflib.SequenceMatcher` returns a lexical ratio in `[0,1]`; it is not guaranteed symmetric by argument order, and `autojunk` can alter matching for long repetitive sequences. The documentation's `0.6` example is illustrative, not a project threshold.
- Animate-A-Story (arXiv:2307.06940) retrieves video motion structures from text and uses them to guide synthesis. It supports retrieval-guided storytelling directionally, but it is not evidence that this project needs CLIP-based static asset matching.
- No embedding-model research is needed unless Stage-1 replay demonstrates residual semantic failures. At that point, research must be a visible escalation decision, not an implementation side effect.

### Project Structure Notes

- Stage-1 production code stays in `src/yt_flow/pipeline/nodes/scenario_chain.py` plus affected repo prompt(s) and tests.
- A new `src/yt_flow/services/asset_retrieval_service.py`, service tests, model configuration, and dependency changes belong only to an explicitly approved Stage 2.
- No UX changes: the existing scenario gate exposes `location_key`, and image review/retry already exists.

### References

- [Source: _bmad-output/planning-artifacts/epics.md:1187] — Epic 8 objective and architecture transition
- [Source: _bmad-output/planning-artifacts/epics.md:1213] — asset library identity, approval, provenance, and lifecycle
- [Source: _bmad-output/planning-artifacts/epics.md:1256] — real location-plate data generation
- [Source: _bmad-output/planning-artifacts/epics.md:1264] — Story 8.19 hypothesis and Stage 0→1→2 ladder
- [Source: _bmad-output/implementation-artifacts/epic-8-context.md:31] — Epic 8 constraints and technical decisions
- [Source: _bmad-output/implementation-artifacts/8-18-cast-decision-diversity-validator.md:29] — deterministic-repair precedent and review lessons
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md:14] — historical mismatch and non-retrieval causes
- [Source: _bmad-output/implementation-artifacts/8-11-per-shot-cut-assembly.md:39] — first-shot-only mismatch root cause
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md:37] — dependency direction and state-purity invariants
- [Source: src/yt_flow/domain/state.py:38] — canonical STOCK and location vocabularies
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:97] — current key normalization and deterministic repair helpers
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:924] — current cast-decision call and bare-key catalog input
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:999] — current visual-breakdown call and bare location keys
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:1251] — `build_scenes` integration boundary
- [Source: prompts/scenario/cast_decision.md:7] — current cast vocabulary contract
- [Source: prompts/scenario/visual_breakdown.md:205] — current location-key selection contract
- [Source: src/yt_flow/services/location_service.py:30] — approved-only plate lookup
- [Source: docs/PROMPT_POLICY.md:5] — current DEV MODE direct-production prompt workflow
- [Source: pyproject.toml:1] — actual dependency pins and coverage gate
- [Python 3.12 difflib documentation](https://docs.python.org/3.12/library/difflib.html)
- [Animate-A-Story, arXiv:2307.06940](https://arxiv.org/abs/2307.06940)

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Diagnostic Evidence and Gate Decision

**Verdict: SUPPORTED for the `cast` namespace. NOT SUPPORTED for the `location` namespace.**

Correction to this story's Context section: the claim that "`yt_flow.db` has no `run` rows and
`workspace/` contains no per-run artifacts" is false in this checkout. The DB holds 172 `run` rows
and 2,075 checkpoints; `workspace/` holds 260 directories, including complete runs with rendered
video. Task 0 was therefore executable and was executed against real artifacts.

Evidence source: LangGraph checkpoints (`checkpoints` table, newest per `thread_id`, decoded with
`JsonPlusSerializer`), the `location_plates` / `character_cards` / `characters` tables, on-disk
`workspace/<run>/images/*.png`, and frames extracted from `workspace/<run>/seg_00N.mp4`. Newest real
run is `c6be1954` (2026-07-12, SCP-049, 10 scenes / 155 shots, complete through video).

#### Case table (AC1)

| # | Run / shot | Narration sentence | `image_prompt` (head) | Emitted decision | Eligible approved asset | Final asset source | Expected decision | Observed frame | Root cause |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `c6be1954` s1/**S00113** | 그 가면은 피부에 융합되어 있습니다. | `extreme close-up of a ceramic surface texture, the glaze has fine cracks…` | `cast=[SCP-049]`, `location_key=None` | `SCP-049` card approved (`characters`, epoch_1, all angles) | STOCK card composited over generated bg | `cast=[]` | `seg_001.mp4` @42.6s — full-body SCP-049 standing beside a macro of an eye; scale nonsensical | **Selection failure** — STOCK reuse where free generation was correct |
| 2 | `c6be1954` s4/**S00406** | 손가락 끝이 피부에 닿는 순간… 디급 인원의 눈이 커졌습니다. | `extreme close-up of a wall-mounted cardiac monitor screen, a green waveform…` | `cast=[SCP-049, STOCK-d-class]` | both approved | STOCK cards composited | `cast=[]` | `seg_004.mp4` @25.0s — two full-body cards standing on a monitor-readout macro | **Selection failure** — same class |
| 3 | `c6be1954` s2/**S00202** | 사람들은 두려워했지만, 그 의사는 전혀 위협적이지 않았다고 합니다. | `medium shot of a village thoroughfare, left side a low stone wall…` | `cast=[SCP-049, STOCK-d-class]` | `STOCK-d-class` approved (epoch_2) | STOCK card composited | `cast=[SCP-049]` — no stock role fits a villager | `seg_002.mp4` @8.5s — orange prison jumpsuit with barcode labels standing in a period village | **Selection failure** — nearest stock role substituted for an out-of-vocabulary person |
| 4 | `c6be1954` s2/**S00204** | 지역 경찰이 신고를 받고 출동했지만, 그 의사는 저항하지 않았습니다. | `medium shot of a village crossroads, left foreground a pale blue police car…` | `cast=[STOCK-security, SCP-049]` | `STOCK-security` approved (epoch_2) | STOCK card composited | `cast=[SCP-049]` — "지역 경찰" is not site security | `seg_002.mp4` @18.0s — gas-masked tactical soldier where the narration says local police | **Selection failure** — same class |
| 5 | `c6be1954` s1/**S00115** | 그런데 이게 전부일까요? | `pull-out wide shot of the containment chamber, the entire room is visible…` | `location_key=observation-room` | **none** — 0 approved plates existed at run time | Generated (warn + fallback) | `containment-chamber` or `None` | No visible mismatch: the frame follows `image_prompt` | **Missing/unapproved asset** masking a latent selection inconsistency (location namespace) |

#### Why the location namespace is NOT SUPPORTED

1. All 42 location plates were created and approved **2026-08-02T07:04–09:02Z**; the newest run is
   **2026-07-12**. Zero plates existed when any recorded run executed.
2. `image.py:319-344` warns and falls back to generation when a key has no approved plates, so every
   shot in every run took the generation path.
3. Direct proof: of **1,843** `workspace/*/images/*.png` files, **0** are byte-identical to any of the
   42 approved plate files. STOCK location reuse has never once executed.
4. Selection quality on the only run with live keys (`c6be1954`, 132/155 shots keyed): 51 shots where
   both key and prompt name an environment **agree**; **1** genuine contradiction (S00115); 2 shots
   name an environment with `location_key=None`; 21 no-environment shots correctly `None`; all of
   scene 2 (medieval village, outside the 14-key vocabulary) correctly `None`. ~99% consistency —
   the opposite of a selection-failure signal.
5. Zero hallucinated or malformed keys in either namespace: every emitted `location_key` was in
   `LOCATION_KEYS` and every `card_key` was the run entity, a derived `SCP-049-2`, or one of the three
   `STOCK_CAST_KEYS`.

Point 5 is why **no text→key matcher was built**. AC5 is gated on "structured catalog selection alone
is insufficient"; the defect is not mis-keying, it is over-attachment. A `text + candidates -> key`
matcher can only *add* cast, so it would fix nothing here and could only introduce false STOCK
matches — precisely what AC6 forbids.

#### Root cause of the cast failures: ordering, not key choice

`cast_decision_step` (`scenario_chain.py:929`) is given the **narration only**;
`visual_breakdown_step` invents the shot's framing **afterwards** and receives the cast as input. So
`cast_decision.md`'s existing rule — "No one in frame (empty room, object close-up…) → `cast: []`" —
asks the LLM to predict a decision that does not yet exist. It cannot comply, and it did not: **27 of
121 cast-bearing shots (22%)** in `c6be1954` composited a card over an object macro or empty
environment (40/193 across all runs). `build_scenes` is the first point where the cast decision and
the `image_prompt` coexist, so that is where the reconciliation belongs.

#### Stage-1 replay (before → after)

| Run | Shots | Cast-bearing before | after | Corrected |
|---|---|---|---|---|
| `c6be1954` | 155 | 121 | 96 | **25** |
| `d55a265b` | 87 | 72 | 57 | **15** |
| `272b05a4` | 59 | 0 | 0 | 0 |

Cases 1 and 2 are corrected by the deterministic guard (S00106, S00109, S00113, S00114, S00301,
S00303, S00308, S00311, S00405, S00406, S00407, S00409, …). Cases 3 and 4 are addressed by the AC4
prompt catalog, not by code: "villager" and "local police" are not detectable from the framing, but
they are decidable once the LLM is told what each stock card actually wears. Verified on replay that
**every non-`cast` field of every shot stays byte-identical**.

**One cross-shot effect inside the `cast` field, surfaced in review.** "Non-`cast` fields unchanged" is
true but easy to over-read, so it is recorded explicitly: `position` lives *inside* `cast`, and
emptying one shot's cast opens a gap in `_enforce_cast_diversity`'s R2 consecutive-placement run
tracking (existing documented behaviour — `test_enforce_cast_diversity_absence_resets_run`). Measured
across the diagnosed runs, **5 surviving sibling shots** in `d55a265b` (S00206, S00207, S00209, S00405,
S00510) therefore keep their LLM-chosen slot where pre-8.19 code would have moved them off it. This is
the intended consequence of running the guard first — a shot with no card on screen genuinely breaks
the repetition R2 exists to break — and it is *less* rewriting of healthy siblings, not more, so it is
not the 8.18 displacement pattern. The order is now pinned by
`test_build_scenes_suppresses_cast_before_diversity_repair`, which fails if the two passes are swapped.

#### Finding recorded, deliberately NOT fixed here

Story 8.17 activated a behaviour no recorded run has ever exercised. Now that plates are approved,
`image.py:325-337` copies a plate and `continue`s — the shot's `image_prompt` is never rendered — and
`_plate_variant_index` picks the variant **per scene**, not per shot. Replaying `c6be1954` against the
now-populated table: 132/155 shots (85%) would take the plate path, e.g. scene 5's 21
`containment-chamber` shots collapsing to one identical image, discarding per-beat set dressing
("overturned metal stool with dented leg", "a single surgical glove").

**Corrected magnitude (review re-verification).** This section first recorded the collapse as
"132 → 34". That 34 is the count of distinct *(scene, `location_key`)* selection **events**, not
distinct images: different scenes sharing a key frequently draw the same variant. Recomputed by
calling the real `_plate_variant_index` against the 42 approved plate files on disk, the 132 keyed
shots resolve to **18** distinct plate images (whole run: 155 shots → **41** distinct backgrounds,
counting the 23 that still generate). The regression is therefore roughly **twice as severe as first
recorded** — scope the follow-up story off 132 → 18, not 132 → 34. Even a per-shot variant index
would cap at 27 (9 keys × 3 variants), so the fix has to address discarding `image_prompt`, not just
the variant granularity.

This is plate **substitution**, not selection, and AC8/AC13 forbid touching
`image.py` here. Recommended owning story: a new Epic 8 story on plate-vs-prompt reconciliation
(blend/condition the plate instead of replacing the prompt), with Story 13.1 owning the visible
run-level warning. **This should be resolved before the next full E2E run**, since it is a latent 85%
regression in background variety.

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created
- **Task 0 gate: SUPPORTED for `cast`, NOT SUPPORTED for `location`.** 5-case table above, all from
  real checkpoints plus frames extracted from rendered video. 4 of the 5 cases are observed cast
  mismatches; the 5th is a latent location inconsistency masked by a missing asset.
- **Stage 1 = two mechanisms, each matched to the failure it actually fixes.**
  (a) AC4 prompt catalog: `cast_decision.md` now receives controlled role descriptions instead of bare
  key names, plus an explicit "no card fits → `cast: []`, never substitute the nearest stock role"
  rule. Fixes cases 3–4 (villager → orange-jumpsuit D-class, 지역 경찰 → tactical site guard).
  (b) Deterministic guard `_suppress_cast_on_no_figure_framing` in `build_scenes`, 8.18's shape (pure,
  total, deterministic, idempotent, mark-targeted, INFO-logged, no LLM re-call). Fixes cases 1–2.
  It runs **before** `_enforce_cast_diversity` so placement repair only ever sees surviving cast.
- **Two Task-3 subtasks are intentionally left unchecked, not forgotten.** "alias/keyword logic before
  any `SequenceMatcher` tie aid" and "calibrate threshold and winner margin" describe AC5's
  `text + candidates -> key` matcher. Task 0 resolved that AC's gating condition to **false**: there
  were zero mis-keyed or hallucinated keys in any run, so there is no selection error for a matcher to
  correct, and a matcher can only add cast where the diagnosed defect is over-attachment. No
  `SequenceMatcher`, no threshold and no score therefore exist in this implementation. The helper that
  *was* built is deterministic marker-based suppression, so AC9's "score/threshold" fields have no
  counterpart; the log line carries namespace, decision, method and reason instead.
- **AC12/AC13 verified clean:** no `asset_retrieval_service.py`, no `pyproject.toml`, `config.py`,
  `image.py`, `location_service.py`, DB, API, frontend or video change. Diff is 3 source files + 1 test
  file. Graph topology untouched.
- **Marker set is precision-calibrated, not copied.** Measured across all runs: the six markers fire on
  40/193 cast-bearing shots and on **0** shots whose framing gives a full-body card anywhere to stand.
  Person-describing close-ups exist only in pre-8.10 runs (11/13 in `272b05a4`), from the
  character-prose-in-`image_prompt` bug that 8.10's call split already fixed; under the current
  background-only contract the latest run has 0 (3 apparent hits were regex artefacts — a clock's
  "second **hand**", a **hand**'s shadow).
  - *Claim narrowed in review.* This note first said "0 shots whose prompt describes a person", which
    is too strong: 4 of the 40 fires do mention a person **part** inside an object framing — `S00712`
    ("close-up of a computer monitor … one feed shows a cell with a figure's feet visible"), `S00713`
    and `S00715` (a certificate's "plague doctor's mask icon", a "doctor's bag"), and `d55a265b`
    `S00508` ("close-up of the concrete floor, a pair of bare feet still as stone"). In every one the
    person-part is drawn by the background prompt itself, so suppressing the composited card is still
    the correct call — the operational conclusion is unchanged, only the wording was overstated. Two
    of these are now regression cases in the marker parametrize list.
  - *Recall ceiling, named not fixed.* The root-cause section counts **27** defective shots in
    `c6be1954` while the replay table corrects **25** — the 2-shot gap is deliberate, not a
    discrepancy. `S00803` ("high-angle shot looking down at a conference table…") and `S00902`
    ("medium shot tight on a steel instrument tray…") are object framings with no marker vocabulary.
    Widening to `high-angle shot` / `tight on` would start catching legitimate figure framings, so
    precision wins and the gap stays until a diagnosed case justifies a sharper marker.
- **AC11:** `uv run python scripts/migrate_prompts.py --label production --source prompts` →
  `created: scenario/cast_decision`, all 15 other prompts `skipped` (no collateral promotion this
  time). Verified the live `production` prompt compiles with the new `stock_cast_catalog` variable.
- **Quality gates:** `tests/pipeline/nodes/test_scenario_chain.py` 293 passed; full suite
  1673 passed / 1 skipped; coverage **92.25%** (gate 80%); Ruff clean on all changed files.
- **One pre-existing test-infrastructure defect, verified not a regression.** Under `--cov` the full
  suite fails
  `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`.
  Not Story 8.19: the failure is entirely the file's own 10s drain timeout.
  - *Diagnosis corrected in review — the original note was wrong on all three counts.* It is **not**
    `assert 'failed' == 'awaiting_approval'`: the actual failure is `TimeoutError` raised from
    `asyncio.wait_for` inside `_drain_bg_tasks` (`test_e2e_stub_run.py:65`, `timeout: float = 10`). It
    does **not** "pass in isolation with and without coverage": in isolation it passes without `--cov`
    and **fails deterministically with** `--cov` (reproduced 2/2). And it is **not flaky or
    load-dependent** — coverage instrumentation simply slows one stub stage past 10s.
  - *Proof:* raising only that default to `timeout=120` makes all 3 tests in the file pass under
    `--cov` in 15s, with nothing else changed. That one-line default is the fix, and it belongs to the
    follow-up story — deliberately not applied here so this story's diff stays the 3 source files +
    1 test file that the AC12 verification rests on.
- **Correction for the record:** this story's Context section asserted the checkout had no run rows or
  artifacts and therefore could not complete Stage 0. It had 172 runs, 2,075 checkpoints and 260
  workspace directories. Stage 0 was fully executable.

### File List

- `src/yt_flow/domain/state.py` — added `STOCK_CAST_ROLES` controlled role catalog + coverage assert
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — added `_NO_FIGURE_FRAMINGS` +
  `_suppress_cast_on_no_figure_framing`, called from `build_scenes` before `_enforce_cast_diversity`;
  `cast_decision_step` now renders `stock_cast_catalog` instead of `stock_cast_keys`
- `prompts/scenario/cast_decision.md` — role catalog replaces the bare key list; explicit
  "no card fits → empty cast" rule
- `tests/pipeline/nodes/test_scenario_chain.py` — 30 new tests (framing markers, negatives,
  case-insensitivity, Korean input, totality, mark-targeting, namespace isolation, determinism,
  idempotence, log evidence, `build_scenes` integration, catalog coverage, prompt placeholders,
  catalog rendering); updated the cast-decision placeholder assertion
- *Review additions (2026-08-03):* `test_scenario_chain.py` +1 test
  (`test_build_scenes_suppresses_cast_before_diversity_repair`, pins the suppress → diversity order)
  and +2 marker parametrize cases (person-part inside an object framing); `scenario_chain.py` comment
  and docstring record the recall ceiling and the R2 run-gap interaction. 296 tests in the file.

## Senior Developer Review (AI)

**Reviewer:** Jay (AI adversarial review) · **Date:** 2026-08-03 · **Outcome:** Approve with fixes applied

Every claim below was re-derived from primary sources — the `checkpoints` table decoded with
`JsonPlusSerializer`, `location_plates` rows against the plate files on disk, the live Langfuse
`production` prompt, and `git diff` — never from task checkboxes or Completion Notes.

### Independently confirmed

| Claim | Verification |
|---|---|
| Stage 0 was executable | 172 `run` rows, 2,075 checkpoints, 260 `workspace/` dirs — story's Context premise was false, its Dev Agent Record correction is right |
| 40/193 marker fires; `c6be1954` 121 → 96, `d55a265b` 72 → 57, `272b05a4` 0 → 0 | Reproduced exactly by replaying `_NO_FIGURE_FRAMINGS` over all 134 scene-bearing checkpoints |
| AC5 gate genuinely false | **0** out-of-vocabulary `location_key` and **0** out-of-vocabulary `card_key` across *all* runs, not just the focus run. A `text -> key` matcher has no error to correct |
| Location namespace NOT SUPPORTED | 42 plates all approved 2026-08-02, newest run 2026-07-12; 1,843 `workspace/*/images/*.png` hashed against all 42 plate files → **0** byte-identical. STOCK location reuse has never executed |
| AC12/AC13 hard constraints honored | `git status` clean for `pyproject.toml`, `uv.lock`, `config.py`, `image.py`, `location_service.py`, all of `services/`, DB, API, frontend, video. No `asset_retrieval_service.py`. Diff is exactly 3 source files + 1 test file |
| AC11 prompt deployment | Langfuse `scenario/cast_decision` **v12**, labels `['production','latest']`, contains `{{stock_cast_catalog}}`, no `{{stock_cast_keys}}`, and normalized content is **identical** to the repo file. Repo remains source of truth |
| No 8.18-class displacement | No scene loses all its cast; no `card_key` loses all appearances (`SCP-049-2` 14 → 12 and 10 → 9, so derived-entity provisioning still fires); the function itself only touches violating shots |
| 8.17 plate regression is REAL | `image.py:325-337` copies a plate and `continue`s, so `image_prompt` is never rendered; `_plate_variant_index` keys on `(run, scene, location_key)`. 132/155 shots (85%) would take the plate path. **Not fixed here — AC8/AC13 forbid it.** Magnitude was mis-stated and is corrected in this file |

### Findings and fixes applied

| # | Sev | Finding | Fix |
|---|---|---|---|
| 1 | MED | The false Stage-0 premise still stood **uncorrected in place** in the Context section, 160 lines above its rebuttal | Corrected at source with the re-verified counts |
| 2 | MED | `build_scenes`'s suppress → diversity order is asserted load-bearing in both code and story, but **nothing pinned it**: swapping the two calls left all 293 tests green | Added `test_build_scenes_suppresses_cast_before_diversity_repair`; verified it is the *only* failure when the calls are swapped |
| 3 | MED | Real cross-shot effect went unrecorded: emptying a cast opens a gap in R2's run tracking, so 5 surviving siblings in `d55a265b` keep a slot pre-8.19 code would have moved. Hidden by the technically-true "non-`cast` fields byte-identical" (position lives *inside* `cast`) | Documented in the docstring and the replay section; confirmed it is *less* sibling rewriting, so not the 8.18 pattern |
| 4 | MED | The 8.17 hand-off number was wrong: "132 → 34" counts distinct *(scene, key)* selection events. Real collapse is 132 → **18** distinct images (155 → 41 run-wide) — ~2× worse, and the follow-up story would have been scoped off it | Recomputed with the real `_plate_variant_index` + on-disk plates and corrected, incl. the 27-image ceiling of a per-shot index |
| 5 | MED | Task 3 was `[x]` with its first subtask `[x]`, but Task 3's deliverable is AC5's matcher, deliberately **not** built. Honest substance, misleading checkboxes | Relabeled `[~] NOT APPLICABLE, gate resolved false` with the reason inline; subtask unchecked |
| 6 | LOW | Undocumented recall ceiling: 27 defective shots vs 25 corrected, never reconciled | Named the 2 misses (`S00803`, `S00902`) and why widening the markers is refused, in both code comment and story |
| 7 | LOW | "0 shots whose prompt describes a person" is overstated — 4 fires mention a person *part* inside an object framing | Narrowed to the accurate claim; 2 of them added as regression cases |
| 8 | MED | The `test_e2e_stub_run.py` failure was mis-diagnosed on symptom, trigger *and* nature: it is a `TimeoutError` from the file's 10s `_drain_bg_tasks`, it reproduces **deterministically** under `--cov` in isolation (not "passes in isolation"), and it is not flakiness. Would have sent the follow-up story chasing a phantom race | Re-diagnosed with proof (`timeout=120` → all 3 pass under `--cov` in 15s). Conclusion "not an 8.19 regression" survives; the one-line fix is handed off, not applied, to keep the diff clean for AC12 |

### Deliberately not fixed

- **8.17 plate substitution (132 → 18).** Out of scope by AC8/AC13. Confirmed real and confirmed
  worse than recorded. **Blocks the next full E2E run** — needs its own Epic 8 story on
  plate-vs-prompt reconciliation, with Story 13.1 owning the visible run-level warning.
- **`tests/api/test_e2e_stub_run.py` timeout.** Pre-existing and unrelated to this story, but *not*
  the flake it was recorded as — a deterministic `--cov` timeout. One-line fix identified and proven;
  left for its own story so this diff stays clean. See the corrected Completion Note.
- **Prompt-path cases 3–4** (villager → D-class, 지역 경찰 → security) can only be validated by a live
  run; DEV MODE forbids an A/B gate as completion evidence, so they rest on the seeded catalog.

## Change Log

- 2026-08-03: Story context created; status set to ready-for-dev. Scope fixed as diagnosis-first, stdlib/LLM Stage 1 only when supported, embeddings as a separately justified last resort.
- 2026-08-03: Task 0 diagnosis executed against real checkpoints and rendered frames — SUPPORTED for
  `cast`, NOT SUPPORTED for `location`. Root cause is decision ordering (cast decided before framing
  exists), not key retrieval.
- 2026-08-03: Stage 1 implemented for the `cast` namespace only — controlled role catalog in
  `cast_decision.md` (seeded to `production`) plus deterministic `_suppress_cast_on_no_figure_framing`
  in `build_scenes`. No matcher, no embeddings, no service, no dependency change. 40 shots corrected on
  replay of three real runs with all non-`cast` fields byte-identical. Status → review.
- 2026-08-03: Adversarial code review — every Task-0 figure independently re-derived from checkpoints,
  plate files, and the live Langfuse prompt; all AC12/AC13 hard constraints confirmed by diff. 7
  findings, all fixed: false Stage-0 premise corrected at source; suppress → diversity order now pinned
  by a test (it was unpinned — swapping the calls left all 293 tests green); R2 run-gap sibling effect
  documented; 8.17 hand-off figure corrected 132 → 34 to 132 → **18** (~2× worse); Task 3 relabeled
  N/A instead of `[x]`; marker recall ceiling and the "0 person prompts" overstatement corrected.
  1673 passed / 1 skipped before the review edits; after them 1675 passed / 1 skipped / 1 failed under
  `--cov` (coverage 92.27%, gate 80%), the one failure being the re-diagnosed pre-existing
  `test_e2e_stub_run.py` 10s-drain timeout. 296 tests in `test_scenario_chain.py`, Ruff clean.
  Status → done.
