#!/usr/bin/env python
"""프롬프트 팔레트/화풍 어휘 전수 스캔 — 텍스트 반증의 재산출. Story 14.3. GPU 0 · VLM 0.

    uv run python .../prompt_vocab_scan.py <run_id>

에픽이 Jay 판정 ⑦("화풍 유지 안 됨")에 대해 적어둔 처방은 *"팔레트·조명·렌더 스타일을 닫힌
어휘로 제약"* 이다. 그 처방이 성립하려면 **지울 단어가 있어야** 한다. 이 스크립트는 43샷의
`image_prompt` 를 닫힌 어휘 목록으로 훑어 그것을 확인한다.

**스코프**: `image_prompt` 는 **플레이트를 그린 텍스트**다. 이 런의 출하 프레임 33/43 을 그린
텍스트는 `shot_recompose.placement_instruction` 이고, 그쪽에는 화풍 절이 **있다**
(*"rendered in the same illustration style as the background"*). 따라서 여기서 나오는 결론은
**플레이트 생성 층에 한정된다.** 리포트 §4 가 같은 절에서 그것을 밝힌다.

결론은 하드코딩돼 있지 않다 — 실제 산출된 p 와 항목 수로 분기해 문장을 고른다.
"""
import json
import re
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# `epics.md:1901` 의 화풍 이탈 라벨. Claude 단독 · Jay 확인 대기.
DRIFT_LABELS = {"S00501", "S00301", "S00605", "S00701", "S00105", "S00403", "S00303"}

# 닫힌 어휘 — "팔레트·조명·렌더 스타일을 제약한다"가 지울 수 있었을 단어들. 라벨의 서술
# (마젠타·시안 / 형광 녹색 / 핑크·블루 / 플랫 아이소메트릭 스케치)에서 뽑았고, 계열 전체를
# 덮도록 넓혔다.
#
# `fluorescent` 는 **일부러 빼 뒀다.** 43샷 중 22샷에 있고 전부 `fluorescent lighting`,
# 즉 형광등이라는 **조명 기구 명사**다. 그것을 어휘에 넣으면 스캔은 절반의 샷을 "네온
# 어휘 보유"로 세고 판별력을 0으로 만드는 대신 0으로 만든 것을 감춘다 — 같은 이유로
# `LED` 도 히트하되 그 성격(기구 명사)을 리포트에 적는다.
VOCAB = [
    # 네온/사이버펑크 계열
    "neon", "cyberpunk", "synthwave", "vaporwave", "retrowave", "holographic", "hologram",
    "iridescent", "psychedelic", "glitch", "chromatic aberration",
    # 라벨이 지목한 색 이름
    "magenta", "fuchsia", "cyan", "teal", "turquoise", "chartreuse", "lime",
    "acid green", "hot pink", "electric blue",
    # 포화색을 만드는 광원 명사
    "led", "rgb lighting", "ultraviolet", "blacklight", "black light", "uv light", "laser",
    # 이질 렌더 스타일
    "isometric", "flat vector", "vector art", "cel-shaded", "cel shaded", "pixel art",
    "watercolor", "watercolour", "comic book", "manga", "oil painting", "pastel",
    # 채도 자체를 지시하는 형용사
    "duotone", "technicolor", "saturated", "vivid", "garish", "lurid",
]
# 단어 경계 필수: 없으면 `swelled` 안의 `led` 가 걸린다.
PATTERNS = {term: re.compile(rf"\b{re.escape(term)}\b", re.I) for term in VOCAB}


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """2×2 Fisher 정확검정 양측 — 관측 표보다 확률이 크지 않은 모든 표의 확률 합.

    stdlib 로 직접 쓴 이유는 이 저장소에 scipy 가 없고 넣지 않기 때문이다(ponytail:
    한 함수를 위해 의존성을 늘리지 않는다). 정의는 표준 초기하 합이고, `scipy.stats
    .fisher_exact(..., alternative="two-sided")` 와 같은 값을 준다.
    """
    n = a + b + c + d
    row1, col1 = a + b, a + c

    def probability(x: int) -> float:
        return comb(row1, x) * comb(c + d, col1 - x) / comb(n, col1)

    observed = probability(a)
    lo, hi = max(0, col1 - (c + d)), min(row1, col1)
    # 1e-9 여유: 대칭 표의 확률은 부동소수점에서 미세하게 어긋난다.
    return sum(p for x in range(lo, hi + 1) if (p := probability(x)) <= observed * (1 + 1e-9))


def scan(run_dir: Path) -> tuple[dict[str, list[str]], list[str]]:
    hits: dict[str, list[str]] = {}
    unreadable: list[str] = []
    for path in sorted((run_dir / "images").glob("*_done.json")):
        shot_id = path.stem.rsplit("_", 1)[0].rsplit("_", 1)[-1]
        try:
            prompt = json.loads(path.read_text(encoding="utf-8"))["image_prompt"]
            assert isinstance(prompt, str)
        except Exception as exc:  # noqa: BLE001 — 사이드카 한 장이 스캔 전체를 죽이지 않는다
            unreadable.append(f"{shot_id}: {type(exc).__name__}: {exc}")
            continue
        hits[shot_id] = sorted(t for t, p in PATTERNS.items() if p.search(prompt))
    return hits, unreadable


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_dir = REPO / "workspace" / argv[1]
    hits, unreadable = scan(run_dir)
    if not hits:
        print(f"no readable sidecars under {run_dir / 'images'}", file=sys.stderr)
        return 3
    if unreadable:
        print(f"UNREADABLE {len(unreadable)}: " + "; ".join(unreadable), file=sys.stderr)

    labelled = {s for s in hits if s in DRIFT_LABELS}
    drift_hit = sorted(s for s in labelled if hits[s])
    other_hit = sorted(s for s in hits if s not in labelled and hits[s])
    a, b = len(drift_hit), len(labelled) - len(drift_hit)
    c, d = len(other_hit), len(hits) - len(labelled) - len(other_hit)
    p = fisher_two_sided(a, b, c, d)
    found = sorted({t for terms in hits.values() for t in terms})

    print(f"run {argv[1]} — image_prompt vocabulary scan over {len(hits)} shots "
          f"({len(VOCAB)} terms, word-boundary matched)")
    print(f"  drift-labelled    {a}/{a + b}  {drift_hit}")
    print(f"  not drift-labelled {c}/{c + d}  {other_hit}")
    print(f"  terms found in the whole corpus: {found or '(none)'}")
    print(f"  Fisher exact, two-sided: p = {p:.3f}")

    print("\n  verdict (computed, not hardcoded):")
    if not found:
        print("    NO palette/style vocabulary exists in ANY of the 43 prompts. The epic's "
              "prescription — constrain the palette to a closed vocabulary — has nothing "
              "to delete at the plate-generation layer.")
    elif p < 0.05:
        print(f"    the split DISCRIMINATES (p = {p:.3f} < 0.05): {found} separates the "
              "drift-labelled shots from the rest. A vocabulary constraint has a target.")
    else:
        rate_drift = a / (a + b) if a + b else 0.0
        rate_other = c / (c + d) if c + d else 0.0
        print(f"    the split does NOT discriminate (p = {p:.3f}): {rate_drift:.0%} of "
              f"drift-labelled prompts carry a term vs {rate_other:.0%} of the rest. "
              f"The only term present is {found}.")
        print("    So the epic's prescription cannot be executed at the plate-generation "
              "layer: there is no neon/foreign-style wording to remove.")
    print("\n  SCOPE: image_prompt drew the PLATES. The delivered frames (33/43 of this run) "
          "were drawn by shot_recompose.placement_instruction, which DOES carry a style "
          "clause. This result does not speak about that text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
