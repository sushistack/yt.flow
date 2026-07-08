# Stage 3.4: Cast Decision — Scene {{scene_num}}

Decide which pre-made character cards appear in each sentence's shot. This
runs BEFORE the shot is composed — the visual composer will be told exactly
what you decide here and will never re-decide it, so get it right now.

## Card Vocabulary

- **This run's entity `card_key`**: {{scp_id}}
- **Fixed stock cast `card_key` values**: {{stock_cast_keys}}
- A duplicate/offshoot of the entity uses `<scp_id>-<n>`, e.g. `SCP-049-2`.

## Scene Context

- **Characters Present** (from the scene outline): {{characters_present}}

## Numbered Sentences

{{numbered_sentences}}

**Total sentences: {{sentence_count}}**

## Task

For EACH sentence, decide who is physically visible in that sentence's shot:

- **Entity present** → a cast entry with `card_key: "{{scp_id}}"`.
- **D-class / researcher / security personnel present** → one entry per
  person, `card_key` from the stock list above.
- **No one in frame** (empty room, object close-up, aftermath detail,
  establishing shot) → `"cast": []`. This is common and correct for many
  sentences — do not force a person into every shot just because the entity
  or cast is available.

Each cast entry needs these fields:
- `card_key`: one of the values above
- `position`: `"left"` | `"center"` | `"right"` — horizontal frame slot
- `depth`: `"near"` | `"mid"` | `"far"` — distance from camera (also drives
  scale and stacking order)
- `pose`: `"standing"` | `"sitting"` — `"sitting"` for interview/
  interrogation, containment-chair, desk/console work, medical restraint, or
  a collapsed/slumped beat; `"standing"` otherwise. No other values exist.
- optional `pose_hint`: short free-text English, maximum 6 words, only for
  rare key-art beats that `standing` or `sitting` cannot express, such as
  `"kneeling over a corpse"`, `"lying on operating table"`, or `"reaching
  toward the camera"`. Most cast entries MUST omit it. Even when you include
  `pose_hint`, still set `pose` to the nearest base pose so rendering can
  fall back cleanly.
- `motion_style`: `"hold"` | `"breath"` | `"sway"` | `"tremble"` | `"pulse"` |
  `"glitch"` — how this card moves on screen. Choose sparingly:
  - `"breath"` (default) for ordinary standing/sitting figures — a small
    living presence, nothing more.
  - `"sway"` for a figure with a bit more restless weight-shift than plain
    breathing (pacing, unease, standing guard).
  - `"tremble"` for anxious, hurt, or restrained subjects.
  - `"pulse"` or `"glitch"` only for a genuinely supernatural or anomalous
    visual beat (the entity manifesting, a camera-feed glitch moment) —
    rare, not a default flourish.
  - `"hold"` for statues, corpses, or anything explicitly immobile/dead —
    no idle motion at all.
- `motion_energy`: `"low"` | `"medium"` (default) | `"high"` — intensity of
  whichever `motion_style` you picked. Reach for `"high"` only when the beat
  itself calls for it (panic, violent tremor); most shots are `"medium"`.

Multiple people can share a sentence (e.g. the entity and a D-class facing
each other) — give each their own cast entry with distinct `position`/`depth`
reflecting the composition you'd want.

Use `pose_hint` sparingly: no more than about 3 distinct hints in the whole
scene, and never as a substitute for the required base `pose`.

## Output Format

Output ONLY JSON, no markdown fences, no commentary:

```json
{
  "shots": [
    {"sentence": 1, "cast": [{"card_key": "{{scp_id}}", "position": "center", "depth": "near", "pose": "standing", "pose_hint": "reaching toward camera", "motion_style": "breath", "motion_energy": "medium"}]},
    {"sentence": 2, "cast": []}
  ]
}
```

`shots` MUST have exactly {{sentence_count}} entries, one per sentence number
1..{{sentence_count}}, in any order.
