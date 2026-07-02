import { mergeTests } from '@playwright/test';
import { test as apiRequestFixture } from '@seontechnologies/playwright-utils/api-request/fixtures';
import { test as logFixture } from '@seontechnologies/playwright-utils/log/fixtures';

// ponytail: only api-request + log merged for now — auth-session/recurse/burn-in
// add when a real test needs them (stub-server-mode session, file 2/3).
export const test = mergeTests(apiRequestFixture, logFixture);

export { expect } from '@playwright/test';
