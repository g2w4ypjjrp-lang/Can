import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import {
  blobStoreFromEnv,
  inspectImage,
  normalizeUpload,
  prepareForPrintArea,
  removeUniformBackground,
  scanProtectedTerms,
  type BlobStore,
} from '@esm/design-tools';
import { JOBS, QUEUES } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { PrintifyService } from '../printify/printify.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';

export interface CreateDesignInput {
  title: string;
  brief?: string;
  humanContribution: string;
  productType: string;
  style?: string;
  tags?: string[];
  opportunityId?: string;
}

@Injectable()
export class DesignsService {
  readonly store: BlobStore;

  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
    private readonly printify: PrintifyService,
  ) {
    this.store = blobStoreFromEnv(env);
  }

  async create(ctx: AuthContext, storeId: string, input: CreateDesignInput, meta: RequestMeta) {
    const id = randomUUID();
    const hits = scanProtectedTerms(
      `${input.title} ${input.brief ?? ''} ${(input.tags ?? []).join(' ')}`,
    );
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      if (input.opportunityId) {
        const o = await db.query(
          `select 1 from public.product_opportunities where id = $1 and store_id = $2`,
          [input.opportunityId, storeId],
        );
        if (!o.rowCount) throw new NotFoundException('Fırsat bulunamadı');
        await db.query(
          `update public.product_opportunities set status = 'in_design' where id = $1`,
          [input.opportunityId],
        );
      }
      await db.query(
        `insert into public.designs (id, store_id, created_by, title, prompt, human_contribution, product_type, style, tags,
                                     opportunity_id, ip_risk_level, ip_risk_notes)
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
        [
          id,
          storeId,
          ctx.userId,
          input.title,
          input.brief ?? null,
          input.humanContribution,
          input.productType,
          input.style ?? null,
          input.tags ?? [],
          input.opportunityId ?? null,
          hits.length ? 'high' : 'unknown',
          JSON.stringify(
            hits.length
              ? [
                  {
                    issue: `Korumalı olabilecek ifadeler: ${hits.join(', ')}`,
                    severity: 'high',
                    source: 'local_scan',
                  },
                ]
              : [],
          ),
        ],
      );
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'design.create',
      entityType: 'design',
      entityId: id,
      after: { ...input, localIpHits: hits },
      meta,
    });
    return this.get(ctx, storeId, id);
  }

  list(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select d.id, d.title, d.status, d.product_type, d.ip_risk_level, d.created_at, d.current_version_id,
                (select count(*)::int from public.design_versions v where v.design_id = d.id) versions
           from public.designs d where d.store_id = $1 order by d.created_at desc limit 200`,
        [storeId],
      );
      return r.rows;
    });
  }

  async get(ctx: AuthContext, storeId: string, id: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const d = await db.query(`select * from public.designs where store_id = $1 and id = $2`, [
        storeId,
        id,
      ]);
      if (!d.rowCount) throw new NotFoundException('Tasarım bulunamadı');
      const v = await db.query(
        `select id, version, width_px, height_px, dpi, has_transparency, generator, operation, parent_version_id, fit_report,
                print_area, checksum_sha256, created_at, generation_params
           from public.design_versions where design_id = $1 order by version desc`,
        [id],
      );
      const products = await db.query(
        `select id, title, status, printify_product_id from public.products where design_id = $1`,
        [id],
      );
      const x = d.rows[0];
      return {
        id: x.id,
        title: x.title,
        brief: x.prompt,
        humanContribution: x.human_contribution,
        productType: x.product_type,
        style: x.style,
        tags: x.tags,
        status: x.status,
        ipRiskLevel: x.ip_risk_level,
        ipRiskNotes: x.ip_risk_notes,
        ipReview: x.ip_review,
        ipReviewedAt: x.ip_reviewed_at,
        currentVersionId: x.current_version_id,
        opportunityId: x.opportunity_id,
        approvedAt: x.approved_at,
        versions: v.rows,
        products: products.rows,
      };
    });
  }

  /** Stores a new version (image already normalised to PNG). */
  private async addVersion(
    db: Queryable,
    storeId: string,
    designId: string,
    png: Buffer,
    data: {
      generator: 'ai' | 'upload' | 'edit';
      operation: string;
      parent?: string | null;
      fit?: unknown;
      area?: unknown;
      params?: unknown;
      aiTaskId?: string | null;
      userId: string | null;
    },
  ) {
    const info = await inspectImage(png);
    const n = await db.query(
      `select coalesce(max(version), 0) + 1 as n from public.design_versions where design_id = $1`,
      [designId],
    );
    const version: number = n.rows[0].n;
    const id = randomUUID();
    const objectPath = `${storeId}/designs/${designId}/v${version}.png`;
    await this.store.put(objectPath, png, 'image/png');
    await db.query(
      `insert into public.design_versions (id, design_id, store_id, version, storage_path, width_px, height_px, dpi, has_transparency,
                                           generator, generation_params, checksum_sha256, created_by, parent_version_id, operation,
                                           fit_report, print_area, ai_task_id)
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)`,
      [
        id,
        designId,
        storeId,
        version,
        objectPath,
        info.width,
        info.height,
        info.density ?? 72,
        info.hasAlpha,
        data.generator,
        JSON.stringify(data.params ?? {}),
        info.sha256,
        data.userId,
        data.parent ?? null,
        data.operation,
        data.fit ? JSON.stringify(data.fit) : null,
        data.area ? JSON.stringify(data.area) : null,
        data.aiTaskId ?? null,
      ],
    );
    // a new artwork invalidates an earlier IP review / approval
    await db.query(
      `update public.designs set current_version_id = $2,
              status = case when status = 'approved' then 'review' else status end,
              ip_reviewed_at = case when $3 then ip_reviewed_at else null end
        where id = $1`,
      [designId, id, data.operation === 'prepare_print'],
    );
    return id;
  }

  private async loadVersion(db: Queryable, storeId: string, designId: string, versionId: string) {
    const r = await db.query(
      `select * from public.design_versions where id = $1 and design_id = $2 and store_id = $3`,
      [versionId, designId, storeId],
    );
    if (!r.rowCount) throw new NotFoundException('Sürüm bulunamadı');
    return { row: r.rows[0], buf: await this.store.get(r.rows[0].storage_path) };
  }

  async upload(
    ctx: AuthContext,
    storeId: string,
    designId: string,
    input: { fileName: string; contentBase64: string },
    meta: RequestMeta,
  ) {
    const raw = Buffer.from(input.contentBase64, 'base64');
    let png: Buffer;
    try {
      png = await normalizeUpload(raw);
    } catch (e) {
      throw new BadRequestException(e instanceof Error ? e.message : 'Dosya okunamadı');
    }
    const id = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await db.query(`select 1 from public.designs where id = $1 and store_id = $2`, [
        designId,
        storeId,
      ]);
      if (!d.rowCount) throw new NotFoundException('Tasarım bulunamadı');
      return this.addVersion(db, storeId, designId, png, {
        generator: 'upload',
        operation: 'upload',
        params: { fileName: input.fileName.slice(0, 200) },
        userId: ctx.userId,
      });
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'design.upload',
      entityType: 'design_version',
      entityId: id,
      meta,
    });
    return this.get(ctx, storeId, designId);
  }

  async removeBackground(
    ctx: AuthContext,
    storeId: string,
    designId: string,
    versionId: string,
    tolerance: number,
  ) {
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const { buf } = await this.loadVersion(db, storeId, designId, versionId);
      const { png, removedRatio, background } = await removeUniformBackground(buf, tolerance);
      if (removedRatio < 0.01)
        throw new ConflictException('Kenarlarda tek renkli bir arka plan bulunamadı');
      await this.addVersion(db, storeId, designId, png, {
        generator: 'edit',
        operation: 'remove_background',
        parent: versionId,
        params: { tolerance, removedRatio, background },
        userId: ctx.userId,
      });
    });
    return this.get(ctx, storeId, designId);
  }

  /** Fits the version to the Printify print area (exact pixel size, transparent padding, 300 DPI). */
  async preparePrint(
    ctx: AuthContext,
    storeId: string,
    designId: string,
    versionId: string,
    input: { blueprintId: number; printProviderId: number; position: string },
  ) {
    await this.db.asUser(ctx, (db) => assertStoreRole(db, storeId, 'admin'));
    const areas = await this.printify.printAreas(storeId, input.blueprintId, input.printProviderId);
    const area = areas.areas.find((a) => a.position === input.position);
    if (!area)
      throw new BadRequestException(
        `Bu üründe "${input.position}" baskı alanı yok (${areas.areas.map((a) => a.position).join(', ')})`,
      );
    await this.db.asUser(ctx, async (db) => {
      const { buf } = await this.loadVersion(db, storeId, designId, versionId);
      const { png, fit } = await prepareForPrintArea(buf, area);
      await this.addVersion(db, storeId, designId, png, {
        generator: 'edit',
        operation: 'prepare_print',
        parent: versionId,
        fit,
        area: {
          blueprintId: input.blueprintId,
          printProviderId: input.printProviderId,
          position: area.position,
          width: area.width,
          height: area.height,
        },
        userId: ctx.userId,
      });
    });
    return this.get(ctx, storeId, designId);
  }

  async file(ctx: AuthContext, storeId: string, designId: string, versionId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      return (await this.loadVersion(db, storeId, designId, versionId)).buf;
    });
  }

  async requestGeneration(ctx: AuthContext, storeId: string, designId: string, meta: RequestMeta) {
    if (!this.env.ANTHROPIC_API_KEY)
      throw new ServiceUnavailableException('ANTHROPIC_API_KEY tanımlı değil');
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await db.query(
        `select prompt, human_contribution, ip_risk_level from public.designs where id = $1 and store_id = $2`,
        [designId, storeId],
      );
      if (!d.rowCount) throw new NotFoundException('Tasarım bulunamadı');
      if (!d.rows[0].prompt)
        throw new BadRequestException('AI üretimi için tasarım özeti (brief) gerekli');
      if (d.rows[0].ip_risk_level === 'high')
        throw new ConflictException('Özet korumalı ifadeler içeriyor; önce düzeltin');
    });
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.designGenerate, {
      idempotencyKey: `design-generate:${designId}:${Date.now()}`,
      storeId,
      payload: { designId, userId: ctx.userId },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'design.generate.request',
      entityType: 'design',
      entityId: designId,
      meta,
    });
    return { jobId };
  }

  async requestIpReview(ctx: AuthContext, storeId: string, designId: string) {
    if (!this.env.ANTHROPIC_API_KEY)
      throw new ServiceUnavailableException('ANTHROPIC_API_KEY tanımlı değil');
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await db.query(
        `select current_version_id from public.designs where id = $1 and store_id = $2`,
        [designId, storeId],
      );
      if (!d.rowCount) throw new NotFoundException('Tasarım bulunamadı');
      if (!d.rows[0].current_version_id)
        throw new BadRequestException('Önce bir görsel yükleyin veya üretin');
    });
    const jobId = await this.queue.enqueue(QUEUES.sync, JOBS.designIpReview, {
      idempotencyKey: `design-ip:${designId}:${Date.now()}`,
      storeId,
      payload: { designId },
    });
    return { jobId };
  }

  /**
   * Approval rules: human creative direction present, an IP review of the CURRENT
   * artwork exists and is not high risk, and a print-ready version exists.
   */
  async setStatus(
    ctx: AuthContext,
    storeId: string,
    designId: string,
    status: 'approved' | 'rejected' | 'archived' | 'review',
    meta: RequestMeta,
  ) {
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await db.query(
        `select * from public.designs where id = $1 and store_id = $2 for update`,
        [designId, storeId],
      );
      const x = d.rows[0];
      if (!x) throw new NotFoundException('Tasarım bulunamadı');
      if (status === 'approved') {
        if (!x.human_contribution || x.human_contribution.length < 20)
          throw new ConflictException('İnsan yaratıcı katkısı (en az 20 karakter) gerekli');
        if (!x.ip_reviewed_at)
          throw new ConflictException('Güncel görsel için IP incelemesi yapılmadı');
        if (x.ip_risk_level === 'high') throw new ConflictException('Yüksek IP riski: onaylanamaz');
        const pr = await db.query(
          `select 1 from public.design_versions where design_id = $1 and operation = 'prepare_print'`,
          [designId],
        );
        if (!pr.rowCount)
          throw new ConflictException('Baskıya hazır sürüm yok (önce baskı alanına hazırlayın)');
      }
      await db.query(
        `update public.designs set status = $2, approved_by = case when $2 = 'approved' then $3::uuid else null end,
                approved_at = case when $2 = 'approved' then now() else null end where id = $1`,
        [designId, status, ctx.userId],
      );
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: `design.${status}`,
      entityType: 'design',
      entityId: designId,
      meta,
    });
    return this.get(ctx, storeId, designId);
  }

  /**
   * Creates an UNPUBLISHED product in the connected Printify shop from an approved,
   * print-ready design (nothing is sent to Etsy). Mockups are produced by Printify and
   * imported by the next Printify sync.
   */
  async createPrintifyProduct(
    ctx: AuthContext,
    storeId: string,
    designId: string,
    input: {
      title: string;
      description: string;
      variantIds: number[];
      priceUsd: string;
      tags?: string[];
    },
    meta: RequestMeta,
  ) {
    const { design, version, shopId } = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const d = await db.query(`select * from public.designs where id = $1 and store_id = $2`, [
        designId,
        storeId,
      ]);
      if (!d.rowCount) throw new NotFoundException('Tasarım bulunamadı');
      if (d.rows[0].status !== 'approved') throw new ConflictException('Tasarım onaylı değil');
      const v = await db.query(
        `select * from public.design_versions where design_id = $1 and operation = 'prepare_print' order by version desc limit 1`,
        [designId],
      );
      const c = await db.query(
        `select external_account_id from public.connected_accounts where store_id = $1 and platform = 'printify' and status = 'active'`,
        [storeId],
      );
      if (!c.rowCount) throw new ConflictException('Printify bağlantısı aktif değil');
      return {
        design: d.rows[0],
        version: v.rows[0],
        shopId: c.rows[0].external_account_id as string,
      };
    });
    const area = version.print_area as {
      blueprintId: number;
      printProviderId: number;
      position: string;
    };
    const client = this.printify.apiClient(storeId);
    const png = await this.store.get(version.storage_path);
    const signed = await this.store.signedUrl(version.storage_path, 900);
    const upload = signed
      ? await client.uploadImageByUrl(`${designId}-v${version.version}.png`, signed)
      : await client.uploadImageBase64(
          `${designId}-v${version.version}.png`,
          png.toString('base64'),
        );
    const cents = Math.round(Number(input.priceUsd) * 100);
    const product = await client.createProduct(shopId, {
      title: input.title,
      description: input.description,
      tags: input.tags ?? design.tags ?? [],
      blueprint_id: area.blueprintId,
      print_provider_id: area.printProviderId,
      variants: input.variantIds.map((id) => ({ id, price: cents, is_enabled: true })),
      print_areas: [
        {
          variant_ids: input.variantIds,
          placeholders: [
            {
              position: area.position,
              images: [{ id: upload.id, x: 0.5, y: 0.5, scale: 1, angle: 0 }],
            },
          ],
        },
      ],
    });
    await this.db.asService(async (db) => {
      await db.query(
        `insert into public.products (store_id, design_id, title, product_type, status, printify_shop_id, printify_product_id,
                                      printify_blueprint_id, printify_print_provider_id, data_origin)
         values ($1,$2,$3,$4,'draft',$5,$6,$7,$8,'live')
         on conflict (store_id, printify_product_id) where printify_product_id is not null do update set design_id = excluded.design_id`,
        [
          storeId,
          designId,
          input.title,
          design.product_type ?? 'Printify',
          Number(shopId),
          product.id,
          area.blueprintId,
          area.printProviderId,
        ],
      );
      if (design.opportunity_id)
        await db.query(
          `update public.product_opportunities set status = 'launched' where id = $1`,
          [design.opportunity_id],
        );
    });
    await this.queue.enqueue(QUEUES.sync, JOBS.printifySyncStore, {
      idempotencyKey: `printify-sync:${storeId}:design:${product.id}`,
      storeId,
      payload: { reason: 'design-product' },
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'design.printify_product',
      entityType: 'design',
      entityId: designId,
      after: { printifyProductId: product.id, imageId: upload.id },
      meta,
    });
    return {
      printifyProductId: product.id,
      note: 'Ürün Printify’da taslak olarak oluşturuldu; Etsy’ye gönderilmedi. Mockup’lar senkronizasyonla gelir.',
    };
  }
}
