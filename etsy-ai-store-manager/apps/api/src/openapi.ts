// Writes the OpenAPI document to docs/api/openapi.json without starting the server.
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createApp } from './bootstrap.js';
import { loadEnv } from './config/env.js';

const env = loadEnv({
  ...process.env,
  DATABASE_URL: process.env.DATABASE_URL ?? 'postgres://unused@localhost/unused',
  SUPABASE_URL: process.env.SUPABASE_URL ?? 'http://localhost:54321',
  SUPABASE_JWT_SECRET: process.env.SUPABASE_JWT_SECRET ?? 'openapi-generation-only',
  TOKEN_ENCRYPTION_KEY: process.env.TOKEN_ENCRYPTION_KEY ?? Buffer.alloc(32).toString('base64'),
  SWAGGER_ENABLED: 'true',
  LOG_LEVEL: 'silent',
});
const { app, openApi } = await createApp(env);
const out = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../docs/api/openapi.json',
);
await writeFile(out, JSON.stringify(openApi, null, 2) + '\n');
await app.close();
console.warn(`OpenAPI written to ${out}`);
