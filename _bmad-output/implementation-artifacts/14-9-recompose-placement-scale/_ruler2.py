"""_ruler.py + 증폭 diff 패널. 검은 인물/검은 배경에서 실루엣 경계를 확정하기 위한 것.
왼쪽=arm(감마), 오른쪽=|arm-plate|*4. 사용:
  uv run python _ruler2.py <shot> <arms> <x0> <x1> <y0> <y1> [zoom] [gamma]"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
H = Path(__file__).resolve().parent; RAW = H/"raw"/"scale"
shot, arms, x0, x1, y0, y1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
Z = float(sys.argv[7]) if len(sys.argv) > 7 else 3
G = float(sys.argv[8]) if len(sys.argv) > 8 else 0.5
plate = np.asarray(Image.open(RAW/f"plate_{shot}.png").convert("RGB")).astype(np.int16)[y0:y1, x0:x1]
panels = []
for arm in arms:
    a = np.asarray(Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB")).astype(np.int16)[y0:y1, x0:x1]
    L = Image.fromarray((np.power(a.astype(np.float32)/255, G)*255).astype(np.uint8))
    R = Image.fromarray(np.clip(np.abs(a-plate)*4, 0, 255).astype(np.uint8))
    w, h = int((x1-x0)*Z), int((y1-y0)*Z)
    L = L.resize((w, h), Image.NEAREST); R = R.resize((w, h), Image.NEAREST)
    c = Image.new("RGB", (w*2+8, h), (255,0,0)); c.paste(L,(0,0)); c.paste(R,(w+8,0))
    d = ImageDraw.Draw(c)
    for y in range(y0 - y0 % 10, y1+1, 10):
        py = (y-y0)*Z; maj = y % 50 == 0
        d.line([(0,py),(c.width,py)], fill=(0,255,255) if maj else (0,130,130), width=1)
        if maj: d.text((3,py+1), str(y), fill=(255,255,0))
    d.text((3,3), f"{shot} arm {arm}", fill=(255,120,255))
    panels.append(c)
W = max(p.width for p in panels); Ht = sum(p.height+8 for p in panels)
s = Image.new("RGB",(W,Ht),(30,30,30)); y=0
for p in panels: s.paste(p,(0,y)); y += p.height+8
p = RAW/f"r2_{shot}_{arms}_{y0}_{y1}.png"; s.save(p); print(s.size, p)
