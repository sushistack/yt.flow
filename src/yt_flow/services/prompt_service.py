"""Runtime access to Langfuse Prompt Hub (Story 1.3).

Pipeline nodes fetch prompts by name through this helper instead of embedding
prompt text. A fresh Langfuse fetch happens on each call, so a production edit
in the Langfuse UI is picked up by the next run without a code change (FR-16).

ponytail: fresh client per call. If prompt fetches ever dominate latency,
cache the client or pass cache_ttl_seconds — not needed until measured.
"""

import logging

from langfuse import Langfuse
from langfuse.api import NotFoundError

from yt_flow.config import Settings

logger = logging.getLogger(__name__)


def build_client() -> Langfuse:
    """Map YTFLOW_ settings onto the Langfuse SDK constructor.

    The SDK reads LANGFUSE_* env vars by default; this project prefixes its
    settings with YTFLOW_, so we pass them explicitly.
    """
    s = Settings()
    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
    )


def get_prompt(name: str, *, label: str | None = None):
    """Fetch a prompt object from Langfuse. Defaults to the `production` label.

    Prompt fetch is required LLM-stage input, so failure raises a clear error
    naming the prompt and label (architecture AD-10).
    """
    client = build_client()
    try:
        return client.get_prompt(name, label=label) if label else client.get_prompt(name)
    except Exception as exc:  # noqa: BLE001 - re-raised with context below
        raise RuntimeError(
            f"Langfuse prompt fetch failed: name={name!r} label={label or 'production'}"
        ) from exc


def get_prompt_with_fallback(name: str, *, label: str, fallback_label: str = "production"):
    """Fetch by `label`, falling back to `fallback_label` if that label doesn't exist.

    Lets an A/B run seed only some prompts as `candidate` — the rest fall
    back to production instead of failing the whole run (Story 6.1 AC5).
    """
    client = build_client()
    try:
        return client.get_prompt(name, label=label)
    except NotFoundError:
        # No warning here would make a fallback silent: if NO prompt is seeded
        # under `label`, every stage falls back and variant B renders identical
        # to production — a meaningless A/B that looks real. Logging each
        # fallback surfaces both the partial (some stages) and total (all
        # stages) case, and leaves a breadcrumb if the fallback fetch also fails.
        logger.warning(
            "prompt %r has no %r label — falling back to %r; this stage is NOT part of the A/B experiment",
            name, label, fallback_label,
        )
        return get_prompt(name, label=fallback_label)
    except Exception as exc:  # noqa: BLE001 - re-raised with context below
        raise RuntimeError(f"Langfuse prompt fetch failed: name={name!r} label={label!r}") from exc


def compile_prompt(name: str, **variables: object) -> str:
    """Fetch and render a prompt to a string."""
    return get_prompt(name).compile(**variables)
