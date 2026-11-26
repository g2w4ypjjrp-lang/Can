import { Decimal } from 'decimal.js';

/**
 * Advertising economics on top of the Profit Engine.
 *  - contributionBeforeAds: average per-order contribution BEFORE ad cost (from profit snapshots)
 *  - break-even ROAS  = AOV / contributionBeforeAds        (ads eat the whole contribution)
 *  - target ROAS      = AOV / (contributionBeforeAds − targetContribution)
 *                       (ads leave the target contribution per order, e.g. 10 USD)
 * Amounts are decimal strings; nothing here is rounded until the end.
 */
export interface CampaignStats {
  campaignId: string;
  name: string;
  platform: string;
  status: string;
  dailyBudget: string | null;
  impressions: number;
  clicks: number;
  spend: string;
  conversions: string;
  conversionValue: string;
  attributionConfidence: 'low' | 'medium' | 'high';
}

export interface Economics {
  aov: string | null;
  contributionBeforeAds: string | null;
  targetContribution: string;
  breakEvenRoas: string | null;
  targetRoas: string | null;
  maxCpa: string | null;
  sampleOrders: number;
}

export interface Kpis {
  ctr: string | null;
  cpc: string | null;
  cvr: string | null;
  cpa: string | null;
  roas: string | null;
  acos: string | null;
}

export type AdVerdict =
  'insufficient_data' | 'unprofitable' | 'below_target' | 'on_target' | 'scale';

export interface CampaignAssessment extends CampaignStats {
  kpis: Kpis;
  verdict: AdVerdict;
  reason: string;
}

const d = (v: string | number | null | undefined) => new Decimal(v ?? 0);
const ratio = (a: Decimal, b: Decimal, dp = 4) =>
  b.isZero() ? null : a.div(b).toDecimalPlaces(dp).toString();

export function computeEconomics(input: {
  revenue: string; // order revenue (item + shipping) of the sample
  contributionBeforeAds: string; // sum over the sample
  orders: number;
  targetContribution: string;
}): Economics {
  const target = d(input.targetContribution);
  if (input.orders <= 0)
    return {
      aov: null,
      contributionBeforeAds: null,
      targetContribution: target.toFixed(2),
      breakEvenRoas: null,
      targetRoas: null,
      maxCpa: null,
      sampleOrders: 0,
    };
  const aov = d(input.revenue).div(input.orders);
  const cba = d(input.contributionBeforeAds).div(input.orders);
  const room = cba.minus(target);
  return {
    aov: aov.toFixed(2),
    contributionBeforeAds: cba.toFixed(2),
    targetContribution: target.toFixed(2),
    breakEvenRoas: cba.gt(0) ? aov.div(cba).toDecimalPlaces(2).toString() : null,
    targetRoas: room.gt(0) ? aov.div(room).toDecimalPlaces(2).toString() : null,
    maxCpa: room.gt(0) ? room.toFixed(2) : '0.00',
    sampleOrders: input.orders,
  };
}

export function computeKpis(
  c: Pick<CampaignStats, 'impressions' | 'clicks' | 'spend' | 'conversions' | 'conversionValue'>,
): Kpis {
  const spend = d(c.spend);
  const conv = d(c.conversions);
  const value = d(c.conversionValue);
  return {
    ctr: ratio(d(c.clicks), d(c.impressions)),
    cpc: c.clicks ? spend.div(c.clicks).toFixed(2) : null,
    cvr: ratio(conv, d(c.clicks)),
    cpa: conv.gt(0) ? spend.div(conv).toFixed(2) : null,
    roas: spend.gt(0) ? value.div(spend).toDecimalPlaces(2).toString() : null,
    acos: value.gt(0) ? spend.div(value).toDecimalPlaces(4).toString() : null,
  };
}

/** Deterministic verdict per campaign; never judged on too little data. */
export function assessCampaign(
  c: CampaignStats,
  e: Economics,
  minClicks: number,
): CampaignAssessment {
  const kpis = computeKpis(c);
  const spend = d(c.spend);
  const enoughData =
    c.clicks >= minClicks || (e.maxCpa !== null && spend.gte(d(e.maxCpa).times(3)) && spend.gt(0));
  let verdict: AdVerdict;
  let reason: string;
  if (!enoughData) {
    verdict = 'insufficient_data';
    reason = `Karar için yetersiz veri (${c.clicks}/${minClicks} tıklama).`;
  } else if (e.breakEvenRoas === null) {
    verdict = 'insufficient_data';
    reason = 'Kâr verisi yok: başa baş ROAS hesaplanamıyor (sipariş kârlılığı gerekli).';
  } else {
    const roas = d(kpis.roas ?? 0);
    const be = d(e.breakEvenRoas);
    const target = e.targetRoas ? d(e.targetRoas) : null;
    if (roas.lt(be)) {
      verdict = 'unprofitable';
      reason = `ROAS ${roas.toFixed(2)} < başa baş ${be.toFixed(2)}: her satış zarar ettiriyor.`;
    } else if (target && roas.lt(target)) {
      verdict = 'below_target';
      reason = `ROAS ${roas.toFixed(2)} kârlı ama hedef ${target.toFixed(2)} altında (sipariş başı hedef katkı karşılanmıyor).`;
    } else if (target && roas.gte(target.times(1.3))) {
      verdict = 'scale';
      reason = `ROAS ${roas.toFixed(2)} hedefin %30 üzerinde: bütçe artışı adayı.`;
    } else {
      verdict = 'on_target';
      reason = `ROAS ${roas.toFixed(2)} hedefte.`;
    }
  }
  if (c.attributionConfidence === 'low' && verdict !== 'insufficient_data')
    reason += ' Atıf güveni düşük; platform raporu siparişleri fazla sayabilir.';
  return { ...c, kpis, verdict, reason };
}

export interface Allocation {
  campaignId: string;
  name: string;
  platform: string;
  currentDailyBudget: string | null;
  proposedDailyBudget: string;
  verdict: AdVerdict;
  reason: string;
}

/**
 * Splits a total daily budget (≤ the user cap) across campaigns:
 *  - unprofitable → 0 (pause), insufficient data → a small test budget,
 *  - the rest weighted by ROAS headroom over break-even.
 * The sum never exceeds the total; amounts are rounded DOWN to cents.
 */
export function allocateBudget(
  assessed: CampaignAssessment[],
  totalDaily: string,
  opts: { testBudgetShare?: number; minPerCampaign?: string } = {},
): Allocation[] {
  const total = d(totalDaily);
  const minPer = d(opts.minPerCampaign ?? '1');
  const testShare = new Decimal(opts.testBudgetShare ?? 0.2);
  const rows = assessed.filter((a) => a.status !== 'ended');
  const testers = rows.filter((a) => a.verdict === 'insufficient_data');
  const earners = rows.filter((a) => ['below_target', 'on_target', 'scale'].includes(a.verdict));
  const out = new Map<string, Decimal>();
  for (const a of rows) out.set(a.campaignId, new Decimal(0));

  let testPool = testers.length ? total.times(earners.length ? testShare : 1) : new Decimal(0);
  if (testers.length) {
    const each = Decimal.max(minPer, testPool.div(testers.length)).toDecimalPlaces(
      2,
      Decimal.ROUND_DOWN,
    );
    let used = new Decimal(0);
    for (const t of testers) {
      const v = Decimal.min(each, total.minus(used));
      out.set(t.campaignId, v);
      used = used.plus(v);
    }
    testPool = used;
  }
  const pool = total.minus(testPool);
  if (earners.length && pool.gt(0)) {
    const weights = earners.map((a) => {
      const roas = d(a.kpis.roas ?? 0);
      return Decimal.max(new Decimal(0.1), roas);
    });
    const sum = weights.reduce((s, w) => s.plus(w), new Decimal(0));
    earners.forEach((a, i) => {
      out.set(
        a.campaignId,
        pool.times(weights[i]!).div(sum).toDecimalPlaces(2, Decimal.ROUND_DOWN),
      );
    });
  }
  return rows.map((a) => ({
    campaignId: a.campaignId,
    name: a.name,
    platform: a.platform,
    currentDailyBudget: a.dailyBudget,
    proposedDailyBudget: out.get(a.campaignId)!.toFixed(2),
    verdict: a.verdict,
    reason: a.verdict === 'unprofitable' ? `${a.reason} Öneri: durdur.` : a.reason,
  }));
}
