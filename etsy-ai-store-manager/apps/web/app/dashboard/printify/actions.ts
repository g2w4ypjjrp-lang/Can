'use server';

import { revalidatePath } from 'next/cache';
import { api, ApiError } from '@/lib/api';

export interface PState {
  ok?: boolean;
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const msg = (e: unknown) => {
  if (e instanceof ApiError) return e.message;
  throw e;
};

export async function connectPrintifyAction(_p: PState, form: FormData): Promise<PState> {
  const storeId = String(form.get('storeId') ?? '');
  const shopId = Number(form.get('shopId'));
  if (!UUID_RE.test(storeId) || !Number.isInteger(shopId)) return { error: 'Mağaza seçin' };
  try {
    const r = await api<{ warning: string | null; webhookNote: string }>(
      `/stores/${storeId}/integrations/printify/connect`,
      {
        method: 'POST',
        body: { shopId },
      },
    );
    revalidatePath('/dashboard/printify');
    return {
      ok: true,
      info: [r.warning, r.webhookNote, 'İlk senkronizasyon başlatıldı.'].filter(Boolean).join(' '),
    };
  } catch (e) {
    return { error: msg(e) };
  }
}

export async function syncPrintifyAction(_p: PState, form: FormData): Promise<PState> {
  const storeId = String(form.get('storeId') ?? '');
  if (!UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${storeId}/integrations/printify/sync`, { method: 'POST' });
    revalidatePath('/dashboard/printify');
    return { ok: true, info: 'Senkronizasyon kuyruğa alındı.' };
  } catch (e) {
    return { error: msg(e) };
  }
}

export async function requestPublishAction(_p: PState, form: FormData): Promise<PState> {
  const storeId = String(form.get('storeId') ?? '');
  const productId = String(form.get('productId') ?? '');
  const reason = String(form.get('reason') ?? '').trim();
  if (!UUID_RE.test(storeId) || !UUID_RE.test(productId)) return { error: 'Geçersiz ürün' };
  if (reason.length < 3) return { error: 'Gerekçe yazın' };
  try {
    const country = String(form.get('country') ?? 'US').toUpperCase();
    await api(`/stores/${storeId}/products/${productId}/publish-requests`, {
      method: 'POST',
      body: {
        reason,
        ...(/^[A-Z]{2}$/.test(country) ? { country } : {}),
        ...(form.get('acknowledgeLowProfit') === 'on' ? { acknowledgeLowProfit: true } : {}),
      },
    });
    revalidatePath('/dashboard/products');
    return {
      ok: true,
      info: 'Yayın isteği oluşturuldu. Etsy Mağazam sayfasından onaylayabilirsiniz.',
    };
  } catch (e) {
    return { error: msg(e) };
  }
}
