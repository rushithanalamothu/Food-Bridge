import { defineConfig } from '@playwright/test';

const release = process.env.FOODBRIDGE_RELEASE_E2E === '1';

export default defineConfig({
  testMatch: release ? '**/release.spec.ts' : /(?<!release)\.spec\.ts$/,
  testDir: './e2e',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: release ? 'http://localhost:55173' : 'http://127.0.0.1:5173',
    timezoneId: 'America/Los_Angeles',
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: release
    ? undefined
    : [
        {
          command: 'npm run dev',
          url: 'http://127.0.0.1:5173',
          reuseExistingServer: !process.env.CI,
          timeout: 30000,
        },
        {
          command: 'npm run dev -- --port 5174 --strictPort',
          url: 'http://127.0.0.1:5174',
          env: {
            VITE_OIDC_AUTHORITY: 'https://identity.foodbridge.test',
            VITE_OIDC_CLIENT_ID: 'foodbridge-browser-tests',
          },
          reuseExistingServer: false,
          timeout: 30000,
        },
      ],
});
