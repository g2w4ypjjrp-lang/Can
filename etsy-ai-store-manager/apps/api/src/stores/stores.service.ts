import {
  BadRequestException,
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import {
  validateThresholdOrder,
  type ProfitRulesDto,
  type ProfitRulesUpdate,
  type StoreCreate,
  type StoreSettingsDto,
  type StoreSettingsUpdate,
  type StoreSummary,
} from '@esm/shared';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { updateFromPatch } from '../common/sql.js';

const STORE_SETTINGS_COLUMNS: Record<string, string> = {
  salesStrategy: 'sales_strategy',
  automationLevel: 'automation_level',
  defaultLanguage: 'default_language',
  languages: 'languages',
  targetMarkets: 'target_markets',
  dailyAdBudgetCap: 'daily_ad_budget_cap',
  adBudgetCurrency: 'ad_budget_currency',
  sellerCountry: 'seller_country',
  payoutCurrency: 'payout_currency',
  timezone: 'timezone',
};

const PROFIT_RULE_COLUMNS: Record<string, string> = {
  currency: 'currency',
  targetContribution: 'target_contribution',
  excellentThreshold: 'excellent_threshold',
  publishThreshold: 'publish_threshold',
  reviewThreshold: 'review_threshold',
  minThreshold: 'min_threshold',
  returnReserveRate: 'return_reserve_rate',
  remakeReserveRate: 'remake_reserve_rate',
  otherVariableCostRate: 'other_variable_cost_rate',
  otherVariableCostFixed: 'other_variable_cost_fixed',
  defaultAdCostPerOrder: 'default_ad_cost_per_order',
  taxRateOnProfit: 'tax_rate_on_profit',
  vatOnFeesRate: 'vat_on_fees_rate',
  offsiteAdsTier: 'offsite_ads_tier',
};

@Injectable()
export class StoresService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
  ) {}

  list(ctx: AuthContext): Promise<StoreSummary[]> {
    return this.db.asUser(ctx, async (db) => {
      const r = await db.query(`${STORE_SELECT} where m.user_id = $1 order by s.created_at asc`, [
        ctx.userId,
      ]);
      return r.rows.map(toStore);
    });
  }

  async get(ctx: AuthContext, storeId: string): Promise<StoreSummary> {
    const store = await this.db.asUser(ctx, (db) => this.findStore(db, ctx.userId, storeId));
    if (!store) throw new NotFoundException('Mağaza bulunamadı');
    return store;
  }

  /**
   * Creates the store record. The Etsy shop itself is linked later via OAuth
   * (Phase 2); until then status = 'not_connected' and no data is shown as live.
   */
  async create(ctx: AuthContext, dto: StoreCreate, meta: RequestMeta): Promise<StoreSummary> {
    const id = randomUUID();
    const store = await this.db.asUser(ctx, async (db) => {
      await db.query(
        `insert into public.stores (id, owner_user_id, name, currency, default_language)
         values ($1, $2, $3, $4, $5)`,
        [id, ctx.userId, dto.name, dto.currency, dto.defaultLanguage],
      );
      return this.findStore(db, ctx.userId, id);
    });
    if (!store) throw new Error('Store not visible after creation');
    await this.audit.record({
      storeId: id,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'store.create',
      entityType: 'store',
      entityId: id,
      after: store,
      meta,
    });
    return store;
  }

  async getSettings(ctx: AuthContext, storeId: string): Promise<StoreSettingsDto> {
    const row = await this.db.asUser(ctx, (db) => this.findSettings(db, storeId));
    if (!row) throw new NotFoundException('Mağaza bulunamadı');
    return row;
  }

  async updateSettings(
    ctx: AuthContext,
    storeId: string,
    patch: StoreSettingsUpdate,
    meta: RequestMeta,
  ): Promise<StoreSettingsDto> {
    const { before, after } = await this.db.asUser(ctx, async (db) => {
      const before = await this.findSettings(db, storeId);
      if (!before) throw new NotFoundException('Mağaza bulunamadı');
      const languages = patch.languages ?? before.languages;
      const defaultLanguage = patch.defaultLanguage ?? before.defaultLanguage;
      if (!languages.includes(defaultLanguage)) {
        throw new BadRequestException('Varsayılan dil, mağaza dilleri arasında olmalı');
      }
      const updated = await updateFromPatch(
        db,
        'public.store_settings',
        'store_id',
        storeId,
        patch,
        STORE_SETTINGS_COLUMNS,
      );
      if (updated === 0) throw new ForbiddenException('Mağaza ayarlarını değiştirme yetkiniz yok');
      return { before, after: (await this.findSettings(db, storeId))! };
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'store_settings.update',
      entityType: 'store_settings',
      entityId: storeId,
      before,
      after,
      meta,
    });
    return after;
  }

  async getProfitRules(ctx: AuthContext, storeId: string): Promise<ProfitRulesDto> {
    const row = await this.db.asUser(ctx, (db) => this.findProfitRules(db, storeId));
    if (!row) throw new NotFoundException('Mağaza bulunamadı');
    return row;
  }

  async updateProfitRules(
    ctx: AuthContext,
    storeId: string,
    patch: ProfitRulesUpdate,
    meta: RequestMeta,
  ): Promise<ProfitRulesDto> {
    const { before, after } = await this.db.asUser(ctx, async (db) => {
      const before = await this.findProfitRules(db, storeId);
      if (!before) throw new NotFoundException('Mağaza bulunamadı');
      const merged = { ...before, ...patch };
      const orderError = validateThresholdOrder(merged);
      if (orderError) throw new BadRequestException(orderError);
      const updated = await updateFromPatch(
        db,
        'public.profit_rules',
        'store_id',
        storeId,
        patch,
        PROFIT_RULE_COLUMNS,
      );
      if (updated === 0) throw new ForbiddenException('Kâr politikasını değiştirme yetkiniz yok');
      return { before, after: (await this.findProfitRules(db, storeId))! };
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'profit_rules.update',
      entityType: 'profit_rules',
      entityId: storeId,
      before,
      after,
      meta,
    });
    return after;
  }

  private async findStore(db: Queryable, userId: string, storeId: string) {
    const r = await db.query(`${STORE_SELECT} where m.user_id = $1 and s.id = $2`, [
      userId,
      storeId,
    ]);
    return r.rows[0] ? toStore(r.rows[0]) : null;
  }

  private async findSettings(db: Queryable, storeId: string): Promise<StoreSettingsDto | null> {
    const r = await db.query(
      `select store_id, sales_strategy, automation_level, market_scope, default_language, languages,
              target_markets, daily_ad_budget_cap::text, ad_budget_currency, seller_country, payout_currency, timezone, updated_at
         from public.store_settings where store_id = $1`,
      [storeId],
    );
    const x = r.rows[0];
    if (!x) return null;
    return {
      storeId: x.store_id,
      salesStrategy: x.sales_strategy,
      automationLevel: x.automation_level,
      marketScope: x.market_scope,
      defaultLanguage: x.default_language,
      languages: x.languages,
      targetMarkets: x.target_markets,
      dailyAdBudgetCap: x.daily_ad_budget_cap,
      adBudgetCurrency: x.ad_budget_currency,
      sellerCountry: x.seller_country,
      payoutCurrency: x.payout_currency,
      timezone: x.timezone,
      updatedAt: x.updated_at,
    };
  }

  private async findProfitRules(db: Queryable, storeId: string): Promise<ProfitRulesDto | null> {
    const r = await db.query(
      `select store_id, currency, target_contribution, excellent_threshold, publish_threshold,
              review_threshold, min_threshold, return_reserve_rate, remake_reserve_rate,
              other_variable_cost_rate, other_variable_cost_fixed, default_ad_cost_per_order,
              tax_rate_on_profit, vat_on_fees_rate, offsite_ads_tier, updated_at
         from public.profit_rules where store_id = $1`,
      [storeId],
    );
    const x = r.rows[0];
    if (!x) return null;
    return {
      storeId: x.store_id,
      currency: x.currency,
      targetContribution: x.target_contribution,
      excellentThreshold: x.excellent_threshold,
      publishThreshold: x.publish_threshold,
      reviewThreshold: x.review_threshold,
      minThreshold: x.min_threshold,
      returnReserveRate: x.return_reserve_rate,
      remakeReserveRate: x.remake_reserve_rate,
      otherVariableCostRate: x.other_variable_cost_rate,
      otherVariableCostFixed: x.other_variable_cost_fixed,
      defaultAdCostPerOrder: x.default_ad_cost_per_order,
      taxRateOnProfit: x.tax_rate_on_profit,
      vatOnFeesRate: x.vat_on_fees_rate,
      offsiteAdsTier: x.offsite_ads_tier,
      updatedAt: x.updated_at,
    };
  }
}

const STORE_SELECT = `select s.id, s.name, s.platform, s.status, s.currency, s.default_language,
  s.data_origin, s.external_shop_id, s.created_at, m.role
  from public.stores s join public.store_members m on m.store_id = s.id`;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toStore(r: any): StoreSummary {
  return {
    id: r.id,
    name: r.name,
    platform: r.platform,
    status: r.status,
    currency: r.currency,
    defaultLanguage: r.default_language,
    dataOrigin: r.data_origin,
    role: r.role,
    externalShopId: r.external_shop_id,
    createdAt: r.created_at,
  };
}
