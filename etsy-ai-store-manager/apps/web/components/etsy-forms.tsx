'use client';

import { useActionState } from 'react';
import type { ApprovalDto, ListingDto } from '@esm/shared';
import {
  connectEtsyAction,
  decideApprovalAction,
  disconnectEtsyAction,
  requestListingChangeAction,
  syncEtsyAction,
  type ActionState,
} from '@/app/dashboard/etsy/actions';

const btn =
  'rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-60 bg-navy-900 text-white hover:bg-navy-800';
const btnGhost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';
const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';

function Feedback({ s }: { s: ActionState }) {
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

export function ConnectEtsyButton({ storeId, label }: { storeId: string; label: string }) {
  const [s, action, pending] = useActionState<ActionState, FormData>(connectEtsyAction, {});
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="storeId" value={storeId} />
      <button className={btn} disabled={pending}>
        {pending ? 'Yönlendiriliyor…' : label}
      </button>
      <Feedback s={s} />
    </form>
  );
}

export function SyncEtsyButton({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<ActionState, FormData>(syncEtsyAction, {});
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="storeId" value={storeId} />
      <button className={btnGhost} disabled={pending}>
        {pending ? 'Kuyruğa alınıyor…' : 'Şimdi senkronize et'}
      </button>
      <Feedback s={s} />
    </form>
  );
}

export function DisconnectEtsyForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<ActionState, FormData>(disconnectEtsyAction, {});
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="storeId" value={storeId} />
      <label className="block text-sm text-slate-600">
        Bağlantıyı kesmek için <strong>BAĞLANTIYI KES</strong> yazın (içe aktarılan veriler korunur)
        <input name="confirm" className={`${input} mt-1`} autoComplete="off" />
      </label>
      <button
        className="rounded-lg border border-red-200 bg-white px-3 py-2 text-sm text-red-700 hover:bg-red-50"
        disabled={pending}
      >
        Bağlantıyı kes
      </button>
      <Feedback s={s} />
    </form>
  );
}

export function ListingChangeForm({ storeId, listing }: { storeId: string; listing: ListingDto }) {
  const [s, action, pending] = useActionState<ActionState, FormData>(
    requestListingChangeAction,
    {},
  );
  const original = JSON.stringify({
    title: listing.title,
    description: listing.description ?? '',
    tags: listing.tags,
    state: listing.state,
  });
  return (
    <form action={action} className="space-y-4" aria-label="İlan değişikliği">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="listingId" value={listing.id} />
      <input type="hidden" name="original" value={original} />
      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">Başlık (en fazla 140)</span>
        <input name="title" defaultValue={listing.title} maxLength={140} className={input} />
      </label>
      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">
          Etiketler (virgülle, en fazla 13, her biri ≤ 20)
        </span>
        <input name="tags" defaultValue={listing.tags.join(', ')} className={input} />
      </label>
      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">Açıklama</span>
        <textarea
          name="description"
          defaultValue={listing.description ?? ''}
          rows={8}
          className={input}
        />
      </label>
      {(listing.state === 'active' || listing.state === 'inactive') && (
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Durum</span>
          <select name="state" defaultValue={listing.state} className={input}>
            <option value="active">Aktif</option>
            <option value="inactive">Pasif</option>
          </select>
        </label>
      )}
      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">
          Gerekçe (onay ekranında görünür)
        </span>
        <input
          name="reason"
          required
          minLength={3}
          className={input}
          placeholder="Ör. arama terimleriyle daha iyi eşleşme"
        />
      </label>
      <div className="flex items-center gap-3">
        <button className={btn} disabled={pending}>
          {pending ? 'Gönderiliyor…' : 'Değişiklik önerisi oluştur'}
        </button>
        <Feedback s={s} />
      </div>
      <p className="text-xs text-slate-500">
        Yalnızca değiştirdiğiniz alanlar gönderilir. Onaydan önce Etsy’deki ilan yeniden okunur; bu
        arada Etsy’de değişmişse üzerine yazılmaz.
      </p>
    </form>
  );
}

export function ApprovalCard({ storeId, a }: { storeId: string; a: ApprovalDto }) {
  const [s, action, pending] = useActionState<ActionState, FormData>(decideApprovalAction, {});
  const changes = (a.payload.changes ?? {}) as Record<string, unknown>;
  const baseline = (a.payload.baseline ?? {}) as Record<string, unknown>;
  return (
    <article className="rounded-xl border border-line bg-white p-4" aria-label={`Onay: ${a.title}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-navy-900">{a.title}</h3>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${a.riskLevel === 'high' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'}`}
        >
          Risk: {a.riskLevel}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <Item k="Ne yapılacak?" v={a.what} />
        <Item k="Neden?" v={a.why} />
        <Item k="Beklenen fayda" v={a.expectedBenefit ?? '—'} />
        <Item k="Tahmini maliyet" v={`${a.estimatedCost ?? '0'} ${a.costCurrency ?? ''}`} />
        <Item k="Kârlılığa etkisi" v={a.profitImpact ?? '—'} />
        <Item k="API işlemi" v={a.apiOperation} mono />
      </dl>
      {Object.keys(changes).length > 0 && (
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-2">Alan</th>
              <th className="py-1 pr-2">Şu an</th>
              <th className="py-1">Önerilen</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(changes).map(([k, v]) => (
              <tr key={k} className="border-t border-line align-top">
                <td className="py-1 pr-2 font-medium">{k}</td>
                <td className="py-1 pr-2 text-slate-500">{fmt(baseline[k])}</td>
                <td className="py-1 text-navy-900">{fmt(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {a.status === 'pending' ? (
        <form action={action} className="mt-4 flex flex-wrap items-end gap-2">
          <input type="hidden" name="storeId" value={storeId} />
          <input type="hidden" name="approvalId" value={a.id} />
          <input type="hidden" name="requiresReauth" value={String(a.requiresReauth)} />
          {a.requiresReauth && (
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">Parola (yeniden doğrulama)</span>
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                className={input}
              />
            </label>
          )}
          <button name="decision" value="approve" className={btn} disabled={pending}>
            Onayla
          </button>
          <button name="decision" value="reject" className={btnGhost} disabled={pending}>
            Reddet
          </button>
          <Feedback s={s} />
        </form>
      ) : (
        <p className="mt-3 text-sm text-slate-600">
          Durum: <strong>{a.status}</strong>
          {a.executionResult && 'error' in a.executionResult
            ? ` — ${String(a.executionResult.error)}`
            : ''}
        </p>
      )}
    </article>
  );
}

function Item({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
      <dd className={mono ? 'font-mono text-xs text-slate-700' : 'text-slate-800'}>{v}</dd>
    </div>
  );
}

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.join(', ');
  if (v === null || v === undefined || v === '') return '—';
  const s = String(v);
  return s.length > 160 ? `${s.slice(0, 160)}…` : s;
}
