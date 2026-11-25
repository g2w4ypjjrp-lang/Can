import { pino } from 'pino';
import { loadWorkerEnv } from './env.js';
import { startWorker } from './worker.js';

const env = loadWorkerEnv();
const logger = pino({ level: env.LOG_LEVEL, base: { service: 'worker' } });

const running = await startWorker({
  databaseUrl: env.DATABASE_URL,
  databaseSsl: env.DATABASE_SSL,
  redisUrl: env.REDIS_URL,
  concurrency: env.WORKER_CONCURRENCY,
  heartbeatEveryMs: env.HEARTBEAT_EVERY_MS,
  logger,
});
logger.info({ queues: running.queues.map((q) => q.name) }, 'worker started');

let stopping = false;
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, async () => {
    if (stopping) return;
    stopping = true;
    logger.info({ signal }, 'shutting down worker');
    await running.close();
    process.exit(0);
  });
}
