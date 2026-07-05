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

**2026-07-05 fix**: the first trim pass had a real bug — `ffmpeg -i in.mp3 -ss
X -t Y -af "afade=...st=Z..."` (seek placed *after* `-i`) resolves `afade`'s
`st=` against the *original* source timeline, not the trimmed clip's own
timeline. Where `Z` landed before the seek point `X`, the fade-out had
already "completed" before the clip even starts, silencing the entire
trimmed output. This affected `bgm/revelation.mp3` (13s of dead air at the
start), `ambient/clinical.mp3` (second half silent), and
`ambient/revelation.mp3` (100% silent). Separately, `sfx/dread_stinger.mp3`
grabbed silence because the actual hit in the source sound doesn't start at
t=0. Fixed by moving `-ss` *before* `-i` (true input seek, resets PTS to 0)
and, for the stinger, finding the actual onset first. All 12 files re-swept
with `ffmpeg ... -af silencedetect=noise=-35dB:d=0.3` — zero unexpected
silence remains (the one silence event on `clinical_stinger.mp3` is the
natural tail after its 0.16s beep, not a defect).

**2026-07-05 second fix**: Jay still heard `ambient/dread.mp3` as silent even
after the above fix. Root cause this time was different: the file wasn't
technically silent (`volumedetect` showed a normal -18dB mean, same as
everything else), but nearly all of its energy sat below 150Hz — filtering
above 200Hz dropped it to -42dB, and above 500Hz to -56dB. That's a deep
sub-bass drone that most laptop/phone speakers can't reproduce audibly,
mixed under narration at only 15% volume (`AMBIENT_VOLUME`) on top of that.
Swept all 12 files with `ffmpeg -af volumedetect` full-spectrum vs.
`highpass=f=200,volumedetect` to catch the same bass-only trap elsewhere —
found the same pattern (>10dB drop above 200Hz) in `bgm/dread.mp3` and
`ambient/revelation.mp3` and replaced both with better-balanced CC0 tracks.
`sfx/dread_stinger.mp3` also shows a real drop (11dB) but is left as-is: a
bass-heavy thump reads as an intentional "impact" character on a short
one-shot hit, not a missing-content bug on a sustained bed a listener stares
at for seconds.

| Mood | Role | File | Title | Author | Source |
|---|---|---|---|---|---|
| dread | bgm | `bgm/dread.mp3` | Action music loop with dark ambient drones (trimmed to 25s) | burning-mir | https://freesound.org/people/burning-mir/sounds/155139/ |
| dread | ambient | `ambient/dread.mp3` | Horror / alien world ambience (trimmed to 20s) | cabled_mess | https://freesound.org/people/cabled_mess/sounds/332249/ |
| dread | stinger | `sfx/dread_stinger.mp3` | HorrorSting1.mp3 (onset trimmed to 1.8s) | shelbyshark | https://freesound.org/people/shelbyshark/sounds/513332/ |
| clinical | bgm | `bgm/clinical.mp3` | Facility Hum Ambience Loopable | aSuperiorPotato | https://freesound.org/people/aSuperiorPotato/sounds/619320/ |
| clinical | ambient | `ambient/clinical.mp3` | Meditate Calm Scape (trimmed to 20s) | szegvari | https://freesound.org/people/szegvari/sounds/580073/ |
| clinical | stinger | `sfx/clinical_stinger.mp3` | Beep Space Button | GameAudio | https://freesound.org/people/GameAudio/sounds/220206/ |
| escalation | bgm | `bgm/escalation.mp3` | Intense loop | nicorico_120 | https://freesound.org/people/nicorico_120/sounds/808224/ |
| escalation | ambient | `ambient/escalation.mp3` | Emergency Siren (trimmed to 28s) | onderwish | https://freesound.org/people/onderwish/sounds/470504/ |
| escalation | stinger | `sfx/escalation_stinger.mp3` | Klaxon off axis short.wav | jameswrowles | https://freesound.org/people/jameswrowles/sounds/514982/ |
| revelation | bgm | `bgm/revelation.mp3` | Slow building synth - Riser Uplifter.wav (build-up skipped, trimmed to 19s) | WelvynZPorterSamples | https://freesound.org/people/WelvynZPorterSamples/sounds/621849/ |
| revelation | ambient | `ambient/revelation.mp3` | Repose Lost Melody (trimmed to 22s) | Stereo Surgeon | https://freesound.org/people/Stereo%20Surgeon/sounds/264425/ |
| revelation | stinger | `sfx/revelation_stinger.mp3` | Shock Stab 12 (trimmed to 2s) | nomiqbomi | https://freesound.org/people/nomiqbomi/sounds/578382/ |

All licensed **CC0 1.0 Universal** (public domain dedication) —
https://creativecommons.org/publicdomain/zero/1.0/ — no attribution legally
required, though Freesound etiquette appreciates it.

Until this pass is verified by ear, `sound_design_enabled` stays forced off
in the test suite (`tests/conftest.py`) so tests stay hermetic and don't
depend on these specific files' content. In a real deployment,
`sound_design_enabled=True` (the `Settings` default) now has real assets to
find — flip `YTFLOW_SOUND_DESIGN_ENABLED=true` in `.env` to enable.
