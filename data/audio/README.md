# Sound Design Assets (Story 7.1)

`sound_design.py` expects 12 CC0-licensed files here, one per mood × role:

```
data/audio/bgm/{dread,clinical,escalation,revelation}.mp3        # 10-30s seamless loop
data/audio/ambient/{dread,clinical,escalation,revelation}.mp3    # 10-30s seamless loop
data/audio/sfx/{dread,clinical,escalation,revelation}_stinger.mp3  # 1-2s one-shot
```

## Status: not yet sourced

**This directory is empty pending human sourcing.** Verifying a track is
genuinely CC0 (not CC-BY, not "free for personal use") is a licensing
judgment call — sourcing and license-verifying these 12 files is a human
step, not something an AI coding session should do autonomously. See
Story 7.1's Dev Agent Record / Saved Questions for the full rationale.

Until these files exist, `sound_design_enabled` is forced off in the test
suite (`tests/conftest.py`) so tests stay hermetic. In a real deployment,
`sound_design_enabled=True` (the `Settings` default) will cause every video
run to fail fast in `validate_mood_assets` with a clear `FileNotFoundError`
naming the missing file — set `YTFLOW_SOUND_DESIGN_ENABLED=false` in `.env`
until the library is populated.

## Sourcing

Curated CC0 libraries (e.g. Pixabay Audio, Freesound filtered to CC0) —
same posture as `data/voices/sutak.mp3`. Once sourced, record each file's
source URL + license here (same evidence posture as Story 5.5's SCP
reference-image sourcing).
