"""Seed the character-generation prompts into Langfuse Prompt Hub (Story 5.12).

``prompts/character/*.md`` are repo-native (not sourced from yt.pipe) and are
consumed two ways: via Langfuse `.compile(**vars)` (double-brace variables) and
via a local-file `.format()`/`.replace()` fallback in ``character_service.py``
(single-brace, so the repo files stay single-brace for that branch to keep
working). This script converts `{var}` -> `{{var}}` at seed time — reusing
``migrate_prompts.convert_placeholders`` — so the Langfuse-hosted copy actually
substitutes its variables. Idempotent: only creates a new version when the
converted text changed.

Usage:
    uv run python scripts/seed_character_prompts.py            # push production-labeled
    uv run python scripts/seed_character_prompts.py --dry-run  # print, no writes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langfuse.api import NotFoundError  # noqa: E402
from migrate_prompts import convert_placeholders  # noqa: E402
from yt_flow.services.prompt_service import build_client  # noqa: E402

PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "character"
PROMPTS = {
    "character-generation": "generation.md",
    "character-angle-selection": "angle_selection.md",
    "character-vision-enrichment": "vision_enrichment.md",
}


def _load(rel: str) -> str:
    return convert_placeholders((PROMPTS_DIR / rel).read_text(encoding="utf-8").strip())


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Seed character prompts into Langfuse.")
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
        except NotFoundError:
            pass  # not present yet → create
        client.create_prompt(name=name, type="text", prompt=text, labels=[args.label])
        print(f"created: {name}")


if __name__ == "__main__":
    main()
