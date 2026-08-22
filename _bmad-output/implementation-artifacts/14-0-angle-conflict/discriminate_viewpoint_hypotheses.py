#!/usr/bin/env python
"""Story 14.0 §4-4 follow-up: which axis predicts the RENDERED viewpoint —
(a) floor/ceiling content mass, or (b) lighting-vocabulary count?

    uv run python .../discriminate_viewpoint_hypotheses.py 4b35c0ed

GPU 0. Reads the shipped plates' adjudicated viewpoints from
``viewpoint_verdicts.csv`` (rule fixed in ``PREREGISTRATION-4-4-hypotheses.md``,
judged blind to the prompt text) and the two axes from the run's checkpoint via
``measure_angle_agreement.load_scenes``.

Exit codes (the falsification gate):
    0  at least one axis separates HIGH from not-HIGH at p < 0.05 (two-tailed Fisher)
       — in EITHER direction. Axis (i) came out INVERTED from hypothesis (a)'s own
       prediction, and an exit code cannot say that: read the printed rates.
    1  neither axis separates — BOTH hypotheses fail, look for a third layer
    2  usage error
    3  nothing to measure (no run / no scenes / verdict-shot mismatch)
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_angle_agreement import _LIGHTING_DECOYS, load_scenes  # noqa: E402

# Axis (i), frozen in PREREGISTRATION before any plate was opened. The three
# decoy phrases of axis (ii) are deliberately absent: two axes that share terms
# cannot discriminate.
_SURFACE = {
    "floor": r"\bfloors?\b", "ground": r"\bground\b", "concrete": r"\bconcrete\b",
    "tile": r"\btiles?\b|\btiled\b", "drain": r"\bdrains?\b", "grate": r"\bgrates?\b|\bgrating\b",
    "linoleum": r"\blinoleum\b", "carpet": r"\bcarpet\w*\b", "pavement": r"\bpavement\b",
    "asphalt": r"\basphalt\b", "floorboard": r"\bfloorboards?\b",
    "ceiling": r"\bceilings?\b(?![- ]mounted)", "rafter": r"\brafters?\b",
    "duct": r"\bducts?\b|\bductwork\b", "skylight": r"\bskylights?\b",
}


def _fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-tailed Fisher exact p for [[a,b],[c,d]]. ponytail: stdlib comb, n<=43."""
    n, r1, c1 = a + b + c + d, a + b, a + c
    def p(x: int) -> float:
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    obs = p(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * 1.0000001))


def _table(name: str, rows: list[tuple[str, int, str]], hi_label: str, lo_label: str) -> float:
    """rows = (shot, group 0/1, verdict). Prints the 2x2 and returns the p-value."""
    cells = Counter((g, v == "HIGH") for _, g, v in rows)
    a, b = cells[(1, True)], cells[(1, False)]
    c, d = cells[(0, True)], cells[(0, False)]
    pv = _fisher(a, b, c, d)
    print(f"\n{name}")
    print(f"  {'':22} {'HIGH':>5} {'not-HIGH':>9}  HIGH rate")
    for lbl, x, y in ((hi_label, a, b), (lo_label, c, d)):
        tot = x + y
        print(f"  {lbl:22} {x:>5} {y:>9}  {x / tot:.0%}" if tot else f"  {lbl:22} (empty)")
    print(f"  Fisher exact (two-tailed) p = {pv:.4f}")
    return pv


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    here = Path(__file__).resolve().parent
    verdicts, y_h = {}, {}
    with (here / "viewpoint_verdicts.csv").open() as fh:
        for row in csv.DictReader(r for r in fh if not r.startswith("#")):
            verdicts[row["shot"]] = (row["verdict"], row["marginal"] == "1")
            y_h[row["shot"]] = float(row["y_h"]) if row["y_h"] else None

    scenes, thread, ckpt = load_scenes(here.parents[2] / "yt_flow.db", argv[1])
    if not scenes:
        print(f"nothing to measure for thread_id LIKE '{argv[1]}%'")
        return 3

    rows = []
    for scene in scenes:
        for shot in scene.get("shots") or []:
            sid, prompt = shot.get("shot_id"), shot.get("image_prompt") or ""
            if sid not in verdicts:
                print(f"shot {sid} has no adjudicated viewpoint — refusing a partial test", file=sys.stderr)
                return 3
            words = len(prompt.split())
            surface = sum(len(re.findall(p, prompt, re.IGNORECASE)) for p in _SURFACE.values())
            decoy = sum(len(re.findall(p, prompt, re.IGNORECASE)) for p in _LIGHTING_DECOYS.values())
            rows.append((sid, shot.get("camera_angle"), words, surface, decoy, *verdicts[sid],
                         prompt.split(",", 1)[0]))

    print(f"run {argv[1]}: {len(rows)} shots — thread {thread} @ {ckpt}\n")
    print(f"{'shot':8} {'field':18} {'words':>5} {'(i)surf':>8} {'/100w':>6} {'(ii)lite':>8} "
          f"{'y_h':>5}  verdict")
    for sid, field, words, surface, decoy, verdict, marginal, _ in rows:
        print(f"{sid:8} {str(field):18} {words:>5} {surface:>8} {100 * surface / max(words, 1):>6.1f} "
              f"{decoy:>8} {('%.2f' % y_h[sid]) if y_h[sid] is not None else '   - ':>5}  "
              f"{verdict}{' *' if marginal else ''}")

    dec = [r for r in rows if r[5] != "UNREADABLE"]
    print(f"\nviewpoints: {dict(Counter(r[5] for r in rows))}  "
          f"(UNREADABLE excluded from the tests: {len(rows) - len(dec)})")

    surf = sorted(r[3] for r in dec)
    med = surf[len(surf) // 2]
    p_i = _table(f"AXIS (i) 내용 질량 — 표면 어휘 히트 (split at median {med})",
                 [(r[0], int(r[3] >= med), r[5]) for r in dec],
                 f"surface >= {med}", f"surface < {med}")
    p_ii = _table("AXIS (ii) 조명 어휘 — overhead / from above / ceiling-mounted",
                  [(r[0], int(r[4] > 0), r[5]) for r in dec], "lighting hit >= 1", "no hit")

    print("\n두 축이 갈라지는 샷 (판별력 있는 표본):")
    print(f"  {'shot':8} {'field':18} {'(i)':>4} {'(ii)':>5}  verdict")
    for r in sorted(dec, key=lambda r: (-r[4], r[3])):
        hi_i, hi_ii = r[3] >= med, r[4] > 0
        if hi_i != hi_ii:
            print(f"  {r[0]:8} {str(r[1]):18} {r[3]:>4} {r[4]:>5}  {r[5]}")

    # ── report.md §8-2/§8-4가 인용하는 확인들. 주효과 표 하나로 결론을 내면 안 된다:
    # 두 축은 이 런에서 음의 상관이라 서로를 오염시키고, 경계 판정 13건이 두 p값을 떠받친다.
    print("\n층화 — 한 축을 고정하고 다른 축이 예측하는지 (주효과 표의 교란 확인)")
    for lab, keep in (("(ii)=0", lambda r: r[4] == 0), ("(ii)>=1", lambda r: r[4] > 0)):
        sub = [r for r in dec if keep(r)]
        _table(f"  {lab} (n={len(sub)}) 안에서 축 (i)", [(r[0], int(r[3] >= med), r[5]) for r in sub],
               f"surface >= {med}", f"surface < {med}")
    for lab, keep in ((f"(i)<{med}", lambda r: r[3] < med), (f"(i)>={med}", lambda r: r[3] >= med)):
        sub = [r for r in dec if keep(r)]
        _table(f"  {lab} (n={len(sub)}) 안에서 축 (ii)", [(r[0], int(r[4] > 0), r[5]) for r in sub],
               "lighting >= 1", "no hit")

    print("\n축 (ii) 용량-반응 (단조가 아니면 '어휘가 카메라를 올린다'는 읽기가 약해진다)")
    for k in sorted({r[4] for r in dec}):
        sub = [r for r in dec if r[4] == k]
        hi = sum(r[5] == "HIGH" for r in sub)
        print(f"  hits={k}  n={len(sub):<3} HIGH={hi} ({hi / len(sub):.0%})"
              + ("   " + " ".join(f"{r[0]}:{r[5]}" for r in sub) if len(sub) <= 4 else ""))

    nm = [r for r in dec if not r[6]]
    med_nm = sorted(r[3] for r in nm)[len(nm) // 2]
    print(f"\n민감도 — 경계 +-0.05 판정 {len(dec) - len(nm)}건 제외 (n={len(nm)})")
    _table(f"  축 (i) (median {med_nm})", [(r[0], int(r[3] >= med_nm), r[5]) for r in nm],
           f"surface >= {med_nm}", f"surface < {med_nm}")
    _table("  축 (ii)", [(r[0], int(r[4] > 0), r[5]) for r in nm], "lighting >= 1", "no hit")

    print("\n통제축 — 축 (i)이 사실 프롬프트 '길이'인지 (사후, 탐색적)")
    medw = sorted(r[2] for r in dec)[len(dec) // 2]
    _table(f"  총 단어수 (median {medw}) — 짧은 쪽이 부감이면 (i)은 길이의 대리변수다",
           [(r[0], int(r[2] < medw), r[5]) for r in dec], f"words < {medw}", f"words >= {medw}")
    rate = sorted(100 * r[3] / r[2] for r in dec)[len(dec) // 2]
    _table(f"  축 (i)을 100단어당 정규화 (median {rate:.1f})",
           [(r[0], int(100 * r[3] / r[2] >= rate), r[5]) for r in dec],
           f"surf/100w >= {rate:.1f}", f"surf/100w < {rate:.1f}")

    print("\n사후·탐색적 축 — 확정 근거로 쓰지 말 것 (같은 런 단일 표본, 다중검정 미보정)")
    noha = [r for r in dec if r[1] != "high-angle"]
    _table(f"  (iii) 선언 버킷이 medium인가 (high-angle 제외, n={len(noha)})",
           [(r[0], int(r[1] == "medium"), r[5]) for r in noha], "medium", "그 외")
    plane = r"\b(floors?|ground|tables?|gurney|slab|basins?|tub|desks?|hatch|drain|grate|grating|bed|stretcher|trolley|cart|countertop|bench)\b"
    _table("  (기각) 슬롯-1이 수평면 명사를 지목하는가",
           [(r[0], int(bool(re.search(plane, r[7], re.IGNORECASE))), r[5]) for r in dec],
           "수평면 명사 있음", "없음")
    _table("  (기각) 슬롯-1 절이 4단어 이하인가",
           [(r[0], int(len(r[7].split()) <= 4), r[5]) for r in dec], "<= 4 단어", "> 4 단어")

    print("\n필드 대 렌더 시점 (§4-4 본문과 별개 — 필드는 배경 프롬프트에 안 들어간다):")
    per_field = Counter((str(r[1]), r[5]) for r in rows)
    for field in sorted({str(r[1]) for r in rows}):
        tot = sum(v for (f, _), v in per_field.items() if f == field)
        got = {v: n for (f, v), n in per_field.items() if f == field}
        print(f"  {field:18} n={tot:<3} " + "  ".join(f"{k}={v}" for k, v in sorted(got.items())))

    unreq = [r for r in dec if r[5] == "HIGH" and r[1] != "high-angle"]
    print(f"\n②의 모집단 (report.md §8-4) — 요청하지 않은 부감 {len(unreq)}/{len(noha)} "
          f"(경계 판정 제외 시 {sum(not r[6] for r in unreq)}):")
    print("  " + " ".join(r[0] for r in unreq))
    ha = [r for r in dec if r[1] == "high-angle"]
    wide = [r for r in dec if r[1] == "wide"]
    print(f"  회귀 감시선: high-angle {sum(r[5] == 'HIGH' for r in ha)}/{len(ha)} 지켜짐, "
          f"wide 눈높이 {sum(r[5] == 'EYE' for r in wide)}/{len(wide)}")

    if min(p_i, p_ii) >= 0.05:
        print("\n두 축 모두 p >= 0.05 — (a)와 (b) 둘 다 기각, 세 번째 층을 봐야 한다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
