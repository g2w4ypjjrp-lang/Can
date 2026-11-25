import { Controller, Get, HttpCode, NotFoundException, Param, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import type { NotificationDto } from '@esm/shared';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { DatabaseService, type AuthContext } from '../database/database.service.js';
import { UuidPipe } from '../common/uuid.pipe.js';

@ApiTags('notifications')
@ApiBearerAuth()
@Controller('notifications')
export class NotificationsController {
  constructor(private readonly db: DatabaseService) {}

  @Get()
  @ApiOperation({ summary: 'Bildirimlerim (en yeni 100)' })
  @ApiQuery({ name: 'unread', required: false })
  list(
    @CurrentUser() user: AuthContext,
    @Query('unread') unread?: string,
  ): Promise<NotificationDto[]> {
    return this.db.asUser(user, async (db) => {
      const r = await db.query(
        `select id, type, severity, title, body, link, read_at, created_at
           from public.notifications
          where user_id = $1 and ($2::boolean is false or read_at is null)
          order by created_at desc limit 100`,
        [user.userId, unread === 'true'],
      );
      return r.rows.map((n) => ({
        id: n.id,
        type: n.type,
        severity: n.severity,
        title: n.title,
        body: n.body,
        link: n.link,
        readAt: n.read_at,
        createdAt: n.created_at,
      }));
    });
  }

  @Post(':id/read')
  @HttpCode(204)
  async markRead(@CurrentUser() user: AuthContext, @Param('id', UuidPipe) id: string) {
    const count = await this.db.asUser(user, async (db) => {
      const r = await db.query(
        `update public.notifications set read_at = coalesce(read_at, now()) where id = $1`,
        [id],
      );
      return r.rowCount ?? 0;
    });
    if (count === 0) throw new NotFoundException('Bildirim bulunamadı');
  }

  @Post('read-all')
  @HttpCode(204)
  async markAll(@CurrentUser() user: AuthContext) {
    await this.db.asUser(user, (db) =>
      db.query(
        `update public.notifications set read_at = now() where user_id = $1 and read_at is null`,
        [user.userId],
      ),
    );
  }
}
