export class EtsyApiError extends Error {
  constructor(
    readonly status: number,
    readonly operation: string,
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(`Etsy ${operation} failed (${status}): ${message}`);
    this.name = 'EtsyApiError';
  }

  /** 401 => token invalid/revoked; the connection needs re-authorization. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}
