"""정밀 판독 자 — 지정 창을 확대 + 10px 눈금. 사용:
  uv run python _ruler.py <shot> <arms> <x0> <x1> <y0> <y1> [zoom] [gamma]"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
H = Path(__file__).resolve().parent; RAW = H/"raw"/"scale"
shot, arms, x0, x1, y0, y1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
Z = float(sys.argv[7]) if len(sys.argv) > 7 else 3
G = float(sys.argv[8]) if len(sys.argv) > 8 else 1.0
panels = []
for arm in arms:
    im = Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB").crop((x0,y0,x1,y1))
    if G != 1.0:
        im = Image.fromarray((np.power(np.asarray(im).astype(np.float32)/255, G)*255).astype(np.uint8))
    im = im.resize((int((x1-x0)*Z), int((y1-y0)*Z)), Image.NEAREST)
    d = ImageDraw.Draw(im)
    for y in range(y0 - y0 % 10, y1+1, 10):
        py = (y-y0)*Z; maj = y % 50 == 0
        d.line([(0,py),(im.width,py)], fill=(0,255,255) if maj else (0,130,130), width=1)
        if maj: d.text((3,py+1), str(y), fill=(255,255,0))
    d.text((3,3), f"{shot} arm {arm}", fill=(255,120,255))
    panels.append(im)
W = max(p.width for p in panels); Ht = sum(p.height+8 for p in panels)
s = Image.new("RGB",(W,Ht),(30,30,30)); y=0
for p in panels: s.paste(p,(0,y)); y += p.height+8
s.save(RAW/f"ruler_{shot}_{arms}_{y0}_{y1}.png"); print(s.size, RAW/f"ruler_{shot}_{arms}_{y0}_{y1}.png")
