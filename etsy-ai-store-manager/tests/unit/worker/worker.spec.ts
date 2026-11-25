import { describe, expect, it } from 'vitest';
import type { Job } from 'bullmq';
import { idempotencyKeyFor, redisConnection } from '../../../apps/worker/src/worker.js';
import { loadWorkerEnv } from '../../../apps/worker/src/env.js';

describe('worker helpers', () => {
  it('prefers the envelope idempotency key', () => {
    expect(
      idempotencyKeyFor({
        name: 'x',
        id: '1',
        data: { idempotencyKey: 'k1', payload: {} },
      } as unknown as Job),
    ).toBe('k1');
  });
  it('derives a deterministic key for scheduler jobs', () => {
    const job = {
      name: 'system.heartbeat',
      id: 'repeat:heartbeat:1700000000000',
      data: {},
    } as unknown as Job;
    expect(idempotencyKeyFor(job)).toBe('system.heartbeat:repeat:heartbeat:1700000000000');
  });
  it('parses redis URLs including TLS and db index', () => {
    expect(redisConnection('rediss://:p%40ss@cache:6380/2')).toMatchObject({
      host: 'cache',
      port: 6380,
      password: 'p@ss',
      db: 2,
      tls: {},
      maxRetriesPerRequest: null,
    });
  });
  it('validates worker env', () => {
    expect(() => loadWorkerEnv({})).toThrow(/DATABASE_URL/);
    expect(loadWorkerEnv({ DATABASE_URL: 'postgres://x' }).WORKER_CONCURRENCY).toBe(4);
  });
});
