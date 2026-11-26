import { Body, Controller, Get, HttpCode, Param, Patch, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { STORE_LANGUAGE_CODES } from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { SeoService, type ContentEdit, type DraftListingRequest } from './seo.service.js';

export const seoRequestSchema = z
  .object({ language: z.enum(STORE_LANGUAGE_CODES).default('en') })
  .strict();
export const contentSchema = z
  .object({
    title: z.string().trim().min(1).max(140),
    description: z.string().trim().min(1).max(20_000),
    tags: z.array(z.string().max(40)).max(20),
    materials: z.array(z.string().trim().min(1).max(45)).max(13).optional(),
  })
  .strict();
export const checkSchema = contentSchema.extend({
  primaryKeyword: z.string().trim().max(80).optional(),
});
export const reasonSchema = z.object({ reason: z.string().trim().min(3).max(500) }).strict();
export const translateSchema = z
  .object({
    languages: z.array(z.enum(STORE_LANGUAGE_CODES)).min(1).max(STORE_LANGUAGE_CODES.length),
  })
  .strict();
export const reviewSchema = z.object({ decision: z.enum(['reviewed', 'rejected']) }).strict();
export const draftListingSchema = z
  .object({
    productId: z.string().uuid().optional(),
    seoDraftId: z.string().uuid().optional(),
    title: z.string().trim().min(1).max(140),
    description: z.string().trim().min(1).max(20_000),
    tags: z.array(z.string().max(40)).max(20).default([]),
    materials: z.array(z.string().trim().min(1).max(45)).max(13).default([]),
    price: z
      .string()
      .regex(/^\d{1,5}(\.\d{1,2})?$/)
      .refine((v) => Number(v) >= 0.2, 'En düşük fiyat 0.20'),
    quantity: z.number().int().min(1).max(999),
    taxonomyId: z.number().int().positive(),
    whoMade: z.enum(['i_did', 'someone_else', 'collective']),
    whenMade: z.enum(['made_to_order', '2020_2026', '2010_2019', '2007_2009', 'before_2007']),
    isSupply: z.boolean().default(false),
    shippingProfileId: z.number().int().positive(),
    returnPolicyId: z.number().int().positive().optional(),
    productionPartnerIds: z.array(z.number().int().positive()).max(10).default([]),
    processingMin: z.number().int().min(1).max(90).optional(),
    processingMax: z.number().int().min(1).max(90).optional(),
    reason: z.string().trim().min(3).max(500),
  })
  .strict()
  .refine((v) => !v.processingMin || !v.processingMax || v.processingMin <= v.processingMax, {
    path: ['processingMax'],
    message: 'En az süre en fazla süreden büyük olamaz',
  });

@ApiTags('seo')
@ApiBearerAuth()
@Controller('stores/:storeId')
export class SeoController {
  constructor(private readonly seo: SeoService) {}

  @Post('listings/:listingId/seo-drafts')
  @HttpCode(202)
  @ApiOperation({ summary: 'Etsy ilanı için AI SEO önerisi (başlık, açıklama, 13 etiket) hazırla' })
  @ApiBody({ schema: zodToOpenApi(seoRequestSchema) })
  draftForListing(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('listingId', UuidPipe) l: string,
    @Body(new ZodValidationPipe(seoRequestSchema)) b: { language: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.requestDraft(u, s, { listingId: l }, b.language, m);
  }

  @Post('products/:productId/seo-drafts')
  @HttpCode(202)
  @ApiOperation({ summary: 'Printify ürünü için AI SEO önerisi hazırla' })
  @ApiBody({ schema: zodToOpenApi(seoRequestSchema) })
  draftForProduct(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('productId', UuidPipe) p: string,
    @Body(new ZodValidationPipe(seoRequestSchema)) b: { language: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.requestDraft(u, s, { productId: p }, b.language, m);
  }

  @Get('seo-drafts')
  listDrafts(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('listingId') listingId?: string,
    @Query('productId') productId?: string,
  ) {
    const uuid = /^[0-9a-f-]{36}$/i;
    return this.seo.listDrafts(u, s, {
      ...(listingId && uuid.test(listingId) ? { listingId } : {}),
      ...(productId && uuid.test(productId) ? { productId } : {}),
    });
  }

  @Post('seo/check')
  @HttpCode(200)
  @ApiOperation({ summary: 'Etsy kural ve spam kontrolü (AI yok)' })
  @ApiBody({ schema: zodToOpenApi(checkSchema) })
  check(
    @Param('storeId', UuidPipe) _s: string,
    @Body(new ZodValidationPipe(checkSchema)) b: ContentEdit & { primaryKeyword?: string },
  ) {
    return this.seo.check(b, b.primaryKeyword);
  }

  @Patch('seo-drafts/:draftId')
  @ApiBody({ schema: zodToOpenApi(contentSchema) })
  editDraft(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('draftId', UuidPipe) d: string,
    @Body(new ZodValidationPipe(contentSchema)) b: ContentEdit,
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.editDraft(u, s, d, b, m);
  }

  @Post('seo-drafts/:draftId/reject')
  @HttpCode(200)
  rejectDraft(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('draftId', UuidPipe) d: string,
  ) {
    return this.seo.rejectDraft(u, s, d);
  }

  @Post('seo-drafts/:draftId/apply')
  @ApiOperation({ summary: 'SEO önerisini uygulamak için onay isteği oluştur' })
  @ApiBody({ schema: zodToOpenApi(reasonSchema) })
  apply(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('draftId', UuidPipe) d: string,
    @Body(new ZodValidationPipe(reasonSchema)) b: { reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.applyDraft(u, s, d, b.reason, m);
  }

  @Post('listings/:listingId/translations')
  @HttpCode(202)
  @ApiOperation({ summary: 'İlanı seçili dillere AI ile yerelleştir (kalite kontrollü)' })
  @ApiBody({ schema: zodToOpenApi(translateSchema) })
  translate(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('listingId', UuidPipe) l: string,
    @Body(new ZodValidationPipe(translateSchema)) b: { languages: string[] },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.requestTranslations(u, s, l, b.languages, m);
  }

  @Get('listings/:listingId/translations')
  translations(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('listingId', UuidPipe) l: string,
  ) {
    return this.seo.listTranslations(u, s, l);
  }

  @Patch('translations/:translationId')
  @ApiBody({ schema: zodToOpenApi(contentSchema) })
  editTranslation(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('translationId', UuidPipe) t: string,
    @Body(new ZodValidationPipe(contentSchema)) b: ContentEdit,
  ) {
    return this.seo.editTranslation(u, s, t, b);
  }

  @Post('translations/:translationId/review')
  @HttpCode(200)
  @ApiBody({ schema: zodToOpenApi(reviewSchema) })
  review(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('translationId', UuidPipe) t: string,
    @Body(new ZodValidationPipe(reviewSchema)) b: { decision: 'reviewed' | 'rejected' },
  ) {
    return this.seo.reviewTranslation(u, s, t, b.decision);
  }

  @Post('translations/:translationId/publish')
  @ApiOperation({ summary: 'Çeviriyi Etsy’ye eklemek için onay isteği oluştur' })
  @ApiBody({ schema: zodToOpenApi(reasonSchema) })
  publishTranslation(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('translationId', UuidPipe) t: string,
    @Body(new ZodValidationPipe(reasonSchema)) b: { reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.publishTranslation(u, s, t, b.reason, m);
  }

  @Get('etsy/listing-options')
  options(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.seo.listingOptions(u, s);
  }

  @Get('etsy/taxonomy')
  @ApiOperation({ summary: 'Etsy satıcı kategorileri (herkese açık veri)' })
  async taxonomy(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('q') q?: string,
  ) {
    await this.seo.listingOptions(u, s); // membership check
    return this.seo.taxonomy(String(q ?? '').slice(0, 60));
  }

  @Post('etsy/draft-listings')
  @ApiOperation({ summary: 'Etsy taslak ilanı için onay isteği (createDraftListing)' })
  @ApiBody({ schema: zodToOpenApi(draftListingSchema) })
  draftListing(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(draftListingSchema)) b: DraftListingRequest,
    @ReqMeta() m: RequestMeta,
  ) {
    return this.seo.requestDraftListing(u, s, b, m);
  }
}
