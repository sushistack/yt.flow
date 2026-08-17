"""Tests for recompose_service (Story 10.1c close-out).

The prompt/workflow half is covered by tests/pipeline/nodes/test_shot_recompose.py; what
this half owns is the *state edit* it makes to the graph — which shots get their frame
replaced, and what has to be taken away from them at the same time.
"""

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from yt_flow.services import recompose_service
from yt_flow.services.recompose_service import recompose_run_shots

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
    assert stats == {"recomposed": 1, "skipped": 0, "failed": 0}


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
    assert stats == {"recomposed": 0, "skipped": 1, "failed": 0}


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
    assert stats == {"recomposed": 0, "skipped": 0, "failed": 1}


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
    assert stats == {"recomposed": 0, "skipped": 1, "failed": 0}
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
    assert stats == {"recomposed": 0, "skipped": 0, "failed": 1}


# ── Story 10.1d: runtime-prerequisite preflight ──────────────────────────────
# A RUN-level refusal, not the per-shot skips above: a misconfigured ComfyUI is wrong for
# every shot, so the whole cast map comes back untouched and nothing is submitted. The
# eight tests above all pass this gate via `_StubClient`'s PASSING_STATS default, which is
# the point — the loop's own behaviour must not have changed.


async def test_a_satisfied_preflight_is_invisible(env):
    """The shipped-good case: no bail keys, and the loop ran exactly as before."""
    _, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert stats == {"recomposed": 1, "skipped": 0, "failed": 0}
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
