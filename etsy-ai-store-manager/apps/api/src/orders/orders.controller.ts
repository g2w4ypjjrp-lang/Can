import { Body, Controller, Get, HttpCode, Param, Post, Put, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { OrdersService } from './orders.service.js';

const reason = z.string().trim().min(3).max(500);
export const trackingSchema = z
  .object({
    trackingCode: z
      .string()
      .trim()
      .regex(/^[A-Za-z0-9-]{5,40}$/, 'Takip numarası 5-40 harf/rakam'),
    carrierName: z.string().trim().min(2).max(60),
    noteToBuyer: z.string().trim().max(500).optional(),
    reason,
  })
  .strict();
export const refundSchema = z
  .object({
    amount: z
      .string()
      .regex(/^\d{1,6}(\.\d{1,2})?$/)
      .refine((v) => Number(v) > 0, 'Tutar sıfırdan büyük olmalı'),
    reason,
  })
  .strict();
export const reasonSchema = z.object({ reason }).strict();
export const messageSchema = z
  .object({
    body: z.string().trim().min(2).max(10_000),
    orderId: z.string().uuid().optional(),
    receiptId: z
      .string()
      .regex(/^\d{1,20}$/)
      .optional(),
  })
  .strict();
export const sendSchema = z
  .object({ text: z.string().trim().min(2).max(10_000), reason: reason.default('Müşteriye yanıt') })
  .strict();
export const slaSchema = z
  .object({
    processingDaysMax: z.number().int().min(1).max(60),
    transitDaysMax: z.number().int().min(1).max(90),
  })
  .strict();

const FILTERS = ['delayed', 'unshipped', 'issues'] as const;
const STATUSES = [
  'open',
  'paid',
  'in_production',
  'shipped',
  'delivered',
  'cancelled',
  'refunded',
  'partially_refunded',
];

@ApiTags('orders')
@ApiBearerAuth()
@Controller('stores/:storeId')
export class OrdersController {
  constructor(private readonly orders: OrdersService) {}

  @Get('orders')
  list(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('status') status?: string,
    @Query('filter') filter?: string,
    @Query('search') search?: string,
    @Query('page') page?: string,
  ) {
    const p = Math.max(1, Number(page) || 1);
    return this.orders.list(u, s, {
      ...(status && STATUSES.includes(status) ? { status } : {}),
      ...(filter && (FILTERS as readonly string[]).includes(filter)
        ? { filter: filter as (typeof FILTERS)[number] }
        : {}),
      ...(search ? { search: search.slice(0, 20) } : {}),
      limit: 50,
      offset: (p - 1) * 50,
    });
  }

  @Get('orders/:orderId')
  get(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('orderId', UuidPipe) o: string,
  ) {
    return this.orders.get(u, s, o);
  }

  @Post('orders/:orderId/tracking')
  @ApiOperation({
    summary: 'Takip numarası için onay isteği (createReceiptShipment; Printify siparişleri hariç)',
  })
  @ApiBody({ schema: zodToOpenApi(trackingSchema) })
  tracking(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('orderId', UuidPipe) o: string,
    @Body(new ZodValidationPipe(trackingSchema))
    b: { trackingCode: string; carrierName: string; noteToBuyer?: string; reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.orders.requestTracking(u, s, o, b, m);
  }

  @Post('orders/:orderId/refunds')
  @ApiOperation({ summary: 'İade için onay isteği (kâr etkisiyle; Etsy’de manuel uygulanır)' })
  @ApiBody({ schema: zodToOpenApi(refundSchema) })
  refund(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('orderId', UuidPipe) o: string,
    @Body(new ZodValidationPipe(refundSchema)) b: { amount: string; reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.orders.requestRefund(u, s, o, b, m);
  }

  @Post('orders/:orderId/cancel')
  @ApiBody({ schema: zodToOpenApi(reasonSchema) })
  cancel(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('orderId', UuidPipe) o: string,
    @Body(new ZodValidationPipe(reasonSchema)) b: { reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.orders.requestCancel(u, s, o, b.reason, m);
  }

  @Put('orders-settings/sla')
  @ApiBody({ schema: zodToOpenApi(slaSchema) })
  sla(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(slaSchema))
    b: { processingDaysMax: number; transitDaysMax: number },
  ) {
    return this.orders.setSla(u, s, b);
  }

  @Get('customers')
  customers(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) s: string) {
    return this.orders.customers(u, s);
  }

  @Get('messages')
  messages(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('status') status?: string,
  ) {
    const ok = [
      'new',
      'classifying',
      'draft_ready',
      'awaiting_approval',
      'sent',
      'closed',
      'failed',
    ];
    return this.orders.messages(u, s, status && ok.includes(status) ? status : undefined);
  }

  @Post('messages')
  @ApiOperation({
    summary: 'Etsy Mesajlar’dan yapıştırılan müşteri mesajını kaydet ve AI ile sınıflandır',
  })
  @ApiBody({ schema: zodToOpenApi(messageSchema) })
  addMessage(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Body(new ZodValidationPipe(messageSchema))
    b: { body: string; orderId?: string; receiptId?: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.orders.addMessage(u, s, b, m);
  }

  @Post('messages/:messageId/triage')
  @HttpCode(202)
  retriage(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('messageId', UuidPipe) id: string,
  ) {
    return this.orders.retriage(u, s, id);
  }

  @Post('messages/:messageId/send')
  @ApiOperation({ summary: 'Yanıt metni için onay isteği (Etsy’de elle gönderilir)' })
  @ApiBody({ schema: zodToOpenApi(sendSchema) })
  send(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('messageId', UuidPipe) id: string,
    @Body(new ZodValidationPipe(sendSchema)) b: { text: string; reason: string },
    @ReqMeta() m: RequestMeta,
  ) {
    return this.orders.requestSend(u, s, id, b, m);
  }

  @Post('messages/:messageId/close')
  @HttpCode(200)
  close(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Param('messageId', UuidPipe) id: string,
  ) {
    return this.orders.closeMessage(u, s, id);
  }

  @Get('reviews')
  reviews(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) s: string,
    @Query('maxRating') maxRating?: string,
  ) {
    const r = Number(maxRating);
    return this.orders.reviews(u, s, r >= 1 && r <= 5 ? r : undefined);
  }
}
