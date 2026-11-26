import { describe, expect, it } from 'vitest';
import { trackerFor } from '../../../apps/api/src/common/user-throttler.guard.js';

describe('rate-limit tracker', () => {
  it('separates users that share the web server IP', () => {
    const a = trackerFor({
      ip: '10.0.0.5',
      headers: { authorization: 'Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.1' },
    });
    const b = trackerFor({
      ip: '10.0.0.5',
      headers: { authorization: 'Bearer bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.2' },
    });
    expect(a).not.toBe(b);
    expect(a).toMatch(/^tok:[0-9a-f]{32}$/);
    expect(a).not.toContain('aaaa'); // the token itself is never used as a key
  });
  it('falls back to the client IP without a token', () => {
    expect(trackerFor({ ip: '10.0.0.5', headers: {} })).toBe('ip:10.0.0.5');
    expect(
      trackerFor({
        ip: '10.0.0.5',
        ips: ['203.0.113.9'],
        headers: { authorization: 'Bearer short' },
      }),
    ).toBe('ip:203.0.113.9');
  });
});
