import type pg from 'pg';
import { JOBS } from '@esm/shared';

export interface JobContext {
  pool: pg.Pool;
  now: Date;
}

export type JobHandler = (ctx: JobContext, payload: Record<string, unknown>) => Promise<unknown>;

/** Liveness record: proves the scheduler + worker + database path works end to end. */
const heartbeat: JobHandler = async ({ pool, now }) => {
  const r = await pool.query<{ now: string }>('select now()::text as now');
  return { workerTime: now.toISOString(), databaseTime: r.rows[0]?.now };
};

/** Pending approval requests past their expiry can no longer be executed. */
const cleanupExpiredApprovals: JobHandler = async ({ pool }) => {
  const r = await pool.query(
    `update public.approval_requests set status = 'expired'
      where status = 'pending' and expires_at is not null and expires_at < now()`,
  );
  return { expired: r.rowCount ?? 0 };
};

export const JOB_HANDLERS: Record<string, JobHandler> = {
  [JOBS.heartbeat]: heartbeat,
  [JOBS.cleanupExpiredApprovals]: cleanupExpiredApprovals,
};
