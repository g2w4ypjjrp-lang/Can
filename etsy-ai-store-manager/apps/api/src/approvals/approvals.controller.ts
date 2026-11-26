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
import { ApiBearerAuth, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { z } from 'zod';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { ZodValidationPipe } from '../common/zod-validation.pipe.js';
import { ReqMeta, type RequestMeta } from '../common/request-meta.decorator.js';
import { ApprovalsService } from './approvals.service.js';

const decisionSchema = z.object({ note: z.string().trim().max(1000).optional() }).strict();
const STATUSES = new Set([
  'pending',
  'approved',
  'rejected',
  'expired',
  'executing',
  'executed',
  'failed',
  'cancelled',
]);

export const manualSchema = z
  .object({ note: z.string().trim().min(3, 'Ne yaptığınızı kısaca yazın').max(500) })
  .strict();

@ApiTags('approvals')
@ApiBearerAuth()
@Controller('stores/:storeId/approvals')
export class ApprovalsController {
  constructor(private readonly approvals: ApprovalsService) {}

  @Get()
  @ApiQuery({ name: 'status', required: false })
  @ApiOperation({
    summary: 'Onay istekleri (ne / neden / fayda / maliyet / kâr etkisi / API işlemi)',
  })
  list(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('status') status?: string,
  ) {
    if (status && !STATUSES.has(status)) throw new BadRequestException('Geçersiz status');
    return this.approvals.list(user, storeId, status);
  }

  @Post(':approvalId/approve')
  @HttpCode(200)
  @ApiOperation({
    summary: 'Onayla ve yürütmeyi kuyruğa al (hassas işlemlerde yeniden kimlik doğrulama)',
  })
  approve(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('approvalId', UuidPipe) approvalId: string,
    @Body(new ZodValidationPipe(decisionSchema)) body: { note?: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.approvals.decide(user, storeId, approvalId, 'approve', body.note, meta);
  }

  @Post(':approvalId/reject')
  @HttpCode(200)
  reject(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('approvalId', UuidPipe) approvalId: string,
    @Body(new ZodValidationPipe(decisionSchema)) body: { note?: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.approvals.decide(user, storeId, approvalId, 'reject', body.note, meta);
  }

  @Post(':approvalId/confirm-manual')
  @HttpCode(200)
  @ApiOperation({
    summary: 'Platform panelinde elle uygulanan onaylı işlemi tamamlandı olarak işaretle',
  })
  confirmManual(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Param('approvalId', UuidPipe) approvalId: string,
    @Body(new ZodValidationPipe(manualSchema)) body: { note: string },
    @ReqMeta() meta: RequestMeta,
  ) {
    return this.approvals.confirmManual(user, storeId, approvalId, body.note, meta);
  }
}
