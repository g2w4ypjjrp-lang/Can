import type pg from 'pg';
import {
  centsToDecimal,
  PrintifyClient,
  type PrintifyOrder,
  type PrintifyProduct,
  type PrintifyShippingV1,
} from '@esm/integrations';
import { notifyAdmins } from '../etsy/sync.js';

export interface PrintifyDeps {
  token: string | null;
  baseUrl?: string | undefined;
  fetchImpl: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

export interface PrintifyConnection {
  accountId: string;
  storeId: string;
  shopId: string;
  metadata: Record<string, unknown>;
}

export async function loadPrintifyConnection(
  pool: pg.Pool,
  storeId: string,
): Promise<PrintifyConnection | null> {
  const r = await pool.query(
    `select id, store_id, external_account_id, metadata from public.connected_accounts
      where store_id = $1 and platform = 'printify' and status = 'active' order by updated_at desc limit 1`,
    [storeId],
  );
  const x = r.rows[0];
  return x
    ? {
        accountId: x.id,
        storeId: x.store_id,
        shopId: x.external_account_id,
        metadata: x.metadata ?? {},
      }
    : null;
}

export function printifyClientFor(
  pool: pg.Pool,
  deps: PrintifyDeps,
  storeId: string | null,
): PrintifyClient {
  if (!deps.token) throw new Error('PRINTIFY_API_TOKEN worker ortamında tanımlı değil');
  return new PrintifyClient({
    token: deps.token,
    baseUrl: deps.baseUrl,
    fetchImpl: deps.fetchImpl,
    sleep: deps.sleep,
    onCall: (log) => {
      void pool
        .query(
          `insert into public.api_logs (store_id, provider, method, endpoint, status_code, duration_ms, error)
           values ($1, 'printify', $2, $3, $4, $5, $6)`,
          [storeId, log.method, log.endpoint, log.status, log.durationMs, log.error ?? null],
        )
        .catch(() => undefined);
    },
  });
}

/** Catalog data changes rarely and has a stricter rate limit: cache it (default 24h). */
export async function cachedCatalog<T>(
  pool: pg.Pool,
  key: string,
  ttlHours: number,
  load: () => Promise<T>,
): Promise<T> {
  const hit = await pool.query(
    `select payload from public.printify_catalog_cache where cache_key = $1 and expires_at > now()`,
    [key],
  );
  if (hit.rowCount) return hit.rows[0].payload as T;
  const value = await load();
  await pool.query(
    `insert into public.printify_catalog_cache (cache_key, payload, fetched_at, expires_at)
     values ($1, $2, now(), now() + make_interval(hours => $3))
     on conflict (cache_key) do update set payload = excluded.payload, fetched_at = now(), expires_at = excluded.expires_at`,
    [key, JSON.stringify(value), ttlHours],
  );
  return value;
}

export interface PrintifySyncResult {
  skipped?: string;
  products: number;
  variants: number;
  costChanges: number;
  orders: number;
  ordersMatched: number;
  lineCostBasis: string;
}

/**
 * Imports Printify products (variants, production cost, shipping profile costs,
 * mockups) and Printify orders (production status, actual costs, shipments) and
 * links them to Etsy listings/orders. Costs are versioned: a changed cost closes the
 * previous row (valid_to) and adds a new one, so cost changes are traceable.
 */
export async function syncPrintifyStore(
  pool: pg.Pool,
  deps: PrintifyDeps,
  storeId: string,
): Promise<PrintifySyncResult> {
  const conn = await loadPrintifyConnection(pool, storeId);
  const res: PrintifySyncResult = {
    products: 0,
    variants: 0,
    costChanges: 0,
    orders: 0,
    ordersMatched: 0,
    lineCostBasis: 'unverified',
  };
  if (!conn) return { ...res, skipped: 'no active Printify connection' };
  const client = printifyClientFor(pool, deps, storeId);

  try {
    const variantCost = new Map<string, number>(); // `${productId}:${variantId}` -> cents
    for await (const p of client.iterateProducts(conn.shopId)) {
      const blueprint = await cachedCatalog(pool, `blueprint:${p.blueprint_id}`, 168, () =>
        client.getBlueprint(p.blueprint_id),
      ).catch(() => null);
      const shipping = await cachedCatalog(
        pool,
        `shipping:${p.blueprint_id}:${p.print_provider_id}`,
        24,
        () => client.getShipping(p.blueprint_id, p.print_provider_id),
      ).catch(() => null);
      const out = await upsertProduct(
        pool,
        storeId,
        p,
        blueprint?.title ?? `Blueprint ${p.blueprint_id}`,
        shipping,
      );
      res.products++;
      res.variants += out.variants;
      res.costChanges += out.costChanges;
      for (const v of p.variants) variantCost.set(`${p.id}:${v.id}`, v.cost);
    }

    let basis = String(conn.metadata.line_cost_basis ?? 'unverified');
    for await (const o of client.iterateOrders(conn.shopId, 4)) {
      res.orders++;
      basis = detectLineCostBasis(o, variantCost, basis);
      if (await upsertPrintifyOrder(pool, storeId, o, basis)) res.ordersMatched++;
    }
    res.lineCostBasis = basis;

    await pool.query(
      `update public.connected_accounts set last_synced_at = now(), last_error = null,
              metadata = metadata || jsonb_build_object('line_cost_basis', $2::text)
        where id = $1`,
      [conn.accountId, basis],
    );
    if (res.costChanges > 0 && conn.metadata.initial_sync_done) {
      await notifyAdmins(
        pool,
        storeId,
        'printify.cost_changed',
        'warning',
        'Printify maliyetleri değişti',
        `${res.costChanges} varyantın maliyeti değişti. Kâr hesaplarını kontrol edin.`,
        '/dashboard/products',
      );
    }
    await pool.query(
      `update public.connected_accounts set metadata = metadata || '{"initial_sync_done": true}'::jsonb where id = $1`,
      [conn.accountId],
    );
    return res;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const auth = (err as { status?: number }).status === 401;
    await pool.query(
      `update public.connected_accounts set last_error = $2, status = case when $3 then 'expired' else status end where id = $1`,
      [conn.accountId, message.slice(0, 500), auth],
    );
    if (auth) {
      await notifyAdmins(
        pool,
        storeId,
        'printify.auth_failed',
        'critical',
        'Printify token geçersiz',
        'PRINTIFY_API_TOKEN geçersiz veya süresi dolmuş (kişisel token 1 yıl geçerlidir). Yeni token oluşturup .env dosyasına girin.',
        '/dashboard/printify',
      );
    }
    throw err;
  }
}

/**
 * The docs do not state whether line_items[].cost is per unit or per line.
 * With a quantity > 1 line whose product variant cost is known we can tell:
 * cost == unit*qty => 'line_total', cost == unit => 'per_unit'. Until then: 'unverified'.
 */
export function detectLineCostBasis(
  o: PrintifyOrder,
  variantCost: Map<string, number>,
  current: string,
): string {
  if (current === 'per_unit' || current === 'line_total') return current;
  for (const li of o.line_items) {
    if (li.quantity <= 1) continue;
    const unit = variantCost.get(`${li.product_id}:${li.variant_id}`);
    if (!unit) continue;
    if (li.cost === unit * li.quantity) return 'line_total';
    if (li.cost === unit) return 'per_unit';
  }
  return current;
}

function lineTotalCents(cost: number, qty: number, basis: string): number {
  return basis === 'line_total' ? cost : cost * qty; // 'per_unit' and 'unverified' (assumed per unit)
}

async function upsertProduct(
  pool: pg.Pool,
  storeId: string,
  p: PrintifyProduct,
  blueprintTitle: string,
  shipping: PrintifyShippingV1 | null,
): Promise<{ variants: number; costChanges: number }> {
  const c = await pool.connect();
  let variants = 0;
  let costChanges = 0;
  try {
    await c.query('begin');
    const external = p.external?.id ? String(p.external.id) : null;
    const pr = await c.query(
      `insert into public.products
         (store_id, title, product_type, status, printify_product_id, printify_blueprint_id, printify_print_provider_id,
          data_origin, metadata, printify_visible, printify_is_locked, external_listing_id, printify_synced_at)
       values ($1,$2,$3,$4,$5,$6,$7,'live',$8,$9,$10,$11,now())
       on conflict (store_id, printify_product_id) where printify_product_id is not null do update set
         title = excluded.title, product_type = excluded.product_type,
         status = case when public.products.status = 'archived' then 'archived' else excluded.status end,
         printify_blueprint_id = excluded.printify_blueprint_id, printify_print_provider_id = excluded.printify_print_provider_id,
         metadata = public.products.metadata || excluded.metadata, printify_visible = excluded.printify_visible,
         printify_is_locked = excluded.printify_is_locked, external_listing_id = excluded.external_listing_id,
         printify_synced_at = now()
       returning id`,
      [
        storeId,
        p.title,
        blueprintTitle,
        external ? 'published' : 'draft',
        p.id,
        p.blueprint_id,
        p.print_provider_id,
        JSON.stringify({
          tags: p.tags,
          description: p.description,
          printify_updated_at: p.updated_at,
        }),
        p.visible,
        p.is_locked,
        external,
      ],
    );
    const productId: string = pr.rows[0].id;
    if (external) {
      await c.query(
        `update public.listings set product_id = $3 where store_id = $1 and etsy_listing_id = $2`,
        [storeId, external, productId],
      );
    }

    for (const v of p.variants) {
      const vr = await c.query(
        `insert into public.product_variants (product_id, store_id, sku, title, options, printify_variant_id, price, currency, is_enabled, is_available)
         values ($1,$2,$3,$4,$5,$6,$7,'USD',$8,$9)
         on conflict (product_id, printify_variant_id) where printify_variant_id is not null do update set
           sku = excluded.sku, title = excluded.title, options = excluded.options, price = excluded.price,
           is_enabled = excluded.is_enabled, is_available = excluded.is_available
         returning id`,
        [
          productId,
          storeId,
          v.sku || null,
          v.title,
          JSON.stringify({ option_ids: v.options ?? [] }),
          v.id,
          centsToDecimal(v.price),
          v.is_enabled,
          v.is_available ?? null,
        ],
      );
      const variantId: string = vr.rows[0].id;
      variants++;
      if (await versionCost(c, storeId, variantId, 'production', centsToDecimal(v.cost)!, null))
        costChanges++;

      // a variant appears in several profiles (one per destination group): store them all
      for (const profile of shipping?.profiles.filter((pf) => pf.variant_ids.includes(v.id)) ??
        []) {
        for (const country of profile.countries) {
          const isRow = country === 'REST_OF_THE_WORLD';
          if (!isRow && !/^[A-Z]{2}$/.test(country)) continue;
          const cc = isRow ? null : country;
          if (
            await versionCost(
              c,
              storeId,
              variantId,
              'shipping_first_item',
              centsToDecimal(profile.first_item.cost)!,
              cc,
              profile.first_item.currency,
            )
          )
            costChanges++;
          if (
            await versionCost(
              c,
              storeId,
              variantId,
              'shipping_additional_item',
              centsToDecimal(profile.additional_items.cost)!,
              cc,
              profile.additional_items.currency,
            )
          )
            costChanges++;
        }
      }
    }

    await c.query(
      `delete from public.product_images where product_id = $1 and source = 'printify_mockup'`,
      [productId],
    );
    const images = [...p.images]
      .sort((a, b) => Number(b.is_default) - Number(a.is_default))
      .slice(0, 20);
    for (const [i, img] of images.entries()) {
      await c.query(
        `insert into public.product_images (product_id, store_id, source_url, source, position, alt_text)
         values ($1,$2,$3,'printify_mockup',$4,$5)`,
        [productId, storeId, img.src, i, `${p.title} – ${img.position}`],
      );
    }
    await c.query('commit');
    return { variants, costChanges };
  } catch (err) {
    await c.query('rollback').catch(() => undefined);
    throw err;
  } finally {
    c.release();
  }
}

/** Inserts a new cost version if it differs from the current one. Returns true when changed. */
async function versionCost(
  c: pg.PoolClient,
  storeId: string,
  variantId: string,
  costType: string,
  amount: string,
  country: string | null,
  currency = 'USD',
): Promise<boolean> {
  const cur = await c.query(
    `select id, amount::text, currency from public.product_costs
      where product_variant_id = $1 and cost_type = $2 and destination_country is not distinct from $3 and valid_to is null
      order by valid_from desc limit 1`,
    [variantId, costType, country],
  );
  const row = cur.rows[0];
  if (row && Number(row.amount) === Number(amount) && row.currency === currency) return false;
  if (row)
    await c.query(`update public.product_costs set valid_to = now() where id = $1`, [row.id]);
  await c.query(
    `insert into public.product_costs (product_variant_id, store_id, cost_type, amount, currency, destination_country, source)
     values ($1,$2,$3,$4,$5,$6,'printify_api')`,
    [variantId, storeId, costType, amount, currency, country],
  );
  return Boolean(row); // first insert is not a "change"
}

/** Links a Printify order to the Etsy order (metadata.shop_order_id = Etsy receipt id). */
async function upsertPrintifyOrder(
  pool: pg.Pool,
  storeId: string,
  o: PrintifyOrder,
  basis: string,
): Promise<boolean> {
  const shopOrderId = o.metadata?.shop_order_id ? String(o.metadata.shop_order_id) : null;
  const local = shopOrderId
    ? await pool.query(
        `select id from public.orders where store_id = $1 and (etsy_receipt_id = $2 or printify_order_id = $3)`,
        [storeId, shopOrderId, o.id],
      )
    : await pool.query(
        `select id from public.orders where store_id = $1 and printify_order_id = $2`,
        [storeId, o.id],
      );
  const orderId: string | undefined = local.rows[0]?.id;
  if (!orderId) return false;

  const prodTotal = o.line_items.reduce(
    (s, li) => s + lineTotalCents(li.cost, li.quantity, basis),
    0,
  );
  const shipTotal = o.line_items.reduce((s, li) => s + (li.shipping_cost ?? 0), 0);
  await pool.query(
    `update public.orders set printify_order_id = $2, printify_status = $3, printify_cost_total = $4,
            printify_shipping_total = $5, printify_tax_total = $6, printify_currency = 'USD', printify_synced_at = now(),
            sent_to_production_at = $7, fulfilled_at = $8,
            raw = coalesce(raw, '{}'::jsonb) || jsonb_build_object('printify', $9::jsonb)
      where id = $1`,
    [
      orderId,
      o.id,
      o.status,
      centsToDecimal(prodTotal),
      centsToDecimal(shipTotal),
      centsToDecimal(o.total_tax ?? 0),
      o.sent_to_production_at ?? null,
      o.fulfilled_at ?? null,
      JSON.stringify({ line_cost_basis: basis, line_items: o.line_items, status: o.status }),
    ],
  );
  for (const li of o.line_items) {
    await pool.query(
      `update public.order_items oi set printify_line_item_id = $3, printify_product_id = $4, printify_variant_id = $5,
              production_cost = $6, production_shipping_cost = $7, printify_status = $8,
              product_variant_id = coalesce(oi.product_variant_id,
                (select v.id from public.product_variants v join public.products p on p.id = v.product_id
                  where p.store_id = $2 and p.printify_product_id = $4 and v.printify_variant_id = $5))
        where oi.order_id = $1 and oi.id = (
          select oi2.id from public.order_items oi2 left join public.listings l on l.id = oi2.listing_id
            left join public.products p2 on p2.id = l.product_id
           where oi2.order_id = $1 and (p2.printify_product_id = $4 or oi2.printify_line_item_id = $3 or
                 (select count(*) from public.order_items x where x.order_id = $1) = 1)
           order by (oi2.printify_line_item_id = $3) desc nulls last limit 1)`,
      [
        orderId,
        storeId,
        li.id ?? null,
        li.product_id,
        li.variant_id,
        centsToDecimal(lineTotalCents(li.cost, li.quantity, basis)),
        centsToDecimal(li.shipping_cost ?? 0),
        li.status,
      ],
    );
  }
  for (const s of o.shipments ?? []) {
    await pool.query(
      `insert into public.shipments (order_id, store_id, carrier, tracking_number, tracking_url, status, delivered_at)
       values ($1,$2,$3,$4,$5,$6,$7)
       on conflict (order_id, coalesce(tracking_number, '')) do update set carrier = excluded.carrier,
         tracking_url = coalesce(excluded.tracking_url, public.shipments.tracking_url),
         status = excluded.status, delivered_at = coalesce(excluded.delivered_at, public.shipments.delivered_at)`,
      [
        orderId,
        storeId,
        s.carrier,
        s.number,
        s.url,
        s.delivered_at ? 'delivered' : 'in_transit',
        s.delivered_at,
      ],
    );
  }
  return true;
}
