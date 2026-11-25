export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? 'postgres://esm:esm@localhost:5432/esm_test';
export const TEST_REDIS_URL = process.env.TEST_REDIS_URL ?? 'redis://localhost:6379/15';
export const TEST_SUPABASE_URL = 'http://supabase.test';
export const TEST_JWT_SECRET = 'test-only-jwt-secret-with-enough-length-0123456789';
export const TEST_TOKEN_KEY = Buffer.alloc(32, 7).toString('base64');
