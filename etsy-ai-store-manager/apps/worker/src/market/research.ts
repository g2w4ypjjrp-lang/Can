import type pg from 'pg';
import { Decimal } from 'decimal.js';
import {
  EtsyClient,
  moneyToDecimal,
  type EtsyAppConfig,
  type EtsyListing,
} from '@esm/integrations';
import {
  analyzeMarket,
  createAnthropic,
  emptyUsage,
  researchTrends,
  type AiUsage,
  type EtsyMarketFacts,
  type MarketAnalysis,
  type WebFindings,
} from '@esm/ai-engine';
import { calculateContribution, convert, decide, loadProfitContext } from '@esm/profit-engine';

export interface MarketDeps {
  etsy: EtsyAppConfig | null;
  anthropic: { apiKey: string; baseURL?: string | undefined } | null;
  fetchImpl: typeof fetch;
}

/** Product types offered from the Printify catalog (spec §7) plus the store's own product types. */
const BASE_PRODUCT_TYPES = [
  'T-Shirt',
  'Sweatshirt',
  'Hoodie',
  'Poster',
  'Canvas',
  'Mug',
  'Tote Bag',
  'Phone Case',
  'Pillow',
  'Blanket',
  'Sticker',
];

const SAMPLE_PAGES = 2; // 2 × 100 listings per keyword

/**
 * Collects REAL marketplace facts for a keyword from Etsy's public search:
 * active listing count (supply), price distribution (USD), favourites, freshness, tags.
 */
export async function scanKeyword(
  client: EtsyClient,
  keyword: string,
  fx: Record<string, string>,
  buyerCountry: string | null,
) {
  const listings: EtsyListing[] = [];
  let total = 0;
  for (let page = 0; page < SAMPLE_PAGES; page++) {
    const r = await client.findActiveListings({
      keywords: keyword,
      limit: 100,
      offset: page * 100,
      ...(buyerCountry ? { buyerCountry } : {}),
    });
    total = r.count;
    listings.push(...r.results);
    if (r.results.length < 100) break;
  }
  const prices: number[] = [];
  for (const l of listings) {
    const p = moneyToDecimal(l.price);
    if (!p) continue;
    try {
      prices.push(convert(new Decimal(p), l.price.currency_code, 'USD', fx).toNumber());
    } catch {
      /* no fx rate for this currency: skip from the distribution */
    }
  }
  prices.sort((a, b) => a - b);
  const q = (f: number) =>
    prices[Math.min(prices.length - 1, Math.floor(f * (prices.length - 1)))]!;
  const now = Date.now() / 1000;
  const created = listings
    .map((l) => l.created_timestamp)
    .filter((x): x is number => typeof x === 'number');
  const tags = new Map<string, number>();
  for (const l of listings)
    for (const t of l.tags ?? []) tags.set(t.toLowerCase(), (tags.get(t.toLowerCase()) ?? 0) + 1);
  const favs = listings.map((l) => l.num_favorers).filter((x) => typeof x === 'number');
  return {
    fact: {
      keyword,
      activeListings: total,
      priceUsd: prices.length
        ? {
            min: round(prices[0]!),
            p25: round(q(0.25)),
            median: round(q(0.5)),
            p75: round(q(0.75)),
            max: round(prices[prices.length - 1]!),
          }
        : null,
      avgFavorers: favs.length ? round(favs.reduce((a, b) => a + b, 0) / favs.length) : null,
      newListingsShare90d: created.length
        ? round(created.filter((c) => now - c < 90 * 86400).length / created.length)
        : null,
      topTags: [...tags]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 15)
        .map(([tag, count]) => ({ tag, count })),
      sampleSize: listings.length,
    },
    top: listings.slice(0, 10),
  };
}

const round = (n: number) => Math.round(n * 100) / 100;

/** Deterministic, explainable opportunity score (0–100). */
export function scoreOpportunity(input: {
  activeListings: number | null;
  avgFavorers: number | null;
  contribution: string | null;
  target: string;
  ipRisk: 'low' | 'medium' | 'high';
}) {
  const clamp = (x: number) => Math.max(0, Math.min(1, x));
  const competition =
    input.activeListings === null ? 0.5 : clamp(1 - Math.log10(1 + input.activeListings) / 6);
  const demand =
    input.avgFavorers === null ? 0.3 : clamp(Math.log10(1 + input.avgFavorers) / Math.log10(201));
  const profit =
    input.contribution === null
      ? 0.4
      : clamp(Number(input.contribution) / (2 * Number(input.target)));
  const penalty = input.ipRisk === 'high' ? 40 : input.ipRisk === 'medium' ? 15 : 0;
  const score = Math.max(
    0,
    Math.min(100, Math.round((35 * profit + 35 * competition + 30 * demand) * 100) / 100 - penalty),
  );
  return {
    score,
    breakdown: {
      formula: '35×kâr + 35×(düşük rekabet) + 30×(ilgi) − IP cezası',
      profit: round(profit),
      competition: round(competition),
      demand: round(demand),
      ipPenalty: penalty,
      notes: [
        input.contribution === null
          ? 'Üretim maliyeti bilinmediği için kâr bileşeni nötr (0.4) alındı'
          : null,
        'İlgi = ilan başına ortalama favori (Etsy API); satış adedi değildir',
      ].filter(Boolean),
    },
  };
}

export async function runMarketResearch(pool: pg.Pool, deps: MarketDeps, researchId: string) {
  const r = await pool.query(`select * from public.market_research where id = $1`, [researchId]);
  const mr = r.rows[0];
  if (!mr) throw new Error('market_research not found');
  if (mr.status === 'completed') return { skipped: 'already completed' };
  await pool.query(
    `update public.market_research set status = 'running', error = null where id = $1`,
    [researchId],
  );
  const storeId: string = mr.store_id;
  const ctx = await loadProfitContext(pool, storeId);
  const notes: string[] = [];
  const dataSources: Array<Record<string, unknown>> = [];
  const extraKeywords: string[] = Array.isArray(mr.summary?.requestedKeywords)
    ? mr.summary.requestedKeywords
    : [];
  const keywords = [mr.query, ...extraKeywords]
    .map((k: string) => k.trim())
    .filter(Boolean)
    .slice(0, 5);

  // 1) Real Etsy marketplace facts
  const facts: EtsyMarketFacts = {
    query: mr.query,
    buyerCountry: mr.buyer_country,
    keywords: [],
    producibleTypes: [],
  };
  if (deps.etsy) {
    const client = new EtsyClient({
      app: deps.etsy,
      fetchImpl: deps.fetchImpl,
      getAccessToken: async () => '',
    });
    for (const kw of keywords) {
      const { fact, top } = await scanKeyword(client, kw, ctx.fxRates, mr.buyer_country);
      facts.keywords.push(fact);
      await pool.query(
        `insert into public.keywords (store_id, keyword, language, region, competition_estimate, trend_direction, source, is_estimate,
                                      last_checked_at, active_listings, median_price_usd, avg_favorers, top_tags, market_research_id)
         values ($1,$2,'en',$3,null,'unknown','etsy_api',false,now(),$4,$5,$6,$7,$8)
         on conflict (store_id, lower(keyword), language, region) do update set
           last_checked_at = now(), active_listings = excluded.active_listings, median_price_usd = excluded.median_price_usd,
           avg_favorers = excluded.avg_favorers, top_tags = excluded.top_tags, market_research_id = excluded.market_research_id,
           source = 'etsy_api', is_estimate = false`,
        [
          storeId,
          kw.slice(0, 120),
          mr.region,
          fact.activeListings,
          fact.priceUsd?.median ?? null,
          fact.avgFavorers,
          JSON.stringify(fact.topTags),
          researchId,
        ],
      );
      for (const l of top) {
        await pool.query(
          `insert into public.competitor_research (store_id, market_research_id, competitor_shop_id, listing_url, listing_title,
                                                   observed_price, currency, signals, source, is_estimate)
           values ($1,$2,$3,$4,$5,$6,$7,$8,'etsy_api',false)`,
          [
            storeId,
            researchId,
            l.shop_id,
            l.url,
            l.title?.slice(0, 300),
            moneyToDecimal(l.price),
            l.price?.currency_code ?? null,
            JSON.stringify({
              keyword: kw,
              num_favorers: l.num_favorers,
              tags: l.tags?.slice(0, 13) ?? [],
            }),
          ],
        );
      }
    }
    dataSources.push({
      type: 'etsy_api',
      endpoint: 'GET /v3/application/listings/active',
      keywords,
      sampleListingsPerKeyword: SAMPLE_PAGES * 100,
    });
  } else {
    notes.push('Etsy API anahtarı yok: pazar verisi (ilan sayısı, fiyat dağılımı) toplanamadı.');
  }

  const own = await pool.query(
    `select distinct product_type from public.products where store_id = $1`,
    [storeId],
  );
  facts.producibleTypes = [
    ...new Set([...BASE_PRODUCT_TYPES, ...own.rows.map((x) => String(x.product_type))]),
  ];

  // 2) AI analysis
  let usage: AiUsage = emptyUsage();
  let analysis: MarketAnalysis | null = null;
  let web: WebFindings | null = null;
  let aiTaskId: string | null = null;
  if (deps.anthropic) {
    const t = await pool.query(
      `insert into public.ai_tasks (store_id, task_type, status, input, model, idempotency_key, started_at, created_by)
       values ($1, 'market_research', 'running', $2, 'claude-opus-5-5', $3, now(), $4) returning id`,
      [
        storeId,
        JSON.stringify({ query: mr.query, region: mr.region, useWebSearch: mr.use_web_search }),
        `market_research:${researchId}`,
        mr.created_by,
      ],
    );
    aiTaskId = t.rows[0].id;
    try {
      const client = createAnthropic(deps.anthropic);
      if (mr.use_web_search) {
        const w = await researchTrends(client, { query: mr.query, region: mr.region }, usage);
        web = w.findings;
        usage = w.usage;
        dataSources.push({ type: 'web_search', sources: web.sources });
      }
      const a = await analyzeMarket(client, { facts, web, region: mr.region }, usage);
      analysis = a.analysis;
      usage = a.usage;
      await pool.query(
        `update public.ai_tasks set status = 'succeeded', output = $2, input_tokens = $3, output_tokens = $4, cost_usd = $5, finished_at = now()
          where id = $1`,
        [
          aiTaskId,
          JSON.stringify({
            summary: analysis.summary,
            opportunities: analysis.opportunities.length,
            webSearchRequests: usage.webSearchRequests,
          }),
          usage.inputTokens,
          usage.outputTokens,
          usage.costUsd.toFixed(6),
        ],
      );
    } catch (err) {
      await pool.query(
        `update public.ai_tasks set status = 'failed', error = $2, input_tokens = $3, output_tokens = $4, cost_usd = $5, finished_at = now() where id = $1`,
        [
          aiTaskId,
          err instanceof Error ? err.message.slice(0, 500) : String(err),
          usage.inputTokens,
          usage.outputTokens,
          usage.costUsd.toFixed(6),
        ],
      );
      throw err;
    }
  } else {
    notes.push(
      'ANTHROPIC_API_KEY yok: AI analizi ve ürün fırsatı önerileri üretilmedi; yalnızca Etsy verisi kaydedildi.',
    );
  }

  // 3) Opportunities + profitability + score
  let created = 0;
  for (const o of analysis?.opportunities ?? []) {
    const kwFact =
      facts.keywords.find((k) =>
        o.keywords.some((x) => x.toLowerCase() === k.keyword.toLowerCase()),
      ) ??
      facts.keywords[0] ??
      null;
    const cost = await pool.query(
      `select avg(c.amount)::text production,
              avg(s.amount)::text shipping
         from public.products p
         join public.product_variants v on v.product_id = p.id and v.is_enabled
         left join public.product_costs c on c.product_variant_id = v.id and c.cost_type = 'production' and c.valid_to is null
         left join public.product_costs s on s.product_variant_id = v.id and s.cost_type = 'shipping_first_item' and s.valid_to is null
              and s.destination_country = $3
        where p.store_id = $1 and p.product_type ilike $2`,
      [storeId, `%${o.productType.replace(/[%_\\]/g, '')}%`, mr.buyer_country ?? 'US'],
    );
    const production = cost.rows[0]?.production as string | null;
    const shipping = cost.rows[0]?.shipping as string | null;
    let contribution: string | null = null;
    let decision: string | null = null;
    if (production && ctx.sellerCountry) {
      const res = calculateContribution(
        {
          currency: 'USD',
          unitPrice: o.suggestedPriceUsd.toFixed(2),
          quantity: 1,
          shippingCharged: '0',
          productionCostPerUnit: production,
          productionCostCurrency: 'USD',
          fulfillmentShippingFirst: shipping ?? '0',
          fulfillmentShippingAdditional: '0',
          fulfillmentShippingCurrency: 'USD',
          sellerCountry: ctx.sellerCountry,
          buyerCountry: mr.buyer_country ?? 'US',
          payoutCurrency: ctx.payoutCurrency ?? 'USD',
          adCostAllocated: ctx.defaultAdCostPerOrder,
          fxRates: ctx.fxRates,
        },
        ctx.rules,
        ctx.policy,
      );
      contribution = res.contribution;
      decision = res.complete ? res.decision : decide(res.contribution, ctx.policy.thresholds);
    }
    const s = scoreOpportunity({
      activeListings: kwFact?.activeListings ?? null,
      avgFavorers: kwFact?.avgFavorers ?? null,
      contribution,
      target: ctx.policy.targetContribution,
      ipRisk: o.ipRisk,
    });
    const autoReject =
      decision === 'rejected'
        ? 'Profit Engine: önerilen fiyatta zarar'
        : o.ipRisk === 'high'
          ? 'Yüksek fikri mülkiyet riski'
          : null;
    const conf = !production ? 'low' : (analysis?.confidence ?? 'low');
    await pool.query(
      `insert into public.product_opportunities
         (store_id, market_research_id, title, category, target_customer, keywords, competition_level, demand_signals,
          est_sale_price, est_production_cost, est_ad_cost, est_contribution, currency, opportunity_score, confidence, is_estimate,
          status, rejection_reason, product_type, personalization, ip_risk, ip_risk_notes, rationale, est_decision, score_breakdown)
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'USD',$13,$14,true,$15,$16,$17,$18,$19,$20,$21,$22,$23)`,
      [
        storeId,
        researchId,
        o.title.slice(0, 200),
        o.category,
        o.targetCustomer,
        o.keywords.slice(0, 13),
        o.competitionLevel,
        JSON.stringify(o.demandSignals),
        o.suggestedPriceUsd.toFixed(2),
        production,
        ctx.defaultAdCostPerOrder,
        contribution,
        s.score,
        conf,
        autoReject ? 'rejected' : 'new',
        autoReject,
        o.productType,
        o.personalization,
        o.ipRisk,
        o.ipRiskNotes,
        o.rationale,
        decision,
        JSON.stringify({
          ...s.breakdown,
          keyword: kwFact?.keyword ?? null,
          costKnown: Boolean(production),
        }),
      ],
    );
    created++;
  }
  if (analysis) {
    for (const k of analysis.keywords) {
      await pool.query(
        `insert into public.keywords (store_id, keyword, language, region, trend_direction, source, is_estimate, last_checked_at, market_research_id)
         values ($1,$2,'en',$3,$4,'ai_analysis',true,now(),$5)
         on conflict (store_id, lower(keyword), language, region) do update set trend_direction = excluded.trend_direction,
           last_checked_at = now(), market_research_id = excluded.market_research_id`,
        [storeId, k.keyword.slice(0, 120), mr.region, k.trend, researchId],
      );
    }
  }

  const confidence = analysis
    ? facts.keywords.length
      ? analysis.confidence
      : 'low'
    : facts.keywords.length
      ? 'medium'
      : 'low';
  await pool.query(
    `update public.market_research set status = 'completed', completed_at = now(), confidence = $2, is_estimate = true,
            summary = summary || $3, data_sources = $4, ai_task_id = $5
      where id = $1`,
    [
      researchId,
      confidence,
      JSON.stringify({
        facts: facts.keywords,
        analysis: analysis
          ? {
              summary: analysis.summary,
              seasonality: analysis.seasonality,
              keywords: analysis.keywords,
            }
          : null,
        web: web ? { text: web.text.slice(0, 8000), sources: web.sources } : null,
        notes,
        usage: {
          inputTokens: usage.inputTokens,
          outputTokens: usage.outputTokens,
          webSearchRequests: usage.webSearchRequests,
          costUsd: usage.costUsd.toFixed(4),
        },
      }),
      JSON.stringify(dataSources),
      aiTaskId,
    ],
  );
  return {
    keywords: facts.keywords.length,
    opportunities: created,
    costUsd: usage.costUsd.toFixed(4),
    notes,
  };
}
