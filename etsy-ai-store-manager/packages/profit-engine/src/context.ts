import type { FeeRule, ProfitPolicy } from './engine.js';

/** Minimal query interface (pg Pool / PoolClient compatible). */
export interface SqlRunner {
  query(sql: string, params?: unknown[]): Promise<{ rows: any[] }>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface ProfitContext {
  storeId: string;
  storeCurrency: string;
  sellerCountry: string | null;
  payoutCurrency: string | null;
  targetMarkets: string[];
  policy: ProfitPolicy;
  defaultAdCostPerOrder: string;
  rules: FeeRule[];
  fxRates: Record<string, string>;
  fxAsOf: string | null;
}

/**
 * Loads everything the engine needs for one store. Global fee rules count as
 * verified only when this store's owner/admin verified them (fee_rule_verifications).
 */
export async function loadProfitContext(db: SqlRunner, storeId: string): Promise<ProfitContext> {
  const s = await db.query(
    `select s.currency, ss.seller_country, ss.payout_currency, ss.target_markets,
            pr.excellent_threshold::text, pr.publish_threshold::text, pr.review_threshold::text, pr.min_threshold::text,
            pr.target_contribution::text, pr.return_reserve_rate::text, pr.remake_reserve_rate::text,
            pr.other_variable_cost_rate::text, pr.other_variable_cost_fixed::text, pr.tax_rate_on_profit::text,
            pr.vat_on_fees_rate::text, pr.offsite_ads_tier, pr.default_ad_cost_per_order::text
       from public.stores s
       join public.store_settings ss on ss.store_id = s.id
       join public.profit_rules pr on pr.store_id = s.id
      where s.id = $1`,
    [storeId],
  );
  const x = s.rows[0];
  if (!x) throw new Error('Store not found');
  const r = await db.query(
    `select f.id, f.platform, f.fee_type, f.rate::text, f.fixed_amount::text, f.fixed_currency, f.basis, f.country,
            f.buyer_scope, f.cap_amount::text, f.cap_currency, f.tier, f.source_url, f.store_id,
            (f.verified_at is not null and f.store_id is not null) or v.fee_rule_id is not null as verified
       from public.fee_rules f
       left join public.fee_rule_verifications v on v.fee_rule_id = f.id and v.store_id = $1
      where (f.store_id is null or f.store_id = $1)
        and f.effective_from <= current_date and (f.effective_to is null or f.effective_to > current_date)`,
    [storeId],
  );
  const fx = await db.query(
    `select distinct on (quote) quote, rate::text, as_of from public.fx_rates
      where base = 'EUR' order by quote, as_of desc`,
  );
  const fxRates: Record<string, string> = {};
  let fxAsOf: string | null = null;
  for (const row of fx.rows) {
    fxRates[row.quote] = row.rate;
    const asOf = row.as_of instanceof Date ? row.as_of.toISOString() : String(row.as_of);
    if (!fxAsOf || asOf < fxAsOf) fxAsOf = asOf;
  }
  return {
    storeId,
    storeCurrency: x.currency,
    sellerCountry: x.seller_country,
    payoutCurrency: x.payout_currency,
    targetMarkets: x.target_markets ?? [],
    policy: {
      thresholds: {
        excellent: x.excellent_threshold,
        publish: x.publish_threshold,
        review: x.review_threshold,
        min: x.min_threshold,
      },
      targetContribution: x.target_contribution,
      returnReserveRate: x.return_reserve_rate,
      remakeReserveRate: x.remake_reserve_rate,
      otherVariableCostRate: x.other_variable_cost_rate,
      otherVariableCostFixed: x.other_variable_cost_fixed,
      taxRateOnProfit: x.tax_rate_on_profit,
      vatOnFeesRate: x.vat_on_fees_rate,
      offsiteAdsTier: x.offsite_ads_tier,
    },
    defaultAdCostPerOrder: x.default_ad_cost_per_order,
    rules: r.rows.map((f) => ({
      id: f.id,
      platform: f.platform,
      feeType: f.fee_type,
      rate: f.rate,
      fixedAmount: f.fixed_amount,
      fixedCurrency: f.fixed_currency,
      basis: f.basis,
      country: f.country,
      buyerScope: f.buyer_scope,
      capAmount: f.cap_amount,
      capCurrency: f.cap_currency,
      tier: f.tier,
      verified: f.verified,
      sourceUrl: f.source_url,
      storeSpecific: f.store_id !== null,
    })),
    fxRates,
    fxAsOf,
  };
}

/** Current production + fulfilment shipping cost for a variant and destination. */
export async function loadVariantCosts(db: SqlRunner, variantId: string, country: string) {
  const r = await db.query(
    `select cost_type, amount::text, currency, destination_country from public.product_costs
      where product_variant_id = $1 and valid_to is null
        and (cost_type = 'production' or destination_country = $2 or destination_country is null)`,
    [variantId, country],
  );
  const pick = (type: string) =>
    r.rows.find((c) => c.cost_type === type && c.destination_country === country) ??
    r.rows.find((c) => c.cost_type === type && c.destination_country === null);
  const production = r.rows.find((c) => c.cost_type === 'production');
  const first = pick('shipping_first_item');
  const add = pick('shipping_additional_item');
  return {
    production: production
      ? { amount: production.amount as string, currency: production.currency as string }
      : null,
    shippingFirst: first
      ? {
          amount: first.amount as string,
          currency: first.currency as string,
          region: first.destination_country ?? 'REST_OF_THE_WORLD',
        }
      : null,
    shippingAdditional: add
      ? { amount: add.amount as string, currency: add.currency as string }
      : null,
  };
}
