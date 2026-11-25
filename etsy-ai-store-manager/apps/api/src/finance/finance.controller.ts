import {
  BadRequestException,
  Body,
  Controller,
  Get,
  HttpCode,
  Param,
  Post,
  Query,
} from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { DECIMAL_2_RE, DECIMAL_4_RE } from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { FinanceService, type SimulationInput } from './finance.service.js';

const amount = z
  .string()
  .trim()
  .regex(DECIMAL_4_RE)
  .refine((v) => !v.startsWith('-'), 'Negatif olamaz');
const price = z
  .string()
  .trim()
  .regex(DECIMAL_2_RE)
  .refine((v) => Number(v) > 0, 'Fiyat > 0 olmalı');
const cc = z
  .string()
  .trim()
  .toUpperCase()
  .regex(/^[A-Z]{2}$/);
const cur = z
  .string()
  .trim()
  .toUpperCase()
  .regex(/^[A-Z]{3}$/);

export const simulationSchema = z
  .object({
    unitPrice: price,
    quantity: z.number().int().min(1).max(100).default(1),
    shippingCharged: amount.default('0'),
    discount: amount.optional(),
    salesTax: amount.optional(),
    productionCostPerUnit: amount,
    productionCostCurrency: cur.default('USD'),
    fulfillmentShippingFirst: amount.default('0'),
    fulfillmentShippingAdditional: amount.default('0'),
    fulfillmentShippingCurrency: cur.default('USD'),
    buyerCountry: cc,
    currency: cur.optional(),
    offsiteAds: z.boolean().optional(),
    adCostAllocated: amount.optional(),
    save: z.boolean().optional(),
  })
  .strict();
export const verifySchema = z.object({ note: z.string().trim().max(500).optional() }).strict();
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

@ApiTags('finance')
@ApiBearerAuth()
@Controller('stores/:storeId')
export class FinanceController {
  constructor(private readonly finance: FinanceService) {}

  @Get('finance/fee-rules')
  @ApiOperation({ summary: 'Etsy ücret kuralları (kaynak, matrah, mağaza doğrulaması)' })
  feeRules(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.finance.feeRules(u, storeId);
  }

  @Post('finance/fee-rules/:ruleId/verify')
  @HttpCode(200)
  verify(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('ruleId', UuidPipe) ruleId: string,
    @Body(new ZodValidationPipe(verifySchema)) body: { note?: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.finance.verifyFeeRule(u, storeId, ruleId, body.note, meta);
  }

  @Post('finance/simulate')
  @HttpCode(200)
  @ApiOperation({ summary: 'Kârlılık simülasyonu + hedef katkı için fiyat önerisi' })
  @ApiBody({ schema: zodToOpenApi(simulationSchema) })
  simulate(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Body(new ZodValidationPipe(simulationSchema)) body: SimulationInput,
  ) {
    return this.finance.simulate(u, storeId, body);
  }

  @Get('products/:productId/profitability')
  @ApiOperation({ summary: 'Ürün varyantlarının hedef ülke için katkısı, kararı ve fiyat önerisi' })
  profitability(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('productId', UuidPipe) productId: string,
    @Query('country') country?: string,
  ) {
    const c = (country ?? 'US').toUpperCase();
    if (!/^[A-Z]{2}$/.test(c)) throw new BadRequestException('country ISO-2');
    return this.finance.productProfitability(u, storeId, productId, c);
  }

  @Post('products/:productId/price-recommendations')
  createRecommendations(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('productId', UuidPipe) productId: string,
    @Query('country') country: string | undefined,
    @ReqMeta() meta: RequestMeta,
  ) {
    const c = (country ?? 'US').toUpperCase();
    if (!/^[A-Z]{2}$/.test(c)) throw new BadRequestException('country ISO-2');
    return this.finance.createPriceRecommendations(u, storeId, productId, c, meta);
  }

  @Post('products/:productId/price-change-requests')
  @ApiOperation({ summary: 'Önerilen fiyatlar için onay isteği (Printify varyant fiyatı → Etsy)' })
  priceChange(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('productId', UuidPipe) productId: string,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.finance.requestPriceChange(u, storeId, productId, meta);
  }

  @Get('finance/summary')
  @ApiOperation({
    summary: 'Dönem kâr/zarar: katkı (reklam öncesi), gerçek reklam harcaması, vergi tahmini',
  })
  summary(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
  ) {
    const today = new Date().toISOString().slice(0, 10);
    const f = from ?? `${today.slice(0, 7)}-01`;
    const t = to ?? today;
    if (!DATE_RE.test(f) || !DATE_RE.test(t) || f > t)
      throw new BadRequestException('from/to YYYY-MM-DD, from <= to');
    return this.finance.summary(u, storeId, f, t);
  }

  @Post('finance/recompute')
  @HttpCode(202)
  recompute(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.finance.requestRecompute(u, storeId);
  }
}
