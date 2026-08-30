#!/usr/bin/env python
"""동일 입력 · 동일 시드 · 동일 지시문으로 N회 반복 렌더해 비결정성의 크기를 잰다.

VETO가 드러낸 것은 "갈린다"는 사실뿐이고 크기는 미측정이다(`VERDICT.md` §3·§6).
이 스크립트는 무효 대조군 3샷(`near` 패스 없음 = 이 스토리의 편집이 안 닿는 샷)을
반복 렌더해 산포를 낸다. 편집 효과가 이 산포보다 작으면 그 편집은 이 표본으로
측정 불가이고, 크면 표본을 얼마나 키워야 하는지가 나온다.

재산출:
    uv run python .../measure_nondeterminism.py --reps 5
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
HERE = Path(__file__).parent

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.shot_recompose import recompose_shot  # noqa: E402

SEED_WORKFLOW = "data/workflows/comfyui_shot_recompose_qwen_seed20260830.json"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--shots", default="S00702,S00800,S00904",
                    help="기본값은 무효 대조군 — 편집이 닿지 않는 샷들이다")
    args = ap.parse_args()

    from yt_flow.services import comfyui_client, recompose_service
    from yt_flow.services.recompose_service import CARD_LOOKS

    settings = Settings()
    failure = await recompose_service._preflight(settings)
    if failure:
        print(f"HALT: preflight {failure[0]}")
        return 3

    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    want = set(args.shots.split(","))
    shots = [s for s in manifest["shots"] if s["shot_id"] in want]
    out_dir = HERE / "nondeterminism"
    out_dir.mkdir(exist_ok=True)

    rows = []
    for shot in shots:
        digests, sizes = [], []
        for rep in range(args.reps):
            t0 = time.monotonic()
            image = await recompose_shot(
                Path(shot["plate"]), [dict(c) for c in shot["cast"]], CARD_LOOKS,
                comfyui_client, SEED_WORKFLOW, settings.comfyui_url,
                shot_id=f"nd{rep}:{shot['shot_id']}",
            )
            if image is None:
                print(f"  ! {shot['shot_id']} rep{rep}: 렌더 실패")
                continue
            (out_dir / f"{shot['shot_id']}_r{rep}.png").write_bytes(image)
            digests.append(_sha(image))
            sizes.append(len(image))
            print(f"  {shot['shot_id']} rep{rep}  sha {digests[-1]}  "
                  f"{len(image)}B  {time.monotonic()-t0:.1f}s", flush=True)
        rows.append({
            "shot_id": shot["shot_id"], "reps": len(digests),
            "distinct_sha": len(set(digests)), "sha": digests,
            "bytes_min": min(sizes) if sizes else None,
            "bytes_max": max(sizes) if sizes else None,
        })
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seed_workflow": SEED_WORKFLOW,
        "seed_workflow_sha256": _sha(Path(SEED_WORKFLOW).read_bytes()),
        "note": "동일 플레이트·카드·지시문·시드·워크플로. 차이는 렌더 비결정성뿐이다.",
        "rows": rows,
    }
    (HERE / "nondeterminism.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n--- 요약 ---")
    for r in rows:
        print(f"{r['shot_id']}: {r['reps']}회 중 서로 다른 이미지 {r['distinct_sha']}종, "
              f"바이트 {r['bytes_min']}~{r['bytes_max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
