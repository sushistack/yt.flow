"""SYS-E2E-001: stub-profile full run driven entirely through the HTTP API.

Upgrades tests/pipeline/test_stub_profile_smoke.py (B-2 seam smoke — drives
run_service directly) to the actual product contract: POST /runs -> observe SSE
events -> approve all 5 gates via the gate endpoint -> assert completion, SSE
event order, and the final artifact on disk. Zero real network/subprocess calls
(stub_profile fakes DeepSeek/Gemini/Qwen/ComfyUI/ffmpeg).

Story 12.2 added the provider-split E2E cases at the bottom: which provider seam
serves which scenario substage, and what a Gemini outage looks like to an API
client. Those live here rather than in the unit tests because the unit tests inject
the seams by hand — only a run driven through POST /runs proves production wiring
picks the same providers.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.services import run_service


class _RecordingRegistry:
    """Records published SSE events in publish order — the same order clients see."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture
async def api_env(tmp_path, monkeypatch, stub_profile):
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
    db.init("sqlite://")
    app.state.scps = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]
    app.state.workspace_path = str(tmp_path / "ws")
    app.state.sse_registry = _RecordingRegistry()
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)

    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk", langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    saver = await run_service.init(settings)
    yield tmp_path
    await saver.conn.close()
    run_service.configure(None)
    run_service._configs.clear()
    db._engine = None


async def _drain_bg_tasks(timeout: float = 60) -> None:
    """Await whatever run_service.spawn() just scheduled before making assertions.

    60s, not 10: the stub cassettes now run 2 scenes end-to-end (writing follows
    structure's scene count since writing_step was batched per scene), so each
    drain does real whisperx + ffmpeg work for two scenes. 10s was already
    load-dependent at one scene.
    """
    tasks = list(run_service._bg_tasks)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)


def _asgi_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk(api_env):
    registry: _RecordingRegistry = app.state.sse_registry

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        assert resp.status_code == 201
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        for stage in ("scenario", "image", "tts", "subtitle", "video"):
            run = (await c.get(f"/runs/{run_id}")).json()
            assert run["status"] == "awaiting_approval"
            assert run["current_stage"] == stage

            resp = await c.post(f"/runs/{run_id}/stages/{stage}/gate", json={"action": "approve"})
            assert resp.status_code == 202
            await _drain_bg_tasks()

        final = (await c.get(f"/runs/{run_id}")).json()
        assert final["status"] == "complete"

        artifact_resp = await c.get(f"/runs/{run_id}/artifact")
        assert artifact_resp.status_code == 200
        assert artifact_resp.headers["content-type"] == "video/mp4"

    # SSE order: each stage's entry/exit brackets its gate_pending, in stage order (AD-3/AD-4).
    kinds_and_stages = [(e["event"], e["data"]["stage"]) for e in registry.events
                        if e["event"] in ("stage_entry", "stage_exit", "gate_pending")]
    expected = [
        ev for stage in ("scenario", "image", "tts", "subtitle", "video")
        for ev in ((("stage_entry", stage), ("stage_exit", stage), ("gate_pending", stage)))
    ]
    assert kinds_and_stages == expected

    # Artifacts on disk: the real video seam wrote the workspace tree end to end.
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
    assert run.status == "complete"
    ws = api_env / "ws" / run_id
    assert (ws / "video.mp4").is_file()
    assert (ws / "video.mp4").stat().st_size > 0


async def test_reject_image_gate_resubmits_to_comfyui_instead_of_reusing_disk_cache(
    api_env, monkeypatch,
):
    """Story 2.6 AC4/AC7: rejecting the image gate on a completed image stage must
    trigger real regeneration, not silently replay the on-disk output.
    ``image_node._existing_complete_shot`` is a disk-only resume cache (sidecar +
    PNG on disk, independent of checkpoint state) — nulling ``image_path`` in state
    alone can't defeat it. Confirmed live pre-fix: rejecting left
    workspace/images/ byte-identical, zero new ComfyUI submissions, until the files
    were deleted by hand.
    """
    import yt_flow.pipeline.nodes.image as image_node
    import yt_flow.services.comfyui_client as comfyui_client
    from tests.stubs import fakes

    # stub-profile's TINY_PNG (70 bytes) is below the real MIN_VALID_IMAGE_BYTES floor,
    # which would make _existing_complete_shot skip every shot regardless of this
    # story's fix — lower the floor so the fixture registers as a genuinely "complete"
    # prior shot and the resume-cache path under test actually engages.
    monkeypatch.setattr(image_node, "MIN_VALID_IMAGE_BYTES", 10)

    calls = {"n": 0}

    async def _counting_submit(base_url, workflow, **kwargs):
        calls["n"] += 1
        return await fakes.fake_submit_and_fetch(base_url, workflow, **kwargs)

    monkeypatch.setattr(comfyui_client, "submit_and_fetch", _counting_submit)

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        resp = await c.post(f"/runs/{run_id}/stages/scenario/gate", json={"action": "approve"})
        assert resp.status_code == 202
        await _drain_bg_tasks()  # image stage runs once, produces valid on-disk output + sidecars

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["current_stage"] == "image"
        first_submit_count = calls["n"]
        assert first_submit_count > 0
        images_dir = api_env / "ws" / run_id / "images"
        first_pngs = sorted(p.name for p in images_dir.glob("*.png"))
        assert first_pngs

        resp = await c.post(f"/runs/{run_id}/stages/image/gate", json={"action": "reject"})
        assert resp.status_code == 202
        await _drain_bg_tasks()  # image reruns against a cleared disk cache (the fix)

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["status"] == "awaiting_approval"
        assert run["current_stage"] == "image"
        # Pre-fix this stayed at first_submit_count: _existing_complete_shot found the
        # unchanged sidecar+PNG still valid and skipped every shot.
        assert calls["n"] > first_submit_count
        assert calls["n"] - first_submit_count == len(first_pngs)  # every shot resubmitted, not just some
        assert sorted(p.name for p in images_dir.glob("*.png")) == first_pngs  # same shots, freshly written

        # AC4: the checkpoint itself (not just disk) reflects a real post-reject
        # regeneration — every shot's image_path was repopulated, not left null.
        snap = await run_service._graph.aget_state(run_service._configs[run_id])
        for scene in snap.values["scenes"]:
            for shot in scene["shots"]:
                assert shot["image_path"] is not None
                assert Path(shot["image_path"]).is_file()


async def test_retry_image_stage_resubmits_to_comfyui_instead_of_reusing_disk_cache(
    api_env, monkeypatch,
):
    """Story 2.6: the identical disk-cache bug fixed for reject also existed in
    `retry_stage` (Story 2.4) — `_delete_image_artifacts` was added there too, but
    only the reject path above was covered by a test through the real image_node.
    Drives POST /stages/image/retry directly to prove that call site too.
    """
    import yt_flow.pipeline.nodes.image as image_node
    import yt_flow.services.comfyui_client as comfyui_client
    from tests.stubs import fakes

    monkeypatch.setattr(image_node, "MIN_VALID_IMAGE_BYTES", 10)

    calls = {"n": 0}

    async def _counting_submit(base_url, workflow, **kwargs):
        calls["n"] += 1
        return await fakes.fake_submit_and_fetch(base_url, workflow, **kwargs)

    monkeypatch.setattr(comfyui_client, "submit_and_fetch", _counting_submit)

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        resp = await c.post(f"/runs/{run_id}/stages/scenario/gate", json={"action": "approve"})
        assert resp.status_code == 202
        await _drain_bg_tasks()  # image stage runs once, produces valid on-disk output + sidecars

        resp = await c.post(f"/runs/{run_id}/stages/image/gate", json={"action": "approve"})
        assert resp.status_code == 202
        await _drain_bg_tasks()  # advances to tts; gate_states["image"] == "approved" (retryable)

        images_dir = api_env / "ws" / run_id / "images"
        first_submit_count = calls["n"]
        assert first_submit_count > 0
        first_pngs = sorted(p.name for p in images_dir.glob("*.png"))
        assert first_pngs

        resp = await c.post(f"/runs/{run_id}/stages/image/retry")
        assert resp.status_code == 202
        await _drain_bg_tasks()  # image reruns against a cleared disk cache (the fix)

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["status"] == "awaiting_approval"
        assert run["current_stage"] == "image"
        # Pre-fix this stayed at first_submit_count: _existing_complete_shot found the
        # unchanged sidecar+PNG still valid and skipped every shot.
        assert calls["n"] > first_submit_count
        assert calls["n"] - first_submit_count == len(first_pngs)  # every shot resubmitted, not just some
        assert sorted(p.name for p in images_dir.glob("*.png")) == first_pngs  # same shots, freshly written


# ── Story 12.2: the DeepSeek/Gemini split, observed end to end ───────────────
#
# The ownership table from the story, keyed by the stage markers the offline
# prompt fake emits. Gemini owns every prose-producing/prose-revising call and
# every call that judges that prose; DeepSeek keeps planning, visual metadata,
# and the Qwen-tuned pronunciation pass.
_STAGE_OWNER = {
    "scenario/research": "deepseek",
    "scenario/structure": "deepseek",
    "scenario/writing": "gemini",
    "scenario/writing_scene_repair": "gemini",
    "scenario/cast_decision": "deepseek",
    "scenario/visual_breakdown": "deepseek",
    "scenario/review": "gemini",
    "scenario/critic_agent": "gemini",
    "scenario/tts_normalize": "deepseek",
}


def _record_provider_seams(monkeypatch) -> list[tuple[str, str]]:
    """Wrap the two seams ``stub_profile`` already installed so a run records
    ``(stage, provider)`` for every LLM call it makes.

    Wrapping rather than replacing keeps the stage-aware cassette fakes in play —
    they raise on a foreign stage marker, so a mis-route fails either way; the
    recording is what lets a test also prove the calls HAPPENED.
    """
    import yt_flow.pipeline.nodes.scenario as scenario

    seen: list[tuple[str, str]] = []

    def _wrap(provider, inner):
        async def recording(rendered, s):
            seen.append((rendered.removeprefix("__STAGE__:"), provider))
            return await inner(rendered, s)
        return recording

    monkeypatch.setattr(scenario, "_call_deepseek", _wrap("deepseek", scenario._call_deepseek))
    monkeypatch.setattr(scenario, "_call_gemini", _wrap("gemini", scenario._call_gemini))
    return seen


async def test_scenario_substages_reach_the_provider_the_ownership_table_assigns(api_env, monkeypatch):
    """AC1/AC8 end to end: a run created through POST /runs routes each substage to
    the provider the story assigns it.

    The unit tests inject the seams by hand, so they prove the routing helper works;
    only a run driven through the API proves production wiring calls it.
    """
    seen = _record_provider_seams(monkeypatch)

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["error"] is None, run["error"]
        assert (run["status"], run["current_stage"]) == ("awaiting_approval", "scenario")

    assert seen, "no provider seam was reached — the scenario stage never ran"
    # .get() not [] so an unmapped stage surfaces here as misrouted instead of KeyError.
    assert [(stage, p) for stage, p in seen if _STAGE_OWNER.get(stage) != p] == []

    observed = {stage for stage, _ in seen}
    # Both halves of the split must actually be exercised. Naming the stages
    # individually, not just "len(providers) == 2": a run that skipped tts_normalize
    # or judged nothing would still hit both providers and tell us nothing.
    assert {"scenario/writing", "scenario/review", "scenario/critic_agent"} <= observed
    assert {"scenario/research", "scenario/structure", "scenario/tts_normalize"} <= observed


async def test_a_gemini_outage_fails_the_run_visibly_instead_of_completing_on_deepseek(api_env, monkeypatch):
    """AC1/AD-10: no silent fallback. A run that quietly finished on DeepSeek would
    look compliant with the model split while invalidating every quality number
    drawn from it, so the outage has to reach the API client as a failure.
    """
    import yt_flow.pipeline.nodes.scenario as scenario

    deepseek = scenario._call_deepseek
    deepseek_stages: list[str] = []

    async def counting_deepseek(rendered, s):
        deepseek_stages.append(rendered.removeprefix("__STAGE__:"))
        return await deepseek(rendered, s)

    async def dead_gemini(rendered, s):
        # 429 RESOURCE_EXHAUSTED is Gemini's project-scoped rate-limit response —
        # the realistic outage, and the one a fallback would be most tempting for.
        raise httpx.HTTPStatusError("429 RESOURCE_EXHAUSTED", request=None, response=None)

    monkeypatch.setattr(scenario, "_call_deepseek", counting_deepseek)
    monkeypatch.setattr(scenario, "_call_gemini", dead_gemini)

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["status"] == "failed"
        assert run["error"] and "stage=scenario" in run["error"]

        # And the failure is not approvable into the rest of the pipeline.
        gate = await c.post(f"/runs/{run_id}/stages/scenario/gate", json={"action": "approve"})
        assert gate.status_code == 409

    # DeepSeek picked up its own planning stages and stopped there — it never
    # covered for the prose stage Gemini owns.
    assert "scenario/writing" not in deepseek_stages
    assert set(deepseek_stages) <= {"scenario/research", "scenario/structure"}

    failed = [e for e in app.state.sse_registry.events if e["event"] == "run_failed"]
    assert [e["data"]["stage"] for e in failed] == ["scenario"]


# ── Story 12.3: the pass-2 verdict, seen through the product's own surfaces ────
#
# Every other 12.3 backend test either injects a fake scenario node or mocks the
# graph snapshot, so all of them would still pass if production never built a
# quality object at all. These two drive the REAL scenario_node (stub cassettes)
# through POST /runs and read the verdict back the way the frontend does: off the
# artifact endpoint and the gate_pending frame.
_REVIEW_NEGATIVE = (
    "overall_pass: false\n"
    "coverage_pct: 71.0\n"
    # Deliberately no scene-scoped issue: with nothing for `_retry_scope` to map,
    # the retry takes the full-rewrite branch, which the offline cassettes cover
    # (there is no `scenario/writing_scene_repair` cassette).
    "issues: []\n"
    "corrections: []\n"
    "storytelling_score: 48\n"
    "storytelling_issues: []\n"
)


def _patch_gemini(monkeypatch, *, review_content: str | None = None) -> list[str]:
    """Record every Gemini-owned stage marker a run reaches, optionally forcing the
    review verdict. Wraps the stub fake rather than replacing it, so every other
    stage still replays its real cassette through the real parser."""
    import yt_flow.pipeline.nodes.scenario as scenario

    inner = scenario._call_gemini
    seen: list[str] = []

    async def fake(rendered, s):
        stage = rendered.removeprefix("__STAGE__:")
        seen.append(stage)
        if review_content is not None and stage == "scenario/review":
            return review_content, {}, "stop"
        return await inner(rendered, s)

    monkeypatch.setattr(scenario, "_call_gemini", fake)
    return seen


def _gate_frame(stage: str) -> dict:
    return next(e["data"] for e in app.state.sse_registry.events
                if e["event"] == "gate_pending" and e["data"]["stage"] == stage)


async def test_clean_stub_run_publishes_code_derived_quality_with_no_warning(api_env):
    """AC3/AC5/AC6 in production wiring: a clean run still reports measurements."""
    async with _asgi_client() as c:
        run_id = (await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})).json()["id"]
        await _drain_bg_tasks()

        run = (await c.get(f"/runs/{run_id}")).json()
        assert run["error"] is None, run["error"]
        assert (run["status"], run["current_stage"]) == ("awaiting_approval", "scenario")

        body = (await c.get(f"/runs/{run_id}/stages/scenario/artifacts")).json()

    quality = body["scenario_quality"]
    assert quality is not None, "production wiring returned no quality object at all"
    assert "warning" not in quality  # the cassettes pass review and critic (AC3)
    assert (quality["final_pass_index"], quality["retry_scope"]) == (1, "none")

    metrics = quality["rule_metrics"]
    # An all-zero payload is the realistic failure here: metrics computed over the
    # wrong object (or the TTS rewrite) rather than the narration the judge saw.
    assert metrics["aggregate"]["character_count"] > 0
    assert metrics["aggregate"]["sentence_count"] > 0
    assert [s["scene_num"] for s in metrics["scenes"]] == list(range(1, len(body["scenes"]) + 1))
    assert metrics["aggregate"]["sentence_count"] == sum(s["sentence_count"] for s in metrics["scenes"])
    assert metrics["slop_vocabulary_version"] == 1

    # SSE and the durable artifact agree, and the frame is JSON-safe as published.
    frame = _gate_frame("scenario")
    assert frame["scenario_quality"] == quality
    assert json.loads(json.dumps(frame)) == frame


async def test_unresolved_pass2_reaches_an_api_client_and_stays_approvable(api_env, monkeypatch):
    """AC1/AC2/AC6: an unresolved retry is a warning at the gate, not a failed run,
    not a third attempt, and not a blocked approval."""
    seen = _patch_gemini(monkeypatch, review_content=_REVIEW_NEGATIVE)

    async with _asgi_client() as c:
        run_id = (await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})).json()["id"]
        await _drain_bg_tasks()

        run = (await c.get(f"/runs/{run_id}")).json()
        # AC2: the stage SUCCEEDED. A degraded script is a human decision, not an error.
        assert run["error"] is None, run["error"]
        assert (run["status"], run["current_stage"]) == ("awaiting_approval", "scenario")

        body = (await c.get(f"/runs/{run_id}/stages/scenario/artifacts")).json()
        quality = body["scenario_quality"]
        assert quality["warning"]["code"] == "unresolved_pass2"
        assert quality["warning"]["message"]  # non-empty Korean operator copy
        assert (quality["final_pass_index"], quality["retry_scope"]) == (2, "full-fallback")
        assert quality["review_overall_pass"] is False
        assert quality["rule_metrics"]["aggregate"]["character_count"] > 0
        assert _gate_frame("scenario")["scenario_quality"]["warning"]["code"] == "unresolved_pass2"

        # AC1: exactly two passes over the whole chain — the fix is visibility, not
        # a third review/critic/rewrite. Per-scene batching (Story 6.6) makes the
        # expected count one call per scene per pass.
        scene_count = len(body["scenes"])
        assert scene_count > 0
        for stage in ("scenario/writing", "scenario/review", "scenario/critic_agent"):
            assert seen.count(stage) == 2 * scene_count, (stage, seen)

        # AC2: approval works exactly as it does for a clean script.
        assert (await c.post(f"/runs/{run_id}/stages/scenario/gate", json={"action": "approve"})).status_code == 202
        await _drain_bg_tasks()
        advanced = (await c.get(f"/runs/{run_id}")).json()
        assert (advanced["status"], advanced["current_stage"]) == ("awaiting_approval", "image")
