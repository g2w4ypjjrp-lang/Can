import { Decimal } from 'decimal.js';

/**
 * Profit Engine — computes the real per-order contribution of a sale.
 *
 *   Net contribution = Net sales revenue − Total variable costs
 *
 * All money uses Decimal (28 significant digits, ROUND_HALF_UP only when a value
 * is presented). Every line is returned in `breakdown` so the result can be stored
 * and audited. Fee percentages are NOT hard-coded here: they come from `FeeRule`s
 * (database table fee_rules) that carry their source and verification state.
 */
const D = Decimal.clone({ precision: 28, rounding: Decimal.ROUND_HALF_UP });
type Dec = InstanceType<typeof D>;

export const ENGINE_VERSION = 'profit-engine/1.0.0';

export type FeeType =
  | 'listing'
  | 'transaction'
  | 'payment_processing'
  | 'currency_conversion'
  | 'offsite_ads'
  | 'regulatory_operating';

export type FeeBasis =
  | 'item_price'
  | 'item_plus_shipping'
  | 'order_total'
  | 'order_total_incl_tax'
  | 'per_listing'
  | 'per_order'
  | 'converted_amount';

export interface FeeRule {
  id: string;
  platform: string;
  feeType: FeeType;
  rate: string | null;
  fixedAmount: string | null;
  fixedCurrency: string | null;
  basis: FeeBasis;
  /** ISO country the rule is bound to (bank/seller country). null = any */
  country: string | null;
  /** domestic = buyer in seller country, international = otherwise */
  buyerScope: 'any' | 'domestic' | 'international';
  capAmount?: string | null;
  capCurrency?: string | null;
  /** e.g. offsite ads tier '15' | '12' */
  tier?: string | null;
  verified: boolean;
  sourceUrl: string;
  storeSpecific?: boolean;
}

export interface Thresholds {
  excellent: string;
  publish: string;
  review: string;
  min: string;
}

export interface ProfitPolicy {
  thresholds: Thresholds;
  targetContribution: string;
  returnReserveRate: string;
  remakeReserveRate: string;
  otherVariableCostRate: string;
  otherVariableCostFixed: string;
  /** income-tax style estimate applied to positive contribution (after-tax view only) */
  taxRateOnProfit: string;
  /** VAT charged by Etsy on its fees (seller-country dependent; user-configured) */
  vatOnFeesRate: string;
  offsiteAdsTier: '15' | '12';
}

export interface ProfitInput {
  /** listing / order currency */
  currency: string;
  unitPrice: string;
  quantity: number;
  shippingCharged: string;
  giftWrap?: string;
  /** seller-funded discount for the whole order (coupon / sale) */
  discount?: string;
  /** sales tax / VAT collected from the buyer (pass-through, never revenue) */
  salesTax?: string;
  productionCostPerUnit: string;
  productionCostCurrency: string;
  fulfillmentShippingFirst: string;
  fulfillmentShippingAdditional: string;
  fulfillmentShippingCurrency: string;
  /** Etsy payment account (bank) country of the seller */
  sellerCountry: string;
  buyerCountry: string;
  payoutCurrency: string;
  /** order attributed to Etsy Offsite Ads */
  offsiteAds?: boolean;
  /** allocated share of ad spend for this order, in `currency` (allocation, not a ledger expense) */
  adCostAllocated?: string;
  /** amount refunded to the buyer (actual orders). Etsy credits the processing fee proportionally. */
  refundedAmount?: string;
  /** units of currency per 1 EUR (ECB reference format); EUR implied 1 */
  fxRates: Record<string, string>;
}

export interface BreakdownLine {
  code: string;
  label: string;
  group: 'revenue' | 'fee' | 'cost' | 'ads' | 'reserve' | 'tax';
  amount: string;
  base?: string;
  rate?: string;
  fixed?: string;
  ruleId?: string;
  note?: string;
}

export type Decision =
  'excellent' | 'publishable' | 'needs_approval' | 'not_recommended' | 'rejected';

export interface ProfitResult {
  engineVersion: string;
  currency: string;
  grossRevenue: string;
  netRevenue: string;
  totalFees: string;
  totalVariableCosts: string;
  contributionBeforeAds: string;
  adCostAllocated: string;
  contribution: string;
  contributionAfterTax: string;
  contributionMargin: string | null;
  decision: Decision;
  complete: boolean;
  feesVerified: boolean;
  warnings: string[];
  breakdown: BreakdownLine[];
  feeRuleIds: string[];
}

export class FxError extends Error {}

export function convert(amount: Dec, from: string, to: string, rates: Record<string, string>): Dec {
  if (from === to) return amount;
  const r = (c: string) =>
    c === 'EUR' ? new D(1) : rates[c] !== undefined ? new D(rates[c]!) : null;
  const rf = r(from);
  const rt = r(to);
  if (!rf || !rt || rf.lte(0) || rt.lte(0)) throw new FxError(`Döviz kuru yok: ${from}->${to}`);
  return amount.div(rf).mul(rt);
}

export function decide(contribution: Dec | string, t: Thresholds): Decision {
  const c = new D(contribution);
  if (c.gte(t.excellent)) return 'excellent';
  if (c.gte(t.publish)) return 'publishable';
  if (c.gte(t.review)) return 'needs_approval';
  if (c.gte(t.min) && !c.isNegative()) return 'not_recommended';
  return 'rejected';
}

const money = (d: Dec) => d.toDecimalPlaces(4, Decimal.ROUND_HALF_UP).toFixed(4);

/** Picks the applicable rule: store-specific before global, verified before unverified. */
export function selectRule(
  rules: FeeRule[],
  feeType: FeeType,
  ctx: { sellerCountry: string; buyerCountry: string; tier?: string },
): FeeRule | null {
  const domestic = ctx.sellerCountry === ctx.buyerCountry;
  const candidates = rules.filter(
    (r) =>
      r.platform === 'etsy' &&
      r.feeType === feeType &&
      (r.country === null || r.country === ctx.sellerCountry) &&
      (r.buyerScope === 'any' || (r.buyerScope === 'domestic') === domestic) &&
      (ctx.tier === undefined || r.tier == null || r.tier === ctx.tier),
  );
  candidates.sort(
    (a, b) =>
      Number(Boolean(b.storeSpecific)) - Number(Boolean(a.storeSpecific)) ||
      Number(b.country !== null) - Number(a.country !== null) ||
      Number(b.buyerScope !== 'any') - Number(a.buyerScope !== 'any') ||
      Number(b.verified) - Number(a.verified),
  );
  return candidates[0] ?? null;
}

export function calculateContribution(
  input: ProfitInput,
  rules: FeeRule[],
  policy: ProfitPolicy,
): ProfitResult {
  const cur = input.currency;
  const warnings: string[] = [];
  const breakdown: BreakdownLine[] = [];
  const usedRules: FeeRule[] = [];
  let complete = true;
  if (!Number.isInteger(input.quantity) || input.quantity < 1)
    throw new Error('quantity must be a positive integer');
  const qty = new D(input.quantity);
  const fx = (v: string | Dec, from: string) => {
    try {
      return convert(new D(v), from, cur, input.fxRates);
    } catch (e) {
      complete = false;
      warnings.push((e as Error).message);
      return new D(0);
    }
  };

  // ---------------- revenue ----------------
  const items = new D(input.unitPrice).mul(qty);
  const shipping = new D(input.shippingCharged || 0);
  const giftWrap = new D(input.giftWrap || 0);
  const discount = new D(input.discount || 0);
  const salesTax = new D(input.salesTax || 0);
  const gross = items.plus(shipping).plus(giftWrap);
  const netSale = D.max(gross.minus(discount), 0);
  breakdown.push({
    code: 'items',
    label: 'Ürün satış tutarı',
    group: 'revenue',
    amount: money(items),
  });
  if (!shipping.isZero())
    breakdown.push({
      code: 'shipping_charged',
      label: 'Alıcıdan alınan kargo',
      group: 'revenue',
      amount: money(shipping),
    });
  if (!giftWrap.isZero())
    breakdown.push({
      code: 'gift_wrap',
      label: 'Hediye paketi',
      group: 'revenue',
      amount: money(giftWrap),
    });
  if (!discount.isZero())
    breakdown.push({
      code: 'discount',
      label: 'İndirim (satıcı karşılar)',
      group: 'revenue',
      amount: money(discount.neg()),
    });
  if (!salesTax.isZero()) {
    breakdown.push({
      code: 'sales_tax',
      label: 'Alıcıdan alınan vergi (gelir değil, aktarılır)',
      group: 'tax',
      amount: money(new D(0)),
      base: money(salesTax),
      note: 'Ödeme işleme ücretinin matrahına dahildir',
    });
  }

  // ---------------- fee bases ("matrah") ----------------
  const bases: Record<FeeBasis, Dec> = {
    item_price: items.minus(D.min(discount, items)),
    item_plus_shipping: netSale,
    order_total: netSale,
    order_total_incl_tax: netSale.plus(salesTax),
    per_listing: qty,
    per_order: new D(1),
    converted_amount: netSale,
  };
  const ctx = { sellerCountry: input.sellerCountry, buyerCountry: input.buyerCountry };

  const applyRule = (feeType: FeeType, label: string, required: boolean, tier?: string): Dec => {
    const rule = selectRule(rules, feeType, tier ? { ...ctx, tier } : ctx);
    if (!rule) {
      if (required) {
        complete = false;
        warnings.push(`${label}: ${input.sellerCountry} için ücret kuralı tanımlı değil`);
      }
      return new D(0);
    }
    usedRules.push(rule);
    if (!rule.verified) warnings.push(`${label}: oran doğrulanmamış kaynaktan (${rule.sourceUrl})`);
    const base = bases[rule.basis];
    let amount = new D(0);
    if (rule.rate) amount = amount.plus(base.mul(rule.rate));
    if (rule.fixedAmount) {
      const fixed = fx(rule.fixedAmount, rule.fixedCurrency ?? 'USD');
      amount = amount.plus(rule.basis === 'per_listing' ? fixed.mul(qty) : fixed);
    }
    if (rule.capAmount) {
      const cap = fx(rule.capAmount, rule.capCurrency ?? 'USD');
      if (amount.gt(cap)) amount = cap;
    }
    breakdown.push({
      code: `fee_${feeType}`,
      label,
      group: 'fee',
      amount: money(amount.neg()),
      base: rule.basis === 'per_listing' || rule.basis === 'per_order' ? undefined : money(base),
      rate: rule.rate ?? undefined,
      fixed: rule.fixedAmount
        ? `${rule.fixedAmount} ${rule.fixedCurrency ?? ''}`.trim()
        : undefined,
      ruleId: rule.id,
      note: rule.capAmount
        ? `Sipariş başı üst sınır ${rule.capAmount} ${rule.capCurrency ?? ''}`
        : undefined,
    });
    return amount;
  };

  let fees = new D(0);
  fees = fees.plus(applyRule('listing', 'Etsy listeleme/yenileme ücreti', true));
  fees = fees.plus(applyRule('transaction', 'Etsy işlem ücreti', true));
  fees = fees.plus(applyRule('payment_processing', 'Ödeme işleme ücreti', true));
  fees = fees.plus(applyRule('regulatory_operating', 'Düzenleyici işletim ücreti', false));
  if (input.offsiteAds)
    fees = fees.plus(applyRule('offsite_ads', 'Offsite Ads ücreti', true, policy.offsiteAdsTier));
  if (input.payoutCurrency !== cur)
    fees = fees.plus(applyRule('currency_conversion', 'Döviz çevirme ücreti', true));
  const vatRate = new D(policy.vatOnFeesRate || 0);
  if (vatRate.gt(0)) {
    const vat = fees.mul(vatRate);
    breakdown.push({
      code: 'fee_vat',
      label: 'Etsy ücretleri üzerindeki KDV',
      group: 'fee',
      amount: money(vat.neg()),
      base: money(fees),
      rate: vatRate.toString(),
    });
    fees = fees.plus(vat);
  }

  // ---------------- refunds (actual orders) ----------------
  const refunded = D.min(new D(input.refundedAmount || 0), netSale.plus(salesTax));
  if (refunded.gt(0)) {
    breakdown.push({
      code: 'refund',
      label: 'İade edilen tutar',
      group: 'revenue',
      amount: money(refunded.neg()),
    });
    const proc = breakdown.find((l) => l.code === 'fee_payment_processing');
    const totalBase = netSale.plus(salesTax);
    if (proc && totalBase.gt(0)) {
      // Help Center: processing fee "credited proportionally and applied to the refund amount"
      const credit = new D(proc.amount).neg().mul(refunded.div(totalBase));
      breakdown.push({
        code: 'fee_processing_refund_credit',
        label: 'İadede geri alınan ödeme işleme ücreti',
        group: 'fee',
        amount: money(credit),
      });
      fees = fees.minus(credit);
    }
    warnings.push(
      'İadede işlem ücretinin iade edilip edilmediği doğrulanmadı; iade edilmediği varsayıldı',
    );
  }

  // ---------------- product & fulfilment costs ----------------
  const production = fx(input.productionCostPerUnit, input.productionCostCurrency).mul(qty);
  const shipFirst = fx(input.fulfillmentShippingFirst, input.fulfillmentShippingCurrency);
  const shipAdd = fx(input.fulfillmentShippingAdditional, input.fulfillmentShippingCurrency).mul(
    qty.minus(1),
  );
  const fulfilShipping = shipFirst.plus(shipAdd);
  breakdown.push({
    code: 'production',
    label: 'Üretim maliyeti (Printify)',
    group: 'cost',
    amount: money(production.neg()),
  });
  breakdown.push({
    code: 'fulfilment_shipping',
    label: 'Üretici kargo maliyeti',
    group: 'cost',
    amount: money(fulfilShipping.neg()),
  });

  // ---------------- reserves & other variable costs ----------------
  const returnReserve = netSale.mul(policy.returnReserveRate || 0);
  const remakeReserve = production.mul(policy.remakeReserveRate || 0);
  const otherVar = netSale
    .mul(policy.otherVariableCostRate || 0)
    .plus(policy.otherVariableCostFixed || 0);
  if (!returnReserve.isZero())
    breakdown.push({
      code: 'return_reserve',
      label: 'İade rezervi',
      group: 'reserve',
      amount: money(returnReserve.neg()),
      base: money(netSale),
      rate: policy.returnReserveRate,
    });
  if (!remakeReserve.isZero())
    breakdown.push({
      code: 'remake_reserve',
      label: 'Yeniden üretim rezervi',
      group: 'reserve',
      amount: money(remakeReserve.neg()),
      base: money(production),
      rate: policy.remakeReserveRate,
    });
  if (!otherVar.isZero())
    breakdown.push({
      code: 'other_variable',
      label: 'Diğer değişken giderler',
      group: 'cost',
      amount: money(otherVar.neg()),
    });

  const costsBeforeAds = fees
    .plus(production)
    .plus(fulfilShipping)
    .plus(returnReserve)
    .plus(remakeReserve)
    .plus(otherVar);
  const revenueAfterRefunds = netSale.minus(refunded);
  const contributionBeforeAds = revenueAfterRefunds.minus(costsBeforeAds);

  // ---------------- ads (allocation only) ----------------
  const ads = new D(input.adCostAllocated || 0);
  if (!ads.isZero()) {
    breakdown.push({
      code: 'ads_allocated',
      label: 'Reklam payı (dağıtım; muhasebe gideri değil)',
      group: 'ads',
      amount: money(ads.neg()),
      note: 'Gerçek reklam harcaması ad_spend kayıtlarında bir kez yer alır',
    });
  }
  const totalVariable = costsBeforeAds.plus(ads);
  const contribution = revenueAfterRefunds.minus(totalVariable);
  const taxRate = new D(policy.taxRateOnProfit || 0);
  const afterTax = contribution.gt(0)
    ? contribution.minus(contribution.mul(taxRate))
    : contribution;

  return {
    engineVersion: ENGINE_VERSION,
    currency: cur,
    grossRevenue: money(gross),
    netRevenue: money(revenueAfterRefunds),
    totalFees: money(fees),
    totalVariableCosts: money(totalVariable),
    contributionBeforeAds: money(contributionBeforeAds),
    adCostAllocated: money(ads),
    contribution: money(contribution),
    contributionAfterTax: money(afterTax),
    contributionMargin: revenueAfterRefunds.isZero()
      ? null
      : contribution.div(revenueAfterRefunds).toDecimalPlaces(6).toFixed(6),
    decision: decide(contribution, policy.thresholds),
    complete,
    feesVerified: usedRules.every((r) => r.verified),
    warnings: [...new Set(warnings)],
    breakdown,
    feeRuleIds: [...new Set(usedRules.map((r) => r.id))],
  };
}

export interface PriceRecommendation {
  minimumUnitPrice: string | null;
  suggestedUnitPrice: string | null;
  expectedContribution: string | null;
  decision: Decision | null;
  note: string;
}

/**
 * Smallest unit price (in cents steps) whose contribution reaches `target`,
 * plus a "charm" price ending in .99 at or above it. Contribution grows
 * monotonically with price (every fee rate < 100%), so binary search is exact.
 */
export function recommendPrice(
  input: ProfitInput,
  rules: FeeRule[],
  policy: ProfitPolicy,
  target: string = policy.targetContribution,
  maxUnitPrice = '10000',
): PriceRecommendation {
  const at = (cents: number) =>
    calculateContribution({ ...input, unitPrice: new D(cents).div(100).toFixed(2) }, rules, policy);
  let lo = 1;
  let hi = new D(maxUnitPrice).mul(100).toNumber();
  if (new D(at(hi).contribution).lt(target)) {
    return {
      minimumUnitPrice: null,
      suggestedUnitPrice: null,
      expectedContribution: null,
      decision: null,
      note: `Hedef katkıya ${maxUnitPrice} ${input.currency} altında ulaşılamıyor`,
    };
  }
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (new D(at(mid).contribution).gte(target)) hi = mid;
    else lo = mid + 1;
  }
  const min = lo;
  const charm =
    Math.floor(min / 100) * 100 + 99 >= min
      ? Math.floor(min / 100) * 100 + 99
      : Math.floor(min / 100) * 100 + 199;
  const r = at(charm);
  return {
    minimumUnitPrice: new D(min).div(100).toFixed(2),
    suggestedUnitPrice: new D(charm).div(100).toFixed(2),
    expectedContribution: r.contribution,
    decision: r.decision,
    note: `Hedef ${target} ${input.currency} katkı için en düşük fiyat; önerilen fiyat .99 ile biter`,
  };
}
