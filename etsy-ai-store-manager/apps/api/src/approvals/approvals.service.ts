import {
  ConflictException,
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { JOBS, QUEUES, type ApprovalDto } from '@esm/shared';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

/** A sensitive approval needs a session that was (re)authenticated within this window. */
export const REAUTH_WINDOW_SECONDS = 5 * 60;

/** Action types the executor can currently carry out through an official API. */
const EXECUTABLE = new Set([
  'update_listing',
  'publish_product',
  'change_price',
  'create_listing',
  'update_listing_translation',
]);

/**
 * Action types with no official write API: approval means "go ahead"; the owner applies the
 * change on the platform and then confirms it here (status awaiting_manual → executed).
 */
export const MANUAL_ACTIONS = new Set([
  'allocate_ad_budget',
  'increase_ad_budget',
  'start_ad_campaign',
]);

@Injectable()
export class ApprovalsService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  list(ctx: AuthContext, storeId: string, status?: string): Promise<ApprovalDto[]> {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select * from public.approval_requests
          where store_id = $1 and ($2::text is null or status = $2)
          order by created_at desc limit 100`,
        [storeId, status ?? null],
      );
      return r.rows.map(toApprovalDto);
    });
  }

  async confirmManual(
    ctx: AuthContext,
    storeId: string,
    approvalId: string,
    note: string,
    meta: RequestMeta,
  ) {
    const row = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      return confirmManualApproval(db, ctx, storeId, approvalId, note);
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.manual_confirmed',
      entityType: 'approval_request',
      entityId: approvalId,
      after: { note },
      meta,
    });
    return toApprovalDto(row);
  }

  async decide(
    ctx: AuthContext,
    storeId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    note: string | undefined,
    meta: RequestMeta,
  ): Promise<ApprovalDto> {
    const row = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const cur = await db.query(
        `select * from public.approval_requests where id = $1 and store_id = $2 for update`,
        [approvalId, storeId],
      );
      const a = cur.rows[0];
      if (!a) throw new NotFoundException('Onay isteği bulunamadı');
      if (a.status !== 'pending')
        throw new ConflictException(`Bu istek zaten "${a.status}" durumunda`);
      if (a.expires_at && new Date(a.expires_at) < new Date()) {
        await db.query(`update public.approval_requests set status = 'expired' where id = $1`, [
          approvalId,
        ]);
        throw new ConflictException('Onay isteğinin süresi dolmuş');
      }
      if (decision === 'approve') {
        if (a.requires_reauth) assertRecentAuth(ctx);
        if (!EXECUTABLE.has(a.action_type) && !MANUAL_ACTIONS.has(a.action_type)) {
          throw new ConflictException(
            'Bu işlem resmi API ile otomatik yapılamıyor; manuel uygulama akışını kullanın.',
          );
        }
      }
      const r = await db.query(
        `update public.approval_requests
            set status = $2, decided_by = $3, decided_at = now(), decision_note = $4
          where id = $1 returning *`,
        [
          approvalId,
          decision === 'approve'
            ? MANUAL_ACTIONS.has(a.action_type)
              ? 'awaiting_manual'
              : 'approved'
            : 'rejected',
          ctx.userId,
          note ?? null,
        ],
      );
      if (decision === 'reject') {
        await db.query(
          `update public.ad_budget_proposals set status = 'rejected' where approval_request_id = $1`,
          [approvalId],
        );
      }
      if (decision === 'reject') {
        // the proposal goes back to editable state
        await db.query(
          `update public.seo_drafts set status = 'draft' where approval_request_id = $1 and status = 'pending_approval'`,
          [approvalId],
        );
        await db.query(
          `update public.listing_translations set status = 'reviewed' where approval_request_id = $1 and status = 'pending_approval'`,
          [approvalId],
        );
      }
      return r.rows[0];
    });

    if (decision === 'approve' && row.status === 'approved') {
      await this.queue.enqueue(QUEUES.sync, JOBS.approvalExecute, {
        idempotencyKey: `approval:${approvalId}`,
        storeId,
        payload: { approvalId },
      });
    }
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: decision === 'approve' ? 'approval.approve' : 'approval.reject',
      entityType: 'approval_request',
      entityId: approvalId,
      after: { status: row.status, note: note ?? null },
      meta,
    });
    return toApprovalDto(row);
  }
}

export async function confirmManualApproval(
  db: Queryable,
  ctx: AuthContext,
  storeId: string,
  approvalId: string,
  note: string,
) {
  const a = (
    await db.query(
      `select * from public.approval_requests where id = $1 and store_id = $2 for update`,
      [approvalId, storeId],
    )
  ).rows[0];
  if (!a) throw new NotFoundException('Onay isteği bulunamadı');
  if (a.status !== 'awaiting_manual')
    throw new ConflictException(`Bu istek "${a.status}" durumunda; manuel onay beklenmiyor`);
  if (a.payload?.kind === 'ad_budget_proposal') {
    const p = (
      await db.query(`select * from public.ad_budget_proposals where id = $1 and store_id = $2`, [
        a.payload.proposalId,
        storeId,
      ])
    ).rows[0];
    for (const x of (p?.allocations ?? []) as Array<{
      campaignId: string;
      proposedDailyBudget: string;
    }>) {
      await db.query(
        `update public.ad_campaigns set daily_budget = $3,
                status = case when $3::numeric = 0 then 'paused' when status = 'paused' then 'active' else status end
          where id = $1 and store_id = $2`,
        [x.campaignId, storeId, x.proposedDailyBudget],
      );
    }
    await db.query(`update public.ad_budget_proposals set status = 'applied' where id = $1`, [
      a.payload.proposalId,
    ]);
  }
  const r = await db.query(
    `update public.approval_requests set status = 'executed', executed_at = now(), manual_confirmed_by = $2,
            manual_confirmed_at = now(), execution_result = $3
      where id = $1 returning *`,
    [approvalId, ctx.userId, JSON.stringify({ manual: true, note })],
  );
  return r.rows[0];
}

/**
 * Supabase issues a new access token (new `iat`) on password sign-in; the web app
 * asks for the password again right before a sensitive approval.
 */
function assertRecentAuth(ctx: AuthContext) {
  const iat = typeof ctx.claims.iat === 'number' ? ctx.claims.iat : 0;
  if (Date.now() / 1000 - iat > REAUTH_WINDOW_SECONDS) {
    throw new ForbiddenException({
      message: 'Bu onay için parolanızı yeniden doğrulamanız gerekiyor',
      details: { reauthRequired: true },
    });
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function toApprovalDto(r: any): ApprovalDto {
  return {
    id: r.id,
    actionType: r.action_type,
    status: r.status,
    title: r.title,
    what: r.what,
    why: r.why,
    expectedBenefit: r.expected_benefit,
    estimatedCost: r.estimated_cost,
    costCurrency: r.cost_currency,
    profitImpact: r.profit_impact,
    apiOperation: r.api_operation,
    riskLevel: r.risk_level,
    requiresReauth: r.requires_reauth,
    requestedByType: r.requested_by_type,
    payload: r.payload,
    createdAt: r.created_at,
    decidedAt: r.decided_at,
    decisionNote: r.decision_note,
    executedAt: r.executed_at,
    executionResult: r.execution_result,
    expiresAt: r.expires_at,
  };
}
