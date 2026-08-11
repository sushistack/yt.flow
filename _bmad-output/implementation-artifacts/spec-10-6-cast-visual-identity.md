---
title: 'Story 10.6 — Cast visual identity: derived-card look inheritance + D-class re-inspection (지적 14·15)'
type: 'bugfix'
created: '2026-08-11'
status: 'done'
baseline_revision: '25bed30'
final_revision: '4a57740'
baseline_tests: '2672 passed, 1 skipped, 0 failed'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
warnings: ['multiple-goals', 'oversized']
---

<intent-contract>

## Intent

**Problem (지적 15, cause proven in code+DB, not hypothesised):** `_ensure_derived_entity_cards`
(`run_service.py:612-615`) builds a derived entity's descriptor as the **base entity's verbatim
`visual_descriptor` + one qualifier line**, and passes `anchor_path` = the base's own front card as an
IPAdapter identity lock. `characters.SCP-049-2.visual_descriptor` in this tree is therefore literally
`"SCP-049 plague doctor humanoid, black hooded robe, white beaked plague doctor mask, dark gloves, full
body\nA reclassified/duplicate instance of SCP-049."` — and both its cards
(`epoch_1/front_candidate_1.png`, `epoch_2/hint_475c8a9231_front.png`) are hooded plague doctors in
white beak masks, i.e. the same person as SCP-049 in 13 of 66 shots. The re-creation path already
encodes the correct distinction (`recompose_service.CARD_LOOKS`: 049 = beak mask, 049-2 = "torn
surgical scrubs"); only the card generator inherits. Secondary: the no-base fallback string injects
`"an SCP Foundation anomaly"` — the demonstrated mask attractor.

**Problem (지적 14, cause NOT yet attributed):** the 8.15-approved D-class **standing** set is not the
defect — `epoch_2/front_candidate_1.png` is a correct 30s male in an orange numbered jumpsuit. The
frame Jay saw came from the **ungated on-demand pose-hint path**: `hint_a40ec9c170_front.png`
(`pose_hint="lying supine on table"`, `pose_hint_key` verified) was composited into **7 of the 19**
D-class shots and shows blank pupil-less eyes, a hulking bodybuilder silhouette with a tiny head, a
mottled face and formless blob hands — while standing upright. `generate_special_pose_card`
(`character_service.py:949`) calls `provider.generate()` with **no `negative_suffix`**, so
`STOCK_NEGATIVE` — which the base cards do get and which names `glowing eyes, monster, chibi, child` —
never reaches this path. That is a *candidate* cause with a live competing one: both bad hint cards
predate 10.3's 2026-08-09 removal of `horror.safetensors` (SD1.5 layout, half the UNet silently
discarded), so a stale-chain artefact explains the same pixels.

**Approach:** ① fix the derived-card rule — authored derived descriptor, no base anchor, no base
wardrobe text, refuse-to-guess when unauthored (the policy `cast_decision.md` and `CARD_LOOKS` already
state twice). ② For 지적 14, run a **pre-registered 2-leg isolation on today's fixed chain before
touching any code path's default**, with the historical asset as control, and let it decide whether a
code change is warranted at all. All regenerated pixels land in a validation directory; nothing is
written to `angle_*_path` or `character_cards`.

## Boundaries & Constraints

**Always:**
- **Evidence, not wiring, closes this story.** Both halves close on rendered card frames a human can
  judge, recorded with the value, the control leg, and a one-command recompute script beside them
  (`gotcha_a-measurement-without-its-sample-band`).
- **Pre-register the ② pass/fail rule in this spec's Design Notes before rendering anything**, and
  record a result that contradicts the hypothesis rather than re-tuning the rule.
- Derived-entity descriptors follow the `STOCK_DESCRIPTORS` discipline verbatim: Danbooru tags lead,
  purely affirmative (no `\bno\b`, no negation — every prohibition belongs in a negative suffix), one
  concrete reproducible hook feature, concrete hair/eye colour, and **never the `"SCP Foundation"`
  token** (`gotcha_scp-foundation-token-poisons-cards`).
- Reuse `STOCK_NEGATIVE` **verbatim** where a negative suffix is applied. Applying an existing string
  on a path that was missing it is in scope; adding a term to it is not.
- Framing/scale stays alpha-bbox arithmetic. This story writes prompts and wiring only.
- ComfyUI at `localhost:8188` is already up and shared with the 10-4b session: batch renders, keep the
  total under ~10 card generations, never stop or `pkill` the server.

**Block If:**
- The ② isolation's third outcome fires (both legs still defective, or leg A already clean *and* the
  historical control cannot be explained by the stale chain) → record the frames and HALT `blocked`;
  do not invent a third hypothesis unattended.
- Promoting any regenerated asset to live (`angle_*_path`, `character_cards`, `selected_image_path`,
  a style-epoch bump) — that is Jay's gate, always deferred.
- ComfyUI becomes unreachable or the character workflow errors on every leg → HALT `blocked`. This
  story cannot close on a green test suite.

**Never:**
- **Do not write `angle_*_path` / `selected_image_path` / a `character_cards` row for any asset this
  story generates.** `_resolve_card_path` reads those columns with no status or epoch filter
  (`character_service.py:838-839`), so writing them *is* publishing
  (`gotcha_standing-cards-have-no-approval-gate`).
- No new negative-prompt clause anywhere (`gotcha_negative-prompt-overstuffing` — backfired 3×).
- No regex scrub of the base descriptor to strip its wardrobe
  (`gotcha_person-token-regex-is-unusable-on-image-prompt`).
- Do not fix "the hint card shows a standing figure when asked to lie supine" — that is 10.5's
   지적 6 (action state on cards). Record it and hand it over.
- Do not add an approval gate/lifecycle for pose-hint cards. Record the gap; it is not this story.
- Do not touch `prompts/scenario/visual_breakdown.md`, `pipeline/nodes/video.py`, or
  `pipeline/nodes/image.py` — 10-4b holds them in another session.
- Do not edit `epics.md` / `sprint-status.yaml` outside the 10-6 entry.
- No new dependency, no new provider, no new config knob.
- **Do not execute the fixed provisioning path live.** The I/O matrix specifies runtime behavior for a
  future run and is to be verified by unit tests with a monkeypatched generator — not by invoking
  `_ensure_derived_entity_cards` against the real ComfyUI, which would create the row and columns the
  rule above forbids. Live pixels come only from `render_legs.py`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Authored derived key | cast references `SCP-049-2`, no `Character` row, `DERIVED_DESCRIPTORS` has the key | `generate_cards_from_descriptor(key, <authored descriptor>, pose="standing", anchor_path=None, negative_suffix=STOCK_NEGATIVE, enrich_ban="SCP Foundation")` | No error expected |
| Unauthored derived key | cast references `SCP-173-2`, no `Character` row, no `DERIVED_DESCRIPTORS` entry | No generation. One WARNING naming the key and that no authored look exists; cast resolution keeps its existing skip | Degrade, never run failure (AD-10) |
| Derived key already has a row | `Character` row exists for `SCP-049-2` | Unchanged: no generation (pre-existing behavior — regeneration is a Jay gate, not a runtime action) | No error expected |
| Base entity has no front card | authored key present, base row missing/frontless | Generation still proceeds (descriptor is authored, the anchor was the only thing the base supplied) — WARNING no longer claims a lost "family-resemblance anchor" | No error expected |
| Cap exceeded | 3 authored derived keys, `derived_entity_max_per_run=2` | First 2 generate; WARNING names the skipped keys | Degrade (existing behavior, unchanged) |
| Descriptor hygiene violated | a `DERIVED_DESCRIPTORS` value contains `"SCP Foundation"` or a `\bno\b` negation | Test fails at collection time | Test-time failure, not runtime |

</intent-contract>

## Code Map

- `src/yt_flow/services/run_service.py:552-635` -- `_ensure_derived_entity_cards`; lines 598-621 hold the
  anchor + inherited-descriptor bug and the `"an SCP Foundation anomaly"` fallback.
- `scripts/seed_stock_cast.py:39-105` -- `_BARE_FACE` / `_KEY_FEATURES` / `STOCK_DESCRIPTORS` /
  `STOCK_NEGATIVE` / `BANNED_STOCK_TOKEN`; the authored-descriptor conventions to copy. Line 217 is the
  other `generate_cards_from_descriptor` call site; line 227 holds the derived-key `enrich_ban` decision
  this story reverses.
- `src/yt_flow/domain/state.py:90-103` -- `STOCK_CAST_KEYS` + `STOCK_CAST_ROLES`; the precedent and new
  home for authored cast tables that both `src/` and `scripts/` must read.
- `src/yt_flow/services/recompose_service.py:32-38` -- `CARD_LOOKS`; the already-correct 049 vs 049-2
  distinction and the refuse-to-guess precedent (its comment states the policy).
- `src/yt_flow/services/character_service.py:909-975` -- `generate_special_pose_card`; line 949 omits
  `negative_suffix`, line 966 auto-approves with no human gate.
- `src/yt_flow/services/character_service.py:1284-1313` -- `resolve_cast_cards` hint-card branch; how a
  pose-hint card reaches a frame ahead of the base card.
- `src/yt_flow/services/character_service.py:812-907, 1368-1391` --
  `generate_cards_from_descriptor` (`stage=` semantics, `enrich_ban`) and `_resolve_card_path` (the
  unfiltered standing-column read that makes a write a publish).
- `src/yt_flow/services/character_image_provider.py:221-349` -- `ComfyUICharacterProvider.generate`;
  honors `negative_suffix`, and `_inject_seed` randomizes the seed on every call (so a 1-vs-1 leg
  comparison needs `random.seed()` pinned around each call).
- `tests/services/test_run_service_character_provisioning.py:427-660` -- the 10 tests pinning
  `_ensure_derived_entity_cards`; :519 and :548 are the two that assert on anchor/descriptor.
- `tests/test_seed_stock_cast.py:200-258` -- the descriptor/negative hygiene tests to extend.
- `assets/characters/{SCP-049,SCP-049-2,STOCK-d-class}/` and `assets/manifest.json`
  (`style_epoch: 2`) -- the assets under inspection.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/10-6-live-validation/README.md` -- create it and write the
  **pre-registered** ② rule + leg definitions **before any render** -- the epic's measurement
  discipline; a threshold invented after seeing a distribution is not evidence.
- [x] `src/yt_flow/domain/state.py` -- add `DERIVED_DESCRIPTORS` with the authored `SCP-049-2` look
  (maskless, hoodless, ashen, sutured, torn surgical scrubs), affirmative-only, no `"SCP Foundation"`,
  and relocate `STOCK_NEGATIVE` / `BANNED_STOCK_TOKEN` here with their authored comments intact --
  `run_service` needs all three and `src/` must never import `scripts/`; this is where
  `STOCK_CAST_KEYS`/`STOCK_CAST_ROLES` already live for exactly this reason ("lives beside the keys so
  the prompt catalog cannot drift").
- [x] `scripts/seed_stock_cast.py` -- import the three relocated names instead of defining them, leaving
  behavior and its own `STOCK_DESCRIPTORS` untouched -- re-exporting keeps `seed.STOCK_NEGATIVE` and
  `seed.BANNED_STOCK_TOKEN` resolving, so `tests/test_seed_stock_cast.py:193,239` need no edit.
- [x] `src/yt_flow/services/run_service.py` -- rewrite `_ensure_derived_entity_cards`'s descriptor/anchor
  resolution: authored descriptor, `anchor_path=None`, `negative_suffix=STOCK_NEGATIVE`,
  `enrich_ban=BANNED_STOCK_TOKEN`, and skip-with-WARNING for unauthored keys; delete the inherited
  `base.visual_descriptor` read and the `"an SCP Foundation anomaly"` fallback -- removes the proven
  cause of 지적 15 and the mask attractor in one edit.
- [x] `tests/services/test_run_service_character_provisioning.py` -- update :519/:548 to the new
  contract and add: authored-key kwargs, unauthored-key no-call + WARNING, base-frontless still
  generates -- the two existing tests actively pin the bug.
- [x] `tests/test_seed_stock_cast.py` -- extend the hygiene tests to iterate
  `DERIVED_DESCRIPTORS` too (affirmative-only, no banned token) -- the one runnable check that fails if
  a future authored look reintroduces either landmine.
- [x] `_bmad-output/implementation-artifacts/10-6-live-validation/render_legs.py` -- one-command script
  that renders every leg into that directory with `random.seed()` pinned per call, writing files only
  under it: ①-old / ①-new for the derived rule (1 each), ②-A / ②-B for the negative-suffix isolation
  (3 each) -- the required recompute script. It **must call
  `CharacterService._compile_generation_prompt` + `provider.generate` directly and never
  `generate_cards_from_descriptor` / `generate_special_pose_card`**, because both of those write assets,
  manifest entries, card rows and `angle_*_path` — i.e. publish (see **Never**).
- [x] `src/yt_flow/services/character_service.py` -- **only if leg A/B lands on H1**: pass
  `negative_suffix=STOCK_NEGATIVE`'s value through `generate_special_pose_card`'s `provider.generate`
  call (line 949) and cover it with a test asserting the kwarg -- the base cards get that suppression and
  this path never did. If the isolation lands on H2, leave this file untouched and say so.
- [x] `_bmad-output/implementation-artifacts/10-6-live-validation/README.md` -- after rendering, record
  the D-class base-asset verdict ("없음" or not) with its inspected paths, the 7/19 usage count and its
  recompute command, the per-leg judgments against the pre-registered rule, and the two hand-offs
  (pose not rendered → 10.5; pose-hint cards have no approval gate → deferred-work).
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- append the Jay gates: promote or
  reject the regenerated `SCP-049-2` look, and decide the fate of the two live ungated D-class hint
  cards (`hint_a40ec9c170`, `hint_970ede32f4`) -- promotion is never unattended.
- [x] `_bmad-output/planning-artifacts/epics.md` + `_bmad-output/implementation-artifacts/sprint-status.yaml`
  -- update the **10-6 entry only** -- 10-4b owns the rest of both files this session.

**Acceptance Criteria:**
- Given a run whose cast references `SCP-049-2` with no `Character` row, when derived provisioning runs,
  then `generate_cards_from_descriptor` receives the authored descriptor with `anchor_path=None`, and
  neither the argument nor the resulting `characters.visual_descriptor` contains any of `plague`,
  `beak`, `hooded`, or `SCP Foundation`.
- Given a derived key with no authored look, when derived provisioning runs, then nothing is generated,
  one WARNING names the key, and the run completes (AD-10).
- Given the pre-registered ② rule and the four rendered legs, when each leg is judged, then the README
  states which hypothesis survived — including the outcome where the code change proves unnecessary
  because 10.3's chain fix already removed the defect.
- Given the ① old-rule and new-rule legs rendered at the same pinned seed on the same chain, when both
  are viewed, then the new-rule card shows an unmasked human head and no hooded coat while the old-rule
  card reproduces the plague-doctor look — establishing the descriptor as the operative variable rather
  than a new seed.
- Given the whole story is complete, when `git status` is inspected, then no file under
  `assets/characters/` is modified or added, `assets/manifest.json` is unchanged, and no row in
  `characters` / `character_cards` differs from its pre-story value.
- Given the D-class 8.15-approved standing set, when its four `epoch_2/*_candidate_1.png` frames are
  inspected, then the README records an explicit per-frame verdict with paths — and if no defect is
  found, records "없음" with the evidence rather than regenerating preventively.

## Spec Change Log

- 2026-08-11 -- Execution complete. The ② isolation's pre-registered decision table landed on
  **H1** (leg A 2/3 fail, leg B 1/3 fail on today's chain at a shared seed triple), so the
  `negative_suffix` wiring on `generate_special_pose_card` **was** warranted and shipped — scoped to
  STOCK + authored-derived keys, because `STOCK_NEGATIVE` suppresses `skull mask, helmet, visor` and
  an entity whose identity *is* a mask would be erased by it. Two things the pre-registration did not
  anticipate are recorded in `10-6-live-validation/README.md` rather than fixed by amending the rule:
  the criteria carry no figure-count clause (so the sharpest same-seed difference — an adult plus a
  chibi child in leg A at seed 1062 versus a single adult in leg B — is invisible to them), and
  criterion (c) fails in both legs (hands are a chronic weakness of this chain). The ① legs came back
  as expected: old = beak mask + hooded coat, new = bare human head + surgical gown at the same
  pinned seed. No asset and no DB row was written.

## Review Triage Log

### 2026-08-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 2, medium 5, low 4)
- defer: 3: (high 0, medium 3, low 0)
- reject: 9: (high 1, medium 5, low 3)
- addressed_findings:
  - `[high]` `[patch]` `_maskless_negative_suffix` keyed on `DERIVED_DESCRIPTORS` membership, but `generate_special_pose_card` builds its positive prompt from the **stored** descriptor. For a pre-10.6 derived row (i.e. `SCP-049-2` today) that meant a prompt demanding "white beaked plague doctor mask" rendered against a negative suppressing `skull mask, gas mask, helmet, visor` — self-fighting conditioning on a reachable path (run `8a9a288b` used `hint:475c8a9231` for that key). Both reviewers found it independently. Now scoped on the descriptor actually in play (`startswith` the authored look, since the vision read-back is appended); new test case pins the stale-row behaviour.
  - `[high]` `[patch]` Cap applied before the authored filter: `to_generate[:cap]` was sliced first and the unauthored skip happened *inside* the loop, so unauthored keys consumed the budget and then `continue`d — an authored key behind two unauthored ones was never generated. Reordered to authored-first, then cap; regression test added (`..._unauthored_keys_do_not_consume_the_cap`) and the existing cap test updated, since the cap now applies among authored keys only.
  - `[medium]` `[patch]` The manual path contradicted the runtime rule: `seed_stock_cast.py` computed `is_stock = key in STOCK_DESCRIPTORS`, so hand-seeding `SCP-049-2` got neither `STOCK_NEGATIVE` nor `enrich_ban` while the pipeline applied both. Now `is_maskless` covers authored derived keys, and `--key` defaults its descriptor from `DERIVED_DESCRIPTORS` so the authored table cannot be bypassed by free text. The 8.13-era test pinning the old contract was updated, and a companion test pins that *unauthored* derived keys stay unsuppressed.
  - `[medium]` `[patch]` Nothing enforced the "authored derived looks are maskless" invariant the runtime scoping depends on. Added `test_authored_derived_looks_never_request_what_stock_negative_suppresses` — a design-time check over every `STOCK_NEGATIVE` term plus `mask`/`hood`/`beak`, so a future authored look that wants a mask or a monster fails at collection instead of rendering with its own request suppressed.
  - `[medium]` `[patch]` No lockstep guard between `DERIVED_DESCRIPTORS` and `recompose_service.CARD_LOOKS`, the authority every 10.6 comment cites — and `CARD_LOOKS` silently skips keys it lacks, so an authored card could be generated then dropped from the re-creation path. Added `test_every_authored_derived_look_is_known_to_the_recomposer` (lives in tests because `state.py` may not import `services`, AD-1).
  - `[medium]` `[patch]` Evidence overclaim on leg ①: code comments, the render script and the README all called the descriptor "the isolated variable", but the pair changes descriptor, anchor, negative suffix **and** t2i-vs-i2i graph topology at once, so the shared RNG seed is not a paired sample and dropping the IPAdapter anchor alone could explain the whole result. Reworded in all four places to "the new rule no longer renders a second SCP-049", with the missing third leg named.
  - `[medium]` `[patch]` Evidence overclaim on leg ②: the `_maskless_negative_suffix` docstring restated the pre-registered 2/3-vs-1/3 tally as established cause, though every scored failure was the hand criterion which failed in both legs. Docstring now leads with the mechanism and the seed-1062 pair and points at the README before the count is quoted.
  - `[low]` `[patch]` "13 of 66 shots" (in `state.py` and `run_service.py` comments) is a cast-slot count from a checkpoint query, not a judged-defect count. Relabelled, with the actual basis of the identity judgment named.
  - `[low]` `[patch]` `DERIVED_DESCRIPTORS` had no key-shape guard while both neighbouring tables in `state.py` assert their coverage; a typo'd key would sit dead forever since lookups only ever use `<scp_id>-<n>`. Added the assert (and `import re`).
  - `[low]` `[patch]` Relocated comment lost its referent — it claimed the banned token is "absent from every descriptor below" while `STOCK_DESCRIPTORS` stayed in `scripts/`. Reworded to name both tables. Also updated `state.py`'s module docstring, which promised "pure stdlib typing only" and now hosts authored cast/prompt tables.
  - `[low]` `[patch]` `render_legs.py` hardening: stale line-number citation removed (it went stale within one session), `db_path`/`assets_path` resolved against the repo root instead of cwd, hard exit unless the provider is `ComfyUICharacterProvider` with `comfyui_mock` off (`QwenCharacterProvider` discards `negative_suffix` with a warning and never reaches `_inject_seed`, which would silently void both legs), and the actual injected KSampler seed is now logged rather than only the RNG input.
  - `[high]` `[reject]` "The fix is inert for the only key it implements" — real and already disclosed in the README, `epics.md` and `sprint-status.yaml`; this pass strengthened that disclosure further. The proposed guard (treat a stale inherited descriptor as unprovisioned and regenerate) is rejected on purpose: it would auto-publish an unreviewed look to `angle_*_path`, which the spec's **Never** rule and `gotcha_standing-cards-have-no-approval-gate` forbid. Correct disposition is the Jay gate already in `deferred-work.md`.
  - `[medium]` `[reject]` ×8 — findings about `pipeline/nodes/scenario_chain.py`, `prompts/scenario/visual_breakdown.md` and the `_fallback_prompt`/`_NO_FIGURE_FRAMINGS`/prompt-seeding items. These belong to story 10.4b, owned by another session; they entered the first reviewer's diff through my own scoping error and were re-scoped out for the second reviewer. Not this story's to patch, defer, or record.

## Design Notes

**Pre-registered ② rule (fixed before any render; 3 renders per leg, `random.seed()` pinned so the two
legs share their seed triple).** Prompt and hint text are `generate_special_pose_card`'s exact
composition for `STOCK-d-class` / `"lying supine on table"`. A render **fails** if any of: (a) neither
eye shows a pupil/iris, (b) shoulder-width exceeds ~3× head-width or the head is otherwise
non-human-proportioned, (c) neither hand resolves into distinguishable digits. Judged per render, then:

| Leg A (no suffix, today's chain) | Leg B (`STOCK_NEGATIVE`, today's chain) | Conclusion |
|---|---|---|
| ≥2/3 fail | ≤1/3 fail | H1 — the missing suffix. Ship the `negative_suffix` wiring on the special-pose path. |
| ≤1/3 fail | ≤1/3 fail | H2 — 10.3's `horror.safetensors` removal already fixed it. **No code change.** 지적 14 becomes "regenerate the two stale hint cards", a Jay gate. |
| ≥2/3 fail | ≥2/3 fail | Neither. Record and HALT `blocked`. |

Control leg is the historical `assets/characters/STOCK-d-class/epoch_2/hint_a40ec9c170_front.png`
(2026-08-07, pre-10.3 chain), which fails all three criteria; it is what makes "today's chain is
already clean" a falsifiable claim rather than an absence of evidence.

**Why refuse-to-guess for unauthored derived keys.** It reverts 8.13's benefit (a referenced derived
entity showing *something*) for entities that have never produced a derived key in practice, and that
trade is deliberate: `cast_decision.md` states "A wrong card is far worse than no card", and
`CARD_LOOKS` already skips rather than guesses "because a wrong description silently redraws the wrong
character". Guessing is what produced 지적 15. The natural upgrade — mining the derived entity's look
from the article via the existing research step — is a new LLM path and belongs in its own story; leave
it as a `ponytail:` comment naming that ceiling, not as speculative code.

**Why `enrich_ban` now applies to derived keys.** `seed_stock_cast.py:227` deliberately keeps the
`"SCP Foundation"` token for derived keys ("Derived keys are SCP entities, so they keep it"). This
story reverses that for derived keys specifically, because the token is the live-proven mask attractor
and SCP-049-2's authored look is defined by the *absence* of a mask. The reversal is a hypothesis about
pixels, so the ① new-rule leg is what confirms it; record it if the frame comes back masked anyway.

## Verification

**Commands:**
- `uv run pytest tests/services/test_run_service_character_provisioning.py tests/test_seed_stock_cast.py -q`
  -- expected: all pass, including the three new derived-descriptor tests.
- `uv run pytest -q` -- expected: no new failures vs the pre-story baseline (record the baseline count
  first; `test_services_does_not_import_api_or_pipeline` is a known pre-existing state to compare, not
  to fix).
- `uv run ruff check src scripts tests` -- expected: clean.
- `uv run python _bmad-output/implementation-artifacts/10-6-live-validation/render_legs.py`
  -- expected: 8 PNGs under `10-6-live-validation/`, every one with an alpha channel, exit 0.
- `git status --porcelain assets/ yt_flow.db` -- expected: empty (no asset or DB mutation).
- `curl -s -m 5 -o /dev/null -w '%{http_code}' http://localhost:8188/system_stats` -- expected: `200`
  before and after rendering (the shared ComfyUI survived).

**Manual checks (if no CLI):**
- View each rendered leg and the four D-class `epoch_2/*_candidate_1.png` frames directly; the judgments
  in the README must be written from those views, not inferred from filenames or metadata.

## Auto Run Result

Status: **done** — `final_revision` `4a57740`, baseline `25bed30`.

### What changed

지적 15's cause was code, not data. `_ensure_derived_entity_cards` built a derived entity's
descriptor as the base entity's verbatim `visual_descriptor` plus one qualifier line, and passed the
base's own front card as an IPAdapter identity anchor — so `SCP-049-2` rendered as a second hooded,
beak-masked plague doctor. `recompose_service.CARD_LOOKS` already distinguished the two; only the card
generator inherited. Fixed by authoring the look (`DERIVED_DESCRIPTORS`), dropping the anchor, applying
the suppression and read-back scrub, and **refusing to guess** for unauthored derived keys.

지적 14 was **not** in the 8.15-approved standing set (verdict "없음", recorded per frame). It came from
the ungated on-demand pose-hint card `hint_a40ec9c170`, composited into 7 of the 19 D-class shots. A
pre-registered 2-leg isolation at a shared seed triple selected H1 (the missing `negative_suffix`) over
H2 (10.3's stale LoRA chain), so the suffix wiring shipped — scoped so it can never suppress a mask an
entity's own descriptor requests.

### Files changed

- `src/yt_flow/domain/state.py` — `DERIVED_DESCRIPTORS` authored; `STOCK_NEGATIVE` / `BANNED_STOCK_TOKEN` relocated here (run_service needs them and `src/` may not import `scripts/`); key-shape assert; module docstring now admits the authored tables.
- `src/yt_flow/services/run_service.py` — authored descriptor, `anchor_path=None`, suffix + `enrich_ban`; unauthored keys skipped with a WARNING; authored-first filtering moved ahead of the cap.
- `src/yt_flow/services/character_service.py` — `_maskless_negative_suffix(card_key, descriptor)` wired into `generate_special_pose_card`, scoped on the descriptor actually in play.
- `scripts/seed_stock_cast.py` — re-exports the relocated names; authored derived keys now get the same suffix/ban as stock keys, and `--key` defaults its descriptor from the authored table.
- `tests/…` (3 files) — +8 tests: authored-key kwargs, unauthored no-call, cap-not-consumed regression, stale-descriptor suffix suppression, design-time masklessness invariant, CARD_LOOKS lockstep, manual-path parity both ways.
- `_bmad-output/implementation-artifacts/10-6-live-validation/` — 8 rendered legs, `README.md` (pre-registered rule, per-render verdicts, per-frame D-class verdict, recompute commands), `render_legs.py` (read-only DB, provider/mock guards, logs the injected KSampler seed).

### Review

Two reviewers in parallel. **11 patches** (high 2, medium 5, low 4), **3 deferred**, **9 rejected** —
8 of the rejections were findings about story 10.4b's files, which entered the first reviewer's diff
through my own scoping error and were excluded for the second. The two high-severity patches:

1. The pose-card suffix keyed on table membership while the prompt is built from the *stored*
   descriptor — for the pre-10.6 `SCP-049-2` row that meant demanding a beak mask while suppressing
   masks. Both reviewers found it independently.
2. The cap was applied before the authored filter, so unauthored keys consumed the budget and skipped,
   starving an authored key behind them.

### Verification

- `uv run pytest -q` → **2680 passed, 1 skipped, 0 failed** (baseline 2672/1/0, +8).
- `uv run ruff check src scripts tests …/render_legs.py` → **All checks passed!**
- `render_legs.py` → 8 PNGs, all `alpha=True`, exit 0, idempotent re-run (no GPU spend).
- `git status --porcelain assets/` → empty. DB unmutated, asserted directly (9 characters / 12 cards /
  `SCP-049-2` descriptor unchanged) rather than via `git status`, which is **vacuous** for
  `yt_flow.db` — `.gitignore:15` makes it untracked.
- ComfyUI `/system_stats` → 200 before and after; never stopped, no `pkill`, 8 renders total.
- Every pixel judgment was made by viewing the file, including an independent re-verification of the
  D-class `side_candidate_1.png` artefact and of the leg-B eye region that the first read got wrong.

### Residual risks

- **The fix is not retroactive, so 지적 15 is still on screen.** Generation fires only when no
  `Character` row exists, and `SCP-049-2` has one. Its live cards and descriptor are still the masked
  ones. Replacing them is Jay's gate; auto-regenerating was rejected on purpose because it would
  publish an unreviewed look to `angle_*_path`, which has no approval filter. This is the exact failure
  mode Epic 10 exists to prevent, so it is recorded in `epics.md`, `sprint-status.yaml`, the README and
  `deferred-work.md`.
- Leg ① compares the **whole rule** — descriptor, anchor, suffix and t2i-vs-i2i topology changed
  together — so it must not be cited as attributing the change to the descriptor.
- Leg ②'s pre-registered tally (2/3 vs 1/3) is weak on its own: every scored failure was the hand
  criterion, which failed in both legs. The mechanism and the seed-1062 pair (adult + chibi child vs
  one adult, against a suffix naming `2boys, child, chibi`) carry the conclusion. The rule was not
  re-tuned after the fact, and its blind spot — no figure-count criterion — is recorded.
- Newly provisioned derived cards still publish unattended (unchanged from 8.13); no gated promote path
  accepts derived keys. Deferred.
- Refuse-to-guess means every SCP other than 049 loses its derived card entirely. Deliberate and
  spec-recorded, but it restores 8.13's original symptom for those entities. Deferred.
