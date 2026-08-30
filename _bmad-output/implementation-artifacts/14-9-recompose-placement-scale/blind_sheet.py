#!/usr/bin/env python
"""Story 14.9 블라인드 시트 — 7행 × 3열 = 21타일. GPU 0 · 렌더 0.

    uv run python .../blind_sheet.py

**행 안의 arm 순서를 샷마다 치환한다.** 10.1e는 좌/우를 arm에 고정했고, 그러면 타일 하나의
정체를 알아채는 순간 나머지 전부를 알게 된다. 여기서는 치환이 `sheet_key.json` 에만 있다.

타일 각인은 **blind id 12-hex 뿐**이다 — shot_id도, arm 이름도, 가설도 찍지 않는다.
`10-1e-live-validation/pair_sheets` 는 가설을 이미지에 각인해서 재사용하지 않는다.

타일 장변은 **512px** 다(CLAUDE.md 의 판정 이미지 기준). 판정 축이 "인물이 방의 척도에
맞는가"이므로 인물 실루엣과 방의 척도 단서(문·가구·천장)가 같이 보여야 한다 — 14.3의 256px
타일은 43타일 시트라 그 값이었고, 21타일이면 512가 들어간다.
"""

import hashlib
import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]

SALT = "14-9-recompose-placement-scale"  # 고정·커밋됨. blind id 는 재현 가능하다
ARMS = ("a", "b", "c")
TILE = (512, 288)
CAPTION_H = 22
GUTTER = 44           # 행 번호가 들어가는 왼쪽 여백
PAD = 8
BG = (24, 24, 27)
FG = (228, 228, 231)
DIM = (113, 113, 122)


def blind_id(shot_id: str, arm: str) -> str:
    return hashlib.sha256(f"{shot_id}|{arm}|{SALT}".encode("utf-8")).hexdigest()[:12]


def permutation(shot_id: str) -> list[str]:
    """이 샷의 열 순서. 샷 id 와 소금만으로 결정되므로 시트를 다시 만들어도 같다."""
    order = list(ARMS)
    random.Random(f"{shot_id}|{SALT}|order").shuffle(order)
    return order


def letterboxed(path: Path) -> Image.Image:
    frame = Image.open(path).convert("RGB")
    frame.thumbnail(TILE, Image.Resampling.LANCZOS)
    box = Image.new("RGB", TILE, BG)
    box.paste(frame, ((TILE[0] - frame.width) // 2, (TILE[1] - frame.height) // 2))
    return box


def main() -> int:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    shots = [s["shot_id"] for s in manifest["shots"]]

    missing = [
        f"arm_{arm}/{shot_id}.png" for shot_id in shots for arm in ARMS
        if not (HERE / f"arm_{arm}" / f"{shot_id}.png").is_file()
    ]
    if missing:
        print(f"STOP: {len(missing)}개 타일이 없다 — 시트를 만들지 않는다\n  {missing[:6]}")
        return 2

    blind_dir = HERE / "blind"
    blind_dir.mkdir(exist_ok=True)
    cell_w, cell_h = TILE[0] + PAD, TILE[1] + CAPTION_H + PAD
    sheet = Image.new("RGB", (GUTTER + 3 * cell_w + PAD, len(shots) * cell_h + PAD), BG)
    draw = ImageDraw.Draw(sheet)
    rows = []
    for r, shot_id in enumerate(shots):
        order = permutation(shot_id)
        y = PAD + r * cell_h
        draw.text((PAD, y + TILE[1] // 2), f"{r + 1:>2}", fill=DIM)
        tiles = []
        for c, arm in enumerate(order):
            src = HERE / f"arm_{arm}" / f"{shot_id}.png"
            bid = blind_id(shot_id, arm)
            # 원본 해상도 사본도 남긴다 — 시트에서 애매하면 이 파일을 열어 확대한다.
            shutil.copyfile(src, blind_dir / f"{bid}.png")
            x = GUTTER + c * cell_w
            sheet.paste(letterboxed(src), (x, y))
            draw.text((x + 4, y + TILE[1] + 5), bid, fill=FG)
            tiles.append({"column": c + 1, "blind_id": bid, "arm": arm,
                          "source": str(src.relative_to(ROOT))})
        rows.append({"row": r + 1, "shot_id": shot_id, "column_order": order, "tiles": tiles})

    out = HERE / "blind_sheet.jpg"
    sheet.save(out, quality=92)
    (HERE / "sheet_key.json").write_text(json.dumps({
        "salt": SALT,
        "id_rule": "sha256(f'{shot_id}|{arm}|{salt}').hexdigest()[:12]",
        "order_rule": "random.Random(f'{shot_id}|{salt}|order').shuffle(['a','b','c'])",
        "arms": {"a": "출하 프레임 (recomposed/, seed 0, 편집 전 문구)",
                 "b": "재렌더 (seed 20260830, 편집 전 문구)",
                 "c": "재렌더 (seed 20260830, 편집 후 문구) — B와 같은 시드·같은 워크플로 파일"},
        "sheet": str(out.relative_to(ROOT)),
        "tile_px": list(TILE),
        "rows": rows,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {out.relative_to(ROOT)}  {sheet.width}x{sheet.height}  {len(shots) * 3}타일")
    print(f"  -> {(HERE / 'sheet_key.json').relative_to(ROOT)}")
    distinct = {tuple(r["column_order"]) for r in rows}
    print(f"  열 순서 {len(distinct)}종 / {len(rows)}행: "
          + ", ".join("".join(o) for o in sorted(distinct)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
