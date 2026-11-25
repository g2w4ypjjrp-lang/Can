import { DynamicModule, Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { ThrottlerGuard, ThrottlerModule } from '@nestjs/throttler';
import { ENV, type Env } from './config/env.js';
import { DatabaseModule } from './database/database.module.js';
import { AuthModule } from './auth/auth.module.js';
import { AuthGuard } from './auth/auth.guard.js';
import { AuditModule } from './audit/audit.module.js';
import { SecurityModule } from './security/security.module.js';
import { HealthModule } from './health/health.module.js';
import { MeModule } from './me/me.module.js';
import { StoresModule } from './stores/stores.module.js';
import { DashboardModule } from './dashboard/dashboard.module.js';
import { NotificationsModule } from './notifications/notifications.module.js';
import { QueueModule } from './queue/queue.module.js';
import { EtsyModule } from './etsy/etsy.module.js';
import { ListingsModule } from './listings/listings.module.js';
import { ApprovalsModule } from './approvals/approvals.module.js';

@Module({})
export class AppModule {
  static register(env: Env): DynamicModule {
    return {
      module: AppModule,
      global: true,
      imports: [
        ThrottlerModule.forRoot([
          { name: 'default', ttl: 60_000, limit: env.RATE_LIMIT_PER_MINUTE },
        ]),
        DatabaseModule,
        AuthModule,
        AuditModule,
        SecurityModule,
        HealthModule,
        MeModule,
        StoresModule,
        DashboardModule,
        NotificationsModule,
        QueueModule,
        EtsyModule,
        ListingsModule,
        ApprovalsModule,
      ],
      providers: [
        { provide: ENV, useValue: env },
        // Order matters: rate limit first, then authentication.
        { provide: APP_GUARD, useClass: ThrottlerGuard },
        { provide: APP_GUARD, useClass: AuthGuard },
      ],
      exports: [ENV],
    };
  }
}
