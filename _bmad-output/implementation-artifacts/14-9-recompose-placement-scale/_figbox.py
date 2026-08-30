"""씨앗 기반 인물 마스크 → bbox. 씨앗은 0.6배 격자 뷰에서 사람이 찍은 몸통 좌표다."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

H = Path(__file__).resolve().parent
RAW = H / "raw" / "scale"
T, OPEN = 40, 3

SEEDS = {
 "S00105": {"a": {"SCP-049": (600, 350)}, "b": {"SCP-049": (600, 400)}, "c": {"SCP-049": (600, 400)}},
 "S00504": {"a": {"STOCK-d-class": (390, 400), "SCP-049": (1350, 400)},
            "b": {"STOCK-d-class": (400, 400), "SCP-049": (1380, 400)},
            "c": {"STOCK-d-class": (410, 400), "SCP-049": (1380, 400)}},
 "S00702": {"a": {"STOCK-researcher": (620, 500), "SCP-049-2": (1340, 400)},
            "b": {"STOCK-researcher": (640, 450), "SCP-049-2": (1390, 450)},
            "c": {"STOCK-researcher": (640, 450), "SCP-049-2": (1390, 450)}},
 "S00800": {"a": {"SCP-049": (580, 400), "SCP-049-2": (1290, 450)},
            "b": {"SCP-049": (600, 400), "SCP-049-2": (1280, 450)},
            "c": {"SCP-049": (600, 400), "SCP-049-2": (1280, 450)}},
 "S00802": {"a": {"SCP-049": (580, 500), "SCP-049-2": (1400, 500)},
            "b": {"SCP-049": (570, 500), "SCP-049-2": (1380, 500)},
            "c": {"SCP-049": (570, 500), "SCP-049-2": (1390, 500)}},
 "S00803": {"a": {"SCP-049": (960, 500)}, "b": {"SCP-049": (970, 500)}, "c": {"SCP-049": (970, 500)}},
 "S00904": {"a": {"SCP-049": (1450, 400)}, "b": {"SCP-049": (1440, 400)}, "c": {"SCP-049": (1440, 400)}},
}

out = {}
for shot, arms in SEEDS.items():
    p = np.asarray(Image.open(RAW/f"plate_{shot}.png").convert("RGB")).astype(np.int16)
    out[shot] = {}
    for arm, seeds in arms.items():
        a = np.asarray(Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB")).astype(np.int16)
        m = ndimage.binary_opening(np.abs(a-p).mean(2) >= T, np.ones((OPEN, OPEN)))
        m = ndimage.binary_closing(m, np.ones((7, 7)))
        lab, _ = ndimage.label(m)
        im = Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB"); d = ImageDraw.Draw(im)
        out[shot][arm] = {}
        for name, (sx, sy) in seeds.items():
            i = lab[sy, sx]
            if i == 0:
                out[shot][arm][name] = {"error": "seed not in mask"}; continue
            ys, xs = np.nonzero(lab == i)
            b = {"top": int(ys.min()), "bottom": int(ys.max()),
                 "left": int(xs.min()), "right": int(xs.max()),
                 "h": int(ys.max()-ys.min()+1), "pct_frame": round((ys.max()-ys.min()+1)/1080*100, 1),
                 "area": int(ys.size), "seed": [sx, sy]}
            out[shot][arm][name] = b
            d.rectangle([b["left"], b["top"], b["right"], b["bottom"]], outline=(255,0,255), width=3)
            d.line([(0,b["top"]),(1919,b["top"])], fill=(255,0,0), width=2)
            d.line([(0,b["bottom"]),(1919,b["bottom"])], fill=(0,255,0), width=2)
            d.text((b["left"]+6, max(0,b["top"]-24)), f"{name} {b['top']}-{b['bottom']} h={b['h']} {b['pct_frame']}%", fill=(255,255,0))
        im.resize((1152, 648)).save(RAW/f"fig_{shot}_{arm}.png")
(H/"figure_bbox.json").write_text(json.dumps(out, indent=1)+"\n", "utf-8")
for shot in SEEDS:
    for arm in "abc":
        for n, b in out[shot][arm].items():
            print(shot, arm, n, b.get("error") or f"{b['top']}..{b['bottom']} h={b['h']} {b['pct_frame']}% x{b['left']}-{b['right']}")
