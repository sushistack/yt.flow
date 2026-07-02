import { type Page, expect } from '@playwright/test';

// Shared Run Detail locators/actions (Story 3.4/3.5) reused across journey specs.

export function stageSidebarButton(page: Page, stage: string) {
  return page.locator('aside').getByRole('button', { name: new RegExp(`^${stage}`) });
}

export function artifactSection(page: Page, stage: string) {
  return page.getByRole('region', { name: `${stage} artifact` });
}

// Selects the stage in the sidebar (if not already selected), waits for its
// gate to go pending (SSE `gate_pending`), approves it, and waits for the
// gate controls to disappear — the visible proof the approval round-tripped.
export async function approveStage(page: Page, stage: string) {
  await stageSidebarButton(page, stage).click();
  const section = artifactSection(page, stage);
  await expect(section.getByRole('heading', { name: stage })).toBeVisible();

  const approve = section.getByRole('button', { name: '승인' });
  // Stub stages normally resolve in well under a second; the generous timeout
  // is headroom for local/CI machine jitter, not expected pipeline latency.
  await expect(approve).toBeVisible({ timeout: 25000 });
  await approve.click();
  await expect(approve).toBeHidden();
}

// Dashboard → SCP Picker → create run (Story 3.3), then open the resulting
// Run Detail page. Returns the created run's id captured from the POST /runs
// response, so later assertions don't depend on dashboard row ordering.
export async function createRun(page: Page, scpQuery: string, scpLabel: string) {
  await page.goto('/app/');
  await page.getByRole('navigation').getByRole('button', { name: '+ 새 실행' }).click();

  const dialog = page.getByRole('dialog', { name: '새 실행 — SCP 선택' });
  await expect(dialog).toBeVisible();

  const search = page.getByRole('combobox', { name: 'SCP 검색' });
  await expect(search).toBeFocused();
  await search.fill(scpQuery);

  const option = page.getByRole('option').filter({ hasText: scpLabel });
  await expect(option).toBeVisible();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/runs')),
    option.click(),
  ]);
  const runId = (await response.json()).id as string;

  await expect(dialog).toBeHidden();

  // A fresh server-side GET to /app/runs/{id} 404s (no SPA history-fallback for
  // nested paths), but the SPA is already loaded here, so drive its client-side
  // router directly — the same pushState + popstate dispatch navigate() does
  // (frontend/src/lib/navigate.ts). This is deterministic; clicking the new
  // dashboard row by SCP label is not, once the dev db accumulates other runs
  // for the same SCP (e.g. from repeat local/CI runs): Dashboard.tsx's
  // onCreated() optimistically prepends the new run, then fires an unawaited
  // getRuns() refetch that can reorder/replace the list before the click
  // lands, so `.first()` can resolve to a stale row instead of this run.
  await page.evaluate((id) => {
    window.history.pushState({}, '', `/app/runs/${id}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, runId);
  await expect(page.getByText(scpLabel, { exact: true })).toBeVisible();

  return runId;
}
