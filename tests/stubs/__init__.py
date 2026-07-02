"""Test-level fakes/cassette playback for the four external seams (B-2).

These live entirely under ``tests/`` — no production stub flag is added (the
existing ``comfyui_mock``/``qwen_tts_mock`` Settings flags are intentionally NOT
extended). Every fake emits a tiny deterministic artifact and makes ZERO network
or subprocess calls, so QA can drive SYS-E2E-001 offline.
"""
