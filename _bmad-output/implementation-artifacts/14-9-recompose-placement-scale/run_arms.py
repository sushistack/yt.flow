#!/usr/bin/env python
"""Story 14.9 — 3-arm 하네스: `_DEPTH_PHRASE["near"]` 한 줄 편집의 실재성 검정.

    digest-gate   recomposed/ 파일명의 16-hex 를 재현한다 (GPU 0 · LLM 0) -> manifest.json
    render        arm a/b/c 를 이 디렉터리에 낸다                          -> <arm>/*.png + arms.json
    snapshot      arm A 디렉터리의 무손상 스냅샷                            -> recomposed_snapshot_*.json

세 arm:

    A  출하된 프레임. `workspace/<run>/recomposed/` 를 **읽기만** 한다. 렌더 0.
    B  현 문구 + 새 시드
    C  수정 문구 + **B와 같은 시드 · 같은 워크플로 파일**

**왜 `recompose_service.recompose_run_shots` 를 쓰지 않는가.** 그 경로의 digest 입력은
플레이트 바이트 · 카드 경로 · 배치 필드 셋뿐이라(`recompose_service.py:550-554`) 워크플로도
지시문도 시드도 해싱되지 않는다. arm C를 그 경로로 렌더하면 digest가 arm A와 같아 `out.exists()`
가 참이 되고 `recompose_shot` 이 **아예 호출되지 않는다** — 에러도 로그도 없이 `stats` 는
`recomposed: 7` 을 찍고 **arm C가 조용히 arm A가 된다.** 그래서 캐시 검사가 없는
`shot_recompose.recompose_shot` 을 직접 부르고, 출력은 `recomposed/` **밖**에 쓴다.

**시드 레버가 코드에 없다.** `sampler.seed` 가 워크플로 JSON에만 있고 `build_single_pass` 는
plate/card/positive만 쓴다(`recompose_shot` 의 `salt` 는 ComfyUI 업로드 파일명일 뿐 샘플러에
안 닿는다). 그래서 시드는 **워크플로 파일 복사**로만 바뀌고, B와 C는 그 파일 하나를 공유한다.
"""

import argparse
import asyncio
import hashlib
import itertools
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)  # 체크포인트의 모든 플레이트 경로가 저장소 상대다

from yt_flow.config import Settings  # noqa: E402

HERE = Path(__file__).parent
RUN = "4b35c0ed-8a1e-4448-8594-11bd9997376d"
# 읽기 전용 URI. 다른 세션이 같은 파일에 쓴다.
DB_RO = "file:yt_flow.db?mode=ro&uri=true"
TARGET = ["S00105", "S00504", "S00702", "S00800", "S00802", "S00803", "S00904"]

SEED = 20260830
SEED_WORKFLOW = "data/workflows/comfyui_shot_recompose_qwen_seed20260830.json"

# arm 별 `_DEPTH_PHRASE["near"]`. **여기가 B와 C의 유일한 차이다.**
# 하네스가 두 문구를 다 들고 있는 이유: 소스 수정이 언제 들어오든 arm B가 항상
# 편집 **전** 문구로 렌더돼야 하기 때문이다. `590db09` 의 바이트 그대로.
NEAR_BEFORE = "in the foreground close to camera, his whole body from head to feet visible in frame"
NEAR_AFTER = "in the foreground, his whole body from head to feet visible in frame"
ARM_NEAR = {"b": NEAR_BEFORE, "c": NEAR_AFTER}


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)}", flush=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── digest-gate ──────────────────────────────────────────────────────────────


def _card_candidates(conn, settings, card_key: str) -> list[tuple[str, str]]:
    """이 키가 낼 수 있는 모든 `(카드 경로, 해소된 pose)`.

    `_resolve_card_path` 가 낼 수 있는 값의 전수다: 4개 `angle_*_path` 는 언제나 pose
    `"standing"` 으로 해소되고, `character_cards` 행은 자기 `pose` 로 해소된다.
    """
    out: list[tuple[str, str]] = []
    row = conn.execute(
        "select angle_front_path, angle_back_path, angle_side_path, angle_three_quarter_path "
        "from characters where scp_id = ?", (card_key,)).fetchone()
    for path in row or ():
        if path:
            out.append((str(Path(settings.assets_path) / path), "standing"))
    for path, pose in conn.execute(
            "select image_path, pose from character_cards where scp_id = ?", (card_key,)):
        out.append((str(Path(settings.assets_path) / path), pose))
    return out


def _digest(plate_bytes: bytes, cards: list[tuple[str, str]], cast: list[dict]) -> str:
    """`recompose_service` 의 digest 를 그 호출부에서 그대로 옮겨온 것.

    입력 순서는 **매니페스트 순서**(체크포인트의 cast 순서)이지 `order_cast` 순서가 아니다.
    """
    from yt_flow.pipeline.nodes.shot_recompose import recompose_digest

    return recompose_digest(
        plate_bytes,
        [path for path, _ in cards],
        [f"{m['card_key']}|{m.get('position')}|{m.get('depth')}|{pose}"
         for m, (_, pose) in zip(cast, cards)],
    )


async def cmd_digest_gate(args) -> int:
    """arm A의 입력을 증명하는 **유일한** 증거.

    이 런은 14.3 이전에 렌더돼 사이드카에 `recompose` 블록이 없고 카드 경로는 어디에도
    기록돼 있지 않다. 그래서 카드를 재해결해 digest를 재계산하고 파일명과 대조한다.

    재해결은 `resolve_cast_cards` 를 부르지 **않는다** — 그 경로는 앵글 선택에 LLM 호출을
    쓰고 그 값이 오늘 다르게 나오면 "A의 카드가 무엇이었나"를 못 잡는다. 대신 그 리졸버가
    낼 수 있는 `(경로, pose)` 조합을 전수 열거해 digest 가 맞는 조합을 찾는다. 16-hex
    (64비트) 일치는 우연으로 나오지 않으므로, 맞는 조합이 곧 그때 쓰인 카드다.
    """
    from yt_flow.services.eval_service import _load_state
    from yt_flow.services.recompose_service import CARD_LOOKS

    settings = Settings()
    workspace = Path(settings.workspace_path) / RUN
    state = await _load_state(RUN, DB_RO)
    by_shot = {
        shot["shot_id"]: (scene, shot)
        for scene in state["scenes"] for shot in scene.get("shots") or []
    }
    conn = sqlite3.connect(DB_RO, uri=True)
    rows, excluded = [], []
    for shot_id in TARGET:
        if shot_id not in by_shot:
            excluded.append({"shot_id": shot_id, "reason": "체크포인트에 없는 샷"})
            continue
        scene, shot = by_shot[shot_id]
        plate = workspace / "images" / f"scene_{scene['scene_num']:03d}_{shot_id}.png"
        delivered = sorted((workspace / "recomposed").glob(f"{shot_id}_*.png"))
        cast = [m for m in shot.get("cast") or [] if m.get("card_key")]
        if not plate.is_file() or len(delivered) != 1 or not cast:
            excluded.append({"shot_id": shot_id, "reason": (
                f"plate={plate.is_file()} delivered={len(delivered)} cast={len(cast)}")})
            continue
        unknown = [m["card_key"] for m in cast if m["card_key"] not in CARD_LOOKS]
        if unknown:
            excluded.append({"shot_id": shot_id, "reason": f"CARD_LOOKS 에 설명 없음: {unknown}"})
            continue
        want = delivered[0].stem.split("_", 1)[1]
        plate_bytes = plate.read_bytes()
        pools = [_card_candidates(conn, settings, m["card_key"]) for m in cast]
        match = next(
            (combo for combo in itertools.product(*pools)
             if _digest(plate_bytes, list(combo), cast) == want), None)
        if match is None:
            excluded.append({"shot_id": shot_id, "reason": (
                f"digest 재현 실패 — 파일명 {want}, 후보 조합 "
                f"{len(list(itertools.product(*pools)))}개 전수 불일치. arm A는 이 샷의 대조가 아니다")})
            print(f"  ✗ {shot_id}  {want}  재현 실패", flush=True)
            continue
        rows.append({
            "shot_id": shot_id,
            "scene_num": scene["scene_num"],
            "plate": str(plate),
            "delivered": str(delivered[0]),
            "digest_from_filename": want,
            "digest_recomputed": _digest(plate_bytes, list(match), cast),
            "digest_matches": True,
            "camera_angle": shot.get("camera_angle"),
            "cast": [
                {"card_key": m["card_key"], "position": m.get("position", "center"),
                 "depth": m.get("depth", "mid"), "pose": pose, "path": path,
                 "pose_in_checkpoint": m.get("pose"), "pose_hint": m.get("pose_hint")}
                for m, (path, pose) in zip(cast, match)
            ],
        })
        print(f"  ✓ {shot_id}  {want}  재현", flush=True)

    near = [r["shot_id"] for r in rows if any(c["depth"] == "near" for c in r["cast"])]
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": RUN,
        "checkpoint": DB_RO,
        "target": TARGET,
        "reproduced": [r["shot_id"] for r in rows],
        "excluded": excluded,
        "treatment_shots": near,
        "null_control_shots": [r["shot_id"] for r in rows if r["shot_id"] not in near],
        "passes_per_arm": sum(len(r["cast"]) for r in rows),
        "seed": SEED,
        "seed_workflow": SEED_WORKFLOW,
        "near_before": NEAR_BEFORE,
        "near_after": NEAR_AFTER,
        "shots": rows,
    }
    _write(HERE / "manifest.json", payload)
    print(f"digest-gate: {len(rows)}/{len(TARGET)} 재현, 제외 {len(excluded)}")
    print(f"  처치 {len(near)}샷 {near}")
    print(f"  무효 대조군 {len(payload['null_control_shots'])}샷 {payload['null_control_shots']}")
    if not rows:
        print("HALT: 재현된 샷이 0건 — arm A는 어떤 샷의 대조도 아니다 (Block If)")
        return 2
    return 0


def _manifest() -> dict:
    return json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


# ── arm A 무손상 스냅샷 ───────────────────────────────────────────────────────


def _snapshot() -> dict:
    """`recomposed/` 의 `(name, size, mtime_ns)` 정렬 목록과 그 sha256.

    `git status --porcelain` 은 여기서 공허하다 — 이 경로는 설계상 ignore 된다
    (`gotcha_gitignored-file-makes-git-status-vacuous`).
    """
    directory = Path(Settings().workspace_path) / RUN / "recomposed"
    entries = sorted(
        (p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir())
    return {
        "dir": str(directory),
        "files": len(entries),
        "sha256": _sha(json.dumps(entries)),
        "entries": [{"name": n, "size": s, "mtime_ns": m} for n, s, m in entries],
    }


def cmd_snapshot(args) -> int:
    _write(HERE / f"recomposed_snapshot_{args.label}.json", _snapshot())
    return 0


# ── render ───────────────────────────────────────────────────────────────────


class _Recorder:
    """`comfyui_client` 를 감싸 **실제로 전송된** 지시문을 잡는다.

    `placement_instruction` 을 하네스에서 다시 계산하면 "전송된 것"이 아니라 "전송됐을
    것"을 기록하게 된다. 여기서는 제출 직전 그래프의 `positive.inputs.prompt` 를 읽으므로
    와이어 값 자체다 (`gotcha_attribution-must-ride-the-channel-that-fires`).
    """

    def __init__(self, client):
        self._client = client
        self.passes: list[dict] = []

    async def upload_image(self, url, data, name):
        return await self._client.upload_image(url, data, name)

    async def submit_and_fetch(self, url, workflow):
        prompt = workflow["positive"]["inputs"]["prompt"]
        self.passes.append({
            "index": len(self.passes),
            "instruction": prompt,
            "instruction_sha256": _sha(prompt),
            "seed": workflow["sampler"]["inputs"]["seed"],
            "plate_upload": workflow["plate"]["inputs"]["image"],
            "card_upload": workflow["card_a"]["inputs"]["image"],
        })
        return await self._client.submit_and_fetch(url, workflow)


@contextmanager
def _near_phrase(phrase: str):
    """`_DEPTH_PHRASE["near"]` 를 한 arm 동안만 갈아 끼운다.

    ponytail: 모듈 상수 하나를 바꿔 끼우는 것이, 워크플로 파일처럼 프롬프트에도 arm 별
    사본을 만드는 것보다 작다 — 그리고 arm B와 C가 **같은 코드 경로**를 지난다는 것이
    이 실험의 전제다. `placement_instruction` 이 이 dict 를 호출 시점에 읽으므로 인자를
    새로 뚫을 필요가 없다.
    """
    from yt_flow.pipeline.nodes import shot_recompose

    before = shot_recompose._DEPTH_PHRASE["near"]
    shot_recompose._DEPTH_PHRASE["near"] = phrase
    try:
        yield
    finally:
        shot_recompose._DEPTH_PHRASE["near"] = before


def _reframe(src: Path, out: Path) -> None:
    """세 arm 공통 리프레이밍 체인. 해상도·크롭으로 arm 이 식별되면 블라인드가 아니다."""
    from yt_flow.pipeline.nodes import video as video_node

    chain = video_node._zoompan_filter(video_node._FUSION_STILL_SPEC, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(video_node.FPS),
         "-i", str(src), "-vf", chain, "-frames:v", "1", "-update", "1", str(out)],
        check=True, capture_output=True)


def _dimensions(path: Path) -> str:
    from yt_flow.domain.png import dimensions

    size = dimensions(path.read_bytes())
    return f"{size[0]}x{size[1]}" if size else "?"


async def _render_arm(arm: str, manifest: dict, settings) -> dict:
    """arm B/C 한 쪽. `recompose_shot` 직접 호출 — 캐시 검사가 없는 경로다."""
    from yt_flow.pipeline.nodes.shot_recompose import recompose_shot
    from yt_flow.services import comfyui_client
    from yt_flow.services.recompose_service import CARD_LOOKS

    raw_dir = HERE / "raw" / arm
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for shot in manifest["shots"]:
        recorder = _Recorder(comfyui_client)
        started = time.monotonic()
        with _near_phrase(ARM_NEAR[arm]):
            image = await recompose_shot(
                Path(shot["plate"]),
                [dict(c) for c in shot["cast"]],
                CARD_LOOKS,
                recorder,
                SEED_WORKFLOW,
                settings.comfyui_url,
                shot_id=f"{arm}:{shot['shot_id']}",
            )
        elapsed = round(time.monotonic() - started, 1)
        if image is None or len(recorder.passes) != len(shot["cast"]):
            failed.append({"shot_id": shot["shot_id"],
                           "reason": f"image={image is not None} passes={len(recorder.passes)}"})
            print(f"  ! {arm} {shot['shot_id']}: 렌더 실패, 이 샷은 스킵", flush=True)
            continue
        raw = raw_dir / f"{shot['shot_id']}.png"
        raw.write_bytes(image)
        out = HERE / f"arm_{arm}" / f"{shot['shot_id']}.png"
        _reframe(raw, out)
        rows.append({
            "shot_id": shot["shot_id"], "raw": str(raw.relative_to(ROOT)),
            "path": str(out.relative_to(ROOT)), "raw_size": _dimensions(raw),
            "size": _dimensions(out), "seconds": elapsed,
            "seconds_per_pass": round(elapsed / len(recorder.passes), 1),
            "passes": recorder.passes,
        })
        print(f"  ✓ {arm} {shot['shot_id']}  {len(recorder.passes)}패스  "
              f"{rows[-1]['raw_size']} -> {rows[-1]['size']}  {elapsed}s", flush=True)
    return {"arm": arm, "near_phrase": ARM_NEAR[arm], "seed": SEED,
            "workflow": SEED_WORKFLOW, "workflow_sha256": _sha(Path(SEED_WORKFLOW).read_text()),
            "rendered": len(rows), "failed": failed, "frames": rows}


def _publish_a(manifest: dict) -> dict:
    """arm A: 출하된 프레임을 **읽기만** 해서 같은 체인으로 리프레이밍한다. 렌더 0."""
    rows = []
    for shot in manifest["shots"]:
        src = Path(shot["delivered"])
        out = HERE / "arm_a" / f"{shot['shot_id']}.png"
        _reframe(src, out)
        rows.append({"shot_id": shot["shot_id"], "source": str(src),
                     "path": str(out.relative_to(ROOT)), "raw_size": _dimensions(src),
                     "size": _dimensions(out)})
        print(f"  ✓ a {shot['shot_id']}  {rows[-1]['raw_size']} -> {rows[-1]['size']}", flush=True)
    return {"arm": "a", "near_phrase": NEAR_BEFORE, "seed": 0,
            "workflow": Settings().shot_recompose_workflow_path,
            "source": "workspace/<run>/recomposed (읽기 전용)",
            "rendered": len(rows), "failed": [], "frames": rows}


def _instruction_diff(manifest: dict, arms: dict) -> list[dict]:
    """B와 C의 지시문을 패스 단위로 대조한다.

    처치 패스(`depth == "near"`)는 **정확히 한 곳**에서만 달라야 하고, 그 밖의 패스는
    **바이트 동일**해야 한다. 후자가 이 실험의 무효 대조군이다.
    """
    if not ({"b", "c"} <= set(arms)):
        return []
    depths = {s["shot_id"]: [c["depth"] for c in s["cast"]] for s in manifest["shots"]}
    frames = {arm: {f["shot_id"]: f for f in arms[arm]["frames"]} for arm in ("b", "c")}
    out = []
    for shot_id in sorted(set(frames["b"]) & set(frames["c"])):
        for i, (pb, pc) in enumerate(zip(frames["b"][shot_id]["passes"],
                                         frames["c"][shot_id]["passes"])):
            # 렌더 순서는 `order_cast`(far 먼저)라 매니페스트 순서와 다르다. depth 는
            # 지시문에서 되읽는다 — 순서를 손으로 맞추면 그 자체가 틀릴 수 있는 가정이다.
            treated = NEAR_BEFORE in pb["instruction"] or NEAR_AFTER in pb["instruction"]
            row = {"shot_id": shot_id, "pass": i, "treated": treated,
                   "identical": pb["instruction"] == pc["instruction"],
                   "b_sha256": pb["instruction_sha256"], "c_sha256": pc["instruction_sha256"]}
            if not row["identical"]:
                row["b"] = pb["instruction"]
                row["c"] = pc["instruction"]
                row["single_substitution"] = (
                    pb["instruction"].replace(NEAR_BEFORE, NEAR_AFTER) == pc["instruction"])
            out.append(row)
        out[-1]["shot_depths"] = depths[shot_id]
    return out


async def cmd_render(args) -> int:
    from yt_flow.services import recompose_service

    settings = Settings()
    manifest = _manifest()
    arms = {a: None for a in args.arm}
    before = _snapshot()
    _write(HERE / "recomposed_snapshot_before.json", before)

    if {"b", "c"} & set(arms):
        failure = await recompose_service._preflight(settings)
        if failure:
            reason, message = failure
            print("\n--- ComfyUI 프리플라이트 실패 (원문) ---")
            print(message)
            print("--- 끝 ---")
            print(f"HALT: {reason} (Block If)")
            return 3
        print("preflight: 통과", flush=True)

    t0 = time.monotonic()
    for arm in args.arm:
        print(f"arm {arm}:", flush=True)
        arms[arm] = _publish_a(manifest) if arm == "a" else await _render_arm(arm, manifest, settings)

    after = _snapshot()
    _write(HERE / "recomposed_snapshot_after.json", after)
    intact = before["sha256"] == after["sha256"]
    print(f"arm A 무손상: {intact}  (파일 {before['files']} -> {after['files']}, "
          f"sha {before['sha256'][:16]} -> {after['sha256'][:16]})")

    existing = {}
    if (HERE / "arms.json").is_file():
        existing = json.loads((HERE / "arms.json").read_text(encoding="utf-8")).get("arms", {})
    existing.update({k: v for k, v in arms.items() if v})
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": RUN,
        "total_seconds": round(time.monotonic() - t0, 1),
        "reframing_chain": "video._zoompan_filter(video._FUSION_STILL_SPEC, 1.0)",
        "recomposed_intact": intact,
        "recomposed_before": {k: before[k] for k in ("dir", "files", "sha256")},
        "recomposed_after": {k: after[k] for k in ("dir", "files", "sha256")},
        "comfyui_argv": await _argv(settings) if {"b", "c"} & set(arms) else None,
        "arms": existing,
    }
    payload["instruction_diff"] = _instruction_diff(manifest, existing)
    _write(HERE / "arms.json", payload)
    if not intact:
        print("FAIL: recomposed/ 가 변했다 — arm A 손상")
        return 4
    return 0


async def _argv(settings):
    from yt_flow.services import comfyui_client

    stats = await comfyui_client.get_system_stats(settings.comfyui_url)
    return ((stats or {}).get("system") or {}).get("argv")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest-gate")
    render = sub.add_parser("render")
    render.add_argument("--arm", action="append", choices=["a", "b", "c"], required=True,
                        help="a 는 디스크 퍼블리시(GPU 0), b/c 는 렌더")
    snap = sub.add_parser("snapshot")
    snap.add_argument("--label", default="manual")
    args = parser.parse_args()
    handler = {"digest-gate": cmd_digest_gate, "render": cmd_render}.get(args.cmd)
    if handler is None:
        return cmd_snapshot(args)
    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
