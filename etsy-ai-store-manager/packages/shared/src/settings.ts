import { z } from 'zod';
import {
  compareDecimalStrings,
  currencyCode,
  moneyString,
  nonNegativeMoneyString,
  nonNegativeMoney4String,
  rateString,
} from './money.js';
import { STORE_LANGUAGE_CODES } from './languages.js';

export const userSettingsUpdateSchema = z
  .object({
    uiLanguage: z.enum(['tr', 'en']),
    baseCurrency: currencyCode,
    notifyEmail: z.boolean(),
    notifyPush: z.boolean(),
    notifyDailyReport: z.boolean(),
    requireReauthForSensitive: z.boolean(),
    fullName: z.string().trim().max(120).nullable(),
    timezone: z.string().trim().min(1).max(64),
  })
  .partial()
  .strict();
export type UserSettingsUpdate = z.infer<typeof userSettingsUpdateSchema>;

export const storeCreateSchema = z
  .object({
    name: z.string().trim().min(1).max(120),
    currency: currencyCode.default('USD'),
    defaultLanguage: z.enum(STORE_LANGUAGE_CODES).default('en'),
  })
  .strict();
export type StoreCreate = z.infer<typeof storeCreateSchema>;

export const SALES_STRATEGIES = ['growth', 'balanced', 'profit'] as const;
export const AUTOMATION_LEVELS = ['manual', 'controlled', 'autonomous_limited'] as const;

export const storeSettingsUpdateSchema = z
  .object({
    salesStrategy: z.enum(SALES_STRATEGIES),
    automationLevel: z.enum(AUTOMATION_LEVELS),
    defaultLanguage: z.enum(STORE_LANGUAGE_CODES),
    languages: z.array(z.enum(STORE_LANGUAGE_CODES)).min(1).max(STORE_LANGUAGE_CODES.length),
    targetMarkets: z.array(z.string().regex(/^[A-Z]{2}$/, 'ISO ülke kodu (ör. US)')).max(60),
    dailyAdBudgetCap: nonNegativeMoneyString,
    adBudgetCurrency: currencyCode,
    timezone: z.string().trim().min(1).max(64),
  })
  .partial()
  .strict()
  .superRefine((v, ctx) => {
    if (v.languages && new Set(v.languages).size !== v.languages.length) {
      ctx.addIssue({ code: 'custom', path: ['languages'], message: 'Diller tekrar edemez' });
    }
    if (v.defaultLanguage && v.languages && !v.languages.includes(v.defaultLanguage)) {
      ctx.addIssue({
        code: 'custom',
        path: ['defaultLanguage'],
        message: 'Varsayılan dil, dil listesinde olmalı',
      });
    }
  });
export type StoreSettingsUpdate = z.infer<typeof storeSettingsUpdateSchema>;

/** Contribution thresholds (USD by default). Order: excellent >= publish >= review >= min. */
export const profitRulesUpdateSchema = z
  .object({
    currency: currencyCode,
    targetContribution: nonNegativeMoneyString,
    excellentThreshold: moneyString,
    publishThreshold: moneyString,
    reviewThreshold: moneyString,
    minThreshold: moneyString,
    returnReserveRate: rateString,
    remakeReserveRate: rateString,
    otherVariableCostRate: rateString,
    otherVariableCostFixed: nonNegativeMoney4String,
    defaultAdCostPerOrder: nonNegativeMoney4String,
    taxRateOnProfit: rateString,
  })
  .partial()
  .strict();
export type ProfitRulesUpdate = z.infer<typeof profitRulesUpdateSchema>;

export interface ProfitThresholds {
  excellentThreshold: string;
  publishThreshold: string;
  reviewThreshold: string;
  minThreshold: string;
}

/** Validates the merged (current + patch) thresholds keep their required order. */
export function validateThresholdOrder(t: ProfitThresholds): string | null {
  if (compareDecimalStrings(t.excellentThreshold, t.publishThreshold) < 0)
    return '"Çok iyi" eşiği "Yayınlanabilir" eşiğinden küçük olamaz';
  if (compareDecimalStrings(t.publishThreshold, t.reviewThreshold) < 0)
    return '"Yayınlanabilir" eşiği "Onay bekler" eşiğinden küçük olamaz';
  if (compareDecimalStrings(t.reviewThreshold, t.minThreshold) < 0)
    return '"Onay bekler" eşiği alt sınırdan küçük olamaz';
  return null;
}

export const DEFAULT_PROFIT_THRESHOLDS: ProfitThresholds & { targetContribution: string } = {
  targetContribution: '10.00',
  excellentThreshold: '15.00',
  publishThreshold: '10.00',
  reviewThreshold: '7.00',
  minThreshold: '0.00',
};
