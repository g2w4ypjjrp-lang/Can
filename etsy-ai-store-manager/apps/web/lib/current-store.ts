import 'server-only';
import { cookies } from 'next/headers';
import type { StoreSummary } from '@esm/shared';
import { api } from './api';

export const STORE_COOKIE = 'esm_store';

/** Loads the user's stores and resolves the active one (cookie, else first). */
export async function loadStores(): Promise<{
  stores: StoreSummary[];
  current: StoreSummary | null;
}> {
  const stores = await api<StoreSummary[]>('/stores');
  const wanted = (await cookies()).get(STORE_COOKIE)?.value;
  const current = stores.find((s) => s.id === wanted) ?? stores[0] ?? null;
  return { stores, current };
}
