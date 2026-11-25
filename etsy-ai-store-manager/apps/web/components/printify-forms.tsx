'use client';

import { useActionState } from 'react';
import {
  connectPrintifyAction,
  requestPublishAction,
  syncPrintifyAction,
  type PState,
} from '@/app/dashboard/printify/actions';

const btn =
  'rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

function Fb({ s }: { s: PState }) {
  if (s.error)
    return (
      <p role="alert" className="text-sm text-red-700">
        {s.error}
      </p>
    );
  if (s.info)
    return (
      <p role="status" className="text-sm text-emerald-700">
        {s.info}
      </p>
    );
  return null;
}

export function ConnectPrintifyForm({
  storeId,
  shops,
}: {
  storeId: string;
  shops: Array<{ id: number; title: string; salesChannel: string }>;
}) {
  const [s, action, pending] = useActionState<PState, FormData>(connectPrintifyAction, {});
  return (
    <form action={action} className="space-y-3" aria-label="Printify bağlantısı">
      <input type="hidden" name="storeId" value={storeId} />
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium text-slate-700">
          Bu mağazaya bağlanacak Printify mağazası
        </legend>
        {shops.map((sh) => (
          <label key={sh.id} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="shopId"
              value={sh.id}
              defaultChecked={sh.salesChannel === 'etsy'}
              className="accent-brand-600"
            />
            {sh.title} <span className="text-slate-500">({sh.salesChannel})</span>
          </label>
        ))}
      </fieldset>
      <button className={btn} disabled={pending}>
        {pending ? 'Bağlanıyor…' : 'Printify mağazasını bağla'}
      </button>
      <Fb s={s} />
    </form>
  );
}

export function SyncPrintifyButton({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<PState, FormData>(syncPrintifyAction, {});
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="storeId" value={storeId} />
      <button className={ghost} disabled={pending}>
        Şimdi senkronize et
      </button>
      <Fb s={s} />
    </form>
  );
}

export function PublishRequestForm({ storeId, productId }: { storeId: string; productId: string }) {
  const [s, action, pending] = useActionState<PState, FormData>(requestPublishAction, {});
  return (
    <form action={action} className="space-y-2" aria-label="Yayın isteği">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="productId" value={productId} />
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">Gerekçe</span>
        <input
          name="reason"
          required
          minLength={3}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm"
          placeholder="Ör. yeni sezon koleksiyonu"
        />
      </label>
      <button className={btn} disabled={pending}>
        Etsy’de yayınlama isteği oluştur
      </button>
      <Fb s={s} />
    </form>
  );
}
