"""Stage node registry for the pipeline graph.

Stubs (stories 1.4) remain for scenario/image/tts/subtitle until their stories
land. video_node is real as of Story 1.9. [AD-4]
"""

from typing import Any

from yt_flow.domain.state import PipelineState, StageName
from yt_flow.pipeline.nodes.video import video_node

STAGES: tuple[StageName, ...] = ("scenario", "image", "tts", "subtitle", "video")


def _stub(stage: StageName):
    def node(state: PipelineState) -> dict:
        # ponytail: stub only marks progress; return a partial update, never mutate `state`.
        return {"current_stage": stage}

    node.__name__ = stage
    return node


scenario = _stub("scenario")
image = _stub("image")
tts = _stub("tts")
subtitle = _stub("subtitle")

STAGE_NODES: dict[StageName, Any] = {
    "scenario": scenario,
    "image": image,
    "tts": tts,
    "subtitle": subtitle,
    "video": video_node,
}
