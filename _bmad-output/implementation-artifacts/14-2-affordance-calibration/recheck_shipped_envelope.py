#!/usr/bin/env python
"""출하 봉투로 재측정 + 검정-재검정. GPU 0.

    uv run python .../recheck_shipped_envelope.py <run_id> [--passes 2]

존재 이유는 적대적 리뷰 지적 둘이다.

1. **런타임 호출이 캘리브레이션한 호출이 아니었다.** `affordance_33.json` 은
   `scripts/assess_plate_affordance.py` 가 `[image, text]` 순서로, `temperature` 미지정으로
   뽑은 것이고 런타임(`vision_check.plate_has_standing_room`)은 `[text, image]` + `temperature=0`
   이다. 프롬프트 텍스트를 공유하는 이유(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`)가
   **요청 봉투에도 그대로 적용된다** — 이미지·지시 순서는 VLM 판정을 움직인다.
   그래서 이 스크립트는 프롬프트를 다시 쓰지 않고 **런타임 함수를 직접 호출한다.**

2. **판정기는 비결정적인데 표본이 1회였다.** `vision_check` 모듈 독스트링이 스스로
   그렇게 적어뒀다. 오탐 1/25 는 사전등록의 삭제 금지선(3/25)에서 두 번 뒤집히면 닿는다
   (`gotcha_same-prompt-reseed-flips-the-viewpoint` 계열). 같은 프레임을 N회 물어 **뒤집힘
   비율**을 재고, 그 밴드 없이는 기본값을 결정하지 않는다.
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.services.vision_check import plate_has_standing_room  # noqa: E402

# PREREGISTRATION.md 의 사전등록 라벨(판정기 실행 전 고정).
BROKEN = {"S00103", "S00105", "S00201", "S00302", "S00601", "S00602", "S00605"}
MARGINAL = {"S00501"}


async def run(args) -> int:
    s = Settings()
    if not s.character_vision_api_key:
        print("YTFLOW_CHARACTER_VISION_API_KEY is not set", file=sys.stderr)
        return 2
    base = REPO / "workspace" / args.run_id
    shots = sorted(p.name.split("_")[0] for p in (base / "recomposed").glob("S*.png"))
    plates = {sid: next(base.joinpath("images").glob(f"scene_*_{sid}.png")) for sid in shots}
    print(f"{len(plates)} cast-bearing plate(s) × {args.passes} pass(es) "
          f"— 출하 봉투(vision_check.plate_has_standing_room)\n")

    sem = asyncio.Semaphore(args.concurrency)
    verdicts: dict[str, list] = {sid: [] for sid in shots}

    async def one(sid: str, path: Path) -> None:
        async with sem:
            verdicts[sid].append(await plate_has_standing_room(path.read_bytes(), s))

    for p in range(args.passes):
        await asyncio.gather(*(one(sid, plates[sid]) for sid in shots))
        print(f"  pass {p + 1} 완료")

    stable_no, stable_yes, flipped, undec = [], [], [], []
    for sid, vs in verdicts.items():
        decided = [v for v in vs if v is not None]
        if not decided:
            undec.append(sid)
        elif len(set(decided)) > 1 or len(decided) != len(vs):
            flipped.append((sid, vs))
        elif decided[0] is False:
            stable_no.append(sid)
        else:
            stable_yes.append(sid)

    print(f"\n안정 false {len(stable_no)}: {stable_no}")
    print(f"안정 true  {len(stable_yes)}")
    print(f"**뒤집힘 {len(flipped)}**: {flipped}")
    print(f"전 패스 판정불가 {len(undec)}: {undec}")

    # 다수결(비결정성을 흡수하는 유일한 정직한 축약)로 채점.
    def majority(vs):
        d = [v for v in vs if v is not None]
        if not d:
            return None
        return Counter(d).most_common(1)[0][0]

    maj = {sid: majority(vs) for sid, vs in verdicts.items()}
    hit = sorted(sid for sid in BROKEN if maj.get(sid) is False)
    miss = sorted(sid for sid in BROKEN if maj.get(sid) is True)
    err = sorted(sid for sid in BROKEN if maj.get(sid) is None)
    ok_pop = [sid for sid in shots if sid not in BROKEN and sid not in MARGINAL]
    fp = sorted(sid for sid in ok_pop if maj.get(sid) is False)
    print(f"\n[다수결 채점] 재현 {len(hit)}/{len(BROKEN)} {hit}\n"
          f"              미검출 {miss}   판정불가 {err}\n"
          f"              오탐 {len(fp)}/{len(ok_pop)} {fp}\n"
          f"  사전등록: 재현 >=6/7 AND 오탐 <=3/25 → "
          f"{'PASS' if len(hit) >= 6 and len(fp) <= 3 else 'FAIL'}")

    out = HERE / args.report
    out.write_text(json.dumps({"run_id": args.run_id, "passes": args.passes,
                               "envelope": "vision_check.plate_has_standing_room",
                               "verdicts": verdicts}, indent=2))
    print(f"\nreport: {out.name}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_id")
    p.add_argument("--passes", type=int, default=2)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--report", default="affordance_shipped_envelope.json")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
