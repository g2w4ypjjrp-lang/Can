import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { pino } from 'pino';
import { createHmac } from 'node:crypto';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL } from '../../helpers/env.js';
import {
  startPrintifyStub,
  PRINTIFY_TOKEN,
  PRINTIFY_SHOP_ID,
  type PrintifyStub,
} from '../../helpers/printify-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
const SECRET = 'f'.repeat(40);
let stub: PrintifyStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

async function waitFor<T>(
  fn: () => Promise<T | null | undefined | false>,
  ms = 15_000,
): Promise<T> {
  const end = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error('timeout');
    await new Promise((r) => setTimeout(r, 150));
  }
}
const syncCount = async () =>
  (
    await pool.query(
      `select count(*)::int n from public.automation_jobs where job_name = 'printify.sync-store' and store_id = $1 and status = 'succeeded'`,
      [storeId],
    )
  ).rows[0].n;

beforeAll(async () => {
  stub = await startPrintifyStub();
  app = await startTestApi({
    PRINTIFY_API_TOKEN: PRINTIFY_TOKEN,
    PRINTIFY_API_BASE_URL: stub.url,
    PRINTIFY_WEBHOOK_SECRET: SECRET,
    API_PUBLIC_URL: 'https://api.example.test',
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
      etsy: null,
      fetchImpl: fetch,
      sleep: async () => undefined,
      printify: {
        token: PRINTIFY_TOKEN,
        baseUrl: stub.url,
        fetchImpl: fetch,
        sleep: async () => undefined,
      },
    },
  });
  const o = await createAuthUser(pool, 'P Owner');
  const v = await createAuthUser(pool, 'P Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Printify shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
    [storeId, viewer.id],
  );
  // Etsy-side data this Printify data links to (as imported in Phase 2)
  await pool.query(
    `insert into public.listings (store_id, etsy_listing_id, title, state) values ($1, 900002, 'Mug listing', 'active')`,
    [storeId],
  );
  const ord = await pool.query(
    `insert into public.orders (store_id, etsy_receipt_id, status, currency, subtotal, grand_total, placed_at) values ($1, 1002, 'paid', 'USD', 39.98, 39.98, now()) returning id`,
    [storeId],
  );
  await pool.query(
    `insert into public.order_items (order_id, store_id, listing_id, etsy_transaction_id, title, quantity, unit_price, currency)
     select $1, $2, l.id, 5002, 'Mug', 2, 19.99, 'USD' from public.listings l where l.store_id = $2 and l.etsy_listing_id = 900002`,
    [ord.rows[0].id, storeId],
  );
});

afterAll(async () => {
  for (const q of worker.queues) {
    for (const s of await q.getJobSchedulers()) await q.removeJobScheduler(s.key);
    await q.obliterate({ force: true }).catch(() => undefined);
  }
  await worker.close();
  await app.close();
  await stub.close();
  await pool.end();
});

describe('Printify connection', () => {
  it('is configured but not connected; only owners list shops', async () => {
    const s = await http
      .get(`/api/v1/stores/${storeId}/integrations/printify`)
      .set(auth(owner.token))
      .expect(200);
    expect(s.body).toMatchObject({
      configured: true,
      webhooksConfigured: true,
      status: 'not_connected',
    });
    await http
      .get(`/api/v1/stores/${storeId}/integrations/printify/shops`)
      .set(auth(viewer.token))
      .expect(403);
    const shops = await http
      .get(`/api/v1/stores/${storeId}/integrations/printify/shops`)
      .set(auth(owner.token))
      .expect(200);
    expect(shops.body).toContainEqual({
      id: PRINTIFY_SHOP_ID,
      title: 'My Etsy via Printify',
      salesChannel: 'etsy',
    });
  });

  it('connects, registers signed webhooks and runs the initial import', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/integrations/printify/connect`)
      .set(auth(owner.token))
      .send({ shopId: 123 })
      .expect(404);
    const r = await http
      .post(`/api/v1/stores/${storeId}/integrations/printify/connect`)
      .set(auth(owner.token))
      .send({ shopId: PRINTIFY_SHOP_ID })
      .expect(200);
    expect(r.body.warning).toBeNull();
    expect(stub.webhooks.length).toBe(11);
    expect(stub.webhooks[0]!.url).toBe(
      `https://api.example.test/api/v1/integrations/printify/webhooks/${storeId}`,
    );
    await waitFor(async () => (await syncCount()) >= 1);
  });

  it('imported products, variants, exact production and shipping costs, mockups, Etsy link', async () => {
    const list = await http
      .get(`/api/v1/stores/${storeId}/products`)
      .set(auth(owner.token))
      .expect(200);
    expect(list.body.total).toBe(2);
    const mug = list.body.items.find((p: { title: string }) => p.title === 'Custom Mug 11oz');
    expect(mug).toMatchObject({
      productType: 'Mug 11oz',
      status: 'published',
      etsyListingId: '900002',
      enabledVariants: 2,
      priceRange: ['19.99', '22.99'],
      productionCostRange: ['5.1600', '6.5000'],
    });
    expect(mug.listingId).toBeTruthy();
    const d = await http
      .get(`/api/v1/stores/${storeId}/products/${mug.id}`)
      .set(auth(owner.token))
      .expect(200);
    const v11 = d.body.variants.find((v: { title: string }) => v.title === '11oz');
    expect(v11.productionCost).toBe('5.1600');
    expect(v11.shipping).toEqual(
      expect.arrayContaining([
        { country: 'US', type: 'shipping_first_item', amount: '6.4900', currency: 'USD' },
        { country: 'DE', type: 'shipping_additional_item', amount: '5.9900', currency: 'USD' },
        {
          country: 'REST_OF_THE_WORLD',
          type: 'shipping_first_item',
          amount: '14.9900',
          currency: 'USD',
        },
      ]),
    );
    expect(d.body.images[0].url).toMatch(/printify/);
  });

  it('linked Printify orders to Etsy orders with production status, costs, tracking; detected cost basis', async () => {
    const o = await pool.query(
      `select printify_order_id, printify_status, printify_cost_total::text, printify_shipping_total::text from public.orders where store_id = $1 and etsy_receipt_id = 1002`,
      [storeId],
    );
    // line cost 1032 = 516 x 2 -> line_total basis, so the order production cost is 10.32 (not 20.64)
    expect(o.rows[0]).toEqual({
      printify_order_id: '5a96f649b2439217d070f507',
      printify_status: 'fulfilled',
      printify_cost_total: '10.3200',
      printify_shipping_total: '6.4900',
    });
    const s = await http
      .get(`/api/v1/stores/${storeId}/integrations/printify`)
      .set(auth(owner.token))
      .expect(200);
    expect(s.body).toMatchObject({
      status: 'active',
      lineCostBasis: 'line_total',
      counts: { products: 2, orders: 1 },
    });
    const li = await pool.query(
      `select production_cost::text, printify_status, product_variant_id from public.order_items where store_id = $1`,
      [storeId],
    );
    expect(li.rows[0]).toMatchObject({ production_cost: '10.3200', printify_status: 'fulfilled' });
    expect(li.rows[0].product_variant_id).toBeTruthy();
    const sh = await pool.query(
      `select tracking_number, tracking_url from public.shipments where store_id = $1`,
      [storeId],
    );
    expect(sh.rows).toEqual([
      { tracking_number: '9400PRINTIFY', tracking_url: 'https://track.example/9400PRINTIFY' },
    ]);
  });

  it('versions costs when Printify changes them and notifies', async () => {
    stub.products.get('5d39b159e7c48c000728c89f')!.variants[0]!.cost = 560;
    await http
      .post(`/api/v1/stores/${storeId}/integrations/printify/sync`)
      .set(auth(viewer.token))
      .expect(403);
    const before = await syncCount();
    await http
      .post(`/api/v1/stores/${storeId}/integrations/printify/sync`)
      .set(auth(owner.token))
      .expect(202);
    await waitFor(async () => (await syncCount()) > before);
    const list = await http
      .get(`/api/v1/stores/${storeId}/products?q=Mug`)
      .set(auth(owner.token))
      .expect(200);
    const d = await http
      .get(`/api/v1/stores/${storeId}/products/${list.body.items[0].id}`)
      .set(auth(owner.token))
      .expect(200);
    expect(d.body.variants.find((v: { title: string }) => v.title === '11oz').productionCost).toBe(
      '5.6000',
    );
    expect(d.body.costHistory).toContainEqual(
      expect.objectContaining({ variant: '11oz', cost_type: 'production', amount: '5.1600' }),
    );
    const n = await pool.query(
      `select 1 from public.notifications where user_id = $1 and type = 'printify.cost_changed'`,
      [owner.id],
    );
    expect(n.rowCount).toBe(1);
  });
});

describe('provider comparison (catalog)', () => {
  it('searches the cached catalog and compares providers by shipping to the destination', async () => {
    const bp = await http
      .get(`/api/v1/stores/${storeId}/printify/catalog/blueprints?q=mug`)
      .set(auth(viewer.token))
      .expect(200);
    expect(bp.body).toEqual([expect.objectContaining({ id: 68, title: 'Mug 11oz' })]);
    const callsBefore = stub.calls.filter((c) => c.path === '/v1/catalog/blueprints.json').length;
    await http
      .get(`/api/v1/stores/${storeId}/printify/catalog/blueprints?q=tee`)
      .set(auth(viewer.token))
      .expect(200);
    expect(stub.calls.filter((c) => c.path === '/v1/catalog/blueprints.json').length).toBe(
      callsBefore,
    ); // cached
    const cmp = await http
      .get(`/api/v1/stores/${storeId}/printify/catalog/blueprints/68/providers?country=US`)
      .set(auth(viewer.token))
      .expect(200);
    expect(
      cmp.body.providers.map((p: { title: string; shipping: { firstItem: string } }) => [
        p.title,
        p.shipping.firstItem,
      ]),
    ).toEqual([
      ['Monster Digital', '4.75'],
      ['SPOKE Custom Products', '6.49'],
    ]);
    expect(cmp.body.note).toMatch(/Üretim maliyeti katalogda yok/);
    const row = await http
      .get(`/api/v1/stores/${storeId}/printify/catalog/blueprints/68/providers?country=JP`)
      .set(auth(viewer.token))
      .expect(200);
    expect(row.body.providers[0].shipping.country).toBe('REST_OF_THE_WORLD');
  });
});

describe('Profit Engine on Printify products', () => {
  const tee = async () =>
    (
      await http
        .get(`/api/v1/stores/${storeId}/products?q=Retro`)
        .set(auth(owner.token))
        .expect(200)
    ).body.items[0];

  it('refuses to evaluate/publish until the seller country is set', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/products/${(await tee()).id}/publish-requests`)
      .set(auth(owner.token))
      .send({ reason: 'test' })
      .expect(409);
    expect(r.body.message).toMatch(/Kârlılık hesaplanamadı/);
    await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(owner.token))
      .send({ sellerCountry: 'US', payoutCurrency: 'USD' })
      .expect(200);
  });

  it('computes per-variant contribution with real Printify costs (28.00 tee -> 9.29 needs approval)', async () => {
    const id = (await tee()).id;
    const p = await http
      .get(`/api/v1/stores/${storeId}/products/${id}/profitability?country=US`)
      .set(auth(viewer.token))
      .expect(200);
    // 28.00 - (0.20 + 1.82 + 0.84 + 0.25) - 10.85 - 4.75
    expect(p.body.variants[0].result).toMatchObject({
      contribution: '9.2900',
      decision: 'needs_approval',
      complete: true,
      feesVerified: false,
    });
    expect(p.body.variants[0].recommendation).toMatchObject({
      minimumUnitPrice: '28.79',
      suggestedUnitPrice: '28.99',
    });
    expect(p.body.variants[0].shippingRegion).toBe('US');
    const jp = await http
      .get(`/api/v1/stores/${storeId}/products/${id}/profitability?country=JP`)
      .set(auth(viewer.token))
      .expect(200);
    expect(jp.body.variants[0].shippingRegion).toBe('REST_OF_THE_WORLD');
    expect(jp.body.worstDecision).toBe('rejected'); // 14.99 world shipping makes it a loss
  });

  it('price recommendation -> approval -> Printify variant prices updated (all variants sent)', async () => {
    const id = (await tee()).id;
    const recs = await http
      .post(`/api/v1/stores/${storeId}/products/${id}/price-recommendations?country=US`)
      .set(auth(owner.token))
      .expect(201);
    expect(recs.body).toEqual([
      expect.objectContaining({ currentPrice: '28.00', recommendedPrice: '28.99' }),
    ]);
    const a = await http
      .post(`/api/v1/stores/${storeId}/products/${id}/price-change-requests`)
      .set(auth(owner.token))
      .expect(201);
    expect(a.body).toMatchObject({
      actionType: 'change_price',
      requiresReauth: true,
      apiOperation: expect.stringContaining('PUT /v1/shops'),
    });
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${a.body.id}/approve`)
      .set(auth(await signTestToken(owner.id)))
      .send({})
      .expect(200);
    const done = await waitFor(async () => {
      const r = await pool.query(
        `select status, execution_result from public.approval_requests where id = $1`,
        [a.body.id],
      );
      return ['executed', 'failed'].includes(r.rows[0].status) ? r.rows[0] : null;
    });
    expect(done).toMatchObject({
      status: 'executed',
      execution_result: { updatedVariants: 1, republished: false },
    });
    expect(stub.updates.at(-1)).toEqual({
      productId: '6e4ac260f8d59d000839d9a0',
      body: { variants: [{ id: 12100, price: 2899, is_enabled: true }] },
    });
    const st = await pool.query(
      `select status from public.price_recommendations where approval_request_id = $1`,
      [a.body.id],
    );
    expect(st.rows).toEqual([{ status: 'applied' }]);
  });

  it('refuses to publish a loss-making product for that market', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/products/${(await tee()).id}/publish-requests`)
      .set(auth(owner.token))
      .send({ reason: 'Japonya', country: 'JP' })
      .expect(409);
    expect(r.body.details).toEqual({ decision: 'rejected' });
  });
});

describe('publishing to Etsy requires approval', () => {
  it('creates an approval and only publishes after (re-authenticated) approval', async () => {
    const list = await http
      .get(`/api/v1/stores/${storeId}/products?q=Retro`)
      .set(auth(owner.token))
      .expect(200);
    const tee = list.body.items[0];
    await http
      .post(`/api/v1/stores/${storeId}/products/${tee.id}/publish-requests`)
      .set(auth(viewer.token))
      .send({ reason: 'yeni ürün' })
      .expect(403);
    const a = await http
      .post(`/api/v1/stores/${storeId}/products/${tee.id}/publish-requests`)
      .set(auth(owner.token))
      .send({ reason: 'Yeni koleksiyon' });
    expect(a.status).toBe(201);
    expect(a.body).toMatchObject({
      actionType: 'publish_product',
      requiresReauth: true,
      riskLevel: 'high',
      apiOperation: expect.stringContaining('publish.json'),
      profitImpact: expect.stringContaining('10.85'),
    });
    expect(stub.published).toEqual([]);
    await http
      .post(`/api/v1/stores/${storeId}/products/${tee.id}/publish-requests`)
      .set(auth(owner.token))
      .send({ reason: 'again' })
      .expect(409);
    const fresh = await signTestToken(owner.id);
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${a.body.id}/approve`)
      .set(auth(fresh))
      .send({})
      .expect(200);
    const done = await waitFor(async () => {
      const r = await pool.query(
        `select status, execution_result from public.approval_requests where id = $1`,
        [a.body.id],
      );
      return ['executed', 'failed'].includes(r.rows[0].status) ? r.rows[0] : null;
    });
    expect(done.status).toBe('executed');
    expect(stub.published).toEqual(['6e4ac260f8d59d000839d9a0']);
  });
});

describe('Printify webhooks', () => {
  const sign = (body: string) =>
    `sha256=${createHmac('sha256', SECRET).update(body).digest('hex')}`;
  it('rejects unsigned / badly signed deliveries', async () => {
    const body = JSON.stringify({ id: 'evt-x', type: 'order:updated', resource: {} });
    await http
      .post(`/api/v1/integrations/printify/webhooks/${storeId}`)
      .set('Content-Type', 'application/json')
      .send(body)
      .expect(401);
    await http
      .post(`/api/v1/integrations/printify/webhooks/${storeId}`)
      .set('Content-Type', 'application/json')
      .set('X-Pfy-Signature', sign(body + ' '))
      .send(body)
      .expect(401);
  });
  it('stores a valid event once, ignores duplicates and triggers a re-sync', async () => {
    const body = JSON.stringify({
      id: 'evt-1',
      type: 'order:shipment:created',
      created_at: new Date().toISOString(),
      resource: { id: 'o1', type: 'order', data: {} },
    });
    const before = await syncCount();
    const r1 = await http
      .post(`/api/v1/integrations/printify/webhooks/${storeId}`)
      .set('Content-Type', 'application/json')
      .set('X-Pfy-Signature', sign(body))
      .send(body)
      .expect(200);
    expect(r1.body).toEqual({ ok: true });
    const r2 = await http
      .post(`/api/v1/integrations/printify/webhooks/${storeId}`)
      .set('Content-Type', 'application/json')
      .set('X-Pfy-Signature', sign(body))
      .send(body)
      .expect(200);
    expect(r2.body).toEqual({ ok: true, duplicate: true });
    await waitFor(async () => {
      const e = await pool.query(
        `select processed_at from public.webhook_events where event_id = 'evt-1'`,
      );
      return e.rows[0]?.processed_at;
    });
    await waitFor(async () => (await syncCount()) > before);
  });
});
