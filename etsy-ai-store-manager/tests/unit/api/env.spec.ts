import { describe, expect, it } from 'vitest';
import { loadEnv } from '../../../apps/api/src/config/env.js';

const base = {
  DATABASE_URL: 'postgres://u:p@localhost:5432/db',
  SUPABASE_URL: 'https://abc.supabase.co',
  TOKEN_ENCRYPTION_KEY: Buffer.alloc(32).toString('base64'),
};

describe('API env validation', () => {
  it('loads with sane defaults', () => {
    const env = loadEnv(base);
    expect(env.API_PORT).toBe(4000);
    expect(env.SWAGGER_ENABLED).toBe(true);
    expect(env.RATE_LIMIT_PER_MINUTE).toBe(120);
  });
  it('requires a 32-byte token encryption key', () => {
    expect(() => loadEnv({ ...base, TOKEN_ENCRYPTION_KEY: 'short' })).toThrow(
      /TOKEN_ENCRYPTION_KEY/,
    );
  });
  it('requires DATABASE_URL and SUPABASE_URL', () => {
    expect(() => loadEnv({ ...base, DATABASE_URL: '' })).toThrow(/DATABASE_URL/);
    expect(() => loadEnv({ ...base, SUPABASE_URL: 'not-a-url' })).toThrow(/SUPABASE_URL/);
  });
  it('requires SSL for a remote production database', () => {
    expect(() =>
      loadEnv({
        ...base,
        NODE_ENV: 'production',
        DATABASE_URL: 'postgres://u:p@db.example.com:5432/x',
      }),
    ).toThrow(/SSL/);
    expect(
      loadEnv({
        ...base,
        NODE_ENV: 'production',
        DATABASE_URL: 'postgres://u:p@db.example.com:5432/x?sslmode=require',
      }).NODE_ENV,
    ).toBe('production');
    expect(
      loadEnv({ ...base, NODE_ENV: 'production', DATABASE_URL: 'postgres://u:p@127.0.0.1:5432/x' })
        .NODE_ENV,
    ).toBe('production');
  });
});
