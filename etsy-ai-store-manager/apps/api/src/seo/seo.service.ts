import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { EtsyClient, type EtsyDraftListingInput, type EtsyTaxonomyNode } from '@esm/integrations';
import { scanProtectedTerms } from '@esm/design-tools';
import {
  JOBS,
  QUEUES,
  STORE_LANGUAGE_CODES,
  normalizeTag,
  validateListingSeo,
  type ApprovalDto,
  type SeoIssue,
} from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

export interface ContentEdit {
  title: string;
  description: string;
  tags: string[];
  materials?: string[];
}

export interface DraftListingRequest {
  productId?: string;
  seoDraftId?: string;
  title: string;
  description: string;
  tags: string[];
  materials: string[];
  price: string;
  quantity: number;
  taxonomyId: number;
  whoMade: 'i_did' | 'someone_else' | 'collective';
  whenMade: string;
  isSupply: boolean;
  shippingProfileId: number;
  returnPolicyId?: number;
  productionPartnerIds: number[];
  processingMin?: number;
  processingMax?: number;
  reason: string;
}

const ipIssue = (text: string): SeoIssue[] => {
  const hits = scanProtectedTerms(text);
  return hits.length
    ? [
        {
          field: 'title',
          code: 'protected_terms',
          severity: 'error',
          message: `Korumalı olabilecek ifadeler: ${hits.join(', ')}`,
        },
      ]
    : [];
};

function check(c: ContentEdit, primaryKeyword?: string | null) {
  const rep = validateListingSeo({ ...c, primaryKeyword });
  const issues = [...rep.issues, ...ipIssue(`${c.title} ${c.tags.join(' ')}`)];
  const blocking = issues.some((i) => i.severity === 'error');
  return { score: blocking ? Math.min(rep.score, 49) : rep.score, issues, blocking };
}

const cleanTags = (tags: string[]) => [...new Set(tags.map(normalizeTag).filter(Boolean))];

@Injectable()
export class SeoService {
  private taxonomyCache: {
    at: number;
    flat: Array<{ id: number; path: string; leaf: boolean }>;
  } | null = null;

  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  private requireAi() {
    if (!this.env.ANTHROPIC_API_KEY)
      throw new ServiceUnavailableException('ANTHROPIC_API_KEY tanımlı değil');
  }

  // ------------------------------------------------------------------ SEO drafts

  async requestDraft(
    ctx: AuthContext,
    storeId: string,
    target: { listingId?: string; productId?: string },
    language: string,
    meta: RequestMeta,
  ) {
    this.requireAi();
    const id = randomUUID();
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const langs = await db.query(
        `select languages from public.store_settings where store_id = $1`,
        [storeId],
      );
      if (!(langs.rows[0]?.languages ?? ['en']).includes(language))
        throw new BadRequestException(
          `"${language}" mağaza dilleri arasında değil (Ayarlar → Diller)`,
        );
      if (target.listingId) {
        const l = await db.query(`select 1 from public.listings where id = $1 and store_id = $2`, [
          target.listingId,
          storeId,
        ]);
        if (!l.rowCount) throw new NotFoundException('İlan bulunamadı');
      } else {
        const p = await db.query(`select 1 from public.products where id = $1 and store_id = $2`, [
          target.productId,
          storeId,
        ]);
        if (!p.rowCount) throw new NotFoundException('Ürün bulunamadı');
      }
      const busy = await db.query(
        `select 1 from public.seo_drafts where store_id = $1 and status = 'generating'
           and (listing_id = $2 or product_id = $3) and created_at > now() - interval '10 minutes'`,
        [storeId, target.listingId ?? null, target.productId ?? null],
      );
      if (busy.rowCount)
        throw new ConflictException('Bu kayıt için SEO önerisi zaten hazırlanıyor');
      await db.query(
        `insert into public.seo_drafts (id, store_id, listing_id, product_id, language, status, created_by)
         values ($1,$2,$3,$4,$5,'generating',$6)`,
        [id, storeId, target.listingId ?? null, target.productId ?? null, language, ctx.userId],
      );
    });
    await this.queue.enqueue(QUEUES.sync, JOBS.seoGenerate, {
      idempotencyKey: `seo-generate:${id}`,
      storeId,
      payload: { draftId: id, userId: ctx.userId },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'seo.draft.request',
      entityType: 'seo_draft',
      entityId: id,
      after: { ...target, language },
      meta,
    });
    return { id, status: 'generating' };
  }

  listDrafts(ctx: AuthContext, storeId: string, q: { listingId?: string; productId?: string }) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select d.*, t.cost_usd from public.seo_drafts d left join public.ai_tasks t on t.id = d.ai_task_id
          where d.store_id = $1 and ($2::uuid is null or d.listing_id = $2) and ($3::uuid is null or d.product_id = $3)
          order by d.created_at desc limit 50`,
        [storeId, q.listingId ?? null, q.productId ?? null],
      );
      return r.rows.map(toDraftDto);
    });
  }

  /** Manual edit of a draft; re-runs the deterministic checks. */
  async editDraft(
    ctx: AuthContext,
    storeId: string,
    draftId: string,
    edit: ContentEdit,
    meta: RequestMeta,
  ) {
    const tags = cleanTags(edit.tags);
    if (tags.length > 13) throw new BadRequestException('En fazla 13 etiket');
    const content = { ...edit, tags, materials: edit.materials ?? [] };
    const row = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await lockDraft(db, storeId, draftId);
      if (!['draft', 'rejected', 'failed'].includes(d.status))
        throw new ConflictException(`"${d.status}" durumundaki öneri düzenlenemez`);
      const c = check(content, d.primary_keyword);
      const r = await db.query(
        `update public.seo_drafts set title = $3, description = $4, tags = $5, materials = $6, seo_score = $7,
                issues = $8, status = 'draft', source = 'manual', error = null
          where id = $1 and store_id = $2 returning *`,
        [
          draftId,
          storeId,
          content.title,
          content.description,
          content.tags,
          content.materials,
          c.score,
          JSON.stringify(c.issues),
        ],
      );
      return r.rows[0];
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'seo.draft.edit',
      entityType: 'seo_draft',
      entityId: draftId,
      after: content,
      meta,
    });
    return toDraftDto(row);
  }

  async rejectDraft(ctx: AuthContext, storeId: string, draftId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await lockDraft(db, storeId, draftId);
      if (d.status === 'pending_approval' || d.status === 'applied')
        throw new ConflictException(`"${d.status}" durumundaki öneri reddedilemez`);
      const r = await db.query(
        `update public.seo_drafts set status = 'rejected' where id = $1 returning *`,
        [draftId],
      );
      return toDraftDto(r.rows[0]);
    });
  }

  /**
   * Turns a checked draft into an approval request. Etsy listing → updateListing
   * (title/description/tags/materials); Printify product → Printify product update
   * (+ title/description/tags republish when it is already on Etsy).
   */
  async applyDraft(
    ctx: AuthContext,
    storeId: string,
    draftId: string,
    reason: string,
    meta: RequestMeta,
  ): Promise<ApprovalDto> {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await lockDraft(db, storeId, draftId);
      if (d.status !== 'draft') throw new ConflictException(`Öneri "${d.status}" durumunda`);
      const c = check(
        { title: d.title, description: d.description, tags: d.tags, materials: d.materials },
        d.primary_keyword,
      );
      if (c.blocking)
        throw new ConflictException({
          message: 'Öneri Etsy kurallarına uymuyor; önce düzenleyin',
          details: c.issues
            .filter((i) => i.severity === 'error')
            .map((i) => ({ path: i.field, message: i.message })),
        });
      const reauth = await needsReauth(db, ctx.userId);
      let row;
      if (d.listing_id) {
        const l = (
          await db.query(
            `select id, etsy_listing_id, title, description, tags, materials, currency from public.listings where id = $1 and store_id = $2`,
            [d.listing_id, storeId],
          )
        ).rows[0];
        if (!l?.etsy_listing_id) throw new ConflictException('İlan Etsy ile eşleşmemiş');
        await assertNoPending(db, storeId, `payload->>'listingId' = $2`, [l.id]);
        const changes: Record<string, unknown> = {};
        const baseline: Record<string, unknown> = {};
        for (const f of ['title', 'description', 'tags', 'materials'] as const) {
          if (f === 'materials' && !d.materials.length) continue;
          if (JSON.stringify(d[f]) === JSON.stringify(l[f])) continue;
          changes[f] = d[f];
          baseline[f] = l[f];
        }
        if (!Object.keys(changes).length) throw new ConflictException('İlan zaten bu içerikte');
        row = await insertApproval(db, {
          storeId,
          userId: ctx.userId,
          actionType: 'update_listing',
          title: `SEO uygula: ${l.title.slice(0, 80)}`,
          what: `Etsy ilanında ${Object.keys(changes).join(', ')} alanları SEO önerisiyle değişecek (puan ${d.seo_score}). Fiyat, stok ve görseller değişmez.`,
          why: reason,
          benefit:
            'Etsy aramasında daha isabetli eşleşme ve tıklanma beklenir (ölçülmeden kesin değildir).',
          currency: l.currency ?? 'USD',
          profit: 'Doğrudan maliyet yok; fiyat değişmiyor.',
          api: 'PATCH /v3/application/shops/{shop_id}/listings/{listing_id} (updateListing, listings_w)',
          payload: {
            listingId: l.id,
            etsyListingId: l.etsy_listing_id,
            changes,
            baseline,
            seoDraftId: d.id,
          },
          risk: 'medium',
          reauth,
        });
      } else {
        const p = (
          await db.query(
            `select id, title, printify_product_id, external_listing_id, metadata from public.products where id = $1 and store_id = $2`,
            [d.product_id, storeId],
          )
        ).rows[0];
        if (!p?.printify_product_id) throw new ConflictException('Ürün Printify ile eşleşmemiş');
        await assertNoPending(
          db,
          storeId,
          `payload->>'printifyProductId' = $2 and payload->>'kind' = 'printify_product_seo'`,
          [p.printify_product_id],
        );
        row = await insertApproval(db, {
          storeId,
          userId: ctx.userId,
          actionType: 'update_listing',
          title: `SEO uygula (Printify): ${p.title.slice(0, 80)}`,
          what: `Printify ürününün başlık, açıklama ve etiketleri güncellenecek${
            p.external_listing_id
              ? ' ve yalnızca bu alanlar Etsy ilanına yeniden gönderilecek'
              : ' (henüz Etsy’de değil)'
          }.`,
          why: reason,
          benefit: 'Yayınlandığında Etsy aramasında daha iyi eşleşme beklenir.',
          currency: 'USD',
          profit: 'Doğrudan maliyet yok; fiyat ve varyantlar değişmiyor.',
          api: p.external_listing_id
            ? 'PUT /v1/shops/{shop_id}/products/{product_id}.json + POST .../publish.json (title, description, tags)'
            : 'PUT /v1/shops/{shop_id}/products/{product_id}.json',
          payload: {
            kind: 'printify_product_seo',
            productId: p.id,
            printifyProductId: p.printify_product_id,
            changes: { title: d.title, description: d.description, tags: d.tags },
            baseline: { title: p.title, tags: p.metadata?.tags ?? [] },
            seoDraftId: d.id,
          },
          risk: p.external_listing_id ? 'medium' : 'low',
          reauth,
        });
      }
      await db.query(
        `update public.seo_drafts set status = 'pending_approval', approval_request_id = $2 where id = $1`,
        [d.id, row.id],
      );
      return row;
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: approval.action_type, seoDraftId: draftId },
      meta,
    });
    return toApprovalDto(approval);
  }

  // ------------------------------------------------------------------ translations

  async requestTranslations(
    ctx: AuthContext,
    storeId: string,
    listingId: string,
    languages: string[],
    meta: RequestMeta,
  ) {
    this.requireAi();
    const ids = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const l = await db.query(
        `select id, description from public.listings where id = $1 and store_id = $2`,
        [listingId, storeId],
      );
      if (!l.rowCount) throw new NotFoundException('İlan bulunamadı');
      if (!l.rows[0].description) throw new ConflictException('Kaynak ilanın açıklaması yok');
      const s = (
        await db.query(
          `select default_language, languages from public.store_settings where store_id = $1`,
          [storeId],
        )
      ).rows[0];
      const out: string[] = [];
      for (const lang of languages) {
        if (lang === s.default_language) throw new BadRequestException(`"${lang}" ilanın ana dili`);
        if (!s.languages.includes(lang))
          throw new BadRequestException(
            `"${lang}" mağaza dilleri arasında değil (Ayarlar → Diller)`,
          );
        const r = await db.query(
          `insert into public.listing_translations (listing_id, store_id, language, status, title, source)
           values ($1,$2,$3,'generating',null,'ai')
           on conflict (listing_id, language) do update set status = 'generating', error = null
             where public.listing_translations.status not in ('pending_approval','generating')
           returning id`,
          [listingId, storeId, lang],
        );
        if (!r.rowCount)
          throw new ConflictException(`"${lang}" çevirisi şu an hazırlanıyor veya onay bekliyor`);
        out.push(r.rows[0].id);
      }
      return out;
    });
    for (const id of ids) {
      await this.queue.enqueue(QUEUES.sync, JOBS.seoTranslate, {
        idempotencyKey: `seo-translate:${id}:${Date.now()}`,
        storeId,
        payload: { translationId: id, userId: ctx.userId },
      });
    }
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'seo.translate.request',
      entityType: 'listing',
      entityId: listingId,
      after: { languages },
      meta,
    });
    return { ids };
  }

  listTranslations(ctx: AuthContext, storeId: string, listingId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select * from public.listing_translations where store_id = $1 and listing_id = $2 order by language`,
        [storeId, listingId],
      );
      return r.rows.map(toTranslationDto);
    });
  }

  async editTranslation(ctx: AuthContext, storeId: string, id: string, edit: ContentEdit) {
    const tags = cleanTags(edit.tags);
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const t = await lockTranslation(db, storeId, id);
      if (['generating', 'pending_approval'].includes(t.status))
        throw new ConflictException(`Çeviri "${t.status}" durumunda`);
      const c = check({ title: edit.title, description: edit.description, tags });
      const r = await db.query(
        `update public.listing_translations set title = $3, description = $4, tags = $5, quality_score = $6, quality_notes = $7,
                status = 'draft', source = 'manual', reviewed_by = null, reviewed_at = null, error = null
          where id = $1 and store_id = $2 returning *`,
        [id, storeId, edit.title, edit.description, tags, c.score, JSON.stringify(c.issues)],
      );
      return toTranslationDto(r.rows[0]);
    });
  }

  /** Human review: the reviewer confirms the translation (back-translation shown in the UI). */
  async reviewTranslation(
    ctx: AuthContext,
    storeId: string,
    id: string,
    decision: 'reviewed' | 'rejected',
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const t = await lockTranslation(db, storeId, id);
      if (!['draft', 'reviewed', 'rejected', 'published'].includes(t.status))
        throw new ConflictException(`Çeviri "${t.status}" durumunda`);
      if (decision === 'reviewed') {
        const blocking = (t.quality_notes as SeoIssue[]).some((i) => i.severity === 'error');
        if (blocking) throw new ConflictException('Kalite kontrolünde hata var; önce düzenleyin');
      }
      const r = await db.query(
        `update public.listing_translations set status = $3, reviewed_by = $4, reviewed_at = now() where id = $1 and store_id = $2 returning *`,
        [id, storeId, decision, ctx.userId],
      );
      return toTranslationDto(r.rows[0]);
    });
  }

  async publishTranslation(
    ctx: AuthContext,
    storeId: string,
    id: string,
    reason: string,
    meta: RequestMeta,
  ): Promise<ApprovalDto> {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const t = await lockTranslation(db, storeId, id);
      if (t.status !== 'reviewed')
        throw new ConflictException('Önce çeviriyi inceleyip onaylayın (insan kontrolü)');
      const l = (
        await db.query(`select title, etsy_listing_id from public.listings where id = $1`, [
          t.listing_id,
        ])
      ).rows[0];
      if (!l?.etsy_listing_id) throw new ConflictException('İlan Etsy ile eşleşmemiş');
      const row = await insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'update_listing_translation',
        title: `Çeviri yayınla (${t.language}): ${l.title.slice(0, 70)}`,
        what: `Etsy ilanına ${t.language} dilinde başlık, açıklama ve ${t.tags.length} etiket eklenecek/güncellenecek. Ana dildeki içerik değişmez.`,
        why: reason,
        benefit: `${t.language} dilinde arama yapan alıcılara yerel içerik gösterilir (kalite puanı ${t.quality_score}).`,
        currency: 'USD',
        profit: 'Doğrudan maliyet yok.',
        api: 'POST/PUT /v3/application/shops/{shop_id}/listings/{listing_id}/translations/{language} (listings_w)',
        payload: {
          translationId: t.id,
          listingId: t.listing_id,
          etsyListingId: l.etsy_listing_id,
          language: t.language,
          title: t.title,
          description: t.description,
          tags: t.tags,
        },
        risk: 'low',
        reauth: await needsReauth(db, ctx.userId),
      });
      await db.query(
        `update public.listing_translations set status = 'pending_approval', approval_request_id = $2 where id = $1`,
        [t.id, row.id],
      );
      return row;
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: 'update_listing_translation', translationId: id },
      meta,
    });
    return toApprovalDto(approval);
  }

  // ------------------------------------------------------------------ new Etsy listings

  /** Options stored by the last Etsy sync (shipping profiles, return policies, production partners). */
  async listingOptions(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select metadata->'listing_options' as o from public.connected_accounts
          where store_id = $1 and platform = 'etsy' and status = 'active' limit 1`,
        [storeId],
      );
      const o = r.rows[0]?.o ?? null;
      return {
        connected: r.rowCount === 1,
        shippingProfiles: o?.shippingProfiles ?? [],
        returnPolicies: o?.returnPolicies ?? [],
        productionPartners: o?.productionPartners ?? [],
        fetchedAt: o?.fetchedAt ?? null,
        whenMade: ['made_to_order', '2020_2026', '2010_2019', 'before_2007'],
      };
    });
  }

  /** Seller taxonomy search (public Etsy data, API key only; cached 24 h in memory). */
  async taxonomy(q: string) {
    if (!this.env.ETSY_KEYSTRING || !this.env.ETSY_SHARED_SECRET)
      throw new ServiceUnavailableException('ETSY_KEYSTRING / ETSY_SHARED_SECRET tanımlı değil');
    if (!this.taxonomyCache || Date.now() - this.taxonomyCache.at > 86_400_000) {
      const client = new EtsyClient({
        app: {
          keystring: this.env.ETSY_KEYSTRING,
          sharedSecret: this.env.ETSY_SHARED_SECRET,
          apiBaseUrl: this.env.ETSY_API_BASE_URL,
        },
        getAccessToken: async () => {
          throw new Error('not used');
        },
      });
      const res = await client.getSellerTaxonomyNodes();
      const flat: Array<{ id: number; path: string; leaf: boolean }> = [];
      const walk = (n: EtsyTaxonomyNode, prefix: string) => {
        const path = prefix ? `${prefix} › ${n.name}` : n.name;
        flat.push({ id: n.id, path, leaf: !n.children?.length });
        for (const c of n.children ?? []) walk(c, path);
      };
      for (const n of res.results) walk(n, '');
      this.taxonomyCache = { at: Date.now(), flat };
    }
    const needle = q.trim().toLowerCase();
    return this.taxonomyCache.flat
      .filter((n) => !needle || n.path.toLowerCase().includes(needle))
      .slice(0, 40);
  }

  /**
   * Approval request for createDraftListing. Printify-managed products are refused here:
   * Printify creates their Etsy listing on publish (a direct listing would duplicate it).
   */
  async requestDraftListing(
    ctx: AuthContext,
    storeId: string,
    input: DraftListingRequest,
    meta: RequestMeta,
  ): Promise<ApprovalDto> {
    const tags = cleanTags(input.tags);
    const c = check({
      title: input.title,
      description: input.description,
      tags,
      materials: input.materials,
    });
    if (c.blocking)
      throw new BadRequestException({
        message: 'İçerik Etsy kurallarına uymuyor',
        details: c.issues
          .filter((i) => i.severity === 'error')
          .map((i) => ({ path: i.field, message: i.message })),
      });
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const opts = (
        await db.query(
          `select metadata->'listing_options' as o from public.connected_accounts where store_id = $1 and platform = 'etsy' and status = 'active'`,
          [storeId],
        )
      ).rows[0]?.o;
      if (!opts) throw new ConflictException('Etsy bağlantısı yok veya henüz senkronize edilmedi');
      if (
        !(opts.shippingProfiles ?? []).some((x: { id: number }) => x.id === input.shippingProfileId)
      )
        throw new BadRequestException(
          'Kargo profili mağazada bulunamadı (Etsy senkronizasyonunu yenileyin)',
        );
      if (
        input.returnPolicyId &&
        !(opts.returnPolicies ?? []).some((x: { id: number }) => x.id === input.returnPolicyId)
      )
        throw new BadRequestException('İade politikası mağazada bulunamadı');
      for (const id of input.productionPartnerIds)
        if (!(opts.productionPartners ?? []).some((x: { id: number }) => x.id === id))
          throw new BadRequestException(`Üretim ortağı ${id} mağazada tanımlı değil`);
      // Etsy: "someone_else" is only valid for supplies or vintage (20+ years) items
      const vintage = !['made_to_order', '2020_2026', '2010_2019'].includes(input.whenMade);
      if (input.whoMade === 'someone_else' && !input.isSupply && !vintage)
        throw new BadRequestException(
          '"Başkası yaptı" yalnızca malzeme veya vintage ürünlerde kullanılabilir',
        );
      if (input.productId) {
        const p = (
          await db.query(
            `select printify_product_id from public.products where id = $1 and store_id = $2`,
            [input.productId, storeId],
          )
        ).rows[0];
        if (!p) throw new NotFoundException('Ürün bulunamadı');
        if (p.printify_product_id)
          throw new ConflictException(
            'Bu ürün Printify üzerinden yönetiliyor; Etsy ilanını Printify yayınlama onayı oluşturur (çift ilan önlenir).',
          );
      }
      await assertNoPending(
        db,
        storeId,
        `action_type = 'create_listing' and payload->'input'->>'title' = $2`,
        [input.title],
      );
      const etsyInput: EtsyDraftListingInput = {
        quantity: input.quantity,
        title: input.title,
        description: input.description,
        price: Number(input.price),
        who_made: input.whoMade,
        when_made: input.whenMade,
        taxonomy_id: input.taxonomyId,
        is_supply: input.isSupply,
        type: 'physical',
        shipping_profile_id: input.shippingProfileId,
        ...(input.returnPolicyId ? { return_policy_id: input.returnPolicyId } : {}),
        tags,
        materials: input.materials,
        ...(input.productionPartnerIds.length
          ? { production_partner_ids: input.productionPartnerIds }
          : {}),
        ...(input.processingMin ? { processing_min: input.processingMin } : {}),
        ...(input.processingMax ? { processing_max: input.processingMax } : {}),
      };
      return insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'create_listing',
        title: `Etsy taslak ilan: ${input.title.slice(0, 80)}`,
        what: `Etsy’de TASLAK ilan oluşturulacak ($${input.price}, ${input.quantity} adet, SEO puanı ${c.score}). Taslak alıcılara görünmez; görseller Etsy’de eklenip ayrıca yayınlanmalıdır.`,
        why: input.reason,
        benefit: 'Yeni ürünün Etsy’de satışa hazırlanması.',
        currency: 'USD',
        profit:
          'Taslak oluşturmak ücretsizdir; Etsy ilan ücreti yayınlandığında alınır. Fiyatın kâr kontrolü yayın öncesi ürün sayfasından yapılmalıdır.',
        api: 'POST /v3/application/shops/{shop_id}/listings (createDraftListing, listings_w)',
        payload: {
          productId: input.productId ?? null,
          seoDraftId: input.seoDraftId ?? null,
          input: etsyInput,
          currency: 'USD',
        },
        risk: 'medium',
        reauth: await needsReauth(db, ctx.userId),
      });
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: approval.id,
      after: { actionType: 'create_listing', title: input.title },
      meta,
    });
    return toApprovalDto(approval);
  }

  /** Read-only checker for the editor (no AI). */
  check(c: ContentEdit, primaryKeyword?: string) {
    return check({ ...c, tags: cleanTags(c.tags) }, primaryKeyword);
  }
}

export const SEO_LANGUAGES = STORE_LANGUAGE_CODES;

// ---------------------------------------------------------------- helpers

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function lockDraft(db: Queryable, storeId: string, id: string): Promise<any> {
  const r = await db.query(
    `select * from public.seo_drafts where id = $1 and store_id = $2 for update`,
    [id, storeId],
  );
  if (!r.rowCount) throw new NotFoundException('SEO önerisi bulunamadı');
  return r.rows[0];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function lockTranslation(db: Queryable, storeId: string, id: string): Promise<any> {
  const r = await db.query(
    `select * from public.listing_translations where id = $1 and store_id = $2 for update`,
    [id, storeId],
  );
  if (!r.rowCount) throw new NotFoundException('Çeviri bulunamadı');
  return r.rows[0];
}

async function needsReauth(db: Queryable, userId: string): Promise<boolean> {
  const s = await db.query(
    `select require_reauth_for_sensitive from public.user_settings where user_id = $1`,
    [userId],
  );
  return s.rows[0]?.require_reauth_for_sensitive === true;
}

async function assertNoPending(db: Queryable, storeId: string, cond: string, params: unknown[]) {
  const r = await db.query(
    `select 1 from public.approval_requests where store_id = $1 and status in ('pending','approved','executing') and ${cond}`,
    [storeId, ...params],
  );
  if (r.rowCount) throw new ConflictException('Bu kayıt için bekleyen bir onay isteği var');
}

async function insertApproval(
  db: Queryable,
  a: {
    storeId: string;
    userId: string;
    actionType: string;
    title: string;
    what: string;
    why: string;
    benefit: string;
    currency: string;
    profit: string;
    api: string;
    payload: unknown;
    risk: 'low' | 'medium' | 'high';
    reauth: boolean;
  },
) {
  const r = await db.query(
    `insert into public.approval_requests
       (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit,
        estimated_cost, cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
     values ($1,'user',$2,$3,$4,$5,$6,$7,0,$8,$9,$10,$11,$12,$13, now() + interval '7 days') returning *`,
    [
      a.storeId,
      a.userId,
      a.actionType,
      a.title,
      a.what,
      a.why,
      a.benefit,
      a.currency,
      a.profit,
      a.api,
      JSON.stringify(a.payload),
      a.risk,
      a.reauth,
    ],
  );
  return r.rows[0];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toDraftDto(r: any) {
  return {
    id: r.id,
    listingId: r.listing_id,
    productId: r.product_id,
    language: r.language,
    status: r.status,
    primaryKeyword: r.primary_keyword,
    title: r.title,
    description: r.description,
    tags: r.tags,
    materials: r.materials,
    rationale: r.rationale,
    seoScore: r.seo_score === null ? null : Number(r.seo_score),
    issues: r.issues,
    baseline: r.baseline,
    source: r.source,
    approvalRequestId: r.approval_request_id,
    error: r.error,
    costUsd: r.cost_usd ?? null,
    createdAt: r.created_at,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toTranslationDto(r: any) {
  return {
    id: r.id,
    listingId: r.listing_id,
    language: r.language,
    status: r.status,
    title: r.title,
    description: r.description,
    tags: r.tags,
    qualityScore: r.quality_score === null ? null : Number(r.quality_score),
    qualityNotes: r.quality_notes,
    backTranslation: r.back_translation,
    localizationNotes: r.localization_notes,
    source: r.source,
    reviewedAt: r.reviewed_at,
    publishedAt: r.published_at,
    approvalRequestId: r.approval_request_id,
    error: r.error,
  };
}
