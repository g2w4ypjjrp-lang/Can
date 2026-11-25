import type Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';
import { addUsage, AI_MODEL, AiRefusalError, emptyUsage, type AiUsage } from './client.js';

/** Real, verifiable facts gathered from the Etsy API before the model is called. */
export interface EtsyMarketFacts {
  query: string;
  buyerCountry: string | null;
  keywords: Array<{
    keyword: string;
    activeListings: number;
    priceUsd: { min: number; p25: number; median: number; p75: number; max: number } | null;
    avgFavorers: number | null;
    newListingsShare90d: number | null;
    topTags: Array<{ tag: string; count: number }>;
    sampleSize: number;
  }>;
  /** Product types the store can produce through its Printify catalog (titles). */
  producibleTypes: string[];
}

export interface WebFindings {
  text: string;
  sources: Array<{ url: string; title: string | null }>;
}

const SignalSchema = z.object({
  signal: z.string().describe('What indicates demand or a trend, in Turkish'),
  source: z
    .string()
    .describe(
      "'etsy_api' for the provided Etsy data, otherwise the exact URL of a web source you used",
    ),
  isEstimate: z
    .boolean()
    .describe('true unless the signal is a number taken directly from the provided Etsy data'),
});

export const MarketAnalysisSchema = z.object({
  summary: z.string().describe('2-4 sentence Turkish summary of the market'),
  seasonality: z.string().describe('Turkish; when demand peaks, or "belirsiz" if unknown'),
  confidence: z.enum(['low', 'medium', 'high']),
  keywords: z
    .array(
      z.object({
        keyword: z
          .string()
          .describe('English buyer search phrase, max 20 characters if used as an Etsy tag'),
        trend: z.enum(['rising', 'stable', 'falling', 'unknown']),
        rationale: z.string().describe('Turkish'),
      }),
    )
    .max(20),
  opportunities: z
    .array(
      z.object({
        title: z.string().describe('English working title for an ORIGINAL product idea'),
        category: z.string(),
        productType: z.string().describe('One of the producible product types provided, verbatim'),
        targetCustomer: z.string().describe('Turkish'),
        keywords: z.array(z.string()).max(13),
        competitionLevel: z.enum(['low', 'medium', 'high', 'unknown']),
        demandSignals: z.array(SignalSchema).max(6),
        suggestedPriceUsd: z
          .number()
          .describe('Retail price you would test, based on the provided price distribution'),
        personalization: z.boolean(),
        ipRisk: z
          .enum(['low', 'medium', 'high'])
          .describe('Risk of trademark/copyright/personality-rights problems'),
        ipRiskNotes: z.string().describe('Turkish; what to avoid'),
        rationale: z.string().describe('Turkish; why this could work, which facts support it'),
      }),
    )
    .max(8),
});
export type MarketAnalysis = z.infer<typeof MarketAnalysisSchema>;

const SYSTEM = `You are the market research analyst of an Etsy print-on-demand shop (products made by Printify).
Work only with: (1) the Etsy marketplace facts in the user message, which come from the official Etsy API, and
(2) web research findings with their source URLs. Rules:
- Etsy does not publish competitor sales. Never state or imply sales volumes or revenues as facts. Anything that is
  not a number from the provided Etsy facts is an estimate: mark it isEstimate=true and keep confidence honest.
- Every demand signal's source is either 'etsy_api' or the exact URL of a web finding you were given.
- Propose only ORIGINAL designs. Never propose products built on brands, trademarks, logos, characters, sports
  teams, celebrities or other people's artwork; flag any residual risk in ipRisk/ipRiskNotes.
- productType must be one of the producible product types listed; skip ideas the shop cannot produce.
- Explanations (summary, rationale, notes, targetCustomer, signal) are written in Turkish; titles and keywords in
  English because the shop sells globally.
- Prefer niches where the price distribution leaves room above the shop's production and fee costs, and where
  active listing counts suggest moderate rather than saturated competition.`;

/**
 * Optional step: web research for trends and seasonality using the server-side
 * web search tool. Handles pause_turn (server tool loop limit) up to 4 times.
 * Server-side refusal fallback is enabled (fallbacks: "default").
 */
export async function researchTrends(
  client: Anthropic,
  input: { query: string; region: string },
  usage: AiUsage = emptyUsage(),
): Promise<{ findings: WebFindings; usage: AiUsage }> {
  const messages: Anthropic.Beta.BetaMessageParam[] = [
    {
      role: 'user',
      content:
        `Research current consumer demand, gift occasions, seasonality and design trends for Etsy products related to "${input.query}" ` +
        `for buyers in ${input.region}. Focus on the next 3-6 months. Report concise findings, each with the URL it came from. ` +
        'Do not guess numbers; quote only what a source states.',
    },
  ];
  let acc = usage;
  for (let i = 0; i < 5; i++) {
    const res = await client.beta.messages.create({
      model: AI_MODEL,
      max_tokens: 16000,
      betas: ['server-side-fallback-2026-07-01'],
      fallbacks: 'default',
      output_config: { effort: 'medium' },
      tools: [{ type: 'web_search_20260209', name: 'web_search', max_uses: 6 }],
      messages,
    });
    acc = addUsage(acc, res.usage, AI_MODEL);
    if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
    if (res.stop_reason === 'pause_turn') {
      messages.push({
        role: 'assistant',
        content: res.content as Anthropic.Beta.BetaContentBlockParam[],
      });
      continue;
    }
    const sources = new Map<string, string | null>();
    let text = '';
    for (const block of res.content) {
      if (block.type === 'text') {
        text += block.text;
        for (const c of block.citations ?? []) {
          if ('url' in c && typeof c.url === 'string')
            sources.set(c.url, 'title' in c ? ((c.title as string | null) ?? null) : null);
        }
      } else if (block.type === 'web_search_tool_result' && Array.isArray(block.content)) {
        for (const r of block.content)
          if (r.type === 'web_search_result') sources.set(r.url, r.title ?? null);
      }
    }
    return {
      findings: {
        text: text.trim(),
        sources: [...sources].map(([url, title]) => ({ url, title })),
      },
      usage: acc,
    };
  }
  return { findings: { text: '', sources: [] }, usage: acc };
}

/** Structured analysis (JSON validated against MarketAnalysisSchema). */
export async function analyzeMarket(
  client: Anthropic,
  input: { facts: EtsyMarketFacts; web: WebFindings | null; region: string },
  usage: AiUsage = emptyUsage(),
): Promise<{ analysis: MarketAnalysis; usage: AiUsage }> {
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 16000,
    output_config: { effort: 'medium', format: zodOutputFormat(MarketAnalysisSchema) },
    system: SYSTEM,
    messages: [
      {
        role: 'user',
        content: [
          `Research topic: "${input.facts.query}" — target buyers: ${input.region}.`,
          `ETSY MARKETPLACE FACTS (official Etsy API, ${new Date().toISOString().slice(0, 10)}):`,
          JSON.stringify(input.facts.keywords, null, 1),
          `PRODUCIBLE PRODUCT TYPES (Printify catalog): ${JSON.stringify(input.facts.producibleTypes)}`,
          input.web && input.web.text
            ? `WEB RESEARCH FINDINGS:\n${input.web.text}\nSOURCES: ${JSON.stringify(input.web.sources.map((s) => s.url))}`
            : 'WEB RESEARCH FINDINGS: none (do not cite web sources).',
          'Return the market analysis.',
        ].join('\n\n'),
      },
    ],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output)
    throw new Error(`Yapılandırılmış çıktı alınamadı (stop_reason=${res.stop_reason})`);
  // keep only web sources that were actually provided
  const allowed = new Set(['etsy_api', ...(input.web?.sources.map((s) => s.url) ?? [])]);
  const analysis = res.parsed_output;
  for (const o of analysis.opportunities) {
    o.demandSignals = o.demandSignals.map((s) =>
      allowed.has(s.source) ? s : { ...s, source: 'unverified', isEstimate: true },
    );
  }
  return { analysis, usage: acc };
}
