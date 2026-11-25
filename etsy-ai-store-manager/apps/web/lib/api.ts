import 'server-only';
import { redirect } from 'next/navigation';
import type { ApiErrorBody } from '@esm/shared';
import { webConfig } from './config';
import { getSessionUser } from './supabase/server';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody | null,
  ) {
    super(body?.message ?? `API hatası (${status})`);
  }
}

/** Server-side call to the NestJS API with the user's Supabase access token. */
export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const session = await getSessionUser();
  if (!session) redirect('/login');
  const res = await fetch(`${webConfig().apiUrl}/api/v1${path}`, {
    method: init.method ?? 'GET',
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: 'no-store',
  });
  if (res.status === 401) redirect('/login');
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const json = text ? (JSON.parse(text) as unknown) : null;
  if (!res.ok) throw new ApiError(res.status, json as ApiErrorBody | null);
  return json as T;
}
