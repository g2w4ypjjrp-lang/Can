import {
  Body,
  Controller,
  Get,
  Header,
  HttpCode,
  Param,
  Patch,
  Post,
  StreamableFile,
} from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { DesignsService, type CreateDesignInput } from './designs.service.js';

export const createDesignSchema = z
  .object({
    title: z.string().trim().min(2).max(120),
    brief: z.string().trim().min(10).max(2000).optional(),
    humanContribution: z
      .string()
      .trim()
      .min(20, 'Kendi yaratıcı yönlendirmenizi en az 20 karakterle yazın (Etsy AI politikası)')
      .max(2000),
    productType: z.string().trim().min(2).max(60),
    style: z.string().trim().max(200).optional(),
    tags: z.array(z.string().trim().min(1).max(20)).max(13).optional(),
    opportunityId: z.string().uuid().optional(),
  })
  .strict();
export const uploadSchema = z
  .object({
    fileName: z.string().trim().min(1).max(200),
    contentBase64: z.string().min(16).max(36_000_000),
  })
  .strict();
export const bgSchema = z
  .object({ tolerance: z.number().int().min(1).max(120).default(28) })
  .strict();
export const printSchema = z
  .object({
    blueprintId: z.number().int().positive(),
    printProviderId: z.number().int().positive(),
    position: z.string().trim().min(1).max(40),
  })
  .strict();
export const statusSchema = z
  .object({ status: z.enum(['approved', 'rejected', 'archived', 'review']) })
  .strict();
export const printifyProductSchema = z
  .object({
    title: z.string().trim().min(3).max(140),
    description: z.string().trim().min(10).max(10_000),
    variantIds: z.array(z.number().int().positive()).min(1).max(200),
    priceUsd: z.string().regex(/^\d{1,5}(\.\d{1,2})?$/),
    tags: z.array(z.string().trim().min(1).max(20)).max(13).optional(),
  })
  .strict();

@ApiTags('designs')
@ApiBearerAuth()
@Controller('stores/:storeId/designs')
export class DesignsController {
  constructor(private readonly designs: DesignsService) {}

  @Post()
  @ApiOperation({ summary: 'Tasarım oluştur (insan yaratıcı katkısı zorunlu)' })
  @ApiBody({ schema: zodToOpenApi(createDesignSchema) })
  create(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(createDesignSchema)) b: CreateDesignInput,
    @ReqMeta() m: RequestMeta,
  ) {
    return this.designs.create(u, s, b, m);
  }

  @Get()
  list(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.designs.list(u, s);
  }

  @Get(':designId')
  get(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
  ) {
    return this.designs.get(u, s, d);
  }

  @Post(':designId/upload')
  @ApiOperation({ summary: 'Görsel yükle (PNG/JPG/WEBP/SVG, en fazla 25 MB, base64)' })
  upload(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Body(new ZodValidationPipe(uploadSchema)) b: { fileName: string; contentBase64: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.designs.upload(u, s, d, b, m);
  }

  @Post(':designId/generate')
  @HttpCode(202)
  @ApiOperation({ summary: 'Claude ile özgün SVG tasarım üret (arka plan işi)' })
  generate(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @ReqMeta() m: RequestMeta,
  ) {
    return this.designs.requestGeneration(u, s, d, m);
  }

  @Post(':designId/ip-review')
  @HttpCode(202)
  @ApiOperation({ summary: 'Telif / marka / kişilik hakkı risk incelemesi (görsel analiz)' })
  ipReview(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
  ) {
    return this.designs.requestIpReview(u, s, d);
  }

  @Post(':designId/versions/:versionId/remove-background')
  removeBg(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Param('versionId', UuidPipe) v: string,
    @Body(new ZodValidationPipe(bgSchema)) b: { tolerance: number },
  ) {
    return this.designs.removeBackground(u, s, d, v, b.tolerance);
  }

  @Post(':designId/versions/:versionId/prepare-print')
  @ApiOperation({
    summary: 'Printify baskı alanına hazırla (piksel boyutu, 300 DPI, çözünürlük raporu)',
  })
  preparePrint(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Param('versionId', UuidPipe) v: string,
    @Body(new ZodValidationPipe(printSchema))
    b: { blueprintId: number; printProviderId: number; position: string },
  ) {
    return this.designs.preparePrint(u, s, d, v, b);
  }

  @Get(':designId/versions/:versionId/file')
  @Header('Content-Type', 'image/png')
  @Header('Cache-Control', 'private, max-age=300')
  async file(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Param('versionId', UuidPipe) v: string,
  ) {
    return new StreamableFile(await this.designs.file(u, s, d, v));
  }

  @Patch(':designId/status')
  setStatus(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Body(new ZodValidationPipe(statusSchema))
    b: { status: 'approved' | 'rejected' | 'archived' | 'review' },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.designs.setStatus(u, s, d, b.status, m);
  }

  @Post(':designId/printify-product')
  @ApiOperation({
    summary: 'Onaylı tasarımdan Printify’da taslak ürün oluştur (Etsy’ye gönderilmez)',
  })
  printifyProduct(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('designId', UuidPipe) d: string,
    @Body(new ZodValidationPipe(printifyProductSchema))
    b: {
      title: string;
      description: string;
      variantIds: number[];
      priceUsd: string;
      tags?: string[];
    },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.designs.createPrintifyProduct(u, s, d, b, m);
  }
}
