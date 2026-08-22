"""Post-generation background screen for image_node (Story 10.2).

One Qwen-VL call per rendered background answering a single question: is there a
person *in the scene*? The card-compositing premise (Epic 8) is that the generated
background is unpopulated — a card dropped onto a frame that already contains a
body gives the shot two figures (Jay's findings 5·12).

Reuses Story 5.13's DashScope wiring (``_DASHSCOPE_VISION_ENDPOINT`` +
``character_vision_*`` settings) and mirrors ``scripts/label_location_plates.py``'s
call shape and brace-slice parse. No new dependency, no local VLM.

Fail-open by construction: this returns ``bool`` only when the model gave a
boolean verdict, and ``None`` for *everything* else — missing key, HTTP failure,
prose reply, non-boolean field, non-bytes input. It never raises, so the caller's
"is this frame populated" question can never fail the image stage (AD-10).

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


async def background_has_person(image_bytes: bytes, settings: Settings) -> bool | None:
    """``True``/``False`` if the model gave a boolean verdict, else ``None``.

    ``None`` means *undecidable*, never "clean" — the caller must treat it as
    "not checked" and account for it, otherwise a dead guard reads as a clean pass.

    Every statement that can raise lives inside the ``try``, including the API-key
    read and the base64 encode: this function's contract is that it does not raise.
    """
    try:
        if not settings.character_vision_api_key:
            return None
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content = [
            {"type": "text", "text": CHECK_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
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
            logger.warning("background person check: no JSON object in reply: %.120r", text)
            return None
        verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
        value = verdict.get("has_person") if isinstance(verdict, dict) else None
        if not isinstance(value, bool):
            # Never coerce: "yes"/1/None must not become a confident verdict.
            logger.warning("background person check: has_person=%r is not boolean", value)
            return None
        # Story 14.4: the model's own one-sentence `notes` was already in the reply and
        # thrown away. It is the only place the frame's actual content is described — on
        # run 4b35c0ed's `S00201` the note named a framed anime portrait, i.e. the
        # depicted-person case, and we had n=1 because we never logged it. Zero cost,
        # no signature/return-type/CHECK_PROMPT change; a corpus for 14.1's plate gate.
        logger.info("background person check: has_person=%r, notes=%.200r",
                    value, verdict.get("notes"))
        return value
    except Exception as exc:  # noqa: BLE001 — undecidable is a valid outcome; raising is not
        logger.warning("background person check unavailable: %s", exc)
        return None
