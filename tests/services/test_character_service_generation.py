"""Unit tests for CharacterService — Vision LLM enrichment and multi-angle generation.

AC: 1, 2 (Vision LLM enrichment)
AC: 3, 8 (Multi-angle generation)
AC: 7 (Config-driven provider selection)
"""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
from yt_flow.services.character_service import CharacterService
from yt_flow.services.character_image_provider import (
    ComfyUICharacterProvider,
    QwenCharacterProvider,
    create_provider,
)


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
        service._settings.deepseek_api_key = ""
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
        service._settings.deepseek_api_key = "test-key"

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

        # Verify the request contained image data
        call_args = mock_post.call_args
        messages = call_args[1]["json"]["messages"]
        content = messages[0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert "base64" in content[1]["image_url"]["url"]

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_vision_llm_failure_returns_none(self, mock_post, service, temp_ref_image):
        """AC2: Vision LLM HTTP error → returns None."""
        service._settings.deepseek_api_key = "test-key"
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
        service._settings.deepseek_api_key = "test-key"
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
        service._settings.deepseek_api_key = "test-key"

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
        s = Settings(workspace_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-096", "Shy Guy")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=b"fake-png-bytes")

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference("SCP-096", temp_ref_image)
            )

        assert len(paths) == 4
        for path in paths:
            assert Path(path).exists()
            assert Path(path).read_bytes() == b"fake-png-bytes"

    def test_generate_candidates_with_custom_angles(self, service, temp_ref_image, tmp_path):
        """Generate only specified angles."""
        s = Settings(workspace_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-173", "The Sculpture")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=b"fake-bytes")

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
        s = Settings(workspace_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-096", "Shy Guy")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        # First call fails, subsequent calls succeed
        mock_provider.generate = AsyncMock(
            side_effect=[RuntimeError("oops"), b"ok1", b"ok2", b"ok3"]
        )

        with patch.object(service, "_get_image_provider", return_value=mock_provider):
            paths = asyncio_run(
                service.generate_candidates_from_reference("SCP-096", temp_ref_image)
            )

        # 3 of 4 angles should succeed
        assert len(paths) == 3

    def test_generate_candidates_uses_visual_descriptor(self, service, temp_ref_image, tmp_path):
        """Uses Character.visual_descriptor in compiled prompt."""
        s = Settings(workspace_path=str(tmp_path))
        service._settings = s
        c = service.create_character("SCP-096", "Shy Guy")
        service.update_character(c.id, visual_descriptor="Pale humanoid, 2.38m tall")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=b"fake-bytes")

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
        """Generated files go to workspace/{scp_id}/characters/."""
        s = Settings(workspace_path=str(tmp_path))
        service._settings = s
        service.create_character("SCP-049", "Plague Doctor")

        mock_provider = MagicMock()
        mock_provider.supports_i2i = True
        mock_provider.generate = AsyncMock(return_value=b"fake-bytes")

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
        candidates = service.create_candidate_batch("SCP-096")
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
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in event loop — use a tiny helper
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()
