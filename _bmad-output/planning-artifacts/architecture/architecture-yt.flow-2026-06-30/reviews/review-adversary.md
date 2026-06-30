---
type: adversarial-architecture-review
spine: ARCHITECTURE-SPINE.md
reviewer: adversary
date: 2026-06-30
---

# Adversarial Architecture Review — yt.flow

## Verdict

The spine is coherent but contains five exploitable gaps where two builders who each follow every written AD to the letter can still produce incompatible units; the worst two are silent data-loss vectors at runtime, not compile-time failures.

---

## Findings

### CRITICAL-1 — `gate_states` ownership split: gates.py vs. run_service.py

**Builders:** Builder A implements `gates.py`; Builder B implements `run_service.py`.

**What the spine says:**
- AD-3: "`gate_states` in `PipelineState` is a query-only mirror updated by `services/` after each interrupt."
- LangGraph graph structure: gate nodes in `gates.py` call `interrupt()`.
- AD-2: PipelineState is the single source of truth.

**The hole:**
AD-3 says `services/` updates `gate_states`. But `gates.py` is a LangGraph *node* — it returns a dict that becomes the next `PipelineState`. Builder A, reading the graph structure, sees `gate_scenario` as a node that calls `interrupt()`. A node that returns nothing yields `{}` or the prior state. Builder A may reasonably infer that `gate_states` should be updated *within* `gates.py`'s node return (e.g., `{"gate_states": {"scenario": "pending"}}`) so that the checkpoint reflects the gate status immediately. Builder B, reading AD-4, writes `run_service.py` to set `gate_states` after consuming the `interrupt` event from `astream()`.

**Result:** Both build legally per the spine. At runtime, if Builder A sets `gate_states["scenario"] = "pending"` in the node return, and Builder B also sets it in `run_service.py`, there are two writers to the same dict key. Worse: if Builder A does NOT set it (relying on `services/` to do so), then the LangGraph checkpoint never captures `gate_states`, making `GET /runs/{id}/stages/{stage}/artifacts` (which reads LangGraph state per AD-7) return stale or missing gate data.

**AD violated (in combination):** AD-2 + AD-3. Neither AD alone is violated, but together they leave an ownership gap.

---

### CRITICAL-2 — `scenes` / `shots` schema divergence between `scenario_node` and `image_node`

**Builders:** Builder A implements `pipeline/nodes/scenario.py`; Builder B implements `pipeline/nodes/image.py`.

**What the spine says:**
- AD-5: `ShotData.sentence_indices: list[int]` is the mapping. `scenario_node` prompts DeepSeek V4 as Director.
- `PipelineState.scenes: list[SceneState]` is built by `scenario_node`.
- `image_node` receives `PipelineState` and reads `scenes[i].shots[j].image_path`.

**The hole:**
The spine specifies `ShotData` fields but does not specify what `scenario_node` is required to populate vs. leave `None`. Builder A (scenario) may choose to populate only `shot_id`, `sentence_indices`, `image_prompt`, and `negative_prompt`, leaving `camera_angle` and `camera_movement` as `None` because the LLM did not produce them. Builder B (image) may write ComfyUI workflow selection logic that *branches on* `camera_angle` or `camera_movement` being a specific string (e.g., `"wide"` → different ControlNet preset), treating `None` as a fallback. This is fine in isolation.

However: AD-5 says shot boundaries are determined by "narrative/camera shift" — Builder A may produce shots *without any camera metadata* because the Director LLM was only prompted for `image_prompt`. Builder B cannot distinguish "camera shift shot" from "narrative shift shot" without that metadata — so it silently generates all shots at the same camera preset. The spine never mandates that `scenario_node` populate `camera_angle`/`camera_movement`, yet the field is defined in `ShotData` suggesting it should. Two builders ship incompatible completeness assumptions, and TypedDict will not raise an error at either end because both fields are `str | None`.

**No AD is textually violated.** The schema is defined but the obligation to populate it is unspecified.

---

### HIGH-1 — `runs` table write timing: `POST /gate` 202 vs. DB sync order

**Builders:** Builder A implements `services/run_service.py`; Builder B implements `api/routes/runs.py`.

**What the spine says:**
- AD-4: "`POST /gate` returns 202 Accepted once LangGraph resume is kicked off; the client confirms stage progression via SSE `stage_entry`."
- AD-4: "DB updates happen **after** LangGraph emits the first confirmation event — never before."

**The hole:**
Builder B (routes/runs.py) handles `POST /gate`. AD-4 says the route returns 202 once "LangGraph resume is kicked off" — Builder B reads this as: call `graph.astream(Command(resume=...))` and immediately return 202. Builder A (run_service.py) drives `astream()` in a background task and updates `runs.status` only after the first `stage_entry` event arrives.

The problem: Builder B may call `graph.astream()` *directly* in the route handler (it sees `services/run_service.py` as the driver for the initial run, but for gate resume, nothing says `run_service.py` must handle it). If Builder B calls `astream()` directly in the route handler, it bypasses `run_service.py`'s DB sync and SSE fan-out entirely. Both builders follow AD-1 (routes call services), but the spine never states that `POST /gate` resume *must go through* `run_service.py` rather than a separate `gate_service` or inline call. Builder B can implement a thin inline `graph.astream()` call that satisfies AD-3 and AD-4's 202 timing while completely skipping `run_service.py`, leaving `runs.status` and the SSE queue stale.

---

### HIGH-2 — `gate_states` JSON blob format: `Run.gate_states` vs. `PipelineState.gate_states`

**Builders:** Builder A implements `db/models.py` (`Run` model); Builder B implements `run_service.py` DB sync.

**What the spine says:**
- `PipelineState.gate_states: dict[str, str]` — stage → `pending|approved|rejected|n/a`.
- `Run.gate_states: str | None` — JSON blob.

**The hole:**
The spine defines both fields but never specifies the serialization contract. Builder A looks at `PipelineState.gate_states` and uses `json.dumps({"scenario": "approved", "image": "pending"})` — flat dict, string values. Builder B looks at the same and uses `json.dumps([{"stage": "scenario", "state": "approved"}, ...])` — list of objects, perhaps to preserve ordering or carry timestamps later. Both produce valid JSON. `Run.gate_states` is `str | None`, so SQLModel accepts both without complaint. `api/routes/runs.py` (Builder C, hypothetically) deserializes with `json.loads()` and then must know the shape. The spine never states a canonical shape beyond the Python TypedDict — TypedDicts cannot be serialized to JSON without a specified convention.

**Effect:** `GET /runs/{id}` returns `gate_states` as an opaque blob; the frontend React SPA must parse it. Two independent builders can silently produce incompatible JSON structures that type-check cleanly on both ends.

---

### MEDIUM-1 — `current_stage` update responsibility: node return vs. `run_service.py`

**Builders:** Builder A implements any stage node (e.g., `pipeline/nodes/scenario.py`); Builder B implements `run_service.py`.

**What the spine says:**
- `PipelineState.current_stage: str` — `scenario|image|tts|subtitle|video`.
- AD-4: `services/` consumes `astream()` events and updates `runs` table projection (which includes `current_stage`).
- Consistency convention: "State mutation — `PipelineState` fields replaced wholesale per node return."

**The hole:**
Builder A may return `{"current_stage": "image"}` from `scenario_node` (updating `PipelineState.current_stage` in the checkpoint) because it is a `PipelineState` field and the convention says nodes replace fields via return. Builder B may read `current_stage` from the `astream()` event metadata (the node name that just ran) and update `runs.current_stage` accordingly — never looking at `PipelineState.current_stage`. This is fine as long as both agree.

But: if a `retry` gate resumes `image_node`, Builder B updates `runs.current_stage = "image"` from the event, but Builder A may not return `{"current_stage": "image"}` from the retry run (the field is already `"image"` in the checkpoint). No conflict. However, if `scenario_node` *also* increments `current_stage` to `"image"` at the end of its own return (anticipating the next stage), Builder B sees a `scenario` event but finds `PipelineState.current_stage == "image"`. `runs.current_stage` is now behind by one stage until the image event fires.

The spine assigns `current_stage` to `PipelineState` as a typed field but never specifies *which node* (or `run_service.py`) is responsible for advancing it, creating a dual-write risk.

---

### LOW-1 — `ab_pair_id` write owner: `POST /runs/{id}/ab` route vs. `run_service.py`

**Builders:** Builder A implements `api/routes/runs.py` `POST /ab`; Builder B implements `run_service.py`.

**What the spine says:**
- AD-6: "`POST /runs/{id}/ab` creates a second independent run with the same `scp_text`, `prompt_variant="B"`, and `ab_pair_id` pointing to the originating run."
- AD-1: `api/` never directly writes to DB — `services/` owns DB.

**The hole:**
AD-6 assigns the B-run creation responsibility to the `/ab` route, but AD-1 says DB writes belong to `services/`. Builder A writes a thin route that delegates to `run_service.create_ab_run()`. Builder B writes `run_service.py` with a `create_run()` method that accepts `ab_pair_id` as an optional parameter. There is no conflict — unless Builder A assumes `ab_pair_id` should be set on *the originating A run* as well (so the A run knows its B pair), while Builder B never updates the A run's `ab_pair_id` field. The `Run` model has `ab_pair_id` on both rows, but AD-6 says only the B run's `ab_pair_id` points to A. The A run's `ab_pair_id` is never specified to remain `None` or be backfilled. Builder A may write a 2-phase DB update (set A.ab_pair_id = B.id, B.ab_pair_id = A.id), Builder B may write a 1-phase update. `eval_service.py` joins on `ab_pair_id` and may find only one direction populated.

---

## Summary Table

| ID | Severity | One-line summary |
|----|----------|-----------------|
| CRITICAL-1 | Critical | `gate_states` has two legal write paths — `gates.py` node return and `run_service.py` — creating a dual-write / no-write ambiguity that the spine never resolves |
| CRITICAL-2 | Critical | `scenario_node` has no mandatory obligation to populate `camera_angle`/`camera_movement` in `ShotData`, allowing silent camera-metadata loss that `image_node` cannot detect |
| HIGH-1 | High | `POST /gate` resume can legally bypass `run_service.py`, leaving DB and SSE queue stale while satisfying AD-3 and AD-4's 202 contract |
| HIGH-2 | High | `Run.gate_states` JSON blob has no canonical shape specified, letting serialization diverge silently between `db/models.py` and `run_service.py` |
| MEDIUM-1 | Medium | `PipelineState.current_stage` has no specified writer — a stage node may advance it preemptively while `run_service.py` derives it from event metadata, causing transient one-stage skew |
| LOW-1 | Low | `ab_pair_id` is only specified as pointing B→A; whether A is backfilled to point A→B is unspecified, and `eval_service.py` will need to pick one join direction |

---

## Recommended Fixes (minimal, no new ADs required)

1. **CRITICAL-1**: Add one sentence to AD-3: "Gate nodes return `{}` — they do not update `gate_states` in their return dict. `services/run_service.py` is the sole writer to `gate_states` in the LangGraph checkpoint via `graph.update_state()`."

2. **CRITICAL-2**: Add one sentence to AD-5: "`scenario_node` MUST populate `camera_angle` and `camera_movement` for every `ShotData`; if the LLM does not produce them, default to `'medium'` and `'static'` respectively."

3. **HIGH-1**: Add to AD-4: "Gate resume (`POST /gate`) MUST call `run_service.resume_run()` — never `graph.astream()` directly from the route handler — so DB sync and SSE fan-out remain in one place."

4. **HIGH-2**: Add to the Consistency Conventions table: "`gate_states` JSON shape — `{"scenario": "approved", ...}` flat string-to-string dict; never array."

5. **MEDIUM-1**: Add to State mutation convention: "`current_stage` is advanced by `run_service.py` from the `astream()` node name event, not by stage nodes in their return dict."
