/** BullMQ queue & job names shared by API (producer) and worker (consumer). */
export const QUEUES = {
  maintenance: 'maintenance',
  sync: 'sync',
  ai: 'ai',
  reports: 'reports',
} as const;
export type QueueName = (typeof QUEUES)[keyof typeof QUEUES];

export const JOBS = {
  heartbeat: 'system.heartbeat',
  cleanupExpiredApprovals: 'system.cleanup-expired-approvals',
  etsySyncStore: 'etsy.sync-store',
  etsySyncAll: 'etsy.sync-all',
  etsyRefreshTokens: 'etsy.refresh-tokens',
  approvalExecute: 'approval.execute',
  printifySyncStore: 'printify.sync-store',
  printifySyncAll: 'printify.sync-all',
  printifyWebhook: 'printify.webhook',
} as const;
export type JobName = (typeof JOBS)[keyof typeof JOBS];

export interface JobEnvelope<T = Record<string, unknown>> {
  /** Unique key; the same key is never processed twice (idempotency). */
  idempotencyKey: string;
  storeId?: string | null;
  payload: T;
}
