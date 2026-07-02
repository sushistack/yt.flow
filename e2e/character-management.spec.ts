import { test, expect } from './support/fixtures/merged-fixtures';

// SYS-E2E-003 — character management journey: character list → new character
// → reference image search → multi-angle candidate generation → finalize →
// angle gallery. Drives the real FastAPI app with all 7 external seams
// stubbed (scripts/run_e2e_stub_server.py): the 5 pipeline seams plus
// DuckDuckGo image search + its download step (Story 1.11's real network
// calls are unstubbed by default — see run_e2e_stub_server.py's
// apply_stub_profile for why those two extra seams exist).
//
// Related stories: 3.7 (Character Management UI), 1.11 (Character Domain +
// Reference Search), 1.12 (Multi-Angle Character Generation).

function referencePanel(page) {
  return page.getByRole('region', { name: '참조 이미지' });
}

function candidatePanel(page) {
  return page.getByRole('region', { name: '후보 생성' });
}

function angleStatus(page, label: string) {
  return page.getByRole('status', { name: new RegExp(`^${label} —`) });
}

test.describe('@P0 SYS-E2E-003 character list → create → search refs → generate → finalize → gallery', () => {
  test('creates SCP-3007 and generates all 4 angle candidates to completion', async ({ page }) => {
    // ── Character List (Story 3.7 AC1) ──────────────────────────────────────
    // Load the dashboard first, then navigate client-side — a fresh server GET
    // to /app/characters 404s (StaticFiles html=True has no SPA history-
    // fallback for nested paths; same gotcha documented in helpers.ts's
    // createRun() for /app/runs/{id}).
    await page.goto('/app/');
    await page.getByRole('navigation').getByRole('link', { name: '캐릭터' }).click();
    await expect(page).toHaveURL(/\/app\/characters\/?$/);
    // Scoped to the nav — an empty character list also renders a same-text
    // "+ 새 캐릭터" CTA in the empty state, which would otherwise double-match.
    await page.getByRole('navigation').getByRole('button', { name: '+ 새 캐릭터' }).click();

    const dialog = page.getByRole('dialog', { name: '새 캐릭터' });
    await expect(dialog).toBeVisible();

    const scpId = `SCP-3007-${Date.now()}`;
    await dialog.getByLabel('SCP ID').fill(scpId);
    await dialog.getByLabel('이름').fill('작은 재앙');

    const [createResponse] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/characters')),
      dialog.getByRole('button', { name: '생성' }).click(),
    ]);
    const charId = (await createResponse.json()).id as string;
    await expect(dialog).toBeHidden();

    // Navigate straight to the detail route rather than relying on list
    // ordering — same rationale as e2e/support/helpers.ts's createRun().
    await page.evaluate((id) => {
      window.history.pushState({}, '', `/app/characters/${id}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, charId);
    await expect(page.getByText(scpId, { exact: true })).toBeVisible();

    // ── Reference Image Search (Story 1.11 AC3/AC4) ─────────────────────────
    const refs = referencePanel(page);
    await refs.getByRole('button', { name: '참조 이미지 검색' }).click();
    await expect(refs.locator('img')).toHaveCount(3, { timeout: 15000 });

    // ── Multi-Angle Candidate Generation (Story 1.12 AC3/AC4) ───────────────
    const candidates = candidatePanel(page);
    await candidates.getByRole('button', { name: '후보 생성' }).click();

    for (const label of ['전면', '후면', '측면', '3/4']) {
      await expect(angleStatus(page, label)).toHaveAccessibleName(`${label} — 완료`, { timeout: 20000 });
    }

    // ── Finalize + Angle Gallery (Story 1.12 AC5/AC6, Story 3.7 AC2) ────────
    const [finalizeResponse] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/finalize')),
      candidates.getByRole('button', { name: '캐릭터 확정' }).click(),
    ]);
    expect(finalizeResponse.ok()).toBe(true);

    const gallery = page.getByRole('group', { name: '캐릭터 각도 갤러리' });
    await expect(gallery.locator('img')).toHaveCount(4, { timeout: 10000 });

    const { body } = await page.evaluate(async (id) => {
      const res = await fetch(`/api/characters/${id}`);
      return { body: await res.json() };
    }, charId);
    expect(body.angle_front_path).toBeTruthy();
    expect(body.angle_back_path).toBeTruthy();
    expect(body.angle_side_path).toBeTruthy();
    expect(body.angle_three_quarter_path).toBeTruthy();
  });
});
