"""Unit tests for CharacterService — Vision LLM enrichment and multi-angle generation.

AC: 1, 2 (Vision LLM enrichment)
AC: 3, 8 (Multi-angle generation)
AC: 7 (Config-driven provider selection)
"""

import base64
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
import pytest
from PIL import Image
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.domain.exceptions import ValidationError
from yt_flow.services.character_service import _ANGLE_IPADAPTER_WEIGHTS, CharacterService, pose_hint_key
from tests.stubs.fakes import TINY_PNG
from yt_flow.services.character_image_provider import (
    ComfyUICharacterProvider,
    QwenCharacterProvider,
    create_provider,
)


RGB_PNG_HEADER_ONLY = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 17) + b"\x02"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _init_db():
    """Fresh file-based SQLite for each test."""
    db.init("sqlite://")


@pytest.fixture
def session():
    from yt_flow.db import _engine
    with Session(_engine) as s:
        yield s


@pytest.fixture
def service(session):
    return CharacterService(session)


@pytest.fixture
def temp_ref_image(tmp_path):
    """Create a tiny valid PNG file for testing."""
    img_path = tmp_path / "ref_1.png"
    # Minimal 1x1 white PNG
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    img_path.write_bytes(png_bytes)
    return str(img_path)


# ── Vision LLM Enrichment (AC1, AC2) ─────────────────────────────────────────


class TestVisionLLMEnrichment:
    """AC1: Vision LLM analyzes ref images and returns visual descriptor.
    AC2: Failure returns None (non-fatal).
    """

    def test_no_reference_images_returns_none(self, service):
        """AC2: No images provided → returns None."""
        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [])
        )
        assert result is None

    def test_no_api_key_returns_none(self, service, temp_ref_image):
        """AC2: No API key → returns None."""
        service._settings.character_vision_api_key = ""
        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [temp_ref_image])
        )
        assert result is None

    def test_image_not_found_skipped(self, service):
        """Nonexistent image paths are skipped gracefully."""
        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", ["/nonexistent/path.png"])
        )
        assert result is None

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_successful_enrichment(self, mock_post, service, temp_ref_image):
        """AC1: Successful Vision LLM call returns enriched descriptor."""
        service._settings.character_vision_api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "A tall humanoid figure with pale skin..."}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [temp_ref_image])
        )
        assert result == "A tall humanoid figure with pale skin..."

        # Verify the request targets DashScope Qwen-VL, not the old DeepSeek endpoint
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "qwen-vl-plus"

        # Verify the request contained image data
        messages = call_args[1]["json"]["messages"]
        content = messages[0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert "base64" in content[1]["image_url"]["url"]

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_max_tokens_is_vision_specific(self, mock_post, service, temp_ref_image):
        """Borrowing deepseek_max_tokens made qwen-vl-plus 400 ("Range of max_tokens
        should be [1, 8192]") for every call once the text budget went to 16384."""
        service._settings.character_vision_api_key = "test-key"
        service._settings.deepseek_max_tokens = 16384

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "desc"}}]}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        asyncio_run(service.enrich_descriptor_from_references("SCP-096", [temp_ref_image]))

        sent = mock_post.call_args[1]["json"]["max_tokens"]
        assert sent == service._settings.character_vision_max_tokens
        assert sent <= 8192

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_vision_llm_failure_returns_none(self, mock_post, service, temp_ref_image):
        """AC2: Vision LLM HTTP error → returns None."""
        service._settings.character_vision_api_key = "test-key"
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [temp_ref_image])
        )
        assert result is None

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_vision_llm_fallback_to_existing_descriptor(self, mock_post, service, temp_ref_image):
        """AC2: On failure, falls back to existing Character.visual_descriptor."""
        service._settings.character_vision_api_key = "test-key"
        mock_post.side_effect = httpx.TimeoutException("timeout")

        # Create character with existing descriptor
        c = service.create_character("SCP-096", "Shy Guy")
        service.update_character(c.id, visual_descriptor="Existing pale humanoid")

        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [temp_ref_image])
        )
        assert result == "Existing pale humanoid"

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_empty_response_returns_none(self, mock_post, service, temp_ref_image):
        """Empty LLM response → returns None."""
        service._settings.character_vision_api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "   "}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = asyncio_run(
            service.enrich_descriptor_from_references("SCP-096", [temp_ref_image])
        )
        assert result is None


# ── Multi-Angle Generation (AC3, AC8) ────────────────────────────────────────


class TestMultiAngleGeneration:
    """AC3: Multi-angle generation with i2i/t2i fallback.
    AC8: Angle-specific prompt compilation.
    """

    def test_generate_candidates_creates_files(self, service, temp_ref_image, tmp_path):
        """AC3: Generate candidates saves files for all 4 angles."""
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-096", "Shy Guy")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference("SCP-096", temp_ref_image)
            )

        assert len(paths) == 4
        for path in paths:
            assert (tmp_path / path).exists()
            assert (tmp_path / path).read_bytes() == TINY_PNG

    def test_generate_candidates_with_custom_angles(self, service, temp_ref_image, tmp_path):
        """Generate only specified angles."""
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-173", "The Sculpture")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-173", temp_ref_image, angles=["front", "back"]
                )
            )

        assert len(paths) == 2
        assert mock_provider.generate.call_count == 2

    def test_failed_angle_doesnt_block_others(self, service, temp_ref_image, tmp_path):
        """AC3: One angle failing doesn't prevent others from generating."""
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-096", "Shy Guy")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        # First call fails, subsequent calls succeed
        mock_provider.generate = AsyncMock(
            side_effect=[RuntimeError("oops"), TINY_PNG, TINY_PNG, TINY_PNG]
        )

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference("SCP-096", temp_ref_image)
            )

        # 3 of 4 angles should succeed
        assert len(paths) == 3

    def test_generate_candidates_uses_visual_descriptor(self, service, temp_ref_image, tmp_path):
        """Uses Character.visual_descriptor in compiled prompt."""
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        c = service.create_character("SCP-096", "Shy Guy")
        service.update_character(c.id, visual_descriptor="Pale humanoid, 2.38m tall")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-096", temp_ref_image, angles=["front"]
                )
            )

        # Verify the prompt sent to the provider includes the visual descriptor
        call_args = mock_provider.generate.call_args
        prompt = call_args[1]["prompt"]
        assert "Pale humanoid" in prompt

    def test_generate_uses_workspace_path(self, service, temp_ref_image, tmp_path):
        """Generated files go to assets/characters/{scp_id}/epoch_{n}/ (Story 8.6)."""
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-049", temp_ref_image, angles=["front"]
                )
            )

        assert len(paths) == 1
        assert "workspace" not in paths[0] or str(tmp_path) in paths[0]
        assert "SCP-049" in paths[0]
        assert "characters" in paths[0]
        assert "front_candidate_1.png" in paths[0]

    def test_generate_candidates_passes_angle_specific_ipadapter_weights(
        self, service, temp_ref_image, tmp_path
    ):
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-049", temp_ref_image, angles=["front", "side", "back"]
                )
            )

        weights = [call.kwargs["ipadapter_weight"] for call in mock_provider.generate.call_args_list]
        assert weights == [_ANGLE_IPADAPTER_WEIGHTS[a] for a in ("front", "side", "back")]

    def test_generate_candidates_rejects_opaque_png_per_angle(
        self, service, temp_ref_image, tmp_path
    ):
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(side_effect=[TINY_PNG, RGB_PNG_HEADER_ONLY, TINY_PNG])

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-049", temp_ref_image, angles=["front", "side", "back"]
                )
            )

        assert len(paths) == 2
        assert [Path(p).name for p in paths] == ["front_candidate_1.png", "back_candidate_1.png"]
        assert not (tmp_path / "SCP-049" / "characters" / "side_candidate_1.png").exists()

    def test_generate_sitting_candidates_write_pose_rows(self, service, temp_ref_image, tmp_path):
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-049", temp_ref_image, angles=["front"], pose="sitting"
                )
            )

        assert Path(paths[0]).name == "sitting_front.png"
        card = service.get_card("SCP-049", "sitting", "front")
        assert card is not None
        assert card.image_path == paths[0]

    def test_save_card_upserts_unique_pose_angle(self, service):
        first = service.save_card("SCP-049", "sitting", "front", "/tmp/a.png")
        second = service.save_card("SCP-049", "sitting", "front", "/tmp/b.png")

        assert second.id == first.id
        assert service.get_card("SCP-049", "sitting", "front").image_path == "/tmp/b.png"

    def test_save_card_accepts_hint_pose_key(self, service):
        card = service.save_card("SCP-049", "hint:012345abcd", "front", "/tmp/special.png")

        assert card.pose == "hint:012345abcd"

    def test_pose_hint_key_normalizes_case_and_whitespace(self):
        assert pose_hint_key(" Kneeling Over A Corpse ") == pose_hint_key("kneeling over a corpse")
        assert pose_hint_key("kneeling over a corpse").startswith("hint:")

    def test_generate_special_pose_card_success_upserts_hint_card(self, service, tmp_path):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        character = service.create_character("SCP-049", "Plague Doctor")
        service.update_character(
            character.id,
            visual_descriptor="black-robed plague doctor",
            angle_front_path=str(tmp_path / "front.png"),
        )
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.produces_alpha = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            path = asyncio_run(service.generate_special_pose_card("SCP-049", "kneeling over a corpse"))

        assert path is not None
        assert (tmp_path / path).exists()
        assert Path(path).name == f"{pose_hint_key('kneeling over a corpse').replace(':', '_')}_front.png"
        card = service.get_card("SCP-049", pose_hint_key("kneeling over a corpse"), "front")
        assert card is not None
        assert card.image_path == path
        assert mock_provider.generate.call_args.kwargs["ref_image_path"] == str(tmp_path / "front.png")

    def test_generate_special_pose_card_applies_stock_negative_to_maskless_keys(self, service, tmp_path):
        """Story 10.6 ② — this was the one card path that never passed a negative
        suffix, so `glowing eyes, monster, child, chibi, 2boys` never reached it. Live
        isolation on today's chain at a shared seed triple: 2/3 renders failed the
        pre-registered criteria without the suffix and 1/3 with it, and at seed 1062 the
        no-suffix frame came back as an adult plus a chibi child in matching jumpsuits
        while the suffixed one is a single adult (`10-6-live-validation/README.md`).

        Scoped on the descriptor in play, because the suffix suppresses `skull mask, gas
        mask, helmet, visor` and SCP-049 legitimately *is* a beaked mask. Table
        membership was not enough: a derived key provisioned before 10.6 still carries
        the inherited base descriptor, so `SCP-049-2` would ask for a beaked mask in the
        positive prompt while the suffix suppressed masks in the negative."""
        from yt_flow.domain.state import DERIVED_DESCRIPTORS, STOCK_NEGATIVE

        stale_049_2 = (
            "SCP-049 plague doctor humanoid, black hooded robe, white beaked plague "
            "doctor mask, dark gloves, full body\nA reclassified/duplicate instance."
        )
        # The read-back is appended to the authored text, so a healthy row starts with it.
        looks = {
            "STOCK-d-class": "STOCK-d-class look",
            "SCP-049-2": f"{DERIVED_DESCRIPTORS['SCP-049-2']}\nenriched read-back",
            "SCP-049": "SCP-049 look",
            "SCP-049-3": stale_049_2,  # stands in for a pre-10.6 row, whatever its key
        }
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        for key, look in looks.items():
            character = service.create_character(key, key)
            service.update_character(character.id, visual_descriptor=look,
                                     angle_front_path=str(tmp_path / "front.png"))
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.produces_alpha = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        suffixes = {}
        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            for key in looks:
                mock_provider.generate.reset_mock()
                assert asyncio_run(service.generate_special_pose_card(key, "lying supine on table"))
                # Assert the call happened, so a regression that returns before calling
                # the provider fails here instead of silently reading the previous key's
                # kwargs and reporting the wrong suffix.
                assert mock_provider.generate.call_count == 1, key
                suffixes[key] = mock_provider.generate.call_args.kwargs["negative_suffix"]

        assert suffixes["STOCK-d-class"] == STOCK_NEGATIVE
        assert suffixes["SCP-049-2"] == STOCK_NEGATIVE  # authored derived look is maskless
        assert suffixes["SCP-049"] is None  # the entity IS a mask; suppressing it erases it
        # The defect this scoping exists for: never suppress masks over a descriptor that
        # asks for one, even for a `<scp_id>-<n>`-shaped key.
        assert suffixes["SCP-049-3"] is None

    def _special_pose_guide_call(self, service, tmp_path, *, enabled, resolved, caplog=None):
        """Run one `generate_special_pose_card` with a guide key and return the kwargs.

        Patches `resolve_pose_guide` rather than building a manifest: the behaviour under
        test is the *wiring* (setting gate → resolver → provider kwarg), and the resolver
        already has its own tests. `resolved=None` stands for every one of its fail-closed
        paths at once — unspellable key, unapproved entry, integrity mismatch,
        incompatible schema/anatomy.
        """
        from unittest.mock import patch as _patch

        from yt_flow.services.asset_service import AssetService

        service._settings = Settings(
            workspace_path=str(tmp_path), assets_path=str(tmp_path),
            pose_guide_conditioning_enabled=enabled,
        )
        character = service.create_character("STOCK-d-class", "D-class")
        service.update_character(
            character.id, visual_descriptor="orange jumpsuit", angle_front_path=str(tmp_path / "front.png"),
        )
        # Set outside `update_character`: `pose_conditioning` is deliberately absent from
        # its allowlist, so 8.20's backfill script is the only writer. The model default
        # is `edit_only`, whose accepted-schema set is empty — a fresh row therefore
        # fails closed to no guide, which is the intended safe default.
        character = service.check_existing_character("STOCK-d-class")
        character.pose_conditioning = "openpose"
        service._session.add(character)
        service._session.commit()
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.produces_alpha = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with _patch.object(service, "_get_image_provider", return_value=mock_provider), \
             _patch.object(AssetService, "resolve_pose_guide", return_value=resolved) as resolver:
            assert asyncio_run(service.generate_special_pose_card(
                "STOCK-d-class", "lying supine on table", "humanoid_lying_supine",
            ))
        return mock_provider.generate.call_args.kwargs, resolver

    def test_special_pose_guide_is_not_even_resolved_while_the_setting_is_off(self, service, tmp_path):
        """AC: at the default setting the arguments passed to `provider.generate` are
        identical to before this story — `pose_guide_path` is None and the resolver is
        never consulted, so an unapproved or corrupt guide cannot change one byte."""
        kwargs, resolver = self._special_pose_guide_call(
            service, tmp_path, enabled=False, resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"},
        )

        assert kwargs["pose_guide_path"] is None
        assert resolver.call_count == 0

    def test_special_pose_guide_is_passed_when_enabled_and_resolvable(self, service, tmp_path):
        kwargs, resolver = self._special_pose_guide_call(
            service, tmp_path, enabled=True, resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"},
        )

        assert kwargs["pose_guide_path"] == "/guides/supine.png"
        # The character's own conditioning profile decides compatibility — never the card
        # key and never a descriptor keyword (domain/pose.py AC4).
        assert resolver.call_args.args == ("humanoid_lying_supine", "openpose")

    def test_unresolvable_guide_degrades_to_the_existing_path_and_says_so(self, service, tmp_path, caplog):
        """A silent fallback is a defect by this epic's own rule, so the degrade must be
        audible: the card is still generated, just without conditioning."""
        with caplog.at_level("WARNING"):
            kwargs, _ = self._special_pose_guide_call(service, tmp_path, enabled=True, resolved=None)

        assert kwargs["pose_guide_path"] is None
        assert "degrading to the unconditioned workflow" in caplog.text

    def test_a_non_openpose_guide_is_refused_rather_than_fed_to_an_openpose_graph(
        self, service, tmp_path, caplog,
    ):
        """`SetUnionControlNetType` is pinned to `openpose` in the graph, but the catalog
        also holds `scribble` silhouette guides that `guide_compatible` legitimately
        approves for the creature profiles. Only the openpose pair was ever rendered
        (3/3 supine), so anything else fails closed instead of shipping an unmeasured
        control type at strength 0.9."""
        with caplog.at_level("WARNING"):
            kwargs, _ = self._special_pose_guide_call(
                service, tmp_path, enabled=True,
                resolved={"abs_path": "/guides/lunge.png", "control_type": "scribble"},
            )

        assert kwargs["pose_guide_path"] is None
        assert "not openpose" in caplog.text

    def test_a_missing_guide_workflow_refuses_before_the_manifest_can_claim_conditioning(
        self, service, tmp_path, caplog, monkeypatch,
    ):
        """The provider degrades to the default graph when its guide workflow file is
        absent and still returns a successful render — so without this check the manifest
        would record `pose_guide` for a card that was never conditioned."""
        monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(tmp_path))  # no data/workflows/ under it

        with caplog.at_level("WARNING"):
            kwargs, _ = self._special_pose_guide_call(
                service, tmp_path, enabled=True,
                resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"},
            )

        assert kwargs["pose_guide_path"] is None
        assert "is missing" in caplog.text

    def test_authored_derived_looks_never_request_what_stock_negative_suppresses(self):
        """The runtime gate assumes authored derived looks are compatible with
        ``STOCK_NEGATIVE``; that assumption is enforced here, at design time, rather
        than re-derived per call. Adding an authored look that wants a mask, a monster,
        a glowing eye or a female subject must fail this test, not render a figure with
        the requested trait suppressed."""
        from yt_flow.domain.state import DERIVED_DESCRIPTORS, STOCK_NEGATIVE

        suppressed = [term.strip() for term in STOCK_NEGATIVE.split(",") if term.strip()]
        for key, descriptor in DERIVED_DESCRIPTORS.items():
            lowered = descriptor.lower()
            for term in suppressed:
                assert term not in lowered, (
                    f"{key} requests {term!r}, which STOCK_NEGATIVE suppresses — the pose-card "
                    f"and provisioning paths would fight their own positive prompt"
                )
            # "mask"/"hood" are the specific 지적 15 collision: the whole point of a
            # derived look is a face with nothing over it.
            for term in ("mask", "hood", "beak"):
                assert term not in lowered, f"{key} requests {term!r}; derived looks must be uncovered"

    def test_generate_special_pose_card_missing_front_returns_none(self, service, tmp_path):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("SCP-049", "Plague Doctor")

        path = asyncio_run(service.generate_special_pose_card("SCP-049", "kneeling over a corpse"))

        assert path is None
        assert service.get_card("SCP-049", pose_hint_key("kneeling over a corpse"), "front") is None

    def test_generate_special_pose_card_rejects_opaque_without_row(self, service, tmp_path):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        character = service.create_character("SCP-049", "Plague Doctor")
        service.update_character(character.id, angle_front_path=str(tmp_path / "front.png"))
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.produces_alpha = True
        mock_provider.generate = AsyncMock(return_value=RGB_PNG_HEADER_ONLY)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            path = asyncio_run(service.generate_special_pose_card("SCP-049", "kneeling over a corpse"))

        assert path is None
        assert service.get_card("SCP-049", pose_hint_key("kneeling over a corpse"), "front") is None

    def test_save_card_rejects_invalid_angle(self, service):
        with pytest.raises(ValidationError, match="angle"):
            service.save_card("SCP-049", "sitting", "top_down", "/tmp/top.png")

    def test_generate_cards_from_descriptor_front_t2i_then_self_references(
        self, service, tmp_path
    ):
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="gaunt human in orange jumpsuit",
                    angles=["front", "side", "back"],
                )
            )

        assert len(paths) == 3
        calls = mock_provider.generate.call_args_list
        assert calls[0].kwargs["ref_image_path"] is None
        assert calls[1].kwargs["ref_image_path"] == str(tmp_path / paths[0])
        assert calls[2].kwargs["ref_image_path"] == str(tmp_path / paths[0])
        character = service.check_existing_character("STOCK-d-class")
        assert character is not None
        assert character.angle_front_path == paths[0]
        assert character.angle_side_path == paths[1]
        assert character.angle_back_path == paths[2]

    def test_generate_cards_from_descriptor_runs_front_first(self, service, tmp_path):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="gaunt human in orange jumpsuit",
                    angles=["side", "front", "back"],
                )
            )

        assert [Path(path).name for path in paths] == [
            "front_candidate_1.png",
            "side_candidate_1.png",
            "back_candidate_1.png",
        ]
        calls = mock_provider.generate.call_args_list
        assert calls[0].kwargs["ref_image_path"] is None
        assert calls[1].kwargs["ref_image_path"] == str(tmp_path / paths[0])

    def test_generate_cards_from_descriptor_anchor_only_conditions_front(
        self, service, tmp_path
    ):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        anchor = str(tmp_path / "curated.png")
        Path(anchor).write_bytes(TINY_PNG)

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="gaunt human in orange jumpsuit",
                    anchor_path=anchor,
                    angles=["front", "side", "back"],
                )
            )

        calls = mock_provider.generate.call_args_list
        assert len(paths) == 3
        assert calls[0].kwargs["ref_image_path"] == anchor
        assert calls[1].kwargs["ref_image_path"] == str(tmp_path / paths[0])
        assert calls[2].kwargs["ref_image_path"] == str(tmp_path / paths[0])

    def test_generate_cards_from_descriptor_skips_later_angles_without_front_anchor(
        self, service, tmp_path
    ):
        s = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service._settings = s

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.produces_alpha = True
        mock_provider.generate = AsyncMock(side_effect=[RuntimeError("front failed"), TINY_PNG, TINY_PNG])

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="gaunt human in orange jumpsuit",
                    angles=["front", "side", "back"],
                )
            )

        assert paths == []
        assert mock_provider.generate.call_count == 1

    def test_generate_candidates_passes_negative_suffix_to_provider(self, service, temp_ref_image, tmp_path):
        """Story 8.15: STOCK-scoped mask suppression must reach the provider per call."""
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("STOCK-d-class", "D-class")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            asyncio_run(
                service.generate_candidates_from_reference(
                    "STOCK-d-class", temp_ref_image, angles=["front"], negative_suffix="skull mask",
                )
            )

        assert mock_provider.generate.call_args.kwargs["negative_suffix"] == "skull mask"

    def test_generate_cards_stage_writes_files_but_nothing_live(self, service, tmp_path):
        """Story 8.15: staging is filesystem-only — a manifest entry, an approval or an
        ``angle_*_path`` repoint would each make the staged set live immediately."""
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        character = service.create_character("STOCK-d-class", "D-class")
        service.update_character(character.id, angle_front_path="characters/STOCK-d-class/epoch_1/front_candidate_1.png")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="bare head, no mask, orange jumpsuit",
                    angles=["front", "side"],
                    stage=True,
                )
            )

        assert [Path(p).parent.name for p in paths] == ["epoch_2", "epoch_2"]
        assert all((tmp_path / p).exists() for p in paths)
        assert not (tmp_path / "manifest.json").exists()
        reloaded = service.check_existing_character("STOCK-d-class")
        assert reloaded.angle_front_path == "characters/STOCK-d-class/epoch_1/front_candidate_1.png"
        assert reloaded.angle_side_path is None
        assert reloaded.selected_image_path is None

    def test_generate_cards_enrich_ban_scrubs_the_token_but_keeps_the_read_back(self, service, tmp_path):
        """Story 8.15: the enrichment prompt says "an SCP Foundation character", so its
        read-back writes that mask-attractor token straight into ``visual_descriptor`` —
        which is exactly what angles 2-4 are prompted from. Skipping enrichment instead
        cost cross-angle identity (three different faces in one card set), so the
        read-back is kept and only the banned phrase is removed."""
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)
        enrich = AsyncMock(return_value="This SCP Foundation character has a plain face")

        with patch.object(service, "_get_image_provider", return_value=mock_provider), \
             patch.object(service, "enrich_descriptor_from_references", enrich):
            asyncio_run(
                service.generate_cards_from_descriptor(
                    "STOCK-d-class",
                    descriptor="ordinary human face, orange jumpsuit",
                    angles=["front", "side"],
                    enrich_ban="SCP Foundation",
                )
            )

        enrich.assert_awaited_once()
        character = service.check_existing_character("STOCK-d-class")
        # Appended, not replaced: the read-back is merged onto the caller's descriptor so
        # the hair/eye/face pins survive into the non-front angles, which is what the
        # enrichment prompt itself cannot supply.
        assert character.visual_descriptor == (
            "ordinary human face, orange jumpsuit\nThis character has a plain face"
        )

    def test_generate_cards_enriches_by_default(self, service, tmp_path):
        """Derived keys keep enrichment — it is what buys the family resemblance."""
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=TINY_PNG)
        enrich = AsyncMock(return_value="reanimated humanoid, sutured grey skin")

        with patch.object(service, "_get_image_provider", return_value=mock_provider), \
             patch.object(service, "enrich_descriptor_from_references", enrich):
            asyncio_run(
                service.generate_cards_from_descriptor(
                    "SCP-049-2",
                    descriptor="reanimated human",
                    angles=["front", "side"],
                )
            )

        enrich.assert_awaited_once()
        character = service.check_existing_character("SCP-049-2")
        assert character.visual_descriptor == (
            "reanimated human\nreanimated humanoid, sutured grey skin"
        )

    def test_generate_candidates_rejects_provider_without_alpha_sprites(
        self, service, temp_ref_image, tmp_path
    ):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.produces_alpha = False

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            with pytest.raises(RuntimeError, match="does not produce alpha sprites"):
                asyncio_run(service.generate_candidates_from_reference("SCP-049", temp_ref_image, angles=["front"]))

    def test_generate_candidates_rejects_unknown_pose(self, service, temp_ref_image, tmp_path):
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        with pytest.raises(ValidationError, match="pose"):
            asyncio_run(
                service.generate_candidates_from_reference(
                    "SCP-049", temp_ref_image, angles=["front"], pose="crouching"
                )
            )


# ── Provider Selection (AC7) ─────────────────────────────────────────────────


class TestProviderSelection:
    """AC7: Config-driven provider selection."""

    def test_create_provider_comfyui(self):
        s = Settings(character_image_provider="comfyui")
        provider = create_provider(s)
        assert isinstance(provider, ComfyUICharacterProvider)

    def test_create_provider_qwen(self):
        s = Settings(character_image_provider="qwen")
        provider = create_provider(s)
        assert isinstance(provider, QwenCharacterProvider)

    def test_create_provider_unknown_raises(self):
        s = Settings(character_image_provider="unknown")
        with pytest.raises(ValueError, match="Unknown character image provider"):
            create_provider(s)

    def test_comfyui_supports_i2i(self):
        s = Settings(character_image_provider="comfyui")
        provider = create_provider(s)
        assert provider.supports_i2i is True

    def test_qwen_supports_i2i(self):
        s = Settings(character_image_provider="qwen")
        provider = create_provider(s)
        assert provider.supports_i2i is False
        assert provider.produces_alpha is False

    def test_load_workflow_resolves_against_project_root_not_cwd(self, monkeypatch, tmp_path):
        """Story 5.10 Dev Notes: the configured path must not silently miss when the
        app's CWD differs from the project root."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
        s = Settings(character_image_provider="comfyui")
        provider = ComfyUICharacterProvider(s)
        workflow = provider._load_workflow()
        assert any(n.get("class_type") == "IPAdapterAdvanced" for n in workflow.values())


# ── Reference image injection / t2i fallback (Story 5.10, AC7-9) ────────────


class TestReferenceImageInjectionAndFallback:
    """Exercises the real authored workflow's node shape offline (no live ComfyUI)."""

    @pytest.fixture
    def workflow(self):
        import json
        path = Path(__file__).resolve().parents[2] / "data" / "workflows" / "comfyui_character_multi_angle_api.json"
        return json.loads(path.read_text())

    def test_inject_reference_image_sets_uploaded_filename(self, workflow):
        """AC7/AC9: LoadImage.inputs.image gets the uploaded filename, not base64."""
        updated = ComfyUICharacterProvider._inject_reference_image(workflow, "ref_1.png [input]")
        load_image_nodes = [n for n in updated.values() if n.get("class_type") == "LoadImage"]
        assert len(load_image_nodes) == 1
        assert load_image_nodes[0]["inputs"]["image"] == "ref_1.png [input]"

    def test_remove_i2i_input_bypasses_ipadapter_node(self, workflow):
        """AC9: t2i fallback reconnects KSampler.model around the IPAdapter node
        (IPAdapter conditions the model, not the latent — the legacy latent
        -reconnection logic would be a no-op for this workflow shape)."""
        ipadapter_node_id = next(
            nid for nid, n in workflow.items() if n.get("class_type") == "IPAdapterAdvanced"
        )
        upstream_model = workflow[ipadapter_node_id]["inputs"]["model"]
        sampler_id = next(nid for nid, n in workflow.items() if n.get("class_type") == "KSampler")
        assert workflow[sampler_id]["inputs"]["model"] == [ipadapter_node_id, 0]

        updated = ComfyUICharacterProvider._remove_i2i_input(workflow)

        assert updated[sampler_id]["inputs"]["model"] == upstream_model
        assert not any(
            n.get("class_type") in ("IPAdapter", "IPAdapterAdvanced", "LoadImage")
            for n in updated.values()
        )

    def test_remove_i2i_input_legacy_shape_reconnects_latent(self):
        """Legacy VAEEncode-i2i workflow shape (no IPAdapter node) still falls
        back via the original latent-reconnection path."""
        legacy_workflow = {
            "3": {"class_type": "KSampler", "inputs": {"latent_image": ["99", 0], "model": ["4", 0]}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
        }
        updated = ComfyUICharacterProvider._remove_i2i_input(legacy_workflow)
        assert updated["3"]["inputs"]["latent_image"] == ["5", 0]

    def test_remove_i2i_input_warns_when_no_ksampler_matches(self, workflow, caplog):
        """Silent no-ops are exactly the failure class this story exists to fix —
        an unmatched IPAdapter node must at least log, not fail silently."""
        ipadapter_node_id = next(
            nid for nid, n in workflow.items() if n.get("class_type") == "IPAdapterAdvanced"
        )
        sampler_id = next(nid for nid, n in workflow.items() if n.get("class_type") == "KSampler")
        workflow[sampler_id]["inputs"]["model"] = ["some-other-node", 0]

        with caplog.at_level("WARNING"):
            ComfyUICharacterProvider._remove_i2i_input(workflow)

        assert f"IPAdapter node {ipadapter_node_id}" in caplog.text

    def test_inject_seed_randomizes_ksampler_seed(self, workflow):
        original_seed = next(
            n["inputs"]["seed"] for n in workflow.values() if n.get("class_type") == "KSampler"
        )
        updated = ComfyUICharacterProvider._inject_seed(workflow)
        new_seed = next(
            n["inputs"]["seed"] for n in updated.values() if n.get("class_type") == "KSampler"
        )
        assert new_seed != original_seed
        assert isinstance(new_seed, int)

    def test_inject_ipadapter_weight_targets_only_ipadapter_nodes(self, workflow):
        updated = ComfyUICharacterProvider._inject_ipadapter_weight(workflow, 0.4)
        ipadapter_nodes = [
            node for node in updated.values()
            if node.get("class_type") in ("IPAdapter", "IPAdapterAdvanced")
        ]
        assert len(ipadapter_nodes) == 1
        assert ipadapter_nodes[0]["inputs"]["weight"] == 0.4
        assert updated["7"]["inputs"]["text"]

    def test_inject_negative_suffix_appends_to_existing_negative_text(self, workflow):
        """Story 8.15: the shared workflow's negative text is kept (SCP-049 needs its
        mask) and the STOCK suppression is appended to it, positive node untouched."""
        original_negative = workflow["7"]["inputs"]["text"]
        original_positive = workflow["6"]["inputs"]["text"]

        updated = ComfyUICharacterProvider._inject_negative_suffix(workflow, "skull mask, glowing eyes")

        assert updated["7"]["inputs"]["text"] == f"{original_negative}, skull mask, glowing eyes"
        assert updated["6"]["inputs"]["text"] == original_positive

    def test_inject_prompt_still_leaves_the_negative_node_alone(self, workflow):
        original_negative = workflow["7"]["inputs"]["text"]

        updated = ComfyUICharacterProvider(Settings())._inject_prompt(workflow, "a bare-faced guard")

        assert updated["6"]["inputs"]["text"] == "a bare-faced guard"
        assert updated["7"]["inputs"]["text"] == original_negative

    # ── Story 10.5: structural conditioning ──────────────────────────────────
    # Live basis (`_bmad-output/implementation-artifacts/10-5-live-validation/README.md`):
    # shared seed triple 1061/1062/1063, everything but the named variable held. The
    # guided leg drew the requested supine pose 3/3, the unguided control 0/3, and
    # dropping the IPAdapter anchor to 0.0 also 0/3 — so the guide is the cause and the
    # anchor is not. These tests fix the *wiring* only; the frames are the evidence.

    @pytest.fixture
    def guide_workflow(self):
        import json
        path = Path(__file__).resolve().parents[2] / "data" / "workflows" / "comfyui_character_pose_guide_api.json"
        return json.loads(path.read_text())

    def test_guide_lands_in_the_guide_node_and_the_reference_stays_out_of_it(self, guide_workflow):
        """The defect this narrowing exists for: `_inject_reference_image` writes
        *every* LoadImage, so on the two-input guide graph the character's own card
        would land in the ControlNet input and condition the pose on itself."""
        updated = ComfyUICharacterProvider._inject_guide_image(guide_workflow, "supine.png [input]")
        updated = ComfyUICharacterProvider._inject_reference_image(updated, "ref_1.png [input]")

        loaders = {
            n.get("_meta", {}).get("title"): n
            for n in updated.values() if n.get("class_type") == "LoadImage"
        }
        assert len(loaders) == 2, "the guide graph must have a reference loader and a guide loader"
        assert loaders["ytflow:guide_image"]["inputs"]["image"] == "supine.png [input]"
        assert [
            n["inputs"]["image"] for title, n in loaders.items() if title != "ytflow:guide_image"
        ] == ["ref_1.png [input]"]

    def test_t2i_fallback_keeps_the_guide_loader_alive(self, guide_workflow):
        """`_drop_reference_only_nodes` deletes every LoadImage. On this graph the guide
        loader is wired into ControlNetApplyAdvanced, so deleting it would leave a
        dangling link and ComfyUI would reject the whole prompt — the i2i fallback would
        turn a recoverable miss into a hard failure."""
        updated = ComfyUICharacterProvider._remove_i2i_input(guide_workflow)

        guide_ids = [
            nid for nid, n in updated.items()
            if n.get("class_type") == "LoadImage" and n.get("_meta", {}).get("title") == "ytflow:guide_image"
        ]
        assert len(guide_ids) == 1
        apply_node = next(n for n in updated.values() if n.get("class_type") == "ControlNetApplyAdvanced")
        assert apply_node["inputs"]["image"] == [guide_ids[0], 0]

    def test_no_guide_loads_the_unchanged_default_workflow(self, workflow, monkeypatch):
        """AC: with no guide the graph loaded is the pre-10.5 one.

        `monkeypatch`, not `os.environ.setdefault`: a leaked (or pre-existing) project
        root makes `_load_workflow` read a *different tree's* workflow while the fixture
        reads this one — the editable-install shadowing hazard this repo already has on
        record."""
        monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
        provider = ComfyUICharacterProvider(Settings())

        assert provider._load_workflow() == workflow
        assert provider._load_workflow(pose_guide=True) != workflow

    async def test_generate_routes_a_guide_through_upload_and_the_controlnet_graph(self, monkeypatch):
        """End-to-end through `generate()`, because the helper-level tests above would all
        still pass if the `pose_guide_path` block were deleted from it outright."""
        monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
        submitted: dict = {}
        uploaded: list[str] = []

        async def fake_upload(base_url, data, name):
            uploaded.append(name)
            return f"{name} [input]"

        async def fake_submit(base_url, workflow):
            submitted.update(workflow)
            return TINY_PNG

        import yt_flow.services.comfyui_client as comfyui_client
        monkeypatch.setattr(comfyui_client, "upload_image", fake_upload)
        monkeypatch.setattr(comfyui_client, "submit_and_fetch", fake_submit)

        guide = Path(__file__).resolve().parents[2] / "assets" / "pose_guides" / "humanoid_lying_supine.png"
        await ComfyUICharacterProvider(Settings()).generate(
            "a d-class in an orange jumpsuit", None, pose_guide_path=str(guide),
        )

        assert uploaded == ["humanoid_lying_supine.png"]
        assert any(n.get("class_type") == "ControlNetApplyAdvanced" for n in submitted.values())
        guide = next(n for n in submitted.values() if n.get("_meta", {}).get("title") == "ytflow:guide_image")
        assert guide["inputs"]["image"] == "humanoid_lying_supine.png [input]"

    async def test_an_unreadable_guide_costs_the_conditioning_not_the_card(self, monkeypatch, caplog):
        """The read/upload sits before the graph choice precisely so this degrades. If it
        raised out of `generate()` the card would never be produced, while the identical
        failure on the identity reference merely falls back to t2i."""
        monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
        submitted: dict = {}

        async def fake_submit(base_url, workflow):
            submitted.update(workflow)
            return TINY_PNG

        import yt_flow.services.comfyui_client as comfyui_client
        monkeypatch.setattr(comfyui_client, "submit_and_fetch", fake_submit)

        with caplog.at_level("WARNING"):
            out = await ComfyUICharacterProvider(Settings()).generate(
                "a d-class in an orange jumpsuit", None, pose_guide_path="/nope/missing_guide.png",
            )

        assert out  # a card came back
        assert not any(n.get("class_type") == "ControlNetApplyAdvanced" for n in submitted.values())
        assert "rendering unconditioned" in caplog.text

    def test_clean_alpha_noise_drops_disconnected_speck_keeps_main_blob(self):
        """Story 8.2 follow-up: InSPyReNet leaves dithered alpha noise as small
        disconnected specks or ragged bands; tiny specks are dropped, while
        meaningful components survive with alpha snapped fully opaque."""
        from yt_flow.services.character_image_provider import _clean_alpha_noise

        size = 100
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[20:80, 20:80, :3] = 255
        arr[20:80, 20:80, 3] = 255  # main blob: opaque 60x60 square
        arr[75:95, 75:95, :3] = 255
        arr[75:95, 75:95, 3] = 255  # meaningful detached component: 400px
        arr[5:10, 5:10, 3] = 200  # disconnected noise speck, far from the blob
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        cleaned = np.array(Image.open(io.BytesIO(_clean_alpha_noise(buf.getvalue()))).convert("RGBA"))

        assert cleaned[50, 50, 3] == 255  # main blob stays fully opaque
        assert cleaned[85, 85, 3] == 255  # large detached component survives
        assert cleaned[7, 7, 3] == 0  # disconnected speck removed

    def test_normalize_subject_scale_makes_framing_consistent(self):
        """Story 8.15: the front angle is t2i and the rest i2i from it, so the same card
        set came back with the front figure noticeably smaller than its own side and back
        views. Framing is not something the text encoder controls, so it is corrected on
        the cutout: subject height is pinned to a fixed share of the canvas, feet down."""
        from yt_flow.services.character_image_provider import (
            _SUBJECT_HEIGHT_FRACTION,
            _normalize_subject_scale,
        )

        def card(subject_h):
            arr = np.zeros((400, 300, 4), dtype=np.uint8)
            top = (400 - subject_h) // 2
            arr[top:top + subject_h, 130:170, :3] = 255
            arr[top:top + subject_h, 130:170, 3] = 255
            buf = io.BytesIO()
            Image.fromarray(arr, "RGBA").save(buf, format="PNG")
            return buf.getvalue()

        def subject_height(png):
            a = np.array(Image.open(io.BytesIO(png)).convert("RGBA"))[:, :, 3]
            rows = np.flatnonzero(a.max(axis=1) > 10)
            return int(rows[-1] - rows[0] + 1)

        small, large = _normalize_subject_scale(card(120)), _normalize_subject_scale(card(300))
        assert abs(subject_height(small) - subject_height(large)) <= 2
        assert abs(subject_height(small) - 400 * _SUBJECT_HEIGHT_FRACTION) <= 4

    def test_normalize_subject_scale_preserves_the_antialiased_edge_alpha(self):
        """Story 8.15 review: pasting the subject with itself as the mask double-applies
        alpha — a 140-alpha edge pixel came out at 77 with RGB dragged toward black. That
        is the feathered band _clean_alpha_noise keeps on purpose (11.1 AC5), so every
        composited character grew a thin dark halo. The synthetic bars used by the other
        tests are fully opaque and cannot see it."""
        from yt_flow.services.character_image_provider import _normalize_subject_scale

        arr = np.zeros((400, 300, 4), dtype=np.uint8)
        arr[100:300, 130:170, :3] = 200
        arr[100:300, 130:170, 3] = 140  # a uniformly semi-transparent subject
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        out = np.array(Image.open(io.BytesIO(_normalize_subject_scale(buf.getvalue()))).convert("RGBA"))
        alphas = out[:, :, 3][out[:, :, 3] > 0]
        assert alphas.max() >= 138, f"alpha was squared: max {alphas.max()} of 140"
        lit = out[out[:, :, 3] > 100]
        assert lit[:, 0].max() >= 195, f"RGB premultiplied toward black: max {lit[:, 0].max()} of 200"

    def test_normalize_subject_scale_keeps_a_bottom_gutter_for_the_feather(self):
        """video.py boxblurs the alpha plane; flush against the last row the feather eats
        the shoe line instead of padding."""
        from yt_flow.services.character_image_provider import (
            _BOTTOM_GUTTER,
            _normalize_subject_scale,
        )

        arr = np.zeros((400, 300, 4), dtype=np.uint8)
        arr[150:250, 140:160, :3] = 255
        arr[150:250, 140:160, 3] = 255
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        out = np.array(Image.open(io.BytesIO(_normalize_subject_scale(buf.getvalue()))).convert("RGBA"))
        rows = np.flatnonzero(out[:, :, 3].max(axis=1) > 10)
        assert 400 - (rows[-1] + 1) >= _BOTTOM_GUTTER - 1



    def test_clean_alpha_noise_drops_a_flanking_second_figure(self):
        """Story 8.15: the checkpoint likes to compose a character reference sheet,
        leaving half-drawn duplicates beside the subject. They are far too big for the
        old 2%-of-largest rule to catch, and a card must be one subject."""
        from yt_flow.services.character_image_provider import _clean_alpha_noise

        arr = np.zeros((200, 200, 4), dtype=np.uint8)
        arr[40:180, 80:130, :3] = 255
        arr[40:180, 80:130, 3] = 255  # subject: 140x50 = 7000px
        arr[50:150, 10:50, :3] = 255
        arr[50:150, 10:50, 3] = 255  # flanking ghost, fully separate: 4000px = 57%
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        cleaned = np.array(Image.open(io.BytesIO(_clean_alpha_noise(buf.getvalue()))).convert("RGBA"))

        assert cleaned[100, 100, 3] == 255  # subject survives
        assert cleaned[100, 30, 3] == 0  # ghost removed despite being 57% of the subject

    def test_clean_alpha_noise_preserves_antialiased_edge_band(self):
        """Story 11.1 AC5: the component interior still snaps to 255 (dither-band
        removal lives there), but the 2px edge band keeps the original alpha so
        anti-aliased edges survive into compositing instead of a binary cutout."""
        from yt_flow.services.character_image_provider import _clean_alpha_noise

        size = 100
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[20:80, 20:80, :3] = 255
        arr[20:80, 20:80, 3] = 255  # solid blob
        arr[50, 22, 3] = 180  # dither-band pixel deep inside the blob
        # AA ring: soften the blob's outermost pixel column/rows to 140 (>100
        # threshold so it stays in the mask, ≠255 so preservation is observable)
        arr[20:80, 20, 3] = 140
        arr[20:80, 79, 3] = 140
        arr[20, 20:80, 3] = 140
        arr[79, 20:80, 3] = 140
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        cleaned = np.array(Image.open(io.BytesIO(_clean_alpha_noise(buf.getvalue()))).convert("RGBA"))

        assert cleaned[50, 50, 3] == 255  # interior stays fully opaque
        assert cleaned[50, 22, 3] == 255  # interior dither pixel still snapped away
        assert cleaned[50, 20, 3] == 140  # edge-band AA alpha preserved, not snapped
        assert cleaned[50, 10, 3] == 0  # outside the mask stays transparent

    def test_clean_alpha_noise_rejects_rgb_input(self):
        from yt_flow.services.character_image_provider import _clean_alpha_noise

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(buf, format="PNG")

        with pytest.raises(ValueError, match="missing an alpha"):
            _clean_alpha_noise(buf.getvalue())

    def test_clean_alpha_noise_rejects_empty_alpha_mask(self):
        from yt_flow.services.character_image_provider import _clean_alpha_noise

        buf = io.BytesIO()
        Image.new("RGBA", (10, 10), (255, 255, 255, 0)).save(buf, format="PNG")

        with pytest.raises(ValueError, match="empty alpha"):
            _clean_alpha_noise(buf.getvalue())


# ── Candidate Tracking (AC4) ─────────────────────────────────────────────────


class TestCandidateTracking:
    """AC4: Candidate status transitions and persistence."""

    def test_create_candidate_batch(self, service):
        """Creates pending candidates for all 4 angles."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        assert len(candidates) == 4
        angles = {c.angle for c in candidates}
        assert angles == {"front", "back", "side", "three_quarter"}
        for c in candidates:
            assert c.status == "pending"
            assert c.scp_id == "SCP-096"

    def test_create_candidate_batch_custom_angles(self, service):
        """Creates candidates for specified angles only."""
        service.create_character("SCP-173", "The Sculpture")
        candidates = service.create_candidate_batch("SCP-173", angles=["front", "side"])
        assert len(candidates) == 2
        assert {c.angle for c in candidates} == {"front", "side"}

    def test_create_candidate_batch_no_character(self, service):
        """Works even without a character record (character_id is None)."""
        candidates = service.create_candidate_batch("SCP-049")
        assert len(candidates) == 4
        assert candidates[0].character_id is None

    def test_update_candidate_status(self, service):
        """Updates status and image path."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        c = candidates[0]

        updated = service.update_candidate_status(c.id, "ready", "/tmp/img.png")
        assert updated.status == "ready"
        assert updated.image_path == "/tmp/img.png"

        # Verify persisted
        fetched = service.get_candidate_status(c.id)
        assert fetched is not None
        assert fetched.status == "ready"

    def test_update_candidate_status_not_found(self, service):
        """Raises LookupError for nonexistent candidate."""
        with pytest.raises(LookupError, match="Candidate not found"):
            service.update_candidate_status("no-such-id", "ready")

    def test_list_candidates(self, service):
        """Lists candidates for an SCP ID."""
        service.create_character("SCP-096", "Shy Guy")
        service.create_candidate_batch("SCP-096")
        all_c = service.list_candidates("SCP-096")
        assert len(all_c) == 4

    def test_list_candidates_filtered_by_angle(self, service):
        """Lists candidates filtered by angle."""
        service.create_character("SCP-096", "Shy Guy")
        service.create_candidate_batch("SCP-096")
        front = service.list_candidates("SCP-096", angle="front")
        assert len(front) == 1
        assert front[0].angle == "front"

    def test_get_candidate_status_not_found(self, service):
        """Returns None for nonexistent candidate."""
        assert service.get_candidate_status("no-such-id") is None


# ── Candidate Selection + Memorization (AC5, AC6) ────────────────────────────


class TestCandidateSelection:
    """AC5: Candidate selection updates character with angle path.
    AC6: Finalize validates all 4 angles.
    """

    def test_select_candidate_maps_angle_path(self, service):
        """AC5: Selecting a candidate sets the correct angle_*_path."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        # Set first candidate (front) ready
        service.update_candidate_status(candidates[0].id, "ready", "/tmp/front.png")

        char = service.select_candidate("SCP-096", 1, "front")
        assert char.angle_front_path == "/tmp/front.png"
        # Front angle also sets selected_image_path
        assert char.selected_image_path == "/tmp/front.png"

    def test_select_candidate_back_angle(self, service):
        """Selecting back angle sets angle_back_path."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        service.update_candidate_status(candidates[1].id, "ready", "/tmp/back.png")

        char = service.select_candidate("SCP-096", 1, "back")
        assert char.angle_back_path == "/tmp/back.png"

    def test_select_candidate_auto_creates_character(self, service):
        """AC5: Auto-creates character if not existing (memorization)."""
        candidates = service.create_candidate_batch("SCP-049")
        service.update_candidate_status(candidates[0].id, "ready", "/tmp/front.png")

        # No character exists yet — select_candidate should create one
        char = service.select_candidate("SCP-049", 1, "front")
        assert char.scp_id == "SCP-049"
        assert char.angle_front_path == "/tmp/front.png"

    def test_select_candidate_not_ready_raises(self, service):
        """Raises ValueError if candidate is not ready."""
        service.create_character("SCP-096", "Shy Guy")
        service.create_candidate_batch("SCP-096")
        # Not updated to ready

        with pytest.raises(ValueError, match="not ready"):
            service.select_candidate("SCP-096", 1, "front")

    def test_select_candidate_no_image_path_raises(self, service):
        """Raises ValueError if candidate has no image path."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        service.update_candidate_status(candidates[0].id, "ready")  # no image_path

        with pytest.raises(ValueError, match="no image path"):
            service.select_candidate("SCP-096", 1, "front")

    def test_select_candidate_invalid_angle_raises(self, service):
        """Raises ValueError for invalid angle name."""
        service.create_character("SCP-096", "Shy Guy")
        candidates = service.create_candidate_batch("SCP-096")
        service.update_candidate_status(candidates[0].id, "ready", "/tmp/x.png")

        with pytest.raises(ValueError, match="Invalid angle"):
            service.select_candidate("SCP-096", 1, "top_down")

    def test_finalize_character_success(self, service):
        """AC6: Finalize succeeds when all 4 angles are set."""
        c = service.create_character("SCP-096", "Shy Guy")
        service.update_character(c.id,
            angle_front_path="/tmp/front.png",
            angle_back_path="/tmp/back.png",
            angle_side_path="/tmp/side.png",
            angle_three_quarter_path="/tmp/three_quarter.png",
        )
        finalized = service.finalize_character(c.id)
        assert finalized.id == c.id

    def test_finalize_character_missing_angles_raises(self, service):
        """AC6: Finalize raises when angles are missing."""
        c = service.create_character("SCP-096", "Shy Guy")
        service.update_character(c.id, angle_front_path="/tmp/front.png")

        with pytest.raises(ValueError, match="Missing angles"):
            service.finalize_character(c.id)

    def test_finalize_character_not_found_raises(self, service):
        """AC6: Raises LookupError for nonexistent character."""
        with pytest.raises(LookupError, match="Character not found"):
            service.finalize_character("no-such-id")

    def test_select_candidate_nonexistent_raises(self, service):
        """Raises LookupError if no candidate matches."""
        service.create_character("SCP-096", "Shy Guy")
        with pytest.raises(LookupError, match="No candidate found"):
            service.select_candidate("SCP-096", 99, "front")


# ── Helpers ──────────────────────────────────────────────────────────────────


def asyncio_run(coro):
    """Synchronous wrapper for running async tests."""
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in event loop — use a tiny helper
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


# ── Story 13.1: the provider-flag degradations, which the bytes cannot reveal ──


class TestProviderDegradationWarnings:
    """A t2i fallback and an unapplied pose guide both return a perfectly valid PNG.

    Nothing in the bytes, the return type or the DB row distinguishes them from a good
    card, which is the whole argument for the `last_i2i_fallback` /
    `last_pose_guide_applied` flags: the provider states what it did, and the caller —
    which knows the card key and the run — turns that into an operator-visible record.
    """

    @pytest.fixture
    def collected(self, session):
        """A CharacterService with the Story 13.1 collector sink attached."""
        sink: list = []
        return CharacterService(session, warnings=sink), sink

    def _provider(self, *, i2i_fallback=False, guide_applied=True):
        provider = MagicMock()
        provider.supports_i2i = True
        provider.produces_alpha = True
        provider.last_i2i_fallback = i2i_fallback
        provider.last_pose_guide_applied = guide_applied
        provider.generate = AsyncMock(return_value=TINY_PNG)
        return provider

    def test_no_collector_keeps_todays_log_only_behaviour(self, service, temp_ref_image, tmp_path):
        """The UI, scripts and every pre-13.1 caller construct the service without a
        sink; `_warn` must be a no-op for them, not a crash."""
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("SCP-096", "Shy Guy")

        with patch.object(service, "_get_image_provider", return_value=self._provider(i2i_fallback=True)):
            paths = asyncio_run(service.generate_candidates_from_reference("SCP-096", temp_ref_image))

        assert len(paths) == 4  # the cards still generated

    def test_i2i_fallback_names_every_angle_it_cost(self, collected, temp_ref_image, tmp_path):
        """The identity anchor was lost, so these four angles are a different person."""
        service, sink = collected
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("SCP-096", "Shy Guy")

        with patch.object(service, "_get_image_provider", return_value=self._provider(i2i_fallback=True)):
            asyncio_run(service.generate_candidates_from_reference("SCP-096", temp_ref_image))

        assert [w["code"] for w in sink] == ["character_card_i2i_fallback"] * 4
        assert all(w["stage"] == "scenario" for w in sink)
        assert {w["context"]["angle"] for w in sink} == {"front", "side", "back", "three_quarter"}
        assert sink[0]["context"]["card_key"] == "SCP-096"

    def test_a_clean_i2i_generation_warns_nothing(self, collected, temp_ref_image, tmp_path):
        service, sink = collected
        service._settings = Settings(workspace_path=str(tmp_path), assets_path=str(tmp_path))
        service.create_character("SCP-096", "Shy Guy")

        with patch.object(service, "_get_image_provider", return_value=self._provider()):
            asyncio_run(service.generate_candidates_from_reference("SCP-096", temp_ref_image))

        assert sink == []

    def _pose_card(self, service, tmp_path, provider, *, enabled=True, resolved=None):
        from yt_flow.services.asset_service import AssetService

        service._settings = Settings(
            workspace_path=str(tmp_path), assets_path=str(tmp_path),
            pose_guide_conditioning_enabled=enabled,
        )
        character = service.create_character("STOCK-d-class", "D-class")
        service.update_character(
            character.id, visual_descriptor="orange jumpsuit", angle_front_path=str(tmp_path / "front.png"),
        )
        character = service.check_existing_character("STOCK-d-class")
        character.pose_conditioning = "openpose"
        service._session.add(character)
        service._session.commit()
        with patch.object(service, "_get_image_provider", return_value=provider), \
             patch.object(AssetService, "resolve_pose_guide", return_value=resolved):
            return asyncio_run(service.generate_special_pose_card(
                "STOCK-d-class", "lying supine on table", "humanoid_lying_supine",
            ))

    def test_a_service_side_guide_rejection_warns_and_still_publishes_the_card(
        self, collected, tmp_path,
    ):
        """Story 10.5's measured difference is 3/3 supine with the guide and 0/3 without
        it, and the unconditioned card is published either way — so the rejection reason
        is the only thing that tells the operator which one they are looking at."""
        service, sink = collected
        assert self._pose_card(service, tmp_path, self._provider(), resolved=None)  # fails closed

        assert [w["code"] for w in sink] == ["special_pose_guide_unapplied"]
        assert sink[0]["context"]["card_key"] == "STOCK-d-class"
        assert sink[0]["context"]["pose_guide_key"] == "humanoid_lying_supine"
        assert "unusable under profile" in sink[0]["context"]["detail"]

    def test_a_non_openpose_guide_rejection_carries_its_reason(self, collected, tmp_path):
        service, sink = collected
        self._pose_card(service, tmp_path, self._provider(),
                         resolved={"abs_path": "/guides/lunge.png", "control_type": "scribble"})

        assert [w["code"] for w in sink] == ["special_pose_guide_unapplied"]
        assert "not openpose" in sink[0]["context"]["detail"]

    def test_a_provider_side_guide_upload_failure_warns(self, collected, tmp_path, monkeypatch):
        """The service resolved a usable guide and the provider still rendered
        unconditioned — it returns success either way, so the flag is the only signal."""
        service, sink = collected
        monkeypatch.setattr(
            "yt_flow.services.character_service._pose_guide_workflow_path",
            lambda: Path(__file__),  # any existing file: the workflow check must pass
        )
        provider = self._provider(guide_applied=False)
        assert self._pose_card(service, tmp_path, provider,
                                resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"})

        assert provider.generate.call_args.kwargs["pose_guide_path"] == "/guides/supine.png"
        assert [w["code"] for w in sink] == ["special_pose_guide_unapplied"]
        assert sink[0]["context"]["detail"] == "provider could not upload the guide"

    def test_an_applied_guide_warns_nothing(self, collected, tmp_path, monkeypatch):
        service, sink = collected
        monkeypatch.setattr(
            "yt_flow.services.character_service._pose_guide_workflow_path", lambda: Path(__file__),
        )
        assert self._pose_card(service, tmp_path, self._provider(),
                                resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"})
        assert sink == []

    def test_a_special_pose_i2i_fallback_warns_against_the_hint(self, collected, tmp_path, monkeypatch):
        service, sink = collected
        monkeypatch.setattr(
            "yt_flow.services.character_service._pose_guide_workflow_path", lambda: Path(__file__),
        )
        self._pose_card(service, tmp_path, self._provider(i2i_fallback=True),
                         resolved={"abs_path": "/guides/supine.png", "control_type": "openpose"})

        assert [w["code"] for w in sink] == ["character_card_i2i_fallback"]
        assert sink[0]["context"]["pose"] == pose_hint_key("lying supine on table")
        assert sink[0]["context"]["angle"] == "front"


# ── Story 13.1: the provider flags themselves ────────────────────────────────


class TestProviderFlags:
    """`last_i2i_fallback` / `last_pose_guide_applied` are the load-bearing part of the
    "the degradation is invisible in the returned bytes" argument, so they get their own
    tests rather than being asserted only through their caller."""

    @pytest.fixture
    def provider(self, tmp_path):
        return ComfyUICharacterProvider(Settings(
            comfyui_url="http://comfy.test:8188", workspace_path=str(tmp_path), assets_path=str(tmp_path),
        ))

    def test_flags_start_false(self, provider):
        assert provider.last_i2i_fallback is False
        assert provider.last_pose_guide_applied is False

    def test_a_successful_i2i_leaves_the_fallback_flag_clear(self, provider, temp_ref_image, monkeypatch):
        monkeypatch.setattr(provider, "_load_workflow", lambda pose_guide=False: {})
        for name in ("_inject_prompt", "_inject_dimensions", "_inject_seed",
                     "_inject_negative_suffix", "_inject_ipadapter_weight",
                     "_inject_reference_image", "_remove_i2i_input", "_inject_guide_image"):
            monkeypatch.setattr(provider, name, lambda wf, *a, **k: wf)
        monkeypatch.setattr("yt_flow.services.comfyui_client.upload_image", AsyncMock(return_value="ref.png"))
        monkeypatch.setattr("yt_flow.services.comfyui_client.submit_and_fetch", AsyncMock(return_value=TINY_PNG))
        provider.last_i2i_fallback = True  # stale value from a previous card must be reset

        asyncio_run(provider.generate("prompt", temp_ref_image))
        assert provider.last_i2i_fallback is False

    def test_an_i2i_failure_sets_the_flag_and_still_returns_bytes(self, provider, temp_ref_image, monkeypatch):
        monkeypatch.setattr(provider, "_load_workflow", lambda pose_guide=False: {})
        for name in ("_inject_prompt", "_inject_dimensions", "_inject_seed",
                     "_inject_negative_suffix", "_inject_ipadapter_weight",
                     "_inject_reference_image", "_remove_i2i_input", "_inject_guide_image"):
            monkeypatch.setattr(provider, name, lambda wf, *a, **k: wf)
        monkeypatch.setattr("yt_flow.services.comfyui_client.upload_image",
                             AsyncMock(side_effect=RuntimeError("upload refused")))
        monkeypatch.setattr("yt_flow.services.comfyui_client.submit_and_fetch", AsyncMock(return_value=TINY_PNG))

        out = asyncio_run(provider.generate("prompt", temp_ref_image))
        # Valid PNG back, identity anchor gone — exactly the case the flag exists for.
        assert out
        assert provider.last_i2i_fallback is True

    def test_an_unusable_pose_guide_clears_the_applied_flag(self, provider, temp_ref_image, monkeypatch):
        monkeypatch.setattr(provider, "_load_workflow", lambda pose_guide=False: {})
        for name in ("_inject_prompt", "_inject_dimensions", "_inject_seed",
                     "_inject_negative_suffix", "_inject_ipadapter_weight",
                     "_inject_reference_image", "_remove_i2i_input", "_inject_guide_image"):
            monkeypatch.setattr(provider, name, lambda wf, *a, **k: wf)
        monkeypatch.setattr("yt_flow.services.comfyui_client.upload_image", AsyncMock(return_value="up.png"))
        monkeypatch.setattr("yt_flow.services.comfyui_client.submit_and_fetch", AsyncMock(return_value=TINY_PNG))

        asyncio_run(provider.generate("prompt", None, pose_guide_path="/nonexistent/guide.png"))
        assert provider.last_pose_guide_applied is False

    def test_a_readable_pose_guide_sets_the_applied_flag(self, provider, temp_ref_image, monkeypatch):
        monkeypatch.setattr(provider, "_load_workflow", lambda pose_guide=False: {})
        for name in ("_inject_prompt", "_inject_dimensions", "_inject_seed",
                     "_inject_negative_suffix", "_inject_ipadapter_weight",
                     "_inject_reference_image", "_remove_i2i_input", "_inject_guide_image"):
            monkeypatch.setattr(provider, name, lambda wf, *a, **k: wf)
        monkeypatch.setattr("yt_flow.services.comfyui_client.upload_image", AsyncMock(return_value="up.png"))
        monkeypatch.setattr("yt_flow.services.comfyui_client.submit_and_fetch", AsyncMock(return_value=TINY_PNG))

        asyncio_run(provider.generate("prompt", None, pose_guide_path=temp_ref_image))
        assert provider.last_pose_guide_applied is True
