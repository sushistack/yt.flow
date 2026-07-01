## Deferred from: code review of story-1.1/1.2 (2026-07-01)

- Layer-boundary guard test only covers `domain/state.py`. AC4's full AD-1 chain (`pipeline` must not import `db`, `api` must not import `pipeline`) is not actively tested because those layers are currently empty package markers. Extend `tests/domain/test_state_imports.py` (or add a dedicated import-boundary test) once pipeline/api modules contain real code.
- `pytest-asyncio` is declared as a dev dependency but no `asyncio_mode` is configured in `[tool.pytest.ini_options]`. Under the plugin's STRICT default, async test functions added without `@pytest.mark.asyncio` are collected but not awaited (silent false-pass). Set `asyncio_mode = "auto"` (or mark tests explicitly) when the first async test lands in story 1.4. **(Resolved in story 1.4: `asyncio_mode = "auto"` added to pyproject.toml.)**

## Deferred from: code review of story-1.3 (2026-07-01)

- **`_unchanged` conflates fetch errors with "prompt absent"** [scripts/migrate_prompts.py] — any Langfuse fetch exception is treated as "not present yet", so a transient outage during a live run creates a spurious prompt version instead of skipping. Acceptable for a manual, rerun-safe migration script (idempotent on rerun); marked with a `ponytail:` comment. Narrow to the SDK's not-found exception type if this ever runs unattended.
- **Live migration ACs (AC1/AC2/AC5) not system-verified** — unit tests use fakes only; the end-to-end run against real source templates + self-hosted Langfuse was never executed here because `/mnt/work/projects/yt.pipe/templates/` is absent on this machine. Run manually before trusting those ACs:
  - `uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates`
  - `uv run python -c "from yt_flow.services.prompt_service import compile_prompt; print(compile_prompt('scenario', scp_text='hello')[:80])"`

## Deferred from: code review of story-1.4 (2026-07-01)

- **AD-3 `pending` gate state is unobservable** [src/yt_flow/pipeline/gates.py] — AD-3 requires each gate node to write `{"gate_states": {stage: "pending"}}` on interrupt entry, but LangGraph discards a node's return value when `interrupt()` pauses (the node re-runs from the top on resume). Empirically verified: at pause `gate_states == {}`, so `pending` never appears. Making it observable requires a pre-gate writer (e.g. the stage node emits `pending` for its own gate), which conflicts with AD-3's "gate node is the sole writer of `gate_states`" rule. This is an architecture reconciliation, not a mechanical fix — resolve it in the story that first consumes `gate_states` (services/ DB projection). No consumer exists in the current stub, so there is no functional impact today.
- **`gate_states` has no LangGraph reducer** [src/yt_flow/pipeline/gates.py] — it is a plain dict field. The current topology is strictly sequential so gates never run concurrently, but if future parallel-stage topology or `Send` is introduced, last-write-wins will silently drop a gate decision. Add an `Annotated[dict, merge]` reducer when parallel gates are introduced.
