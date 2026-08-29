"""Tests for recompose_service (Story 10.1c close-out).

The prompt/workflow half is covered by tests/pipeline/nodes/test_shot_recompose.py; what
this half owns is the *state edit* it makes to the graph — which shots get their frame
replaced, and what has to be taken away from them at the same time.
"""

import hashlib
import json
import os
import struct
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from yt_flow.pipeline.nodes.shot_recompose import placement_instruction
from yt_flow.services import recompose_service
from yt_flow.services.recompose_service import CARD_LOOKS, recompose_run_shots

# Only `dimensions()` inspects the bytes, and it reads the IHDR alone.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 8, 8)
RECOMPOSED = PNG + b"recomposed"


# A server started the way Story 10.1d's preflight requires: every flag present and RAM
# well clear of the floor. `_StubClient` answers this unless a test overrides it, so the
# tests that are about the shot loop never have to think about the preflight.
PASSING_STATS = {
    "system": {
        "argv": ["main.py", "--lowvram", "--cache-lru", "10"],
        "ram_free": 20 * 2**30,
        "ram_total": 31 * 2**30,
    },
}


class _StubClient:
    """Duck-typed stand-in for services.comfyui_client (the module, not a class)."""

    def __init__(self, result: bytes | None = RECOMPOSED, stats: dict | None = PASSING_STATS):
        self.result = result
        self.stats = stats
        self.uploads: list[str] = []
        self.submits = 0
        self.stats_urls: list[str] = []

    async def get_system_stats(self, url):
        self.stats_urls.append(url)
        return self.stats

    async def upload_image(self, url, data, name):
        self.uploads.append(name)
        return name

    async def submit_and_fetch(self, url, workflow):
        self.submits += 1
        return self.result


def _workflow(tmp_path: Path) -> str:
    p = tmp_path / "wf.json"
    p.write_text(json.dumps({
        "ytflow_verified_recompose_qwen": True,
        "plate": {"class_type": "LoadImage", "inputs": {"image": "p.png"}},
        "card_a": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "card_b": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
        "positive": {"class_type": "TextEncodeQwenImageEditPlus",
                     "inputs": {"prompt": "x", "image1": ["plate", 0],
                                "image2": ["card_a", 0], "image3": ["card_b", 0]}},
    }))
    return str(p)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One run dir with a plate, a depth map and a card, plus the stub client wired in."""
    images = tmp_path / "run" / "images"
    images.mkdir(parents=True)
    plate = images / "S001.png"
    plate.write_bytes(PNG + b"plate")
    depth = images / "S001_depth.png"
    depth.write_bytes(PNG + b"depth")
    card = tmp_path / "card.png"
    card.write_bytes(PNG + b"card")

    client = _StubClient()
    monkeypatch.setattr(recompose_service, "comfyui_client", client)
    scenes = [{"scene_num": 1, "shots": [
        {"shot_id": "S001", "image_path": str(plate), "depth_map_path": str(depth)},
    ]}]
    cast = {"1:S001": [{"path": str(card), "card_key": "SCP-049",
                        "position": "left", "depth": "mid"}]}
    settings = SimpleNamespace(
        workspace_path=str(tmp_path), comfyui_url="http://stub",
        shot_recompose_workflow_path=_workflow(tmp_path),
        recompose_preflight_min_free_ram_gb=12.0,
    )
    return SimpleNamespace(
        scenes=scenes, cast=cast, settings=settings, client=client,
        shot=scenes[0]["shots"][0], plate=plate, depth=depth, tmp_path=tmp_path,
    )


async def test_recomposed_shot_swaps_the_frame_and_drops_the_stale_depth_map(env):
    """The frame is new; the depth map still describes the empty plate.

    Keeping it would warp the characters the model just drew against their own
    background. parallax_service degrades to NO_DEPTH, which is recorded, so dropping
    the key is a visible downgrade rather than a silent wrong render.
    """
    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] != str(env.plate)
    assert Path(env.shot["image_path"]).read_bytes() == RECOMPOSED
    assert "depth_map_path" not in env.shot
    assert remaining == {}          # nothing left to overlay onto the new frame
    assert stats == {"recomposed": 1, "skipped": 0, "reentered": 0, "failed": 0,
                     "attributed": 0}


async def test_recomposed_frame_lands_beside_the_run_that_owns_it(env):
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    assert Path(env.shot["image_path"]).parent == env.tmp_path / "run" / "recomposed"


async def test_cached_frame_is_reused_without_a_second_render(env):
    """Content-addressed by plate+cards+instructions: the same plate must not re-render.

    The shot is reset to the plate on purpose — this covers the cache, not re-entry.
    The state the pipeline actually presents on a video retry is the next test.
    """
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    first = env.shot["image_path"]
    env.shot["image_path"] = str(env.plate)
    env.shot["depth_map_path"] = str(env.depth)

    await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert env.shot["image_path"] == first
    assert env.client.submits == 1


async def test_rerunning_over_an_already_recomposed_shot_is_a_no_op(env):
    """The video stage is retryable and the frame swap is in place, so the second run
    sees a "plate" that already contains the characters. Recomposing it again would
    insert every figure a second time, and the run-dir derivation would miss besides.
    """
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    recomposed = env.shot["image_path"]

    remaining, stats = await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert env.shot["image_path"] == recomposed   # untouched
    assert env.client.submits == 1                # no second render
    assert remaining == {}                        # still nothing to overlay
    # `reentered`, not `skipped`: the shot is recomposed, it just was not recomposed HERE.
    assert stats == {"recomposed": 0, "skipped": 0, "reentered": 1, "failed": 0,
                     "attributed": 0}


async def test_write_failure_leaves_the_shot_renderable(env, monkeypatch):
    """ENOSPC mid-loop must not escape: the caller's blanket except would keep the
    original cast_cards while the shots already swapped have the characters baked in.
    """
    def boom(self, *a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", boom)

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 0, "reentered": 0, "failed": 1,
                     "attributed": 0}


async def test_undescribed_card_leaves_the_shot_on_the_overlay_path(env):
    """No entry in CARD_LOOKS means no way to name the figure in the instruction.

    The shot must stay fully intact — depth map included — because the overlay path is
    what will render it, and 11.5 parallax needs that map.
    """
    env.cast["1:S001"][0]["card_key"] = "STOCK-nobody"

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 1, "reentered": 0, "failed": 0,
                     "attributed": 0}
    assert env.client.submits == 0


async def test_unreadable_plate_leaves_the_shot_on_the_overlay_path(env):
    env.shot["image_path"] = str(env.tmp_path / "run" / "images" / "gone.png")

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats["skipped"] == 1


async def test_failed_render_keeps_both_paths_and_the_cards(env, monkeypatch):
    """A ComfyUI failure is non-fatal, so the shot must be left renderable as it was."""
    monkeypatch.setattr(recompose_service, "comfyui_client", _StubClient(result=None))

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 0, "reentered": 0, "failed": 1,
                     "attributed": 0}


# ── Story 10.1d: runtime-prerequisite preflight ──────────────────────────────
# A RUN-level refusal, not the per-shot skips above: a misconfigured ComfyUI is wrong for
# every shot, so the whole cast map comes back untouched and nothing is submitted. The
# eight tests above all pass this gate via `_StubClient`'s PASSING_STATS default, which is
# the point — the loop's own behaviour must not have changed.


async def test_a_satisfied_preflight_is_invisible(env):
    """The shipped-good case: no bail keys, and the loop ran exactly as before."""
    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats == {"recomposed": 1, "skipped": 0, "reentered": 0, "failed": 0,
                     "attributed": 0}
    assert env.client.submits == 1


@pytest.mark.parametrize("flag", ["--lowvram", "--cache-lru"])
async def test_each_missing_flag_is_named_alone(env, flag):
    """One absent flag must accuse itself and nothing else — a message that over-reports
    sends the operator to restart with settings that were already correct."""
    argv = [a for a in PASSING_STATS["system"]["argv"] if a != flag]
    env.client.stats = {"system": {**PASSING_STATS["system"], "argv": argv}}

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "missing_flags"
    detail = stats["preflight_detail"]
    assert detail.splitlines()[0] == (
        f"Shot recompose preflight failed: ComfyUI is missing {flag}.")
    # The operator must be able to act on this line alone: what was observed, what to add.
    assert f"observed argv: {argv}" in detail
    # ADD, not replace: run.sh carries the venv activation and the ROCm gfx override, and
    # an operator who pastes a bare `python main.py …` over it loses both.
    assert ("add to ComfyUI's launcher (e.g. run.sh) and restart: "
            "--lowvram --cache-lru 10") in detail
    assert remaining == env.cast
    assert env.client.submits == 0


@pytest.mark.parametrize("argv_tail", [
    ["--cache-lru", "0"],       # ComfyUI's own default: main.py enables LRU only when > 0
    ["--cache-lru=0"],
    ["--cache-lru", "-1"],
    ["--cache-lru", "auto"],    # unparseable — argparse would have refused it, but ask
    ["--cache-lru"],            # value swallowed by the end of argv
])
async def test_a_value_taking_flag_present_but_inert_counts_as_missing(env, argv_tail):
    """`--cache-lru 0` IS the eviction behaviour the flag exists to prevent (490 s/shot),
    so presence alone must not satisfy the gate — the operator has to hear the value."""
    env.client.stats = {"system": {**PASSING_STATS["system"],
                                   "argv": ["main.py", "--lowvram", *argv_tail]}}

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "missing_flags"
    assert "--cache-lru is present but set to" in stats["preflight_detail"]
    assert "which is the same as not passing it" in stats["preflight_detail"]
    assert remaining == env.cast
    assert env.client.submits == 0


async def test_missing_flags_are_reported_even_when_the_ram_reading_is_unreadable(env):
    """Flags are the half the operator can act on. Bailing `stats_unreadable` first told a
    doubly-broken box only about the field it can do nothing about."""
    env.client.stats = {"system": {"argv": ["main.py"], "ram_free": "?"}}

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "missing_flags"
    assert "missing --lowvram, --cache-lru" in stats["preflight_detail"]
    assert "free RAM:" not in stats["preflight_detail"]   # nothing readable to report


async def test_ram_total_absent_degrades_to_the_free_only_form(env):
    """`ram_total` is decoration — the floor is compared against `ram_free` alone, so a
    payload without it must still bail (or pass) on the reading that matters."""
    env.client.stats = {"system": {"argv": PASSING_STATS["system"]["argv"],
                                   "ram_free": int(1.2 * 2**30)}}

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "low_ram"
    assert "1.2 GiB free (threshold 12.0)" in stats["preflight_detail"]

    env.client.stats = {"system": {"argv": PASSING_STATS["system"]["argv"],
                                   "ram_free": 20 * 2**30, "ram_total": "lots"}}
    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)
    assert "preflight_failed" not in stats


async def test_the_preflight_asks_the_configured_server(env):
    """The RUNNING server is the only argv that decides the outcome, and it may be on
    another host — reading our own Settings/.env instead would answer the wrong question."""
    await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.client.stats_urls == [env.settings.comfyui_url]


async def test_a_flag_written_with_an_equals_sign_still_counts(env):
    """`--cache-lru=10` is what argparse accepts too; telling an operator who wrote the
    working spelling that it is missing would send them to fix a non-problem."""
    env.client.stats = {"system": {**PASSING_STATS["system"],
                                   "argv": ["main.py", "--lowvram", "--cache-lru=10"]}}

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert "preflight_failed" not in stats


async def test_low_free_ram_bails_and_states_the_measurement(env):
    """The reading and the threshold both go in the message: 1.2 GB free means something
    else on the box has to be stopped, which no restart command can say on its own."""
    env.client.stats = {"system": {**PASSING_STATS["system"],
                                   "ram_free": int(1.2 * 2**30), "ram_total": 31 * 2**30}}

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "low_ram"
    # GiB, because that is what the reading was divided by and what `free` reports.
    assert "1.2 / 31.0 GiB (threshold 12.0)" in stats["preflight_detail"]
    assert remaining == env.cast
    assert env.client.submits == 0


async def test_an_unanswered_server_bails_rather_than_assuming_the_best(env):
    """`get_system_stats` is best-effort and answers None for every failure [AD-10]. A
    misconfigured server is indistinguishable from a healthy one without the answer, so
    "could not ask" is not "prerequisites met"."""
    env.client.stats = None

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "stats_unavailable"
    assert "did not answer /system_stats" in stats["preflight_detail"]
    assert remaining == env.cast
    assert env.client.submits == 0


# The `ram_free` rows carry a PASSING argv on purpose: flags are compared first now, so an
# argv of `["main.py"]` would bail `missing_flags` and never reach the RAM read.
@pytest.mark.parametrize("payload, field", [
    ({}, "'system'"),
    ({"system": []}, "'system'"),
    ({"system": {"argv": "x"}}, "'system.argv'"),
    ({"system": {"argv": PASSING_STATS["system"]["argv"], "ram_total": 31 * 2**30}},
     "'system.ram_free'"),
    ({"system": {"argv": PASSING_STATS["system"]["argv"], "ram_free": True}},
     "'system.ram_free'"),
])
async def test_an_unreadable_payload_names_the_field_and_never_raises(env, payload, field):
    """`/system_stats`' shape differs across ComfyUI versions — that is the reason to read
    it at all — so every unexpected shape must produce a named bail, not a TypeError out
    of a path whose whole job is to keep the run rendering."""
    env.client.stats = payload

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "stats_unreadable"
    assert field in stats["preflight_detail"]
    assert remaining == env.cast
    assert env.client.submits == 0


async def test_a_bailed_run_leaves_every_shot_on_the_overlay_path(env):
    """The whole point of a run-level bail: the shots must be exactly as renderable as if
    the feature flag were off — frame, depth map (11.5 parallax needs it) and cards."""
    env.client.stats = {"system": {**PASSING_STATS["system"], "argv": ["main.py"]}}

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats["recomposed"] == stats["skipped"] == stats["failed"] == 0
    assert env.client.submits == 0


async def test_a_forbidden_flag_is_refused_even_though_every_required_flag_is_present(env):
    """`--disable-smart-memory` left REQUIRED_FLAGS in 10.1e; a launcher that still passes it
    would otherwise sail through into the state that was measured at 385-677 s/pass against
    108 without it. Slowness is the only symptom, so nothing downstream would surface it."""
    env.client.stats = {"system": {**PASSING_STATS["system"],
                                   "argv": [*PASSING_STATS["system"]["argv"],
                                            "--disable-smart-memory"]}}

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "forbidden_flags"
    assert "--disable-smart-memory" in stats["preflight_detail"]
    assert remaining == env.cast
    assert env.client.submits == 0


async def test_a_forbidden_flag_beats_a_missing_one_in_the_message(env):
    """Checked first on purpose: a missing flag announces itself as an error, a forbidden one
    only as a slow run, so it must not be masked by the louder failure."""
    env.client.stats = {"system": {**PASSING_STATS["system"],
                                   "argv": ["main.py", "--disable-smart-memory"]}}

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["preflight_failed"] == "forbidden_flags"


# ── Story 14.3: attribution ──────────────────────────────────────────────────
# Before this story a recomposed frame's only trace on disk was the 16-hex digest in its
# filename, which hashes the plate bytes, the card paths and the placement strings
# together and is not invertible. Nothing said which workflow or which instruction drew
# it, so no later GPU session could attribute a before/after pair to anything.

SIDECAR_BASE = "scene_001_S001"


def _sidecar(env, base: str = SIDECAR_BASE, **extra) -> Path:
    """The completion sentinel image_node would have left beside the plate."""
    path = env.plate.parent / f"{base}_done.json"
    path.write_text(json.dumps({
        "image_prompt": "a dark room", "negative_prompt": "blurry", "seed": 7,
        "provenance": {"workflow_sha256": "plate-graph"}, "recompose": None, **extra,
    }), encoding="utf-8")
    return path


def _block(sidecar: Path) -> dict:
    return json.loads(sidecar.read_text(encoding="utf-8"))["recompose"]


async def test_a_recomposed_shot_records_what_drew_it(env):
    sidecar = _sidecar(env)
    env.cast["1:S001"].append({
        "path": str(env.tmp_path / "card.png"), "card_key": "STOCK-d-class",
        "position": "right", "depth": "far", "pose": "kneeling",
    })

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats == {"recomposed": 1, "skipped": 0, "reentered": 0, "failed": 0,
                     "attributed": 1}
    block = _block(sidecar)
    assert block["source"] == "rendered"
    assert block["workflow_sha256"] == hashlib.sha256(
        Path(env.settings.shot_recompose_workflow_path).read_bytes()).hexdigest()
    assert block["output_path"] == env.shot["image_path"]
    # Pass order, not cast order: `order_cast` inserts the far figure first so the
    # nearer one is drawn over it, and the record has to match what was submitted.
    assert [(p["depth"], p["position"], p["pose"]) for p in block["passes"]] == [
        ("far", "right", "kneeling"), ("mid", "left", None),
    ]


async def test_the_recompose_block_does_not_disturb_the_three_compared_keys(env):
    """Additive and uncompared — the invariant every cached shot depends on."""
    sidecar = _sidecar(env)
    before = json.loads(sidecar.read_text(encoding="utf-8"))

    await recompose_run_shots(env.scenes, env.cast, env.settings)

    after = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {k: after[k] for k in ("image_prompt", "negative_prompt", "seed")} == \
           {k: before[k] for k in ("image_prompt", "negative_prompt", "seed")}
    assert after["provenance"] == before["provenance"]


async def test_a_cache_hit_does_not_restamp_the_frame_it_did_not_draw(env):
    """The digest covers the plate, the card paths and the placement strings — NOT the
    workflow or the instruction text. So a cached frame may have been drawn by an older
    graph, and writing today's sha onto it attributes the frame to a workflow that never
    rendered it. Preserve, do not re-stamp."""
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    first = _block(sidecar)
    env.shot["image_path"] = str(env.plate)

    await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert _block(sidecar) == first
    assert env.client.submits == 1


async def test_a_cache_hit_fills_in_an_attribution_that_is_missing(env):
    """The other half: preserving an existing block must not become "never write on a
    cache hit", or a shot whose first stamp failed stays un-attributed forever."""
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    _sidecar(env)                      # as if the first stamp had never landed
    env.shot["image_path"] = str(env.plate)

    await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    block = _block(sidecar)
    assert block["source"] == "cache"
    # Null, not the current sha: this pass did not draw the frame.
    assert block["workflow_sha256"] is None
    assert block["digest"] == Path(env.shot["image_path"]).stem.rsplit("_", 1)[-1]


async def test_reentry_over_an_already_recomposed_shot_still_records_the_attribution(env):
    """Re-entry counts as `skipped`, which used to `continue` before anything was
    recorded — so a shot whose stamp failed lost even its warning on the retry. That is
    the silence this story exists to remove, reintroduced by this story."""
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    _sidecar(env)                      # attribution lost; shot still points at the frame

    _, stats = await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    # `reentered`, NOT `skipped`: this shot IS recomposed, and every reader of `skipped`
    # (the degraded warning's copy, the run trace) means "not recomposed" by it.
    assert stats["reentered"] == 1
    assert stats["skipped"] == 0
    assert _block(sidecar)["source"] == "cache"


async def test_a_shot_with_no_sidecar_is_not_an_attribution_failure(env):
    """A plate with no completion sentinel was not written by image_node (mock fixtures,
    hand-placed plates), so there is no record to annotate. ponytail: no synthesis — a
    sidecar without `image_prompt` would sit in front of the resume check."""
    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    # `attributed` is 0, not 1: there was no sidecar to stamp. That gap is exactly what
    # the counter exists to make visible — `recomposed` alone cannot be read as coverage.
    assert stats == {"recomposed": 1, "skipped": 0, "reentered": 0, "failed": 0,
                     "attributed": 0}
    assert not list(env.plate.parent.glob("*_done.json"))


@pytest.mark.parametrize("payload", ["not json at all", "[1, 2, 3]", '"a string"'])
async def test_an_unusable_sidecar_warns_instead_of_failing_the_shot(env, payload):
    """JSON someone may have edited: a list where a dict belongs raises TypeError, torn
    bytes raise ValueError. Attribution never fails the run. [AD-10]"""
    sidecar = env.plate.parent / f"{SIDECAR_BASE}_done.json"
    sidecar.write_text(payload, encoding="utf-8")

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["recomposed"] == 1                    # the frame still shipped
    assert Path(env.shot["image_path"]).read_bytes() == RECOMPOSED
    assert [(w["scene_num"], w["shot_id"]) for w in stats["warnings"]] == [(1, "S001")]
    assert stats["attributed"] == 0


async def test_a_failed_stamp_warns_again_on_the_next_pass(env, monkeypatch):
    """Not "warned once, then quiet": the operator has to be able to see it on the run
    they are actually looking at."""
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    _sidecar(env)
    env.shot["image_path"] = str(env.plate)

    def boom(self, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", boom)

    _, stats = await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert [(w["scene_num"], w["shot_id"]) for w in stats["warnings"]] == [(1, "S001")]
    assert "OSError" in stats["warnings"][0]["detail"]
    assert json.loads(sidecar.read_text(encoding="utf-8"))["recompose"] is None


async def test_a_clean_run_reports_no_warnings_key_at_all(env):
    """Absent, not empty: `stats` is what video_node reads and what the log line prints,
    and an always-present empty list makes a clean run look like it had something to say."""
    _sidecar(env)

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert "warnings" not in stats


async def test_the_stamp_is_atomic(env, monkeypatch):
    """The sidecar carries `image_prompt` and `seed`. A torn write makes
    `_existing_complete_shot` miss and re-renders the shot on the next resume — spending
    a GPU pass to record that a GPU pass happened."""
    sidecar = _sidecar(env)
    seen = []
    real_replace = Path.replace

    def watched(self, target):
        seen.append((self.name, Path(target).name))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", watched)

    await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert (f"{sidecar.name}.tmp", sidecar.name) in seen
    assert not list(sidecar.parent.glob("*.tmp"))


# ── Story 14.3 review patches ────────────────────────────────────────────────


async def test_the_block_hashes_the_instruction_text_not_just_its_inputs(env):
    """`workflow_sha256` covers the graph and `digest` covers the placement FIELDS —
    neither covers the Python that turns `depth="near"` into a sentence. The next fix
    queued in this area edits `_DEPTH_PHRASE["near"]`, after which every block written
    on either side of it still says `depth: "near"` and reconstructs to different text.
    """
    sidecar = _sidecar(env)

    await recompose_run_shots(env.scenes, env.cast, env.settings)

    card = env.cast["1:S001"][0]
    assert _block(sidecar)["instruction_sha256"] == hashlib.sha256(
        placement_instruction(
            CARD_LOOKS[card["card_key"]], card["position"], card["depth"], None,
        ).encode("utf-8")).hexdigest()


async def test_a_cache_fill_dates_the_frame_by_its_mtime_not_by_today(env):
    """`recomposed_at` is when the frame was DRAWN. On a cache fill the pixels can be
    days old — that is the whole resume case — and today's clock there is the same
    misattribution the `workflow_sha256=None` rule exists to prevent, one field across.
    """
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    drawn = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    os.utime(env.shot["image_path"], (drawn.timestamp(), drawn.timestamp()))
    _sidecar(env)                      # as if the first stamp had never landed
    env.shot["image_path"] = str(env.plate)

    await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    block = _block(sidecar)
    assert block["source"] == "cache"
    assert block["recomposed_at"] == drawn.isoformat(timespec="seconds")
    assert block["instruction_sha256"] is None   # this pass did not send that text either


async def test_a_failed_stamp_does_not_leave_its_tmp_file_behind(env, monkeypatch):
    """The tmp file is `_stamp_sidecar`'s own litter: `write_text` lands, `replace`
    fails, and a stale `<name>.tmp` sits beside the sidecar looking like a torn write."""
    sidecar = _sidecar(env)
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    _sidecar(env)
    env.shot["image_path"] = str(env.plate)

    def boom(self, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", boom)

    _, stats = await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert stats["warnings"]
    assert not list(sidecar.parent.glob("*.tmp"))


async def test_a_recomposed_frame_with_no_digest_in_its_name_records_null(env):
    """`rsplit("_", 1)[-1]` returns the WHOLE stem when there is no separator, which put
    a filename fragment in a field every reader treats as a content digest — a value
    that compares unequal to the real digest without ever admitting it is not one."""
    frames = env.tmp_path / "run" / "recomposed"
    frames.mkdir(parents=True, exist_ok=True)
    odd = frames / "S001.png"          # a rename, a hand-placed frame
    odd.write_bytes(RECOMPOSED)
    env.shot["image_path"] = str(odd)
    sidecar = _sidecar(env)

    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["reentered"] == 1
    assert _block(sidecar)["digest"] is None


async def test_one_shots_attribution_failure_does_not_abort_the_sweep(env, monkeypatch):
    """`_sidecar_for` globs the filesystem and `_recompose_block` walks caller-supplied
    dicts, so either can raise on ONE shot. Escaping the loop leaves the frames already
    swapped while the caller's blanket except restores the ORIGINAL cast map — which
    composites every figure a second time onto a frame that already has them."""
    second = env.plate.parent / "S002.png"
    second.write_bytes(PNG + b"plate2")
    env.scenes[0]["shots"].append({"shot_id": "S002", "image_path": str(second)})
    env.cast["1:S002"] = [{"path": str(env.tmp_path / "card.png"), "card_key": "SCP-049",
                           "position": "right", "depth": "mid"}]
    _sidecar(env)
    _sidecar(env, base="scene_001_S002")

    def boom(**kwargs):
        raise RuntimeError("attribution blew up")

    monkeypatch.setattr(recompose_service, "_recompose_block", boom)

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats["recomposed"] == 2                       # the sweep finished
    assert stats["attributed"] == 0
    assert remaining == {}
    assert [w["shot_id"] for w in stats["warnings"]] == ["S001", "S002"]
    assert all("RuntimeError" in w["detail"] for w in stats["warnings"])
