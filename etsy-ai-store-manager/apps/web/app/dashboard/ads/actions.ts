'use server';

import { revalidatePath } from 'next/cache';
import { api, ApiError } from '@/lib/api';

export interface AState {
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const str = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === 'string' ? v.trim() : '';
};
const store = (f: FormData) => (UUID_RE.test(str(f, 'storeId')) ? str(f, 'storeId') : null);

function fail(e: unknown): AState {
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
function ok(info: string): AState {
  revalidatePath('/dashboard/ads');
  return { info };
}

export async function policyAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/ads/policy`, {
      method: 'PUT',
      body: {
        dailyCap: str(f, 'dailyCap'),
        monthlyCap: str(f, 'monthlyCap') || null,
        currency: str(f, 'currency') || 'USD',
        minClicksForDecision: Number(str(f, 'minClicks') || 100),
      },
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Bütçe sınırı kaydedildi.');
}

export async function accountAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/ads/accounts`, {
      method: 'POST',
      body: {
        platform: str(f, 'platform'),
        externalAccountId: str(f, 'externalAccountId'),
        name: str(f, 'name'),
        currency: str(f, 'currency') || 'USD',
      },
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Reklam hesabı eklendi.');
}

export async function metaConnectAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    const r = await api<{ name: string }>(`/stores/${s}/ads/meta/connect`, {
      method: 'POST',
      body: { adAccountId: str(f, 'adAccountId'), accessToken: str(f, 'accessToken') },
    });
    return ok(`Meta hesabı bağlandı: ${r.name}. Raporlar içe aktarılıyor.`);
  } catch (e) {
    return fail(e);
  }
}

/** CSV columns: date,campaign,impressions,clicks,spend,orders,revenue (header row required). */
export async function importCsvAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  const accountId = str(f, 'adAccountId');
  if (!s || !UUID_RE.test(accountId)) return { error: 'Hesap seçin' };
  let text = str(f, 'csv');
  const file = f.get('file');
  if (file instanceof File && file.size > 0) {
    if (file.size > 2_000_000) return { error: 'Dosya 2 MB’den büyük' };
    text = (await file.text()).trim();
  }
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return { error: 'Başlık satırı ve en az bir veri satırı gerekli' };
  const head = lines[0]!.split(',').map((h) => h.trim().toLowerCase());
  const need = ['date', 'campaign', 'spend'];
  const missing = need.filter((n) => !head.includes(n));
  if (missing.length) return { error: `Eksik sütunlar: ${missing.join(', ')}` };
  const col = (cells: string[], name: string) => {
    const i = head.indexOf(name);
    return i >= 0 ? (cells[i] ?? '').trim().replace(/^"|"$/g, '') : '';
  };
  const num = (v: string) => v.replace(/[$€£\s]/g, '').replace(/,(?=\d{3}\b)/g, '');
  const rows = lines.slice(1).map((l) => {
    const c = l.split(',');
    return {
      date: col(c, 'date'),
      campaign: col(c, 'campaign'),
      impressions: Number(num(col(c, 'impressions')) || 0),
      clicks: Number(num(col(c, 'clicks')) || 0),
      spend: num(col(c, 'spend')) || '0',
      orders: num(col(c, 'orders')) || '0',
      revenue: num(col(c, 'revenue')) || '0',
    };
  });
  try {
    const r = await api<{ written: number }>(`/stores/${s}/ads/metrics/import`, {
      method: 'POST',
      body: { adAccountId: accountId, rows },
    });
    return ok(`${r.written} satır içe aktarıldı.`);
  } catch (e) {
    return fail(e);
  }
}

export async function proposalAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/ads/proposals`, {
      method: 'POST',
      body: str(f, 'total') ? { totalDailyBudget: str(f, 'total') } : {},
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Öneri oluşturuldu (henüz hiçbir şey değişmedi).');
}

export async function submitProposalAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  const id = str(f, 'proposalId');
  if (!s || !UUID_RE.test(id)) return { error: 'Geçersiz öneri' };
  try {
    await api(`/stores/${s}/ads/proposals/${id}/submit`, {
      method: 'POST',
      body: { reason: str(f, 'reason') || 'Bütçe dağıtımı' },
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Onay isteği oluşturuldu. Etsy Mağazam → Onaylar bölümünden parolanızla onaylayın.');
}

export async function confirmManualAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  const id = str(f, 'approvalId');
  if (!s || !UUID_RE.test(id)) return { error: 'Geçersiz istek' };
  try {
    await api(`/stores/${s}/approvals/${id}/confirm-manual`, {
      method: 'POST',
      body: { note: str(f, 'note') },
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Uygulandı olarak işaretlendi; kampanya bütçeleri güncellendi.');
}

export async function ledgerMappingAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/ads/etsy-ledger/mapping`, {
      method: 'PUT',
      body: { types: f.getAll('types').map(String) },
    });
  } catch (e) {
    return fail(e);
  }
  return ok('Eşleme kaydedildi; Etsy ödeme defteri içe aktarılıyor.');
}

export async function syncAction(_p: AState, f: FormData): Promise<AState> {
  const s = store(f);
  if (!s) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${s}/ads/sync`, { method: 'POST' });
  } catch (e) {
    return fail(e);
  }
  return ok('Senkronizasyon başlatıldı.');
}
