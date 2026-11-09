// Testlerin veritabanına doğrudan erişimi: e-posta kutusundaki bağlantıları okumak ve
// satış/lisans gibi henüz arayüzü olmayan durumları hazırlamak için (yalnızca test).
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

import pg from "pg";

import { LICENSE_ENV, e2eDsn } from "./env.mjs";

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

/**
 * Müşteriye satılmış lisans (bulutun kendi lisans servisiyle: gerçek anahtar, şifreli saklama)
 * ve bir bilgisayarda etkinleştirilmiş durumu. Anahtarı döner.
 */
export async function grantLicense(email: string): Promise<string> {
  const cloud = fileURLToPath(new URL("../../cloud", import.meta.url));
  const result = spawnSync(
    "uv",
    ["run", "--project", cloud, "python", "scripts/e2e_license_fixture.py", "issue", email, "d30_1dev"],
    { cwd: cloud, encoding: "utf8", env: { ...process.env, ATI_ENVIRONMENT: "test", ATI_DATABASE_URL: e2eDsn, ...LICENSE_ENV } },
  );
  if (result.status !== 0) throw new Error(result.stderr);
  const issued = JSON.parse(result.stdout.trim().split("\n").pop() ?? "{}") as { license_id: string; key: string };
  const [customer] = await sql<{ id: string }>("SELECT id FROM customers WHERE email = $1", [email]);
  const [device] = await sql<{ id: string }>(
    "INSERT INTO devices (customer_id, platform, fingerprint_hash, display_name) VALUES ($1, 'windows', $2, 'Ofis PC') RETURNING id",
    [customer!.id, randomBytes(32)],
  );
  await sql("INSERT INTO license_activations (license_id, device_id) VALUES ($1, $2)", [issued.license_id, device!.id]);
  return issued.key;
}
