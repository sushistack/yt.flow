# Stage 3.4: Cast Decision

Decide which pre-made character cards appear in each sentence's shot. This
runs BEFORE the shot is composed — the visual composer will be told exactly
what you decide here and will never re-decide it, so get it right now.

## Card Vocabulary

- **This run's entity `card_key`**: {{scp_id}}
- **Fixed stock cast `card_key` values**: {{stock_cast_keys}}
- A duplicate/offshoot of the entity uses `<scp_id>-<n>`, e.g. `SCP-049-2`.

## Task

{{parse_error}}

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
- optional `movement_mode`: `"anchored"` (default, omit the field entirely) |
  `"drift"` | `"enter"` | `"exit"` | `"cross"` | `"approach"` | `"retreat"` —
  how this card moves THROUGH the frame during the shot, distinct from
  `motion_style`'s in-place idle motion above. This is cinematic blocking, not
  a walk-cycle: a card never actually strides, it eases into/out of/across the
  frame or scales toward/away from camera.
  - Omit entirely (`anchored`) for almost every shot — a character standing,
    sitting, or gesturing in place needs no `movement_mode` at all.
  - `"drift"` for a small composition shift within the same slot — restless
    repositioning, not a real entrance/exit.
  - `"enter"` / `"exit"` only for a motivated shot beat where someone visibly
    arrives or leaves the frame (a door, a retreat, an ambush).
  - `"cross"` only when the shot's whole point is a subject crossing from one
    side of the frame to the other.
  - `"approach"` for a looming/threat reveal — the subject reads as coming
    closer to camera over the shot.
  - `"retreat"` for withdrawal or recession — the subject reads as moving away.
  - Use `movement_mode` sparingly, at most once or twice per scene. If nothing
    in the sentence calls for the card to travel, omit it.
- optional `movement_direction`: `"none"` | `"left"` | `"right"` | `"in"` |
  `"out"` — only meaningful together with `movement_mode`; omit unless you
  also set `movement_mode`. Leave unset (or `"none"`) to let the renderer pick
  a sensible default for the chosen mode.
- optional `movement_pace`: `"slow"` | `"medium"` | `"fast"` (default `"slow"`)
  — how quickly the movement resolves; omit unless you also set `movement_mode`.

Multiple people can share a sentence (e.g. the entity and a D-class facing
each other) — give each their own cast entry with distinct `position`/`depth`
reflecting the composition you'd want.

Use `pose_hint` sparingly: no more than about 3 distinct hints in the whole
scene, and never as a substitute for the required base `pose`.

## Composition

Choose `position`/`depth` deliberately — do not default every entry to
`center`/`near`.

- **Position (rule-of-thirds first):** default a lone subject to `left` or
  `right`. Reserve `center` for a deliberate symmetry beat — head-on
  confrontation, ritual/reveal, direct-to-camera address — never a fallback.
- **Anti-repetition:** don't repeat the same `position` for the same
  `card_key` across consecutive sentences unless the character hasn't moved
  and the beat is one continuous shot. Alternate sides across the scene.
- **Multi-cast:** two people facing each other take opposing thirds
  (`left`+`right`), never both `center` or stacked.
- **Three or more:** stagger across all three thirds (`left`/`center`/`right`)
  — never leave two adjacent slots empty or stack multiple people in the
  same slot.
- **Depth, calibrated:**
  - `far` = establishing/environmental presence, a small figure (roughly
    30-50% of frame height) — use it whenever the beat is about scale or
    environment, not only rarely.
  - `mid` = the normal storytelling distance — default for most shots.
  - `near` = intentional intimacy or threat only, not a default.
  - Across a scene, expect mostly `mid`, `near` reserved for emphasis beats,
    and `far` used whenever the beat calls for it — not near-zero.

## Output Format

Output ONLY valid YAML, no markdown fences, no commentary. This example
demonstrates the expected spread — vary position/depth per beat, don't copy
these exact values:

```yaml
shots:
  - sentence: 1
    cast:
      - card_key: "{{scp_id}}"
        position: "left"
        depth: "far"
        pose: "standing"
        motion_style: "breath"
        motion_energy: "low"
  - sentence: 2
    cast:
      - card_key: "STOCK-d-class"
        position: "right"
        depth: "mid"
        pose: "sitting"
        motion_style: "tremble"
        motion_energy: "medium"
  - sentence: 3
    cast:
      - card_key: "{{scp_id}}"
        position: "right"
        depth: "near"
        pose: "standing"
        motion_style: "sway"
        motion_energy: "medium"
      - card_key: "STOCK-d-class"
        position: "left"
        depth: "near"
        pose: "standing"
        motion_style: "tremble"
        motion_energy: "high"
  - sentence: 4
    cast:
      - card_key: "{{scp_id}}"
        position: "center"
        depth: "near"
        pose: "standing"
        pose_hint: "reaching toward camera"
        motion_style: "pulse"
        motion_energy: "high"
  - sentence: 5
    cast: []
```

`shots` MUST have exactly {{sentence_count}} entries, one per sentence number
1..{{sentence_count}}, in any order.

## Scene Context

- **Characters Present** (from the scene outline): {{characters_present}}

## Numbered Sentences

{{numbered_sentences}}

**Total sentences: {{sentence_count}}**
