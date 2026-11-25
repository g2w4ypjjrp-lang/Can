import { ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { DatabaseService, type AuthContext } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

/** Products (Printify-backed) with variants and their CURRENT costs (valid_to is null). */
@Injectable()
export class ProductsService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
  ) {}

  list(
    ctx: AuthContext,
    storeId: string,
    q: { status?: string; search?: string; limit: number; offset: number },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const params: unknown[] = [storeId];
      let where = 'p.store_id = $1';
      if (q.status) {
        params.push(q.status);
        where += ` and p.status = $${params.length}`;
      }
      if (q.search) {
        params.push(`%${q.search.replace(/[%_\\]/g, (c) => `\\${c}`)}%`);
        where += ` and p.title ilike $${params.length}`;
      }
      const total = await db.query(
        `select count(*)::int n from public.products p where ${where}`,
        params,
      );
      params.push(q.limit, q.offset);
      const r = await db.query(
        `select p.id, p.title, p.product_type, p.status, p.printify_product_id, p.printify_blueprint_id,
                p.printify_print_provider_id, p.external_listing_id, p.printify_is_locked, p.printify_synced_at,
                p.data_origin,
                (select source_url from public.product_images i where i.product_id = p.id order by position limit 1) as image,
                (select count(*)::int from public.product_variants v where v.product_id = p.id and v.is_enabled) as enabled_variants,
                (select min(v.price)::text from public.product_variants v where v.product_id = p.id and v.is_enabled) as min_price,
                (select max(v.price)::text from public.product_variants v where v.product_id = p.id and v.is_enabled) as max_price,
                (select min(c.amount)::text from public.product_costs c join public.product_variants v on v.id = c.product_variant_id
                  where v.product_id = p.id and v.is_enabled and c.cost_type = 'production' and c.valid_to is null) as min_cost,
                (select max(c.amount)::text from public.product_costs c join public.product_variants v on v.id = c.product_variant_id
                  where v.product_id = p.id and v.is_enabled and c.cost_type = 'production' and c.valid_to is null) as max_cost,
                (select l.id from public.listings l where l.product_id = p.id limit 1) as listing_id
           from public.products p where ${where}
          order by p.updated_at desc limit $${params.length - 1} offset $${params.length}`,
        params,
      );
      return {
        total: total.rows[0].n,
        items: r.rows.map((x) => ({
          id: x.id,
          title: x.title,
          productType: x.product_type,
          status: x.status,
          printifyProductId: x.printify_product_id,
          blueprintId: x.printify_blueprint_id,
          printProviderId: x.printify_print_provider_id,
          etsyListingId: x.external_listing_id,
          listingId: x.listing_id,
          locked: x.printify_is_locked,
          syncedAt: x.printify_synced_at,
          image: x.image,
          enabledVariants: x.enabled_variants,
          priceRange: [x.min_price, x.max_price],
          productionCostRange: [x.min_cost, x.max_cost],
          dataOrigin: x.data_origin,
        })),
      };
    });
  }

  get(ctx: AuthContext, storeId: string, productId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const p = await db.query(`select * from public.products where store_id = $1 and id = $2`, [
        storeId,
        productId,
      ]);
      if (!p.rowCount) throw new NotFoundException('Ürün bulunamadı');
      const variants = await db.query(
        `select v.id, v.title, v.sku, v.price::text, v.currency, v.is_enabled, v.is_available, v.printify_variant_id,
                (select amount::text from public.product_costs c where c.product_variant_id = v.id and c.cost_type = 'production' and c.valid_to is null limit 1) as production_cost,
                (select json_agg(json_build_object('country', coalesce(c.destination_country, 'REST_OF_THE_WORLD'),
                         'type', c.cost_type, 'amount', c.amount::text, 'currency', c.currency) order by c.destination_country nulls last, c.cost_type)
                   from public.product_costs c where c.product_variant_id = v.id and c.cost_type like 'shipping%' and c.valid_to is null) as shipping
           from public.product_variants v where v.product_id = $1 order by v.title`,
        [productId],
      );
      const history = await db.query(
        `select v.title as variant, c.cost_type, c.amount::text, c.currency, c.destination_country, c.valid_from, c.valid_to
           from public.product_costs c join public.product_variants v on v.id = c.product_variant_id
          where v.product_id = $1 and c.valid_to is not null order by c.valid_to desc limit 50`,
        [productId],
      );
      const images = await db.query(
        `select source_url, alt_text from public.product_images where product_id = $1 order by position`,
        [productId],
      );
      const x = p.rows[0];
      return {
        id: x.id,
        title: x.title,
        productType: x.product_type,
        status: x.status,
        printifyProductId: x.printify_product_id,
        etsyListingId: x.external_listing_id,
        locked: x.printify_is_locked,
        syncedAt: x.printify_synced_at,
        variants: variants.rows.map((v) => ({
          id: v.id,
          title: v.title,
          sku: v.sku,
          price: v.price,
          currency: v.currency,
          enabled: v.is_enabled,
          available: v.is_available,
          productionCost: v.production_cost,
          shipping: v.shipping ?? [],
        })),
        costHistory: history.rows,
        images: images.rows.map((i) => ({ url: i.source_url, alt: i.alt_text })),
      };
    });
  }

  /**
   * Request to publish a Printify product to the connected Etsy shop. Creates an
   * approval request; Printify's publish endpoint is called only after approval.
   */
  async requestPublish(
    ctx: AuthContext,
    storeId: string,
    productId: string,
    reason: string,
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const p = await db.query(
        `select id, title, printify_product_id, external_listing_id, printify_is_locked from public.products where store_id = $1 and id = $2`,
        [storeId, productId],
      );
      const prod = p.rows[0];
      if (!prod) throw new NotFoundException('Ürün bulunamadı');
      if (!prod.printify_product_id) throw new ConflictException('Bu ürün Printify ürünü değil');
      if (prod.printify_is_locked)
        throw new ConflictException('Ürün Printify’da kilitli (yayınlama sürüyor)');
      const pending = await db.query(
        `select 1 from public.approval_requests where store_id = $1 and action_type = 'publish_product'
            and status in ('pending','approved','executing') and payload->>'productId' = $2`,
        [storeId, productId],
      );
      if (pending.rowCount)
        throw new ConflictException('Bu ürün için bekleyen bir yayın isteği var');
      const costs = await db.query(
        `select min(v.price)::text min_price, max(v.price)::text max_price,
                min(c.amount)::text min_cost, max(c.amount)::text max_cost, count(distinct v.id)::int variants
           from public.product_variants v left join public.product_costs c
             on c.product_variant_id = v.id and c.cost_type = 'production' and c.valid_to is null
          where v.product_id = $1 and v.is_enabled`,
        [productId],
      );
      const k = costs.rows[0];
      const r = await db.query(
        `insert into public.approval_requests
           (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit,
            estimated_cost, cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
         values ($1,'user',$2,'publish_product',$3,$4,$5,$6,0,'USD',$7,$8,$9,'high',true, now() + interval '7 days')
         returning *`,
        [
          storeId,
          ctx.userId,
          `Etsy’de yayınla: ${prod.title.slice(0, 80)}`,
          prod.external_listing_id
            ? `Printify ürünü bağlı Etsy ilanını (#${prod.external_listing_id}) güncelleyecek: başlık, açıklama, görseller, varyantlar, etiketler.`
            : `Printify ürünü bağlı Etsy mağazasında yeni ilan olarak yayınlanacak (${k.variants} aktif varyant).`,
          reason,
          'Yeni ürünün satışa açılması',
          `Satış fiyatı ${k.min_price ?? '?'}–${k.max_price ?? '?'} USD, Printify üretim maliyeti ${k.min_cost ?? '?'}–${k.max_cost ?? '?'} USD. ` +
            'Etsy listeleme ücreti uygulanır. Tam katkı hesabı Profit Engine ile yapılır.',
          'POST /v1/shops/{shop_id}/products/{product_id}/publish.json (Printify → Etsy)',
          JSON.stringify({
            kind: 'printify_publish',
            productId,
            printifyProductId: prod.printify_product_id,
          }),
        ],
      );
      return r.rows[0];
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: 'publish_product', productId },
      meta,
    });
    return toApprovalDto(approval);
  }
}
