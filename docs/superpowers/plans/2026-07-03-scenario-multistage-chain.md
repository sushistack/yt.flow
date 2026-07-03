# Scenario Multi-Stage Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `scenario_node`'s single DeepSeek call with the 6-stage chain (research → structure → writing → visual_breakdown ×N → review + critic_agent, bounded 1-retry) specified in `docs/superpowers/specs/2026-07-03-scenario-multistage-design.md`, without changing the node's external contract (`PipelineState.scenes` in, gate/DB/frontend untouched).

**Architecture:** A new `scenario_chain.py` module holds one pure/async function per stage (fetch its Langfuse prompt, compile, call DeepSeek via the existing `_call_deepseek` seam, parse+validate JSON) plus the sentence splitter and the shot-merge mapping function. `scenario.py` becomes a thin orchestrator: run the chain in order, apply the bounded retry, assemble `PipelineState.scenes`. Six Langfuse prompts get seeded — four verbatim from yt.pipe via the existing `migrate_prompts.py`, two (`research`, `structure`) as small in-repo variants that change the output contract to JSON.

**Tech Stack:** Python 3.12, DeepSeek (OpenAI-compatible JSON mode) via `httpx` (already a dependency, no new one), `asyncio.gather` (stdlib) for the per-scene visual_breakdown fan-out, pytest + `pytest-asyncio` (already used by `test_scenario.py`).

## Global Constraints

- `StageName` (`scenario|image|tts|subtitle|video`) does not change — one gate for the whole chain.
- `PipelineState.scenes: list[SceneState]` is the only thing the rest of the pipeline sees; internal chain state never leaks past `scenario_node`.
- Every DeepSeek call goes through the existing `_call_deepseek(rendered, s) -> (content, usage, finish_reason)` seam in `scenario.py` — do not add a second HTTP client.
- Prompts are fetched by name via `yt_flow.services.prompt_service.get_prompt` — never hardcode prompt text in Python (existing project rule, see `scenario.py`'s original docstring).
- Retry is bounded to exactly one extra pass — never loop until a verdict is reached.
- `target_duration` is a fixed constant (3 minutes) per the spec — not a `Settings` field (it never varies).
- No new pip/uv dependency — stdlib `re`/`asyncio`/`json` cover everything needed.

---

## File Structure

- Create: `src/yt_flow/pipeline/nodes/scenario_chain.py` — the 6 stage functions, `split_sentences`, `build_scenes`.
- Modify: `src/yt_flow/pipeline/nodes/scenario.py` — replace body of `scenario_node`; keep `_call_deepseek`, `_settings`, `_ms`, `_record_trace` (adapted for multi-stage).
- Replace: `tests/pipeline/nodes/test_scenario.py` — orchestration-level tests only (the old single-call tests no longer apply).
- Create: `tests/pipeline/nodes/test_scenario_chain.py` — per-stage unit tests.
- Create: `prompts/scenario/research.md`, `prompts/scenario/structure.md` — in-repo prompt variants (JSON-contract deviations from yt.pipe source).
- Create: `tests/fixtures/cassettes/deepseek_research.json`, `deepseek_structure.json`, `deepseek_writing.json`, `deepseek_visual_breakdown.json`, `deepseek_review.json`, `deepseek_critic.json`.
- Modify: `scripts/migrate_prompts.py` — drop the unused/wrong `scenario` and `image_prompt` `ALIASES` entries.
- Delete: `prompts/scenario.md` (superseded interim single-shot draft, never committed).

---

## Task 1: Sentence splitter

**Files:**
- Create: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Test: `tests/pipeline/nodes/test_scenario_chain.py`

**Interfaces:**
- Produces: `split_sentences(text: str) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/nodes/test_scenario_chain.py
import yt_flow.pipeline.nodes.scenario_chain as chain


def test_split_sentences_basic():
    assert chain.split_sentences("격리 절차가 시작된다. 요원들이 진입한다.") == [
        "격리 절차가 시작된다.",
        "요원들이 진입한다.",
    ]


def test_split_sentences_question_and_exclamation():
    assert chain.split_sentences("무슨 일이야? 도망쳐! 늦었어.") == ["무슨 일이야?", "도망쳐!", "늦었어."]


def test_split_sentences_empty_string():
    assert chain.split_sentences("") == []


def test_split_sentences_strips_whitespace_and_blank_segments():
    assert chain.split_sentences("첫 문장.   \n\n  둘째 문장.  ") == ["첫 문장.", "둘째 문장."]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError: module ... has no attribute 'split_sentences'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/yt_flow/pipeline/nodes/scenario_chain.py
"""Multi-stage LLM chain for scenario_node.

See docs/superpowers/specs/2026-07-03-scenario-multistage-design.md for the
design this implements. Each ``*_step`` function fetches its Langfuse prompt,
compiles it, calls DeepSeek via the caller-supplied ``call_deepseek`` seam
(the same ``_call_deepseek`` from ``scenario.py`` — injected as a parameter so
tests can fake it per stage), and returns a parsed+validated payload. No
exception handling here: every failure propagates to ``scenario_node``, which
converts it into ``PipelineState.error`` exactly as before.
"""

import re

# ponytail: fixed per the design spec — this never varies, so it's a constant,
# not a Settings field.
TARGET_DURATION_MINUTES = 3

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences on '.'/'?'/'!' + whitespace.

    ponytail: regex heuristic tuned to writing_step's own output style (short
    TTS-friendly sentences ending in standard punctuation), not a general
    tokenizer.
    """
    text = text.strip()
    if not text:
        return []
    return [p.strip() for p in _SENTENCE_BOUNDARY.split(text) if p.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py
git commit -m "feat: add sentence splitter for scenario visual_breakdown stage"
```

---

## Task 2: Author and seed the 6 Langfuse prompts

**Files:**
- Create: `prompts/scenario/research.md`
- Create: `prompts/scenario/structure.md`
- Modify: `scripts/migrate_prompts.py`

**Interfaces:**
- Produces: Langfuse prompts named `scenario/research`, `scenario/structure`, `scenario/writing`, `scenario/visual_breakdown`, `scenario/review`, `scenario/critic_agent`, `scenario/format_guide`, all labeled `production`. Task 3-5's `_call_stage` helper fetches these by exact name.

- [ ] **Step 1: Write the JSON-contract research prompt**

Based on `/mnt/work/projects/yt.pipe/templates/scenario/01_research.md`, identical except the final `## Task` section, which now demands JSON instead of "structured text with clear section headers" (per the spec's noted deviation — downstream stages need `frozen_descriptor` extracted programmatically).

```markdown
# Stage 1: SCP Research & Visual Identity Analysis

You are a creative director preparing materials for a viral SCP YouTube video about {{scp_id}}. You need to identify the most dramatic, visually striking, and emotionally resonant elements.

## Source Data

### SCP Fact Sheet
{{scp_fact_sheet}}

### SCP Full Document
{{main_text}}

{{glossary_section}}

## Storytelling Format Guide

Use the following format guide to identify narrative hooks and dramatic structure during research.

{{format_guide}}

## Task

Analyze the provided SCP data and produce a research packet. Respond with ONLY a JSON object, no prose, no markdown fences:

```json
{
  "core_identity": "Official designation, object class, primary anomalous properties, containment summary, discovery/origin context, key incidents — as flowing text.",
  "frozen_descriptor": "A single dense physical description covering: Silhouette & Build, Head/Face, Body Covering, Hands & Limbs, Carried Items, Organic Integration Note (if applicable). This will be reused verbatim across all image prompts for visual consistency.",
  "dramatic_beats": "6-10 dramatic moments from the document suitable for video scenes, ordered from introduction to climax, each noting its emotional tone.",
  "environment": "Primary settings/locations, lighting conditions, ambient sounds/environmental factors, overall mood and horror subgenre.",
  "hooks": "Opening hook candidates (3, using different hook types: Question/Shock/Mystery/Contrast, each a single punchy Korean sentence that does NOT mention SCP classification), the mid-video twist, the closing mystery, and a 'what if' moment."
}
```

Every field is a non-empty string. `frozen_descriptor` must not be empty — it is the single source of visual truth for every later stage.
```

- [ ] **Step 2: Write the object-wrapped structure prompt**

Based on `02_structure.md`, identical except the output is wrapped in a `{"scenes": [...]}` object instead of a bare array (DeepSeek's `response_format=json_object` mode requires a top-level JSON object).

```markdown
# Stage 2: Scene Structure Design

You are a YouTube content director structuring a {{target_duration}}-minute SCP horror anime video about {{scp_id}}. Your goal is maximum viewer retention — every scene must earn the next 30 seconds of watch time.

## Research Packet (from Stage 1)
{{research_packet}}

## Visual Identity Profile (Frozen Descriptor)
{{scp_visual_reference}}

{{glossary_section}}

## Storytelling Format Guide

Apply the following storytelling principles when designing scene structure, emotional curve, and pacing.

{{format_guide}}

## Structure Requirements

Design the scene structure following the **INCIDENT-FIRST format**. This is NOT a wiki article — viewers don't care about classification. They care about WHAT HAPPENED.

**Structure (4 acts, but the order is different from a wiki):**
- **Act 1 - 사건으로 시작** (~15%): 가장 충격적인 사건, 피해, 또는 미스터리로 시작. 개체 이름이나 등급을 말하지 마세요. "무슨 일이 일어났는지"만 보여주세요.
- **Act 2 - 미스터리 확장** (~30%): 사건의 맥락을 더 주되, 정체는 아직 완전히 드러내지 마세요. "왜 이런 일이 일어났을까?"를 시청자가 궁금해하게. 격리 절차를 통해 위험성을 간접적으로 암시.
- **Act 3 - 정체 공개 + 더 깊은 사건** (~40%): 이제서야 개체가 뭔지 본격적으로 밝힘. 추가 사건/실험 로그/목격담으로 공포를 극대화. 가장 무서운 디테일은 여기에.
- **Act 4 - 미해결 미스터리** (~15%): 재단도 모르는 것, 해결 안 된 질문, 시청자에게 여운을 남기는 결말.

**핵심 원칙:**
- ❌ "SCP-173은 유클리드 등급 개체입니다. 1993년에 발견되었습니다." (위키 순서)
- ✅ "14명의 인원이 목이 꺾인 채 발견되었습니다. 어떤 무기도 사용되지 않았습니다." (사건 순서)
- 개체의 정체와 능력은 **미스터리처럼 천천히 드러내세요**
- 격리 절차는 "이렇게까지 해야 하는 이유"를 암시하는 장치로 사용

## Task

For each scene (8-12 total), include:

```json
{
  "scene_num": 1,
  "act": "hook",
  "synopsis": "Brief description of what happens in this scene",
  "key_points": ["fact or detail to convey", "visual element to show"],
  "emotional_beat": "tension/mystery/horror/revelation/etc",
  "estimated_duration_sec": 45,
  "fact_references": ["fact_key_1", "fact_key_2"]
}
```

### Rules:
1. Each scene's `key_points` must reference the Visual Identity Profile verbatim when the entity appears
2. Scenes must cover all Key Dramatic Beats from the research
3. Each fact from the source data should appear in at least one scene's `fact_references`
4. **Pacing variation is MANDATORY**: alternate between slower atmospheric scenes (60-90s) and faster incident scenes (30-45s). Never use the same duration for 3+ consecutive scenes.
5. **The first scene must hook within 5 seconds** — use one of the candidate hooks from the research packet
6. The last scene must leave an unresolved mystery
7. **Adjacent scenes MUST have different emotional beats** — never repeat the same mood consecutively
8. **Include at least one "viewer immersion" scene** where the narration addresses the viewer directly (2nd person)

Respond with ONLY a JSON object, no prose, no markdown fences: `{"scenes": [ ...scene objects as above... ]}`.
```

- [ ] **Step 3: Remove the broken/unused aliases from migrate_prompts.py**

The `scenario` alias (→ `01_research.md`) and `image_prompt` alias (→ `image/02_shot_to_prompt.md`) predate this design and are wrong for it (`scenario_node` never calls a prompt literally named `scenario` anymore; `image/shot_to_prompt` is explicitly out of scope per the spec). Remove them so a future `migrate_prompts.py` run can't silently recreate a stale/misleading prompt.

In `scripts/migrate_prompts.py`, replace:

```python
# Required runtime entrypoint prompts -> source file (relative to --source) they wrap.
# Downstream nodes fetch these by name; they must compile without node-side concatenation.
ALIASES = {
    "scenario": "scenario/01_research.md",
    "image_prompt": "image/02_shot_to_prompt.md",
}
```

with:

```python
# No runtime entrypoint aliases: scenario_chain.py fetches prompts by their
# discovered scenario/* names directly (see docs/superpowers/specs/
# 2026-07-03-scenario-multistage-design.md). image/shot_breakdown and
# image/shot_to_prompt are migrated for reference but unused by yt.flow.
ALIASES: dict[str, str] = {}
```

- [ ] **Step 4: Dry-run to confirm the discovered prompt set**

Run: `cd /mnt/work/projects/yt.flow && uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates --dry-run`
Expected: 11 lines, including `scenario/writing`, `scenario/visual_breakdown`, `scenario/review`, `scenario/critic_agent`, `scenario/format_guide` — and no bare `scenario:` or `image_prompt:` line (those aliases are gone).

- [ ] **Step 5: Seed the 5 verbatim prompts from yt.pipe**

Run: `cd /mnt/work/projects/yt.flow && uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates`
Expected: `created: scenario/writing`, `created: scenario/visual_breakdown`, `created: scenario/review`, `created: scenario/critic_agent`, `created: scenario/format_guide` (plus the unused `image/*`, `tts/*`, `vision/*` ones — harmless).

- [ ] **Step 6: Seed the 2 in-repo JSON-contract variants**

```bash
cd /mnt/work/projects/yt.flow
uv run python -c "
from yt_flow.services.prompt_service import build_client
client = build_client()
for name, path in [('scenario/research', 'prompts/scenario/research.md'), ('scenario/structure', 'prompts/scenario/structure.md')]:
    text = open(path, encoding='utf-8').read().strip()
    client.create_prompt(name=name, type='text', prompt=text, labels=['production'])
    print(f'created: {name}')
"
```

Expected: `created: scenario/research` and `created: scenario/structure`.

- [ ] **Step 7: Verify all 7 prompts are fetchable**

```bash
cd /mnt/work/projects/yt.flow
uv run python -c "
from yt_flow.services.prompt_service import build_client
client = build_client()
for name in ['scenario/research', 'scenario/structure', 'scenario/writing', 'scenario/visual_breakdown', 'scenario/review', 'scenario/critic_agent', 'scenario/format_guide']:
    p = client.get_prompt(name, label='production')
    print(name, 'OK', len(p.prompt), 'chars')
"
```

Expected: 7 lines, each `OK` with a nonzero char count, no exceptions.

- [ ] **Step 8: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add prompts/scenario/research.md prompts/scenario/structure.md scripts/migrate_prompts.py
git commit -m "feat: seed 7-prompt scenario chain into Langfuse Prompt Hub"
```

---

## Task 3: `research_step` and `structure_step`

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Modify: `tests/pipeline/nodes/test_scenario_chain.py`
- Create: `tests/fixtures/cassettes/deepseek_research.json`
- Create: `tests/fixtures/cassettes/deepseek_structure.json`

**Interfaces:**
- Consumes: `TARGET_DURATION_MINUTES` (Task 1)
- Produces:
  - `async def _call_stage(prompt_name: str, variables: dict, s, call_deepseek) -> str`
  - `async def research_step(scp_id: str, scp_text: str, format_guide: str, s, call_deepseek) -> dict` — keys `core_identity, frozen_descriptor, dramatic_beats, environment, hooks` (all `str`)
  - `async def structure_step(scp_id: str, research: dict, format_guide: str, s, call_deepseek) -> list[dict]` — each item has `scene_num, act, synopsis, key_points, emotional_beat, estimated_duration_sec`

- [ ] **Step 1: Add the two cassette fixtures**

```json
// tests/fixtures/cassettes/deepseek_research.json
{
  "id": "chatcmpl-cassette-research",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"core_identity\": \"SCP-173 is a Euclid-class hostile sculpture that can only move unobserved.\", \"frozen_descriptor\": \"Silhouette & Build: rigid 2-meter humanoid concrete form. Head/Face: featureless smooth dome. Body Covering: weathered grey concrete with visible rebar seams. Hands & Limbs: elongated clawed fingers. Carried Items: none. Organic Integration Note: reddish-brown staining at the base, origin unknown.\", \"dramatic_beats\": \"1) First blinking incident kills a guard. 2) Camera blind spot discovered. 3) Containment chamber redesign after second death.\", \"environment\": \"Underground concrete containment chamber, harsh fluorescent lighting, damp floor stains, oppressive silence.\", \"hooks\": \"Opening hooks: 'Blink and you die.' / 'Fourteen people are dead and no one saw it move.' / 'It has never been photographed moving.' Mid-video twist: cameras don't stop it either. Closing mystery: no one knows where it came from.\"}"
      }
    }
  ],
  "usage": {"prompt_tokens": 400, "completion_tokens": 180, "total_tokens": 580}
}
```

```json
// tests/fixtures/cassettes/deepseek_structure.json
{
  "id": "chatcmpl-cassette-structure",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"scenes\": [{\"scene_num\": 1, \"act\": \"hook\", \"synopsis\": \"A guard is found dead with a broken neck, no weapon present.\", \"key_points\": [\"14 deaths total\", \"no weapon found\"], \"emotional_beat\": \"tension\", \"estimated_duration_sec\": 45, \"fact_references\": [\"death_count\"]}, {\"scene_num\": 2, \"act\": \"mystery_expansion\", \"synopsis\": \"Security footage shows the room was empty seconds before.\", \"key_points\": [\"footage anomaly\"], \"emotional_beat\": \"mystery\", \"estimated_duration_sec\": 75, \"fact_references\": [\"camera_blind_spot\"]}]}"
      }
    }
  ],
  "usage": {"prompt_tokens": 500, "completion_tokens": 150, "total_tokens": 650}
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/pipeline/nodes/test_scenario_chain.py (append)
import json
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "cassettes"


def _load_cassette(name):
    return json.loads((CASSETTE_DIR / name).read_text(encoding="utf-8"))


def _deepseek_from_cassette(name):
    data = _load_cassette(name)
    choice = data["choices"][0]

    async def fake(rendered, s):
        return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")

    return fake


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


async def test_research_step_returns_frozen_descriptor(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_research.json")
    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    assert result["frozen_descriptor"].startswith("Silhouette")
    assert result["core_identity"]


async def test_research_step_rejects_empty_frozen_descriptor(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="frozen_descriptor"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


async def test_structure_step_returns_scene_list(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_structure.json")
    research = {"frozen_descriptor": "desc"}
    scenes = await chain.structure_step("SCP-173", research, "guide", None, call)
    assert len(scenes) == 2
    assert scenes[0]["scene_num"] == 1
    assert scenes[0]["emotional_beat"] == "tension"


async def test_structure_step_rejects_empty_scene_list(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"scenes": []}), {}, "stop"

    with pytest.raises(ValueError, match="scenes"):
        await chain.structure_step("SCP-173", {"frozen_descriptor": "d"}, "guide", None, call)
```

Add `import pytest` at the top of the test file if not already present (it is — the existing file style uses bare async def tests under pytest-asyncio's auto mode, matching `test_scenario.py`'s convention).

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: FAIL — `AttributeError: module 'yt_flow.pipeline.nodes.scenario_chain' has no attribute 'research_step'`

- [ ] **Step 4: Implement `_call_stage`, `research_step`, `structure_step`**

Append to `src/yt_flow/pipeline/nodes/scenario_chain.py`:

```python
import json

from yt_flow.services.prompt_service import get_prompt


async def _call_stage(prompt_name: str, variables: dict, s, call_deepseek) -> str:
    """Fetch + compile a Langfuse prompt, call DeepSeek, return raw JSON text.

    Raises on truncation (finish_reason == "length") so a caller never has to
    special-case a partial payload — json.loads on it would fail anyway, but
    this gives a clearer error message.
    """
    rendered = get_prompt(prompt_name).compile(**variables)
    raw, _usage, finish_reason = await call_deepseek(rendered, s)
    if finish_reason == "length":
        raise ValueError(f"{prompt_name} response truncated (finish_reason=length); raise max_tokens")
    return raw


async def research_step(scp_id: str, scp_text: str, format_guide: str, s, call_deepseek) -> dict:
    raw = await _call_stage(
        "scenario/research",
        {
            "scp_id": scp_id,
            "scp_fact_sheet": scp_text,
            "main_text": scp_text,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or not str(data.get("frozen_descriptor") or "").strip():
        raise ValueError("research: payload missing non-empty 'frozen_descriptor'")
    return data


async def structure_step(scp_id: str, research: dict, format_guide: str, s, call_deepseek) -> list[dict]:
    raw = await _call_stage(
        "scenario/structure",
        {
            "scp_id": scp_id,
            "research_packet": json.dumps(research, ensure_ascii=False),
            "scp_visual_reference": research["frozen_descriptor"],
            "target_duration": TARGET_DURATION_MINUTES,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("structure: payload must contain a non-empty 'scenes' list")
    return scenes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py tests/fixtures/cassettes/deepseek_research.json tests/fixtures/cassettes/deepseek_structure.json
git commit -m "feat: add research_step and structure_step to scenario chain"
```

---

## Task 4: `writing_step` and `visual_breakdown_step`

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Modify: `tests/pipeline/nodes/test_scenario_chain.py`
- Create: `tests/fixtures/cassettes/deepseek_writing.json`
- Create: `tests/fixtures/cassettes/deepseek_visual_breakdown.json`

**Interfaces:**
- Consumes: `_call_stage` (Task 3), `split_sentences` (Task 1)
- Produces:
  - `async def writing_step(scp_id: str, structure: list[dict], frozen_descriptor: str, format_guide: str, quality_feedback: str, s, call_deepseek) -> dict` — `{"scp_id": str, "title": str, "scenes": [{"scene_num", "narration", "location", "characters_present", "color_palette", "atmosphere"}]}`
  - `async def visual_breakdown_step(scene: dict, sentences: list[str], frozen_descriptor: str, s, call_deepseek) -> list[dict]` — one item per sentence: `{"image_prompt", "negative_prompt", "sentence_start", "sentence_end", "entity_visible", "camera_type"}`

- [ ] **Step 1: Add the two cassette fixtures**

```json
// tests/fixtures/cassettes/deepseek_writing.json
{
  "id": "chatcmpl-cassette-writing",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"scp_id\": \"SCP-173\", \"title\": \"눈을 감는 순간\", \"scenes\": [{\"scene_num\": 1, \"narration\": \"14명. 단 하룻밤에 목이 꺾인 채 발견된 재단 인원 수입니다. (정적) 아무도 무기를 찾지 못했습니다.\", \"location\": \"underground containment chamber\", \"characters_present\": [\"SCP-173\"], \"color_palette\": \"cold gray, fluorescent white\", \"atmosphere\": \"claustrophobic dread, oppressive silence\"}]}"
      }
    }
  ],
  "usage": {"prompt_tokens": 600, "completion_tokens": 200, "total_tokens": 800}
}
```

```json
// tests/fixtures/cassettes/deepseek_visual_breakdown.json
{
  "id": "chatcmpl-cassette-visual-breakdown",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"scene_num\": 1, \"visual_descriptions\": [{\"image_prompt\": \"high-angle wide shot, a covered body under a stained white sheet on a poured concrete floor, three foundation guards frozen mid-stride at frame edges, damp concrete floor with hairline cracks, twin fluorescent tubes casting hard shadows, thin condensation mist at knee level, paralytic helplessness, institutional dread\", \"negative_prompt\": \"extra limbs, extra arms, extra fingers, deformed hands, mutated, bad anatomy, blurry, watermark, text, low quality\", \"sentence_start\": 1, \"sentence_end\": 1, \"entity_visible\": false, \"camera_type\": \"high-angle\"}, {\"image_prompt\": \"\", \"negative_prompt\": \"\", \"sentence_start\": 2, \"sentence_end\": 2, \"entity_visible\": false, \"camera_type\": \"wide\"}, {\"image_prompt\": \"static wide shot, an empty steel evidence table under a single hanging bulb, a blank chain-of-custody form and an unused weapon-tag envelope, bare cinder block walls with peeling green paint, harsh single-source light with hard falloff, still air with no dust motes, procedural futility, institutional denial\", \"negative_prompt\": \"extra limbs, extra arms, extra fingers, deformed hands, mutated, bad anatomy, blurry, watermark, text, low quality\", \"sentence_start\": 3, \"sentence_end\": 3, \"entity_visible\": false, \"camera_type\": \"wide\"}]}"
      }
    }
  ],
  "usage": {"prompt_tokens": 700, "completion_tokens": 250, "total_tokens": 950}
}
```

Note the middle entry has an empty `image_prompt`/`negative_prompt` — this is the transition-sentence case (`(정적)`) Task 6's merge logic must handle.

- [ ] **Step 2: Write the failing tests**

```python
# tests/pipeline/nodes/test_scenario_chain.py (append)
async def test_writing_step_returns_scenes(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_writing.json")
    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert result["scenes"][0]["narration"]
    assert result["scenes"][0]["location"] == "underground containment chamber"


async def test_writing_step_rejects_empty_narration(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scp_id": "SCP-173", "title": "t", "scenes": [{"scene_num": 1, "narration": "", "location": "x", "characters_present": [], "color_palette": "x", "atmosphere": "x"}]}
        return json.dumps(payload), {}, "stop"

    with pytest.raises(ValueError, match="narration"):
        await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)


async def test_visual_breakdown_step_maps_one_shot_per_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_visual_breakdown.json")
    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    sentences = ["첫 문장.", "(정적)", "셋째 문장."]
    result = await chain.visual_breakdown_step(scene, sentences, "desc", None, call)
    assert len(result) == 3
    assert result[0]["image_prompt"]
    assert result[1]["image_prompt"] == ""  # transition sentence, no image
    assert result[2]["camera_type"] == "wide"


async def test_visual_breakdown_step_rejects_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [{"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "entity_visible": False, "camera_type": "wide"}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    with pytest.raises(ValueError, match="1:1"):
        await chain.visual_breakdown_step(scene, ["문장1.", "문장2."], "desc", None, call)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'writing_step'`

- [ ] **Step 4: Implement `writing_step` and `visual_breakdown_step`**

Append to `src/yt_flow/pipeline/nodes/scenario_chain.py`:

```python
async def writing_step(
    scp_id: str,
    structure: list[dict],
    frozen_descriptor: str,
    format_guide: str,
    quality_feedback: str,
    s,
    call_deepseek,
) -> dict:
    raw = await _call_stage(
        "scenario/writing",
        {
            "scp_id": scp_id,
            "scene_structure": json.dumps(structure, ensure_ascii=False),
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
            "quality_feedback": quality_feedback,
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("writing: payload must contain a non-empty 'scenes' list")
    for scene in scenes:
        if not str(scene.get("narration") or "").strip():
            raise ValueError(f"writing: scene[{scene.get('scene_num')}] has empty narration")
    return data


async def visual_breakdown_step(
    scene: dict,
    sentences: list[str],
    frozen_descriptor: str,
    s,
    call_deepseek,
) -> list[dict]:
    numbered = "\n".join(f"{i + 1}. {sent}" for i, sent in enumerate(sentences))
    raw = await _call_stage(
        "scenario/visual_breakdown",
        {
            "scene_num": scene["scene_num"],
            "location": scene["location"],
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "color_palette": scene["color_palette"],
            "atmosphere": scene["atmosphere"],
            "scp_visual_reference": frozen_descriptor,
            "character_visual_context": "",
            "narration": scene.get("narration", ""),
            "numbered_sentences": numbered,
            "sentence_count": len(sentences),
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    shots = data.get("visual_descriptions") if isinstance(data, dict) else None
    if not isinstance(shots, list) or len(shots) != len(sentences):
        raise ValueError(
            f"visual_breakdown: expected 1:1 sentence-to-shot mapping "
            f"({len(sentences)} sentences), got {len(shots) if isinstance(shots, list) else 'non-list'}"
        )
    return shots
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py tests/fixtures/cassettes/deepseek_writing.json tests/fixtures/cassettes/deepseek_visual_breakdown.json
git commit -m "feat: add writing_step and visual_breakdown_step to scenario chain"
```

---

## Task 5: `review_step` and `critic_step`

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Modify: `tests/pipeline/nodes/test_scenario_chain.py`
- Create: `tests/fixtures/cassettes/deepseek_review.json`
- Create: `tests/fixtures/cassettes/deepseek_critic.json`

**Interfaces:**
- Consumes: `_call_stage` (Task 3)
- Produces:
  - `async def review_step(scp_text: str, writing: dict, visual_by_scene: dict[int, list[dict]], frozen_descriptor: str, format_guide: str, s, call_deepseek) -> dict` — `{"overall_pass": bool, "coverage_pct": float, "issues": list, "corrections": list, "storytelling_score": float, "storytelling_issues": list}`
  - `async def critic_step(writing: dict, visual_by_scene: dict[int, list[dict]], format_guide: str, s, call_deepseek) -> dict` — `{"verdict": "pass"|"retry"|"accept_with_notes", "feedback": str, "scene_notes": list}`

- [ ] **Step 1: Add the two cassette fixtures**

```json
// tests/fixtures/cassettes/deepseek_review.json
{
  "id": "chatcmpl-cassette-review",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"overall_pass\": true, \"coverage_pct\": 92.0, \"issues\": [], \"corrections\": [], \"storytelling_score\": 81, \"storytelling_issues\": []}"
      }
    }
  ],
  "usage": {"prompt_tokens": 900, "completion_tokens": 80, "total_tokens": 980}
}
```

```json
// tests/fixtures/cassettes/deepseek_critic.json
{
  "id": "chatcmpl-cassette-critic",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"verdict\": \"pass\", \"hook_effective\": true, \"retention_risk\": \"low\", \"ending_impact\": \"strong\", \"feedback\": \"훅이 강력하고 몰입도가 높습니다.\", \"scene_notes\": []}"
      }
    }
  ],
  "usage": {"prompt_tokens": 900, "completion_tokens": 60, "total_tokens": 960}
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/pipeline/nodes/test_scenario_chain.py (append)
async def test_review_step_returns_report(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_review.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.review_step("scp text", writing, {1: []}, "desc", "guide", None, call)
    assert result["overall_pass"] is True
    assert result["coverage_pct"] == 92.0


async def test_review_step_rejects_missing_overall_pass(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"coverage_pct": 50.0}), {}, "stop"

    with pytest.raises(ValueError, match="overall_pass"):
        await chain.review_step("t", {"scenes": []}, {}, "desc", "guide", None, call)


async def test_critic_step_returns_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_critic.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step(writing, {1: []}, "guide", None, call)
    assert result["verdict"] == "pass"
    assert result["feedback"]


async def test_critic_step_rejects_unknown_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"verdict": "maybe", "feedback": "x", "scene_notes": []}), {}, "stop"

    with pytest.raises(ValueError, match="verdict"):
        await chain.critic_step({"scenes": []}, {}, "guide", None, call)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'review_step'`

- [ ] **Step 4: Implement `review_step` and `critic_step`**

Append to `src/yt_flow/pipeline/nodes/scenario_chain.py`:

```python
_VALID_VERDICTS = {"pass", "retry", "accept_with_notes"}


async def review_step(
    scp_text: str,
    writing: dict,
    visual_by_scene: dict,
    frozen_descriptor: str,
    format_guide: str,
    s,
    call_deepseek,
) -> dict:
    raw = await _call_stage(
        "scenario/review",
        {
            "scp_id": writing.get("scp_id", ""),
            "scp_fact_sheet": scp_text,
            "narration_script": json.dumps(writing, ensure_ascii=False),
            "visual_descriptions": json.dumps(visual_by_scene, ensure_ascii=False),
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or "overall_pass" not in data:
        raise ValueError("review: payload missing 'overall_pass'")
    return data


async def critic_step(writing: dict, visual_by_scene: dict, format_guide: str, s, call_deepseek) -> dict:
    scenario_json = {"writing": writing, "visual_descriptions": visual_by_scene}
    raw = await _call_stage(
        "scenario/critic_agent",
        {
            "format_guide": format_guide,
            "scenario_json": json.dumps(scenario_json, ensure_ascii=False),
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("verdict") not in _VALID_VERDICTS:
        raise ValueError(f"critic_agent: payload has invalid 'verdict' (must be one of {_VALID_VERDICTS})")
    return data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: 16 passed

- [ ] **Step 6: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py tests/fixtures/cassettes/deepseek_review.json tests/fixtures/cassettes/deepseek_critic.json
git commit -m "feat: add review_step and critic_step to scenario chain"
```

---

## Task 6: Shot-merge mapping (`build_scenes`)

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Modify: `tests/pipeline/nodes/test_scenario_chain.py`

**Interfaces:**
- Consumes: nothing new — pure function over plain dicts (no LLM calls, no fixtures)
- Produces: `build_scenes(writing: dict, visual_by_scene: dict[int, list[dict]]) -> list[SceneState]` — imports `SceneState`, `ShotData` from `yt_flow.domain.state`

This is the piece the spec calls out explicitly: an empty `image_prompt` (transition-only sentence) must not become its own `ShotData` — it merges into the previous shot's `sentence_indices` instead, so every `ShotData.image_prompt` stays non-empty (yt.flow's `image_node` needs a real prompt per shot) while every sentence index is still covered by exactly one shot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/pipeline/nodes/test_scenario_chain.py (append)
def test_build_scenes_merges_empty_prompt_into_previous_shot():
    writing = {
        "scenes": [
            {"scene_num": 1, "narration": "첫 문장. (정적) 셋째 문장."}
        ]
    }
    visual_by_scene = {
        1: [
            {"image_prompt": "shot one", "negative_prompt": "neg one", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 2, "sentence_end": 2, "camera_type": "wide"},
            {"image_prompt": "shot three", "negative_prompt": "neg three", "sentence_start": 3, "sentence_end": 3, "camera_type": "close-up"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene)
    assert len(scenes) == 1
    shots = scenes[0]["shots"]
    assert len(shots) == 2  # the empty-prompt sentence merged into shot 1, not its own shot
    assert shots[0]["sentence_indices"] == [0, 1]  # 0-based: sentences 1 and 2
    assert shots[1]["sentence_indices"] == [2]
    assert all(s["image_prompt"] for s in shots)  # never empty


def test_build_scenes_first_sentence_empty_falls_back_to_scene_context():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적) 둘째 문장.", "location": "hallway", "atmosphere": "cold dread"}]}
    visual_by_scene = {
        1: [
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "shot two", "negative_prompt": "neg two", "sentence_start": 2, "sentence_end": 2, "camera_type": "medium"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene)
    shots = scenes[0]["shots"]
    assert len(shots) == 2  # no previous shot to merge into -> kept as its own, backfilled
    assert "hallway" in shots[0]["image_prompt"] or "cold dread" in shots[0]["image_prompt"]
    assert shots[0]["sentence_indices"] == [0]


def test_build_scenes_scene_num_is_positional():
    writing = {"scenes": [
        {"scene_num": 1, "narration": "문장."},
        {"scene_num": 1, "narration": "다른 문장."},  # duplicate scene_num from a misbehaving LLM
    ]}
    visual_by_scene = {
        1: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}],
    }
    # Reuse the same visual breakdown for both (test only cares about positional numbering).
    visual_by_scene_full = {1: visual_by_scene[1], 2: visual_by_scene[1]}
    scenes = chain.build_scenes(writing, visual_by_scene_full)
    assert [s["scene_num"] for s in scenes] == [1, 2]


def test_build_scenes_no_shots_after_merge_raises():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적)"}]}
    visual_by_scene = {1: [{"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]}
    # Single sentence, empty prompt, nothing to merge into and no scene context to fall back on cleanly —
    # location/atmosphere still present (writing_step guarantees non-empty), so this should NOT raise;
    # it falls back to scene-context text. Assert it produces exactly one non-empty shot instead.
    scenes = chain.build_scenes(writing, {1: [{**visual_by_scene[1][0]}]})
```

Fix the last test to actually assert something concrete instead of trailing off — replace it with:

```python
def test_build_scenes_single_empty_shot_falls_back_not_raises():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적)", "location": "vault", "atmosphere": "silence"}]}
    visual_by_scene = {1: [{"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]}
    scenes = chain.build_scenes(writing, visual_by_scene)
    assert len(scenes[0]["shots"]) == 1
    assert scenes[0]["shots"][0]["image_prompt"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'build_scenes'`

- [ ] **Step 3: Implement `build_scenes`**

Append to `src/yt_flow/pipeline/nodes/scenario_chain.py`:

```python
from yt_flow.domain.state import SceneState, ShotData


def _fallback_prompt(scene: dict) -> str:
    """Minimal prompt for a leading transition-only sentence with nothing to merge into."""
    location = scene.get("location") or "an unmarked containment area"
    atmosphere = scene.get("atmosphere") or "tense silence"
    return f"static wide shot, {location}, {atmosphere}, no visible subject"


def build_scenes(writing: dict, visual_by_scene: dict) -> list:
    """Convert the chain's per-scene narration + visual_descriptions into PipelineState.scenes.

    A shot with an empty ``image_prompt`` (yt.pipe's transition/effect-only
    sentence marker) is merged into the previous shot's ``sentence_indices``
    instead of becoming its own ``ShotData`` — yt.flow's image_node needs a
    real prompt for every shot it renders.
    """
    scenes: list = []
    for idx, writing_scene in enumerate(writing["scenes"]):
        scene_num = idx + 1  # positional, matches scenario.py's pre-existing rule
        raw_shots = visual_by_scene[writing_scene["scene_num"]]

        shots: list = []
        for i, raw_shot in enumerate(raw_shots):
            sentence_idx = raw_shot["sentence_start"] - 1  # 1-based -> 0-based
            image_prompt = str(raw_shot.get("image_prompt") or "").strip()

            if not image_prompt:
                if shots:
                    shots[-1]["sentence_indices"].append(sentence_idx)
                    continue
                # No previous shot to merge into (leading transition sentence) — backfill.
                image_prompt = _fallback_prompt(writing_scene)
                raw_shot = {**raw_shot, "negative_prompt": raw_shot.get("negative_prompt") or ""}

            shots.append(
                ShotData(
                    shot_id=f"S{scene_num:03d}{i:02d}",
                    sentence_indices=[sentence_idx],
                    image_prompt=image_prompt,
                    negative_prompt=str(raw_shot.get("negative_prompt") or ""),
                    camera_angle=raw_shot.get("camera_type") if isinstance(raw_shot.get("camera_type"), str) else None,
                    camera_movement=None,  # yt.pipe's visual_breakdown has no equivalent field
                    image_path=None,
                    background_path=None,
                    character_path=None,
                )
            )

        if not shots:
            raise ValueError(f"scene[{scene_num}]: no shots produced after merge")

        scenes.append(
            SceneState(
                scene_num=scene_num,
                narration=writing_scene["narration"],
                shots=shots,
                audio_path=None,
                audio_duration=None,
                word_timings=[],
                subtitle_path=None,
            )
        )
    return scenes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py
git commit -m "feat: add build_scenes shot-merge mapping to scenario chain"
```

---

## Task 7: Orchestrate `scenario_node` with bounded retry

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario.py`
- Replace: `tests/pipeline/nodes/test_scenario.py`

**Interfaces:**
- Consumes: every function from `scenario_chain.py` (Tasks 1, 3-6): `research_step`, `structure_step`, `writing_step`, `visual_breakdown_step`, `review_step`, `critic_step`, `build_scenes`, `split_sentences`
- Produces: `async def scenario_node(state: PipelineState) -> dict` — same public signature as before (`{"scenes": [...], "current_stage": "scenario"}` on success, `{"current_stage": "scenario", "error": str}` on failure)

- [ ] **Step 1: Read the current file to see what to keep**

`_call_deepseek`, `_settings`, `_ms`, `_require_text`/`_opt_text`/`_parse_indices` (no longer used — `build_scenes` replaces `_parse_scenes`, delete it), `_record_trace` (adapt), the `@observe(name="scenario")` decorator on `scenario_node` (keep).

- [ ] **Step 2: Replace `tests/pipeline/nodes/test_scenario.py` entirely**

The old file tested the single-call design's parsing directly (`_parse_scenes` via raw JSON) — that function is gone. The new orchestration tests stub each chain function instead:

```python
"""Unit tests for src/yt_flow/pipeline/nodes/scenario.py orchestration (multi-stage
chain redesign — see docs/superpowers/specs/2026-07-03-scenario-multistage-design.md).

Per-stage parsing/validation is covered by test_scenario_chain.py; these tests
only cover scenario_node's own responsibility: sequencing, the bounded retry,
and surfacing errors as PipelineState.error.
"""

import pytest

import yt_flow.pipeline.nodes.scenario as sc


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


RESEARCH = {"core_identity": "x", "frozen_descriptor": "desc", "dramatic_beats": "x", "environment": "x", "hooks": "x"}
STRUCTURE = [{"scene_num": 1, "act": "hook", "synopsis": "x", "key_points": [], "emotional_beat": "tension", "estimated_duration_sec": 45}]
WRITING = {"scp_id": "SCP-173", "title": "t", "scenes": [{"scene_num": 1, "narration": "문장.", "location": "x", "characters_present": [], "color_palette": "x", "atmosphere": "x"}]}
VISUAL = [{"image_prompt": "shot", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]
REVIEW_PASS = {"overall_pass": True, "coverage_pct": 90.0, "issues": [], "corrections": [], "storytelling_score": 80, "storytelling_issues": []}
REVIEW_FAIL = {**REVIEW_PASS, "overall_pass": False, "issues": [{"scene_num": 1, "description": "bad", "correction": "fix it"}]}
CRITIC_PASS = {"verdict": "pass", "feedback": "good", "scene_notes": []}
CRITIC_RETRY = {"verdict": "retry", "feedback": "다시 써주세요", "scene_notes": []}


def _state(**over):
    base = {
        "run_id": "run-123",
        "scp_id": "SCP-173",
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": [],
        "video_path": None,
        "current_stage": "",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(sc, "_settings", lambda: FakeSettings())
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: None)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())


def _stub_chain(monkeypatch, *, review=REVIEW_PASS, critic=CRITIC_PASS, review_retry=None, critic_retry=None):
    calls = {"writing": 0}

    async def fake_research(*a, **k):
        return RESEARCH

    async def fake_structure(*a, **k):
        return STRUCTURE

    async def fake_writing(*a, **k):
        calls["writing"] += 1
        return WRITING

    async def fake_visual(*a, **k):
        return VISUAL

    async def fake_review(*a, **k):
        return review_retry if (calls["writing"] > 1 and review_retry) else review

    async def fake_critic(*a, **k):
        return critic_retry if (calls["writing"] > 1 and critic_retry) else critic

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    return calls


async def test_success_populates_scenes(monkeypatch):
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out.get("error") is None
    assert len(out["scenes"]) == 1
    assert out["scenes"][0]["shots"][0]["image_prompt"] == "shot"


async def test_no_retry_when_critic_passes(monkeypatch):
    calls = _stub_chain(monkeypatch)
    await sc.scenario_node(_state())
    assert calls["writing"] == 1


async def test_retries_once_when_critic_says_retry(monkeypatch):
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2  # exactly one retry, not an open loop
    assert out.get("error") is None


async def test_retries_once_when_review_fails(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2
    assert out.get("error") is None


async def test_accepts_second_pass_result_even_if_still_failing(monkeypatch):
    # Bounded retry: even if the second pass ALSO comes back "retry", accept it —
    # never loop a third time.
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_RETRY)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2
    assert out.get("error") is None
    assert out["scenes"]


async def test_stage_failure_surfaces_as_error(monkeypatch):
    _stub_chain(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("Langfuse prompt fetch failed: name='scenario/research'")

    monkeypatch.setattr(sc, "research_step", boom)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out["error"] and "stage=scenario" in out["error"] and "run-123" in out["error"]
    assert "scenes" not in out


async def test_missing_api_key_sets_error(monkeypatch):
    class NoKeySettings(FakeSettings):
        deepseek_api_key = ""

    monkeypatch.setattr(sc, "_settings", lambda: NoKeySettings())
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["error"] and "DEEPSEEK_API_KEY" in out["error"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario.py -v`
Expected: FAIL — `AttributeError: module 'yt_flow.pipeline.nodes.scenario' has no attribute 'research_step'` (not imported yet)

- [ ] **Step 4: Rewrite `scenario.py`**

```python
"""scenario_node — the LLM-Director stage (Story 1.5, multi-stage redesign 2026-07-03).

Runs the 6-stage chain (research -> structure -> writing -> visual_breakdown
xN -> review + critic_agent, bounded to one retry) documented in
docs/superpowers/specs/2026-07-03-scenario-multistage-design.md, and maps the
result onto ``PipelineState.scenes``. Pure function of state: reads a few
fields, returns only the changed ones (``scenes``, ``current_stage``, and
``error`` on failure). No DB / SSE / gate writes and no ``interrupt()`` — gate
behaviour stays in ``gates.py``. [AD-4, AD-3]

DeepSeek is OpenAI-compatible, so we POST to ``/chat/completions`` with the
already-installed ``httpx`` client instead of adding the ``openai`` SDK.
"""

import asyncio
import time

import httpx
from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.scenario_chain import (
    build_scenes,
    critic_step,
    research_step,
    review_step,
    split_sentences,
    structure_step,
    visual_breakdown_step,
    writing_step,
)
from yt_flow.domain.state import PipelineState
from yt_flow.services.prompt_service import get_prompt


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


async def _call_deepseek(rendered: str, s: Settings) -> tuple[str, dict, str | None]:
    """Return (content, usage, finish_reason) from a JSON-mode chat completion."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{s.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
            json={
                "model": s.deepseek_model,
                "messages": [{"role": "user", "content": rendered}],
                "response_format": {"type": "json_object"},
                "max_tokens": s.deepseek_max_tokens,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")


def _record_trace(*, stages: list[dict], total_latency_ms: int, error: Exception | None = None) -> None:
    """Best-effort enrich the current ``scenario`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            input={"stage_count": len(stages)},
            output=None if error is not None else {"stages": [s["name"] for s in stages]},
            metadata={
                "stages": stages,
                "total_latency_ms": total_latency_ms,
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


def _format_feedback(review: dict, critic: dict) -> str:
    lines = [critic.get("feedback", "")]
    for issue in review.get("issues", []):
        lines.append(f"- Scene {issue.get('scene_num')}: {issue.get('description')} -> {issue.get('correction')}")
    return "\n".join(line for line in lines if line)


async def _write_and_review(
    scp_id: str,
    scp_text: str,
    structure: list[dict],
    frozen_descriptor: str,
    format_guide: str,
    quality_feedback: str,
    s: Settings,
    stages: list[dict],
) -> tuple[dict, dict, dict, dict]:
    t0 = time.perf_counter()
    writing = await writing_step(scp_id, structure, frozen_descriptor, format_guide, quality_feedback, s, _call_deepseek)
    stages.append({"name": "writing", "latency_ms": _ms(t0)})

    t0 = time.perf_counter()

    async def _breakdown_for(scene: dict) -> tuple[int, list[dict]]:
        sentences = split_sentences(scene["narration"])
        shots = await visual_breakdown_step(scene, sentences, frozen_descriptor, s, _call_deepseek)
        return scene["scene_num"], shots

    results = await asyncio.gather(*(_breakdown_for(scene) for scene in writing["scenes"]))
    visual_by_scene = dict(results)
    stages.append({"name": "visual_breakdown", "latency_ms": _ms(t0), "scene_count": len(visual_by_scene)})

    t0 = time.perf_counter()
    review = await review_step(scp_text, writing, visual_by_scene, frozen_descriptor, format_guide, s, _call_deepseek)
    stages.append({"name": "review", "latency_ms": _ms(t0)})

    t0 = time.perf_counter()
    critic = await critic_step(writing, visual_by_scene, format_guide, s, _call_deepseek)
    stages.append({"name": "critic_agent", "latency_ms": _ms(t0)})

    return writing, visual_by_scene, review, critic


@observe(name="scenario")
async def scenario_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0_total = time.perf_counter()
    stages: list[dict] = []
    try:
        s = _settings()
        if not s.deepseek_api_key:
            raise RuntimeError("YTFLOW_DEEPSEEK_API_KEY is not configured")

        format_guide = get_prompt("scenario/format_guide").compile()

        t0 = time.perf_counter()
        research = await research_step(state["scp_id"], state["scp_text"], format_guide, s, _call_deepseek)
        stages.append({"name": "research", "latency_ms": _ms(t0)})

        t0 = time.perf_counter()
        structure = await structure_step(state["scp_id"], research, format_guide, s, _call_deepseek)
        stages.append({"name": "structure", "latency_ms": _ms(t0)})

        writing, visual_by_scene, review, critic = await _write_and_review(
            state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
            format_guide, "", s, stages,
        )

        if critic["verdict"] == "retry" or not review["overall_pass"]:
            feedback = _format_feedback(review, critic)
            writing, visual_by_scene, review, critic = await _write_and_review(
                state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
                format_guide, feedback, s, stages,
            )

        scenes = build_scenes(writing, visual_by_scene)
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total))
        return {"scenes": scenes, "current_stage": "scenario"}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total), error=exc)
        return {"current_stage": "scenario", "error": f"stage=scenario run_id={run_id}: {exc}"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario.py tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: all pass (8 in `test_scenario.py` + 20 in `test_scenario_chain.py`)

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest -x -q`
Expected: all pass. If anything outside these two files imports `scenario._parse_scenes`, `scenario._require_text`, etc. (removed in this rewrite), fix that call site — grep first: `grep -rn "_parse_scenes\|_require_text\|_opt_text\|_parse_indices" --include=*.py src tests`.

- [ ] **Step 7: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario.py tests/pipeline/nodes/test_scenario.py
git commit -m "feat: orchestrate scenario_node as bounded-retry multi-stage chain"
```

---

## Task 8: Cleanup stale interim artifacts

**Files:**
- Delete: `prompts/scenario.md`
- Delete: `playwright.live.config.ts`, `server-live.log`, `.playwright-mcp/` (session-local live-testing artifacts, never meant to be committed)

**Interfaces:** none — pure cleanup, no code depends on these files.

- [ ] **Step 1: Remove the superseded single-shot prompt draft**

```bash
cd /mnt/work/projects/yt.flow
rm prompts/scenario.md
git status --short  # confirm it was untracked (never committed) — nothing to `git rm`
```

- [ ] **Step 2: Remove this session's live-testing scratch files**

```bash
cd /mnt/work/projects/yt.flow
rm -f playwright.live.config.ts server-live.log
rm -rf .playwright-mcp
git status --short
```

Expected: clean `git status` (these were all untracked).

- [ ] **Step 3: Confirm the Langfuse `scenario` prompt entry is simply unused, not referenced**

```bash
cd /mnt/work/projects/yt.flow
grep -rn 'get_prompt("scenario"' --include=*.py src tests
```

Expected: no output (nothing calls `get_prompt("scenario")` anymore — everything goes through `scenario/research`, `scenario/structure`, etc.). The orphaned Langfuse Prompt Hub entry named `scenario` is harmless and left in place — the SDK has no delete-by-name call worth scripting for one unused entry.

No commit needed for this task (nothing tracked changed).

---

## Task 9: Fix E2E stub fixtures for the new chain (regression found during Task 7)

Task 7's implementer surfaced a real regression, root-caused in `.superpowers/sdd/task-7-report.md`: `tests/conftest.py`'s `stub_profile` fixture and `tests/stubs/fakes.py` were built for the old single-call `scenario_node` (one `get_prompt("scenario")` call, one `_call_deepseek` call replaying one fixed cassette). The new chain makes `prompt_service.get_prompt(name)` calls (module-qualified, six different names) that `stub_profile` never patches, and needs six *different* per-stage responses from `_call_deepseek`, not one replayed six times. Result: `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` — previously passing — now fails (the scenario stage's every real fetch attempt hits a dead `http://localhost` and errors out, so the run drifts through empty gates with no artifact). This also breaks the Playwright E2E suite's `webServer` stub server (`scripts/run_e2e_stub_server.py` reuses these same fakes), which is what `playwright.config.ts` boots for every `npm run test:e2e` run.

**Files:**
- Modify: `tests/stubs/fakes.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: the 6 existing per-stage cassette fixtures from Tasks 3-5 (`tests/fixtures/cassettes/deepseek_{research,structure,writing,visual_breakdown,review,critic}.json`) — reused as-is, no new cassette content needed (verified: the `writing` cassette's narration splits into exactly 3 sentences via `split_sentences`, matching the `visual_breakdown` cassette's 3 shots).
- Produces: `fake_get_prompt_for_chain(name, *, label=None)`, `deepseek_stage_aware()` in `tests/stubs/fakes.py`; `stub_profile` in `tests/conftest.py` patches `yt_flow.services.prompt_service.get_prompt` (module-qualified — the exact attribute `scenario_chain.py`'s `_call_stage` reads) in addition to what it already patches.

- [ ] **Step 1: Write the failing test**

The existing `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` already covers this — it currently fails. No new test file needed; this fix's own passing of that test IS the verification.

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/api/test_e2e_stub_run.py -v`
Expected (before this task's fix): FAIL — the scenario stage errors out on the first real network fetch attempt.

- [ ] **Step 2: Add the stage-aware fakes**

Append to `tests/stubs/fakes.py`:

```python
# ── scenario_chain multi-stage prompt/DeepSeek fakes (Story 1.5 chain redesign) ─
_STAGE_CASSETTES = {
    "scenario/research": "deepseek_research.json",
    "scenario/structure": "deepseek_structure.json",
    "scenario/writing": "deepseek_writing.json",
    "scenario/visual_breakdown": "deepseek_visual_breakdown.json",
    "scenario/review": "deepseek_review.json",
    "scenario/critic_agent": "deepseek_critic.json",
}


class _FakeChainPrompt:
    """Stands in for a Langfuse prompt object for one scenario_chain stage.

    ``compile()`` returns a marker string embedding the stage name instead of
    real prompt text — paired with ``deepseek_stage_aware()``, which reads the
    marker back out of ``rendered`` to pick the right per-stage cassette. The
    chain never inspects prompt *content* in tests, only structure, so a
    marker is sufficient and avoids needing real prompt text offline.
    """

    def __init__(self, name: str):
        self._name = name

    def compile(self, **variables: object) -> str:
        return f"__STAGE__:{self._name}"


def fake_get_prompt_for_chain(name: str, *, label: str | None = None):
    """Replaces ``yt_flow.services.prompt_service.get_prompt`` for the scenario chain.

    ``scenario/format_guide`` has no variables and is only ever compiled once
    for its static text — the existing zero-arg ``_FakePrompt`` fake covers it.
    Every other name is one of the six chain stages.
    """
    if name == "scenario/format_guide":
        return _FakePrompt()
    return _FakeChainPrompt(name)


def deepseek_stage_aware():
    """Replaces ``scenario._call_deepseek`` for the multi-stage chain.

    Reads the stage marker out of ``rendered`` (see ``_FakeChainPrompt``) and
    replays that stage's real cassette from Tasks 3-5 — one fixed cassette per
    stage, cached after first load. ``visual_breakdown`` is called once per
    scene; the same cassette (3 shots) is replayed for every scene, which is
    fine because the stub-profile run only ever has one scene (see the
    ``deepseek_writing.json`` cassette's single scene).
    """
    cache: dict[str, dict] = {}

    async def fake(rendered: str, s):
        for name, filename in _STAGE_CASSETTES.items():
            if rendered == f"__STAGE__:{name}":
                if filename not in cache:
                    cache[filename] = load_cassette(filename)
                data = cache[filename]
                choice = data["choices"][0]
                return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")
        raise AssertionError(f"deepseek_stage_aware: no cassette mapped for rendered={rendered!r}")

    return fake
```

- [ ] **Step 3: Wire the new fakes into `stub_profile`**

In `tests/conftest.py`, change:

```python
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.comfyui_client as comfyui_client

    monkeypatch.setattr(scenario, "get_prompt", fakes.fake_get_prompt)
    monkeypatch.setattr(scenario, "_call_deepseek", fakes.deepseek_from_cassette())
```

to:

```python
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.comfyui_client as comfyui_client
    import yt_flow.services.prompt_service as prompt_service

    # scenario.py's own one format_guide fetch uses the bare imported name...
    monkeypatch.setattr(scenario, "get_prompt", fakes.fake_get_prompt_for_chain)
    # ...but every scenario_chain.py step fetches via the module-qualified
    # attribute (`from yt_flow.services import prompt_service`), which needs
    # its own patch target.
    monkeypatch.setattr(prompt_service, "get_prompt", fakes.fake_get_prompt_for_chain)
    monkeypatch.setattr(scenario, "_call_deepseek", fakes.deepseek_stage_aware())
```

(Leave `fakes.fake_get_prompt`/`fakes.deepseek_from_cassette` in place — do not delete them. They're still valid, reusable generic fakes; nothing else in the plan asks to remove them, and deleting working code outside this task's stated diff is out of scope.)

- [ ] **Step 4: Run the target test to verify it passes**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/api/test_e2e_stub_run.py -v`
Expected: `test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` PASSED

- [ ] **Step 5: Run the full suite to confirm no new regressions**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest -q`
Expected: the same 3 pre-existing `tests/test_prompt_migration.py` failures noted in Task 7's report (unrelated, pre-existing — confirm via `git stash` if in doubt), zero others. If any test besides those 3 fails, that's a new regression from this task's own change — fix it before reporting done.

- [ ] **Step 6: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add tests/stubs/fakes.py tests/conftest.py
git commit -m "fix: update E2E stub fixtures for the multi-stage scenario chain"
```

---

## Task 10: Fix test_prompt_migration.py regression (found during final verification)

Task 2 correctly emptied `scripts/migrate_prompts.py`'s `ALIASES` dict (the old `"scenario"`/`"image_prompt"` entries pointed at the wrong source files for this design — see Task 2). But `tests/test_prompt_migration.py` has 3 tests that assert on those specific production alias values existing, so they now fail — confirmed via `git stash`/checkout against the pre-Task-2 commit (57ecad5) that these 3 tests passed before Task 2's `ALIASES` change and only started failing after it. This was missed because no task's review ran the full suite until after Task 9; it is a real regression from Task 2, not pre-existing project debt.

The alias *mechanism* in `build_manifest` (`scripts/migrate_prompts.py` lines 85-93: raise if an alias's backing source file is missing, raise if a discovered name collides with a reserved alias name) is untouched and still fully functional — it's just that production no longer populates `ALIASES` with any entries. The tests should exercise that mechanism generically, via a monkeypatched local `ALIASES`, instead of depending on now-removed production values.

**Files:**
- Modify: `tests/test_prompt_migration.py`

**Interfaces:** none new — this only changes test bodies, not any function signature.

- [ ] **Step 1: Confirm the current failure**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/test_prompt_migration.py -v`
Expected: 3 failures — `test_build_manifest_maps_known_names_and_derives_unknown`, `test_build_manifest_fails_when_alias_source_missing`, `test_build_manifest_fails_on_reserved_alias_collision`. 12 others pass.

- [ ] **Step 2: Rewrite the 3 failing tests to monkeypatch a local alias**

Replace these three test functions in `tests/test_prompt_migration.py`:

```python
def test_build_manifest_maps_known_names_and_derives_unknown(tmp_path):
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "misc/extra_stage.md", "extra {y}")
    manifest = mp.build_manifest(tmp_path)
    # mapped name from SOURCE_TO_NAME
    assert manifest["scenario/research"] == "research {{scp_text}}"
    # derived name for a file not in the map
    assert manifest["misc/extra_stage"] == "extra {{y}}"
    # required runtime aliases exist and are compiled from their backing source
    assert "scenario" in manifest and "{{scp_text}}" in manifest["scenario"]
    assert "image_prompt" in manifest and "{{shot}}" in manifest["image_prompt"]


def test_build_manifest_fails_when_no_prompts(tmp_path):
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_when_alias_source_missing(tmp_path):
    # only a non-alias file present -> alias backing source is absent
    _write(tmp_path, "misc/only.md", "x {a}")
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_on_reserved_alias_collision(tmp_path):
    # a discovered file deriving to a reserved alias name must not silently overwrite it
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "scenario.md", "colliding top-level file")  # derives to name "scenario"
    with pytest.raises(SystemExit, match="collides"):
        mp.build_manifest(tmp_path)
```

with (note `monkeypatch` added as a parameter to each — pytest auto-injects it):

```python
def test_build_manifest_maps_known_names_and_derives_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "misc/extra_stage.md", "extra {y}")
    manifest = mp.build_manifest(tmp_path)
    # mapped name from SOURCE_TO_NAME
    assert manifest["scenario/research"] == "research {{scp_text}}"
    # derived name for a file not in the map
    assert manifest["misc/extra_stage"] == "extra {{y}}"
    # an alias exists and is compiled from its backing source (mechanism test,
    # not tied to any specific production alias — production has none, see
    # docs/superpowers/specs/2026-07-03-scenario-multistage-design.md)
    assert "my_alias" in manifest and "{{scp_text}}" in manifest["my_alias"]


def test_build_manifest_fails_when_no_prompts(tmp_path):
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_when_alias_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    # only a non-alias file present -> alias backing source is absent
    _write(tmp_path, "misc/only.md", "x {a}")
    with pytest.raises(SystemExit):
        mp.build_manifest(tmp_path)


def test_build_manifest_fails_on_reserved_alias_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "ALIASES", {"my_alias": "scenario/01_research.md"})
    # a discovered file deriving to a reserved alias name must not silently overwrite it
    _write(tmp_path, "scenario/01_research.md", "research {scp_text}")
    _write(tmp_path, "image/02_shot_to_prompt.md", "shot {shot}")
    _write(tmp_path, "my_alias.md", "colliding top-level file")  # derives to name "my_alias"
    with pytest.raises(SystemExit, match="collides"):
        mp.build_manifest(tmp_path)
```

- [ ] **Step 3: Run the file's tests to verify they pass**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/test_prompt_migration.py -v`
Expected: 15 passed

- [ ] **Step 4: Run the full suite to confirm the only remaining failures are none**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest -q`
Expected: `X passed, 1 skipped` — zero failures.

- [ ] **Step 5: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add tests/test_prompt_migration.py
git commit -m "fix: decouple migrate_prompts alias tests from production ALIASES content"
```

---

## Task 11: Fix duplicate scene_num silently corrupting shot assignment (found during final review)

The final whole-branch review found a real, confirmed data-corruption bug. `scenario.py`'s `_write_and_review` builds `visual_by_scene = dict(results)` keyed by **the writing stage's own LLM-assigned `scene["scene_num"]`** (`scenario.py:106`: `return scene["scene_num"], shots`), and `build_scenes` looks shots up by that same LLM-assigned key (`scenario_chain.py:226`: `visual_by_scene[writing_scene["scene_num"]]`). If the writing stage (especially on the retry pass, where `quality_feedback` perturbs its output) emits two scenes with the same `scene_num`, `dict(results)` silently collapses them: **both output scenes end up sharing the second scene's shots, and the first scene's real visuals vanish with no error raised.** This directly contradicts the spec's own "duplicate LLM scene_num" edge case and `build_scenes`'s own established convention of assigning `scene_num` **positionally** (`scenario_chain.py`'s `build_scenes` already does `scene_num = idx + 1`, ignoring the LLM's value for the *output* — the fix makes the internal *lookup* equally positional, closing the gap between the two).

Task 6's existing `test_build_scenes_scene_num_is_positional` gives false confidence here: it hand-builds `visual_by_scene` with distinct keys (`{1: [...], 2: [...]}`) and only asserts the positional *output* `scene_num` — it never exercises the actual `dict(results)`-collapse path from `scenario.py`, and never checks which shots land on which scene.

**Files:**
- Modify: `src/yt_flow/pipeline/nodes/scenario.py`
- Modify: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- Modify: `tests/pipeline/nodes/test_scenario.py`

**Interfaces:**
- `_write_and_review`'s internal `_breakdown_for` helper and its `visual_by_scene` dict now key by the **positional 0-based index** of the scene in `writing["scenes"]`, not the LLM's `scene["scene_num"]`.
- `build_scenes(writing, visual_by_scene)`'s signature is unchanged, but its internal lookup switches from `visual_by_scene[writing_scene["scene_num"]]` to `visual_by_scene[idx]` (the same positional `idx` the function already uses for output numbering).
- `review_step`/`critic_step` signatures are unchanged — they only serialize `visual_by_scene` as opaque JSON context for another LLM call; switching its keys from scene_num ints to positional-index ints has no effect on their behavior or contract.

- [ ] **Step 1: Write the failing test**

Add to `tests/pipeline/nodes/test_scenario.py` (uses the same `_stub_chain` helper and fixtures already in that file — see Task 7's test file for `WRITING`, `VISUAL`, etc.):

```python
async def test_duplicate_llm_scene_num_does_not_corrupt_shots(monkeypatch):
    # Writing stage emits TWO scenes, both claiming scene_num=1 (a real, if
    # rare, LLM misbehavior) — each scene's visual_breakdown must still keep
    # its own distinct shots; nothing may silently collapse or drop.
    writing_two_scenes = {
        "scp_id": "SCP-173",
        "title": "t",
        "scenes": [
            {"scene_num": 1, "narration": "첫 씬 문장.", "location": "a", "characters_present": [], "color_palette": "a", "atmosphere": "a"},
            {"scene_num": 1, "narration": "둘째 씬 문장.", "location": "b", "characters_present": [], "color_palette": "b", "atmosphere": "b"},
        ],
    }

    call_count = {"n": 0}

    async def fake_research(*a, **k):
        return RESEARCH

    async def fake_structure(*a, **k):
        return STRUCTURE

    async def fake_writing(*a, **k):
        return writing_two_scenes

    async def fake_visual(scene, sentences, *a, **k):
        # Distinguish the two scenes by their own narration/location so the
        # test can prove which shot ended up where.
        call_count["n"] += 1
        tag = scene["location"]
        return [{"image_prompt": f"shot-for-{tag}", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]

    async def fake_review(*a, **k):
        return REVIEW_PASS

    async def fake_critic(*a, **k):
        return CRITIC_PASS

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)

    out = await sc.scenario_node(_state())

    assert call_count["n"] == 2  # both scenes' visual_breakdown actually ran
    assert out.get("error") is None
    scenes = out["scenes"]
    assert len(scenes) == 2
    # Each output scene must carry ITS OWN shot, not both collapsing onto one.
    assert scenes[0]["shots"][0]["image_prompt"] == "shot-for-a"
    assert scenes[1]["shots"][0]["image_prompt"] == "shot-for-b"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario.py::test_duplicate_llm_scene_num_does_not_corrupt_shots -v`
Expected: FAIL — `scenes[0]["shots"][0]["image_prompt"] == "shot-for-b"` (both scenes get the second scene's shot; `assert ... == "shot-for-a"` fails).

- [ ] **Step 3: Fix `_write_and_review` to key positionally**

In `src/yt_flow/pipeline/nodes/scenario.py`, replace:

```python
    async def _breakdown_for(scene: dict) -> tuple[int, list[dict]]:
        sentences = split_sentences(scene["narration"])
        shots = await visual_breakdown_step(scene, sentences, frozen_descriptor, s, _call_deepseek)
        return scene["scene_num"], shots

    results = await asyncio.gather(*(_breakdown_for(scene) for scene in writing["scenes"]))
    visual_by_scene = dict(results)
```

with:

```python
    async def _breakdown_for(idx: int, scene: dict) -> tuple[int, list[dict]]:
        sentences = split_sentences(scene["narration"])
        shots = await visual_breakdown_step(scene, sentences, frozen_descriptor, s, _call_deepseek)
        return idx, shots  # positional key — never trust the LLM's own scene_num for lookups

    results = await asyncio.gather(*(_breakdown_for(idx, scene) for idx, scene in enumerate(writing["scenes"])))
    visual_by_scene = dict(results)
```

- [ ] **Step 4: Fix `build_scenes`'s lookup to match**

In `src/yt_flow/pipeline/nodes/scenario_chain.py`, inside `build_scenes`, replace:

```python
        raw_shots = visual_by_scene[writing_scene["scene_num"]]
```

with:

```python
        raw_shots = visual_by_scene[idx]  # positional — matches _write_and_review's keying
```

(`idx` is already in scope — `build_scenes`'s loop is `for idx, writing_scene in enumerate(writing["scenes"]):`.)

- [ ] **Step 5: Update the 4 existing `build_scenes` tests in `test_scenario_chain.py` that assumed scene_num-keyed `visual_by_scene`**

`build_scenes` is called directly (not through `scenario_node`) by 4 tests in `tests/pipeline/nodes/test_scenario_chain.py`, all hand-rolling a `visual_by_scene` dict keyed by the writing stage's `scene_num` (`1`, or `1`/`2`). After Step 4's fix, `build_scenes` looks shots up by positional 0-based `idx` instead — every one of these 4 dicts must be re-keyed from 1-based `scene_num` to 0-based position, or the test will `KeyError`. Make these exact changes:

1. `test_build_scenes_merges_empty_prompt_into_previous_shot` — one scene, dict currently starts `visual_by_scene = {\n    1: [`. Change the key `1` to `0`.
2. `test_build_scenes_first_sentence_empty_falls_back_to_scene_context` — one scene, dict currently starts `visual_by_scene = {\n    1: [`. Change the key `1` to `0`.
3. `test_build_scenes_single_empty_shot_falls_back_not_raises` — one scene, currently `visual_by_scene = {1: [{...}]}`. Change to `visual_by_scene = {0: [{...}]}`.
4. `test_build_scenes_scene_num_is_positional` — two scenes (both LLM-tagged `scene_num=1`, the exact duplicate-scene_num case this task fixes), currently:
   ```python
   visual_by_scene = {
       1: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}],
   }
   # Reuse the same visual breakdown for both (test only cares about positional numbering).
   visual_by_scene_full = {1: visual_by_scene[1], 2: visual_by_scene[1]}
   scenes = chain.build_scenes(writing, visual_by_scene_full)
   assert [s["scene_num"] for s in scenes] == [1, 2]
   ```
   Change to positional keys `0`/`1` (this test can now drop its old comment about not exercising the real collapse path, since Step 1's new orchestration-level test now covers that; this test still independently verifies `build_scenes`'s own positional *output* numbering):
   ```python
   visual_by_scene = {
       0: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}],
   }
   visual_by_scene_full = {0: visual_by_scene[0], 1: visual_by_scene[0]}
   scenes = chain.build_scenes(writing, visual_by_scene_full)
   assert [s["scene_num"] for s in scenes] == [1, 2]
   ```

Do not change the two `review_step`/`critic_step` tests that pass `{1: []}` (`test_review_step_returns_report`, `test_critic_step_returns_verdict`) — those functions treat `visual_by_scene` as opaque JSON context for another LLM call, never index into it, so any key value works and `{1: []}` stays valid.

- [ ] **Step 6: Run the target test and the full suite to verify everything passes**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest tests/pipeline/nodes/test_scenario.py tests/pipeline/nodes/test_scenario_chain.py -v`
Expected: all pass, including the new `test_duplicate_llm_scene_num_does_not_corrupt_shots`.

Run: `cd /mnt/work/projects/yt.flow && uv run pytest -q`
Expected: `484 passed, 1 skipped` (or one more than the current total, counting the new test) — zero failures.

- [ ] **Step 7: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add src/yt_flow/pipeline/nodes/scenario.py src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/pipeline/nodes/test_scenario_chain.py
git commit -m "fix: key visual_by_scene positionally, not by the LLM's own scene_num"
```

---

## Task 12: Fix run_e2e_stub_server.py for the new chain (found during final go/no-go review)

Task 9 fixed `tests/conftest.py`'s `stub_profile` fixture for the new 6-stage chain but Task 9's own report claimed (incorrectly) that this covered `scripts/run_e2e_stub_server.py` too, since its docstring says it "applies the exact same monkeypatch... as plain attribute assignment." It does not — it independently sets `scenario.get_prompt = fakes.fake_get_prompt` and `scenario._call_deepseek = fakes.deepseek_from_cassette()` (old single-call fakes), never patches `prompt_service.get_prompt` (module-qualified, what `scenario_chain.py`'s `_call_stage` actually reads), and replays the old `deepseek_scenario.json` cassette (no `frozen_descriptor`) for every stage. This script is what `playwright.config.ts`'s `webServer` boots for `npm run test:e2e` — any Playwright journey that drives a run past the scenario gate fails immediately with `research_step` raising on the missing `frozen_descriptor`.

**Files:**
- Modify: `scripts/run_e2e_stub_server.py`

**Interfaces:** none new — reuses `fakes.fake_get_prompt_for_chain` and `fakes.deepseek_stage_aware()`, both already added by Task 9.

- [ ] **Step 1: Confirm the current break**

Run: `cd /mnt/work/projects/yt.flow && uv run python scripts/run_e2e_stub_server.py --port 8099 &` then `sleep 2 && curl -s -X POST http://127.0.0.1:8099/runs -H "content-type: application/json" -d '{"scp_id": "SCP-096"}'` then check the run's status — it will show `status: "awaiting_approval"` with an empty/no artifact (the scenario stage errored out silently, same symptom as the Task 9 bug). Kill the background server afterward (`kill %1` or find its PID).

- [ ] **Step 2: Apply the same fix Task 9 already made to `tests/conftest.py`**

In `scripts/run_e2e_stub_server.py`, replace:

```python
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.character_service as character_service
    import yt_flow.services.comfyui_client as comfyui_client
    import yt_flow.services.image_search as image_search

    scenario.get_prompt = fakes.fake_get_prompt
    scenario._call_deepseek = fakes.deepseek_from_cassette()
```

with:

```python
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.character_service as character_service
    import yt_flow.services.comfyui_client as comfyui_client
    import yt_flow.services.image_search as image_search
    import yt_flow.services.prompt_service as prompt_service

    # scenario.py's own one format_guide fetch uses the bare imported name;
    # every scenario_chain.py step fetches via the module-qualified attribute
    # (`from yt_flow.services import prompt_service`) — same two-target patch
    # as tests/conftest.py's stub_profile fixture (Task 9), applied here as
    # plain attribute assignment since this runs as a standalone process, not
    # under pytest/monkeypatch.
    scenario.get_prompt = fakes.fake_get_prompt_for_chain
    prompt_service.get_prompt = fakes.fake_get_prompt_for_chain
    scenario._call_deepseek = fakes.deepseek_stage_aware()
```

- [ ] **Step 3: Re-run the same manual check from Step 1 to verify the fix**

Run: `cd /mnt/work/projects/yt.flow && uv run python scripts/run_e2e_stub_server.py --port 8099 &` then `sleep 2 && curl -s -X POST http://127.0.0.1:8099/runs -H "content-type: application/json" -d '{"scp_id": "SCP-096"}'`, capture the returned run id, then `curl -s http://127.0.0.1:8099/runs/<id>/stages/scenario/artifacts` — expect real scenario content (non-404, contains narration/shots), not the "Stage not reached" or a silent error. Kill the background server afterward.

- [ ] **Step 4: Run the Playwright E2E suite to confirm end-to-end**

Run: `cd /mnt/work/projects/yt.flow && npx playwright test --project=chromium e2e/dashboard-run-gate-artifacts.spec.ts 2>&1 | tail -30` (this spec drives a full run through all 5 gates via the stub server this task fixes).
Expected: the scenario stage's artifact panel populates and the gate can be approved — if this spec still fails for a reason unrelated to the scenario stage (e.g. pre-existing flakiness noted elsewhere in this session), that's fine; the acceptance bar for this task is that it no longer fails AT the scenario stage.

- [ ] **Step 5: Run the full pytest suite to confirm no regression**

Run: `cd /mnt/work/projects/yt.flow && uv run pytest -q`
Expected: `485 passed, 1 skipped` — this script isn't imported by pytest, so this is a sanity check that nothing else was disturbed.

- [ ] **Step 6: Commit**

```bash
cd /mnt/work/projects/yt.flow
git add scripts/run_e2e_stub_server.py
git commit -m "fix: update Playwright E2E stub server for the multi-stage scenario chain"
```

---

## Self-Review

**Spec coverage:**
- Chain order + stage contracts → Tasks 3-5. ✅
- Research JSON-contract deviation, structure object-wrap deviation → Task 2. ✅
- Bounded 1-retry with `quality_feedback` → Task 7 (`_write_and_review` called at most twice). ✅
- Sentence splitting → Task 1. ✅
- Empty-`image_prompt` merge + fallback → Task 6. ✅
- Error handling (no silent swallowing inside the chain) → every `*_step` raises on contract violation; Task 7's `scenario_node` catches once at the top, matching the original contract. ✅
- Cost/latency tradeoff (accepted, no code change needed) → `asyncio.gather` in Task 7 at least parallelizes the N `visual_breakdown` calls, cutting wall-clock versus a naive sequential loop. ✅
- Out-of-scope items (StageName expansion, image/shot_breakdown+shot_to_prompt, real character_visual_context, the separate error-swallowing-in-run_service bug) → untouched by this plan, as specified. ✅
- Testing section (retry-triggered vs not, transition-sentence merge) → Task 7's `test_retries_once_when_critic_says_retry`/`test_no_retry_when_critic_passes`, Task 6's `test_build_scenes_merges_empty_prompt_into_previous_shot`. ✅

**Type/signature consistency check:** `_call_stage`/`research_step`/.../`critic_step` all take `(..., s, call_deepseek)` as their last two positional params, consistently, across Tasks 3-5 and Task 7's usage. `build_scenes(writing, visual_by_scene)` signature matches its Task 6 definition and Task 7's call site. `split_sentences` used identically in Task 7 as defined in Task 1.

**Known gap flagged, not silently dropped:** the live-testing session also found that a stage error currently doesn't surface through `GET /runs/{id}` (`error` stayed `null`). This plan does not fix that — it's in `run_service.py`/`gates.py`, outside `scenario_node`'s contract, and was explicitly deferred as a separate follow-up in the spec's "Out of scope" section.

---

Plan complete and saved to `docs/superpowers/plans/2026-07-03-scenario-multistage-chain.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
