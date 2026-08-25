"""Post-generation pixel screens for image_node (Story 10.2, Story 14.2).

Two Qwen-VL questions about a rendered background, one call each, both asked only
about frames that are about to ship. **Is there a person in the scene?** (Story
10.2) — the card-compositing premise (Epic 8) is that the generated background is
unpopulated, and a card dropped onto a frame that already contains a body gives
the shot two figures (Jay's findings 5·12). **Can a person stand in it?** (Story
14.2) — a plate with no readable ground for a whole body makes the recompose pass
invent a floor, re-frame the room away, or wedge the card in as a floating bust;
7 of run 4b35c0ed's 33 cast-bearing shots broke that way.

Reuses Story 5.13's DashScope wiring (``_DASHSCOPE_VISION_ENDPOINT`` +
``character_vision_*`` settings) and mirrors ``scripts/label_location_plates.py``'s
call shape and brace-slice parse. No new dependency, no local VLM.

Fail-open by construction: this returns ``bool`` only when the model gave a
boolean verdict, and ``None`` for *everything* else — missing key, HTTP failure,
prose reply, non-boolean field, non-bytes input. It never raises, so neither
question can ever fail the image stage (AD-10).

NOT deterministic (Story 11.1's caveat): the request pins ``temperature=0``, but
the verdict still comes from a hosted model. The same frame replayed later can
read differently if the endpoint's model changes, so a replayed run can accept a
different rung of the seed ladder and ship a different image. The renders
themselves stay seed-deterministic; only *which* render is accepted is not.
"""

import base64
import json
import logging

import httpx

from yt_flow.config import Settings

logger = logging.getLogger(__name__)

# ponytail: duplicated literal, not an import. The same URL is defined at
# ``services/character_service._DASHSCOPE_VISION_ENDPOINT`` (keep them in sync),
# but importing it from there drags db.models / sqlmodel / image_search into
# ``yt_flow.pipeline.nodes.image``'s import graph — the first time pipeline/ would
# reach the DB layer.
_DASHSCOPE_VISION_ENDPOINT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

# The runtime question is NOT the plate labeler's question. Seeding asks "is this
# plate clean enough to bank"; here we ask "will a composited character card
# collide with a body already in this frame". A poster of a person cannot collide
# with a card, and SCP set dressing is full of depicted humans — counting those
# burns renders and then ships the frame anyway. Hence the explicit exclusions.
CHECK_PROMPT = """You are inspecting one background plate rendered for an SCP Foundation video.
It is supposed to be an EMPTY environment: a character cutout will be composited on top of it later.

Reply with a single JSON object and nothing else:
{"has_person": true|false, "notes": "one short sentence"}

Apply ONE rule: is a real body occupying space inside this frame?

has_person is true if a person, humanoid figure or creature is physically there in
the environment — standing, sitting, lying, passing through — including only part of
one (a face, a hand, a shoulder entering frame) and including one rendered as a dark
backlit shape, as long as the body itself is in the frame.

has_person is FALSE for everything that is not such a body: a depiction of a human
(anatomical diagram, medical illustration, drawing, poster, photograph on a wall,
painting), a statue, a bust, a mannequin, a skull or skeleton, an empty mirror, a
shadow or reflection whose body is outside the frame, or clothing with nobody in it.
When in doubt about whether a shape is a body or a texture, answer false."""


# Story 14.2 — the affordance question, and the SAME text `scripts/assess_plate_affordance.py`
# asks: that script's 33-plate calibration (7/33 broken, 1/25 false positive) is the only
# evidence this gate ships on, and a hand-copied second wording would silently invalidate
# it (`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). Jay's §4-2 decision is one schema
# for both callers, so the offline curator imports THIS constant rather than owning its own.
# ponytail: the constant lives here, on the `src` side, and the script imports it —
# the inverse (runtime importing `scripts/`) is not importable at all: `scripts/` is not
# a package, so it would need a runpy/importlib.util path load inside a library module.
# Only `standing_room` is read at runtime; the other four fields exist for the offline
# report, and dropping them from the text would change the question being asked.
STANDING_ROOM_PROMPT = """You are assessing whether a background plate can accept a standing human figure.

Answer ONLY about the room as photographed. Do not imagine changing the camera.

Reply with strict JSON, no prose:
{
  "standing_room": true/false,     // is there visible floor a full-body adult could stand on?
  "floor_fraction": 0.0-1.0,       // roughly how much of the frame is usable standing floor
  "camera_distance": "close-up" | "medium" | "wide",
  "best_spot": "left" | "center" | "right" | "none",
  "reason": "one short sentence"
}

standing_room is false when the frame is a close-up of an object or surface with no floor,
or when the only floor is too small/occluded for a whole person."""


async def background_has_person(image_bytes: bytes, settings: Settings) -> bool | None:
    """``True``/``False`` if the model gave a boolean verdict, else ``None`` (Story 10.2).

    ``None`` means *undecidable*, never "clean" — the caller must treat it as
    "not checked" and account for it, otherwise a dead guard reads as a clean pass.
    """
    # `[text, image]`: the order every number for THIS question was measured on
    # (Story 10.2/14.4). The affordance question below ships `[image, text]` because
    # that is the order ITS calibration used, and 14.2's review loop 1 measured the
    # ordering to be worth 3/7 vs 5/7 recall there. Whether this question moves too is
    # UNMEASURED — re-measuring it would invalidate 14.4's guard numbers, so it is
    # deferred work, not a silent flip.
    return await _bool_verdict(
        image_bytes, settings, CHECK_PROMPT, "has_person", "notes", "background person check",
        image_first=False)


async def plate_has_standing_room(image_bytes: bytes, settings: Settings) -> bool | None:
    """``True``/``False`` if the model judged the plate, else ``None`` (Story 14.2).

    ``None`` means *undecidable* and is emphatically NOT "no standing room": this
    endpoint refuses a whole class of SCP plates deterministically —
    `data_inspection_failed` on the sheet-covered-corpse plate `S00601`, reproduced
    twice, and the same plate is `None` for `background_has_person` too. Corpses,
    medical and mutilation imagery are standing output of this pipeline, so treating
    undecidable as failure would delete the cast of that class of shot forever.

    ``image_first=True`` is part of the contract, not a detail: sharing the prompt TEXT
    with `scripts/assess_plate_affordance.py` while splitting the request ENVELOPE is
    what the sharing existed to prevent. Re-measured on all 33 plates in review loop 1 —
    `[text, image]` recall 3/7 · FP 0/25, `[image, text]` recall 5/7 · FP 1/25, zero
    flips across repeated passes in either — so the order is a deterministic effect and
    the 5/7 this gate is judged on is only true image-first.
    """
    return await _bool_verdict(
        image_bytes, settings, STANDING_ROOM_PROMPT, "standing_room", "reason",
        "plate affordance check", image_first=True)


async def _bool_verdict(
    image_bytes: bytes, settings: Settings,
    prompt: str, field: str, note_field: str, label: str, *, image_first: bool,
) -> bool | None:
    """One image + one prompt -> one boolean field, or ``None``. Never raises.

    Every statement that can raise lives inside the ``try``, including the API-key
    read and the base64 encode: this function's contract is that it does not raise.

    ponytail: one body for both questions instead of a second 40-line copy. Two
    callers, so this is not an abstraction over one implementation; the ONLY things
    that differ are the prompt, the boolean field, the free-text sibling field that
    gets logged, the log label, and the part order — each question ships the order its
    own numbers were measured on, because the order changes the answer (see
    ``plate_has_standing_room``). ``image_first`` is keyword-only and has no default:
    a third question must state which envelope it was calibrated on.
    """
    try:
        if not settings.character_vision_api_key:
            return None
        b64 = base64.b64encode(image_bytes).decode("ascii")
        text_part = {"type": "text", "text": prompt}
        image_part = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        content = [image_part, text_part] if image_first else [text_part, image_part]
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                _DASHSCOPE_VISION_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
                json={
                    "model": settings.character_vision_model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": settings.character_vision_max_tokens,
                    # Story 11.1 keeps renders seed-deterministic; sampling the judge
                    # would make *which* render is accepted a coin flip on replay.
                    "temperature": 0,
                },
            )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        # Qwen-VL wraps JSON in ``` fences or prefaces it with prose, so slice the
        # outermost brace pair rather than special-casing fences (label_location_plates).
        if "{" not in text or "}" not in text:
            logger.warning("%s: no JSON object in reply: %.120r", label, text)
            return None
        verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
        value = verdict.get(field) if isinstance(verdict, dict) else None
        if not isinstance(value, bool):
            # Never coerce: "yes"/1/None must not become a confident verdict.
            logger.warning("%s: %s=%r is not boolean", label, field, value)
            return None
        # Story 14.4: the model's own one-sentence free text was already in the reply and
        # thrown away. It is the only place the frame's actual content is described — on
        # run 4b35c0ed's `S00201` the note named a framed anime portrait, i.e. the
        # depicted-person case, and we had n=1 because we never logged it. Zero cost, no
        # signature/return-type/prompt change; a corpus for 14.1's plate gate. Story 14.2
        # logs `reason` for the same reason: it names WHY a shot just lost its cast.
        logger.info("%s: %s=%r, %s=%.200r", label, field, value, note_field,
                    verdict.get(note_field))
        return value
    except Exception as exc:  # noqa: BLE001 — undecidable is a valid outcome; raising is not
        logger.warning("%s unavailable: %s", label, exc)
        return None
