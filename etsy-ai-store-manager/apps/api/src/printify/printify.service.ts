import {
  BadRequestException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
  UnauthorizedException,
} from '@nestjs/common';
import {
  centsToDecimal,
  PRINTIFY_WEBHOOK_TOPICS,
  PrintifyClient,
  verifyPrintifySignature,
} from '@esm/integrations';
import { JOBS, QUEUES } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

export interface ProviderComparison {
  printProviderId: number;
  title: string;
  location: string | null;
  productionTime: string | null;
  variantCount: number;
  shipping: {
    country: string;
    firstItem: string | null;
    additionalItem: string | null;
    currency: string | null;
    handlingDays: number | null;
  } | null;
}

@Injectable()
export class PrintifyService {
  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  private client(storeId: string | null): PrintifyClient {
    if (!this.env.PRINTIFY_API_TOKEN) {
      throw new ServiceUnavailableException({
        message:
          'Printify entegrasyonu yapılandırılmadı. Sunucu .env dosyasına PRINTIFY_API_TOKEN ekleyin.',
        details: { missing: ['PRINTIFY_API_TOKEN'] },
      });
    }
    return new PrintifyClient({
      token: this.env.PRINTIFY_API_TOKEN,
      baseUrl: this.env.PRINTIFY_API_BASE_URL,
      maxRetries: 2,
      onCall: (log) => {
        void this.db
          .asService((db) =>
            db.query(
              `insert into public.api_logs (store_id, provider, method, endpoint, status_code, duration_ms, error)
               values ($1,'printify',$2,$3,$4,$5,$6)`,
              [storeId, log.method, log.endpoint, log.status, log.durationMs, log.error ?? null],
            ),
          )
          .catch(() => undefined);
      },
    });
  }

  /** Catalog responses are cached (catalog has its own 100 req/min limit). */
  private async cached<T>(key: string, ttlHours: number, load: () => Promise<T>): Promise<T> {
    const hit = await this.db.asService((db) =>
      db.query(
        `select payload from public.printify_catalog_cache where cache_key = $1 and expires_at > now()`,
        [key],
      ),
    );
    if (hit.rowCount) return hit.rows[0].payload as T;
    const value = await load();
    await this.db.asService((db) =>
      db.query(
        `insert into public.printify_catalog_cache (cache_key, payload, fetched_at, expires_at)
         values ($1, $2, now(), now() + make_interval(hours => $3))
         on conflict (cache_key) do update set payload = excluded.payload, fetched_at = now(), expires_at = excluded.expires_at`,
        [key, JSON.stringify(value), ttlHours],
      ),
    );
    return value;
  }

  async status(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select status, external_account_id, display_name, last_synced_at, last_error, metadata
           from public.connected_accounts where store_id = $1 and platform = 'printify'
          order by updated_at desc limit 1`,
        [storeId],
      );
      const counts = await db.query(
        `select (select count(*)::int from public.products where store_id = $1 and printify_product_id is not null) as products,
                (select count(*)::int from public.orders where store_id = $1 and printify_order_id is not null) as orders,
                (select count(*)::int from public.orders where store_id = $1 and printify_status in
                   ('has-issues','unfulfillable','payment-not-received','source-check-failed')) as problem_orders`,
        [storeId],
      );
      const a = r.rows[0] ?? {};
      return {
        configured: Boolean(this.env.PRINTIFY_API_TOKEN),
        webhooksConfigured: Boolean(this.env.PRINTIFY_WEBHOOK_SECRET),
        status: a.status ?? 'not_connected',
        shopId: a.external_account_id ?? null,
        shopTitle: a.display_name ?? null,
        salesChannel: a.metadata?.sales_channel ?? null,
        lastSyncedAt: a.last_synced_at ?? null,
        lastError: a.last_error ?? null,
        lineCostBasis: a.metadata?.line_cost_basis ?? 'unverified',
        counts: counts.rows[0],
      };
    });
  }

  async listShops(ctx: AuthContext, storeId: string) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'owner'));
    const shops = await this.client(storeId).getShops();
    return shops.map((s) => ({ id: s.id, title: s.title, salesChannel: s.sales_channel }));
  }

  async connect(ctx: AuthContext, storeId: string, shopId: number, meta: RequestMeta) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'owner'));
    const client = this.client(storeId);
    const shop = (await client.getShops()).find((s) => s.id === shopId);
    if (!shop) throw new NotFoundException('Bu Printify hesabında böyle bir mağaza yok');

    const webhooks: Array<{ id: string; topic: string }> = [];
    let webhookNote =
      'Webhook kaydı yapılmadı (PRINTIFY_WEBHOOK_SECRET ve https API_PUBLIC_URL gerekir); periyodik senkronizasyon kullanılır.';

    const accountId = await this.db.asService(async (db) => {
      const r = await db.query(
        `insert into public.connected_accounts (store_id, connected_by, platform, external_account_id, display_name, status, metadata, last_error)
         values ($1, $2, 'printify', $3, $4, 'active', $5, null)
         on conflict (store_id, platform, external_account_id) do update
           set status = 'active', display_name = excluded.display_name, last_error = null,
               metadata = public.connected_accounts.metadata || excluded.metadata
         returning id`,
        [
          storeId,
          ctx.userId,
          String(shop.id),
          shop.title,
          JSON.stringify({ sales_channel: shop.sales_channel }),
        ],
      );
      // only one active Printify shop per store
      await db.query(
        `update public.connected_accounts set status = 'revoked'
          where store_id = $1 and platform = 'printify' and id <> $2`,
        [storeId, r.rows[0].id],
      );
      return r.rows[0].id as string;
    });

    if (this.env.PRINTIFY_WEBHOOK_SECRET && this.env.API_PUBLIC_URL.startsWith('https://')) {
      const url = `${this.env.API_PUBLIC_URL.replace(/\/+$/, '')}/api/v1/integrations/printify/webhooks/${storeId}`;
      for (const topic of PRINTIFY_WEBHOOK_TOPICS) {
        try {
          const w = await createWebhook(this.env, shop.id, topic, url);
          webhooks.push({ id: w.id, topic });
        } catch {
          /* a failed webhook registration is not fatal: periodic sync still runs */
        }
      }
      webhookNote = `${webhooks.length}/${PRINTIFY_WEBHOOK_TOPICS.length} webhook kaydedildi`;
      await this.db.asService((db) =>
        db.query(`update public.connected_accounts set metadata = metadata || $2 where id = $1`, [
          accountId,
          JSON.stringify({ webhooks }),
        ]),
      );
    }

    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'printify.connect',
      entityType: 'connected_account',
      entityId: accountId,
      after: {
        shopId: shop.id,
        title: shop.title,
        salesChannel: shop.sales_channel,
        webhooks: webhooks.length,
      },
      meta,
    });
    await this.queue.enqueue(QUEUES.sync, JOBS.printifySyncStore, {
      idempotencyKey: `printify-sync:${storeId}:initial:${Date.now()}`,
      storeId,
      payload: { reason: 'initial' },
    });
    return {
      ok: true,
      shop: { id: shop.id, title: shop.title, salesChannel: shop.sales_channel },
      warning:
        shop.sales_channel !== 'etsy'
          ? 'Bu Printify mağazası Etsy’ye bağlı görünmüyor; yayınlama Etsy’ye gitmez.'
          : null,
      webhookNote,
    };
  }

  async requestSync(ctx: AuthContext, storeId: string) {
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select 1 from public.connected_accounts where store_id = $1 and platform = 'printify' and status = 'active'`,
        [storeId],
      );
      if (!r.rowCount) throw new BadRequestException('Printify bağlantısı aktif değil');
    });
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.printifySyncStore, {
      idempotencyKey: `printify-sync:${storeId}:manual:${Math.floor(Date.now() / 60_000)}`,
      storeId,
      payload: { reason: 'manual' },
    });
    return { jobId };
  }

  async disconnect(ctx: AuthContext, storeId: string, meta: RequestMeta) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'owner'));
    await this.db.asService((db) =>
      db.query(
        `update public.connected_accounts set status = 'revoked' where store_id = $1 and platform = 'printify'`,
        [storeId],
      ),
    );
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'printify.disconnect',
      entityType: 'store',
      entityId: storeId,
      meta,
    });
    return { ok: true };
  }

  async searchBlueprints(ctx: AuthContext, storeId: string, q: string) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'viewer'));
    const all = await this.cached('blueprints', 24, () => this.client(storeId).getBlueprints());
    const needle = q.trim().toLowerCase();
    return all
      .filter((b) => !needle || `${b.title} ${b.brand} ${b.model}`.toLowerCase().includes(needle))
      .slice(0, 50)
      .map((b) => ({
        id: b.id,
        title: b.title,
        brand: b.brand,
        model: b.model,
        image: b.images?.[0] ?? null,
      }));
  }

  /**
   * Provider comparison for one blueprint: shipping cost for the destination,
   * handling/production time and variant coverage. NOTE: Printify's catalog does not
   * expose production (base) cost; it appears only on created products (variants[].cost).
   */
  async compareProviders(ctx: AuthContext, storeId: string, blueprintId: number, country: string) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'viewer'));
    const client = this.client(storeId);
    const providers = await this.cached(`providers:${blueprintId}`, 24, () =>
      client.getBlueprintProviders(blueprintId),
    );
    const out: ProviderComparison[] = [];
    for (const p of providers.slice(0, 12)) {
      const [variants, shipping, detail] = await Promise.all([
        this.cached(`variants:${blueprintId}:${p.id}`, 24, () =>
          client.getVariants(blueprintId, p.id),
        ).catch(() => null),
        this.cached(`shipping:${blueprintId}:${p.id}`, 24, () =>
          client.getShipping(blueprintId, p.id),
        ).catch(() => null),
        this.cached(`provider:${p.id}`, 168, () => client.getPrintProvider(p.id)).catch(() => null),
      ]);
      const profile =
        shipping?.profiles.find((x) => x.countries.includes(country)) ??
        shipping?.profiles.find((x) => x.countries.includes('REST_OF_THE_WORLD'));
      out.push({
        printProviderId: p.id,
        title: p.title,
        location: detail?.location?.country ?? null,
        productionTime: p.production_time
          ? `${p.production_time.average} ${p.production_time.unit}`
          : null,
        variantCount: variants?.variants.length ?? 0,
        shipping: profile
          ? {
              country: profile.countries.includes(country) ? country : 'REST_OF_THE_WORLD',
              firstItem: centsToDecimal(profile.first_item.cost),
              additionalItem: centsToDecimal(profile.additional_items.cost),
              currency: profile.first_item.currency,
              handlingDays: shipping?.handling_time?.value ?? null,
            }
          : null,
      });
    }
    out.sort((a, b) => Number(a.shipping?.firstItem ?? 1e9) - Number(b.shipping?.firstItem ?? 1e9));
    return {
      blueprintId,
      country,
      providers: out,
      note: 'Üretim maliyeti katalogda yok; ürün taslağı oluşturulunca Printify varyant maliyeti olarak gelir.',
    };
  }

  /** Public webhook endpoint: verify signature over raw bytes, store once, enqueue processing. */
  async receiveWebhook(
    storeId: string,
    rawBody: Buffer | undefined,
    signature: string | undefined,
  ) {
    if (!this.env.PRINTIFY_WEBHOOK_SECRET)
      throw new ServiceUnavailableException('Webhook doğrulaması yapılandırılmadı');
    if (
      !rawBody ||
      !verifyPrintifySignature(rawBody, signature, this.env.PRINTIFY_WEBHOOK_SECRET)
    ) {
      throw new UnauthorizedException('Geçersiz imza');
    }
    let event: { id?: string; type?: string; resource?: unknown };
    try {
      event = JSON.parse(rawBody.toString('utf8'));
    } catch {
      throw new BadRequestException('Geçersiz JSON');
    }
    if (!event.id || !event.type) throw new BadRequestException('Eksik olay alanları');
    const row = await this.db.asService(async (db: Queryable) => {
      const s = await db.query(
        `select 1 from public.connected_accounts where store_id = $1 and platform = 'printify' and status = 'active'`,
        [storeId],
      );
      if (!s.rowCount) return null;
      const r = await db.query(
        `insert into public.webhook_events (provider, event_id, store_id, topic, payload)
         values ('printify', $1, $2, $3, $4) on conflict (provider, event_id) do nothing returning id`,
        [String(event.id), storeId, String(event.type), JSON.stringify(event)],
      );
      return r.rows[0] ?? { duplicate: true };
    });
    if (!row) return { ok: true, ignored: 'store not connected' };
    if ('duplicate' in row) return { ok: true, duplicate: true };
    await this.queue.enqueue(QUEUES.sync, JOBS.printifyWebhook, {
      idempotencyKey: `printify-webhook:${row.id}`,
      storeId,
      payload: { webhookEventId: row.id },
    });
    return { ok: true };
  }
}

async function createWebhook(
  env: Env,
  shopId: number,
  topic: string,
  url: string,
): Promise<{ id: string }> {
  const base = (env.PRINTIFY_API_BASE_URL ?? 'https://api.printify.com').replace(/\/+$/, '');
  const res = await fetch(`${base}/v1/shops/${shopId}/webhooks.json`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.PRINTIFY_API_TOKEN}`,
      'User-Agent': 'EtsyAIStoreManager/0.1 (Node.js)',
      'Content-Type': 'application/json;charset=utf-8',
    },
    body: JSON.stringify({ topic, url, secret: env.PRINTIFY_WEBHOOK_SECRET }),
  });
  if (!res.ok) throw new Error(`webhook ${topic}: ${res.status}`);
  return (await res.json()) as { id: string };
}
