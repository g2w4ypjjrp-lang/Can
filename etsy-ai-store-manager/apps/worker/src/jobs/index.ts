import type pg from 'pg';
import { JOBS } from '@esm/shared';
import type { IntegrationDeps } from '../etsy/deps.js';
import { syncEtsyStore, notifyAdmins } from '../etsy/sync.js';
import { executeApproval } from '../etsy/execute-approval.js';
import { getEtsyAccessToken, REFRESH_MARGIN_MS } from '../etsy/token-provider.js';
import { syncPrintifyStore } from '../printify/sync.js';
import { recomputeOrderSnapshots } from '../finance/recompute.js';
import { refreshFxRates } from '../finance/fx.js';
import { runMarketResearch } from '../market/research.js';
import { generateDesign, reviewDesign } from '../designs/jobs.js';

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

const etsySyncStore: JobHandler = async ({ pool, deps, storeId, attempt, enqueue }, payload) => {
  if (!storeId) throw new Error('storeId required');
  try {
    const result = await syncEtsyStore(pool, deps, storeId);
    await enqueueRecompute(enqueue, storeId);
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

const printifySyncStore: JobHandler = async ({ pool, deps, storeId, attempt, enqueue }) => {
  if (!storeId) throw new Error('storeId required');
  if (!deps.printify) return { skipped: 'PRINTIFY_API_TOKEN not configured' };
  try {
    const result = await syncPrintifyStore(pool, deps.printify, storeId);
    await enqueueRecompute(enqueue, storeId);
    return result;
  } catch (err) {
    if (attempt.current >= attempt.max) {
      await notifyAdmins(
        pool,
        storeId,
        'printify.sync_failed',
        'warning',
        'Printify senkronizasyonu başarısız',
        err instanceof Error ? err.message.slice(0, 300) : 'Bilinmeyen hata',
        '/dashboard/printify',
      );
    }
    throw err;
  }
};

const printifySyncAll: JobHandler = async ({ pool, enqueue, now }) => {
  const r = await pool.query(
    `select store_id from public.connected_accounts where platform = 'printify' and status = 'active'`,
  );
  const window = Math.floor(now.getTime() / 3_600_000);
  for (const row of r.rows) {
    await enqueue(
      JOBS.printifySyncStore,
      row.store_id,
      `printify-sync:${row.store_id}:scheduled:${window}`,
      { reason: 'scheduled' },
    );
  }
  return { scheduled: r.rowCount ?? 0 };
};

/** Webhook deliveries are stored by the API; processing = debounced re-sync of that store. */
const printifyWebhook: JobHandler = async ({ pool, enqueue, storeId }, payload) => {
  const eventRowId = String(payload.webhookEventId ?? '');
  if (!storeId || !eventRowId) throw new Error('storeId and webhookEventId required');
  const bucket = Math.floor(Date.now() / 60_000);
  await enqueue(JOBS.printifySyncStore, storeId, `printify-sync:${storeId}:webhook:${bucket}`, {
    reason: 'webhook',
  });
  await pool.query(`update public.webhook_events set processed_at = now() where id = $1`, [
    eventRowId,
  ]);
  return { queuedSync: true };
};

/** Debounced (per minute) profit recompute after data changes. */
async function enqueueRecompute(enqueue: JobContext['enqueue'], storeId: string) {
  await enqueue(
    JOBS.profitRecomputeOrders,
    storeId,
    `profit-recompute:${storeId}:${Math.floor(Date.now() / 60_000)}`,
    {
      reason: 'after-sync',
    },
  ).catch(() => undefined);
}

const profitRecomputeOrders: JobHandler = async ({ pool, storeId }) => {
  if (!storeId) throw new Error('storeId required');
  return recomputeOrderSnapshots(pool, storeId);
};

const fxRefresh: JobHandler = async ({ pool, deps }) => refreshFxRates(pool, deps.fetchImpl);

const marketResearch: JobHandler = async ({ pool, deps, attempt }, payload) => {
  const researchId = String(payload.researchId ?? '');
  if (!researchId) throw new Error('researchId required');
  try {
    return await runMarketResearch(
      pool,
      { etsy: deps.etsy, anthropic: deps.anthropic ?? null, fetchImpl: deps.fetchImpl },
      researchId,
    );
  } catch (err) {
    const message = err instanceof Error ? err.message.slice(0, 500) : String(err);
    await pool.query(`update public.market_research set status = $2, error = $3 where id = $1`, [
      researchId,
      attempt.current >= attempt.max ? 'failed' : 'queued',
      message,
    ]);
    throw err;
  }
};

const designGenerate: JobHandler = async ({ pool, deps }, payload) => {
  if (!deps.store) throw new Error('storage not configured');
  return generateDesign(
    pool,
    { anthropic: deps.anthropic ?? null, store: deps.store },
    String(payload.designId),
    (payload.userId as string) ?? null,
  );
};

const designIpReview: JobHandler = async ({ pool, deps }, payload) => {
  if (!deps.store) throw new Error('storage not configured');
  return reviewDesign(
    pool,
    { anthropic: deps.anthropic ?? null, store: deps.store },
    String(payload.designId),
  );
};

export const JOB_HANDLERS: Record<string, JobHandler> = {
  [JOBS.designGenerate]: designGenerate,
  [JOBS.designIpReview]: designIpReview,
  [JOBS.marketResearch]: marketResearch,
  [JOBS.profitRecomputeOrders]: profitRecomputeOrders,
  [JOBS.fxRefresh]: fxRefresh,
  [JOBS.printifySyncStore]: printifySyncStore,
  [JOBS.printifySyncAll]: printifySyncAll,
  [JOBS.printifyWebhook]: printifyWebhook,
  [JOBS.heartbeat]: heartbeat,
  [JOBS.cleanupExpiredApprovals]: cleanupExpiredApprovals,
  [JOBS.etsySyncStore]: etsySyncStore,
  [JOBS.etsySyncAll]: etsySyncAll,
  [JOBS.etsyRefreshTokens]: etsyRefreshTokens,
  [JOBS.approvalExecute]: approvalExecute,
};
