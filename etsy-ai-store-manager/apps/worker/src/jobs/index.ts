import type pg from 'pg';
import { JOBS } from '@esm/shared';
import type { IntegrationDeps } from '../etsy/deps.js';
import { syncEtsyStore, notifyAdmins } from '../etsy/sync.js';
import { executeApproval } from '../etsy/execute-approval.js';
import { getEtsyAccessToken, REFRESH_MARGIN_MS } from '../etsy/token-provider.js';

export interface JobContext {
  pool: pg.Pool;
  now: Date;
  deps: IntegrationDeps;
  storeId: string | null;
  attempt: { current: number; max: number };
  /** enqueue follow-up jobs (fan-out) */
  enqueue: (
    jobName: string,
    storeId: string,
    idempotencyKey: string,
    payload?: Record<string, unknown>,
  ) => Promise<void>;
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

const etsySyncStore: JobHandler = async ({ pool, deps, storeId, attempt }, payload) => {
  if (!storeId) throw new Error('storeId required');
  try {
    const result = await syncEtsyStore(pool, deps, storeId);
    if (payload.reason === 'initial' && !result.skipped) {
      await notifyAdmins(
        pool,
        storeId,
        'etsy.sync_done',
        'success',
        'Etsy içe aktarma tamamlandı',
        `${result.listings} ilan, ${result.receipts} sipariş içe aktarıldı.`,
      );
    }
    return result;
  } catch (err) {
    if (attempt.current >= attempt.max) {
      await notifyAdmins(
        pool,
        storeId,
        'etsy.sync_failed',
        'warning',
        'Etsy içe aktarma başarısız',
        err instanceof Error ? err.message.slice(0, 300) : 'Bilinmeyen hata',
      );
    }
    throw err;
  }
};

/** Fan-out: schedule a sync for every active Etsy connection (one key per store per window). */
const etsySyncAll: JobHandler = async ({ pool, enqueue, now }) => {
  const r = await pool.query(
    `select store_id from public.connected_accounts where platform = 'etsy' and status = 'active'`,
  );
  const window = Math.floor(now.getTime() / 3_600_000);
  for (const row of r.rows) {
    await enqueue(
      JOBS.etsySyncStore,
      row.store_id,
      `etsy-sync:${row.store_id}:scheduled:${window}`,
      {
        reason: 'scheduled',
      },
    );
  }
  return { scheduled: r.rowCount ?? 0 };
};

/**
 * Keeps access tokens fresh and the 90-day refresh token rolling, even for
 * stores without recent activity.
 */
const etsyRefreshTokens: JobHandler = async ({ pool, deps }) => {
  if (!deps.cipher || !deps.etsy) return { skipped: 'etsy not configured' };
  const r = await pool.query(
    `select t.connected_account_id from public.oauth_tokens t
       join public.connected_accounts ca on ca.id = t.connected_account_id
      where ca.platform = 'etsy' and ca.status = 'active'
        and (t.expires_at is null or t.expires_at < now() + make_interval(secs => $1::double precision / 1000))`,
    [REFRESH_MARGIN_MS * 4],
  );
  let refreshed = 0;
  const failed: string[] = [];
  for (const row of r.rows) {
    try {
      await getEtsyAccessToken(
        pool,
        { cipher: deps.cipher, app: deps.etsy, fetchImpl: deps.fetchImpl },
        row.connected_account_id,
        { force: true },
      );
      refreshed++;
    } catch {
      failed.push(row.connected_account_id);
    }
  }
  return { refreshed, failed };
};

const approvalExecute: JobHandler = async ({ pool, deps, attempt }, payload) => {
  const approvalId = String(payload.approvalId ?? '');
  if (!approvalId) throw new Error('approvalId required');
  return executeApproval(pool, deps, approvalId, attempt);
};

export const JOB_HANDLERS: Record<string, JobHandler> = {
  [JOBS.heartbeat]: heartbeat,
  [JOBS.cleanupExpiredApprovals]: cleanupExpiredApprovals,
  [JOBS.etsySyncStore]: etsySyncStore,
  [JOBS.etsySyncAll]: etsySyncAll,
  [JOBS.etsyRefreshTokens]: etsyRefreshTokens,
  [JOBS.approvalExecute]: approvalExecute,
};
