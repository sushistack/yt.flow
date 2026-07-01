"""Seed the A/B evaluation prompts into Langfuse Prompt Hub (Story 4.2).

The judge/pairwise prompts are new to yt.flow (not present in the yt.pipe
templates that ``migrate_prompts.py`` sources), so they live in ``prompts/``
in this repo and are pushed by this script. Idempotent: only creates a new
version when the text changed.

Usage:
    uv run python scripts/seed_eval_prompts.py            # push production-labeled
    uv run python scripts/seed_eval_prompts.py --dry-run  # print, no writes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yt_flow.services.prompt_service import build_client  # noqa: E402

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
PROMPTS = {
    "evaluation/judge": "evaluation/judge.md",
    "evaluation/pairwise": "evaluation/pairwise.md",
}


def _load(rel: str) -> str:
    return (PROMPTS_DIR / rel).read_text(encoding="utf-8").strip()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Seed A/B evaluation prompts into Langfuse.")
    ap.add_argument("--label", default="production")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    manifest = {name: _load(rel) for name, rel in PROMPTS.items()}

    if args.dry_run:
        for name, text in manifest.items():
            print(f"--- {name} ---\n{text}\n")
        return

    client = build_client()
    for name, text in manifest.items():
        try:
            existing = client.get_prompt(name, label=args.label)
            if getattr(existing, "prompt", None) == text:
                print(f"skipped: {name}")
                continue
        except Exception:  # noqa: BLE001 — not present yet → create
            pass
        client.create_prompt(name=name, type="text", prompt=text, labels=[args.label])
        print(f"created: {name}")


if __name__ == "__main__":
    main()
