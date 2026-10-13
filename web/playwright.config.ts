import { defineConfig, devices } from '@playwright/test'

const ci = process.env.CI !== undefined

/** The journeys run against the compose stack: nginx, the demo login, the API and Postgres with row-level security. */
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  // Headless Firefox on the Windows laptop this was built on freezes now and then, whatever the page: on a blank page
  // with none of this project's code, one `page.evaluate` took 15.2 s with four instances running and 2.2 s with one.
  // The limits below sit above that stall, and fewer workers make it rarer. They do not remove it, so a local run can
  // still lose a Firefox journey to a freeze; the assertions are the same in both browsers.
  workers: ci ? 2 : 4,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: ci ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.SPR_WEB_URL ?? 'http://127.0.0.1:8440',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: devices['Desktop Chrome'] },
    { name: 'firefox', use: devices['Desktop Firefox'] },
  ],
})
