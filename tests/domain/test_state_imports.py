"""Scaffold guards for story 1.2: domain types import, shapes are stable,
required directories exist, and the domain layer imports nothing from above.
"""

import ast
from pathlib import Path
from typing import get_type_hints

import yt_flow.domain.state as state

# Exact field sets from the Architecture domain contract. If a field is renamed
# or dropped, get_type_hints keys diverge and this test fails fast.
EXPECTED_FIELDS = {
    "WordTiming": {"word", "start_sec", "end_sec"},
    "ShotData": {
        "shot_id", "sentence_indices", "image_prompt", "negative_prompt",
        "camera_angle", "camera_movement", "image_path", "cast", "location_key",
        "depth_map_path",  # Story 11.5 — NotRequired, so pre-11.5 checkpoints still load
    },
    "CastMember": {
        "card_key", "position", "depth", "pose", "pose_hint", "pose_guide_key",
        "motion_style", "motion_energy",
        "movement_mode", "movement_direction", "movement_pace",
        "ground_y", "occlusion_mask",
    },
    "SceneState": {
        "scene_num", "narration", "shots", "audio_path", "audio_duration",
        "word_timings", "subtitle_path", "mood", "title", "kicker", "display_narration",
    },
    "SearchResult": {"url", "thumbnail_url", "title"},
    "ReferenceImage": {"id", "character_id", "url", "local_path", "width", "height", "created_at"},
    "Character": {
        "id", "scp_id", "canonical_name", "aliases",
        "visual_descriptor", "style_guide", "image_prompt_base",
        "selected_image_path",
        "angle_front_path", "angle_back_path", "angle_side_path", "angle_three_quarter_path",
        "created_at", "updated_at",
    },
    "CharacterCandidate": {
        "id", "character_id", "scp_id", "angle", "candidate_num",
        "status", "image_path", "created_at", "updated_at",
    },
    "PipelineState": {
        "run_id", "scp_id", "scp_text", "scenes", "video_path", "current_stage",
        "gate_states", "prompt_variant", "error", "ending_credit_error",
        "scenario_quality",  # Story 12.3 — NotRequired, so pre-12.3 checkpoints still load
    },
    # Story 12.3 quality contract — checkpoint- AND interrupt-serialized, so its shape
    # is as much a compatibility surface as PipelineState's.
    "RuleCounts": {
        "character_count", "sentence_count", "duplicate_sentence_count", "repeated_4gram_count",
    },
    "SceneRuleCounts": {
        "scene_num",
        "character_count", "sentence_count", "duplicate_sentence_count", "repeated_4gram_count",
    },
    "RepeatedPhrase": {"phrase", "count"},
    "SlopPhraseHit": {"scene_num", "phrase", "count"},
    "RuleMetrics": {
        "aggregate", "scenes", "repeated_ngrams", "slop_phrase_hits", "slop_vocabulary_version",
    },
    "GroundedContradiction": {
        "scene_num", "narration_quote", "grounding_source", "grounding_quote",
        "explanation", "correction",
    },
    "ReviewIssue": {"scene_num", "type", "severity", "description", "correction"},
    "ScenarioWarning": {"code", "message"},
    "ScenarioQuality": {
        "final_pass_index", "retry_scope", "review_overall_pass", "critic_verdict",
        "critic_feedback", "rule_metrics", "grounded_contradictions", "review_issues",
        "warning",
    },
}


def test_typeddicts_import():
    for name in ("PipelineState", "SceneState", "ShotData", "WordTiming",
                  "SearchResult", "ReferenceImage", "Character", "CharacterCandidate", "AngleName",
                  "CastMember", "ScenarioQuality", "RuleMetrics", "GroundedContradiction"):
        assert hasattr(state, name), name


def test_type_hint_shapes():
    for name, fields in EXPECTED_FIELDS.items():
        hints = get_type_hints(getattr(state, name))
        assert set(hints) == fields, f"{name} fields drifted: {set(hints)}"


def test_required_directories_exist():
    pkg = Path(state.__file__).resolve().parents[1]  # .../src/yt_flow
    for sub in ("domain", "pipeline", "pipeline/nodes", "services", "db", "api", "api/routes"):
        assert (pkg / sub).is_dir(), sub


def _yt_flow_imports(path: Path) -> list[str]:
    mods = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("yt_flow"):
                mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods += [a.name for a in node.names if a.name.startswith("yt_flow")]
    return mods


def test_domain_imports_no_project_layers():
    tree = ast.parse(Path(state.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("yt_flow"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("yt_flow"), alias.name


def test_pipeline_imports_no_db():
    # AD-1: pipeline layer must never import from db. Activated now that pipeline
    # has real code (stories 1.5-1.7). [see deferred-work.md]
    pkg = Path(state.__file__).resolve().parents[1]
    for py in (pkg / "pipeline").rglob("*.py"):
        for mod in _yt_flow_imports(py):
            assert not mod.startswith("yt_flow.db"), f"{py.name}: imports {mod}"


def test_api_imports_no_pipeline():
    # AD-1: api layer must never import from pipeline. Exception: api/main.py
    # imports `inject_cast_resolver` from pipeline.nodes.video — the sole AD-1
    # injection point for the cast card resolver service (Story 1.13, reworked
    # in Story 8.3) — and `inject_location_service` from pipeline.nodes.image
    # (Story 8.5), the equivalent seam for the location plate resolver.
    pkg = Path(state.__file__).resolve().parents[1]
    allowed = {"yt_flow.pipeline.nodes.video", "yt_flow.pipeline.nodes.image"}
    for py in (pkg / "api").rglob("*.py"):
        for mod in _yt_flow_imports(py):
            if py.name == "main.py" and mod in allowed:
                continue  # allowed: injection seam
            assert not mod.startswith("yt_flow.pipeline"), f"{py.name}: imports {mod}"


# The pipeline→services crossings that predate the rule being enforced, each a
# stateless client rather than a db/session-holding service: the two Langfuse prompt
# fetches and the ComfyUI HTTP client. Anything NEW belongs behind an inject_* seam
# (Story 8.16's ground/relight resolvers are the model), which is what this list is
# for — it must not grow.
_LEGACY_PIPELINE_SERVICE_IMPORTS = {
    ("scenario.py", "yt_flow.services.prompt_service"),
    ("scenario_chain.py", "yt_flow.services"),
    ("image.py", "yt_flow.services"),
    ("image.py", "yt_flow.services.comfyui_client"),
}


def test_pipeline_imports_no_services():
    # AD-1: pipeline layer must never import from services or api. Story 8.16 builds its
    # ground-plane and relight crossings on that rule (inject_ground_resolver /
    # inject_relight_resolver), and until now only pipeline↛db and api↛pipeline were
    # enforced — this third seam was convention alone.
    pkg = Path(state.__file__).resolve().parents[1]
    for py in (pkg / "pipeline").rglob("*.py"):
        for mod in _yt_flow_imports(py):
            if (py.name, mod) in _LEGACY_PIPELINE_SERVICE_IMPORTS:
                continue
            assert not mod.startswith("yt_flow.services"), f"{py.name}: imports {mod}"
            assert not mod.startswith("yt_flow.api"), f"{py.name}: imports {mod}"
