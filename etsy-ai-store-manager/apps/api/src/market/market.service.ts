import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { JOBS, QUEUES } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

export interface ResearchRequest {
  query: string;
  buyerCountry?: string;
  keywords?: string[];
  useWebSearch?: boolean;
}

@Injectable()
export class MarketService {
  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  capabilities() {
    return {
      etsyMarketData: Boolean(this.env.ETSY_KEYSTRING && this.env.ETSY_SHARED_SECRET),
      aiAnalysis: Boolean(this.env.ANTHROPIC_API_KEY),
    };
  }

  async create(ctx: AuthContext, storeId: string, input: ResearchRequest, meta: RequestMeta) {
    const id = randomUUID();
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      await db.query(
        `insert into public.market_research (id, store_id, query, region, buyer_country, use_web_search, status, summary, created_by)
         values ($1,$2,$3,$4,$5,$6,'queued',$7,$8)`,
        [
          id,
          storeId,
          input.query,
          input.buyerCountry ?? 'global',
          input.buyerCountry ?? null,
          Boolean(input.useWebSearch),
          JSON.stringify({ requestedKeywords: input.keywords ?? [] }),
          ctx.userId,
        ],
      );
    });
    await this.queue.enqueue(QUEUES.sync, JOBS.marketResearch, {
      idempotencyKey: `market-research:${id}`,
      storeId,
      payload: { researchId: id },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'market_research.create',
      entityType: 'market_research',
      entityId: id,
      after: input,
      meta,
    });
    return { id, status: 'queued', capabilities: this.capabilities() };
  }

  list(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select mr.id, mr.query, mr.region, mr.status, mr.confidence, mr.use_web_search, mr.error, mr.created_at, mr.completed_at,
                (select count(*)::int from public.product_opportunities o where o.market_research_id = mr.id) opportunities
           from public.market_research mr where mr.store_id = $1 order by mr.created_at desc limit 50`,
        [storeId],
      );
      return { capabilities: this.capabilities(), items: r.rows };
    });
  }

  get(ctx: AuthContext, storeId: string, id: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select * from public.market_research where store_id = $1 and id = $2`,
        [storeId, id],
      );
      const mr = r.rows[0];
      if (!mr) throw new NotFoundException('Araştırma bulunamadı');
      const opps = await db.query(
        `select * from public.product_opportunities where market_research_id = $1 order by opportunity_score desc nulls last`,
        [id],
      );
      const comps = await db.query(
        `select competitor_shop_id, listing_url, listing_title, observed_price::text, currency, signals, source, is_estimate, observed_at
           from public.competitor_research where market_research_id = $1 order by observed_at, listing_title limit 50`,
        [id],
      );
      const ai = mr.ai_task_id
        ? (
            await db.query(
              `select status, model, input_tokens, output_tokens, cost_usd::text, error from public.ai_tasks where id = $1`,
              [mr.ai_task_id],
            )
          ).rows[0]
        : null;
      return {
        research: mr,
        opportunities: opps.rows.map(toOpportunity),
        competitors: comps.rows,
        aiTask: ai ?? null,
      };
    });
  }

  listOpportunities(ctx: AuthContext, storeId: string, q: { status?: string; minScore?: number }) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select o.*, mr.query as research_query from public.product_opportunities o
           left join public.market_research mr on mr.id = o.market_research_id
          where o.store_id = $1 and ($2::text is null or o.status = $2) and coalesce(o.opportunity_score, 0) >= $3
          order by o.opportunity_score desc nulls last, o.created_at desc limit 200`,
        [storeId, q.status ?? null, q.minScore ?? 0],
      );
      return r.rows.map((x) => ({ ...toOpportunity(x), researchQuery: x.research_query }));
    });
  }

  async decide(
    ctx: AuthContext,
    storeId: string,
    id: string,
    status: 'new' | 'shortlisted' | 'rejected',
    reason: string | undefined,
    meta: RequestMeta,
  ) {
    const row = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `update public.product_opportunities set status = $3, rejection_reason = $4, decided_by = $5, decided_at = now()
          where store_id = $1 and id = $2 returning *`,
        [
          storeId,
          id,
          status,
          status === 'rejected' ? (reason ?? 'Kullanıcı reddetti') : null,
          ctx.userId,
        ],
      );
      if (!r.rowCount) throw new NotFoundException('Fırsat bulunamadı');
      return r.rows[0];
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'opportunity.decide',
      entityType: 'product_opportunity',
      entityId: id,
      after: { status, reason },
      meta,
    });
    return toOpportunity(row);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toOpportunity(o: any) {
  return {
    id: o.id,
    researchId: o.market_research_id,
    title: o.title,
    category: o.category,
    productType: o.product_type,
    targetCustomer: o.target_customer,
    keywords: o.keywords,
    competitionLevel: o.competition_level,
    demandSignals: o.demand_signals,
    estSalePrice: o.est_sale_price,
    estProductionCost: o.est_production_cost,
    estAdCost: o.est_ad_cost,
    estContribution: o.est_contribution,
    estDecision: o.est_decision,
    currency: o.currency,
    score: o.opportunity_score === null ? null : Number(o.opportunity_score),
    scoreBreakdown: o.score_breakdown,
    confidence: o.confidence,
    isEstimate: o.is_estimate,
    personalization: o.personalization,
    ipRisk: o.ip_risk,
    ipRiskNotes: o.ip_risk_notes,
    rationale: o.rationale,
    status: o.status,
    rejectionReason: o.rejection_reason,
    createdAt: o.created_at,
  };
}
