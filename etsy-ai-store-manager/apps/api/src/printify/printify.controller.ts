import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  HttpCode,
  Param,
  ParseIntPipe,
  Post,
  Query,
  Req,
} from '@nestjs/common';
import { ApiBearerAuth, ApiExcludeEndpoint, ApiOperation, ApiTags } from '@nestjs/swagger';
import { SkipThrottle } from '@nestjs/throttler';
import type { RawBodyRequest } from '@nestjs/common';
import type { Request } from 'express';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Public } from '../auth/public.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { PrintifyService } from './printify.service.js';

const connectSchema = z.object({ shopId: z.number().int().positive() }).strict();

@ApiTags('printify')
@ApiBearerAuth()
@Controller()
export class PrintifyController {
  constructor(private readonly printify: PrintifyService) {}

  @Get('stores/:storeId/integrations/printify')
  status(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.printify.status(u, storeId);
  }

  @Get('stores/:storeId/integrations/printify/shops')
  @ApiOperation({ summary: 'Token’a bağlı Printify mağazaları (sales_channel ile)' })
  shops(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.printify.listShops(u, storeId);
  }

  @Post('stores/:storeId/integrations/printify/connect')
  @HttpCode(200)
  connect(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Body(new ZodValidationPipe(connectSchema)) body: { shopId: number },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.printify.connect(u, storeId, body.shopId, meta);
  }

  @Post('stores/:storeId/integrations/printify/sync')
  @HttpCode(202)
  sync(@CurrentUser() u: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.printify.requestSync(u, storeId);
  }

  @Delete('stores/:storeId/integrations/printify')
  disconnect(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.printify.disconnect(u, storeId, meta);
  }

  @Get('stores/:storeId/printify/catalog/blueprints')
  @ApiOperation({ summary: 'Printify kataloğu (önbellekli)' })
  blueprints(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('q') q?: string,
  ) {
    return this.printify.searchBlueprints(u, storeId, (q ?? '').slice(0, 80));
  }

  @Get('stores/:storeId/printify/catalog/blueprints/:blueprintId/providers')
  @ApiOperation({ summary: 'Baskı sağlayıcı karşılaştırması: kargo, süre, varyant sayısı' })
  providers(
    @CurrentUser() u: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('blueprintId', ParseIntPipe) blueprintId: number,
    @Query('country') country?: string,
  ) {
    const cc = (country ?? 'US').toUpperCase();
    if (!/^[A-Z]{2}$/.test(cc)) throw new BadRequestException('country ISO-2 olmalı');
    return this.printify.compareProviders(u, storeId, blueprintId, cc);
  }

  /** Printify webhook receiver. Authenticated by HMAC signature (X-Pfy-Signature), not by JWT. */
  @Public()
  @SkipThrottle()
  @Post('integrations/printify/webhooks/:storeId')
  @HttpCode(200)
  @ApiExcludeEndpoint()
  webhook(
    @Param('storeId', UuidPipe) storeId: string,
    @Req() req: RawBodyRequest<Request>,
    @Headers('x-pfy-signature') signature?: string,
  ) {
    return this.printify.receiveWebhook(storeId, req.rawBody, signature);
  }
}
