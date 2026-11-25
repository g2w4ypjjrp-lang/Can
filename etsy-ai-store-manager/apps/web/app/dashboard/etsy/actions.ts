'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { listingChangeRequestSchema } from '@esm/shared';
import { api, ApiError } from '@/lib/api';
import { createSupabaseServerClient } from '@/lib/supabase/server';

export interface ActionState {
  ok?: boolean;
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;

function uuid(form: FormData, key: string): string | null {
  const v = form.get(key);
  return typeof v === 'string' && UUID_RE.test(v) ? v : null;
}

function message(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.body?.details;
    if (Array.isArray(d) && d.length) {
      return d
        .map((x: { path?: string; message?: string }) => `${x.path ?? ''}: ${x.message ?? ''}`)
        .join(' · ');
    }
    return e.message;
  }
  throw e;
}

/** Starts OAuth: the API returns Etsy's consent URL (state + PKCE kept server-side). */
export async function connectEtsyAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const storeId = uuid(form, 'storeId');
  if (!storeId) return { error: 'Mağaza seçili değil' };
  let url: string;
  try {
    url = (
      await api<{ authorizeUrl: string }>(`/stores/${storeId}/integrations/etsy/connect`, {
        method: 'POST',
      })
    ).authorizeUrl;
  } catch (e) {
    return { error: message(e) };
  }
  redirect(url);
}

export async function syncEtsyAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const storeId = uuid(form, 'storeId');
  if (!storeId) return { error: 'Mağaza seçili değil' };
  try {
    await api(`/stores/${storeId}/integrations/etsy/sync`, { method: 'POST' });
  } catch (e) {
    return { error: message(e) };
  }
  revalidatePath('/dashboard/etsy');
  return { ok: true, info: 'İçe aktarma kuyruğa alındı. Birkaç dakika içinde güncellenecek.' };
}

export async function disconnectEtsyAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const storeId = uuid(form, 'storeId');
  if (!storeId) return { error: 'Mağaza seçili değil' };
  if (form.get('confirm') !== 'BAĞLANTIYI KES')
    return { error: 'Onaylamak için "BAĞLANTIYI KES" yazın' };
  let note: string;
  try {
    note = (
      await api<{ note: string }>(`/stores/${storeId}/integrations/etsy`, { method: 'DELETE' })
    ).note;
  } catch (e) {
    return { error: message(e) };
  }
  revalidatePath('/dashboard', 'layout');
  return { ok: true, info: note };
}

export async function requestListingChangeAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const storeId = uuid(form, 'storeId');
  const listingId = uuid(form, 'listingId');
  if (!storeId || !listingId) return { error: 'Geçersiz ilan' };
  const original = JSON.parse(String(form.get('original') ?? '{}')) as Record<string, unknown>;
  const title = String(form.get('title') ?? '').trim();
  const description = String(form.get('description') ?? '').trim();
  const tags = String(form.get('tags') ?? '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
  const state = String(form.get('state') ?? '');
  const input: Record<string, unknown> = { reason: String(form.get('reason') ?? '') };
  if (title !== original.title) input.title = title;
  if (description !== (original.description ?? '')) input.description = description;
  if (JSON.stringify(tags) !== JSON.stringify(original.tags)) input.tags = tags;
  if (state && state !== original.state && (state === 'active' || state === 'inactive'))
    input.state = state;
  const parsed = listingChangeRequestSchema.safeParse(input);
  if (!parsed.success) {
    const i = parsed.error.issues[0];
    return { error: i ? `${i.path.join('.') || 'form'}: ${i.message}` : 'Geçersiz bilgi' };
  }
  try {
    await api(`/stores/${storeId}/listings/${listingId}/change-requests`, {
      method: 'POST',
      body: parsed.data,
    });
  } catch (e) {
    return { error: message(e) };
  }
  revalidatePath('/dashboard/etsy');
  return {
    ok: true,
    info: 'Değişiklik önerisi oluşturuldu. Onaylanana kadar Etsy’ye hiçbir şey gönderilmez.',
  };
}

/**
 * Approve: when the request needs re-authentication, the password is verified
 * again with Supabase Auth and the fresh access token (new `iat`) is used.
 */
export async function decideApprovalAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const storeId = uuid(form, 'storeId');
  const approvalId = uuid(form, 'approvalId');
  const decision = form.get('decision') === 'approve' ? 'approve' : 'reject';
  if (!storeId || !approvalId) return { error: 'Geçersiz istek' };
  let accessToken: string | undefined;
  if (decision === 'approve' && form.get('requiresReauth') === 'true') {
    const password = String(form.get('password') ?? '');
    if (!password) return { error: 'Onay için parolanızı girin' };
    const supabase = await createSupabaseServerClient();
    const { data: userData } = await supabase.auth.getUser();
    const email = userData.user?.email;
    if (!email) redirect('/login');
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error || !data.session) return { error: 'Parola doğrulanamadı' };
    accessToken = data.session.access_token;
  }
  try {
    await api(`/stores/${storeId}/approvals/${approvalId}/${decision}`, {
      method: 'POST',
      body: { note: String(form.get('note') ?? '').trim() || undefined },
      accessToken,
    });
  } catch (e) {
    return { error: message(e) };
  }
  revalidatePath('/dashboard/etsy');
  return {
    ok: true,
    info:
      decision === 'approve'
        ? 'Onaylandı; işlem kuyruğa alındı.'
        : 'Reddedildi; Etsy’de değişiklik yapılmadı.',
  };
}
