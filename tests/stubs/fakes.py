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
import wave
from pathlib import Path

from yt_flow.domain.state import SearchResult

CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "cassettes"

# Tiny valid 1x1 RGBA PNG — enough for any "image bytes" seam.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9fa11e000782027f3dc848ef0000000049454e44ae426082"
)


def load_cassette(name: str) -> dict:
    """Load a recorded response-shape cassette by filename (e.g. 'deepseek_scenario.json')."""
    return json.loads((CASSETTE_DIR / name).read_text(encoding="utf-8"))


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


async def fake_check_health(base_url) -> None:
    """Story 5.14: stub-profile ComfyUI is always "reachable" — no real HTTP."""
    return None


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


def patch_character_reference_seams(monkeypatch) -> None:
    """Wire DuckDuckGo search + download + generation to the offline fakes above.

    Shared by every fixture that needs ``run_service._ensure_character_reference``
    (Story 5.8) to stay offline: ``conftest.stub_profile`` plus the gate/resume test
    files, which stub LangGraph nodes directly instead of going through it.
    """
    import yt_flow.services.character_service as character_service
    import yt_flow.services.image_search as image_search

    monkeypatch.setattr(image_search.ScpWikiImageFetch, "fetch", fake_wiki_fetch_miss)
    monkeypatch.setattr(image_search.DuckDuckGoImageSearch, "search", fake_image_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image",
                         fake_download_reference_image)
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
