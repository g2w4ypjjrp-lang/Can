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
import { startMetaStub, META_ACCOUNT, META_TOKEN, type MetaStub } from '../../helpers/meta-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';
import { syncMetaAccount } from '../../../apps/worker/src/ads/sync.js';

// Etsy and Meta are contract stubs (tests/helpers/*-stub.ts).
const REDIRECT_URI = 'http://api.test/api/v1/integrations/etsy/callback';
const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let etsy: EtsyStub;
let meta: MetaStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
let metaAccountId: string;
let pinAccountId: string;
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });
const base = () => `/api/v1/stores/${storeId}/ads`;

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
const spendBy = async (source: string) =>
  (
    await pool.query(
      `select coalesce(sum(amount),0)::text s, count(*)::int n from public.ad_spend where store_id = $1 and source = $2`,
      [storeId, source],
    )
  ).rows[0];

beforeAll(async () => {
  await pool.query(`update public.stores set external_shop_id = null where external_shop_id = $1`, [
    String(STUB_SHOP_ID),
  ]);
  etsy = await startEtsyStub({ listingCount: 2 });
  meta = await startMetaStub();
  const etsyEnv = {
    ETSY_KEYSTRING: STUB_APP.keystring,
    ETSY_SHARED_SECRET: STUB_APP.sharedSecret,
    ETSY_REDIRECT_URI: REDIRECT_URI,
    ETSY_CONNECT_URL: `${etsy.url}/oauth/connect`,
    ETSY_TOKEN_URL: `${etsy.url}/v3/public/oauth/token`,
    ETSY_API_BASE_URL: etsy.url,
  };
  app = await startTestApi({ ...etsyEnv, META_GRAPH_BASE_URL: meta.url });
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
      metaBaseUrl: meta.url,
    },
  });
  const o = await createAuthUser(pool, 'Ads Owner');
  const v = await createAuthUser(pool, 'Ads Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http.post('/api/v1/stores').set(auth(owner.token)).send({ name: 'Ads shop' }).expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1,$2,'viewer')`,
    [storeId, viewer.id],
  );
  const start = await http
    .post(`/api/v1/stores/${storeId}/integrations/etsy/connect`)
    .set(auth(owner.token))
    .expect(200);
  const consent = await fetch(new URL(start.body.authorizeUrl), { redirect: 'manual' });
  await http
    .get(`/api/v1/integrations/etsy/callback${new URL(consent.headers.get('location')!).search}`)
    .expect(302);
  await waitFor(
    async () =>
      (await pool.query(`select external_shop_id from public.stores where id = $1`, [storeId]))
        .rows[0]?.external_shop_id,
  );

  // 10 orders: AOV 30, contribution before ads 15 → break-even ROAS 2.00, target ROAS 30/(15−10) = 6.00
  for (let i = 0; i < 10; i++) {
    const ord = await pool.query(
      `insert into public.orders (store_id, currency, subtotal, grand_total, placed_at) values ($1,'USD',30,30,now()) returning id`,
      [storeId],
    );
    await pool.query(
      `insert into public.profit_snapshots (store_id, order_id, scenario, currency, gross_revenue, net_revenue, total_variable_costs,
                                            contribution, contribution_before_ads, decision, breakdown, inputs, engine_version)
       values ($1,$2,'order_actual','USD',30,30,15,15,15,'excellent','{}','{}','test')`,
      [storeId, ord.rows[0].id],
    );
  }
});

afterAll(async () => {
  for (const q of worker.queues) {
    for (const s of await q.getJobSchedulers()) await q.removeJobScheduler(s.key);
    await q.obliterate({ force: true }).catch(() => undefined);
  }
  await worker.close();
  await app.close();
  await etsy.close();
  await meta.close();
  await pool.query(
    `delete from public.oauth_tokens where connected_account_id in (select id from public.connected_accounts where store_id = $1)`,
    [storeId],
  );
  await pool.query(`update public.stores set external_shop_id = null where id = $1`, [storeId]);
  await pool.end();
});

describe('budget policy (user-set caps)', () => {
  it('validates and requires admin', async () => {
    await http.put(`${base()}/policy`).set(auth(viewer.token)).send({ dailyCap: '50' }).expect(403);
    await http
      .put(`${base()}/policy`)
      .set(auth(owner.token))
      .send({ dailyCap: '50', monthlyCap: '20' })
      .expect(400);
    const r = await http
      .put(`${base()}/policy`)
      .set(auth(owner.token))
      .send({ dailyCap: '50', monthlyCap: '1200' })
      .expect(200);
    expect(r.body).toMatchObject({
      configured: true,
      dailyCap: '50.00',
      monthlyCap: '1200.00',
      minClicksForDecision: 100,
    });
  });
});

describe('Meta Ads (read-only Marketing API reporting)', () => {
  it('refuses an invalid token and stores a valid one encrypted', async () => {
    await http
      .post(`${base()}/meta/connect`)
      .set(auth(owner.token))
      .send({ adAccountId: META_ACCOUNT, accessToken: 'EAAwrong-token-xxxxxxxxxxxx' })
      .expect(400);
    const r = await http
      .post(`${base()}/meta/connect`)
      .set(auth(owner.token))
      .send({ adAccountId: `act_${META_ACCOUNT}`, accessToken: META_TOKEN })
      .expect(201);
    metaAccountId = r.body.id;
    expect(r.body.name).toBe('Botanical Ads');
    const tok = await pool.query(
      `select t.access_token_ciphertext c from public.oauth_tokens t join public.connected_accounts ca on ca.id = t.connected_account_id
        where ca.store_id = $1 and ca.platform = 'meta_ads'`,
      [storeId],
    );
    expect(tok.rows[0].c).toMatch(/^v1\./);
    expect(tok.rows[0].c).not.toContain(META_TOKEN);
    const audit = await pool.query(
      `select after::text a from public.audit_logs where store_id = $1 and action = 'ads.meta.connect'`,
      [storeId],
    );
    expect(audit.rows[0].a).not.toContain(META_TOKEN);
  });

  it('imports daily campaign insights across pages and books spend once', async () => {
    await waitFor(async () => (await spendBy('api_report')).n === 6);
    expect((await spendBy('api_report')).s).toBe('90.0000');
    const insights = meta.calls.filter((c) => c.path.endsWith('/insights'));
    expect(insights[0]!.query).toMatchObject({ level: 'campaign', time_increment: '1' });
    expect(insights.some((c) => c.query.after === 'cursor1')).toBe(true);
    // a second sync rewrites the same rows (idempotent, no double booking)
    const again = await syncMetaAccount(
      pool,
      {
        cipher: new TokenCipher(1, { 1: TEST_TOKEN_KEY }),
        etsy: null,
        fetchImpl: fetch,
        metaBaseUrl: meta.url,
      },
      metaAccountId,
    );
    expect(again).toMatchObject({
      rows: 6,
      campaignsWithoutPurchaseAction: ['Mugs - retargeting'],
    });
    expect(await spendBy('api_report')).toEqual({ s: '90.0000', n: 6 });
    const conv = await pool.query(
      `select sum(m.conversions)::text c, sum(m.conversion_value)::text v from public.ad_metrics m
         join public.ad_campaigns c on c.id = m.campaign_id where c.name = 'Botanical tees - prospecting' and m.store_id = $1`,
      [storeId],
    );
    expect(conv.rows[0]).toEqual({ c: '9.00', v: '270.0000' });
  });

  it('refuses CSV import into an API-reported account (double counting)', async () => {
    await http
      .post(`${base()}/metrics/import`)
      .set(auth(owner.token))
      .send({
        adAccountId: metaAccountId,
        rows: [{ date: '2026-11-01', campaign: 'x', spend: '1' }],
      })
      .expect(409);
  });
});

describe('manual / CSV platforms', () => {
  it('imports rows idempotently', async () => {
    pinAccountId = (
      await http
        .post(`${base()}/accounts`)
        .set(auth(owner.token))
        .send({ platform: 'pinterest_ads', externalAccountId: '549', name: 'Pins' })
        .expect(201)
    ).body.id;
    const d = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
    const rows = [
      {
        date: d,
        campaign: 'Pins test',
        impressions: 900,
        clicks: 50,
        spend: '5.00',
        orders: '0',
        revenue: '0',
      },
      {
        date: d,
        campaign: 'Winner',
        impressions: 4000,
        clicks: 200,
        spend: '10.00',
        orders: '3',
        revenue: '90.00',
      },
    ];
    for (let i = 0; i < 2; i++)
      await http
        .post(`${base()}/metrics/import`)
        .set(auth(owner.token))
        .send({ adAccountId: pinAccountId, rows })
        .expect(201);
    expect(await spendBy('csv_import')).toEqual({ s: '15.0000', n: 2 });
  });
});

describe('overview, recommendations and budget split', () => {
  let proposalId: string;

  it('derives break-even / target ROAS from real order contribution and judges campaigns', async () => {
    const o = (await http.get(`${base()}/overview?days=30`).set(auth(viewer.token)).expect(200))
      .body;
    expect(o.economics).toMatchObject({
      aov: '30.00',
      contributionBeforeAds: '15.00',
      breakEvenRoas: '2',
      targetRoas: '6',
      maxCpa: '5.00',
    });
    const v = Object.fromEntries(
      o.campaigns.map((c: { name: string; verdict: string }) => [c.name, c.verdict]),
    );
    expect(v).toEqual({
      'Botanical tees - prospecting': 'below_target', // ROAS 4.5
      'Mugs - retargeting': 'unprofitable', // ROAS 0
      Winner: 'scale', // ROAS 9 ≥ 6 × 1.3
      'Pins test': 'insufficient_data', // 50 < 100 clicks
    });
  });

  it('never proposes more than the cap', async () => {
    await http
      .post(`${base()}/proposals`)
      .set(auth(owner.token))
      .send({ totalDailyBudget: '60' })
      .expect(400);
    const p = (await http.post(`${base()}/proposals`).set(auth(owner.token)).send({}).expect(201))
      .body;
    proposalId = p.id;
    const a = Object.fromEntries(
      p.allocations.map((x: { name: string; proposedDailyBudget: string }) => [
        x.name,
        x.proposedDailyBudget,
      ]),
    );
    expect(a).toEqual({
      'Botanical tees - prospecting': '13.33',
      'Mugs - retargeting': '0.00',
      Winner: '26.66',
      'Pins test': '10.00',
    });
    const sum = p.allocations.reduce(
      (s: number, x: { proposedDailyBudget: string }) => s + Number(x.proposedDailyBudget),
      0,
    );
    expect(sum).toBeLessThanOrEqual(50);
  });

  it('goes through approval, then waits for the owner to apply it manually', async () => {
    const appr = (
      await http
        .post(`${base()}/proposals/${proposalId}/submit`)
        .set(auth(owner.token))
        .send({ reason: 'Haftalık dağıtım' })
        .expect(201)
    ).body;
    expect(appr.actionType).toBe('increase_ad_budget');
    expect(appr.apiOperation).toMatch(/^MANUEL/);
    expect(appr.requiresReauth).toBe(true);
    const ok = await http
      .post(`/api/v1/stores/${storeId}/approvals/${appr.id}/approve`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    expect(ok.body.status).toBe('awaiting_manual');
    await new Promise((r) => setTimeout(r, 300));
    const before = await pool.query(
      `select daily_budget from public.ad_campaigns where store_id = $1 and name = 'Winner'`,
      [storeId],
    );
    expect(before.rows[0].daily_budget).toBeNull(); // nothing changes before confirmation
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${appr.id}/confirm-manual`)
      .set(auth(owner.token))
      .send({ note: '' })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${appr.id}/confirm-manual`)
      .set(auth(viewer.token))
      .send({ note: 'yaptım' })
      .expect(403);
    const done = await http
      .post(`/api/v1/stores/${storeId}/approvals/${appr.id}/confirm-manual`)
      .set(auth(owner.token))
      .send({ note: 'Pinterest ve Meta panelinde uygulandı' })
      .expect(200);
    expect(done.body.status).toBe('executed');
    const c = await pool.query(
      `select name, daily_budget::text b, status from public.ad_campaigns where store_id = $1 order by name`,
      [storeId],
    );
    expect(c.rows).toEqual(
      expect.arrayContaining([
        { name: 'Mugs - retargeting', b: '0.00', status: 'paused' },
        { name: 'Winner', b: '26.66', status: 'active' },
      ]),
    );
    const p = (await http.get(`${base()}/proposals`).set(auth(owner.token)).expect(200)).body;
    expect(p.find((x: { id: string }) => x.id === proposalId).status).toBe('applied');
  });
});

describe('Etsy Ads spend from the Etsy payment ledger', () => {
  it('refuses Offsite Ads (an order fee, counted in the Profit Engine)', async () => {
    await http
      .put(`${base()}/etsy-ledger/mapping`)
      .set(auth(owner.token))
      .send({ types: ['offsite_ads_fee'] })
      .expect(400);
  });

  it('imports the ledger, suggests ad types and books mapped debits as spend', async () => {
    await http
      .put(`${base()}/etsy-ledger/mapping`)
      .set(auth(owner.token))
      .send({ types: ['PROLIST'] })
      .expect(200);
    const t = await waitFor(async () => {
      const r = (await http.get(`${base()}/etsy-ledger/types`).set(auth(owner.token)).expect(200))
        .body;
      return r.types.length ? r : null;
    });
    expect(t.mapped).toEqual(['PROLIST']);
    const byType = Object.fromEntries(
      t.types.map((x: { ledgerType: string; suggested: boolean; total: string }) => [
        x.ledgerType,
        x,
      ]),
    );
    expect(byType.PROLIST).toMatchObject({ suggested: true, total: '-7.5000' });
    expect(byType.offsite_ads_fee.suggested).toBe(false);
    await waitFor(async () => (await spendBy('platform_invoice')).n === 2);
    expect((await spendBy('platform_invoice')).s).toBe('7.5000');
    await http.get(`${base()}/etsy-ledger/types`).set(auth(viewer.token)).expect(403);
  });
});
