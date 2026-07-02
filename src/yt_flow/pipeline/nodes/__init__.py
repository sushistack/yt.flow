"""Stage node registry for the pipeline graph. [AD-4]"""

from typing import Any

from yt_flow.domain.state import StageName
from yt_flow.pipeline.nodes.image import image_node
from yt_flow.pipeline.nodes.scenario import scenario_node
from yt_flow.pipeline.nodes.subtitle import subtitle_node
from yt_flow.pipeline.nodes.tts import tts_node
from yt_flow.pipeline.nodes.video import video_node

STAGES: tuple[StageName, ...] = ("scenario", "image", "tts", "subtitle", "video")

STAGE_NODES: dict[StageName, Any] = {
    "scenario": scenario_node,
    "image": image_node,
    "tts": tts_node,
    "subtitle": subtitle_node,
    "video": video_node,
}
