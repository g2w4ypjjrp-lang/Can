// Uçtan uca testler için bulut API'si: boş bir veritabanı oluşturur, geçişleri uygular ve
// gerçek API sunucusunu (ati-cloud-api) başlatır. Playwright bu betiği webServer olarak çalıştırır.
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import pg from "pg";

import { API_PORT, E2E_DB, LICENSE_ENV, WEB_ORIGIN, adminDsn, e2eDsn } from "./env.mjs";

const cloudDir = fileURLToPath(new URL("../../cloud", import.meta.url));

const admin = new pg.Client({ connectionString: adminDsn });
await admin.connect();
await admin.query(`DROP DATABASE IF EXISTS ${E2E_DB} WITH (FORCE)`);
await admin.query(`CREATE DATABASE ${E2E_DB}`);
await admin.end();

const env = {
  ...process.env,
  ATI_DATABASE_URL: e2eDsn,
  ATI_ENVIRONMENT: "test",
  ATI_SESSION_COOKIE_SECURE: "false",
  ATI_WEB_ORIGINS: JSON.stringify([WEB_ORIGIN]),
  ATI_PUBLIC_WEB_URL: WEB_ORIGIN,
  ATI_ADMIN_ORIGINS: JSON.stringify([WEB_ORIGIN]),
  ATI_ADMIN_PUBLIC_URL: WEB_ORIGIN,
  ...LICENSE_ENV,
};
const migrate = spawnSync("uv", ["run", "--project", cloudDir, "ati-cloud-migrate"], { env, stdio: "inherit" });
if (migrate.status !== 0) process.exit(migrate.status ?? 1);

const api = spawn("uv", ["run", "--project", cloudDir, "ati-cloud-api", "--port", String(API_PORT)], {
  env,
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => api.kill(signal));
api.on("exit", (code) => process.exit(code ?? 0));
