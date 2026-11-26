import { describe, expect, it } from 'vitest';
import {
  allocateBudget,
  assessCampaign,
  computeEconomics,
  computeKpis,
  type CampaignStats,
} from '@esm/profit-engine';
import { metaPurchases } from '@esm/integrations';
import { ledgerAmount } from '../../../apps/worker/src/ads/sync.js';

const econ = computeEconomics({
  revenue: '300',
  contributionBeforeAds: '150',
  orders: 10,
  targetContribution: '10',
});
const camp = (name: string, o: Partial<CampaignStats>): CampaignStats => ({
  campaignId: name,
  name,
  platform: 'meta_ads',
  status: 'active',
  dailyBudget: null,
  impressions: 10_000,
  clicks: 200,
  spend: '100',
  conversions: '0',
  conversionValue: '0',
  attributionConfidence: 'medium',
  ...o,
});

describe('ad economics', () => {
  it('derives break-even and target ROAS from contribution before ads', () => {
    expect(econ).toMatchObject({
      aov: '30.00',
      contributionBeforeAds: '15.00',
      breakEvenRoas: '2',
      targetRoas: '6',
      maxCpa: '5.00',
    });
  });
  it('has no target ROAS when the contribution cannot reach the target', () => {
    const e = computeEconomics({
      revenue: '300',
      contributionBeforeAds: '80',
      orders: 10,
      targetContribution: '10',
    });
    expect(e.targetRoas).toBeNull();
    expect(e.maxCpa).toBe('0.00');
    expect(
      computeEconomics({
        revenue: '0',
        contributionBeforeAds: '0',
        orders: 0,
        targetContribution: '10',
      }).breakEvenRoas,
    ).toBeNull();
  });
  it('computes KPIs without dividing by zero', () => {
    expect(
      computeKpis({
        impressions: 1000,
        clicks: 50,
        spend: '25',
        conversions: '2',
        conversionValue: '100',
      }),
    ).toEqual({
      ctr: '0.05',
      cpc: '0.50',
      cvr: '0.04',
      cpa: '12.50',
      roas: '4',
      acos: '0.25',
    });
    expect(
      computeKpis({
        impressions: 0,
        clicks: 0,
        spend: '0',
        conversions: '0',
        conversionValue: '0',
      }),
    ).toEqual({
      ctr: null,
      cpc: null,
      cvr: null,
      cpa: null,
      roas: null,
      acos: null,
    });
  });
});

describe('campaign verdicts', () => {
  it('waits for enough data and flags low attribution confidence', () => {
    expect(assessCampaign(camp('a', { clicks: 20, spend: '5' }), econ, 100).verdict).toBe(
      'insufficient_data',
    );
    // enough spend (3 × max CPA) counts as enough data even with few clicks
    expect(assessCampaign(camp('b', { clicks: 20, spend: '15' }), econ, 100).verdict).toBe(
      'unprofitable',
    );
    expect(
      assessCampaign(camp('c', { conversionValue: '150', attributionConfidence: 'low' }), econ, 100)
        .reason,
    ).toContain('Atıf güveni düşük');
  });
  it('maps ROAS to verdicts around break-even and target', () => {
    const v = (value: string) =>
      assessCampaign(camp(value, { conversionValue: value }), econ, 100).verdict;
    expect(v('150')).toBe('unprofitable'); // 1.5 < 2
    expect(v('400')).toBe('below_target'); // 4
    expect(v('650')).toBe('on_target'); // 6.5
    expect(v('800')).toBe('scale'); // 8 ≥ 7.8
  });
  it('needs profit data to judge', () => {
    const none = computeEconomics({
      revenue: '0',
      contributionBeforeAds: '0',
      orders: 0,
      targetContribution: '10',
    });
    expect(assessCampaign(camp('x', { conversionValue: '800' }), none, 100).verdict).toBe(
      'insufficient_data',
    );
  });
});

describe('budget allocation', () => {
  it('stays within the total, pauses losers and funds tests', () => {
    const a = [
      assessCampaign(camp('loser', { conversionValue: '100' }), econ, 100),
      assessCampaign(camp('good', { conversionValue: '400' }), econ, 100),
      assessCampaign(camp('great', { conversionValue: '800' }), econ, 100),
      assessCampaign(camp('new', { clicks: 5, spend: '2' }), econ, 100),
    ];
    const out = allocateBudget(a, '50');
    const by = Object.fromEntries(out.map((x) => [x.name, x.proposedDailyBudget]));
    expect(by.loser).toBe('0.00');
    expect(by.new).toBe('10.00');
    expect(Number(by.great)).toBeGreaterThan(Number(by.good));
    expect(out.reduce((s, x) => s + Number(x.proposedDailyBudget), 0)).toBeLessThanOrEqual(50);
  });
  it('gives everything to tests when nothing has data, never exceeding the total', () => {
    const a = ['a', 'b', 'c'].map((n) =>
      assessCampaign(camp(n, { clicks: 1, spend: '0' }), econ, 100),
    );
    const out = allocateBudget(a, '2', { minPerCampaign: '1' });
    expect(out.reduce((s, x) => s + Number(x.proposedDailyBudget), 0)).toBeLessThanOrEqual(2);
  });
});

describe('platform parsing', () => {
  it('reads Meta purchases by action type priority', () => {
    expect(
      metaPurchases({
        campaign_id: '1',
        campaign_name: 'x',
        date_start: '2026-11-01',
        date_stop: '2026-11-01',
        actions: [
          { action_type: 'purchase', value: '2' },
          { action_type: 'omni_purchase', value: '3' },
        ],
        action_values: [{ action_type: 'omni_purchase', value: '90' }],
      }),
    ).toEqual({ conversions: '3', value: '90', actionType: 'omni_purchase' });
    expect(
      metaPurchases({ campaign_id: '1', campaign_name: 'x', date_start: '', date_stop: '' })
        .actionType,
    ).toBeNull();
  });
  it('converts Etsy ledger minor units (zero-decimal currencies as is)', () => {
    expect(ledgerAmount(-450, 'USD')).toBe('-4.50');
    expect(ledgerAmount(-450, 'JPY')).toBe('-450');
  });
});
