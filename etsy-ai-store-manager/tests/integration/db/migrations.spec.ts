import { afterAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { migrate } from '../../../infrastructure/scripts/migrate.mjs';
import { TEST_DATABASE_URL } from '../../helpers/env.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
afterAll(() => pool.end());

const REQUIRED_TABLES = [
  'users',
  'user_settings',
  'connected_accounts',
  'oauth_tokens',
  'stores',
  'store_settings',
  'products',
  'product_variants',
  'product_costs',
  'product_images',
  'designs',
  'design_versions',
  'market_research',
  'competitor_research',
  'keywords',
  'product_opportunities',
  'listings',
  'listing_translations',
  'orders',
  'order_items',
  'shipments',
  'refunds',
  'customers',
  'customer_messages',
  'ad_accounts',
  'ad_campaigns',
  'ad_metrics',
  'ad_spend',
  'fee_rules',
  'fx_rates',
  'profit_rules',
  'profit_snapshots',
  'price_recommendations',
  'tax_reserves',
  'ai_tasks',
  'ai_decisions',
  'approval_requests',
  'automation_jobs',
  'notifications',
  'audit_logs',
  'api_logs',
];

describe('database migrations', () => {
  it('creates all 41 required tables (+ store_members)', async () => {
    const r = await pool.query(`select tablename from pg_tables where schemaname = 'public'`);
    const names = r.rows.map((x) => x.tablename);
    expect(REQUIRED_TABLES).toHaveLength(41);
    for (const t of REQUIRED_TABLES) expect(names, `missing table ${t}`).toContain(t);
    expect(names).toContain('store_members');
  });

  it('enables Row Level Security on every public table', async () => {
    const r = await pool.query(
      `select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity`,
    );
    expect(r.rows.map((x) => x.relname)).toEqual([]);
  });

  it('indexes every foreign key column (leading column)', async () => {
    const r = await pool.query(`
      select conrelid::regclass::text as tbl, a.attname as col
        from pg_constraint c
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
       where c.contype = 'f' and c.connamespace = 'public'::regnamespace
         and not exists (
           select 1 from pg_index i
            where i.indrelid = c.conrelid and i.indkey[0] = c.conkey[1])`);
    // Actor / approval references are lookup-only and intentionally not indexed:
    const allowed = new Set([
      'ai_tasks.created_by',
      'approval_requests.decided_by',
      'approval_requests.requested_by_user_id',
      'connected_accounts.connected_by',
      'design_versions.created_by',
      'designs.created_by',
      'designs.current_version_id',
      'fee_rules.verified_by',
      'market_research.created_by',
      'ai_decisions.approval_request_id',
      'customer_messages.approval_request_id',
      'price_recommendations.approval_request_id',
      'price_recommendations.profit_snapshot_id',
      'refunds.approval_request_id',
    ]);
    const missing = r.rows.map((x) => `${x.tbl}.${x.col}`).filter((k) => !allowed.has(k));
    expect(missing).toEqual([]);
  });

  it('stores money as NUMERIC, never float', async () => {
    const r = await pool.query(`
      select table_name, column_name from information_schema.columns
       where table_schema = 'public' and data_type in ('real','double precision')`);
    expect(r.rows).toEqual([]);
  });

  it('is idempotent when re-run', async () => {
    const result = await migrate({ connectionString: TEST_DATABASE_URL, log: () => undefined });
    expect(result.applied).toBe(0);
    expect(result.total).toBeGreaterThanOrEqual(11);
  });

  it('detects edited (already applied) migrations', async () => {
    const r = await pool.query(
      `select filename from private.schema_migrations order by filename limit 1`,
    );
    await pool.query(
      `update private.schema_migrations set sha256 = 'tampered' where filename = $1`,
      [r.rows[0].filename],
    );
    try {
      await expect(
        migrate({ connectionString: TEST_DATABASE_URL, log: () => undefined }),
      ).rejects.toThrow(/modified/);
    } finally {
      // restore by recomputing: simplest is to re-run with the real hash
      const { createHash } = await import('node:crypto');
      const { readFile } = await import('node:fs/promises');
      const sql = await readFile(
        `packages/database/supabase/migrations/${r.rows[0].filename}`,
        'utf8',
      );
      await pool.query(`update private.schema_migrations set sha256 = $2 where filename = $1`, [
        r.rows[0].filename,
        createHash('sha256').update(sql).digest('hex'),
      ]);
    }
  });

  it('enforces profit threshold ordering and Etsy listing limits at the database level', async () => {
    const { id } = (
      await pool.query(`insert into auth.users (email) values ('ck@example.test') returning id`)
    ).rows[0];
    const store = (
      await pool.query(
        `insert into public.stores (owner_user_id, name) values ($1, 'Constraint shop') returning id`,
        [id],
      )
    ).rows[0];
    await expect(
      pool.query(`update public.profit_rules set publish_threshold = 20 where store_id = $1`, [
        store.id,
      ]),
    ).rejects.toThrow(/profit_rules_threshold_order/);
    await expect(
      pool.query(`insert into public.listings (store_id, title, tags) values ($1, 't', $2)`, [
        store.id,
        Array.from({ length: 14 }, (_, i) => `tag${i}`),
      ]),
    ).rejects.toThrow(/check/);
    await expect(
      pool.query(`insert into public.listings (store_id, title) values ($1, $2)`, [
        store.id,
        'x'.repeat(141),
      ]),
    ).rejects.toThrow(/check/);
  });
});
