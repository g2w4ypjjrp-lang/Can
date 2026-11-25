import { Injectable, NotFoundException } from '@nestjs/common';
import type { DashboardOverview, IntegrationStatus } from '@esm/shared';
import { DatabaseService, type AuthContext } from '../database/database.service.js';

const TRACKED_INTEGRATIONS = [
  'etsy',
  'printify',
  'etsy_ads',
  'meta_ads',
  'google_ads',
  'pinterest_ads',
  'tiktok_ads',
];

/**
 * Aggregates ONLY real rows from the database. No synthetic numbers are ever
 * produced: when nothing is connected, the KPIs are zero/null and `dataOrigin`
 * is 'none'. Demo stores are reported as 'demo' and never mixed with live data.
 */
@Injectable()
export class DashboardService {
  constructor(private readonly db: DatabaseService) {}

  overview(ctx: AuthContext, storeId: string, days = 30): Promise<DashboardOverview> {
    return this.db.asUser(ctx, async (db) => {
      const s = await db.query(
        `select s.id, s.currency, s.status, s.data_origin, coalesce(ss.timezone, 'UTC') as tz
           from public.stores s left join public.store_settings ss on ss.store_id = s.id
          where s.id = $1`,
        [storeId],
      );
      const store = s.rows[0];
      if (!store) throw new NotFoundException('Mağaza bulunamadı');
      const tz: string = store.tz;
      const currency: string = store.currency;
      const params = [storeId, currency, tz, days];

      // Orders in the store currency, excluding cancelled ones. Revenue excludes tax.
      const k = await db.query(
        `with o as (
           select (placed_at at time zone $3)::date as d, grand_total - tax_total as revenue, id
             from public.orders
            where store_id = $1 and currency = $2 and status <> 'cancelled'
              and placed_at >= (date_trunc('day', now() at time zone $3) - make_interval(days => $4 - 1)) at time zone $3
         )
         select
           coalesce(sum(revenue) filter (where d = (now() at time zone $3)::date), 0)::text as revenue_today,
           coalesce(sum(revenue) filter (where d >= date_trunc('month', now() at time zone $3)::date), 0)::text as revenue_month,
           count(*) filter (where d >= date_trunc('month', now() at time zone $3)::date)::int as orders_month,
           case when count(*) filter (where d >= date_trunc('month', now() at time zone $3)::date) > 0
             then round(sum(revenue) filter (where d >= date_trunc('month', now() at time zone $3)::date)
                  / count(*) filter (where d >= date_trunc('month', now() at time zone $3)::date), 2)::text
           end as aov
         from o`,
        params,
      );
      const daily = await db.query(
        `select g.d::text as date,
                coalesce(sum(o.grand_total - o.tax_total), 0)::text as revenue,
                count(o.id)::int as orders
           from generate_series((now() at time zone $3)::date - ($4 - 1), (now() at time zone $3)::date, interval '1 day') g(d)
           left join public.orders o
             on o.store_id = $1 and o.currency = $2 and o.status <> 'cancelled'
            and (o.placed_at at time zone $3)::date = g.d::date
          group by g.d order by g.d`,
        params,
      );
      const month = await db.query(
        `select
           (select coalesce(sum(amount), 0)::text from public.ad_spend
             where store_id = $1 and currency = $2
               and spend_date >= date_trunc('month', now() at time zone $3)::date) as ad_spend,
           (select sum(contribution)::text from public.profit_snapshots ps
             join public.orders o on o.id = ps.order_id
             where ps.store_id = $1 and ps.scenario = 'order_actual' and ps.currency = $2
               and o.placed_at >= date_trunc('month', now() at time zone $3) at time zone $3) as contribution,
           (select count(distinct r.order_id)::int from public.refunds r
             join public.orders o on o.id = r.order_id
             where r.store_id = $1 and r.status = 'processed'
               and o.placed_at >= date_trunc('month', now() at time zone $3) at time zone $3) as refunded_orders`,
        [storeId, currency, tz],
      );
      const top = await db.query(
        `select oi.title, sum(oi.quantity)::int as units, sum(oi.quantity * oi.unit_price)::text as revenue
           from public.order_items oi join public.orders o on o.id = oi.order_id
          where o.store_id = $1 and o.currency = $2 and o.status <> 'cancelled'
            and o.placed_at >= (now() - make_interval(days => $3))
          group by oi.title order by sum(oi.quantity * oi.unit_price) desc limit 5`,
        [storeId, currency, days],
      );
      const countries = await db.query(
        `select coalesce(buyer_country, '??') as country, count(*)::int as orders,
                sum(grand_total - tax_total)::text as revenue
           from public.orders
          where store_id = $1 and currency = $2 and status <> 'cancelled'
            and placed_at >= (now() - make_interval(days => $3))
          group by 1 order by sum(grand_total - tax_total) desc limit 10`,
        [storeId, currency, days],
      );
      const misc = await db.query(
        `select
           (select count(*)::int from public.approval_requests where store_id = $1 and status = 'pending') as pending,
           (select count(*)::int from public.notifications where user_id = $2 and read_at is null) as unread,
           (select count(*)::int from public.orders where store_id = $1 and currency <> $3) as other_currency_orders`,
        [storeId, ctx.userId, currency],
      );
      const decisions = await db.query(
        `select id, summary, confidence, created_at from public.ai_decisions
          where store_id = $1 and status in ('proposed','approval_requested')
          order by created_at desc limit 5`,
        [storeId],
      );
      const accounts = await db.query(
        `select platform, status, last_synced_at from public.connected_accounts where store_id = $1`,
        [storeId],
      );

      const kpi = k.rows[0];
      const m = month.rows[0];
      const ordersMonth: number = kpi.orders_month;
      const adSpend: string = m.ad_spend;
      const revenueMonth: string = kpi.revenue_month;
      const integrations: IntegrationStatus[] = TRACKED_INTEGRATIONS.map((platform) => {
        const a = accounts.rows.find((r) => r.platform === platform);
        return {
          platform,
          status: a ? a.status : 'not_connected',
          lastSyncedAt: a?.last_synced_at ?? null,
        };
      });

      const notes: string[] = [];
      const dataOrigin: DashboardOverview['dataOrigin'] =
        store.data_origin === 'demo' ? 'demo' : store.status === 'connected' ? 'live' : 'none';
      if (dataOrigin === 'none')
        notes.push('Etsy mağazası henüz bağlanmadı; gösterilecek gerçek veri yok.');
      if (dataOrigin === 'demo')
        notes.push('Bu bir DEMO mağazasıdır; rakamlar gerçek satış değildir.');
      if (misc.rows[0].other_currency_orders > 0) {
        notes.push(
          `${misc.rows[0].other_currency_orders} sipariş farklı para biriminde; döviz çevrimi FAZ 4 (Profit Engine) ile eklenecek.`,
        );
      }
      if (m.contribution === null)
        notes.push('Sipariş bazlı katkı hesabı FAZ 4 (Profit Engine) ile aktifleşecek.');

      return {
        storeId,
        currency,
        dataOrigin,
        period: {
          from: daily.rows[0]?.date ?? '',
          to: daily.rows[daily.rows.length - 1]?.date ?? '',
        },
        kpis: {
          revenueToday: kpi.revenue_today,
          revenueMonth,
          ordersMonth,
          averageOrderValue: kpi.aov ?? null,
          adSpendMonth: adSpend,
          roas: Number(adSpend) > 0 ? (Number(revenueMonth) / Number(adSpend)).toFixed(2) : null,
          contributionMonth: m.contribution,
          refundRate: ordersMonth > 0 ? (m.refunded_orders / ordersMonth).toFixed(4) : null,
        },
        dailyRevenue: daily.rows,
        topProducts: top.rows,
        countrySales: countries.rows,
        pendingApprovals: misc.rows[0].pending,
        unreadNotifications: misc.rows[0].unread,
        recentDecisions: decisions.rows.map((d) => ({
          id: d.id,
          summary: d.summary,
          confidence: d.confidence,
          createdAt: d.created_at,
        })),
        integrations,
        notes,
      };
    });
  }
}
