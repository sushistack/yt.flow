import { test, expect } from './support/fixtures/merged-fixtures';
import { approveStage, createRun } from './support/helpers';
import type { Page } from '@playwright/test';

// Journey 3 (P1) — A/B comparison view + accessibility floor.
// Related stories: 3.6 (AB Comparison + Accessibility), 4.1 (AB Run Creation),
// 4.3 (Results Storage + API + Auto Winner).
//
// There is no UI control to create a Variant B run — RunDetail's "A/B 비교"
// button only navigates to `/runs/{id}/ab` and expects a pair to already
// exist (frontend/src/pages/RunDetail.tsx:146). `POST /runs/{id}/ab` (story
// 4.1) is API-only, so this spec triggers it via `apiRequest`, same as any
// other operator action with no UI surface.
//
// More importantly: `run_service._trigger_ab_eval_if_variant_b` fires
// `eval_service.evaluate_ab()` fire-and-forget when a Variant B run completes
// (eval-ab-trigger-wiring), but `scripts/run_e2e_stub_server.py` deliberately
// forces `YTFLOW_DEEPSEEK_API_KEY=""` before boot — evaluate_ab() has no
// DeepSeek stub seam (raw httpx, not one of the 5 monkeypatched seams), so
// letting a real key through would make this spec hit the live API. That
// means the trigger runs but always fails with a non-fatal RuntimeError
// (AD-10) in this environment, so a real run through the live stack still
// reaches two *complete* variants but never a populated `ab_result` — the
// comparison page's honest, current behavior here is the "평가 대기"
// (evaluation pending) state. Test 1 below exercises that directly, the same
// way `dashboard-run-gate-artifacts.spec.ts` documents the missing
// run→complete SSE event instead of asserting a UI behavior that doesn't
// exist. Test 2 covers the axis-scores/winner rendering contract itself via
// mocked API responses — exactly what story 3.6's own Testing Requirements
// section asks for ("smoke spec that loads `/runs/{id}/ab` with mocked API
// responses").

const STAGES = ['scenario', 'image', 'tts', 'subtitle', 'video'] as const;

// Full reload (not a same-session pushState hop) before landing on the target
// run — switching runId via pushState alone while an SSE subscription for the
// *previous* run is still live left the stage sidebar stuck in a detach/
// reattach loop that never settled (observed directly: approveStage's click
// on the sidebar button timed out after 15s with "element was detached from
// the DOM, retrying"). A fresh load matches the proven `createRun` pattern
// and sidesteps whatever the stale-subscription race is instead of chasing
// it here — this spec generates tests, it doesn't fix `useRunProgress`.
async function gotoRun(page: Page, runId: string) {
  await page.goto('/app/');
  await page.evaluate((id) => {
    window.history.pushState({}, '', `/app/runs/${id}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, runId);
}

async function completeRun(page: Page, runId: string) {
  await gotoRun(page, runId);
  for (const stage of STAGES) {
    await approveStage(page, stage);
  }
}

test.describe('@P1 SYS-E2E-002 A/B comparison + accessibility floor', () => {
  test('A/B pair reaches comparison view; evaluation-pending state; keyboard stage nav', async ({
    page,
    apiRequest,
  }) => {
    const runA = await createRun(page, '096', 'SCP-096');
    await completeRun(page, runA);

    const { status, body } = await apiRequest({ method: 'POST', path: `/runs/${runA}/ab` });
    expect(status).toBe(201);
    const runB = body.id as string;
    expect(body.ab_pair_id).toBe(runA);

    await completeRun(page, runB);

    // Entry point (AC 3.6-1/2): keyboard-reachable "A/B 비교" nav button, not
    // a dashboard link — reached from whichever run's detail page is open.
    const abLink = page.getByRole('navigation').getByRole('button', { name: 'A/B 비교' });
    await expect(abLink).toBeVisible();
    await abLink.click();

    await expect(page.getByRole('heading', { name: 'A/B 비교' })).toBeVisible();
    const variantA = page.getByRole('region', { name: 'Variant A' });
    const variantB = page.getByRole('region', { name: 'Variant B' });
    await expect(variantA).toBeVisible();
    await expect(variantB).toBeVisible();
    await expect(variantA.getByText(runA)).toBeVisible();
    await expect(variantB.getByText(runB)).toBeVisible();

    // Documented gap: no evaluation trigger exists anywhere in the app, so a
    // genuinely completed pair can only ever show "평가 대기" — never a winner.
    await expect(page.getByRole('status').filter({ hasText: '평가 대기' })).toBeVisible();

    // Basic keyboard navigation (AC 3.6-2): Tab reaches the stage tabs, Enter
    // activates one — switching the rendered artifact section per variant.
    const stageTabs = page.locator('div[aria-label="비교 스테이지"]');
    const scenarioTab = stageTabs.getByRole('button', { name: 'scenario', exact: true });
    const imageTab = stageTabs.getByRole('button', { name: 'image', exact: true });

    await scenarioTab.focus();
    await expect(scenarioTab).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(imageTab).toBeFocused();
    await page.keyboard.press('Enter');

    await expect(variantA.getByRole('region', { name: 'image artifact' })).toBeVisible();
    await expect(variantB.getByRole('region', { name: 'image artifact' })).toBeVisible();
  });

  test('renders axis scores and winner for a completed, evaluated pair (mocked API)', async ({ page }) => {
    // Mocked per story 3.6's own testing guidance — evaluate_ab() has no live
    // trigger (see describe-block comment), so this is the only way to
    // exercise the score/winner rendering contract end-to-end in a browser.
    const runA = {
      id: 'ab-mock-a',
      scp_id: 'SCP-096',
      status: 'complete',
      current_stage: 'video',
      gate_states: null,
      prompt_variant: 'A',
      ab_pair_id: null,
      ab_result: {
        winner: 'A',
        reason: 'Variant A가 더 안정적입니다.',
        // CORRECTED IN STORY 13.2 along with types.ts and the vitest fixture. This
        // mock used `llm_scores` / `rule_scores` with `scene_count_match` /
        // `subtitle_sync` — names the backend has never written (see
        // eval_service._axis_scores_to_dict / _rule_metrics_to_dict). Every score cell
        // rendered the not-measured placeholder while the assertion below still passed,
        // because the assertion and the mock agreed with each other rather than with
        // the backend. Keep these key names in step with the backend, not with the UI.
        axis_scores: {
          A: { atmosphere: 5, narrative_coherence: 4, article_fidelity: 4 },
          B: { atmosphere: 3, narrative_coherence: 3, article_fidelity: 3 },
        },
        // The visual pair is omitted on purpose: it exists only for runs the offline
        // scorer was run on, so this mock exercises the "not measured" rendering too.
        rule_based_scores: {
          A: {
            scene_count_match_rate: 1, subtitle_sync_error: 1, audio_duration_variance: 0,
            cut_alignment_error: 0, motion_archetype_coverage: 1, motion_repeat_ratio: 0,
          },
          B: {
            scene_count_match_rate: 1, subtitle_sync_error: 1, audio_duration_variance: 0,
            cut_alignment_error: 0, motion_archetype_coverage: 1, motion_repeat_ratio: 0,
          },
        },
      },
      error: null,
      started_at: '2026-07-01T10:00:00Z',
      updated_at: '2026-07-01T10:10:00Z',
      langfuse_trace_url: null,
    };
    const runB = { ...runA, id: 'ab-mock-b', prompt_variant: 'B', ab_pair_id: 'ab-mock-a' };

    await page.route('**/runs/ab-mock-a', (route) => route.fulfill({ json: runA }));
    await page.route('**/runs', (route) => route.fulfill({ json: [runA, runB] }));
    await page.route('**/runs/ab-mock-a/stages/*/artifacts', (route) => route.fulfill({ status: 404, json: {} }));
    await page.route('**/runs/ab-mock-b/stages/*/artifacts', (route) => route.fulfill({ status: 404, json: {} }));

    await page.goto('/app/');
    await page.evaluate(() => {
      window.history.pushState({}, '', '/app/runs/ab-mock-a/ab');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    await expect(page.getByRole('heading', { name: 'A/B 비교' })).toBeVisible();
    await expect(page.getByText('승자: Variant A')).toBeVisible();

    const variantA = page.getByRole('region', { name: 'Variant A' });
    const variantB = page.getByRole('region', { name: 'Variant B' });
    // 3 judge axes + 8 rule metrics per variant. The last two rule rows are the visual
    // pair, absent from the mock above, so they render the not-measured placeholder —
    // asserting that explicitly is what keeps "absent" from silently becoming 0.
    const notMeasured = '결과 없음';
    await expect(variantA.locator('dl dd')).toHaveText([
      '5', '4', '4',
      '1', '1', '0', '0', '1', '0',
      notMeasured, notMeasured,
    ]);
    await expect(variantB.locator('dl dd')).toHaveText([
      '3', '3', '3',
      '1', '1', '0', '0', '1', '0',
      notMeasured, notMeasured,
    ]);
  });
});
