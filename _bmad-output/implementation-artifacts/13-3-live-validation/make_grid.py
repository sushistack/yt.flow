"""Build the committed judgement image + the numbers it cites (Story 13.3 AC9).

Re-derives everything from raw_*.png, which run_probe.py produced against live
ComfyUI. Downscaled to 512px on the long edge — the criterion is "are these two
different rooms, and did the renumbered graph render the same room as the
original", which survives it comfortably.
"""
import json
import struct
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).parent
NAMES = ["corridor", "autopsy", "renumbered"]
CAPTIONS = {
    "corridor": "A: 'corridor' prompt, shipped graph",
    "autopsy": "B: 'autopsy suite' prompt, shipped graph",
    "renumbered": "C: 'corridor' prompt, ALL node ids +700",
}


def rms(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    hist = diff.histogram()
    total = sum(h * (i % 256) ** 2 for i, h in enumerate(hist))
    return (total / (a.size[0] * a.size[1] * 3)) ** 0.5


def submitted_encoders(path: Path) -> dict[str, str]:
    """node id -> declared title, for the CLIPTextEncodes in the graph ComfyUI RAN.

    ComfyUI stores the executed prompt in the output PNG's ``prompt`` tEXt chunk,
    so this is the only artifact proving the renumbered submission really carried
    nodes 706/707 — the raws are gitignored, hence extracting it into metrics.json.
    Stdlib chunk walk; PIL's ``.text`` would do too but drags the whole image in.
    """
    data = path.read_bytes()
    offset, chunks = 8, {}
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        if data[offset + 4:offset + 8] == b"tEXt":
            key, _, value = data[offset + 8:offset + 8 + length].partition(b"\x00")
            chunks[key.decode()] = value
        offset += 12 + length
    graph = json.loads(chunks["prompt"].decode("utf-8"))
    return {
        nid: node["_meta"]["title"] for nid, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"
    }


imgs = {n: Image.open(HERE / f"raw_{n}.png") for n in NAMES}
metrics = {
    "A_vs_B_rms": round(rms(imgs["corridor"], imgs["autopsy"]), 2),
    "A_vs_C_rms": round(rms(imgs["corridor"], imgs["renumbered"]), 2),
    "sizes": {n: imgs[n].size for n in NAMES},
    "file_bytes": {n: (HERE / f"raw_{n}.png").stat().st_size for n in NAMES},
    # A vs C is PIXEL-identical (RMS 0.00), not byte-identical: the files differ by
    # exactly the length of the embedded prompt graph, which is the proof below.
    "submitted_text_encoders": {
        n: submitted_encoders(HERE / f"raw_{n}.png") for n in ("corridor", "renumbered")
    },
}
(HERE / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
print(json.dumps(metrics, indent=2))

W = 512
thumbs = [imgs[n].resize((W, int(imgs[n].size[1] * W / imgs[n].size[0]))) for n in NAMES]
h = max(t.size[1] for t in thumbs)
grid = Image.new("RGB", (W * 3, h + 22), (18, 18, 20))
draw = ImageDraw.Draw(grid)
for i, (n, t) in enumerate(zip(NAMES, thumbs, strict=True)):
    grid.paste(t, (i * W, 22))
    draw.text((i * W + 6, 6), CAPTIONS[n], fill=(235, 235, 235))
grid.save(HERE / "title_resolution_grid.jpg", quality=88)
print("wrote title_resolution_grid.jpg", grid.size)
