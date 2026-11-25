/**
 * Required Profit Engine scenarios (spec §23). Expected values are computed by hand
 * from the seeded Etsy fee rules:
 *   listing 0.20 USD per unit, transaction 6.5% of (items + shipping − discount),
 *   US processing 3% + 0.25 USD of (order total incl. tax), conversion 2.5%.
 */
import { describe, expect, it } from 'vitest';
import {
  calculateContribution,
  decide,
  ETSY_FEE_RULE_SEEDS,
  recommendPrice,
  selectRule,
  type FeeRule,
  type ProfitInput,
  type ProfitPolicy,
} from '@esm/profit-engine';

const RULES: FeeRule[] = ETSY_FEE_RULE_SEEDS.map((s) => ({ ...s, id: s.key, verified: true }));
const POLICY: ProfitPolicy = {
  thresholds: { excellent: '15', publish: '10', review: '7', min: '0' },
  targetContribution: '10',
  returnReserveRate: '0',
  remakeReserveRate: '0',
  otherVariableCostRate: '0',
  otherVariableCostFixed: '0',
  taxRateOnProfit: '0',
  vatOnFeesRate: '0',
  offsiteAdsTier: '15',
};
const FX = { USD: '1.0800', GBP: '0.8400', TRY: '37.0000', CAD: '1.5000', AUD: '1.6500' }; // per 1 EUR
const base: ProfitInput = {
  currency: 'USD',
  unitPrice: '29.99',
  quantity: 1,
  shippingCharged: '0',
  productionCostPerUnit: '10.85',
  productionCostCurrency: 'USD',
  fulfillmentShippingFirst: '4.75',
  fulfillmentShippingAdditional: '2.00',
  fulfillmentShippingCurrency: 'USD',
  sellerCountry: 'US',
  buyerCountry: 'US',
  payoutCurrency: 'USD',
  fxRates: FX,
};
const calc = (p: Partial<ProfitInput> = {}, pol: Partial<ProfitPolicy> = {}) =>
  calculateContribution({ ...base, ...p }, RULES, { ...POLICY, ...pol });
const line = (r: ReturnType<typeof calc>, code: string) =>
  r.breakdown.find((l) => l.code === code)?.amount;

describe('1. contribution ≥ 10 USD', () => {
  it('29.99 mug, US→US: fees 3.2991, contribution 11.0910 → publishable', () => {
    const r = calc();
    // listing 0.20 + transaction 1.94935 + processing (0.8997 + 0.25)
    expect(r.totalFees).toBe('3.2991');
    expect(line(r, 'fee_transaction')).toBe('-1.9494');
    expect(line(r, 'fee_payment_processing')).toBe('-1.1497');
    expect(r.contribution).toBe('11.0910'); // 29.99 − 3.29905 − 10.85 − 4.75
    expect(r.decision).toBe('publishable');
    expect(r.complete).toBe(true);
    expect(r.feesVerified).toBe(true);
  });
  it('≥ 15 is excellent', () => {
    expect(calc({ unitPrice: '36.00' }).decision).toBe('excellent');
  });
});

describe('2. contribution below 10 USD', () => {
  it('26.99 → 8.3760 needs approval', () => {
    // fees: 0.20 + 1.75435 + 0.8097 + 0.25 = 3.01405 ; 26.99 − 3.01405 − 15.60 = 8.37595
    const r = calc({ unitPrice: '26.99' });
    expect(r.contribution).toBe('8.3760');
    expect(r.decision).toBe('needs_approval');
  });
  it('22.00 → 3.8600 not recommended', () => {
    // fees: 0.20 + 1.43 + 0.66 + 0.25 = 2.54 ; 22 − 2.54 − 15.60 = 3.86
    const r = calc({ unitPrice: '22.00' });
    expect(r.contribution).toBe('3.8600');
    expect(r.decision).toBe('not_recommended');
  });
});

describe('3. negative contribution', () => {
  it('15.00 sells below cost → rejected', () => {
    // fees: 0.20 + 0.975 + 0.45 + 0.25 = 1.875 ; 15 − 1.875 − 15.60 = −2.475
    const r = calc({ unitPrice: '15.00' });
    expect(r.contribution).toBe('-2.4750');
    expect(r.decision).toBe('rejected');
  });
});

describe('4. ad cost increase', () => {
  it('allocated ad cost lowers contribution 1:1 and is reported separately (no double counting)', () => {
    const noAds = calc();
    const ads = calc({ adCostAllocated: '3.50' });
    expect(ads.contributionBeforeAds).toBe(noAds.contribution);
    expect(ads.adCostAllocated).toBe('3.5000');
    expect(ads.contribution).toBe('7.5910');
    expect(ads.decision).toBe('needs_approval');
    expect(ads.breakdown.filter((l) => l.group === 'ads')).toHaveLength(1);
  });
  it('Offsite Ads fee 15% of order total, capped at 100 USD', () => {
    const r = calc({ offsiteAds: true });
    expect(line(r, 'fee_offsite_ads')).toBe('-4.4985');
    const big = calc({ offsiteAds: true, unitPrice: '900.00' });
    expect(line(big, 'fee_offsite_ads')).toBe('-100.0000');
    const tier12 = calc({ offsiteAds: true }, { offsiteAdsTier: '12' });
    expect(line(tier12, 'fee_offsite_ads')).toBe('-3.5988');
  });
});

describe('5. Printify production cost change', () => {
  it('+1.20 production cost reduces contribution by exactly 1.20', () => {
    const r = calc({ productionCostPerUnit: '12.05' });
    expect(r.contribution).toBe('9.8910');
    expect(r.decision).toBe('needs_approval');
  });
  it('production cost in another currency is converted with the FX table', () => {
    // 10.00 EUR → 10.80 USD
    const r = calc({ productionCostPerUnit: '10.00', productionCostCurrency: 'EUR' });
    expect(line(r, 'production')).toBe('-10.8000');
  });
});

describe('6. shipping cost change', () => {
  it('fulfilment shipping first + additional items for quantity 3', () => {
    // 3 × 29.99 = 89.97 ; fees 0.60 + 5.84805 + 2.6991 + 0.25 = 9.39715 ;
    // production 32.55 ; shipping 4.75 + 2 × 2.00 = 8.75 → 89.97 − 9.39715 − 32.55 − 8.75 = 39.27285
    const r = calc({ quantity: 3 });
    expect(line(r, 'fulfilment_shipping')).toBe('-8.7500');
    expect(line(r, 'fee_listing')).toBe('-0.6000');
    expect(r.contribution).toBe('39.2729');
  });
  it('shipping charged to the buyer is part of the transaction & processing base', () => {
    // items 29.99 + shipping 5.00 = 34.99 → transaction 2.27435, processing 1.0497 + 0.25
    const r = calc({ shippingCharged: '5.00' });
    expect(line(r, 'fee_transaction')).toBe('-2.2744');
    expect(r.contribution).toBe('15.6160'); // 34.99 − (0.20 + 2.27435 + 1.2997) − 15.60 = 15.61595
  });
});

describe('7. discount', () => {
  it('a 20% coupon (6.00) reduces revenue and the fee bases', () => {
    // net 23.99 ; fees 0.20 + 1.55935 + 0.7197 + 0.25 = 2.72905 ; 23.99 − 2.72905 − 15.60 = 5.66095
    const r = calc({ discount: '6.00' });
    expect(r.netRevenue).toBe('23.9900');
    expect(r.contribution).toBe('5.6610');
    expect(r.decision).toBe('not_recommended');
  });
});

describe('8. refund reserve', () => {
  it('5% return reserve on net revenue + 2% remake reserve on production cost', () => {
    // 29.99 × 0.05 = 1.4995 ; 10.85 × 0.02 = 0.217 ; 11.09095 − 1.4995 − 0.217 = 9.37445
    const r = calc({}, { returnReserveRate: '0.05', remakeReserveRate: '0.02' });
    expect(line(r, 'return_reserve')).toBe('-1.4995');
    expect(line(r, 'remake_reserve')).toBe('-0.2170');
    expect(r.contribution).toBe('9.3745');
  });
});

describe('9. different currencies', () => {
  it('TR seller (TRY payout), EUR listing, German buyer: processing 6.5% + 14 TRY, conversion 2.5%, regulatory 1.67%', () => {
    const r = calc({
      currency: 'EUR',
      unitPrice: '30.00',
      sellerCountry: 'TR',
      buyerCountry: 'DE',
      payoutCurrency: 'TRY',
      productionCostPerUnit: '10.85',
      fulfillmentShippingFirst: '10.99',
    });
    // processing: 30 × 0.065 = 1.95 + 14 TRY (14/37 = 0.378378 EUR)
    expect(line(r, 'fee_payment_processing')).toBe('-2.3284');
    // listing 0.20 USD = 0.185185 EUR
    expect(line(r, 'fee_listing')).toBe('-0.1852');
    expect(line(r, 'fee_currency_conversion')).toBe('-0.7500');
    expect(line(r, 'fee_regulatory_operating')).toBe('-0.5010');
    // production 10.85 USD = 10.046296 EUR ; shipping 10.99 USD = 10.175926 EUR
    expect(line(r, 'production')).toBe('-10.0463');
    expect(r.currency).toBe('EUR');
    expect(r.complete).toBe(true);
  });
  it('missing FX rate makes the result incomplete instead of guessing', () => {
    const r = calc({ currency: 'JPY', unitPrice: '4000' });
    expect(r.complete).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/Döviz kuru yok/);
  });
  it('Canada: domestic vs international processing rates', () => {
    const dom = calc({
      currency: 'CAD',
      unitPrice: '40.00',
      sellerCountry: 'CA',
      buyerCountry: 'CA',
      payoutCurrency: 'CAD',
    });
    const intl = calc({
      currency: 'CAD',
      unitPrice: '40.00',
      sellerCountry: 'CA',
      buyerCountry: 'US',
      payoutCurrency: 'CAD',
    });
    expect(line(dom, 'fee_payment_processing')).toBe('-1.4500'); // 3% + 0.25
    expect(line(intl, 'fee_payment_processing')).toBe('-1.8500'); // 4% + 0.25
  });
});

describe('10. different fee bases ("matrah")', () => {
  it('sales tax is in the processing base but not in revenue or the transaction base', () => {
    const r = calc({ salesTax: '2.40' });
    expect(line(r, 'fee_transaction')).toBe('-1.9494'); // unchanged
    expect(line(r, 'fee_payment_processing')).toBe('-1.2217'); // (29.99 + 2.40) × 3% + 0.25
    expect(r.netRevenue).toBe('29.9900');
    expect(r.contribution).toBe('11.0190');
  });
  it('regulatory fee is charged on items + shipping for the seller country', () => {
    const r = calc({
      currency: 'GBP',
      unitPrice: '25.00',
      shippingCharged: '3.00',
      sellerCountry: 'GB',
      buyerCountry: 'GB',
      payoutCurrency: 'GBP',
    });
    expect(line(r, 'fee_regulatory_operating')).toBe('-0.1344'); // 28 × 0.48%
    expect(line(r, 'fee_payment_processing')).toBe('-1.3200'); // 28 × 4% + 0.20 GBP
  });
  it('VAT on Etsy fees when configured', () => {
    const r = calc({}, { vatOnFeesRate: '0.20' });
    expect(line(r, 'fee_vat')).toBe('-0.6598'); // 3.29905 × 20%
  });
});

describe('policy & rules', () => {
  it('thresholds are inclusive and configurable', () => {
    const t = { excellent: '15', publish: '10', review: '7', min: '0' };
    expect([
      decide('15', t),
      decide('14.9999', t),
      decide('10', t),
      decide('9.99', t),
      decide('7', t),
      decide('6.99', t),
      decide('0', t),
      decide('-0.01', t),
    ]).toEqual([
      'excellent',
      'publishable',
      'publishable',
      'needs_approval',
      'needs_approval',
      'not_recommended',
      'not_recommended',
      'rejected',
    ]);
    expect(decide('11', { excellent: '20', publish: '12', review: '9', min: '1' })).toBe(
      'needs_approval',
    );
  });
  it('after-tax contribution is separate from pre-tax contribution', () => {
    const r = calc({}, { taxRateOnProfit: '0.25' });
    expect(r.contribution).toBe('11.0910');
    expect(r.contributionAfterTax).toBe('8.3182');
  });
  it('unverified rules are used but flagged', () => {
    const r = calculateContribution(
      base,
      RULES.map((x) => ({ ...x, verified: false })),
      POLICY,
    );
    expect(r.feesVerified).toBe(false);
    expect(r.warnings.some((w) => w.includes('doğrulanmamış'))).toBe(true);
  });
  it('missing processing rule for the seller country marks the result incomplete', () => {
    const r = calc({ sellerCountry: 'BR', buyerCountry: 'BR' });
    expect(r.complete).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/Ödeme işleme ücreti: BR/);
  });
  it('store-specific rules override global ones', () => {
    const custom: FeeRule = {
      ...RULES.find((r) => r.id === 'transaction')!,
      id: 'custom',
      rate: '0.05',
      storeSpecific: true,
    };
    expect(
      selectRule([...RULES, custom], 'transaction', { sellerCountry: 'US', buyerCountry: 'US' })
        ?.id,
    ).toBe('custom');
  });
  it('keeps a full breakdown with rule ids for auditing', () => {
    const r = calc();
    expect(r.feeRuleIds.sort()).toEqual(['listing', 'processing:US:any', 'transaction']);
    expect(r.breakdown.every((l) => /^-?\d+\.\d{4}$/.test(l.amount))).toBe(true);
  });
});

describe('price recommendation', () => {
  it('finds the minimum price reaching the 10 USD target and a .99 price', () => {
    const rec = recommendPrice(base, RULES, POLICY);
    // contribution(p) = p − 0.20 − 0.065p − 0.03p − 0.25 − 15.60 = 0.905p − 16.05 ≥ 10 → p ≥ 28.7845
    expect(rec.minimumUnitPrice).toBe('28.79');
    expect(rec.suggestedUnitPrice).toBe('28.99');
    expect(rec.decision).toBe('publishable');
    expect(Number(calc({ unitPrice: '28.78' }).contribution)).toBeLessThan(10);
  });
  it('reports when the target is unreachable', () => {
    const rec = recommendPrice({ ...base, productionCostPerUnit: '20000' }, RULES, POLICY);
    expect(rec.minimumUnitPrice).toBeNull();
  });
});

describe('8b. actual refund', () => {
  it('partial refund reduces revenue and credits the processing fee proportionally', () => {
    // processing 1.1497 ; refund 10 of 29.99 → credit 1.1497 × 10/29.99 = 0.383361...
    const r = calc({ refundedAmount: '10.00' });
    expect(line(r, 'refund')).toBe('-10.0000');
    expect(line(r, 'fee_processing_refund_credit')).toBe('0.3834');
    expect(r.netRevenue).toBe('19.9900');
    // 11.09095 − 10 + 0.383361 = 1.474311
    expect(r.contribution).toBe('1.4743');
    expect(r.warnings.join(' ')).toMatch(/işlem ücretinin iade/);
  });
});
