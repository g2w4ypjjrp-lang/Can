import { BadRequestException, Body, Controller, Get, Param, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { listingChangeRequestSchema, type ListingChangeRequest } from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { ListingsService } from './listings.service.js';

const STATES = new Set(['draft', 'active', 'inactive', 'expired', 'sold_out', 'removed', 'edit']);

@ApiTags('listings')
@ApiBearerAuth()
@Controller('stores/:storeId/listings')
export class ListingsController {
  constructor(private readonly listings: ListingsService) {}

  @Get()
  @ApiOperation({ summary: 'İçe aktarılmış ilanlar' })
  @ApiQuery({ name: 'state', required: false })
  @ApiQuery({ name: 'q', required: false })
  @ApiQuery({ name: 'limit', required: false })
  @ApiQuery({ name: 'offset', required: false })
  list(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('state') state?: string,
    @Query('q') search?: string,
    @Query('limit') limitRaw?: string,
    @Query('offset') offsetRaw?: string,
  ) {
    if (state && !STATES.has(state)) throw new BadRequestException('Geçersiz state');
    const limit = limitRaw ? Number(limitRaw) : 50;
    const offset = offsetRaw ? Number(offsetRaw) : 0;
    if (!Number.isInteger(limit) || limit < 1 || limit > 200)
      throw new BadRequestException('limit 1-200');
    if (!Number.isInteger(offset) || offset < 0) throw new BadRequestException('offset >= 0');
    return this.listings.list(user, storeId, {
      state,
      search: search?.slice(0, 100) || undefined,
      limit,
      offset,
    });
  }

  @Get(':listingId')
  get(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('listingId', UuidPipe) listingId: string,
  ) {
    return this.listings.get(user, storeId, listingId);
  }

  @Post(':listingId/change-requests')
  @ApiOperation({
    summary: 'İlan değişikliği önerisi oluşturur (onaydan sonra Etsy’ye gönderilir)',
  })
  @ApiBody({ schema: zodToOpenApi(listingChangeRequestSchema) })
  requestChange(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('listingId', UuidPipe) listingId: string,
    @Body(new ZodValidationPipe(listingChangeRequestSchema)) body: ListingChangeRequest,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.listings.requestChange(user, storeId, listingId, body, meta);
  }
}
