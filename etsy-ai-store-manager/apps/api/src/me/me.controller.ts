import { Body, Controller, Get, Patch } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiOperation, ApiTags } from '@nestjs/swagger';
import { userSettingsUpdateSchema, type UserSettingsUpdate } from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { zodToOpenApi } from '../common/openapi.js';
import { MeService } from './me.service.js';

@ApiTags('me')
@ApiBearerAuth()
@Controller('me')
export class MeController {
  constructor(private readonly me: MeService) {}

  @Get()
  @ApiOperation({ summary: 'Oturumdaki kullanıcı ve kişisel ayarlar' })
  get(@CurrentUser() user: AuthContext) {
    return this.me.get(user);
  }

  @Patch('settings')
  @ApiOperation({ summary: 'Kişisel ayarları güncelle' })
  @ApiBody({ schema: zodToOpenApi(userSettingsUpdateSchema) })
  update(
    @CurrentUser() user: AuthContext,
    @Body(new ZodValidationPipe(userSettingsUpdateSchema)) body: UserSettingsUpdate,
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.me.update(user, body, meta);
  }
}
