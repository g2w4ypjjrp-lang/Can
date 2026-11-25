import { afterAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { Queue, QueueEvents, Worker } from 'bullmq';
import { pino } from 'pino';
import { runIdempotent } from '../../../apps/worker/src/idempotency.js';
import { createProcessor, redisConnection, startWorker } from '../../../apps/worker/src/worker.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL } from '../../helpers/env.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
const logger = pino({ level: 'silent' });
afterAll(() => pool.end());

const meta = (key: string, attempt = 1, maxAttempts = 3) => ({
  idempotencyKey: key,
  jobName: 'test.job',
  queue: 'test',
  attempt,
  maxAttempts,
});

describe('runIdempotent', () => {
  it('executes once and skips duplicates', async () => {
    const key = `dup-${Date.now()}`;
    let calls = 0;
    const first = await runIdempotent(pool, meta(key), async () => ++calls);
    const second = await runIdempotent(pool, meta(key), async () => ++calls);
    expect(first).toEqual({ status: 'executed', result: 1 });
    expect(second).toEqual({ status: 'skipped', reason: 'already_succeeded' });
    expect(calls).toBe(1);
  });

  it('allows retry after a failure and records attempts / errors', async () => {
    const key = `retry-${Date.now()}`;
    await expect(
      runIdempotent(pool, meta(key, 1), async () => {
        throw new Error('boom');
      }),
    ).rejects.toThrow('boom');
    let row = (
      await pool.query(
        `select status, attempts, last_error from public.automation_jobs where idempotency_key = $1`,
        [key],
      )
    ).rows[0];
    expect(row).toEqual({ status: 'queued', attempts: 1, last_error: 'boom' });
    await runIdempotent(pool, meta(key, 2), async () => 'ok');
    row = (
      await pool.query(
        `select status, attempts, last_error from public.automation_jobs where idempotency_key = $1`,
        [key],
      )
    ).rows[0];
    expect(row).toEqual({ status: 'succeeded', attempts: 2, last_error: null });
  });

  it('marks the job failed after the final attempt', async () => {
    const key = `final-${Date.now()}`;
    await expect(
      runIdempotent(pool, meta(key, 3, 3), async () => {
        throw new Error('nope');
      }),
    ).rejects.toThrow();
    const row = (
      await pool.query(`select status from public.automation_jobs where idempotency_key = $1`, [
        key,
      ])
    ).rows[0];
    expect(row.status).toBe('failed');
  });

  it('runs concurrent duplicates only once', async () => {
    const key = `conc-${Date.now()}`;
    let calls = 0;
    const slow = async () => {
      calls++;
      await new Promise((r) => setTimeout(r, 200));
      return calls;
    };
    const results = await Promise.all([
      runIdempotent(pool, meta(key), slow),
      runIdempotent(pool, meta(key), slow),
    ]);
    expect(calls).toBe(1);
    expect(results.map((r) => r.status).sort()).toEqual(['executed', 'skipped']);
  });
});

describe('runIdempotent lease', () => {
  it('reclaims a job abandoned in running state by a crashed worker', async () => {
    const key = `stale-${Date.now()}`;
    await pool.query(
      `insert into public.automation_jobs (idempotency_key, job_name, queue, status, attempts, started_at)
       values ($1, 'test.job', 'test', 'running', 1, now() - interval '1 hour')`,
      [key],
    );
    const out = await runIdempotent(pool, meta(key, 2), async () => 'recovered');
    expect(out).toEqual({ status: 'executed', result: 'recovered' });
  });
});

describe('BullMQ worker with real Redis', () => {
  it('retries a failing job with backoff until it succeeds, executing side effects once', async () => {
    const connection = redisConnection(TEST_REDIS_URL);
    const name = `itest-${Date.now()}`;
    const queue = new Queue(name, { connection });
    const events = new QueueEvents(name, { connection });
    await events.waitUntilReady();
    let attempts = 0;
    let sideEffects = 0;
    const worker = new Worker(
      name,
      async (job) =>
        runIdempotent(
          pool,
          { ...meta(`bull-${name}`, job.attemptsMade + 1, 3), queue: name },
          async () => {
            attempts++;
            if (attempts < 3) throw new Error(`transient ${attempts}`);
            sideEffects++;
            return 'done';
          },
        ),
      { connection },
    );
    try {
      const job = await queue.add(
        'flaky',
        {},
        { attempts: 3, backoff: { type: 'fixed', delay: 50 } },
      );
      const result = await job.waitUntilFinished(events, 10_000);
      expect(result).toEqual({ status: 'executed', result: 'done' });
      expect(attempts).toBe(3);
      expect(sideEffects).toBe(1);
      const row = (
        await pool.query(
          `select status, attempts from public.automation_jobs where idempotency_key = $1`,
          [`bull-${name}`],
        )
      ).rows[0];
      expect(row).toEqual({ status: 'succeeded', attempts: 3 });
    } finally {
      await worker.close();
      await events.close();
      await queue.obliterate({ force: true });
      await queue.close();
    }
  });

  it('runs the real processor for system jobs and expires stale approvals', async () => {
    const { id: uid } = (
      await pool.query(`insert into auth.users (email) values ('w@example.test') returning id`)
    ).rows[0];
    const store = (
      await pool.query(
        `insert into public.stores (owner_user_id, name) values ($1, 'W') returning id`,
        [uid],
      )
    ).rows[0];
    const ar = (
      await pool.query(
        `insert into public.approval_requests (store_id, requested_by_type, action_type, title, what, why, api_operation, expires_at)
       values ($1, 'ai', 'change_price', 't', 'w', 'y', 'PATCH /listings', now() - interval '1 minute') returning id`,
        [store.id],
      )
    ).rows[0];
    const processor = createProcessor(pool, logger);
    const out = await processor({
      name: 'system.cleanup-expired-approvals',
      id: `manual-${Date.now()}`,
      queueName: 'maintenance',
      data: {},
      opts: { attempts: 3 },
      attemptsMade: 0,
    } as never);
    expect(out.status).toBe('executed');
    const status = (
      await pool.query(`select status from public.approval_requests where id = $1`, [ar.id])
    ).rows[0].status;
    expect(status).toBe('expired');
  });

  it('starts schedulers and processes the heartbeat end to end', async () => {
    const running = await startWorker({
      databaseUrl: TEST_DATABASE_URL,
      redisUrl: TEST_REDIS_URL,
      concurrency: 1,
      heartbeatEveryMs: 200,
      logger,
    });
    try {
      const deadline = Date.now() + 8000;
      let count = 0;
      while (Date.now() < deadline) {
        count = Number(
          (
            await pool.query(
              `select count(*) from public.automation_jobs where job_name = 'system.heartbeat' and status = 'succeeded'`,
            )
          ).rows[0].count,
        );
        if (count >= 2) break;
        await new Promise((r) => setTimeout(r, 150));
      }
      expect(count).toBeGreaterThanOrEqual(2);
    } finally {
      const q = running.queues[0]!;
      await q.removeJobScheduler('heartbeat');
      await q.removeJobScheduler('cleanup-expired-approvals');
      await running.close();
    }
  });
});
