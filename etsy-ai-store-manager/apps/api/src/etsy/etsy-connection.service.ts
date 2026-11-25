import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  Logger,
  ServiceUnavailableException,
} from '@nestjs/common';
import { createHash, randomUUID } from 'node:crypto';
import {
  buildAuthorizeUrl,
  createOAuthState,
  createPkcePair,
  ETSY_SCOPES,
  ETSY_UNSUPPORTED_OPERATIONS,
  EtsyClient,
  exchangeAuthorizationCode,
  type EtsyAppConfig,
} from '@esm/integrations';
import { JOBS, QUEUES, type EtsyConnectionDto } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext } from '../database/database.service.js';
import { TokenCryptoService } from '../security/token-crypto.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

const STATE_TTL_MS = 10 * 60_000;

@Injectable()
export class EtsyConnectionService {
  private readonly logger = new Logger(EtsyConnectionService.name);

  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly crypto: TokenCryptoService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  missingConfig(): string[] {
    const missing: string[] = [];
    if (!this.env.ETSY_KEYSTRING) missing.push('ETSY_KEYSTRING');
    if (!this.env.ETSY_SHARED_SECRET) missing.push('ETSY_SHARED_SECRET');
    if (!this.env.ETSY_REDIRECT_URI) missing.push('ETSY_REDIRECT_URI');
    return missing;
  }

  appConfig(): EtsyAppConfig {
    const missing = this.missingConfig();
    if (missing.length) {
      throw new ServiceUnavailableException({
        message: `Etsy entegrasyonu yapılandırılmadı. Sunucu .env dosyasına ekleyin: ${missing.join(', ')}`,
        details: { missing },
      });
    }
    return {
      keystring: this.env.ETSY_KEYSTRING,
      sharedSecret: this.env.ETSY_SHARED_SECRET,
      redirectUri: this.env.ETSY_REDIRECT_URI,
      connectUrl: this.env.ETSY_CONNECT_URL,
      tokenUrl: this.env.ETSY_TOKEN_URL,
      apiBaseUrl: this.env.ETSY_API_BASE_URL,
    };
  }

  async status(ctx: AuthContext, storeId: string): Promise<EtsyConnectionDto> {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select ca.status, ca.external_account_id, ca.display_name, ca.scopes, ca.last_synced_at,
                ca.last_error, s.shop_url
           from public.stores s
           left join public.connected_accounts ca on ca.store_id = s.id and ca.platform = 'etsy'
          where s.id = $1
          order by ca.updated_at desc nulls last limit 1`,
        [storeId],
      );
      const counts = await db.query(
        `select (select count(*)::int from public.listings where store_id = $1 and etsy_listing_id is not null) as listings,
                (select count(*)::int from public.orders where store_id = $1 and etsy_receipt_id is not null) as orders`,
        [storeId],
      );
      const a = r.rows[0] ?? {};
      // token expiry is not visible to clients (oauth_tokens has no client access)
      const expiry = a.external_account_id
        ? await this.db.asService((s) =>
            s.query(
              `select t.expires_at from public.oauth_tokens t
                 join public.connected_accounts ca on ca.id = t.connected_account_id
                where ca.store_id = $1 and ca.platform = 'etsy'`,
              [storeId],
            ),
          )
        : null;
      return {
        configured: this.missingConfig().length === 0,
        missingConfig: this.missingConfig(),
        status: a.status ?? 'not_connected',
        shopId: a.external_account_id ?? null,
        shopName: a.display_name ?? null,
        shopUrl: a.shop_url ?? null,
        scopes: a.scopes ?? [],
        lastSyncedAt: a.last_synced_at ?? null,
        lastError: a.last_error ?? null,
        tokenExpiresAt: expiry?.rows[0]?.expires_at ?? null,
        counts: counts.rows[0],
        unsupportedOperations: { ...ETSY_UNSUPPORTED_OPERATIONS },
      };
    });
  }

  /** Step 1: create single-use state + PKCE verifier and return Etsy's consent URL. */
  async startConnect(
    ctx: AuthContext,
    storeId: string,
    meta: RequestMeta,
  ): Promise<{ authorizeUrl: string }> {
    const cfg = this.appConfig();
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'owner'));
    const state = createOAuthState();
    const pkce = createPkcePair();
    const id = randomUUID();
    await this.db.asService(async (db) => {
      await db.query(`delete from public.oauth_states where expires_at < now() - interval '1 day'`);
      await db.query(
        `insert into public.oauth_states (id, state_hash, platform, store_id, user_id, code_verifier_ciphertext, expires_at)
         values ($1, $2, 'etsy', $3, $4, $5, $6)`,
        [
          id,
          sha256(state),
          storeId,
          ctx.userId,
          this.crypto.encrypt(pkce.verifier, `oauth_state:${id}`),
          new Date(Date.now() + STATE_TTL_MS),
        ],
      );
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'etsy.connect.start',
      entityType: 'store',
      entityId: storeId,
      after: { scopes: ETSY_SCOPES },
      meta,
    });
    return { authorizeUrl: buildAuthorizeUrl(cfg, { state, codeChallenge: pkce.challenge }) };
  }

  /**
   * Step 2 (public callback): validates state, exchanges the code, identifies the
   * shop with getMe/getShop and stores encrypted tokens. Returns the web URL to redirect to.
   */
  async handleCallback(
    q: { code?: string; state?: string; error?: string; error_description?: string },
    meta: RequestMeta,
  ): Promise<string> {
    const web = `${this.env.WEB_APP_URL.replace(/\/+$/, '')}/dashboard/etsy`;
    if (q.error) return `${web}?error=${encodeURIComponent(q.error_description ?? q.error)}`;
    if (!q.code || !q.state || q.state.length > 200 || q.code.length > 2000) {
      throw new BadRequestException('Eksik veya geçersiz OAuth parametresi');
    }
    const cfg = this.appConfig();

    const st = await this.db.asService(async (db) => {
      const r = await db.query(
        `update public.oauth_states set used_at = now()
          where state_hash = $1 and platform = 'etsy' and used_at is null and expires_at > now()
          returning id, store_id, user_id, code_verifier_ciphertext`,
        [sha256(q.state!)],
      );
      return r.rows[0] as
        | { id: string; store_id: string; user_id: string; code_verifier_ciphertext: string }
        | undefined;
    });
    if (!st)
      return `${web}?error=${encodeURIComponent('Bağlantı isteği geçersiz veya süresi dolmuş. Tekrar deneyin.')}`;

    try {
      const verifier = this.crypto.decrypt(st.code_verifier_ciphertext, `oauth_state:${st.id}`);
      const tokens = await exchangeAuthorizationCode(cfg, { code: q.code, codeVerifier: verifier });
      const client = new EtsyClient({ app: cfg, getAccessToken: async () => tokens.accessToken });
      const me = await client.getMe();
      const shop = await client.getShop(me.shop_id);
      const shopId = String(me.shop_id);

      const accountId = await this.db.asService(async (db) => {
        const clash = await db.query(
          `select id from public.stores where platform = 'etsy' and external_shop_id = $1 and id <> $2`,
          [shopId, st.store_id],
        );
        if (clash.rowCount)
          throw new ConflictException('Bu Etsy mağazası başka bir mağaza kaydına bağlı');
        await db.query(
          `update public.stores set external_shop_id = $2, shop_url = $3, status = 'connected', currency = $4
            where id = $1`,
          [st.store_id, shopId, shop.url, shop.currency_code],
        );
        const acc = await db.query(
          `insert into public.connected_accounts
             (store_id, connected_by, platform, external_account_id, display_name, scopes, status, last_error, metadata)
           values ($1, $2, 'etsy', $3, $4, $5, 'active', null, $6)
           on conflict (store_id, platform, external_account_id) do update
             set connected_by = excluded.connected_by, display_name = excluded.display_name,
                 scopes = excluded.scopes, status = 'active', last_error = null,
                 metadata = public.connected_accounts.metadata || excluded.metadata
           returning id`,
          [
            st.store_id,
            st.user_id,
            shopId,
            shop.shop_name,
            tokens.scopes.length ? tokens.scopes : [...ETSY_SCOPES],
            JSON.stringify({
              etsy_user_id: String(me.user_id),
              shop_name: shop.shop_name,
              currency: shop.currency_code,
            }),
          ],
        );
        const id: string = acc.rows[0].id;
        await db.query(
          `insert into public.oauth_tokens
             (connected_account_id, access_token_ciphertext, refresh_token_ciphertext, token_type, scopes,
              expires_at, refresh_expires_at, key_version, last_refreshed_at)
           values ($1, $2, $3, $4, $5, $6, now() + interval '90 days', $7, now())
           on conflict (connected_account_id) do update set
             access_token_ciphertext = excluded.access_token_ciphertext,
             refresh_token_ciphertext = excluded.refresh_token_ciphertext,
             token_type = excluded.token_type, scopes = excluded.scopes, expires_at = excluded.expires_at,
             refresh_expires_at = excluded.refresh_expires_at, key_version = excluded.key_version,
             last_refreshed_at = now()`,
          [
            id,
            this.crypto.encrypt(tokens.accessToken, `connected_account:${id}`),
            this.crypto.encrypt(tokens.refreshToken, `connected_account:${id}`),
            tokens.tokenType,
            tokens.scopes,
            tokens.expiresAt,
            this.crypto.keyVersion,
          ],
        );
        await db.query(
          `insert into public.notifications (user_id, store_id, type, severity, title, body, link)
           values ($1, $2, 'etsy.connected', 'success', 'Etsy mağazası bağlandı', $3, '/dashboard/etsy')`,
          [st.user_id, st.store_id, `${shop.shop_name} bağlandı. İlk içe aktarma başlatıldı.`],
        );
        return id;
      });

      await this.audit.record({
        storeId: st.store_id,
        actorUserId: st.user_id,
        actorType: 'user',
        action: 'etsy.connect.complete',
        entityType: 'connected_account',
        entityId: accountId,
        after: { shopId, shopName: shop.shop_name, scopes: tokens.scopes },
        meta,
      });
      await this.queue.enqueue(QUEUES.sync, JOBS.etsySyncStore, {
        idempotencyKey: `etsy-sync:${st.store_id}:initial:${accountId}:${Date.now()}`,
        storeId: st.store_id,
        payload: { reason: 'initial' },
      });
      return `${web}?connected=1`;
    } catch (err) {
      const message =
        err instanceof ConflictException ? err.message : 'Etsy bağlantısı tamamlanamadı';
      this.logger.warn(
        `Etsy callback failed for store ${st.store_id}: ${err instanceof Error ? err.message : String(err)}`,
      );
      await this.audit.record({
        storeId: st.store_id,
        actorUserId: st.user_id,
        actorType: 'user',
        action: 'etsy.connect.failed',
        entityType: 'store',
        entityId: st.store_id,
        after: { error: err instanceof Error ? err.message.slice(0, 300) : 'unknown' },
        meta,
      });
      return `${web}?error=${encodeURIComponent(message)}`;
    }
  }

  async requestSync(
    ctx: AuthContext,
    storeId: string,
    meta: RequestMeta,
  ): Promise<{ jobId: string }> {
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select 1 from public.connected_accounts where store_id = $1 and platform = 'etsy' and status = 'active'`,
        [storeId],
      );
      if (!r.rowCount) throw new BadRequestException('Etsy bağlantısı aktif değil');
    });
    // one manual sync per store per minute
    const bucket = Math.floor(Date.now() / 60_000);
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.etsySyncStore, {
      idempotencyKey: `etsy-sync:${storeId}:manual:${bucket}`,
      storeId,
      payload: { reason: 'manual', requestedBy: ctx.userId },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'etsy.sync.requested',
      entityType: 'store',
      entityId: storeId,
      meta,
    });
    return { jobId };
  }

  /**
   * Removes stored tokens locally. Imported data is kept. Etsy's API has no token
   * revocation endpoint in the reference, so the user is told to also remove the
   * app from their Etsy account settings.
   */
  async disconnect(
    ctx: AuthContext,
    storeId: string,
    meta: RequestMeta,
  ): Promise<{ ok: true; note: string }> {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'owner'));
    await this.db.asService(async (db) => {
      await db.query(
        `delete from public.oauth_tokens where connected_account_id in
           (select id from public.connected_accounts where store_id = $1 and platform = 'etsy')`,
        [storeId],
      );
      await db.query(
        `update public.connected_accounts set status = 'revoked' where store_id = $1 and platform = 'etsy'`,
        [storeId],
      );
      await db.query(`update public.stores set status = 'disconnected' where id = $1`, [storeId]);
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'etsy.disconnect',
      entityType: 'store',
      entityId: storeId,
      meta,
    });
    return {
      ok: true,
      note: 'Belirteçler silindi, içe aktarılan veriler korundu. Erişimi tamamen kaldırmak için Etsy hesap ayarlarınızdan bu uygulamanın erişimini de kaldırın.',
    };
  }
}

function sha256(v: string): string {
  return createHash('sha256').update(v).digest('hex');
}
