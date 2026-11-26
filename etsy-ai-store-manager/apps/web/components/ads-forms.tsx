'use client';

import { useActionState } from 'react';
import {
  accountAction,
  confirmManualAction,
  importCsvAction,
  ledgerMappingAction,
  metaConnectAction,
  policyAction,
  proposalAction,
  submitProposalAction,
  syncAction,
  type AState,
} from '@/app/dashboard/ads/actions';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const label = 'mb-1 block text-xs font-medium text-slate-600';
const btn =
  'rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

function Fb({ s }: { s: AState }) {
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

export function PolicyForm({
  storeId,
  policy,
}: {
  storeId: string;
  policy: {
    dailyCap: string;
    monthlyCap: string | null;
    currency: string;
    minClicksForDecision: number;
    configured: boolean;
  };
}) {
  const [s, action, pending] = useActionState<AState, FormData>(policyAction, {});
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-4" aria-label="Bütçe sınırı">
      <input type="hidden" name="storeId" value={storeId} />
      <label>
        <span className={label}>Günlük üst sınır</span>
        <input
          name="dailyCap"
          required
          inputMode="decimal"
          defaultValue={policy.configured ? policy.dailyCap : ''}
          className={input}
        />
      </label>
      <label>
        <span className={label}>Aylık üst sınır (isteğe bağlı)</span>
        <input
          name="monthlyCap"
          inputMode="decimal"
          defaultValue={policy.monthlyCap ?? ''}
          className={input}
        />
      </label>
      <label>
        <span className={label}>Para birimi</span>
        <input
          name="currency"
          defaultValue={policy.currency}
          maxLength={3}
          className={`${input} uppercase`}
        />
      </label>
      <label>
        <span className={label}>Karar için en az tıklama</span>
        <input
          name="minClicks"
          type="number"
          min={10}
          max={10000}
          defaultValue={policy.minClicksForDecision}
          className={input}
        />
      </label>
      <div className="flex items-center gap-3 sm:col-span-4">
        <button className={btn} disabled={pending}>
          Sınırı kaydet
        </button>
        <Fb s={s} />
      </div>
    </form>
  );
}

export function ProposalForm({ storeId, cap }: { storeId: string; cap: string }) {
  const [s, action, pending] = useActionState<AState, FormData>(proposalAction, {});
  return (
    <form action={action} className="flex flex-wrap items-center gap-2" aria-label="Bütçe önerisi">
      <input type="hidden" name="storeId" value={storeId} />
      <input
        name="total"
        inputMode="decimal"
        placeholder={`Toplam günlük (en fazla ${cap})`}
        className="rounded-lg border border-line px-3 py-2 text-sm"
        aria-label="Toplam günlük bütçe"
      />
      <button className={btn} disabled={pending}>
        Dağıtım önerisi oluştur
      </button>
      <Fb s={s} />
    </form>
  );
}

export function SubmitProposalForm({
  storeId,
  proposalId,
}: {
  storeId: string;
  proposalId: string;
}) {
  const [s, action, pending] = useActionState<AState, FormData>(submitProposalAction, {});
  return (
    <form
      action={action}
      className="mt-3 flex flex-wrap items-center gap-2"
      aria-label="Öneriyi onaya gönder"
    >
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="proposalId" value={proposalId} />
      <input
        name="reason"
        placeholder="Gerekçe"
        className="rounded-lg border border-line px-3 py-2 text-sm"
        aria-label="Gerekçe"
      />
      <button className={btn} disabled={pending}>
        Onaya gönder
      </button>
      <Fb s={s} />
    </form>
  );
}

export function ConfirmManualForm({
  storeId,
  approvalId,
}: {
  storeId: string;
  approvalId: string;
}) {
  const [s, action, pending] = useActionState<AState, FormData>(confirmManualAction, {});
  return (
    <form
      action={action}
      className="mt-2 flex flex-wrap items-center gap-2"
      aria-label="Manuel uygulamayı onayla"
    >
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="approvalId" value={approvalId} />
      <input
        name="note"
        required
        minLength={3}
        placeholder="Ne yaptınız? (ör. Etsy Ads panelinde bütçeleri güncelledim)"
        className="min-w-[280px] flex-1 rounded-lg border border-line px-3 py-2 text-sm"
        aria-label="Not"
      />
      <button className={btn} disabled={pending}>
        Uyguladım
      </button>
      <Fb s={s} />
    </form>
  );
}

export function AccountForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<AState, FormData>(accountAction, {});
  return (
    <form action={action} className="grid gap-2 sm:grid-cols-5" aria-label="Reklam hesabı ekle">
      <input type="hidden" name="storeId" value={storeId} />
      <select name="platform" className={input} aria-label="Platform">
        <option value="etsy_ads">Etsy Ads</option>
        <option value="google_ads">Google Ads</option>
        <option value="pinterest_ads">Pinterest Ads</option>
        <option value="tiktok_ads">TikTok Ads</option>
        <option value="meta_ads">Meta Ads (manuel)</option>
      </select>
      <input
        name="externalAccountId"
        required
        placeholder="Hesap kimliği"
        className={input}
        aria-label="Hesap kimliği"
      />
      <input name="name" required placeholder="Ad" className={input} aria-label="Hesap adı" />
      <input
        name="currency"
        defaultValue="USD"
        maxLength={3}
        className={`${input} uppercase`}
        aria-label="Para birimi"
      />
      <button className={ghost} disabled={pending}>
        Ekle
      </button>
      <div className="sm:col-span-5">
        <Fb s={s} />
      </div>
    </form>
  );
}

export function MetaConnectForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<AState, FormData>(metaConnectAction, {});
  return (
    <form
      action={action}
      className="grid gap-2 sm:grid-cols-3"
      aria-label="Meta bağlantısı"
      autoComplete="off"
    >
      <input type="hidden" name="storeId" value={storeId} />
      <input
        name="adAccountId"
        required
        placeholder="act_1234567890"
        className={input}
        aria-label="Meta reklam hesabı"
      />
      <input
        name="accessToken"
        required
        type="password"
        placeholder="Erişim jetonu (ads_read)"
        className={input}
        aria-label="Erişim jetonu"
      />
      <button className={ghost} disabled={pending}>
        Doğrula ve bağla
      </button>
      <p className="text-xs text-slate-500 sm:col-span-3">
        Jeton yalnızca sunucuda, şifreli saklanır ve tarayıcıya geri gönderilmez. Salt okuma
        (ads_read) yeterlidir.
      </p>
      <div className="sm:col-span-3">
        <Fb s={s} />
      </div>
    </form>
  );
}

export function CsvImportForm({
  storeId,
  accounts,
}: {
  storeId: string;
  accounts: Array<{ id: string; label: string }>;
}) {
  const [s, action, pending] = useActionState<AState, FormData>(importCsvAction, {});
  return (
    <form action={action} className="space-y-2" aria-label="Rapor içe aktar">
      <input type="hidden" name="storeId" value={storeId} />
      <select name="adAccountId" className={input} aria-label="Hesap">
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label}
          </option>
        ))}
      </select>
      <textarea
        name="csv"
        rows={4}
        className={`${input} font-mono text-xs`}
        aria-label="CSV"
        placeholder={
          'date,campaign,impressions,clicks,spend,orders,revenue\n2026-11-20,Botanical tees,5000,80,20.00,3,90.00'
        }
      />
      <input
        type="file"
        name="file"
        accept=".csv,text/csv"
        className="text-sm"
        aria-label="CSV dosyası"
      />
      <button className={ghost} disabled={pending || !accounts.length}>
        İçe aktar
      </button>
      <Fb s={s} />
    </form>
  );
}

export function LedgerMappingForm({
  storeId,
  types,
  mapped,
}: {
  storeId: string;
  types: Array<{
    ledgerType: string;
    entries: number;
    total: string;
    currency: string;
    example: string | null;
    suggested: boolean;
  }>;
  mapped: string[];
}) {
  const [s, action, pending] = useActionState<AState, FormData>(ledgerMappingAction, {});
  return (
    <form action={action} className="space-y-2" aria-label="Etsy defter eşlemesi">
      <input type="hidden" name="storeId" value={storeId} />
      {types.length === 0 && (
        <p className="text-sm text-slate-500">
          Henüz defter kaydı yok. “Etsy Ads harcamasını defterden al”ı kaydedin; içe aktarma başlar.
        </p>
      )}
      <ul className="space-y-1 text-sm">
        {types.map((t) => (
          <li key={`${t.ledgerType}-${t.currency}`}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                name="types"
                value={t.ledgerType}
                defaultChecked={mapped.includes(t.ledgerType)}
                disabled={/offsite/i.test(t.ledgerType)}
                className="h-4 w-4 accent-brand-600"
              />
              <code>{t.ledgerType}</code> · {t.entries} kayıt · {t.total} {t.currency}
              {t.example ? ` · “${t.example}”` : ''}
              {t.suggested && (
                <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">
                  Etsy Ads olabilir
                </span>
              )}
              {/offsite/i.test(t.ledgerType) && (
                <span className="text-xs text-slate-500">(sipariş ücreti — Profit Engine’de)</span>
              )}
            </label>
          </li>
        ))}
      </ul>
      <button className={ghost} disabled={pending}>
        Etsy Ads harcamasını defterden al
      </button>
      <Fb s={s} />
    </form>
  );
}

export function SyncButton({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<AState, FormData>(syncAction, {});
  return (
    <form action={action} className="flex items-center gap-2">
      <input type="hidden" name="storeId" value={storeId} />
      <button className={ghost} disabled={pending}>
        Raporları yenile
      </button>
      <Fb s={s} />
    </form>
  );
}
