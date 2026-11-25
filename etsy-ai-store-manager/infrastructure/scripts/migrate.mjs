#!/usr/bin/env node
// Applies packages/database/supabase/migrations/*.sql in order, tracking applied
// files in private.schema_migrations (sha256 checked to detect edited history).
//
// Usage:
//   DATABASE_URL=postgres://... node infrastructure/scripts/migrate.mjs [--reset] [--with-shim]
//
// --with-shim  : install the Supabase emulation (auth schema, roles) for plain Postgres (tests/CI only)
// --reset      : DROP public/private/auth schemas first (refuses when NODE_ENV=production)
//
// In a real Supabase project prefer: supabase db push --workdir packages/database
import { readdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import pg from 'pg';

const here = path.dirname(fileURLToPath(import.meta.url));
const dbDir = path.resolve(here, '../../packages/database');
const migrationsDir = path.join(dbDir, 'supabase/migrations');

export async function migrate({
  connectionString,
  reset = false,
  withShim = false,
  log = console.log,
}) {
  if (!connectionString) throw new Error('DATABASE_URL is required');
  if (reset && process.env.NODE_ENV === 'production') {
    throw new Error('--reset is not allowed in production');
  }
  const client = new pg.Client({ connectionString });
  await client.connect();
  try {
    if (reset) {
      log('Resetting schemas public, private, auth ...');
      await client.query(`drop schema if exists public cascade; drop schema if exists private cascade;
        drop schema if exists auth cascade; create schema public; grant usage on schema public to public;`);
    }
    if (withShim) {
      await client.query(await readFile(path.join(dbDir, 'test/supabase-shim.sql'), 'utf8'));
      log('Supabase shim installed');
    }
    await client.query(`create schema if not exists private;
      create table if not exists private.schema_migrations (
        filename text primary key, sha256 text not null, applied_at timestamptz not null default now())`);
    const applied = new Map(
      (await client.query('select filename, sha256 from private.schema_migrations')).rows.map(
        (r) => [r.filename, r.sha256],
      ),
    );
    const files = (await readdir(migrationsDir)).filter((f) => f.endsWith('.sql')).sort();
    let count = 0;
    for (const file of files) {
      const sql = await readFile(path.join(migrationsDir, file), 'utf8');
      const sha = createHash('sha256').update(sql).digest('hex');
      if (applied.has(file)) {
        if (applied.get(file) !== sha) {
          throw new Error(
            `Migration ${file} was modified after being applied. Create a new migration instead.`,
          );
        }
        continue;
      }
      await client.query('begin');
      try {
        await client.query(sql);
        await client.query(
          'insert into private.schema_migrations (filename, sha256) values ($1, $2)',
          [file, sha],
        );
        await client.query('commit');
        count++;
        log(`applied ${file}`);
      } catch (err) {
        await client.query('rollback');
        throw new Error(`Migration ${file} failed: ${err.message}`, { cause: err });
      }
    }
    log(`Done. ${count} new migration(s), ${files.length} total.`);
    return { applied: count, total: files.length };
  } finally {
    await client.end();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = new Set(process.argv.slice(2));
  migrate({
    connectionString: process.env.DATABASE_URL,
    reset: args.has('--reset'),
    withShim: args.has('--with-shim'),
  }).catch((err) => {
    console.error(err.message);
    process.exit(1);
  });
}
