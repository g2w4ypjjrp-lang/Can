import { Injectable } from '@nestjs/common';
import { DatabaseService, type Queryable } from '../database/database.service.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

export interface AuditEntry {
  storeId?: string | null;
  actorUserId?: string | null;
  actorType: 'user' | 'ai' | 'system' | 'worker';
  action: string;
  entityType?: string;
  entityId?: string;
  before?: unknown;
  after?: unknown;
  meta?: RequestMeta;
}

/** Append-only audit trail. Written with the service role (clients cannot insert). */
@Injectable()
export class AuditService {
  constructor(private readonly db: DatabaseService) {}

  async record(entry: AuditEntry, db?: Queryable): Promise<void> {
    const sql = `insert into public.audit_logs
      (store_id, actor_user_id, actor_type, action, entity_type, entity_id, before, after, ip, user_agent, request_id)
      values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`;
    const params = [
      entry.storeId ?? null,
      entry.actorUserId ?? null,
      entry.actorType,
      entry.action,
      entry.entityType ?? null,
      entry.entityId ?? null,
      entry.before === undefined ? null : JSON.stringify(entry.before),
      entry.after === undefined ? null : JSON.stringify(entry.after),
      entry.meta?.ip ?? null,
      entry.meta?.userAgent ?? null,
      entry.meta?.requestId ?? null,
    ];
    if (db) {
      await db.query(sql, params);
    } else {
      await this.db.asService((c) => c.query(sql, params));
    }
  }
}
