import { Injectable } from '@nestjs/common';
import { ThrottlerGuard } from '@nestjs/throttler';
import { createHash } from 'node:crypto';

/**
 * Rate-limit key per caller, not per socket IP.
 * The web app calls this API from its own server, so every signed-in user arrives from the
 * same IP; keying on req.ip would make all users share one budget. With a bearer token the
 * key is a hash of the token (one per session; tokens are never stored). Requests without a
 * token fall back to the client IP (Nginx additionally rate-limits real client IPs at the edge).
 * A forged token only changes the key: it is still rejected by the AuthGuard right after.
 */
@Injectable()
export class UserThrottlerGuard extends ThrottlerGuard {
  protected override async getTracker(req: Record<string, unknown>): Promise<string> {
    return trackerFor(req);
  }
}

export function trackerFor(req: Record<string, unknown>): string {
  const headers = (req.headers ?? {}) as Record<string, string | string[] | undefined>;
  const h = headers.authorization;
  const auth = Array.isArray(h) ? h[0] : h;
  if (auth && /^Bearer\s+\S{20,}$/i.test(auth)) {
    return `tok:${createHash('sha256').update(auth.slice(7).trim()).digest('hex').slice(0, 32)}`;
  }
  const ips = req.ips as string[] | undefined;
  return `ip:${ips?.length ? ips[0] : String(req.ip ?? 'unknown')}`;
}
