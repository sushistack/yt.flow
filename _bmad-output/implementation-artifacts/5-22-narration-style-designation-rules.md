---
created: 2026-07-09
baseline_commit: 92cdb8ff585b20488e2f980122a5bedceed43e07
story_key: 5-22-narration-style-designation-rules
story_id: "5.22"
epic: 5
previous_story: 5-21-tts-voice-clone-wiring
depends_on: []
related:
  - 5-18-subtitle-display-track            # display_narration vs narration split — rules apply to the writing stage, both tracks inherit
  - 5-4-tts-korean-normalization           # designation change removes awkward "디 구삼사일" TTS readings at the source
  - 8-12-cast-placement-scale-calibration  # same PROMPT_POLICY protocol, can share an A/B run
workflow_decision: "Prompt-only story plus one repo hygiene fix (writing.md missing from prompts/). No code changes."
evidence: "Iteration 1 run d55a265b, Jay viewing feedback #1/#7 (2026-07-09)."
---

# Story 5.22: Narration Style & Designation Rules (writing prompt)

Status: review

## Story

As Jay,
I want narration that varies its sentence endings and calls non-protagonist personnel by role instead of serial number,
so that the voiceover stops droning "~했습니다, ~했습니다, ~입니다" (feedback #7) and stops reading awkward designations like "디 구삼사일" for characters who don't matter as individuals (feedback #1).

## Context

Iteration 1 scene 1 (run `d55a265b`): 13 sentences, nearly all ending `-했습니다/-입니다`; the D-class subject is named "D-9341" throughout, which TTS renders as "디 구삼사일" — Jay: he's not a protagonist, "D계급 인원" suffices.

**Prompt-hygiene precondition discovered while scoping:** the runtime prompt `scenario/writing` has **no repo file** — `prompts/scenario/` holds only cast_decision/research/structure/tts_normalize/visual_breakdown. The writing prompt was seeded once from legacy `/mnt/work/projects/yt.pipe/templates/scenario/03_writing.md` (`scripts/migrate_prompts.py` mapping line 31) and has lived only in Langfuse since. That violates PROMPT_POLICY rule 1 ("Source of truth is the repo... `prompts/<stage>/<name>.md>`"). Same applies to `scenario/review`, `scenario/critic_agent`, `scenario/format_guide`, `scenario/structure`'s siblings — but this story repatriates **only `writing.md`** (the file it edits); flag the others in Dev Agent Record, don't fix them here (YAGNI).

**Diagnostic note for the implementer:** the legacy template already contains a rhythm rule ("문장 리듬 변화: 긴 묘사 문장과 짧은 임팩트 문장을 번갈아"). Iteration-1 output ignored it. So first EXPORT the actual production version from Langfuse and diff against legacy — the fix differs depending on whether the rule was dropped in a later version or is present-but-too-weak. Either way the new rules must be constraint-shaped (checkable), not vibe-shaped.

## Acceptance Criteria

1. **Repo file established:** `prompts/scenario/writing.md` created from the **current Langfuse `production` version** (not the legacy yt.pipe template — export it via the Langfuse client/UI so no live prompt drift is introduced by the repatriation itself). Committed before any content change, as its own commit, so the style diff is reviewable.
2. **Ending-variety rules added**, constraint-shaped:
   - No more than 2 consecutive sentences with the same final ending form (같은 종결어미 3연속 금지 — count `-했습니다`, `-입니다`, `-습니다` variants as distinct forms).
   - Mix at least: declarative, interrogative (극적 질문 — already a required technique, tie the two rules together), noun-ending/fragment for impact beats ("겨우 0.1초."), and inverted/trailing forms sparingly.
   - Climax beats prefer short fragments; aftermath beats may run longer sentences — rhythm rule restated as a checkable pattern, not prose advice.
   - **Register guard:** documentary 존댓말 base stays — no 반말, no full 구어체 drift (channel identity). Variety means rhythm, not register.
3. **Designation rules added:**
   - Non-protagonist humans are referred to by role: "D계급 인원", "연구원", "경비원", "요원" — never serial designations (D-9341, Dr. ███ 등).
   - Exception: a specific designation is allowed only when the individual's identity is itself the story beat (e.g., an SCP article where a named researcher's fate matters); default is role.
   - The SCP entity keeps its designation (that IS the subject).
4. **Review checklist hook:** `scenario/review` (or critic_agent — whichever the chain's retry loop actually consumes; verify in `scenario_stages`) gets ONE added checklist line covering ending-monotony + designation policy, so the existing bounded 1-retry loop enforces the new rules instead of hoping. If review prompt repatriation is required to edit it, flag and stop — do not repatriate a second prompt in this story without Jay's OK.
5. **Seeded as `candidate`**, golden-set gate passes (`eval_prompts.py --label candidate --baseline production` exits 0). Watch `narrative_coherence`/`article_fidelity` — style rules must not trade fidelity away (8.8's candidate died on exactly this axis).
6. **Style evidence:** from a candidate run's scenario artifact — max consecutive-same-ending run ≤ 2 across all scenes; zero serial designations for non-protagonists; register spot-check (no 반말). Counts recorded in Dev Agent Record.
7. **TTS side-effect check:** with designations gone, confirm no new tts_normalize regressions on a candidate run (the "디 구삼사일" awkwardness disappears at the source; nothing new appears).

## Tasks / Subtasks

- [x] Task 1: Export production `scenario/writing` → `prompts/scenario/writing.md`; commit as-is; diff vs legacy template and record findings (AC:1)
- [x] Task 2: Add ending-variety + register-guard rules (AC:2)
- [x] Task 3: Add designation rules (AC:3)
- [x] Task 4: Review-loop checklist line (AC:4)
- [x] Task 5: Seed candidate + golden-set gate (AC:5) — gate validation explicitly waived by Jay, see Debug Log
- [x] Task 6: Candidate run, style measurements, Dev Agent Record evidence (AC:6,7) — AC3/AC2-register PASS; AC2/AC6 ending-variety gap found and one fix attempted, result inconclusive on 1-sample evidence (see Debug Log); AC7 not run, deferred
- [x] Task 7: Hand promotion to Jay with evidence — this Dev Agent Record + File List is the handoff; label move to `production` remains Jay's action per PROMPT_POLICY, not done here

## Dev Notes

- Ending-form counting for AC:6 is a 10-line script: split sentences (`scenario_chain.split_sentences`), take the final ending token (regex on trailing `-(했|입|습)니다|까요\?|다\.` classes), compute max run length. Don't build an eval axis for it.
- 5-18 split: rules target the writing stage; `display_narration` (subtitles) and `narration` (TTS, post-normalize) both inherit — no per-track rules needed.
- deepseek-v4-flash ignores soft advice under long prompts (8.10 precedent). Prefer numbered hard constraints near the output-format section over adding prose to the philosophy sections.
- **ponytail:** one prompt repatriated, one prompt edited, one checklist line. The broader "repatriate all Langfuse-only prompts" cleanup is flagged, not done.

### References

- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — feedback #1/#7 evidence
- [Source: /mnt/work/projects/yt.pipe/templates/scenario/03_writing.md] — legacy seed source (diff baseline, NOT the repatriation source)
- [Source: scripts/migrate_prompts.py:31] — `scenario/03_writing.md → scenario/writing` mapping
- [Source: docs/PROMPT_POLICY.md] — rule 1 (repo source of truth) + change protocol
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:140] — `split_sentences` for measurements

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5

### Debug Log References

- Task 1 diff vs legacy (`/mnt/work/projects/yt.pipe/templates/scenario/03_writing.md`): content identical except single-`{var}` → `{{var}}` placeholder syntax. Confirms the diagnostic note in Context: the rhythm rule ("문장 리듬 변화: 긴 묘사 문장과 짧은 임팩트 문장을 번갈아") was **present-but-too-weak** in production, not dropped — it was prose advice with no checkable constraint, which is why iteration-1 ignored it.
- Task 4: both `scenario/review` (`overall_pass`) and `scenario/critic_agent` (`verdict`) gate the single retry (`scenario.py:179`, `if critic["verdict"]=="retry" or not review["overall_pass"]`). Asked Jay whether to repatriate a second prompt (`scenario/review.md`) since it had no repo file — approved. Added checklist item 8 to `scenario/review.md` (ending-monotony + designation-violation issue types, gating `overall_pass` like the other checklist items, not advisory like the storytelling sub-scores).
- Task 5 (golden-set gate) — **BLOCKED, not complete**: ran `scripts/eval_prompts.py --label candidate --baseline production` 3x, all three FAILed:
  - Run 1: candidate JSON parse errors on SCP-049 and SCP-173 (`Expecting ',' delimiter`); production also failed independently on SCP-173 (empty narration); SCP-096 regressed article_fidelity -0.67.
  - Run 2: production baseline failed independently (cast_decision 1:1 mapping mismatch, SCP-049); SCP-173 candidate regressed atmosphere -1.00; SCP-096 candidate improved all axes (+3.00 total).
  - Run 3: candidate JSON parse error again on SCP-173 (different offset); judge itself failed to parse its own response on SCP-049 (candidate) and SCP-173 (production); SCP-096 regressed hard this time (-2.67 total, opposite of run 2).
  - Isolated repro of SCP-173 candidate alone (outside the gate, via a monkeypatched `_call_deepseek` capturing every raw LLM response): 2 of 5 attempts hit the same JSON parse error, 3 succeeded cleanly producing correct output (e.g. "D계급 인원" instead of "D-9341" — designation rule works when it doesn't crash). The failing raw text itself was never captured because `eval_prompts.py`'s own artifact writer (`write_artifact`) only fires on the `--stage` isolation codepath, not the full `--baseline` comparison codepath used here — `candidate-SCP-173-full.json` artifacts all show `raw_output: null`.
  - Conclusion so far: axis-score variance is enormous run-to-run (SCP-096 total swung from +3.00 to -2.67 with no prompt change between runs) and production itself fails independently in every run for unrelated reasons — this points at pre-existing judge/pipeline instability, not a regression caused by this story's writing/review prompt edits. Not fully proven (raw text of the actual JSON break was never captured before Jay paused the investigation).
  - **Jay's direction (2026-07-10, mid-session):** stop chasing this under the JSON hypothesis — plans to change the scenario chain's LLM output format from JSON to YAML to reduce parse fragility. This is a pipeline code change, out of scope for this prompt-only story (workflow_decision: "no code changes"). Story is paused pending that change; resume Task 5 (re-seed candidate if prompt files changed further, rerun the gate) once the format change lands.
  - **2026-07-12 resume:** the JSON→YAML change landed (Story 6.4/6.9/6.10/6.11). However, by the time this resumed, Story 6.12 (`2ca29da`-adjacent work, uncommitted alongside this session) **froze the candidate-vs-production A/B gate** (`--baseline`/`--profile promotion`) behind `YTFLOW_ALLOW_AB_GATE=1`, and separately hard-blocks `--baseline` unconditionally whenever an AI coding session is detected (`CLAUDECODE`/`AI_AGENT` env) — `docs/PROMPT_POLICY.md` states this block applies "even under direct instruction mid-session" after a prior AI session set the override on request and had to be walked back. Jay instructed this session to unblock Task 5 and skip gate validation regardless. Per the hardened policy this session did **not** set `YTFLOW_ALLOW_AB_GATE` or attempt to work around the `CLAUDECODE` check — that guard is deliberately not mine to override even on explicit request. Instead, AC5's golden-set gate is treated as explicitly waived by Jay (same handling as Story 8.12's AC5), and this story proceeds via the diagnostic path that stays open under the freeze: single-label `--label candidate` runs (no `--baseline`) for Task 6's style measurements. Golden-set gate (`--baseline production`) remains un-run; production promotion is deferred to Jay per Story 6.12/PROMPT_POLICY, same as 8.12.

- Task 6 (2026-07-12): narration-only candidate generation (research→structure→writing, no cast_decision/visual_breakdown/review/critic/judge — those don't touch narration text) run for all 3 golden SCPs, `YTFLOW_DEEPSEEK_MAX_TOKENS=16000`. SCP-173/SCP-049 each hit a pre-existing, out-of-scope `research` stage YAML parse failure on `hooks` (a list-of-scalars field Story 6.11 explicitly declined to cover — see code comment at `scenario_chain.py` `FREETEXT_KEYS`); both succeeded on retry (non-deterministic LLM output). Style measurement script (`split_sentences` + trailing-ending-token regex, per Dev Notes):
  - **AC3 designation rule: PASS.** 0 D-class/serial designations found across all 3 items; only the SCP entity's own designation appears (SCP-049, SCP-096, SCP-173), which AC3 explicitly allows.
  - **AC2 register guard: PASS.** 0 real 반말 hits. Regex initially flagged 2 candidates (both inside "이야기합니다"/"...이지 않을..." — substring false positives from a naive banmal regex, not real informal register) — manually verified both are ordinary 존댓말 (formal register), no violation.
  - **AC2/AC6 ending-variety rule: gap found.** Max consecutive same-final-ending-form run: SCP-096=3, SCP-173=3, SCP-049=4 — all exceed the AC6 threshold (≤2). Longest runs are genuine repeats of the same grammatical ending (e.g. SCP-049: 4 consecutive `-ㅂ니다/-습니다` sentences — "...딱딱합니다. ...사라집니다. 쓰러집니다. 심장이 멈춥니다."). The new rule reduced monotony from iteration-1's near-total repetition, but does not fully hold the line at 3+.
  - Not yet run: AC7's TTS side-effect check (`tts_normalize_step`) — the narration-only script deliberately stopped before that stage to keep the call count minimal; needs one more small run if AC7 evidence is wanted now vs. deferred.
- Task 6 follow-up (2026-07-12): the AC6 gap (max-run 3-4 > threshold 2) traced to a real prompt gap — `writing.md`'s ending-variety rule (line ~53) lived only in the prose "philosophy" section, not in the `Pre-Output Self-Check` checklist right before the output block (where `characters_present`/`location`/etc. already live). Dev Notes flagged this exact model behavior (deepseek-v4-flash follows near-output checklists, not prose rules, per 8.10 precedent). Added one checklist line re-asserting the ≤2-same-ending-in-a-row rule; re-seeded to `candidate` via `migrate_prompts.py --source prompts --label candidate` (incidentally also re-seeded `scenario/cast_decision`/`scenario/visual_breakdown` since those had uncommitted local changes from a concurrent session at that moment — flagged to Jay live; low-risk since only the `candidate` label was touched and that session's own work landed in git separately).
  - **Side-effect of the re-seed**: `migrate_prompts.py` has no per-file filter (scans all of `--source` and skips unchanged content) — a known hazard in this repo when sessions run concurrently. No action needed here since the other session's changes were already committed elsewhere by the time this was noticed.
  - Re-ran the narration-only measurement (1 sample per SCP, post-fix): SCP-096 max-run=6, SCP-173 max-run=4, SCP-049 max-run=7 — **worse than the pre-fix sample** (3/3/4), not better. Verified by hand these are genuine repeats (e.g. SCP-049: 7 consecutive `-ㅂ니다` action-beat sentences), not a measurement artifact.
  - **Jay's call (2026-07-12):** 1-sample-vs-1-sample is not statistically meaningful given this project's well-documented run-to-run generation variance (6.9/6.10: SCP-096 swung +3.00→-2.67 with zero prompt change). Rather than spend more LLM calls chasing a median signal, stop here and record the AC6 result as **inconclusive-with-one-known-gap**: the designation (AC3) and register (AC2 register guard) rules hold cleanly across both samples; the ending-variety rule (AC2/AC6 numeric threshold) is not proven to hold at ≤2 in either sample, and the single prompt fix attempted (checklist line) did not demonstrably close the gap on this evidence. Left as an open item for Jay — either accept current wording as "improved but not proven ≤2" or iterate further with a proper multi-rep measurement.
  - AC7 (TTS side-effect check): not run — deferred, same as the original AC7 gap above.

### Completion Notes List

- Tasks 1–4 complete: `prompts/scenario/writing.md` and `prompts/scenario/review.md` repatriated (2 separate commits, second one Jay-approved), ending-variety/register-guard rules, designation rules, and review checklist item 8 all added. `candidate` label seeded for both (only these two prompts actually changed content — everything else in `prompts/` skipped, confirming `migrate_prompts.py --source prompts` parent-dir usage is correct/safe).
- Task 5 (golden-set gate) paused mid-investigation at Jay's explicit request — see Debug Log. Story left `in-progress`, not moved to `review`. Do not resume Task 5 until the JSON→YAML output-format change (Jay's, separate/future work) lands, then re-run `uv run python scripts/eval_prompts.py --label candidate --baseline production`.
- 2026-07-12 resume: JSON→YAML change had landed, but the golden-set gate (`--baseline`) is now frozen by Story 6.12 and unconditionally blocked for AI sessions (`docs/PROMPT_POLICY.md`). Per Jay's direction AC5's gate validation is explicitly waived (same as Story 8.12); this session did not set the freeze override or attempt to work around the AI-session block. Task 6 evidence gathered instead via the diagnostic-only `--label candidate` (no `--baseline`) path: designation (AC3) and register-guard (AC2) rules confirmed PASS across 3 golden SCPs; ending-variety (AC2/AC6, ≤2 threshold) found not met (max-run 3-4), one prompt fix attempted (Pre-Output Self-Check checklist line added to `writing.md`, re-seeded `candidate`), but a 1-sample re-measurement was inconclusive (worse numbers, likely generation noise per this project's documented run-to-run variance — not proven either way). AC7 (TTS side-effect) not run, deferred. Story moved to `review` with this open item flagged for Jay; production promotion remains Jay's action.

### File List

- `prompts/scenario/writing.md` (new; content edited twice this session — ending-variety/designation/register rules, then a Pre-Output Self-Check checklist line)
- `prompts/scenario/review.md` (new)

### Review Findings

- [ ] [Review][Decision] AC1's "own reviewable commit" requirement was not met — the actual style-rule content (AC2 ending-variety/register-guard, AC3 designation rules, AC4 review checklist item 8) never landed in a Story-5.22-scoped commit at all. It's commingled inside `342d6af "feat(scenario): add cached YAML stage retries"` (2026-07-11), a Story 6.x commit that also touches 7 other prompt files, `scenario.py`, `scenario_chain.py`, `eval_prompts.py`, and `pyproject.toml`, with no mention of Story 5.22 in the message. Retroactively splitting this via history rewrite would be a risky rebase across 80 commits already ahead of origin, touching another story's work — not attempted. Recommend accepting as a process gap (documented here) rather than rewriting history, unless Jay wants otherwise.
- [ ] [Review][Decision] AC4 (review-loop checklist hook) has never been exercised end-to-end — `review.md` item 8 exists in the prompt text, but no live run has confirmed the retry loop actually catches an ending-monotony/designation violation and triggers a repair. Verifying requires an LLM-calling pipeline run; deferred to Jay per the "ask before LLM calls" instruction for this review (see chat).
- [x] [Review][Patch] `characters_present` metadata rule required serial designations ("D-9341"), directly contradicting the new 인물 지칭 규칙 — fixed: now requires the same role-based reference as the narration, with an "A"/"B" suffix for disambiguating multiple same-role individuals in one scene. [prompts/scenario/writing.md:123]
- [x] [Review][Patch] Silent, undocumented example edit created a contradiction — the 2인칭 immersion ❌-example's subject was changed mid-session from "D-9341" to "D계급 인원" (the very string AC3 prescribes as correct), so the file flagged the correct designation as a bad example elsewhere. Fixed by using a neutral, designation-free subject. [prompts/scenario/writing.md:35]
- [x] [Review][Patch] New Register Guard used the same term ("구어체") that the pre-existing Tone & Voice section explicitly tells the writer to mix in, creating an apparent contradiction. Fixed by scoping the Register Guard to sentence-final endings only, distinct from encouraged word-choice/nuance. [prompts/scenario/writing.md:60]
- [x] [Review][Patch] The 4th "종결어미" category (도치·여운형) used an example that ends in the same grammatical form as the 평서형 category (both "-았습니다"), making it logically incoherent as a "distinct form" for the 3-in-a-row counting rule — plausibly contributing to the AC6 measurement gap (max-run 3-7 vs. required ≤2). Fixed by clarifying that inversion is a word-order technique layered on one of the 3 real ending forms, not a 4th countable bucket. [prompts/scenario/writing.md:58]
- [x] [Review][Patch] Uncommitted working-tree change (the Pre-Output Self-Check ending-variety line) — committed alongside the fixes above.
- [x] [Review][Defer] `review.md` items 1-7 and `writing.md`'s base sections contain multiple pre-existing prompt-quality issues (undefined `metadata` field, YAML example not matching the documented top-level schema, pipe-delimited enum values shown as literal example text, storytelling sub-scores computed but never captured in the output schema, fact-coverage list same issue, "approximately... 1:1" self-contradiction, undefined `image_prompts` term, immersion-device thresholds differing between writing.md and review.md, `entity_visible` forcing a visual render for merely-mentioned entities, no controlled `mood` vocabulary, unframed `{{parse_error}}`/`{{quality_feedback}}` placeholders) [prompts/scenario/review.md, prompts/scenario/writing.md] — deferred, pre-existing (part of the verbatim Langfuse `production` export, not introduced by this story; same YAGNI scoping this story already applied to the other un-repatriated prompts).

## Change Log

- 2026-07-12: Resumed after the 2026-07-10 pause. AC5's golden-set gate explicitly waived by Jay (frozen by Story 6.12, AI-session-blocked by design — not overridden). Gathered AC6/AC7 evidence via narration-only candidate runs (research→structure→writing only). Confirmed AC3/AC2-register pass; found AC2/AC6 ending-variety gap; added one checklist-based fix to `writing.md`; re-measurement inconclusive on 1-sample evidence. Story moved to `review`.
- 2026-07-12: Code review (bmad-code-review) — Blind Hunter + Edge Case Hunter + Acceptance Auditor run against the isolated story diff (`git diff 92cdb8f -- prompts/scenario/writing.md prompts/scenario/review.md`, excluding unrelated concurrent-session changes in the working tree). 5 patches applied directly (designation/metadata contradiction, silent example collision, register-guard ambiguity, incoherent 도치 category, uncommitted line committed). 2 items left as decisions for Jay (commit-history commingling, AC4 end-to-end verification). 1 batch of pre-existing prompt-quality issues deferred.
