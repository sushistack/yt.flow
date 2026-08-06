# External-API cassettes (B-2)

Hand-authored recorded-shape responses used by the test-level fakes in
`tests/stubs/fakes.py`. They stand in for live DeepSeek / Gemini / Qwen calls so
the suite runs fully offline (zero network, zero subprocess).

Since Story 12.2 the scenario chain spans **two** providers, and `fakes.py` plays
these cassettes back through two separate seams:

| Seam | Stages | Cassettes |
|------|--------|-----------|
| `scenario._call_deepseek` | research, structure, cast_decision, visual_breakdown, tts_normalize | `deepseek_research/structure/cast_decision/visual_breakdown/tts_normalize.json` |
| `scenario._call_gemini` | writing, review, critic_agent | `deepseek_writing/review/critic.json` |

The `deepseek_`-prefixed filenames are kept for the Gemini-owned stages on
purpose: a cassette records the **OpenAI-compatible response shape**, which
Gemini's compatibility endpoint shares byte-for-byte with DeepSeek's. Only the
seam changed, not the shape — renaming the files would churn every reference for
no behavioural difference.

| File | Seam | Shape source |
|------|------|--------------|
| `deepseek_scenario.json` | `scenario._call_deepseek` | OpenAI-compatible chat completion; `choices[0].message.content` is a JSON string parsed by `_parse_scenes` |
| `deepseek_tts_normalize.json` | `scenario_chain.tts_normalize_step` | OpenAI-compatible chat completion; `choices[0].message.content` is `{"scenes": [{scene_num, narration}]}` from `prompts/scenario/tts_normalize.md` |
| `qwen_tts.json` | `tts._synthesize` | Qwen DashScope response; `output.audio.url` (the audio itself is faked by `fake_synthesize`) |

**Re-record these whenever the Prompt Hub templates or the pinned model IDs
change** (`YTFLOW_DEEPSEEK_MODEL`, `YTFLOW_GEMINI_WRITING_MODEL`,
`YTFLOW_QWEN_TTS_MODEL`), since a template/model
change can shift the response shape or the JSON the model is asked to emit.
Live keys are not available in CI, so update them by hand against the vendor
docs / a captured real response.
