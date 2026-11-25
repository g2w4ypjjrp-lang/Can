'use client';

import { useActionState } from 'react';
import {
  decideOpportunityAction,
  startResearchAction,
  type MState,
} from '@/app/dashboard/market-research/actions';
import { DecisionBadge } from './decision-badge';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';

export function ResearchForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<MState, FormData>(startResearchAction, {});
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-4" aria-label="Araştırma başlat">
      <input type="hidden" name="storeId" value={storeId} />
      <label className="sm:col-span-2">
        <span className="mb-1 block text-sm font-medium text-slate-700">
          Konu / ana anahtar kelime (İngilizce)
        </span>
        <input
          name="query"
          required
          minLength={2}
          maxLength={80}
          placeholder="ör. plant mug"
          className={input}
        />
      </label>
      <label>
        <span className="mb-1 block text-sm font-medium text-slate-700">Alıcı ülkesi</span>
        <input
          name="buyerCountry"
          maxLength={2}
          placeholder="US (boş = global)"
          className={`${input} uppercase`}
        />
      </label>
      <label>
        <span className="mb-1 block text-sm font-medium text-slate-700">
          Ek kelimeler (virgülle, en fazla 4)
        </span>
        <input name="keywords" placeholder="gardener gift, plant lover" className={input} />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-3">
        <input type="checkbox" name="useWebSearch" className="h-4 w-4 accent-brand-600" />
        Web’de trend ve sezon araştırması da yap (Claude web araması; ek maliyet)
      </label>
      <div className="flex items-center gap-3">
        <button
          className="w-full rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60"
          disabled={pending}
        >
          {pending ? 'Başlatılıyor…' : 'Araştırmayı başlat'}
        </button>
      </div>
      {s.error && (
        <p role="alert" className="text-sm text-red-700 sm:col-span-4">
          {s.error}
        </p>
      )}
    </form>
  );
}

export interface Opportunity {
  id: string;
  title: string;
  productType: string | null;
  targetCustomer: string | null;
  keywords: string[];
  competitionLevel: string | null;
  demandSignals: Array<{ signal: string; source: string; isEstimate: boolean }>;
  estSalePrice: string | null;
  estProductionCost: string | null;
  estContribution: string | null;
  estDecision: string | null;
  score: number | null;
  scoreBreakdown: {
    profit?: number;
    competition?: number;
    demand?: number;
    ipPenalty?: number;
    costKnown?: boolean;
    notes?: string[];
  };
  confidence: string;
  personalization: boolean;
  ipRisk: string | null;
  ipRiskNotes: string | null;
  rationale: string | null;
  status: string;
  rejectionReason: string | null;
  researchQuery?: string;
}

export function OpportunityCard({
  storeId,
  o,
  canEdit,
}: {
  storeId: string;
  o: Opportunity;
  canEdit: boolean;
}) {
  const [s, action, pending] = useActionState<MState, FormData>(decideOpportunityAction, {});
  return (
    <article
      className="rounded-xl border border-line bg-white p-4"
      aria-label={`Fırsat: ${o.title}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-navy-900">{o.title}</h3>
          <p className="text-xs text-slate-500">
            {o.productType} · {o.targetCustomer}
            {o.researchQuery ? ` · araştırma: ${o.researchQuery}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="rounded-full bg-navy-900 px-2.5 py-0.5 text-xs font-semibold text-white"
            title="Fırsat puanı (0-100)"
          >
            {o.score ?? '—'}
          </span>
          <DecisionBadge decision={o.estDecision} />
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">Önerilen fiyat</dt>
          <dd>{o.estSalePrice ? `$${o.estSalePrice}` : '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Üretim maliyeti</dt>
          <dd>{o.estProductionCost ? `$${o.estProductionCost}` : 'bilinmiyor'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Tahmini katkı</dt>
          <dd className="font-medium">{o.estContribution ? `$${o.estContribution}` : '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Rekabet · güven</dt>
          <dd>
            {o.competitionLevel} · {o.confidence}
          </dd>
        </div>
      </dl>
      {o.rationale && <p className="mt-3 text-sm text-slate-700">{o.rationale}</p>}
      {o.demandSignals.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slate-600">
          {o.demandSignals.map((d, i) => (
            <li key={i}>
              • {d.signal}{' '}
              <span className={d.isEstimate ? 'text-amber-700' : 'text-emerald-700'}>
                [{d.isEstimate ? 'tahmin' : 'veri'}]
              </span>{' '}
              {d.source.startsWith('http') ? (
                <a
                  href={d.source}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-600 hover:underline"
                >
                  kaynak ↗
                </a>
              ) : (
                <span>({d.source === 'etsy_api' ? 'Etsy API' : 'doğrulanmamış'})</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Etiketler: {o.keywords.join(', ')} · IP riski: {o.ipRisk}
        {o.ipRiskNotes ? ` (${o.ipRiskNotes})` : ''}
        {o.personalization ? ' · kişiselleştirilebilir' : ''}
      </p>
      <p className="mt-1 text-xs text-slate-400">
        Puan: kâr {o.scoreBreakdown.profit ?? '—'} · düşük rekabet{' '}
        {o.scoreBreakdown.competition ?? '—'} · ilgi {o.scoreBreakdown.demand ?? '—'}
        {o.scoreBreakdown.ipPenalty ? ` · IP cezası −${o.scoreBreakdown.ipPenalty}` : ''}
      </p>
      {o.status === 'rejected' && o.rejectionReason && (
        <p className="mt-2 text-sm text-red-700">Elendi: {o.rejectionReason}</p>
      )}
      {canEdit && (
        <form action={action} className="mt-3 flex flex-wrap items-center gap-2">
          <input type="hidden" name="storeId" value={storeId} />
          <input type="hidden" name="opportunityId" value={o.id} />
          {o.status !== 'shortlisted' && (
            <button
              name="status"
              value="shortlisted"
              disabled={pending}
              className="rounded-lg bg-navy-900 px-3 py-1.5 text-xs font-semibold text-white"
            >
              Kısa listeye al
            </button>
          )}
          {o.status !== 'rejected' && (
            <button
              name="status"
              value="rejected"
              disabled={pending}
              className="rounded-lg border border-line px-3 py-1.5 text-xs"
            >
              Reddet
            </button>
          )}
          {o.status !== 'new' && (
            <button
              name="status"
              value="new"
              disabled={pending}
              className="rounded-lg border border-line px-3 py-1.5 text-xs"
            >
              Sıfırla
            </button>
          )}
          <span className="text-xs text-slate-500">Durum: {o.status}</span>
          {s.error && (
            <span role="alert" className="text-xs text-red-700">
              {s.error}
            </span>
          )}
        </form>
      )}
    </article>
  );
}
