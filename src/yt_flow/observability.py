"""Langfuse tracing seam (B-3).

Re-exports the real ``observe``/``get_client`` when ``settings.langfuse_enabled``
is true, or the drop-in no-op versions below when false. Import sites use
``from yt_flow.observability import get_client, observe`` instead of importing
straight from ``langfuse``.

The flag ONLY governs runtime *tracing*. Prompt Hub fetching lives in
``prompt_service`` (its own ``Langfuse`` client) and is intentionally untouched
here, so prompts still load with tracing off.

ponytail: we wrap rather than use langfuse's native ``tracing_enabled=False``
because that flag is bound at first client construction keyed by public_key —
and in this project the only real-key registrar is ``prompt_service.build_client``,
so ``@observe``/``get_client`` reliably resolving to a disabled instance depends on
fragile init ordering. A tiny local wrapper is ordering-independent and testable.
"""

import os


def _noop_observe(*dargs, **dkwargs):
    """No-op stand-in for ``langfuse.observe`` (supports ``@observe`` and ``@observe(name=...)``)."""
    if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
        return dargs[0]  # bare @observe

    def decorate(fn):
        return fn

    return decorate


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _NoopClient:
    """Silently accepts every tracing call (update_current_span, create_score…)."""

    def start_as_current_observation(self, *_, **__):
        return _NoopSpan()

    def create_trace_id(self, *, seed=None):
        return seed or ""

    def __getattr__(self, _name):
        return lambda *a, **k: None


_noop_client = _NoopClient()


def _noop_get_client(*_, **__):
    return _noop_client


# ponytail: read only the one flag via env — constructing Settings() here would
# require all langfuse_* env vars just to *import* any of the 7 dependent modules
# (a new import-time crash the direct `from langfuse import ...` never had).
# Mirrors pydantic-settings' bool parsing of YTFLOW_LANGFUSE_ENABLED.
if os.getenv("YTFLOW_LANGFUSE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}:
    from langfuse import get_client, observe  # noqa: F401  (real re-export)
else:
    observe = _noop_observe
    get_client = _noop_get_client
