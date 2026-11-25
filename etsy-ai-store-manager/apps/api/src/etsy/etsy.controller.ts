import { Controller, Delete, Get, HttpCode, Param, Post, Query, Res } from '@nestjs/common';
import { ApiBearerAuth, ApiExcludeEndpoint, ApiOperation, ApiTags } from '@nestjs/swagger';
import type { Response } from 'express';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Public } from '../auth/public.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { EtsyConnectionService } from './etsy-connection.service.js';

@ApiTags('etsy')
@ApiBearerAuth()
@Controller()
export class EtsyController {
  constructor(private readonly etsy: EtsyConnectionService) {}

  @Get('stores/:storeId/integrations/etsy')
  @ApiOperation({ summary: 'Etsy bağlantı durumu, sayılar ve API ile yapılamayan işlemler' })
  status(@CurrentUser() user: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.etsy.status(user, storeId);
  }

  @Post('stores/:storeId/integrations/etsy/connect')
  @HttpCode(200)
  @ApiOperation({ summary: 'OAuth 2.0 + PKCE onay URL’si üretir (yalnızca mağaza sahibi)' })
  connect(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.etsy.startConnect(user, storeId, meta);
  }

  @Post('stores/:storeId/integrations/etsy/sync')
  @HttpCode(202)
  @ApiOperation({ summary: 'Mağaza, ilan ve sipariş içe aktarmayı kuyruğa alır' })
  sync(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.etsy.requestSync(user, storeId, meta);
  }

  @Delete('stores/:storeId/integrations/etsy')
  @ApiOperation({ summary: 'Bağlantıyı keser, belirteçleri siler (veriler korunur)' })
  disconnect(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.etsy.disconnect(user, storeId, meta);
  }

  /** Registered Etsy redirect URI. Authenticated by the single-use OAuth state, not by a JWT. */
  @Public()
  @Get('integrations/etsy/callback')
  @ApiExcludeEndpoint()
  async callback(
    @Query() q: { code?: string; state?: string; error?: string; error_description?: string },
    @ReqMeta() meta: RequestMeta,
    @Res() res: Response,
  ) {
    const target = await this.etsy.handleCallback(q, meta);
    res.redirect(302, target);
  }
}
