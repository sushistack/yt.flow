#!/usr/bin/env python
"""14.9 후속 — 인물 높이 측정 하네스 (GPU 0).

Jay 2026-08-30 판정의 "캐릭터가 85% 크기였어야" 는 **분모가 없다.** 이 스크립트는
분모 후보 (i) 프레임 높이 를 재고, (ii) 방 자체 척도(문/천장/침대) 는 사람이 읽어야 하므로
그 판독을 위한 확대 크롭만 만든다.

방법:
  1. 깨끗한 플레이트(1344x768)를 arm 과 **같은 리프레이밍 체인**으로 1920x1080 으로 올린다.
     그러지 않으면 diff 좌표가 arm 좌표계와 다르다.
  2. arm 프레임 − 리프레이밍된 플레이트 로 |Δ| 맵을 만든다. recompose 는 화면 전체를
     다시 그리므로 이 diff 는 **힌트일 뿐** — 임계 위 픽셀의 행별 밀도 프로파일을 내고
     인물 후보 밴드를 제안한다. 최종 top/bottom 은 사람이 확대 크롭에서 확정한다.
  3. 확대 크롭·행 프로파일 오버레이를 raw/scale/ (gitignore 됨) 에 쓴다.

재산출:
  uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/measure_figure_scale.py

표본 밴드: 7샷 × 3 arm = 21 프레임. 프레임 1920x1080. 플레이트 1344x768 원본.
diff 임계 = 채널 평균 |Δ| >= 24 (0-255). 행 밀도 임계 = 그 행의 폭 대비 2%.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "scale"
RUN = "4b35c0ed-8a1e-4448-8594-11bd9997376d"
SHOTS = ["S00105", "S00504", "S00702", "S00800", "S00802", "S00803", "S00904"]
ARMS = ["a", "b", "c"]
DIFF_THRESH = 24
ROW_FRAC = 0.02


def plate(shot: str) -> Path:
    return REPO / "workspace" / RUN / "images" / f"scene_{int(shot[1:4]):03d}_{shot}.png"


def reframe(src: Path, out: Path) -> Path:
    """arm 과 동일한 체인. src/ 는 읽기만 한다."""
    if out.exists():
        return out
    sys.path.insert(0, str(REPO / "src"))
    from yt_flow.pipeline.nodes import video as video_node

    chain = video_node._zoompan_filter(video_node._FUSION_STILL_SPEC, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(video_node.FPS),
         "-i", str(src), "-vf", chain, "-frames:v", "1", "-update", "1", str(out)],
        check=True, capture_output=True)
    return out


def row_profile(arm_img: np.ndarray, plate_img: np.ndarray) -> np.ndarray:
    d = np.abs(arm_img.astype(np.int16) - plate_img.astype(np.int16)).mean(axis=2)
    return (d >= DIFF_THRESH).sum(axis=1) / arm_img.shape[1]


def band(prof: np.ndarray) -> tuple[int, int]:
    hot = np.flatnonzero(prof >= ROW_FRAC)
    return (int(hot[0]), int(hot[-1])) if hot.size else (-1, -1)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for shot in SHOTS:
        pl = reframe(plate(shot), RAW / f"plate_{shot}.png")
        p = np.asarray(Image.open(pl).convert("RGB"))
        out[shot] = {}
        for arm in ARMS:
            a = np.asarray(Image.open(HERE / f"arm_{arm}" / f"{shot}.png").convert("RGB"))
            prof = row_profile(a, p)
            top, bot = band(prof)
            out[shot][arm] = {
                "diff_band_top": top,
                "diff_band_bottom": bot,
                "diff_band_h": bot - top + 1 if top >= 0 else 0,
                "changed_frac": float((prof * a.shape[1]).sum() / a.size * 3),
                "row_profile_max": float(prof.max()),
            }
            # 사람 판독용: 프레임 옆에 행 프로파일 막대를 붙인 오버레이
            bar = np.zeros((a.shape[0], 120, 3), np.uint8)
            for y, v in enumerate(prof):
                bar[y, : max(1, int(v * 120))] = (255, 80, 80)
            Image.fromarray(np.concatenate([a, bar], axis=1)).save(
                RAW / f"prof_{shot}_{arm}.png")
        # 플레이트 대 arm_a 나란히 (시점 판독용)
        Image.fromarray(np.concatenate(
            [p, np.asarray(Image.open(HERE / "arm_a" / f"{shot}.png").convert("RGB"))],
            axis=0)).save(RAW / f"pair_{shot}.png")
    (HERE / "figure_scale.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", "utf-8")
    for shot in SHOTS:
        for arm in ARMS:
            r = out[shot][arm]
            print(f"{shot} {arm}  diff-band {r['diff_band_top']:>4}..{r['diff_band_bottom']:<4}"
                  f" h={r['diff_band_h']:<4} changed={r['changed_frac']*100:.1f}%")


if __name__ == "__main__":
    main()
