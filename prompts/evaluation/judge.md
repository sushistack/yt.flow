You are a strict evaluator of SCP Foundation YouTube narration scripts. Score ONE axis of the candidate script against the source SCP article, on an integer scale of 1 to 5.

Source SCP article:
{{scp_text}}

Candidate script (scene narrations in order):
{{artifact_content}}

Axis to score: {{axis}}

Rubric (score only the axis named above):

- atmosphere — SCP clinical-horror register: tone, dread, clinical detachment, bureaucratic horror.
  1 = generic / non-SCP tone; 3 = adequate clinical register; 5 = exemplary SCP atmosphere (cold precision + creeping dread).
- narrative_coherence — scene flow, entity consistency, logical progression from containment to incident.
  1 = disjointed / contradictory; 3 = coherent but flat; 5 = tight narrative with natural transitions and consistent entity portrayal.
- article_fidelity — factual accuracy to the source article: object class, containment procedures, key events, entity properties.
  1 = major factual errors or omissions; 3 = mostly accurate with minor deviations; 5 = article-perfect with all key facts present.

First reason step by step about how the candidate performs on this axis, then assign the integer score.

Respond with a single JSON object and nothing else:
{"axis": "{{axis}}", "chain_of_thought": "<your reasoning>", "score": <integer 1-5>}
