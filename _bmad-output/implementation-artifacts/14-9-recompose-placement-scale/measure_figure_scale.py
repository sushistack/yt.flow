#!/usr/bin/env python
"""14.9 후속 — 인물 높이 측정 + S00504 시점 판독 하네스 (GPU 0, LLM 0).

Jay 2026-08-30 판정의 *"캐릭터가 85%정도 크기였어야함"* 은 **분모가 없다.** 이 스크립트는
분모 후보 (i) 프레임 높이 를 재현 가능하게 만들고, (ii) 방 자체 척도 판독에 필요한
확대 크롭을 만든다. (ii) 는 사람이 읽어야 하는 값이라 여기서 자동 산출하지 않는다.

## 왜 diff 자동 측정이 아닌가

recompose 는 프레임 전체를 다시 그린다. arm − 플레이트 diff 는 프레임의 **15~40%** 에서
켜지고(`stage diff`), 임계를 40 으로 올려도 배경 재화풍 영역이 인물과 연결돼 씨앗 기반
연결성분도 프레임 전체로 샌다(`stage blob`). 그래서 top/bottom 은 **사람이 확대 크롭에서
읽은 값**이고, 이 파일의 `READINGS` 가 그 판독 결과다. 스크립트가 하는 일은 그 판독이
나온 **바로 그 크롭을 재생성**하는 것이다.

## 표본 밴드 (`gotcha_a-measurement-without-its-sample-band`)

- 표본: 7샷 × 3 arm, 인물 11개체 → 판독 28건. 무효 대조군 3샷(`S00702` `S00800` `S00904`)은
  arm B 와 C 가 **픽셀 동일**하므로(`VERDICT.md` §8) b 판독을 c 에 그대로 쓴다.
- 좌표계: 리프레이밍된 **1920×1080** arm 프레임. 플레이트(1344×768)는 arm 과 동일한 체인
  `video._zoompan_filter(video._FUSION_STILL_SPEC, 1.0)` 으로 올려 좌표를 맞춘다.
- 정의: `top` = 인물 머리(모자·후드 포함, **손에 든 물건 제외**)의 최상단 행,
  `bottom` = 신발/맨발 바닥의 최하단 행. 둘 다 포함 좌표.
- 판독 오차: 밝은 인물 ±8 px(±0.8 pp), 어두운 플레이트 위 검은 인물 ±15 px(±1.4 pp).
  후자는 `S00105` · `S00800` SCP-049 · `S00802` SCP-049 세 개체.

## 재산출

    uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/measure_figure_scale.py table
    uv run python .../measure_figure_scale.py crops     # 판독에 쓴 확대 크롭 재생성
    uv run python .../measure_figure_scale.py plates    # 리프레이밍된 깨끗한 플레이트
    uv run python .../measure_figure_scale.py cards     # S00504 입력 카드 대조 시트

출력은 전부 `raw/scale/` — 디렉터리 `.gitignore` 가 `raw/` 를 무시한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "scale"
RUN = "4b35c0ed-8a1e-4448-8594-11bd9997376d"
SHOTS = ["S00105", "S00504", "S00702", "S00800", "S00802", "S00803", "S00904"]
FRAME_H = 1080
# arm B 와 C 가 픽셀 동일한 샷 (near 패스 없음 → 지시문 바이트 동일, 렌더러 결정론적)
B_EQ_C = {"S00702", "S00800", "S00904"}

# (shot, arm, figure) -> (top, bottom, x0, x1, note)
# x0/x1 은 판독에 쓴 크롭의 가로 밴드. 열 프로파일에서 도출한 뒤 눈으로 확인했다.
READINGS: dict[tuple[str, str, str], tuple[int, int, int, int, str]] = {
    ("S00105", "a", "SCP-049"):          (76, 1027, 800, 1200, "어두운 인물/어두운 플레이트 — ±15px"),
    ("S00105", "b", "SCP-049"):          (106, 1013, 800, 1200, "±15px"),
    ("S00105", "c", "SCP-049"):          (158, 1030, 800, 1200, "±15px"),
    ("S00504", "a", "STOCK-d-class"):    (42, 1045, 460, 850, ""),
    ("S00504", "b", "STOCK-d-class"):    (53, 1068, 460, 850, ""),
    ("S00504", "c", "STOCK-d-class"):    (68, 1050, 460, 850, ""),
    ("S00504", "a", "SCP-049"):          (122, 908, 1230, 1560, ""),
    ("S00504", "b", "SCP-049"):          (97, 897, 1230, 1560, ""),
    ("S00504", "c", "SCP-049"):          (105, 903, 1230, 1560, ""),
    ("S00702", "a", "STOCK-researcher"): (190, 1053, 485, 745, ""),
    ("S00702", "b", "STOCK-researcher"): (197, 1000, 530, 760, ""),
    ("S00702", "a", "SCP-049-2"):        (147, 1012, 1225, 1410, ""),
    ("S00702", "b", "SCP-049-2"):        (202, 945, 1280, 1470, ""),
    ("S00800", "a", "SCP-049"):          (178, 1015, 480, 800, "검은 인물 — ±15px; 든 무기 제외"),
    ("S00800", "b", "SCP-049"):          (195, 1008, 480, 800, "±15px; 든 무기 제외"),
    ("S00800", "a", "SCP-049-2"):        (170, 1012, 1150, 1420, ""),
    ("S00800", "b", "SCP-049-2"):        (181, 978, 1150, 1420, ""),
    ("S00802", "a", "SCP-049"):          (188, 1032, 455, 750, "검은 인물 — ±15px"),
    ("S00802", "b", "SCP-049"):          (163, 1042, 455, 750, "±15px"),
    ("S00802", "c", "SCP-049"):          (163, 1048, 455, 750, "±15px"),
    ("S00802", "a", "SCP-049-2"):        (35, 1055, 1160, 1600, ""),
    ("S00802", "b", "SCP-049-2"):        (25, 1030, 1160, 1600, ""),
    ("S00802", "c", "SCP-049-2"):        (45, 1075, 1160, 1600, "발끝이 프레임 하단(1079)에 닿음 — 하한값"),
    ("S00803", "a", "SCP-049"):          (25, 1038, 820, 1130, ""),
    ("S00803", "b", "SCP-049"):          (53, 1042, 820, 1130, ""),
    ("S00803", "c", "SCP-049"):          (63, 1045, 820, 1130, ""),
    ("S00904", "a", "SCP-049"):          (75, 945, 1290, 1620, ""),
    ("S00904", "b", "SCP-049"):          (100, 985, 1290, 1620, ""),
}

# 판독에 쓴 크롭 창: (shot, arms, x0, x1, y0, y1, zoom, gamma)
CROPS = [
    ("S00105", "abc", 880, 1100, 30, 210, 2.5, 0.5),
    ("S00105", "abc", 800, 1200, 950, 1060, 2.5, 0.5),
    ("S00504", "abc", 460, 850, 20, 160, 2.2, 0.7),
    ("S00504", "abc", 460, 850, 980, 1079, 2.2, 0.7),
    ("S00504", "abc", 1230, 1490, 40, 210, 2.2, 0.5),
    ("S00504", "abc", 1230, 1560, 840, 980, 2.2, 0.5),
    ("S00702", "ab", 485, 745, 35, 355, 2.0, 0.45),
    ("S00702", "ab", 485, 745, 890, 1079, 2.0, 0.45),
    ("S00702", "ab", 1225, 1470, 40, 360, 2.0, 0.45),
    ("S00702", "ab", 1225, 1470, 880, 1079, 2.0, 0.45),
    ("S00800", "ab", 480, 800, 60, 260, 1.8, 0.40),
    ("S00800", "ab", 480, 800, 950, 1079, 1.8, 0.40),
    ("S00800", "ab", 1150, 1420, 60, 200, 2.4, 0.6),
    ("S00800", "ab", 1150, 1420, 920, 1060, 2.4, 0.6),
    ("S00802", "abc", 455, 750, 130, 280, 2.2, 0.6),
    ("S00802", "abc", 455, 750, 980, 1079, 2.2, 0.6),
    ("S00802", "abc", 1160, 1600, 0, 130, 2.0, 0.6),
    ("S00802", "abc", 1160, 1600, 990, 1079, 2.0, 0.6),
    ("S00803", "abc", 820, 1130, 20, 160, 1.6, 0.5),
    ("S00803", "abc", 820, 1130, 970, 1079, 1.6, 0.5),
    ("S00904", "abc", 1290, 1620, 20, 160, 2.2, 0.5),
    ("S00904", "abc", 1290, 1620, 830, 990, 2.2, 0.5),
]

# S00504 시점 판독에 쓴 입력 카드 — 넷 다 **눈높이 정면 전신**이고 yaw 만 다르다.
S00504_CARDS = [
    "assets/characters/STOCK-d-class/epoch_2/back_candidate_1.png",
    "assets/characters/SCP-049/epoch_1/side_candidate_1.png",
    "assets/characters/SCP-049/epoch_1/front_candidate_1.png",
    "assets/characters/SCP-049/epoch_1/three_quarter_candidate_1.png",
    "assets/characters/SCP-049/epoch_1/back_candidate_1.png",
]


def plate_src(shot: str) -> Path:
    return REPO / "workspace" / RUN / "images" / f"scene_{int(shot[1:4]):03d}_{shot}.png"


def plate(shot: str) -> Path:
    """깨끗한 플레이트를 arm 과 **같은 리프레이밍 체인**으로 1920x1080 으로 올린다.
    그러지 않으면 좌표계가 arm 과 다르다. `src/` 는 읽기만 한다."""
    out = RAW / f"plate_{shot}.png"
    if out.exists():
        return out
    sys.path.insert(0, str(REPO / "src"))
    from yt_flow.pipeline.nodes import video as video_node

    chain = video_node._zoompan_filter(video_node._FUSION_STILL_SPEC, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(video_node.FPS),
         "-i", str(plate_src(shot)), "-vf", chain, "-frames:v", "1", "-update", "1", str(out)],
        check=True, capture_output=True)
    return out


def _gamma(im: Image.Image, g: float) -> Image.Image:
    if g == 1.0:
        return im
    return Image.fromarray((np.power(np.asarray(im).astype(np.float32) / 255, g) * 255).astype(np.uint8))


def crops() -> None:
    """판독에 쓴 확대 크롭을 재생성한다. 왼쪽=arm(감마 보정), 오른쪽=|arm-plate|*4.
    오른쪽 패널이 있어야 검은 인물/검은 배경에서 실루엣 경계가 확정된다."""
    RAW.mkdir(parents=True, exist_ok=True)
    for shot, arms, x0, x1, y0, y1, z, g in CROPS:
        p = np.asarray(Image.open(plate(shot)).convert("RGB")).astype(np.int16)[y0:y1, x0:x1]
        panels = []
        for arm in arms:
            a = np.asarray(Image.open(HERE / f"arm_{arm}" / f"{shot}.png").convert("RGB"))
            a = a.astype(np.int16)[y0:y1, x0:x1]
            w, h = int((x1 - x0) * z), int((y1 - y0) * z)
            left = _gamma(Image.fromarray(a.astype(np.uint8)), g).resize((w, h), Image.NEAREST)
            right = Image.fromarray(np.clip(np.abs(a - p) * 4, 0, 255).astype(np.uint8)).resize((w, h), Image.NEAREST)
            c = Image.new("RGB", (w * 2 + 8, h), (255, 0, 0))
            c.paste(left, (0, 0))
            c.paste(right, (w + 8, 0))
            d = ImageDraw.Draw(c)
            for y in range(y0 - y0 % 10, y1 + 1, 10):
                py = (y - y0) * z
                major = y % 50 == 0
                d.line([(0, py), (c.width, py)], fill=(0, 255, 255) if major else (0, 130, 130))
                if major:
                    d.text((3, py + 1), str(y), fill=(255, 255, 0))
            d.text((3, 3), f"{shot} arm {arm}", fill=(255, 120, 255))
            panels.append(c)
        sheet = Image.new("RGB", (max(p_.width for p_ in panels),
                                  sum(p_.height + 8 for p_ in panels)), (30, 30, 30))
        y = 0
        for p_ in panels:
            sheet.paste(p_, (0, y))
            y += p_.height + 8
        sheet.save(RAW / f"crop_{shot}_{arms}_{y0}_{y1}.png")
    print(f"{len(CROPS)} crops -> {RAW}")


def cards() -> None:
    """S00504 진단의 근거 시트 — 입력 카드는 넷 다 눈높이 정면 전신이고 yaw 만 다르다.
    `STOCK-d-class/back_candidate_1.png` 은 이름과 달리 **정면**이라는 것도 여기서 보인다."""
    RAW.mkdir(parents=True, exist_ok=True)
    ims = []
    for rel in S00504_CARDS:
        p = REPO / rel
        if not p.exists():
            print("MISSING", rel)
            continue
        im = Image.open(p).convert("RGB")
        im.thumbnail((230, 400))
        ImageDraw.Draw(im).text((3, 3), f"{Path(rel).parts[2]}/{Path(rel).stem}"[:34], fill=(255, 255, 0))
        ims.append(im)
    sheet = Image.new("RGB", (len(ims) * 238, 408), (240, 240, 240))
    for i, im in enumerate(ims):
        sheet.paste(im, (i * 238, 0))
    sheet.save(RAW / "cards_S00504.png")
    print(RAW / "cards_S00504.png")


def table() -> None:
    rows = []
    for (shot, arm, fig), (top, bot, x0, x1, note) in sorted(READINGS.items()):
        for a in ([arm, "c"] if (shot in B_EQ_C and arm == "b") else [arm]):
            h = bot - top + 1
            dup = a == "c" and shot in B_EQ_C
            rows.append({"shot": shot, "arm": a, "figure": fig, "top": top, "bottom": bot,
                         "height_px": h, "pct_frame": round(h / FRAME_H * 100, 1),
                         "x_band": [x0, x1], "duplicate_of_arm_b": dup,
                         "note": "; ".join(x for x in (note, "arm b 와 픽셀 동일" if dup else "") if x)})
    rows.sort(key=lambda r: (r["shot"], r["figure"], r["arm"]))
    # 통계는 **구별되는 렌더**에만 건다(28건). b==c 인 5건을 두 번 세면 무효 대조군이
    # 모집단에서 두 배 무게를 갖는다.
    pcts = sorted(r["pct_frame"] for r in rows if not r["duplicate_of_arm_b"])
    stats = {"n_rows": len(rows), "n_distinct": len(pcts), "min": pcts[0], "max": pcts[-1],
             "median": round((pcts[len(pcts)//2 - 1] + pcts[len(pcts)//2]) / 2, 1),
             "mean": round(sum(pcts) / len(pcts), 1)}
    (HERE / "figure_heights.json").write_text(
        json.dumps({"frame": [1920, 1080], "stats": stats, "rows": rows}, indent=1, ensure_ascii=False) + "\n",
        "utf-8")
    print(f"{'shot':7} {'arm':4} {'figure':17} {'top':>5} {'bot':>5} {'h':>5} {'%frame':>7}  note")
    for r in rows:
        print(f"{r['shot']:7} {r['arm']:4} {r['figure']:17} {r['top']:5} {r['bottom']:5} "
              f"{r['height_px']:5} {r['pct_frame']:7}  {r['note']}")
    print(f"\nrows={stats['n_rows']}  distinct renders={stats['n_distinct']}  "
          f"min={stats['min']}%  median={stats['median']}%  "
          f"mean={stats['mean']}%  max={stats['max']}%")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "table"
    {"table": table, "crops": crops, "cards": cards,
     "plates": lambda: [print(plate(s)) for s in SHOTS]}[cmd]()
