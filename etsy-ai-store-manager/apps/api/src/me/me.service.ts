import { Injectable, NotFoundException } from '@nestjs/common';
import type { MeResponse, UserSettingsUpdate } from '@esm/shared';
import { DatabaseService, type AuthContext } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { updateFromPatch } from '../common/sql.js';

interface Row {
  id: string;
  email: string;
  full_name: string | null;
  locale: string;
  timezone: string;
  ui_language: 'tr' | 'en';
  base_currency: string;
  notify_email: boolean;
  notify_push: boolean;
  notify_daily_report: boolean;
  require_reauth_for_sensitive: boolean;
}

const SETTINGS_COLUMNS: Record<string, string> = {
  uiLanguage: 'ui_language',
  baseCurrency: 'base_currency',
  notifyEmail: 'notify_email',
  notifyPush: 'notify_push',
  notifyDailyReport: 'notify_daily_report',
  requireReauthForSensitive: 'require_reauth_for_sensitive',
};
const PROFILE_COLUMNS: Record<string, string> = { fullName: 'full_name', timezone: 'timezone' };

@Injectable()
export class MeService {
  constructor(
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
  ) {}

  async get(ctx: AuthContext): Promise<MeResponse> {
    const row = await this.db.asUser(ctx, async (db) => {
      const r = await db.query<Row>(
        `select u.id, u.email, u.full_name, u.locale, u.timezone, s.ui_language, s.base_currency,
                s.notify_email, s.notify_push, s.notify_daily_report, s.require_reauth_for_sensitive
           from public.users u join public.user_settings s on s.user_id = u.id
          where u.id = $1`,
        [ctx.userId],
      );
      return r.rows[0];
    });
    if (!row) throw new NotFoundException('Kullanıcı profili bulunamadı');
    return toDto(row);
  }

  async update(
    ctx: AuthContext,
    patch: UserSettingsUpdate,
    meta: RequestMeta,
  ): Promise<MeResponse> {
    const before = await this.get(ctx);
    await this.db.asUser(ctx, async (db) => {
      await updateFromPatch(
        db,
        'public.user_settings',
        'user_id',
        ctx.userId,
        patch,
        SETTINGS_COLUMNS,
      );
      await updateFromPatch(db, 'public.users', 'id', ctx.userId, patch, PROFILE_COLUMNS);
    });
    const after = await this.get(ctx);
    await this.audit.record({
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'user_settings.update',
      entityType: 'user_settings',
      entityId: ctx.userId,
      before,
      after,
      meta,
    });
    return after;
  }
}

function toDto(r: Row): MeResponse {
  return {
    id: r.id,
    email: r.email,
    fullName: r.full_name,
    locale: r.locale,
    timezone: r.timezone,
    settings: {
      uiLanguage: r.ui_language,
      baseCurrency: r.base_currency,
      notifyEmail: r.notify_email,
      notifyPush: r.notify_push,
      notifyDailyReport: r.notify_daily_report,
      requireReauthForSensitive: r.require_reauth_for_sensitive,
    },
  };
}
