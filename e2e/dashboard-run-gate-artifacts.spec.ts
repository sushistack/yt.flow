import { test, expect, type Page } from './support/fixtures/merged-fixtures';

// SYS-E2E-002 (P0) — the baseline journey: dashboard → create run → approve
// gate → artifact panel per stage type. Drives the real FastAPI app with all
// 5 external seams stubbed (scripts/run_e2e_stub_server.py via
// playwright.config.ts's webServer), so gates advance in seconds, not the
// minutes a real DeepSeek/ComfyUI/ffmpeg run would take.
//
// Related stories: 3.3 (Dashboard + SCP Picker), 3.4 (Run Detail + Artifact
// Panel), 3.5 (Gate Controls + Retry + SSE).

function stageSidebarButton(page: Page, stage: string) {
  return page.locator('aside').getByRole('button', { name: new RegExp(`^${stage}`) });
}

function artifactSection(page: Page, stage: string) {
  return page.getByRole('region', { name: `${stage} artifact` });
}

// Selects the stage in the sidebar (if not already selected), waits for its
// gate to go pending (SSE `gate_pending`), approves it, and waits for the
// gate controls to disappear — the visible proof the approval round-tripped.
async function approveStage(page: Page, stage: string) {
  await stageSidebarButton(page, stage).click();
  const section = artifactSection(page, stage);
  await expect(section.getByRole('heading', { name: stage })).toBeVisible();

  const approve = section.getByRole('button', { name: '승인' });
  await expect(approve).toBeVisible({ timeout: 15000 });
  await approve.click();
  await expect(approve).toBeHidden();
}

test.describe('@P0 SYS-E2E-002 dashboard → create run → approve gate → artifact panel', () => {
  test('runs SCP-096 through all 5 stages to completion', async ({ page, apiRequest }) => {
    await page.goto('/app/');

    // ── Dashboard → SCP Picker → create run (Story 3.3) ────────────────────
    // Top nav CTA — the empty-state CTA (same label) only renders when the run
    // list is empty, so scope to the nav to stay strict-mode safe either way.
    await page.getByRole('navigation').getByRole('button', { name: '+ 새 실행' }).click();

    const dialog = page.getByRole('dialog', { name: '새 실행 — SCP 선택' });
    await expect(dialog).toBeVisible();

    const search = page.getByRole('combobox', { name: 'SCP 검색' });
    await expect(search).toBeFocused();
    await search.fill('096');

    const option = page.getByRole('option').filter({ hasText: 'SCP-096' });
    await expect(option).toBeVisible();
    // Capture the created run's id from the response so the later completion
    // check is unambiguous even if other SCP-096 runs exist in the (gitignored,
    // locally-accumulating) dev db.
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/runs')),
      option.click(),
    ]);
    const runId = (await response.json()).id as string;

    await expect(dialog).toBeHidden();

    // New run row appears on the dashboard (Story 3.3, AC6) — click it to open
    // Run Detail. (Direct navigation to /app/runs/{id} 404s: the FastAPI static
    // mount has no SPA history-fallback for nested paths, only for /app/ itself
    // — a separate real gap, noted here rather than worked around.)
    await page.getByRole('main').getByRole('button', { name: /SCP-096/ }).first().click();

    // ── Run Detail (Story 3.4) ──────────────────────────────────────────────
    await expect(page.getByText('SCP-096', { exact: true })).toBeVisible();

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
