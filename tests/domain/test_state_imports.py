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
        "camera_angle", "camera_movement", "image_path",
        "background_path", "character_path",
    },
    "SceneState": {
        "scene_num", "narration", "shots", "audio_path", "audio_duration",
        "word_timings", "subtitle_path",
    },
    "PipelineState": {
        "run_id", "scp_text", "scenes", "video_path", "current_stage",
        "gate_states", "prompt_variant", "error",
    },
}


def test_typeddicts_import():
    for name in ("PipelineState", "SceneState", "ShotData", "WordTiming"):
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
    # AD-1: api layer must never import from pipeline. Api is currently empty stubs;
    # test is wired now to catch future violations automatically.
    pkg = Path(state.__file__).resolve().parents[1]
    for py in (pkg / "api").rglob("*.py"):
        for mod in _yt_flow_imports(py):
            assert not mod.startswith("yt_flow.pipeline"), f"{py.name}: imports {mod}"
