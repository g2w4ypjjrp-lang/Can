import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { pino } from 'pino';
import { TokenCipher } from '@esm/integrations';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL, TEST_TOKEN_KEY } from '../../helpers/env.js';
import { startEtsyStub, STUB_APP, type EtsyStub } from '../../helpers/etsy-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
const REDIRECT_URI = 'http://api.test/api/v1/integrations/etsy/callback';
let stub: EtsyStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let owner: { id: string; token: string };
let stranger: { id: string; token: string };
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

beforeAll(async () => {
  stub = await startEtsyStub({ listingCount: 102 });
  const etsyEnv = {
    ETSY_KEYSTRING: STUB_APP.keystring,
    ETSY_SHARED_SECRET: STUB_APP.sharedSecret,
    ETSY_REDIRECT_URI: REDIRECT_URI,
    ETSY_CONNECT_URL: `${stub.url}/oauth/connect`,
    ETSY_TOKEN_URL: `${stub.url}/v3/public/oauth/token`,
    ETSY_API_BASE_URL: stub.url,
  };
  app = await startTestApi(etsyEnv);
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
        apiBaseUrl: stub.url,
      },
      fetchImpl: fetch,
      sleep: async () => undefined,
    },
  });
  for (const [k, name] of [
    ['o', 'Owner'],
    ['s', 'Stranger'],
    ['v', 'Viewer'],
  ] as const) {
    const u = await createAuthUser(pool, name);
    const t = { id: u.id, token: await signTestToken(u.id) };
    if (k === 'o') owner = t;
    else if (k === 's') stranger = t;
    else viewer = t;
  }
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Etsy test shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
    [storeId, viewer.id],
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

describe('Etsy connection (OAuth 2.0 + PKCE)', () => {
  it('reports configuration and unsupported operations honestly', async () => {
    const r = await http
      .get(`/api/v1/stores/${storeId}/integrations/etsy`)
      .set(auth(owner.token))
      .expect(200);
    expect(r.body).toMatchObject({
      configured: true,
      status: 'not_connected',
      counts: { listings: 0, orders: 0 },
    });
    expect(Object.keys(r.body.unsupportedOperations)).toEqual(
      expect.arrayContaining(['ads_campaigns', 'buyer_messages', 'issue_refund', 'cancel_order']),
    );
  });

  it('only the owner can start the connection; others get 403/404', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/integrations/etsy/connect`)
      .set(auth(viewer.token))
      .expect(403);
    await http
      .post(`/api/v1/stores/${storeId}/integrations/etsy/connect`)
      .set(auth(stranger.token))
      .expect(404);
  });

  it('rejects a callback with an unknown state', async () => {
    const r = await http
      .get('/api/v1/integrations/etsy/callback?code=abc&state=forged')
      .expect(302);
    expect(r.headers.location).toMatch(/\/dashboard\/etsy\?error=/);
  });

  it('completes the flow, stores encrypted tokens and imports the shop', async () => {
    const start = await http
      .post(`/api/v1/stores/${storeId}/integrations/etsy/connect`)
      .set(auth(owner.token))
      .expect(200);
    const authorizeUrl = new URL(start.body.authorizeUrl);
    expect(authorizeUrl.searchParams.get('code_challenge_method')).toBe('S256');
    expect(start.body.authorizeUrl).not.toContain(STUB_APP.sharedSecret);

    // user approves on "Etsy" -> redirected to our callback
    const consent = await fetch(authorizeUrl, { redirect: 'manual' });
    const callback = new URL(consent.headers.get('location')!);
    expect(callback.origin + callback.pathname).toBe(REDIRECT_URI);
    const cb = await http.get(`/api/v1/integrations/etsy/callback${callback.search}`).expect(302);
    expect(cb.headers.location).toBe('http://localhost:3000/dashboard/etsy?connected=1');

    // replaying the same state must fail (single use)
    const replay = await http
      .get(`/api/v1/integrations/etsy/callback${callback.search}`)
      .expect(302);
    expect(replay.headers.location).toMatch(/error=/);

    const tok = await pool.query(
      `select t.access_token_ciphertext, t.refresh_token_ciphertext, t.expires_at from public.oauth_tokens t
         join public.connected_accounts ca on ca.id = t.connected_account_id where ca.store_id = $1`,
      [storeId],
    );
    expect(tok.rows[0].access_token_ciphertext).toMatch(/^v1\./);
    expect(tok.rows[0].access_token_ciphertext).not.toContain('77001.');

    const store = await pool.query(
      `select status, external_shop_id, shop_url from public.stores where id = $1`,
      [storeId],
    );
    expect(store.rows[0]).toEqual({
      status: 'connected',
      external_shop_id: '55001',
      shop_url: 'https://www.etsy.com/shop/StubCeramics',
    });

    // initial sync is queued automatically and processed by the worker
    await waitFor(async () => {
      const r = await pool.query(
        `select last_synced_at from public.connected_accounts where store_id = $1`,
        [storeId],
      );
      return r.rows[0]?.last_synced_at;
    });
  });

  it('imported all listings across pages (101 active + 1 draft) with images', async () => {
    const all = await http
      .get(`/api/v1/stores/${storeId}/listings?limit=200`)
      .set(auth(owner.token))
      .expect(200);
    expect(all.body.total).toBe(102);
    const drafts = await http
      .get(`/api/v1/stores/${storeId}/listings?state=draft`)
      .set(auth(owner.token))
      .expect(200);
    expect(drafts.body.total).toBe(1);
    const one = all.body.items.find((l: { etsyListingId: string }) => l.etsyListingId === '900001');
    expect(one).toMatchObject({
      price: '24.51',
      currency: 'USD',
      dataOrigin: 'live',
      tags: ['ceramic mug', 'gift'],
    });
    expect(one.primaryImageUrl).toMatch(/etsystatic/);
  });

  it('imported receipts with exact money, VAT, shipments and refunds (no buyer e-mail)', async () => {
    const o = await pool.query(
      `select etsy_receipt_id, status, subtotal::text, shipping_total::text, tax_total::text, discount_total::text,
              grand_total::text, buyer_country from public.orders where store_id = $1 order by etsy_receipt_id`,
      [storeId],
    );
    expect(o.rows).toEqual([
      {
        etsy_receipt_id: '1001',
        status: 'paid',
        subtotal: '49.0000',
        shipping_total: '5.9900',
        tax_total: '9.8000',
        discount_total: '4.9000',
        grand_total: '59.8900',
        buyer_country: 'DE',
      },
      {
        etsy_receipt_id: '1002',
        status: 'shipped',
        subtotal: '24.5200',
        shipping_total: '0.0000',
        tax_total: '1.9600',
        discount_total: '0.0000',
        grand_total: '26.4800',
        buyer_country: 'US',
      },
      {
        etsy_receipt_id: '1003',
        status: 'cancelled',
        subtotal: '24.5300',
        shipping_total: '0.0000',
        tax_total: '0.0000',
        discount_total: '0.0000',
        grand_total: '24.5300',
        buyer_country: 'US',
      },
    ]);
    const items = await pool.query(
      `select oi.quantity, oi.unit_price::text, l.etsy_listing_id from public.order_items oi
         left join public.listings l on l.id = oi.listing_id where oi.store_id = $1 order by oi.etsy_transaction_id`,
      [storeId],
    );
    expect(items.rows[0]).toEqual({
      quantity: 2,
      unit_price: '24.5100',
      etsy_listing_id: '900001',
    });
    expect(
      (
        await pool.query(`select tracking_number from public.shipments where store_id = $1`, [
          storeId,
        ])
      ).rows,
    ).toEqual([{ tracking_number: '9400TEST' }]);
    expect(
      (
        await pool.query(`select amount::text, status from public.refunds where store_id = $1`, [
          storeId,
        ])
      ).rows,
    ).toEqual([{ amount: '5.0000', status: 'processed' }]);
    const c = await pool.query(
      `select email, total_orders from public.customers where store_id = $1 order by etsy_user_id`,
      [storeId],
    );
    expect(c.rows.every((r) => r.email === null)).toBe(true);
    expect(c.rows[0].total_orders).toBe(1);
  });

  it('dashboard now shows live data computed from imported orders', async () => {
    const d = await http
      .get(`/api/v1/stores/${storeId}/dashboard`)
      .set(auth(owner.token))
      .expect(200);
    expect(d.body.dataOrigin).toBe('live');
    // revenue excludes tax and cancelled orders: (59.89-9.80) + (26.48-1.96)
    expect(d.body.kpis.revenueMonth).toBe('74.6100');
    expect(
      d.body.integrations.find((i: { platform: string }) => i.platform === 'etsy').status,
    ).toBe('active');
  });

  it('re-sync is idempotent and refreshes an expired access token', async () => {
    const issuedBefore = stub.issuedAccessTokens();
    stub.expireAllAccessTokens();
    await pool.query(`update public.oauth_tokens set expires_at = now() - interval '1 minute'`);
    await http
      .post(`/api/v1/stores/${storeId}/integrations/etsy/sync`)
      .set(auth(owner.token))
      .expect(202);
    await waitFor(async () => {
      const r = await pool.query(
        `select count(*)::int n from public.automation_jobs where job_name = 'etsy.sync-store' and store_id = $1 and status = 'succeeded'`,
        [storeId],
      );
      return r.rows[0].n >= 2;
    });
    expect(stub.issuedAccessTokens()).toBe(issuedBefore + 1);
    const counts = await pool.query(
      `select (select count(*) from public.listings where store_id = $1)::int l, (select count(*) from public.orders where store_id = $1)::int o,
              (select count(*) from public.order_items where store_id = $1)::int i, (select count(*) from public.refunds where store_id = $1)::int r`,
      [storeId],
    );
    expect(counts.rows[0]).toEqual({ l: 102, o: 3, i: 3, r: 1 });
    const logs = await pool.query(
      `select count(*)::int n from public.api_logs where store_id = $1 and provider = 'etsy'`,
      [storeId],
    );
    expect(logs.rows[0].n).toBeGreaterThan(5);
  });

  it('viewers cannot trigger sync; strangers cannot see listings', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/integrations/etsy/sync`)
      .set(auth(viewer.token))
      .expect(403);
    await http.get(`/api/v1/stores/${storeId}/listings`).set(auth(stranger.token)).expect(404);
  });
});

describe('listing changes require approval and never overwrite Etsy edits', () => {
  let listingId: string;

  beforeAll(async () => {
    const r = await pool.query(
      `select id from public.listings where store_id = $1 and etsy_listing_id = '900005'`,
      [storeId],
    );
    listingId = r.rows[0].id;
  });

  it('creates an approval request with what/why/cost/profit impact/API operation; nothing is sent yet', async () => {
    const before = stub.calls.filter((c) => c.method === 'PATCH').length;
    const r = await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/change-requests`)
      .set(auth(owner.token))
      .send({
        title: 'Handmade Ceramic Mug – Personalized Gift',
        tags: ['ceramic mug', 'personalized gift'],
        reason: 'Daha iyi arama eşleşmesi',
      })
      .expect(201);
    expect(r.body).toMatchObject({
      status: 'pending',
      actionType: 'update_listing',
      why: 'Daha iyi arama eşleşmesi',
      estimatedCost: '0.0000',
      apiOperation: expect.stringContaining(
        'PATCH /v3/application/shops/{shop_id}/listings/{listing_id}',
      ),
      profitImpact: expect.any(String),
      requiresReauth: true,
    });
    expect(r.body.payload.baseline.title).toBe('Handmade Ceramic Mug 5');
    expect(stub.calls.filter((c) => c.method === 'PATCH').length).toBe(before);
    // a second pending request for the same listing is refused
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/change-requests`)
      .set(auth(owner.token))
      .send({ title: 'Other', reason: 'again please' })
      .expect(409);
  });

  it('viewers cannot propose or approve', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/change-requests`)
      .set(auth(viewer.token))
      .send({ title: 'x y', reason: 'viewer try' })
      .expect(403);
  });

  it('requires a recent re-authentication to approve, then executes only the changed fields', async () => {
    const pending = await http
      .get(`/api/v1/stores/${storeId}/approvals?status=pending`)
      .set(auth(owner.token))
      .expect(200);
    const approval = pending.body[0];
    const staleToken = await signTestToken(owner.id, { expiresIn: '10m' });
    // simulate a session that authenticated 10 minutes ago
    const { SignJWT } = await import('jose');
    const old = await new SignJWT({ role: 'authenticated' })
      .setProtectedHeader({ alg: 'HS256' })
      .setSubject(owner.id)
      .setIssuer('http://supabase.test/auth/v1')
      .setAudience('authenticated')
      .setIssuedAt(Math.floor(Date.now() / 1000) - 600)
      .setExpirationTime('5m')
      .sign(new TextEncoder().encode('test-only-jwt-secret-with-enough-length-0123456789'));
    const denied = await http
      .post(`/api/v1/stores/${storeId}/approvals/${approval.id}/approve`)
      .set(auth(old))
      .send({})
      .expect(403);
    expect(denied.body.details).toEqual({ reauthRequired: true });

    const listingBefore = { ...stub.listings.get(900005)! };
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${approval.id}/approve`)
      .set(auth(staleToken))
      .send({ note: 'ok' })
      .expect(200);
    const done = await waitFor(async () => {
      const r = await pool.query(
        `select status, execution_result from public.approval_requests where id = $1`,
        [approval.id],
      );
      return ['executed', 'failed'].includes(r.rows[0].status) ? r.rows[0] : null;
    });
    expect(done.status).toBe('executed');
    expect([...done.execution_result.updatedFields].sort()).toEqual(['tags', 'title']);
    const after = stub.listings.get(900005)!;
    expect(after.title).toBe('Handmade Ceramic Mug – Personalized Gift');
    expect(after.tags).toEqual(['ceramic mug', 'personalized gift']);
    // untouched fields preserved on Etsy
    expect({
      d: after.description,
      p: after.price,
      q: after.quantity,
      s: after.state,
      m: after.materials,
    }).toEqual({
      d: listingBefore.description,
      p: listingBefore.price,
      q: listingBefore.quantity,
      s: listingBefore.state,
      m: listingBefore.materials,
    });
    const local = await http
      .get(`/api/v1/stores/${storeId}/listings/${listingId}`)
      .set(auth(owner.token))
      .expect(200);
    expect(local.body.title).toBe('Handmade Ceramic Mug – Personalized Gift');
    // approving twice is impossible
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${approval.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(409);
  });

  it('refuses to apply a change when the listing was edited on Etsy in the meantime', async () => {
    const r = await pool.query(
      `select id from public.listings where store_id = $1 and etsy_listing_id = '900006'`,
      [storeId],
    );
    const req = await http
      .post(`/api/v1/stores/${storeId}/listings/${r.rows[0].id}/change-requests`)
      .set(auth(owner.token))
      .send({ description: 'New description from the platform', reason: 'Açıklama iyileştirme' })
      .expect(201);
    stub.listings.get(900006)!.description = 'Seller edited this directly on Etsy';
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${req.body.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    const done = await waitFor(async () => {
      const x = await pool.query(
        `select status, execution_result from public.approval_requests where id = $1`,
        [req.body.id],
      );
      return ['executed', 'failed'].includes(x.rows[0].status) ? x.rows[0] : null;
    });
    expect(done.status).toBe('failed');
    expect(done.execution_result.conflicts).toEqual(['description']);
    expect(stub.listings.get(900006)!.description).toBe('Seller edited this directly on Etsy');
    const n = await pool.query(
      `select title from public.notifications where user_id = $1 and type = 'approval.failed'`,
      [owner.id],
    );
    expect(n.rowCount).toBe(1);
  });

  it('rejecting keeps Etsy untouched', async () => {
    const r = await pool.query(
      `select id from public.listings where store_id = $1 and etsy_listing_id = '900007'`,
      [storeId],
    );
    const req = await http
      .post(`/api/v1/stores/${storeId}/listings/${r.rows[0].id}/change-requests`)
      .set(auth(owner.token))
      .send({ state: 'inactive', reason: 'Sezon dışı' })
      .expect(201);
    const rej = await http
      .post(`/api/v1/stores/${storeId}/approvals/${req.body.id}/reject`)
      .set(auth(owner.token))
      .send({ note: 'hayır' })
      .expect(200);
    expect(rej.body.status).toBe('rejected');
    expect(stub.listings.get(900007)!.state).toBe('active');
  });
});

describe('disconnect', () => {
  it('deletes tokens, keeps imported data, and marks the store disconnected', async () => {
    await http
      .delete(`/api/v1/stores/${storeId}/integrations/etsy`)
      .set(auth(viewer.token))
      .expect(403);
    const r = await http
      .delete(`/api/v1/stores/${storeId}/integrations/etsy`)
      .set(auth(owner.token))
      .expect(200);
    expect(r.body.note).toMatch(/Etsy hesap ayarlarınızdan/);
    expect((await pool.query(`select count(*)::int n from public.oauth_tokens`)).rows[0].n).toBe(0);
    expect(
      (
        await pool.query(`select count(*)::int n from public.listings where store_id = $1`, [
          storeId,
        ])
      ).rows[0].n,
    ).toBe(102);
    const s = await http
      .get(`/api/v1/stores/${storeId}/integrations/etsy`)
      .set(auth(owner.token))
      .expect(200);
    expect(s.body.status).toBe('revoked');
  });
});
