import type pg from 'pg';
import { EtsyApiError, mapListing, mapReceipt, type EtsyListingState } from '@esm/integrations';
import { etsyClientFor, loadEtsyConnection, type IntegrationDeps } from './deps.js';

/** Listing states imported. `removed` listings are not returned for import by Etsy. */
const LISTING_STATES: EtsyListingState[] = ['active', 'draft', 'inactive', 'expired', 'sold_out'];
/** Overlap when resuming receipts so late updates at the cursor boundary are not missed. */
const RECEIPT_OVERLAP_SECONDS = 24 * 3600;

export interface SyncResult {
  skipped?: string;
  shopId?: string;
  listings: number;
  receipts: number;
  orderItems: number;
  cursor?: number | null;
}

/**
 * Imports shop details, listings (all importable states) and receipts with their
 * transactions, shipments and refunds. Upserts are keyed on Etsy ids, so re-running
 * is safe (idempotent). Local edits never overwrite Etsy here; Etsy is the source of truth
 * for imported fields and the full payload is kept in `raw`.
 */
export async function syncEtsyStore(
  pool: pg.Pool,
  deps: IntegrationDeps,
  storeId: string,
): Promise<SyncResult> {
  const conn = await loadEtsyConnection(pool, storeId);
  if (!conn)
    return { skipped: 'no active Etsy connection', listings: 0, receipts: 0, orderItems: 0 };
  const client = etsyClientFor(pool, deps, conn);
  const result: SyncResult = { shopId: conn.shopId, listings: 0, receipts: 0, orderItems: 0 };

  try {
    const shop = await client.getShop(conn.shopId);
    await pool.query(`update public.stores set shop_url = $2, currency = $3 where id = $1`, [
      storeId,
      shop.url,
      shop.currency_code,
    ]);
    await pool.query(`update public.connected_accounts set display_name = $2 where id = $1`, [
      conn.accountId,
      shop.shop_name,
    ]);

    for (const state of LISTING_STATES) {
      for await (const raw of client.iterateListings(conn.shopId, state, ['Images'])) {
        await upsertListing(pool, storeId, mapListing(raw));
        result.listings++;
      }
    }

    const prevCursor = Number(conn.metadata.receipts_cursor ?? 0) || 0;
    let cursor = prevCursor;
    const since = prevCursor ? Math.max(0, prevCursor - RECEIPT_OVERLAP_SECONDS) : undefined;
    for await (const raw of client.iterateReceipts(conn.shopId, since)) {
      result.orderItems += await upsertReceipt(pool, storeId, mapReceipt(raw));
      result.receipts++;
      cursor = Math.max(cursor, raw.updated_timestamp ?? 0);
    }
    result.cursor = cursor || null;

    await pool.query(
      `update public.connected_accounts
          set last_synced_at = now(), last_error = null,
              metadata = metadata || jsonb_build_object('receipts_cursor', $2::bigint)
        where id = $1`,
      [conn.accountId, cursor],
    );
    await refreshCustomerAggregates(pool, storeId);
    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const authFailure = err instanceof EtsyApiError && err.isAuthError;
    await pool.query(
      `update public.connected_accounts set last_error = $2, status = case when $3 then 'expired' else status end
        where id = $1`,
      [conn.accountId, message.slice(0, 500), authFailure],
    );
    if (authFailure) {
      await notifyAdmins(
        pool,
        storeId,
        'etsy.auth_failed',
        'critical',
        'Etsy bağlantısı yenilenmeli',
        'Etsy erişim izni geçersiz. Etsy Mağazam sayfasından yeniden bağlayın.',
      );
    }
    throw err;
  }
}

type MappedListing = ReturnType<typeof mapListing>;
type MappedReceipt = ReturnType<typeof mapReceipt>;

async function upsertListing(pool: pg.Pool, storeId: string, l: MappedListing) {
  const primary = [...l.images].sort((a, b) => a.rank - b.rank)[0];
  const raw = l.raw as { url?: string; updated_timestamp?: number };
  await pool.query(
    `insert into public.listings
       (store_id, etsy_listing_id, state, title, description, tags, materials, taxonomy_id, price, currency,
        quantity, shipping_profile_id, who_made, when_made, is_supply, num_favorers, raw, data_origin,
        last_synced_at, etsy_url, primary_image_url, etsy_updated_at)
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,'live',now(),$18,$19,$20)
     on conflict (store_id, etsy_listing_id) where etsy_listing_id is not null do update set
       state = excluded.state, title = excluded.title, description = excluded.description,
       tags = excluded.tags, materials = excluded.materials, taxonomy_id = excluded.taxonomy_id,
       price = excluded.price, currency = excluded.currency, quantity = excluded.quantity,
       shipping_profile_id = excluded.shipping_profile_id, who_made = excluded.who_made,
       when_made = excluded.when_made, is_supply = excluded.is_supply, num_favorers = excluded.num_favorers,
       raw = excluded.raw, data_origin = 'live', last_synced_at = now(), etsy_url = excluded.etsy_url,
       primary_image_url = excluded.primary_image_url, etsy_updated_at = excluded.etsy_updated_at`,
    [
      storeId,
      l.etsyListingId,
      l.state,
      l.title || '(başlıksız)',
      l.description,
      l.tags,
      l.materials,
      l.taxonomyId,
      l.price,
      l.currency,
      l.quantity,
      l.shippingProfileId,
      l.whoMade,
      l.whenMade,
      l.isSupply,
      l.numFavorers,
      JSON.stringify(l.raw),
      raw.url ?? null,
      primary?.url ?? null,
      raw.updated_timestamp ? new Date(raw.updated_timestamp * 1000) : null,
    ],
  );
}

/** Returns number of order items written. Runs in one transaction per receipt. */
async function upsertReceipt(pool: pg.Pool, storeId: string, r: MappedReceipt): Promise<number> {
  const c = await pool.connect();
  try {
    await c.query('begin');
    let customerId: string | null = null;
    if (r.customer) {
      const cu = await c.query(
        `insert into public.customers (store_id, etsy_user_id, name, country, data_origin)
         values ($1, $2, $3, $4, 'live')
         on conflict (store_id, etsy_user_id) where etsy_user_id is not null do update
           set name = coalesce(excluded.name, public.customers.name),
               country = coalesce(excluded.country, public.customers.country)
         returning id`,
        [storeId, r.customer.etsyUserId, r.customer.name, r.customer.country?.slice(0, 2) ?? null],
      );
      customerId = cu.rows[0].id;
    }
    const o = await c.query(
      `insert into public.orders
         (store_id, customer_id, etsy_receipt_id, status, currency, subtotal, shipping_total, tax_total,
          discount_total, grand_total, buyer_country, placed_at, paid_at, shipped_at, data_origin, raw)
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'live',$15)
       on conflict (store_id, etsy_receipt_id) where etsy_receipt_id is not null do update set
         customer_id = excluded.customer_id, status = excluded.status, currency = excluded.currency,
         subtotal = excluded.subtotal, shipping_total = excluded.shipping_total, tax_total = excluded.tax_total,
         discount_total = excluded.discount_total, grand_total = excluded.grand_total,
         buyer_country = excluded.buyer_country, paid_at = excluded.paid_at, shipped_at = excluded.shipped_at,
         raw = excluded.raw
       returning id`,
      [
        storeId,
        customerId,
        r.etsyReceiptId,
        r.status,
        r.currency,
        r.subtotal,
        r.shippingTotal,
        r.taxTotal,
        r.discountTotal,
        r.grandTotal,
        r.buyerCountry,
        r.placedAt,
        r.paidAt,
        r.shippedAt,
        JSON.stringify(r.raw),
      ],
    );
    const orderId: string = o.rows[0].id;
    for (const it of r.items) {
      await c.query(
        `insert into public.order_items
           (order_id, store_id, listing_id, etsy_transaction_id, title, quantity, unit_price, currency)
         values ($1, $2, (select id from public.listings where store_id = $2 and etsy_listing_id = $3), $4, $5, $6, $7, $8)
         on conflict (store_id, etsy_transaction_id) where etsy_transaction_id is not null do update set
           listing_id = excluded.listing_id, title = excluded.title, quantity = excluded.quantity,
           unit_price = excluded.unit_price, currency = excluded.currency`,
        [
          orderId,
          storeId,
          it.etsyListingId,
          it.etsyTransactionId,
          it.title,
          it.quantity,
          it.unitPrice,
          it.currency,
        ],
      );
    }
    for (const s of r.shipments) {
      await c.query(
        `insert into public.shipments (order_id, store_id, carrier, tracking_number, status, shipped_at)
         values ($1, $2, $3, $4, 'in_transit', $5)
         on conflict (order_id, coalesce(tracking_number, '')) do update set carrier = excluded.carrier,
           shipped_at = coalesce(public.shipments.shipped_at, excluded.shipped_at)`,
        [orderId, storeId, s.carrier, s.trackingNumber, s.shippedAt],
      );
    }
    for (const f of r.refunds) {
      await c.query(
        `insert into public.refunds (order_id, store_id, amount, currency, reason, status, external_ref, processed_at)
         values ($1, $2, $3, $4, $5, 'processed', $6, $7)
         on conflict (order_id, external_ref) where external_ref is not null do nothing`,
        [
          orderId,
          storeId,
          f.amount,
          f.currency,
          f.reason,
          `etsy:${r.etsyReceiptId}:${f.createdAt}:${f.amount}`,
          f.createdAt,
        ],
      );
    }
    await c.query('commit');
    return r.items.length;
  } catch (err) {
    await c.query('rollback').catch(() => undefined);
    throw err;
  } finally {
    c.release();
  }
}

async function refreshCustomerAggregates(pool: pg.Pool, storeId: string) {
  await pool.query(
    `update public.customers c set
       total_orders = x.n, first_order_at = x.first, last_order_at = x.last
     from (select customer_id, count(*)::int n, min(placed_at) first, max(placed_at) last
             from public.orders where store_id = $1 and customer_id is not null group by customer_id) x
     where c.id = x.customer_id`,
    [storeId],
  );
}

export async function notifyAdmins(
  pool: pg.Pool,
  storeId: string,
  type: string,
  severity: 'info' | 'success' | 'warning' | 'critical',
  title: string,
  body: string,
  link = '/dashboard/etsy',
) {
  await pool.query(
    `insert into public.notifications (user_id, store_id, type, severity, title, body, link)
     select user_id, $1, $2, $3, $4, $5, $6 from public.store_members
      where store_id = $1 and role in ('owner','admin')`,
    [storeId, type, severity, title, body, link],
  );
}
