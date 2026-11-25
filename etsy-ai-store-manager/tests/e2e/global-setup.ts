// Test-only: releases the Etsy STUB shop (55001) from stores created by earlier
// E2E runs, because one Etsy shop may be linked to only one store record.
import pg from 'pg';

export default async function globalSetup() {
  const url =
    process.env.E2E_DATABASE_URL ?? 'postgresql://postgres:postgres@127.0.0.1:54322/postgres';
  if (!/127\.0\.0\.1|localhost/.test(url))
    throw new Error('E2E cleanup only runs against a local database');
  const client = new pg.Client({ connectionString: url });
  await client.connect();
  try {
    await client.query(
      `update public.stores set external_shop_id = null, status = 'disconnected'
        where platform = 'etsy' and external_shop_id = '55001' and name like 'E2E%'`,
    );
  } finally {
    await client.end();
  }
}
