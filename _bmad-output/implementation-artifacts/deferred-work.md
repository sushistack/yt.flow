## Deferred from: code review of story-1.1/1.2 (2026-07-01)

- Layer-boundary guard test only covers `domain/state.py`. AC4's full AD-1 chain (`pipeline` must not import `db`, `api` must not import `pipeline`) is not actively tested because those layers are currently empty package markers. Extend `tests/domain/test_state_imports.py` (or add a dedicated import-boundary test) once pipeline/api modules contain real code.
- `pytest-asyncio` is declared as a dev dependency but no `asyncio_mode` is configured in `[tool.pytest.ini_options]`. Under the plugin's STRICT default, async test functions added without `@pytest.mark.asyncio` are collected but not awaited (silent false-pass). Set `asyncio_mode = "auto"` (or mark tests explicitly) when the first async test lands in story 1.4.
