---
created: 2026-07-07
story_key: 8-7-composite-harmonization
story_id: "8.7"
epic: 8
previous_story: 8-6-asset-library-management
depends_on:
  - 8-6-asset-library-management   # AssetService + manifest.json + assets/ layout; IC-Light caching writes into this
  - 8-3-bg-only-generation-multicard-compositing  # multicard overlay pipeline; this story harmonizes what 8.3 composes
blocks: []
related:
  - 7-2-post-fx-color-grade        # Tier 1 reorders: grade must run AFTER composite, not before — current code already does this for character shots, verify + enforce
  - 5-6-character-cutout-quality   # InSPyReNet cutouts are the RGBA input; edge quality determines how much harmonization is needed
entry_gate: "iteration 1 (8-3 DoD A/B) 실측에서 콜라주 룩 확인 시 착수 — 확인 전에는 backlog 상태 유지"
---

# Story 8.7: Composite Harmonization — Collage Look Resolution Ladder

Status: ready-for-dev

## Story

As Jay,
I want the multi-card composite output to read as a coherent scene — not a collage of disconnected sprites pasted onto a background — by applying a tiered harmonization ladder (ffmpeg mood tint + contact shadow → light wrap → IC-Light re-lighting with pre-computed caching),
so that each tier incrementally resolves the visual disconnect between character cards and background plates, and the pipeline stops at the first tier that produces acceptable results in A/B comparison.

## Context

**Context: Jay 지시(2026-07-07), deferred-work #1 (콜라주 룩 리스크).** Epic 8의 멀티카드 합성 아키텍처(8-3)는 배경+캐릭터 카드를 별도 생성 후 ffmpeg overlay로 합성한다. 이 접근의 구조적 리스크는 **콜라주 룩** — 배경과 캐릭터의 조명 방향·색온도·톤이 불일치해 "오려붙인 종이인형"처럼 읽히는 현상. 이 스토리는 업계 표준 2D 합성 기법을 비용 순 사다리로 적용하고, 각 티어의 기여를 A/B로 측정, 충분해지면 상위 티어를 중단(YAGNI)한다.

**착수 게이트(Jay, 2026-07-07):** iteration 1(8-3 DoD A/B)에서 콜라주 룩이 실측으로 확인되어야 이 스토리에 착수한다. 실측되지 않으면 이 스토리는 backlog 상태로 유지 — 없는 문제를 풀지 않는다(YAGNI).

**사다리 설계:**
- **Tier 1 (ffmpeg, 저비용):** mood별 스프라이트 틴트(gradient tint — 게임 2D 라이팅 관행) + 컨택트 섀도(카드 발밑 타원 그림자 — 접지감) + 합성 **후** 그레이드·그레인 적용(현재 코드는 이미 character_path 경로에서 composite→post_fx 순서, 검증 후 강제)
- **Tier 2 (ffmpeg, 중간비용):** 라이트 랩 — 배경색이 스프라이트 가장자리로 번지는 VFX 표준 기법. ffmpeg edgedetect+boxblur로 근사 구현 가능
- **Tier 3 (AI, ComfyUI):** IC-Light 배경 조건 리라이팅 — 카드를 플레이트 광원에 맞춰 재조명. 핵심 최적화: STOCK 카드 × STOCK 플레이트 조합은 유한하므로 (card_key, location_key) 쌍으로 사전 계산해 8-6 라이브러리에 PNG 캐싱 → 런타임 비용 0

**참고 기술:** IC-Light ComfyUI 노드 (https://github.com/lllyasviel/IC-Light), DreamLight, harmonization diffusion 계열.

## Interfaces (Epic 8 contract — Consumes and extends)

### Consumes (8-3, 8-6)

- `video_node._compose_scene`의 character overlay chain: `[bg][char]overlay[ov];[ov]post_fx+subtitles[out]` — 이 파이프라인에 Tier 1~2 필터를 삽입한다.
- `AssetService` (8-6): `get_asset(key)`, `add_asset(key, path, source, **meta)`, `style_epoch` — Tier 3 리라이팅 결과물 캐싱에 사용.
- `CharacterCard` / `LocationPlate` 모델 (8-2/8-6): `card_key`와 `location_key`가 Tier 3 캐시 키의 축.

### Extends

- `video.py`: `_compose_scene` + `_compose_chapter_card` 필터 체인 확장
- `config.py`: 티어별 feature flag 추가
- 신규: `composite_harmonization.py` — tint/contact-shadow/light-wrap 순수 함수 + IC-Light ComfyUI 클라이언트 래퍼
- 신규: `data/workflows/comfyui_iclight_relight_api.json` — IC-Light 워크플로우

### Config additions

```python
# config.py — Tiered harmonization flags. Each tier gates the one below:
# tier_1 alone, tier_1+tier_2, or all three. Default: tier_1 only (lowest cost,
# largest impact-to-cost ratio). tier_2 / tier_3 default OFF until A/B justifies.
composite_harmonization_tier: int = 1   # 1 | 2 | 3 — upper bound; 0 = off
iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"
```

## Acceptance Criteria

### Tier 1 — ffmpeg Mood Tint + Contact Shadow + Composite-Then-Grade

1. **Mood-driven sprite tint.** Given `build_sprite_tint(mood: str) -> str` (신규 `composite_harmonization.py`), then it returns an ffmpeg `colorbalance` or `eq` filter string that shifts the character sprite toward the mood's canonical color temperature: dread=desaturated cool blue tint, clinical=neutral-cool slight desaturation, escalation=warm slight saturation boost, revelation=high-contrast neutral. The tint is applied to the `[char]` stream BEFORE the overlay, not to the background. Mood taxonomy reuses `sound_design.MOOD_VALUES` — no new mood vocabulary.

2. **Contact shadow.** Given `build_contact_shadow(cast_member: CastMember) -> str` (신규), then it returns an ffmpeg filter fragment that renders a soft elliptical shadow at the character's foot position: a `geq` or `drawbox`-based dark ellipse at the bottom center of the character's bounding box, blended under the character via an intermediate overlay. The shadow ellipse scales with the character's `depth` plane: near=larger/softer, far=smaller/sharper. `scale` parameter ranges 0.6-1.0 normalized to CHAR_MAX_W.

3. **Composite-then-grade enforcement.** Given `_compose_scene`'s current filter chain `[bg][char]overlay[ov];[ov]post_fx+subtitles[out]`, then this ordering is already correct (grade after composite) — the story validates this with a regression test asserting that `post_frag` appears AFTER the `overlay` label in the filter_complex string, not before. For the background-only path (`[0:v]zp_chain+post_frag+subtitles`), no change needed — there's no composite to grade over. For `_compose_chapter_card`, the grade-before-drawtext order is already correct (text should not be grained) — validate, don't change.

4. **Tier 1 toggle.** Given `Settings.composite_harmonization_tier >= 1`, then `_compose_scene` applies mood tint + contact shadow + composite-then-grade ordering. Given `tier == 0`, then today's byte-for-byte output is preserved (no harmonization). A/B comparison must confirm Tier 1 alone reduces the collage look perceptibly.

### Tier 2 — Light Wrap

5. **Light wrap filter.** Given `build_light_wrap(mood: str, blur_radius: int = 8, intensity: float = 0.15) -> str` (신규), then it returns a filter chain that: (a) extracts the character alpha as a mask, (b) edge-detects + box-blurs the background at the mask boundary, (c) blends the blurred background edge "bleed" onto the character's perimeter. This is the standard VFX light-wrap technique — background color spills into the sprite edge, simulating subsurface scattering / rim light integration. ffmpeg-only: `edgedetect` → `boxblur` → `alphamerge` → `overlay` with the original character. The `blur_radius` and `intensity` are config constants, not per-shot parameters — tune once, apply uniformly. ponytail: do not add per-shot params until a shot actually needs different values.

6. **Light wrap in the filter chain.** Given `composite_harmonization_tier >= 2`, then the character branch of `_compose_scene` inserts light wrap between the tint step and the overlay:
   ```
   [1:v]sprite_tint[tinted];
   [tinted]light_wrap[char];
   [bg][char]overlay+shadow[ov];
   [ov]post_fx+subtitles[out]
   ```
   The background-only path and chapter card path are unaffected (no character to wrap).

### Tier 3 — IC-Light Re-lighting with Pre-computed Caching

7. **IC-Light ComfyUI workflow.** A new `data/workflows/comfyui_iclight_relight_api.json` workflow accepts: `card_image` (character sprite PNG), `background_image` (location plate), `card_mask` (alpha channel extracted or passed separately). The workflow outputs a re-lit character sprite PNG at the same resolution. The ComfyUI prompt is minimal — IC-Light is a conditioning model, not a text-to-image model; the "prompt" field carries a short scene descriptor for the lighting direction hint (e.g., "warm key light from top-right matching the background").

8. **Pre-computed caching.** Given `RelightCache` (신규, `composite_harmonization.py`), then `get_or_compute(card_key: str, location_key: str, style_epoch: int) -> Path | None` checks `assets/relit/{card_key}/{location_key}/epoch_{style_epoch}.png`: if it exists and `AssetService.verify_asset()` passes, return the path (cache hit). If it doesn't exist, return `None` (cold miss — caller triggers ComfyUI generation). After generation, `store(card_key, location_key, image_bytes)` writes to the path + calls `AssetService.add_asset()` with `source.type: "iclight_relight"` + `source.card_key` + `source.location_key`.

9. **Batch pre-computation.** Given a run's cast list (from `ShotData.cast`), `precompute_relights(scenes: list[SceneState], asset_service: AssetService) -> dict[tuple[str, str], Path]` (신규) identifies all unique `(card_key, location_key)` pairs where both the card and the location plate are STOCK assets (both keys resolve in `AssetService`), computes cold misses via ComfyUI, and returns a lookup dict mapping `(card_key, location_key) -> relit_path`. Non-STOCK cards (entity-specific, e.g. SCP-049) are excluded from pre-computation — their relighting is deferred to runtime (Tier 3 runtime path, YAGNI until proven needed). Non-STOCK backgrounds (free-text generated) are also excluded — IC-Light needs a reference plate, not a prompt.

10. **Tier 3 toggle + runtime substitution.** Given `composite_harmonization_tier >= 3`, then `video_node` calls `precompute_relights` before the scene composition loop, and `_compose_scene` receives a `relit_map: dict[tuple[str, str], Path] | None` parameter. For each `CastMember` in a shot, if `(card_key, location_key)` is in the map, use the re-lit sprite instead of the original `character_path`. The original sprite remains in the library — relighting is a derived asset, not a mutation.

11. **IC-Light is non-fatal.** Given IC-Light ComfyUI call fails (timeout, OOM, model missing), then `precompute_relights` logs a warning and returns the cold-miss pairs absent from the map — the pipeline continues with un-relit sprites. No run ever fails due to IC-Light unavailability. This follows the `_ensure_character_reference` non-fatal pattern (5-8/5-10). Langfuse span records `relit_pairs_computed` and `relit_pairs_failed` counts.

### Cross-Tier

12. **A/B measurement ladder.** Each tier is independently measurable: Tier 1 produces output A, Tier 1+2 produces output B, all three produce output C. The Epic 4 A/B evaluation framework is reused — a single SCP run with `prompt_variant="A"` at tier=N and `prompt_variant="B"` at tier=N+1 quantifies the incremental improvement. The YAGNI gate: if tier N's A/B score delta versus tier N-1 is below a human-judged significance threshold (Jay reviews the side-by-side), the next tier is not implemented. This is a process rule, not code — documented in the story, not enforced by the pipeline.

13. **Regression safety.** Given `composite_harmonization_tier == 0` (default off for safety until iteration 1 gate), then ALL existing tests pass with byte-for-byte identical output. The filter chain is gated behind the tier flag — no code path change when tier=0. The new `composite_harmonization.py` module is imported only when tier >= 1; when tier=0, `video.py` does not import it at all (lazy import behind the tier check, ponytail: don't import what you don't use).

14. **Multi-character shots.** Given a shot with N `CastMember` entries, then each character sprite receives its own tint + contact shadow + light wrap + relighting independently. The per-character filter chains run in sequence before a single multi-input overlay step (one overlay per character, bottom-to-top by z-order from `CastMember.depth`: far→near→mid using `overlay` with per-layer positioning from `position`). This is an 8-3 concern — this story only ensures the harmonization filters work correctly when 8-3 passes N character inputs.

## Technical Requirements

### New module: `src/yt_flow/pipeline/nodes/composite_harmonization.py`

```python
"""Composite harmonization — ffmpeg filter builders for collage-look resolution.

Pure functions returning ffmpeg filter strings. No I/O, no ComfyUI — this
module is import-safe even when tier=0 (lazy-imported behind the tier check).

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

from yt_flow.domain.state import CastMember, CastDepth
from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES, resolve_mood

# ── Mood tint parameters ────────────────────────────────────────────────────
# colorbalance: rs/gs/bs = red/green/blue shadow, rh/gh/bh = highlight.
# Negative = cool shift, positive = warm shift.
MOOD_TINT_PARAMS: dict[str, dict[str, float]] = {
    "dread":      {"rs": -0.12, "gs": -0.06, "bs": 0.12, "rh": -0.08, "gh": -0.04, "bh": 0.10},
    "clinical":   {"rs": -0.05, "gs": 0.00, "bs": 0.05, "rh": -0.03, "gh": -0.01, "bh": 0.04},
    "escalation": {"rs": 0.10,  "gs": 0.04, "bs": -0.06, "rh": 0.08,  "gh": 0.03,  "bh": -0.04},
    "revelation": {"rs": 0.15,  "gs": 0.05, "bs": -0.02, "rh": 0.12,  "gh": 0.04,  "bh": 0.00},
}
# Enforce lockstep with MOOD_VALUES so a taxonomy change doesn't silently
# produce the wrong tint.
assert set(MOOD_TINT_PARAMS) == set(MOOD_VALUES)


def build_sprite_tint(mood: str | None) -> str:
    """Return ffmpeg colorbalance filter for mood-driven character tint."""
    p = MOOD_TINT_PARAMS[resolve_mood(mood)]
    return (
        f"colorbalance=rs={p['rs']}:gs={p['gs']}:bs={p['bs']}:"
        f"rh={p['rh']}:gh={p['gh']}:bh={p['bh']}"
    )


def build_contact_shadow(cast_member: CastMember) -> str:
    """Return ffmpeg filter fragment for a soft contact shadow under one character.

    Renders as a dark ellipse (geq) under the character, sized by depth plane.
    The caller composites this shadow layer between bg and char in the overlay stack.
    """
    # Depth → shadow scale: near=large/soft, far=small/crisp
    depth_scales: dict[CastDepth, float] = {"near": 0.9, "mid": 0.7, "far": 0.5}
    scale = depth_scales.get(cast_member.get("depth", "mid"), 0.7)
    # Build a geq filter that draws a dark semi-transparent ellipse
    # at the bottom center of the frame, shifted per position.
    pos_h_offsets = {"left": -0.15, "center": 0.0, "right": 0.15}
    h_offset = pos_h_offsets.get(cast_member.get("position", "center"), 0.0)
    return (
        f"geq=r=0:g=0:b=0:a='if("
        f"((X/W-0.5-{h_offset})*(X/W-0.5-{h_offset})/({0.08*scale:.3f}*{0.08*scale:.3f})"
        f"+(Y/H-0.85)*(Y/H-0.85)/({0.03*scale:.3f}*{0.03*scale:.3f}))<1,64,0)'"
        ":eval=frame"
    )


def build_light_wrap(blur_radius: int = 8, intensity: float = 0.15) -> str:
    """Return ffmpeg filter chain for light-wrap edge blending.

    Extracts alpha mask from character → edge-detects background at mask boundary
    → box-blurs the bleed → blends back onto character perimeter.
    """
    return (
        f"[1:v]alphaextract[char_mask];"
        f"[0:v]crop=iw:ih:0:0,edgedetect=low=0.1:high=0.3,"
        f"boxblur={blur_radius}:1[bg_edge];"
        f"[bg_edge][char_mask]alphamerge[wrap];"
        f"[1:v][wrap]overlay=0:0:"
        f"format=auto:alpha=1,"
        f"colorchannelmixer=aa={intensity}[char]"
    )
```

**Note:** The `build_light_wrap` filter chain above is a structural sketch. The exact ffmpeg filter syntax for light wrap is non-trivial — the chain may need adjustment during implementation. The acceptance criterion is visual correctness (A/B comparison confirms edge blending reduces the cutout look), not filter syntax purity.

### Modified: `src/yt_flow/pipeline/nodes/video.py`

In `_compose_scene`, when `composite_harmonization_tier >= 1`:

```python
# After: char_chain = _character_scale_filter() (or _character_zoom_filter for parallax)
# Before: overlay = _overlay_filter(...)
# Insert:

if composite_harmonization_tier >= 1:
    from yt_flow.pipeline.nodes.composite_harmonization import build_sprite_tint, build_contact_shadow
    tint = build_sprite_tint(mood)
    # Apply tint to the character sprite before overlay
    char_chain = f"{char_chain},{tint}"
    # Contact shadow: render as an intermediate layer between bg and char
    # (requires restructuring the overlay stack — see task details)
```

The `_compose_scene` signature gains:
```python
async def _compose_scene(
    ...,
    composite_harmonization_tier: int = 0,
    relit_map: dict[tuple[str, str], Path] | None = None,
) -> ...
```

### Tier 3 ComfyUI client (when tier >= 3)

```python
# composite_harmonization.py — IC-Light section (only imported when tier >= 3)

async def relight_sprite(
    card_path: Path,
    background_path: Path,
    comfyui_client: Any,  # ComfyUIClient from services/
    workflow_path: str,
) -> bytes | None:
    """Submit IC-Light relight job to ComfyUI. Returns PNG bytes or None on failure."""
    ...
```

### Modified: `src/yt_flow/config.py`

Add after `parallax_enabled`:
```python
# ── Composite harmonization (Story 8.7) ────────────────────────────────────
# Tiered ladder: 0=off, 1=tint+shadow+composite-grade, 2=+light-wrap, 3=+IC-Light
composite_harmonization_tier: int = 1
iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"
```

## Tasks / Subtasks

- [ ] Task 1 — `composite_harmonization.py` pure functions (AC: 1, 2, 5)
  - [ ] Create `src/yt_flow/pipeline/nodes/composite_harmonization.py`: `build_sprite_tint`, `build_contact_shadow`, `build_light_wrap` as pure filter-string builders. No imports beyond `domain.state` and `sound_design.MOOD_VALUES`.
  - [ ] `build_sprite_tint(mood)` returns valid ffmpeg `colorbalance=` filter string per AC1.
  - [ ] `build_contact_shadow(cast_member)` returns valid ffmpeg geq filter string per AC2.
  - [ ] `build_light_wrap(blur_radius=8, intensity=0.15)` returns filter chain per AC5.
  - [ ] Unit tests in `tests/pipeline/test_composite_harmonization.py`: syntax validation (all returned strings are accepted by a dry-run ffmpeg filter parse or at minimum regex-validated), mood-to-tint mapping covers all four moods, depth→shadow-scale monotonic (near > mid > far).

- [ ] Task 2 — Wire Tier 1 into `_compose_scene` (AC: 1, 2, 3, 4)
  - [ ] Add `composite_harmonization_tier: int = 0` parameter to `_compose_scene`.
  - [ ] When `tier >= 1`: apply `build_sprite_tint(mood)` to the character chain before overlay.
  - [ ] When `tier >= 1`: render contact shadow layer between bg and char. Restructure the character overlay section to: bg → shadow layer (geq over bg) → char (overlay on shadow+bg) → post_fx.
  - [ ] Validate composite-then-grade ordering: add an assertion or regression test that `post_frag` appears after the `overlay` label in the filter_complex string when character_path is set.
  - [ ] When `tier == 0`: no import of `composite_harmonization`, no filter injection, byte-for-byte identical to today.
  - [ ] Update `video_node` to pass `s.composite_harmonization_tier` to `_compose_scene`.

- [ ] Task 3 — Wire Tier 2 light wrap (AC: 5, 6)
  - [ ] When `tier >= 2`: insert `build_light_wrap()` filter chain between tinted character and overlay. The chain operates on `[bg]` (input 0, already zoompanned) and `[tinted_char]` (after tint) → outputs `[char]` with edge blending.
  - [ ] Ensure the filter chain's stream labels don't collide with existing labels (`[bg]`, `[char]`, `[ov]`). Use intermediate labels: `[tinted]`, `[wrapped]`.

- [ ] Task 4 — IC-Light ComfyUI workflow (AC: 7)
  - [ ] Create `data/workflows/comfyui_iclight_relight_api.json`: ComfyUI workflow JSON with IC-Light node(s). Two image inputs: `card_image` (character sprite) + `background_image` (plate/reference). Output: single re-lit sprite PNG. The workflow uses the IC-Light conditioning pipeline — prompt is minimal (lighting direction hint only).
  - [ ] Add `iclight_comfyui_workflow_path` to `Settings` (`config.py`).

- [ ] Task 5 — RelightCache + pre-computation (AC: 8, 9)
  - [ ] In `composite_harmonization.py`, add `RelightCache` class: `get_or_compute(card_key, location_key, style_epoch) -> Path | None`, `store(card_key, location_key, image_bytes)`. Uses `AssetService` for `assets/relit/` path management + manifest entries.
  - [ ] `precompute_relights(scenes, asset_service, comfyui_client, workflow_path)` identifies all `(card_key, location_key)` pairs where both are STOCK assets in `AssetService`, checks cache, submits cold misses to ComfyUI in parallel (asyncio.gather, capped at 3 concurrent), returns `dict[(card_key, location_key), Path]`. Non-fatal on ComfyUI failure — logs warning + skips the pair.
  - [ ] Wire `precompute_relights` into `video_node` before the scene composition loop, pass result as `relit_map` to `_compose_scene`.

- [ ] Task 6 — Tier 3 runtime path in `_compose_scene` (AC: 10, 11)
  - [ ] When `tier >= 3` and `relit_map` is provided: for each `CastMember` in the shot, if `(card_key, location_key)` is in the map, substitute `relit_map[(card_key, location_key)]` as the character input instead of the original `character_path`.
  - [ ] When a pair is missing from the map (cold miss or non-STOCK), use the original character_path — no runtime ComfyUI call inside the composition loop.
  - [ ] Langfuse span enrichment: add `relit_pairs_total`, `relit_pairs_hit`, `relit_pairs_miss` to `_record_trace`.

- [ ] Task 7 — Regression safety + toggles (AC: 12, 13)
  - [ ] Default `composite_harmonization_tier = 0` in config — the iteration 1 gate has not yet fired. All existing tests MUST pass with tier=0.
  - [ ] Unit tests with `tier=1`: verify filter chain contains `colorbalance` + `geq` shadow when character_path is set.
  - [ ] Unit tests with `tier=0`: verify filter chain is identical to pre-8.7 baseline (no `colorbalance`, no `geq`).
  - [ ] `tests/pipeline/test_video_harmonization.py`: dedicated test file covering all three tiers with mock ffmpeg (no real ffmpeg calls — use `_run_ffmpeg` monkeypatch).
  - [ ] Regression: `uv run pytest tests/pipeline/test_video.py tests/pipeline/test_color_grade.py -q` stays green.
  - [ ] `ruff check` clean on all new + modified files.
  - [ ] Frontend unaffected — no UI changes in this story.

## Dev Notes

### Current filter chain (baseline, pre-8.7)

Character shot:
```
[0:v]zoompan...[bg];
[1:v]scale...char_chain[char];
[bg][char]overlay=x=...:y=...[ov];
[ov]post_fx,subtitles=...[out]
```

Background-only shot:
```
[0:v]zoompan...post_fx,subtitles=...[vout]
```

### Target filter chain (Tier 1)

Character shot:
```
[0:v]zoompan...[bg];
[1:v]scale...,colorbalance=...[tinted];
[tinted]geq=...alpha...[shadow_mask];
[bg][shadow_mask]overlay=...[bg_with_shadow];
[bg_with_shadow][tinted]overlay=x=...:y=...[ov];
[ov]post_fx,subtitles=...[out]
```

The contact shadow is tricky in ffmpeg — it requires rendering a separate shadow layer and overlaying it between bg and character. An alternative simpler implementation: use `drawbox` on a `color=c=black@0.3:s=...` source, apply `boxblur` for softness, then overlay. This may be simpler than `geq`. The implementer should choose the most maintainable approach.

### Target filter chain (Tier 2)

Adds light wrap between tint and overlay:
```
[bg][tinted]edgedetect+blur+alphamerge...[wrapped];
[bg_with_shadow][wrapped]overlay...[ov];
[ov]post_fx,subtitles=...[out]
```

### IC-Light caching layout

```
assets/relit/{card_key}/{location_key}/epoch_{style_epoch}.png
```

Example: `assets/relit/STOCK-d-class/isolation-cell/epoch_1.png`

The `asset_key` in `manifest.json` follows the 8-6 convention: `"relit/{card_key}/{location_key}"`. `source.type = "iclight_relight"` with `source.card_key` + `source.location_key` metadata.

### Ponytail notes

- The `build_light_wrap` filter chain may need iteration — ffmpeg light wrap is not a built-in filter. If a clean ffmpeg-only implementation proves too complex/costly, defer to Tier 3 only (skip Tier 2) rather than adding a Python image-processing dependency. Document the decision.
- `composite_harmonization.py` lazy import: `video.py` imports it only inside the `if tier >= 1:` block, not at module top. This keeps the tier=0 import graph unchanged (ponytail: don't import what you don't use).
- Mood taxonomy: reuse `MOOD_VALUES` from `sound_design.py`. If a new mood is added, the `MOOD_TINT_PARAMS` assertion catches the mismatch at import time.

## Testing

### Test plan

1. **`tests/pipeline/test_composite_harmonization.py`:**
   - `test_build_sprite_tint_all_moods` — all four moods return valid ffmpeg filter strings, no KeyError
   - `test_build_sprite_tint_unknown_mood_falls_back_to_dread` — resolve_mood fallback
   - `test_build_contact_shadow_depth_scales` — near > mid > far; all positions produce valid filter strings
   - `test_build_light_wrap_syntax` — filter string contains expected ffmpeg filter names (edgedetect, boxblur, alphamerge)
   - `test_mood_tint_params_match_mood_values` — assertion enforces lockstep

2. **`tests/pipeline/test_video_harmonization.py`:**
   - `test_tier0_no_harmonization` — patch `_run_ffmpeg`, verify filter_complex has no colorbalance/geq
   - `test_tier1_adds_tint_and_shadow` — verify filter_complex contains `colorbalance` and shadow `geq`
   - `test_tier1_composite_before_grade` — verify `overlay` appears before `eq=` (post_fx's eq filter) in the chain
   - `test_tier2_adds_light_wrap` — verify filter_complex contains `edgedetect`
   - `test_tier3_relit_map_substitution` — when relit_map has the pair, character_path is substituted
   - `test_tier3_missing_pair_uses_original` — when pair not in map, original character_path used
   - `test_chapter_card_unchanged` — chapter card filter chain unchanged regardless of tier

3. **Regression suite:** `uv run pytest -q` — full suite green.

### Manual validation

After implementation, run with `composite_harmonization_tier=1` on a real SCP run (SCP-049 is the reference). Compare side-by-side screenshots of character scenes vs tier=0 baseline. Jay reviews the A/B difference. If Tier 1 is visibly better, keep it on by default. If no perceptible difference, keep tier=0 default and document.

---

**Story Status:** ready-for-dev
**Story Completion:** Ultimate context engine analysis completed — comprehensive developer guide created with full architecture analysis, code context, prior-story learnings, and tiered implementation ladder.
