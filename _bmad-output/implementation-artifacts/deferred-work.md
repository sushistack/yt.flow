## Deferred from: code review of story-1.1/1.2 (2026-07-01)

- Layer-boundary guard test only covers `domain/state.py`. AC4's full AD-1 chain (`pipeline` must not import `db`, `api` must not import `pipeline`) is not actively tested because those layers are currently empty package markers. Extend `tests/domain/test_state_imports.py` (or add a dedicated import-boundary test) once pipeline/api modules contain real code. **(Resolved in stories 1.5–1.7: `test_pipeline_imports_no_db` and `test_api_imports_no_pipeline` added to `tests/domain/test_state_imports.py`.)**
- `pytest-asyncio` is declared as a dev dependency but no `asyncio_mode` is configured in `[tool.pytest.ini_options]`. Under the plugin's STRICT default, async test functions added without `@pytest.mark.asyncio` are collected but not awaited (silent false-pass). Set `asyncio_mode = "auto"` (or mark tests explicitly) when the first async test lands in story 1.4. **(Resolved in story 1.4: `asyncio_mode = "auto"` added to pyproject.toml.)**

## Deferred from: code review of story-1.3 (2026-07-01)

- **`_unchanged` conflates fetch errors with "prompt absent"** [scripts/migrate_prompts.py] — any Langfuse fetch exception is treated as "not present yet", so a transient outage during a live run creates a spurious prompt version instead of skipping. Acceptable for a manual, rerun-safe migration script (idempotent on rerun); marked with a `ponytail:` comment. Narrow to the SDK's not-found exception type if this ever runs unattended.
- **Live migration ACs (AC1/AC2/AC5) not system-verified** — unit tests use fakes only; the end-to-end run against real source templates + self-hosted Langfuse was never executed here because `/mnt/work/projects/yt.pipe/templates/` is absent on this machine. Run manually before trusting those ACs:
  - `uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates`
  - `uv run python -c "from yt_flow.services.prompt_service import compile_prompt; print(compile_prompt('scenario', scp_text='hello')[:80])"`

## Deferred from: code review of story-1.4 (2026-07-01)

- **AD-3 `pending` gate state is unobservable** [src/yt_flow/pipeline/gates.py] — AD-3 requires each gate node to write `{"gate_states": {stage: "pending"}}` on interrupt entry, but LangGraph discards a node's return value when `interrupt()` pauses (the node re-runs from the top on resume). Empirically verified: at pause `gate_states == {}`, so `pending` never appears. Making it observable requires a pre-gate writer (e.g. the stage node emits `pending` for its own gate), which conflicts with AD-3's "gate node is the sole writer of `gate_states`" rule. This is an architecture reconciliation, not a mechanical fix — resolve it in the story that first consumes `gate_states` (services/ DB projection). No consumer exists in the current stub, so there is no functional impact today.
- **`gate_states` has no LangGraph reducer** [src/yt_flow/pipeline/gates.py] — it is a plain dict field. The current topology is strictly sequential so gates never run concurrently, but if future parallel-stage topology or `Send` is introduced, last-write-wins will silently drop a gate decision. Add an `Annotated[dict, merge]` reducer when parallel gates are introduced.

## Deferred from: code review of 1-8-subtitle-node (2026-07-01)

- **Partial alignment silent empty return** [subtitle.py:64] — `word_segments` non-empty but all tokens unaligned silently returns `[]`, bypassing the segment fallback path. Reproduce only with a live WhisperX model; narrow the guard when testable.
- **WhisperX model reloaded on every scene** [subtitle.py:48] — `load_model` is called inside `_align_sync` each time, so model weights reload per scene. Cache on `WhisperXAligner` instance if throughput matters.
- **Error format flat string, not structured dict** [subtitle.py:208] — `PipelineState.error` is a freeform string embedding `stage=subtitle run_id=...`. API/UI layers that need structured error fields must parse it. Revisit if story 2.4 error handling requires a structured contract.
- **Overlapping input word_timings not pre-validated** [subtitle.py:108] — `_word_timings_to_segments` trusts TTS-provided `WordTiming.end_sec` is not overlapping. Add a pre-validate step if the TTS node ever emits overlapping timings.
- **Empty scenes list is a valid no-op without a downstream guard** [subtitle.py:180] — `subtitle_node` succeeds with `scenes=[]`; `video_node` likely assumes ≥1 scene. Add a guard in the video integration story.
- **run_id path traversal** [subtitle.py:176] — `Path(workspace)/run_id` is unvalidated. Internal CLI state keeps risk low; add sanitisation if `run_id` ever comes from an HTTP boundary.

## Deferred from: code review of story-1.5/1.6/1.7 (2026-07-01)

- **Real stage nodes are not wired into the graph** [src/yt_flow/pipeline/nodes/__init__.py] — `STAGE_NODES` still binds the Story 1.4 stubs for `scenario`/`image`/`tts`; the real `*_node` callables are only exercised by direct unit tests, not through the compiled graph. This is a deliberate, consistent deferral across all three stories (rewiring now would regress the Story 1.4 stub-graph tests). No story-1.5/1.6/1.7 AC requires graph reachability (all ACs are phrased "when X_node runs"). Rewire `STAGE_NODES` to the real nodes in the integration story that owns end-to-end graph execution (candidate: 1.10).
- **`sentence_indices` bounds are unenforceable when the LLM omits `sentences`** [src/yt_flow/pipeline/nodes/scenario.py `_parse_indices`] — the story explicitly permits omitting the optional `sentences` array; when absent, out-of-range indices pass validation. Deriving a bound from `narration` splitting was rejected as a fragile heuristic that could reject valid output. Revisit if the image/subtitle stages start dereferencing indices against narration sentences.
- **Synthesized ComfyUI workflow JSON is unverified against a real export** [data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json] — the real source file was absent at implementation time, so the asset was synthesized from the story's prose. `_load_workflow` proves internal self-consistency (nodes "6"/"7" are CLIPTextEncode with `inputs`) but NOT correctness against a live ComfyUI node pack. **Must be verified/replaced against a real ComfyUI API export before any non-mock (`YTFLOW_COMFYUI_MOCK=false`) run.**

## Deferred from: code review of 1-6b-image-layered-assets (2026-07-01)

- **`image_node` hardcodes `Path("workspace")` instead of `s.workspace_path`** [image.py:204] — pre-existing from Story 1.6; new layered path inherits the same root. Fix together with the Story 1.6 workspace_path cleanup whenever `YTFLOW_WORKSPACE_PATH` support is needed.
- **`_await_outputs` returns on first node found, not all requested nodes** [comfyui_client.py:138] — assumes ComfyUI writes all outputs atomically. Spec allows background-only (AC2), so this is compliant. Add per-node wait if a future story requires guaranteeing both layers succeed.
- **`_has_alpha` does not detect tRNS-chunk palette transparency** [image.py:113] — color_type 3 (indexed PNG) with a tRNS chunk would be rejected as opaque. ComfyUI SaveImage outputs RGBA (color_type 6), so this edge case is non-applicable in practice.
