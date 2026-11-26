import type pg from 'pg';
import { mapListing, type EtsyDraftListingInput, type EtsyListingPatch } from '@esm/integrations';
import { etsyClientFor, loadEtsyConnection, type IntegrationDeps } from './deps.js';
import { notifyAdmins } from './sync.js';
import { loadPrintifyConnection, printifyClientFor } from '../printify/sync.js';

type Field = 'title' | 'description' | 'tags' | 'materials' | 'state';

export interface ExecuteOutcome {
  status: 'executed' | 'failed' | 'skipped';
  reason?: string;
  updatedFields?: string[];
  conflicts?: string[];
}

/**
 * Executes an APPROVED listing change:
 *  1. claims the request (approved -> executing) so it runs once,
 *  2. reads the current listing from Etsy,
 *  3. refuses if any field to change was edited on Etsy after the proposal (no silent overwrite),
 *  4. PATCHes only the changed fields (all other listing data stays as is on Etsy),
 *  5. stores the result locally and records audit + notification.
 */
export async function executeApproval(
  pool: pg.Pool,
  deps: IntegrationDeps,
  approvalId: string,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  const claim = await pool.query(
    `update public.approval_requests set status = 'executing'
      where id = $1 and status = 'approved' returning *`,
    [approvalId],
  );
  const a = claim.rows[0];
  if (!a) {
    const cur = await pool.query(`select status from public.approval_requests where id = $1`, [
      approvalId,
    ]);
    return { status: 'skipped', reason: `status=${cur.rows[0]?.status ?? 'missing'}` };
  }
  if (a.action_type === 'change_price' && a.payload?.kind === 'printify_variant_price') {
    return executePrintifyPriceChange(pool, deps, a, attempt);
  }
  if (a.action_type === 'publish_product' && a.payload?.kind === 'printify_publish') {
    return executePrintifyPublish(pool, deps, a, attempt);
  }
  if (a.action_type === 'update_listing' && a.payload?.kind === 'printify_product_seo') {
    return executePrintifySeo(pool, deps, a, attempt);
  }
  if (a.action_type === 'update_listing_translation') {
    return executeTranslation(pool, deps, a, attempt);
  }
  if (a.action_type === 'create_listing') {
    return executeCreateListing(pool, deps, a, attempt);
  }
  if (!['update_listing', 'publish_product'].includes(a.action_type)) {
    return finish(pool, a, 'failed', { error: 'Bu işlem türü için otomatik yürütücü yok' });
  }

  const payload = a.payload as {
    listingId: string;
    etsyListingId: string;
    changes: Partial<Record<Field, unknown>>;
    baseline: Partial<Record<Field, unknown>>;
  };
  try {
    const conn = await loadEtsyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Etsy bağlantısı aktif değil' });
    const client = etsyClientFor(pool, deps, conn);

    const current = await client.getListing(payload.etsyListingId);
    const conflicts = (Object.keys(payload.changes) as Field[]).filter(
      (f) => !sameValue(current[f], payload.baseline[f]),
    );
    if (conflicts.length) {
      return finish(pool, a, 'failed', {
        error: 'İlan, öneri oluşturulduktan sonra Etsy üzerinde değişmiş; üzerine yazılmadı.',
        conflicts,
      });
    }

    const patch: EtsyListingPatch = {};
    for (const [k, v] of Object.entries(payload.changes)) (patch as Record<string, unknown>)[k] = v;
    const updated = await client.updateListing(conn.shopId, payload.etsyListingId, patch);
    const m = mapListing({ ...current, ...updated });
    await pool.query(
      `update public.listings set title = $3, description = $4, tags = $5, materials = $6, state = $7,
              raw = $8, last_synced_at = now()
        where store_id = $1 and id = $2`,
      [
        a.store_id,
        payload.listingId,
        m.title,
        m.description,
        m.tags,
        m.materials,
        m.state,
        JSON.stringify(m.raw),
      ],
    );
    return finish(pool, a, 'executed', { updatedFields: Object.keys(payload.changes) });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (attempt.current >= attempt.max) {
      return finish(pool, a, 'failed', { error: message.slice(0, 500) });
    }
    // give the request back so the BullMQ retry can claim it again
    await pool.query(
      `update public.approval_requests set status = 'approved', execution_result = $2 where id = $1`,
      [approvalId, JSON.stringify({ lastError: message.slice(0, 500), attempt: attempt.current })],
    );
    throw err;
  }
}

/**
 * Approved "publish Printify product to Etsy": calls Printify publish.json. Printify then
 * creates/updates the Etsy listing through its own Etsy connection; the Etsy listing id
 * appears later on product.external (picked up by the next Printify sync).
 */
async function executePrintifyPublish(
  pool: pg.Pool,
  deps: IntegrationDeps,
  a: { id: string; store_id: string; title: string; payload: Record<string, unknown> },
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  try {
    if (!deps.printify)
      return finish(pool, a, 'failed', { error: 'PRINTIFY_API_TOKEN tanımlı değil' });
    const conn = await loadPrintifyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Printify bağlantısı aktif değil' });
    const productId = String(a.payload.printifyProductId ?? '');
    const client = printifyClientFor(pool, deps.printify, a.store_id);
    const product = await client.getProduct(conn.shopId, productId);
    if (product.is_locked) {
      return finish(pool, a, 'failed', {
        error: 'Ürün Printify’da kilitli (yayınlama sürüyor olabilir)',
      });
    }
    await client.publishProduct(conn.shopId, productId);
    await pool.query(
      `update public.products set status = 'ready', printify_is_locked = true where store_id = $1 and printify_product_id = $2`,
      [a.store_id, productId],
    );
    return finish(pool, a, 'executed', {
      publishedProduct: productId,
      note: 'Printify yayınlamayı başlattı; Etsy ilan kimliği sonraki senkronizasyonda gelir.',
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (attempt.current >= attempt.max)
      return finish(pool, a, 'failed', { error: message.slice(0, 500) });
    await pool.query(
      `update public.approval_requests set status = 'approved', execution_result = $2 where id = $1`,
      [a.id, JSON.stringify({ lastError: message.slice(0, 500), attempt: attempt.current })],
    );
    throw err;
  }
}

/**
 * Approved price change: updates the variant prices on the Printify product (all
 * variants must be sent, per the API) and republishes ONLY variants to Etsy.
 */
async function executePrintifyPriceChange(
  pool: pg.Pool,
  deps: IntegrationDeps,
  a: { id: string; store_id: string; title: string; payload: Record<string, unknown> },
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  try {
    if (!deps.printify)
      return finish(pool, a, 'failed', { error: 'PRINTIFY_API_TOKEN tanımlı değil' });
    const conn = await loadPrintifyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Printify bağlantısı aktif değil' });
    const productId = String(a.payload.printifyProductId ?? '');
    const prices = a.payload.prices as Record<string, string>;
    const client = printifyClientFor(pool, deps.printify, a.store_id);
    const product = await client.getProduct(conn.shopId, productId);
    if (product.is_locked) return finish(pool, a, 'failed', { error: 'Ürün Printify’da kilitli' });
    const variants = product.variants.map((v) => ({
      id: v.id,
      price:
        prices[String(v.id)] !== undefined
          ? Math.round(Number(prices[String(v.id)]) * 100)
          : v.price,
      is_enabled: v.is_enabled,
    }));
    await client.updateProduct(conn.shopId, productId, { variants });
    if (product.external?.id) {
      await client.publishProduct(conn.shopId, productId, {
        title: false,
        description: false,
        images: false,
        variants: true,
        tags: false,
        keyFeatures: false,
        shipping_template: false,
      });
    }
    for (const [vid, price] of Object.entries(prices)) {
      await pool.query(
        `update public.product_variants v set price = $3 from public.products p
          where p.id = v.product_id and p.store_id = $1 and p.printify_product_id = $2 and v.printify_variant_id = $4`,
        [a.store_id, productId, price, Number(vid)],
      );
    }
    await pool.query(
      `update public.price_recommendations set status = 'applied' where approval_request_id = $1`,
      [a.id],
    );
    return finish(pool, a, 'executed', {
      updatedVariants: Object.keys(prices).length,
      republished: Boolean(product.external?.id),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (attempt.current >= attempt.max)
      return finish(pool, a, 'failed', { error: message.slice(0, 500) });
    await pool.query(
      `update public.approval_requests set status = 'approved', execution_result = $2 where id = $1`,
      [a.id, JSON.stringify({ lastError: message.slice(0, 500), attempt: attempt.current })],
    );
    throw err;
  }
}

type ApprovalRow = {
  id: string;
  store_id: string;
  title: string;
  payload: Record<string, unknown>;
};

/** Gives the request back for a BullMQ retry, or fails it on the last attempt. */
async function retryOrFail(
  pool: pg.Pool,
  a: ApprovalRow,
  err: unknown,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  const message = err instanceof Error ? err.message : String(err);
  if (attempt.current >= attempt.max)
    return finish(pool, a, 'failed', { error: message.slice(0, 500) });
  await pool.query(
    `update public.approval_requests set status = 'approved', execution_result = $2 where id = $1`,
    [a.id, JSON.stringify({ lastError: message.slice(0, 500), attempt: attempt.current })],
  );
  throw err;
}

/**
 * Approved SEO for a Printify product: PUT title/description/tags on Printify. If the
 * product is already on Etsy, republishes ONLY title, description and tags (Printify
 * pushes them to the Etsy listing through its own connection).
 */
async function executePrintifySeo(
  pool: pg.Pool,
  deps: IntegrationDeps,
  a: ApprovalRow,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  try {
    if (!deps.printify)
      return finish(pool, a, 'failed', { error: 'PRINTIFY_API_TOKEN tanımlı değil' });
    const conn = await loadPrintifyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Printify bağlantısı aktif değil' });
    const productId = String(a.payload.printifyProductId ?? '');
    const changes = a.payload.changes as { title: string; description: string; tags: string[] };
    const baseline = a.payload.baseline as { title?: string };
    const client = printifyClientFor(pool, deps.printify, a.store_id);
    const product = await client.getProduct(conn.shopId, productId);
    if (product.is_locked) return finish(pool, a, 'failed', { error: 'Ürün Printify’da kilitli' });
    if (baseline.title !== undefined && product.title !== baseline.title) {
      return finish(pool, a, 'failed', {
        error: 'Ürün başlığı öneriden sonra Printify’da değişmiş; üzerine yazılmadı.',
        conflicts: ['title'],
      });
    }
    await client.updateProduct(conn.shopId, productId, {
      title: changes.title,
      description: changes.description,
      tags: changes.tags,
    });
    const republished = Boolean(product.external?.id);
    if (republished) {
      await client.publishProduct(conn.shopId, productId, {
        title: true,
        description: true,
        images: false,
        variants: false,
        tags: true,
        keyFeatures: false,
        shipping_template: false,
      });
    }
    await pool.query(
      `update public.products set title = $3,
              metadata = metadata || jsonb_build_object('tags', $4::jsonb, 'description', $5::text)
        where store_id = $1 and printify_product_id = $2`,
      [a.store_id, productId, changes.title, JSON.stringify(changes.tags), changes.description],
    );
    return finish(pool, a, 'executed', {
      updatedFields: ['title', 'description', 'tags'],
      republished,
    });
  } catch (err) {
    return retryOrFail(pool, a, err, attempt);
  }
}

/** Approved translation: createListingTranslation, or updateListingTranslation if one exists. */
async function executeTranslation(
  pool: pg.Pool,
  deps: IntegrationDeps,
  a: ApprovalRow,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  const p = a.payload as {
    translationId: string;
    etsyListingId: string;
    language: string;
    title: string;
    description: string;
    tags: string[];
  };
  try {
    const conn = await loadEtsyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Etsy bağlantısı aktif değil' });
    const client = etsyClientFor(pool, deps, conn);
    const existing = await client.getListingTranslation(conn.shopId, p.etsyListingId, p.language);
    await client.saveListingTranslation(
      conn.shopId,
      p.etsyListingId,
      p.language,
      { title: p.title, description: p.description, tags: p.tags },
      existing !== null,
    );
    await pool.query(
      `update public.listing_translations set published_at = now() where id = $1 and store_id = $2`,
      [p.translationId, a.store_id],
    );
    return finish(pool, a, 'executed', {
      language: p.language,
      operation: existing ? 'updateListingTranslation' : 'createListingTranslation',
    });
  } catch (err) {
    return retryOrFail(pool, a, err, attempt);
  }
}

/**
 * Approved new listing: createDraftListing. The listing stays a DRAFT on Etsy (not visible,
 * no listing fee until it is published); images must be added before it can be published.
 */
async function executeCreateListing(
  pool: pg.Pool,
  deps: IntegrationDeps,
  a: ApprovalRow,
  attempt: { current: number; max: number },
): Promise<ExecuteOutcome> {
  const p = a.payload as {
    productId: string | null;
    input: EtsyDraftListingInput;
    currency: string;
  };
  try {
    const conn = await loadEtsyConnection(pool, a.store_id);
    if (!conn) return finish(pool, a, 'failed', { error: 'Etsy bağlantısı aktif değil' });
    const client = etsyClientFor(pool, deps, conn);
    const created = await client.createDraftListing(conn.shopId, p.input);
    const m = mapListing(created);
    const r = await pool.query(
      `insert into public.listings
         (store_id, product_id, etsy_listing_id, state, title, description, tags, materials, taxonomy_id, price, currency,
          quantity, shipping_profile_id, return_policy_id, production_partner_ids, who_made, when_made, is_supply,
          listing_type, raw, data_origin, last_synced_at)
       values ($1,$2,$3,'draft',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,'live',now())
       on conflict (store_id, etsy_listing_id) where etsy_listing_id is not null do update set state = 'draft'
       returning id`,
      [
        a.store_id,
        p.productId,
        created.listing_id,
        m.title,
        m.description,
        m.tags,
        m.materials,
        p.input.taxonomy_id,
        p.input.price.toFixed(2),
        p.currency,
        p.input.quantity,
        p.input.shipping_profile_id ?? null,
        p.input.return_policy_id ?? null,
        p.input.production_partner_ids ?? [],
        p.input.who_made,
        p.input.when_made,
        p.input.is_supply,
        p.input.type ?? 'physical',
        JSON.stringify(m.raw),
      ],
    );
    return finish(pool, a, 'executed', {
      etsyListingId: created.listing_id,
      listingId: r.rows[0].id,
      note: 'Etsy’de TASLAK ilan oluşturuldu. Yayın öncesi Etsy’de görsel ekleyin; yayınlama ayrı onay gerektirir.',
    });
  } catch (err) {
    return retryOrFail(pool, a, err, attempt);
  }
}

async function finish(
  pool: pg.Pool,
  a: { id: string; store_id: string; title: string },
  status: 'executed' | 'failed',
  result: Record<string, unknown>,
): Promise<ExecuteOutcome> {
  await pool.query(
    `update public.approval_requests set status = $2, execution_result = $3,
            executed_at = case when $2 = 'executed' then now() else executed_at end
      where id = $1`,
    [a.id, status, JSON.stringify(result)],
  );
  // keep the proposal records in step with the request
  await pool.query(
    `update public.seo_drafts set status = $2, error = $3 where approval_request_id = $1`,
    [
      a.id,
      status === 'executed' ? 'applied' : 'draft',
      status === 'executed' ? null : String(result.error ?? ''),
    ],
  );
  await pool.query(
    `update public.listing_translations set status = $2, error = $3 where approval_request_id = $1`,
    [
      a.id,
      status === 'executed' ? 'published' : 'reviewed',
      status === 'executed' ? null : String(result.error ?? ''),
    ],
  );
  await pool.query(
    `insert into public.audit_logs (store_id, actor_type, action, entity_type, entity_id, after)
     values ($1, 'worker', $2, 'approval_request', $3, $4)`,
    [
      a.store_id,
      status === 'executed' ? 'approval.executed' : 'approval.failed',
      a.id,
      JSON.stringify(result),
    ],
  );
  await notifyAdmins(
    pool,
    a.store_id,
    `approval.${status}`,
    status === 'executed' ? 'success' : 'warning',
    status === 'executed' ? 'Değişiklik Etsy’ye uygulandı' : 'Değişiklik uygulanamadı',
    `${a.title}${result.error ? ` — ${String(result.error)}` : ''}`,
    '/dashboard/etsy',
  );
  return {
    status,
    ...(result.error ? { reason: String(result.error) } : {}),
    ...(result.updatedFields ? { updatedFields: result.updatedFields as string[] } : {}),
    ...(result.conflicts ? { conflicts: result.conflicts as string[] } : {}),
  };
}

function sameValue(a: unknown, b: unknown): boolean {
  const norm = (v: unknown) =>
    Array.isArray(v)
      ? JSON.stringify([...v].map(String))
      : v === null || v === undefined
        ? ''
        : String(v);
  return norm(a) === norm(b);
}
