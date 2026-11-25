import type { INestApplication } from '@nestjs/common';
import { createApp } from '../../apps/api/src/bootstrap.js';
import { loadEnv } from '../../apps/api/src/config/env.js';
import {
  TEST_DATABASE_URL,
  TEST_JWT_SECRET,
  TEST_REDIS_URL,
  TEST_SUPABASE_URL,
  TEST_TOKEN_KEY,
} from './env.js';

export async function startTestApi(
  overrides: Record<string, string> = {},
): Promise<INestApplication> {
  const env = loadEnv({
    NODE_ENV: 'test',
    DATABASE_URL: TEST_DATABASE_URL,
    SUPABASE_URL: TEST_SUPABASE_URL,
    SUPABASE_JWT_SECRET: TEST_JWT_SECRET,
    TOKEN_ENCRYPTION_KEY: TEST_TOKEN_KEY,
    REDIS_URL: TEST_REDIS_URL,
    LOG_LEVEL: 'silent',
    RATE_LIMIT_PER_MINUTE: '1000',
    ...overrides,
  });
  const { app } = await createApp(env);
  await app.init();
  return app;
}
