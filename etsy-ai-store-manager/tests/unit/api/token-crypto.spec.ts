import { describe, expect, it } from 'vitest';
import { TokenCryptoService } from '../../../apps/api/src/security/token-crypto.service.js';
import type { Env } from '../../../apps/api/src/config/env.js';

const make = (key = Buffer.alloc(32, 1).toString('base64'), version = 1) =>
  new TokenCryptoService({
    TOKEN_ENCRYPTION_KEY: key,
    TOKEN_ENCRYPTION_KEY_VERSION: version,
  } as Env);

describe('TokenCryptoService (AES-256-GCM)', () => {
  it('round-trips and never contains the plaintext', () => {
    const c = make();
    const env = c.encrypt('etsy-access-token-123', 'account:abc');
    expect(env).not.toContain('etsy-access-token-123');
    expect(env.startsWith('v1.')).toBe(true);
    expect(c.decrypt(env, 'account:abc')).toBe('etsy-access-token-123');
  });
  it('uses a random IV (same plaintext -> different ciphertext)', () => {
    const c = make();
    expect(c.encrypt('x', 'a')).not.toBe(c.encrypt('x', 'a'));
  });
  it('fails when bound to a different account (AAD)', () => {
    const c = make();
    expect(() => c.decrypt(c.encrypt('t', 'account:1'), 'account:2')).toThrow();
  });
  it('detects tampering', () => {
    const c = make();
    const parts = c.encrypt('secret-token', 'a').split('.');
    const ct = Buffer.from(parts[3]!, 'base64url');
    ct[0] = ct[0]! ^ 0xff;
    parts[3] = ct.toString('base64url');
    expect(() => c.decrypt(parts.join('.'), 'a')).toThrow();
  });
  it('fails with a different key', () => {
    const env = make().encrypt('t', 'a');
    expect(() => make(Buffer.alloc(32, 2).toString('base64')).decrypt(env, 'a')).toThrow();
  });
  it('rejects unknown key versions and malformed envelopes', () => {
    const env = make(undefined, 2).encrypt('t', 'a');
    expect(() => make(undefined, 1).decrypt(env, 'a')).toThrow(/key version/);
    expect(() => make().decrypt('garbage', 'a')).toThrow();
  });
});
