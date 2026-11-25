import { SignJWT } from 'jose';
import { randomUUID } from 'node:crypto';
import type pg from 'pg';
import { TEST_JWT_SECRET, TEST_SUPABASE_URL } from './env.js';

export async function signTestToken(
  sub: string,
  overrides: {
    secret?: string;
    issuer?: string;
    audience?: string;
    role?: string;
    expiresIn?: string;
    email?: string;
  } = {},
): Promise<string> {
  return new SignJWT({
    role: overrides.role ?? 'authenticated',
    email: overrides.email ?? `${sub}@example.test`,
  })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setSubject(sub)
    .setIssuer(overrides.issuer ?? `${TEST_SUPABASE_URL}/auth/v1`)
    .setAudience(overrides.audience ?? 'authenticated')
    .setIssuedAt()
    .setExpirationTime(overrides.expiresIn ?? '10m')
    .sign(new TextEncoder().encode(overrides.secret ?? TEST_JWT_SECRET));
}

/** Creates a Supabase auth user (shim table); the provisioning trigger creates the profile. */
export async function createAuthUser(
  pool: pg.Pool,
  fullName = 'Test User',
): Promise<{ id: string; email: string }> {
  const id = randomUUID();
  const email = `${id.slice(0, 8)}@example.test`;
  await pool.query(`insert into auth.users (id, email, raw_user_meta_data) values ($1, $2, $3)`, [
    id,
    email,
    JSON.stringify({ full_name: fullName }),
  ]);
  return { id, email };
}

/** Runs fn as the `authenticated` role with the given user's claims (like PostgREST). */
export async function asUser<T>(
  pool: pg.Pool,
  userId: string | null,
  fn: (c: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const c = await pool.connect();
  try {
    await c.query('begin');
    if (userId) {
      await c.query('set local role authenticated');
      await c.query(`select set_config('request.jwt.claims', $1, true)`, [
        JSON.stringify({ sub: userId, role: 'authenticated' }),
      ]);
    } else {
      await c.query('set local role anon');
    }
    const result = await fn(c);
    await c.query('commit');
    return result;
  } catch (e) {
    await c.query('rollback').catch(() => undefined);
    throw e;
  } finally {
    c.release();
  }
}
