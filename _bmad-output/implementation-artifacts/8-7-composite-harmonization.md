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
baseline_commit: edad3f7ba0ac8e40ffaed29c3994d198f20817a7
---

# Story 8.7: Composite Harmonization — Collage Look Resolution Ladder

Status: review

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
composite_harmonization_tier: int = 0   # 0 | 1 | 2 | 3 — default off until tier-1 A/B approval
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

10. **Tier 3 toggle + runtime substitution.** Given `composite_harmonization_tier >= 3`, then `video_node` calls `precompute_relights` before the scene composition loop and substitutes each STOCK `(card_key, location_key)` hit into the resolved card list before calling `_compose_scene`. `_compose_scene` remains pure composition over concrete card paths; it does not call ComfyUI or know about `AssetService`. For each `CastMember` in a shot, if `(card_key, location_key)` is in the map and the relit PNG is alpha-preserving, use the re-lit sprite instead of the original `character_path`; otherwise fall back to the original sprite. The original sprite remains in the library — relighting is a derived asset, not a mutation.

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
composite_harmonization_tier: int = 0
iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"
```

## Tasks / Subtasks

- [x] Task 1 — `composite_harmonization.py` pure functions (AC: 1, 2, 5)
  - [x] Create `src/yt_flow/pipeline/nodes/composite_harmonization.py`: `build_sprite_tint`, `build_contact_shadow`, `build_light_wrap` as pure filter-string builders. No imports beyond `domain.state` and `sound_design.MOOD_VALUES`.
  - [x] `build_sprite_tint(mood)` returns valid ffmpeg `colorbalance=` filter string per AC1.
  - [x] `build_contact_shadow(cast_member)` returns valid ffmpeg geq filter string per AC2.
  - [x] `build_light_wrap(bg_label, char_label, out_label, blur_radius=8, intensity=0.15)` returns filter chain per AC5. Deviation: signature takes explicit stream labels instead of `mood`/hardcoded `[0:v]`/`[1:v]` — required for the real N-card filter graph (see Task 3 note).
  - [x] Unit tests in `tests/pipeline/nodes/test_composite_harmonization.py` (actual repo convention is `tests/pipeline/nodes/`, not `tests/pipeline/` as drafted): regex-validated syntax + **live ffmpeg dry-run validation** for every mood/depth/position combination (caught 3 real ffmpeg syntax bugs the string-level tests alone would have missed — see Completion Notes), mood-to-tint mapping covers all four moods, depth→shadow-scale monotonic (near > mid > far).

- [x] Task 2 — Wire Tier 1 into `_compose_scene` (AC: 1, 2, 3, 4)
  - [x] Add `composite_harmonization_tier: int = 0` parameter to `_compose_scene`.
  - [x] When `tier >= 1`: apply `build_sprite_tint(mood)` to the character chain before overlay.
  - [x] When `tier >= 1`: render contact shadow layer between bg and char, per-card in the real N-card overlay loop (bg/prior-card output → shadow overlay → card overlay → next card...).
  - [x] Validate composite-then-grade ordering: `test_tier1_composite_before_grade` asserts `overlay=` precedes `eq=saturation=` (post_fx) in the filter_complex string.
  - [x] When `tier == 0`: no import of `composite_harmonization` (verified via `sys.modules` check), no filter injection, byte-for-byte identical to today (full regression suite green at tier=0 default fixture).
  - [x] Update `video_node` to pass `s.composite_harmonization_tier` to `_compose_scene`.

- [x] Task 3 — Wire Tier 2 light wrap (AC: 5, 6)
  - [x] When `tier >= 2`: insert `build_light_wrap()` filter chain between the tinted card and the overlay, per-card.
  - [x] Stream labels don't collide across cards (`sh{k}*`, `wbg{k}a/b`, `cw{k}*`, indexed by card `k`) — live-verified with a real 2-card ffmpeg render (AC:14).

- [ ] Task 4 — IC-Light ComfyUI workflow (AC: 7)
  - [ ] `data/workflows/comfyui_iclight_relight_api.json` remains a **structural placeholder, not a verified graph** (this environment's local ComfyUI has no IC-Light custom nodes installed; see `README-iclight-relight.md` for what's real vs. placeholder and what to do before enabling tier 3 for real). Code review patched the runtime so unverified placeholder workflows are rejected as non-fatal cache misses unless the workflow is explicitly marked `ytflow_verified_iclight: true`.
  - [x] Added `iclight_comfyui_workflow_path` to `Settings` (`config.py`) + `composite_harmonization_tier`.

- [x] Task 5 — RelightCache + pre-computation (AC: 8, 9)
  - [x] `RelightCache`: `get_or_compute(card_key, location_key, style_epoch) -> Path | None`, `store(...)`. `asset_service` is accepted as a duck-typed `Any` param (not imported) to keep `composite_harmonization.py` AD-1-compliant (domain/config only). Fixed a latent bug during implementation: `get_or_compute` now checks the cached entry's own `style_epoch` metadata, not just key presence — otherwise a style_epoch bump would silently keep serving a stale relight.
  - [x] `precompute_relights(scenes, cast_cards, asset_service, comfyui_client, workflow_path, assets_path, comfyui_url)` — **deviation**: takes `cast_cards` (video_node's already-resolved card paths) instead of re-deriving sprite paths from `AssetService` from scratch, avoiding duplicate pose/angle resolution logic. STOCK detection is a pure domain check (`card_key in STOCK_CAST_KEYS`, `shot.location_key is not None`), not an AssetService query. Concurrency capped at 3 via `asyncio.Semaphore`. Returns `(relit_map, stats)` instead of just the map, so Task 6's Langfuse counts don't need a second pass.
  - [x] Wired into `video_node` before the composition loop via a new `inject_relight_resolver` seam (mirrors Story 8.3/8.5's `inject_cast_resolver`/`inject_location_service`), injected in `api/main.py`. The AssetService/comfyui_client glue (`precompute_relights_for_run`) lives in `services/run_service.py`, not a new services module — two independent architecture tests each caught a wrong first attempt: `tests/domain/test_state_imports.py::test_api_imports_no_pipeline` rejected `api/main.py` importing `composite_harmonization` directly (only the two allow-listed `inject_*` seams from `pipeline.nodes.video`/`.image` may cross that boundary), and `tests/services/test_character_service.py::test_services_does_not_import_api_or_pipeline` rejected a standalone `services/relight_service.py` (only `run_service.py` — the sole `graph.astream()` caller per AD-3/AD-4 — is exempted from services' no-pipeline-imports rule).

- [x] Task 6 — Tier 3 runtime path in `_compose_scene` (AC: 10, 11)
  - [x] **Deviation**: substitution happens in `video_node`'s per-scene loop (mutating `scene_cards`' `path` before calling `_compose_scene`), not inside `_compose_scene` via a `relit_map` parameter — simpler, and keeps `_compose_scene` itself free of any Tier-3/ComfyUI awareness. `_compose_scene`'s signature was not extended with `relit_map`.
  - [x] Missing pair (cold miss or non-STOCK) falls back to the original card path — no runtime ComfyUI call in the composition loop.
  - [x] Langfuse span enrichment: added `composite_harmonization_tier`, `relit_pairs_computed`, `relit_pairs_failed` to `_record_trace` (renamed from the draft's `relit_pairs_total`/`hit`/`miss` — `computed`/`failed` is what `precompute_relights` actually tracks, and `computed` already covers both cache hits and fresh generations).

- [x] Task 7 — Regression safety + toggles (AC: 12, 13)
  - [x] Code review restored the safe default: `composite_harmonization_tier: int = 0` with `Field(0, ge=0, le=3)`. The collage-look entry gate justifies implementing the ladder, but Tier 1 still needs a real tier-0 vs tier-1 A/B before becoming default-on.
  - [x] Unit tests with `tier=1`: `test_tier1_adds_tint_and_shadow` verifies `colorbalance`/`geq` in the filter_complex.
  - [x] Unit tests with `tier=0`: `test_tier0_no_harmonization_filters_present` verifies their absence.
  - [x] `tests/pipeline/nodes/test_video_harmonization.py` (actual convention, not `tests/pipeline/`): 15 tests covering tiers 0-3, non-fatal Tier 3 failure, chapter-card non-interference, plus 3 **real-ffmpeg** integration tests (tier=1, tier=2, tier=2 two-card) that caught 2 additional real bugs no monkeypatched test could (see Completion Notes).
  - [x] Regression: full `uv run pytest -q` green (1057 passed, 1 skipped) — adapted from the draft's narrower `test_video.py`/`test_color_grade.py` invocation to the actual full suite, since this story touches `api/main.py` and `services/` too.
  - [x] `ruff check .` clean.
  - [x] Frontend unaffected — confirmed via `git status`, no `frontend/` files touched.

### Review Findings

- [x] [Review][Patch] Prevent placeholder IC-Light workflow from caching bogus generated sprites [data/workflows/comfyui_iclight_relight_api.json; src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched by requiring `ytflow_verified_iclight: true`; unverified workflow now becomes a non-fatal miss.
- [x] [Review][Patch] Sanitize relight cache key/path components [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched with strict cache-key validation and unsafe-pair skip.
- [x] [Review][Patch] Validate relit output remains a valid alpha PNG before cache/substitution [src/yt_flow/pipeline/nodes/composite_harmonization.py; src/yt_flow/pipeline/nodes/video.py] — patched with `has_alpha` checks before storing and regression coverage.
- [x] [Review][Patch] Malformed resolver cards without `card_key` can crash Tier 3 substitution [src/yt_flow/pipeline/nodes/video.py] — patched to use `card.get("card_key")` and fall back to the original sprite.
- [x] [Review][Patch] Bound `composite_harmonization_tier` to 0..3 and keep default off pending A/B [src/yt_flow/config.py] — patched with `Field(0, ge=0, le=3)` and config tests.
- [x] [Review][Patch] Mood tint omitted saturation/contrast changes required by AC1 [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched by adding `eq=saturation=...:contrast=...` after `colorbalance`.
- [x] [Review][Patch] Contact shadow used out-of-range far scale and hard edge [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched to keep depth scales in 0.6..1.0 and add depth-scaled blur.
- [x] [Review][Patch] `run_service` imported composite harmonization at module import time [src/yt_flow/services/run_service.py] — patched by moving `precompute_relights` import into the Tier 3 glue function.
- [x] [Review][Patch] Batch relight precompute did not verify both STOCK assets through AssetService [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched to require approved, integrity-verified card and location manifest entries before IC-Light precompute.
- [x] [Review][Defer] Real IC-Light workflow graph is still missing [data/workflows/comfyui_iclight_relight_api.json] — deferred, external ComfyUI IC-Light custom nodes are not installed locally; Tier 3 remains disabled/non-fatal until a real graph is installed and live-verified.
- [x] [Review][Patch] Cached relit sprites could bypass alpha and path-root validation [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched cache hits to reject unsafe manifest paths and non-alpha/unreadable PNGs.
- [x] [Review][Patch] Relight cache writes could collide or leave file bytes inconsistent after manifest failure [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched unique temp names and existing-file rollback on store failure.
- [x] [Review][Patch] A single malformed relight shot/card/pair could abort all Tier 3 precompute [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched per-shot, per-card, and per-pair exception isolation.
- [x] [Review][Patch] Relit-map substitution could accept opaque injected sprites [src/yt_flow/pipeline/nodes/video.py] — patched video substitution to alpha-check relit paths and fall back to originals.
- [x] [Review][Patch] Tier 2 light wrap sampled the whole plate instead of the card's local placement region [src/yt_flow/pipeline/nodes/composite_harmonization.py] — patched position-aware left/center/right background band sampling before edge blur.
- [x] [Review][Patch] Tier 3 substitution contract in AC10 contradicted the implemented service boundary [8-7-composite-harmonization.md] — patched AC10 to formalize pre-call path substitution in `video_node` while keeping `_compose_scene` pure over concrete card paths.

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

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Completion Notes List

- **dev-story halted before any implementation — entry gate not satisfied.** This story's own `entry_gate` requires iteration 1's 8-3 DoD A/B to *empirically confirm* the collage-look defect before work starts; unconfirmed, the story stays in `backlog`. Checked for that confirmation and found none:
  - 8-3's Dev Agent Record never mentions collage look in either direction. Its DoD A/B was explicitly *substituted* — an unrelated Story 8.1 cast-prompt bug forced hand-crafted cast metadata in place of the real candidate-prompt A/B, and the Dev Agent Record itself flags the result as "code-author self-assessment... not an independent judge run; Jay should treat these scores as directional pending his own look."
  - `deferred-work.md`'s collage-look entry (written 2026-07-07, before 8-3 shipped) is framed as a prediction with its own recheck condition ("8-3 DoD 결과에서 실제 결함으로 확인되면 그때 스토리화") — still unconfirmed.
  - 8-5's context (written 2026-07-09, after 8-3 closed) still frames Jay's confirmation as pending/future tense, not done.
  - `sprint-status.yaml` and this story's frontmatter had both drifted to `ready-for-dev` despite the gate — a bookkeeping error, not a signal the gate fired. Corrected back to `backlog` here and in sprint-status.yaml.
- Confirmed with Jay directly (2026-07-09 session) that the gate is unmet; he chose to revert to `backlog` rather than override YAGNI. No code, tests, or config were touched.
- **Gate re-confirmed and satisfied (2026-07-09, same session).** Found the 8-3 live-verification artifacts already on disk (`workspace/story-8-3-live-ab/seg_002.mp4`, 2026-07-08) — a real two-card composite (SCP-049 + STOCK-d-class) rendered through actual ComfyUI, not a mockup. Extracted frames and reviewed with Jay: Scene 2 shows a clear collage look — the character renders in a dark, desaturated illustration/comic style while the background+other card render in a more photoreal style, lighting direction/color temperature mismatched (cool/dark left vs bright/warm right), and the background itself splices two visually disjoint environments (dark interior vs bright canyon) in one frame. Caveat noted: this render predates Story 8.5's STOCK location-plate library (merged one day later, 2026-07-09) — backgrounds today come from a curated plate set rather than free generation — but the underlying architecture (character card and background plate generated independently, composited via ffmpeg overlay with no shared lighting pass) is unchanged by 8.5, so the defect mechanism is not expected to have gone away. Jay confirmed the gate is satisfied and directed implementation to proceed. Status reverted `backlog` → `ready-for-dev`.
- **Implemented Tiers 1-3 per spec, with three documented deviations** (Tasks 3/5/6 above have the details): `build_light_wrap` takes explicit stream labels instead of a `mood` param; `precompute_relights` takes `cast_cards` instead of re-resolving sprite paths from `AssetService`; Tier 3 substitution happens in `video_node` (mutating `scene_cards` before `_compose_scene`) instead of threading a `relit_map` parameter through `_compose_scene` itself. All three simplify the real integration without changing any AC's observable behavior.
- **Live ffmpeg validation caught 5 real bugs the string-level unit tests alone would have missed** — worth recording since the story's own `build_contact_shadow`/`build_light_wrap` sketch code (Technical Requirements section) contained several of them verbatim:
  1. `geq=...:eval=frame` — `geq` has no `eval` option (that's for time-varying filters like `overlay`/`scale`); a static per-pixel ellipse never needed it. Removed.
  2. The shadow's horizontal offset produced a bare double-minus (`X/W-0.5--0.1667`) for a negative position offset — ffmpeg's expression parser rejects it. Fixed by parenthesizing the offset term.
  3. Infix `<` inside `if(...)` is rejected by this ffmpeg build's eval parser ("Missing ')' or too many args") — needed the `lt(a,b)` function form instead.
  4. Reusing a filter-graph label as input to two different filters without an explicit `split` fails with "Invalid file index 0" / "matches no streams" — hit this twice: once for `build_light_wrap`'s own `char_label`, and again at the `_compose_scene` integration level where `base_label` (bg+shadow) feeds both the light-wrap's edge-detection input and the final overlay. Both fixed with explicit `split=2`.
  5. `alphamerge` requires matching frame dimensions — the edge-detected background (full `COMP_W x COMP_H`) is essentially never the same size as a card scaled to its depth-scaled motion-safe box. Fixed with `scale2ref` to resize the edge stream to the character's own dimensions before merging.
  All five were found by writing real (non-monkeypatched) `ffmpeg` invocations against `color=`/lavfi sources in the test suite (`tests/pipeline/nodes/test_composite_harmonization.py`'s live dry-run checks, plus 3 real-ffmpeg integration tests in `test_video_harmonization.py` for tier=1/tier=2/two-card-tier=2) — the regex-only validation the story's test plan called for as a *minimum* would not have caught any of them.
- **IC-Light (Tier 3) is unverified against a real ComfyUI install** — this environment's local ComfyUI (`$HOME/workspaces/ComfyUI/custom_nodes/`) has IPAdapter/ControlNet-aux/Impact-Pack/InSPyReNet installed but no IC-Light nodes. `data/workflows/comfyui_iclight_relight_api.json` is a structural placeholder (real `LoadImage` interchange nodes, placeholder conditioning graph) — documented in `data/workflows/README-iclight-relight.md` with what's real, what's placeholder, and what to do before enabling tier 3 for real. Code review patched the runtime so this placeholder is rejected unless explicitly marked `ytflow_verified_iclight: true`; a tier=3 run today gets 0 relit pairs and falls back to un-relit sprites everywhere, never fails.
- Fixed a latent cache-staleness bug found while implementing `RelightCache`: `get_or_compute` originally didn't check the cached entry's `style_epoch`, so a style_epoch bump would silently keep serving relights computed against the old epoch's assets. Now checks `entry["style_epoch"] == style_epoch` and treats a mismatch as a cache miss.
- **Config default restored to `composite_harmonization_tier=0` during code review** — the entry gate justifies implementing the ladder, but AC4/AC12 still require real tier-0 vs tier-1 A/B before making Tier 1 production-default. The field is now bounded to `0..3`.
- **Initial full regression**: `uv run pytest -q` — 1057 passed, 1 skipped, no failures. `ruff check .` — clean. Frontend untouched (confirmed via `git status`).
- **Code review patch regression**: targeted Story 8.7/config/architecture tests passed (62 passed, 1 warning).
- **Post-review full regression**: `uv run pytest -q` — 1066 passed, 1 skipped, 1 warning. `uv run ruff check .` — clean.
- **Not live-validated**: an actual end-to-end SCP run with `composite_harmonization_tier=1` (or higher) through the real pipeline (ComfyUI + real cast/location assets) — the story's own "Manual validation" section calls for Jay to do this side-by-side against the tier=0 baseline and judge whether Tier 1 alone resolves the collage look. Recommend running that next, on a real SCP (SCP-049 per the story's reference), before deciding whether Tier 2/3 are worth pursuing further (per AC:12's YAGNI stopping rule).

### File List

**New:**
- `src/yt_flow/pipeline/nodes/composite_harmonization.py`
- `tests/pipeline/nodes/test_composite_harmonization.py`
- `tests/pipeline/nodes/test_video_harmonization.py`
- `data/workflows/comfyui_iclight_relight_api.json`
- `data/workflows/README-iclight-relight.md`

**Modified:**
- `src/yt_flow/pipeline/nodes/video.py` — `_compose_scene` gains `composite_harmonization_tier`; per-card overlay loop wires Tier 1 tint+shadow / Tier 2 light wrap; `inject_relight_resolver` seam; `video_node` precomputes Tier 3 relights + substitutes STOCK sprite paths before composition; `_record_trace` gains `composite_harmonization_tier`/`relit_pairs_computed`/`relit_pairs_failed`
- `src/yt_flow/config.py` — `composite_harmonization_tier`, `iclight_comfyui_workflow_path`
- `src/yt_flow/services/run_service.py` — `precompute_relights_for_run()` (the AssetService/comfyui_client ↔ `composite_harmonization.precompute_relights` glue; lives here, not a new module, because this is the one services file AD-1 allows to import pipeline/)
- `src/yt_flow/api/main.py` — `inject_relight_resolver` wiring via `run_service.precompute_relights_for_run`
- `tests/pipeline/nodes/test_video.py` — `_settings_ns` fixture gains `composite_harmonization_tier` (defaults 0, ponytail convention)
- `tests/test_config.py` — `test_composite_harmonization_defaults`
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status backlog → ready-for-dev → in-progress → review

## Change Log

- 2026-07-07: Story created from Epic 8 architecture decision (Jay 지시), status `ready-for-dev`, entry_gate pending iteration 1 confirmation.
- 2026-07-09: dev-story invoked; entry_gate checked and found unsatisfied (8-3's DoD A/B was substituted for an unrelated bug and never produced a real collage-look verdict). Jay confirmed unmet, reverted status to `backlog`. No implementation performed.
- 2026-07-09 (same session): Located pre-existing 8-3 live-verification render evidence on disk, reviewed with Jay, confirmed collage look is real and visible. Status reverted `backlog` → `ready-for-dev`; implementation begins.
- 2026-07-09 (same session): Implemented Tiers 1/2 and Tier 3 scaffolding. `composite_harmonization.py` (Tiers 1/2 pure ffmpeg filter builders + Tier 3 RelightCache/precompute_relights/relight_sprite), wired into `video.py`'s per-card overlay loop and `video_node`, `inject_relight_resolver` seam + `run_service.precompute_relights_for_run` + `api/main.py` wiring, `config.py` fields, IC-Light workflow placeholder + README. Live ffmpeg validation (not just regex) caught and fixed 5 real filter-graph bugs; two AD-1 architecture tests each caught a wrong first attempt at the services/pipeline injection boundary. Full regression green (1057 passed, 1 skipped), ruff clean. IC-Light itself unverified (no local custom-node install) and left as deferred external-work. Status → review.
- 2026-07-09 (code review): Applied review patches: safe default restored to tier 0 with range validation, mood tint now includes saturation/contrast, contact shadow scale/blur corrected, relight cache path components sanitized, relit outputs validated as alpha PNG before cache/substitution, approved AssetService entries required for STOCK relight precompute, malformed cards fall back safely, unverified placeholder workflow cannot cache outputs, and run_service Tier 3 import made lazy. Targeted regression green (62 passed, 1 warning). Status → in-progress pending real IC-Light workflow or explicit scope decision.
- 2026-07-09 (scope decision, Jay via dev-story): explicit scope decision made — real IC-Light (Tier 3) live validation against an actual installed custom-node graph is deferred as external infra work, same precedent as Story 8.4's live-validation split into 8.4a. Non-blocking because Tier 3 is non-fatal by construction (gated behind `ytflow_verified_iclight`, falls back to un-relit sprites). Re-verified before closing: `ruff check .` clean, targeted regression (composite_harmonization/video_harmonization/config/AD-1 architecture tests) 67 passed. Status → review.
- 2026-07-10 (code review): Applied review patches for relight cache hardening (safe manifest paths, alpha-checked cache hits, UUID temp files, restore-on-store-failure), per-shot/card/pair Tier 3 exception isolation, relit substitution alpha fallback, position-aware Tier 2 light-wrap sampling, and AC10 contract clarification. Re-verified: targeted regression 67 passed, ruff clean.

---

**Story Status:** review
**Story Completion:** Entry gate confirmed 2026-07-09 via real 8-3 render evidence; Tiers 1/2 implemented and review-patched. Tier 3 remains deferred because no real IC-Light workflow/custom-node install exists locally; placeholder workflow is now safely non-operational until verified.
