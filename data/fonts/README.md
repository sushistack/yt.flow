# Bundled Typography (Story 5.17, 5.18)

`Pretendard-Bold.otf` — used by `video.py`'s chapter-card `drawtext` (title +
kicker), pointed at directly via `fontfile=`, no fontconfig involvement.

`Pretendard-SemiBold.otf` — used by `subtitle.py`'s `.ass` `Style: Default`
line as `Fontname`, resolved via the ffmpeg `subtitles=` filter's `fontsdir`
option (libass scans this directory, no system fontconfig involvement).
`fc-scan` reports `family: Pretendard,Pretendard SemiBold` — the `Fontname`
constant pins the more specific `Pretendard SemiBold` name so libass doesn't
ambiguously match the bundled Bold weight (which also registers under the
bare `Pretendard` family) when both files sit in the same `fontsdir`.

Source: https://github.com/orioncactus/pretendard release `v1.3.9`
(`Pretendard-1.3.9.zip` → `public/static/Pretendard-{Bold,SemiBold}.otf`).
Licensed under the SIL Open Font License 1.1 (`Pretendard-LICENSE.txt`,
copied from the same release) — free to bundle/redistribute. Vendored, not
fetched at runtime.
