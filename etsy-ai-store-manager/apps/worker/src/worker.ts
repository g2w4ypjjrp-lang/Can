import { Queue, Worker, type ConnectionOptions, type Job } from 'bullmq';
import pg from 'pg';
import type { Logger } from 'pino';
import { JOBS, QUEUES, type JobEnvelope } from '@esm/shared';
import { JOB_HANDLERS } from './jobs/index.js';
import { runIdempotent } from './idempotency.js';
import type { IntegrationDeps } from './etsy/deps.js';

const NO_DEPS: IntegrationDeps = { cipher: null, etsy: null, fetchImpl: fetch };

export type Enqueue = (
  jobName: string,
  storeId: string,
  idempotencyKey: string,
  payload?: Record<string, unknown>,
) => Promise<void>;

export const DEFAULT_JOB_OPTIONS = {
  attempts: 3,
  backoff: { type: 'exponential' as const, delay: 5_000 },
  removeOnComplete: { age: 7 * 24 * 3600, count: 1000 },
  removeOnFail: { age: 30 * 24 * 3600 },
};

export function redisConnection(url: string): ConnectionOptions {
  const u = new URL(url);
  return {
    host: u.hostname,
    port: Number(u.port || 6379),
    username: u.username || undefined,
    password: u.password ? decodeURIComponent(u.password) : undefined,
    db: u.pathname.length > 1 ? Number(u.pathname.slice(1)) : 0,
    tls: u.protocol === 'rediss:' ? {} : undefined,
    maxRetriesPerRequest: null,
  };
}

/**
 * The idempotency key comes from the job envelope; for scheduler-produced jobs
 * (no envelope) it is derived from the job name + scheduled timestamp, so a
 * re-delivered occurrence is never executed twice.
 */
export function idempotencyKeyFor(job: Job): string {
  const data = job.data as Partial<JobEnvelope> | undefined;
  if (data?.idempotencyKey) return data.idempotencyKey;
  // Scheduler jobs get a deterministic id per occurrence: "repeat:<scheduler>:<millis>"
  return `${job.name}:${job.id}`;
}

export function createProcessor(
  pool: pg.Pool,
  logger: Logger,
  deps: IntegrationDeps = NO_DEPS,
  enqueue: Enqueue = async () => {
    throw new Error('enqueue not available');
  },
) {
  return async (job: Job) => {
    const handler = JOB_HANDLERS[job.name];
    if (!handler) throw new Error(`Unknown job ${job.name}`);
    const envelope = (job.data ?? {}) as Partial<JobEnvelope>;
    const key = idempotencyKeyFor(job);
    const outcome = await runIdempotent(
      pool,
      {
        idempotencyKey: key,
        jobName: job.name,
        queue: job.queueName,
        storeId: envelope.storeId ?? null,
        payload: envelope.payload ?? {},
        attempt: job.attemptsMade + 1,
        maxAttempts: job.opts.attempts ?? 1,
        schedule: job.repeatJobKey ? 'repeat' : null,
      },
      () =>
        handler(
          {
            pool,
            now: new Date(),
            deps,
            storeId: envelope.storeId ?? null,
            attempt: { current: job.attemptsMade + 1, max: job.opts.attempts ?? 1 },
            enqueue,
          },
          envelope.payload ?? {},
        ),
    );
    logger.info({ job: job.name, id: job.id, key, outcome: outcome.status }, 'job processed');
    return outcome;
  };
}

export interface RunningWorker {
  close(): Promise<void>;
  queues: Queue[];
  workers: Worker[];
}

export async function startWorker(opts: {
  databaseUrl: string;
  databaseSsl?: boolean;
  redisUrl: string;
  concurrency: number;
  heartbeatEveryMs: number;
  logger: Logger;
  deps?: IntegrationDeps;
  etsySyncEveryMs?: number;
}): Promise<RunningWorker> {
  const pool = new pg.Pool({
    connectionString: opts.databaseUrl,
    max: Math.max(2, opts.concurrency),
    ssl: opts.databaseSsl ? { rejectUnauthorized: true } : undefined,
    application_name: 'esm-worker',
  });
  const connection = redisConnection(opts.redisUrl);
  const maintenance = new Queue(QUEUES.maintenance, {
    connection,
    defaultJobOptions: DEFAULT_JOB_OPTIONS,
  });

  await maintenance.upsertJobScheduler(
    'heartbeat',
    { every: opts.heartbeatEveryMs },
    { name: JOBS.heartbeat, data: {}, opts: DEFAULT_JOB_OPTIONS },
  );
  await maintenance.upsertJobScheduler(
    'cleanup-expired-approvals',
    { pattern: '*/15 * * * *', tz: 'UTC' },
    { name: JOBS.cleanupExpiredApprovals, data: {}, opts: DEFAULT_JOB_OPTIONS },
  );

  const sync = new Queue(QUEUES.sync, { connection, defaultJobOptions: DEFAULT_JOB_OPTIONS });
  const deps = opts.deps ?? NO_DEPS;
  if (deps.etsy && deps.cipher) {
    await sync.upsertJobScheduler(
      'etsy-sync-all',
      { every: opts.etsySyncEveryMs ?? 6 * 3600_000 },
      { name: JOBS.etsySyncAll, data: {}, opts: DEFAULT_JOB_OPTIONS },
    );
    await sync.upsertJobScheduler(
      'etsy-refresh-tokens',
      { pattern: '*/20 * * * *', tz: 'UTC' },
      { name: JOBS.etsyRefreshTokens, data: {}, opts: DEFAULT_JOB_OPTIONS },
    );
  }
  if (deps.printify) {
    await sync.upsertJobScheduler(
      'printify-sync-all',
      { every: 3 * 3600_000 },
      { name: JOBS.printifySyncAll, data: {}, opts: DEFAULT_JOB_OPTIONS },
    );
  }
  const enqueue: Enqueue = async (jobName, storeId, idempotencyKey, payload = {}) => {
    await sync.add(jobName, { idempotencyKey, storeId, payload } satisfies JobEnvelope, {
      jobId: idempotencyKey.replace(/:/g, '_'),
    });
  };

  const processor = createProcessor(pool, opts.logger, deps, enqueue);
  const workers = [
    new Worker(QUEUES.maintenance, processor, { connection, concurrency: opts.concurrency }),
    // Etsy calls are rate limited per API key: keep sync concurrency low
    new Worker(QUEUES.sync, processor, { connection, concurrency: Math.min(2, opts.concurrency) }),
  ];
  for (const worker of workers) {
    worker.on('failed', (job, err) =>
      opts.logger.warn(
        { job: job?.name, id: job?.id, attempts: job?.attemptsMade, err: err.message },
        'job failed',
      ),
    );
    worker.on('error', (err) => opts.logger.error({ err }, 'worker error'));
  }

  return {
    queues: [maintenance, sync],
    workers,
    async close() {
      await Promise.all(workers.map((w) => w.close()));
      await Promise.all([maintenance.close(), sync.close()]);
      await pool.end();
    },
  };
}
