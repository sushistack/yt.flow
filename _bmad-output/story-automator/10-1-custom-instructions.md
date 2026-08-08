STORY 10-1 ONLY. Do not start any other Epic 10 story (10-2 background depopulation, 10-3 LoRA, 10-4 semantic alignment, 10-5 pose, 10-6 cast, 10-7 sound). 11-6 is also FORBIDDEN.

NATURE OF THIS STORY (applies to create/dev/review sessions alike): the body of this work is NOT coding — it is rendering and then adjudicating paired frames. Code changes begin ONLY IF the comparison shows "enabled and still looks pasted-on". A dev session that starts writing code immediately is going the wrong way.

BACKGROUND: On 2026-08-08 Jay watched run 8a9a288b-800f-4c73-88a2-25ae6b5a4d7d (SCP-049) and reported "characters look torn out and pasted onto the background" and "characters float" (findings 3 and 11). But that run was rendered with depth_placement_enabled=false, so BOTH 8.16 ground placement AND 11.5 parallax were OFF (a previous session misdiagnosed the throughput bottleneck as depth; the real cause was the GPU DPM stuck at its lowest clock). So findings 3/11 are NOT evidence the feature is ineffective — they only establish that it was rendered with the feature off.

WHAT TO DO:
1. Restart the API with YTFLOW_DEPTH_PLACEMENT_ENABLED=true, then create a new run on the SAME SCP-049.
2. Run it to completion (auto-approve all 5 gates when the artifact sanity check passes).
3. Extract the SAME scene/shot frames from the new run and from the existing run 8a9a288b, and compare them SIDE BY SIDE as pairs.
4. Record the verdict: if it now looks grounded, close. If it still floats, determine at frame level which link is broken — ground line, card scale, contact shadow, or 8.7 harmonization. THAT is where the real story scope begins.
5. 8.16 passed its own gate at "tracking 3.9px vs static 57.2px". If the perceived result is unchanged despite that, it means the gate metric does not proxy perception — record that fact and feed it into story 13-2.

EXIT CRITERION (REVIEW SESSION MUST ENFORCE): Do NOT close this on passing tests or on code wiring. It closes ONLY when FRAME EVIDENCE (off/on pairs) is present in the story file. This is the Epic 10 common AC. It exists because the previous session closed Epic 8 stories while the video stayed the same and nobody could prove what had any effect. If visual adjudication is impossible, do NOT flip to done — escalate to Jay.

ENVIRONMENT (you WILL flounder without this):
- GPU DPM must be `high`. If `auto`, the clock sticks at 52MHz and generation goes from 15s to 500s. Check: cat /sys/class/drm/card*/device/power_dpm_force_performance_level (resets on reboot, needs root — escalate to Jay, do not try to set it yourself).
- ComfyUI cold start is about 8min30s; ~15-20s per generation once warm. WARNING: a stall threshold shorter than that KILLS A HEALTHY LOADING ComfyUI. Distinguish "wedged" from "slow" by completion history: journalctl --user -u ytflow-comfy | grep "Prompt executed".
- Services are systemd --user units: ytflow-api and ytflow-comfy.
- POST /runs/{id}/stages/{stage}/retry INVALIDATES that stage and everything downstream. Target the stage that actually failed — a previous session retried `image` for a `video` failure and destroyed 66 rendered images.
- Keep stock_plate_substitution_enabled = false (8.17 substitution collapsed background diversity 155 -> 41). Turning it on contaminates the comparison.
- Narration coming out at 2-3 minutes is caused by reasoning=low and belongs to Epic 12 — do NOT address it in this story.

REFERENCES:
- Comparison target: workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/ (66 images, video.mp4 3min06s)
- Older baseline: c6be1954-... (8min10s, 155 images)
- Full record of the previous session: _bmad-output/story-automator/orchestration-8-20260803-100738.md
