'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { api, ApiError } from '@/lib/api';

export interface MState {
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;

export async function startResearchAction(_p: MState, form: FormData): Promise<MState> {
  const storeId = String(form.get('storeId') ?? '');
  if (!UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  const query = String(form.get('query') ?? '').trim();
  const country = String(form.get('buyerCountry') ?? '')
    .trim()
    .toUpperCase();
  const keywords = String(form.get('keywords') ?? '')
    .split(',')
    .map((k) => k.trim())
    .filter(Boolean)
    .slice(0, 4);
  let id: string;
  try {
    id = (
      await api<{ id: string }>(`/stores/${storeId}/market-research`, {
        method: 'POST',
        body: {
          query,
          ...(country ? { buyerCountry: country } : {}),
          ...(keywords.length ? { keywords } : {}),
          useWebSearch: form.get('useWebSearch') === 'on',
        },
      })
    ).id;
  } catch (e) {
    if (e instanceof ApiError) {
      const d = e.body?.details;
      return {
        error: Array.isArray(d)
          ? d.map((x: { path?: string; message?: string }) => `${x.path}: ${x.message}`).join(' · ')
          : e.message,
      };
    }
    throw e;
  }
  revalidatePath('/dashboard/market-research');
  redirect(`/dashboard/market-research?id=${id}`);
}

export async function decideOpportunityAction(_p: MState, form: FormData): Promise<MState> {
  const storeId = String(form.get('storeId') ?? '');
  const id = String(form.get('opportunityId') ?? '');
  const status = String(form.get('status') ?? '');
  if (
    !UUID_RE.test(storeId) ||
    !UUID_RE.test(id) ||
    !['new', 'shortlisted', 'rejected'].includes(status)
  )
    return { error: 'Geçersiz istek' };
  try {
    await api(`/stores/${storeId}/opportunities/${id}`, { method: 'PATCH', body: { status } });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e;
  }
  revalidatePath('/dashboard/opportunities');
  revalidatePath('/dashboard/market-research');
  return {
    info:
      status === 'shortlisted'
        ? 'Kısa listeye alındı'
        : status === 'rejected'
          ? 'Reddedildi'
          : 'Sıfırlandı',
  };
}
