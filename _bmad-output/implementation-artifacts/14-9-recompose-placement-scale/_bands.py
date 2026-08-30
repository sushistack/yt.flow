"""고배율 판독 몽타주 — 각 인물의 머리끝/발끝 추정 위치 ±BAND 를 2배로 잘라
10px 눈금(50px 라벨)과 함께 한 장에 모은다. 최종 top/bottom 은 이 이미지에서 읽는다."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

H = Path(__file__).resolve().parent
RAW = H / "raw" / "scale"
BAND, Z = 70, 2

# shot -> arm -> [(name, x0, x1, est_top, est_bot)]
EST = {
 "S00105": {"a":[("SCP-049",830,1180,60,1010)], "b":[("SCP-049",830,1180,60,1010)], "c":[("SCP-049",830,1180,80,1010)]},
 "S00504": {"a":[("d-class",470,730,60,1040),("SCP-049",1230,1450,130,870)],
            "b":[("d-class",555,825,60,1040),("SCP-049",1270,1500,110,845)],
            "c":[("d-class",555,825,60,1040),("SCP-049",1270,1500,75,845)]},
 "S00702": {"a":[("researcher",490,750,195,1020),("SCP-049-2",1220,1470,140,1030)],
            "b":[("researcher",520,770,120,980),("SCP-049-2",1280,1500,175,965)]},
 "S00800": {"a":[("SCP-049",470,730,115,1015),("SCP-049-2",1150,1430,90,1015)],
            "b":[("SCP-049",480,790,130,1020),("SCP-049-2",1140,1430,155,975)]},
 "S00802": {"a":[("SCP-049",470,760,185,1015),("SCP-049-2",1240,1590,25,1070)],
            "b":[("SCP-049",460,720,165,1035),("SCP-049-2",1200,1570,15,1055)],
            "c":[("SCP-049",460,720,165,1035),("SCP-049-2",1230,1560,50,1060)]},
 "S00803": {"a":[("SCP-049",780,1160,45,1030)], "b":[("SCP-049",790,1170,45,1035)], "c":[("SCP-049",800,1160,40,1040)]},
 "S00904": {"a":[("SCP-049",1300,1630,60,890)], "b":[("SCP-049",1290,1610,60,940)]},
}

def band(im, x0, x1, yc, label):
    y0, y1 = max(0, yc-BAND), min(1080, yc+BAND)
    c = im.crop((x0, y0, x1, y1)).resize(((x1-x0)*Z, (y1-y0)*Z), Image.NEAREST)
    d = ImageDraw.Draw(c)
    for y in range(y0 - y0 % 10, y1+1, 10):
        py = (y-y0)*Z
        maj = y % 50 == 0
        d.line([(0,py),(c.width,py)], fill=(0,255,255) if maj else (0,120,120), width=1)
        if maj: d.text((3,py+1), str(y), fill=(255,255,0))
    d.text((3, 3), label, fill=(255,120,255))
    return c

for shot, arms in EST.items():
    panels = []
    for arm, figs in arms.items():
        for name, x0, x1, t, b in figs:
            im = Image.open(H/f"arm_{arm}"/f"{shot}.png").convert("RGB")
            panels.append(band(im, x0, x1, t, f"{arm} {name} TOP~{t}"))
            panels.append(band(im, x0, x1, b, f"{arm} {name} BOT~{b}"))
    W = max(p.width for p in panels); Hh = sum(p.height+6 for p in panels)
    sheet = Image.new("RGB", (W, Hh), (20,20,20)); y = 0
    for p in panels:
        sheet.paste(p, (0, y)); y += p.height+6
    sc = min(1.0, 1400/sheet.width)
    if sc < 1.0: sheet = sheet.resize((int(sheet.width*sc), int(sheet.height*sc)), Image.LANCZOS)
    sheet.save(RAW/f"band_{shot}.png")
    print(shot, sheet.size)
