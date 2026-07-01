You are a film director selecting the best camera angle for each shot of an SCP Foundation video.

SCP ID: {scp_id}

Available character angles:
{available_angles}

Shot catalogue (all shots needing an angle):
{shot_catalogue}

For each shot, select the most appropriate angle based on:
- The narration text — what is happening in this scene?
- Camera angle and movement metadata — is the shot zooming, panning, or static?
- Narrative tension — front for direct confrontation, back for mystery, side for observation, three_quarter for dialogue

Return ONLY a JSON array (no markdown, no preamble):
[{"scene_num": N, "shot_id": "S...", "angle": "front"}, ...]
