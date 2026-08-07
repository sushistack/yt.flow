# Test Automation Summary — Story 12.5 (TTS Provider Comparison — Naver CLOVA Voice)

Date: 2026-08-08 · Workflow: `bmad-qa-generate-e2e-tests` · Framework: **pytest 9.1.1** (existing)

Story 12.5 shipped no UI, no API endpoint, no LangGraph node and no provider client
(AC1 returned `naver-ineligible`; AC8/AC9 are unreachable). Its only executable surface
is the operator helper `scripts/compare_tts_providers.py`. So "E2E" here means driving
that script through its **real** seams — the HTTP transport under `tts._synthesize`, and
the real `ffmpeg` binary — instead of around them. Browser/Playwright E2E is not
applicable. No test makes a live or billed provider call.

## Gap analysis

The story shipped 17 tests. All of them monkeypatch **both** `tts._synthesize` and
`tts._run_ffmpeg`, so the suite asserted the script's *intent* (argument strings, file
layout) and never its *effect*. Every gap below would have stayed green with the helper
functionally broken:

| # | Gap | Would have survived because |
|---|-----|------------------------------|
| 1 | Nothing asserted the DashScope target/headers/body **through the script** — AC10 names this explicitly | `_synthesize` was replaced wholesale; the payload tests in `test_tts.py` cover the function, not the helper's use of it |
| 2 | No tripwire that the helper never reaches a Naver endpoint — the single hardest AC1 constraint | a Naver call added later would have broken no test |
| 3 | The downloaded audio was never proven to be what lands in `raw/` | the fake wrote the file itself, so the download step was untested |
| 4 | The ffmpeg filter chain was only compared as a **string**; the binary never ran | an ffmpeg-invalid filter that matches its own expectation ships green |
| 5 | ffmpeg exiting non-zero → no test | the fake always returned `0, ""` |
| 6 | A final file that is not readable PCM → no test (the story's own "do not trust a `.wav` extension" guardrail) | the fake always wrote a valid WAV |
| 7 | Preflight was proven to block billed calls, but not to leave the filesystem clean | the assertion only checked `calls["synth"] == []` |
| 8 | `listen/` was globbed for `*.wav` only — a stray provider-named file there was invisible | the glob could not see it |
| 9 | Manifest non-joinability (`outputs` label-keyed vs `candidates` candidate-keyed) was claimed in the story notes but only checked via `"mapping" not in raw` | a `{"engine": name}` field inside `outputs` passes that check |
| 10 | `--seed` reproducibility was "tested" by re-deriving the shuffle with `random` — never against the script's own output | the script could ignore `--seed` entirely |
| 11 | `--out-root` untested; nothing pinned AC4's "must not overwrite `workspace/voice-ab/`" | the flag was never passed |
| 12 | Byte-for-byte text (AC3) was tested with a clean string only | a `.strip()` would pass |

## Generated tests (`tests/test_compare_tts_providers.py`, +12)

### E2E — script → `_synthesize` → HTTP transport (only `ffmpeg` faked)

- [x] `test_e2e_transport_posts_exact_dashscope_target_headers_and_bodies` — happy path.
  Exactly two POSTs, exact URL (`endpoint + tts._GENERATION_PATH`), exact
  `Authorization: Bearer …`, and exact bodies: stock → `qwen3-tts-flash`/`Cherry`,
  clone → `qwen3-tts-vc-2026-01-22`/enrolled voice id, with **identical** text.
- [x] `test_e2e_transport_never_contacts_naver` — AC1 policy tripwire: no outbound URL
  may contain `naver`/`ntruss`.
- [x] `test_e2e_transport_downloads_each_rendered_audio_once` — one GET per candidate,
  `raw/` keeps provider-named originals outside `listen/`, and the downloaded bytes are
  what actually gets persisted.

### E2E — real `ffmpeg` binary (`skipif` when absent, project's existing pattern)

- [x] `test_e2e_real_ffmpeg_yields_identical_readable_pcm_and_applies_the_speed` — two
  raws at deliberately unequal sample rates (44.1 kHz / 16 kHz) converge to one readable
  24 kHz mono 16-bit PCM output each, non-empty, with a 1.0 s tone shortened into the
  0.75–0.92 s band that `atempo=1.2` implies.

### Error cases

- [x] `test_ffmpeg_failure_aborts_with_no_partial_package` — non-zero exit → `RuntimeError`, package dir gone.
- [x] `test_unreadable_final_audio_fails_instead_of_shipping` — a `.wav` that is not a WAV fails the run, no partial package.
- [x] `test_preflight_failure_writes_nothing_at_all` — missing credentials leave no directory behind at all.

### Package integrity

- [x] `test_listening_dir_holds_only_neutral_files` — `listen/` is exactly `A.wav`, `B.wav`, `scorecard.md`.
- [x] `test_manifest_never_pairs_a_label_with_a_candidate` — `outputs` names no engine and `candidates` carries no blind label.
- [x] `test_cli_seed_determines_the_mapping` — six seeds, each compared against the independently derived shuffle (one seed is a coin flip with two candidates).
- [x] `test_out_root_override_is_honored_and_leaves_story_5_21_evidence_alone` — AC4: `--out-root` is respected and a sibling `voice-ab/` is byte-untouched.
- [x] `test_source_text_reaches_the_provider_byte_for_byte` — leading/trailing whitespace and an embedded newline survive to both providers and to the manifest hash/byte count.

## Mutation verification

Every new test was proven to bite: one defect injected at a time, targeted test run,
source restored, `git diff --stat scripts/` confirmed clean afterwards. **11/11 caught.**

| Mutation | Killed |
|----------|--------|
| `.strip()` the source text | byte-for-byte |
| ignore `--out-root` | out-root |
| swallow ffmpeg's non-zero exit | ffmpeg-failure |
| trust the `.wav` extension instead of reading it | unreadable-audio |
| move preflight after `mkdir` | preflight-writes-nothing |
| write `mapping.json` into `listen/` | listening-dir |
| add `"engine": name` to manifest `outputs` | manifest-pairing |
| ignore `--seed` | cli-seed |
| render both candidates as clone | transport-bodies |
| skip the audio download | transport-download |
| add a Naver POST | never-contacts-naver |

The real-ffmpeg test guards something no mocked test structurally can, so it was checked
differently: `_LOUDNORM` was made ffmpeg-invalid (`LRA=99`) **together with** the mocked
test's expected string. The mocked assertion stayed green — the real-binary test failed.
That is exactly the class of defect it exists to catch.

## Coverage

- **AC10 (mocked comparison-helper tests):** all nine named requirements now have a test.
  Exact provider target/headers/body moved from "covered in `test_tts.py`" to covered
  through the helper itself.
- **AC1 / AC4 / AC6:** the never-call-Naver constraint, the `voice-ab/` non-overwrite
  rule, and the "no billed call without credentials" rule are now enforced by tests, not
  only by prose in the story.
- **Not covered, deliberately:** audio *quality* — a human gate, already satisfied
  (verdict `qwen-clone`, Jay, 2026-08-08). No live DashScope smoke test was added; the
  suite must stay unbilled, and Naver has no opt-in live test because AC1 forbids calling
  it at all.

## Results

```
uv run pytest tests/test_compare_tts_providers.py tests/pipeline/nodes/test_tts.py \
              tests/test_config.py tests/test_seed_voice_clone.py -q   → 85 passed, 1 skipped  (was 73 → +12)
uv run pytest -q                                                       → 2368 passed, 1 skipped  (was 2356 → +12)
uv run ruff check scripts/compare_tts_providers.py tests/test_compare_tts_providers.py \
              src/yt_flow/config.py src/yt_flow/pipeline/nodes/tts.py  → All checks passed
git diff 878bad6 -- <production TTS/normalization/config/state/clone-asset paths>  → empty (AC6 still holds)
```

One non-test change: `scripts/compare_tts_providers.py` had the same two-line comment
pasted twice above the progress `print`. The duplicate was deleted. No behaviour change.

## Next steps

- Run in CI as-is: no new dependency, fixture file, or marker. The real-ffmpeg test
  self-skips where the binary is absent.
- Unchanged from the story: production still renders with Qwen **stock** while Jay's
  listening verdict was **clone**. Flipping it is one operator line
  (`YTFLOW_QWEN_TTS_CLONE_ENABLED=true`) and is explicitly out of 12.5's scope — weigh
  the ~34 % faster clone read first.
