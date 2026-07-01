"""Set required env vars before any module imports for API tests."""
import os

# Dummy values so Settings() constructs without a .env file in tests
os.environ.setdefault("YTFLOW_LANGFUSE_HOST", "http://localhost:3000")
os.environ.setdefault("YTFLOW_LANGFUSE_PUBLIC_KEY", "test-pub")
os.environ.setdefault("YTFLOW_LANGFUSE_SECRET_KEY", "test-secret")
