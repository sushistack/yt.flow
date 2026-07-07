# Story 5.17 — Live Validation Evidence

Real ffmpeg render of `_compose_chapter_card("첫 면담", 1, out_dir, 2.0, kicker="개체가 입을 열다", mood="escalation", sound_design_enabled=True)`.

- `card_frame_mid.png` — frame at t=1.0s: Pretendard Bold renders both Korean
  lines correctly (title centered, kicker below, no tofu/missing glyphs).
- `card_001_label.txt` / `card_001_kicker.txt` — the exact textfiles fed to
  `drawtext`, confirming no inline-filtergraph text (AC:4 hazard avoidance).
- `rms_frames_fixed.txt` — per-frame `astats` RMS (0.04s windows) of
  `card_001.mp4`'s audio. Peaks at -22dB during the stinger's real content
  (t≈0.3-1.0s), decays to -36..-51dB (ambient-only range) after — confirms a
  genuine stinger transient at card entry (AC:7).

**Bug found and fixed during this validation**: the initial `amix` call for
the card's ambient+stinger mix used ffmpeg's default `normalize=1`, which
auto-attenuates by active-input count and flattened the stinger down to the
ambient bed's level — no audible hit at all (first RMS pass showed a flat
~-26dB across the whole card, never approaching either input's solo level).
Fixed by adding `normalize=0` (matching `sound_design.py`'s own convention for
its final narration mix) in `video.py::_compose_chapter_card`.
