---
title: 'Story 14.4: 무인 배경을 출하 기본값으로 — 가드 승격 + 결정↔출하 표류 리포트(13.6)'
type: 'feature'
created: '2026-08-22'
baseline_revision: '003045c'
status: 'in-review'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** Story 10.2 built a working background-person guard and shipped it behind
`background_person_guard_attempts = 0`, so for 15 days it never ran (`never screened` 43/43 in run
`4b35c0ed`). Turning it on rescued the run — but only through a `.env` pin, which is
`gotcha_a-decision-that-only-reaches-env-never-ships` verbatim: a fresh checkout or another box
silently reverts a judged decision. Two adjacent gaps ride along: a *single* undecidable verdict
produces **no warning at all** (the run had one, and it was invisible), and nobody has decided which
layer owns people *depicted* inside frames/monitors/posters — the guard deliberately answers `false`
for those, which is right for its purpose and wrong for Jay's ⑤.

**Approach:** Promote the decided value to the code default and remove every `.env`-side pin of it, so
the code is the single source. Then close the class, not just the instance (Story 13.6): declare
decision-bearing settings with their recorded verdict, and add a one-command drift report that names
where each effective value actually came from — including `.env.example`, which already carries two
latent reverts. Make the undecidable path visible per shot without spending a render, log the note the
detector already returns, and **record** the depicted-person ownership decision rather than extending
the guard.

## Boundaries & Constraints

**Always:**
- Every decision entry in the table must cite an **existing dated verdict** already in `config.py`.
  If a candidate field has no such comment, it does not get an entry — the prose is the source
  (13.6 Dev Notes: "Harvest those rather than re-deciding").
- The drift report is a **report, not a gate**: it always exits 0 on a successful read, whatever it
  finds. Only a usage/IO error may exit non-zero.
- `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS` stays `4` — `config.py:11-13` is a resume contract, it may
  only grow. The knob flip is `0 → 2`, well inside it.
- An undecidable verdict still **accepts** the frame and still consumes **no** rung. Only its
  visibility changes. Re-rendering on no information would spend ~17s to learn nothing.
- Keep the existing decision that a knob at its shipped value is not a degradation and is not warned
  (13.1 AC2, restated in `epic-14-context.md`). After the flip, a knob at `0` becomes a **deviation
  from a recorded decision** — visible in the drift report, which is the right layer.
- Every measurement lands with its sample band and a re-derivation script
  (`gotcha_a-measurement-without-its-sample-band`).
- `CHECK_PROMPT` keeps **one rule**. `tests/services/test_vision_check.py:127` and `:135` pin that;
  they are not to be relaxed.

**Block If:**
- The vision-latency measurement shows per-shot detector overhead **> 30 s** (i.e. the flip would add
  more than ~20 min to a 43-shot run). The decided value `2` is a cost/benefit claim; if the cost is
  an order out, do not flip the default unattended — HALT and report the number.
- The drift report surfaces a decision-bearing setting **other than** the guard whose effective value
  contradicts its recorded verdict. Report it, do not fix it (13.6 AC5) — and if closing it looks
  necessary to make this story's own claims true, HALT rather than flip someone else's flag.

**Never:**
- Do not extend the guard to fire on depicted people. It would break the duplicate-figure purpose the
  detector was narrowed for, re-open the exact distinction
  `gotcha_person-token-regex-is-unusable-on-image-prompt` warns against, and spend a render on a
  defect that is not a duplicate-figure defect. Research §2: "가드 확장은 마지막 선택지".
- No negative-prompt edits. `BG_NEGATIVE_SUFFIX` already contains person tokens and `S00201` was
  drawn anyway; the class has failed twice (`gotcha_negative-prompt-overstuffing`).
- No new `Settings` field for the report mechanism (13.6 AC6), no new dependency, no UI.
- No GPU. No new renders, no re-run of `4b35c0ed`. The only network calls allowed are the
  vision-latency probe (≤ 4 calls against PNGs already on disk).
- Do not implement 13.6 AC4 (decision provenance in the render sidecar) — it touches 13.3's AC8
  resume rule and is not what "결정↔출하 기본값 표류" needs. Defer it explicitly.
- Do not flip `camera_noise_enabled`, `qwen_tts_clone_enabled`, `shot_recompose_enabled`, or any
  other flag (13.6 AC5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Default ships the decision | `Settings(_env_file=None)`, no `YTFLOW_*` env | `background_person_guard_attempts == 2` | No error expected |
| Drift: decided ON, shipped OFF | table entry decided `2`, code default `0` | one DRIFT row: field, decided, effective, source | No error expected |
| Env-sourced but matching | `.env` assigns the decided value | row present, source = `.env`, marked matching-but-env-sourced (13.6 AC3) | No error expected |
| OS env beats `.env` | `YTFLOW_X` in `os.environ` and in `.env` | source = `os.environ` (the winning source, not both) | No error expected |
| Latent example drift | `.env.example` pins a value ≠ code default | reported as latent drift, separate from effective drift | No error expected |
| Unclassified field | field with no table entry | absent from the report, never crashes it (13.6 AC7) | No error expected |
| Healthy repo | no drift anywhere | empty result + explicit "no drift" line, exit 0 | No error expected |
| `.env` absent | file missing | report runs, source falls back to code default / `os.environ` | No crash, no non-zero exit |
| Single undecidable verdict | detector returns `None` once, below breaker | frame accepted, **no** rung consumed, one **per-shot** warning naming scene+shot | Detector raising is already coerced to `None` |
| Breaker trips | 3 consecutive / 6 total undecidables | unchanged: guard off for the run + one run-level warning | No error expected |
| Knob explicitly 0 | operator sets `YTFLOW_...=0` | guard off, detector never called, **no** warning; drift report shows the deviation | No error expected |

</intent-contract>

## Code Map

- `src/yt_flow/config.py:317` -- `background_person_guard_attempts = Field(0, …)`. The flip. Its
  comment block (`:310-317`) argues *for* the default `0` ("Off by default like every other new path
  in this epic") — that whole rationale inverts and must be rewritten, not appended to.
- `src/yt_flow/config.py:11-25` -- `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS = 4` (resume contract, do not
  touch), `_BREAKER_STREAK = 3`, `_BREAKER_TOTAL = 6`. The breaker is why an undecidable storm is
  bounded at 6, which is what bounds the new per-shot warning.
- `src/yt_flow/config.py:163, 167, 198, 242, 247, 259, 269, 300-308, 402` -- the existing dated
  verdicts. These are the **seed set** for the decision table; each is a citation, not a new decision.
- `src/yt_flow/pipeline/nodes/image.py:543-583` -- `_populated`. `verdict is None` currently only
  bumps `guard_counts["unavailable"]`; the breaker at `:567-568` is the *only* thing that warns. This
  is where the per-shot warning goes.
- `src/yt_flow/pipeline/nodes/image.py:526-542` -- `guard_off` computation and the
  `vision_api_key_missing` run warning. Read this before touching the no-warn-on-knob-0 policy.
- `src/yt_flow/pipeline/nodes/image.py:732-764` -- the ladder (`seeds[: attempts + 1]`) and the
  `ladder_exhausted` per-shot warning. The shape the new warning must match.
- `src/yt_flow/services/vision_check.py:50` -- `CHECK_PROMPT`, a repo literal (not Langfuse). Its
  FALSE-list (diagram/poster/statue/mannequin/skull/painting) **is** the depicted-person decision,
  already made in code. `:104-111` parses the reply and **discards `notes`** — one line fixes that.
- `src/yt_flow/domain/warnings.py:56` -- the `background_guard_unscreened` catalog entry (stage
  `image`, Korean copy). Reused as-is; only a new `reason` value is added. `:99` `MAX_SAMPLE_RECORDS
  = 12` bounds the new rows.
- `frontend/src/components/ArtifactPanel.tsx:189-207` -- `IDENTIFIER_LABELS` already renders
  `scene_num` / `shot_id` / `reason`, so the new warning needs **no** frontend change.
- `tests/test_config.py:243` -- `test_recompose_defaults`, the house pattern for pinning a decided
  default hermetically (`_base_env` + `delenv` + `Settings(_env_file=None)`).
- `tests/pipeline/nodes/test_image.py:37-49` -- `FakeSettings(guard_attempts=0, …)`; `:43-45`,
  `:1674-1678`, `:1696` are comments/docstrings that assert **in prose** that `0` is the shipped
  default. All three become false.
- `.env:78`, `.env.example:62-64` -- the pins to remove. `.env.example:34` (`clone_enabled=false`)
  and `:38` (`qwen_tts_speed=1.2`) are two **latent reverts** of already-decided values.
- `_bmad-output/implementation-artifacts/13-6-shipping-defaults-match-decisions.md` -- the ACs this
  story satisfies (1,2,3,5,7) and the one it defers (4).
- `_bmad-output/implementation-artifacts/10-2-live-validation/README.md` -- the guard's live evidence;
  its closing section says "The guard ships OFF" and must be amended, not deleted.
- `scripts/report_card_coverage.py` -- house pattern for a report script (docstring stating what it
  refuses to do, `sys.path.insert`, argparse from `__doc__`, `__main__` guard).
- `_bmad-output/planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md`
  §2 -- the open question this story answers ("그림 속 인물을 어느 층이 책임지나").

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/config.py` -- flip `background_person_guard_attempts` to `2` and **rewrite** its
  comment block: the live evidence (10-2 needed rung 2; run `4b35c0ed` hit 5/43 shots, all cleared on
  rung 1, 0 exhausted), the measured cost, and the fact that `2` is one spare rung above what this
  run needed rather than a round number. Add the decision table (module-level constant, e.g.
  `DECISIONS`, keyed by field name, carrying deciding story / date / decided value / a one-line
  citation of the existing comment). Seed it **only** from the dated verdicts listed in the Code Map.
  -- rationale: the flip is the story; the table is what stops the next one.
- [x] `.env` and `.env.example` -- delete the `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS` assignment
  from `.env`; in `.env.example` comment it out, keeping the prose and adding that the code default is
  now `2`. Fix the two latent reverts: `.env.example:34` `CLONE_ENABLED=false` and `:38` `SPEED=1.2`
  contradict decided values (`True`, `1.1`) -- comment both out the same way. -- rationale: a pin that
  agrees today is a stale pin tomorrow; a fresh checkout copying `.env.example` would revert two
  judged decisions on day one.
- [x] `scripts/report_decision_drift.py` -- new. For every field in `DECISIONS`: decided value, code
  default (`Settings.model_fields[name].default`), effective value, and the **winning source**
  (`os.environ` > `.env` > code default; resolve `.env` with the already-installed
  `dotenv.dotenv_values`, path from `Settings.model_config["env_file"]`). Report three buckets:
  effective-vs-decided drift, env-sourced (even when matching), and latent `.env.example` pins that
  differ from the code default. Empty is healthy and says so. Always exit 0 on a successful read.
  -- rationale: 13.6 AC2/AC3; `Settings()` cannot tell you where a value came from.
- [x] `src/yt_flow/pipeline/nodes/image.py` -- in `_populated`, on `verdict is None` append a
  **per-shot** `background_guard_unscreened` warning with `scene_num` / `shot_id` and a new `reason`
  (e.g. `detector_undecidable_shot`), keeping accept-and-do-not-consume-a-rung. The breaker warning
  and every counter stay as they are. `_populated` needs the current shot's identity in scope --
  thread it in the least invasive way the surrounding loop allows. -- rationale: run `4b35c0ed` had
  one undecidable and it produced zero warnings; an unscreened frame is indistinguishable in the UI
  from a verified-clean one, which is the exact defect 13.1 exists to remove.
- [x] `src/yt_flow/services/vision_check.py` -- log the `notes` string the detector already returns
  alongside the verdict (one line, at the point the JSON is parsed). Do **not** change
  `CHECK_PROMPT`, the return type, or the signature. -- rationale: `S00201`'s framed anime portrait
  was in the detector's own note on the first run and we threw it away; this gives 14.1 a corpus
  instead of n=1, at zero cost.
- [x] `tests/test_config.py` -- add a hermetic default test for the guard following
  `test_recompose_defaults`: `delenv` the key, `Settings(_env_file=None)`, assert `== 2`, and assert
  `BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS == 4` with the resume-contract reason in the docstring. Add a
  test that every `DECISIONS` key is a real `Settings` field. -- rationale: there is currently **no**
  test pinning this default at all, and `FakeSettings` carries its own literal `0`, so nothing in the
  suite would notice the flip in either direction.
- [x] `tests/pipeline/nodes/test_image.py` -- add the single-undecidable warning test (exactly one
  row, correct `scene_num`/`shot_id`/`reason`) and a test that the breaker case still emits exactly
  one run-level row. Correct the three prose claims that `0` is the shipped default (`:43-45`,
  `:1674-1678`, `:1696`) and rename/re-document
  `test_guard_disabled_by_config_is_warning_free` so it reads as *an operator override is still not
  warned* rather than *the default is off*. -- rationale: those comments are the policy record; left
  as-is they contradict the shipped code.
- [x] `tests/test_report_decision_drift.py` -- cover the I/O matrix rows for the report: decided-but-
  drifted, env-sourced-and-matching, `os.environ` beating `.env`, latent `.env.example` pin, a field
  with no decision entry, the all-clean case, and a missing `.env`. Load the script by path like
  `tests/test_measure_script.py:19-25`, fully offline. -- rationale: this report's only job is being
  believed; AC7 of 13.6 names these cases.
- [x] `_bmad-output/implementation-artifacts/14-4-live-validation/` -- new. (i) a script that
  re-derives the guard's real behaviour in run `4b35c0ed` from the on-disk sidecars by matching each
  accepted `seed` against `_seed_ladder` (expected: 43 shots, 38 on rung 0, 5 on rung 1 —
  `S00103`/`S00202`/`S00203`/`S00301`/`S00400` — 0 exhausted), printing thread id and the sidecar
  directory as its sample band and refusing to report if the workspace is absent; (ii) a small probe
  that times `background_has_person` against 2-4 PNGs already in that workspace and reports per-call
  seconds; (iii) `README.md` tying both to the flip's cost/benefit claim and stating what the sample
  does **not** say (one run, one checkpoint, one SCP; the 5 hits all cleared on rung 1 so rung 2 is
  still only justified by 10.2's single hit). -- rationale: the flip's whole justification is a
  measured cost/benefit, and `gotcha_a-measurement-without-its-sample-band` forbids the number
  without the script.
- [x] `_bmad-output/implementation-artifacts/10-2-live-validation/README.md` -- amend the "What this
  sample does NOT say" bullet that reads "**The guard ships OFF**" and the earlier "it is **not** the
  shipped default, which is 0" -- mark them superseded by this story with the date, do not delete the
  original text. -- rationale: `gotcha_recorded-root-cause-can-be-inverted`; a stale "ships OFF"
  sentence in the guard's own evidence directory is the sentence the next reader will quote.
- [x] `_bmad-output/planning-artifacts/epics.md` and
  `.../research/technical-perspective-population-narration-match-2026-08-17.md` §2 -- record the
  depicted-person decision in Story 14.4, 14.1 and research §2: **owner is 14.1's approval gate**
  (a framed portrait is a plate-level property, judged once by a human at approval, and the approval
  gate is already the single enforcement point for ③⑤⑦); guard extension is **rejected** with the
  three reasons from Boundaries; and the residual gap is named — free-generated shots (12/43 in this
  run) never reach an approval gate, so until 14.1's set covers them this defect class is accepted
  risk, not covered. Also record the undecidable policy. -- rationale: the story's (b) deliverable is
  a decision, and a decision that only lives in a spec file is the same anti-pattern one level up.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- two entries: 13.6 AC4 (decision
  provenance in the render sidecar, with the 13.3 AC8 constraint) and the free-generation
  depicted-person gap routed to 14.1/14.3. -- rationale: deferral is only honest if it is tracked.
- [x] `CLAUDE.md` and `_bmad-output/implementation-artifacts/sprint-status.yaml` -- a short CLAUDE.md
  subsection: how to run the drift report, that a non-empty result is a finding for the owning
  feature story and never a build failure, and the rule that a decision-bearing value belongs in the
  code default with `.env`/`.env.example` left unpinned. Sync sprint status for `14-4` and mark `13-6`
  partially satisfied (which ACs, which deferred). -- rationale: 13.6 Task 5; and a report nobody
  knows to run is not a mechanism.

**Acceptance Criteria:**
- Given a checkout with no `.env` and no `YTFLOW_*` environment, when the image stage runs against a
  generated background, then the guard is active with a 2-rung budget — i.e. the decision reaches
  pixels without anything in `.env`.
- Given the repository as shipped by this story, when `report_decision_drift.py` runs on a box with no
  `YTFLOW_*` overrides, then it reports **no** effective drift for
  `background_person_guard_attempts`, names the code default as its source, and exits 0.
- Given a decision-bearing setting whose recorded verdict differs from the code default, when the
  report runs, then that setting appears with both values, its deciding story and date, and the report
  still exits 0 — it never fails a run (13.6 AC2).
- Given `4b35c0ed`'s workspace, when the re-derivation script runs, then it prints 43 shots / 38 rung-0
  / 5 rung-1 / 0 exhausted with its sample band, and refuses to print numbers when the workspace is
  absent.
- Given the whole test suite, when it runs, then no test or comment asserts that `0` is the shipped
  default, and `tests/test_config.py` fails if the default is changed in either direction.
- Given `epics.md`, research §2 and `10-2-live-validation/README.md` after this story, when a reader
  looks for who owns people depicted inside frames, then they find 14.1's approval gate named, guard
  extension recorded as rejected with reasons, the free-generation gap named as accepted risk, and no
  surviving unmarked sentence claiming the guard ships off.

## Spec Change Log

**2026-08-22 — implementation notes where the spec was under-specified or wrong.**

1. **`stock_plate_substitution_enabled` gets no `DECISIONS` row.** The Code Map lists
   `config.py:300-308` in "the existing dated verdicts", but that comment carries a story
   (8.17) and a measurement and **no date**. Boundaries → Always says an entry must cite an
   *existing dated verdict*, so the Boundary won over the Code Map and the field is
   excluded, with the exclusion (and three other undated candidates) written into the
   `DECISIONS` header comment so it reads as a decision rather than an oversight. Result:
   **9 rows** — the 8 dated verdicts in the Code Map plus this story's own flip. Two
   further fields (`depth_placement_enabled`, `composite_harmonization_tier`) *are* dated
   and *are* eligible but sit outside the seed set the Code Map fixed; that is recorded in
   the same comment rather than acted on.
2. **"free-generated shots (12/43 in this run)" needed a correction to be true.**
   `stock_plate_substitution_enabled` is False, so **43/43** of run `4b35c0ed`'s
   backgrounds were free-generated (verified: `provenance.stock_plate` null on all 43
   sidecars). The 12/43 figure is the count of shots with **no `location_key`**
   (`14-0-angle-conflict/report.md`: 31/43 have one). Both numbers are stated separately
   in `deferred-work.md` so the residual-gap claim is not resting on a conflation: 14.1's
   set can at best shrink the uncovered set to 12, and today it is 43.
3. **No `Block If` fired.** The vision-latency probe measured **1.46–2.58 s** per call
   (mean 2.00, 4/4 decided) against the 30 s line, and the drift report surfaced exactly
   one non-guard row — `qwen_tts_speed` env-sourced from `.env` and **matching** its
   recorded verdict — so nothing contradicts a decision and no flag of another story's was
   touched.
4. **One test in the repo was already red at the baseline** and stays red:
   `tests/test_render_pose_guides.py::…[humanoid_lying_supine]` (a PIL render sha pin).
   Reproduced byte-identically in a clean `HEAD` (003045c) worktree, so it is not a
   regression from this story and was deliberately not "fixed" here.
5. **A stale "ships OFF" sentence lived in a fourth place** the Code Map did not list:
   `10-2-live-validation/run_probe.py:191`'s argparse help string. Corrected the same way
   as the README's three.

**2026-08-22 — review pass, root cause of the two high-severity findings (recorded, not looped back).**

6. **The spec ENUMERATED where it should have instructed a SWEEP.** The Code Map named
   ``.env.example:34`` and ``:38`` as "the two latent reverts" and the task said "fix the
   two latent reverts", so the implementation stopped at two. Review found a third
   (``DEEPSEEK_MAX_TOKENS=16384``, a *measured* failure value against a code default of
   32768) and a fourth-class instance (``CHARACTER_VISION_API_KEY=<YOUR_VISION_API_KEY>``,
   a **truthy placeholder** that defeats the flip on the very fresh checkout this story is
   about). Both were missed for the same reason: the audit ran over ``DECISIONS`` members,
   i.e. it was blind exactly where it had not already looked. This was triaged as **patch,
   not bad_spec** — the corrective edits are two commented lines, one table row and one
   report predicate, and re-deriving 15 files would not have produced structurally
   different code — but the lesson is spec-level and belongs here: **a story that closes a
   class must instruct a sweep of the population, never a list of known instances.** The
   sweep is now a test (``test_the_repo_pins_no_decision_bearing_value_in_the_example_file``)
   rather than a manual ``grep`` of one key.

   **KEEP if this is ever re-derived:** the `DECISIONS` "index into the prose, comment
   wins" contract; the refusal to assert `decided == default` in tests (that would make
   the report a gate by proxy and break 13.6 AC5); the two-live-samples argument for `2`;
   the per-shot-not-per-run scoping of the undecidable flag; and every "what this sample
   does not say" bullet — those are the parts review confirmed rather than corrected.

## Review Triage Log

### 2026-08-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 2, medium 12, low 5)
- defer: 2: (high 0, medium 1, low 1)
- reject: 6: (high 0, medium 2, low 4)
- addressed_findings:
  - `[high]` `[patch]` A **fourth** latent `.env.example` revert was still live and worse than the three fixed: `DEEPSEEK_MAX_TOKENS=16384` against a code default of 32768, where 16384 is the *measured* value that truncated `scenario/structure` 4/4 on 2026-08-05. Commented out, given a `DECISIONS` row (9 -> 10), and the three shipped claims that said "three of them" corrected in `CLAUDE.md`, `epics.md` and `sprint-status.yaml`. Root cause — enumeration instead of a sweep — recorded in the Spec Change Log.
  - `[high]` `[patch]` The flip did not reach pixels on the checkout it was written for: `.env.example` shipped `YTFLOW_CHARACTER_VISION_API_KEY=<YOUR_VISION_API_KEY>`, and a **placeholder is truthy**, so a fresh checkout fired real DashScope calls with a bogus key, tripped the breaker after 3 shots, and never saw `vision_api_key_missing` (the key was non-empty). Commented out, with the reasoning in the file.
  - `[medium]` `[patch]` The new per-shot undecidable rows shared a code with `ladder_exhausted` and `cap_samples` capped per CODE first-seen, so the cheap numerous reason evicted the severest one (`gotcha_summary-from-a-capped-list-drops-the-severest-item`). `cap_samples` now caps per `(code, reason)` and the aggregate row names the reason it counted; test added that reproduces the displacement shape (5 undecidable + 15 exhausted -> 5 + 12 named, not 5 + 7).
  - `[medium]` `[patch]` The new visibility was not durable, unlike the `guard_exhausted` sibling it was modelled on: `run_warnings` ride the LangGraph checkpoint and `full_restart_run` deletes the checkpoint while leaving the images, so a restarted pass skipped every shot and the never-screened frame came back looking verified-clean. `guard_undecidable` now goes into the sidecar (additive, outside the three compared keys, 13.3 AC8 respected) and re-fires as `detector_undecidable_earlier_run` on resume; `_sidecar_guard_exhausted` generalised to `_sidecar_guard_flag`.
  - `[medium]` `[patch]` The latent bucket compared the example pin against `field.default`, which was wrong in both directions — a pin carrying a STALE default was silent (the case 13.6 exists for) and a pin carrying the DECIDED value was reported as a problem. Now keys on PRESENCE, with `agrees` ranking the row, matching the rule this story shipped in `CLAUDE.md`. Two tests replace the obsolete one.
  - `[medium]` `[patch]` The report printed a clean bill of health from the wrong directory: `--env-file` defaulted cwd-relative, so run from `/tmp` it said "no drift, every value code default" about files it never opened. Default now resolves from `__file__`, and an ABSENT/UNREADABLE file prints `NOT CHECKED` instead of "none".
  - `[medium]` `[patch]` Nothing pinned the repository's own `.env.example` — re-adding the guard pin left every test green. The real-table test now asserts `latent == [] and drift == [] and stale == []` over the whole declared set, which is the check that would have caught the deepseek revert.
  - `[medium]` `[patch]` The diff added a rule and simultaneously told the reader to break it: `config.py`'s `qwen_tts_speed` comment said "the .env pin must move with this or it wins" while the new `CLAUDE.md` section said such values must be left unpinned, and `.env` still pinned it. Both matching `.env` pins (`qwen_tts_speed`, `deepseek_max_tokens`) removed — effective values unchanged, so this is not a flag flip — and the comment rewritten to point at the rule.
  - `[medium]` `[patch]` An unreadable or non-UTF-8 `.env` raised straight out of a tool whose contract is "only argparse exits non-zero". `_read_env` catches `OSError`/`UnicodeDecodeError` and reports the state.
  - `[medium]` `[patch]` "5 hits" was presented as 5 contaminations. `14-0-angle-conflict/report.md` §8-5, same run same day, records **no person visible in either render** of `S00103`, so at least one is probably a false positive that cost a real ~17s render, and `S00202` was never eyeballed. The caveat is now in the `config.py` comment, the artifact README, `epics.md` and `sprint-status.yaml` as "3 confirmed + 2 unadjudicated".
  - `[medium]` `[patch]` The first latency figure was a sparse-sample claim. Re-probing produced **10.11 s** on the same frame that took 1.46 s, so the honest band is 1.46–10.11 s over 7 timed calls (mean 3.17), not "~2 s constant" — inside the 30 s Block-If line by 3x rather than by an order (`gotcha_measure-densely-before-declaring-a-fix`). Corrected everywhere the number appears; the probe now projects on the run's own shot count instead of a hardcoded 43.
  - `[medium]` `[patch]` `derive_guard_rungs.py` would overstate the guard the moment 14.1/8.17 turns stock plates on: a copied plate is written with rung 0's seed and never put to the detector, so it would tally as "cleared first try". Plates are now excluded and reported (0 today, verified `provenance.stock_plate` null on 43/43).
  - `[medium]` `[patch]` Four unguarded paths in `derive_guard_rungs.py`: a truncated sidecar tracebacked out with an exit code colliding with the off-ladder signal; a pre-11.1 seedless sidecar was misreported as off-ladder (i.e. as falsifying the derivation); zero *matching* sidecars printed "a budget of 0 would have covered every hit" and exited 0; and the budget sentence claimed coverage even with exhausted shots present. All four now separate "missing data" from "bad rung", and exit 3 covers the vacuous case.
  - `[medium]` `[patch]` `probe_vision_latency.py`: `Settings()` tracebacked on a fresh checkout (the required Langfuse keys) instead of reporting DID NOT RUN; `--limit 0` printed the false claim "no PNGs under <dir>"; `--limit 10` silently did 4. Argparse now refuses 1..4 and the config load is caught.
  - `[low]` `[patch]` A `DECISIONS` row naming a required field would have printed `PydanticUndefined` as both effective and default forever. `field.is_required()` routes it to the stale bucket with a reason.
  - `[low]` `[patch]` `DECISIONS` citations were unverifiable free text although the contract is "the comment wins": a test now asserts each quoted fragment is still present in `config.py`.
  - `[low/medium]` `[patch]` 13.6 AC1 was reported as satisfied while two of its own named categories had no rows — the non-boolean `qwen_tts_voice` that Dev Notes trap 4 calls out by name, and `composite_harmonization_tier`. Downgraded to "부분 충족" with the reason and the remaining work.
  - `[low]` `[patch]` `partially-satisfied` is not in the sprint-status vocabulary (`backlog → ready-for-dev → in-progress → review → done`), so a tool filtering on it would have lost 13-6 from both the "next" and the "done" sets and with it the deferred AC4. Back to `backlog`, with the partiality in the comment where all the other nuance lives.
  - `[low]` `[patch]` Two unmarked stale sentences survived AC6's "no surviving unmarked sentence claiming the guard ships off": the research doc's §0 summary table ("지금도 `.env` 핀 상태") and its §5 closing line, plus `epics.md`'s original 14.4 paragraph. Struck and annotated the way `10-2-live-validation/README.md` was.
  - `[low]` `[patch]` The `.env.example` clone-voice line now says what a fresh checkout will hit (a loud `tts_node` failure naming `scripts/seed_voice_clone.py`) and why that is the intended outcome rather than a regression.
  - `[medium]` `[patch]` The flip's worst-case aggregate cost was measured and forgotten. `config.py` now states it: 2 extra renders per shot, i.e. at most 3x the image stage's render time, bounded by construction rather than by a threshold — and names the deferral for the missing aggregate warning.

## Design Notes

**Why `2` and not `1`.** The two live samples disagree in a way worth writing down. Story 10.2's one
hit needed rung **2** (rung 1 was still populated), so a budget of 1 would have shipped a populated
frame. Run `4b35c0ed`'s five hits all cleared on rung **1**. So the *observed* modal need is 1 and the
*observed* worst case is 2; `2` is the worst case seen, not a margin someone liked. `MAX_ATTEMPTS` is
4 and stays 4 — raising the shipped budget further has no evidence behind it and each rung is a full
render.

**Why the flip costs nothing on resume.** `_seed_ladder` is deliberately fixed-length
(`MAX_ATTEMPTS + 1`) and `_existing_complete_shot` compares the accepted seed against the **whole**
ladder, so raising or lowering the knob can never invalidate a cached shot. Rung 0 hashes the pre-10.2
string byte-identically. The flip therefore changes only newly-generated shots — there is no
re-render of existing workspaces to budget for.

**Why the depicted-person case is not a guard problem.** The detector's FALSE-list is not an oversight;
it is the answer to a different question. The guard exists so a composited card does not become the
*second* body in frame, and a poster is not a second body. Jay's ⑤ for `S00201` is really two defects
wearing one costume — a person-shaped thing on the wall (population) *and* an anime-styled portrait in
a painterly room (⑦, style). Both are properties of the plate, decidable once by a human looking at
it, which is exactly what 14.1's approval gate is. Extending the runtime guard would pay a render per
hit, forever, to re-answer a question a human answers once per plate.

**Where the report gets "source" from.** `Settings()` resolves env over default silently and keeps no
provenance, so the report reconstructs it from the only two external sources this app configures:
`os.environ` and `model_config["env_file"]`. That ordering is the report's whole claim to honesty —
if a future `Settings` grows a third source (init kwargs, `secrets_dir`), the report must grow with it
or start lying.

## Verification

**Commands:**
- `uv run pytest tests/test_config.py tests/pipeline/nodes/test_image.py tests/services/test_vision_check.py -q` -- expected: all pass, new tests included
- `uv run pytest tests/test_report_decision_drift.py -q` -- expected: all matrix rows pass, offline
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0; no effective drift for the guard; any remaining rows are reported not fixed
- `uv run python _bmad-output/implementation-artifacts/14-4-live-validation/derive_guard_rungs.py` -- expected: 43 shots / rung-0 38 / rung-1 5 / exhausted 0, with thread id and sidecar dir printed
- `uv run pytest tests/ -q` -- expected: no regressions
- `uv run ruff check src tests scripts` -- expected: clean

**Manual checks (if no CLI):**
- `grep -rn "BACKGROUND_PERSON_GUARD_ATTEMPTS" .env .env.example` -- expected: no active assignment in either file
- `git diff prompts/` -- expected: empty. This story changes no runtime prompt, so `docs/PROMPT_POLICY.md` and the Langfuse seeding path are not involved.

## Auto Run Result

Status: done — the guard ships, and the class it belonged to now has a reporter.

### 구현한 변경

**(a) 가드 승격.** `background_person_guard_attempts` 코드 기본값 `0 → 2`. `.env` 핀 삭제.
`.env.example`의 잠재 되돌림 **4건**과 truthy 플레이스홀더 **1건** 주석 처리. 근거는 두 쪽 모두
재산출 스크립트와 함께 `14-4-live-validation/`에 있다 — 편익은 run `4b35c0ed` 43샷의 rung 분포
(38/5/0, 소진 0)를 사이드카 `seed` × `_seed_ladder` 인덱스로 되짚은 것이고, 비용은 실제
`background_has_person` 호출 7회의 초 단위 실측이다(GPU 0, 렌더 0).

**(b) "그림 속 인물" 결정.** 소관은 **14.1의 승인 게이트**. 런타임 가드 확장은 이유 셋으로
기각하고, 자유생성 샷이 승인 게이트에 도달하지 않는다는 잔여 갭을 **명시적 감수 리스크**로
등재했다. 코드 쪽 동반 변경은 한 줄뿐 — 탐지기가 이미 반환하던 `notes`를 로그로 남긴다. 라이브
확인됨: `notes='The frame depicts an empty industrial environment with no human presence.'`

**(c) undecidable 정책.** 수용·단 미소비 유지, 가시성만 추가. 단발 판정불가도 샷 단위 경고를
남기고, 리뷰에서 그 경고를 사이드카(`guard_undecidable`)로 내구화했다 — 경고만으로는
`full_restart_run` 이후 미검사 프레임이 "검증된 클린"으로 돌아왔다.

**(d) 13.6 부분 충족.** `config.DECISIONS`(10필드, 전부 기존 날짜 있는 판정 인용) +
`scripts/report_decision_drift.py`(승자 소스 `os.environ > .env > 코드 기본값`, 네 버킷, 항상
exit 0). AC1은 **부분** — 13.6이 이름으로 지목한 `qwen_tts_voice`가 날짜 없는 판정이라 행이 없다.
AC4(사이드카 결정 프로비넌스)는 명시적 보류.

### 변경 파일

- [src/yt_flow/config.py](../../src/yt_flow/config.py) — 기본값 플립 + 주석 전면 재작성(둘로 갈린
  라이브 표본, 실측 비용과 그 상한, 오탐 주의) + `Decision`/`DECISIONS` 테이블
- [src/yt_flow/pipeline/nodes/image.py](../../src/yt_flow/pipeline/nodes/image.py) — 샷 단위 판정불가
  경고, `guard_undecidable` 사이드카 키, `_sidecar_guard_exhausted` → `_sidecar_guard_flag`
- [src/yt_flow/domain/warnings.py](../../src/yt_flow/domain/warnings.py) — `cap_samples`를
  (code, reason) 단위로. 집계 행이 센 reason을 이름으로 밝힌다
- [src/yt_flow/services/vision_check.py](../../src/yt_flow/services/vision_check.py) — `notes` 로깅 1줄
- [scripts/report_decision_drift.py](../../scripts/report_decision_drift.py) — 신규 표류 리포트
- `.env` / `.env.example` — 결정 담지 핀 제거(둘 다), 잠재 되돌림 4건 + 플레이스홀더 주석 처리
- [tests/test_config.py](../../tests/test_config.py),
  [tests/test_report_decision_drift.py](../../tests/test_report_decision_drift.py),
  [tests/pipeline/nodes/test_image.py](../../tests/pipeline/nodes/test_image.py),
  [tests/services/test_vision_check.py](../../tests/services/test_vision_check.py) — 기본값 고정,
  리포트 17건, 판정불가 가시성·내구성·캡 밀림, `notes` 채널
- [14-4-live-validation/](14-4-live-validation/) — `derive_guard_rungs.py`,
  `probe_vision_latency.py`, `README.md`(스크립트·README만, PNG 미복사)
- [10-2-live-validation/README.md](10-2-live-validation/README.md) + `run_probe.py` — "ships OFF"
  4곳 원문 보존 + 승계 표시
- [epics.md](../planning-artifacts/epics.md), [research §2](../planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md),
  [epic-14-context.md](epic-14-context.md), [deferred-work.md](deferred-work.md),
  [CLAUDE.md](../../CLAUDE.md), [sprint-status.yaml](sprint-status.yaml)

### 리뷰 결과

intent_gap 0 · bad_spec 0 · **patch 19**(high 2, medium 12, low 5) · defer 2 · reject 6.
상세는 위 Review Triage Log. high 2건은 둘 다 **이 스토리의 주장 자체를 반증**하는 종류였다 —
(i) 잠재 되돌림이 3건이 아니라 4건이었고 넷째(`DEEPSEEK_MAX_TOKENS=16384`)는 실측 실패값이었으며,
(ii) `.env.example`의 truthy 플레이스홀더 비전 키 때문에 **새 체크아웃에서는 플립이 픽셀에 닿지
않았다**(가짜 키 → 판정불가 3건 → 차단기 → 정작 `vision_api_key_missing`은 침묵). 두 건의 원인은
하나다: 첫 패스가 `DECISIONS` 멤버만 훑어서 **이미 보고 있는 곳만** 봤다. 이제 `.env.example` 전수
대조가 테스트다.

reject 6건 중 판단이 필요했던 것: `.env.example`의 `QWEN_TTS_CLONE_ENABLED=false` 주석 처리가
새 체크아웃의 TTS를 깨뜨린다는 지적. 확인 결과 깨지는 방식이 `tts.py:_voice_config`의
**이름 있는 RuntimeError + 고칠 스크립트 지목**이고, 그 전의 조용한 스톡 음성 대체가 바로 13.6이
"가장 날카로운 사례"로 기록한 침묵이다. 의도된 동작으로 유지하고 `.env.example`에 그 사실을 적었다.

### 검증

- `uv run pytest tests/test_config.py tests/test_report_decision_drift.py tests/pipeline/nodes/test_image.py tests/services/test_vision_check.py -q` → 통과(신규 포함)
- `uv run pytest tests/ -q` → **1 failed, 3207 passed, 1 skipped** (411s). 유일한 적색은 사전
  적색 1건이고 이 스토리와 무관하다(아래 잔여 리스크 1). 이 런에는 동시 진행 중인 14.7 세션의
  `test_scenario_chain.py` 신규 67줄도 포함돼 있었고 전부 통과했다.
- `uv run ruff check src tests scripts _bmad-output/.../14-4-live-validation` → clean
- `uv run pyright` 신규 오류 0(image.py의 2건은 `003045c` 워크트리에서 바이트 동일하게 재현)
- `uv run python scripts/report_decision_drift.py` → exit 0, 표류 0, env 출처 0, 잠재 핀 0.
  `/tmp`에서 실행해도 같은 파일을 읽는다(리뷰 수정)
- `uv run python .../derive_guard_rungs.py` → 43 / 38 / 5 / 소진 0, 없는 런은 exit 3
- `uv run python .../probe_vision_latency.py --limit 1..4` → 실측, `--limit 0`은 exit 2로 거부
- 프롬프트 무변경 계약: 이 스토리가 손댄 `prompts/` 파일은 **0개**. (워킹 트리의
  `prompts/scenario/review.md` 변경은 **동시 진행 중인 Story 14.7 세션**의 것이며 이 커밋에
  포함하지 않는다 — `spec-14-7-...md` status=in-review.)

### 잔여 리스크

1. **사전 적색 1건**: `tests/test_render_pose_guides.py::…[humanoid_lying_supine]`(PIL 렌더 sha 핀,
   기대 `fbeb030b…` / 산출 `48c55bc2…`). `003045c` 클린 워크트리에서 바이트 동일하게 재현되고,
   `scripts/render_pose_guides.py`가 `Settings`에서 읽는 것은 `character_image_width/height`뿐인데
   이 스토리는 그 둘을 건드리지 않았다. 이 스토리의 회귀가 아니므로 고치지 않았다.
2. **비전 콜 지연의 상한이 미확정.** 7콜 중 하나가 같은 프레임에서 10.11초였다. 30초 Block-If
   안쪽이지만 여유가 3배뿐이고, 표본은 한 계정·하루·전부 음성 판정이다. 양성 판정이 더 느린지는
   모른다.
3. **오탐 비용이 미측정.** rung 1 다섯 건 중 확인된 오염은 3건, `S00103`은 오탐 개연이 높고
   `S00202`는 육안 미확인. 오탐은 히트마다 ~17초를 영구히 낸다. 다음 런의 히트 프레임을 눈으로
   보는 것이 임계값 판단의 가장 싼 길이다.
4. **집계 렌더 비용에 경고가 없다**(보류, `deferred-work.md`). 샷당 상한은 구조적으로 2단이지만,
   체크포인트가 바뀌어 히트율이 12%→60%가 되면 느린 런으로만 나타난다.
5. **`DECISIONS`는 주석의 인덱스이고 기계적 연결이 없다.** 인용 문구 부패는 테스트가 잡지만,
   행과 주석의 *값*이 갈리는 것은 잡지 못한다(일부러 — 그러면 리포트가 게이트가 된다).
6. **"그림 속 인물"은 아직 아무 층도 실제로 막지 않는다.** 결정만 됐고 집행은 14.1이다.
   그때까지 이 결함 부류는 감수다.
