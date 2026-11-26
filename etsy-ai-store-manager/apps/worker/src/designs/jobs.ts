import type pg from 'pg';
import { randomUUID } from 'node:crypto';
import sharp from 'sharp';
import {
  createAnthropic,
  emptyUsage,
  generateSvgDesign,
  reviewDesignIp,
  type AiUsage,
} from '@esm/ai-engine';
import {
  assertSafeSvg,
  inspectImage,
  scanProtectedTerms,
  svgToPng,
  type BlobStore,
} from '@esm/design-tools';
import { notifyAdmins } from '../etsy/sync.js';

export interface DesignDeps {
  anthropic: { apiKey: string; baseURL?: string | undefined } | null;
  store: BlobStore;
}

/** Default print canvas when no print area was chosen yet (common Printify front placeholder, px at 300 DPI). */
const DEFAULT_CANVAS = { width: 4500, height: 5400 };

async function startTask(
  pool: pg.Pool,
  storeId: string,
  type: string,
  key: string,
  input: unknown,
  userId: string | null,
) {
  const r = await pool.query(
    `insert into public.ai_tasks (store_id, task_type, status, input, model, idempotency_key, started_at, created_by)
     values ($1,$2,'running',$3,'claude-opus-5-5',$4,now(),$5)
     on conflict (idempotency_key) do update set status = 'running', started_at = now(), attempts = public.ai_tasks.attempts + 1
     returning id`,
    [storeId, type, JSON.stringify(input), key, userId],
  );
  return r.rows[0].id as string;
}

async function finishTask(
  pool: pg.Pool,
  id: string,
  status: 'succeeded' | 'failed',
  usage: AiUsage,
  output: unknown,
  error?: string,
) {
  await pool.query(
    `update public.ai_tasks set status = $2, output = $3, error = $4, input_tokens = $5, output_tokens = $6, cost_usd = $7, finished_at = now()
      where id = $1`,
    [
      id,
      status,
      output ? JSON.stringify(output) : null,
      error ?? null,
      usage.inputTokens,
      usage.outputTokens,
      usage.costUsd.toFixed(6),
    ],
  );
}

async function addVersion(
  pool: pg.Pool,
  store: BlobStore,
  storeId: string,
  designId: string,
  png: Buffer,
  data: { params: unknown; aiTaskId: string; userId: string | null },
) {
  const info = await inspectImage(png);
  const n = await pool.query(
    `select coalesce(max(version), 0) + 1 as n from public.design_versions where design_id = $1`,
    [designId],
  );
  const version: number = n.rows[0].n;
  const id = randomUUID();
  const objectPath = `${storeId}/designs/${designId}/v${version}.png`;
  await store.put(objectPath, png, 'image/png');
  await pool.query(
    `insert into public.design_versions (id, design_id, store_id, version, storage_path, width_px, height_px, dpi, has_transparency,
                                         generator, generation_params, checksum_sha256, created_by, operation, ai_task_id)
     values ($1,$2,$3,$4,$5,$6,$7,300,$8,'ai',$9,$10,$11,'ai_generate',$12)`,
    [
      id,
      designId,
      storeId,
      version,
      objectPath,
      info.width,
      info.height,
      info.hasAlpha,
      JSON.stringify(data.params),
      info.sha256,
      data.userId,
      data.aiTaskId,
    ],
  );
  await pool.query(
    `update public.designs set current_version_id = $2, ip_reviewed_at = null,
            status = case when status in ('approved','draft') then 'review' else status end where id = $1`,
    [designId, id],
  );
  return { id, version };
}

/** AI design: Claude writes an original SVG from the brief + human direction; it is checked and rasterised. */
export async function generateDesign(
  pool: pg.Pool,
  deps: DesignDeps,
  designId: string,
  userId: string | null,
) {
  if (!deps.anthropic) throw new Error('ANTHROPIC_API_KEY tanımlı değil');
  const d = (await pool.query(`select * from public.designs where id = $1`, [designId])).rows[0];
  if (!d) throw new Error('design not found');
  const area = (
    await pool.query(
      `select print_area from public.design_versions where design_id = $1 and print_area is not null order by version desc limit 1`,
      [designId],
    )
  ).rows[0]?.print_area as { width: number; height: number } | undefined;
  const canvas = area ? { width: area.width, height: area.height } : DEFAULT_CANVAS;
  const taskId = await startTask(
    pool,
    d.store_id,
    'design_generate',
    `design_generate:${designId}:${Date.now()}`,
    { designId },
    userId,
  );
  let usage = emptyUsage();
  try {
    const out = await generateSvgDesign(
      createAnthropic(deps.anthropic),
      {
        brief: d.prompt,
        humanContribution: d.human_contribution,
        productType: d.product_type ?? 'T-Shirt',
        aspect: canvas,
        style: d.style,
      },
      usage,
    );
    usage = out.usage;
    assertSafeSvg(out.design.svg);
    const hits = scanProtectedTerms(`${out.design.title} ${out.design.textInDesign.join(' ')}`);
    const png = await svgToPng(out.design.svg, canvas.width);
    const v = await addVersion(pool, deps.store, d.store_id, designId, png, {
      params: {
        model: 'claude-opus-5-5',
        brief: d.prompt,
        humanContribution: d.human_contribution,
        canvas,
        title: out.design.title,
        description: out.design.description,
        textInDesign: out.design.textInDesign,
        palette: out.design.palette,
      },
      aiTaskId: taskId,
      userId,
    });
    // keep the vector source next to the raster for later edits
    await deps.store.put(
      `${d.store_id}/designs/${designId}/v${v.version}.svg`,
      Buffer.from(out.design.svg),
      'image/svg+xml',
    );
    if (hits.length) {
      await pool.query(
        `update public.designs set ip_risk_level = 'high', ip_risk_notes = $2 where id = $1`,
        [
          designId,
          JSON.stringify([
            {
              issue: `Üretilen tasarımda korumalı olabilecek ifadeler: ${hits.join(', ')}`,
              severity: 'high',
              source: 'local_scan',
            },
          ]),
        ],
      );
    }
    await finishTask(pool, taskId, 'succeeded', usage, {
      versionId: v.id,
      title: out.design.title,
    });
    await notifyAdmins(
      pool,
      d.store_id,
      'design.generated',
      'success',
      'AI tasarım hazır',
      `${d.title}: sürüm ${v.version}. Yayın öncesi IP incelemesi yapın.`,
      '/dashboard/design-studio',
    );
    return { versionId: v.id, costUsd: usage.costUsd.toFixed(4) };
  } catch (err) {
    await finishTask(
      pool,
      taskId,
      'failed',
      usage,
      null,
      err instanceof Error ? err.message.slice(0, 500) : String(err),
    );
    throw err;
  }
}

/** Vision IP review of the CURRENT version; stores the result on the design. */
export async function reviewDesign(pool: pg.Pool, deps: DesignDeps, designId: string) {
  if (!deps.anthropic) throw new Error('ANTHROPIC_API_KEY tanımlı değil');
  const d = (await pool.query(`select * from public.designs where id = $1`, [designId])).rows[0];
  if (!d?.current_version_id) throw new Error('design has no version');
  const v = (
    await pool.query(`select * from public.design_versions where id = $1`, [d.current_version_id])
  ).rows[0];
  const buf = await deps.store.get(v.storage_path);
  // vision input: downscale to keep the request small (detail is irrelevant for IP review)
  const preview = await sharp(buf)
    .resize({ width: 1024, height: 1024, fit: 'inside', withoutEnlargement: true })
    .flatten({ background: '#ffffff' })
    .png()
    .toBuffer();
  const localHits = scanProtectedTerms(`${d.title} ${d.prompt ?? ''} ${(d.tags ?? []).join(' ')}`);
  const taskId = await startTask(
    pool,
    d.store_id,
    'design_ip_review',
    `design_ip_review:${designId}:${v.id}`,
    { designId, versionId: v.id },
    null,
  );
  let usage = emptyUsage();
  try {
    const out = await reviewDesignIp(
      createAnthropic(deps.anthropic),
      { pngBase64: preview.toString('base64'), title: d.title, prompt: d.prompt, localHits },
      usage,
    );
    usage = out.usage;
    const level =
      localHits.length && out.review.riskLevel !== 'high' ? 'high' : out.review.riskLevel;
    await pool.query(
      `update public.designs set ip_risk_level = $2, ip_review = $3, ip_reviewed_at = now(), ip_risk_notes = $4 where id = $1 and current_version_id = $5`,
      [
        designId,
        level,
        JSON.stringify({
          ...out.review,
          localHits,
          versionId: v.id,
          model: 'claude-opus-5-5',
          disclaimer: 'Hukuki görüş değildir',
        }),
        JSON.stringify(out.review.findings),
        v.id,
      ],
    );
    await finishTask(pool, taskId, 'succeeded', usage, { riskLevel: level });
    return { riskLevel: level };
  } catch (err) {
    await finishTask(
      pool,
      taskId,
      'failed',
      usage,
      null,
      err instanceof Error ? err.message.slice(0, 500) : String(err),
    );
    throw err;
  }
}
