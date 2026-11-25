import { describe, expect, it } from 'vitest';
import { SupabaseJwtService } from '../../../apps/api/src/auth/supabase-jwt.service.js';
import type { Env } from '../../../apps/api/src/config/env.js';
import { signTestToken } from '../../helpers/auth.js';
import { TEST_JWT_SECRET, TEST_SUPABASE_URL } from '../../helpers/env.js';

const svc = new SupabaseJwtService({
  SUPABASE_URL: TEST_SUPABASE_URL,
  SUPABASE_JWT_SECRET: TEST_JWT_SECRET,
  SUPABASE_JWT_AUDIENCE: 'authenticated',
} as Env);
const sub = '11111111-1111-4111-8111-111111111111';

describe('SupabaseJwtService', () => {
  it('accepts a valid Supabase access token', async () => {
    const ctx = await svc.verify(await signTestToken(sub));
    expect(ctx.userId).toBe(sub);
    expect(ctx.email).toBe(`${sub}@example.test`);
  });
  it.each([
    ['wrong secret', { secret: 'another-secret-another-secret-another-secret' }],
    ['wrong issuer', { issuer: 'https://evil.example/auth/v1' }],
    ['wrong audience', { audience: 'service' }],
    ['anon role', { role: 'anon' }],
    ['service_role token', { role: 'service_role' }],
    ['expired', { expiresIn: '-1m' }],
  ])('rejects %s', async (_name, overrides) => {
    await expect(svc.verify(await signTestToken(sub, overrides))).rejects.toThrow();
  });
  it('rejects garbage and alg=none tokens', async () => {
    await expect(svc.verify('not.a.jwt')).rejects.toThrow();
    const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
    const body = Buffer.from(
      JSON.stringify({ sub, role: 'authenticated', aud: 'authenticated' }),
    ).toString('base64url');
    await expect(svc.verify(`${header}.${body}.`)).rejects.toThrow();
  });
});
