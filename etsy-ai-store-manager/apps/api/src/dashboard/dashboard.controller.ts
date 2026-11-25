import { BadRequestException, Controller, Get, Param, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';
import { DashboardService } from './dashboard.service.js';

@ApiTags('dashboard')
@ApiBearerAuth()
@Controller('stores/:storeId/dashboard')
export class DashboardController {
  constructor(private readonly dashboard: DashboardService) {}

  @Get()
  @ApiOperation({
    summary: 'Genel bakış: ciro, sipariş, reklam, katkı, onaylar (yalnızca gerçek kayıtlar)',
  })
  @ApiQuery({ name: 'days', required: false, description: '1-365, varsayılan 30' })
  overview(
    @CurrentUser() user: AuthContext,
    @Param('storeId', UuidPipe) storeId: string,
    @Query('days') daysRaw?: string,
  ) {
    const days = daysRaw === undefined ? 30 : Number(daysRaw);
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      throw new BadRequestException('days 1 ile 365 arasında tam sayı olmalı');
    }
    return this.dashboard.overview(user, storeId, days);
  }
}
