#!/usr/bin/env python3
"""Jay 시청 판정용 시트 (캡션은 ASCII — PIL 기본 폰트에 CJK 글리프가 없다) — 축 ②가 치르는 대가를 화면으로 보이게 한다.

두 장을 만든다.
  c4-mismatch.jpg : C4' 5샷. 각 행 = 배정된 플레이트(눈높이)와, 그 샷이 요구한 시점.
                    판정 질문은 "부감/앙각을 요구한 샷에 눈높이 방이 와서 이상한가".
  served-vs-generated.jpg : 같은 씬 안에서 플레이트가 온 샷과 생성이 온 샷을 나란히.
                    판정 질문은 "배경이 샷마다 흔들리는 것이 멎었는가".

원본 렌더는 루트 .gitignore가 처리하고, 여기서 만든 시트만 커밋한다(CLAUDE.md).
긴 변 512px — 지금까지 쓰인 판정 기준(시점·인물 수·배경 일관성)은 전부 이 해상도에서 산다.
"""
from __future__ import annotations

import json
import pathlib
import sys

from PIL import Image, ImageDraw

RUN = "780cb8b3-9f01-4b88-aae7-6e78f246cdf3"
REPO = pathlib.Path(__file__).resolve().parents[4]
WS = REPO / "workspace" / RUN / "images"
OUT = pathlib.Path(__file__).resolve().parent
LONG = 512

# C4': 배정 플레이트의 측정 시점이 샷의 camera_angle이 요구한 것과 다른 샷.
# replay_coverage.py 780cb8b3 의 C4' 블록에서 그대로 옮겼다(재산출 가능).
C4 = [("S00203", "high-angle", "HIGH", "containment-chamber/b", "EYE"),
      ("S00301", "low-angle", "LOW", "containment-chamber/c", "EYE"),
      ("S00600", "high-angle", "HIGH", "observation-room/c", "EYE"),
      ("S00604", "low-angle", "LOW", "corridor/c", "EYE"),
      ("S00801", "low-angle", "LOW", "containment-chamber/a", "EYE")]


def _shot_image(shot_id: str) -> pathlib.Path | None:
    hits = sorted(WS.glob(f"*_{shot_id}.png")) or sorted(WS.glob(f"*{shot_id}*.png"))
    return hits[0] if hits else None


def _thumb(p: pathlib.Path) -> Image.Image:
    im = Image.open(p).convert("RGB")
    im.thumbnail((LONG, LONG))
    return im


def _sheet(rows: list[tuple[pathlib.Path, str]], out: pathlib.Path, cols: int = 2) -> None:
    if not rows:
        print(f"  {out.name}: 대상 0건, 건너뜀")
        return
    tiles = [(_thumb(p), cap) for p, cap in rows]
    w = max(t.width for t, _ in tiles)
    h = max(t.height for t, _ in tiles)
    pad, bar = 8, 22
    n = len(tiles)
    r = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + pad) + pad, r * (h + bar + pad) + pad), (24, 24, 27))
    d = ImageDraw.Draw(sheet)
    for i, (t, cap) in enumerate(tiles):
        x = pad + (i % cols) * (w + pad)
        y = pad + (i // cols) * (h + bar + pad)
        sheet.paste(t, (x, y))
        d.text((x + 2, y + h + 4), cap, fill=(235, 235, 235))
    sheet.save(out, quality=88)
    print(f"  {out.name}: {n}장, {sheet.size[0]}x{sheet.size[1]}")


def main() -> int:
    if not WS.is_dir():
        sys.exit(f"workspace 없음: {WS}")

    print("C4' 시점 불일치 시트")
    rows = []
    for sid, angle, want, plate, got in C4:
        p = _shot_image(sid)
        if p is None:
            print(f"  {sid}: 이미지 없음")
            continue
        rows.append((p, f"{sid}  asked {angle}={want}  got {plate}={got}"))
    _sheet(rows, OUT / "c4-mismatch.jpg")

    print("플레이트 vs 생성 시트")
    served, generated = [], []
    for f in sorted(WS.glob("*_done.json")):
        sp = (json.loads(f.read_text()).get("provenance") or {}).get("stock_plate")
        sid = f.name.split("_")[2] if len(f.name.split("_")) > 2 else f.name
        img = _shot_image(sid.replace("_done.json", ""))
        if img is None:
            continue
        (served if sp else generated).append(
            (img, f"{sid.replace('_done.json','')}  " + (f"PLATE {sp['location_key']}/{sp['variant']}" if sp else "generated")))
    _sheet(served[:6] + generated[:6], OUT / "served-vs-generated.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
