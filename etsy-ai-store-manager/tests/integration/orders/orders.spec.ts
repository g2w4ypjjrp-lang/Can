import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { pino } from 'pino';
import { TokenCipher } from '@esm/integrations';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL, TEST_TOKEN_KEY } from '../../helpers/env.js';
import { startEtsyStub, STUB_APP, STUB_SHOP_ID, type EtsyStub } from '../../helpers/etsy-stub.js';
import { startAnthropicStub, type AnthropicStub } from '../../helpers/anthropic-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';

// Etsy and Claude are contract stubs (tests/helpers/*-stub.ts).
const REDIRECT_URI = 'http://api.test/api/v1/integrations/etsy/callback';
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
const S = () => `/api/v1/stores/${storeId}`;
const orderId = async (receipt: number) =>
  (
    await pool.query(`select id from public.orders where store_id = $1 and etsy_receipt_id = $2`, [
      storeId,
      receipt,
    ])
  ).rows[0].id as string;
const approval = async (id: string) =>
  (
    await pool.query(
      `select status, execution_result from public.approval_requests where id = $1`,
      [id],
    )
  ).rows[0];

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

beforeAll(async () => {
  await pool.query(`update public.stores set external_shop_id = null where external_shop_id = $1`, [
    String(STUB_SHOP_ID),
  ]);
  etsy = await startEtsyStub({ listingCount: 3 });
  ai = await startAnthropicStub();
  const etsyEnv = {
    ETSY_KEYSTRING: STUB_APP.keystring,
    ETSY_SHARED_SECRET: STUB_APP.sharedSecret,
    ETSY_REDIRECT_URI: REDIRECT_URI,
    ETSY_CONNECT_URL: `${etsy.url}/oauth/connect`,
    ETSY_TOKEN_URL: `${etsy.url}/v3/public/oauth/token`,
    ETSY_API_BASE_URL: etsy.url,
  };
  app = await startTestApi({ ...etsyEnv, ANTHROPIC_API_KEY: 'sk-ant-test' });
  http = request(app.getHttpServer());
  worker = await startWorker({
    databaseUrl: TEST_DATABASE_URL,
    redisUrl: TEST_REDIS_URL,
    concurrency: 2,
    heartbeatEveryMs: 3_600_000,
    logger: pino({ level: 'silent' }),
    deps: {
      cipher: new TokenCipher(1, { 1: TEST_TOKEN_KEY }),
      etsy: {
        ...STUB_APP,
        redirectUri: REDIRECT_URI,
        tokenUrl: etsyEnv.ETSY_TOKEN_URL,
        apiBaseUrl: etsy.url,
      },
      fetchImpl: fetch,
      sleep: async () => undefined,
      anthropic: { apiKey: 'sk-ant-test', baseURL: ai.url },
    },
  });
  const o = await createAuthUser(pool, 'Orders Owner');
  const v = await createAuthUser(pool, 'Orders Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Orders shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1,$2,'viewer')`,
    [storeId, viewer.id],
  );
  const start = await http
    .post(`${S()}/integrations/etsy/connect`)
    .set(auth(owner.token))
    .expect(200);
  const consent = await fetch(new URL(start.body.authorizeUrl), { redirect: 'manual' });
  await http
    .get(`/api/v1/integrations/etsy/callback${new URL(consent.headers.get('location')!).search}`)
    .expect(302);
  await waitFor(
    async () =>
      (await pool.query(`select count(*)::int n from public.orders where store_id = $1`, [storeId]))
        .rows[0].n === 3,
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
  await pool.query(
    `delete from public.oauth_tokens where connected_account_id in (select id from public.connected_accounts where store_id = $1)`,
    [storeId],
  );
  await pool.query(`update public.stores set external_shop_id = null where id = $1`, [storeId]);
  await pool.end();
});

describe('reviews → AI triage (drafts only)', () => {
  it('imports reviews and triages low ratings into reply drafts', async () => {
    const r = await waitFor(async () => {
      const b = (await http.get(`${S()}/reviews`).set(auth(viewer.token)).expect(200)).body;
      return b.stats.n === 2 ? b : null;
    });
    expect(r.stats).toMatchObject({ n: 2, low: 1, avg: '3.50' });
    const m = await waitFor(async () => {
      const list = (await http.get(`${S()}/messages`).set(auth(owner.token)).expect(200)).body;
      return list.find(
        (x: { source: string; status: string }) =>
          x.source === 'etsy_review' && x.status === 'draft_ready',
      );
    });
    expect(m).toMatchObject({
      rating: 2,
      category: 'complaint',
      urgency: 'high',
      suggestedAction: 'replacement',
    });
    expect(m.draft).toContain('sorry');
    await http.get(`${S()}/messages`).set(auth(viewer.token)).expect(403); // customer data: admin only
    const n = await pool.query(
      `select count(*)::int n from public.notifications where store_id = $1 and type = 'support.urgent'`,
      [storeId],
    );
    expect(n.rows[0].n).toBeGreaterThan(0);
  });
});

describe('orders, delays and tracking', () => {
  it('lists orders with filters and flags late ones', async () => {
    const all = (await http.get(`${S()}/orders`).set(auth(viewer.token)).expect(200)).body;
    expect(all.total).toBe(3);
    const unshipped = (
      await http.get(`${S()}/orders?filter=unshipped`).set(auth(viewer.token)).expect(200)
    ).body;
    expect(unshipped.items.map((o: { etsyReceiptId: string }) => o.etsyReceiptId)).toEqual([
      '1001',
    ]);
    expect(unshipped.items[0].late).toBe(false);
    await pool.query(
      `update public.orders set placed_at = now() - interval '10 days', paid_at = now() - interval '10 days' where id = $1`,
      [await orderId(1001)],
    );
    const delayed = (
      await http.get(`${S()}/orders?filter=delayed`).set(auth(viewer.token)).expect(200)
    ).body;
    expect(delayed.items.map((o: { etsyReceiptId: string }) => o.etsyReceiptId)).toEqual(['1001']);
    expect(delayed.items[0].late).toBe(true);
  });

  it('refuses tracking for Printify-fulfilled orders and missing scope; uploads after approval', async () => {
    const o1001 = await orderId(1001);
    await http
      .post(`${S()}/orders/${o1001}/tracking`)
      .set(auth(viewer.token))
      .send({ trackingCode: '9400111', carrierName: 'usps', reason: 'kargo' })
      .expect(403);
    await http
      .post(`${S()}/orders/${o1001}/tracking`)
      .set(auth(owner.token))
      .send({ trackingCode: 'x!', carrierName: 'usps', reason: 'kargo' })
      .expect(400);
    const o1003 = await orderId(1003);
    await pool.query(`update public.orders set printify_order_id = 'pf-1' where id = $1`, [o1003]);
    await http
      .post(`${S()}/orders/${o1003}/tracking`)
      .set(auth(owner.token))
      .send({ trackingCode: '9400222', carrierName: 'usps', reason: 'kargo' })
      .expect(409);

    // connection without transactions_w → execution fails with a clear message
    await pool.query(
      `update public.connected_accounts set scopes = array['shops_r','transactions_r'] where store_id = $1 and platform = 'etsy'`,
      [storeId],
    );
    const a1 = (
      await http
        .post(`${S()}/orders/${o1001}/tracking`)
        .set(auth(owner.token))
        .send({ trackingCode: '9400111', carrierName: 'usps', reason: 'kargo' })
        .expect(201)
    ).body;
    expect(a1.actionType).toBe('add_tracking');
    await http
      .post(`${S()}/approvals/${a1.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    await waitFor(async () => (await approval(a1.id)).status === 'failed');
    expect((await approval(a1.id)).execution_result.error).toContain('transactions_w');
    expect(etsy.shipmentsPosted).toHaveLength(0);

    await pool.query(
      `update public.connected_accounts set scopes = array['shops_r','listings_r','listings_w','transactions_r','transactions_w'] where store_id = $1 and platform = 'etsy'`,
      [storeId],
    );
    const a2 = (
      await http
        .post(`${S()}/orders/${o1001}/tracking`)
        .set(auth(owner.token))
        .send({
          trackingCode: '9400111',
          carrierName: 'usps',
          noteToBuyer: 'Thanks!',
          reason: 'kargo',
        })
        .expect(201)
    ).body;
    await http
      .post(`${S()}/approvals/${a2.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    await waitFor(async () => (await approval(a2.id)).status === 'executed');
    expect(etsy.shipmentsPosted[0]).toMatchObject({
      receiptId: 1001,
      tracking_code: '9400111',
      carrier_name: 'usps',
      note_to_buyer: 'Thanks!',
    });
    const d = (await http.get(`${S()}/orders/${o1001}`).set(auth(owner.token)).expect(200)).body;
    expect(d.status).toBe('shipped');
    expect(d.shipmentsDetail).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tracking_number: '9400111', source: 'etsy' }),
      ]),
    );
    // shipped orders cannot be cancelled
    await http
      .post(`${S()}/orders/${o1001}/cancel`)
      .set(auth(owner.token))
      .send({ reason: 'müşteri istedi' })
      .expect(409);
  });
});

describe('refunds (manual on Etsy, profit impact shown)', () => {
  it('blocks over-refunds and shows the contribution change', async () => {
    const o = await orderId(1002); // grand total 26.48, 5.00 already refunded on Etsy
    await waitFor(
      async () =>
        (await pool.query(`select 1 from public.profit_snapshots where order_id = $1`, [o]))
          .rowCount,
    );
    await http
      .post(`${S()}/orders/${o}/refunds`)
      .set(auth(owner.token))
      .send({ amount: '30', reason: 'kırık' })
      .expect(400);
    const a = (
      await http
        .post(`${S()}/orders/${o}/refunds`)
        .set(auth(owner.token))
        .send({ amount: '10', reason: 'kırık ürün' })
        .expect(201)
    ).body;
    expect(a.actionType).toBe('refund');
    expect(a.apiOperation).toMatch(/^MANUEL/);
    expect(a.profitImpact).toMatch(/→/);
    const ref = (
      await pool.query(
        `select contribution_before::numeric b, contribution_after::numeric a from public.refunds where approval_request_id = $1`,
        [a.id],
      )
    ).rows[0];
    expect(Number(ref.a)).toBeLessThan(Number(ref.b));
    // a partial processing-fee credit means the loss is a bit less than the refund
    expect(Number(ref.b) - Number(ref.a)).toBeGreaterThan(9);
    expect(Number(ref.b) - Number(ref.a)).toBeLessThanOrEqual(10);

    const ok = await http
      .post(`${S()}/approvals/${a.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    expect(ok.body.status).toBe('awaiting_manual');
    await http
      .post(`${S()}/approvals/${a.id}/confirm-manual`)
      .set(auth(owner.token))
      .send({ note: 'Etsy panelinde 10 USD iade edildi' })
      .expect(200);
    const d = (await http.get(`${S()}/orders/${o}`).set(auth(owner.token)).expect(200)).body;
    expect(d.status).toBe('partially_refunded');
    expect(d.refunds.find((r: { amount: string }) => r.amount === '10.0000').status).toBe(
      'processed',
    );
  });
});

describe('pasted customer messages', () => {
  it('links to the order, drafts a reply and records the approved text', async () => {
    const r = (
      await http
        .post(`${S()}/messages`)
        .set(auth(owner.token))
        .send({ body: 'Hi, when will my order ship?', receiptId: '1001' })
        .expect(201)
    ).body;
    await http
      .post(`${S()}/messages`)
      .set(auth(owner.token))
      .send({ body: 'x x', receiptId: '424242' })
      .expect(404);
    const m = await waitFor(async () =>
      (await http.get(`${S()}/messages`).set(auth(owner.token)).expect(200)).body.find(
        (x: { id: string; status: string }) => x.id === r.id && x.status === 'draft_ready',
      ),
    );
    expect(m).toMatchObject({ category: 'question', etsyReceiptId: '1001' });
    const call = ai.requests
      .filter((q) => JSON.stringify(q.body).includes('when will my order ship'))
      .at(-1)!;
    expect(JSON.stringify(call.body)).toContain('9400111'); // grounded in the real tracking number
    const a = (
      await http
        .post(`${S()}/messages/${r.id}/send`)
        .set(auth(owner.token))
        .send({ text: 'Your order shipped: USPS 9400111.' })
        .expect(201)
    ).body;
    expect(a.actionType).toBe('send_customer_message');
    await http.post(`${S()}/approvals/${a.id}/approve`).set(auth(owner.token)).send({}).expect(200);
    await http
      .post(`${S()}/approvals/${a.id}/confirm-manual`)
      .set(auth(owner.token))
      .send({ note: 'Etsy Mesajlar’dan gönderildi' })
      .expect(200);
    const sent = (await http.get(`${S()}/messages?status=sent`).set(auth(owner.token)).expect(200))
      .body;
    expect(sent[0]).toMatchObject({ id: r.id, draft: 'Your order shipped: USPS 9400111.' });
  });

  it('lists customers for admins only', async () => {
    await http.get(`${S()}/customers`).set(auth(viewer.token)).expect(403);
    const c = (await http.get(`${S()}/customers`).set(auth(owner.token)).expect(200)).body;
    expect(c.length).toBeGreaterThan(0);
  });
});
