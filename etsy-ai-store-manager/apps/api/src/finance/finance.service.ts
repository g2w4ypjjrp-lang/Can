import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import {
  calculateContribution,
  loadProfitContext,
  loadVariantCosts,
  recommendPrice,
  type Decision,
  type ProfitContext,
  type ProfitInput,
  type ProfitResult,
} from '@esm/profit-engine';
import { JOBS, QUEUES } from '@esm/shared';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

const DECISION_RANK: Record<Decision, number> = {
  rejected: 0,
  not_recommended: 1,
  needs_approval: 2,
  publishable: 3,
  excellent: 4,
};

export interface SimulationInput {
  unitPrice: string;
  quantity: number;
  shippingCharged: string;
  discount?: string;
  salesTax?: string;
  productionCostPerUnit: string;
  productionCostCurrency: string;
  fulfillmentShippingFirst: string;
  fulfillmentShippingAdditional: string;
  fulfillmentShippingCurrency: string;
  buyerCountry: string;
  currency?: string;
  offsiteAds?: boolean;
  adCostAllocated?: string;
  save?: boolean;
}

@Injectable()
export class FinanceService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  /** Store-level inputs shared by every calculation; warns about missing seller settings. */
  private baseInput(ctx: ProfitContext, buyerCountry: string, currency?: string) {
    const warnings: string[] = [];
    if (!ctx.sellerCountry) warnings.push('Satıcı (banka) ülkesi ayarlanmadı: Ayarlar > Mağaza');
    if (!ctx.payoutCurrency)
      warnings.push('Ödeme hesabı para birimi ayarlanmadı: Ayarlar > Mağaza');
    return {
      warnings,
      base: {
        currency: currency ?? ctx.storeCurrency,
        sellerCountry: ctx.sellerCountry ?? 'XX',
        buyerCountry,
        payoutCurrency: ctx.payoutCurrency ?? currency ?? ctx.storeCurrency,
        fxRates: ctx.fxRates,
      },
    };
  }

  private finalize(r: ProfitResult, extra: string[]): ProfitResult {
    if (extra.length) return { ...r, complete: false, warnings: [...extra, ...r.warnings] };
    return r;
  }

  async feeRules(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select f.id, f.fee_type, f.rate::text, f.fixed_amount::text, f.fixed_currency, f.basis, f.country, f.buyer_scope,
                f.cap_amount::text, f.cap_currency, f.tier, f.source_url, f.notes, f.store_id is not null as store_specific,
                v.verified_at, u.email as verified_by
           from public.fee_rules f
           left join public.fee_rule_verifications v on v.fee_rule_id = f.id and v.store_id = $1
           left join public.users u on u.id = v.verified_by
          where (f.store_id is null or f.store_id = $1) and f.platform = 'etsy'
          order by f.fee_type, f.country nulls first, f.buyer_scope`,
        [storeId],
      );
      return r.rows.map((x) => ({
        id: x.id,
        feeType: x.fee_type,
        rate: x.rate,
        fixed: x.fixed_amount ? `${x.fixed_amount} ${x.fixed_currency}` : null,
        basis: x.basis,
        country: x.country,
        buyerScope: x.buyer_scope,
        cap: x.cap_amount ? `${x.cap_amount} ${x.cap_currency}` : null,
        tier: x.tier,
        sourceUrl: x.source_url,
        notes: x.notes,
        storeSpecific: x.store_specific,
        verifiedAt: x.verified_at,
        verifiedBy: x.verified_by,
      }));
    });
  }

  async verifyFeeRule(
    ctx: AuthContext,
    storeId: string,
    ruleId: string,
    note: string | undefined,
    meta: RequestMeta,
  ) {
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select 1 from public.fee_rules where id = $1 and (store_id is null or store_id = $2)`,
        [ruleId, storeId],
      );
      if (!r.rowCount) throw new NotFoundException('Ücret kuralı bulunamadı');
      await db.query(
        `insert into public.fee_rule_verifications (store_id, fee_rule_id, verified_by, note) values ($1, $2, $3, $4)
         on conflict (store_id, fee_rule_id) do update set verified_by = excluded.verified_by, verified_at = now(), note = excluded.note`,
        [storeId, ruleId, ctx.userId, note ?? null],
      );
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'fee_rule.verify',
      entityType: 'fee_rule',
      entityId: ruleId,
      after: { note },
      meta,
    });
    return { ok: true };
  }

  async simulate(ctx: AuthContext, storeId: string, input: SimulationInput) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const pc = await loadProfitContext(db, storeId);
      const { base, warnings } = this.baseInput(pc, input.buyerCountry, input.currency);
      const full: ProfitInput = {
        ...base,
        unitPrice: input.unitPrice,
        quantity: input.quantity,
        shippingCharged: input.shippingCharged,
        discount: input.discount,
        salesTax: input.salesTax,
        productionCostPerUnit: input.productionCostPerUnit,
        productionCostCurrency: input.productionCostCurrency,
        fulfillmentShippingFirst: input.fulfillmentShippingFirst,
        fulfillmentShippingAdditional: input.fulfillmentShippingAdditional,
        fulfillmentShippingCurrency: input.fulfillmentShippingCurrency,
        offsiteAds: input.offsiteAds,
        adCostAllocated: input.adCostAllocated ?? pc.defaultAdCostPerOrder,
      };
      const result = this.finalize(calculateContribution(full, pc.rules, pc.policy), warnings);
      const recommendation = recommendPrice(full, pc.rules, pc.policy);
      if (input.save) {
        if (
          !(await db.query(`select private.has_store_role($1, 'admin') ok`, [storeId])).rows[0].ok
        ) {
          throw new BadRequestException('Simülasyon kaydı için yönetici yetkisi gerekir');
        }
        await saveSnapshot(db, storeId, 'simulation', result, full, {});
      }
      return { result, recommendation, fxAsOf: pc.fxAsOf };
    });
  }

  /** Per-variant profitability of a product for a destination country (current price & costs). */
  async productProfitability(
    ctx: AuthContext,
    storeId: string,
    productId: string,
    country: string,
  ) {
    return this.db.asUser(ctx, (db) => this.computeProduct(db, storeId, productId, country));
  }

  async computeProduct(db: Queryable, storeId: string, productId: string, country: string) {
    await assertStoreRole(db, storeId, 'viewer');
    const p = await db.query(
      `select id, title from public.products where store_id = $1 and id = $2`,
      [storeId, productId],
    );
    if (!p.rowCount) throw new NotFoundException('Ürün bulunamadı');
    const pc = await loadProfitContext(db, storeId);
    const variants = await db.query(
      `select id, title, price::text, currency, printify_variant_id from public.product_variants
        where product_id = $1 and is_enabled order by title`,
      [productId],
    );
    const rows = [];
    for (const v of variants.rows) {
      const costs = await loadVariantCosts(db, v.id, country);
      const { base, warnings } = this.baseInput(pc, country, v.currency);
      if (!costs.production)
        warnings.push('Üretim maliyeti bilinmiyor (Printify senkronizasyonu gerekli)');
      if (!costs.shippingFirst) warnings.push(`${country} için kargo maliyeti bilinmiyor`);
      if (!v.price) warnings.push('Satış fiyatı yok');
      const input: ProfitInput = {
        ...base,
        unitPrice: v.price ?? '0',
        quantity: 1,
        shippingCharged: '0',
        productionCostPerUnit: costs.production?.amount ?? '0',
        productionCostCurrency: costs.production?.currency ?? 'USD',
        fulfillmentShippingFirst: costs.shippingFirst?.amount ?? '0',
        fulfillmentShippingAdditional: costs.shippingAdditional?.amount ?? '0',
        fulfillmentShippingCurrency: costs.shippingFirst?.currency ?? 'USD',
        adCostAllocated: pc.defaultAdCostPerOrder,
      };
      const result = this.finalize(calculateContribution(input, pc.rules, pc.policy), warnings);
      const recommendation = costs.production ? recommendPrice(input, pc.rules, pc.policy) : null;
      rows.push({
        variantId: v.id,
        title: v.title,
        printifyVariantId: v.printify_variant_id,
        price: v.price,
        currency: v.currency,
        shippingRegion: costs.shippingFirst?.region ?? null,
        result,
        recommendation,
      });
    }
    const proposals = await db.query(
      `select count(*)::int n from public.price_recommendations pr join public.product_variants v on v.id = pr.product_variant_id
        where v.product_id = $1 and pr.status = 'proposed'`,
      [productId],
    );
    const worst = rows.reduce<Decision | null>(
      (w, r) =>
        w === null || DECISION_RANK[r.result.decision] < DECISION_RANK[w] ? r.result.decision : w,
      null,
    );
    return {
      productId,
      title: p.rows[0].title,
      country,
      targetContribution: pc.policy.targetContribution,
      worstDecision: worst,
      complete: rows.every((r) => r.result.complete),
      feesVerified: rows.every((r) => r.result.feesVerified),
      fxAsOf: pc.fxAsOf,
      pendingPriceProposals: proposals.rows[0].n as number,
      variants: rows,
    };
  }

  /** Stores price recommendations for variants below the contribution target. */
  async createPriceRecommendations(
    ctx: AuthContext,
    storeId: string,
    productId: string,
    country: string,
    meta: RequestMeta,
  ) {
    const out = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const prof = await this.computeProduct(db, storeId, productId, country);
      const created = [];
      for (const v of prof.variants) {
        if (!v.recommendation?.suggestedUnitPrice || !v.result.complete) continue;
        if (
          v.price &&
          Number(v.recommendation.suggestedUnitPrice) <= Number(v.price) &&
          Number(v.result.contribution) >= Number(prof.targetContribution)
        )
          continue;
        await db.query(
          `update public.price_recommendations set status = 'superseded' where product_variant_id = $1 and status = 'proposed'`,
          [v.variantId],
        );
        const snap = await saveSnapshot(
          db,
          storeId,
          'listing_estimate',
          v.result,
          { variantId: v.variantId, country },
          { product_variant_id: v.variantId },
        );
        const r = await db.query(
          `insert into public.price_recommendations
             (store_id, product_variant_id, current_price, recommended_price, currency, target_contribution, expected_contribution, rationale, profit_snapshot_id)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning id`,
          [
            storeId,
            v.variantId,
            v.price,
            v.recommendation.suggestedUnitPrice,
            v.currency,
            prof.targetContribution,
            v.recommendation.expectedContribution,
            `${country} için mevcut katkı ${v.result.contribution} ${v.currency}; ${v.recommendation.note}`,
            snap,
          ],
        );
        created.push({
          id: r.rows[0].id,
          variant: v.title,
          currentPrice: v.price,
          recommendedPrice: v.recommendation.suggestedUnitPrice,
          expectedContribution: v.recommendation.expectedContribution,
        });
      }
      return created;
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'price_recommendation.create',
      entityType: 'product',
      entityId: productId,
      after: out,
      meta,
    });
    return out;
  }

  /** Turns proposed price recommendations of a product into ONE change_price approval request. */
  async requestPriceChange(
    ctx: AuthContext,
    storeId: string,
    productId: string,
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select pr.id, pr.current_price::text, pr.recommended_price::text, pr.expected_contribution::text, pr.currency,
                v.printify_variant_id, v.title, p.printify_product_id, p.title as product_title
           from public.price_recommendations pr
           join public.product_variants v on v.id = pr.product_variant_id
           join public.products p on p.id = v.product_id
          where pr.store_id = $1 and p.id = $2 and pr.status = 'proposed'`,
        [storeId, productId],
      );
      if (!r.rowCount) throw new NotFoundException('Önerilen fiyat yok');
      const first = r.rows[0];
      if (!first.printify_product_id)
        throw new ConflictException(
          'Fiyat değişikliği yalnızca Printify ürünlerinde otomatik uygulanabilir',
        );
      const pending = await db.query(
        `select 1 from public.approval_requests where store_id = $1 and action_type = 'change_price' and status in ('pending','approved','executing') and payload->>'productId' = $2`,
        [storeId, productId],
      );
      if (pending.rowCount)
        throw new ConflictException('Bu ürün için bekleyen bir fiyat değişikliği var');
      const lines = r.rows.map(
        (x) =>
          `${x.title}: ${x.current_price ?? '—'} → ${x.recommended_price} ${x.currency} (beklenen katkı ${x.expected_contribution})`,
      );
      const ins = await db.query(
        `insert into public.approval_requests
           (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit, estimated_cost,
            cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
         values ($1,'user',$2,'change_price',$3,$4,$5,$6,0,$7,$8,$9,$10,'high',true, now() + interval '7 days') returning *`,
        [
          storeId,
          ctx.userId,
          `Fiyat değiştir: ${first.product_title.slice(0, 80)}`,
          lines.join('; '),
          'Profit Engine: varyant katkısı hedefin altında veya fiyat hedefe göre ayarlanmalı',
          'Sipariş başı katkının hedefe ulaşması',
          first.currency,
          lines.join('; '),
          'PUT /v1/shops/{shop_id}/products/{product_id}.json (varyant fiyatları) + POST publish.json (yalnızca variants) — Printify → Etsy',
          JSON.stringify({
            kind: 'printify_variant_price',
            productId,
            printifyProductId: first.printify_product_id,
            recommendationIds: r.rows.map((x) => x.id),
            prices: Object.fromEntries(
              r.rows.map((x) => [String(x.printify_variant_id), x.recommended_price]),
            ),
          }),
        ],
      );
      await db.query(
        `update public.price_recommendations set approval_request_id = $2 where id = any($1::uuid[])`,
        [r.rows.map((x) => x.id), ins.rows[0].id],
      );
      return ins.rows[0];
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: 'change_price' },
      meta,
    });
    return toApprovalDto(approval);
  }

  /**
   * P&L for a period. Ads are taken ONCE from the ad_spend ledger; order snapshots
   * contribute their contribution BEFORE ads, so allocations are never double counted.
   */
  async summary(ctx: AuthContext, storeId: string, from: string, to: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const pc = await loadProfitContext(db, storeId);
      const cur = pc.storeCurrency;
      const s = await db.query(
        `select count(*)::int orders,
                coalesce(sum(ps.net_revenue), 0)::text net_revenue,
                coalesce(sum(ps.contribution_before_ads), 0)::text contribution_before_ads,
                coalesce(sum(ps.total_variable_costs - ps.ad_cost_allocated), 0)::text variable_costs_ex_ads,
                count(*) filter (where not ps.complete)::int incomplete,
                count(*) filter (where not ps.fees_verified)::int unverified
           from public.profit_snapshots ps join public.orders o on o.id = ps.order_id
          where ps.store_id = $1 and ps.scenario = 'order_actual' and ps.currency = $2
            and o.placed_at >= $3::date and o.placed_at < ($4::date + 1)`,
        [storeId, cur, from, to],
      );
      const ads = await db.query(
        `select coalesce(sum(amount), 0)::text spend from public.ad_spend
          where store_id = $1 and currency = $2 and spend_date between $3::date and $4::date`,
        [storeId, cur, from, to],
      );
      const fees = await db.query(
        `select l->>'code' code, l->>'label' label, sum((l->>'amount')::numeric)::text amount
           from public.profit_snapshots ps join public.orders o on o.id = ps.order_id,
                jsonb_array_elements(ps.breakdown) l
          where ps.store_id = $1 and ps.scenario = 'order_actual' and ps.currency = $2
            and o.placed_at >= $3::date and o.placed_at < ($4::date + 1) and l->>'group' in ('fee','cost','reserve')
          group by 1, 2 order by 3`,
        [storeId, cur, from, to],
      );
      const unmatched = await db.query(
        `select count(*)::int n from public.orders o where o.store_id = $1 and o.placed_at >= $2::date and o.placed_at < ($3::date + 1)
            and o.status <> 'cancelled' and not exists (select 1 from public.profit_snapshots ps where ps.order_id = o.id and ps.scenario = 'order_actual')`,
        [storeId, from, to],
      );
      const x = s.rows[0];
      const before = Number(x.contribution_before_ads);
      const spend = Number(ads.rows[0].spend);
      const afterAds = before - spend;
      const taxRate = Number(pc.policy.taxRateOnProfit);
      return {
        currency: cur,
        period: { from, to },
        orders: x.orders,
        netRevenue: x.net_revenue,
        variableCostsExAds: x.variable_costs_ex_ads,
        contributionBeforeAds: x.contribution_before_ads,
        adSpendActual: ads.rows[0].spend,
        contributionAfterAds: afterAds.toFixed(4),
        estimatedTax: afterAds > 0 ? (afterAds * taxRate).toFixed(4) : '0.0000',
        netAfterTax: (afterAds > 0 ? afterAds * (1 - taxRate) : afterAds).toFixed(4),
        averageContributionPerOrder: x.orders ? (afterAds / x.orders).toFixed(4) : null,
        costLines: fees.rows,
        dataQuality: {
          incompleteOrders: x.incomplete,
          unverifiedFeeOrders: x.unverified,
          ordersWithoutCalculation: unmatched.rows[0].n,
        },
        note: 'Reklam gideri yalnızca gerçek reklam harcaması kayıtlarından bir kez düşülür. Vergi tahmini bilgi amaçlıdır.',
      };
    });
  }

  async requestRecompute(ctx: AuthContext, storeId: string) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'admin'));
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.profitRecomputeOrders, {
      idempotencyKey: `profit-recompute:${storeId}:${Math.floor(Date.now() / 60_000)}`,
      storeId,
      payload: { reason: 'manual' },
    });
    return { jobId };
  }
}

/** Stores an immutable calculation snapshot; returns its id. */
export async function saveSnapshot(
  db: Queryable,
  storeId: string,
  scenario: 'simulation' | 'listing_estimate' | 'order_actual',
  r: ProfitResult,
  inputs: unknown,
  refs: { product_variant_id?: string; order_id?: string },
): Promise<string> {
  const ins = await db.query(
    `insert into public.profit_snapshots
       (store_id, product_variant_id, order_id, scenario, currency, gross_revenue, net_revenue, total_variable_costs,
        contribution, contribution_after_tax, contribution_margin, decision, breakdown, inputs, fee_rule_ids,
        engine_version, contribution_before_ads, ad_cost_allocated, complete, fees_verified, warnings)
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21) returning id`,
    [
      storeId,
      refs.product_variant_id ?? null,
      refs.order_id ?? null,
      scenario,
      r.currency,
      r.grossRevenue,
      r.netRevenue,
      r.totalVariableCosts,
      r.contribution,
      r.contributionAfterTax,
      r.contributionMargin,
      r.decision,
      JSON.stringify(r.breakdown),
      JSON.stringify(inputs),
      r.feeRuleIds.filter((id) => /^[0-9a-f-]{36}$/.test(id)),
      r.engineVersion,
      r.contributionBeforeAds,
      r.adCostAllocated,
      r.complete,
      r.feesVerified,
      JSON.stringify(r.warnings),
    ],
  );
  return ins.rows[0].id;
}
