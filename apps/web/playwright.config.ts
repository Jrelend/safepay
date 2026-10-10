import { defineConfig, devices } from "@playwright/test";

/**
 * Browser E2E against a running stack (see scripts/e2e-stack.sh).
 * The origin must be http://localhost:3000: the API's Origin check allows only it.
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
});
