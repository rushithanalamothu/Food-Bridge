import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch:
    process.env.FOODBRIDGE_RELEASE_E2E === '1' ? '**/release.spec.ts' : '**/intake.spec.ts',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL:
      process.env.FOODBRIDGE_RELEASE_E2E === '1'
        ? 'http://localhost:55173'
        : 'http://127.0.0.1:5173',
    timezoneId: 'America/Los_Angeles',
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer:
    process.env.FOODBRIDGE_RELEASE_E2E === '1'
      ? undefined
      : {
          command: 'npm run dev',
          url: 'http://127.0.0.1:5173',
          reuseExistingServer: !process.env.CI,
          timeout: 30000,
        },
});
