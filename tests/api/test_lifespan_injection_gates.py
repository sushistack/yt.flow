"""Lifespan wiring gates: which resolvers get injected for which settings.

Story 11.5's depth resolver is gated on depth_placement_enabled — depth maps
have no consumer when placement is off, and every depth prompt evicts the SDXL
checkpoint from VRAM (measured live: ~500s image reload per shot vs ~16s when
no depth workflow runs between two image workflows).
"""
import pytest
from fastapi import FastAPI

from yt_flow.api import main


@pytest.fixture
def injected(monkeypatch, tmp_path):
    """Run the real lifespan with the heavy startup stubbed; record injections."""
    calls: list[str] = []

    class _Saver:
        class conn:
            @staticmethod
            async def close():
                pass

    async def _init(_settings):
        return _Saver()

    monkeypatch.setattr(main.db, "init", lambda _url: None)
    monkeypatch.setattr(main.run_service, "init", _init)
    for name in (
        "inject_depth_resolver",
        "inject_ground_resolver",
        "inject_motion_renderer",
        "inject_cast_resolver",
        "inject_location_service",
        "inject_relight_resolver",
    ):
        monkeypatch.setattr(main, name, lambda _fn, _n=name: calls.append(_n))

    async def _run():
        async with main.lifespan(FastAPI()):
            pass
        return calls

    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path))
    return _run


@pytest.mark.asyncio
async def test_depth_resolver_not_injected_when_placement_disabled(injected, monkeypatch):
    monkeypatch.setenv("YTFLOW_DEPTH_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("YTFLOW_PARALLAX_25D_ENABLED", "true")

    calls = await injected()

    assert "inject_depth_resolver" not in calls
    assert "inject_ground_resolver" not in calls
    # The parallax renderer keeps its own switch; it degrades via its NO_DEPTH rung.
    assert "inject_motion_renderer" in calls


@pytest.mark.asyncio
async def test_depth_resolver_injected_when_placement_enabled(injected, monkeypatch):
    monkeypatch.setenv("YTFLOW_DEPTH_PLACEMENT_ENABLED", "true")
    monkeypatch.setenv("YTFLOW_PARALLAX_25D_ENABLED", "true")

    calls = await injected()

    assert "inject_depth_resolver" in calls
    assert "inject_ground_resolver" in calls
