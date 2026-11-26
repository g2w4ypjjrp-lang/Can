'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { api, ApiError } from '@/lib/api';

export interface DState {
  error?: string;
  info?: string;
}

const UUID_RE = /^[0-9a-f-]{36}$/i;
const s = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === 'string' && v.trim() ? v.trim() : undefined;
};
function err(e: unknown): DState {
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
const ids = (f: FormData) => {
  const storeId = String(f.get('storeId') ?? '');
  const designId = String(f.get('designId') ?? '');
  return UUID_RE.test(storeId) && UUID_RE.test(designId) ? { storeId, designId } : null;
};

export async function createDesignAction(_p: DState, form: FormData): Promise<DState> {
  const storeId = String(form.get('storeId') ?? '');
  if (!UUID_RE.test(storeId)) return { error: 'Mağaza seçili değil' };
  let id: string;
  try {
    id = (
      await api<{ id: string }>(`/stores/${storeId}/designs`, {
        method: 'POST',
        body: {
          title: s(form, 'title'),
          brief: s(form, 'brief'),
          humanContribution: s(form, 'humanContribution'),
          productType: s(form, 'productType') ?? 'T-Shirt',
          style: s(form, 'style'),
          ...(s(form, 'opportunityId') ? { opportunityId: s(form, 'opportunityId') } : {}),
        },
      })
    ).id;
  } catch (e) {
    return err(e);
  }
  redirect(`/dashboard/design-studio/${id}`);
}

export async function designOpAction(_p: DState, form: FormData): Promise<DState> {
  const x = ids(form);
  if (!x) return { error: 'Geçersiz tasarım' };
  const op = String(form.get('op') ?? '');
  const versionId = String(form.get('versionId') ?? '');
  const base = `/stores/${x.storeId}/designs/${x.designId}`;
  try {
    switch (op) {
      case 'generate':
        await api(`${base}/generate`, { method: 'POST' });
        return done(x.designId, 'AI tasarım üretimi kuyruğa alındı (bir dakika kadar sürebilir).');
      case 'ip-review':
        await api(`${base}/ip-review`, { method: 'POST' });
        return done(x.designId, 'IP incelemesi kuyruğa alındı.');
      case 'remove-background':
        if (!UUID_RE.test(versionId)) return { error: 'Sürüm seçin' };
        await api(`${base}/versions/${versionId}/remove-background`, { method: 'POST', body: {} });
        return done(x.designId, 'Arka plan kaldırıldı (yeni sürüm).');
      case 'prepare-print':
        if (!UUID_RE.test(versionId)) return { error: 'Sürüm seçin' };
        await api(`${base}/versions/${versionId}/prepare-print`, {
          method: 'POST',
          body: {
            blueprintId: Number(s(form, 'blueprintId')),
            printProviderId: Number(s(form, 'printProviderId')),
            position: s(form, 'position') ?? 'front',
          },
        });
        return done(x.designId, 'Baskı dosyası hazırlandı (yeni sürüm).');
      case 'approve':
      case 'reject':
        await api(`${base}/status`, {
          method: 'PATCH',
          body: { status: op === 'approve' ? 'approved' : 'rejected' },
        });
        return done(x.designId, op === 'approve' ? 'Tasarım onaylandı.' : 'Tasarım reddedildi.');
      default:
        return { error: 'Bilinmeyen işlem' };
    }
  } catch (e) {
    return err(e);
  }
}

export async function uploadDesignAction(_p: DState, form: FormData): Promise<DState> {
  const x = ids(form);
  if (!x) return { error: 'Geçersiz tasarım' };
  const file = form.get('file');
  if (!(file instanceof File) || file.size === 0) return { error: 'Dosya seçin' };
  if (file.size > 25 * 1024 * 1024) return { error: 'Dosya 25 MB sınırını aşıyor' };
  try {
    const buf = Buffer.from(await file.arrayBuffer());
    await api(`/stores/${x.storeId}/designs/${x.designId}/upload`, {
      method: 'POST',
      body: { fileName: file.name.slice(0, 200), contentBase64: buf.toString('base64') },
    });
  } catch (e) {
    return err(e);
  }
  return done(x.designId, 'Yüklendi (yeni sürüm).');
}

export async function createPrintifyProductAction(_p: DState, form: FormData): Promise<DState> {
  const x = ids(form);
  if (!x) return { error: 'Geçersiz tasarım' };
  const variantIds = String(form.get('variantIds') ?? '')
    .split(',')
    .map((v) => Number(v.trim()))
    .filter((n) => Number.isInteger(n) && n > 0);
  try {
    const r = await api<{ note: string }>(
      `/stores/${x.storeId}/designs/${x.designId}/printify-product`,
      {
        method: 'POST',
        body: {
          title: s(form, 'title'),
          description: s(form, 'description'),
          variantIds,
          priceUsd: s(form, 'priceUsd'),
        },
      },
    );
    return done(x.designId, r.note);
  } catch (e) {
    return err(e);
  }
}

function done(designId: string, info: string): DState {
  revalidatePath(`/dashboard/design-studio/${designId}`);
  revalidatePath('/dashboard/design-studio');
  return { info };
}
