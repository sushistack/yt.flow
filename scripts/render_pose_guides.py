#!/usr/bin/env python
"""Render + register the Story 8.20 structural pose-guide set.

Why this exists as authored data rather than extracted skeletons: a guide must
depict *the requested action*, and the only skeletons available to extract are
the approved standing cards — feeding one of those back in would restate the
pose the card already has (AC5 forbids exactly that). The MIT VNCCS poseset was
evaluated as a source and rejected for the same reason: all 12 of its poses are
standing character-sheet variants.

Poses are authored as joint ANGLES and resolved by forward kinematics from a
single limb-length table, so every pose is anatomically consistent by
construction — a hand-typed (x, y) table can silently grow a 400px femur.

Run: uv run python scripts/render_pose_guides.py [--out assets] [--no-register]
Output is deterministic; re-running rewrites byte-identical PNGs.
"""

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.db import get_engine, init  # noqa: E402
from yt_flow.domain.pose import POSE_GUIDE_KEYS  # noqa: E402

# ── Canvas ───────────────────────────────────────────────────────────────────
# Matches character_image_width x character_image_height so guide geometry maps
# onto the reference card 1:1 with no rescale (same reason the workflow omits
# FluxKontextImageScale).
W, H = 832, 1216

# ── Limb lengths (px) ────────────────────────────────────────────────────────
# Proportions taken from the VNCCS 512x1536 reference skeleton (MIT) and scaled
# to this canvas; only the ratios are borrowed, no pose data.
HEAD = 116.0        # neck -> nose
SHOULDER = 60.0     # neck -> shoulder (half-width)
UPPER_ARM = 160.0
FOREARM = 124.0
TORSO = 280.0       # neck -> mid-hip
HIP = 46.0          # mid-hip -> hip (half-width)
THIGH = 264.0
SHIN = 264.0

# Canonical OpenPose COCO-18 limb colours (right = warm, left = cool). The
# palette is part of the control signal, not decoration — a preprocessor-trained
# model reads left/right from hue.
BONES: tuple[tuple[str, str, tuple[int, int, int]], ...] = (
    ("nose", "neck", (0, 0, 255)),
    ("neck", "r_shoulder", (255, 0, 0)),
    ("r_shoulder", "r_elbow", (255, 170, 0)),
    ("r_elbow", "r_wrist", (255, 255, 0)),
    ("neck", "l_shoulder", (255, 85, 0)),
    ("l_shoulder", "l_elbow", (0, 255, 0)),
    ("l_elbow", "l_wrist", (0, 255, 85)),
    ("neck", "r_hip", (0, 255, 0)),
    ("r_hip", "r_knee", (85, 255, 0)),
    ("r_knee", "r_ankle", (2, 153, 102)),
    ("neck", "l_hip", (0, 255, 170)),
    ("l_hip", "l_knee", (0, 255, 255)),
    ("l_knee", "l_ankle", (0, 0, 255)),
    ("nose", "r_eye", (170, 0, 255)),
    ("r_eye", "r_ear", (255, 0, 170)),
    ("nose", "l_eye", (170, 0, 255)),
    ("l_eye", "l_ear", (255, 0, 170)),
)

COCO18 = (
    "nose", "neck", "r_shoulder", "r_elbow", "r_wrist", "l_shoulder", "l_elbow", "l_wrist",
    "r_hip", "r_knee", "r_ankle", "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear",
)


def _polar(origin: tuple[float, float], length: float, deg: float) -> tuple[float, float]:
    """Screen-space polar step: 0deg = +x (right), 90deg = +y (down)."""
    rad = math.radians(deg)
    return (origin[0] + length * math.cos(rad), origin[1] + length * math.sin(rad))


def build_skeleton(
    *, head: float, torso: float,
    r_upper: float, r_fore: float, l_upper: float, l_fore: float,
    r_thigh: float, r_shin: float, l_thigh: float, l_shin: float,
    rotate: float = 0.0,
) -> dict[str, tuple[float, float]]:
    """Forward-kinematics a COCO-18 skeleton from joint angles (degrees).

    ``rotate`` turns the whole body (used for the lying pose, so a horizontal
    figure keeps identical limb lengths to a standing one).
    """
    def a(deg: float) -> float:
        return deg + rotate

    neck = (0.0, 0.0)
    nose = _polar(neck, HEAD, a(head))
    # Eyes/ears sit around the nose on the head axis; small fixed offsets keep
    # the face readable without a second angle table.
    face = a(head)
    r_eye = _polar(nose, 26, face - 115)
    l_eye = _polar(nose, 26, face - 65)
    r_ear = _polar(nose, 46, face - 140)
    l_ear = _polar(nose, 46, face - 40)

    shoulder_axis = a(0)
    r_shoulder = _polar(neck, SHOULDER, shoulder_axis + 180)
    l_shoulder = _polar(neck, SHOULDER, shoulder_axis)
    r_elbow = _polar(r_shoulder, UPPER_ARM, a(r_upper))
    r_wrist = _polar(r_elbow, FOREARM, a(r_fore))
    l_elbow = _polar(l_shoulder, UPPER_ARM, a(l_upper))
    l_wrist = _polar(l_elbow, FOREARM, a(l_fore))

    mid_hip = _polar(neck, TORSO, a(torso))
    r_hip = _polar(mid_hip, HIP, shoulder_axis + 180)
    l_hip = _polar(mid_hip, HIP, shoulder_axis)
    r_knee = _polar(r_hip, THIGH, a(r_thigh))
    r_ankle = _polar(r_knee, SHIN, a(r_shin))
    l_knee = _polar(l_hip, THIGH, a(l_thigh))
    l_ankle = _polar(l_knee, SHIN, a(l_shin))

    return {
        "nose": nose, "neck": neck, "r_eye": r_eye, "l_eye": l_eye, "r_ear": r_ear, "l_ear": l_ear,
        "r_shoulder": r_shoulder, "r_elbow": r_elbow, "r_wrist": r_wrist,
        "l_shoulder": l_shoulder, "l_elbow": l_elbow, "l_wrist": l_wrist,
        "r_hip": r_hip, "r_knee": r_knee, "r_ankle": r_ankle,
        "l_hip": l_hip, "l_knee": l_knee, "l_ankle": l_ankle,
    }


def fit_to_canvas(kp: dict[str, tuple[float, float]], margin: int = 60) -> dict[str, tuple[float, float]]:
    """Translate + uniformly scale so the figure fills the canvas inside ``margin``.

    Uniform scale only: a per-axis stretch would change the very proportions the
    angle-driven construction exists to preserve.
    """
    xs = [p[0] for p in kp.values()]
    ys = [p[1] for p in kp.values()]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    scale = min((W - 2 * margin) / max(span_x, 1e-6), (H - 2 * margin) / max(span_y, 1e-6))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return {k: ((x - cx) * scale + W / 2, (y - cy) * scale + H / 2) for k, (x, y) in kp.items()}


def render_openpose(kp: dict[str, tuple[float, float]]) -> Image.Image:
    im = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(im)
    for a, b, colour in BONES:
        dr.line([kp[a], kp[b]], fill=colour, width=14)
    for name in COCO18:
        x, y = kp[name]
        dr.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255))
    return im


def render_scribble(strokes: tuple[tuple[tuple[float, float], ...], ...], width: int = 34) -> Image.Image:
    """Crude white-on-black silhouette scribble for non-humanoid anatomy.

    No keypoints and no palette: a creature has no COCO-18 ontology to encode,
    so the guide carries silhouette and nothing else.
    """
    im = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(im)
    for stroke in strokes:
        dr.line(stroke, fill=(255, 255, 255), width=width, joint="curve")
    return im


# ── The catalog ──────────────────────────────────────────────────────────────
# Angles are screen-space degrees: 90 = straight down, 0 = to the right.
HUMANOID_POSES: dict[str, dict] = {
    # "reaching toward camera" (24 production placements) + "extending hand" (12).
    # The reach is on the LEFT limb: l_shoulder sits on the screen-right side
    # (the figure faces the viewer), so the arm extends outward instead of
    # crossing back over the torso.
    "humanoid_reaching_forward": dict(
        head=-88, torso=90,
        r_upper=98, r_fore=94, l_upper=2, l_fore=-4,
        r_thigh=87, r_shin=89, l_thigh=95, l_shin=91,
    ),
    # "lying on floor" (24). Same skeleton, rotated 90deg — a horizontal figure
    # built from its own angle table drifts out of proportion with the others.
    #
    # 2026-08-16, Jay on the Story 10.8 live gate: "누워있는데 팔이 너무 벌려져 있는 것".
    # The arms were the widest in the catalog by 3-4x — measured as the included angle
    # between the two limbs, this pose was 47deg at the upper arms and 70deg at the
    # forearms, against `humanoid_collapsed`'s 12deg ("arms slack at the sides") and
    # `humanoid_kneeling`'s 16deg. The rendered card came out spread like a starfish,
    # with an alpha bbox of w/h 2.15 that spanned the full 832px canvas width and
    # clipped the head and one boot at the frame edges.
    # Brought to 18deg / 26deg: arms near the body as a figure on an operating table
    # holds them, still parted enough to read as separate limbs rather than one mass.
    # These four numbers are the whole knob — widen or narrow them symmetrically about
    # 90 (straight down, pre-rotation) if the next render wants a different spread.
    "humanoid_lying_supine": dict(
        head=-96, torso=90,
        r_upper=100, r_fore=104, l_upper=82, l_fore=78,
        r_thigh=86, r_shin=94, l_thigh=97, l_shin=88,
        rotate=-90,
    ),
    # "kneeling over a corpse" (12): torso pitched forward, knee on the ground,
    # shin folded back horizontally behind it, arms reaching down.
    # "kneeling over a corpse" (12): femur vertical with the hip stacked above
    # the knee, shin lying flat on the ground behind it, torso pitched forward.
    # The knee — not the ankle — is the ground contact; that is what separates
    # kneeling from a deep forward bend.
    "humanoid_kneeling": dict(
        head=-46, torso=74,
        r_upper=80, r_fore=64, l_upper=96, l_fore=102,
        r_thigh=92, r_shin=181, l_thigh=99, l_shin=173,
    ),
    # "collapsed" (12): sat down hard, torso pitched back, knees up with the feet
    # planted, arms slack at the sides.
    "humanoid_collapsed": dict(
        head=-62, torso=118,
        r_upper=112, r_fore=98, l_upper=100, l_fore=88,
        r_thigh=8, r_shin=88, l_thigh=20, l_shin=78,
    ),
}

# Non-humanoid silhouettes, authored in canvas coordinates. Deliberately crude:
# a scribble control signal wants gesture, not detail.
CREATURE_SCRIBBLES: dict[str, tuple[tuple[tuple[float, float], ...], ...]] = {
    # Low, long, lunging quadruped (SCP-682 archetype): head forward and low,
    # heavy body, tail counterweight.
    "creature_prone_lunge": (
        ((110, 700), (250, 660), (430, 650), (610, 680), (720, 760), (770, 860)),   # spine + tail
        ((110, 700), (70, 740), (120, 780), (210, 770)),                            # head / jaw
        ((300, 660), (280, 800), (330, 900)),                                        # front leg near
        ((400, 655), (430, 800), (390, 900)),                                        # front leg far
        ((580, 680), (610, 820), (560, 910)),                                        # hind leg near
        ((650, 700), (700, 830), (660, 915)),                                        # hind leg far
    ),
    # Reared up: quadruped torso pitched near-vertical, forelimbs off the ground,
    # weight on the hind legs, heavy tail braced behind. Kept unmistakably
    # non-bipedal — a vertical spine with two raised arms would read humanoid and
    # defeat the point of a separate creature guide.
    "creature_rearing": (
        ((330, 250), (370, 430), (430, 620), (500, 790), (560, 900)),                # spine, pitched
        ((330, 250), (250, 190), (190, 250), (275, 305)),                            # head + jaw
        ((250, 190), (200, 140)),                                                    # horn / crest
        ((375, 445), (250, 470), (170, 410)),                                        # foreleg near, raised
        ((390, 480), (290, 580), (215, 545)),                                        # foreleg far, raised
        ((505, 800), (455, 940), (490, 1060)),                                       # hind leg near
        ((525, 815), (620, 950), (600, 1065)),                                       # hind leg far
        ((560, 900), (690, 930), (780, 1010)),                                       # tail brace
    ),
}

GUIDE_META = {
    **{k: {"schema": "coco18", "anatomy": "humanoid", "control_type": "openpose"} for k in HUMANOID_POSES},
    **{k: {"schema": "silhouette", "anatomy": "non_humanoid", "control_type": "scribble"}
       for k in CREATURE_SCRIBBLES},
}


def build_all() -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for key, angles in HUMANOID_POSES.items():
        kp = fit_to_canvas(build_skeleton(**angles))
        for name in COCO18:  # every COCO-18 point must exist or the schema claim is a lie
            assert name in kp, f"{key} missing keypoint {name}"
        for name, (x, y) in kp.items():
            assert 0 <= x < W and 0 <= y < H, f"{key} keypoint {name} outside canvas at ({x:.1f}, {y:.1f})"
        images[key] = render_openpose(kp)
    for key, strokes in CREATURE_SCRIBBLES.items():
        for stroke in strokes:
            for x, y in stroke:
                assert 0 <= x < W and 0 <= y < H, f"{key} stroke point outside canvas at ({x}, {y})"
        images[key] = render_scribble(strokes)
    assert set(images) == set(POSE_GUIDE_KEYS), (
        f"rendered set != declared catalog: {sorted(set(images) ^ set(POSE_GUIDE_KEYS))}"
    )
    return images


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="asset root (default: settings.assets_path)")
    ap.add_argument("--no-register", action="store_true", help="render PNGs only, skip the manifest")
    ap.add_argument("--contact-sheet", default=None, help="also write a review contact sheet here")
    args = ap.parse_args()

    settings = Settings()
    root = Path(args.out or settings.assets_path)
    (root / "pose_guides").mkdir(parents=True, exist_ok=True)

    images = build_all()
    for key, im in images.items():
        im.save(root / "pose_guides" / f"{key}.png")
        print(f"rendered pose_guides/{key}.png  {im.size}")

    if args.contact_sheet:
        tw, th = W // 4, H // 4
        sheet = Image.new("RGB", (tw * len(images), th), "black")
        for i, key in enumerate(POSE_GUIDE_KEYS):
            sheet.paste(images[key].resize((tw, th)), (i * tw, 0))
        Path(args.contact_sheet).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.contact_sheet)
        print(f"contact sheet -> {args.contact_sheet}")

    if args.no_register:
        return 0

    from sqlmodel import Session

    from yt_flow.services.asset_service import AssetService

    init(f"sqlite:///{settings.db_path}")
    with Session(get_engine()) as session:
        svc = AssetService(root, session)
        for key in POSE_GUIDE_KEYS:
            meta = GUIDE_META[key]
            svc.add_pose_guide(
                key, f"pose_guides/{key}.png",
                schema=meta["schema"], anatomy=meta["anatomy"], control_type=meta["control_type"],
                source={
                    "type": "authored_diagram",
                    "generator": "scripts/render_pose_guides.py",
                    "license": "CC0-1.0",
                    "proportion_reference": "ComfyUI_VNCCS presets/poses (MIT) — limb ratios only, no pose data",
                },
            )
            svc.approve_pose_guide(key)
            print(f"registered + approved pose_guide/{key}  ({meta['control_type']}/{meta['anatomy']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
