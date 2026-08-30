"""Tests for scripts/seed_location_plates.py (Story 8.5 gates + Story 8.17 batch fixes).

Fully offline: the ComfyUI seam is faked in every test, so nothing here spends GPU.
Settings is pointed at a tmp DB, tmp assets root and tmp anchor dir via env overrides —
never the repo's own assets/, yt_flow.db or data/anchors/, which hold the real
curated library.
"""

import asyncio
import importlib.util
import io
import json
import struct
from pathlib import Path

import pytest
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import LocationPlate
from yt_flow.services.comfyui_client import ComfyUIError


# Anchor on this file, never on the CWD: pytest is run from worktrees and from
# the repo root alike, and `Settings().location_plate_workflow_path` is a
# repo-relative default. `tests/test_workflow_definitions.py` anchors the same way.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _plate_workflow_path() -> str:
    return str(_REPO_ROOT / Settings().location_plate_workflow_path)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "seed_location_plates", _REPO_ROOT / "scripts" / "seed_location_plates.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png(width: int, height: int) -> bytes:
    """A real PNG of the given size — PIL, the same library the upscale uses."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (32, 34, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _fake_plate(width: int = 1920, height: int = 1080, size: int = 4096) -> bytes:
    """Just enough PNG for ``_valid_plate``: signature, IHDR dimensions, and bulk."""
    head = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)
    return head + b"\x00" * (size - len(head))


def _dimensions(path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def _env(tmp_path, monkeypatch, *, mock=False, anchors=True, lookdev=True):
    """Point Settings at tmp everything and seed the anchor gate as requested."""
    assets = tmp_path / "assets"
    anchor_dir = tmp_path / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "workspace"))
    monkeypatch.setenv("YTFLOW_LOCATION_ANCHOR_DIR", str(anchor_dir))
    # Never the repo's own data/refs/: an absent dir is the blockout fallback, which is
    # the default these tests assume unless _write_ref puts one there.
    monkeypatch.setenv("YTFLOW_LOCATION_REFS_DIR", str(tmp_path / "refs"))
    monkeypatch.setenv("YTFLOW_COMFYUI_MOCK", "true" if mock else "false")
    if anchors:
        (anchor_dir / "anchor.png").write_bytes(_png(64, 64))
    if lookdev:
        (anchor_dir / "LOOKDEV_DECISION.md").write_text("chosen: candidate_2\n", encoding="utf-8")
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    return assets, anchor_dir


def _fake_comfy(monkeypatch, module, *, fail_on=(), image=None, uploads=None):
    """Replace the ComfyUI HTTP seam; returns the list of submitted workflows.

    ``fail_on`` holds 1-based submit call numbers that raise ComfyUIError — the shape
    a hipErrorIllegalAddress abort takes at this seam. ``uploads``, if given, collects
    ``(filename, bytes)`` for every upload so a test can prove which image was sent.
    """
    calls: list[dict] = []

    async def fake_submit(url, workflow):
        calls.append(workflow)
        if len(calls) in fail_on:
            raise ComfyUIError("hipErrorIllegalAddress (simulated)")
        return image if image is not None else _png(1344, 768)

    async def fake_upload(url, image_bytes, filename):
        if uploads is not None:
            uploads.append((filename, image_bytes))
        return filename

    monkeypatch.setattr(module.comfyui_client, "submit_and_fetch", fake_submit)
    monkeypatch.setattr(module.comfyui_client, "upload_image", fake_upload)
    return calls


def _write_ref(tmp_path, location_key, variant, colour=(11, 22, 33)):
    """Put a curated structure reference where ``_reference_path`` will find it."""
    from PIL import Image

    path = tmp_path / "refs" / location_key / f"ref_{variant}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1344, 768), colour).save(path, format="PNG")
    return path


def _reachable(workflow: dict, node_id: str, socket: str) -> set[str]:
    """Node ids reachable upstream from ``workflow[node_id]["inputs"][socket]``."""
    seen: set[str] = set()
    frontier = [workflow[node_id]["inputs"][socket]]
    while frontier:
        link = frontier.pop()
        if not (isinstance(link, list) and len(link) == 2 and isinstance(link[0], str)):
            continue
        upstream = link[0]
        if upstream in seen or upstream not in workflow:
            continue
        seen.add(upstream)
        frontier.extend(workflow[upstream]["inputs"].values())
    return seen


def _nodes(module) -> dict[str, str]:
    """manifest key -> node id, resolved from the shipped plate workflow the way
    the script itself resolves it (Story 13.3 — ids are no longer constants)."""
    return module._load_workflow(_plate_workflow_path())[1]


def _rows() -> list[LocationPlate]:
    with Session(db._engine) as session:
        return list(session.exec(select(LocationPlate)).all())


def _run(module, argv) -> int:
    return asyncio.run(module.run(module.build_parser().parse_args(argv)))


# ── Preflight gates (AC1: explain what is missing, spend no GPU) ──────────────

def test_missing_lookdev_decision_halts_before_any_submission(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, lookdev=False)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, [])

    assert "Lookdev decision not recorded" in str(exc.value)
    assert calls == []


def test_missing_anchor_image_halts_before_any_submission(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, anchors=False)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, [])

    assert "No anchor images found" in str(exc.value)
    assert calls == []


# ── _valid_plate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload,expected",
    [
        (_fake_plate(), True),
        (_fake_plate(width=1344, height=768), False),          # the render bucket, not the contract
        (_fake_plate(size=512), False),                        # a truncated/blank render
        (b"not a png at all" + b"\x00" * 2048, False),         # wrong signature
    ],
)
def test_valid_plate_enforces_the_on_disk_contract(tmp_path, payload, expected):
    seed = _load_script()
    path = tmp_path / "plate.png"
    path.write_bytes(payload)

    assert seed._valid_plate(path, mock=False) is expected


def test_valid_plate_is_false_for_a_missing_file(tmp_path):
    seed = _load_script()

    assert seed._valid_plate(tmp_path / "absent.png", mock=False) is False


def test_valid_plate_in_mock_mode_only_checks_the_signature(tmp_path):
    """Mock mode copies a tiny fixture, never a rendered plate."""
    seed = _load_script()
    path = tmp_path / "plate.png"
    path.write_bytes(_fake_plate(width=1, height=1, size=64))

    assert seed._valid_plate(path, mock=True) is True


# ── Seed determinism + reroll ────────────────────────────────────────────────

def test_plate_seed_is_salt_sensitive_and_collision_free():
    """The shipped little-endian truncation made the seed a function of the first four
    bytes only: "containment-chamber" and "control-room" collided, and an appended salt
    was discarded entirely."""
    seed = _load_script()

    assert seed._plate_seed("corridor", "a") == seed._plate_seed("corridor", "a")
    assert seed._plate_seed("corridor", "a") != seed._plate_seed("corridor", "b")
    assert seed._plate_seed("containment-chamber", "a") != seed._plate_seed("control-room", "a")
    assert seed._plate_seed("corridor", "a") != seed._plate_seed("corridor", "a", "deadbeef")
    assert seed._plate_seed("corridor", "a", "deadbeef") == seed._plate_seed("corridor", "a", "deadbeef")
    assert 0 <= seed._plate_seed("corridor", "a", "deadbeef") < 2**31


def test_reroll_produces_a_different_image_and_records_a_reproducible_salt(tmp_path, monkeypatch):
    seed = _load_script()
    nodes = _nodes(seed)
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    assert _run(seed, [*argv, "--reroll"]) == 0
    assert _run(seed, [*argv, "--reroll"]) == 0

    seeds = [call[nodes[seed.SAMPLER_KEY]]["inputs"]["seed"] for call in calls]
    assert len(set(seeds)) == 3, "a bare --reroll must draw a fresh salt every invocation"

    source = json.loads((assets / "manifest.json").read_text())["assets"]["corridor/a"]["source"]
    assert source["seed"] == seeds[-1]
    assert source["reroll_salt"]

    # The recorded salt is what makes a re-rolled keeper reproducible.
    assert _run(seed, [*argv, "--reroll", source["reroll_salt"]]) == 0
    assert calls[-1][nodes[seed.SAMPLER_KEY]]["inputs"]["seed"] == seeds[-1]


# ── Render bucket + upscale ──────────────────────────────────────────────────

def test_upscale_to_contract_yields_exactly_1920x1080(tmp_path):
    seed = _load_script()

    out = seed._upscale_to_contract(_png(seed.PLATE_RENDER_WIDTH, seed.PLATE_RENDER_HEIGHT))

    assert struct.unpack(">II", out[16:24]) == (1920, 1080)


def test_plate_renders_at_the_native_bucket_and_is_saved_at_the_contract(tmp_path, monkeypatch):
    seed = _load_script()
    nodes = _nodes(seed)
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)

    assert _run(seed, ["--key", "corridor", "--variant", "a"]) == 0

    latent = calls[0][nodes[seed.LATENT_KEY]]["inputs"]
    assert (latent["width"], latent["height"]) == (seed.PLATE_RENDER_WIDTH, seed.PLATE_RENDER_HEIGHT)
    assert _dimensions(assets / "locations" / "corridor" / "a.png") == (1920, 1080)


# ── Resume / skip / force ────────────────────────────────────────────────────

def test_an_existing_draft_with_a_file_is_not_regenerated(tmp_path, monkeypatch):
    """AC: after an abort, a re-run must continue rather than re-render the batch."""
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    assert _run(seed, argv) == 0

    assert len(calls) == 1
    assert len(_rows()) == 1


def test_a_draft_whose_file_vanished_is_regenerated(tmp_path, monkeypatch):
    seed = _load_script()
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    (assets / "locations" / "corridor" / "a.png").unlink()
    assert _run(seed, argv) == 0

    assert len(calls) == 2


def test_an_approved_plate_is_skipped_but_force_regenerates_it(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]
    assert _run(seed, argv) == 0
    with Session(db._engine) as session:
        plate = session.exec(select(LocationPlate)).one()
        plate.status = "approved"
        session.add(plate)
        session.commit()

    assert _run(seed, argv) == 0
    assert len(calls) == 1, "an approved plate must not be re-rendered"

    assert _run(seed, [*argv, "--force"]) == 0
    assert len(calls) == 2
    with Session(db._engine) as session:
        assert session.exec(select(LocationPlate)).one().status == "draft"


# ── Crash recovery (Story 5.23's loop, reused) ───────────────────────────────

def test_a_mid_batch_abort_recovers_and_continues_with_the_next_plate(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed, fail_on={2})
    recoveries = []

    async def fake_recovery(url, *, poll_sec, timeout_sec, shots_done, total_shots):
        recoveries.append((shots_done, total_shots))

    monkeypatch.setattr(seed, "_wait_for_comfyui_recovery", fake_recovery)

    assert _run(seed, ["--key", "corridor"]) == 0

    # Derived from VARIANTS, not pinned at 3: Story 14.1's shortfall batch added the
    # "d"/"e" viewpoint variants, and a test that hardcodes the count fails for a reason
    # that has nothing to do with what it is testing (abort recovery).
    n = len(seed.VARIANTS)
    assert len(calls) == n + 1, "every plate + one retry of the aborted submit"
    assert recoveries == [(1, n)]
    assert sorted(row.variant for row in _rows()) == sorted(seed.VARIANTS)


def test_an_exhausted_recovery_window_aborts_and_names_the_remaining_plates(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed, fail_on={2})

    async def never_recovers(url, **kwargs):
        raise ComfyUIError("ComfyUI unreachable")

    monkeypatch.setattr(seed, "_wait_for_comfyui_recovery", never_recovers)

    assert _run(seed, ["--key", "corridor"]) == 1

    out = capsys.readouterr().out
    assert "not generated: corridor b, corridor c" in out
    assert len(calls) == 2, "the batch must not keep submitting against a dead server"
    assert [row.variant for row in _rows()] == ["a"]


# ── Structure hint: curated reference vs procedural blockout ─────────────────

def test_a_curated_reference_is_used_as_the_controlnet_hint(tmp_path, monkeypatch):
    seed = _load_script()
    nodes = _nodes(seed)
    _env(tmp_path, monkeypatch)
    uploads: list[tuple[str, bytes]] = []
    calls = _fake_comfy(monkeypatch, seed, uploads=uploads)
    ref = _write_ref(tmp_path, "autopsy-room", "a")

    assert _run(seed, ["--key", "autopsy-room", "--variant", "a"]) == 0

    workflow = calls[0]
    assert workflow[nodes[seed.BLOCKOUT_KEY]]["inputs"]["image"] == "locref_autopsy-room_a.png"
    # The photo is preprocessed into line structure before it reaches the ControlNet.
    assert workflow[nodes[seed.SCRIBBLE_KEY]]["inputs"]["image"] == [nodes[seed.BLOCKOUT_KEY], 0]
    assert workflow[nodes[seed.CONTROLNET_APPLY_KEY]]["inputs"]["image"] == [nodes[seed.SCRIBBLE_KEY], 0]
    assert ("locref_autopsy-room_a.png", ref.read_bytes()) in uploads


def test_a_plate_without_a_reference_falls_back_to_the_procedural_blockout(tmp_path, monkeypatch):
    seed = _load_script()
    nodes = _nodes(seed)
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    # No reference at all for this key — only then is the empty blockout the best hint.
    assert _run(seed, ["--key", "corridor"]) == 0

    by_variant = {call[nodes[seed.BLOCKOUT_KEY]]["inputs"]["image"]: call for call in calls}
    assert set(by_variant) == {f"blockout_corridor_{v}.png" for v in seed.VARIANTS}
    # The blockout is already line art; passing it through scribble_hed would return each
    # stroke as a pair of thin parallel ones, so the fallback path drops the preprocessor.
    for workflow in by_variant.values():
        assert nodes[seed.SCRIBBLE_KEY] not in workflow
        assert workflow[nodes[seed.CONTROLNET_APPLY_KEY]]["inputs"]["image"] == [nodes[seed.BLOCKOUT_KEY], 0]
        assert workflow[nodes[seed.CONTROLNET_APPLY_KEY]]["inputs"]["strength"] == seed.BLOCKOUT_STRENGTH


def test_a_variant_without_its_own_reference_borrows_a_sibling_not_the_blockout(tmp_path, monkeypatch):
    """Curation rarely fills all three slots, and the keys that got one reference rendered
    variant `a` with furniture and `b`/`c` as bare boxes. Another photo of the right room
    beats an empty box: the seed and the variant's camera wording still differ."""
    seed = _load_script()
    nodes = _nodes(seed)
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    _write_ref(tmp_path, "corridor", "a")  # only variant a is curated

    assert _run(seed, ["--key", "corridor"]) == 0

    # The upload is named per plate, not per source file, so the tell is which path ran:
    # every variant went through the photo path (preprocessor present, full strength) and
    # none fell back to the blockout.
    used = {call[nodes[seed.BLOCKOUT_KEY]]["inputs"]["image"] for call in calls}
    assert used == {f"locref_corridor_{v}.png" for v in seed.VARIANTS}
    for call in calls:
        assert nodes[seed.SCRIBBLE_KEY] in call
        assert call[nodes[seed.CONTROLNET_APPLY_KEY]]["inputs"]["strength"] != seed.BLOCKOUT_STRENGTH


def test_the_reference_never_reaches_the_ipadapter_or_the_latent(tmp_path, monkeypatch):
    """COPYRIGHT GUARD. A downloaded photograph may only ever reach the model as a
    preprocessed structure map. If it were wired into the IPAdapter it would transfer the
    photo's style, and into a latent it would be img2img — both reproduce the original.
    This asserts on the workflow that is actually submitted, not on intent."""
    seed = _load_script()
    nodes = _nodes(seed)
    _, anchor_dir = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    _write_ref(tmp_path, "cafeteria", "b")

    assert _run(seed, ["--key", "cafeteria", "--variant", "b"]) == 0

    workflow = calls[0]
    assert workflow[nodes[seed.BLOCKOUT_KEY]]["inputs"]["image"] == "locref_cafeteria_b.png"

    # The IPAdapter's image input resolves to the style-anchor LoadImage chain only.
    upstream = _reachable(workflow, nodes[seed.IPADAPTER_KEY], "image")
    assert nodes[seed.BLOCKOUT_KEY] not in upstream
    assert nodes[seed.SCRIBBLE_KEY] not in upstream
    # Constructed, never prefix-matched: `_inject_anchors` derives its ids as
    # f"{anchor_id}_extra_{i}" / f"{anchor_id}_batch_{i}", and `startswith("2")`
    # for an anchor resolved to "2" would admit node "23" — the IPAdapter itself,
    # which is what this assertion is supposed to be excluding.
    anchor_id = nodes[seed.ANCHOR_KEY]
    anchor_count = len(list(anchor_dir.glob("*.png")))
    derived = {anchor_id} | {
        f"{anchor_id}_{kind}_{i}" for kind in ("extra", "batch") for i in range(1, anchor_count)
    }
    assert upstream <= derived

    # The sampler starts from noise: an EmptyLatentImage, with nothing upstream of it.
    assert workflow[nodes[seed.SAMPLER_KEY]]["inputs"]["latent_image"] == [nodes[seed.LATENT_KEY], 0]
    assert workflow[nodes[seed.LATENT_KEY]]["class_type"] == "EmptyLatentImage"
    assert _reachable(workflow, nodes[seed.SAMPLER_KEY], "latent_image") == {nodes[seed.LATENT_KEY]}
    assert not any(
        node["class_type"] in ("VAEEncode", "VAEEncodeForInpaint", "ImageScaleToTotalPixels")
        for node in workflow.values()
    ), "an encode node is how a reference photo becomes an img2img latent"

    # The only node holding the uploaded filename is the structure-hint LoadImage.
    holders = [nid for nid, node in workflow.items() if node["inputs"].get("image") == "locref_cafeteria_b.png"]
    assert holders == [nodes[seed.BLOCKOUT_KEY]]


# ── Anchor candidates ────────────────────────────────────────────────────────

def test_anchor_candidates_render_unconditioned_and_touch_no_library_state(tmp_path, monkeypatch):
    seed = _load_script()
    nodes = _nodes(seed)
    assets, _ = _env(tmp_path, monkeypatch, anchors=False, lookdev=False)
    calls = _fake_comfy(monkeypatch, seed)

    assert _run(seed, ["--anchor-candidates", "3"]) == 0

    review_dir = tmp_path / "workspace" / "location-anchor-candidates"
    assert sorted(p.name for p in review_dir.glob("*.png")) == [
        "candidate_1.png", "candidate_2.png", "candidate_3.png",
    ]
    assert len(calls) == 3
    assert len({call[nodes[seed.SAMPLER_KEY]]["inputs"]["seed"] for call in calls}) == 3
    for call in calls:
        # No anchor exists yet, so the candidate cannot be style-anchored to one.
        assert nodes[seed.ANCHOR_KEY] not in call and nodes[seed.IPADAPTER_KEY] not in call
        assert not any("IPAdapter" in node.get("class_type", "") for node in call.values())
        assert call[nodes[seed.SAMPLER_KEY]]["inputs"]["model"] == [nodes[seed.MODEL_KEY], 0]
        # Dropping every LoadImage used to leave ControlNetApplyAdvanced pointing at a
        # node that no longer existed — a dangling link ComfyUI rejects outright.
        assert nodes[seed.CONTROLNET_APPLY_KEY] not in call and nodes[seed.SCRIBBLE_KEY] not in call
        assert call[nodes[seed.SAMPLER_KEY]]["inputs"]["positive"] == [nodes[seed.POSITIVE_KEY], 0]
        assert call[nodes[seed.SAMPLER_KEY]]["inputs"]["negative"] == [nodes[seed.NEGATIVE_KEY], 0]
        assert all(
            isinstance(value, str) or value[0] in call
            for node in call.values() for value in node["inputs"].values()
            if not isinstance(value, (str, int, float, bool))
        ), "no dangling links"
    # Candidates are review material, not library assets.
    assert not (assets / "manifest.json").exists()
    assert _rows() == []


def test_anchor_candidates_are_refused_in_mock_mode(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, mock=True)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, ["--anchor-candidates", "2"])

    assert "--anchor-candidates" in str(exc.value)
    assert calls == []


def test_prompts_cover_every_location_key():
    """LOCATION_PROMPTS is the batch's only prompt source; a missing key is a KeyError
    mid-batch, after GPU has already been spent on the earlier ones."""
    seed = _load_script()
    settings = Settings()

    assert set(seed.LOCATION_PROMPTS) == set(seed.LOCATION_KEYS)
    assert seed.ANCHOR_CANDIDATE_KEY in seed.LOCATION_PROMPTS
    assert settings.location_plate_workflow_path.endswith(".json")


# ── Node resolution by title (Story 13.3) ────────────────────────────────────

def _renumber(workflow: dict, offset: int = 500) -> dict:
    """What the ComfyUI UI does on copy/paste + re-export: every id changes,
    every link follows. The manifest titles are the only stable handles left."""
    remap = {nid: str(int(nid) + offset) for nid in workflow}

    def relink(value):
        if isinstance(value, list) and len(value) == 2 and str(value[0]) in remap:
            return [remap[str(value[0])], value[1]]
        return value

    return {
        remap[nid]: {**node, "inputs": {k: relink(v) for k, v in node["inputs"].items()}}
        for nid, node in workflow.items()
    }


def test_a_renumbered_workflow_still_resolves_and_rewires(tmp_path, monkeypatch):
    """The failure Story 13.3 removes: with ids hardcoded, a renumber produced a
    structurally valid but WRONG graph, because three of the writes are links."""
    seed = _load_script()
    path = tmp_path / "renumbered.json"
    original = json.loads(Path(_plate_workflow_path()).read_text(encoding="utf-8"))
    path.write_text(json.dumps(_renumber(original)), encoding="utf-8")

    workflow, nodes = seed._load_workflow(str(path))
    assert sorted(nodes) == sorted(seed.PLATE_NODE_KEYS)
    assert all(int(nid) >= 500 for nid in nodes.values())

    injected = seed._inject(workflow, nodes, "a corridor", 42, 0.5)
    assert injected[nodes[seed.POSITIVE_KEY]]["inputs"]["text"] == "a corridor"
    assert injected[nodes[seed.SAMPLER_KEY]]["inputs"]["seed"] == 42

    # the link rewrites — the half a node-id constant silently corrupts
    seed._bypass_scribble(injected, nodes)
    assert injected[nodes[seed.CONTROLNET_APPLY_KEY]]["inputs"]["image"] == [nodes[seed.BLOCKOUT_KEY], 0]
    assert nodes[seed.SCRIBBLE_KEY] not in injected

    stripped = seed._strip_ipadapter(injected, nodes)
    assert stripped[nodes[seed.SAMPLER_KEY]]["inputs"]["model"] == [nodes[seed.MODEL_KEY], 0]
    assert stripped[nodes[seed.SAMPLER_KEY]]["inputs"]["positive"] == [nodes[seed.POSITIVE_KEY], 0]


def test_load_workflow_reports_a_renamed_node(tmp_path):
    """AC1: the error names the key and lists what the file actually declares."""
    seed = _load_script()
    original = json.loads(Path(_plate_workflow_path()).read_text(encoding="utf-8"))
    for node in original.values():
        if node.get("_meta", {}).get("title") == seed.SAMPLER_KEY:
            node["_meta"]["title"] = "KSampler"
    path = tmp_path / "renamed.json"
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        seed._load_workflow(str(path))
    assert seed.SAMPLER_KEY in str(exc.value)
    assert seed.POSITIVE_KEY in str(exc.value)  # ...among the titles present


def test_two_swapped_titles_are_rejected_at_load(tmp_path):
    """Resolving eleven titles proves they are DECLARED, not that they sit on the
    right nodes. Swap two in the UI and every lookup still succeeds, the seed is
    written into an EmptyLatentImage, the sampler never gets it and `--reroll`
    silently no-ops — the structurally-valid-but-wrong graph this story removes.
    """
    seed = _load_script()
    original = json.loads(Path(_plate_workflow_path()).read_text(encoding="utf-8"))
    swap = {seed.SAMPLER_KEY: seed.LATENT_KEY, seed.LATENT_KEY: seed.SAMPLER_KEY}
    for node in original.values():
        title = node.get("_meta", {}).get("title")
        if title in swap:
            node["_meta"]["title"] = swap[title]
    path = tmp_path / "swapped.json"
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        seed._load_workflow(str(path))
    assert "KSampler" in str(exc.value) or "EmptyLatentImage" in str(exc.value)


def test_every_manifest_key_declares_the_class_it_must_be(tmp_path):
    """...and the expectation table covers all eleven, so no key is unguarded."""
    seed = _load_script()
    assert tuple(seed.PLATE_NODE_CLASSES) == seed.PLATE_NODE_KEYS
    workflow, nodes = seed._load_workflow(_plate_workflow_path())
    for key, expected in seed.PLATE_NODE_CLASSES.items():
        assert workflow[nodes[key]]["class_type"] in expected
