---
story_key: 13-5-depth-node-id-decoupling
story_id: "13.5"
epic: "Epic 13: 품질 관측 & 게이트 성숙 — 조용한 실패 표면화 + 시각 평가 축"
created: 2026-08-15
source_status_before: backlog
baseline_commit: 4769608b4b1c05b7129ed716f087e22fdcb15495
---

# Story 13.5: depth 그래프 노드ID 커플링 제거 — 13.3이 남긴 2/6

Status: draft

## Story

As Jay,
I want the depth-map path to address its ComfyUI nodes by declared title like every other injection site,
so that the one graph that runs for **every generated background** stops being the last place a ComfyUI re-export can silently mis-target an injection.

## Context

Story 13.3 replaced node-ID addressing with an exact-title resolver (`comfyui_client.resolve_nodes`) across `image.py`, `composite_harmonization.py`, `seed_location_plates.py` and `character_image_provider.py`. It converted **four of six** coupling sites. This story closes the fifth, which is also the hottest.

[compositing_service.py:41-42](../../src/yt_flow/services/compositing_service.py#L41) pins:

```python
DEPTH_IMAGE_NODE = "1"
DEPTH_MODEL_NODE = "2"
```

and [:324-328](../../src/yt_flow/services/compositing_service.py#L324) blind-writes `workflow["1"]["inputs"]["image"]`, `workflow["2"]["inputs"]["ckpt_name"]`, `workflow["2"]["inputs"]["resolution"]` into `settings.depth_comfyui_workflow_path`. The committed graph really is keyed `"1"/"2"/"3"`.

`depth_placement_enabled` defaults **True** and `image_node._with_depth` drives it per background, so this is not a corner — live run `e5ed4b3a` executed it 43 times.

**Severity is asymmetric between the two nodes:**

| Node | Guard today | Behaviour on a re-number |
|---|---|---|
| `"1"` | presence + `class_type == "LoadImage"` | fails **loudly** |
| `"2"` | only "has an `inputs` dict" | any input-bearing node that lands on `"2"` receives `ckpt_name`/`resolution` — **silently wrong** |

That second row is the same shape as the `GREY_MATTE_NODE`/`LIGHT_SOURCE_NODE` pair 13.3 found in harmonization: a `.get()` plus a weak isinstance guard that degrades without raising.

### How this was missed, and the lesson worth keeping

13.3's scope table was built from `grep 'workflow\["N"\]'` — a literal-index search. This site addresses through **named constants**, so the census returned nothing and the story recorded "the remaining workflows are class_type-scanned" as *verified*. It was not. A scope claim recorded as verified, that a five-second grep can refute, is the same failure the epic exists against; the recurrence is worth one line in the retro.

## Acceptance Criteria

1. **Titles on the committed depth graph.** `data/workflows/comfyui_depth_anything_v2_api.json` gains `_meta.title` = `ytflow:depth_image` on node `"1"` and `ytflow:depth_model` on node `"2"`. Any prose displaced from those titles moves verbatim into a README, as 13.3 did — no explanatory text is lost.
2. **`compositing_service` resolves by title.** `DEPTH_IMAGE_NODE`/`DEPTH_MODEL_NODE` are deleted, not kept as a fallback: a silent ID fallback is the defect being removed. Resolution happens once at workflow load, and the resolved nodes are class-type checked so a title pasted onto the wrong node fails loudly (13.3's pattern: the resolver supersedes the ID assertion, the class check moves onto the *resolved* node).
3. **`ytflow:depth_model` gets a real guard.** Presence of an `inputs` dict is not enough — assert the resolved node is the checkpoint loader the writes assume. This is the whole point of the story.
4. **AD-1 is respected.** `compositing_service` lives in `services/`; check whether it already imports `comfyui_client` before adding an import. 13.3 hit exactly this in `composite_harmonization.py`, where `tests/domain/test_state_imports.py` enforces a pipeline↛services allowlist marked "must not grow", and solved it by threading the resolver through the duck-typed client already being injected. Use whichever fits; do not grow the allowlist.
5. **The data test covers it.** `tests/test_workflow_definitions.py::CONSUMER_KEYS` (added by 13.3) gains a row for the depth consumer, sourced from the consumer module rather than retyped. This is the net that catches a ComfyUI-UI re-export.
6. **Behaviour unchanged.** `depth_model_resolution`, the model checkpoint, the 11.5 parallax consumption of the depth map, and `depth_map_file`'s caching/best-effort contract are untouched. Byte-identical depth maps for an unchanged graph.
7. **Census, not spot-fix.** Re-run the coupling census with a search that finds *constant-mediated* indexing, not just literals, and record the result. If a sixth site exists, this story either closes it or names it explicitly. Suggested starting point: `grep -rnE 'workflow\[(_?[A-Z_]+|"[0-9]+")\]' src/ scripts/`.
8. **Tests + `uv run ruff check`, full suite green.** Report real counts.

## Tasks / Subtasks

- [ ] **Task 0 — Census (AC: 7)** — run it *first*; the result may change this story's scope.
- [ ] **Task 1 — Retitle the depth graph (AC: 1)**
- [ ] **Task 2 — Resolve + guard in `compositing_service` (AC: 2, 3, 4)**
- [ ] **Task 3 — `CONSUMER_KEYS` row (AC: 5)**
- [ ] **Task 4 — Tests (AC: 6, 8)** — include a re-numbered-graph test; 13.3 proved position-independence live by shifting every node id by +700 and getting a pixel-identical render, which is a cheap pattern to reuse in a unit test.

## Dev Notes

### Traps

1. **`shot_recompose.py` is NOT a sixth site** — checked 2026-08-15. Its constants (`PLATE_NODE = "plate"`, `CARD_A_NODE = "card_a"`, …) are semantic node *names*, not renumber-prone integers; `_load_workflow` validates them as `LoadImage` and raises by name; and the committed graph lacks `ytflow_verified_recompose_qwen`, so the path is gated off. A reviewer flagged it as coupling on 2026-08-15 and that reading was wrong.
2. **`comfyui_qwen_pose_edit_api.json` carries sixteen `ytflow:` titles nothing resolves** (13.3 deferred item). It is the inverse defect — a manifest with no reader — and inverts the prefix's meaning. Out of scope here, but do not "tidy" it either way without deciding whether Story 8.20's qwen path is being revived.
3. **The depth path also reaches `upload_image`.** Run `e5ed4b3a` exposed that `depth_map_file` calls the *real* `comfyui_client.upload_image` when no client is injected, and that call was leaking to a live ComfyUI from the offline test profiles until 13.3's follow-up pass closed it. Do not reintroduce an un-stubbed seam.

### Files

**UPDATE**
- [src/yt_flow/services/compositing_service.py](../../src/yt_flow/services/compositing_service.py) — constants at 41-42, writes at ~314-328.
- `data/workflows/comfyui_depth_anything_v2_api.json` (+ a README for displaced prose).
- `tests/test_workflow_definitions.py`, and the compositing-service tests.

### References

- [Source: _bmad-output/implementation-artifacts/13-3-comfyui-workflow-ops-hardening.md] — resolver contract, error-message shape, `CONSUMER_KEYS` data test, the +700 renumber proof
- Project memory: `project_13-3-review-done`, `gotcha_deleting-a-constant-needs-a-reader-census`

## Dev Agent Record
