#!/usr/bin/env python3
"""Story 10.7 evidence: siren-signature + loudness + in-mix band-energy measurement.

Re-derivation (one command, from repo root):

    uv run python _bmad-output/implementation-artifacts/10-7-live-validation/measure.py

Optional: extra file paths as argv are appended to the signature table (used
while shortlisting Freesound candidates).

Prints four sections:
  1. ROUND 1 — the ambient-bed "wail" signature (old siren vs new bed vs 3 controls)
  2. ROUND 2 — the stinger tonal-frame table (all four stingers + old klaxon)
  3. LOOP/HOLD — loop-seam dip + 0.3s black-hold level, all four ambient beds
  4. in-mix   — the real filter graph rendered over real narration, scene path AND
                chapter-card path (the card path is where the klaxon actually played)

Sample band coordinates (fixed, so every number below is reproducible):

  ROUND 1 (ambient bed, "is there a wail?")
    WAIL_BAND    = 700-1000 Hz   the band the outgoing "Emergency Siren" bed occupied
    ANALYSIS_SR  = 22050 Hz      mono, decoded by ffmpeg -f f32le
    FRAME / HOP  = 2048 / 1024 samples (92.9 ms frame, 46.4 ms hop, Hann window)
    FRAME FLOOR  = -50 dBFS RMS  absolute; frames quieter are not "analysed frames".
                   BOTH `in_band%` and `band_energy%` are computed over the surviving
                   frames only — one population, one documented method. (Until
                   2026-08-09 `band_energy%` silently used every frame including the
                   sub-floor ones; on these files the difference is <0.1 point because
                   nothing here has a sub-floor stretch, but the two columns now
                   provably describe the same frames.)
    Controls     = the three untouched moods' ambient beds (dread/clinical/revelation)
    Also listed  = bgm/escalation.mp3. It is not an ambient bed, but it is the one
                   escalation cue that has never been swapped or measured here, and
                   the only remaining candidate if a siren is ever reported again.

  LOOP / HOLD (added 2026-08-09 after the loop-seam regression, see the spec's
  "Auto Run Result — Review patches")
    loop_seam_dip = loop the bed with `-stream_loop -1 -t 40`, slide a 0.3 s RMS
                   window at a 0.01 s hop, and report (worst window overlapping a
                   wrap point) − (median window). A long in/out `afade` replays at
                   EVERY wrap, so a fade that reads as "loop-safe" on the raw file is
                   an audible hole in the loop. Wraps are located at k × (decoded file
                   duration); the fine hop is deliberate — the dip depth depends on
                   where the window lands, and the worst case is the one a listener hits.
    hold_0.3s_dB = `-stream_loop -1 -i bed -af volume=0.15 -t 0.3`, volumedetect mean.
                   This is exactly `_compose_black_hold`'s audio (video.py ~:2241,
                   BLACK_HOLD_DURATION = 0.3, AMBIENT_VOLUME = 0.15) — 0.3 s taken from
                   the START of the file, i.e. entirely inside any fade-in.

  ROUND 2 (one-shot stinger, "is it an alarm tone or a hit?")
    TONAL_BAND   = 200-1500 Hz   where an alarm honk / horn / siren tone lives
    ANALYSIS_SR  = 22050 Hz      mono, decoded by ffmpeg -f f32le
    FRAME / HOP  = 1024 / 256 samples (46.4 ms frame, 11.6 ms hop, Hann window)
    FRAME FLOOR  = -40 dB RELATIVE to the file's loudest frame (a one-shot decays,
                   so an absolute floor would silently drop most of the tail)
    tonal% = share of surviving frames whose single loudest FFT bin is inside
                   TONAL_BAND. A sustained pure tone -> ~100%; a broadband hit -> ~0%.
    Controls     = the three stingers Jay has never complained about, plus the
                   outgoing klaxon kept at old_escalation_klaxon.mp3.

  in-mix section: control_narration_only.wav (narration with no sound design).
    scene path — before/after minus the narration control. NOTE: production renders
      escalation scene 5 with include_stinger=False (video.py:2510 passes
      `not (chapter_cards_enabled and i > 0)`), so the SCENE path in the shipped run
      carried no stinger at all. These rows are the scene bed, not a reproduction of
      shipped seg_005.mp4.
    card path — card_before/card_after, the `_compose_chapter_card` mix. This IS where
      the klaxon played in run 8a9a288b (card_004.mp4 / card_006.mp4 measure 45.32%
      of their first 2 s energy in 540-580 Hz; seg_005.mp4 measures 2.49%).

# ponytail: numpy + ffmpeg only, no soundfile/librosa - both are already on hand.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "data/audio/ambient").is_dir():
    raise SystemExit(
        f"measure.py: repo root resolved to {ROOT}, which has no data/audio/ambient/.\n"
        "This script assumes it lives at "
        "_bmad-output/implementation-artifacts/10-7-live-validation/measure.py. "
        "Move it back or fix ROOT — a wrong root would otherwise print MISSING for "
        "every asset and read as a clean 'nothing to see here'."
    )

ANALYSIS_SR = 22050
FRAME, HOP = 2048, 1024
FRAME_FLOOR_DB = -50.0
WAIL_LO, WAIL_HI = 700.0, 1000.0

# Round 2: one-shot stinger framing. Finer frame (a 2s hit has no steady state) and a
# floor relative to the file's own loudest frame, because a one-shot decays to nothing.
ST_FRAME, ST_HOP = 1024, 256
ST_FLOOR_REL_DB = -40.0
TONAL_LO, TONAL_HI = 200.0, 1500.0


def decode(path: Path) -> np.ndarray:
    """Mono float32 PCM at ANALYSIS_SR via ffmpeg."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(ANALYSIS_SR),
         "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4")


def ffmpeg_af(path: Path, af: str) -> str:
    """Run one -af chain to null and return ffmpeg's stderr (volumedetect/silencedetect).

    check=True on purpose: without it a failed ffmpeg returns empty stderr, `_grab`
    returns nan, and the evidence table prints `nan` in a cell instead of failing.
    """
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "info", "-i", str(path),
         "-af", af, "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    ).stderr


def _grab(text: str, key: str) -> float:
    for line in text.splitlines():
        if key in line:
            return float(line.split(key)[1].split("dB")[0].strip(": "))
    return float("nan")


def _frames(x: np.ndarray, frame: int, hop: int) -> np.ndarray | None:
    """Hann-windowed frame matrix, or None if the signal is shorter than one frame.

    The old `if frames else` guard was dead: `range(0, max(len(x)-FRAME, 0)+1, HOP)`
    always yields index 0, so a sub-frame input produced one short slice and the
    window multiply raised `ValueError: operands could not be broadcast`. That path
    is reachable from the documented argv shortlisting mode (any clip under 92.9 ms
    here, 46.4 ms in tonal_signature).
    """
    if len(x) < frame:
        return None
    win = np.hanning(frame)
    return np.stack([x[i:i + frame] * win for i in range(0, len(x) - frame + 1, hop)])


def signature(path: Path) -> dict | None:
    x = decode(path)
    fr = _frames(x, FRAME, HOP)
    if fr is None:
        return None
    spec = np.abs(np.fft.rfft(fr, axis=1))
    freqs = np.fft.rfftfreq(FRAME, 1 / ANALYSIS_SR)

    rms_db = 20 * np.log10(np.maximum(np.sqrt((fr ** 2).mean(axis=1)), 1e-12))
    live = rms_db > FRAME_FLOOR_DB
    peaks = freqs[spec[live].argmax(axis=1)] if live.any() else np.array([0.0])

    # Both columns over the SAME population — the surviving (above-floor) frames.
    energy = spec[live] ** 2 if live.any() else spec[:0] ** 2
    band = (freqs >= WAIL_LO) & (freqs <= WAIL_HI)
    wail_ratio = energy[:, band].sum() / max(energy.sum(), 1e-12)

    vd = ffmpeg_af(path, "volumedetect")
    hp = ffmpeg_af(path, "highpass=f=200,volumedetect")
    sd = ffmpeg_af(path, "silencedetect=noise=-35dB:d=0.3")
    mean_db, hp_mean_db = _grab(vd, "mean_volume"), _grab(hp, "mean_volume")
    silences = [ln.split("] ")[-1] for ln in sd.splitlines() if "silence_start" in ln]

    return {
        "file": str(path),
        "dur": len(x) / ANALYSIS_SR,
        "mean_db": mean_db,
        "max_db": _grab(vd, "max_volume"),
        "hp200_drop": mean_db - hp_mean_db,
        "silence": "; ".join(silences) or "none",
        "frames": int(live.sum()),
        "p_med": float(np.median(peaks)),
        "p10": float(np.percentile(peaks, 10)),
        "p90": float(np.percentile(peaks, 90)),
        "p_std": float(peaks.std()),
        "in_wail": float(((peaks >= WAIL_LO) & (peaks <= WAIL_HI)).mean()),
        "wail_ratio": float(wail_ratio),
    }


def tonal_signature(path: Path) -> dict | None:
    """Round 2: is this one-shot an alarm tone or a hit? See module docstring for params."""
    x = decode(path)
    fr = _frames(x, ST_FRAME, ST_HOP)
    if fr is None:
        return None
    energy = (fr ** 2).sum(axis=1)
    live = energy > energy.max() * 10 ** (ST_FLOOR_REL_DB / 10)
    spec = np.abs(np.fft.rfft(fr[live], axis=1))
    freqs = np.fft.rfftfreq(ST_FRAME, 1 / ANALYSIS_SR)
    pk = freqs[spec.argmax(axis=1)]

    # Spectral split, to show *what kind* of hit it is (dread = pure sub thump,
    # klaxon = zero sub and all tone, revelation = balanced).
    whole = np.abs(np.fft.rfft(x)) ** 2
    wf = np.fft.rfftfreq(len(x), 1 / ANALYSIS_SR)
    tot = max(whole.sum(), 1e-24)

    vd = ffmpeg_af(path, "volumedetect")
    hp = ffmpeg_af(path, "highpass=f=200,volumedetect")
    sd = ffmpeg_af(path, "silencedetect=noise=-35dB:d=0.3")
    mean_db = _grab(vd, "mean_volume")
    return {
        "dur": len(x) / ANALYSIS_SR,
        "mean_db": mean_db,
        "max_db": _grab(vd, "max_volume"),
        "hp200_drop": mean_db - _grab(hp, "mean_volume"),
        "frames": int(live.sum()),
        "tonal": float(((pk >= TONAL_LO) & (pk <= TONAL_HI)).mean()),
        "p_med": float(np.median(pk)),
        "p_std": float(pk.std()),
        "sub200": float(whole[wf < 200].sum() / tot),
        "mid": float(whole[(wf >= 200) & (wf < 1500)].sum() / tot),
        "hi": float(whole[wf >= 1500].sum() / tot),
        "silence": "; ".join(ln.split("] ")[-1] for ln in sd.splitlines()
                             if "silence_start" in ln) or "none",
    }


def _db(v: float) -> float:
    return 10 * np.log10(max(v, 1e-24))


def band_stats(x: np.ndarray) -> tuple[float, float, float]:
    """(overall_dBFS, wail_band_dBFS, wail_share) of a mono signal, whole-file FFT.

    Parseval over an rfft needs the interior bins doubled — `rfft` returns only the
    non-negative half, and every bin except DC and (for even N) Nyquist stands for a
    conjugate pair. Summing the half-spectrum undercounts by a factor of ~2, i.e.
    exactly 3.01 dB, which is what these columns reported until 2026-08-09 while
    being labelled dBFS. Cross-check: `overall_dBFS` of the narration control now
    agrees with the independently computed `nar_rms` (plain 20log10 of the RMS) to
    0.0 dB; before the fix it was 3.0 dB lower on the same samples.
    """
    spec2 = np.abs(np.fft.rfft(x)) ** 2
    w = np.full(spec2.shape, 2.0)
    w[0] = 1.0
    if len(x) % 2 == 0:
        w[-1] = 1.0
    spec2 = spec2 * w
    freqs = np.fft.rfftfreq(len(x), 1 / ANALYSIS_SR)
    band = (freqs >= WAIL_LO) & (freqs <= WAIL_HI)
    tot, bnd, n2 = spec2.sum(), spec2[band].sum(), len(x) ** 2
    return _db(tot / n2), _db(bnd / n2), bnd / max(tot, 1e-24)


def loop_seam_dip(path: Path) -> tuple[float, float, float]:
    """(steady_dB, worst_seam_dB, dip_dB) of the bed under `-stream_loop -1`.

    See the module docstring's LOOP/HOLD block for the exact window/hop and why the
    worst overlapping window is the right statistic.
    """
    one = decode(path)
    dur = len(one) / ANALYSIS_SR
    loop = np.frombuffer(subprocess.run(
        ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(path), "-t", "40",
         "-ac", "1", "-ar", str(ANALYSIS_SR), "-f", "f32le", "-"],
        check=True, capture_output=True).stdout, dtype="<f4")
    w, hop = int(0.3 * ANALYSIS_SR), int(0.01 * ANALYSIS_SR)
    starts = np.arange(0, len(loop) - w, hop)
    rms = np.array([20 * np.log10(max(np.sqrt((loop[s:s + w] ** 2).mean()), 1e-12))
                    for s in starts])
    steady = float(np.median(rms))
    worst = steady
    k = 1
    while k * dur * ANALYSIS_SR + w < len(loop):
        c = k * dur * ANALYSIS_SR
        sel = (starts < c) & (starts + w > c)
        if sel.any():
            worst = min(worst, float(rms[sel].min()))
        k += 1
    return steady, worst, worst - steady


def black_hold_mean(path: Path) -> float:
    """volumedetect mean of `_compose_black_hold`'s exact audio: looped bed,
    volume=AMBIENT_VOLUME, first BLACK_HOLD_DURATION seconds."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "info", "-stream_loop", "-1", "-i", str(path),
         "-af", "volume=0.15,volumedetect", "-t", "0.3", "-f", "null", "-"],
        check=True, capture_output=True, text=True).stderr
    return _grab(err, "mean_volume")


def main() -> None:
    targets = [
        ("OLD escalation (siren)", HERE / "old_escalation_siren.mp3"),
        ("NEW escalation (shipped)", ROOT / "data/audio/ambient/escalation.mp3"),
        ("control dread", ROOT / "data/audio/ambient/dread.mp3"),
        ("control clinical", ROOT / "data/audio/ambient/clinical.mp3"),
        ("control revelation", ROOT / "data/audio/ambient/revelation.mp3"),
        # Never swapped, never previously measured; the last escalation cue standing.
        ("escalation BGM (never swapped)", ROOT / "data/audio/bgm/escalation.mp3"),
    ] + [(f"argv {p}", Path(p)) for p in sys.argv[1:]]

    print(f"# ROUND 1 — ambient bed wail signature — band {WAIL_LO:.0f}-{WAIL_HI:.0f} Hz, "
          f"{ANALYSIS_SR} Hz mono, frame {FRAME}/hop {HOP}, floor {FRAME_FLOOR_DB} dBFS")
    hdr = ("label", "dur_s", "mean_dB", "max_dB", "hp200_drop", "frames",
           "peak_med", "p10", "p90", "std", "in_band%", "band_energy%", "silence")
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for label, path in targets:
        if not path.exists():
            print(f"| {label} | MISSING {path} |")
            continue
        s = signature(path)
        if s is None:
            print(f"| {label} | TOO SHORT (< {FRAME / ANALYSIS_SR * 1000:.1f} ms, "
                  f"one analysis frame) — not measurable at this framing |")
            continue
        print("| {} | {:.2f} | {:.1f} | {:.1f} | {:.1f} | {} | {:.0f} | {:.0f} | {:.0f} | {:.0f} "
              "| {:.1f} | {:.2f} | {} |".format(
                  label, s["dur"], s["mean_db"], s["max_db"], s["hp200_drop"], s["frames"],
                  s["p_med"], s["p10"], s["p90"], s["p_std"],
                  s["in_wail"] * 100, s["wail_ratio"] * 100, s["silence"]))

    print(f"\n# ROUND 2 — stinger tonal-frame table — band {TONAL_LO:.0f}-{TONAL_HI:.0f} Hz, "
          f"{ANALYSIS_SR} Hz mono, frame {ST_FRAME}/hop {ST_HOP} Hann, "
          f"floor {ST_FLOOR_REL_DB:.0f} dB relative to the file's loudest frame")
    print("# tonal% = share of surviving frames whose loudest FFT bin is inside the band.")
    print("# Acceptance: <=20%. Duration 1.5-2.0s, mean within ~3 dB of -16.4, "
          "max within ~3 dB of -3.3 (the outgoing klaxon's numbers).")
    stingers = [
        ("dread_stinger (control)", ROOT / "data/audio/sfx/dread_stinger.mp3"),
        ("clinical_stinger (control)", ROOT / "data/audio/sfx/clinical_stinger.mp3"),
        ("revelation_stinger (control)", ROOT / "data/audio/sfx/revelation_stinger.mp3"),
        ("OLD escalation_stinger (klaxon)", HERE / "old_escalation_klaxon.mp3"),
        ("NEW escalation_stinger (shipped)", ROOT / "data/audio/sfx/escalation_stinger.mp3"),
    ]
    sh = ("label", "dur_s", "mean_dB", "max_dB", "hp200_drop", "frames", "tonal%",
          "peak_med", "peak_std", "<200Hz%", "200-1.5k%", ">1.5k%", "silence")
    print("| " + " | ".join(sh) + " |")
    print("|" + "---|" * len(sh))
    for label, path in stingers:
        if not path.exists():
            print(f"| {label} | MISSING {path} |")
            continue
        s = tonal_signature(path)
        if s is None:
            print(f"| {label} | TOO SHORT (< {ST_FRAME / ANALYSIS_SR * 1000:.1f} ms, "
                  f"one analysis frame) — not measurable at this framing |")
            continue
        print("| {} | {:.2f} | {:.1f} | {:.1f} | {:.1f} | {} | {:.1f} | {:.0f} | {:.0f} "
              "| {:.1f} | {:.1f} | {:.1f} | {} |".format(
                  label, s["dur"], s["mean_db"], s["max_db"], s["hp200_drop"], s["frames"],
                  s["tonal"] * 100, s["p_med"], s["p_std"],
                  s["sub200"] * 100, s["mid"] * 100, s["hi"] * 100, s["silence"]))
    print("# NOTE: a bass-heavy one-shot is NOT a bass-trap failure — data/audio/README.md's"
          "\n#       2026-07-05 second fix exempts short hits from the >10 dB rule "
          "(dread_stinger ships at 11.2 dB).")

    # LOOP / HOLD — the 2026-08-09 review regression. A bed is not "loop-safe" because
    # its raw file has fades; the fades REPLAY at every -stream_loop -1 wrap.
    print("\n# LOOP / HOLD — loop-seam dip and black-hold level, all four ambient beds")
    print("# seam: -stream_loop -1 -t 40, 0.3s RMS window at 0.01s hop; dip = worst window "
          "overlapping a wrap minus the median window.")
    print("# hold: -stream_loop -1 -af volume=0.15 -t 0.3 volumedetect mean "
          "(= _compose_black_hold's audio, video.py ~:2241).")
    lh = ("bed", "dur_s", "steady_dB", "worst_seam_dB", "seam_dip_dB", "hold_0.3s_dB")
    print("| " + " | ".join(lh) + " |")
    print("|" + "---|" * len(lh))
    for label, path in [
        ("OLD escalation (1.5s fades)", HERE / "old_escalation_siren.mp3"),
        ("NEW escalation (0.04s fades)", ROOT / "data/audio/ambient/escalation.mp3"),
        ("dread", ROOT / "data/audio/ambient/dread.mp3"),
        ("clinical", ROOT / "data/audio/ambient/clinical.mp3"),
        ("revelation", ROOT / "data/audio/ambient/revelation.mp3"),
    ]:
        if not path.exists():
            print(f"| {label} | MISSING {path} |")
            continue
        steady, worst, dip = loop_seam_dip(path)
        print(f"| {label} | {len(decode(path)) / ANALYSIS_SR:.2f} | {steady:.1f} | {worst:.1f} "
              f"| {dip:+.1f} | {black_hold_mean(path):.1f} |")
    print("# The other three beds still carry the 2026-07-05 1.5s-fade recipe — recorded as "
          "deferred work, out of scope for a story scoped to escalation.")

    print("\n# in-mix — real graphs over run 8a9a288b, two paths")
    print(f"# regenerate the wavs with: bash {HERE.relative_to(ROOT)}/make_ab.sh")
    mixes = [("before.wav (old siren bed)", HERE / "before.wav"),
             ("after.wav  (new bed)", HERE / "after.wav"),
             ("control_narration_only.wav", HERE / "control_narration_only.wav")]
    cards = [("card_before.wav (old klaxon)", HERE / "card_before.wav"),
             ("card_after.wav  (new hit)", HERE / "card_after.wav")]
    if not all(p.exists() for _, p in mixes + cards):
        print("  (wavs absent — run make_ab.sh first)")
        return

    # Staleness guard: an evidence table rendered from stale wavs is worse than no
    # table — it reads as a measurement of the shipped state and is not one.
    renders = min((p.stat().st_mtime for _, p in mixes + cards))
    stale = [p for label, p in targets + stingers
             if not label.startswith("argv ") and p.exists()
             and p.stat().st_mtime > renders]
    if stale:
        print("\n!! STALE RENDERS — refusing to print in-mix numbers.")
        for p in stale:
            print(f"   newer than the A/B wavs: {p}")
        print(f"   run: bash {HERE.relative_to(ROOT)}/make_ab.sh")
        raise SystemExit(1)

    print("\n## SCENE path — build_sound_design_filter, include_stinger=True."
          "\n## NOT the shipped scene 5: video.py:2510 passes include_stinger="
          "not (chapter_cards_enabled and i > 0), and scene 5 is i=4, so the shipped"
          "\n## seg_005.mp4 carried NO stinger. See the card block below for the path"
          "\n## the klaxon actually played on.")
    print("\n## whole-mix (narration dominates the wail band, so this alone proves nothing)")
    print("| mix | overall_dB | wail_band_dB | wail_share% | wail_dB vs control |")
    print("|---|---|---|---|---|")
    sig = {label: decode(path) for label, path in mixes}
    n = min(len(v) for v in sig.values())
    sig = {k: v[:n] for k, v in sig.items()}
    ctl = sig[mixes[2][0]]
    ctl_band = band_stats(ctl)
    for label, _ in mixes:
        o, b, sh = band_stats(sig[label])
        print(f"| {label} | {o:.1f} | {b:.1f} | {sh * 100:.2f} | {b - ctl_band[1]:+.1f} |")

    # The graph's final stage is `amix=inputs=2:...:normalize=0` of [ducked]+narration,
    # i.e. a plain sum. Both renders share the same narration input and -t, so they are
    # sample-aligned and (mix - control) recovers the ducked bed EXACTLY as it sits in
    # the mix — after AMBIENT_VOLUME, after the bed amix's normalize=1, after the duck.
    print("\n## isolated bed = mix - control_narration_only (exact: final amix is normalize=0)")
    print(f"| bed | rms_dBFS | vs narration_dB | wail_band_dB | wail_share% "
          f"| peak_med_Hz | in {WAIL_LO:.0f}-{WAIL_HI:.0f}Hz frames% |")
    print("|---|---|---|---|---|---|---|")
    nar_rms = 20 * np.log10(max(np.sqrt((ctl ** 2).mean()), 1e-12))
    for label, _ in mixes[:2]:
        bed = sig[label] - ctl
        rms = 20 * np.log10(max(np.sqrt((bed ** 2).mean()), 1e-12))
        _, bdb, sh = band_stats(bed)
        win = np.hanning(FRAME)
        fr = np.stack([bed[i:i + FRAME] * win for i in range(0, len(bed) - FRAME + 1, HOP)])
        spec = np.abs(np.fft.rfft(fr, axis=1))
        freqs = np.fft.rfftfreq(FRAME, 1 / ANALYSIS_SR)
        live = 20 * np.log10(np.maximum(np.sqrt((fr ** 2).mean(axis=1)), 1e-12)) > FRAME_FLOOR_DB
        pk = freqs[spec[live].argmax(axis=1)] if live.any() else np.array([0.0])
        print(f"| {label} | {rms:.1f} | {rms - nar_rms:+.1f} | {bdb:.1f} | {sh * 100:.2f} "
              f"| {np.median(pk):.0f} | {((pk >= WAIL_LO) & (pk <= WAIL_HI)).mean() * 100:.1f} |")
    print(f"  narration (control) rms = {nar_rms:.1f} dBFS over {n / ANALYSIS_SR:.2f}s")

    # Round 2 in-mix: the stinger only sounds in the first ~2s of the scene, and the
    # klaxon's whole complaint was one fixed tone. Measure that tone's own narrow band
    # (540-580 Hz, +-20 Hz around the 560 Hz the outgoing file sat at) in the isolated bed.
    print("\n## ROUND 2 in-mix — isolated bed, FIRST 2.0s only (the stinger window), "
          "klaxon band 540-580 Hz")
    print("| bed (first 2s) | dominant_Hz | 540-580Hz share% | rms_dBFS |")
    print("|---|---|---|---|")
    for label, _ in mixes[:2]:
        seg = (sig[label] - ctl)[: int(2.0 * ANALYSIS_SR)]
        sp = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(len(seg), 1 / ANALYSIS_SR)
        k = (f >= 540) & (f <= 580)
        rms = 20 * np.log10(max(np.sqrt((seg ** 2).mean()), 1e-12))
        print(f"| {label} | {f[sp.argmax()]:.0f} | {sp[k].sum() / max(sp.sum(), 1e-24) * 100:.2f} "
              f"| {rms:.1f} |")

    # CHAPTER-CARD path — where the klaxon actually played. No narration and no
    # sidechain here, and _compose_chapter_card mixes at normalize=0, so the raw
    # render IS the cue: no control subtraction needed.
    print("\n## CARD path — _compose_chapter_card mix (ambient 0.15 + stinger 0.5, "
          "amix normalize=0, no narration)")
    print("| card render | dur_s | rms_dBFS | max_dB | dominant_Hz (first 2s) "
          "| 540-580Hz share% (first 2s) |")
    print("|---|---|---|---|---|---|")
    for label, path in cards:
        x = decode(path)
        seg = x[: int(2.0 * ANALYSIS_SR)]
        sp = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(len(seg), 1 / ANALYSIS_SR)
        k = (f >= 540) & (f <= 580)
        rms = 20 * np.log10(max(np.sqrt((x ** 2).mean()), 1e-12))
        print(f"| {label} | {len(x) / ANALYSIS_SR:.2f} | {rms:.1f} "
              f"| {_grab(ffmpeg_af(path, 'volumedetect'), 'max_volume'):.1f} "
              f"| {f[sp.argmax()]:.0f} "
              f"| {sp[k].sum() / max(sp.sum(), 1e-24) * 100:.2f} |")
    print("# Reference, measured from the shipped run's own artifacts (same first-2.0s "
          "540-580 Hz share):"
          "\n#   card_004.mp4 45.32% / 556 Hz · card_006.mp4 45.32% / 556 Hz "
          "· seg_005.mp4 2.49% / 378 Hz · seg_007.mp4 2.65% / 767 Hz.")


if __name__ == "__main__":
    main()
