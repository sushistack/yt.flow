"""scripts/run_e2e_stub_server.py — AC9's "the stub server reaches no provider".

The script boots the real app for Playwright with every external seam rebound to
``tests/stubs/fakes.py``, so nothing else in the suite covers it: it runs as its own
process, outside pytest. Two things can silently break it, and both did — once per
provider:

- a missing dummy key, which makes ``scenario_node``'s fail-fast guard kill every
  run unless the developer happens to have a real key in ``.env``;
- a provider seam added to production but not to ``apply_stub_profile()``, which
  turns a "zero real calls" run into a live billed one.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_e2e_stub_server.py"

# Every (module, attribute) pair apply_stub_profile() rebinds. Registered with
# monkeypatch BEFORE the call so the plain attribute assignments the script makes
# (it has no monkeypatch — it is a standalone process) are undone at teardown
# instead of leaking a fake ffmpeg into the rest of the suite.
_PATCHED_SEAMS = [
    ("yt_flow.pipeline.nodes.scenario", "get_prompt"),
    ("yt_flow.pipeline.nodes.scenario", "_call_deepseek"),
    ("yt_flow.pipeline.nodes.scenario", "_call_gemini"),
    ("yt_flow.services.prompt_service", "get_prompt"),
    ("yt_flow.pipeline.nodes.tts", "_synthesize"),
    ("yt_flow.pipeline.nodes.video", "_run_ffmpeg"),
    ("yt_flow.services.comfyui_client", "submit_and_fetch"),
    ("yt_flow.services.comfyui_client", "submit_and_fetch_outputs"),
    ("yt_flow.services.comfyui_client", "check_health"),
    ("yt_flow.services.comfyui_client", "get_system_stats"),
    ("yt_flow.services.comfyui_client", "upload_image"),
    # The five seams ``fakes.patch_character_reference_seams`` rebinds. They are
    # *class* attributes, so registering the owning module attribute (as this list
    # used to) restored nothing — the mutation is on the class object itself.
    ("yt_flow.services.image_search.ScpWikiImageFetch", "fetch"),
    ("yt_flow.services.image_search.DuckDuckGoImageSearch", "search"),
    ("yt_flow.services.character_service.CharacterService", "_download_reference_image"),
    ("yt_flow.services.character_service.CharacterService", "enrich_descriptor_from_references"),
    ("yt_flow.services.character_service.CharacterService", "_get_image_provider"),
]

# Story 13.3: the ComfyUI adapter's network surface — every public async function
# is stubbed, with no "unreached" escape hatch. There used to be one, holding
# ``upload_image`` on the claim that only character generation and IC-Light relight
# reach it; ``compositing_service.depth_map_file`` reaches it too, from an
# ``api/main.py`` seam injected whenever ``depth_placement_enabled`` (ships True),
# and its blanket except hid the resulting live socket. Listing the two
# prompt-submission calls by hand is likewise how ``check_health`` and
# ``get_system_stats`` stayed live. The set equality below turns a newly added HTTP
# function into a failing test instead of a silent real call.
_COMFYUI_STUBBED = {
    "submit_and_fetch", "submit_and_fetch_outputs", "check_health", "get_system_stats",
    "upload_image",
}

# The character-reference seams, as (owner, attribute) — the drift guard for
# ``patch_character_reference_seams``, which the script must call rather than
# re-list. It named two of these five, so the SCP-wiki fetch made real HTTP.
_CHARACTER_SEAMS = [
    ("yt_flow.services.image_search.ScpWikiImageFetch", "fetch"),
    ("yt_flow.services.image_search.DuckDuckGoImageSearch", "search"),
    ("yt_flow.services.character_service.CharacterService", "_download_reference_image"),
    ("yt_flow.services.character_service.CharacterService", "enrich_descriptor_from_references"),
    ("yt_flow.services.character_service.CharacterService", "_get_image_provider"),
]


def _owner(dotted: str):
    """The module or class named by ``dotted`` — modules and classes alike, so one
    seam table can address ``module.attr`` and ``module.Class.attr``."""
    try:
        return importlib.import_module(dotted)
    except ImportError:
        module, _, attr = dotted.rpartition(".")
        return getattr(_owner(module), attr)


@pytest.fixture
def stub_server(monkeypatch):
    """Import the script and apply its stub profile, with every touched seam restored
    afterwards. Importing is safe: the module top only sets dummy env keys and
    sys.path entries — uvicorn boots under ``__main__`` only."""
    for dotted, attr in _PATCHED_SEAMS:
        owner = _owner(dotted)
        monkeypatch.setattr(owner, attr, getattr(owner, attr))
    # Same trick for the env keys the script assigns at module top: registering them
    # first is what makes monkeypatch restore the suite's own dummies at teardown.
    for var in ("YTFLOW_DEEPSEEK_API_KEY", "YTFLOW_GEMINI_API_KEY"):
        monkeypatch.setenv(var, os.environ[var])

    spec = importlib.util.spec_from_file_location("_e2e_stub_server", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "_e2e_stub_server", module)
    spec.loader.exec_module(module)
    module.apply_stub_profile()
    return module


def test_both_provider_keys_are_non_secret_dummies(stub_server):
    """Set unconditionally, so a real ``.env`` key can neither be required to boot
    nor be reachable from a process whose whole purpose is zero real calls."""
    from yt_flow.config import Settings

    s = Settings()
    assert s.deepseek_api_key == "sk-e2e-stub-dummy"
    assert s.gemini_api_key == "gm-e2e-stub-dummy"
    # Whatever the ambient environment held, the script overrode it.
    assert os.environ["YTFLOW_DEEPSEEK_API_KEY"] == "sk-e2e-stub-dummy"
    assert os.environ["YTFLOW_GEMINI_API_KEY"] == "gm-e2e-stub-dummy"


def test_every_comfyui_network_function_is_classified():
    """Every async function on the adapter must be stubbed — no "unreached" bucket.

    ``get_system_stats`` fell through the hand-kept list; ``upload_image`` then sat
    in an ``_COMFYUI_UNREACHED`` set that certified a live call as intentional. A
    test that blesses a real socket is worse than no test."""
    import inspect

    import yt_flow.services.comfyui_client as cc

    public_async = {
        name for name, obj in vars(cc).items()
        if not name.startswith("_") and inspect.iscoroutinefunction(obj)
        and getattr(obj, "__module__", None) == cc.__name__
    }
    assert public_async == _COMFYUI_STUBBED


def test_every_stubbed_comfyui_seam_is_actually_rebound(stub_server):
    """...and the script really rebinds each one — the classification is only a
    contract if something checks it against ``apply_stub_profile``."""
    import yt_flow.services.comfyui_client as cc

    for name in _COMFYUI_STUBBED:
        assert getattr(cc, name).__module__ in ("tests.stubs.fakes", "_e2e_stub_server"), name


def test_pytest_stub_profile_rebinds_the_same_comfyui_seams(stub_profile):
    """The in-process fixture and the standalone script must not drift apart:
    ``tests/conftest.py`` had the identical ``get_system_stats`` hole, which sent
    every offline stub-profile test at a real ``127.0.0.1:8188``."""
    import yt_flow.services.comfyui_client as cc

    for name in _COMFYUI_STUBBED:
        assert getattr(cc, name).__module__ == "tests.stubs.fakes", name


@pytest.mark.parametrize("dotted,attr", _CHARACTER_SEAMS, ids=lambda v: v.rpartition(".")[2])
def test_the_script_rebinds_every_character_reference_seam(stub_server, dotted, attr):
    """The script must go through ``patch_character_reference_seams``, not re-list a
    subset of it: with only search + download named, ``ScpWikiImageFetch.fetch`` made
    real HTTP to the SCP wiki and an unstubbed ``_get_image_provider`` was a second
    live route into ``upload_image``."""
    assert getattr(_owner(dotted), attr).__module__ == "tests.stubs.fakes"


@pytest.mark.parametrize("dotted,attr", _CHARACTER_SEAMS, ids=lambda v: v.rpartition(".")[2])
def test_pytest_stub_profile_rebinds_the_same_character_seams(stub_profile, dotted, attr):
    """...and the in-process fixture binds the identical five, through the identical
    helper — the drift guard covers both callers, not just ``comfyui_client``."""
    assert getattr(_owner(dotted), attr).__module__ == "tests.stubs.fakes"


async def test_both_scenario_provider_seams_are_stubbed_and_stage_scoped(stub_server):
    """AC9: each seam replays only its own provider's stages. Handing a seam a stage
    the other provider owns must raise rather than replay the right cassette from the
    wrong provider — that is what makes the stub server a routing check too.
    """
    import yt_flow.pipeline.nodes.scenario as scenario

    deepseek, gemini = scenario._call_deepseek, scenario._call_gemini

    content, _, _ = await deepseek("__STAGE__:scenario/research", None)
    assert content, "the DeepSeek seam must replay its own planning stage"
    content, _, _ = await gemini("__STAGE__:scenario/writing", None)
    assert content, "the Gemini seam must replay its own prose stage"

    with pytest.raises(AssertionError):
        await deepseek("__STAGE__:scenario/writing", None)   # Gemini's stage
    with pytest.raises(AssertionError):
        await gemini("__STAGE__:scenario/research", None)    # DeepSeek's stage
