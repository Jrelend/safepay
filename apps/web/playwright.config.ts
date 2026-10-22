import { defineConfig, devices } from "@playwright/test";

/**
 * Browser E2E against a running stack (see scripts/e2e-stack.sh).
 * Each web origin must be the one its API allows (Origin check):
 *   "standard" → http://localhost:3000 (email verification required)
 *   "demo"     → http://localhost:3001 (BETA_DEMO_MODE, demo-*.spec.ts)
 *   "local-demo" → http://localhost:3002 (LOCAL_DEMO seeded accounts, localdemo.spec.ts)
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    ...devices["Pixel 7"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    locale: "mn-MN",
    timezoneId: "Asia/Ulaanbaatar",
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "standard", testIgnore: /(demo-.*|localdemo)\.spec\.ts/ },
    {
      name: "demo",
      testMatch: /demo-.*\.spec\.ts/,
      use: { baseURL: process.env.E2E_DEMO_BASE_URL ?? "http://localhost:3001" },
    },
    {
      name: "local-demo",
      testMatch: /localdemo\.spec\.ts/,
      use: { baseURL: process.env.E2E_LOCAL_DEMO_BASE_URL ?? "http://localhost:3002" },
    },
  ],
});
