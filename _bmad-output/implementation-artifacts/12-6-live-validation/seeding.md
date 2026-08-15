# Story 12.6 — Langfuse seeding (DEV MODE, straight to `production`)

Per `CLAUDE.md` / `docs/PROMPT_POLICY.md`'s DEV-MODE banner: prompt edits seed
straight to `production`, no A/B and no promotion gate.

## Pre-check — what would change

`--dry-run` only lists names + variables; it does not diff against Langfuse. So the
change set was computed with the script's own `build_manifest` + `client.get_prompt`,
run 2026-08-15 against `langfuse.eli.kr`:

```
CHANGED:
   scenario/critic_agent
   scenario/review
   scenario/structure
   scenario/writing
MISSING (would be created):
unchanged: 16
```

Exactly the four prompts this story edits. **`character/angle_selection` and
`character/generation` were NOT drifted** at seeding time — the story's Task 6
warning (2026-08-15) is stale; both compared byte-identical to their `production`
versions and were skipped. Nothing rode along.

`--dry-run` also confirmed `scenario/structure` now carries the seven new variables:

```
scenario/structure: vars=['archetype_guide', 'format_guide', 'glossary_section',
  'max_closing_word_pct', 'max_opening_word_pct', 'min_budget_spread', 'parse_error',
  'research_packet', 'scene_word_budget_max', 'scene_word_budget_min', 'scp_id',
  'scp_visual_reference', 'story_archetype', 'target_duration',
  'total_word_budget_max', 'total_word_budget_min']
```

## Seed

```
uv run python scripts/migrate_prompts.py --label production --source prompts
```

```
created: scenario/critic_agent
created: scenario/review
created: scenario/structure
created: scenario/writing
skipped: (the other 16)
```

Exit 0.
