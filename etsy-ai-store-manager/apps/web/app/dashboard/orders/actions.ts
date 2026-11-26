'use server';

import { revalidatePath } from 'next/cache';
import { api, ApiError } from '@/lib/api';

export interface OState {
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const str = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === 'string' ? v.trim() : '';
};
const id = (f: FormData, k: string) => (UUID_RE.test(str(f, k)) ? str(f, k) : null);

function fail(e: unknown): OState {
  if (e instanceof ApiError) {
    const d = e.body?.details;
    return {
      error:
        Array.isArray(d) && d.length
          ? d
              .map(
                (x: { path?: string; message?: string }) => `${x.path ?? ''}: ${x.message ?? ''}`,
              )
              .join(' · ')
          : e.message,
    };
  }
  throw e;
}
function ok(paths: string[], info: string): OState {
  for (const p of paths) revalidatePath(p);
  return { info };
}

export async function orderAction(_p: OState, f: FormData): Promise<OState> {
  const s = id(f, 'storeId');
  const o = id(f, 'orderId');
  if (!s || !o) return { error: 'Geçersiz sipariş' };
  const op = str(f, 'op');
  const base = `/stores/${s}/orders/${o}`;
  const path = `/dashboard/orders/${o}`;
  try {
    if (op === 'tracking') {
      await api(`${base}/tracking`, {
        method: 'POST',
        body: {
          trackingCode: str(f, 'trackingCode'),
          carrierName: str(f, 'carrierName'),
          ...(str(f, 'noteToBuyer') ? { noteToBuyer: str(f, 'noteToBuyer') } : {}),
          reason: str(f, 'reason') || 'Kargo bildirimi',
        },
      });
      return ok([path], 'Onay isteği oluşturuldu (Etsy Mağazam → Onaylar).');
    }
    if (op === 'refund') {
      await api(`${base}/refunds`, {
        method: 'POST',
        body: { amount: str(f, 'amount'), reason: str(f, 'reason') },
      });
      return ok([path], 'İade onay isteği oluşturuldu; kâr etkisi istekte görünür.');
    }
    if (op === 'cancel') {
      await api(`${base}/cancel`, { method: 'POST', body: { reason: str(f, 'reason') } });
      return ok([path], 'İptal onay isteği oluşturuldu.');
    }
  } catch (e) {
    return fail(e);
  }
  return { error: 'Bilinmeyen işlem' };
}

export async function slaAction(_p: OState, f: FormData): Promise<OState> {
  const s = id(f, 'storeId');
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/orders-settings/sla`, {
      method: 'PUT',
      body: {
        processingDaysMax: Number(str(f, 'processing')),
        transitDaysMax: Number(str(f, 'transit')),
      },
    });
  } catch (e) {
    return fail(e);
  }
  return ok(['/dashboard/orders'], 'Kaydedildi.');
}

export async function addMessageAction(_p: OState, f: FormData): Promise<OState> {
  const s = id(f, 'storeId');
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    const r = await api<{ triage: boolean }>(`/stores/${s}/messages`, {
      method: 'POST',
      body: {
        body: str(f, 'body'),
        ...(str(f, 'receiptId') ? { receiptId: str(f, 'receiptId') } : {}),
      },
    });
    return ok(
      ['/dashboard/customers'],
      r.triage
        ? 'Kaydedildi; AI sınıflandırıp yanıt taslağı hazırlıyor.'
        : 'Kaydedildi (AI anahtarı yok; taslak hazırlanmadı).',
    );
  } catch (e) {
    return fail(e);
  }
}

export async function messageAction(_p: OState, f: FormData): Promise<OState> {
  const s = id(f, 'storeId');
  const m = id(f, 'messageId');
  if (!s || !m) return { error: 'Geçersiz mesaj' };
  const op = str(f, 'op');
  try {
    if (op === 'send') {
      await api(`/stores/${s}/messages/${m}/send`, {
        method: 'POST',
        body: { text: str(f, 'text'), reason: str(f, 'reason') || 'Müşteriye yanıt' },
      });
      return ok(
        ['/dashboard/customers'],
        'Onay isteği oluşturuldu. Onaydan sonra metni Etsy’de gönderip burada işaretleyin.',
      );
    }
    if (op === 'triage') {
      await api(`/stores/${s}/messages/${m}/triage`, { method: 'POST' });
      return ok(['/dashboard/customers'], 'Yeniden sınıflandırılıyor.');
    }
    if (op === 'close') {
      await api(`/stores/${s}/messages/${m}/close`, { method: 'POST' });
      return ok(['/dashboard/customers'], 'Kapatıldı.');
    }
  } catch (e) {
    return fail(e);
  }
  return { error: 'Bilinmeyen işlem' };
}
