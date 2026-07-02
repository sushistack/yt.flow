import { test, expect } from './support/fixtures/merged-fixtures';

// Framework scaffold verification only — real E2E scenarios (SYS-E2E-002) land
// in a later session (bmad-qa-generate-e2e-tests).
test.describe('@P0 framework smoke', () => {
  test('dashboard loads on the FastAPI-served build', async ({ page }) => {
    await page.goto('/app/');
    await expect(page).toHaveTitle(/.+/);
  });

  test('@API health check reaches the backend', async ({ apiRequest }) => {
    const { status } = await apiRequest({ method: 'GET', path: '/docs' });
    expect(status).toBe(200);
  });
});
