"""Runtime access to Langfuse Prompt Hub (Story 1.3).

Pipeline nodes fetch prompts by name through this helper instead of embedding
prompt text. A fresh Langfuse fetch happens on each call, so a production edit
in the Langfuse UI is picked up by the next run without a code change (FR-16).

ponytail: fresh client per call. If prompt fetches ever dominate latency,
cache the client or pass cache_ttl_seconds — not needed until measured.
"""

from langfuse import Langfuse

from yt_flow.config import Settings


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


def compile_prompt(name: str, **variables: object) -> str:
    """Fetch and render a prompt to a string."""
    return get_prompt(name).compile(**variables)
