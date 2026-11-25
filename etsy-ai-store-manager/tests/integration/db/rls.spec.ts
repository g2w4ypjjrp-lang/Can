import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { asUser, createAuthUser } from '../../helpers/auth.js';
import { TEST_DATABASE_URL } from '../../helpers/env.js';

const pool = new pg.Pool({ connectionString: TEST_DATABASE_URL });
let alice: { id: string }, bob: { id: string }, carol: { id: string };
let aliceStore: string;

beforeAll(async () => {
  alice = await createAuthUser(pool, 'Alice');
  bob = await createAuthUser(pool, 'Bob');
  carol = await createAuthUser(pool, 'Carol');
  aliceStore = await asUser(pool, alice.id, async (c) => {
    const id = crypto.randomUUID();
    await c.query(
      `insert into public.stores (id, owner_user_id, name) values ($1, $2, 'Alice Shop')`,
      [id, alice.id],
    );
    return id;
  });
  // Carol is a read-only viewer of Alice's store
  await pool.query(
    `insert into public.store_members (store_id, user_id, role) values ($1, $2, 'viewer')`,
    [aliceStore, carol.id],
  );
});
afterAll(() => pool.end());

describe('provisioning triggers', () => {
  it('creates profile + settings for a new auth user', async () => {
    const r = await pool.query(
      `select u.full_name, s.ui_language, s.base_currency from public.users u
         join public.user_settings s on s.user_id = u.id where u.id = $1`,
      [alice.id],
    );
    expect(r.rows[0]).toEqual({ full_name: 'Alice', ui_language: 'tr', base_currency: 'USD' });
  });
  it('creates owner membership, store settings and default profit rules for a new store', async () => {
    const r = await pool.query(
      `select m.role, ss.sales_strategy, ss.automation_level, ss.languages, pr.target_contribution,
              pr.excellent_threshold, pr.publish_threshold, pr.review_threshold, pr.min_threshold
         from public.store_members m
         join public.store_settings ss on ss.store_id = m.store_id
         join public.profit_rules pr on pr.store_id = m.store_id
        where m.store_id = $1 and m.user_id = $2`,
      [aliceStore, alice.id],
    );
    expect(r.rows[0]).toEqual({
      role: 'owner',
      sales_strategy: 'balanced',
      automation_level: 'controlled',
      languages: ['en'],
      target_contribution: '10.00',
      excellent_threshold: '15.00',
      publish_threshold: '10.00',
      review_threshold: '7.00',
      min_threshold: '0.00',
    });
  });
});

describe('row level security', () => {
  it("isolates tenants: Bob cannot see or modify Alice's store", async () => {
    const seen = await asUser(pool, bob.id, (c) =>
      c.query(`select id from public.stores where id = $1`, [aliceStore]),
    );
    expect(seen.rowCount).toBe(0);
    const upd = await asUser(pool, bob.id, (c) =>
      c.query(`update public.store_settings set daily_ad_budget_cap = 999 where store_id = $1`, [
        aliceStore,
      ]),
    );
    expect(upd.rowCount).toBe(0);
    const pr = await asUser(pool, bob.id, (c) =>
      c.query(`select * from public.profit_rules where store_id = $1`, [aliceStore]),
    );
    expect(pr.rowCount).toBe(0);
  });

  it('prevents creating stores on behalf of another user', async () => {
    await expect(
      asUser(pool, bob.id, (c) =>
        c.query(`insert into public.stores (owner_user_id, name) values ($1, 'stolen')`, [
          alice.id,
        ]),
      ),
    ).rejects.toThrow(/row-level security/);
  });

  it('prevents inserting data into a store you are not admin of', async () => {
    await expect(
      asUser(pool, bob.id, (c) =>
        c.query(
          `insert into public.products (store_id, title, product_type) values ($1, 'x', 'tshirt')`,
          [aliceStore],
        ),
      ),
    ).rejects.toThrow(/row-level security/);
  });

  it('lets viewers read but not write', async () => {
    const seen = await asUser(pool, carol.id, (c) =>
      c.query(`select id from public.stores where id = $1`, [aliceStore]),
    );
    expect(seen.rowCount).toBe(1);
    const upd = await asUser(pool, carol.id, (c) =>
      c.query(`update public.profit_rules set target_contribution = 1 where store_id = $1`, [
        aliceStore,
      ]),
    );
    expect(upd.rowCount).toBe(0);
  });

  it('hides customer PII from viewers', async () => {
    await pool.query(
      `insert into public.customers (store_id, name, email) values ($1, 'Jane', 'jane@example.test')`,
      [aliceStore],
    );
    const viewer = await asUser(pool, carol.id, (c) =>
      c.query(`select * from public.customers where store_id = $1`, [aliceStore]),
    );
    expect(viewer.rowCount).toBe(0);
    const owner = await asUser(pool, alice.id, (c) =>
      c.query(`select * from public.customers where store_id = $1`, [aliceStore]),
    );
    expect(owner.rowCount).toBe(1);
  });

  it('never exposes oauth tokens to any client role, not even the owner', async () => {
    const acc = await pool.query(
      `insert into public.connected_accounts (store_id, platform, external_account_id, status)
       values ($1, 'etsy', 'shop-1', 'active') returning id`,
      [aliceStore],
    );
    await pool.query(
      `insert into public.oauth_tokens (connected_account_id, access_token_ciphertext) values ($1, 'v1.x.y.z')`,
      [acc.rows[0].id],
    );
    await expect(
      asUser(pool, alice.id, (c) => c.query(`select * from public.oauth_tokens`)),
    ).rejects.toThrow(/permission denied/);
    // but the owner can see the connection status
    const accounts = await asUser(pool, alice.id, (c) =>
      c.query(`select status from public.connected_accounts`),
    );
    expect(accounts.rows).toEqual([{ status: 'active' }]);
  });

  it('gives anon nothing', async () => {
    await expect(asUser(pool, null, (c) => c.query(`select * from public.stores`))).rejects.toThrow(
      /permission denied/,
    );
  });

  it('keeps AI/automation tables read-only for clients', async () => {
    await expect(
      asUser(pool, alice.id, (c) =>
        c.query(`insert into public.ai_tasks (store_id, task_type) values ($1, 'x')`, [aliceStore]),
      ),
    ).rejects.toThrow(/row-level security/);
  });

  it('forbids clients from transferring store ownership', async () => {
    await expect(
      asUser(pool, alice.id, (c) =>
        c.query(`update public.stores set owner_user_id = $1 where id = $2`, [bob.id, aliceStore]),
      ),
    ).rejects.toThrow(/ownership/);
  });

  it('makes audit logs append-only, even for the database owner', async () => {
    const r = await pool.query(
      `insert into public.audit_logs (store_id, actor_type, action) values ($1, 'system', 'test') returning id`,
      [aliceStore],
    );
    await expect(
      pool.query(`update public.audit_logs set action = 'x' where id = $1`, [r.rows[0].id]),
    ).rejects.toThrow(/append-only/);
    await expect(
      pool.query(`delete from public.audit_logs where id = $1`, [r.rows[0].id]),
    ).rejects.toThrow(/append-only/);
  });

  it('notifications are strictly personal', async () => {
    await pool.query(
      `insert into public.notifications (user_id, type, title) values ($1, 'test', 'for alice')`,
      [alice.id],
    );
    const b = await asUser(pool, bob.id, (c) => c.query(`select * from public.notifications`));
    expect(b.rowCount).toBe(0);
    const a = await asUser(pool, alice.id, (c) =>
      c.query(`select title from public.notifications`),
    );
    expect(a.rows.map((x) => x.title)).toContain('for alice');
  });
});
