import type pg from 'pg';
import { refreshAccessToken, type EtsyAppConfig, type TokenCipher } from '@esm/integrations';

/** Refresh when the access token (1h lifetime) expires within this margin. */
export const REFRESH_MARGIN_MS = 5 * 60_000;

/**
 * Returns a valid "<user_id>.<token>" access token for a connected account,
 * refreshing it first if needed. The row lock (FOR UPDATE) makes concurrent jobs
 * wait for a single refresh instead of each rotating the refresh token.
 */
export async function getEtsyAccessToken(
  pool: pg.Pool,
  deps: { cipher: TokenCipher; app: EtsyAppConfig; fetchImpl: typeof fetch },
  accountId: string,
  opts: { force?: boolean } = {},
): Promise<string> {
  const aad = `connected_account:${accountId}`;
  const client = await pool.connect();
  try {
    await client.query('begin');
    const r = await client.query(
      `select access_token_ciphertext, refresh_token_ciphertext, expires_at
         from public.oauth_tokens where connected_account_id = $1 for update`,
      [accountId],
    );
    const row = r.rows[0];
    if (!row) throw new Error('Etsy token bulunamadı (bağlantı yeniden kurulmalı)');
    const expiresAt = row.expires_at ? new Date(row.expires_at).getTime() : 0;
    if (!opts.force && expiresAt - Date.now() > REFRESH_MARGIN_MS) {
      await client.query('commit');
      return deps.cipher.decrypt(row.access_token_ciphertext, aad);
    }
    if (!row.refresh_token_ciphertext) throw new Error('Refresh token yok');
    let tokens;
    try {
      tokens = await refreshAccessToken(
        deps.app,
        deps.cipher.decrypt(row.refresh_token_ciphertext, aad),
        deps.fetchImpl,
      );
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 400 || status === 401) {
        // refresh token revoked/expired -> user must reconnect
        await client.query(
          `update public.connected_accounts set status = 'expired', last_error = $2 where id = $1`,
          [accountId, 'Etsy oturumu yenilenemedi; mağazayı yeniden bağlayın'],
        );
        await client.query('commit');
      } else {
        await client.query('rollback');
      }
      throw err;
    }
    await client.query(
      `update public.oauth_tokens
          set access_token_ciphertext = $2, refresh_token_ciphertext = $3, expires_at = $4,
              refresh_expires_at = now() + interval '90 days', key_version = $5, last_refreshed_at = now()
        where connected_account_id = $1`,
      [
        accountId,
        deps.cipher.encrypt(tokens.accessToken, aad),
        deps.cipher.encrypt(tokens.refreshToken, aad),
        tokens.expiresAt,
        deps.cipher.keyVersion,
      ],
    );
    await client.query('commit');
    return tokens.accessToken;
  } catch (err) {
    await client.query('rollback').catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }
}
