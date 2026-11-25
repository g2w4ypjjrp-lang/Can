/**
 * TEST DOUBLE of the Claude Messages API (POST /v1/messages) used through the real
 * @anthropic-ai/sdk client. It checks the request contract this project relies on
 * and returns canned, schema-valid responses. Not evidence of model quality.
 */
import http from 'node:http';
import type { AddressInfo } from 'node:net';

export interface AnthropicStub {
  url: string;
  close(): Promise<void>;
  requests: Array<{ headers: http.IncomingHttpHeaders; body: Record<string, unknown> }>;
  /** next analysis responses: 'ok' | 'refusal' */
  mode: { analysis: 'ok' | 'refusal' };
}

export const STUB_ANALYSIS = {
  summary: 'Kişiselleştirilmiş seramik kupa pazarı kalabalık ama niş temalarda fırsat var.',
  seasonality: 'Kasım-Aralık hediye sezonunda zirve',
  confidence: 'medium',
  keywords: [
    { keyword: 'gardener mug', trend: 'rising', rationale: 'Bahçe hobisi hediyeleri' },
    { keyword: 'plant lover gift', trend: 'stable', rationale: 'Yıl boyu talep' },
  ],
  opportunities: [
    {
      title: 'Botanical Line-Art Plant Mom Mug',
      category: 'Home & Living',
      productType: 'Mug',
      targetCustomer: 'Bitki seven kadınlar ve hediye alıcıları',
      keywords: ['plant mom mug', 'gardener gift'],
      competitionLevel: 'medium',
      demandSignals: [
        { signal: 'İlan başı ortalama favori yüksek', source: 'etsy_api', isEstimate: false },
        {
          signal: 'Hediye rehberlerinde bitki temaları',
          source: 'https://example.com/gift-trends',
          isEstimate: true,
        },
        { signal: 'Uydurma kaynak', source: 'https://not-provided.example/x', isEstimate: false },
      ],
      suggestedPriceUsd: 24.99,
      personalization: true,
      ipRisk: 'low',
      ipRiskNotes: 'Marka ve karakter içermeyen özgün çizim kullanın',
      rationale: 'Fiyat dağılımının ortası 22-26 USD; özgün çizimle ayrışma mümkün.',
    },
    {
      title: 'Cheap Novelty Mug',
      category: 'Home & Living',
      productType: 'Mug',
      targetCustomer: 'Fiyat odaklı alıcılar',
      keywords: ['funny mug'],
      competitionLevel: 'high',
      demandSignals: [],
      suggestedPriceUsd: 14.99,
      personalization: false,
      ipRisk: 'low',
      ipRiskNotes: '-',
      rationale: 'Düşük fiyat segmenti',
    },
    {
      title: 'Famous Wizard Fan Mug',
      category: 'Home & Living',
      productType: 'Mug',
      targetCustomer: 'Hayranlar',
      keywords: ['wizard mug'],
      competitionLevel: 'high',
      demandSignals: [],
      suggestedPriceUsd: 26.99,
      personalization: false,
      ipRisk: 'high',
      ipRiskNotes: 'Telifli karaktere benzer; kullanılmamalı',
      rationale: 'Yüksek ilgi ama IP riski',
    },
  ],
};

export async function startAnthropicStub(): Promise<AnthropicStub> {
  const requests: AnthropicStub['requests'] = [];
  const mode: AnthropicStub['mode'] = { analysis: 'ok' };
  let webCalls = 0;
  const server = http.createServer(async (req, res) => {
    let raw = '';
    for await (const c of req) raw += c;
    const body = JSON.parse(raw || '{}') as Record<string, unknown>;
    requests.push({ headers: req.headers, body });
    const send = (status: number, json: unknown) => {
      res.writeHead(status, {
        'content-type': 'application/json',
        'request-id': `req_${requests.length}`,
      });
      res.end(JSON.stringify(json));
    };
    if (req.method !== 'POST' || !req.url?.startsWith('/v1/messages'))
      return send(404, { type: 'error', error: { type: 'not_found_error', message: 'nf' } });
    const key =
      req.headers['x-api-key'] ?? String(req.headers.authorization ?? '').replace(/^Bearer /, '');
    if (key !== 'sk-ant-test')
      return send(401, {
        type: 'error',
        error: { type: 'authentication_error', message: 'invalid x-api-key' },
      });
    const bad = (m: string) =>
      send(400, { type: 'error', error: { type: 'invalid_request_error', message: m } });
    if (body.model !== 'claude-opus-5-5') return bad('unexpected model');
    for (const k of ['temperature', 'top_p', 'top_k'])
      if (k in body) return bad(`${k} not supported`);
    const thinking = body.thinking as { type?: string } | undefined;
    if (thinking && thinking.type !== 'adaptive')
      return bad('thinking must be adaptive or omitted');
    const base = {
      id: `msg_${requests.length}`,
      type: 'message',
      role: 'assistant',
      model: 'claude-opus-5-5',
      stop_sequence: null,
      stop_details: null,
    };
    const tools = (body.tools ?? []) as Array<{ type?: string }>;

    if (tools.some((t) => t.type === 'web_search_20260209')) {
      const beta = String(req.headers['anthropic-beta'] ?? '');
      if (!beta.includes('server-side-fallback-2026-07-01') || body.fallbacks !== 'default')
        return bad('fallbacks expected');
      webCalls++;
      const searchBlocks = [
        {
          type: 'server_tool_use',
          id: `srvtoolu_${webCalls}`,
          name: 'web_search',
          input: { query: 'plant gift trends' },
        },
        {
          type: 'web_search_tool_result',
          tool_use_id: `srvtoolu_${webCalls}`,
          content: [
            {
              type: 'web_search_result',
              url: 'https://example.com/gift-trends',
              title: 'Gift trends 2026',
              encrypted_content: 'x',
              page_age: null,
            },
          ],
        },
      ];
      if (webCalls % 2 === 1) {
        return send(200, {
          ...base,
          content: searchBlocks,
          stop_reason: 'pause_turn',
          usage: {
            input_tokens: 1000,
            output_tokens: 100,
            server_tool_use: { web_search_requests: 1 },
          },
        });
      }
      return send(200, {
        ...base,
        stop_reason: 'end_turn',
        content: [
          ...searchBlocks,
          {
            type: 'text',
            text: 'Plant-themed gifts are trending for the holidays.',
            citations: [
              {
                type: 'web_search_result_location',
                url: 'https://example.com/gift-trends',
                title: 'Gift trends 2026',
                encrypted_index: 'e',
                cited_text: 'plant gifts',
              },
            ],
          },
        ],
        usage: {
          input_tokens: 2000,
          output_tokens: 300,
          server_tool_use: { web_search_requests: 1 },
        },
      });
    }

    const format = (body.output_config as { format?: { type?: string } } | undefined)?.format;
    if (format?.type === 'json_schema') {
      if (mode.analysis === 'refusal') {
        return send(200, {
          ...base,
          content: [],
          stop_reason: 'refusal',
          stop_details: { type: 'refusal', category: 'cyber', explanation: 'test' },
          usage: { input_tokens: 10, output_tokens: 0 },
        });
      }
      return send(200, {
        ...base,
        stop_reason: 'end_turn',
        content: [{ type: 'text', text: JSON.stringify(STUB_ANALYSIS) }],
        usage: { input_tokens: 5000, output_tokens: 1500 },
      });
    }
    return bad('unexpected request shape');
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((r) => server.close(() => r())),
    requests,
    mode,
  };
}
