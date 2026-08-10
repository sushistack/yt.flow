---
stepsCompleted: [1, 2, 3]
inputDocuments: ['_bmad-output/implementation-artifacts/spec-10-4-image-narration-semantic-match.md', '_bmad-output/implementation-artifacts/10-4-live-validation/README.md']
workflowType: 'research'
lastStep: 3
research_type: 'technical'
research_topic: 'Why generated frames do not read as their narration sentence: prompt-side (absence as subject, shot planning) and measurement-side (VLM Likert vs QG/A metrics)'
research_goals: 'Story 10.4 measured two defects live and could not close either with the levers it tried. Find what the published literature already knows about (1) prompts whose subject is an absence, (2) mapping narration to shots, (3) measuring whether an image expresses a sentence — and turn that into the scope of Story 10.4b and the instrument upgrade in Story 13.2.'
user_name: 'Jay'
date: '2026-08-10'
web_research_enabled: true
source_verification: true
---

# Research Report: narration→image semantic alignment

**Date:** 2026-08-10
**Author:** Jay
**Research Type:** technical

---

## Why this research exists

Story 10.4 built a judgment axis, ran it over all 66 frames of the run Jay watched, and measured two defects:

- **12/66 (18.2%) frames are unreadable** — a viewer cannot say what the place is or what happened. This is Jay's finding 2, "무슨 배경인지 모르는 배경이 많음".
- **4/66 frames do not match their sentence.** This is finding 4.

It then tried two levers and neither moved the score: rewording the prompt (effect −0.333 against a same-prompt control of sd 1.87) and replacing the 1:1 sentence↔shot bijection with an ordered cover (paired Δ −0.152, 95% CI [−0.394, +0.076]; a hand-authored cover moved five merged sentences by exactly 0.000).

Reporting "does not work" and stopping is not a result. This document is what the field already knows about all three of those things, and it re-scopes the follow-up work accordingly.

---

## Finding 1 — We were asking the model to render an absence, which diffusion models cannot do

The 12 unreadable frames share a prompt shape. Their `image_prompt` makes **the absence itself the subject**:

| narration sentence | what the prompt asked for |
|---|---|
| "검은 눈구멍이 초점 없이 공중을 스캔합니다" | `close-up of open air in a containment cell, a ladder of faint dust motes` |
| "아주 협조적으로요" | `vast empty concrete floor stretching across the frame` |
| "그는 진심으로 보고 있습니다" | `over-the-shoulder view toward a blank wall section` |

Inspected directly, `S00304` ("open air") rendered as nested doorway geometry with no readable space at all. The renderer did not fail — it drew what it was told, and it was told to draw nothing.

**This is a documented, structural limitation, not a prompt-quality problem.** Text-to-image and text-to-video diffusion models fail to realise negation: prompted for "a room without a cat", the model produced a cat on 5 of 5 seeds. The interesting part of that result is *where* it breaks — the text encoder carries a correct representation of the empty room, so the model "understands" the negation linguistically, but positively steering emptiness features does not remove the object from the image ([NEGATE](https://arxiv.org/pdf/2603.06533), [SpaceVLM](https://arxiv.org/pdf/2511.12331)). Generative vision models incorporate positive attributes well and cannot perform concept exclusion from a natural-language instruction at inference time, unlike instruction-tuned LLMs.

Our own history is consistent with this and we read it as a separate problem at the time: `gotcha_negative-prompt-overstuffing` (adding a negative clause per defect made renders worse twice), and Story 10.2's finding that a background prompt forbidding people in six places still rendered people.

**Where the empty prompts come from — three of our rules colliding:**

1. `image_prompt` is **background-only**; no body, face, or clothing (Epic 8's card architecture).
2. The sentence is often **entirely about a person** — "검은 눈구멍이 …스캔합니다", "아주 협조적으로요".
3. The prompt actively teaches emptiness as craft: *"Use negative space as a storytelling tool — Large empty areas in the frame create unease… The space where something SHOULD be but isn't."*

A writer forbidden from naming the subject, handed a sentence that is only about the subject, and told that absence is good composition, writes "vast empty concrete floor". Story 10.2 already deleted one bullet of this instruction ("A figure small in an enormous space") for a related reason; the rest survived.

**Weak supporting measurement, stated as weak:** across all 66 frames, prompts whose text makes emptiness the subject (`empty|bare|blank|open air|nothing|void|featureless|devoid`) are unreadable at 29% (8/28) versus 11% (4/38) for the rest. Directionally consistent with the mechanism, but n=12 unreadable total — a hint, not proof, and a keyword match is not the mechanism itself.

---

## Finding 2 — Our measuring instrument is a generation behind

Story 10.4's axis asked a VLM for a 1–5 Likert score. Two failures showed up in its own data:

- The `legible` score was **dead**: 66 frames produced `{4:46, 5:20}`, nothing below 4 — while *the same replies* wrote `event: "unclear"` on 9/66. Replacing it with the boolean the model was already volunteering surfaced **12/66**.
- `match` **clusters at 3** (15/16 rows unchanged in the merge probe), so it has almost no resolution in the band where our defects live.

The field moved past VLM-Likert years ago, to question-generation/answering (QG/A) decomposition:

- **[TIFA](https://arxiv.org/abs/2303.11897)** — an LLM generates question/answer pairs from the prompt; a VQA model answers them against the image; the score is the fraction answered correctly. Interpretable, but its questions are independent, so a VQA model can answer inconsistently.
- **[Davidsonian Scene Graph (DSG)](https://arxiv.org/pdf/2310.18235)** (ICLR 2024, [code](https://github.com/j-min/DSG)) — decomposes the text into **atomic propositions** as typed semantic tuples, converts each to a natural-language question, and builds a **dependency graph**. A question counts as correct only if its dependencies were also correct: if the model says there is no dog and then says the dog is red, the second answer is invalidated. This is the direct fix for TIFA's hallucinated/inconsistent answers.
- **[VQAScore](https://arxiv.org/abs/2404.01291)** (ECCV 2024) — one question, *"Does this figure show {text}? Please answer yes or no"*, scored by the **probability of the "yes" token**. Continuous by construction, one call, and reported to beat CLIPScore (weak on composition) and GQA-style QG/A (yes-bias); its CLIP-FlanT5 variant outperforms proprietary GPT-4V-based scoring.

**Why this matters specifically for us:** DSG fixes both of our measured instrument defects at once.

- **Resolution** — a fraction over ~5 propositions is continuous, so it cannot cluster at 3 the way a Likert does.
- **The card-absence confound** — 11/66 of our `match` rows dock a frame for a person who is composited separately, and 28/66 blind captions read a body inside a plate that should be unpopulated. With propositions, person-propositions are simply **not generated** (or marked as satisfied by the card layer), instead of silently polluting a single opaque number.
- **Attribution** — we would learn *which* proposition failed, which is what "무슨 배경인지 모르겠다" actually needs.

Practical note: VQAScore needs token log-probabilities from the scoring endpoint; DSG needs none, only yes/no answers. Whether our endpoints expose logprobs is an open item to verify, not an assumption — DSG is the safer default because it does not depend on it.

---

## Finding 3 — Jay was right about N:M; our experiment simply could not see it

Every current story-visualisation system treats narration→shots as **planning**, not as a per-sentence mapping:

- **[ViStoryBench](https://arxiv.org/html/2505.24862v3)** uses an LLM as a **shot planner** that segments each narrative into a coherent sequence of visual shots while keeping character presence, camera composition, environment and story progression consistent — averaging 16.5 shots per story, not one per sentence.
- **[DreamStory](https://arxiv.org/html/2407.12899)** puts an LLM in as a **story director** that writes subject and scene prompts and annotates which subjects appear in each scene.
- **[Dialogue Director](https://arxiv.org/html/2412.20725)** separates a Story Director (script → enriched scene description), a cinematographer, and a storyboard maker.
- **[Narrative Graph Prompting](https://openaccess.thecvf.com/content/ICCV2025W/AISTORY/papers/Shin_Generating_Visually_Consistent_Images_for_Storytelling_via_Narrative_Graph_Prompting_ICCVW_2025_paper.pdf)** (ICCVW 2025) drives prompt generation from a narrative graph with consistent identifiers injected across frames.

So the ordered cover Story 10.4 built is the field-standard shape. What 10.4 showed is narrower and should be stated narrowly: **freeing the sentence↔shot count does not by itself raise a semantic-match score.** That is not the same claim as "N:M is wrong", and the instrument that produced it is the one Finding 2 says to replace.

**The deeper divergence is elsewhere.** All of these systems **generate the subject inside the frame** and solve identity consistency by conditioning (multi-subject diffusion, identity injection, narrative-graph identifiers). Our background-only-plus-composited-card architecture is the outlier, and it is the direct cause of the empty prompts in Finding 1. We already have the field-standard path in-tree and live-validated: **Story 10.1c's recompose** (plate + cards + natural-language placement → one generated frame), which Epic 10's "⛳ 확정 방향" anchor already declares to be the destination.

---

## What this changes

| | Work | Basis |
|---|---|---|
| **Story 13.2 (do first)** | Replace the Likert axis with DSG-style proposition decomposition; drop person-propositions to remove the card-absence confound; wire the boolean `readable`. | DSG/TIFA/VQAScore; our own 12/66 and 11/66 measurements |
| **Story 10.4b** | Stop asking for an absence. `visual_breakdown` must never make emptiness the subject; a sentence with no renderable referent must not mint its own background. | negation literature; 12/66 unreadable, all with absence-as-subject prompts |
| **Epic 10 record** | Correct the Story 10.4 baseline provenance: 51 of the 66 scored frames are Story 10.1c's `recomposed/` re-creations (2026-08-09), not the frames Jay watched (2026-08-08). | found while auditing `baseline_v2.json` |

**Order matters and is not negotiable.** 13.2's instrument upgrade comes first. Running 10.4b against a score that clusters at 3 and docks frames for absent composited people would reproduce this exact round: a defensible change, an unmeasurable result, and another blocked story.

---

## Limits of this research

Desk research over published abstracts and papers; nothing here was reproduced locally. DSG's and VQAScore's reported correlations with human judgment are on general text-to-image benchmarks, **not** on Korean narration, not on horror/SCP material, and not on background plates whose subject is composited afterwards — the third of those is unusual enough that the metric's behaviour on our frames has to be measured, not assumed. The negation results are reported for object exclusion ("a room without a cat"); our case is the weaker cousin (an under-specified scene rather than an explicit exclusion), so the mechanism is a strong hypothesis rather than a demonstrated identity.

## Sources

- [NEGATE: Constrained Semantic Guidance for Linguistic Negation in Text-to-Video Diffusion](https://arxiv.org/pdf/2603.06533)
- [SpaceVLM: Sub-Space Modeling of Negation in Vision-Language Models](https://arxiv.org/pdf/2511.12331)
- [TIFA: Text-to-Image Faithfulness Evaluation with Question Answering](https://arxiv.org/abs/2303.11897) · [project page](https://tifa-benchmark.github.io/)
- [Davidsonian Scene Graph (ICLR 2024)](https://arxiv.org/pdf/2310.18235) · [OpenReview](https://openreview.net/forum?id=ITq4ZRUT4a) · [code](https://github.com/j-min/DSG)
- [VQAScore: Evaluating Text-to-Visual Generation with Image-to-Text Generation (ECCV 2024)](https://arxiv.org/abs/2404.01291) · [project page](https://linzhiqiu.github.io/papers/vqascore/)
- [What makes a good metric? Evaluating automatic metrics for text-to-image consistency](https://arxiv.org/pdf/2412.13989)
- [ViStoryBench](https://arxiv.org/html/2505.24862v3)
- [DreamStory](https://arxiv.org/html/2407.12899)
- [Dialogue Director](https://arxiv.org/html/2412.20725)
- [Narrative Graph Prompting (ICCVW 2025)](https://openaccess.thecvf.com/content/ICCV2025W/AISTORY/papers/Shin_Generating_Visually_Consistent_Images_for_Storytelling_via_Narrative_Graph_Prompting_ICCVW_2025_paper.pdf)
