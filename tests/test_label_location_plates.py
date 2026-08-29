"""Tests for scripts/label_location_plates.py (Story 8.17 auto-labeler).

Fully offline: the DashScope vision call is faked at the httpx seam. Auto-approval is
publishing (only approved plates reach a render), so every non-pass path is asserted to
leave the plate draft — not merely to print something.
"""

import asyncio
import importlib.util
import io
import json
import types

import pytest
from sqlmodel import Session

import httpx
from yt_flow import db
from yt_flow.config import Settings
from yt_flow.services.asset_service import AssetService

CLEAR_PASS = {
    "matches_location": True,
    "has_person": False,
    "depicts_person": False,
    "has_legible_text": False,
    "has_duplicated_architecture": False,
    "quality": "good",
    "confidence": 0.93,
    "notes": "clean utilitarian corridor",
}


def _load_script():
    spec = importlib.util.spec_from_file_location("label_location_plates", "scripts/label_location_plates.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (32, 34, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _env(tmp_path, monkeypatch, *, api_key="test-key", plates=(("corridor", "a"),)):
    """Point Settings at a tmp DB + assets root and seed draft plates with manifest entries."""
    assets = tmp_path / "assets"
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    monkeypatch.setenv("YTFLOW_CHARACTER_VISION_API_KEY", api_key)
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db._engine) as session:
        asset_service = AssetService(assets, session)
        for location_key, variant in plates:
            rel = f"locations/{location_key}/{variant}.png"
            (assets / rel).parent.mkdir(parents=True, exist_ok=True)
            (assets / rel).write_bytes(_png())
            asset_service.add_location_plate(location_key, variant, rel)
    return assets


def _fake_httpx(module, monkeypatch, *, reply=None, error=None):
    """Replace the module's httpx with a one-response stand-in; returns sent payloads."""
    payloads: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": reply}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            payloads.append(json)
            if error is not None:
                raise error
            return FakeResponse()

    monkeypatch.setattr(
        module, "httpx",
        types.SimpleNamespace(AsyncClient=lambda **kwargs: FakeClient(), Timeout=lambda value: value),
    )
    return payloads


def _run(module, argv=()) -> int:
    return asyncio.run(module.run(module.build_parser().parse_args(list(argv))))


def _plate(assets, tmp_path, location_key="corridor", variant="a"):
    from yt_flow.services.location_service import LocationService

    settings = Settings(assets_path=str(assets))
    with Session(db._engine) as session:
        matches = [
            p for p in LocationService(session, settings=settings).list_plates(location_key=location_key)
            if p.variant == variant
        ]
        return matches[0]


def _manifest_source(assets, location_key="corridor", variant="a") -> dict:
    return json.loads((assets / "manifest.json").read_text())["assets"][f"{location_key}/{variant}"]["source"]


def _manifest_status(assets, location_key="corridor", variant="a") -> str:
    return json.loads((assets / "manifest.json").read_text())["assets"][f"{location_key}/{variant}"]["status"]


# ── Decision rule ────────────────────────────────────────────────────────────

def test_a_clear_pass_is_approved_and_the_verdict_justifies_it(tmp_path, monkeypatch):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    payloads = _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))

    assert _run(label) == 0

    assert _plate(assets, tmp_path).status == "approved"
    assert _manifest_status(assets) == "approved"
    recorded = _manifest_source(assets)["label"]
    assert recorded["decision"] == "approved"
    assert recorded["confidence"] == 0.93
    # The plate's own description is what the model was asked to grade against.
    assert "utilitarian facility corridor" in payloads[0]["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize(
    "override,expected_reason",
    [
        ({"quality": "acceptable"}, "quality='acceptable'"),
        ({"confidence": 0.4}, "confidence=0.4"),
        ({"matches_location": False}, "matches_location=False"),
        ({"has_legible_text": True}, "has_legible_text=True"),
        ({"has_duplicated_architecture": True}, "has_duplicated_architecture=True"),
        ({"quality": None}, "quality=None"),
        ({"confidence": True}, "confidence=True not a number"),
        ({"has_person": "no"}, "has_person='no' not boolean"),
        # Story 14.1, handed over from 14.4: a person INSIDE a picture/monitor/statue.
        # An approval criterion, not a runtime guard — and a missing field is a fail,
        # never a pass, exactly like the four axes above it.
        ({"depicts_person": True}, "depicts_person=True"),
    ],
)
def test_anything_short_of_a_clear_pass_stays_draft(tmp_path, monkeypatch, capsys, override, expected_reason):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    verdict = {**CLEAR_PASS, **override}
    _fake_httpx(label, monkeypatch, reply=json.dumps(verdict))

    assert _run(label) == 0

    assert _plate(assets, tmp_path).status == "draft"
    assert _manifest_status(assets) == "draft"
    # The verdict is recorded either way — that is what the operator reviews against.
    assert _manifest_source(assets)["label"]["decision"] == "draft"
    out = capsys.readouterr().out
    assert expected_reason in out
    assert "operator queue: corridor a" in out


def test_a_detected_person_is_never_approved_however_confident(tmp_path, monkeypatch):
    """D11-class defect: a figure in the plate disqualifies it outright."""
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    _fake_httpx(label, monkeypatch, reply=json.dumps({**CLEAR_PASS, "has_person": True, "confidence": 1.0}))

    assert _run(label) == 0

    assert _plate(assets, tmp_path).status == "draft"
    assert _manifest_source(assets)["label"]["has_person"] is True


# ── Failure paths ────────────────────────────────────────────────────────────

def test_a_non_json_reply_leaves_the_plate_draft(tmp_path, monkeypatch, capsys):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    _fake_httpx(label, monkeypatch, reply="Sure! This looks like a great corridor to me.")

    assert _run(label) == 1

    assert _plate(assets, tmp_path).status == "draft"
    assert "label" not in _manifest_source(assets)
    assert "operator queue: corridor a" in capsys.readouterr().out


def test_a_scorer_http_failure_leaves_the_plate_draft(tmp_path, monkeypatch):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    _fake_httpx(label, monkeypatch, error=httpx.ConnectError("dashscope unreachable"))

    assert _run(label) == 1

    assert _plate(assets, tmp_path).status == "draft"
    assert "label" not in _manifest_source(assets)


def test_a_missing_image_file_leaves_the_plate_draft(tmp_path, monkeypatch):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    (assets / "locations" / "corridor" / "a.png").unlink()
    _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))

    assert _run(label) == 1

    assert _plate(assets, tmp_path).status == "draft"


def test_a_missing_api_key_halts_before_touching_anything(tmp_path, monkeypatch):
    label = _load_script()
    _env(tmp_path, monkeypatch, api_key="")

    with pytest.raises(SystemExit) as exc:
        _run(label)

    assert "CHARACTER_VISION_API_KEY" in str(exc.value)


def test_no_draft_plates_is_a_no_op(tmp_path, monkeypatch, capsys):
    label = _load_script()
    _env(tmp_path, monkeypatch, plates=())
    payloads = _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))

    assert _run(label) == 0

    assert payloads == []
    assert "no draft plates" in capsys.readouterr().out


# ── Reply parsing ────────────────────────────────────────────────────────────

def test_fenced_or_prefaced_json_is_still_parsed():
    """Qwen-VL wraps JSON in ``` fences or prefaces it with prose."""
    label = _load_script()
    body = json.dumps(CLEAR_PASS)

    for reply in (f"```json\n{body}\n```", f"Here is my verdict:\n{body}\nHope that helps!"):
        assert label._parse_verdict(reply)["quality"] == "good"

    for reply in ("", "no json here", "{not json}"):
        with pytest.raises(ValueError):
            label._parse_verdict(reply)


def test_only_one_key_is_labelled_when_key_is_given(tmp_path, monkeypatch):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch, plates=(("corridor", "a"), ("office", "a")))
    _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))

    assert _run(label, ["--key", "corridor"]) == 0

    assert _plate(assets, tmp_path, "corridor").status == "approved"
    assert _plate(assets, tmp_path, "office").status == "draft"


# ── Story 14.1: depicts_person + a pinned temperature ────────────────────────


def test_the_request_pins_temperature_zero(tmp_path, monkeypatch):
    """A curation verdict that cannot be re-derived cannot be recorded as a measurement,
    and this script's output is now the input to a plate's shipped metadata."""
    label = _load_script()
    _env(tmp_path, monkeypatch)
    payloads = _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))
    assert _run(label) == 0
    assert payloads[0]["temperature"] == 0


def test_depicts_person_is_asked_for_separately_from_has_person(tmp_path, monkeypatch):
    """The two questions must stay apart: `vision_check.CHECK_PROMPT` answers "is a body in
    the room" correctly, and merging the picture case into it re-muddies a question that is
    already right (14.4's rejected guard extension)."""
    label = _load_script()
    _env(tmp_path, monkeypatch)
    payloads = _fake_httpx(label, monkeypatch, reply=json.dumps(CLEAR_PASS))
    assert _run(label) == 0
    prompt = payloads[0]["messages"][0]["content"][0]["text"]
    assert "depicts_person" in prompt
    assert label.REQUIRED_BOOLS["depicts_person"] is False
    assert label.REQUIRED_BOOLS["has_person"] is False


def test_a_depicted_person_leaves_the_plate_draft_and_records_the_verdict(tmp_path, monkeypatch):
    label = _load_script()
    assets = _env(tmp_path, monkeypatch)
    _fake_httpx(label, monkeypatch, reply=json.dumps({**CLEAR_PASS, "depicts_person": True}))
    assert _run(label) == 0
    assert _plate(assets, tmp_path).status == "draft"
    assert _manifest_source(assets)["label"]["depicts_person"] is True
