# Story 13.3 — live gate: title resolution lands, provenance is populated

**Ran 2026-08-14** on the local GPU host (`/home/jay/workspaces/ComfyUI`,
`http://127.0.0.1:8188`, ComfyUI `0.12.3`, torch `2.11.0.dev20260206+rocm7.1`,
`cuda:0 AMD Radeon Graphics : native`, queue empty before submission).

## What was submitted

`run_probe.py` drives the **shipped** code path end to end — `image._load_workflow`
(title resolution, no id fallback) → `image._inject_prompts` →
`comfyui_client.submit_and_fetch` — plus `image._build_provenance` against the live
`/system_stats`. Three renders, seed `13300001` throughout:

| Panel | Prompt | Graph |
|---|---|---|
| A | facility corridor | shipped `comfyui_sdxl_anime_lora_workflow_api2.json` |
| B | stainless steel autopsy suite | shipped, same file |
| C | facility corridor | **every node id shifted +700**, links rewritten |

C is the point. Renumbering is exactly what the ComfyUI UI does on copy/paste and
re-export, and it is what the old hardcoded `"6"`/`"7"` could not survive.

## Verdict

![title resolution grid](title_resolution_grid.jpg)

- **A vs B RMS 72.78** — two visibly different rooms from two different prompts, so
  the positive prompt is reaching the sampler. A frame that ignored injection would
  render the workflow's placeholder text for both.
- **A vs C RMS 0.00** — **pixel**-identical, which is what RMS 0.00 measures. The
  files are *not* byte-identical (1,426,434 vs 1,426,468 bytes, `file_bytes` in
  `metrics.json`): the 34-byte delta is the PNG `prompt` tEXt chunk, in which
  ComfyUI records the graph it actually executed.
- That chunk is the proof, and it is now committed rather than left in a gitignored
  raw. `metrics.json`'s `submitted_text_encoders` reads it back out of each PNG:
  A submitted `{"6": "ytflow:positive_prompt", "7": "ytflow:negative_prompt"}`,
  C submitted `{"706": "ytflow:positive_prompt", "707": "ytflow:negative_prompt"}`.
  So ComfyUI really received the renumbered nodes and the resolver really found
  them there. Position-independence is measured, not argued.
- Resolved map as `image._load_workflow` reported it, live:
  `{'ytflow:positive_prompt': '6', 'ytflow:negative_prompt': '7'}`;
  renumbered: `{'ytflow:positive_prompt': '706', 'ytflow:negative_prompt': '707'}`.

## Provenance (AC7), captured live

`provenance.json` is the object `_write_sidecar` now embeds. Every field is
populated against the real server — `env_snapshot_sha256` is the sha256 of the
committed `data/comfyui/env-snapshot.json`, and `workflow_sha256` is the canonical
hash of the loaded template **before** per-shot injection.

## Re-deriving

```bash
cd <repo>
PYTHONPATH=$PWD/src uv run python _bmad-output/implementation-artifacts/13-3-live-validation/run_probe.py
uv run python _bmad-output/implementation-artifacts/13-3-live-validation/make_grid.py
```

`run_probe.py` writes the ignored `raw_*.png`; `make_grid.py` rebuilds
`title_resolution_grid.jpg` and `metrics.json` from them — including
`submitted_text_encoders`, walked out of each PNG's `prompt` tEXt chunk, so the
committed evidence carries the judgement even with the raws ignored.
