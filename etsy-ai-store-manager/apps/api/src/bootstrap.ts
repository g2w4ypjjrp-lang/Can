import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { DocumentBuilder, SwaggerModule, type OpenAPIObject } from '@nestjs/swagger';
import helmet from 'helmet';
import { pinoHttp } from 'pino-http';
import { randomUUID } from 'node:crypto';
import type { Logger } from 'pino';
import { AppModule } from './app.module.js';
import type { Env } from './config/env.js';
import { AllExceptionsFilter } from './common/http-exception.filter.js';
import { createRootLogger, PinoNestLogger } from './common/logger.js';

export const API_PREFIX = 'api/v1';

export interface CreatedApp {
  app: NestExpressApplication;
  logger: Logger;
  openApi: OpenAPIObject | null;
}

export async function createApp(env: Env): Promise<CreatedApp> {
  const logger = createRootLogger(env.LOG_LEVEL);
  const app = await NestFactory.create<NestExpressApplication>(AppModule.register(env), {
    logger: new PinoNestLogger(logger),
    bodyParser: true,
    rawBody: true, // needed to verify webhook signatures over the exact bytes
  });

  app.set('trust proxy', 1); // behind Nginx
  app.disable('x-powered-by');
  app.useBodyParser('json', { limit: '1mb' });
  app.use(
    pinoHttp({
      logger,
      genReqId: (req, res) => {
        const incoming = req.headers['x-request-id'];
        const id =
          typeof incoming === 'string' && /^[\w-]{8,64}$/.test(incoming) ? incoming : randomUUID();
        res.setHeader('x-request-id', id);
        return id;
      },
      autoLogging: { ignore: (req) => req.url?.startsWith('/api/v1/health') ?? false },
    }),
  );
  app.use(helmet());
  app.enableCors({
    origin: env.CORS_ORIGINS.split(',')
      .map((o) => o.trim())
      .filter(Boolean),
    credentials: true,
    methods: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
    allowedHeaders: ['Authorization', 'Content-Type', 'X-Request-Id', 'Idempotency-Key'],
  });
  app.setGlobalPrefix(API_PREFIX);
  app.useGlobalFilters(new AllExceptionsFilter(logger));
  app.enableShutdownHooks();

  let openApi: OpenAPIObject | null = null;
  if (env.SWAGGER_ENABLED) {
    const config = new DocumentBuilder()
      .setTitle('Etsy AI Store Manager API')
      .setDescription(
        'Etsy + Printify mağaza yönetimi API. Kimlik doğrulama: Supabase Auth erişim belirteci (Bearer).',
      )
      .setVersion('0.1.0')
      .addBearerAuth()
      .build();
    openApi = SwaggerModule.createDocument(app, config);
    SwaggerModule.setup('docs', app, openApi, { jsonDocumentUrl: 'docs/openapi.json' });
  }
  return { app, logger, openApi };
}
