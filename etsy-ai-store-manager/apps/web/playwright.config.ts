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

export default defineConfig({
  testDir: '../../tests/e2e',
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
      command: 'node ../api/dist/main.js',
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      env: {
        NODE_ENV: 'test',
        API_PORT: String(API_PORT),
        DATABASE_URL,
        SUPABASE_URL,
        SUPABASE_JWT_SECRET: '',
        TOKEN_ENCRYPTION_KEY: Buffer.alloc(32, 9).toString('base64'),
        CORS_ORIGINS: `http://127.0.0.1:${WEB_PORT}`,
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
