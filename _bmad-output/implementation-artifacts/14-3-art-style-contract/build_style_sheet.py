#!/usr/bin/env python
"""출하 면 컨택트 시트 — Jay 의 화풍 라벨 확정용. Story 14.3. GPU 0 · 렌더 0.

    uv run python .../build_style_sheet.py <run_id>

**출하 면으로 만든다.** Jay 가 판정할 것은 그가 본 프레임이고, 이 런에서 영상에 들어간 것은
`recomposed/` 33장 + 나머지 플레이트 10장이다. `images/` 43장은 recompose **이전** 배경이라
그것으로 시트를 만들면 사람이 본 적 없는 픽셀에 라벨을 받게 된다.

**시트는 두 장 나온다. 판정용은 블라인드 쪽이다.**

- `style_sheet_delivered_<run_id>.jpg` — **판정 산출물.** 타일 각인은 `shot_id` 와 출처
  (`REC` = `recomposed/`, `PLATE` = recompose 안 된 샷이라 플레이트가 곧 출하 프레임)뿐이다.
  **Claude 표류 라벨은 찍히지 않는다.**
- `style_sheet_delivered_annotated_<run_id>.jpg` — **기록용, 판정에 쓰지 않는다.** 같은 시트에
  `epics.md:1901` 의 Claude 단독 라벨 7건을 노란 `*drift?` 로 얹은 것. 사후에 "라벨이 어디에
  붙어 있었나"를 보기 위한 것이다.

라벨을 판정 시트에 찍으면 **판정기를 가설에 고정**시킨다. 이 시트의 목적 자체가 그 7건을 Jay 가
확정하거나 **뒤집는** 것이고(14.2 에서 같은 종류 인계 라벨 2건이 전수 판정으로 뒤집혔다),
게이트가 될 판정은 가설에 블라인드여야 한다. 그래서 블라인드가 기본이고 주석본은 별도 파일이다.

타일 장변은 **256px** 이다. CLAUDE.md 의 "판정 이미지는 장변 ~512px" 는 **시트 전체**가 아니라
판정에 쓰이는 이미지 기준이고, 43타일 시트에서 시트 장변을 512로 두면 타일이 73px 썸네일이
되어 화풍을 판정할 수 없다. 그래서 **타일 크기**를 적는다(시트는 1536×1280).

입력 해상도가 섞여 있다(스톡 1920×1080 / 자유생성 1216×832). 늘리지 않고 **레터박스**한다 —
가로세로비를 바꾸면 판정 대상인 렌더 스타일이 왜곡된다.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from measure_palette import DRIFT_LABELS, plates, recomposed  # noqa: E402

TILE = (256, 144)          # 장변 256px, 16:9 박스
CAPTION_H = 16
COLS = 6
BG = (24, 24, 27)
FG = (228, 228, 231)
DRIFT_FG = (250, 204, 21)


def letterboxed(path: Path) -> Image.Image:
    """타일 박스에 비율을 지켜 넣는다. `thumbnail` 은 축소 전용이라 확대하지 않는다."""
    frame = Image.open(path).convert("RGB")
    frame.thumbnail(TILE, Image.Resampling.LANCZOS)
    box = Image.new("RGB", TILE, BG)
    box.paste(frame, ((TILE[0] - frame.width) // 2, (TILE[1] - frame.height) // 2))
    return box


def sheet(tiles: list[tuple[str, bool, Image.Image]], *, annotate: bool) -> Image.Image:
    """한 장의 시트. `annotate=False` 가 판정용 — 타일에 가설을 얹지 않는다."""
    rows = -(-len(tiles) // COLS)
    out = Image.new("RGB", (COLS * TILE[0], rows * (TILE[1] + CAPTION_H)), BG)
    draw = ImageDraw.Draw(out)
    for i, (shot_id, is_rec, tile) in enumerate(tiles):
        x, y = (i % COLS) * TILE[0], (i // COLS) * (TILE[1] + CAPTION_H)
        out.paste(tile, (x, y))
        drift = annotate and shot_id in DRIFT_LABELS
        draw.text((x + 4, y + TILE[1] + 3),
                  f"{shot_id}  {'REC' if is_rec else 'PLATE'}{'  *drift?' if drift else ''}",
                  fill=DRIFT_FG if drift else FG)
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_id = argv[1]
    run_dir = REPO / "workspace" / run_id
    if not (run_dir / "images").is_dir():
        print(f"no run at {run_dir}", file=sys.stderr)
        return 3

    plate_by_shot, rec_by_shot = plates(run_dir), recomposed(run_dir)
    tiles, skipped = [], []
    for shot_id in sorted(plate_by_shot):
        src = rec_by_shot.get(shot_id, plate_by_shot[shot_id])
        try:
            tiles.append((shot_id, shot_id in rec_by_shot, letterboxed(src)))
        except Exception as exc:  # noqa: BLE001 — 한 장이 깨져도 나머지로 시트를 만든다
            skipped.append(f"{shot_id}: {type(exc).__name__}: {exc}")

    if not tiles:
        print("every frame failed to open", file=sys.stderr)
        return 4

    for suffix, annotate in (("", False), ("annotated_", True)):
        image = sheet(tiles, annotate=annotate)
        dest = HERE / f"style_sheet_delivered_{suffix}{run_id}.jpg"
        image.save(dest, quality=88)
        print(f"{dest.name}  {image.width}x{image.height}  tiles={len(tiles)} "
              f"(REC {sum(r for _, r, _ in tiles)} / PLATE {sum(not r for _, r, _ in tiles)})"
              f"{'' if annotate else '   <- JUDGING ARTIFACT (blind)'}")
    if skipped:
        print(f"SKIPPED {len(skipped)}: " + "; ".join(skipped), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
