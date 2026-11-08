import { defineConfig, devices } from "@playwright/test";

/**
 * Uçtan uca arayüz testleri: gerçek motor (sahte Binance piyasa verisi + sahte test ağı borsası)
 * ve üretim derlemesi (`vite preview`). Önce `npm run build` çalıştırılmalıdır.
 */
export const ENGINE_PORT = 47999;
export const ENGINE_TOKEN = "e2e-belirtec-0123456789";
const UI_PORT = 4173;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // tek motor: testler sırayla ve ortak durumla çalışır
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    trace: "off",
    screenshot: "only-on-failure",
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `uv run --project ../engine python ../engine/tests/e2e_backend.py --port ${ENGINE_PORT} --token ${ENGINE_TOKEN} --origin http://127.0.0.1:${UI_PORT}`,
      url: `http://127.0.0.1:${ENGINE_PORT}/v1/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npx vite preview --host 127.0.0.1 --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}`,
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
