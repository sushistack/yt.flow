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
"Horror" pack, "Facility Hum Ambience Loopable"), not by ear. Treat this as a
first pass; do a listening pass before relying on this for a real release, and
re-tune `BGM_VOLUME` / `SIDECHAIN_*` in `sound_design.py` by ear per the
still-open Live Validation task.

**Listening status (updated 2026-08-09).** The original sentence here said
"nobody has listened to these yet"; that is no longer true of the whole
library, and leaving it unqualified would undercut the controls the 10.7 notes
below lean on. Judged by a human (Jay, 2026-08-09, in a real render of the real
filter graph): `ambient/escalation.mp3` and `sfx/escalation_stinger.mp3`, both
swapped as a result, plus `bgm/escalation.mp3`, `sfx/dread_stinger.mp3`,
`sfx/clinical_stinger.mp3` and `sfx/revelation_stinger.mp3` heard in that mix
and *not* complained about — which is the whole basis on which those three
stingers are used as acceptance controls. **Still unlistened:** `bgm/dread.mp3`,
`bgm/clinical.mp3`, `bgm/revelation.mp3`, `ambient/dread.mp3`,
`ambient/clinical.mp3`, `ambient/revelation.mp3`. "Not complained about while
audible in a mix" is a weaker claim than "auditioned in isolation" — see the
`clinical_stinger.mp3` caveat in `deferred-work.md`.

**Duration convention.** Two numbers exist for every file and they differ by up
to ~0.03 s: `ffprobe -show_entries format=duration` reports the *container*
duration (includes the mp3 encoder delay/padding frames), while `measure.py`
reports the *decoded sample length* at 22050 Hz. Unless a line says otherwise,
**every duration in this file and in the 10.7 tables is the decoded length**,
because that is what the analysis frames are counted over. For the record on the
files this document argues about: `ambient/escalation.mp3` 24.00 decoded /
24.03 container, the retired siren 28.00 / 28.03, the retired klaxon 1.98 /
2.01, `sfx/escalation_stinger.mp3` 1.80 / 1.83.

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

**2026-08-09 escalation ambient swap (Story 10.7, Jay's finding 13 — "이상한 싸이렌
소리 좀 없애줘")**: `ambient/escalation.mp3` was literally Freesound "Emergency
Siren" (onderwish/470504) looped forever under every escalation scene, chapter
card and black hold. Measured signature: a narrowband wail parked in the
700–1000 Hz band — 81.7% of analysed frames had their spectral peak inside that
band and 76.8% of the file's total spectral energy sat there. Replaced by
"Factory Dark Fantasy Atmo" (szegvari/577079, CC0 verified on the sound's own
page), which reads as facility/industrial unease rather than an alarm. The 44–68s
window of the 70s source was chosen because it is the flattest stretch (per-second
RMS −14.7 to −18.7 dB, no silence), so the loop does not pump:

```
ffmpeg -y -ss 44 -i src577079.mp3 -t 24 \
  -af "volume=-0.7dB,afade=t=in:st=0:d=0.04,afade=t=out:st=23.96:d=0.04" \
  -ar 44100 -ac 2 -c:a libmp3lame -b:a 128k data/audio/ambient/escalation.mp3
```

`-ss` is before `-i` — see the 2026-07-05 fix above; the post-`-i` form silently
mis-times `afade` and already destroyed three files in this library once. The
40 ms fades are **click guards, not fades** — see the 2026-08-09 third fix below
for why the 1.5 s fades this note originally shipped were a defect. Result vs the
outgoing file: 24.00s, mean −17.3 dB (was −17.3 — matched exactly), max −1.7 dB
(was −3.5), above-200 Hz drop 2.7 dB (well inside the ≤10 dB bass-trap rule from
the second 2026-07-05 fix), zero `silencedetect` events, 0.0% of frames peaking in
the 700–1000 Hz wail band and 4.7% of energy there.

Loudness was matched deliberately, on the **mean**. The bed `amix` in
`sound_design.py` runs at ffmpeg's default `normalize=1`, which divides the sum by
the number of *active inputs* regardless of their level — so a quieter file does
not get compensated for; it simply arrives ~9.5 dB down like everything else and
then sits that much lower under the narration duck. (The earlier wording here said
`normalize=1` would make a quieter file "vanish"; the conclusion — match the
outgoing loudness — is right, the stated mechanism was not. `normalize=1` is
level-blind.) The new bed's **peak** is 1.8 dB hotter than the outgoing file's
(−1.7 vs −3.5) while its mean is identical, i.e. a smaller crest factor. That is
the right trade here and is deliberate, not an oversight: on the loudest path this
bed touches — `_compose_chapter_card`, which sums at `normalize=0` — `volume=0.15`
puts its peak at **−18.2 dBFS**, nowhere near clipping, so peak has no headroom
consequence for a *bed* and mean is what decides audibility. The stinger below was
matched on **peak** instead, for the opposite reason: it is a one-shot at
`STINGER_VOLUME = 0.5` on that same `normalize=0` path, where the transient's
height is exactly what jumps out at a chapter boundary.

Verified in a real render of the real filter graph (not on the raw asset): in the
scene-path A/B the isolated bed sits at **−37.2 dBFS** with both new assets vs
**−36.2 dBFS** with both old ones, i.e. 1.0 dB quieter overall — and essentially
all of that 1.0 dB is the stinger swap below (the new hit's mean is 0.9 dB under
the klaxon's), not the ambient, whose file mean matches the siren's to 0.0 dB.
(The −36.6 dBFS quoted here before round 2 was measured against a `before.wav`
that still carried the old klaxon on only one side; it is stale and has been
re-derived.) Evidence, A/B renders and the one-command re-derivation script:
`_bmad-output/implementation-artifacts/10-7-live-validation/`. The escalation
*stinger* (klaxon) was deliberately left alone; it is a 2s one-shot, not the wail.
**That call was wrong — see the next note.**

**2026-08-09 escalation stinger swap (Story 10.7 round 2, still Jay's finding 13)**:
after the ambient swap above, Jay listened to the A/B and said "사이렌 그대로" — the
siren was still there, even though the new bed measures 0% of frames peaking in the
wail band. Escalation plays three cues, so each one was isolated at its real mix gain
into `10-7-live-validation/identify/` and Jay's ear pinned the third:
`sfx/escalation_stinger.mp3`, Freesound "Klaxon off axis short.wav"
(jameswrowles/514982). It is a 1.98s **pure 560 Hz alarm honk** — 98.1% of its
analysed frames have their loudest FFT bin inside 200–1500 Hz, and essentially
nothing below 200 Hz (0.0002% of its total spectral energy; the round-2 table's
`0.0` is a rounded column, not an absolute) — and it is the loudest cue in the
whole system (`STINGER_VOLUME = 0.5` vs 0.25 bgm / 0.15 ambient).

**Where it actually fired — corrected 2026-08-09.** This note originally said the
klaxon "fired in the first two seconds of every escalation scene and louder still
on a chapter card". In the shipped configuration it fired **only on the chapter
card**. `video.py:2510` renders each scene with
`include_stinger=not (chapter_cards_enabled and i > 0)`, and `chapter_cards`
defaults on, so every scene except the first omits the stinger input entirely —
the card at the boundary carries that one hit instead
(`_compose_chapter_card`, Story 5.17 AC:7). Measured on run `8a9a288b`'s own
output, first 2.0 s, share of energy in the klaxon's 540–580 Hz band and the
dominant bin: `card_004.mp4` 45.32% / 556 Hz and `card_006.mp4` 45.32% / 556 Hz,
against `seg_005.mp4` 2.49% / 378 Hz and `seg_007.mp4` 2.65% / 767 Hz — the two
escalation *scenes* carried no klaxon at all. The card path is also the loud one
for the second reason already noted: it sums at `normalize=0` while the scene bed
path runs `normalize=1`. None of this changes the swap or the verdict — the cue was
real, audible, identified by ear and approved for replacement — only the account of
which segment played it. Scoping round 1 to the ambient on the strength of the
*ambient's* file title was the original mistake: the title said "Emergency Siren",
but the alarm Jay could hear was the honk at the chapter boundaries.

Replaced by "Impact sfx 018.wav" (AudioPapkin/511882, CC0 verified on the sound's own
page) — a broadband impact/breach hit with no sustained tone anywhere:

```
ffmpeg -y -ss 0 -i src.mp3 -t 1.8 \
  -af "volume=-3.4dB,afade=t=out:st=1.65:d=0.15" \
  -ar 44100 -ac 2 -c:a libmp3lame -b:a 128k data/audio/sfx/escalation_stinger.mp3
```

`-ss` before `-i` again. The hit starts at sample 0 of the source (checked, not
assumed — this is the `sfx/dread_stinger.mp3` trap from the 2026-07-05 fix, where the
onset was *not* at t=0 and the trim grabbed silence); by 1.8s the tail is at −43 dB,
so the 0.15s fade only cleans the cut. The −3.4 dB is chosen so the **peak** matches
the outgoing klaxon exactly, because the chapter-card path runs `normalize=0` and peak
is what jumps out there. Result vs the outgoing file: 1.80s (was 1.98s), mean −17.3 dB
(was −16.4), max −3.1 dB (was −3.3), **tonal frames 8.8% (was 98.1%)**, spectral split
46% below 200 Hz / 48% in 200–1500 Hz / 5% above (the klaxon was 0/53/47), zero
`silencedetect` events. 8.8% sits inside the band of the three stingers nobody has ever
complained about: dread 0.0%, revelation 4.5%, clinical 10.5%. Its above-200 Hz drop is
2.1 dB, so this one is not even close to the bass-trap rule.

Measured in the real mix, not on the raw asset, on **both** paths. Chapter card
(`_compose_chapter_card`'s own mix, the path the cue actually played on, first 2.0 s):
dominant bin **557 Hz → 57 Hz**, 540–580 Hz share **45.05% → 1.65%**. The
`card_before` render lands within 0.3 points of the shipped `card_004.mp4`'s 45.32%,
so the reproduction is faithful. Scene path (bed isolated by subtracting the narration
control, first 2.0 s, `include_stinger=True` — a configuration production does not use
for this scene, see above): **556 Hz → 57 Hz**, **33.26% → 1.94%**. Re-derive
every number in this note with one command:
`uv run python _bmad-output/implementation-artifacts/10-7-live-validation/measure.py`.
Method for "tonal frames": mono 22050 Hz, 1024-sample Hann frame / 256 hop, frames
below −40 dB of the file's loudest frame dropped, count frames whose single loudest FFT
bin lands in 200–1500 Hz. Finding 13 was closed by **Jay's ear on 2026-08-09**
("없어졌다 — 닫자"), not by this table — no measurement in this file was ever
allowed to close it.

**2026-08-09 third fix — the trim recipe broke a file again (loop seam)**: the
escalation ambient shipped above was re-trimmed the same day. Root cause, and the
pattern worth remembering: **an `afade` on a bed is not a fade, it is a click
guard, because the bed is played with `-stream_loop -1`.** The 1.5 s in/out fades
copied from the 2026-07-05 recipe replay at *every* wrap, so the loop had a ~3 s
hole in it every 24 s; and `_compose_black_hold` (`video.py` ~:2241,
`BLACK_HOLD_DURATION = 0.3`) starts the bed at t=0, i.e. entirely inside the
fade-in, so every dip-to-black played near-silence. Fixed by cutting both fades to
**40 ms** and applying the 0.7 dB the fades had been contributing as a flat
`volume=-0.7dB` (recipe above, already updated). Measured — loop the bed with
`-stream_loop -1 -t 40`, slide a 0.3 s RMS window at a 0.01 s hop, dip = worst
window overlapping a wrap minus the median window; hold = `-stream_loop -1
-af volume=0.15 -t 0.3` volumedetect mean:

| ambient bed | loop-seam dip | 0.3 s black-hold mean |
|---|---|---|
| escalation, 1.5 s fades (before this fix) | **−18.2 dB** | **−40.6 dB** |
| escalation, 40 ms fades (shipped) | **−1.0 dB** | **−31.9 dB** |
| dread (untouched, 1.5 s recipe) | −12.6 dB | −33.5 dB |
| clinical (untouched, 1.5 s recipe) | −11.1 dB | −35.8 dB |
| revelation (untouched, 1.5 s recipe) | −18.8 dB | −37.8 dB |

Nothing else about the file changed: same source, same 44–68 s window, mean still
−17.3 dB, wail-band frames still 0.0%, still zero `silencedetect` events.

**This is the third time this library's *trim recipe* — not its source material —
has broken an asset**, and that is the useful record here: 2026-07-05 first fix,
`-ss` placed after `-i` mis-timing `afade` and silencing three files; 2026-07-05
first fix again, a stinger trimmed from t=0 when the onset was not at t=0; and now
a fade length that is correct for a one-shot and wrong for anything looped. Every
one was a fade/seek argument, every one measured fine on the raw file, and every
one only showed up in playback context. The standing rules that fall out of it:
`-ss` before `-i`; find the onset before trimming a one-shot; and on anything
played with `-stream_loop`, fades are **≤50 ms click guards** — check the seam by
looping the file, not by looking at the trim command.

| Mood | Role | File | Title | Author | Source |
|---|---|---|---|---|---|
| dread | bgm | `bgm/dread.mp3` | Action music loop with dark ambient drones (trimmed to 25s) | burning-mir | https://freesound.org/people/burning-mir/sounds/155139/ |
| dread | ambient | `ambient/dread.mp3` | Horror / alien world ambience (trimmed to 20s) | cabled_mess | https://freesound.org/people/cabled_mess/sounds/332249/ |
| dread | stinger | `sfx/dread_stinger.mp3` | HorrorSting1.mp3 (onset trimmed to 1.8s) | shelbyshark | https://freesound.org/people/shelbyshark/sounds/513332/ |
| clinical | bgm | `bgm/clinical.mp3` | Facility Hum Ambience Loopable | aSuperiorPotato | https://freesound.org/people/aSuperiorPotato/sounds/619320/ |
| clinical | ambient | `ambient/clinical.mp3` | Meditate Calm Scape (trimmed to 20s) | szegvari | https://freesound.org/people/szegvari/sounds/580073/ |
| clinical | stinger | `sfx/clinical_stinger.mp3` | Beep Space Button | GameAudio | https://freesound.org/people/GameAudio/sounds/220206/ |
| escalation | bgm | `bgm/escalation.mp3` | Intense loop | nicorico_120 | https://freesound.org/people/nicorico_120/sounds/808224/ |
| escalation | ambient | `ambient/escalation.mp3` | Factory Dark Fantasy Atmo (44–68s window, trimmed to 24s) | szegvari | https://freesound.org/people/szegvari/sounds/577079/ |
| escalation | stinger | `sfx/escalation_stinger.mp3` | Impact sfx 018.wav (trimmed to 1.8s, −3.4 dB) | AudioPapkin | https://freesound.org/people/AudioPapkin/sounds/511882/ |
| revelation | bgm | `bgm/revelation.mp3` | Slow building synth - Riser Uplifter.wav (build-up skipped, trimmed to 19s) | WelvynZPorterSamples | https://freesound.org/people/WelvynZPorterSamples/sounds/621849/ |
| revelation | ambient | `ambient/revelation.mp3` | Repose Lost Melody (trimmed to 22s) | Stereo Surgeon | https://freesound.org/people/Stereo%20Surgeon/sounds/264425/ |
| revelation | stinger | `sfx/revelation_stinger.mp3` | Shock Stab 12 (trimmed to 2s) | nomiqbomi | https://freesound.org/people/nomiqbomi/sounds/578382/ |

All licensed **CC0 1.0 Universal** (public domain dedication) —
https://creativecommons.org/publicdomain/zero/1.0/ — no attribution legally
required, though Freesound etiquette appreciates it.

### Retired assets still in the tree

Story 10.7 swapped two escalation cues **in place**, so the outgoing files survive
only as retained copies under
`_bmad-output/implementation-artifacts/10-7-live-validation/`. They are not on any
runtime path — `MOOD_ASSET_PATHS` never looks there — but they are tracked in git
and every `before`/OLD row in `measure.py` and `make_ab.sh` reads them, so the
advertised one-command re-derivation depends on them. Their provenance rows were
deleted from the table above when the replacements landed; this is that record.

| Retired | Kept at | Title | Author | Source |
|---|---|---|---|---|
| escalation ambient (round 1) | `10-7-live-validation/old_escalation_siren.mp3` | Emergency Siren (trimmed to 28s) | onderwish | https://freesound.org/people/onderwish/sounds/470504/ |
| escalation stinger (round 2) | `10-7-live-validation/old_escalation_klaxon.mp3` | Klaxon off axis short.wav | jameswrowles | https://freesound.org/people/jameswrowles/sounds/514982/ |

Both **CC0 1.0 Universal**, verified on their own Freesound pages at sourcing
time. Retiring an asset does not retract its dedication, and keeping a CC0 file as
a measurement baseline needs no further permission.

Until this pass is verified by ear, `sound_design_enabled` stays forced off
in the test suite (`tests/conftest.py`) so tests stay hermetic and don't
depend on these specific files' content. In a real deployment,
`sound_design_enabled=True` (the `Settings` default) now has real assets to
find — flip `YTFLOW_SOUND_DESIGN_ENABLED=true` in `.env` to enable.
