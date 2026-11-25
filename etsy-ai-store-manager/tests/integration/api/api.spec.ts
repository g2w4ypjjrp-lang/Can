import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL } from '../../helpers/env.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let app: INestApplication;
let http: ReturnType<typeof request>;
let owner: { id: string; token: string };
let stranger: { id: string; token: string };
let storeId: string;

beforeAll(async () => {
  app = await startTestApi();
  http = request(app.getHttpServer());
  const o = await createAuthUser(pool, 'Owner');
  const s = await createAuthUser(pool, 'Stranger');
  owner = { id: o.id, token: await signTestToken(o.id) };
  stranger = { id: s.id, token: await signTestToken(s.id) };
});
afterAll(async () => {
  await app.close();
  await pool.end();
});

const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

describe('API: authentication & hardening', () => {
  it('serves health publicly with a request id', async () => {
    const r = await http.get('/api/v1/health').expect(200);
    expect(r.body.status).toBe('ok');
    expect(r.headers['x-request-id']).toBeTruthy();
  });
  it('reports readiness of database and redis', async () => {
    const r = await http.get('/api/v1/health/ready').expect(200);
    expect(r.body.checks).toEqual({ database: 'ok', redis: 'ok' });
  });
  it('rejects requests without / with invalid tokens', async () => {
    await http.get('/api/v1/me').expect(401);
    await http.get('/api/v1/me').set(auth('garbage')).expect(401);
    const forged = await signTestToken(owner.id, {
      secret: 'forged-secret-forged-secret-forged-secret',
    });
    await http.get('/api/v1/me').set(auth(forged)).expect(401);
  });
  it('sets security headers and hides the framework', async () => {
    const r = await http.get('/api/v1/health');
    expect(r.headers['x-powered-by']).toBeUndefined();
    expect(r.headers['x-content-type-options']).toBe('nosniff');
    expect(r.headers['strict-transport-security']).toBeTruthy();
  });
  it('exposes the OpenAPI document', async () => {
    const r = await http.get('/docs/openapi.json').expect(200);
    expect(Object.keys(r.body.paths)).toEqual(
      expect.arrayContaining([
        '/api/v1/me',
        '/api/v1/stores',
        '/api/v1/stores/{storeId}/profit-rules',
      ]),
    );
  });
});

describe('API: me & personal settings', () => {
  it('returns the provisioned profile', async () => {
    const r = await http.get('/api/v1/me').set(auth(owner.token)).expect(200);
    expect(r.body).toMatchObject({
      id: owner.id,
      fullName: 'Owner',
      settings: { uiLanguage: 'tr', baseCurrency: 'USD' },
    });
  });
  it('updates settings with validation and writes an audit log', async () => {
    const r = await http
      .patch('/api/v1/me/settings')
      .set(auth(owner.token))
      .send({ baseCurrency: 'eur', notifyPush: true, fullName: 'Shop Owner' })
      .expect(200);
    expect(r.body.settings.baseCurrency).toBe('EUR');
    expect(r.body.fullName).toBe('Shop Owner');
    const a = await pool.query(
      `select action, request_id from public.audit_logs where actor_user_id = $1 and action = 'user_settings.update'`,
      [owner.id],
    );
    expect(a.rowCount).toBe(1);
    expect(a.rows[0].request_id).toBeTruthy();
  });
  it('rejects unknown fields (mass assignment)', async () => {
    const r = await http
      .patch('/api/v1/me/settings')
      .set(auth(owner.token))
      .send({ id: 'x', role: 'admin' })
      .expect(400);
    expect(r.body.message).toBe('Doğrulama hatası');
  });
});

describe('API: stores, settings and profit rules', () => {
  it('creates a store that starts as not_connected', async () => {
    const r = await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'My Etsy Shop' })
      .expect(201);
    expect(r.body).toMatchObject({
      name: 'My Etsy Shop',
      status: 'not_connected',
      role: 'owner',
      currency: 'USD',
      dataOrigin: 'live',
    });
    storeId = r.body.id;
    const list = await http.get('/api/v1/stores').set(auth(owner.token)).expect(200);
    expect(list.body.map((s: { id: string }) => s.id)).toContain(storeId);
  });

  it('hides the store from other users (404, not 403, to avoid enumeration)', async () => {
    await http.get(`/api/v1/stores/${storeId}`).set(auth(stranger.token)).expect(404);
    await http.get(`/api/v1/stores/${storeId}/profit-rules`).set(auth(stranger.token)).expect(404);
    await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(stranger.token))
      .send({ dailyAdBudgetCap: '1000.00' })
      .expect(404);
    const list = await http.get('/api/v1/stores').set(auth(stranger.token)).expect(200);
    expect(list.body).toEqual([]);
  });

  it('validates path ids', async () => {
    await http.get('/api/v1/stores/not-a-uuid').set(auth(owner.token)).expect(400);
  });

  it('returns default profit rules (10 USD target; 15/10/7/0)', async () => {
    const r = await http
      .get(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(owner.token))
      .expect(200);
    expect(r.body).toMatchObject({
      currency: 'USD',
      targetContribution: '10.00',
      excellentThreshold: '15.00',
      publishThreshold: '10.00',
      reviewThreshold: '7.00',
      minThreshold: '0.00',
    });
  });

  it('lets the owner change thresholds and keeps exact decimals', async () => {
    const r = await http
      .patch(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(owner.token))
      .send({
        targetContribution: '12.50',
        publishThreshold: '12.50',
        excellentThreshold: '18',
        returnReserveRate: '0.0300',
      })
      .expect(200);
    expect(r.body).toMatchObject({
      targetContribution: '12.50',
      publishThreshold: '12.50',
      excellentThreshold: '18.00',
      returnReserveRate: '0.0300',
    });
  });

  it('rejects an inconsistent threshold order', async () => {
    const r = await http
      .patch(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(owner.token))
      .send({ reviewThreshold: '13' })
      .expect(400);
    expect(r.body.message).toMatch(/Yayınlanabilir/);
  });

  it('updates store settings (languages, ad budget cap)', async () => {
    const r = await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(owner.token))
      .send({
        languages: ['en', 'de', 'fr'],
        targetMarkets: ['US', 'DE', 'FR'],
        dailyAdBudgetCap: '20.00',
      })
      .expect(200);
    expect(r.body).toMatchObject({
      languages: ['en', 'de', 'fr'],
      dailyAdBudgetCap: '20.00',
      salesStrategy: 'balanced',
      automationLevel: 'controlled',
    });
  });

  it('refuses removing the default language from the list', async () => {
    await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(owner.token))
      .send({ languages: ['de'] })
      .expect(400);
  });

  it('returns 403 for a viewer trying to change settings', async () => {
    const viewer = await createAuthUser(pool, 'Viewer');
    await pool.query(
      `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
      [storeId, viewer.id],
    );
    const token = await signTestToken(viewer.id);
    await http.get(`/api/v1/stores/${storeId}/settings`).set(auth(token)).expect(200);
    await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(token))
      .send({ dailyAdBudgetCap: '500.00' })
      .expect(403);
    await http
      .patch(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(token))
      .send({ minThreshold: '1' })
      .expect(403);
  });

  it('records audit logs with before/after for settings changes', async () => {
    const r = await pool.query(
      `select before, after from public.audit_logs where store_id = $1 and action = 'profit_rules.update' order by id`,
      [storeId],
    );
    expect(r.rowCount).toBe(1);
    expect(r.rows[0].before.targetContribution).toBe('10.00');
    expect(r.rows[0].after.targetContribution).toBe('12.50');
  });
});

describe('API: dashboard (real data only)', () => {
  it('reports no data for an unconnected store instead of inventing numbers', async () => {
    const r = await http
      .get(`/api/v1/stores/${storeId}/dashboard`)
      .set(auth(owner.token))
      .expect(200);
    expect(r.body.dataOrigin).toBe('none');
    expect(r.body.kpis).toMatchObject({
      revenueToday: '0',
      revenueMonth: '0',
      ordersMonth: 0,
      averageOrderValue: null,
      roas: null,
    });
    expect(r.body.dailyRevenue).toHaveLength(30);
    expect(
      r.body.integrations.find((i: { platform: string }) => i.platform === 'etsy').status,
    ).toBe('not_connected');
    expect(r.body.notes.join(' ')).toMatch(/henüz bağlanmadı/);
  });

  it('aggregates real orders exactly (decimal strings) and excludes cancelled/tax', async () => {
    await pool.query(`update public.stores set status = 'connected' where id = $1`, [storeId]);
    const now = new Date().toISOString();
    await pool.query(
      `insert into public.orders (store_id, status, currency, subtotal, shipping_total, tax_total, grand_total, buyer_country, placed_at)
       values ($1,'paid','USD',25.10,4.99,2.00,32.09,'US',$2),
              ($1,'shipped','USD',19.99,0,0,19.99,'DE',$2),
              ($1,'cancelled','USD',100,0,0,100,'US',$2)`,
      [storeId, now],
    );
    await pool.query(
      `insert into public.ad_accounts (store_id, platform, external_account_id) values ($1, 'etsy_ads', 'acc') `,
      [storeId],
    );
    await pool.query(
      `insert into public.ad_spend (store_id, ad_account_id, spend_date, amount, currency, source)
       select $1, id, current_date, 10, 'USD', 'manual' from public.ad_accounts where store_id = $1`,
      [storeId],
    );
    const r = await http
      .get(`/api/v1/stores/${storeId}/dashboard?days=7`)
      .set(auth(owner.token))
      .expect(200);
    expect(r.body.dataOrigin).toBe('live');
    expect(r.body.kpis.revenueMonth).toBe('50.0800'); // 30.09 + 19.99, tax and cancelled excluded
    expect(r.body.kpis.ordersMonth).toBe(2);
    expect(r.body.kpis.averageOrderValue).toBe('25.04');
    expect(r.body.kpis.adSpendMonth).toBe('10.0000');
    expect(r.body.kpis.roas).toBe('5.01');
    expect(r.body.dailyRevenue).toHaveLength(7);
    expect(r.body.countrySales.map((c: { country: string }) => c.country)).toEqual(['US', 'DE']);
  });

  it('rejects invalid ranges and other tenants', async () => {
    await http.get(`/api/v1/stores/${storeId}/dashboard?days=0`).set(auth(owner.token)).expect(400);
    await http.get(`/api/v1/stores/${storeId}/dashboard`).set(auth(stranger.token)).expect(404);
  });
});

describe('API: notifications', () => {
  it('lists and marks own notifications only', async () => {
    const n = await pool.query(
      `insert into public.notifications (user_id, type, title) values ($1, 'test', 'Hello') returning id`,
      [owner.id],
    );
    const list = await http
      .get('/api/v1/notifications?unread=true')
      .set(auth(owner.token))
      .expect(200);
    expect(list.body.map((x: { id: string }) => x.id)).toContain(n.rows[0].id);
    await http
      .post(`/api/v1/notifications/${n.rows[0].id}/read`)
      .set(auth(stranger.token))
      .expect(404);
    await http
      .post(`/api/v1/notifications/${n.rows[0].id}/read`)
      .set(auth(owner.token))
      .expect(204);
    const after = await http
      .get('/api/v1/notifications?unread=true')
      .set(auth(owner.token))
      .expect(200);
    expect(after.body.map((x: { id: string }) => x.id)).not.toContain(n.rows[0].id);
  });
});

describe('API: rate limiting', () => {
  it('returns 429 after the configured per-minute limit', async () => {
    const limited = await startTestApi({ RATE_LIMIT_PER_MINUTE: '3' });
    try {
      const h = request(limited.getHttpServer());
      for (let i = 0; i < 3; i++) await h.get('/api/v1/me').set(auth(owner.token)).expect(200);
      await h.get('/api/v1/me').set(auth(owner.token)).expect(429);
    } finally {
      await limited.close();
    }
  });
});
