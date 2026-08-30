"""diff 힌트 → 인물 후보 블롭. 최종 확정은 사람이 확대 크롭에서 한다."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

H = Path(__file__).resolve().parent
RAW = H / "raw" / "scale"
SHOTS = ["S00105","S00504","S00702","S00800","S00802","S00803","S00904"]
T, MIN_AREA, OPEN = 40, 6000, 5

out = {}
for s in SHOTS:
    p = np.asarray(Image.open(RAW/f"plate_{s}.png").convert("RGB")).astype(np.int16)
    out[s] = {}
    for arm in "abc":
        a = np.asarray(Image.open(H/f"arm_{arm}"/f"{s}.png").convert("RGB")).astype(np.int16)
        m = np.abs(a-p).mean(2) >= T
        m = ndimage.binary_opening(m, np.ones((OPEN,OPEN)))
        m = ndimage.binary_closing(m, np.ones((9,9)))
        lab, n = ndimage.label(m)
        blobs = []
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            area = int((lab[sl] == i).sum())
            if area < MIN_AREA: continue
            ys, xs = sl
            blobs.append({"top": int(ys.start), "bottom": int(ys.stop)-1,
                          "left": int(xs.start), "right": int(xs.stop)-1,
                          "h": int(ys.stop-ys.start), "w": int(xs.stop-xs.start),
                          "area": area,
                          "fill": round(area/((ys.stop-ys.start)*(xs.stop-xs.start)), 3)})
        blobs.sort(key=lambda b: -b["area"])
        out[s][arm] = blobs[:6]
        im = Image.open(H/f"arm_{arm}"/f"{s}.png").convert("RGB")
        d = ImageDraw.Draw(im)
        for j, b in enumerate(blobs[:6]):
            d.rectangle([b["left"],b["top"],b["right"],b["bottom"]], outline=(255,0,255), width=4)
            d.text((b["left"]+6,b["top"]+6), f"{j} h={b['h']} y{b['top']}-{b['bottom']}", fill=(255,255,0))
        im.resize((1152,648)).save(RAW/f"blob_{s}_{arm}.png")
(H/"figure_blobs.json").write_text(json.dumps(out, indent=1)+"\n","utf-8")
for s in SHOTS:
    for arm in "abc":
        print(s, arm, [(b["top"],b["bottom"],b["h"],b["left"],b["right"],b["area"]) for b in out[s][arm]])
