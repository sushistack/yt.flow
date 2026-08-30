"""판독 보조 — 프레임에 100px 격자 + 행/열 라벨을 얹어 raw/scale/ 에 쓴다 (gitignore)."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "scale"

def grid(src: Path, out: Path, step: int = 100, scale: float = 1.0, crop=None):
    im = Image.open(src).convert("RGB")
    if crop:
        im = im.crop(crop)
        ox, oy = crop[0], crop[1]
    else:
        ox = oy = 0
    if scale != 1.0:
        im = im.resize((int(im.width*scale), int(im.height*scale)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    y = (oy // step) * step
    while y <= oy + (im.height/scale):
        py = (y - oy) * scale
        if 0 <= py < im.height:
            d.line([(0, py), (im.width, py)], fill=(0,255,255), width=1)
            d.text((4, py+2), str(y), fill=(255,255,0))
        y += step
    x = (ox // step) * step
    while x <= ox + (im.width/scale):
        px = (x - ox) * scale
        if 0 <= px < im.width:
            d.line([(px, 0), (px, im.height)], fill=(0,255,255), width=1)
            d.text((px+2, 4), str(x), fill=(255,255,0))
        x += step
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out

if __name__ == "__main__":
    a = sys.argv[1:]
    src = Path(a[0]); out = RAW / a[1]
    step = int(a[2]) if len(a) > 2 else 100
    sc = float(a[3]) if len(a) > 3 else 1.0
    cr = tuple(int(v) for v in a[4].split(",")) if len(a) > 4 else None
    print(grid(src, out, step, sc, cr))
