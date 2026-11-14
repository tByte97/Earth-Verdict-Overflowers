import { defineConfig } from '@playwright/test';

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.test.mjs',
  workers: 1,
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
    launchOptions: process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {},
  },
  webServer: process.env.TEST_BASE_URL ? undefined : {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort',
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
