import { test, expect } from './support/fixtures/merged-fixtures';
import { stageSidebarButton, artifactSection, approveStage, createRun } from './support/helpers';

// SYS-E2E-002 (P0) — the baseline journey: dashboard → create run → approve
// gate → artifact panel per stage type. Drives the real FastAPI app with all
// 5 external seams stubbed (scripts/run_e2e_stub_server.py via
// playwright.config.ts's webServer), so gates advance in seconds, not the
// minutes a real DeepSeek/ComfyUI/ffmpeg run would take.
//
// Related stories: 3.3 (Dashboard + SCP Picker), 3.4 (Run Detail + Artifact
// Panel), 3.5 (Gate Controls + Retry + SSE).

test.describe('@P0 SYS-E2E-002 dashboard → create run → approve gate → artifact panel', () => {
  test('runs SCP-096 through all 5 stages to completion', async ({ page, apiRequest }) => {
    // Capture the created run's id so the completion check at the end is
    // unambiguous even if other SCP-096 runs exist in the (gitignored,
    // locally-accumulating) dev db.
    const runId = await createRun(page, '096', 'SCP-096');

    // ── Run Detail (Story 3.4) ──────────────────────────────────────────────
    // scenario: text artifact, live via SSE stage_entry/gate_pending (Story 3.5).
    await stageSidebarButton(page, 'scenario').click();
    await expect(artifactSection(page, 'scenario').getByRole('button', { name: '편집' })).toBeVisible();
    await approveStage(page, 'scenario');

    // image: rendered scene shots.
    await approveStage(page, 'image');
    await expect(artifactSection(page, 'image').locator('img').first()).toBeVisible();

    // tts: per-scene audio players.
    await approveStage(page, 'tts');
    await expect(artifactSection(page, 'tts').locator('audio').first()).toBeVisible();

    // subtitle: fetched + rendered cue text, editable like scenario.
    await approveStage(page, 'subtitle');
    await expect(artifactSection(page, 'subtitle').getByText(/자막 \d+개/)).toBeVisible();
    await expect(artifactSection(page, 'subtitle').getByRole('button', { name: '편집' })).toBeVisible();

    // video: final render + download link.
    await approveStage(page, 'video');
    await expect(artifactSection(page, 'video').locator('video')).toBeVisible();
    await expect(artifactSection(page, 'video').getByRole('link', { name: '영상 다운로드' })).toBeVisible();

    // ── Final state ──────────────────────────────────────────────────────
    // NOTE: the backend never emits an SSE event for the run→"complete"
    // transition (only stage_entry/stage_exit/gate_pending/run_failed exist —
    // see run_service._consume), so the live page has no signal to flip the
    // header badge after the last gate. Verify completion at the API, the
    // authoritative source, rather than asserting a UI behavior that doesn't
    // exist yet. Flagged for follow-up; out of scope for test generation.
    const { body } = await apiRequest({ method: 'GET', path: `/runs/${runId}` });
    expect(body.status).toBe('complete');
  });
});
