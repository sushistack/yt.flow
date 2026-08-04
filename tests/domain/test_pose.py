"""Unit tests for domain.pose — conditioning vocabulary, guide compatibility, fingerprint (Story 8.20)."""

import pytest

from yt_flow.domain.pose import (
    DEFAULT_POSE_CONDITIONING,
    FINGERPRINT_FIELDS,
    POSE_CONDITIONING_PROFILES,
    POSE_GUIDE_ALIASES,
    POSE_GUIDE_KEYS,
    PROFILE_ANATOMY,
    PROFILE_SCHEMAS,
    MissingFingerprintInput,
    canonical_guide_key,
    guide_compatible,
    pose_fingerprint,
)


def _fp_inputs(**overrides):
    base: dict[str, object] = {f: f"{f}-value" for f in FINGERPRINT_FIELDS}
    base.update(width=832, height=1216)
    base.update(overrides)
    return base


# ── Vocabulary invariants (AC4) ─────────────────────────────────────────────


def test_default_conditioning_is_the_no_guide_route():
    """The safe default must be edit_only — anything else would apply structural
    conditioning to an uncurated character."""
    assert DEFAULT_POSE_CONDITIONING == "edit_only"
    assert DEFAULT_POSE_CONDITIONING in POSE_CONDITIONING_PROFILES


def test_every_profile_declares_schemas_and_edit_only_accepts_none():
    assert set(PROFILE_SCHEMAS) == set(POSE_CONDITIONING_PROFILES)
    assert PROFILE_SCHEMAS["edit_only"] == frozenset()


def test_every_guide_accepting_profile_declares_an_anatomy():
    """A profile that can consume a guide must say which body it describes, or
    guide_compatible could never reject a human skeleton on a creature."""
    for profile, schemas in PROFILE_SCHEMAS.items():
        if schemas:
            assert profile in PROFILE_ANATOMY, profile


def test_openpose_is_the_only_humanoid_profile():
    """AC6: a human COCO-18 skeleton must never reach a non-humanoid route."""
    humanoid = [p for p, a in PROFILE_ANATOMY.items() if a == "humanoid"]
    assert humanoid == ["openpose"]
    assert PROFILE_SCHEMAS["openpose"] == frozenset({"coco18"})


def test_no_creature_profile_accepts_coco18():
    for profile in ("depth", "lineart", "scribble"):
        assert "coco18" not in PROFILE_SCHEMAS[profile], profile


# ── Guide key canonicalization (AC5) ────────────────────────────────────────


@pytest.mark.parametrize("raw", ["humanoid_kneeling", "HUMANOID_KNEELING", " humanoid-kneeling ", "Humanoid Kneeling"])
def test_canonical_guide_key_is_case_space_and_hyphen_tolerant(raw):
    assert canonical_guide_key(raw) == "humanoid_kneeling"


def test_canonical_guide_key_resolves_operator_aliases():
    assert canonical_guide_key("reaching") == "humanoid_reaching_forward"
    assert canonical_guide_key("lying_on_floor") == "humanoid_lying_supine"


def test_every_alias_targets_a_real_catalog_key():
    """A dangling alias would silently degrade to edit_only for an operator who
    used the documented synonym."""
    for alias, target in POSE_GUIDE_ALIASES.items():
        assert target in POSE_GUIDE_KEYS, f"{alias} -> {target}"


def test_no_alias_shadows_a_canonical_key():
    assert not set(POSE_GUIDE_ALIASES) & set(POSE_GUIDE_KEYS)


@pytest.mark.parametrize("raw", [None, 42, "", "   ", "kneeling over a corpse", "humanoid_backflip", ["kneeling"]])
def test_canonical_guide_key_rejects_everything_outside_the_catalog(raw):
    """Notably a free-text pose_hint ("kneeling over a corpse") is NOT a guide
    key — AC5 forbids mapping hints to guides heuristically."""
    assert canonical_guide_key(raw) is None


def test_guide_key_naming_matches_declared_anatomy():
    """The prompt teaches "creature_* for non-human, humanoid_* for human", so
    the prefix has to stay honest or the LLM's choice is misled."""
    for key in POSE_GUIDE_KEYS:
        assert key.startswith(("humanoid_", "creature_")), key


# ── Compatibility gating (AC6) ──────────────────────────────────────────────


def test_humanoid_coco18_guide_is_compatible_with_openpose():
    assert guide_compatible("openpose", "coco18", "humanoid") is True


def test_human_skeleton_is_rejected_by_every_creature_profile():
    for profile in ("depth", "lineart", "scribble"):
        assert guide_compatible(profile, "coco18", "humanoid") is False, profile


def test_creature_silhouette_is_rejected_by_openpose():
    assert guide_compatible("openpose", "silhouette", "non_humanoid") is False


def test_matching_schema_but_wrong_anatomy_is_rejected():
    """Both axes are checked: a humanoid-anatomy silhouette still describes the
    wrong body on a creature route."""
    assert guide_compatible("scribble", "silhouette", "humanoid") is False


def test_edit_only_accepts_no_guide_at_all():
    for schema, anatomy in (("coco18", "humanoid"), ("silhouette", "non_humanoid")):
        assert guide_compatible("edit_only", schema, anatomy) is False


def test_unknown_profile_is_rejected_rather_than_defaulting_open():
    assert guide_compatible("bogus_profile", "coco18", "humanoid") is False


# ── Fingerprint (AC9) ───────────────────────────────────────────────────────


def test_fingerprint_is_stable_and_kwarg_order_independent():
    a = pose_fingerprint(**_fp_inputs())
    inputs = _fp_inputs()
    b = pose_fingerprint(**dict(reversed(list(inputs.items()))))
    assert a == b
    assert len(a) == 64


@pytest.mark.parametrize("field", FINGERPRINT_FIELDS)
def test_changing_any_single_field_changes_the_fingerprint(field):
    """The whole point of AC9: no input that can change the pixels may be
    invisible to the cache key."""
    base = pose_fingerprint(**_fp_inputs())
    assert pose_fingerprint(**_fp_inputs(**{field: "MUTATED"})) != base


@pytest.mark.parametrize("field", FINGERPRINT_FIELDS)
def test_missing_any_field_fails_closed(field):
    inputs = _fp_inputs()
    del inputs[field]
    with pytest.raises(MissingFingerprintInput, match=field):
        pose_fingerprint(**inputs)


def test_unknown_field_is_rejected_so_a_typo_cannot_escape_the_hash():
    with pytest.raises(MissingFingerprintInput, match="workflow_sha"):
        pose_fingerprint(**_fp_inputs(), workflow_sha="typo-of-workflow_sha256")


def test_env_snapshot_is_a_required_fingerprint_input():
    """Story 13.3 owns the environment snapshot. Keeping it required is what
    forces the wiring instead of letting a custom-node upgrade serve stale
    cards forever."""
    assert "env_snapshot_sha256" in FINGERPRINT_FIELDS
