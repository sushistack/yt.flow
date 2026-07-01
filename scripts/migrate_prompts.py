"""Migrate yt.pipe prompt templates into Langfuse Prompt Hub (Story 1.3).

Discovers `.md`/`.tmpl` prompt sources, converts single-brace `{var}` placeholders
to Langfuse `{{var}}` variables, and pushes each as a `production`-labeled text
prompt. Idempotent: a prompt is only re-created when its normalized content changed.

Usage:
    uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates
    uv run python scripts/migrate_prompts.py --dry-run   # list names + variables, no writes

Live migration writes to Jay's self-hosted Langfuse; unit tests never call it.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yt_flow.services.prompt_service import build_client  # noqa: E402

DEFAULT_SOURCE = "/mnt/work/projects/yt.pipe/templates"
SOURCE_SUFFIXES = {".md", ".tmpl"}

# Stable Langfuse names for known source files (folders = slashes).
# Files not listed here get a name derived from their path (suffix stripped).
SOURCE_TO_NAME = {
    "scenario/01_research.md": "scenario/research",
    "scenario/02_structure.md": "scenario/structure",
    "scenario/03_writing.md": "scenario/writing",
    "scenario/03_5_visual_breakdown.md": "scenario/visual_breakdown",
    "scenario/04_review.md": "scenario/review",
    "scenario/critic_agent.md": "scenario/critic_agent",
    "scenario/format_guide.md": "scenario/format_guide",
    "image/01_shot_breakdown.md": "image/shot_breakdown",
    "image/02_shot_to_prompt.md": "image/shot_to_prompt",
    "tts/scenario_refine.md": "tts/scenario_refine",
    "vision/descriptor_enrichment.md": "vision/descriptor_enrichment",
}

# Required runtime entrypoint prompts -> source file (relative to --source) they wrap.
# Downstream nodes fetch these by name; they must compile without node-side concatenation.
ALIASES = {
    "scenario": "scenario/01_research.md",
    "image_prompt": "image/02_shot_to_prompt.md",
}

# A template variable is a bare identifier in single braces, not already doubled
# and not a JSON object / literal. ponytail: identifier heuristic; if a real
# prompt needs a literal `{word}`, escape it in the source before migrating.
_VARIABLE_RE = re.compile(r"(?<!\{)\{([A-Za-z_]\w*)\}(?!\})")


def convert_placeholders(text: str) -> str:
    """`{var}` -> `{{var}}`, leaving `{{already}}`, JSON, and non-identifiers alone."""
    return _VARIABLE_RE.sub(r"{{\1}}", text)


def iter_source_files(source: Path):
    for p in sorted(source.rglob("*")):
        if p.is_file() and p.suffix in SOURCE_SUFFIXES:
            yield p


def derive_name(rel: Path) -> str:
    return rel.with_suffix("").as_posix()


def _load(source: Path, rel: str) -> str:
    return convert_placeholders((source / rel).read_text(encoding="utf-8").strip())


def build_manifest(source: Path) -> dict[str, str]:
    """Return {prompt_name: converted_text} for all sources plus required aliases."""
    files = list(iter_source_files(source))
    if not files:
        raise SystemExit(f"No prompt files ({'/'.join(sorted(SOURCE_SUFFIXES))}) found under {source}")

    manifest: dict[str, str] = {}
    for p in files:
        rel = p.relative_to(source)
        name = SOURCE_TO_NAME.get(rel.as_posix(), derive_name(rel))
        manifest[name] = convert_placeholders(p.read_text(encoding="utf-8").strip())

    for alias, src_rel in ALIASES.items():
        if not (source / src_rel).is_file():
            raise SystemExit(f"Required alias {alias!r} source missing: {source / src_rel}")
        if alias in manifest:
            raise SystemExit(
                f"Reserved alias {alias!r} collides with a discovered prompt name; "
                f"rename the source file that maps to {alias!r}."
            )
        manifest[alias] = _load(source, src_rel)

    return manifest


def _unchanged(client, name: str, text: str, label: str) -> bool:
    # ponytail: any fetch error is treated as "not present yet" → create. A transient
    # Langfuse outage during a live run can therefore create a spurious version instead
    # of skipping. Acceptable for a manual, rerun-safe migration script; narrow to the
    # SDK's not-found type if this ever runs unattended.
    try:
        existing = client.get_prompt(name, label=label)
    except Exception:
        return False
    return getattr(existing, "prompt", None) == text


def migrate(client, manifest: dict[str, str], label: str) -> dict[str, str]:
    """Push each prompt, skipping unchanged ones. Returns {name: 'created'|'skipped'}."""
    results: dict[str, str] = {}
    for name, text in manifest.items():
        if _unchanged(client, name, text, label):
            results[name] = "skipped"
            continue
        client.create_prompt(name=name, type="text", prompt=text, labels=[label])
        results[name] = "created"
    return results


def _variables(text: str) -> list[str]:
    return sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Migrate prompts into Langfuse Prompt Hub.")
    ap.add_argument("--source", type=Path, default=Path(DEFAULT_SOURCE))
    ap.add_argument("--label", default="production")
    ap.add_argument("--dry-run", action="store_true", help="list discovered prompts + variables, no writes")
    args = ap.parse_args(argv)

    if not args.source.is_dir():
        raise SystemExit(f"Source directory not found: {args.source}")

    manifest = build_manifest(args.source)

    if args.dry_run:
        for name in sorted(manifest):
            print(f"{name}: vars={_variables(manifest[name])}")
        return

    results = migrate(build_client(), manifest, args.label)
    for name in sorted(results):
        print(f"{results[name]}: {name}")


if __name__ == "__main__":
    main()
