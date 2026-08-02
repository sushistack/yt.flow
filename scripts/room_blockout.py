"""Procedural room blockout line art for ControlNet scribble conditioning.

Composition is not something a text prompt controls. Describing rooms in words produced
a library that was 95% one identical receding corridor, and adding camera wording and
room-shape wording only brought it to 81% — the checkpoint's spatial prior for
"facility" wins. The standard fix in architectural visualisation is to stop asking:
feed the generator a grey-box blockout and let the prompt supply only subject and style.

This draws that blockout — a box room's structural edges under a pinhole camera — so
each (location, variant) gets a deterministic, genuinely different geometry.

# ponytail: a hand-rolled projection of one axis-aligned box, not a 3D library. A room
# is six planes; importing a renderer to draw twelve lines would be the larger cost.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    """Pinhole camera inside the room. Angles in degrees, positions in room units."""

    x: float = 0.0          # lateral position, 0 = room centre
    z: float = -0.9         # distance back from the room centre (negative = toward viewer)
    height: float = 0.55    # eye height as a fraction of room height
    yaw: float = 0.0        # rotation about vertical; 0 = facing the far wall
    pitch: float = 0.0      # positive = looking up
    fov: float = 60.0


# Each shot is a different place to stand, so the geometry differs rather than the
# wording. Named for what the verifier reports back, so a failure maps to a knob.
SHOTS: dict[str, Camera] = {
    # Square-on but far enough back that the far wall is a wall, not a vanishing point.
    "wide-room-from-doorway": Camera(x=0.0, z=-1.15, height=0.55, yaw=0.0, fov=62.0),
    # Standing in a corner: two walls recede at different rates, which is what kills
    # the one-point look.
    "corner-three-quarter": Camera(x=-0.62, z=-0.95, height=0.45, yaw=26.0, pitch=4.0, fov=66.0),
    # Close and off-axis, so one wall dominates and the far wall is cropped.
    "close-detail-offset": Camera(x=0.5, z=-0.25, height=0.5, yaw=-30.0, fov=70.0),
    # Deliberate corridor, for the two locations that really are corridors.
    "corridor": Camera(x=0.0, z=-1.6, height=0.5, yaw=0.0, fov=55.0),
}


def _project(p, cam: Camera, w: int, h: int):
    """Room-space point -> pixel, or None when behind the camera."""
    x, y, z = p[0] - cam.x, p[1] - cam.height, p[2] - cam.z
    yaw, pitch = math.radians(cam.yaw), math.radians(cam.pitch)
    x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
    y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
    if z <= 0.05:
        return None
    f = (w / 2) / math.tan(math.radians(cam.fov) / 2)
    return (w / 2 + f * x / z, h / 2 - f * y / z)


def _box_edges(depth: float):
    """The twelve edges of a unit-width, unit-high room extending `depth` away."""
    x0, x1, y0, y1, z0, z1 = -0.5, 0.5, 0.0, 1.0, 0.0, depth
    c = {(i, j, k): (x0 if i == 0 else x1, y0 if j == 0 else y1, z0 if k == 0 else z1)
         for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    edges = []
    for a, b in [((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 1, 0)), ((0, 0, 1), (1, 0, 1)),
                 ((0, 1, 1), (1, 1, 1)), ((0, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0)),
                 ((0, 0, 1), (0, 1, 1)), ((1, 0, 1), (1, 1, 1)), ((0, 0, 0), (0, 0, 1)),
                 ((1, 0, 0), (1, 0, 1)), ((0, 1, 0), (0, 1, 1)), ((1, 1, 0), (1, 1, 1))]:
        edges.append((c[a], c[b]))
    return edges


def render_blockout(shot: str, depth: float, width: int, height: int, line: int = 5) -> bytes:
    """White-on-black structural line art of a room, as PNG bytes.

    ``depth`` is how far the room runs back in units of its width: ~1.0 reads as a
    square room, ~4.0 as a corridor.
    """
    import io

    from PIL import Image, ImageDraw

    cam = SHOTS[shot]
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for a, b in _box_edges(depth):
        pa, pb = _project(a, cam, width, height), _project(b, cam, width, height)
        if pa and pb:
            draw.line([pa, pb], fill=(255, 255, 255), width=line)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":  # smoke check: every shot must draw something visible
    import numpy as np
    from PIL import Image
    import io

    for name in SHOTS:
        arr = np.array(Image.open(io.BytesIO(render_blockout(name, 1.4, 512, 288))).convert("L"))
        lit = int((arr > 128).sum())
        assert lit > 500, f"{name} drew almost nothing ({lit} px)"
        print(f"{name:26s} {lit:6d} lit px")
