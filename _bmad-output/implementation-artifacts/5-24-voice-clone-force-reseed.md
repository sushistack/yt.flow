---
created: 2026-07-10
story_key: 5-24-voice-clone-force-reseed
story_id: "5.24"
epic: 5
previous_story: 5-23-comfyui-crash-mitigation
depends_on:
  - 5-21-tts-voice-clone-wiring   # the script and voice id this story adds a force path to
related: []
workflow_decision: "Extend scripts/seed_voice_clone.py with a --force flag. No pipeline/runtime code touched — enrollment is a one-off operator script."
evidence: "Jay re-recorded data/voices/sutak.mp3 from 7.68s (stereo, below the 10-20s recommendation) to 12.93s (commit e52aed4). Re-running seed_voice_clone.py today would print the OLD voice id (matched by name, not content) without re-enrolling."
---

# Story 5.24: Force Re-Enrollment Support in seed_voice_clone.py

Status: ready-for-dev

## Story

As Jay,
I want a way to re-enroll the TTS clone voice from a new reference sample,
so that my re-recorded, longer `sutak.mp3` (12.93s) actually gets used, instead of the script silently keeping the old 7.68s enrollment forever.

## Context

`scripts/seed_voice_clone.py`'s idempotency check (`_find_existing`, line 67) matches an existing voice by **name substring** (`"sutak" in voice_id.lower()`) and `target_model` only — it has no way to know the local sample file changed. Confirmed by reading the code: there is no content hash, timestamp, or file-size comparison anywhere in the script. So today, re-running the script after Jay's re-recording (7.68s → 12.93s, addressing 5.21's flagged shortfall) does nothing: it finds the voice enrolled from the *old* sample and prints that same id — the new recording is never actually sent to DashScope.

The DashScope `qwen-voice-enrollment` API supports `action: "delete"` (documented in 5.21's Dev Notes API research: "`action=list`/`delete` exist for management") but the script only implements `list` and `create`. This story adds `delete` + a `--force` flag that chains delete-then-create, gated behind an explicit flag because delete is destructive (the old voice id becomes invalid — any `.env` or downstream reference to it breaks until replaced) and create costs USD 0.01.

## Acceptance Criteria

1. `--force` CLI flag added (`argparse`, alongside existing `--dry-run`). Without it, behavior is byte-for-byte unchanged (idempotent list-then-create-if-missing, per 5.21 AC3).
2. `_delete_voice(client, s, voice_id) -> None`: `POST` the customization endpoint with `{"model": "qwen-voice-enrollment", "input": {"action": "delete", "voice_id": voice_id}}` (confirm exact payload shape against DashScope's delete contract — 5.21's research only confirmed the action *exists*, not its request schema; verify live with a throwaway test voice or the docs before wiring the real flow, since a malformed delete payload against the wrong id would be an expensive mistake).
3. With `--force` and an existing "sutak" voice found: delete it, then always create a new one from the *current* `qwen_tts_clone_voice_path` file (bypassing the "found existing, no create call made" short-circuit). Print both the deleted id (for the operator's audit trail) and the new id + `.env` line, matching the existing `_print_voice_id` format.
4. Without `--force` and no existing voice: unchanged create-if-missing path (AC:1).
5. `--force` with no existing voice found: behaves like a plain create (no delete call attempted — nothing to delete), same output format.
6. `--dry-run --force` prints both the would-be delete target (if any) and the create payload, makes no network calls — same safety guarantee `--dry-run` already provides.
7. Mocked tests: force-with-existing (delete called once, create called once, in that order), force-without-existing (no delete call, create called), plain run unchanged (existing 5.21 tests stay green).
8. **Live execution as part of this story's completion** (not deferred to a later session): run `uv run python scripts/seed_voice_clone.py --force` for real, confirm the new voice id targets the 12.93s sample, update `.env`'s `YTFLOW_QWEN_TTS_CLONE_VOICE_ID`, and record both the deleted and created ids in Dev Agent Record. This unblocks 5.21's still-open DoD (stock vs. clone A/B listening comparison) — note in the completion summary that the A/B itself remains Jay's listening judgment, not this story's to perform.

## Tasks / Subtasks

- [ ] Task 0: Confirm DashScope delete payload shape (dry-run against docs or a disposable test enrollment) before wiring against the real `sutak` voice (AC:2)
- [ ] Task 1: `--force` flag + `_delete_voice` (AC:1,2)
- [ ] Task 2: Force-flow branching in `main()` (AC:3,4,5,6)
- [ ] Task 3: Mocked tests (AC:7)
- [ ] Task 4: Live re-enrollment run + `.env` update + Dev Agent Record (AC:8)

## Dev Notes

- **This is destructive and costs money** — `--force` must never be the default path, and Task 0 exists specifically because guessing the delete payload wrong against the one real production voice id is the failure mode to avoid. If delete's exact schema can't be confirmed from docs, do a `list` immediately after a test delete-of-nothing (invalid id) to observe the API's error shape first, rather than risking the real enrollment.
- House pattern precedent: `scripts/seed_character_prompts.py` (idempotent, `--dry-run`, docstring usage) — 5.21 already followed this; extend the same file's conventions, don't introduce a different CLI style.
- **ponytail:** one flag, one new small function, reusing all existing auth/list/create plumbing.

### References

- [Source: scripts/seed_voice_clone.py] — file being extended, `_find_existing`/`_list_voices`/`main` read in full during story authoring
- [Source: _bmad-output/implementation-artifacts/5-21-tts-voice-clone-wiring.md#L108] — "`action=list`/`delete` exist for management" (the API research this story acts on)
- [Source: data/voices/sutak.mp3] — commit e52aed4, 12.93s/44.1kHz/stereo, the sample that needs to actually get enrolled

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
