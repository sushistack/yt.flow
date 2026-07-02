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
  // Every spec drives one shared, single-process stub server (webServer below) —
  // two full 5-stage pipeline runs executing concurrently contend for the same
  // SQLite file and in-process LangGraph state and reliably time out each other's
  // requests (confirmed: default worker count intermittently fails both journey
  // specs). Serialize everywhere, not just CI.
  workers: 1,
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
    // Stub-profile server (scripts/run_e2e_stub_server.py), not the real app —
    // SYS-E2E-002 scenarios drive real gate/pipeline flows and must not hit
    // DeepSeek/Qwen/ComfyUI/ffmpeg for real. See that script's docstring.
    command: 'uv run python scripts/run_e2e_stub_server.py --port ' + PORT,
    url: `${BASE_URL}/app/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
