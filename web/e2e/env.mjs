// Uçtan uca test ortamı: ayrı portlar ve ayrı bir veritabanı (ati_e2e).
export const API_PORT = 8100;
export const WEB_PORT = 3100;
export const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
export const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;
export const E2E_DB = "ati_e2e";
export const adminDsn =
  process.env.ATI_TEST_DATABASE_URL ?? "postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test";

const url = new URL(adminDsn);
url.pathname = `/${E2E_DB}`;
export const e2eDsn = url.toString();

// Yalnızca uçtan uca testler için sabit lisans gizli değerleri (üretimde gizli bilgi deposundan gelir).
const b64 = (seed) => Buffer.alloc(32, seed).toString("base64");
export const LICENSE_ENV = {
  ATI_LICENSE_PEPPER: b64(1),
  ATI_LICENSE_KEK: b64(2),
  ATI_LEASE_SIGNING_KEY: b64(3),
};
