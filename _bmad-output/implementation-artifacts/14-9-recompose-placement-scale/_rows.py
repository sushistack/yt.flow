"""x 밴드 안에서 행별 diff 화소수 → top/bottom. 임계 3개를 함께 찍어 민감도를 보인다.
x 밴드는 열 프로파일에서 자동 도출한 뒤 사람이 확인한 값이다(_bands.py EST 참조)."""
import json, os
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

H = Path(__file__).resolve().parent
RAW = H / "raw" / "scale"
# shot -> arm -> name -> (x0, x1)
XB = {
 "S00105": {"a": {"SCP-049": (860,1120)}, "b": {"SCP-049": (860,1120)}, "c": {"SCP-049": (860,1120)}},
 "S00504": {"a": {"STOCK-d-class": (470,730), "SCP-049": (1235,1470)},
            "b": {"STOCK-d-class": (555,825), "SCP-049": (1240,1465)},
            "c": {"STOCK-d-class": (555,825), "SCP-049": (1240,1465)}},
 "S00702": {"a": {"STOCK-researcher": (485,745), "SCP-049-2": (1225,1410)},
            "b": {"STOCK-researcher": (530,760), "SCP-049-2": (1280,1470)},
            "c": {"STOCK-researcher": (530,760), "SCP-049-2": (1280,1470)}},
 "S00800": {"a": {"SCP-049": (485,700), "SCP-049-2": (1160,1415)},
            "b": {"SCP-049": (510,705), "SCP-049-2": (1168,1405)},
            "c": {"SCP-049": (510,705), "SCP-049-2": (1168,1405)}},
 "S00802": {"a": {"SCP-049": (505,740), "SCP-049-2": (1250,1575)},
            "b": {"SCP-049": (468,686), "SCP-049-2": (1175,1560)},
            "c": {"SCP-049": (468,686), "SCP-049-2": (1235,1575)}},
 "S00803": {"a": {"SCP-049": (830,1110)}, "b": {"SCP-049": (825,1112)}, "c": {"SCP-049": (848,1110)}},
 "S00904": {"a": {"SCP-049": (1318,1610)}, "b": {"SCP-049": (1305,1572)}, "c": {"SCP-049": (1305,1572)}},
}
NPIX = 6
res = {}
for shot, arms in XB.items():
    p = np.asarray(Image.open(RAW/f"plate_{shot}.png").convert("RGB")).astype(np.int16)
    res[shot] = {}
    for arm, figs in arms.items():
        a = np.asarray(Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB")).astype(np.int16)
        d = np.abs(a-p).mean(2)
        res[shot][arm] = {}
        for name, (x0, x1) in figs.items():
            row = {}
            for T in (25, 40, 60):
                m = ndimage.binary_opening(d[:, x0:x1] >= T, np.ones((3,3)))
                c = m.sum(1); hot = np.flatnonzero(c >= NPIX)
                row[T] = [int(hot[0]), int(hot[-1]), int(hot[-1]-hot[0]+1)] if hot.size else None
            res[shot][arm][name] = row
            print(shot, arm, name, f"x{x0}-{x1}",
                  " ".join(f"T{T}:{v[0]}..{v[1]}(h{v[2]})" if v else f"T{T}:none" for T, v in row.items()))
(H/"row_extents.json").write_text(json.dumps(res, indent=1)+"\n","utf-8")
