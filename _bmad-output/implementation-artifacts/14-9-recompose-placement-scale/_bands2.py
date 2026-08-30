"""_bands.py 의 어두운 판독을 개선 — 감마 보정 + 같은 밴드의 플레이트를 나란히.
왼쪽=arm(인물 있음) / 오른쪽=플레이트(인물 없음). 실루엣 경계가 이 대조에서 확정된다."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from _bands import EST
import os
BAND = int(os.environ.get('BAND', 70))

H = Path(__file__).resolve().parent
RAW = H / "raw" / "scale"
Z = 2
GAMMA = 0.45

def boost(im):
    a = np.asarray(im).astype(np.float32)/255.0
    return Image.fromarray((np.power(a, GAMMA)*255).astype(np.uint8))

def panel(arm_im, plate_im, x0, x1, yc, label):
    y0, y1 = max(0, yc-BAND), min(1080, yc+BAND)
    box = (x0, y0, x1, y1)
    left = boost(arm_im.crop(box)).resize(((x1-x0)*Z, (y1-y0)*Z), Image.NEAREST)
    right = boost(plate_im.crop(box)).resize(((x1-x0)*Z, (y1-y0)*Z), Image.NEAREST)
    c = Image.new("RGB", (left.width*2+8, left.height), (255,0,0))
    c.paste(left, (0,0)); c.paste(right, (left.width+8, 0))
    d = ImageDraw.Draw(c)
    for y in range(y0 - y0 % 10, y1+1, 10):
        py = (y-y0)*Z; maj = y % 50 == 0
        d.line([(0,py),(c.width,py)], fill=(0,255,255) if maj else (0,110,110), width=1)
        if maj: d.text((3,py+1), str(y), fill=(255,255,0))
    d.text((3,3), label, fill=(255,120,255))
    return c

shot = sys.argv[1]
which = sys.argv[2] if len(sys.argv) > 2 else None   # 'TOP' | 'BOT' | None
plate = Image.open(RAW/f"plate_{shot}.png").convert("RGB")
panels = []
for arm, figs in EST[shot].items():
    im = Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB")
    for name, x0, x1, t, b in figs:
        if which in (None, "TOP"): panels.append(panel(im, plate, x0, x1, t, f"{arm} {name} TOP~{t}"))
        if which in (None, "BOT"): panels.append(panel(im, plate, x0, x1, b, f"{arm} {name} BOT~{b}"))
W = max(p.width for p in panels); Ht = sum(p.height+6 for p in panels)
sheet = Image.new("RGB", (W, Ht), (20,20,20)); y = 0
for p in panels: sheet.paste(p, (0,y)); y += p.height+6
sheet.save(RAW/f"band2_{shot}_{which or 'all'}.png")
print(sheet.size)
