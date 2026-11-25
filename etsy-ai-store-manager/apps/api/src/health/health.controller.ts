import { Controller, Get, Inject, ServiceUnavailableException } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { SkipThrottle } from '@nestjs/throttler';
import { Redis } from 'ioredis';
import { Public } from '../auth/public.decorator.js';
import { DatabaseService } from '../database/database.service.js';
import { ENV, type Env } from '../config/env.js';

@ApiTags('health')
@Controller('health')
@Public()
@SkipThrottle()
export class HealthController {
  constructor(
    private readonly db: DatabaseService,
    @Inject(ENV) private readonly env: Env,
  ) {}

  @Get()
  @ApiOperation({ summary: 'Liveness' })
  live() {
    return { status: 'ok', time: new Date().toISOString() };
  }

  @Get('ready')
  @ApiOperation({ summary: 'Readiness: veritabanı ve Redis bağlantısı' })
  async ready() {
    const checks: Record<string, 'ok' | 'fail'> = {};
    try {
      checks.database = (await this.db.ping()) ? 'ok' : 'fail';
    } catch {
      checks.database = 'fail';
    }
    const redis = new Redis(this.env.REDIS_URL, {
      lazyConnect: true,
      maxRetriesPerRequest: 0,
      connectTimeout: 2000,
    });
    try {
      await redis.connect();
      checks.redis = (await redis.ping()) === 'PONG' ? 'ok' : 'fail';
    } catch {
      checks.redis = 'fail';
    } finally {
      redis.disconnect();
    }
    const ok = Object.values(checks).every((v) => v === 'ok');
    if (!ok) throw new ServiceUnavailableException({ message: 'not ready', details: checks });
    return { status: 'ready', checks };
  }
}
