import type pg from 'pg';
import { EtsyClient, TokenCipher, type EtsyAppConfig, type EtsyCallLog } from '@esm/integrations';
import type { WorkerEnv } from '../env.js';
import { getEtsyAccessToken } from './token-provider.js';
import type { PrintifyDeps } from '../printify/sync.js';

export interface IntegrationDeps {
  cipher: TokenCipher | null;
  etsy: EtsyAppConfig | null;
  fetchImpl: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  printify?: PrintifyDeps | null;
}

export function integrationDepsFromEnv(
  env: WorkerEnv,
  fetchImpl: typeof fetch = fetch,
): IntegrationDeps {
  const cipher = env.TOKEN_ENCRYPTION_KEY
    ? TokenCipher.fromEnv({
        TOKEN_ENCRYPTION_KEY: env.TOKEN_ENCRYPTION_KEY,
        TOKEN_ENCRYPTION_KEY_VERSION: env.TOKEN_ENCRYPTION_KEY_VERSION,
        TOKEN_ENCRYPTION_PREVIOUS_KEYS: env.TOKEN_ENCRYPTION_PREVIOUS_KEYS,
      })
    : null;
  const etsy =
    env.ETSY_KEYSTRING && env.ETSY_SHARED_SECRET
      ? {
          keystring: env.ETSY_KEYSTRING,
          sharedSecret: env.ETSY_SHARED_SECRET,
          redirectUri: env.ETSY_REDIRECT_URI,
          tokenUrl: env.ETSY_TOKEN_URL,
          apiBaseUrl: env.ETSY_API_BASE_URL,
        }
      : null;
  const printify: PrintifyDeps | null = env.PRINTIFY_API_TOKEN
    ? { token: env.PRINTIFY_API_TOKEN, baseUrl: env.PRINTIFY_API_BASE_URL, fetchImpl }
    : null;
  return { cipher, etsy, fetchImpl, printify };
}

export class IntegrationNotConfiguredError extends Error {}

export interface EtsyConnection {
  accountId: string;
  storeId: string;
  shopId: string;
  metadata: Record<string, unknown>;
}

export async function loadEtsyConnection(
  pool: pg.Pool,
  storeId: string,
): Promise<EtsyConnection | null> {
  const r = await pool.query(
    `select id, store_id, external_account_id, metadata from public.connected_accounts
      where store_id = $1 and platform = 'etsy' and status = 'active'
      order by updated_at desc limit 1`,
    [storeId],
  );
  const row = r.rows[0];
  return row
    ? {
        accountId: row.id,
        storeId: row.store_id,
        shopId: row.external_account_id,
        metadata: row.metadata ?? {},
      }
    : null;
}

/** Etsy client for a connection; every call is written to api_logs (no bodies, no tokens). */
export function etsyClientFor(
  pool: pg.Pool,
  deps: IntegrationDeps,
  conn: EtsyConnection,
): EtsyClient {
  if (!deps.etsy || !deps.cipher) {
    throw new IntegrationNotConfiguredError(
      'Etsy anahtarları veya TOKEN_ENCRYPTION_KEY worker ortamında tanımlı değil',
    );
  }
  const app = deps.etsy;
  const cipher = deps.cipher;
  return new EtsyClient({
    app,
    fetchImpl: deps.fetchImpl,
    sleep: deps.sleep,
    getAccessToken: () =>
      getEtsyAccessToken(pool, { cipher, app, fetchImpl: deps.fetchImpl }, conn.accountId),
    onCall: (log: EtsyCallLog) => {
      void pool
        .query(
          `insert into public.api_logs (store_id, provider, method, endpoint, status_code, duration_ms, error, rate_limit_remaining)
           values ($1, 'etsy', $2, $3, $4, $5, $6, $7)`,
          [
            conn.storeId,
            log.method,
            log.endpoint,
            log.status,
            log.durationMs,
            log.error ?? null,
            log.rateLimitRemaining ?? null,
          ],
        )
        .catch(() => undefined);
    },
  });
}
