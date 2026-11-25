import { ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import type { ApprovalDto, ListingChangeRequest, ListingDto } from '@esm/shared';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

const LISTING_COLUMNS = `id, etsy_listing_id, state, title, description, tags, materials, price, currency,
  quantity, num_favorers, etsy_url, primary_image_url, data_origin, last_synced_at, etsy_updated_at`;

const CHANGE_FIELDS = ['title', 'description', 'tags', 'materials', 'state'] as const;
type ChangeField = (typeof CHANGE_FIELDS)[number];

@Injectable()
export class ListingsService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
  ) {}

  list(
    ctx: AuthContext,
    storeId: string,
    q: { state?: string; search?: string; limit: number; offset: number },
  ): Promise<{ total: number; items: ListingDto[] }> {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const params: unknown[] = [storeId];
      let where = 'store_id = $1';
      if (q.state) {
        params.push(q.state);
        where += ` and state = $${params.length}`;
      }
      if (q.search) {
        params.push(`%${q.search.replace(/[%_\\]/g, (c) => `\\${c}`)}%`);
        where += ` and title ilike $${params.length}`;
      }
      const total = await db.query(
        `select count(*)::int as n from public.listings where ${where}`,
        params,
      );
      params.push(q.limit, q.offset);
      const r = await db.query(
        `select ${LISTING_COLUMNS} from public.listings where ${where}
          order by etsy_updated_at desc nulls last, created_at desc
          limit $${params.length - 1} offset $${params.length}`,
        params,
      );
      return { total: total.rows[0].n, items: r.rows.map(toListingDto) };
    });
  }

  async get(ctx: AuthContext, storeId: string, listingId: string): Promise<ListingDto> {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const row = await findListing(db, storeId, listingId);
      if (!row) throw new NotFoundException('İlan bulunamadı');
      return toListingDto(row);
    });
  }

  /**
   * Creates an approval request; nothing is sent to Etsy until the owner approves.
   * The baseline captures the values the change was based on, so the executor can
   * refuse to overwrite edits made directly on Etsy in the meantime.
   */
  async requestChange(
    ctx: AuthContext,
    storeId: string,
    listingId: string,
    input: ListingChangeRequest,
    meta: RequestMeta,
  ): Promise<ApprovalDto> {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const listing = await findListing(db, storeId, listingId);
      if (!listing) throw new NotFoundException('İlan bulunamadı');
      if (!listing.etsy_listing_id) throw new ConflictException('Bu ilan Etsy ile eşleşmemiş');

      const changes: Partial<Record<ChangeField, unknown>> = {};
      const baseline: Partial<Record<ChangeField, unknown>> = {};
      for (const f of CHANGE_FIELDS) {
        const next = input[f];
        if (next === undefined) continue;
        if (JSON.stringify(next) === JSON.stringify(listing[f])) continue;
        changes[f] = next;
        baseline[f] = listing[f];
      }
      if (!Object.keys(changes).length)
        throw new ConflictException('Mevcut değerlerle aynı; değişiklik yok');

      const pending = await db.query(
        `select 1 from public.approval_requests
          where store_id = $1 and action_type = 'update_listing' and status in ('pending','approved','executing')
            and payload->>'listingId' = $2`,
        [storeId, listingId],
      );
      if (pending.rowCount)
        throw new ConflictException('Bu ilan için bekleyen bir değişiklik isteği var');

      const settings = await db.query(
        `select require_reauth_for_sensitive from public.user_settings where user_id = $1`,
        [ctx.userId],
      );
      const publishes = changes.state === 'active' && listing.state !== 'active';
      const fields = Object.keys(changes);
      const r = await db.query(
        `insert into public.approval_requests
           (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit,
            estimated_cost, cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
         values ($1, 'user', $2, $3, $4, $5, $6, $7, 0, $8, $9, $10, $11, $12, $13, now() + interval '7 days')
         returning *`,
        [
          storeId,
          ctx.userId,
          publishes ? 'publish_product' : 'update_listing',
          `İlan güncelle: ${listing.title.slice(0, 80)}`,
          `Etsy ilanında şu alanlar değişecek: ${fields.join(', ')}. Diğer alanlar korunur.`,
          input.reason,
          fields.some((f) => f === 'title' || f === 'tags' || f === 'description')
            ? 'Arama görünürlüğü / dönüşüm iyileşmesi beklenir (ölçülmeden kesin değildir).'
            : null,
          listing.currency ?? 'USD',
          'Doğrudan maliyet yok; fiyat ve stok değişmiyor.',
          'PATCH /v3/application/shops/{shop_id}/listings/{listing_id} (updateListing, listings_w)',
          JSON.stringify({ listingId, etsyListingId: listing.etsy_listing_id, changes, baseline }),
          publishes ? 'high' : 'medium',
          publishes || settings.rows[0]?.require_reauth_for_sensitive === true,
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
      after: { actionType: approval.action_type, payload: approval.payload },
      meta,
    });
    return toApprovalDto(approval);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function findListing(db: Queryable, storeId: string, listingId: string): Promise<any> {
  const r = await db.query(
    `select ${LISTING_COLUMNS} from public.listings where store_id = $1 and id = $2`,
    [storeId, listingId],
  );
  return r.rows[0] ?? null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toListingDto(r: any): ListingDto {
  return {
    id: r.id,
    etsyListingId: r.etsy_listing_id,
    state: r.state,
    title: r.title,
    description: r.description,
    tags: r.tags,
    materials: r.materials,
    price: r.price,
    currency: r.currency,
    quantity: r.quantity,
    numFavorers: r.num_favorers,
    etsyUrl: r.etsy_url,
    primaryImageUrl: r.primary_image_url,
    dataOrigin: r.data_origin,
    lastSyncedAt: r.last_synced_at,
    etsyUpdatedAt: r.etsy_updated_at,
  };
}
