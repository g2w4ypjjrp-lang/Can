import { createApp } from './bootstrap.js';
import { loadEnv } from './config/env.js';

async function main() {
  const env = loadEnv();
  const { app, logger } = await createApp(env);
  await app.listen(env.API_PORT, '0.0.0.0');
  logger.info(
    { port: env.API_PORT, swagger: env.SWAGGER_ENABLED ? '/docs' : 'disabled' },
    'API started',
  );
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
