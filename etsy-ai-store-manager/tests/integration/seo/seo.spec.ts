import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import { pino } from 'pino';
import { TokenCipher } from '@esm/integrations';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL, TEST_TOKEN_KEY } from '../../helpers/env.js';
import { startAnthropicStub, type AnthropicStub } from '../../helpers/anthropic-stub.js';
import { startEtsyStub, STUB_APP, STUB_SHOP_ID, type EtsyStub } from '../../helpers/etsy-stub.js';
import {
  startPrintifyStub,
  PRINTIFY_TOKEN,
  PRINTIFY_SHOP_ID,
  type PrintifyStub,
} from '../../helpers/printify-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';

// Etsy, Printify and Claude are contract stubs (tests/helpers/*-stub.ts).
const REDIRECT_URI = 'http://api.test/api/v1/integrations/etsy/callback';
const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let ai: AnthropicStub;
let etsy: EtsyStub;
let printify: PrintifyStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
let listingId: string;
let etsyListingId: number;
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
const drafts = async (q: string) =>
  (await http.get(`/api/v1/stores/${storeId}/seo-drafts?${q}`).set(auth(owner.token)).expect(200))
    .body;
const approve = (id: string) =>
  http
    .post(`/api/v1/stores/${storeId}/approvals/${id}/approve`)
    .set(auth(owner.token))
    .send({})
    .expect(200);
const approvalStatus = async (id: string) =>
  (
    await pool.query(
      `select status, execution_result from public.approval_requests where id = $1`,
      [id],
    )
  ).rows[0];

beforeAll(async () => {
  // one Etsy stub shop may belong to one store only (released from earlier test files)
  await pool.query(`update public.stores set external_shop_id = null where external_shop_id = $1`, [
    String(STUB_SHOP_ID),
  ]);
  ai = await startAnthropicStub();
  etsy = await startEtsyStub({ listingCount: 3 });
  printify = await startPrintifyStub();
  const etsyEnv = {
    ETSY_KEYSTRING: STUB_APP.keystring,
    ETSY_SHARED_SECRET: STUB_APP.sharedSecret,
    ETSY_REDIRECT_URI: REDIRECT_URI,
    ETSY_CONNECT_URL: `${etsy.url}/oauth/connect`,
    ETSY_TOKEN_URL: `${etsy.url}/v3/public/oauth/token`,
    ETSY_API_BASE_URL: etsy.url,
  };
  app = await startTestApi({
    ...etsyEnv,
    ANTHROPIC_API_KEY: 'sk-ant-test',
    PRINTIFY_API_TOKEN: PRINTIFY_TOKEN,
    PRINTIFY_API_BASE_URL: printify.url,
  });
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
      printify: { token: PRINTIFY_TOKEN, baseUrl: printify.url, fetchImpl: fetch },
    },
  });
  const o = await createAuthUser(pool, 'SEO Owner');
  const v = await createAuthUser(pool, 'SEO Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http.post('/api/v1/stores').set(auth(owner.token)).send({ name: 'SEO shop' }).expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1,$2,'viewer')`,
    [storeId, viewer.id],
  );
  await pool.query(
    `update public.store_settings set languages = array['en','de','fr'] where store_id = $1`,
    [storeId],
  );

  // Etsy OAuth through the stub, then the initial sync
  const start = await http
    .post(`/api/v1/stores/${storeId}/integrations/etsy/connect`)
    .set(auth(owner.token))
    .expect(200);
  const consent = await fetch(new URL(start.body.authorizeUrl), { redirect: 'manual' });
  const cb = new URL(consent.headers.get('location')!);
  await http.get(`/api/v1/integrations/etsy/callback${cb.search}`).expect(302);
  const l = await waitFor(async () => {
    const r = await pool.query(
      `select id, etsy_listing_id from public.listings where store_id = $1 order by etsy_listing_id limit 1`,
      [storeId],
    );
    return r.rows[0];
  });
  listingId = l.id;
  etsyListingId = Number(l.etsy_listing_id);
  await waitFor(async () => {
    const r = await pool.query(
      `select metadata->'listing_options' as o from public.connected_accounts where store_id = $1 and platform = 'etsy'`,
      [storeId],
    );
    return r.rows[0]?.o;
  });
});

afterAll(async () => {
  for (const q of worker.queues) {
    for (const s of await q.getJobSchedulers()) await q.removeJobScheduler(s.key);
    await q.obliterate({ force: true }).catch(() => undefined);
  }
  await worker.close();
  await app.close();
  await ai.close();
  await etsy.close();
  await printify.close();
  await pool.query(
    `delete from public.oauth_tokens where connected_account_id in (select id from public.connected_accounts where store_id = $1)`,
    [storeId],
  );
  await pool.query(`update public.stores set external_shop_id = null where id = $1`, [storeId]);
  await pool.end();
});

describe('SEO drafts (AI + deterministic Etsy checks)', () => {
  let draftId: string;

  it('requires admin and a store language', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/seo-drafts`)
      .set(auth(viewer.token))
      .send({})
      .expect(403);
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/seo-drafts`)
      .set(auth(owner.token))
      .send({ language: 'ja' })
      .expect(400);
  });

  it('generates a validated draft with cleaned tags and keeps the baseline', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/seo-drafts`)
      .set(auth(owner.token))
      .send({ language: 'en' })
      .expect(202);
    draftId = r.body.id;
    const d = await waitFor(async () =>
      (await drafts(`listingId=${listingId}`)).find(
        (x: { id: string; status: string }) => x.id === draftId && x.status !== 'generating',
      ),
    );
    expect(d.status).toBe('draft');
    expect(d.title.startsWith('Botanical T-Shirt')).toBe(true);
    // "Plant Lover Gift!" normalised to a duplicate of "plant lover gift" and dropped
    expect(d.tags).toHaveLength(12);
    expect(d.tags.every((t: string) => t.length <= 20 && /^[\p{L}\p{Nd}\s\-']+$/u.test(t))).toBe(
      true,
    );
    expect(d.issues.some((i: { code: string }) => i.code === 'tags_unused_slots')).toBe(true);
    expect(d.issues.some((i: { severity: string }) => i.severity === 'error')).toBe(false);
    expect(d.seoScore).toBeGreaterThan(70);
    expect(d.description).toContain('production partner');
    const listing = (
      await pool.query(`select title from public.listings where id = $1`, [listingId])
    ).rows[0];
    expect(d.baseline.title).toBe(listing.title);
  });

  it('runs a repair round when the model breaks Etsy rules', async () => {
    ai.mode.seoStuffedFirst = true;
    const before = ai.requests.length;
    const r = await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/seo-drafts`)
      .set(auth(owner.token))
      .send({ language: 'en' })
      .expect(202);
    const d = await waitFor(async () =>
      (await drafts(`listingId=${listingId}`)).find(
        (x: { id: string; status: string }) => x.id === r.body.id && x.status !== 'generating',
      ),
    );
    ai.mode.seoStuffedFirst = false;
    const seoCalls = ai.requests
      .slice(before)
      .filter((q) => JSON.stringify(q).includes('primaryKeyword'));
    expect(seoCalls).toHaveLength(2);
    expect(JSON.stringify(seoCalls[1])).toContain('previous attempt failed');
    expect(d.status).toBe('draft');
    expect(d.title).not.toMatch(/plant.*plant.*plant/i);
    await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${r.body.id}/reject`)
      .set(auth(owner.token))
      .expect(200);
  });

  it('re-checks manual edits and blocks rule violations from being applied', async () => {
    const bad = await http
      .patch(`/api/v1/stores/${storeId}/seo-drafts/${draftId}`)
      .set(auth(owner.token))
      .send({
        title: 'Fern Tee: Grow Slow: Plant Gift',
        description: 'short',
        tags: ['fern tee', 'Fern Tee'],
      })
      .expect(200);
    expect(bad.body.issues.map((i: { code: string }) => i.code)).toEqual(
      expect.arrayContaining(['title_char_repeat', 'tags_unused_slots']),
    );
    expect(bad.body.tags).toEqual(['fern tee']); // duplicate removed on save
    await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${draftId}/apply`)
      .set(auth(owner.token))
      .send({ reason: 'SEO' })
      .expect(409);
  });

  it('creates an approval and updates the Etsy listing only after approval', async () => {
    const good = {
      title: 'Botanical T-Shirt, Grow Slow Fern Tee, Minimal Plant Lover Gift',
      description:
        'Botanical t-shirt with a hand-drawn fern and the words GROW SLOW. Soft unisex tee printed on demand by our production partner; a calm gift for gardeners and houseplant fans who enjoy slow living and minimal design.',
      tags: [
        'botanical shirt',
        'plant lover gift',
        'fern t-shirt',
        'gardener gift',
        'grow slow',
        'houseplant tee',
        'minimal plant art',
        'nature lover gift',
        'plant mom shirt',
        'slow living',
        'green thumb gift',
        'leaf graphic tee',
        'fern lover',
      ],
    };
    await http
      .patch(`/api/v1/stores/${storeId}/seo-drafts/${draftId}`)
      .set(auth(owner.token))
      .send(good)
      .expect(200);
    const a = await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${draftId}/apply`)
      .set(auth(owner.token))
      .send({ reason: 'Arama görünürlüğü' })
      .expect(201);
    expect(a.body.actionType).toBe('update_listing');
    expect(a.body.apiOperation).toContain('updateListing');
    expect(Object.keys(a.body.payload.changes)).toEqual(
      expect.arrayContaining(['title', 'description', 'tags']),
    );
    expect(etsy.listings.get(etsyListingId)!.title).not.toBe(good.title); // nothing sent yet
    await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${draftId}/apply`)
      .set(auth(owner.token))
      .send({ reason: 'x x x' })
      .expect(409);

    await approve(a.body.id);
    await waitFor(async () => (await approvalStatus(a.body.id)).status === 'executed');
    expect(etsy.listings.get(etsyListingId)!.title).toBe(good.title);
    expect(etsy.listings.get(etsyListingId)!.tags).toHaveLength(13);
    const d = (await drafts(`listingId=${listingId}`)).find(
      (x: { id: string }) => x.id === draftId,
    );
    expect(d.status).toBe('applied');
  });

  it('puts a draft back to editable when its approval is rejected', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/seo-drafts`)
      .set(auth(owner.token))
      .send({})
      .expect(202);
    await waitFor(async () =>
      (await drafts(`listingId=${listingId}`)).find(
        (x: { id: string; status: string }) => x.id === r.body.id && x.status === 'draft',
      ),
    );
    const a = await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${r.body.id}/apply`)
      .set(auth(owner.token))
      .send({ reason: 'deneme' })
      .expect(201);
    await http
      .post(`/api/v1/stores/${storeId}/approvals/${a.body.id}/reject`)
      .set(auth(owner.token))
      .send({})
      .expect(200);
    const d = (await drafts(`listingId=${listingId}`)).find(
      (x: { id: string }) => x.id === r.body.id,
    );
    expect(d.status).toBe('draft');
  });
});

describe('multilingual listings (quality-checked translations)', () => {
  let trId: string;

  it('refuses the default language and languages outside the store settings', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/translations`)
      .set(auth(owner.token))
      .send({ languages: ['en'] })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/translations`)
      .set(auth(owner.token))
      .send({ languages: ['ja'] })
      .expect(400);
  });

  it('translates with back-translation and quality notes', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/listings/${listingId}/translations`)
      .set(auth(owner.token))
      .send({ languages: ['de'] })
      .expect(202);
    trId = r.body.ids[0];
    const t = await waitFor(async () => {
      const list = (
        await http
          .get(`/api/v1/stores/${storeId}/listings/${listingId}/translations`)
          .set(auth(viewer.token))
          .expect(200)
      ).body;
      return list.find(
        (x: { id: string; status: string }) => x.id === trId && x.status !== 'generating',
      );
    });
    expect(t.status).toBe('draft');
    expect(t.language).toBe('de');
    expect(t.title).toContain('Botanik');
    expect(t.tags).toHaveLength(13);
    expect(t.backTranslation.title).toContain('Botanical');
    expect(t.qualityScore).toBeGreaterThan(50);
    expect(t.localizationNotes.length).toBeGreaterThan(0);
  });

  it('needs a human review before an approval request, then creates the Etsy translation', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/publish`)
      .set(auth(owner.token))
      .send({ reason: 'DE pazarı' })
      .expect(409);
    await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/review`)
      .set(auth(viewer.token))
      .send({ decision: 'reviewed' })
      .expect(403);
    await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/review`)
      .set(auth(owner.token))
      .send({ decision: 'reviewed' })
      .expect(200);
    const a = await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/publish`)
      .set(auth(owner.token))
      .send({ reason: 'DE pazarı' })
      .expect(201);
    expect(a.body.actionType).toBe('update_listing_translation');
    expect(etsy.translations.size).toBe(0);
    await approve(a.body.id);
    await waitFor(async () => (await approvalStatus(a.body.id)).status === 'executed');
    expect((await approvalStatus(a.body.id)).execution_result.operation).toBe(
      'createListingTranslation',
    );
    const saved = etsy.translations.get(`${etsyListingId}:de`)!;
    expect(saved.title).toContain('Botanik');
    expect(saved.tags).toHaveLength(13);
    const row = (
      await pool.query(
        `select status, published_at from public.listing_translations where id = $1`,
        [trId],
      )
    ).rows[0];
    expect(row.status).toBe('published');
    expect(row.published_at).not.toBeNull();
  });

  it('updates an existing Etsy translation with PUT after an edit', async () => {
    const cur = etsy.translations.get(`${etsyListingId}:de`)!;
    await http
      .patch(`/api/v1/stores/${storeId}/translations/${trId}`)
      .set(auth(owner.token))
      .send({
        title: 'Botanik T-Shirt mit Farn, Grow Slow Geschenk',
        description: String(cur.description),
        tags: cur.tags as string[],
      })
      .expect(200);
    await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/review`)
      .set(auth(owner.token))
      .send({ decision: 'reviewed' })
      .expect(200);
    const a = await http
      .post(`/api/v1/stores/${storeId}/translations/${trId}/publish`)
      .set(auth(owner.token))
      .send({ reason: 'Düzeltme' })
      .expect(201);
    await approve(a.body.id);
    await waitFor(async () => (await approvalStatus(a.body.id)).status === 'executed');
    expect((await approvalStatus(a.body.id)).execution_result.operation).toBe(
      'updateListingTranslation',
    );
    expect(etsy.translations.get(`${etsyListingId}:de`)!.title).toBe(
      'Botanik T-Shirt mit Farn, Grow Slow Geschenk',
    );
  });
});

describe('new Etsy draft listings (createDraftListing)', () => {
  const body = {
    title: 'Grow Slow Botanical Fern T-Shirt',
    description:
      'Botanical t-shirt with a hand-drawn fern and the words GROW SLOW, designed by our shop. Printed and shipped on demand by our production partner. Unisex fit; see the size chart in the photos.',
    tags: ['botanical shirt', 'fern t-shirt', 'grow slow'],
    materials: ['cotton'],
    price: '28.99',
    quantity: 10,
    taxonomyId: 482,
    whoMade: 'i_did',
    whenMade: 'made_to_order',
    isSupply: false,
    shippingProfileId: 3001,
    returnPolicyId: 4001,
    productionPartnerIds: [5001],
    reason: 'Yeni ürün',
  };

  it('exposes the shop options cached by the Etsy sync and the public taxonomy', async () => {
    const o = (
      await http
        .get(`/api/v1/stores/${storeId}/etsy/listing-options`)
        .set(auth(viewer.token))
        .expect(200)
    ).body;
    expect(o.shippingProfiles).toEqual([{ id: 3001, title: 'Standard (Printify)' }]);
    expect(o.productionPartners[0]).toMatchObject({ id: 5001, name: 'Printify' });
    const t = (
      await http
        .get(`/api/v1/stores/${storeId}/etsy/taxonomy?q=t-shirt`)
        .set(auth(viewer.token))
        .expect(200)
    ).body;
    expect(t).toEqual([{ id: 482, path: 'Clothing › Tops & Tees › T-shirts', leaf: true }]);
  });

  it('validates shop options, content rules and Printify-managed products', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(owner.token))
      .send({ ...body, shippingProfileId: 9999 })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(owner.token))
      .send({ ...body, title: 'Tee 🌿 gift' })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(owner.token))
      .send({ ...body, whoMade: 'someone_else' })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(viewer.token))
      .send(body)
      .expect(403);
    const p = await pool.query(
      `insert into public.products (store_id, title, product_type, printify_product_id) values ($1,'PF tee','T-Shirt','aaaaaaaaaaaaaaaaaaaaaaaa') returning id`,
      [storeId],
    );
    await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(owner.token))
      .send({ ...body, productId: p.rows[0].id })
      .expect(409);
  });

  it('creates a DRAFT listing on Etsy only after approval', async () => {
    const a = await http
      .post(`/api/v1/stores/${storeId}/etsy/draft-listings`)
      .set(auth(owner.token))
      .send(body)
      .expect(201);
    expect(a.body.actionType).toBe('create_listing');
    expect(a.body.apiOperation).toContain('createDraftListing');
    expect(etsy.draftForms).toHaveLength(0);
    await approve(a.body.id);
    await waitFor(async () => (await approvalStatus(a.body.id)).status === 'executed');
    const form = etsy.draftForms[0]!;
    expect(form).toMatchObject({
      title: body.title,
      price: '28.99',
      who_made: 'i_did',
      when_made: 'made_to_order',
      taxonomy_id: '482',
      is_supply: 'false',
      type: 'physical',
      shipping_profile_id: '3001',
      production_partner_ids: '5001',
      tags: 'botanical shirt,fern t-shirt,grow slow',
    });
    const row = (
      await pool.query(
        `select state, price, production_partner_ids from public.listings where store_id = $1 and title = $2`,
        [storeId, body.title],
      )
    ).rows[0];
    expect(row).toMatchObject({ state: 'draft', price: '28.99' });
    expect(row.production_partner_ids.map(Number)).toEqual([5001]);
  });
});

describe('SEO for Printify products', () => {
  it('updates the Printify product and republishes only text fields', async () => {
    await pool.query(
      `insert into public.connected_accounts (store_id, platform, external_account_id, display_name, status) values ($1,'printify',$2,'Shop','active')`,
      [storeId, String(PRINTIFY_SHOP_ID)],
    );
    const pid = '5d39b159e7c48c000728c89f';
    const prod = await pool.query(
      `insert into public.products (store_id, title, product_type, printify_product_id, external_listing_id, metadata)
       values ($1,'Custom Mug 11oz','Mug',$2,'900002','{"tags":["mug"]}') returning id`,
      [storeId, pid],
    );
    const r = await http
      .post(`/api/v1/stores/${storeId}/products/${prod.rows[0].id}/seo-drafts`)
      .set(auth(owner.token))
      .send({})
      .expect(202);
    await waitFor(async () =>
      (await drafts(`productId=${prod.rows[0].id}`)).find(
        (x: { id: string; status: string }) => x.id === r.body.id && x.status === 'draft',
      ),
    );
    const a = await http
      .post(`/api/v1/stores/${storeId}/seo-drafts/${r.body.id}/apply`)
      .set(auth(owner.token))
      .send({ reason: 'SEO' })
      .expect(201);
    expect(a.body.payload.kind).toBe('printify_product_seo');
    await approve(a.body.id);
    await waitFor(async () => (await approvalStatus(a.body.id)).status === 'executed');
    expect(printify.products.get(pid)!.title).toBe(
      'Botanical T-Shirt, Grow Slow Fern Tee, Minimal Plant Lover Gift for Gardeners',
    );
    expect((printify.products.get(pid)!.tags as string[]).length).toBe(12);
    expect(printify.publishBodies.at(-1)).toMatchObject({
      title: true,
      description: true,
      tags: true,
      variants: false,
      images: false,
    });
  });
});
