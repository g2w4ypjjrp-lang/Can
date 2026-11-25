'use server';

import { revalidatePath } from 'next/cache';
import { api, ApiError } from '@/lib/api';

export interface FState {
  ok?: boolean;
  error?: string;
  info?: string;
  result?: SimulationResponse;
}

export interface SimulationResponse {
  result: {
    contribution: string;
    contributionBeforeAds: string;
    contributionAfterTax: string;
    contributionMargin: string | null;
    netRevenue: string;
    totalFees: string;
    decision: string;
    complete: boolean;
    feesVerified: boolean;
    warnings: string[];
    currency: string;
    breakdown: Array<{
      code: string;
      label: string;
      amount: string;
      base?: string;
      rate?: string;
      fixed?: string;
      note?: string;
    }>;
  };
  recommendation: {
    minimumUnitPrice: string | null;
    suggestedUnitPrice: string | null;
    expectedContribution: string | null;
    note: string;
  };
  fxAsOf: string | null;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const err = (e: unknown) => {
  if (e instanceof ApiError) {
    const d = e.body?.details;
    if (Array.isArray(d) && d.length)
      return d
        .map((x: { path?: string; message?: string }) => `${x.path}: ${x.message}`)
        .join(' · ');
    return e.message;
  }
  throw e;
};
const s = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === 'string' && v.trim() ? v.trim().replace(',', '.') : undefined;
};

export async function simulateAction(_p: FState, form: FormData): Promise<FState> {
  const storeId = String(form.get('storeId') ?? '');
  if (!UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  const body: Record<string, unknown> = {
    unitPrice: s(form, 'unitPrice'),
    quantity: Number(s(form, 'quantity') ?? 1),
    shippingCharged: s(form, 'shippingCharged') ?? '0',
    discount: s(form, 'discount'),
    productionCostPerUnit: s(form, 'productionCostPerUnit'),
    fulfillmentShippingFirst: s(form, 'fulfillmentShippingFirst') ?? '0',
    fulfillmentShippingAdditional: s(form, 'fulfillmentShippingAdditional') ?? '0',
    buyerCountry: (s(form, 'buyerCountry') ?? 'US').toUpperCase(),
    adCostAllocated: s(form, 'adCostAllocated'),
    offsiteAds: form.get('offsiteAds') === 'on',
  };
  for (const k of Object.keys(body)) if (body[k] === undefined) delete body[k];
  try {
    const result = await api<SimulationResponse>(`/stores/${storeId}/finance/simulate`, {
      method: 'POST',
      body,
    });
    return { ok: true, result };
  } catch (e) {
    return { error: err(e) };
  }
}

export async function verifyFeeRuleAction(_p: FState, form: FormData): Promise<FState> {
  const storeId = String(form.get('storeId') ?? '');
  const ruleId = String(form.get('ruleId') ?? '');
  if (!UUID_RE.test(storeId) || !UUID_RE.test(ruleId)) return { error: 'Geçersiz kural' };
  try {
    await api(`/stores/${storeId}/finance/fee-rules/${ruleId}/verify`, {
      method: 'POST',
      body: { note: 'Panelden doğrulandı' },
    });
  } catch (e) {
    return { error: err(e) };
  }
  revalidatePath('/dashboard/finance');
  return { ok: true, info: 'Doğrulandı' };
}

export async function recomputeAction(_p: FState, form: FormData): Promise<FState> {
  const storeId = String(form.get('storeId') ?? '');
  if (!UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${storeId}/finance/recompute`, { method: 'POST' });
  } catch (e) {
    return { error: err(e) };
  }
  return { ok: true, info: 'Yeniden hesaplama kuyruğa alındı.' };
}

export async function priceRecommendationAction(_p: FState, form: FormData): Promise<FState> {
  const storeId = String(form.get('storeId') ?? '');
  const productId = String(form.get('productId') ?? '');
  const country = (s(form, 'country') ?? 'US').toUpperCase();
  const step = form.get('step');
  if (!UUID_RE.test(storeId) || !UUID_RE.test(productId) || !/^[A-Z]{2}$/.test(country))
    return { error: 'Geçersiz istek' };
  try {
    if (step === 'request') {
      await api(`/stores/${storeId}/products/${productId}/price-change-requests`, {
        method: 'POST',
      });
      revalidatePath(`/dashboard/products/${productId}`);
      return {
        ok: true,
        info: 'Fiyat değişikliği onaya gönderildi (Etsy Mağazam sayfasında onaylayın).',
      };
    }
    const recs = await api<Array<{ variant: string; recommendedPrice: string }>>(
      `/stores/${storeId}/products/${productId}/price-recommendations?country=${country}`,
      { method: 'POST' },
    );
    revalidatePath(`/dashboard/products/${productId}`);
    return {
      ok: true,
      info: recs.length
        ? `${recs.length} varyant için fiyat önerisi kaydedildi.`
        : 'Tüm varyantlar hedef katkıyı karşılıyor; öneri gerekmedi.',
    };
  } catch (e) {
    return { error: err(e) };
  }
}
