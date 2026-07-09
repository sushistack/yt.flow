---
created: 2026-07-09
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

Status: ready-for-dev

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

- [ ] Task 1: Export production `scenario/writing` → `prompts/scenario/writing.md`; commit as-is; diff vs legacy template and record findings (AC:1)
- [ ] Task 2: Add ending-variety + register-guard rules (AC:2)
- [ ] Task 3: Add designation rules (AC:3)
- [ ] Task 4: Review-loop checklist line (AC:4)
- [ ] Task 5: Seed candidate + golden-set gate (AC:5)
- [ ] Task 6: Candidate run, style measurements, Dev Agent Record evidence (AC:6,7)
- [ ] Task 7: Hand promotion to Jay with evidence (label move is Jay's action per PROMPT_POLICY)

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

### Debug Log References

### Completion Notes List

### File List
