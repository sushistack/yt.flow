"""Smoke test: verify Langfuse homelab connectivity using YTFLOW_ settings.

Note: `python -c "from langfuse import Langfuse; Langfuse().auth_check()"` (from the epic AC)
reads LANGFUSE_* env vars, not YTFLOW_*. This script maps our prefixed settings into
the SDK constructor instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langfuse import Langfuse
from yt_flow.config import Settings

s = Settings()
lf = Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key, host=s.langfuse_host)
ok = lf.auth_check()
print(f"host={s.langfuse_host} auth_check={ok}")
