'use server';

import { cookies } from 'next/headers';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import {
  profitRulesUpdateSchema,
  storeCreateSchema,
  storeSettingsUpdateSchema,
  userSettingsUpdateSchema,
  type StoreSummary,
} from '@esm/shared';
import { api, ApiError } from '@/lib/api';
import { STORE_COOKIE } from '@/lib/current-store';

export interface FormState {
  ok?: boolean;
  error?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const details = e.body?.details;
    if (Array.isArray(details) && details.length) {
      return details
        .map((d: { path?: string; message?: string }) => `${d.path ?? ''}: ${d.message ?? ''}`)
        .join(' · ');
    }
    return e.message;
  }
  throw e; // let Next handle redirects / unexpected errors
}

function str(form: FormData, key: string): string | undefined {
  const v = form.get(key);
  return typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;
}

export async function selectStoreAction(form: FormData) {
  const id = str(form, 'storeId');
  if (id && UUID_RE.test(id)) {
    (await cookies()).set(STORE_COOKIE, id, {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
    });
  }
  revalidatePath('/dashboard', 'layout');
}

export async function createStoreAction(_prev: FormState, form: FormData): Promise<FormState> {
  const parsed = storeCreateSchema.safeParse({
    name: str(form, 'name'),
    currency: str(form, 'currency') ?? 'USD',
    defaultLanguage: str(form, 'defaultLanguage') ?? 'en',
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? 'Geçersiz bilgi' };
  let store: StoreSummary;
  try {
    store = await api<StoreSummary>('/stores', { method: 'POST', body: parsed.data });
  } catch (e) {
    return { error: errorMessage(e) };
  }
  (await cookies()).set(STORE_COOKIE, store.id, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
  });
  redirect('/dashboard');
}

export async function updateUserSettingsAction(
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  const parsed = userSettingsUpdateSchema.safeParse({
    fullName: str(form, 'fullName') ?? null,
    timezone: str(form, 'timezone'),
    uiLanguage: str(form, 'uiLanguage'),
    baseCurrency: str(form, 'baseCurrency'),
    notifyEmail: form.get('notifyEmail') === 'on',
    notifyPush: form.get('notifyPush') === 'on',
    notifyDailyReport: form.get('notifyDailyReport') === 'on',
    requireReauthForSensitive: form.get('requireReauthForSensitive') === 'on',
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? 'Geçersiz bilgi' };
  try {
    await api('/me/settings', { method: 'PATCH', body: parsed.data });
  } catch (e) {
    return { error: errorMessage(e) };
  }
  revalidatePath('/dashboard/settings');
  return { ok: true };
}

export async function updateStoreSettingsAction(
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  const storeId = str(form, 'storeId');
  if (!storeId || !UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  const parsed = storeSettingsUpdateSchema.safeParse({
    salesStrategy: str(form, 'salesStrategy'),
    automationLevel: str(form, 'automationLevel'),
    defaultLanguage: str(form, 'defaultLanguage'),
    languages: form.getAll('languages').map(String),
    targetMarkets: (str(form, 'targetMarkets') ?? '')
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean),
    dailyAdBudgetCap: str(form, 'dailyAdBudgetCap'),
    adBudgetCurrency: str(form, 'adBudgetCurrency'),
    sellerCountry: str(form, 'sellerCountry'),
    payoutCurrency: str(form, 'payoutCurrency'),
    timezone: str(form, 'timezone'),
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? 'Geçersiz bilgi' };
  try {
    await api(`/stores/${storeId}/settings`, { method: 'PATCH', body: parsed.data });
  } catch (e) {
    return { error: errorMessage(e) };
  }
  revalidatePath('/dashboard', 'layout');
  return { ok: true };
}

const PROFIT_FIELDS = [
  'targetContribution',
  'excellentThreshold',
  'publishThreshold',
  'reviewThreshold',
  'minThreshold',
  'returnReserveRate',
  'remakeReserveRate',
  'otherVariableCostRate',
  'otherVariableCostFixed',
  'defaultAdCostPerOrder',
  'taxRateOnProfit',
  'vatOnFeesRate',
  'offsiteAdsTier',
] as const;

export async function updateProfitRulesAction(
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  const storeId = str(form, 'storeId');
  if (!storeId || !UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  const raw: Record<string, string | undefined> = {};
  for (const f of PROFIT_FIELDS) raw[f] = str(form, f)?.replace(',', '.');
  const parsed = profitRulesUpdateSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    return { error: issue ? `${String(issue.path[0] ?? '')}: ${issue.message}` : 'Geçersiz bilgi' };
  }
  try {
    await api(`/stores/${storeId}/profit-rules`, { method: 'PATCH', body: parsed.data });
  } catch (e) {
    return { error: errorMessage(e) };
  }
  revalidatePath('/dashboard', 'layout');
  return { ok: true };
}

export async function markNotificationReadAction(form: FormData) {
  const id = str(form, 'id');
  if (id && UUID_RE.test(id)) await api(`/notifications/${id}/read`, { method: 'POST' });
  revalidatePath('/dashboard/notifications');
}

export async function markAllNotificationsReadAction() {
  await api('/notifications/read-all', { method: 'POST' });
  revalidatePath('/dashboard/notifications');
}
