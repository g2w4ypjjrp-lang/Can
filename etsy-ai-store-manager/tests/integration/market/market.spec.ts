import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { pino } from 'pino';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL } from '../../helpers/env.js';
import { startEtsyStub, STUB_APP, type EtsyStub } from '../../helpers/etsy-stub.js';
import { startAnthropicStub, type AnthropicStub } from '../../helpers/anthropic-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';
import { runMarketResearch, scoreOpportunity } from '../../../apps/worker/src/market/research.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let etsy: EtsyStub;
let ai: AnthropicStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

async function waitFor<T>(
  fn: () => Promise<T | null | undefined | false>,
  ms = 20_000,
): Promise<T> {
  const end = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error('timeout');
    await new Promise((r) => setTimeout(r, 150));
  }
}

const etsyApp = () => ({ ...STUB_APP, redirectUri: 'http://x/cb', apiBaseUrl: etsy.url });

beforeAll(async () => {
  etsy = await startEtsyStub({ listingCount: 3 });
  ai = await startAnthropicStub();
  app = await startTestApi({
    ETSY_KEYSTRING: STUB_APP.keystring,
    ETSY_SHARED_SECRET: STUB_APP.sharedSecret,
    ETSY_REDIRECT_URI: 'http://x/cb',
    ETSY_API_BASE_URL: etsy.url,
    ANTHROPIC_API_KEY: 'sk-ant-test',
  });
  http = request(app.getHttpServer());
  worker = await startWorker({
    databaseUrl: TEST_DATABASE_URL,
    redisUrl: TEST_REDIS_URL,
    concurrency: 2,
    heartbeatEveryMs: 3_600_000,
    logger: pino({ level: 'silent' }),
    deps: {
      cipher: null,
      etsy: etsyApp(),
      fetchImpl: fetch,
      anthropic: { apiKey: 'sk-ant-test', baseURL: ai.url },
    },
  });
  const o = await createAuthUser(pool, 'M Owner');
  const v = await createAuthUser(pool, 'M Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Market shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
    [storeId, viewer.id],
  );
  await http
    .patch(`/api/v1/stores/${storeId}/settings`)
    .set(auth(owner.token))
    .send({ sellerCountry: 'US', payoutCurrency: 'USD' })
    .expect(200);
  await pool.query(
    `insert into public.fx_rates (base, quote, rate, as_of, source) values ('EUR','USD',1.08,'2026-11-25','ECB') on conflict do nothing`,
  );
  // existing Printify mug with known costs (production 5.16, US shipping 6.49)
  const p = await pool.query(
    `insert into public.products (store_id, title, product_type, status) values ($1,'Mug','Mug 11oz','published') returning id`,
    [storeId],
  );
  const v2 = await pool.query(
    `insert into public.product_variants (product_id, store_id, title, price) values ($1,$2,'11oz',19.99) returning id`,
    [p.rows[0].id, storeId],
  );
  await pool.query(
    `insert into public.product_costs (product_variant_id, store_id, cost_type, amount, currency, destination_country, source)
     values ($1,$2,'production',5.16,'USD',null,'printify_api'), ($1,$2,'shipping_first_item',6.49,'USD','US','printify_api')`,
    [v2.rows[0].id, storeId],
  );
});

afterAll(async () => {
  for (const q of worker.queues) {
    for (const s of await q.getJobSchedulers()) await q.removeJobScheduler(s.key);
    await q.obliterate({ force: true }).catch(() => undefined);
  }
  await worker.close();
  await app.close();
  await etsy.close();
  await ai.close();
  await pool.end();
});

describe('opportunity score', () => {
  it('is deterministic and explainable', () => {
    const a = scoreOpportunity({
      activeListings: 12500,
      avgFavorers: 22.5,
      contribution: '10.5160',
      target: '10',
      ipRisk: 'low',
    });
    expect(a.score).toBeGreaterThan(0);
    expect(a.breakdown).toMatchObject({ ipPenalty: 0 });
    const b = scoreOpportunity({
      activeListings: 12500,
      avgFavorers: 22.5,
      contribution: '10.5160',
      target: '10',
      ipRisk: 'high',
    });
    expect(a.score - b.score).toBeCloseTo(40, 5);
    expect(
      scoreOpportunity({
        activeListings: 100,
        avgFavorers: 22.5,
        contribution: '10',
        target: '10',
        ipRisk: 'low',
      }).score,
    ).toBeGreaterThan(
      scoreOpportunity({
        activeListings: 500000,
        avgFavorers: 22.5,
        contribution: '10',
        target: '10',
        ipRisk: 'low',
      }).score,
    );
  });
});

describe('market research end to end (API -> queue -> worker -> Etsy + Claude)', () => {
  let researchId: string;

  it('only admins start research; reports capabilities', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/market-research`)
      .set(auth(viewer.token))
      .send({ query: 'plant mug' })
      .expect(403);
    await http
      .post(`/api/v1/stores/${storeId}/market-research`)
      .set(auth(owner.token))
      .send({ query: 'x' })
      .expect(400);
    const r = await http
      .post(`/api/v1/stores/${storeId}/market-research`)
      .set(auth(owner.token))
      .send({
        query: 'plant mug',
        buyerCountry: 'US',
        keywords: ['gardener gift'],
        useWebSearch: true,
      })
      .expect(201);
    expect(r.body).toMatchObject({
      status: 'queued',
      capabilities: { etsyMarketData: true, aiAnalysis: true },
    });
    researchId = r.body.id;
    await waitFor(
      async () =>
        (await pool.query(`select status from public.market_research where id = $1`, [researchId]))
          .rows[0].status === 'completed',
    );
  });

  it('stored REAL Etsy facts: supply count, USD price distribution (FX converted), competitors', async () => {
    const d = await http
      .get(`/api/v1/stores/${storeId}/market-research/${researchId}`)
      .set(auth(viewer.token))
      .expect(200);
    const facts = d.body.research.summary.facts;
    expect(facts.map((f: { keyword: string }) => f.keyword)).toEqual([
      'plant mug',
      'gardener gift',
    ]);
    expect(facts[0]).toMatchObject({
      activeListings: 12500,
      sampleSize: 150,
      newListingsShare90d: 0.67,
    });
    expect(facts[0].priceUsd).toMatchObject({ min: 15.1 }); // EUR listings converted with ECB rate
    expect(facts[0].topTags[0]).toEqual({ tag: 'plant mug', count: 150 });
    expect(d.body.competitors).toHaveLength(20);
    expect(
      d.body.competitors.every(
        (c: { source: string; is_estimate: boolean }) => c.source === 'etsy_api' && !c.is_estimate,
      ),
    ).toBe(true);
    // public search sends only the API key, never an OAuth token
    expect(
      etsy.calls
        .filter((c) => c.path === '/v3/application/listings/active')
        .every((c) => c.status === 200),
    ).toBe(true);
  });

  it('called Claude correctly: web search with pause_turn resume + fallbacks, then structured output', async () => {
    const web = ai.requests.filter((r) => (r.body.tools as unknown[] | undefined)?.length);
    expect(web).toHaveLength(2); // paused once, resumed
    const resumed = web[1]!.body.messages as Array<{ role: string }>;
    expect(resumed.map((m) => m.role)).toEqual(['user', 'assistant']);
    const parse = ai.requests.find((r) => (r.body.output_config as { format?: unknown })?.format);
    expect(parse?.body.system).toMatch(/Never state or imply sales volumes/);
    expect(JSON.stringify(parse?.body.messages)).toContain('12500');
    const t = await pool.query(
      `select status, input_tokens, output_tokens, cost_usd::text from public.ai_tasks where store_id = $1`,
      [storeId],
    );
    // (1000+2000+5000) in, (100+300+1500) out at $4/$20 per MTok
    expect(t.rows[0]).toEqual({
      status: 'succeeded',
      input_tokens: 8000,
      output_tokens: 1900,
      cost_usd: '0.070000',
    });
  });

  it('created opportunities with Profit Engine contribution, deterministic score and auto-rejections', async () => {
    const d = await http
      .get(`/api/v1/stores/${storeId}/market-research/${researchId}`)
      .set(auth(owner.token))
      .expect(200);
    const byTitle = Object.fromEntries(
      d.body.opportunities.map((o: { title: string }) => [o.title, o]),
    );
    // 24.99 − (0.20 + 1.62435 + 0.7497 + 0.25) − 5.16 − 6.49 = 10.51595
    expect(byTitle['Botanical Line-Art Plant Mom Mug']).toMatchObject({
      estContribution: '10.52',
      estDecision: 'publishable',
      status: 'new',
      productType: 'Mug',
      isEstimate: true,
      confidence: 'medium',
      estProductionCost: '5.16',
    });
    const signals = byTitle['Botanical Line-Art Plant Mom Mug'].demandSignals;
    expect(
      signals.find((s: { source: string }) => s.source === 'https://example.com/gift-trends'),
    ).toBeTruthy();
    expect(signals.find((s: { signal: string }) => s.signal === 'Uydurma kaynak')).toMatchObject({
      source: 'unverified',
      isEstimate: true,
    });
    expect(byTitle['Cheap Novelty Mug']).toMatchObject({
      estDecision: 'not_recommended',
      status: 'new',
    });
    expect(byTitle['Famous Wizard Fan Mug']).toMatchObject({
      status: 'rejected',
      rejectionReason: 'Yüksek fikri mülkiyet riski',
    });
    expect(byTitle['Botanical Line-Art Plant Mom Mug'].score).toBeGreaterThan(
      byTitle['Cheap Novelty Mug'].score,
    );
    expect(byTitle['Botanical Line-Art Plant Mom Mug'].scoreBreakdown.formula).toMatch(/kâr/);
  });

  it('opportunities can be listed, shortlisted and rejected (admin only)', async () => {
    const list = await http
      .get(`/api/v1/stores/${storeId}/opportunities?minScore=1`)
      .set(auth(viewer.token))
      .expect(200);
    expect(list.body[0].title).toBe('Botanical Line-Art Plant Mom Mug');
    await http
      .patch(`/api/v1/stores/${storeId}/opportunities/${list.body[0].id}`)
      .set(auth(viewer.token))
      .send({ status: 'shortlisted' })
      .expect(403);
    const s = await http
      .patch(`/api/v1/stores/${storeId}/opportunities/${list.body[0].id}`)
      .set(auth(owner.token))
      .send({ status: 'shortlisted' })
      .expect(200);
    expect(s.body.status).toBe('shortlisted');
    const sl = await http
      .get(`/api/v1/stores/${storeId}/opportunities?status=shortlisted`)
      .set(auth(owner.token))
      .expect(200);
    expect(sl.body).toHaveLength(1);
  });
});

describe('degraded and failure modes', () => {
  const create = async (useWebSearch = false) => {
    const r = await pool.query(
      `insert into public.market_research (store_id, query, region, buyer_country, use_web_search, created_by) values ($1,'test query','US','US',$2,$3) returning id`,
      [storeId, useWebSearch, owner.id],
    );
    return r.rows[0].id as string;
  };
  it('without an Anthropic key only real Etsy data is stored and no opportunities are invented', async () => {
    const id = await create();
    const out = await runMarketResearch(
      pool,
      { etsy: etsyApp(), anthropic: null, fetchImpl: fetch },
      id,
    );
    expect(out).toMatchObject({ opportunities: 0 });
    expect(out.notes.join(' ')).toMatch(/ANTHROPIC_API_KEY yok/);
    const r = await pool.query(
      `select status, confidence from public.market_research where id = $1`,
      [id],
    );
    expect(r.rows[0]).toEqual({ status: 'completed', confidence: 'medium' });
  });
  it('a model refusal fails the task cleanly (recorded), without partial opportunities', async () => {
    ai.mode.analysis = 'refusal';
    const id = await create();
    await expect(
      runMarketResearch(
        pool,
        {
          etsy: etsyApp(),
          anthropic: { apiKey: 'sk-ant-test', baseURL: ai.url },
          fetchImpl: fetch,
        },
        id,
      ),
    ).rejects.toThrow(/reddetti/);
    const t = await pool.query(
      `select status, error from public.ai_tasks where idempotency_key = $1`,
      [`market_research:${id}`],
    );
    expect(t.rows[0].status).toBe('failed');
    expect(
      (
        await pool.query(
          `select count(*)::int n from public.product_opportunities where market_research_id = $1`,
          [id],
        )
      ).rows[0].n,
    ).toBe(0);
    ai.mode.analysis = 'ok';
  });
});
