---
created: 2026-07-10
story_key: 5-24-voice-clone-force-reseed
story_id: "5.24"
epic: 5
previous_story: 5-23-comfyui-crash-mitigation
depends_on:
  - 5-21-tts-voice-clone-wiring   # the script and voice id this story adds a force path to
related: []
baseline_commit: 85e07cd528361caf902cfd9153e1b8f5ce8ec08c
workflow_decision: "Extend scripts/seed_voice_clone.py with a --force flag. No pipeline/runtime code touched — enrollment is a one-off operator script."
evidence: "Jay re-recorded data/voices/sutak.mp3 from 7.68s (stereo, below the 10-20s recommendation) to 12.93s (commit e52aed4). Re-running seed_voice_clone.py today would print the OLD voice id (matched by name, not content) without re-enrolling."
---

# Story 5.24: Force Re-Enrollment Support in seed_voice_clone.py

Status: done

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

- [x] Task 0: Confirm DashScope delete payload shape (dry-run against docs or a disposable test enrollment) before wiring against the real `sutak` voice (AC:2)
- [x] Task 1: `--force` flag + `_delete_voice` (AC:1,2)
- [x] Task 2: Force-flow branching in `main()` (AC:3,4,5,6)
- [x] Task 3: Mocked tests (AC:7)
- [x] Task 4: Live re-enrollment run + `.env` update + Dev Agent Record (AC:8)

### Review Findings

- [x] [Review][Patch] No operator-facing warning when create fails after a successful `--force` delete — leaves the voice deleted with nothing re-created and only a bare traceback [scripts/seed_voice_clone.py:176-186]
- [x] [Review][Patch] No test asserts the actual `_delete_voice` request payload (the `voice` key + exact target id) — the force-flow test only checked call order, not contents, so a wrong id/key would still pass [tests/test_seed_voice_clone.py]
- [x] [Review][Defer] `_find_existing` returns only the first match; duplicate "sutak" enrollments for the same target_model would leave orphans after `--force` [scripts/seed_voice_clone.py:67-74] — deferred, pre-existing limitation of `_find_existing`, not introduced by this diff
- [x] [Review][Defer] No idempotent handling for a delete-then-404 race (voice removed externally between list and delete) [scripts/seed_voice_clone.py:108-113] — deferred, YAGNI for a single-operator on-demand CLI script

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

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Task 0 payload confirmation (2026-07-10): DashScope docs (`help.aliyun.com/en/model-studio/qwen-omni-voice-cloning`) give the delete request as `{"model": "qwen-voice-enrollment", "input": {"action": "delete", "voice": "<id>"}}` — note the key is **`voice`**, not `voice_id` as AC2's placeholder text guessed. This matches the existing code's own convention: `_voice_id()` already reads the `"voice"` key first, and the create response is read via `output.voice`. Implemented `_delete_voice` with the confirmed `voice` key. Delete response carries no useful body (`{"output": {}, "usage": {"count": 0}}`), so nothing is parsed from it — only `raise_for_status()`.
- Live re-enrollment (2026-07-10, AC8): ran `uv run python scripts/seed_voice_clone.py --force` for real.
  - Deleted voice_id: `qwen-tts-vc-sutak-voice-20260707211054527-0f76` (old, from the 7.68s sample)
  - Created voice_id: `qwen-tts-vc-sutak-voice-20260710174246336-dce4` (new, from the 12.93s re-recorded `data/voices/sutak.mp3`)
  - `.env`'s `YTFLOW_QWEN_TTS_CLONE_VOICE_ID` updated to the new id.
  - Note: 5.21's stock-vs-clone A/B listening comparison remains Jay's judgment call, not automated by this story — the clone voice now targets the correct (longer) reference sample so that comparison is unblocked.

### Completion Notes List

- Added `--force` CLI flag (default off — behavior byte-for-byte unchanged without it) and `_delete_voice()` to `scripts/seed_voice_clone.py`, reusing existing auth/list/create plumbing (ponytail: one flag, one small function).
- `main()` branching: `existing and not force` → unchanged short-circuit; `existing and force` → delete then always create; no `existing` → plain create regardless of `--force` (nothing to delete). `--dry-run --force` prints a static "would delete" line plus the existing create-payload dry-run output — no network calls, since existence isn't looked up in dry-run mode.
- Added 4 mocked tests in `tests/test_seed_voice_clone.py` covering: force+existing (delete→create order), force+no-existing (create only, no delete), plain run unchanged, and dry-run+force (no network client constructed). All 5 pre-existing 5.21 tests remain green.
- Full regression suite: 1074 passed, 1 skipped (pre-existing), 0 failures. `ruff check` clean on both changed files.
- Live-executed AC8's `--force` run against production DashScope (see Debug Log above) and updated `.env`. This was a real, irreversible destructive+billed call — confirmed with Jay before running.

### File List

- `scripts/seed_voice_clone.py` (modified — `--force` flag, `_delete_voice`, `main()` branching, docstring)
- `tests/test_seed_voice_clone.py` (modified — 4 new mocked tests for force flow)
- `.env` (modified — `YTFLOW_QWEN_TTS_CLONE_VOICE_ID` updated to new live-enrolled voice id)

## Change Log

- 2026-07-10: Implemented `--force` re-enrollment flow (Tasks 0-3), confirmed DashScope delete payload shape via docs research (key is `voice`, not `voice_id`), added mocked tests. Live-executed the real `--force` re-enrollment (Task 4/AC8): old voice id deleted, new id created from the 12.93s sample, `.env` updated. Full regression suite green (1074 passed).
- 2026-07-10: Code review (3-layer: Blind Hunter, Edge Case Hunter, Acceptance Auditor) — 2 patches applied, 2 items deferred (pre-existing/YAGNI), rest dismissed (false positives or already-justified design decisions). Patches: (1) `main()` now warns on stderr with the deleted voice id before re-raising if re-create fails after a successful `--force` delete, so the operator isn't left with just a bare traceback; (2) added a test asserting `_delete_voice`'s actual request payload (`voice` key + exact target id), closing the gap AC2 explicitly warned about (no test previously proved the delete targets the right id). 13 tests total, full regression suite still green.
