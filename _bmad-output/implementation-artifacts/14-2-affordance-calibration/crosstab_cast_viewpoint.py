#!/usr/bin/env python
"""cast × 시점 × 어포던스 교차표 — Story 14.2 라벨 검증. GPU 0, VLM 0.

    uv run python .../crosstab_cast_viewpoint.py <thread_prefix> [affordance_report.json]

§4-4가 손으로 라벨한 시점 판정(`14-0-angle-conflict/viewpoint_verdicts.csv`,
소실점 세로 위치 `y_h`)을 체크포인트의 `cast` 와 붙인다. 존재 이유는 하나다 — "부감이니까
사람을 놓을 수 없다"가 참인지 확인하는 것이고, 실측 결과 **거짓**이다. 시점 라벨은 이미
사람이 판정해 커밋돼 있으므로 이 대조는 VLM 콜도 렌더도 쓰지 않는다.

두 번째 인자로 `assess_plate_affordance.py` 리포트를 주면 `standing_room` 열이 붙는다.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "_bmad-output/implementation-artifacts/14-0-angle-conflict"))

from measure_angle_agreement import load_scenes, slot1  # noqa: E402

# PREREGISTRATION.md 의 사전등록 라벨. 판정기를 돌리기 전에 고정됐다.
BROKEN = {"S00103", "S00105", "S00201", "S00302", "S00601", "S00602", "S00605"}
MARGINAL = {"S00501"}
# 스토리가 인계받은 라벨 — 위와 서로소인 것이 첫 발견이다.
HANDED_OVER = {"S00504", "S00803"}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    scenes, thread, ckpt = load_scenes(REPO / "yt_flow.db", argv[1])
    if not scenes:
        print(f"no checkpoint with non-empty scenes for {argv[1]!r}", file=sys.stderr)
        return 3

    vp: dict[str, tuple[str, str, str, str]] = {}
    with open(HERE.parent / "14-0-angle-conflict/viewpoint_verdicts.csv") as f:
        for row in csv.DictReader(line for line in f if not line.startswith("#")):
            vp[row["shot"]] = (row["verdict"], row["marginal"], row["y_h"], row["floor_share"])

    aff: dict[str, object] = {}
    if len(argv) > 2:
        for rec in json.loads(Path(argv[2]).read_text()):
            sid = Path(rec["path"]).stem.split("_")[-1]
            aff[sid] = "ERR" if "error" in rec else rec.get("standing_room")

    print(f"thread {thread} @ checkpoint {ckpt}\n")
    print(f"{'shot':8} {'cast':>4} {'field':17} {'y_h':>5} {'flr':>5} {'vp':11} "
          f"{'stand':6} {'label':9} slot1")
    rows = []
    for sc in scenes:
        for sh in sc["shots"]:
            sid = sh["shot_id"]
            n = len(sh.get("cast") or [])
            verdict, marg, yh, fs = vp.get(sid, ("?", "", "", ""))
            label = "BROKEN" if sid in BROKEN else "MARGINAL" if sid in MARGINAL else \
                    "handed" if sid in HANDED_OVER else ("OK" if n else "-")
            stand = {True: "yes", False: "NO", "ERR": "err", None: "?"}.get(aff.get(sid), "")
            rows.append((sid, n, verdict, yh, fs, label, stand))
            print(f"{sid:8} {n:>4} {str(sh.get('camera_angle')):17} {yh:>5} {fs:>5} "
                  f"{verdict + ('*' if marg == '1' else ''):11} {stand:6} {label:9} {slot1(sh['image_prompt'])[:34]}")

    cast = [r for r in rows if r[1] > 0]
    print(f"\n43샷 중 cast 보유 {len(cast)} (= recomposed/ 실물 수)")
    print(f"  cast 보유 시점 분포: {dict(Counter(r[2] for r in cast))}")
    print(f"  cast-free  시점 분포: {dict(Counter(r[2] for r in rows if r[1] == 0))}")

    non_eye = [r for r in cast if r[2] != "EYE"]
    print(f"\n[반증] 시점은 어포던스가 아니다 — cast 보유 중 비-눈높이 {len(non_eye)}건,"
          f" 그 중 사전등록 BROKEN {sum(1 for r in non_eye if r[5] == 'BROKEN')}건")
    print(f"        극단 부감(y_h<=0.15)인데 OK: "
          f"{[r[0] for r in cast if r[3] and float(r[3]) <= 0.15 and r[5] == 'OK']}")
    print(f"        인계 라벨 {sorted(HANDED_OVER)} 의 시점: "
          f"{[(r[0], r[2], f'floor={r[4]}') for r in cast if r[0] in HANDED_OVER]}")

    if aff:
        hit = [r[0] for r in cast if r[5] == "BROKEN" and r[6] == "NO"]
        miss = [r[0] for r in cast if r[5] == "BROKEN" and r[6] == "yes"]
        err = [r[0] for r in cast if r[5] == "BROKEN" and r[6] == "err"]
        fp = [r[0] for r in cast if r[5] in ("OK", "handed") and r[6] == "NO"]
        ok_n = sum(1 for r in cast if r[5] in ("OK", "handed"))
        print(f"\n[사전등록 채점] 재현 {len(hit)}/{len(BROKEN)} {hit}"
              f"\n              미검출 {miss}   판정불가 {err}"
              f"\n              오탐 {len(fp)}/{ok_n} {fp}"
              f"\n  통과조건: 재현 >=6/7 AND 오탐 <=3/25 → "
              f"{'PASS' if len(hit) >= 6 and len(fp) <= 3 else 'FAIL(사전등록 문면대로)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
