import { defineConfig, devices } from '@playwright/test';

/**
 * E2E against the real stack: local Supabase (supabase start), NestJS API and
 * the production Next.js build. Requires: `supabase start --workdir packages/database`,
 * Redis, and env vars E2E_SUPABASE_URL / E2E_SUPABASE_ANON_KEY / E2E_DATABASE_URL.
 */
const SUPABASE_URL = process.env.E2E_SUPABASE_URL ?? 'http://127.0.0.1:54321';
const SUPABASE_KEY = process.env.E2E_SUPABASE_ANON_KEY ?? '';
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql://postgres:postgres@127.0.0.1:54322/postgres';
const API_PORT = 4300;
const WEB_PORT = 3300;
const STUB_PORT = 4600;
const PRINTIFY_PORT = 4700;
const PRINTIFY_ENV = {
  PRINTIFY_API_TOKEN: 'printify-test-token',
  PRINTIFY_API_BASE_URL: `http://127.0.0.1:${PRINTIFY_PORT}`,
};
const TOKEN_KEY = Buffer.alloc(32, 9).toString('base64');
// Etsy contract stub (test double) — see tests/helpers/etsy-stub.ts
const ETSY_ENV = {
  ETSY_KEYSTRING: 'stubkeystring123',
  ETSY_SHARED_SECRET: 'stubsharedsecret',
  ETSY_REDIRECT_URI: `http://127.0.0.1:${API_PORT}/api/v1/integrations/etsy/callback`,
  ETSY_CONNECT_URL: `http://127.0.0.1:${STUB_PORT}/oauth/connect`,
  ETSY_TOKEN_URL: `http://127.0.0.1:${STUB_PORT}/v3/public/oauth/token`,
  ETSY_API_BASE_URL: `http://127.0.0.1:${STUB_PORT}`,
};

export default defineConfig({
  testDir: '../../tests/e2e',
  globalSetup: '../../tests/e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: 'off' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] }, grepInvert: /@mobile/ },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: 'node ../../tests/e2e/run-etsy-stub.ts',
      url: `http://127.0.0.1:${STUB_PORT}/__test/listings/900001`,
      reuseExistingServer: false,
      env: { ETSY_STUB_PORT: String(STUB_PORT) },
    },
    {
      command: 'node ../../tests/e2e/run-printify-stub.ts',
      url: `http://127.0.0.1:${PRINTIFY_PORT}/__test/published`,
      reuseExistingServer: false,
      env: { PRINTIFY_STUB_PORT: String(PRINTIFY_PORT) },
    },
    {
      command: 'node ../worker/dist/main.js',
      reuseExistingServer: false,
      env: {
        NODE_ENV: 'test',
        DATABASE_URL,
        REDIS_URL: 'redis://127.0.0.1:6379/14',
        TOKEN_ENCRYPTION_KEY: TOKEN_KEY,
        LOG_LEVEL: 'warn',
        HEARTBEAT_EVERY_MS: '3600000',
        ...ETSY_ENV,
        ...PRINTIFY_ENV,
      },
    },
    {
      command: 'node ../api/dist/main.js',
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      env: {
        NODE_ENV: 'test',
        API_PORT: String(API_PORT),
        DATABASE_URL,
        SUPABASE_URL,
        SUPABASE_JWT_SECRET: '',
        TOKEN_ENCRYPTION_KEY: TOKEN_KEY,
        REDIS_URL: 'redis://127.0.0.1:6379/14',
        WEB_APP_URL: `http://127.0.0.1:${WEB_PORT}`,
        CORS_ORIGINS: `http://127.0.0.1:${WEB_PORT}`,
        ...ETSY_ENV,
        ...PRINTIFY_ENV,
        LOG_LEVEL: 'warn',
      },
    },
    {
      command: 'node .next/standalone/apps/web/server.js',
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      reuseExistingServer: false,
      env: {
        PORT: String(WEB_PORT),
        HOSTNAME: '127.0.0.1',
        NEXT_PUBLIC_SUPABASE_URL: SUPABASE_URL,
        NEXT_PUBLIC_SUPABASE_ANON_KEY: SUPABASE_KEY,
        API_INTERNAL_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_PUBLIC_SITE_URL: `http://127.0.0.1:${WEB_PORT}`,
      },
    },
  ],
});
