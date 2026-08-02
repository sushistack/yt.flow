"""Tests for scripts/fetch_location_refs.py (Story 8.17 structure references).

Fully offline: DuckDuckGo, the downloader and the DashScope vision call are all faked,
so nothing here touches the network. Keeping a candidate writes a third-party photo into
the repo, so every non-pass path is asserted to leave *no file behind*, not merely to
print something.
"""

import asyncio
import importlib.util
import io
import json

import pytest

CLEAR_KEEP = {
    "matches_location": True,
    "has_person": False,
    "has_watermark_or_text": False,
    "matches_shot_type": True,
    "confidence": 0.91,
    "notes": "empty hospital autopsy suite, oblique view",
}


def _load_script():
    spec = importlib.util.spec_from_file_location("fetch_location_refs", "scripts/fetch_location_refs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _jpg(width: int = 800, height: int = 600) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 92, 96)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _env(tmp_path, monkeypatch, *, api_key="test-key"):
    refs = tmp_path / "refs"
    monkeypatch.setenv("YTFLOW_LOCATION_REFS_DIR", str(refs))
    monkeypatch.setenv("YTFLOW_CHARACTER_VISION_API_KEY", api_key)
    return refs


def _fake_search(module, monkeypatch, results):
    """Replace DuckDuckGoImageSearch with a canned result list; returns the queries sent."""
    queries: list[str] = []

    class FakeSearch:
        async def search(self, query, max_results=10):
            queries.append(query)
            if isinstance(results, Exception):
                raise results
            return results[:max_results]

    monkeypatch.setattr(module, "DuckDuckGoImageSearch", FakeSearch)
    return queries


def _fake_download(module, monkeypatch, *, fail_on=()):
    """Replace the SSRF-hardened downloader; writes a real JPEG into the staging dir."""
    downloaded: list[str] = []

    async def fake(url, refs_dir, num):
        downloaded.append(url)
        if url in fail_on:
            raise ValueError("Blocked private IP: 127.0.0.1")
        (refs_dir / f"ref_{num}.jpg").write_bytes(_jpg())
        return "jpg"

    monkeypatch.setattr(module.CharacterService, "_download_reference_image", fake)
    return downloaded


def _fake_vision(module, monkeypatch, *, replies=None, error=None):
    """Replace the module's httpx with a scripted stand-in; returns sent payloads."""
    payloads: list[dict] = []
    queue = list(replies or [])

    class FakeResponse:
        def __init__(self, reply):
            self._reply = reply

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self._reply}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            payloads.append(json)
            if error is not None:
                raise error
            return FakeResponse(queue.pop(0) if queue else "{}")

    monkeypatch.setattr(
        module, "httpx",
        type("FakeHttpx", (), {"AsyncClient": lambda **kw: FakeClient(), "Timeout": lambda *a, **k: None}),
    )
    return payloads


def _result(url, title="candidate"):
    return {"url": url, "thumbnail_url": f"{url}?t", "title": title}


def _run(module, argv) -> int:
    return asyncio.run(module.run(module.build_parser().parse_args(argv)))


# ── Queries ──────────────────────────────────────────────────────────────────

def test_queries_cover_every_key_and_never_say_scp():
    """"SCP" / "SCP Foundation" returns fan art, wiki logos and cosplay — and it is the
    same attractor that poisoned the character cards. The point is a real room."""
    fetch = _load_script()

    assert set(fetch.REF_QUERIES) == set(fetch.LOCATION_KEYS)
    for key, query in fetch.REF_QUERIES.items():
        assert "scp" not in query.lower(), key
        assert query.strip() == query and query


# ── Curation decision rule ───────────────────────────────────────────────────

def test_a_clean_candidate_is_kept_with_its_provenance(tmp_path, monkeypatch, capsys):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    queries = _fake_search(fetch, monkeypatch, [_result("https://example.com/morgue.jpg", "morgue")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)])

    assert _run(fetch, ["--key", "autopsy-room"]) == 0

    assert queries == [fetch.REF_QUERIES["autopsy-room"]]
    kept = refs / "autopsy-room" / "ref_a.png"
    assert kept.is_file()
    record = json.loads((refs / "autopsy-room" / "refs.json").read_text())
    assert record["refs"]["a"]["url"] == "https://example.com/morgue.jpg"
    assert record["refs"]["a"]["verdict"] == CLEAR_KEEP
    assert record["query"] == fetch.REF_QUERIES["autopsy-room"]
    assert "kept: autopsy-room a" in capsys.readouterr().out


@pytest.mark.parametrize(
    "defect,field",
    [
        ({"has_person": True}, "has_person"),
        ({"has_watermark_or_text": True}, "has_watermark_or_text"),
        ({"matches_location": False}, "matches_location"),
        ({"matches_shot_type": False}, "matches_shot_type"),
        ({"confidence": 0.4}, "confidence"),
        ({"has_person": "no"}, "has_person"),          # non-boolean is a reject, not a pass
        ({"matches_location": None}, "matches_location"),
    ],
)
def test_a_defective_candidate_is_rejected_and_written_nowhere(tmp_path, monkeypatch, defect, field):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/bad.jpg")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=[json.dumps({**CLEAR_KEEP, **defect})])

    assert _run(fetch, ["--key", "corridor"]) == 1

    assert list((refs / "corridor").glob("ref_*.png")) == []
    record = json.loads((refs / "corridor" / "refs.json").read_text())
    assert record["refs"] == {}
    assert field in record["rejected"][0]["reason"]


def test_a_missing_field_is_a_reject(tmp_path, monkeypatch):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/partial.jpg")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=['{"matches_location": true, "confidence": 0.99}'])

    assert _run(fetch, ["--key", "office"]) == 1
    assert list((refs / "office").glob("ref_*.png")) == []


def test_a_scorer_failure_rejects_rather_than_accepts(tmp_path, monkeypatch, capsys):
    """The failure mode that matters: a dead vision endpoint must not silently publish
    every downloaded photo into the repo."""
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/a.jpg"), _result("https://example.com/b.jpg")])
    _fake_vision(fetch, monkeypatch, error=RuntimeError("dashscope 503"))
    _fake_download(fetch, monkeypatch)

    assert _run(fetch, ["--key", "cafeteria"]) == 1

    assert list((refs / "cafeteria").glob("ref_*.png")) == []
    assert "scorer failed" in capsys.readouterr().out


def test_an_unparsable_reply_rejects(tmp_path, monkeypatch):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/chatty.jpg")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=["Sure! Here is my assessment of the photograph."])

    assert _run(fetch, ["--key", "medical-bay"]) == 1
    assert list((refs / "medical-bay").glob("ref_*.png")) == []


def test_a_download_failure_is_recorded_and_the_next_candidate_still_runs(tmp_path, monkeypatch):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://10.0.0.1/x.jpg"), _result("https://example.com/ok.jpg")])
    _fake_download(fetch, monkeypatch, fail_on={"https://10.0.0.1/x.jpg"})
    _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)])

    assert _run(fetch, ["--key", "server-room"]) == 0

    record = json.loads((refs / "server-room" / "refs.json").read_text())
    assert record["refs"]["a"]["url"] == "https://example.com/ok.jpg"
    assert "download" in record["rejected"][0]["reason"]


# ── Batch shape ──────────────────────────────────────────────────────────────

def test_at_most_one_reference_per_variant_is_kept(tmp_path, monkeypatch):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result(f"https://example.com/{i}.jpg") for i in range(6)])
    downloaded = _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)] * 6)

    assert _run(fetch, ["--key", "control-room"]) == 0

    assert sorted(p.name for p in (refs / "control-room").glob("ref_*.png")) == [
        "ref_a.png", "ref_b.png", "ref_c.png",
    ]
    assert len(downloaded) == 3, "screening must stop once all three variants are filled"


def test_max_candidates_bounds_the_search(tmp_path, monkeypatch):
    fetch = _load_script()
    _env(tmp_path, monkeypatch)
    seen: list[int] = []

    class FakeSearch:
        async def search(self, query, max_results=10):
            seen.append(max_results)
            return []

    monkeypatch.setattr(fetch, "DuckDuckGoImageSearch", FakeSearch)

    assert _run(fetch, ["--key", "corridor", "--max-candidates", "2"]) == 1
    assert seen == [2]


def test_a_curated_key_is_skipped_unless_forced(tmp_path, monkeypatch):
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    (refs / "office").mkdir(parents=True)
    for variant in fetch.VARIANTS:
        (refs / "office" / f"ref_{variant}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    queries = _fake_search(fetch, monkeypatch, [_result("https://example.com/a.jpg")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)] * 3)

    assert _run(fetch, ["--key", "office"]) == 0
    assert queries == [], "a complete key must not re-spend search and vision calls"

    assert _run(fetch, ["--key", "office", "--force"]) == 0
    assert queries == [fetch.REF_QUERIES["office"]]


def test_a_search_failure_fails_only_that_key(tmp_path, monkeypatch, capsys):
    fetch = _load_script()
    _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, RuntimeError("VQD acquisition failed"))

    assert _run(fetch, ["--key", "corridor"]) == 1
    assert "failed (search: VQD acquisition failed)" in capsys.readouterr().out


def test_a_missing_vision_key_halts_before_any_network_call(tmp_path, monkeypatch):
    fetch = _load_script()
    _env(tmp_path, monkeypatch, api_key="")
    queries = _fake_search(fetch, monkeypatch, [_result("https://example.com/a.jpg")])

    with pytest.raises(SystemExit) as exc:
        _run(fetch, ["--key", "corridor"])

    assert "CHARACTER_VISION_API_KEY" in str(exc.value)
    assert queries == []


# ── Written form ─────────────────────────────────────────────────────────────

def test_a_kept_reference_is_normalised_to_the_render_bucket(tmp_path, monkeypatch):
    """The on-disk file is what ComfyUI will center-crop and rescale anyway; doing it
    here makes the reference an honest record of what the sampler saw."""
    fetch = _load_script()
    refs = _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/tall.jpg")])
    _fake_download(fetch, monkeypatch)
    _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)])

    assert _run(fetch, ["--key", "storage-vault"]) == 0

    from PIL import Image

    with Image.open(refs / "storage-vault" / "ref_a.png") as im:
        assert im.size == (fetch.PLATE_RENDER_WIDTH, fetch.PLATE_RENDER_HEIGHT)
        assert im.format == "PNG"


def test_the_exterior_key_is_screened_as_an_exterior(tmp_path, monkeypatch):
    fetch = _load_script()
    _env(tmp_path, monkeypatch)
    _fake_search(fetch, monkeypatch, [_result("https://example.com/site.jpg")])
    _fake_download(fetch, monkeypatch)
    payloads = _fake_vision(fetch, monkeypatch, replies=[json.dumps(CLEAR_KEEP)])

    assert _run(fetch, ["--key", "facility-exterior"]) == 0

    sent = payloads[0]["messages"][0]["content"][0]["text"]
    assert fetch.EXTERIOR_SHOT in sent and fetch.INTERIOR_SHOT not in sent
