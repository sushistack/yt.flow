"""Pose conditioning vocabulary + guide catalog + cache fingerprint (Story 8.20).

Lives in ``domain/`` because three layers need the same closed vocabularies and
none of them may import each other: ``db`` (Character.pose_conditioning column),
``pipeline`` (cast parser validating ``pose_guide_key``), and ``services``
(AssetService guide lifecycle, PoseService routing). [AD-1]

Nothing here does I/O or knows about ComfyUI. Approval status, file bytes, and
integrity hashes are AssetService's authority (AC5: one manifest, no second
registry) — this module only declares what a legal value *is*.
"""

import hashlib
import json
from typing import Literal

# ── Conditioning profiles (AC4) ──────────────────────────────────────────────
# Durable character-level catalog data on Character.pose_conditioning. Routing
# reads this column and nothing else: inferring anatomy from a card key or a
# descriptor keyword is forbidden (AC4), because "SCP-1471" and "SCP-096" are
# indistinguishable as strings yet need opposite structural routes.
PoseConditioning = Literal["openpose", "depth", "lineart", "scribble", "edit_only"]
POSE_CONDITIONING_PROFILES: tuple[str, ...] = ("openpose", "depth", "lineart", "scribble", "edit_only")

# The safe default for every creation path and every unknown/invalid value:
# reference-only editing, which needs no guide and can never apply a human
# skeleton to a non-human body (AC6).
DEFAULT_POSE_CONDITIONING = "edit_only"

# ── Guide keypoint schemas (AC6) ─────────────────────────────────────────────
# A guide raster is only legal for a profile whose accepted schema it matches.
# COCO-18 is a *human* ontology — its 18 keypoints name eyes, ears, and a
# two-arm/two-leg topology that does not exist on a reptile — so a
# ``coco18`` guide is never compatible with a non-humanoid profile.
PoseSchema = Literal["coco18", "silhouette"]

# profile -> the guide schemas that profile may consume. ``edit_only`` accepts
# nothing: it is the no-guide route by definition, so a cast entry naming both
# ``edit_only`` and a guide key is a contradiction that degrades to no guide.
PROFILE_SCHEMAS: dict[str, frozenset[str]] = {
    "openpose": frozenset({"coco18"}),
    "depth": frozenset({"silhouette"}),
    "lineart": frozenset({"silhouette"}),
    "scribble": frozenset({"silhouette"}),
    "edit_only": frozenset(),
}

# Anatomy class a guide depicts. Enforced against the profile so no human
# skeleton can reach a creature card even if an operator names the wrong key.
PoseAnatomy = Literal["humanoid", "non_humanoid"]

PROFILE_ANATOMY: dict[str, str] = {
    "openpose": "humanoid",
    "depth": "non_humanoid",
    "lineart": "non_humanoid",
    "scribble": "non_humanoid",
}

# ── Guide catalog (AC5) ──────────────────────────────────────────────────────
# The closed vocabulary the cast prompt selects from and the parser validates
# against. Membership here means "this key is spellable", NOT "this guide is
# usable" — usability additionally requires an approved, integrity-verified
# AssetService entry, which only the service layer can check.
#
# The set is deliberately small and demand-driven: these cover the structural
# `pose_hint` values actually observed in production checkpoints (2075
# checkpoints scanned: "lying on floor" 24, "reaching toward camera" 24,
# "collapsed" 12, "extending hand" 12, "kneeling over a corpse" 12). The
# remaining observed hints ("head bowed", "shaking head", "looking at camera")
# are head-level, not skeletal, and route to edit_only with no guide — a guide
# for them would constrain the whole body to say something about a neck.
POSE_GUIDE_KEYS: tuple[str, ...] = (
    "humanoid_reaching_forward",
    "humanoid_lying_supine",
    "humanoid_kneeling",
    "humanoid_collapsed",
    "creature_prone_lunge",
    "creature_rearing",
)

# Operator-discovery aliases -> canonical key. Not inference: this maps the
# *guide catalog's own* synonyms so an operator naming a guide by a near-miss
# gets the guide instead of a silent edit_only downgrade. It never maps a
# free-text `pose_hint` to a guide (AC5 forbids that heuristic).
POSE_GUIDE_ALIASES: dict[str, str] = {
    "reaching": "humanoid_reaching_forward",
    "reaching_toward_camera": "humanoid_reaching_forward",
    "extending_hand": "humanoid_reaching_forward",
    "lying": "humanoid_lying_supine",
    "lying_on_floor": "humanoid_lying_supine",
    "supine": "humanoid_lying_supine",
    "kneeling": "humanoid_kneeling",
    "collapsed": "humanoid_collapsed",
    "slumped": "humanoid_collapsed",
    "lunging": "creature_prone_lunge",
    "prone_lunge": "creature_prone_lunge",
    "rearing": "creature_rearing",
}


def canonical_guide_key(raw: object) -> str | None:
    """Return the canonical guide key for ``raw``, or ``None`` if unspellable.

    Case/whitespace/hyphen tolerant so a prompt or operator typo lands on the
    catalog entry rather than degrading silently. Returns ``None`` for anything
    outside the closed catalog — the caller decides whether that warns.
    """
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in POSE_GUIDE_KEYS:
        return key
    return POSE_GUIDE_ALIASES.get(key)


def guide_compatible(profile: str, schema: str, anatomy: str) -> bool:
    """True when a guide of (``schema``, ``anatomy``) may be used by ``profile``.

    Both axes must agree. Schema alone is not enough: ``silhouette`` is legal
    for the creature profiles, but a humanoid-anatomy silhouette on a
    ``scribble`` creature profile still describes the wrong body.
    """
    if profile not in PROFILE_SCHEMAS:
        return False
    if schema not in PROFILE_SCHEMAS[profile]:
        return False
    return PROFILE_ANATOMY.get(profile) == anatomy


# ── Cache fingerprint (AC9) ──────────────────────────────────────────────────
# Every input that can change the pixels must be in the fingerprint, or a
# cached card outlives the thing that produced it. Story 8.15's lesson in
# concrete form: a swapped model with an unchanged cache key serves stale
# output forever.
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "engine",              # e.g. "comfyui-0.12.3"
    "workflow_sha256",     # the API-format workflow JSON as committed
    "model",               # diffusion model file identity
    "quantization",        # Q4_K_M vs Q5_* changes output
    "lora",                # Lightning-4step vs none changes steps/cfg AND output
    "guide",               # guide key + content hash, or "" for edit_only
    "conditioning_profile",
    "reference_sha256",    # the approved source card's bytes
    "preprocessor",
    "postprocessor",       # alpha cleanup / subject-scale normalization contract
    "env_snapshot_sha256",  # Story 13.3's custom-node/environment snapshot
    "width",
    "height",
    "seed_policy",         # how the seed is derived, not the seed value
)


class MissingFingerprintInput(ValueError):
    """A fingerprint input was absent. Fails closed rather than hashing a
    partial identity, which would collide across genuinely different renders."""


def pose_fingerprint(**inputs: object) -> str:
    """Hash the complete AC9 provenance identity of a pose render.

    Every field in ``FINGERPRINT_FIELDS`` is required — a missing one raises
    rather than defaulting, because a silently-omitted field is precisely how a
    stale card passes a freshness check. Extra fields are also rejected so a
    typo'd kwarg cannot quietly land outside the hash.

    ``env_snapshot_sha256`` is Story 13.3's environment snapshot. 13.3 is not
    implemented yet, so no production caller exists — this function is the
    contract that forces the wiring rather than letting it be forgotten.
    """
    missing = [f for f in FINGERPRINT_FIELDS if f not in inputs]
    if missing:
        raise MissingFingerprintInput(f"pose fingerprint missing required inputs: {sorted(missing)}")
    extra = [k for k in inputs if k not in FINGERPRINT_FIELDS]
    if extra:
        raise MissingFingerprintInput(f"pose fingerprint got unknown inputs: {sorted(extra)}")
    # sort_keys so kwarg order can never change the hash.
    payload = json.dumps({f: inputs[f] for f in FINGERPRINT_FIELDS}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
