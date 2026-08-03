"""Standalone DepthFlow runner — executed by the ISOLATED DepthFlow virtualenv.

This file is deliberately import-free with respect to ``yt_flow``: it runs under
a different interpreter, in a different environment, with AGPL-3.0 dependencies
that must never enter yt.flow's own dependency graph
(see ``docs/PARALLAX_RUNTIME.md`` for the compliance decision).

Contract — ``parallax_service._render_depthflow`` writes a JSON spec::

    {"image": str, "depth": str, "output": str,
     "width": int, "height": int, "fps": int, "far_gain": float,
     "samples": [[t, x, y, rot, zoom], ...]}   # x/y are fractions of WIDTH

Exit codes are the adapter's failure taxonomy:

* ``0`` — the output file was written.
* ``3`` — DepthFlow is not importable, or its API surface does not match what
  this runner drives. Classified ``unavailable``: the adapter degrades to the
  depth-warp renderer and logs it, rather than reporting a render failure for
  what is really an install/version problem.
* ``4`` — a headless OpenGL context could not be created.
* ``1`` — anything else (a genuine render failure).

STATUS: the API calls below follow upstream DepthFlow 1.0.0's documented
``DepthScene`` surface (``state.offset_x/offset_y/isometric/height``,
``main(output=…, fps=…, time=…)``) but have NOT been executed on the target
host — Story 11.5 Task 0's spike is Jay's GPU/OpenGL gate. Until it runs,
``depthflow_enabled`` stays false and rung 2 does the work. An API mismatch
lands on exit code 3 by construction, so the pipeline degrades visibly instead
of breaking.
"""

import argparse
import json
import sys
import traceback


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)

    try:
        from DepthFlow.Scene import DepthScene
    except Exception:  # noqa: BLE001 — any import problem is "runtime unusable"
        traceback.print_exc()
        return 3

    samples = spec["samples"]
    fps = int(spec["fps"])

    class TrajectoryScene(DepthScene):  # type: ignore[misc, valid-type]
        """Drive DepthFlow's per-frame camera state from our numeric samples.

        No DepthFlow animation preset is used: the trajectory is already the
        single source of base move + handheld noise + trauma (Story 11.5 AC7,
        "owns base movement exactly once"), so letting DepthFlow add its own
        would double every channel.
        """

        def update(self) -> None:
            i = min(int(round(self.scene_time * fps)), len(samples) - 1)
            _, x, y, rot, zoom = samples[i]
            # x/y arrive as fractions of frame WIDTH; DepthFlow's offsets are in
            # normalised scene units, which the spike must confirm are the same
            # scale. Sign convention: positive x moves visible content right.
            self.state.offset_x = x
            self.state.offset_y = y
            self.state.zoom = 1.0 + zoom
            self.state.rotate = rot
            # Effects OFF (AC6): existing post-FX owns vignette/grain/grade, and
            # DOF/lens distortion are not accepted until the live quality gate says so.
            self.state.dof_enable = False
            self.state.vignette_enable = False

        @property
        def scene_time(self) -> float:
            return float(getattr(self, "time", 0.0))

    try:
        scene = TrajectoryScene(backend="headless")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        # Distinguish "no GL" from "no DepthFlow" so the operator knows whether
        # to install a driver or a package.
        text = f"{type(exc).__name__}: {exc}".lower()
        return 4 if any(k in text for k in ("gl", "egl", "glfw", "context", "display")) else 3

    try:
        scene.input(image=spec["image"], depth=spec["depth"])
        scene.main(
            output=spec["output"],
            width=int(spec["width"]),
            height=int(spec["height"]),
            fps=fps,
            time=len(samples) / fps,
            ssaa=2.0,          # native supersampling — the anti-alias rung 2 lacks
            loop=1,
        )
    except AttributeError:
        # A renamed/removed API member is an install/version problem, not a
        # render problem — same classification as a failed import.
        traceback.print_exc()
        return 3
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
