import { Body, Controller, Get, Param, Patch, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import {
  profitRulesUpdateSchema,
  storeCreateSchema,
  storeSettingsUpdateSchema,
  type ProfitRulesUpdate,
  type StoreCreate,
  type StoreSettingsUpdate,
} from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { StoresService } from './stores.service.js';

@ApiTags('stores')
@ApiBearerAuth()
@Controller('stores')
export class StoresController {
  constructor(private readonly stores: StoresService) {}

  @Get()
  @ApiOperation({ summary: 'Erişimim olan mağazalar' })
  list(@CurrentUser() user: AuthContext) {
    return this.stores.list(user);
  }

  @Post()
  @ApiOperation({
    summary: 'Mağaza kaydı oluştur',
    description:
      'Etsy bağlantısı FAZ 2 OAuth akışıyla yapılır; bu kayıt o zamana kadar "not_connected" kalır.',
  })
  @ApiBody({ schema: zodToOpenApi(storeCreateSchema) })
  create(
    @CurrentUser() user: AuthContext,
    @Body(new ZodValidationPipe(storeCreateSchema)) body: StoreCreate,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.stores.create(user, body, meta);
  }

  @Get(':storeId')
  get(@CurrentUser() user: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.stores.get(user, storeId);
  }

  @Get(':storeId/settings')
  @ApiOperation({ summary: 'Mağaza ayarları (strateji, diller, reklam bütçe sınırı)' })
  getSettings(@CurrentUser() user: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.stores.getSettings(user, storeId);
  }

  @Patch(':storeId/settings')
  @ApiBody({ schema: zodToOpenApi(storeSettingsUpdateSchema) })
  updateSettings(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Body(new ZodValidationPipe(storeSettingsUpdateSchema)) body: StoreSettingsUpdate,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.stores.updateSettings(user, storeId, body, meta);
  }

  @Get(':storeId/profit-rules')
  @ApiOperation({ summary: 'Katkı eşikleri ve kâr politikası' })
  getProfitRules(@CurrentUser() user: AuthContext, @Param('storeId', UuidPipe) storeId: string) {
    return this.stores.getProfitRules(user, storeId);
  }

  @Patch(':storeId/profit-rules')
  @ApiBody({ schema: zodToOpenApi(profitRulesUpdateSchema) })
  updateProfitRules(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Body(new ZodValidationPipe(profitRulesUpdateSchema)) body: ProfitRulesUpdate,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.stores.updateProfitRules(user, storeId, body, meta);
  }
}
