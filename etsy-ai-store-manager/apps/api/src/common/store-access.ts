import { ForbiddenException, NotFoundException } from '@nestjs/common';
import type { Queryable } from '../database/database.service.js';

export type StoreRole = 'owner' | 'admin' | 'analyst' | 'viewer';

/**
 * Must be called inside DatabaseService.asUser(). Uses the same SQL helper as the
 * RLS policies. Non-members get 404 (no store enumeration); members without the
 * required role get 403.
 */
export async function assertStoreRole(
  db: Queryable,
  storeId: string,
  role: StoreRole,
): Promise<void> {
  const r = await db.query<{ member: boolean; allowed: boolean }>(
    `select private.has_store_role($1, 'viewer') as member, private.has_store_role($1, $2) as allowed`,
    [storeId, role],
  );
  const row = r.rows[0];
  if (!row?.member) throw new NotFoundException('Mağaza bulunamadı');
  if (!row.allowed) throw new ForbiddenException('Bu işlem için yetkiniz yok');
}
