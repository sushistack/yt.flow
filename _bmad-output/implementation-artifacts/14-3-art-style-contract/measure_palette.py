#!/usr/bin/env python
"""팔레트 측정 — 두 모집단(플레이트 면 / 출하 면) 각각. Story 14.3. GPU 0 · VLM 0.

    uv run python .../measure_palette.py <run_id> [--surface plate|delivered|both]

정의는 `PREREGISTRATION.md` §2 와 **같은 값이 여기 코드에도 적혀 있다**. 특히 `resample`은
`Image.Resampling.BICUBIC` 을 **명시**한다 — Pillow 12.3 의 `resize()` 기본값이 NEAREST 가
아니라 BICUBIC 이고, 인용된 수치는 인자 없이 뽑혔으므로 BICUBIC 수치다. 기본값에 기대면
Pillow 가 바뀌는 날 조용히 다른 숫자가 나온다.

두 면을 나누는 이유: `images/*.png` 는 recompose **이전** 플레이트이고, 이 런이 영상에
실제로 내보낸 프레임은 `recomposed/` 의 33장 + 나머지 10장의 플레이트다. Jay 가 판정한 것은
후자이고, 화풍 표류 라벨 7건 중 6건이 recompose된 샷이다. 두 면은 같은 순위를 주지 않는다.

CSV 파일명과 모든 행에 `run_id` 가 실린다. 다른 런으로 돌려도 커밋된 증거를 덮어쓰지 않는다.
"""
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# `epics.md:1901` (2026-08-17, E2E iteration 4 시청 직후) 의 화풍 이탈 라벨.
# **Claude 단독이며 Jay 확인 대기 중이다** — 이 목록은 순위표에 주석을 붙이는 용도이고
# 어떤 커트의 근거도 아니다(PREREGISTRATION.md §6).
DRIFT_LABELS = {"S00501", "S00301", "S00605", "S00701", "S00105", "S00403", "S00303"}

# PREREGISTRATION.md §2. 코드와 문서에 같은 값이 적혀 있어야 한다.
RESIZE_TO = (256, 144)
RESAMPLE = Image.Resampling.BICUBIC
VIVID_S = 0.55
VIVID_V = 0.35


def measure(path: Path) -> dict[str, float]:
    hsv = Image.open(path).convert("RGB").resize(RESIZE_TO, resample=RESAMPLE).convert("HSV")
    a = np.asarray(hsv, dtype=np.float64) / 255.0
    s, v = a[..., 1], a[..., 2]
    return {
        "sat_mean": float(s.mean()),
        "vivid_frac": float(((s > VIVID_S) & (v > VIVID_V)).mean()),
        "sat_p95": float(np.percentile(s, 95)),
    }


def plates(run_dir: Path) -> dict[str, Path]:
    """shot_id -> 플레이트. 파일명 `scene_NNN_SXXXXX.png` 의 마지막 절이 shot_id."""
    return {p.stem.rsplit("_", 1)[-1]: p for p in sorted(run_dir.glob("images/scene_*_S*.png"))}


def recomposed(run_dir: Path) -> dict[str, Path]:
    """shot_id -> 출하 프레임. 한 샷에 둘 이상이면 파일명 정렬 첫 번째(결정적)."""
    out: dict[str, Path] = {}
    for p in sorted((run_dir / "recomposed").glob("*.png")):
        out.setdefault(p.name.split("_")[0], p)
    return out


def rows(run_id: str, run_dir: Path, surface: str) -> tuple[list[dict], list[str]]:
    plate_by_shot = plates(run_dir)
    rec_by_shot = recomposed(run_dir) if surface == "delivered" else {}
    out, skipped = [], []
    for shot_id, plate in plate_by_shot.items():
        src = rec_by_shot.get(shot_id, plate)
        try:
            stats = measure(src)
        except Exception as exc:  # noqa: BLE001 — 한 장이 깨져도 나머지 42장은 측정된다
            skipped.append(f"{shot_id}: {type(exc).__name__}: {exc}")
            continue
        out.append({
            "run_id": run_id,
            "surface": surface,
            "shot_id": shot_id,
            "source": "recomposed" if shot_id in rec_by_shot else "plate",
            "source_path": str(src.relative_to(run_dir)),
            "claude_drift_label": int(shot_id in DRIFT_LABELS),
            **{k: f"{v:.6f}" for k, v in stats.items()},
        })
    out.sort(key=lambda r: -float(r["vivid_frac"]))
    for i, r in enumerate(out):
        r["vivid_rank"] = i
    return out, skipped


def report(run_id: str, run_dir: Path, surface: str) -> None:
    data, skipped = rows(run_id, run_dir, surface)
    dest = HERE / f"palette_{surface}_{run_id}.csv"
    with dest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "surface", "shot_id", "source", "source_path",
            "claude_drift_label", "sat_mean", "vivid_frac", "sat_p95", "vivid_rank",
        ])
        writer.writeheader()
        writer.writerows(data)

    counts = {"recomposed": sum(r["source"] == "recomposed" for r in data),
              "plate": sum(r["source"] == "plate" for r in data)}
    print(f"\n── surface={surface}  n={len(data)}  {counts}  -> {dest.name}")
    if skipped:
        print(f"   SKIPPED {len(skipped)}: " + "; ".join(skipped), file=sys.stderr)
    print(f"   {'rank':>4} {'shot':8} {'source':11} {'vivid_frac':>10} {'sat_mean':>9} "
          f"{'sat_p95':>8}  label")
    for r in data[:5]:
        print(f"   {r['vivid_rank']:>4} {r['shot_id']:8} {r['source']:11} "
              f"{float(r['vivid_frac']):10.4f} {float(r['sat_mean']):9.4f} "
              f"{float(r['sat_p95']):8.4f}  {'DRIFT' if r['claude_drift_label'] else ''}")
    ranks = sorted(r["vivid_rank"] for r in data if r["claude_drift_label"])
    print(f"   drift-label ranks (of {len(data)}): {ranks}")
    _stratified(data)
    flat = next((r for r in data if r["shot_id"] == "S00303"), None)
    if flat:
        print(f"   S00303 (flat isometric, the label this axis CANNOT see): "
              f"vivid_frac={float(flat['vivid_frac']):.4f} "
              f"sat_mean={float(flat['sat_mean']):.4f} rank={flat['vivid_rank']}")


def _stratified(data: list[dict]) -> None:
    """출처(recomposed / plate)로 층화한 대조. **이 축의 최대 교란이다.**

    출하 면에서 recompose된 행과 플레이트 행은 **다른 모델이 그렸다** — 앞은 Qwen-Image-Edit,
    뒤는 AnimagineXL. 두 무리의 `vivid_frac` 평균이 통째로 다르므로, 층화하지 않은 순위표에서
    "라벨과 지표가 같이 움직인다"는 관찰은 **어느 모델이 그렸는가**로 상당 부분 설명된다
    (표류 라벨 7건 중 6건도 recompose된 샷이다). 그래서 전체 순위와 **함께** 층 내부 대조를
    찍는다 — 층 안에서도 라벨 쪽이 높은지가 지표가 라벨과 무관하게 무엇을 보는지에 대한
    실제 증거다. 층 크기가 작으므로(플레이트 10행, 그중 라벨 1행) 이것은 검정이 아니라
    **교란의 크기를 눈에 보이게 하는 서술 통계**다 — 임계값 금지 규칙은 그대로다.
    """
    def mean(rows: list[dict]) -> float:
        return sum(float(r["vivid_frac"]) for r in rows) / len(rows) if rows else float("nan")

    print("   -- stratified by source (the confound: a different model drew each stratum) --")
    print(f"   {'source':11} {'n':>3} {'mean vivid':>11} "
          f"{'n label':>7} {'mean label':>11} {'n other':>7} {'mean other':>11}")
    for source in ("recomposed", "plate"):
        stratum = [r for r in data if r["source"] == source]
        if not stratum:
            continue
        labelled = [r for r in stratum if r["claude_drift_label"]]
        other = [r for r in stratum if not r["claude_drift_label"]]
        print(f"   {source:11} {len(stratum):>3} {mean(stratum):>11.4f} "
              f"{len(labelled):>7} {mean(labelled):>11.4f} "
              f"{len(other):>7} {mean(other):>11.4f}")
    top = data[:9]
    print(f"   top-9 by source: " + ", ".join(
        f"{s}={sum(r['source'] == s for r in top)}" for s in ("recomposed", "plate")))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_id = argv[1]
    surface = argv[argv.index("--surface") + 1] if "--surface" in argv else "both"
    if surface not in ("plate", "delivered", "both"):
        print(f"unknown --surface {surface!r}", file=sys.stderr)
        return 2
    run_dir = REPO / "workspace" / run_id
    if not (run_dir / "images").is_dir():
        print(f"no run at {run_dir}", file=sys.stderr)
        return 3
    for one in (("plate", "delivered") if surface == "both" else (surface,)):
        report(run_id, run_dir, one)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
