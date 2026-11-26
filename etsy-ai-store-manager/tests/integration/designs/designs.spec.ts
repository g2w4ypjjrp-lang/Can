import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import pg from 'pg';
import sharp from 'sharp';
import { pino } from 'pino';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { LocalBlobStore } from '@esm/design-tools';
import { createAuthUser, signTestToken } from '../../helpers/auth.js';
import { startTestApi } from '../../helpers/api-app.js';
import { TEST_DATABASE_URL, TEST_REDIS_URL } from '../../helpers/env.js';
import { startAnthropicStub, type AnthropicStub } from '../../helpers/anthropic-stub.js';
import {
  startPrintifyStub,
  PRINTIFY_TOKEN,
  PRINTIFY_SHOP_ID,
  type PrintifyStub,
} from '../../helpers/printify-stub.js';
import { startWorker, type RunningWorker } from '../../../apps/worker/src/worker.js';
import { generateDesign } from '../../../apps/worker/src/designs/jobs.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let ai: AnthropicStub;
let printify: PrintifyStub;
let app: INestApplication;
let http: ReturnType<typeof request>;
let worker: RunningWorker;
let storageDir: string;
let owner: { id: string; token: string };
let viewer: { id: string; token: string };
let storeId: string;
let designId: string;
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
const design = async () =>
  (
    await http
      .get(`/api/v1/stores/${storeId}/designs/${designId}`)
      .set(auth(owner.token))
      .expect(200)
  ).body;

beforeAll(async () => {
  storageDir = await mkdtemp(path.join(os.tmpdir(), 'esm-store-'));
  ai = await startAnthropicStub();
  printify = await startPrintifyStub();
  app = await startTestApi({
    ANTHROPIC_API_KEY: 'sk-ant-test',
    STORAGE_DRIVER: 'local',
    STORAGE_LOCAL_DIR: storageDir,
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
      cipher: null,
      etsy: null,
      fetchImpl: fetch,
      anthropic: { apiKey: 'sk-ant-test', baseURL: ai.url },
      store: new LocalBlobStore(storageDir),
      printify: { token: PRINTIFY_TOKEN, baseUrl: printify.url, fetchImpl: fetch },
    },
  });
  const o = await createAuthUser(pool, 'D Owner');
  const v = await createAuthUser(pool, 'D Viewer');
  owner = { id: o.id, token: await signTestToken(o.id) };
  viewer = { id: v.id, token: await signTestToken(v.id) };
  storeId = (
    await http
      .post('/api/v1/stores')
      .set(auth(owner.token))
      .send({ name: 'Design shop' })
      .expect(201)
  ).body.id;
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1,$2,'viewer')`,
    [storeId, viewer.id],
  );
  await pool.query(
    `insert into public.connected_accounts (store_id, platform, external_account_id, display_name, status) values ($1,'printify',$2,'Shop','active')`,
    [storeId, String(PRINTIFY_SHOP_ID)],
  );
});

afterAll(async () => {
  for (const q of worker.queues) {
    for (const s of await q.getJobSchedulers()) await q.removeJobScheduler(s.key);
    await q.obliterate({ force: true }).catch(() => undefined);
  }
  await worker.close();
  await app.close();
  await ai.close();
  await printify.close();
  await pool.end();
});

describe('design creation (human contribution, IP pre-check)', () => {
  it('requires a real human creative direction and admin role', async () => {
    const base = {
      title: 'Grow Slow',
      productType: 'T-Shirt',
      brief: 'Minimal botanical typography about patience',
    };
    await http
      .post(`/api/v1/stores/${storeId}/designs`)
      .set(auth(owner.token))
      .send({ ...base, humanContribution: 'short' })
      .expect(400);
    await http
      .post(`/api/v1/stores/${storeId}/designs`)
      .set(auth(viewer.token))
      .send({ ...base, humanContribution: 'x'.repeat(30) })
      .expect(403);
    const r = await http
      .post(`/api/v1/stores/${storeId}/designs`)
      .set(auth(owner.token))
      .send({
        ...base,
        humanContribution:
          'Large round blue sun shape above the words GROW SLOW in a clean sans serif, navy text',
        tags: ['plant gift'],
      })
      .expect(201);
    designId = r.body.id;
    expect(r.body).toMatchObject({ status: 'draft', ipRiskLevel: 'unknown', versions: [] });
  });
  it('local pre-check marks obviously protected names as high risk and blocks AI generation', async () => {
    const r = await http
      .post(`/api/v1/stores/${storeId}/designs`)
      .set(auth(owner.token))
      .send({
        title: 'Pikachu party',
        productType: 'T-Shirt',
        brief: 'A pikachu birthday design for kids',
        humanContribution: 'Yellow mouse character with balloons and confetti',
      })
      .expect(201);
    expect(r.body.ipRiskLevel).toBe('high');
    await http
      .post(`/api/v1/stores/${storeId}/designs/${r.body.id}/generate`)
      .set(auth(owner.token))
      .expect(409);
  });
});

describe('AI generation -> IP review -> print prep -> approval -> Printify draft', () => {
  it('generates an original SVG with Claude, rasterised to print size, cost tracked', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/generate`)
      .set(auth(owner.token))
      .expect(202);
    const d = await waitFor(async () => {
      const x = await design();
      return x.versions.length ? x : null;
    });
    expect(d.versions[0]).toMatchObject({
      generator: 'ai',
      operation: 'ai_generate',
      width_px: 4500,
      height_px: 5400,
      has_transparency: true,
    });
    expect(d.versions[0].generation_params).toMatchObject({
      title: 'Grow Slow Botanical',
      textInDesign: ['GROW SLOW'],
    });
    expect(d.status).toBe('review');
    const req = ai.requests.find((r) => JSON.stringify(r.body.output_config ?? {}).includes('svg'));
    expect(String(req?.body.system)).toMatch(/Never use or imitate brands/);
    expect(JSON.stringify(req?.body.messages)).toContain('Large round blue sun');
    const t = await pool.query(
      `select status, cost_usd::text from public.ai_tasks where task_type = 'design_generate' and store_id = $1`,
      [storeId],
    );
    expect(t.rows[0]).toEqual({ status: 'succeeded', cost_usd: '0.027200' }); // 800×4 + 1200×20 per 1M
  });

  it('streams the version file only to store members', async () => {
    const d = await design();
    const url = `/api/v1/stores/${storeId}/designs/${designId}/versions/${d.versions[0].id}/file`;
    const res = await http
      .get(url)
      .set(auth(viewer.token))
      .buffer(true)
      .parse((r, cb) => {
        const c: Buffer[] = [];
        r.on('data', (x: Buffer) => c.push(x));
        r.on('end', () => cb(null, Buffer.concat(c)));
      })
      .expect(200);
    expect(res.headers['content-type']).toMatch(/image\/png/);
    expect((await sharp(res.body as Buffer).metadata()).width).toBe(4500);
    const stranger = await createAuthUser(pool, 'Stranger');
    await http
      .get(url)
      .set(auth(await signTestToken(stranger.id)))
      .expect(404);
  });

  it('cannot be approved before IP review and print preparation', async () => {
    const r = await http
      .patch(`/api/v1/stores/${storeId}/designs/${designId}/status`)
      .set(auth(owner.token))
      .send({ status: 'approved' })
      .expect(409);
    expect(r.body.message).toMatch(/IP incelemesi/);
  });

  it('IP review sends the image to Claude (vision) and stores a structured verdict', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/ip-review`)
      .set(auth(owner.token))
      .expect(202);
    const d = await waitFor(async () => {
      const x = await design();
      return x.ipReviewedAt ? x : null;
    });
    expect(d.ipRiskLevel).toBe('low');
    expect(d.ipReview).toMatchObject({
      riskLevel: 'low',
      textDetected: ['GROW SLOW'],
      disclaimer: 'Hukuki görüş değildir',
    });
  });

  it('prepares the print file for the Printify print area and reports resolution', async () => {
    const d = await design();
    const r = await http
      .post(
        `/api/v1/stores/${storeId}/designs/${designId}/versions/${d.versions[0].id}/prepare-print`,
      )
      .set(auth(owner.token))
      .send({ blueprintId: 6, printProviderId: 29, position: 'front' })
      .expect(201);
    const v = r.body.versions[0];
    expect(v).toMatchObject({
      operation: 'prepare_print',
      width_px: 4500,
      height_px: 5400,
      dpi: 300,
    });
    expect(v.fit_report).toMatchObject({ status: 'ok', effectiveDpi: 300 });
    expect(v.print_area).toMatchObject({ blueprintId: 6, printProviderId: 29, position: 'front' });
    await http
      .post(
        `/api/v1/stores/${storeId}/designs/${designId}/versions/${d.versions[0].id}/prepare-print`,
      )
      .set(auth(owner.token))
      .send({ blueprintId: 6, printProviderId: 29, position: 'sleeve' })
      .expect(400);
  });

  it('approval succeeds once all conditions hold, and a new artwork resets it', async () => {
    const ok = await http
      .patch(`/api/v1/stores/${storeId}/designs/${designId}/status`)
      .set(auth(owner.token))
      .send({ status: 'approved' })
      .expect(200);
    expect(ok.body.status).toBe('approved');
  });

  it('creates an UNPUBLISHED Printify product from the approved design (no Etsy call)', async () => {
    await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/printify-product`)
      .set(auth(viewer.token))
      .send({
        title: 'Grow Slow Tee',
        description: 'Original botanical typography tee',
        variantIds: [12100],
        priceUsd: '28.99',
      })
      .expect(403);
    const r = await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/printify-product`)
      .set(auth(owner.token))
      .send({
        title: 'Grow Slow Tee',
        description: 'Original botanical typography tee',
        variantIds: [12100],
        priceUsd: '28.99',
      })
      .expect(201);
    expect(r.body.note).toMatch(/Etsy’ye gönderilmedi/);
    expect(printify.uploads.at(-1)?.bytes).toBeGreaterThan(1000); // base64 upload (local storage has no signed URL)
    const created = printify.createdProducts.at(-1) as {
      blueprint_id: number;
      variants: Array<{ price: number }>;
      print_areas: Array<{ placeholders: Array<{ position: string }> }>;
    };
    expect(created.blueprint_id).toBe(6);
    expect(created.variants[0]!.price).toBe(2899);
    expect(created.print_areas[0]!.placeholders[0]!.position).toBe('front');
    expect(printify.published).toEqual([]);
    const p = await pool.query(
      `select status, design_id from public.products where printify_product_id = $1`,
      [r.body.printifyProductId],
    );
    expect(p.rows[0]).toEqual({ status: 'draft', design_id: designId });
  });

  it('upload + background removal create versions; new artwork resets approval and IP review', async () => {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="#ffffff"/><rect x="100" y="100" width="100" height="100" fill="#000"/></svg>';
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    const up = await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/upload`)
      .set(auth(owner.token))
      .send({ fileName: 'mine.png', contentBase64: png.toString('base64') })
      .expect(201);
    expect(up.body.status).toBe('review');
    expect(up.body.ipReviewedAt).toBeNull();
    const v = up.body.versions[0];
    const bg = await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/versions/${v.id}/remove-background`)
      .set(auth(owner.token))
      .send({})
      .expect(201);
    expect(bg.body.versions[0]).toMatchObject({
      operation: 'remove_background',
      parent_version_id: v.id,
      has_transparency: true,
    });
    await http
      .post(`/api/v1/stores/${storeId}/designs/${designId}/upload`)
      .set(auth(owner.token))
      .send({
        fileName: 'x.txt',
        contentBase64: Buffer.from('hello world, not an image').toString('base64'),
      })
      .expect(400);
  });
});

describe('model output safety', () => {
  it('rejects an unsafe SVG from the model instead of rendering it', async () => {
    ai.mode.unsafeSvg = true;
    try {
      await expect(
        generateDesign(
          pool,
          {
            anthropic: { apiKey: 'sk-ant-test', baseURL: ai.url },
            store: new LocalBlobStore(storageDir),
          },
          designId,
          owner.id,
        ),
      ).rejects.toThrow(/SVG güvenlik denetimi/);
      const t = await pool.query(
        `select status from public.ai_tasks where task_type = 'design_generate' and store_id = $1 order by created_at desc limit 1`,
        [storeId],
      );
      expect(t.rows[0].status).toBe('failed');
    } finally {
      ai.mode.unsafeSvg = false;
    }
  });
});
