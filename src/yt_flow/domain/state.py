"""Domain state types — the single shared type substrate for the pipeline.

Pure stdlib only. This module MUST NOT import any upper layer
(pipeline, services, db, api); the layered dependency rule is
`api -> services -> (pipeline | db) -> domain`. [AD-1]

These are TypedDicts, not Pydantic models, because LangGraph state is the
source of truth and must stay plain JSON-serializable for checkpointing. [AD-2]

Alongside the types this module also holds the **closed vocabularies and authored
cast/prompt tables** that more than one upper layer must agree on — stock cast keys and
roles, story archetypes, location keys, and the derived-entity looks plus their negative
suffix. They live here for the same reason: `services/` and `scripts/` both read them and
neither may import the other, so `domain` is the only shared floor. Each table keeps its
live tuning rationale in a comment and, where a sibling table must cover it, an `assert`
that fails at import rather than drifting silently.
"""

import re
from typing import Literal, NotRequired, TypedDict, get_args

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
GateState = Literal["pending", "approved", "rejected", "n/a"]
PromptVariant = Literal["A", "B"]
AngleName = Literal["front", "back", "side", "three_quarter"]
CastPosition = Literal["left", "center", "right"]
CastDepth = Literal["near", "mid", "far"]
CastPose = Literal["standing", "sitting"]  # closed v1 vocabulary — free-text special
                                            # poses arrive via Story 8.4's pose_hint field

# Story 8.8: closed micro-motion vocabulary the LLM selects per cast member,
# rendered procedurally by video_node. No amplitude/frequency knobs — those
# stay server-side constants (Interfaces rule: closed enums are the point).
CharacterMotionStyle = Literal["hold", "breath", "sway", "tremble", "pulse", "glitch"]
CharacterMotionEnergy = Literal["low", "medium", "high"]

# Story 8.9: closed screen-blocking vocabulary for a card's movement *through*
# the frame (distinct from 8.8's in-place idle motion above). Cinematic
# blocking, not a walk-cycle sim — video_node maps each mode to a
# deterministic x/y/scale curve over the shot's duration.
CharacterMovementMode = Literal[
    "anchored", "drift", "enter", "exit", "cross", "approach", "retreat",
]
CharacterMovementDirection = Literal["none", "left", "right", "in", "out"]
CharacterMovementPace = Literal["slow", "medium", "fast"]

# Story 12.4: closed narrative-archetype vocabulary. Research selects exactly one
# per run from the SOURCE's anatomy; `structure`/`writing` obey it. Closed because
# an unknown value would send the writer to a guide that doesn't exist — the
# deterministic resolution is `incident_first`, the pre-12.4 production behavior.
StoryArchetype = Literal[
    "incident_first",               # consequential event -> expanding mystery -> identity -> residue
    "discovery_log",                # dated evidence -> hypothesis shifts -> implication -> record gap
    "interview_testimony",          # testimony -> credibility fractures -> corroborated core -> uncertainty
    "containment_breach_realtime",  # baseline -> trigger -> compressed escalation -> aftermath
]
STORY_ARCHETYPES = get_args(StoryArchetype)  # source of truth: parser, guide lookup, tests, eval
STORY_ARCHETYPE_FALLBACK: StoryArchetype = "incident_first"

# Which SCP-document addendum types the supplied source actually contains. Research
# reports this inventory; it is evidence ABOUT the source, never a story choice.
SourceEvidenceKey = Literal[
    "incident_log", "experiment_log", "interview_log", "recovery_report", "dated_chronology",
]
SOURCE_EVIDENCE_KEYS = get_args(SourceEvidenceKey)

# The grounding gate (Story 12.4 AC2): an archetype whose framing device is absent
# from the source forces the writer to INVENT it — an interview that was never
# logged, a chronology that does not exist — and that loss lands on
# `article_fidelity` (the Story 8.8 SCP-096 -1.00 failure class). Any ONE of an
# archetype's listed keys satisfies it; an empty tuple means no evidence is needed.
# Deliberately narrow: widening this to make more SCPs "eligible" trades fidelity
# for diversity, which is the wrong direction.
# Key stays `str`: `missing_archetype_evidence` is deliberately total over
# unvalidated input, so it must be able to look up a value the parser rejected.
ARCHETYPE_REQUIRED_EVIDENCE: dict[str, tuple[SourceEvidenceKey, ...]] = {
    "incident_first": (),
    "discovery_log": ("recovery_report", "dated_chronology"),
    "interview_testimony": ("interview_log",),
    "containment_breach_realtime": ("incident_log",),
}
assert set(ARCHETYPE_REQUIRED_EVIDENCE) == set(STORY_ARCHETYPES)  # lockstep with the vocabulary
assert not set().union(*ARCHETYPE_REQUIRED_EVIDENCE.values()) - set(SOURCE_EVIDENCE_KEYS)


def missing_archetype_evidence(archetype: str, evidence: dict[str, bool] | None) -> tuple[str, ...]:
    """The evidence keys ``archetype`` needs and ``evidence`` does not report.

    Empty tuple == satisfied (including every unknown archetype, which the parser
    has already rejected on the vocabulary, and ``incident_first``, which needs
    nothing). Pure function of the two arguments — no I/O, no LLM. [AD-2]
    """
    required = ARCHETYPE_REQUIRED_EVIDENCE.get(archetype, ())
    if not required or any((evidence or {}).get(key) for key in required):
        return ()
    return required


# Story 12.6: closed vocabulary for what the critic is complaining ABOUT. Same
# pattern as StoryArchetype above, and for the same reason — but the defect it fixes
# is a gate defect, not a lookup defect. Run e5ed4b3a's critic was right three times
# (두 건은 Fact Sheet에 없는 단언, 한 건은 보고서 낭독 톤) and all three arrived at
# the human gate as one undifferentiated `unresolved_pass2` warning, because
# `scene_notes[].issue` is free text. A fabricated fact and a flat-pacing gripe need
# different actions, so they must be different categories at the gate.
# NOT a loosening of the critic: the judgment is unchanged, only its label is typed.
CriticIssueType = Literal[
    "ungrounded_claim",  # asserts a number/grade/date/event/capability the fact sheet lacks
    "substance_gap",     # technique applied correctly over nothing — criterion 6
    "report_tone",       # reads as a wiki/Foundation report rather than a story
    "pacing",            # flat or misallocated within/between scenes
    "hook",              # scene 1 opening fails to hold
    "ending",            # closing beat lands weak
    "other",             # deliberate escape hatch + the coercion target below
]
CRITIC_ISSUE_TYPES = get_args(CriticIssueType)
CRITIC_ISSUE_TYPE_FALLBACK: CriticIssueType = "other"

# Story 12.6: the OTHER judge's closed vocabulary — `issues[].type` from
# `scenario/review`. Verbatim from the enum on `prompts/scenario/review.md`'s
# `type:` line, and pinned against it by a test so the two cannot drift.
#
# Unlike the critic's, this one is never normalized on the way in: `review_step`
# does not schema-validate `issues[]`, so `type` reaches `_build_quality` as model
# free text clipped to 600 characters. Without a membership filter a 600-character
# Korean sentence renders at the gate as a "category". Membership only — a
# non-member is DROPPED, never coerced to a fallback, because there is no reviewer
# equivalent of `other` and inventing one would put an unread label on the gate.
ReviewIssueType = Literal[
    "fact_error", "missing_fact", "descriptor_violation", "invented_content",
    "ending_monotony", "designation_violation", "grounded_contradiction",
]
REVIEW_ISSUE_TYPES = get_args(ReviewIssueType)


def normalize_critic_issue_type(value: object) -> str:
    """Model-authored ``issue_type`` → a member of ``CRITIC_ISSUE_TYPES``.

    Total over any input, including ``None`` and a missing field: an unrecognised
    category must never fail a run that the critic itself judged fine, and it must
    never reach the gate raw. Pure function — the caller does the logging, because
    only it knows which scene the rejected value came from. [AD-2]

    Annotated ``object``, not ``str``, for the same reason ``missing_archetype_evidence``
    takes a bare ``str`` archetype: the totality is the contract. The one call site
    passes ``note.get("issue_type")`` straight off parsed YAML, so ``None``, an int
    and a mapping all arrive here by design.
    """
    candidate = " ".join(str(value or "").split()).lower()
    return candidate if candidate in CRITIC_ISSUE_TYPES else CRITIC_ISSUE_TYPE_FALLBACK


STOCK_CAST_KEYS = ("STOCK-d-class", "STOCK-researcher", "STOCK-security")  # single source of truth

# Story 8.19 — controlled role descriptions for the stock cast. Diagnosed cause:
# cast_decision received *bare* key names, so whenever a sentence mentioned any
# person it reached for the nearest stock key regardless of fit (villagers ->
# STOCK-d-class in an orange prison jumpsuit; "지역 경찰" -> STOCK-security as a
# facility guard). Naming the role makes "no stock role fits -> empty cast" a
# decidable call. Lives beside the keys so the prompt catalog cannot drift.
STOCK_CAST_ROLES: dict[str, str] = {
    "STOCK-d-class": "Foundation D-class test subject — orange prison jumpsuit with a stenciled number. Only ever inside Foundation custody.",
    "STOCK-researcher": "Foundation research staff — white lab coat, ID badge, clinical posture. Site personnel, never a civilian doctor.",
    "STOCK-security": "Foundation site security — black tactical vest and cap, alert posture. A facility guard, never civilian police or military.",
}
assert set(STOCK_CAST_ROLES) == set(STOCK_CAST_KEYS)  # the prompt catalog must cover every key

BANNED_STOCK_TOKEN = "SCP Foundation"
# Relocated from scripts/seed_stock_cast.py in Story 10.6: run_service needs this token,
# STOCK_NEGATIVE and DERIVED_DESCRIPTORS, and src/ must never import scripts/. The script
# re-exports all three, so seed.STOCK_NEGATIVE / seed.BANNED_STOCK_TOKEN still resolve.
#
# The token is deliberately absent from every authored cast descriptor — both
# DERIVED_DESCRIPTORS here and STOCK_DESCRIPTORS in scripts/seed_stock_cast.py: probing
# the live checkpoint showed that token alone is what collapsed these extras into a
# masked, hazmat-suited figure — with it the render is a skull mask or a visored helmet,
# without it an ordinary person, every other lever held constant. The wardrobe carries the
# setting instead.

# Story 10.6 — authored looks for `<scp_id>-<n>` derived entities (지적 15). Story 8.13
# built the derived-card path by inheriting the *base* entity's verbatim visual_descriptor
# plus one qualifier line, so SCP-049-2 rendered as a second hooded plague doctor in a
# white beak mask; 13 of the 66 cast slots in run 8a9a288b named it. (A slot count, not a
# defect count — nobody judged those 13 frames individually. The identity collision itself
# was judged on one same-seed render pair, `10-6-live-validation/`.) Meanwhile
# recompose_service.CARD_LOOKS already encoded the correct distinction ("torn surgical
# scrubs"). Only an authored look can carry that distinction into the card generator.
#
# Same discipline as STOCK_DESCRIPTORS, for the same live reasons: Danbooru tags lead
# (AnimagineXL is Danbooru-trained and "solo, 1boy" is its one-character control),
# purely affirmative (text encoders do not negate — "no mask" in a positive prompt
# summons masks, so every prohibition belongs in STOCK_NEGATIVE), one concrete
# reproducible hook feature so the non-front angles have something to hold, and hair/eye
# colour pinned concretely rather than as "dark".
#
# ponytail: a hand-authored table, and an unauthored derived key is skipped rather than
# guessed at — cast_decision.md's "a wrong card is far worse than no card", the same rule
# CARD_LOOKS already states. Guessing is what produced 지적 15. The natural upgrade is to
# mine the derived entity's look from the article via the existing research step; that is
# a new LLM path and its own story, not speculative code here.
DERIVED_DESCRIPTORS: dict[str, str] = {
    # SCP-049-2 is a *victim* SCP-049 reanimated — maskless and hoodless by definition,
    # which is exactly what the inherited descriptor destroyed. The hook feature is the
    # suture line; the scrubs are what CARD_LOOKS already promises the recomposer.
    "SCP-049-2": (
        "solo, 1boy, mature adult man, adult male body proportions, "
        "bare uncovered head, ordinary human face, visible nose and mouth, "
        "short dark brown hair, grey eyes, ashen grey skin, "
        "coarse black surgical sutures across the chest and forearms, "
        "torn pale green surgical scrubs, bare feet, "
        "slack expressionless features, stiff upright stance"
    ),
}
# `_ensure_derived_entity_cards` only ever looks up keys matching `<scp_id>-<n>`, so a key
# of any other shape here is dead weight that reads as authored. Same lockstep habit as
# STOCK_CAST_ROLES above.
assert all(re.fullmatch(r"SCP-\d+-\d+", key) for key in DERIVED_DESCRIPTORS), (
    "DERIVED_DESCRIPTORS keys must match the <scp_id>-<n> shape cast_decision emits"
)

# Suppression stays per-call and STOCK-scoped: the shared workflow's own negative
# node must stay mask-neutral because SCP-049 legitimately needs a mask.
#
# Deliberately short, and it names "face" zero times. CLIP negative conditioning is
# a token bag, not a set of phrases: a longer list that repeated "face" (full-face
# mask, face shield, hood covering face, monster face, horror creature face) got the
# word itself suppressed — STOCK-security rendered a blank white face with white
# blob hands and STOCK-d-class a black void with eye slits. Body/age terms
# (bald, child, shorts…) are steered affirmatively by the descriptor instead.
#
# LENGTH IS THE CONSTRAINT, not just wording. This list is appended to the workflow's
# own ~30-term negative, and every defect met along the way tempted one more clause.
# Twice now that ended badly: a version repeating "face" blanked the faces, and a
# ~40-term version turned all four STOCK-security cards into giant abstract polygons
# with a thumbnail-sized guard inside them. Keep it to the defects that actually
# recurred, steer everything else affirmatively from the descriptor, and re-add a term
# only when its defect comes back — never pre-emptively.
STOCK_NEGATIVE = (
    "skull mask, gas mask, helmet, visor, glowing eyes, monster, "
    "character sheet, multiple views, 2boys, "
    "child, 1girl, chibi"
)

# Story 8.5 — closed location key vocabulary for pre-built stock background
# plates. Closed because an LLM emitting an unknown key degrades to free-text
# image_prompt generation (parse_location_key), the existing safe behavior.
LocationKey = Literal[
    "containment-chamber",   # primary SCP holding cell — cold, concrete, reinforced
    "observation-room",      # scientists viewing through reinforced glass/monitors
    "corridor",               # facility hallway — dim utilitarian, pipes/conduits
    "interview-room",         # interrogation/interview — table, two chairs, bare walls
    "autopsy-room",           # medical/autopsy suite — stainless steel, drain channels
    "control-room",           # monitoring stations, banks of screens, consoles
    "facility-exterior",      # outside the Site — brutalist architecture, fences, night
    "server-room",            # data center rows, blinking lights, climate control
    "storage-vault",          # high-security artifact storage — lockers, cages, dim
    "medical-bay",            # infirmary/treatment room — bed, IV stands, clinical
    "cafeteria",              # mess hall — empty, fluorescent, unsettlingly normal
    "office",                 # researcher office/desk work
    "maintenance-tunnel",     # below-grade service access — pipes, steam, grates
    "entrance-checkpoint",    # security screening/airlock entry
]
LOCATION_KEYS = get_args(LocationKey)  # single source of truth for prompt template + parser


class CastMember(TypedDict):
    card_key: str          # CharacterModel.scp_id key: entity's scp_id, a STOCK_CAST_KEYS
                            # member, or a derived "<scp_id>-<n>"
    position: CastPosition  # horizontal slot in frame
    depth: CastDepth        # distance plane: drives scale, parallax amplitude, and stacking
    pose: CastPose          # body stance: selects which pose entry of the card library
    pose_hint: NotRequired[str]  # Story 8.4 on-demand key-art pose; advisory, falls back to `pose`
    pose_guide_key: NotRequired[str]  # Story 8.20 structural guide for the hint, from the closed
                                      # domain.pose.POSE_GUIDE_KEYS catalog. Absent == reference-only
                                      # editing. Never inferred from `pose_hint` — the hint stays the
                                      # action instruction, this names the geometry source.
    motion_style: NotRequired[CharacterMotionStyle]  # Story 8.8; absent == parser/resolver default "breath"
    motion_energy: NotRequired[CharacterMotionEnergy]  # Story 8.8; absent == parser/resolver default "medium"
    movement_mode: NotRequired[CharacterMovementMode]  # Story 8.9; absent == parser/resolver default "anchored"
    movement_direction: NotRequired[CharacterMovementDirection]  # Story 8.9; absent == default "none"
    movement_pace: NotRequired[CharacterMovementPace]  # Story 8.9; absent == default "slow"
    ground_y: NotRequired[float]  # Story 8.16; fraction of FRAME height the feet stand on.
                                  # Written only by inject_ground_resolver; absent == the
                                  # pre-8.16 centre anchor. Read by video.py's overlay AND
                                  # build_contact_shadow — one value, two consumers.
    occlusion_mask: NotRequired[str]  # Story 8.16; gray mask at the sprite's own pixel size,
                                      # multiplied into its alpha. Absent == nothing in front.


class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float


# Story 11.2: closed camera-motion vocabulary for ShotData.camera_movement.
# Lives here because scenario_chain (producer) and video (consumer) both
# already import domain.state and never each other — same placement logic as
# MOOD_VALUES living in sound_design.
CAMERA_ARCHETYPES = ("push_in", "pull_back", "drift", "locked", "shake")


class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]  # 0-based narration sentence indices; the image-gen unit [AD-5]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None   # one of prompts/scenario/visual_breakdown.md:215's 7 `camera_type`
                               # values, normalized to that spelling (`POV` is uppercase) by
                               # scenario_chain._resolve_camera_angle; None == off-vocabulary or
                               # absent. Story 14.0: a label of image_prompt's slot 1. It never
                               # reaches the background renderer's prompt (image.py assigns
                               # image_prompt only) but DOES feed cast-card angle selection
                               # (character_service._select_entity_angles -> angle_*_path PNG),
                               # so it is not render-inert.
                               # Story 14.1 added a THIRD consumer and Story 14.8 NARROWED it.
                               # 14.1 mapped this field to the plate `viewpoint` a
                               # stock-substituted shot required; that matching axis was retired
                               # on measurement (2026-08-30) and `image._select_plate` no longer
                               # reads the mapped value at all. What survives is MEMBERSHIP: a
                               # `close-up`/`POV` shot is refused a room plate (permanent by
                               # design) and an unrecognised string falls back to generation
                               # rather than being guessed. So with stock_plate_substitution_enabled
                               # on, this field decides WHETHER a shot may take an approved plate,
                               # not WHICH one — the which is `location_key` plus a sha256
                               # tie-break. See `14-8-plate-reuse-shipping/AXIS-CANDIDATES.md` ②.
    camera_movement: str | None  # one of CAMERA_ARCHETYPES (Story 11.2) | legacy free-text hint | None
    image_path: str | None       # background-only render (Story 8.3); character overlays live in `cast`
    depth_map_path: NotRequired[str | None]  # Story 11.5: monocular depth companion of THIS
                                  # shot's image_path, resolved once in the image stage and
                                  # consumed by the video stage's 2.5D parallax renderer.
                                  # NotRequired so pre-11.5 checkpoints still deserialize;
                                  # absent/None == no depth, renderer falls back (AC9).
    cast: list[CastMember]       # [] == background-only shot: downstream does NO overlay work at all
    location_key: LocationKey | None  # Story 8.5: STOCK plate to copy instead of generating.
                                       # None == use image_prompt (existing generation behavior).


class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None
    mood: str  # one of sound_design.MOOD_VALUES; drives BGM/ambient/stinger selection
    title: str  # chapter-card title for this scene; "" = card falls back to "- N -" (Story 5.17)
    kicker: str  # chapter-card one-line context below the title; "" = no kicker line (Story 5.17)
    display_narration: str  # pre-normalization original writing text; subtitles render this, TTS speaks `narration` (Story 5.18)


class SearchResult(TypedDict):
    """A single image search result from a provider (e.g. DuckDuckGo)."""
    url: str
    thumbnail_url: str
    title: str


class ReferenceImage(TypedDict):
    """A downloaded reference image record — persisted in DB, used in UI."""
    id: str
    character_id: str
    url: str
    local_path: str
    width: int | None
    height: int | None
    created_at: str


class Character(TypedDict):
    """SCP character definition — long-lived configuration, not per-run state. [AD-2]"""
    id: str
    scp_id: str
    canonical_name: str
    aliases: list[str]
    visual_descriptor: str | None
    style_guide: str | None
    image_prompt_base: str | None
    selected_image_path: str | None
    angle_front_path: str | None
    angle_back_path: str | None
    angle_side_path: str | None
    angle_three_quarter_path: str | None
    created_at: str
    updated_at: str


class CharacterCandidate(TypedDict):
    """A generated candidate image for a character angle. [AD-2]"""
    id: str
    character_id: str | None
    scp_id: str
    angle: str  # front, back, side, three_quarter
    candidate_num: int
    status: str  # pending, generating, ready, failed
    image_path: str | None
    created_at: str
    updated_at: str


# ── Story 12.3: scenario quality contract carried to the human gate ───────────
# Every field below is a plain JSON scalar/list/dict so the whole object survives
# a LangGraph checkpoint round-trip AND a `interrupt()` value AND the artifact
# endpoint's JSON encoding. No exceptions, prompt objects, or raw completions.


class RuleCounts(TypedDict):
    """Deterministic, code-derived measurements. Raw counts only — this story
    deliberately defines no failure threshold on them (Story 12.1 owns calibrated
    word budgets)."""
    character_count: int          # non-whitespace code points after NFKC
    sentence_count: int           # split_sentences() result count
    duplicate_sentence_count: int  # occurrences beyond the first, normalized
    repeated_4gram_count: int     # distinct 4-grams occurring >= 3 times


class SceneRuleCounts(RuleCounts):
    scene_num: int


class RepeatedPhrase(TypedDict):
    """Script-wide n-gram repeat evidence — counted across the whole script, so a
    phrase recycled between two scenes shows up (the actual slop signal)."""
    phrase: str
    count: int


class SlopPhraseHit(TypedDict):
    scene_num: int
    phrase: str
    count: int


class RuleMetrics(TypedDict):
    aggregate: RuleCounts          # pooled over every scene: character/sentence counts are
                                   # exactly the per-scene sums, while duplicates and repeated
                                   # n-grams additionally catch phrases recycled BETWEEN scenes
    scenes: list[SceneRuleCounts]
    repeated_ngrams: list[RepeatedPhrase]
    slop_phrase_hits: list[SlopPhraseHit]
    slop_vocabulary_version: int   # bump when the phrase tuple changes, so an old
                                   # checkpoint's hits stay interpretable
    # Story 12.6: the WRITTEN total 어절 (whitespace split, the same unit
    # `word_budget` is denominated in). The retention contract is enforced on the
    # declared outline only, and `writing.md` allows each scene ±20% — wider than
    # the ±15% band the total is held to — so an outline declaring a legal 370 can
    # ship 296. Measurement, not a gate: failing here would burn a whole run after
    # every writing call has already been paid for.
    total_words: int


class GroundedContradiction(TypedDict):
    """A narration/grounding conflict backed by quoted evidence. Every field is
    required — an unevidenced claim is rejected at parse time (AC4)."""
    scene_num: int
    narration_quote: str
    grounding_source: str   # which grounding artifact conflicts (entity_sheet / frozen_descriptor / scp_text)
    grounding_quote: str
    explanation: str
    correction: str
    # Story 12.8: "outline", "writing", or "unknown" — which stage minted the claim,
    # decided in code (`scenario._stamp_origin`), never by a model. The critic judges
    # narration against the SCP fact sheet while the writer is under orders to execute
    # the outline verbatim, so an outline fabrication used to arrive here billed to the
    # writer. "unknown" is the honest answer when there is no outline scene to compare
    # against; asserting "writing" there would be the producer claiming a determination
    # it never made. Absent on a pre-12.8 checkpoint.
    origin: NotRequired[str]
    # The `_overlap` score behind `origin`, preformatted ("0.29") because the gate
    # payload clips every field as text. Empty when `origin` is "unknown". Carried so a
    # judgment made against a 0.10 threshold is never read as a bare determination.
    origin_overlap: NotRequired[str]


class OutlineGroundingNote(TypedDict):
    """Story 12.8: one deterministic finding from `_check_fact_evidence`.

    Not a model claim and not a verdict — a pure-Python observation about the
    outline: a `quote` that is not a verbatim span of the source article
    (`quote_not_found`), a statement that raised the quote's certainty
    (`hedge_dropped`), an `event` field asserting what no fact statement in its scene
    supports (`event_unsupported`), or a run whose source article was not in scope at
    all (`source_unavailable`, `scene_num` 0).
    """
    scene_num: int
    code: str
    detail: str


class ReviewIssue(TypedDict):
    scene_num: int
    type: str
    severity: str
    description: str
    correction: str


class CriticSceneNote(TypedDict):
    scene_num: int
    issue_type: str  # a CRITIC_ISSUE_TYPES member — normalized in critic_step.parse
    issue: str
    suggestion: str
    # Story 12.8: same attribution as `GroundedContradiction`, and this is the channel
    # that actually carries grounding findings in practice — both live runs of that
    # story reported `grounded_contradictions: []` with every finding here instead.
    # Stamped only on the fact-typed notes (`ungrounded_claim`); a `pacing` note has no
    # fact to trace, so it carries neither key.
    origin: NotRequired[str]
    origin_overlap: NotRequired[str]


class ScenarioWarning(TypedDict):
    code: str      # "unresolved_pass2" — the stable identifier the UI keys on
    message: str   # Korean operator copy
    # Story 12.6: the distinct `issue_type`s behind this one warning, sorted. The
    # code stays `unresolved_pass2` (the UI and its tests key on it); the categories
    # are what tell the operator whether they are looking at a fact violation or a
    # craft one. Absent on a pre-12.6 checkpoint.
    categories: NotRequired[list[str]]
    # Story 12.8: the scenes whose grounding findings were minted by the OUTLINE, plus
    # the Korean sentence saying what that means for the operator — scene repair
    # cannot fix them, because `structure_step` runs once per run and the retry reuses
    # the same outline. Absent when nothing traced to the outline (and on a pre-12.8
    # checkpoint), so its presence is the signal.
    outline_originated: NotRequired["OutlineOriginated"]


class OutlineOriginated(TypedDict):
    scenes: list[int]
    note: str


class ScenarioQuality(TypedDict):
    """The scenario stage's final review/critic verdict, kept for the human gate.

    Written once per successful scenario run. ``warning`` is absent for a clean
    result — its presence IS the "approve knowingly" signal (AC2/AC3).
    """
    final_pass_index: int
    retry_scope: str
    review_overall_pass: bool
    critic_verdict: str
    critic_feedback: str
    rule_metrics: RuleMetrics
    grounded_contradictions: list[GroundedContradiction]
    review_issues: list[ReviewIssue]
    # Story 12.6: the critic's own typed evidence, beside the review's. Until now the
    # gate carried `critic_feedback` (a joined prose blob) and nothing else from the
    # critic, so a typed note had nowhere to land. Absent on a pre-12.6 checkpoint.
    critic_scene_notes: NotRequired[list[CriticSceneNote]]
    # Story 12.8: the outline's own evidence check, carried even on a clean pass — a
    # run can satisfy review and critic while still having shipped a statement whose
    # quote nobody could locate in the source. Absent on a pre-12.8 checkpoint.
    outline_grounding: NotRequired[list[OutlineGroundingNote]]
    # How many notes there were before `_MAX_QUALITY_ITEMS` capped the list above, so a
    # count rendered at the gate is the real one.
    outline_grounding_total: NotRequired[int]
    warning: NotRequired[ScenarioWarning]


# ── Story 13.1: run-warning contract carried to every human gate ──────────────
# Parallel to (never a replacement for) ScenarioQuality above: that one describes the
# scenario stage's review verdict, this one is the run-wide history of *non-fatal
# degradations* — a best-effort path that fell back instead of failing. A warning is
# never an error: it never populates PipelineState.error and never fails a run.
#
# The vocabulary is closed because the UI, the tests and the dedupe key all agree on
# these exact strings. Each code owns exactly one stage — see RUN_WARNING_CATALOG in
# domain/warnings.py, which pairs every code below with its stage and Korean operator
# copy and fails at import if the two drift.
RunWarningCode = Literal[
    # pre-graph / scenario-approval character provisioning (run_service)
    "vision_enrichment_failed",
    "character_provisioning_failed",
    "special_pose_cap_exceeded",
    "special_pose_generation_failed",
    "special_pose_guide_unapplied",     # Story 10.5 — guide rejected, rendered unconditioned
    "derived_entity_cap_exceeded",
    "derived_entity_generation_failed",
    "derived_entity_look_unauthored",   # Story 10.6 — no authored look, key skipped
    "character_card_i2i_fallback",      # provider i2i failed -> t2i, identity anchor lost
    "character_card_multi_figure",      # Story 10.8 — render held 0 or >=2 figures, card refused
    "character_descriptor_missing",     # Story 14.6 — no visual_descriptor, generation refused
                                        # rather than prompted with an empty subject. Fires from
                                        # `generate_candidates_from_reference`, the funnel every
                                        # card producer passes through, so it rides the pre-graph
                                        # 5.8 path (`_ensure_character_reference`) and the derived
                                        # -entity path alike — both build CharacterService with
                                        # `warnings=`, which is what makes `_warn` non-silent.
    # image_node
    "stock_plate_resolver_unavailable",
    "stock_plate_missing",
    "stock_plate_resolution_failed",
    "stock_plate_unfit",                # Story 14.1, reasons re-cut by 14.8 — approved plates
                                        # exist but none was assigned to this shot. The fallback
                                        # is generation, never a lost shot. `reason` is one of
                                        # FIVE, in the order `image._select_plate` decides them:
                                        #   unknown_framing     camera_angle absent, or a string
                                        #                       outside the vocabulary (a pre-14.0
                                        #                       checkpoint) — never guessed
                                        #   unservable_framing  close-up/POV: a room plate cannot
                                        #                       serve an object close-up or a
                                        #                       ceiling POV. Permanent by design
                                        #   no_metadata         no plate of that key carries BOTH
                                        #                       curators' person verdicts yet —
                                        #                       fail-open, an unjudged plate is
                                        #                       never picked. BOTH, not either:
                                        #                       half a verdict is not a verdict
                                        #                       (`test_d1_half_a_verdict_is_not_a
                                        #                       _verdict`). 14.8 moved this
                                        #                       sentinel off `viewpoint`, which the
                                        #                       selector stopped reading. THE NAME
                                        #                       IS KEPT although the trigger is now
                                        #                       narrower: "the metadata this
                                        #                       selector needs is missing" is still
                                        #                       exactly what it means, and a reason
                                        #                       string is written into finished
                                        #                       runs' warnings, so renaming it
                                        #                       rewrites history that is already on
                                        #                       disk
                                        #   plate_shows_person  every judged candidate is labelled
                                        #                       has_person / depicts_person.
                                        #                       Refusing to assign it is NOT
                                        #                       un-approving it
                                        #   no_standing_room    the shot carries cast, the
                                        #                       affordance knob is up and no
                                        #                       candidate has room for a standing
                                        #                       figure
                                        # RETIRED BY STORY 14.8, with the axis they named:
                                        # `no_viewpoint_match` and `partial_metadata`. The
                                        # selector matches on `location_key` alone now, so there
                                        # is no post-metadata match step for either to describe
                                        # and neither can fire. They are removed rather than kept
                                        # dormant so this list cannot document a retired axis as
                                        # if it shipped. Warnings already written to a finished
                                        # run's checkpoint keep their old string; nothing reads
                                        # this list to validate history.
    "background_guard_unscreened",      # Story 10.2 — guard wanted but not applied
    "plate_affordance_unusable",        # Story 14.2 — the plate's standing room (or the lack of a verdict on it)
    # subtitle_node
    "subtitle_alignment_fallback",
    # video_node (+ relight diagnostics)
    "cast_resolution_failed",
    "cast_card_missing",
    "cast_card_fallback",
    "relight_resolver_unavailable",
    "relight_pair_skipped",
    "relight_failed",
    "relit_sprite_invalid",
    "recompose_preflight_failed",       # Story 10.1d — ComfyUI misconfigured, whole run on overlay
    "recompose_shots_degraded",          # Story 10.1e — preflight passed but some shots fell back
    "recompose_sidecar_failed",          # Story 14.3 — the frame shipped, its attribution did not
]


class RunWarning(TypedDict):
    """One non-fatal degradation, JSON-safe end to end (checkpoint -> interrupt
    payload -> SSE frame -> artifact response -> UI).

    ``context`` carries the narrowest identifiers the producer had — ``scene_num``,
    ``shot_id``, ``card_key``, ``location_key``, ``pose_hint``, counts — plus at most
    one bounded ``detail`` string. ``detail`` is diagnostic only: it is never rendered
    as primary UI copy and is deliberately excluded from warning identity, because
    exception text varies between attempts and would defeat deduplication.
    """
    code: RunWarningCode
    stage: StageName
    message: str          # short Korean operator copy, from RUN_WARNING_CATALOG
    context: NotRequired[dict[str, str | int | float | bool]]


class PipelineState(TypedDict):
    run_id: str
    scp_id: str
    scp_text: str
    scenes: list[SceneState]
    video_path: str | None
    current_stage: StageName
    gate_states: dict[StageName, GateState]
    prompt_variant: PromptVariant | None
    error: str | None
    ending_credit_error: NotRequired[str | None]  # Story 5.20 — absent unless the run attempted the ending credit (cc_attribution=True); presence signals attempted
    scenario_quality: NotRequired[ScenarioQuality | None]  # Story 12.3 — final review/critic
                                   # verdict + deterministic metrics, read by the scenario gate.
                                   # NotRequired so pre-12.3 checkpoints still deserialize;
                                   # None == cleared by a retry/restart (never "clean").
    story_archetype: NotRequired[StoryArchetype | None]  # Story 12.4 — the narrative template
                                   # research selected for THIS run. Observability only:
                                   # non-authoritative outside LangGraph state, never read back
                                   # to steer generation. None == not generated / cleared.
    run_warnings: NotRequired[list[RunWarning]]  # Story 13.1 — non-fatal degradation history
                                   # for the whole run, shown at every human gate. NotRequired
                                   # so pre-13.1 checkpoints still deserialize; every reader
                                   # uses state.get("run_warnings", []). No reducer: producers
                                   # return the whole merged list (domain.warnings.merge).
    story_archetype_fallback_used: NotRequired[bool]  # Story 12.4 — True when the selection was
                                   # resolved deterministically (invalid value or missing source
                                   # evidence) instead of chosen. Required as its own signal:
                                   # post-resolution validity is always true and would hide drift.
