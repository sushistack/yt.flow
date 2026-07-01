"""Unit tests for src/yt_flow/pipeline/nodes/scenario.py (Story 1.5).

No live DeepSeek / Langfuse: the LLM call, prompt fetch, settings, and trace
sink are all monkeypatched. Tests assert the node's PipelineState contract
(scenes shape, error handling, purity) and observability boundary.
"""

import json

import pytest

# Import the submodule explicitly: nodes/__init__.py still binds a stub `scenario`
# attribute (Story 1.4), which `from ... import scenario` would return instead of
# this module. `import a.b.scenario as sc` always resolves to the module. [Story 1.5]
import yt_flow.pipeline.nodes.scenario as sc


# ── Fakes / helpers ─────────────────────────────────────────────────────────

class FakePrompt:
    def __init__(self, text="Write JSON for {{scp_text}}"):
        self.text = text
        self.compiled_with = None

    def compile(self, **variables):
        self.compiled_with = variables
        out = self.text
        for k, v in variables.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192


GOOD_PAYLOAD = {
    "scenes": [
        {
            "scene_num": 1,
            "narration": "격리 절차가 시작된다. 요원들이 진입한다.",
            "sentences": ["격리 절차가 시작된다.", "요원들이 진입한다."],
            "shots": [
                {
                    "shot_id": "S001",
                    "sentence_indices": [0],
                    "image_prompt": "a dark containment chamber, cinematic",
                    "negative_prompt": "blurry, text, watermark",
                    "camera_angle": "wide",
                    "camera_movement": "static",
                },
                {
                    "shot_id": "S002",
                    "sentence_indices": [0, 1],
                    "image_prompt": "armed agents entering",
                    "negative_prompt": "cartoon",
                    "camera_angle": None,
                    "camera_movement": None,
                },
            ],
        }
    ]
}


def _state(**over):
    base = {
        "run_id": "run-123",
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": [],
        "video_path": None,
        "current_stage": "",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Default wiring: fake prompt, fake settings, silent trace sink.

    Individual tests override ``_call_deepseek`` to supply a raw response.
    """
    prompt = FakePrompt()
    monkeypatch.setattr(sc, "get_prompt", lambda *a, **k: prompt)
    monkeypatch.setattr(sc, "_settings", lambda: FakeSettings())
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: None)
    return {"prompt": prompt}


def _mock_llm(monkeypatch, raw, usage=None, finish_reason="stop"):
    async def fake(rendered, settings):
        return raw, usage or {"prompt_tokens": 10, "completion_tokens": 20}, finish_reason
    monkeypatch.setattr(sc, "_call_deepseek", fake)


# ── AC1, AC2, AC6: successful parse ─────────────────────────────────────────

async def test_success_populates_scenes(monkeypatch):
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD))
    out = await sc.scenario_node(_state())

    assert out["current_stage"] == "scenario"  # AC5
    assert out.get("error") is None
    scenes = out["scenes"]
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["narration"]
    assert scene["audio_path"] is None and scene["word_timings"] == []
    shots = scene["shots"]
    assert len(shots) == 2
    # AC2: every shot has non-empty prompts + non-empty int indices
    for shot in shots:
        assert isinstance(shot["sentence_indices"], list) and shot["sentence_indices"]
        assert all(isinstance(i, int) for i in shot["sentence_indices"])
        assert shot["image_prompt"] and shot["negative_prompt"]
        assert shot["image_path"] is None
    # AC6: N:M mapping preserved (shot S002 maps two sentences)
    assert shots[1]["sentence_indices"] == [0, 1]


async def test_prompt_hub_is_used_with_scp_text(monkeypatch, _isolate):
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD))
    await sc.scenario_node(_state(scp_text="SCP-999"))
    # Prompt was fetched + compiled with scp_text (no hardcoded template path).
    assert _isolate["prompt"].compiled_with == {"scp_text": "SCP-999"}


async def test_input_state_not_mutated(monkeypatch):
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD))
    state = _state()
    snapshot = json.loads(json.dumps(state))
    await sc.scenario_node(state)
    assert state == snapshot  # AD-4 purity


# ── AC4: malformed / empty / truncated → error, no partial scenes ───────────

async def test_invalid_json_sets_error(monkeypatch):
    _mock_llm(monkeypatch, "not json at all {")
    out = await sc.scenario_node(_state())
    assert "scenes" not in out or out.get("scenes") in (None, [])
    assert out["error"] and "stage=scenario" in out["error"] and "run-123" in out["error"]
    assert out["current_stage"] == "scenario"


async def test_no_scenes_sets_error(monkeypatch):
    _mock_llm(monkeypatch, json.dumps({"scenes": []}))
    out = await sc.scenario_node(_state())
    assert out["error"] and "scenes" not in out


async def test_scene_without_shots_sets_error(monkeypatch):
    payload = {"scenes": [{"scene_num": 1, "narration": "x", "sentences": ["x"], "shots": []}]}
    _mock_llm(monkeypatch, json.dumps(payload))
    out = await sc.scenario_node(_state())
    assert out["error"]


async def test_empty_prompt_strings_set_error(monkeypatch):
    bad = json.loads(json.dumps(GOOD_PAYLOAD))
    bad["scenes"][0]["shots"][0]["image_prompt"] = ""
    _mock_llm(monkeypatch, json.dumps(bad))
    out = await sc.scenario_node(_state())
    assert out["error"]


async def test_truncated_response_sets_error(monkeypatch):
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD), finish_reason="length")
    out = await sc.scenario_node(_state())
    assert out["error"] and "truncat" in out["error"].lower()


@pytest.mark.parametrize("bad_indices", [[], [-1], [2], ["0"], "0"])
async def test_bad_sentence_indices_set_error(monkeypatch, bad_indices):
    bad = json.loads(json.dumps(GOOD_PAYLOAD))
    # scene has 2 sentences (valid indices 0,1); [2] is out of range.
    bad["scenes"][0]["shots"][0]["sentence_indices"] = bad_indices
    _mock_llm(monkeypatch, json.dumps(bad))
    out = await sc.scenario_node(_state())
    assert out["error"]


async def test_scene_num_is_positional_ignoring_llm_duplicates(monkeypatch):
    # Two scenes both claiming scene_num=1 must come out as unique 1,2 so downstream
    # file naming (scene_{n:03d}.wav / .png) can't silently overwrite. [review]
    bad = json.loads(json.dumps(GOOD_PAYLOAD))
    bad["scenes"].append(json.loads(json.dumps(GOOD_PAYLOAD["scenes"][0])))  # dup scene_num=1
    _mock_llm(monkeypatch, json.dumps(bad))
    out = await sc.scenario_node(_state())
    assert [s["scene_num"] for s in out["scenes"]] == [1, 2]


async def test_non_string_camera_fields_become_none(monkeypatch):
    bad = json.loads(json.dumps(GOOD_PAYLOAD))
    bad["scenes"][0]["shots"][0]["camera_angle"] = 42  # non-str from a misbehaving LLM
    _mock_llm(monkeypatch, json.dumps(bad))
    out = await sc.scenario_node(_state())
    assert out.get("error") is None
    assert out["scenes"][0]["shots"][0]["camera_angle"] is None  # normalized to str|None


async def test_prompt_fetch_failure_sets_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Langfuse prompt fetch failed: name='scenario'")
    monkeypatch.setattr(sc, "get_prompt", boom)
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD))
    out = await sc.scenario_node(_state())
    assert out["error"] and "stage=scenario" in out["error"]


# ── AC3: observability boundary ─────────────────────────────────────────────

async def test_trace_receives_prompt_response_usage(monkeypatch):
    captured = {}
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: captured.update(kw))
    _mock_llm(monkeypatch, json.dumps(GOOD_PAYLOAD), usage={"prompt_tokens": 7, "completion_tokens": 42})
    await sc.scenario_node(_state())
    assert captured["rendered"] and "SCP-173" in captured["rendered"]
    assert captured["raw"] and "S001" in captured["raw"]
    assert captured["usage"] == {"prompt_tokens": 7, "completion_tokens": 42}
    assert captured["model"] == "deepseek-v4-flash"
    assert isinstance(captured["latency_ms"], int)
    assert captured.get("error") is None


async def test_trace_captures_error_on_failure(monkeypatch):
    captured = {}
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: captured.update(kw))
    _mock_llm(monkeypatch, "broken")
    await sc.scenario_node(_state())
    assert captured.get("error") is not None  # AC4: span sees the exception


async def test_record_trace_is_non_fatal(monkeypatch):
    # AD-10: a Langfuse transport failure must not break the node.
    def boom(**kw):
        raise RuntimeError("langfuse down")
    monkeypatch.setattr(sc, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    # _record_trace swallows internally; calling it directly must not raise.
    sc._record_trace(rendered="p", raw="r", usage={}, model="m", latency_ms=1)
