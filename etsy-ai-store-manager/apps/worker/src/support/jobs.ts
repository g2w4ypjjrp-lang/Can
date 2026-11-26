import type pg from 'pg';
import { createAnthropic, emptyUsage, triageCustomerMessage, type AiUsage } from '@esm/ai-engine';
import { etsyClientFor, loadEtsyConnection, type IntegrationDeps } from '../etsy/deps.js';
import { finishTask, startTask } from '../designs/jobs.js';
import { notifyAdmins } from '../etsy/sync.js';

/** Reviews at or below this rating become inbound messages for triage. */
export const LOW_RATING = 3;

/**
 * Imports Etsy shop reviews (getReviewsByShop). Low ratings are turned into inbound
 * messages for AI triage; nothing is ever sent to the buyer automatically.
 */
export async function syncShopReviews(pool: pg.Pool, deps: IntegrationDeps, storeId: string) {
  const conn = await loadEtsyConnection(pool, storeId);
  if (!conn) return { skipped: 'no active Etsy connection' };
  const client = etsyClientFor(pool, deps, conn);
  const since = Number(conn.metadata.reviews_cursor ?? 0) || 0;
  let cursor = since;
  let imported = 0;
  let low = 0;
  let offset = 0;
  for (;;) {
    const page = await client.getShopReviews(conn.shopId, {
      limit: 100,
      offset,
      ...(since ? { minCreated: Math.max(0, since - 86400) } : {}),
    });
    for (const r of page.results) {
      const created = r.created_timestamp ?? r.create_timestamp;
      cursor = Math.max(cursor, created);
      const row = await pool.query(
        `insert into public.shop_reviews (store_id, etsy_listing_id, listing_id, rating, review, language, etsy_created_at, etsy_updated_at)
         values ($1,$2,(select id from public.listings where store_id = $1 and etsy_listing_id = $2),$3,$4,$5,to_timestamp($6),
                 case when $7::bigint is null then null else to_timestamp($7) end)
         on conflict (store_id, etsy_listing_id, etsy_created_at) do update set rating = excluded.rating, review = excluded.review,
           etsy_updated_at = excluded.etsy_updated_at
         returning id, (xmax = 0) as inserted`,
        [
          storeId,
          r.listing_id,
          r.rating,
          r.review,
          r.language,
          created,
          r.updated_timestamp ?? r.update_timestamp ?? null,
        ],
      );
      imported++;
      if (r.rating <= LOW_RATING) {
        const m = await pool.query(
          `insert into public.customer_messages (store_id, direction, channel, body, status, source, review_id, received_at)
           values ($1,'inbound','etsy',$2,'new','etsy_review',$3,to_timestamp($4))
           on conflict (review_id) where review_id is not null do nothing returning id`,
          [storeId, r.review?.trim() || `(${r.rating}★ yorum, metin yok)`, row.rows[0].id, created],
        );
        if (m.rowCount) low++;
      }
    }
    offset += page.results.length;
    if (!page.results.length || offset >= page.count) break;
  }
  await pool.query(
    `update public.connected_accounts set metadata = metadata || jsonb_build_object('reviews_cursor', $2::bigint) where id = $1`,
    [conn.accountId, cursor],
  );
  if (low)
    await notifyAdmins(
      pool,
      storeId,
      'reviews.low_rating',
      'warning',
      'Düşük puanlı yeni yorum',
      `${low} yeni düşük puanlı yorum. Müşteriler sayfasında AI yanıt taslağı hazırlanıyor.`,
      '/dashboard/customers',
    );
  return { imported, lowRatingMessages: low };
}

/**
 * AI triage of one inbound message: category, sentiment, urgency, issues, suggested action
 * and a reply DRAFT in the customer's language, grounded in the order facts we hold.
 */
export async function triageMessage(
  pool: pg.Pool,
  deps: { anthropic: { apiKey: string; baseURL?: string | undefined } | null },
  messageId: string,
  userId: string | null,
) {
  const m = (await pool.query(`select * from public.customer_messages where id = $1`, [messageId]))
    .rows[0];
  if (!m) throw new Error('message not found');
  if (!['new', 'classifying', 'failed'].includes(m.status))
    return { skipped: true, status: m.status };
  if (!deps.anthropic) {
    await pool.query(
      `update public.customer_messages set status = 'failed', ai_error = $2 where id = $1`,
      [messageId, 'ANTHROPIC_API_KEY tanımlı değil'],
    );
    return { failed: true };
  }
  await pool.query(
    `update public.customer_messages set status = 'classifying', ai_error = null where id = $1`,
    [messageId],
  );
  const store = (
    await pool.query(
      `select s.name, ss.processing_days_max, ss.transit_days_max from public.stores s
         join public.store_settings ss on ss.store_id = s.id where s.id = $1`,
      [m.store_id],
    )
  ).rows[0];
  const facts: string[] = [];
  if (m.order_id) {
    const o = (
      await pool.query(
        `select o.status, o.placed_at, o.shipped_at, o.printify_status, o.grand_total::text, o.currency,
                (select json_agg(json_build_object('carrier', sh.carrier, 'tracking', sh.tracking_number, 'status', sh.status, 'url', sh.tracking_url))
                   from public.shipments sh where sh.order_id = o.id) as shipments,
                (select string_agg(i.title || ' ×' || i.quantity, ', ') from public.order_items i where i.order_id = o.id) as items
           from public.orders o where o.id = $1`,
        [m.order_id],
      )
    ).rows[0];
    if (o) {
      facts.push(
        `Order status: ${o.status}${o.printify_status ? ` (production: ${o.printify_status})` : ''}`,
      );
      facts.push(
        `Placed: ${new Date(o.placed_at).toISOString().slice(0, 10)}; total ${o.grand_total} ${o.currency}`,
      );
      if (o.items) facts.push(`Items: ${o.items}`);
      for (const s of o.shipments ?? [])
        facts.push(
          `Shipment: ${s.carrier ?? 'carrier?'} ${s.tracking ?? ''} status ${s.status}${s.url ? ` ${s.url}` : ''}`,
        );
      if (!o.shipments?.length) facts.push('No shipment/tracking yet.');
    }
  }
  if (m.source === 'etsy_review') {
    const r = (
      await pool.query(`select rating from public.shop_reviews where id = $1`, [m.review_id])
    ).rows[0];
    if (r)
      facts.push(
        `This is a public Etsy review with rating ${r.rating}/5 (the reply is a public shop response).`,
      );
  }
  facts.push(
    `Typical processing up to ${store.processing_days_max} days, transit up to ${store.transit_days_max} days.`,
  );

  const taskId = await startTask(
    pool,
    m.store_id,
    'support_triage',
    `support_triage:${messageId}:${Date.now()}`,
    { messageId },
    userId,
  );
  let usage: AiUsage = emptyUsage();
  try {
    const out = await triageCustomerMessage(
      createAnthropic(deps.anthropic),
      { shopName: store.name, message: m.body, facts, isPublicReview: m.source === 'etsy_review' },
      usage,
    );
    usage = out.usage;
    const t = out.triage;
    await pool.query(
      `update public.customer_messages set status = 'draft_ready', category = $2, sentiment = $3, urgency = $4, issues = $5,
              suggested_action = $6, ai_draft = $7, internal_note = $8, draft_language = $9, ai_task_id = $10
        where id = $1`,
      [
        messageId,
        t.category,
        t.sentiment,
        t.urgency,
        JSON.stringify(t.issues),
        t.suggestedAction,
        t.replyDraft,
        t.internalNote,
        t.language,
        taskId,
      ],
    );
    await finishTask(pool, taskId, 'succeeded', usage, {
      messageId,
      category: t.category,
      urgency: t.urgency,
    });
    if (t.urgency === 'critical' || t.urgency === 'high')
      await notifyAdmins(
        pool,
        m.store_id,
        'support.urgent',
        'warning',
        'Acil müşteri konusu',
        `${t.category}: ${t.internalNote.slice(0, 200)}`,
        '/dashboard/customers',
      );
    return { messageId, category: t.category, urgency: t.urgency };
  } catch (err) {
    const message = err instanceof Error ? err.message.slice(0, 500) : String(err);
    await finishTask(pool, taskId, 'failed', usage, null, message);
    await pool.query(
      `update public.customer_messages set status = 'failed', ai_error = $2, ai_task_id = $3 where id = $1`,
      [messageId, message, taskId],
    );
    return { failed: true, error: message };
  }
}

/** Flags late orders and shipments from the store's processing / transit windows. */
export async function detectDelays(pool: pg.Pool, storeId: string) {
  const s = await pool.query(
    `update public.shipments sh set status = 'delayed'
       from public.store_settings ss
      where sh.store_id = $1 and ss.store_id = sh.store_id and sh.status = 'in_transit'
        and sh.shipped_at < now() - make_interval(days => ss.transit_days_max)
     returning sh.id`,
    [storeId],
  );
  const late = await pool.query(
    `select count(*)::int n from public.orders o join public.store_settings ss on ss.store_id = o.store_id
      where o.store_id = $1 and o.status in ('open','paid','in_production') and o.shipped_at is null
        and coalesce(o.paid_at, o.placed_at) < now() - make_interval(days => ss.processing_days_max)`,
    [storeId],
  );
  const recent = await pool.query(
    `select 1 from public.notifications where store_id = $1 and type = 'orders.delayed' and created_at > now() - interval '20 hours' limit 1`,
    [storeId],
  );
  if ((s.rowCount || late.rows[0].n) && !recent.rowCount)
    await notifyAdmins(
      pool,
      storeId,
      'orders.delayed',
      'warning',
      'Geciken siparişler',
      `${late.rows[0].n} sipariş işlem süresini aştı, ${s.rowCount ?? 0} kargo teslimat süresini aştı.`,
      '/dashboard/orders?filter=delayed',
    );
  return { delayedShipments: s.rowCount ?? 0, lateOrders: late.rows[0].n };
}
