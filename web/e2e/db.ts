// Testlerin veritabanına doğrudan erişimi: e-posta kutusundaki bağlantıları okumak ve
// satış/lisans gibi henüz arayüzü olmayan durumları hazırlamak için (yalnızca test).
import { randomBytes } from "node:crypto";

import pg from "pg";

import { e2eDsn } from "./env.mjs";

export async function sql<T extends pg.QueryResultRow = pg.QueryResultRow>(text: string, params: unknown[] = []): Promise<T[]> {
  const client = new pg.Client({ connectionString: e2eDsn });
  await client.connect();
  try {
    return (await client.query<T>(text, params)).rows;
  } finally {
    await client.end();
  }
}

/** E-posta kutusundaki son bağlantı (doğrulama, parola sıfırlama). */
export async function latestLink(email: string, template: string): Promise<string> {
  const rows = await sql<{ link: string }>(
    "SELECT payload->>'link' AS link FROM email_outbox WHERE to_email = $1 AND template = $2 ORDER BY created_at DESC LIMIT 1",
    [email, template],
  );
  const link = rows[0]?.link;
  if (!link) throw new Error(`${email} için ${template} e-postası yok`);
  return link;
}

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${randomBytes(4).toString("hex")}@example.com`;
}

/** Müşteriye satılmış ve bir cihazda etkinleştirilmiş 30 günlük lisans (Aşama 15/17 öncesi test verisi). */
export async function grantLicense(email: string): Promise<void> {
  const [customer] = await sql<{ id: string }>("SELECT id FROM customers WHERE email = $1", [email]);
  if (!customer) throw new Error("müşteri yok");
  const [license] = await sql<{ id: string }>(
    `INSERT INTO licenses (key_hash, key_ciphertext, key_hint, plan_code, status, duration_days, device_limit, companion_device_limit)
     SELECT $1, $2, 'ATI-****-****-****-E2E1', code, 'ready_for_sale', duration_days, device_limit, companion_device_limit
     FROM license_plans WHERE code = 'd30_1dev' RETURNING id`,
    [randomBytes(32), randomBytes(60)],
  );
  const [order] = await sql<{ id: string }>(
    "INSERT INTO orders (customer_id, currency, subtotal_minor, total_minor, payment_provider) VALUES ($1, 'USD', 1000, 1000, 'test') RETURNING id",
    [customer.id],
  );
  const [item] = await sql<{ id: string }>(
    "INSERT INTO order_items (order_id, plan_code, quantity, unit_price_minor, line_total_minor) VALUES ($1, 'd30_1dev', 1, 1000, 1000) RETURNING id",
    [order!.id],
  );
  await sql(
    "UPDATE licenses SET status = 'sold', customer_id = $1, order_item_id = $2, order_item_unit = 1, sold_at = now() WHERE id = $3",
    [customer.id, item!.id, license!.id],
  );
  const [device] = await sql<{ id: string }>(
    "INSERT INTO devices (customer_id, platform, fingerprint_hash, display_name) VALUES ($1, 'windows', $2, 'Ofis PC') RETURNING id",
    [customer.id, randomBytes(32)],
  );
  await sql("INSERT INTO license_activations (license_id, device_id) VALUES ($1, $2)", [license!.id, device!.id]);
}
