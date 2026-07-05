# Sound Design Assets (Story 7.1)

`sound_design.py` expects 12 CC0-licensed files here, one per mood × role:

```
data/audio/bgm/{dread,clinical,escalation,revelation}.mp3        # 10-30s seamless loop
data/audio/ambient/{dread,clinical,escalation,revelation}.mp3    # 10-30s seamless loop
data/audio/sfx/{dread,clinical,escalation,revelation}_stinger.mp3  # 1-2s one-shot
```

## Status: sourced (2026-07-05)

All 12 files below were sourced from Freesound, filtered to `license:"Creative
Commons 0"` (verified per-track by checking the sound's page links to
`creativecommons.org/publicdomain/zero/1.0/`, not Freesound's non-CC0
"Sampling+" or attribution licenses). Downloaded via Freesound's public
`-hq.mp3` preview CDN (`cdn.freesound.org/previews/...`), which is served to
anonymous visitors without login — no Freesound account/API key was used.
Files were trimmed to spec length with `ffmpeg` (loop-safe in/out fades on
bgm/ambient, a fade-out at the cut point on stingers trimmed from a longer
source) — trimming does not affect CC0 status (CC0 waives all rights,
including the right to make modified copies).

Human note: track selection was based on title/tag/pack metadata (e.g.
"Horror" pack, "Facility Hum Ambience Loopable"), not by ear — nobody has
listened to these yet. Treat this as a first pass; do a listening pass before
relying on this for a real release, and re-tune `BGM_VOLUME` /
`SIDECHAIN_*` in `sound_design.py` by ear per the still-open Live Validation
task.

| Mood | Role | File | Title | Author | Source |
|---|---|---|---|---|---|
| dread | bgm | `bgm/dread.mp3` | Drone Loop (Fixed) | Fission9 | https://freesound.org/people/Fission9/sounds/567220/ |
| dread | ambient | `ambient/dread.mp3` | Paranoia | Fission9 | https://freesound.org/people/Fission9/sounds/490958/ |
| dread | stinger | `sfx/dread_stinger.mp3` | HorrorSting1.mp3 (trimmed to 1.8s) | shelbyshark | https://freesound.org/people/shelbyshark/sounds/513332/ |
| clinical | bgm | `bgm/clinical.mp3` | Facility Hum Ambience Loopable | aSuperiorPotato | https://freesound.org/people/aSuperiorPotato/sounds/619320/ |
| clinical | ambient | `ambient/clinical.mp3` | Meditate Calm Scape (trimmed to 20s) | szegvari | https://freesound.org/people/szegvari/sounds/580073/ |
| clinical | stinger | `sfx/clinical_stinger.mp3` | Beep Space Button | GameAudio | https://freesound.org/people/GameAudio/sounds/220206/ |
| escalation | bgm | `bgm/escalation.mp3` | Intense loop | nicorico_120 | https://freesound.org/people/nicorico_120/sounds/808224/ |
| escalation | ambient | `ambient/escalation.mp3` | Emergency Siren (trimmed to 28s) | onderwish | https://freesound.org/people/onderwish/sounds/470504/ |
| escalation | stinger | `sfx/escalation_stinger.mp3` | Klaxon off axis short.wav | jameswrowles | https://freesound.org/people/jameswrowles/sounds/514982/ |
| revelation | bgm | `bgm/revelation.mp3` | Slow building synth - Riser Uplifter.wav (trimmed to 25s) | WelvynZPorterSamples | https://freesound.org/people/WelvynZPorterSamples/sounds/621849/ |
| revelation | ambient | `ambient/revelation.mp3` | Em Pentatonic Pads 80bpm.WAV (trimmed to 22s) | BuytheField | https://freesound.org/people/BuytheField/sounds/436130/ |
| revelation | stinger | `sfx/revelation_stinger.mp3` | Shock Stab 12 (trimmed to 2s) | nomiqbomi | https://freesound.org/people/nomiqbomi/sounds/578382/ |

All licensed **CC0 1.0 Universal** (public domain dedication) —
https://creativecommons.org/publicdomain/zero/1.0/ — no attribution legally
required, though Freesound etiquette appreciates it.

Until this pass is verified by ear, `sound_design_enabled` stays forced off
in the test suite (`tests/conftest.py`) so tests stay hermetic and don't
depend on these specific files' content. In a real deployment,
`sound_design_enabled=True` (the `Settings` default) now has real assets to
find — flip `YTFLOW_SOUND_DESIGN_ENABLED=true` in `.env` to enable.
