import type pg from 'pg';
import { Decimal } from 'decimal.js';
import {
  calculateContribution,
  loadProfitContext,
  loadVariantCosts,
  type ProfitInput,
} from '@esm/profit-engine';

/**
 * Computes `order_actual` profit snapshots for a store's orders.
 *  - Revenue, shipping, discount, tax and refunds come from the imported Etsy order.
 *  - Production + fulfilment shipping: actual Printify order costs when linked,
 *    otherwise the current catalog costs of the matched variants (flagged as estimate).
 *  - Ads: the month's ACTUAL ad spend (ad_spend ledger) divided by the month's orders.
 *    This is an allocation for per-order analysis only; P&L subtracts ad_spend once.
 *  - Return reserve is not applied to actual orders (actual refunds are used).
 * Each run replaces the previous order_actual snapshot of an order.
 */
export async function recomputeOrderSnapshots(
  pool: pg.Pool,
  storeId: string,
  opts: { sinceDays?: number } = {},
) {
  const ctx = await loadProfitContext(pool, storeId);
  const policy = { ...ctx.policy, returnReserveRate: '0' };
  const orders = await pool.query(
    `select o.id, o.currency, o.subtotal::text, o.shipping_total::text, o.discount_total::text, o.tax_total::text,
            o.buyer_country, o.placed_at, o.printify_cost_total::text, o.printify_shipping_total::text, o.printify_currency,
            coalesce((select sum(r.amount) from public.refunds r where r.order_id = o.id and r.status = 'processed'), 0)::text refunded,
            (o.raw -> 'printify' ->> 'line_cost_basis') as cost_basis
       from public.orders o
      where o.store_id = $1 and o.status <> 'cancelled' and o.placed_at >= now() - make_interval(days => $2)`,
    [storeId, opts.sinceDays ?? 400],
  );
  // ad allocation per month
  const months = await pool.query(
    `select to_char(o.placed_at, 'YYYY-MM') m, count(*)::int n,
            (select coalesce(sum(a.amount), 0) from public.ad_spend a
              where a.store_id = $1 and a.currency = $2 and to_char(a.spend_date, 'YYYY-MM') = to_char(o.placed_at, 'YYYY-MM'))::text spend
       from public.orders o where o.store_id = $1 and o.status <> 'cancelled' group by 1, 3`,
    [storeId, ctx.storeCurrency],
  );
  const adPerOrder = new Map<string, string>();
  for (const m of months.rows)
    adPerOrder.set(m.m, m.n ? new Decimal(m.spend).div(m.n).toFixed(4) : '0');

  let computed = 0;
  let incomplete = 0;
  for (const o of orders.rows) {
    const items = await pool.query(
      `select quantity, unit_price::text, product_variant_id, production_cost::text, production_shipping_cost::text
         from public.order_items where order_id = $1`,
      [o.id],
    );
    const units = items.rows.reduce((s, i) => s + Number(i.quantity), 0);
    if (!units) continue;
    const warnings: string[] = [];
    let production = new Decimal(0);
    let fulfil = new Decimal(0);
    let costCurrency = 'USD';
    if (o.printify_cost_total !== null) {
      production = new Decimal(o.printify_cost_total);
      fulfil = new Decimal(o.printify_shipping_total ?? 0);
      costCurrency = o.printify_currency ?? 'USD';
      if (o.cost_basis === 'unverified')
        warnings.push('Printify kalem maliyeti esası doğrulanmadı (birim varsayıldı)');
    } else {
      warnings.push('Printify siparişi eşleşmedi; güncel katalog maliyetleri kullanıldı (tahmin)');
      let first = true;
      for (const it of items.rows) {
        if (!it.product_variant_id) {
          warnings.push('Ürün varyantı eşleşmedi; üretim maliyeti bilinmiyor');
          continue;
        }
        const c = await loadVariantCosts(pool, it.product_variant_id, o.buyer_country ?? 'US');
        if (!c.production) {
          warnings.push('Üretim maliyeti bilinmiyor');
          continue;
        }
        costCurrency = c.production.currency;
        production = production.plus(new Decimal(c.production.amount).mul(it.quantity));
        const add = new Decimal(c.shippingAdditional?.amount ?? 0);
        const firstCost = new Decimal(c.shippingFirst?.amount ?? 0);
        fulfil = fulfil.plus(
          first ? firstCost.plus(add.mul(it.quantity - 1)) : add.mul(it.quantity),
        );
        first = false;
      }
    }
    const month = new Date(o.placed_at).toISOString().slice(0, 7);
    const input: ProfitInput = {
      currency: o.currency,
      unitPrice: new Decimal(o.subtotal).div(units).toFixed(10),
      quantity: units,
      shippingCharged: o.shipping_total,
      discount: o.discount_total,
      salesTax: o.tax_total,
      refundedAmount: o.refunded,
      productionCostPerUnit: production.div(units).toFixed(10),
      productionCostCurrency: costCurrency,
      fulfillmentShippingFirst: fulfil.toFixed(4),
      fulfillmentShippingAdditional: '0',
      fulfillmentShippingCurrency: costCurrency,
      sellerCountry: ctx.sellerCountry ?? 'XX',
      buyerCountry: o.buyer_country ?? ctx.sellerCountry ?? 'XX',
      payoutCurrency: ctx.payoutCurrency ?? o.currency,
      adCostAllocated: o.currency === ctx.storeCurrency ? (adPerOrder.get(month) ?? '0') : '0',
      fxRates: ctx.fxRates,
    };
    const r = calculateContribution(input, ctx.rules, policy);
    if (!ctx.sellerCountry) warnings.push('Satıcı ülkesi ayarlanmadı');
    const complete =
      r.complete && !warnings.some((w) => w.includes('bilinmiyor') || w.includes('Satıcı ülkesi'));
    const allWarnings = [...new Set([...warnings, ...r.warnings])];
    if (!complete) incomplete++;

    const c = await pool.connect();
    try {
      await c.query('begin');
      await c.query(
        `delete from public.profit_snapshots where order_id = $1 and scenario = 'order_actual'`,
        [o.id],
      );
      await c.query(
        `insert into public.profit_snapshots
           (store_id, order_id, scenario, currency, gross_revenue, net_revenue, total_variable_costs, contribution,
            contribution_after_tax, contribution_margin, decision, breakdown, inputs, fee_rule_ids, engine_version,
            contribution_before_ads, ad_cost_allocated, complete, fees_verified, warnings)
         values ($1,$2,'order_actual',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)`,
        [
          storeId,
          o.id,
          r.currency,
          r.grossRevenue,
          r.netRevenue,
          r.totalVariableCosts,
          r.contribution,
          r.contributionAfterTax,
          r.contributionMargin,
          r.decision,
          JSON.stringify(r.breakdown),
          JSON.stringify(input),
          r.feeRuleIds.filter((id) => /^[0-9a-f-]{36}$/.test(id)),
          r.engineVersion,
          r.contributionBeforeAds,
          r.adCostAllocated,
          complete,
          r.feesVerified,
          JSON.stringify(allWarnings),
        ],
      );
      await c.query('commit');
    } catch (e) {
      await c.query('rollback').catch(() => undefined);
      throw e;
    } finally {
      c.release();
    }
    computed++;
  }
  return { computed, incomplete };
}
