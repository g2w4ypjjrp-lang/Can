import { describe, expect, it } from 'vitest';
import {
  DEFAULT_PROFIT_THRESHOLDS,
  NAV_ITEMS,
  profitRulesUpdateSchema,
  storeCreateSchema,
  storeSettingsUpdateSchema,
  userSettingsUpdateSchema,
  validateThresholdOrder,
} from '@esm/shared';

describe('profit threshold policy', () => {
  it('defaults match the business policy (15 / 10 / 7 / 0, target 10 USD)', () => {
    expect(DEFAULT_PROFIT_THRESHOLDS).toEqual({
      targetContribution: '10.00',
      excellentThreshold: '15.00',
      publishThreshold: '10.00',
      reviewThreshold: '7.00',
      minThreshold: '0.00',
    });
    expect(validateThresholdOrder(DEFAULT_PROFIT_THRESHOLDS)).toBeNull();
  });

  it('rejects inverted thresholds', () => {
    expect(
      validateThresholdOrder({ ...DEFAULT_PROFIT_THRESHOLDS, publishThreshold: '16' }),
    ).toMatch(/Çok iyi/);
    expect(validateThresholdOrder({ ...DEFAULT_PROFIT_THRESHOLDS, reviewThreshold: '11' })).toMatch(
      /Yayınlanabilir/,
    );
    expect(validateThresholdOrder({ ...DEFAULT_PROFIT_THRESHOLDS, minThreshold: '8' })).toMatch(
      /alt sınır/,
    );
  });

  it('allows the user to change thresholds (e.g. target 12)', () => {
    const r = profitRulesUpdateSchema.safeParse({
      targetContribution: '12.00',
      publishThreshold: '12',
    });
    expect(r.success).toBe(true);
  });

  it('accepts values exactly as the database returns them (numeric(12,4) -> "0.0000")', () => {
    const r = profitRulesUpdateSchema.safeParse({
      otherVariableCostFixed: '0.0000',
      defaultAdCostPerOrder: '1.2500',
      returnReserveRate: '0.0000',
      targetContribution: '10.00',
    });
    expect(r.success).toBe(true);
    expect(profitRulesUpdateSchema.safeParse({ defaultAdCostPerOrder: '1.23456' }).success).toBe(
      false,
    );
  });

  it('rejects unknown fields (strict) and invalid money', () => {
    expect(profitRulesUpdateSchema.safeParse({ hack: 1 }).success).toBe(false);
    expect(profitRulesUpdateSchema.safeParse({ publishThreshold: 10 }).success).toBe(false);
    expect(profitRulesUpdateSchema.safeParse({ returnReserveRate: '2' }).success).toBe(false);
  });
});

describe('store settings validation', () => {
  it('requires the default language to be part of the languages list', () => {
    const r = storeSettingsUpdateSchema.safeParse({
      languages: ['en', 'de'],
      defaultLanguage: 'fr',
    });
    expect(r.success).toBe(false);
  });
  it('rejects duplicate / unsupported languages and negative ad budget', () => {
    expect(storeSettingsUpdateSchema.safeParse({ languages: ['en', 'en'] }).success).toBe(false);
    expect(storeSettingsUpdateSchema.safeParse({ languages: ['xx'] }).success).toBe(false);
    expect(storeSettingsUpdateSchema.safeParse({ dailyAdBudgetCap: '-5' }).success).toBe(false);
  });
  it('accepts a valid multilingual configuration', () => {
    const r = storeSettingsUpdateSchema.safeParse({
      languages: ['en', 'de', 'fr'],
      defaultLanguage: 'en',
      targetMarkets: ['US', 'DE'],
      dailyAdBudgetCap: '25.00',
    });
    expect(r.success).toBe(true);
  });
});

describe('store & user schemas', () => {
  it('applies store defaults (USD, English)', () => {
    expect(storeCreateSchema.parse({ name: 'My Shop' })).toEqual({
      name: 'My Shop',
      currency: 'USD',
      defaultLanguage: 'en',
    });
  });
  it('rejects empty names and unknown user settings fields', () => {
    expect(storeCreateSchema.safeParse({ name: '  ' }).success).toBe(false);
    expect(userSettingsUpdateSchema.safeParse({ isAdmin: true }).success).toBe(false);
  });
});

describe('navigation', () => {
  it('has the 17 required menu items in order', () => {
    expect(NAV_ITEMS.map((n) => n.label)).toEqual([
      'Genel Bakış',
      'AI Store Manager',
      'Pazar Araştırma',
      'Ürün Fırsatları',
      'Tasarım Stüdyosu',
      'Ürünler',
      'Etsy Mağazam',
      'Printify',
      'Reklam Yönetimi',
      'Siparişler',
      'Müşteriler',
      'SEO Merkezi',
      'Finans ve Kâr',
      'Otomasyon',
      'Bildirimler',
      'Raporlar',
      'Ayarlar',
    ]);
    expect(new Set(NAV_ITEMS.map((n) => n.href)).size).toBe(17);
  });
});
