import { Body, Controller, Get, HttpCode, Param, Post, Put, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { AD_PLATFORMS, AdsService, type AdPlatform, type MetricRow } from './ads.service.js';

const money = z.string().regex(/^\d{1,8}(\.\d{1,2})?$/, 'Tutar biçimi: 12.50');
const currency = z.string().regex(/^[A-Z]{3}$/);

export const policySchema = z
  .object({
    dailyCap: money,
    monthlyCap: money.nullable().optional(),
    currency: currency.default('USD'),
    minClicksForDecision: z.number().int().min(10).max(10000).default(100),
  })
  .strict();
export const accountSchema = z
  .object({
    platform: z.enum(AD_PLATFORMS),
    externalAccountId: z.string().trim().min(1).max(80),
    name: z.string().trim().min(1).max(120),
    currency: currency.default('USD'),
  })
  .strict();
export const metaConnectSchema = z
  .object({
    adAccountId: z
      .string()
      .trim()
      .regex(/^(act_)?\d{5,20}$/, 'Reklam hesabı kimliği (act_123… veya 123…)')
      .transform((v) => v.replace(/^act_/, '')),
    accessToken: z.string().trim().min(20).max(1000),
  })
  .strict();
export const campaignSchema = z
  .object({
    adAccountId: z.string().uuid(),
    name: z.string().trim().min(1).max(200),
    objective: z.string().trim().max(60).optional(),
    dailyBudget: money.optional(),
  })
  .strict();
export const metricsSchema = z
  .object({
    adAccountId: z.string().uuid(),
    rows: z
      .array(
        z
          .object({
            date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
            campaign: z.string().trim().min(1).max(200),
            impressions: z.number().int().min(0).default(0),
            clicks: z.number().int().min(0).default(0),
            spend: money,
            orders: z
              .string()
              .regex(/^\d{1,8}(\.\d{1,2})?$/)
              .default('0'),
            revenue: money.default('0'),
          })
          .strict(),
      )
      .min(1)
      .max(5000),
  })
  .strict();
export const proposalSchema = z
  .object({ totalDailyBudget: money.optional(), days: z.number().int().min(7).max(90).default(30) })
  .strict();
export const reasonSchema = z.object({ reason: z.string().trim().min(3).max(500) }).strict();
export const ledgerMappingSchema = z
  .object({ types: z.array(z.string().trim().min(1).max(80)).max(20) })
  .strict();

@ApiTags('ads')
@ApiBearerAuth()
@Controller('stores/:storeId/ads')
export class AdsController {
  constructor(private readonly ads: AdsService) {}

  @Get('policy')
  policy(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.ads.getPolicy(u, s);
  }

  @Put('policy')
  @ApiOperation({ summary: 'Günlük / aylık reklam bütçesi sınırı (kullanıcı belirler)' })
  @ApiBody({ schema: zodToOpenApi(policySchema) })
  setPolicy(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(policySchema))
    b: {
      dailyCap: string;
      monthlyCap?: string | null;
      currency: string;
      minClicksForDecision: number;
    },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.ads.setPolicy(u, s, b, m);
  }

  @Get('accounts')
  accounts(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.ads.listAccounts(u, s);
  }

  @Post('accounts')
  @ApiBody({ schema: zodToOpenApi(accountSchema) })
  createAccount(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(accountSchema))
    b: { platform: AdPlatform; externalAccountId: string; name: string; currency: string },
  ) {
    return this.ads.createAccount(u, s, b);
  }

  @Post('meta/connect')
  @ApiOperation({
    summary:
      'Meta reklam hesabını salt-okuma raporlama için bağla (ads_read jetonu şifreli saklanır)',
  })
  @ApiBody({ schema: zodToOpenApi(metaConnectSchema) })
  connectMeta(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(metaConnectSchema)) b: { adAccountId: string; accessToken: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.ads.connectMeta(u, s, b, m);
  }

  @Post('sync')
  @HttpCode(202)
  sync(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.ads.requestSync(u, s);
  }

  @Post('campaigns')
  @ApiOperation({ summary: 'Var olan bir kampanyayı takibe ekle (başlatma onaylı manuel adımdır)' })
  @ApiBody({ schema: zodToOpenApi(campaignSchema) })
  createCampaign(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(campaignSchema))
    b: { adAccountId: string; name: string; objective?: string; dailyBudget?: string },
  ) {
    return this.ads.createCampaign(u, s, b);
  }

  @Post('metrics/import')
  @ApiOperation({ summary: 'Günlük kampanya raporu içe aktar (CSV / elle)' })
  @ApiBody({ schema: zodToOpenApi(metricsSchema) })
  importMetrics(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(metricsSchema)) b: { adAccountId: string; rows: MetricRow[] },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.ads.importMetrics(u, s, b.adAccountId, b.rows, m);
  }

  @Get('overview')
  @ApiOperation({ summary: 'ROAS, başa baş / hedef ROAS, kampanya kararları, bütçe sınırı durumu' })
  overview(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('days') days?: string,
  ) {
    const d = Math.min(90, Math.max(7, Number(days) || 30));
    return this.ads.overview(u, s, d);
  }

  @Get('proposals')
  proposals(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.ads.listProposals(u, s);
  }

  @Post('proposals')
  @ApiOperation({ summary: 'Sınır içinde bütçe dağıtım önerisi oluştur (hiçbir şey değişmez)' })
  @ApiBody({ schema: zodToOpenApi(proposalSchema) })
  createProposal(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(proposalSchema)) b: { totalDailyBudget?: string; days: number },
  ) {
    return this.ads.createProposal(u, s, b);
  }

  @Post('proposals/:proposalId/submit')
  @ApiOperation({ summary: 'Bütçe dağıtımı için onay isteği' })
  @ApiBody({ schema: zodToOpenApi(reasonSchema) })
  submit(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('proposalId', UuidPipe) p: string,
    @Body(new ZodValidationPipe(reasonSchema)) b: { reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.ads.submitProposal(u, s, p, b.reason, m);
  }

  @Get('etsy-ledger/types')
  @ApiOperation({ summary: 'Etsy ödeme defterindeki kayıt türleri (Etsy Ads eşlemesi için)' })
  ledgerTypes(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.ads.ledgerTypes(u, s);
  }

  @Put('etsy-ledger/mapping')
  @ApiBody({ schema: zodToOpenApi(ledgerMappingSchema) })
  ledgerMapping(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(ledgerMappingSchema)) b: { types: string[] },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.ads.setLedgerMapping(u, s, b.types, m);
  }
}
