import { z } from 'zod';

const bool = z.enum(['true', 'false', '1', '0']).transform((v) => v === 'true' || v === '1');

export const envSchema = z
  .object({
    NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
    API_PORT: z.coerce.number().int().positive().default(4000),
    API_PUBLIC_URL: z.string().url().default('http://localhost:4000'),
    WEB_APP_URL: z.string().url().default('http://localhost:3000'),
    CORS_ORIGINS: z.string().default('http://localhost:3000'),

    DATABASE_URL: z.string().min(1, 'DATABASE_URL gerekli'),
    DATABASE_POOL_MAX: z.coerce.number().int().positive().default(10),
    DATABASE_SSL: bool.default(false),

    SUPABASE_URL: z.string().url(),
    /** Legacy HS256 secret. When empty, tokens are verified with the project's JWKS (asymmetric keys). */
    SUPABASE_JWT_SECRET: z.string().optional().default(''),
    SUPABASE_JWT_AUDIENCE: z.string().default('authenticated'),

    REDIS_URL: z.string().default('redis://localhost:6379'),

    /** base64-encoded 32 byte key for AES-256-GCM token encryption */
    TOKEN_ENCRYPTION_KEY: z
      .string()
      .refine(
        (v) => Buffer.from(v, 'base64').length === 32,
        'TOKEN_ENCRYPTION_KEY 32 baytlık base64 olmalı',
      ),
    TOKEN_ENCRYPTION_KEY_VERSION: z.coerce.number().int().positive().default(1),
    /** Older keys kept for decryption during rotation: "1:base64,2:base64" */
    TOKEN_ENCRYPTION_PREVIOUS_KEYS: z.string().optional(),

    /** Etsy app (Phase 2). Empty = integration disabled; the UI shows what is missing. */
    ETSY_KEYSTRING: z.string().optional().default(''),
    ETSY_SHARED_SECRET: z.string().optional().default(''),
    ETSY_REDIRECT_URI: z.string().optional().default(''),
    /** Overrides for tests only; defaults are the official endpoints. */
    ETSY_CONNECT_URL: z.string().url().optional(),
    ETSY_TOKEN_URL: z.string().url().optional(),
    ETSY_API_BASE_URL: z.string().url().optional(),

    /** Printify personal access token (Phase 3). Server-side only; valid for one year. */
    /** Claude API key (worker uses it; API only reports whether AI is configured). */
    ANTHROPIC_API_KEY: z.string().optional().default(''),

    /** Design file storage: 'local' (dev/tests) or 'supabase' (production, private bucket) */
    STORAGE_DRIVER: z.enum(['local', 'supabase']).default('local'),
    STORAGE_LOCAL_DIR: z.string().default('./.data/storage'),
    /** Service role key: server-side only, used for Storage. Never sent to browsers. */
    SUPABASE_SERVICE_ROLE_KEY: z.string().optional().default(''),

    PRINTIFY_API_TOKEN: z.string().optional().default(''),
    /** openssl rand -hex 20 — used to verify X-Pfy-Signature on webhooks */
    PRINTIFY_WEBHOOK_SECRET: z.string().optional().default(''),
    PRINTIFY_API_BASE_URL: z.string().url().optional(),

    RATE_LIMIT_PER_MINUTE: z.coerce.number().int().positive().default(120),
    SWAGGER_ENABLED: bool.default(true),
    LOG_LEVEL: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .default('info'),
  })
  .superRefine((env, ctx) => {
    if (env.NODE_ENV === 'production') {
      if (
        !env.DATABASE_URL.includes('sslmode') &&
        !env.DATABASE_SSL &&
        !/@(localhost|127\.0\.0\.1|\[::1\]|db|postgres)[:/]/.test(env.DATABASE_URL)
      ) {
        ctx.addIssue({
          code: 'custom',
          path: ['DATABASE_SSL'],
          message: 'Production uzak veritabanı için SSL zorunlu',
        });
      }
    }
  });

export type Env = z.infer<typeof envSchema>;

export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const parsed = envSchema.safeParse(source);
  if (!parsed.success) {
    const lines = parsed.error.issues.map((i) => `  - ${i.path.join('.')}: ${i.message}`);
    throw new Error(`Geçersiz ortam değişkenleri:\n${lines.join('\n')}`);
  }
  return parsed.data;
}

export const ENV = Symbol('ENV');
