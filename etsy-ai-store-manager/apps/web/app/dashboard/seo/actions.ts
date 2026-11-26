'use server';

import { revalidatePath } from 'next/cache';
import { api, ApiError } from '@/lib/api';

export interface SState {
  error?: string;
  info?: string;
  check?: {
    score: number;
    blocking: boolean;
    issues: Array<{ field: string; severity: string; message: string }>;
  };
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const str = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === 'string' ? v.trim() : '';
};
const id = (f: FormData, k: string) => (UUID_RE.test(str(f, k)) ? str(f, k) : null);
const list = (v: string) =>
  v
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

function fail(e: unknown): SState {
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
function refresh(path: string | null, info: string): SState {
  if (path) revalidatePath(path);
  revalidatePath('/dashboard/seo');
  return { info };
}
const pathFor = (f: FormData) => (str(f, 'path').startsWith('/dashboard/') ? str(f, 'path') : null);
const content = (f: FormData) => ({
  title: str(f, 'title'),
  description: str(f, 'description'),
  tags: list(str(f, 'tags')),
  ...(str(f, 'materials') ? { materials: list(str(f, 'materials')) } : {}),
});

/** Starts an AI SEO draft for a listing or product. */
export async function requestSeoAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  const listingId = id(f, 'listingId');
  const productId = id(f, 'productId');
  if (!storeId || (!listingId && !productId)) return { error: 'Geçersiz kayıt' };
  try {
    await api(
      listingId
        ? `/stores/${storeId}/listings/${listingId}/seo-drafts`
        : `/stores/${storeId}/products/${productId}/seo-drafts`,
      {
        method: 'POST',
        body: { language: str(f, 'language') || 'en' },
      },
    );
  } catch (e) {
    return fail(e);
  }
  return refresh(pathFor(f), 'SEO önerisi hazırlanıyor (yaklaşık bir dakika). Sayfayı yenileyin.');
}

export async function draftAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  const draftId = id(f, 'draftId');
  if (!storeId || !draftId) return { error: 'Geçersiz öneri' };
  const op = str(f, 'op');
  const base = `/stores/${storeId}/seo-drafts/${draftId}`;
  try {
    if (op === 'save') {
      await api(base, { method: 'PATCH', body: content(f) });
      return refresh(pathFor(f), 'Kaydedildi ve yeniden kontrol edildi.');
    }
    if (op === 'apply') {
      await api(`${base}/apply`, {
        method: 'POST',
        body: { reason: str(f, 'reason') || 'SEO iyileştirmesi' },
      });
      return refresh(
        pathFor(f),
        'Onay isteği oluşturuldu. Onaylar sayfasından onaylayın; onaydan önce hiçbir şey gönderilmez.',
      );
    }
    if (op === 'reject') {
      await api(`${base}/reject`, { method: 'POST' });
      return refresh(pathFor(f), 'Öneri reddedildi.');
    }
  } catch (e) {
    return fail(e);
  }
  return { error: 'Bilinmeyen işlem' };
}

export async function translateAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  const listingId = id(f, 'listingId');
  const languages = f.getAll('languages').map(String);
  if (!storeId || !listingId) return { error: 'Geçersiz ilan' };
  if (!languages.length) return { error: 'En az bir dil seçin' };
  try {
    await api(`/stores/${storeId}/listings/${listingId}/translations`, {
      method: 'POST',
      body: { languages },
    });
  } catch (e) {
    return fail(e);
  }
  return refresh(pathFor(f), `${languages.join(', ')} çevirisi hazırlanıyor.`);
}

export async function translationAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  const trId = id(f, 'translationId');
  if (!storeId || !trId) return { error: 'Geçersiz çeviri' };
  const op = str(f, 'op');
  const base = `/stores/${storeId}/translations/${trId}`;
  try {
    if (op === 'save') {
      await api(base, { method: 'PATCH', body: content(f) });
      return refresh(pathFor(f), 'Kaydedildi; yeniden inceleyin.');
    }
    if (op === 'review' || op === 'reject') {
      await api(`${base}/review`, {
        method: 'POST',
        body: { decision: op === 'review' ? 'reviewed' : 'rejected' },
      });
      return refresh(
        pathFor(f),
        op === 'review' ? 'Çeviri incelendi olarak işaretlendi.' : 'Çeviri reddedildi.',
      );
    }
    if (op === 'publish') {
      await api(`${base}/publish`, {
        method: 'POST',
        body: { reason: str(f, 'reason') || 'Yerel alıcılar için çeviri' },
      });
      return refresh(pathFor(f), 'Onay isteği oluşturuldu.');
    }
  } catch (e) {
    return fail(e);
  }
  return { error: 'Bilinmeyen işlem' };
}

/** Live Etsy rule check (no AI). */
export async function checkAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  if (!storeId) return { error: 'Mağaza seçili değil' };
  try {
    const r = await api<NonNullable<SState['check']>>(`/stores/${storeId}/seo/check`, {
      method: 'POST',
      body: {
        ...content(f),
        ...(str(f, 'primaryKeyword') ? { primaryKeyword: str(f, 'primaryKeyword') } : {}),
      },
    });
    return { check: r };
  } catch (e) {
    return fail(e);
  }
}

export async function draftListingAction(_p: SState, f: FormData): Promise<SState> {
  const storeId = id(f, 'storeId');
  if (!storeId) return { error: 'Mağaza seçili değil' };
  const num = (k: string) => (str(f, k) ? Number(str(f, k)) : undefined);
  try {
    await api(`/stores/${storeId}/etsy/draft-listings`, {
      method: 'POST',
      body: {
        ...content(f),
        materials: list(str(f, 'materials')),
        price: str(f, 'price'),
        quantity: num('quantity'),
        taxonomyId: num('taxonomyId'),
        whoMade: str(f, 'whoMade'),
        whenMade: str(f, 'whenMade'),
        isSupply: f.get('isSupply') === 'on',
        shippingProfileId: num('shippingProfileId'),
        ...(num('returnPolicyId') ? { returnPolicyId: num('returnPolicyId') } : {}),
        productionPartnerIds: f.getAll('productionPartnerIds').map(Number).filter(Boolean),
        ...(num('processingMin') ? { processingMin: num('processingMin') } : {}),
        ...(num('processingMax') ? { processingMax: num('processingMax') } : {}),
        reason: str(f, 'reason') || 'Yeni ürün ilanı',
      },
    });
  } catch (e) {
    return fail(e);
  }
  return refresh(
    '/dashboard/seo/new-listing',
    'Onay isteği oluşturuldu. Onaydan sonra Etsy’de TASLAK ilan açılır.',
  );
}
