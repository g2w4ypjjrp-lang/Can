import { Inject, Injectable, OnModuleDestroy } from '@nestjs/common';
import pg from 'pg';
import { ENV, type Env } from '../config/env.js';

export type Queryable = Pick<pg.PoolClient, 'query'>;

export interface AuthContext {
  userId: string;
  email?: string | undefined;
  /** verified JWT claims; forwarded to Postgres so auth.uid() / RLS work */
  claims: Record<string, unknown>;
}

// Keep NUMERIC as string (exact decimals) and timestamps as ISO strings.
pg.types.setTypeParser(pg.types.builtins.NUMERIC, (v) => v);
pg.types.setTypeParser(pg.types.builtins.INT8, (v) => v);
pg.types.setTypeParser(pg.types.builtins.TIMESTAMPTZ, (v) => new Date(v).toISOString());
pg.types.setTypeParser(pg.types.builtins.DATE, (v) => v);

@Injectable()
export class DatabaseService implements OnModuleDestroy {
  readonly pool: pg.Pool;

  constructor(@Inject(ENV) env: Env) {
    this.pool = new pg.Pool({
      connectionString: env.DATABASE_URL,
      max: env.DATABASE_POOL_MAX,
      ssl: env.DATABASE_SSL ? { rejectUnauthorized: true } : undefined,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
      statement_timeout: 15_000,
      application_name: 'esm-api',
    });
  }

  /**
   * Runs `fn` in a transaction as the Postgres `authenticated` role with the
   * caller's JWT claims, so Row Level Security policies apply exactly as they
   * would for the Supabase Data API. Use this for every user-initiated query.
   */
  async asUser<T>(ctx: AuthContext, fn: (db: Queryable) => Promise<T>): Promise<T> {
    return this.tx(async (client) => {
      await client.query('set local role authenticated');
      await client.query(
        `select set_config('request.jwt.claims', $1, true), set_config('request.jwt.claim.sub', $2, true)`,
        [JSON.stringify({ ...ctx.claims, sub: ctx.userId, role: 'authenticated' }), ctx.userId],
      );
      return fn(client);
    });
  }

  /**
   * Privileged context (bypasses RLS). Only for server-owned writes such as
   * audit logs, token storage and worker jobs. Callers must scope by store_id.
   */
  async asService<T>(fn: (db: Queryable) => Promise<T>): Promise<T> {
    return this.tx(async (client) => {
      await client.query('set local role service_role');
      return fn(client);
    });
  }

  async ping(): Promise<boolean> {
    const r = await this.pool.query('select 1 as ok');
    return r.rows[0]?.ok === 1;
  }

  private async tx<T>(fn: (client: pg.PoolClient) => Promise<T>): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query('begin');
      const result = await fn(client);
      await client.query('commit');
      return result;
    } catch (err) {
      await client.query('rollback').catch(() => undefined);
      throw err;
    } finally {
      client.release();
    }
  }

  async onModuleDestroy() {
    await this.pool.end();
  }
}
