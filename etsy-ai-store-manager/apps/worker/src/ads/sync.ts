import type pg from 'pg';
import { MetaAdsClient, metaPurchases } from '@esm/integrations';
import { etsyClientFor, loadEtsyConnection, type IntegrationDeps } from '../etsy/deps.js';
import { notifyAdmins } from '../etsy/sync.js';

const ZERO_DECIMAL = new Set([
  'JPY',
  'KRW',
  'VND',
  'CLP',
  'ISK',
  'HUF',
  'TWD',
  'UGX',
  'XAF',
  'XOF',
]);
/** Etsy ledger amounts are integers (minor units assumed; see docs/operations/phase-8-report.md). */
export function ledgerAmount(amount: number, currency: string): string {
  return ZERO_DECIMAL.has(currency.toUpperCase()) ? String(amount) : (amount / 100).toFixed(2);
}
const day = (d: Date) => d.toISOString().slice(0, 10);

/**
 * Meta Ads (read-only): daily campaign insights for the last `days` days.
 * Writes campaigns, ad_metrics (source api_report) and — when the account books spend
 * from metrics — the ad_spend ledger (one row per campaign/day, idempotent).
 */
export async function syncMetaAccount(
  pool: pg.Pool,
  deps: IntegrationDeps,
  adAccountId: string,
  days = 30,
) {
  const acc = (
    await pool.query(
      `select a.*, t.access_token_ciphertext from public.ad_accounts a
         join public.connected_accounts ca on ca.id = a.connected_account_id
         join public.oauth_tokens t on t.connected_account_id = ca.id
        where a.id = $1 and a.platform = 'meta_ads' and a.status = 'active' and ca.status = 'active'`,
      [adAccountId],
    )
  ).rows[0];
  if (!acc) return { skipped: 'no active Meta connection' };
  if (!deps.cipher) throw new Error('TOKEN_ENCRYPTION_KEY tanımlı değil');
  const token = deps.cipher.decrypt(
    acc.access_token_ciphertext,
    `connected_account:${acc.connected_account_id}`,
  );
  const client = new MetaAdsClient({
    accessToken: token,
    baseUrl: deps.metaBaseUrl,
    fetchImpl: deps.fetchImpl,
    sleep: deps.sleep,
  });
  const until = new Date();
  const since = new Date(Date.now() - (days - 1) * 86_400_000);
  let rows = 0;
  const unmatched = new Set<string>();
  try {
    for await (const r of client.iterateDailyCampaignInsights(
      acc.external_account_id,
      day(since),
      day(until),
    )) {
      const camp = await pool.query(
        `insert into public.ad_campaigns (ad_account_id, store_id, external_campaign_id, name, status, currency, managed_via)
         values ($1,$2,$3,$4,'active',$5,'manual')
         on conflict (ad_account_id, external_campaign_id) where external_campaign_id is not null
           do update set name = excluded.name
         returning id`,
        [acc.id, acc.store_id, r.campaign_id, r.campaign_name.slice(0, 200), acc.currency],
      );
      const p = metaPurchases(r);
      if (!p.actionType) unmatched.add(r.campaign_name);
      await pool.query(
        `insert into public.ad_metrics (campaign_id, store_id, metric_date, impressions, clicks, spend, conversions,
                                        conversion_value, currency, attribution_model, attribution_confidence, source)
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'medium','api_report')
         on conflict (campaign_id, metric_date) do update set impressions = excluded.impressions, clicks = excluded.clicks,
           spend = excluded.spend, conversions = excluded.conversions, conversion_value = excluded.conversion_value,
           attribution_model = excluded.attribution_model, source = excluded.source`,
        [
          camp.rows[0].id,
          acc.store_id,
          r.date_start,
          Number(r.impressions ?? 0),
          Number(r.clicks ?? 0),
          r.spend ?? '0',
          p.conversions,
          p.value,
          acc.currency,
          `meta default (7d click + 1d view)${p.actionType ? `; ${p.actionType}` : ''}`,
        ],
      );
      if (acc.spend_source === 'metrics') {
        await pool.query(
          `insert into public.ad_spend (store_id, ad_account_id, campaign_id, spend_date, amount, currency, source, external_ref)
           values ($1,$2,$3,$4,$5,$6,'api_report',$7)
           on conflict (ad_account_id, spend_date, coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), source)
             do update set amount = excluded.amount`,
          [
            acc.store_id,
            acc.id,
            camp.rows[0].id,
            r.date_start,
            r.spend ?? '0',
            acc.currency,
            `meta:${r.campaign_id}`,
          ],
        );
      }
      rows++;
    }
    await pool.query(
      `update public.ad_accounts set last_synced_at = now(), last_error = null where id = $1`,
      [acc.id],
    );
    return { rows, campaignsWithoutPurchaseAction: [...unmatched] };
  } catch (err) {
    const message = err instanceof Error ? err.message.slice(0, 500) : String(err);
    await pool.query(`update public.ad_accounts set last_error = $2 where id = $1`, [
      acc.id,
      message,
    ]);
    if ((err as { isAuthError?: boolean }).isAuthError) {
      await pool.query(
        `update public.connected_accounts set status = 'expired', last_error = $2 where id = $1`,
        [acc.connected_account_id, message],
      );
      await notifyAdmins(
        pool,
        acc.store_id,
        'ads.meta_auth',
        'critical',
        'Meta reklam erişimi geçersiz',
        message,
        '/dashboard/ads',
      );
    }
    throw err;
  }
}

/**
 * Imports Etsy payment-ledger entries (transactions_r) and rebuilds Etsy Ads spend from the
 * ledger types the owner mapped as Etsy Ads. Etsy does not document ledger_type values.
 */
export async function importEtsyLedger(
  pool: pg.Pool,
  deps: IntegrationDeps,
  storeId: string,
  days = 35,
) {
  const conn = await loadEtsyConnection(pool, storeId);
  if (!conn) return { skipped: 'no active Etsy connection' };
  const client = etsyClientFor(pool, deps, conn);
  const now = Math.floor(Date.now() / 1000);
  let imported = 0;
  // query in 30-day windows (the allowed range is not documented)
  for (let end = now; end > now - days * 86400; end -= 30 * 86400) {
    const start = Math.max(end - 30 * 86400, now - days * 86400);
    let offset = 0;
    for (;;) {
      const page = await client.getLedgerEntries(conn.shopId, {
        minCreated: start,
        maxCreated: end,
        limit: 100,
        offset,
      });
      for (const e of page.results) {
        await pool.query(
          `insert into public.etsy_ledger_entries (store_id, entry_id, ledger_type, reference_type, reference_id, description,
                                                   amount, currency, entry_created_at)
           values ($1,$2,$3,$4,$5,$6,$7,$8,to_timestamp($9))
           on conflict (store_id, entry_id) do nothing`,
          [
            storeId,
            e.entry_id,
            e.ledger_type,
            e.reference_type,
            e.reference_id === null ? null : String(e.reference_id),
            e.description?.slice(0, 500) ?? null,
            ledgerAmount(e.amount, e.currency),
            e.currency.toUpperCase(),
            e.created_timestamp ?? e.create_date,
          ],
        );
        imported++;
      }
      offset += page.results.length;
      if (!page.results.length || offset >= page.count) break;
    }
  }
  const rebuilt = await rebuildEtsyAdsSpend(pool, storeId);
  return { imported, ...rebuilt };
}

/** Daily Etsy Ads spend = −(sum of mapped ledger debits); replaces earlier ledger-sourced rows. */
export async function rebuildEtsyAdsSpend(pool: pg.Pool, storeId: string) {
  const types = (
    await pool.query(
      `select etsy_ads_ledger_types from public.store_settings where store_id = $1`,
      [storeId],
    )
  ).rows[0]?.etsy_ads_ledger_types as string[] | undefined;
  const acc = (
    await pool.query(
      `select id, currency from public.ad_accounts where store_id = $1 and platform = 'etsy_ads' and spend_source = 'ledger' limit 1`,
      [storeId],
    )
  ).rows[0];
  if (!acc) return { days: 0, note: 'Etsy Ads hesabı “ledger” kaynağında değil' };
  const c = await pool.connect();
  try {
    await c.query('begin');
    await c.query(
      `delete from public.ad_spend where ad_account_id = $1 and source = 'platform_invoice'`,
      [acc.id],
    );
    const r = await c.query(
      `insert into public.ad_spend (store_id, ad_account_id, spend_date, amount, currency, source, external_ref)
       select $1, $2, (entry_created_at at time zone 'UTC')::date, -sum(amount), currency, 'platform_invoice', 'etsy_ledger'
         from public.etsy_ledger_entries
        where store_id = $1 and ledger_type = any($3::text[])
        group by (entry_created_at at time zone 'UTC')::date, currency
       having -sum(amount) > 0`,
      [storeId, acc.id, types ?? []],
    );
    await c.query('commit');
    return { days: r.rowCount ?? 0 };
  } catch (e) {
    await c.query('rollback');
    throw e;
  } finally {
    c.release();
  }
}

export async function syncAdsStore(pool: pg.Pool, deps: IntegrationDeps, storeId: string) {
  const out: Record<string, unknown> = {};
  const metas = await pool.query(
    `select id from public.ad_accounts where store_id = $1 and platform = 'meta_ads' and status = 'active' and connected_account_id is not null`,
    [storeId],
  );
  for (const m of metas.rows) out[`meta:${m.id}`] = await syncMetaAccount(pool, deps, m.id);
  const ledger = await pool.query(
    `select 1 from public.ad_accounts where store_id = $1 and platform = 'etsy_ads' and spend_source = 'ledger'`,
    [storeId],
  );
  if (ledger.rowCount) out.etsyLedger = await importEtsyLedger(pool, deps, storeId);
  return out;
}
