import { Inject, Injectable, OnModuleDestroy } from '@nestjs/common';
import { Queue } from 'bullmq';
import { QUEUES, type JobEnvelope, type QueueName } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';

export const DEFAULT_JOB_OPTIONS = {
  attempts: 3,
  backoff: { type: 'exponential' as const, delay: 5_000 },
  removeOnComplete: { age: 7 * 24 * 3600, count: 1000 },
  removeOnFail: { age: 30 * 24 * 3600 },
};

/** Producer side of BullMQ. The worker process consumes these queues. */
@Injectable()
export class QueueService implements OnModuleDestroy {
  private readonly queues = new Map<QueueName, Queue>();

  constructor(@Inject(ENV) private readonly env: Env) {}

  private queue(name: QueueName): Queue {
    let q = this.queues.get(name);
    if (!q) {
      const u = new URL(this.env.REDIS_URL);
      q = new Queue(name, {
        connection: {
          host: u.hostname,
          port: Number(u.port || 6379),
          username: u.username || undefined,
          password: u.password ? decodeURIComponent(u.password) : undefined,
          db: u.pathname.length > 1 ? Number(u.pathname.slice(1)) : 0,
          tls: u.protocol === 'rediss:' ? {} : undefined,
          maxRetriesPerRequest: null,
        },
        defaultJobOptions: DEFAULT_JOB_OPTIONS,
      });
      this.queues.set(name, q);
    }
    return q;
  }

  /**
   * Enqueues a job. BullMQ jobId = idempotency key, so the same logical job is
   * never queued twice while it exists; the worker additionally dedupes in the DB.
   */
  async enqueue<T extends Record<string, unknown>>(
    queue: QueueName,
    jobName: string,
    envelope: JobEnvelope<T>,
  ): Promise<string> {
    const jobId = envelope.idempotencyKey.replace(/:/g, '_');
    const job = await this.queue(queue).add(jobName, envelope, { jobId });
    return job.id ?? jobId;
  }

  async onModuleDestroy() {
    await Promise.all([...this.queues.values()].map((q) => q.close()));
  }
}

export { QUEUES };
