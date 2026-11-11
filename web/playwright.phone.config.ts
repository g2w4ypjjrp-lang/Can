import { defineConfig, devices } from "@playwright/test";

// Telefondan izleme uçtan uca: gerçek aktarma servisi (ati-cloud-relay) + gerçek işlem motoru
// (sahte Binance ile) + derlenmiş site. Telefon tarayıcısı QR adresini açar ve eşleşir.
// Önce `npm run build` gerekir.
export const RELAY_PORT = 47811;
export const ENGINE_PORT = 47812;
export const PHONE_WEB_PORT = 3110;
export const ENGINE_TOKEN = "telefon-e2e-belirtec-0123456789";

export default defineConfig({
  testDir: "e2e-phone",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PHONE_WEB_PORT}`, trace: "off", locale: "tr-TR", timezoneId: "Europe/Istanbul" },
  projects: [{ name: "iphone", use: { ...devices["iPhone 15"], browserName: "chromium" } }],
  webServer: [
    {
      command: `uv run --project ../cloud ati-cloud-relay --host 127.0.0.1 --port ${RELAY_PORT}`,
      url: `http://127.0.0.1:${RELAY_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `uv run --project ../engine python ../engine/tests/e2e_backend.py --port ${ENGINE_PORT} --token ${ENGINE_TOKEN} --relay ws://127.0.0.1:${RELAY_PORT}`,
      url: `http://127.0.0.1:${ENGINE_PORT}/v1/health`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: `npx next start -p ${PHONE_WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${PHONE_WEB_PORT}/telefon`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ATI_PUBLIC_API_URL: "http://127.0.0.1:9",
        ATI_PUBLIC_WEB_URL: `http://127.0.0.1:${PHONE_WEB_PORT}`,
        ATI_PUBLIC_RELAY_URL: `ws://127.0.0.1:${RELAY_PORT}`,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
