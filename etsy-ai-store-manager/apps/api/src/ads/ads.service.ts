import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { Decimal } from 'decimal.js';
import { MetaAdsClient, MetaApiError } from '@esm/integrations';
import {
  allocateBudget,
  assessCampaign,
  computeEconomics,
  type CampaignStats,
} from '@esm/profit-engine';
import { JOBS, QUEUES } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { TokenCryptoService } from '../security/token-crypto.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

export const AD_PLATFORMS = [
  'etsy_ads',
  'meta_ads',
  'google_ads',
  'pinterest_ads',
  'tiktok_ads',
] as const;
export type AdPlatform = (typeof AD_PLATFORMS)[number];

/** Honest capability matrix shown in the UI and the API. */
export const PLATFORM_CAPABILITIES: Record<
  AdPlatform,
  { reporting: string; management: string; note: string }
> = {
  etsy_ads: {
    reporting: 'csv/manual + Etsy ödeme defteri (gerçek harcama)',
    management: 'manual',
    note: 'Etsy Open API v3’te Etsy Ads uç noktası yok. Bütçe/kampanya değişiklikleri Etsy panelinde elle yapılır.',
  },
  meta_ads: {
    reporting: 'api (Marketing API v27.0 insights, ads_read)',
    management: 'manual',
    note: 'Bütçe yazımı otomatik değil: resmî dokümanda daily_budget birimi doğrulanamadı. Değişiklikler Ads Manager’da onaylı manuel adımla.',
  },
  google_ads: {
    reporting: 'csv/manual',
    management: 'manual',
    note: 'Google Ads API onaylı geliştirici jetonu (developer token) ve OAuth gerektirir; jeton verildiğinde bağlanacak.',
  },
  pinterest_ads: {
    reporting: 'csv/manual',
    management: 'manual',
    note: 'Pinterest API v5 erişimi uygulama onayı gerektirir; onay sonrası raporlama bağlanacak.',
  },
  tiktok_ads: {
    reporting: 'csv/manual',
    management: 'manual',
    note: 'TikTok Marketing API onaylı geliştirici uygulaması gerektirir.',
  },
};

export interface MetricRow {
  date: string;
  campaign: string;
  impressions: number;
  clicks: number;
  spend: string;
  orders: string;
  revenue: string;
}

const today = () => new Date().toISOString().slice(0, 10);

@Injectable()
export class AdsService {
  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
    private readonly crypto: TokenCryptoService,
  ) {}

  // ------------------------------------------------------------ policy

  getPolicy(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      return toPolicy(
        (await db.query(`select * from public.ad_budget_policies where store_id = $1`, [storeId]))
          .rows[0],
      );
    });
  }

  async setPolicy(
    ctx: AuthContext,
    storeId: string,
    p: {
      dailyCap: string;
      monthlyCap?: string | null;
      currency: string;
      minClicksForDecision: number;
    },
    meta: RequestMeta,
  ) {
    const row = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      if (p.monthlyCap && new Decimal(p.monthlyCap).lt(p.dailyCap))
        throw new BadRequestException('Aylık sınır günlük sınırdan küçük olamaz');
      const before = (
        await db.query(`select * from public.ad_budget_policies where store_id = $1`, [storeId])
      ).rows[0];
      const r = await db.query(
        `insert into public.ad_budget_policies (store_id, daily_cap, monthly_cap, currency, min_clicks_for_decision, updated_by)
         values ($1,$2,$3,$4,$5,$6)
         on conflict (store_id) do update set daily_cap = excluded.daily_cap, monthly_cap = excluded.monthly_cap,
           currency = excluded.currency, min_clicks_for_decision = excluded.min_clicks_for_decision, updated_by = excluded.updated_by
         returning *`,
        [storeId, p.dailyCap, p.monthlyCap ?? null, p.currency, p.minClicksForDecision, ctx.userId],
      );
      return { before, after: r.rows[0] };
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'ads.policy.update',
      entityType: 'ad_budget_policy',
      entityId: storeId,
      before: row.before ? toPolicy(row.before) : null,
      after: toPolicy(row.after),
      meta,
    });
    return toPolicy(row.after);
  }

  // ------------------------------------------------------------ accounts & campaigns

  listAccounts(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select a.*, ca.status as connection_status,
                (select count(*)::int from public.ad_campaigns c where c.ad_account_id = a.id) as campaigns
           from public.ad_accounts a left join public.connected_accounts ca on ca.id = a.connected_account_id
          where a.store_id = $1 order by a.platform, a.created_at`,
        [storeId],
      );
      return {
        capabilities: PLATFORM_CAPABILITIES,
        accounts: r.rows.map((a) => ({
          id: a.id,
          platform: a.platform,
          externalAccountId: a.external_account_id,
          name: a.name,
          currency: a.currency,
          status: a.status,
          spendSource: a.spend_source,
          reporting: a.connected_account_id ? 'api' : 'manual',
          connectionStatus: a.connection_status,
          lastSyncedAt: a.last_synced_at,
          lastError: a.last_error,
          campaigns: a.campaigns,
        })),
      };
    });
  }

  async createAccount(
    ctx: AuthContext,
    storeId: string,
    a: { platform: AdPlatform; externalAccountId: string; name: string; currency: string },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `insert into public.ad_accounts (store_id, platform, external_account_id, name, currency, management_mode, spend_source)
         values ($1,$2,$3,$4,$5,'manual','metrics')
         on conflict (store_id, platform, external_account_id) do nothing returning id`,
        [storeId, a.platform, a.externalAccountId, a.name, a.currency],
      );
      if (!r.rowCount) throw new ConflictException('Bu reklam hesabı zaten kayıtlı');
      return { id: r.rows[0].id };
    });
  }

  /** Verifies a Meta token by reading the ad account, then stores it encrypted (server side only). */
  async connectMeta(
    ctx: AuthContext,
    storeId: string,
    input: { adAccountId: string; accessToken: string },
    meta: RequestMeta,
  ) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'admin'));
    const client = new MetaAdsClient({
      accessToken: input.accessToken,
      baseUrl: this.env.META_GRAPH_BASE_URL,
    });
    let acct: { name: string; currency: string };
    try {
      acct = await client.getAdAccount(input.adAccountId);
    } catch (e) {
      if (e instanceof MetaApiError)
        throw new BadRequestException(
          `Meta hesabı doğrulanamadı: ${e.message} (ads_read izni ve hesap kimliğini kontrol edin)`,
        );
      throw e;
    }
    const id = await this.db.asService(async (db) => {
      const ca = await db.query(
        `insert into public.connected_accounts (store_id, connected_by, platform, external_account_id, display_name, scopes, status, metadata)
         values ($1,$2,'meta_ads',$3,$4,array['ads_read'],'active','{}'::jsonb)
         on conflict (store_id, platform, external_account_id) do update set status = 'active', display_name = excluded.display_name,
           last_error = null, connected_by = excluded.connected_by
         returning id`,
        [storeId, ctx.userId, input.adAccountId, acct.name],
      );
      const caId: string = ca.rows[0].id;
      await db.query(
        `insert into public.oauth_tokens (connected_account_id, access_token_ciphertext, token_type, scopes, key_version, last_refreshed_at)
         values ($1,$2,'Bearer',array['ads_read'],$3,now())
         on conflict (connected_account_id) do update set access_token_ciphertext = excluded.access_token_ciphertext,
           key_version = excluded.key_version, last_refreshed_at = now()`,
        [
          caId,
          this.crypto.encrypt(input.accessToken, `connected_account:${caId}`),
          this.crypto.keyVersion,
        ],
      );
      const a = await db.query(
        `insert into public.ad_accounts (store_id, connected_account_id, platform, external_account_id, name, currency, management_mode, spend_source)
         values ($1,$2,'meta_ads',$3,$4,$5,'manual','metrics')
         on conflict (store_id, platform, external_account_id) do update set connected_account_id = excluded.connected_account_id,
           name = excluded.name, currency = excluded.currency, status = 'active'
         returning id`,
        [storeId, caId, input.adAccountId, acct.name, acct.currency.toUpperCase()],
      );
      return a.rows[0].id as string;
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'ads.meta.connect',
      entityType: 'ad_account',
      entityId: id,
      after: { adAccountId: input.adAccountId, name: acct.name }, // never the token
      meta,
    });
    await this.requestSync(ctx, storeId);
    return { id, name: acct.name, currency: acct.currency };
  }

  async requestSync(ctx: AuthContext, storeId: string) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'admin'));
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.adsSyncStore, {
      idempotencyKey: `ads-sync:${storeId}:manual:${Math.floor(Date.now() / 60_000)}`,
      storeId,
      payload: { reason: 'manual' },
    });
    return { jobId };
  }

  async createCampaign(
    ctx: AuthContext,
    storeId: string,
    c: { adAccountId: string; name: string; objective?: string; dailyBudget?: string },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const a = await db.query(
        `select currency from public.ad_accounts where id = $1 and store_id = $2`,
        [c.adAccountId, storeId],
      );
      if (!a.rowCount) throw new NotFoundException('Reklam hesabı bulunamadı');
      // records an EXISTING campaign for tracking; starting one is an approved manual step
      const r = await db.query(
        `insert into public.ad_campaigns (ad_account_id, store_id, external_campaign_id, name, objective, status, daily_budget, currency, managed_via)
         values ($1,$2,$3,$4,$5,'active',$6,$7,'manual')
         on conflict (ad_account_id, external_campaign_id) where external_campaign_id is not null do nothing returning id`,
        [
          c.adAccountId,
          storeId,
          `manual:${c.name.toLowerCase()}`,
          c.name,
          c.objective ?? null,
          c.dailyBudget ?? null,
          a.rows[0].currency,
        ],
      );
      if (!r.rowCount) throw new ConflictException('Bu isimde kampanya zaten var');
      return { id: r.rows[0].id };
    });
  }

  /** CSV / manual daily rows. Campaigns are matched by name within the account. */
  async importMetrics(
    ctx: AuthContext,
    storeId: string,
    adAccountId: string,
    rows: MetricRow[],
    meta: RequestMeta,
  ) {
    const res = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const acc = (
        await db.query(`select * from public.ad_accounts where id = $1 and store_id = $2`, [
          adAccountId,
          storeId,
        ])
      ).rows[0];
      if (!acc) throw new NotFoundException('Reklam hesabı bulunamadı');
      if (acc.connected_account_id)
        throw new ConflictException(
          'Bu hesap API ile raporlanıyor; CSV içe aktarma çift kayıt oluşturur',
        );
      let written = 0;
      for (const r of rows) {
        const camp = await db.query(
          `insert into public.ad_campaigns (ad_account_id, store_id, external_campaign_id, name, status, currency, managed_via)
           values ($1,$2,$3,$4,'active',$5,'manual')
           on conflict (ad_account_id, external_campaign_id) where external_campaign_id is not null do update set name = excluded.name
           returning id`,
          [acc.id, storeId, `manual:${r.campaign.toLowerCase()}`, r.campaign, acc.currency],
        );
        const cid = camp.rows[0].id;
        await db.query(
          `insert into public.ad_metrics (campaign_id, store_id, metric_date, impressions, clicks, spend, conversions, conversion_value,
                                          currency, attribution_model, attribution_confidence, source)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,'platform report (imported)','low','csv_import')
           on conflict (campaign_id, metric_date) do update set impressions = excluded.impressions, clicks = excluded.clicks,
             spend = excluded.spend, conversions = excluded.conversions, conversion_value = excluded.conversion_value, source = excluded.source`,
          [
            cid,
            storeId,
            r.date,
            r.impressions,
            r.clicks,
            r.spend,
            r.orders,
            r.revenue,
            acc.currency,
          ],
        );
        if (acc.spend_source === 'metrics') {
          await db.query(
            `insert into public.ad_spend (store_id, ad_account_id, campaign_id, spend_date, amount, currency, source)
             values ($1,$2,$3,$4,$5,$6,'csv_import')
             on conflict (ad_account_id, spend_date, coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), source)
               do update set amount = excluded.amount`,
            [storeId, acc.id, cid, r.date, r.spend, acc.currency],
          );
        }
        written++;
      }
      return { written, spendBooked: acc.spend_source === 'metrics' };
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'ads.metrics.import',
      entityType: 'ad_account',
      entityId: adAccountId,
      after: { rows: rows.length },
      meta,
    });
    return res;
  }

  // ------------------------------------------------------------ overview & recommendations

  async overview(ctx: AuthContext, storeId: string, days: number) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      return buildOverview(db, storeId, days);
    });
  }

  // ------------------------------------------------------------ proposals

  async createProposal(
    ctx: AuthContext,
    storeId: string,
    input: { totalDailyBudget?: string; days: number },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const o = await buildOverview(db, storeId, input.days);
      if (!o.policy.configured)
        throw new ConflictException('Önce günlük reklam bütçesi sınırını belirleyin');
      const total = new Decimal(input.totalDailyBudget ?? o.policy.dailyCap);
      if (total.gt(o.policy.dailyCap))
        throw new BadRequestException(
          `Toplam günlük bütçe sınırı aşıyor (${o.policy.dailyCap} ${o.policy.currency})`,
        );
      if (!o.campaigns.length)
        throw new ConflictException('Önce reklam kampanyası kaydı / raporu ekleyin');
      const allocations = allocateBudget(o.campaigns, total.toFixed(2));
      const r = await db.query(
        `insert into public.ad_budget_proposals (store_id, period_start, period_end, total_daily_budget, currency, allocations, assumptions, created_by)
         values ($1, current_date, current_date + 6, $2, $3, $4, $5, $6) returning *`,
        [
          storeId,
          total.toFixed(2),
          o.policy.currency,
          JSON.stringify(allocations),
          JSON.stringify({
            economics: o.economics,
            windowDays: input.days,
            minClicks: o.policy.minClicksForDecision,
          }),
          ctx.userId,
        ],
      );
      return toProposal(r.rows[0]);
    });
  }

  listProposals(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select * from public.ad_budget_proposals where store_id = $1 order by created_at desc limit 20`,
        [storeId],
      );
      return r.rows.map(toProposal);
    });
  }

  /** Approval request for a budget split (approve → do it on the platform → confirm). */
  async submitProposal(
    ctx: AuthContext,
    storeId: string,
    proposalId: string,
    reason: string,
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const p = (
        await db.query(
          `select * from public.ad_budget_proposals where id = $1 and store_id = $2 for update`,
          [proposalId, storeId],
        )
      ).rows[0];
      if (!p) throw new NotFoundException('Öneri bulunamadı');
      if (p.status !== 'draft') throw new ConflictException(`Öneri "${p.status}" durumunda`);
      const policy = toPolicy(
        (await db.query(`select * from public.ad_budget_policies where store_id = $1`, [storeId]))
          .rows[0],
      );
      if (new Decimal(p.total_daily_budget).gt(policy.dailyCap))
        throw new ConflictException('Sınır öneriden sonra düşürülmüş; yeni öneri oluşturun');
      const allocs = p.allocations as Array<{
        name: string;
        platform: string;
        currentDailyBudget: string | null;
        proposedDailyBudget: string;
        verdict: string;
      }>;
      const current = allocs.reduce((s, a) => s.plus(a.currentDailyBudget ?? 0), new Decimal(0));
      const increase = new Decimal(p.total_daily_budget).gt(current);
      const lines = allocs.map(
        (a) =>
          `${a.platform} · ${a.name}: ${a.currentDailyBudget ?? '—'} → ${a.proposedDailyBudget} ${p.currency}${a.proposedDailyBudget === '0.00' ? ' (durdur)' : ''}`,
      );
      const r = await db.query(
        `insert into public.approval_requests
           (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit,
            estimated_cost, cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
         values ($1,'user',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,true, now() + interval '3 days') returning *`,
        [
          storeId,
          ctx.userId,
          increase ? 'increase_ad_budget' : 'allocate_ad_budget',
          `Reklam bütçesi dağıtımı: günlük ${p.total_daily_budget} ${p.currency}`,
          `Günlük bütçeler şöyle değişecek:\n${lines.join('\n')}`,
          reason,
          'Bütçe kârlı kampanyalara kayar; başa baş ROAS altındaki kampanyalar durdurulur.',
          new Decimal(p.total_daily_budget).times(7).toFixed(2),
          p.currency,
          `Haftalık en fazla ${new Decimal(p.total_daily_budget).times(7).toFixed(2)} ${p.currency} harcama. Başa baş ROAS ${
            p.assumptions?.economics?.breakEvenRoas ?? 'bilinmiyor'
          }, hedef ROAS ${p.assumptions?.economics?.targetRoas ?? 'bilinmiyor'} (sipariş başı hedef katkı korunur).`,
          'MANUEL: Etsy Ads / Meta Ads Manager / diğer panellerde uygulanır (resmî API ile bütçe yazımı yok veya doğrulanmadı); uygulandıktan sonra burada onaylanır.',
          JSON.stringify({ kind: 'ad_budget_proposal', proposalId, manual: true }),
          increase ? 'high' : 'medium',
        ],
      );
      await db.query(
        `update public.ad_budget_proposals set status = 'pending_approval', approval_request_id = $2 where id = $1`,
        [proposalId, r.rows[0].id],
      );
      return r.rows[0];
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: approval.action_type, proposalId },
      meta,
    });
    return toApprovalDto(approval);
  }

  // ------------------------------------------------------------ Etsy ledger

  ledgerTypes(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select ledger_type, count(*)::int as entries, sum(amount)::text as total, currency,
                min(description) as example
           from public.etsy_ledger_entries where store_id = $1 and entry_created_at > now() - interval '90 days'
          group by ledger_type, currency order by ledger_type`,
        [storeId],
      );
      const mapped =
        (
          await db.query(
            `select etsy_ads_ledger_types from public.store_settings where store_id = $1`,
            [storeId],
          )
        ).rows[0]?.etsy_ads_ledger_types ?? [];
      return {
        mapped,
        types: r.rows.map((x) => ({
          ledgerType: x.ledger_type,
          entries: x.entries,
          total: x.total,
          currency: x.currency,
          example: x.example,
          // a hint only: Etsy does not document these values
          suggested:
            /prolist|etsy.?ads|promoted|marketing/i.test(`${x.ledger_type} ${x.example ?? ''}`) &&
            !/offsite/i.test(x.ledger_type ?? ''),
        })),
      };
    });
  }

  /** Maps ledger types to Etsy Ads spend and switches the Etsy Ads account to the ledger source. */
  async setLedgerMapping(ctx: AuthContext, storeId: string, types: string[], meta: RequestMeta) {
    if (types.some((t) => /offsite/i.test(t)))
      throw new BadRequestException(
        'Offsite Ads ücreti sipariş başı ücrettir (Profit Engine’de); reklam harcaması olarak eklenemez',
      );
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      await db.query(
        `update public.store_settings set etsy_ads_ledger_types = $2 where store_id = $1`,
        [storeId, types],
      );
      const shop = (
        await db.query(`select external_shop_id, currency from public.stores where id = $1`, [
          storeId,
        ])
      ).rows[0];
      if (!shop?.external_shop_id) throw new ConflictException('Etsy bağlı değil');
      await db.query(
        `insert into public.ad_accounts (store_id, platform, external_account_id, name, currency, management_mode, spend_source)
         values ($1,'etsy_ads',$2,'Etsy Ads',$3,'manual','ledger')
         on conflict (store_id, platform, external_account_id) do update set spend_source = 'ledger'`,
        [storeId, `etsy-shop:${shop.external_shop_id}`, shop.currency ?? 'USD'],
      );
      // spend previously booked from CSV for this account would now be counted twice
      await db.query(
        `delete from public.ad_spend s using public.ad_accounts a
          where a.id = s.ad_account_id and a.store_id = $1 and a.platform = 'etsy_ads' and a.spend_source = 'ledger'
            and s.source in ('csv_import','manual')`,
        [storeId],
      );
    });
    // import the ledger now and rebuild Etsy Ads spend from the new mapping
    await this.queue.enqueue(QUEUES.sync, JOBS.adsSyncStore, {
      idempotencyKey: `ads-sync:${storeId}:ledger-mapping:${Date.now()}`,
      storeId,
      payload: { reason: 'ledger-mapping' },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'ads.ledger.mapping',
      entityType: 'store_settings',
      entityId: storeId,
      after: { types },
      meta,
    });
    return { types };
  }
}

// ---------------------------------------------------------------- helpers

async function buildOverview(db: Queryable, storeId: string, days: number) {
  const policy = toPolicy(
    (await db.query(`select * from public.ad_budget_policies where store_id = $1`, [storeId]))
      .rows[0],
  );
  const target =
    (
      await db.query(
        `select target_contribution::text t from public.profit_rules where store_id = $1`,
        [storeId],
      )
    ).rows[0]?.t ?? '10.00';
  const sample = (
    await db.query(
      `select count(distinct order_id)::int orders, coalesce(sum(gross_revenue),0)::text revenue,
              coalesce(sum(coalesce(contribution_before_ads, contribution + ad_cost_allocated)),0)::text cba
         from public.profit_snapshots
        where store_id = $1 and scenario = 'order_actual' and complete and calculated_at > now() - interval '90 days'`,
      [storeId],
    )
  ).rows[0];
  const economics = computeEconomics({
    revenue: sample.revenue,
    contributionBeforeAds: sample.cba,
    orders: sample.orders,
    targetContribution: target,
  });
  const rows = (
    await db.query(
      `select c.id, c.name, c.status, c.daily_budget::text daily_budget, a.platform,
              coalesce(sum(m.impressions),0)::bigint impressions, coalesce(sum(m.clicks),0)::bigint clicks,
              coalesce(sum(m.spend),0)::text spend, coalesce(sum(m.conversions),0)::text conversions,
              coalesce(sum(m.conversion_value),0)::text conversion_value,
              case when bool_or(m.attribution_confidence = 'low') then 'low'
                   when bool_or(m.attribution_confidence = 'medium') then 'medium'
                   when count(m.id) > 0 then 'high' else 'low' end attribution
         from public.ad_campaigns c join public.ad_accounts a on a.id = c.ad_account_id
         left join public.ad_metrics m on m.campaign_id = c.id and m.metric_date > current_date - $2::int
        where c.store_id = $1 and c.status <> 'ended'
        group by c.id, a.platform order by sum(m.spend) desc nulls last`,
      [storeId, days],
    )
  ).rows;
  const campaigns = rows.map((r) =>
    assessCampaign(
      {
        campaignId: r.id,
        name: r.name,
        platform: r.platform,
        status: r.status,
        dailyBudget: r.daily_budget,
        impressions: Number(r.impressions),
        clicks: Number(r.clicks),
        spend: r.spend,
        conversions: r.conversions,
        conversionValue: r.conversion_value,
        attributionConfidence: r.attribution,
      } satisfies CampaignStats,
      economics,
      policy.minClicksForDecision,
    ),
  );
  const spend = (
    await db.query(
      `select coalesce(sum(amount) filter (where spend_date = current_date),0)::text spend_today,
              coalesce(sum(amount) filter (where date_trunc('month', spend_date) = date_trunc('month', current_date)),0)::text spend_month,
              coalesce(sum(amount) filter (where spend_date > current_date - $2::int),0)::text spend_period
         from public.ad_spend where store_id = $1`,
      [storeId, days],
    )
  ).rows[0];
  const budgets = campaigns.reduce(
    (s, c) => s.plus(c.status === 'active' ? (c.dailyBudget ?? 0) : 0),
    new Decimal(0),
  );
  return {
    windowDays: days,
    asOf: today(),
    policy,
    economics,
    spend: { today: spend.spend_today, month: spend.spend_month, period: spend.spend_period },
    activeDailyBudgets: budgets.toFixed(2),
    overCap: policy.configured && budgets.gt(policy.dailyCap),
    monthOverCap:
      policy.monthlyCap !== null && new Decimal(spend.spend_month).gt(policy.monthlyCap),
    campaigns,
    note: 'ad_spend tek harcama defteridir; sipariş kârlılığındaki reklam payı ayrıca gider yazılmaz.',
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toPolicy(r: any) {
  return r
    ? {
        configured: true,
        dailyCap: r.daily_cap as string,
        monthlyCap: (r.monthly_cap as string | null) ?? null,
        currency: r.currency as string,
        minClicksForDecision: r.min_clicks_for_decision as number,
        updatedAt: r.updated_at,
      }
    : {
        configured: false,
        dailyCap: '0.00',
        monthlyCap: null,
        currency: 'USD',
        minClicksForDecision: 100,
        updatedAt: null,
      };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toProposal(r: any) {
  return {
    id: r.id,
    periodStart: r.period_start,
    periodEnd: r.period_end,
    totalDailyBudget: r.total_daily_budget,
    currency: r.currency,
    allocations: r.allocations,
    assumptions: r.assumptions,
    status: r.status,
    approvalRequestId: r.approval_request_id,
    createdAt: r.created_at,
  };
}
