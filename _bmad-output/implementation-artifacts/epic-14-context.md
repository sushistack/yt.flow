# Epic 14 Context: Visual Asset Layer — Moving to Curated Sets (Backgrounds, D-Class, Objects)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A full-length viewing verdict left five coupled visual defects: broken perspective, inconsistent backgrounds, people drawn into supposedly people-free backgrounds, narration that does not match the background or the character pose, and art-style drift across shots. They share one prescription — **stop generating a fresh background per shot and pick from human-approved asset sets instead**. Consistency, emptiness and style get filtered once at approval time; perspective, affordance and narration match, which cannot be guessed at generation time, become queryable metadata attached to the asset. Per-run GPU cost drops because backgrounds are no longer synthesized per shot (filling the sets is a one-time expense). This is not a new architecture — it completes an earlier, abandoned plate-reuse attempt and connects the existing stock-plate, asset-library and plate-data layers. **The central proposition has still never shipped**: plate substitution remains off by default, so every shot in the reference run was free-generated. Turning it on is the epic's remaining outcome.

## Stories

- Story 14.0: 리서치 게이트 — ②⑤⑥은 자료 없이 착수하지 않는다 (done)
- Story 14.1: 승인된 배경 플레이트 세트 — 샷 단위·프롬프트 인식 재사용 (done; flag ships OFF)
- Story 14.2: 플레이트 어포던스 게이트 — 인물이 설 수 있는 플레이트만 캐스트 샷에 (done; knob ships OFF)
- Story 14.3: 화풍 계약 — 플레이트와 카드가 하나의 렌더 스타일을 공유 (shipped: attribution path + workflow style contract)
- Story 14.4: 무인 배경을 출하 기본값으로 — 가드 승격 + "그림 속 인물" 처리 (done)
- Story 14.5: 나레이션 ↔ 배경·포즈 정합 (done; the prompt edit was rejected, measurement corrections were the yield)
- Story 14.6: D급·오브젝트 자산 세트 + 카드 라이브러리 재생성 (gates/contract/audit done; pixels and the object set open)
- Story 14.7: scenario 리뷰어를 recompose 이후 규칙에 맞춘다 (done)
- Story 14.8: 배경 플레이트 재활용을 실제로 출하한다 (ready-for-dev — the epic's open work)

## Requirements & Constraints

- **Reuse is the goal, not a regression.** When candidates run short, grow the set — never derive variants from one plate, and never "fix" reduced background diversity. The earlier attempt failed because assignment keyed on scene rather than the shot's own prompt, collapsing a 21-shot scene onto one plate.
- **The blind human verdict is the epic's ground truth, and it reclassified the problem.** A 2026-08-30 blind pass over the shipped 43-tile contact sheet flagged **17 shots spanning five distinct classes** — palette/style 7, compositing 5, unreadable background 3, figure scale 1, person-in-background 1. Most of what was filed as "art style drift" is not art style drift, so **no single style metric can gate this axis**: a cut on the palette axis closes ~41% of the flagged frames and miscounts the rest as inspected.
- **Machine visual labels lose to human judgement here — three times in this epic.** Automated labelling underestimated the defect base rate 2.4x (7/43 vs 17/43). Any promotion decision needs a human viewing verdict, not a score.
- **Negative prompts are not the answer** to background population or to style; adding a clause per defect has wrecked renders twice, and person tokens were already present when a framed portrait still rendered. The only mechanism that works is **detect-then-regenerate** (render, judge pixels, re-roll).
- **Viewpoint is not a function of prompt text** — same prompt, new seed flipped viewpoint in 2 of 5 controlled pairs. Text screening cannot guarantee framing; a viewpoint or style gate must measure rendered pixels.
- **Text pose instructions are ignored by the renderer.** Pose comes from approved card assets or pose conditioning, never from wording.
- **Never promote a prompt-derived checklist to a visual gate.** Those questions are leading — unreadable frames score *higher* because nothing in them contradicts. Sub-axes are worse than the aggregate. Gating verdicts must be blind to the generating prompt, and a fourth instrumentation round is not authorized.
- **Screen every prompt change as text before spending GPU**, and pin the request envelope, not just the prompt text.
- **A decision only ships if it reaches the code default.** Product judgements live as the `config.py` default plus a dated verdict comment; env files stay unpinned. The drift report is an instrument, not a build gate.
- **Undecidable judgements are accepted, not retried** — they consume no ladder rung but must raise a per-shot warning. Never count an unscreened frame as clean.
- **Sampler-internal interventions are unavailable** (no installed custom node implements them); narration-match work goes through the prompt-rewriting layer.
- **Identity floor holds.** No scene-conditioned human-insertion model is adopted; poses come from *more approved cards*. Style work must not loosen identity to close the style gap.
- **Writing to a character's angle paths is publishing** — regeneration happens behind an approval gate, and an epoch promotes atomically (every key and pose together, always closing with the epoch bump).

## Technical Decisions

- **The shot is the image-generation unit**, mapped N:M onto narration sentences. Plate assignment, affordance judging and match scoring are all per-shot; scene granularity reproduces the known collapse.
- **Plate selection is a pure filter chain** — framing, then metadata, then viewpoint, then person, then affordance — falling back to generation when no candidate fits. Metadata (viewpoint, standing room, depicts-person) is measured once per plate, so per-run cost is zero. The selector reads only camera angle, cast and location key; it discards the shot prompt, and semantic prompt match is explicitly out of its scope.
- **Affordance = asset metadata plus a runtime path for free-generated shots, with one shared judgement schema.** The runtime half is permanent; approved sets change its scope, not its existence.
- **A shared judgement prompt is not enough — the request envelope must match.** Image-before-text vs text-before-image is a deterministic order effect (3/7 vs 5/7, zero within-condition flips). Pin image-first plus temperature 0 wherever an offline curator and the runtime must agree.
- **One VLM blind spot is permanent**: corpse/medical/gore plates draw a hard content rejection from the vision endpoint. Since those are routine output here, treating "undecidable" as "no standing room" would delete cast from that whole class.
- **Camera-angle field and prompt body do not conflict** (43/43 agreement) — a widely repeated assumption to the contrary is false. The field never reaches the background renderer's prompt but does drive cast-card angle selection, so it is not render-inert. The intervention point is inside the prompt text.
- **Do not build a floor/ceiling text-mass gate**, and do not widen the cast-suppression keyword vocabulary — high-angle plates are overwhelmingly fine, and measured surface-noun mass runs opposite to the hypothesis.
- **Card sprites have a declared contract** (alpha profile plus sprite-validity reasons) enforced at the approval gate alongside the alpha check. Cards that fail it are not merely bad frames — casting them raises and kills the run.
- **Denominators must exclude rows whose correct answer is "no event"**; pooling descriptive or definitional sentences rewards inventing content the narration never claimed.
- **Any regeneration comparison needs a same-prompt control leg** — re-rolling the old prompt alone moved the target axis by +7pp.
- **Report from a population sweep, not an enumerated set of cases**, and honor a preregistered band when stamping data. Both rules were established by findings that inverted this epic's own conclusions.
- **Measurement reproducibility is worse than the preregistered band** on some plates, so record both readings rather than overwriting, and never lower a criterion to fit the result.

## Cross-Story Dependencies

- The research gate (14.0) blocked 14.2, 14.3 and 14.5; it is closed, and each inherited a constraint (assets-not-models for pose, metadata-plus-runtime for affordance, prompt-rewriting for narration match).
- **14.8 is the epic's remaining work and depends on 14.1 + 14.2.** Its unlock is an AND of exactly two conditions: preregistered plate-coverage thresholds, and a human end-to-end viewing verdict on a run with substitution enabled. Five drafted plates exist to close the coverage shortfall; they must be labelled, measured and approved blind.
- **The relight-coupling item is NOT an unlock condition.** It was carried as a third condition across several documents and has now been falsified twice: the pair key lives inside a code path reachable only above the shipped harmonization tier, and the higher tier was rejected by a human viewing verdict. The coupling defect is real but unreachable at shipped defaults; it is pinned by a test and handed forward, not blocking anything here.
- **Plate substitution and the affordance knob both ship OFF and interact** — the standing-room filter sits behind the substitution flag, so whether to enable them together is an explicit decision, not an implementation detail. The plate path also has **no runtime person guard**, mitigated only by approval labels.
- **Enabling substitution shrinks the reach of prompt-layer work** from every shot to only the free-generated remainder; any later prompt measurement must state that denominator. Close-up and POV shots are permanent generation fallbacks by design, not defects.
- **14.3's flagged defect classes were routed, not fixed**: compositing and scale go to the next end-to-end iteration, unreadable backgrounds to a new story, and the diagnosed depth-phrase cause is deliberately deferred rather than edited (a one-line change would invalidate a 43-plate sweep and an existing validation slate). What 14.3 shipped is the attribution path that makes those pairs attributable in the next full run.
- **14.1 owns the "person inside a picture" class** (framed art, monitors, posters, models, statues) as an approval-gate criterion; the runtime guard deliberately does not fire on it, so until the sets cover free-generated shots this is an accepted, documented risk.
- **14.5's pose half moved to 14.6**, which closed the non-retroactive card-library state behind gates and audit but produced no pixels: the regeneration batch, bulk standing-card regeneration, and the object set are all still open. The object set has no consumer — shot data has no object axis and assets have no kind field — so its seams were handed forward.
- Pixel adjudication for the remaining axes rides the next full end-to-end iteration's blind readability judgement; no single story owns it.
