import { test, expect } from './support/fixtures/merged-fixtures';
import { artifactSection, approveStage, createRun, stageSidebarButton } from './support/helpers';

// Journey 2 (P1) — gate reject → retry trigger → inline artifact edit →
// re-approve → downstream stage rerun, plus the B-1 concurrency guard.
// Related stories: 3.5 (Gate Controls + Retry + SSE), 2.4 (backend retry/edit
// — already covered at the API level by tests/api/test_stages.py; this
// exercises the UI wiring), and the B-1 dev-dependency chore (concurrency
// guard: run_service.py's `_MUTABLE_STATES` check on retry_stage/edit_artifact).
//
// Two distinct "retry" mechanisms exist server-side (pipeline/graph.py +
// run_service.py._consume): rejecting the `scenario` gate routes to END and
// fails the run, but rejecting any other stage's gate loops the graph back
// into that same stage node and re-interrupts automatically — no explicit
// `POST /retry` call involved. The explicit "재시도" button (calling
// `POST .../retry`) is only offered for stages already `approved`/`rejected`/
// `failed`. This test exercises both: reject on `subtitle` for the implicit
// gate-driven retry loop, and an explicit `재시도` click on `image` (after
// approving it) for the manual retry path — the latter is also the only one
// of the two whose `run.status` write is synchronous before the response
// returns, making it the reliable place to probe the concurrency guard.

async function rejectAndExpectAutoRetry(page: import('@playwright/test').Page, stage: string) {
  await stageSidebarButton(page, stage).click();
  const section = artifactSection(page, stage);
  const reject = section.getByRole('button', { name: '반려' });
  await expect(reject).toBeVisible({ timeout: 15000 });

  const [response] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes(`/stages/${stage}/gate`)),
    reject.click(),
  ]);
  expect(response.status()).toBe(202);
  await expect(reject).toBeHidden();

  // Non-scenario gates loop back into the same stage node and re-interrupt —
  // rejection itself is what re-triggers execution. Wait for the gate to
  // cycle back to pending as proof the stage actually re-ran.
  await expect(section.getByRole('button', { name: '승인' })).toBeVisible({ timeout: 20000 });
}

async function editArtifactAndSave(page: import('@playwright/test').Page, stage: string, newText: string) {
  const section = artifactSection(page, stage);
  await section.getByRole('button', { name: '편집' }).click();
  await section.getByRole('textbox').fill(newText);

  const [response] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/stages/${stage}/artifact`)),
    section.getByRole('button', { name: '저장' }).click(),
  ]);
  expect(response.status()).toBe(200);

  await expect(section.getByRole('button', { name: '편집' })).toBeVisible();
  await expect(section.getByText(newText)).toBeVisible();
}

test.describe('@P1 gate reject → retry trigger → inline edit → re-approve → downstream rerun', () => {
  test('subtitle reject/edit cycle and image explicit-retry concurrency guard', async ({ page, apiRequest }) => {
    const runId = await createRun(page, '096', 'SCP-096');

    // ── scenario: inline edit before first approval ─────────────────────────
    await expect(artifactSection(page, 'scenario').getByRole('button', { name: '승인' })).toBeVisible({
      timeout: 15000,
    });
    await editArtifactAndSave(page, 'scenario', 'E2E-edited scenario narration for run ' + runId);
    await approveStage(page, 'scenario');

    // ── image: approve, then explicitly retry via the 재시도 button ────────
    await approveStage(page, 'image');
    await expect(artifactSection(page, 'image').locator('img').first()).toBeVisible();

    const imageSection = artifactSection(page, 'image');
    const imageRetryBtn = imageSection.getByRole('button', { name: '재시도' });
    await expect(imageRetryBtn).toBeVisible();
    await imageRetryBtn.click();

    const confirmAlert = imageSection.getByRole('alert');
    await expect(confirmAlert).toBeVisible();
    await expect(confirmAlert).toContainText('이 스테이지를 다시 실행합니까?');

    const [retryResponse] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes('/stages/image/retry')),
      confirmAlert.getByRole('button', { name: '확인' }).click(),
    ]);
    expect(retryResponse.status()).toBe(202);

    // B-1 concurrency guard, API level: run.status is "running" the instant
    // the 202 above is received (retry_stage writes it synchronously before
    // returning), so any other mutation on this run is rejected with 409
    // until the stage settles back to a gate. The stub pipeline re-executes a
    // stage in milliseconds, so both probes are fired concurrently right
    // after the 202 to maximize the chance they land inside that window
    // rather than sequentially (a real, if narrow, timing dependency).
    const [blockedRetry, blockedEdit] = await Promise.all([
      apiRequest({ method: 'POST', path: `/runs/${runId}/stages/image/retry` }),
      apiRequest({
        method: 'PATCH',
        path: `/runs/${runId}/stages/scenario/artifact`,
        body: { body: 'should be rejected while another stage is running' },
      }),
    ]);
    expect(blockedRetry.status).toBe(409);
    expect(blockedRetry.body.detail).toContain('running');
    expect(blockedEdit.status).toBe(409);
    expect(blockedEdit.body.detail).toContain('running');

    // B-1 concurrency guard, UI reflection: once retry is in flight the
    // stage's own controls disappear immediately (gate state flips away from
    // approved/rejected/failed) — there is no way to double-trigger it
    // through the UI while the run is running.
    await expect(imageRetryBtn).toBeHidden();
    await expect(confirmAlert).toBeHidden();

    await approveStage(page, 'image');

    // ── tts: plain approval ──────────────────────────────────────────────
    await approveStage(page, 'tts');
    await expect(artifactSection(page, 'tts').locator('audio').first()).toBeVisible();

    // ── subtitle: reject → automatic retry loop → inline edit → re-approve ──
    await rejectAndExpectAutoRetry(page, 'subtitle');
    await editArtifactAndSave(page, 'subtitle', '00:00:01,000 --> 00:00:02,000\nE2E-edited subtitle cue');
    await approveStage(page, 'subtitle');

    // ── video: downstream stage re-runs cleanly after the subtitle churn ────
    await approveStage(page, 'video');
    await expect(artifactSection(page, 'video').locator('video')).toBeVisible();
    await expect(artifactSection(page, 'video').getByRole('link', { name: '영상 다운로드' })).toBeVisible();

    // No SSE event exists for the run→"complete" transition (same documented
    // gap as SYS-E2E-002) — verify completion at the API.
    const { body } = await apiRequest({ method: 'GET', path: `/runs/${runId}` });
    expect(body.status).toBe('complete');
  });
});
