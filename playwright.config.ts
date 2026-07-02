import { defineConfig } from '@playwright/test';

// E2E targets the FastAPI-served build (frontend/dist mounted at /app, story 3.1),
// not the Vite dev server — same origin as production, no CORS/proxy to configure.
// ponytail: single local env, no envConfigMap; add staging/prod configs when those environments exist.
const PORT = process.env.PORT ?? '8000';
const BASE_URL = process.env.BASE_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['junit', { outputFile: 'test-results/results.xml' }],
    ['list'],
  ],
  use: {
    baseURL: BASE_URL,
    actionTimeout: 15000,
    navigationTimeout: 30000,
    trace: 'retain-on-failure-and-retries',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  timeout: 60000,
  expect: { timeout: 10000 },
  webServer: {
    command: 'uv run uvicorn yt_flow.api.main:app --host 127.0.0.1 --port ' + PORT,
    url: `${BASE_URL}/app/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
