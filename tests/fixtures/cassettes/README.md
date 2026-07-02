# External-API cassettes (B-2)

Hand-authored recorded-shape responses used by the test-level fakes in
`tests/stubs/fakes.py`. They stand in for live DeepSeek / Qwen calls so the
suite runs fully offline (zero network, zero subprocess).

| File | Seam | Shape source |
|------|------|--------------|
| `deepseek_scenario.json` | `scenario._call_deepseek` | OpenAI-compatible chat completion; `choices[0].message.content` is a JSON string parsed by `_parse_scenes` |
| `qwen_tts.json` | `tts._synthesize` | Qwen DashScope response; `output.audio.url` (the audio itself is faked by `fake_synthesize`) |

**Re-record these whenever the Prompt Hub templates or the pinned model IDs
change** (`YTFLOW_DEEPSEEK_MODEL`, `YTFLOW_QWEN_TTS_MODEL`), since a template/model
change can shift the response shape or the JSON the model is asked to emit.
Live keys are not available in CI, so update them by hand against the vendor
docs / a captured real response.
