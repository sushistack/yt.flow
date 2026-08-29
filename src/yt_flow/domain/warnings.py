"""Run-warning catalog + merge — the only place a ``RunWarning`` is built. [AD-1]

Pure stdlib, no I/O, no upper-layer import: producers live in ``services/`` and
``pipeline/`` and neither may import the other, so ``domain`` is the shared floor
(same reason the cast/prompt tables in ``state.py`` live there).

Two rules make this a *single* authority rather than one more logging channel:

* **The catalog owns stage + copy.** A producer names a code and hands over
  identifiers; it never writes Korean, and it cannot file a warning against the
  wrong stage. ``RUN_WARNING_CATALOG`` is asserted complete against
  ``RunWarningCode`` at import, so adding a code without deciding its stage and
  operator copy fails immediately instead of shipping an unlabelled row.
* **Identity excludes volatile text.** Two attempts at the same shot produce two
  different exception strings for the same defect; keying dedupe on the message or
  on ``detail`` would append a near-duplicate on every retry, which is exactly the
  noise AC6 forbids.
"""

from collections import Counter
from typing import cast, get_args

from yt_flow.domain.state import RunWarning, RunWarningCode, StageName

# code -> (owning stage, short Korean operator copy). The stage is the one whose
# human gate reviews the condition, not the layer of the Python function that
# detected it: provisioning runs in the service around the scenario decision, so its
# warnings are scenario's even though no scenario *node* produced them.
RUN_WARNING_CATALOG: dict[str, tuple[StageName, str]] = {
    "vision_enrichment_failed": (
        "scenario", "레퍼런스 비전 분석에 실패해 식별 묘사 없이 카드를 만들었습니다"),
    "character_provisioning_failed": (
        "scenario", "캐릭터 레퍼런스 자동 확보에 실패했습니다 — 이 배역은 화면에 나오지 않습니다"),
    "special_pose_cap_exceeded": (
        "scenario", "특수 포즈 카드 한도를 넘겨 생성을 건너뛰었습니다 — 기본 포즈로 대체됩니다"),
    "special_pose_generation_failed": (
        "scenario", "특수 포즈 카드 생성에 실패했습니다 — 기본 포즈로 대체됩니다"),
    "special_pose_guide_unapplied": (
        "scenario", "포즈 가이드를 적용하지 못해 조건화 없이 생성했습니다"),
    "derived_entity_cap_exceeded": (
        "scenario", "파생 개체 카드 한도를 넘겨 생성을 건너뛰었습니다 — 해당 배역은 화면에서 빠집니다"),
    "derived_entity_generation_failed": (
        "scenario", "파생 개체 카드 생성에 실패했습니다 — 해당 배역은 화면에서 빠집니다"),
    "derived_entity_look_unauthored": (
        "scenario", "승인된 외형이 없는 파생 개체라 카드를 만들지 않았습니다 — 해당 배역은 화면에서 빠집니다"),
    "character_card_i2i_fallback": (
        "scenario", "레퍼런스 조건화에 실패해 t2i로 생성했습니다 — 동일 인물 보장이 약해집니다"),
    "character_card_multi_figure": (
        "scenario", "렌더에 인물이 하나가 아니라 카드를 폐기했습니다 — 해당 앵글은 만들어지지 않았습니다"),
    # Reason-neutral, like `stock_plate_unfit` above: the descriptor can be absent
    # because enrichment failed, because a human never wrote one, or because a
    # whitespace-only value was persisted. The one thing every case shares is what
    # happened — no card was made — so that is what the line says.
    "character_descriptor_missing": (
        "scenario", "식별 묘사가 없어 카드를 만들지 않았습니다 — 이 배역은 화면에 나오지 않습니다"),
    "stock_plate_resolver_unavailable": (
        "image", "스톡 배경 조회기를 쓸 수 없어 배경을 생성했습니다"),
    "stock_plate_missing": (
        "image", "승인된 스톡 배경이 없어 배경을 생성했습니다"),
    "stock_plate_resolution_failed": (
        "image", "스톡 배경 조회에 실패해 배경을 생성했습니다"),
    # Reason-neutral on purpose. "맞는 승인 배경이 없어" would be FALSE for the most
    # common reason of all: `unservable_framing` (close-up/POV, 7/31 shots of run
    # 4b35c0ed and permanent by design) fires on keys whose approved backgrounds are
    # perfectly good — the shot is simply a close-up. The same row also rides
    # `partial_metadata`, where the prescription is to measure plates we already have.
    # One sentence for seven reasons has to state what happened (a plate was not
    # assigned, the background was generated), not diagnose why. 14.2 took this lesson
    # already.
    "stock_plate_unfit": (
        "image", "이 샷에는 승인 배경을 배정하지 않고 배경을 생성했습니다"),
    "background_guard_unscreened": (
        "image", "배경 인물 검사를 마치지 못했습니다 — 배경에 사람이 남아 있을 수 있습니다"),
    "plate_affordance_unusable": (
        "image", "배경에 인물이 설 자리가 있는지 확인이 필요합니다 — 자리가 없다고 판정된 샷은 배역이 화면에서 빠지고, 판정하지 못한 샷은 배역을 그대로 둡니다"),
    "subtitle_alignment_fallback": (
        "subtitle", "WhisperX 정렬에 실패해 임시 단어 타이밍으로 자막을 만들었습니다"),
    "cast_resolution_failed": (
        "video", "배역 카드 해석에 실패해 배경만으로 렌더링합니다"),
    "cast_card_missing": (
        "video", "배역 카드를 찾지 못해 해당 인물이 화면에서 빠졌습니다"),
    "cast_card_fallback": (
        "video", "요청한 포즈·앵글 카드가 없어 대체 카드를 사용했습니다"),
    "relight_resolver_unavailable": (
        "video", "리라이트 사전계산을 쓸 수 없어 원본 스프라이트로 합성했습니다"),
    "relight_pair_skipped": (
        "video", "일부 카드·배경 조합이 리라이트에서 제외돼 원본 스프라이트로 합성했습니다"),
    "relight_failed": (
        "video", "리라이트에 실패해 원본 스프라이트로 합성했습니다"),
    "relit_sprite_invalid": (
        "video", "리라이트 결과가 잘못돼 원본 스프라이트로 합성했습니다"),
    "recompose_preflight_failed": (
        "video", "ComfyUI 실행 전제가 맞지 않아 샷 재구성을 건너뛰고 오버레이로 렌더했습니다"),
    "recompose_shots_degraded": (
        "video",
        "일부 샷의 재구성이 실패하거나 건너뛰어져 오버레이로 렌더했습니다",
    ),
    # Story 14.3. The copy has to say "the frame is fine, only the record is lost",
    # because the obvious operator reaction to a recompose warning is to re-render
    # the shot — and here that would spend a GPU pass on a frame that is already
    # correct. What was lost is the attribution (which workflow, which placement
    # instruction drew it), which no re-render restores either.
    "recompose_sidecar_failed": (
        "video",
        "재구성 프레임은 정상이지만 기록(사이드카)에 남기지 못했습니다 — 재렌더하지 마세요, 그 샷의 생성 근거만 추적이 안 됩니다",
    ),
}
if set(RUN_WARNING_CATALOG) != set(get_args(RunWarningCode)):
    # `raise`, not `assert`: the docstring promises import-time failure, and `python -O`
    # strips an assert — which would degrade this into a KeyError thrown out of
    # `make_warning` from inside a best-effort `except` block in production.
    raise RuntimeError(
        "every RunWarningCode needs an owning stage and Korean operator copy; missing: "
        f"{sorted(set(get_args(RunWarningCode)) ^ set(RUN_WARNING_CATALOG))}"
    )

# Bounded on purpose: `detail` is the one free-text field and it carries provider /
# exception text. Long enough to name the failure, short enough that a checkpoint
# cannot grow on a pathological provider body.
MAX_DETAIL_CHARS = 200

# Named rows per code per producer. These lists ride a LangGraph checkpoint, are copied
# into every gate `interrupt()` payload and `gate_pending` frame, and render one line
# each directly above the Approve button — a 155-shot run with a resolver outage would
# otherwise put hundreds of near-identical rows in front of the decision.
MAX_SAMPLE_RECORDS = 12

# Excluded from identity — see the module docstring. `detail` is free text; the
# `*_count` tallies and the undecidable streak/total are per-ATTEMPT counters, so a
# retry that degrades the same way with a different tally would append a near-duplicate
# row instead of converging on the one already in the checkpoint (AC1/AC6). They stay in
# `context` and stay on the operator's screen — they are just not part of the identity.
_VOLATILE_CONTEXT_KEYS = frozenset({"detail", "undecidable_streak", "undecidable_total"})


def _volatile(key: str) -> bool:
    return key in _VOLATILE_CONTEXT_KEYS or key.endswith("_count")


def make_warning(code: RunWarningCode, **context: object) -> RunWarning:
    """Build one warning: stage and copy from the catalog, identifiers from kwargs.

    ``None`` values are dropped (an absent identifier must not become part of the
    dedupe key as a null), non-JSON values are stringified, and every string is
    truncated — the record has to survive a checkpoint round-trip and an
    ``interrupt()`` payload unchanged.
    """
    stage, message = RUN_WARNING_CATALOG[code]
    warning: RunWarning = {"code": code, "stage": stage, "message": message}
    bounded = {k: _safe(v) for k, v in context.items() if v is not None}
    if bounded:
        warning["context"] = bounded
    return warning


def _safe(value: object) -> str | int | float | bool:
    if isinstance(value, bool | int | float):
        return value
    return str(value)[:MAX_DETAIL_CHARS]


def _identity(warning: RunWarning) -> tuple:
    context = warning.get("context") or {}
    return (
        warning["code"],
        warning["stage"],
        tuple(sorted((k, v) for k, v in context.items() if not _volatile(k))),
    )


def _cap_key(warning: RunWarning) -> tuple[str, str | None]:
    """Cap per (code, reason), not per code.

    One code can carry reasons of very different severity — `background_guard_unscreened`
    now spans five, from "the detector hiccupped on one shot" to "the guard KNEW this
    frame was populated and shipped it". Capping the code as a whole let the cheap,
    numerous reason consume the 12 slots and push the severest rows into the aggregate,
    which is `gotcha_summary-from-a-capped-list-drops-the-severest-item` exactly. Per
    reason, each failure mode is still bounded at MAX_SAMPLE_RECORDS, so the flood the
    cap exists to stop is still stopped. Codes that carry no `reason` behave as before.
    """
    context = warning.get("context") or {}
    reason = context.get("reason")
    return (warning["code"], reason if isinstance(reason, str) else None)


def cap_samples(warnings: list[RunWarning]) -> list[RunWarning]:
    """Bound each code's named rows per reason, keeping the true total on one aggregate row.

    Same policy the relight diagnostics already apply at the source (they can only
    sample, because the pairs they skipped are never materialised). A code whose
    producer already rolled up its own total — a row carrying a ``*_count`` — is left
    alone: it counted rows it deliberately never emitted, so re-counting here would
    understate it. Order is preserved, aggregates land last in first-seen code order.
    """
    rolled = {_cap_key(w) for w in warnings
              if any(k.endswith("_count") for k in (w.get("context") or ()))}
    seen: Counter[tuple[str, str | None]] = Counter()
    kept: list[RunWarning] = []
    for warning in warnings:
        key = _cap_key(warning)
        seen[key] += 1
        if key in rolled or seen[key] <= MAX_SAMPLE_RECORDS:
            kept.append(warning)
    # The aggregate carries the reason it counted, or the tally would say `총 26건` over
    # two failure modes and name neither.
    kept.extend(
        make_warning(cast(RunWarningCode, code), reason=reason, total_count=total)
        for (code, reason), total in seen.items()
        if total > MAX_SAMPLE_RECORDS and (code, reason) not in rolled
    )
    return kept


def merge(existing: list[RunWarning] | None, new: list[RunWarning] | None) -> list[RunWarning]:
    """Whole-field replacement value: ``existing`` then ``new``, first-seen order, deduped.

    Deterministic by construction — the output order is the input order — so a
    resumed or retried path that re-derives the same warnings returns a list equal
    to the one already in the checkpoint instead of a longer one. This is the
    explicit merge the architecture spine asks for in place of a reducer.
    """
    merged: list[RunWarning] = []
    seen: set[tuple] = set()
    for warning in (*(existing or ()), *(new or ())):
        key = _identity(warning)
        if key in seen:
            continue
        seen.add(key)
        merged.append(warning)
    return merged
