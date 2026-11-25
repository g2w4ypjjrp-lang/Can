import {
  BadRequestException,
  Body,
  Controller,
  Get,
  Param,
  Patch,
  Post,
  Query,
} from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { MarketService, type ResearchRequest } from './market.service.js';

export const researchSchema = z
  .object({
    query: z.string().trim().min(2).max(80),
    buyerCountry: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{2}$/)
      .optional(),
    keywords: z.array(z.string().trim().min(2).max(60)).max(4).optional(),
    useWebSearch: z.boolean().optional(),
  })
  .strict();
export const decisionSchema = z
  .object({
    status: z.enum(['new', 'shortlisted', 'rejected']),
    reason: z.string().trim().max(500).optional(),
  })
  .strict();

@ApiTags('market')
@ApiBearerAuth()
@Controller('stores/:storeId')
export class MarketController {
  constructor(private readonly market: MarketService) {}

  @Post('market-research')
  @ApiOperation({
    summary:
      'Pazar araştırması başlat (Etsy pazar verisi + isteğe bağlı web araştırması + AI analizi)',
  })
  @ApiBody({ schema: zodToOpenApi(researchSchema) })
  create(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Body(new ZodValidationPipe(researchSchema)) body: ResearchRequest,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.market.create(u, storeId, body, meta);
  }

  @Get('market-research')
  list(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.market.list(u, storeId);
  }

  @Get('market-research/:researchId')
  get(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('researchId', UuidPipe) id: string,
  ) {
    return this.market.get(u, storeId, id);
  }

  @Get('opportunities')
  @ApiOperation({
    summary: 'Ürün fırsatları (puan, tahmini katkı, güven, kaynaklı talep sinyalleri)',
  })
  opportunities(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('status') status?: string,
    @Query('minScore') minScore?: string,
  ) {
    if (status && !['new', 'shortlisted', 'rejected', 'in_design', 'launched'].includes(status)) {
      throw new BadRequestException('Geçersiz status');
    }
    const ms = minScore ? Number(minScore) : 0;
    if (!Number.isFinite(ms) || ms < 0 || ms > 100) throw new BadRequestException('minScore 0-100');
    return this.market.listOpportunities(u, storeId, { status, minScore: ms });
  }

  @Patch('opportunities/:opportunityId')
  decide(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('opportunityId', UuidPipe) id: string,
    @Body(new ZodValidationPipe(decisionSchema))
    body: { status: 'new' | 'shortlisted' | 'rejected'; reason?: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.market.decide(u, storeId, id, body.status, body.reason, meta);
  }
}
