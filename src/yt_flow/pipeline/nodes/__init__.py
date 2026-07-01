"""Stub stage nodes for Story 1.4.

Each stage node is a pure function of ``PipelineState`` that returns a partial
update setting ``current_stage``. No external calls (DeepSeek, ComfyUI, Qwen,
FFmpeg, Prompt Hub) and no DB/SSE/filesystem writes — real logic lands in
stories 1.5–1.9. [AD-4]
"""

from yt_flow.domain.state import PipelineState, StageName

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
video = _stub("video")

STAGE_NODES = {s: globals()[s] for s in STAGES}
