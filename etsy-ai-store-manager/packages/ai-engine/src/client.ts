import Anthropic from '@anthropic-ai/sdk';

/** Model used for all AI tasks (current default Opus model). */
export const AI_MODEL = 'claude-opus-5-5';

/**
 * Per-token prices used ONLY to record an estimated cost per AI task (ai_tasks.cost_usd).
 * Source: Anthropic model table (claude-opus-5-5: $4 input / $20 output per 1M tokens,
 * cache reads $0.20), cached 2026-11-03. Web search requests are billed separately by
 * Anthropic and are counted in `server_tool_use.web_search_requests` (price not hard-coded).
 */
export const MODEL_PRICES_USD_PER_MTOK: Record<
  string,
  { input: number; output: number; cacheRead: number }
> = {
  'claude-opus-5-5': { input: 4, output: 20, cacheRead: 0.2 },
};

export interface AiUsage {
  model: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  webSearchRequests: number;
  costUsd: number;
}

export function emptyUsage(model = AI_MODEL): AiUsage {
  return {
    model,
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    webSearchRequests: 0,
    costUsd: 0,
  };
}

/** Accumulates usage from an API response (works for Message and BetaMessage). */
export function addUsage(acc: AiUsage, usage: unknown, model = acc.model): AiUsage {
  const u = (usage ?? {}) as {
    input_tokens?: number;
    output_tokens?: number;
    cache_read_input_tokens?: number | null;
    server_tool_use?: { web_search_requests?: number } | null;
  };
  const p = MODEL_PRICES_USD_PER_MTOK[model];
  const input = u.input_tokens ?? 0;
  const output = u.output_tokens ?? 0;
  const cacheRead = u.cache_read_input_tokens ?? 0;
  return {
    model,
    inputTokens: acc.inputTokens + input,
    outputTokens: acc.outputTokens + output,
    cacheReadTokens: acc.cacheReadTokens + cacheRead,
    webSearchRequests: acc.webSearchRequests + (u.server_tool_use?.web_search_requests ?? 0),
    costUsd:
      acc.costUsd +
      (p ? (input * p.input + output * p.output + cacheRead * p.cacheRead) / 1_000_000 : 0),
  };
}

export class AiRefusalError extends Error {
  constructor(readonly category: string | null) {
    super(`Model isteği güvenlik politikası nedeniyle reddetti${category ? ` (${category})` : ''}`);
  }
}

export function createAnthropic(opts: {
  apiKey: string;
  baseURL?: string | undefined;
  maxRetries?: number;
}) {
  return new Anthropic({
    apiKey: opts.apiKey,
    ...(opts.baseURL ? { baseURL: opts.baseURL } : {}),
    maxRetries: opts.maxRetries ?? 2,
    timeout: 10 * 60_000,
  });
}

export { Anthropic };
