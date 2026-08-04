"""Tests for scripts/render_pose_guides.py — the authored guide set (Story 8.20, AC5/AC6).

Guide PNGs are gitignored like every other asset binary (repo policy: the
manifest is the committed audit trail), so these tests are what actually pin the
guide *content* in git. A changed joint angle fails here and forces a conscious
hash update rather than silently re-posing the whole library.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from yt_flow.domain.pose import POSE_GUIDE_KEYS, guide_compatible

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "render_pose_guides.py"

# sha256 of each rendered PNG. Regenerate with:
#   uv run python scripts/render_pose_guides.py && sha256sum assets/pose_guides/*.png
EXPECTED_SHA256 = {
    "humanoid_reaching_forward": "59fc1ccd228698d7fbe4ed48069491fd31e987c5690dceb118f26c2359c8bcc6",
    "humanoid_lying_supine": "fbeb030b07535be8f645dd06594554514f9ae807144a2235ab95d72f28926520",
    "humanoid_kneeling": "1b9304ec63a0882d137b88fc462c0cba8761aa8034e0e760ec2329efe9f2a5a2",
    "humanoid_collapsed": "0dec077da4a7ecf81d08b75a4786a0ba56aee0391dda3a008c769bddf262b541",
    "creature_prone_lunge": "90d506a0462be3bd700d8b3214207bf2458b065e1ac79ef4e24cda2e3b187043",
    "creature_rearing": "7846e6cf860346eb631dd85549d9b618e94743b4b67c924509b329c2e58b64ca",
}


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("render_pose_guides", _SCRIPT)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules["render_pose_guides"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def images(mod):
    return mod.build_all()


def test_renders_exactly_the_declared_catalog(images):
    assert set(images) == set(POSE_GUIDE_KEYS)


def test_every_guide_matches_the_configured_card_dimensions(images, mod):
    """AC10: guide geometry must map onto the reference card 1:1, so the guide
    canvas equals character_image_width x character_image_height."""
    from yt_flow.config import Settings

    settings = Settings()
    for key, im in images.items():
        assert im.size == (settings.character_image_width, settings.character_image_height), key
        assert im.size == (mod.W, mod.H), key


@pytest.mark.parametrize("key", sorted(EXPECTED_SHA256))
def test_render_is_deterministic_and_content_pinned(images, key):
    """Deterministic output is what lets a fresh clone restore byte-identical
    guides that still satisfy the committed manifest's integrity hashes."""
    import io

    buf = io.BytesIO()
    images[key].save(buf, format="PNG")
    assert hashlib.sha256(buf.getvalue()).hexdigest() == EXPECTED_SHA256[key], (
        f"{key} render changed — update EXPECTED_SHA256 and re-register the guide, "
        "and re-check the pose still depicts the intended action"
    )


def test_expected_hashes_cover_the_whole_catalog():
    assert set(EXPECTED_SHA256) == set(POSE_GUIDE_KEYS)


def test_guide_metadata_is_routable_under_its_own_profile(mod):
    """Every declared guide must actually pass guide_compatible for the profile
    it is meant to serve, or the catalog ships an unusable entry."""
    for key, meta in mod.GUIDE_META.items():
        profile = meta["control_type"]
        assert guide_compatible(profile, meta["schema"], meta["anatomy"]), key


def test_humanoid_guides_are_coco18_and_creature_guides_are_not(mod):
    """AC6: a creature guide carrying a human keypoint schema is the exact
    failure this story exists to prevent."""
    for key, meta in mod.GUIDE_META.items():
        if key.startswith("humanoid_"):
            assert meta["schema"] == "coco18" and meta["anatomy"] == "humanoid", key
        else:
            assert meta["schema"] == "silhouette" and meta["anatomy"] == "non_humanoid", key


def test_humanoid_skeletons_keep_consistent_limb_lengths(mod):
    """Angle-driven forward kinematics exists so limb lengths cannot drift between
    poses. Verify it: after the uniform canvas fit, each pose's femur/shin/upper-arm
    ratios must match the shared limb table.
    """
    for key, angles in mod.HUMANOID_POSES.items():
        kp = mod.fit_to_canvas(mod.build_skeleton(**angles))

        def seg(a, b, _kp=kp):
            (x1, y1), (x2, y2) = _kp[a], _kp[b]
            return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

        # Left/right of the same bone must be identical in every pose.
        assert seg("r_hip", "r_knee") == pytest.approx(seg("l_hip", "l_knee"), rel=1e-6), key
        assert seg("r_knee", "r_ankle") == pytest.approx(seg("l_knee", "l_ankle"), rel=1e-6), key
        assert seg("r_shoulder", "r_elbow") == pytest.approx(seg("l_shoulder", "l_elbow"), rel=1e-6), key
        # Thigh and shin are equal length in the limb table, so their ratio is a
        # scale-free check that survives the per-pose canvas fit.
        assert seg("r_hip", "r_knee") == pytest.approx(seg("r_knee", "r_ankle"), rel=1e-6), key
        assert seg("r_shoulder", "r_elbow") / seg("r_elbow", "r_wrist") == pytest.approx(
            mod.UPPER_ARM / mod.FOREARM, rel=1e-6,
        ), key


def test_no_pose_is_merely_the_standing_reference(mod):
    """AC5: a guide must depict the requested action. Extracting/reusing the
    standing card's own skeleton would restate the pose the card already has, so
    every authored pose must differ materially from an upright A-pose.
    """
    upright = dict(
        head=-90, torso=90, r_upper=95, r_fore=93, l_upper=85, l_fore=87,
        r_thigh=88, r_shin=90, l_thigh=92, l_shin=90,
    )
    ref = mod.fit_to_canvas(mod.build_skeleton(**upright))
    for key, angles in mod.HUMANOID_POSES.items():
        kp = mod.fit_to_canvas(mod.build_skeleton(**angles))
        drift = max(((kp[j][0] - ref[j][0]) ** 2 + (kp[j][1] - ref[j][1]) ** 2) ** 0.5 for j in mod.COCO18)
        assert drift > 100, f"{key} is within {drift:.0f}px of a plain standing pose"


def test_all_keypoints_stay_inside_the_canvas(images, mod):
    """build_all() asserts this internally; assert it here too so the guarantee is
    a test failure rather than a stack trace in a render script."""
    for key, angles in mod.HUMANOID_POSES.items():
        kp = mod.fit_to_canvas(mod.build_skeleton(**angles))
        for joint, (x, y) in kp.items():
            assert 0 <= x < mod.W and 0 <= y < mod.H, f"{key}/{joint}"


def test_guides_have_ink_on_a_black_field(images):
    """A guide that renders empty (or fully white) is not a control signal."""
    for key, im in images.items():
        colours = im.convert("RGB").getcolors(maxcolors=1 << 24) or []
        lit = sum(count for count, rgb in colours if rgb != (0, 0, 0))
        assert lit > 0, f"{key} rendered blank"
        assert lit < im.size[0] * im.size[1] * 0.5, f"{key} is mostly ink, not a skeleton"
