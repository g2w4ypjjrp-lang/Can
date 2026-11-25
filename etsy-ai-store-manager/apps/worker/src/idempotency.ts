import type pg from 'pg';

export interface IdempotentJobMeta {
  idempotencyKey: string;
  jobName: string;
  queue: string;
  storeId?: string | null;
  payload?: unknown;
  attempt: number;
  maxAttempts: number;
  schedule?: string | null;
  /** A 'running' row older than this is considered abandoned (crashed worker) and may be re-run. */
  leaseMs?: number;
}

export const DEFAULT_LEASE_MS = 15 * 60_000;

export type IdempotentOutcome<T> =
  | { status: 'executed'; result: T }
  | { status: 'skipped'; reason: 'already_succeeded' | 'running_elsewhere' };

/**
 * Executes `fn` at most once successfully per idempotency key, recording every
 * attempt in public.automation_jobs. A retry (BullMQ attempt > 1) of a failed
 * run is allowed; a key that already succeeded is skipped. Concurrent duplicates
 * are serialised with a row lock (SELECT ... FOR UPDATE SKIP LOCKED).
 */
export async function runIdempotent<T>(
  pool: pg.Pool,
  meta: IdempotentJobMeta,
  fn: () => Promise<T>,
): Promise<IdempotentOutcome<T>> {
  await pool.query(
    `insert into public.automation_jobs
       (idempotency_key, job_name, queue, store_id, payload, max_attempts, schedule, status)
     values ($1, $2, $3, $4, $5, $6, $7, 'queued')
     on conflict (idempotency_key) do nothing`,
    [
      meta.idempotencyKey,
      meta.jobName,
      meta.queue,
      meta.storeId ?? null,
      JSON.stringify(meta.payload ?? {}),
      meta.maxAttempts,
      meta.schedule ?? null,
    ],
  );

  const client = await pool.connect();
  try {
    await client.query('begin');
    const locked = await client.query<{ status: string; lease_active: boolean }>(
      `select status,
              (started_at is not null and started_at > now() - make_interval(secs => $2::double precision / 1000)) as lease_active
         from public.automation_jobs where idempotency_key = $1 for update skip locked`,
      [meta.idempotencyKey, meta.leaseMs ?? DEFAULT_LEASE_MS],
    );
    const row = locked.rows[0];
    if (!row) {
      await client.query('rollback');
      return { status: 'skipped', reason: 'running_elsewhere' };
    }
    if (row.status === 'succeeded') {
      await client.query('rollback');
      return { status: 'skipped', reason: 'already_succeeded' };
    }
    if (row.status === 'running' && row.lease_active) {
      await client.query('rollback');
      return { status: 'skipped', reason: 'running_elsewhere' };
    }
    await client.query(
      `update public.automation_jobs
          set status = 'running', attempts = attempts + 1, started_at = now(), last_error = null
        where idempotency_key = $1`,
      [meta.idempotencyKey],
    );
    await client.query('commit');
  } catch (err) {
    await client.query('rollback').catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }

  try {
    const result = await fn();
    await pool.query(
      `update public.automation_jobs set status = 'succeeded', result = $2, finished_at = now()
        where idempotency_key = $1`,
      [meta.idempotencyKey, JSON.stringify(result ?? null)],
    );
    return { status: 'executed', result };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const final = meta.attempt >= meta.maxAttempts;
    await pool.query(
      `update public.automation_jobs set status = $2, last_error = $3, finished_at = now()
        where idempotency_key = $1`,
      [meta.idempotencyKey, final ? 'failed' : 'queued', message.slice(0, 2000)],
    );
    throw err;
  }
}
