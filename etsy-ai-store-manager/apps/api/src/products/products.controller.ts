import { BadRequestException, Body, Controller, Get, Param, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { ProductsService } from './products.service.js';

const STATUSES = new Set(['idea', 'draft', 'ready', 'published', 'archived']);
export const publishSchema = z.object({ reason: z.string().trim().min(3).max(1000) }).strict();

@ApiTags('products')
@ApiBearerAuth()
@Controller('stores/:storeId/products')
export class ProductsController {
  constructor(private readonly products: ProductsService) {}

  @Get()
  @ApiOperation({ summary: 'Ürünler, varyant sayısı, fiyat ve güncel üretim maliyeti aralığı' })
  list(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('status') status?: string,
    @Query('q') q?: string,
    @Query('limit') limitRaw?: string,
    @Query('offset') offsetRaw?: string,
  ) {
    if (status && !STATUSES.has(status)) throw new BadRequestException('Geçersiz status');
    const limit = limitRaw ? Number(limitRaw) : 50;
    const offset = offsetRaw ? Number(offsetRaw) : 0;
    if (
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 200 ||
      !Number.isInteger(offset) ||
      offset < 0
    ) {
      throw new BadRequestException('limit 1-200, offset >= 0');
    }
    return this.products.list(u, storeId, {
      status,
      search: q?.slice(0, 100) || undefined,
      limit,
      offset,
    });
  }

  @Get(':productId')
  get(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('productId', UuidPipe) productId: string,
  ) {
    return this.products.get(u, storeId, productId);
  }

  @Post(':productId/publish-requests')
  @ApiOperation({ summary: 'Printify → Etsy yayın isteği (onay gerektirir)' })
  publish(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('productId', UuidPipe) productId: string,
    @Body(new ZodValidationPipe(publishSchema)) body: { reason: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.products.requestPublish(u, storeId, productId, body.reason, meta);
  }
}
