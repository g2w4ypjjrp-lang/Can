import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL } from '../../helpers/env.js';
import { recomputeOrderSnapshots } from '../../../apps/worker/src/finance/recompute.js';
import { parseEcbXml, refreshFxRates } from '../../../apps/worker/src/finance/fx.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let app: INestApplication;
let http: ReturnType<typeof request>;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

const ECB = `<?xml version="1.0"?><gesmes:Envelope><Cube><Cube time='2026-11-25'>
<Cube currency='USD' rate='1.0800'/><Cube currency='GBP' rate='0.8400'/><Cube currency='TRY' rate='37.0000'/></Cube></Cube></gesmes:Envelope>`;

beforeAll(async () => {
  app = await startTestApi();
  http = request(app.getHttpServer());
  const o = await createAuthUser(pool, 'F Owner');
  const v = await createAuthUser(pool, 'F Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Finance shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
    [storeId, viewer.id],
  );
});
afterAll(async () => {
  await app.close();
  await pool.end();
});

describe('FX reference rates (ECB)', () => {
  it('parses the ECB format and stores rates idempotently', async () => {
    expect(parseEcbXml(ECB)).toEqual({
      asOf: '2026-11-25',
      rates: { USD: '1.0800', GBP: '0.8400', TRY: '37.0000' },
    });
    const fakeFetch = (async () => new Response(ECB, { status: 200 })) as typeof fetch;
    expect(await refreshFxRates(pool, fakeFetch)).toMatchObject({ currencies: 3 });
    expect((await refreshFxRates(pool, fakeFetch)).inserted).toBe(0);
  });
});

describe('fee rules', () => {
  it('lists the seeded Etsy rules with source and NO verification yet', async () => {
    const r = await http
      .get(`/api/v1/stores/${storeId}/finance/fee-rules`)
      .set(auth(viewer.token))
      .expect(200);
    expect(r.body.length).toBe(26);
    expect(
      r.body.every(
        (x: { verifiedAt: string | null; sourceUrl: string }) =>
          x.verifiedAt === null && x.sourceUrl.startsWith('https://help.etsy.com/'),
      ),
    ).toBe(true);
    const tr = r.body.find(
      (x: { feeType: string; country: string }) =>
        x.feeType === 'payment_processing' && x.country === 'TR',
    );
    expect(tr).toMatchObject({
      rate: '0.065000',
      fixed: '14.0000 TRY',
      basis: 'order_total_incl_tax',
    });
  });

  it('only admins verify; verification is per store', async () => {
    const rules = (
      await http.get(`/api/v1/stores/${storeId}/finance/fee-rules`).set(auth(owner.token))
    ).body;
    for (const id of rules
      .filter(
        (x: { feeType: string; country: string | null }) =>
          ['listing', 'transaction'].includes(x.feeType) ||
          (x.feeType === 'payment_processing' && x.country === 'US'),
      )
      .map((x: { id: string }) => x.id)) {
      await http
        .post(`/api/v1/stores/${storeId}/finance/fee-rules/${id}/verify`)
        .set(auth(viewer.token))
        .send({})
        .expect(403);
      await http
        .post(`/api/v1/stores/${storeId}/finance/fee-rules/${id}/verify`)
        .set(auth(owner.token))
        .send({ note: 'Etsy ekstresiyle karşılaştırıldı' })
        .expect(200);
    }
    const after = (
      await http.get(`/api/v1/stores/${storeId}/finance/fee-rules`).set(auth(owner.token))
    ).body;
    expect(after.filter((x: { verifiedAt: string | null }) => x.verifiedAt).length).toBe(3);
    // another store does not inherit this store's verification
    const other = (await http.post('/api/v1/stores').set(auth(owner.token)).send({ name: 'Other' }))
      .body.id;
    const o = (await http.get(`/api/v1/stores/${other}/finance/fee-rules`).set(auth(owner.token)))
      .body;
    expect(o.filter((x: { verifiedAt: string | null }) => x.verifiedAt).length).toBe(0);
  });
});

describe('simulation', () => {
  it('requires seller settings for a complete result', async () => {
    const body = {
      unitPrice: '29.99',
      productionCostPerUnit: '10.85',
      fulfillmentShippingFirst: '4.75',
      buyerCountry: 'US',
    };
    const r = await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(viewer.token))
      .send(body)
      .expect(200);
    expect(r.body.result.complete).toBe(false);
    expect(r.body.result.warnings.join(' ')).toMatch(/Satıcı \(banka\) ülkesi/);
    await http
      .patch(`/api/v1/stores/${storeId}/settings`)
      .set(auth(owner.token))
      .send({ sellerCountry: 'US', payoutCurrency: 'USD' })
      .expect(200);
    const ok = await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(viewer.token))
      .send(body)
      .expect(200);
    expect(ok.body.result).toMatchObject({
      contribution: '11.0910',
      decision: 'publishable',
      complete: true,
      feesVerified: true,
    });
    expect(ok.body.recommendation).toMatchObject({
      minimumUnitPrice: '28.79',
      suggestedUnitPrice: '28.99',
    });
    expect(ok.body.fxAsOf).toBeTruthy();
  });

  it('uses the store policy (thresholds, reserves, VAT on fees) after changes', async () => {
    await http
      .patch(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(owner.token))
      .send({ returnReserveRate: '0.0500', vatOnFeesRate: '0.2000' })
      .expect(200);
    const r = await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(owner.token))
      .send({
        unitPrice: '29.99',
        productionCostPerUnit: '10.85',
        fulfillmentShippingFirst: '4.75',
        buyerCountry: 'US',
      })
      .expect(200);
    // 11.09095 − 1.4995 (5% reserve) − 0.65981 (20% VAT on 3.29905) = 8.93164
    expect(r.body.result.contribution).toBe('8.9316');
    expect(r.body.result.decision).toBe('needs_approval');
    await http
      .patch(`/api/v1/stores/${storeId}/profit-rules`)
      .set(auth(owner.token))
      .send({ returnReserveRate: '0', vatOnFeesRate: '0' })
      .expect(200);
  });

  it('validates input and saves snapshots only for admins', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(owner.token))
      .send({ unitPrice: '-1', productionCostPerUnit: '1', buyerCountry: 'US' })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(viewer.token))
      .send({ unitPrice: '20', productionCostPerUnit: '5', buyerCountry: 'US', save: true })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/finance/simulate`)
      .set(auth(owner.token))
      .send({ unitPrice: '20', productionCostPerUnit: '5', buyerCountry: 'US', save: true })
      .expect(200);
    const n = await pool.query(
      `select count(*)::int n from public.profit_snapshots where store_id = $1 and scenario = 'simulation'`,
      [storeId],
    );
    expect(n.rows[0].n).toBe(1);
  });
});

describe('actual order contribution and P&L', () => {
  it('computes order_actual snapshots with Printify actual costs, refunds and ad allocation; P&L counts ad spend once', async () => {
    const now = new Date();
    const mk = async (
      receipt: number,
      subtotal: string,
      extra: { pcost?: string; pship?: string; refund?: string } = {},
    ) => {
      const o = await pool.query(
        `insert into public.orders (store_id, etsy_receipt_id, status, currency, subtotal, shipping_total, tax_total, discount_total, grand_total,
                                    buyer_country, placed_at, printify_cost_total, printify_shipping_total, printify_currency)
         values ($1,$2,'paid','USD',$3,0,0,0,$3,'US',$4,$5,$6,'USD') returning id`,
        [storeId, receipt, subtotal, now, extra.pcost ?? null, extra.pship ?? null],
      );
      await pool.query(
        `insert into public.order_items (order_id, store_id, title, quantity, unit_price, currency) values ($1,$2,'Mug',1,$3,'USD')`,
        [o.rows[0].id, storeId, subtotal],
      );
      if (extra.refund)
        await pool.query(
          `insert into public.refunds (order_id, store_id, amount, currency, status) values ($1,$2,$3,'USD','processed')`,
          [o.rows[0].id, storeId, extra.refund],
        );
      return o.rows[0].id;
    };
    await mk(7001, '29.99', { pcost: '10.85', pship: '4.75' });
    await mk(7002, '29.99', { pcost: '10.85', pship: '4.75', refund: '10.00' });
    await mk(7003, '29.99'); // no Printify link and no variant -> incomplete
    const acc = await pool.query(
      `insert into public.ad_accounts (store_id, platform, external_account_id) values ($1,'etsy_ads','a1') returning id`,
      [storeId],
    );
    await pool.query(
      `insert into public.ad_spend (store_id, ad_account_id, spend_date, amount, currency, source) values ($1,$2,current_date,9,'USD','manual')`,
      [storeId, acc.rows[0].id],
    );

    const res = await recomputeOrderSnapshots(pool, storeId);
    expect(res).toEqual({ computed: 3, incomplete: 1 });
    const again = await recomputeOrderSnapshots(pool, storeId); // replaces, does not duplicate
    expect(again.computed).toBe(3);
    const snaps = await pool.query(
      `select o.etsy_receipt_id, ps.contribution_before_ads::text, ps.ad_cost_allocated::text, ps.contribution::text, ps.complete
         from public.profit_snapshots ps join public.orders o on o.id = ps.order_id
        where ps.store_id = $1 and ps.scenario = 'order_actual' order by o.etsy_receipt_id`,
      [storeId],
    );
    expect(snaps.rows).toEqual([
      {
        etsy_receipt_id: '7001',
        contribution_before_ads: '11.0910',
        ad_cost_allocated: '3.0000',
        contribution: '8.0910',
        complete: true,
      },
      // refund 10 → −10 revenue, +0.3834 processing credit
      {
        etsy_receipt_id: '7002',
        contribution_before_ads: '1.4743',
        ad_cost_allocated: '3.0000',
        contribution: '-1.5257',
        complete: true,
      },
      {
        etsy_receipt_id: '7003',
        contribution_before_ads: expect.any(String),
        ad_cost_allocated: '3.0000',
        contribution: expect.any(String),
        complete: false,
      },
    ]);

    const today = now.toISOString().slice(0, 10);
    const s = await http
      .get(`/api/v1/stores/${storeId}/finance/summary?from=${today.slice(0, 7)}-01&to=${today}`)
      .set(auth(viewer.token))
      .expect(200);
    const before = 11.09095 + 1.474311 + Number(snaps.rows[2].contribution_before_ads);
    expect(Number(s.body.contributionBeforeAds)).toBeCloseTo(before, 3);
    expect(s.body.adSpendActual).toBe('9.0000');
    // ads subtracted exactly once (9), not 3 × allocation + 9
    expect(Number(s.body.contributionAfterAds)).toBeCloseTo(before - 9, 3);
    expect(s.body.dataQuality).toMatchObject({ incompleteOrders: 1 });
    expect(s.body.costLines.map((l: { code: string }) => l.code)).toEqual(
      expect.arrayContaining(['fee_transaction', 'production']),
    );

    const dash = await http
      .get(`/api/v1/stores/${storeId}/dashboard`)
      .set(auth(owner.token))
      .expect(200);
    expect(dash.body.kpis.contributionMonth).not.toBeNull();
  });

  it('recompute endpoint is admin only', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/finance/recompute`)
      .set(auth(viewer.token))
      .expect(403);
    await http
      .post(`/api/v1/stores/${storeId}/finance/recompute`)
      .set(auth(owner.token))
      .expect(202);
  });
});
