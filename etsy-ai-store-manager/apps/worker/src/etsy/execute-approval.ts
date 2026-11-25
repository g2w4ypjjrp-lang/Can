import type pg from 'pg';
import { mapListing, type EtsyListingPatch } from '@esm/integrations';
import { etsyClientFor, loadEtsyConnection, type IntegrationDeps } from './deps.js';
import { notifyAdmins } from './sync.js';

type Field = 'title' | 'description' | 'tags' | 'materials' | 'state';

export interface ExecuteOutcome {
  status: 'executed' | 'failed' | 'skipped';
  reason?: string;
  updatedFields?: string[];
  conflicts?: string[];
}

/**
 * Executes an APPROVED listing change:
 *  1. claims the request (approved -> executing) so it runs once,
 *  2. reads the current listing from Etsy,
 *  3. refuses if any field to change was edited on Etsy after the proposal (no silent overwrite),
 *  4. PATCHes only the changed fields (all other listing data stays as is on Etsy),
 *  5. stores the result locally and records audit + notification.
 */
export async function executeApproval(
  pool: pg.Pool,
  deps: IntegrationDeps,
  approvalId: string,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  const claim = await pool.query(
    `update public.approval_requests set status = 'executing'
      where id = $1 and status = 'approved' returning *`,
    [approvalId],
  );
  const a = claim.rows[0];
  if (!a) {
    const cur = await pool.query(`select status from public.approval_requests where id = $1`, [
      approvalId,
    ]);
    return { status: 'skipped', reason: `status=${cur.rows[0]?.status ?? 'missing'}` };
  }
  if (!['update_listing', 'publish_product'].includes(a.action_type)) {
    return finish(pool, a, 'failed', { error: 'Bu işlem türü için otomatik yürütücü yok' });
  }

  const payload = a.payload as {
    listingId: string;
    etsyListingId: string;
    changes: Partial<Record<Field, unknown>>;
    baseline: Partial<Record<Field, unknown>>;
  };
  try {
    const conn = await loadEtsyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Etsy bağlantısı aktif değil' });
    const client = etsyClientFor(pool, deps, conn);

    const current = await client.getListing(payload.etsyListingId);
    const conflicts = (Object.keys(payload.changes) as Field[]).filter(
      (f) => !sameValue(current[f], payload.baseline[f]),
    );
    if (conflicts.length) {
      return finish(pool, a, 'failed', {
        error: 'İlan, öneri oluşturulduktan sonra Etsy üzerinde değişmiş; üzerine yazılmadı.',
        conflicts,
      });
    }

    const patch: EtsyListingPatch = {};
    for (const [k, v] of Object.entries(payload.changes)) (patch as Record<string, unknown>)[k] = v;
    const updated = await client.updateListing(conn.shopId, payload.etsyListingId, patch);
    const m = mapListing({ ...current, ...updated });
    await pool.query(
      `update public.listings set title = $3, description = $4, tags = $5, materials = $6, state = $7,
              raw = $8, last_synced_at = now()
        where store_id = $1 and id = $2`,
      [
        a.store_id,
        payload.listingId,
        m.title,
        m.description,
        m.tags,
        m.materials,
        m.state,
        JSON.stringify(m.raw),
      ],
    );
    return finish(pool, a, 'executed', { updatedFields: Object.keys(payload.changes) });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (attempt.current >= attempt.max) {
      return finish(pool, a, 'failed', { error: message.slice(0, 500) });
    }
    // give the request back so the BullMQ retry can claim it again
    await pool.query(
      `update public.approval_requests set status = 'approved', execution_result = $2 where id = $1`,
      [approvalId, JSON.stringify({ lastError: message.slice(0, 500), attempt: attempt.current })],
    );
    throw err;
  }
}

async function finish(
  pool: pg.Pool,
  a: { id: string; store_id: string; title: string },
  status: 'executed' | 'failed',
  result: Record<string, unknown>,
): Promise<ExecuteOutcome> {
  await pool.query(
    `update public.approval_requests set status = $2, execution_result = $3,
            executed_at = case when $2 = 'executed' then now() else executed_at end
      where id = $1`,
    [a.id, status, JSON.stringify(result)],
  );
  await pool.query(
    `insert into public.audit_logs (store_id, actor_type, action, entity_type, entity_id, after)
     values ($1, 'worker', $2, 'approval_request', $3, $4)`,
    [
      a.store_id,
      status === 'executed' ? 'approval.executed' : 'approval.failed',
      a.id,
      JSON.stringify(result),
    ],
  );
  await notifyAdmins(
    pool,
    a.store_id,
    `approval.${status}`,
    status === 'executed' ? 'success' : 'warning',
    status === 'executed' ? 'Değişiklik Etsy’ye uygulandı' : 'Değişiklik uygulanamadı',
    `${a.title}${result.error ? ` — ${String(result.error)}` : ''}`,
    '/dashboard/etsy',
  );
  return {
    status,
    ...(result.error ? { reason: String(result.error) } : {}),
    ...(result.updatedFields ? { updatedFields: result.updatedFields as string[] } : {}),
    ...(result.conflicts ? { conflicts: result.conflicts as string[] } : {}),
  };
}

function sameValue(a: unknown, b: unknown): boolean {
  const norm = (v: unknown) =>
    Array.isArray(v)
      ? JSON.stringify([...v].map(String))
      : v === null || v === undefined
        ? ''
        : String(v);
  return norm(a) === norm(b);
}
