"""Deterministic fakes for the external seams (B-2 + character search).

- ``fake_run_ffmpeg``       — replaces ``video._run_ffmpeg`` (subprocess seam)
- ``fake_submit_and_fetch`` / ``fake_submit_and_fetch_outputs`` — ComfyUI HTTP seam
- ``fake_synthesize``       — replaces ``tts._synthesize`` (Qwen HTTP seam)
- ``deepseek_stage_aware``/``gemini_stage_aware`` — the two scenario provider seams
- ``deepseek_from_cassette``/``qwen_payload_from_cassette`` — recorded-shape playback
- ``fake_image_search`` / ``fake_download_reference_image`` — DuckDuckGo character
  reference search seam (Story 1.11/3.7)

None of these touch the network or a subprocess. The ffmpeg / synth / reference
image fakes write tiny real files so downstream file-existence checks pass.
"""

import json
import math
import wave
from pathlib import Path

import yaml

from yt_flow.domain.state import SearchResult

CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "cassettes"

# Tiny valid 1x1 RGBA PNG — enough for any "image bytes" seam.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9fa11e000782027f3dc848ef0000000049454e44ae426082"
)


def load_cassette(name: str) -> dict:
    """Load a recorded response-shape cassette by filename (e.g. 'deepseek_scenario.json').

    ``deepseek_structure.json`` is the one cassette carrying numbers the code
    CONTRACTUALLY checks, so its ``word_budget`` values are re-solved here instead of
    being frozen in the JSON — see ``retention_budgets``.
    """
    data = json.loads((CASSETTE_DIR / name).read_text(encoding="utf-8"))
    if name == "deepseek_structure.json":
        _apply_retention_budgets(data)
    return data


def retention_budgets(total: int) -> list[int]:
    """Contract-valid, deliberately UNEVEN word budgets: short ends, fat middle.

    Solved from ``scenario_chain``'s DERIVED constants rather than tabulated, so it
    follows ``TARGET_DURATION_MINUTES`` wherever that goes. Story 12.6 made a uniform
    split a rejection (``budget_uniform``), which is exactly what a flat split
    produces.

    Shape: both ends at the per-scene floor, every middle scene at whatever it takes
    to clear the total band AND the spread ratio; if the middles hit the per-scene
    ceiling first, the ends absorb the remainder instead.

    Below 4 scenes there IS no legal distribution — the opening/closing 20% caps
    force the single middle scene past the 30% per-scene ceiling, which
    ``_validate_retention_outline`` now names as ``scene_count`` — so those callers
    get the floor everywhere. They are the ledger tests, which are rejected by an
    earlier check and never reach the budget block.

    Lives here rather than in one test module because three test modules and the
    structure cassette all need the same solve, and a fourth hand-typed copy is how
    "one line, no second edit anywhere" quietly stops being true.
    """
    from yt_flow.pipeline.nodes import scenario_chain as chain

    if total < 4:
        return [chain.MIN_SCENE_WORD_BUDGET] * total
    inner = total - 2
    end = chain.MIN_SCENE_WORD_BUDGET
    middle = min(
        chain.MAX_SCENE_WORD_BUDGET,
        max(
            math.ceil(end * chain.MIN_BUDGET_SPREAD),
            math.ceil((chain.MIN_TOTAL_WORD_BUDGET - 2 * end) / inner),
        ),
    )
    end = max(end, math.ceil((chain.MIN_TOTAL_WORD_BUDGET - middle * inner) / 2))
    return [end] + [middle] * inner + [end]


def _apply_retention_budgets(data: dict) -> None:
    """Re-solve the structure cassette's ``word_budget`` values in place.

    As recorded they summed to exactly ``MIN_TOTAL_WORD_BUDGET``, so setting
    ``TARGET_DURATION_MINUTES = 4`` made the cassette violate ``budget_total`` and
    broke every test that replays it — including the offline stub-profile E2E. That
    is a second edit the story's headline promise says does not exist, hiding in a
    fixture.
    """
    message = data["choices"][0]["message"]
    scenes = yaml.safe_load(message["content"])["scenes"]
    for scene, budget in zip(scenes, retention_budgets(len(scenes)), strict=True):
        scene["word_budget"] = budget
    message["content"] = yaml.safe_dump({"scenes": scenes}, allow_unicode=True, sort_keys=False)


# ── video._run_ffmpeg ───────────────────────────────────────────────────────
async def fake_run_ffmpeg(*args: str) -> tuple[int, str]:
    """No-op ffmpeg: write a 1-byte file to the output path (always the last arg)."""
    Path(args[-1]).write_bytes(b"\x00")
    return 0, ""


# ── services.comfyui_client ─────────────────────────────────────────────────
async def fake_submit_and_fetch(base_url, workflow, **kwargs) -> bytes:
    return TINY_PNG


async def fake_submit_and_fetch_outputs(base_url, workflow, output_node_ids, **kwargs) -> dict:
    return {node_id: TINY_PNG for node_id in output_node_ids}


async def fake_upload_image(base_url, image_bytes: bytes, filename: str) -> str:
    """Story 13.3 review-2: the ComfyUI seam the "offline" profile really was using.

    ``compositing_service.depth_map_file`` defaults ``comfyui_client`` to the real
    module, and ``api/main.py`` injects it into ``image_node`` unconditionally
    whenever ``depth_placement_enabled`` (which ships True) — so every distinct
    background opened a real ``POST /upload/image``. ``depth_map_file``'s blanket
    ``except`` then swallowed the outcome, exactly like ``get_system_stats``.

    Returns what ComfyUI returns: the name to set as ``LoadImage.inputs.image``.
    """
    return filename


async def fake_check_health(base_url) -> None:
    """Story 5.14: stub-profile ComfyUI is always "reachable" — no real HTTP."""
    return None


async def fake_get_system_stats(base_url) -> dict:
    """Story 13.3: image_node's provenance probe is a fifth ComfyUI seam.

    It is awaited unconditionally in real (non-mock) mode, so without this the
    "offline" stub profile opened a real socket to whatever ``comfyui_url``
    pointed at — silently, since the probe swallows every failure [AD-10]. A
    fixed payload, so provenance assertions stay deterministic.

    Story 10.1d added a second reader: `recompose_service._preflight` bails the whole
    recompose path when `system.argv` or `system.ram_free` is unreadable. So the payload
    also states a server started the way REQUIRED_FLAGS demands, with RAM well clear of
    the floor — otherwise the offline profile would report a preflight failure that is
    indistinguishable from a real misconfiguration to whoever runs the next live gate.
    """
    return {
        "system": {
            "comfyui_version": "stub-0.0.0", "pytorch_version": "stub-torch",
            "argv": ["main.py", "--lowvram", "--cache-lru", "10"],
            "ram_free": 24 * 2**30, "ram_total": 32 * 2**30,
        },
        "devices": [{"name": "stub-device"}],
    }


# ── tts._synthesize ─────────────────────────────────────────────────────────
async def fake_synthesize(text: str, s, path: Path) -> None:
    """Write a tiny valid mono WAV instead of calling Qwen + downloading audio."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)  # 1 second of silence


# ── scenario._call_deepseek (cassette playback) ─────────────────────────────
def deepseek_from_cassette(name: str = "deepseek_scenario.json"):
    """Return an async fake matching ``_call_deepseek(rendered, s) -> (content, usage, finish_reason)``."""
    data = load_cassette(name)
    choice = data["choices"][0]

    async def fake(rendered, s):
        return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")

    return fake


# ── scenario.get_prompt (Langfuse Prompt Hub) ───────────────────────────────
class _FakePrompt:
    """Stands in for the Langfuse SDK's prompt object — only `.compile()` is used."""

    def compile(self, **variables: object) -> str:
        return "fake rendered prompt"


def fake_get_prompt(name: str, *, label: str | None = None) -> _FakePrompt:
    return _FakePrompt()


# ── image_search.ScpWikiImageFetch.fetch (Story 5.10) ───────────────────────
async def fake_wiki_fetch_miss(self, scp_id: str):
    """Always misses — routes offline tests through the (also-faked) DuckDuckGo path."""
    return None


# ── image_search.DuckDuckGoImageSearch.search ────────────────────────────────
async def fake_image_search(self, query: str, max_results: int = 10) -> list[SearchResult]:
    """3 canned SearchResults — never fetched for real (download is also faked)."""
    return [
        SearchResult(
            url=f"https://example.invalid/{query}/{i}.png",
            thumbnail_url=f"https://example.invalid/{query}/{i}_thumb.png",
            title=f"{query} {i}",
        )
        for i in range(1, 4)
    ][:max_results]


# ── character_service.CharacterService._download_reference_image ───────────
async def fake_download_reference_image(self, url: str, refs_dir: Path, num: int) -> str:
    """No-op download: writes TINY_PNG locally instead of fetching ``url``."""
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / f"ref_{num}.png").write_bytes(TINY_PNG)
    return "png"


# ── character_service.CharacterService._get_image_provider (Story 5.8) ─────
class _FakeCharacterImageProvider:
    """Stands in for ComfyUI/Qwen multi-angle character generation — returns TINY_PNG."""

    supports_i2i = True

    async def generate(
        self,
        prompt: str,
        ref_image_path: str | None,
        *,
        width: int = 832,
        height: int = 1216,
        ipadapter_weight: float | None = None,
        negative_suffix: str | None = None,
    ) -> bytes:
        return TINY_PNG


def fake_get_image_provider(self) -> _FakeCharacterImageProvider:
    return _FakeCharacterImageProvider()


# ── character_service.CharacterService.enrich_descriptor_from_references ───
async def fake_enrich_descriptor(self, scp_id: str, ref_image_paths, timeout: float = 60.0) -> str:
    """Canned vision descriptor — the real method POSTs to DashScope.

    Without this the offline seams above are incomplete: `_ensure_character_reference`
    calls enrichment between search and generation, and a developer `.env` that carries
    `YTFLOW_CHARACTER_VISION_API_KEY` turns every gate/resume unit test into a live
    multimodal API call whose outcome (and therefore whose Story 13.1 warning) depends
    on the network.
    """
    return f"{scp_id} 참조 묘사"


def patch_character_reference_seams(monkeypatch) -> None:
    """Wire SCP-wiki fetch + DuckDuckGo search + download + enrichment + generation
    to the offline fakes.

    Shared by every fixture that needs ``run_service._ensure_character_reference``
    (Story 5.8) to stay offline: ``conftest.stub_profile`` plus the gate/resume test
    files, which stub LangGraph nodes directly instead of going through it —
    **and** ``scripts/run_e2e_stub_server.py``, which used to hand-list a two-seam
    subset of the five below and therefore made real HTTP to the SCP wiki (and had
    a live ``_get_image_provider`` route into ``upload_image``) from a process whose
    docstring promises zero real network calls.

    ``monkeypatch`` is only ever asked for ``.setattr(obj, name, value)``, so the
    standalone script passes ``SimpleNamespace(setattr=setattr)`` rather than
    growing a second copy of this list. ponytail: duck typing, no adapter class.
    """
    import yt_flow.services.character_service as character_service
    import yt_flow.services.image_search as image_search

    monkeypatch.setattr(image_search.ScpWikiImageFetch, "fetch", fake_wiki_fetch_miss)
    monkeypatch.setattr(image_search.DuckDuckGoImageSearch, "search", fake_image_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image",
                         fake_download_reference_image)
    monkeypatch.setattr(character_service.CharacterService, "enrich_descriptor_from_references",
                         fake_enrich_descriptor)
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider",
                         fake_get_image_provider)


# ── scenario_chain multi-stage prompt/provider fakes (Story 1.5 chain redesign) ─
#
# Story 12.2 split these by provider so the offline stubs mirror production
# routing. Each fake only knows its OWN stages: hand a DeepSeek-owned marker to
# the Gemini fake (or vice versa) and it raises instead of quietly replaying the
# cassette — which is what makes the offline profile a routing regression test
# rather than just a network stub. The cassette files keep their `deepseek_`
# names because they record the *OpenAI-compatible response shape*, which both
# providers share; only the seam they are played back through changed.
_DEEPSEEK_STAGE_CASSETTES = {
    "scenario/research": "deepseek_research.json",
    "scenario/structure": "deepseek_structure.json",
    "scenario/cast_decision": "deepseek_cast_decision.json",
    "scenario/visual_breakdown": "deepseek_visual_breakdown.json",
    "scenario/tts_normalize": "deepseek_tts_normalize.json",
}
_GEMINI_STAGE_CASSETTES = {
    "scenario/writing": "deepseek_writing.json",
    "scenario/review": "deepseek_review.json",
    "scenario/critic_agent": "deepseek_critic.json",
}


class _FakeChainPrompt:
    """Stands in for a Langfuse prompt object for one scenario_chain stage.

    ``compile()`` returns a marker string embedding the stage name instead of
    real prompt text — paired with ``deepseek_stage_aware()``, which reads the
    marker back out of ``rendered`` to pick the right per-stage cassette. The
    chain never inspects prompt *content* in tests, only structure, so a
    marker is sufficient and avoids needing real prompt text offline.
    """

    def __init__(self, name: str):
        self._name = name

    def compile(self, **variables: object) -> str:
        return f"__STAGE__:{self._name}"


def fake_get_prompt_for_chain(name: str, *, label: str | None = None):
    """Replaces ``yt_flow.services.prompt_service.get_prompt`` for the scenario chain.

    ``scenario/format_guide`` has no variables and is only ever compiled once
    for its static text — the existing zero-arg ``_FakePrompt`` fake covers it.
    Every other name is one of the six chain stages, or (Story 12.4) one of the
    four ``scenario/archetypes/*`` guide components, whose compiled text is a
    *variable* injected into structure rather than a provider call — so a marker
    is all it needs and no cassette exists for it.
    """
    if name == "scenario/format_guide":
        return _FakePrompt()
    return _FakeChainPrompt(name)


def _stage_aware(provider: str, cassettes: dict[str, str]):
    """Replay one provider's stage cassettes, keyed by the ``_FakeChainPrompt``
    marker embedded in ``rendered``. One fixed cassette per stage, cached after
    first load. ``visual_breakdown`` is called once per scene; the same cassette
    (3 shots) is replayed for every scene, which is fine because the stub-profile
    run only ever has one scene (see the ``deepseek_writing.json`` cassette's
    single scene).
    """
    cache: dict[str, dict] = {}

    async def fake(rendered: str, s):
        for name, filename in cassettes.items():
            if rendered == f"__STAGE__:{name}":
                if filename not in cache:
                    cache[filename] = load_cassette(filename)
                data = cache[filename]
                choice = data["choices"][0]
                return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")
        raise AssertionError(
            f"{provider}_stage_aware: no cassette mapped for rendered={rendered!r}. "
            f"If that stage belongs to the other provider, the routing under test is wrong."
        )

    return fake


def deepseek_stage_aware():
    """Replaces ``scenario._call_deepseek`` — the planning/visual/normalize stages."""
    return _stage_aware("deepseek", _DEEPSEEK_STAGE_CASSETTES)


def gemini_stage_aware():
    """Replaces ``scenario._call_gemini`` — the prose + prose-judging stages (Story 12.2)."""
    return _stage_aware("gemini", _GEMINI_STAGE_CASSETTES)
