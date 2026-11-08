import { defineConfig, devices } from "@playwright/test";

import { API_ORIGIN, WEB_ORIGIN, WEB_PORT } from "./e2e/env.mjs";

// Gerçek yığın: PostgreSQL + bulut API'si (ati-cloud-api) + derlenmiş site (next start).
// Önce `npm run build` gerekir.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: WEB_ORIGIN, trace: "off", locale: "tr-TR", timezoneId: "Europe/Istanbul" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node e2e/start-api.mjs",
      url: `${API_ORIGIN}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx next start -p ${WEB_PORT} -H 127.0.0.1`,
      url: WEB_ORIGIN,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ATI_PUBLIC_API_URL: API_ORIGIN,
        ATI_PUBLIC_WEB_URL: WEB_ORIGIN,
        ATI_PLANS_REVALIDATE_S: "0",
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
