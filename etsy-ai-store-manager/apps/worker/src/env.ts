import { z } from 'zod';

export const workerEnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  DATABASE_URL: z.string().min(1),
  DATABASE_SSL: z
    .enum(['true', 'false', '1', '0'])
    .default('false')
    .transform((v) => v === 'true' || v === '1'),
  REDIS_URL: z.string().default('redis://localhost:6379'),
  WORKER_CONCURRENCY: z.coerce.number().int().positive().max(50).default(4),
  HEARTBEAT_EVERY_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(5 * 60_000),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),
  /** Same key material as the API (needed to read/refresh OAuth tokens). */
  TOKEN_ENCRYPTION_KEY: z.string().optional(),
  TOKEN_ENCRYPTION_KEY_VERSION: z.coerce.number().int().positive().default(1),
  TOKEN_ENCRYPTION_PREVIOUS_KEYS: z.string().optional(),
  ETSY_KEYSTRING: z.string().optional().default(''),
  ETSY_SHARED_SECRET: z.string().optional().default(''),
  ETSY_REDIRECT_URI: z.string().optional().default(''),
  ETSY_TOKEN_URL: z.string().url().optional(),
  ETSY_API_BASE_URL: z.string().url().optional(),
  /** Claude API (Phase 5+). Never exposed to clients. */
  ANTHROPIC_API_KEY: z.string().optional().default(''),
  ANTHROPIC_BASE_URL: z.string().url().optional(),
  STORAGE_DRIVER: z.enum(['local', 'supabase']).default('local'),
  STORAGE_LOCAL_DIR: z.string().default('./.data/storage'),
  SUPABASE_URL: z.string().url().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().optional().default(''),
  PRINTIFY_API_TOKEN: z.string().optional().default(''),
  PRINTIFY_API_BASE_URL: z.string().url().optional(),
  ETSY_SYNC_EVERY_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(6 * 3600_000),
});
export type WorkerEnv = z.infer<typeof workerEnvSchema>;

export function loadWorkerEnv(source: NodeJS.ProcessEnv = process.env): WorkerEnv {
  const parsed = workerEnvSchema.safeParse(source);
  if (!parsed.success) {
    throw new Error(
      'Geçersiz worker ortam değişkenleri:\n' +
        parsed.error.issues.map((i) => `  - ${i.path.join('.')}: ${i.message}`).join('\n'),
    );
  }
  return parsed.data;
}
