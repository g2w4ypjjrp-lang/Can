'use client';

import { useActionState } from 'react';
import {
  priceRecommendationAction,
  recomputeAction,
  simulateAction,
  verifyFeeRuleAction,
  type FState,
} from '@/app/dashboard/finance/actions';
import { DecisionBadge } from './decision-badge';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const label = 'mb-1 block text-sm font-medium text-slate-700';
const btn =
  'rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

function Fb({ s }: { s: FState }) {
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

const FIELDS: Array<[string, string, string]> = [
  ['unitPrice', 'Satış fiyatı (birim)', '29.99'],
  ['quantity', 'Adet', '1'],
  ['shippingCharged', 'Alıcıdan alınan kargo', '0'],
  ['discount', 'İndirim (sipariş)', '0'],
  ['productionCostPerUnit', 'Üretim maliyeti (USD/birim)', '10.85'],
  ['fulfillmentShippingFirst', 'Üretici kargo (ilk ürün, USD)', '4.75'],
  ['fulfillmentShippingAdditional', 'Üretici kargo (ek ürün, USD)', '0'],
  ['adCostAllocated', 'Sipariş başı reklam payı', ''],
  ['buyerCountry', 'Alıcı ülkesi', 'US'],
];

export function SimulatorForm({ storeId, currency }: { storeId: string; currency: string }) {
  const [s, action, pending] = useActionState<FState, FormData>(simulateAction, {});
  const r = s.result?.result;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form action={action} className="grid gap-3 sm:grid-cols-2" aria-label="Kârlılık simülatörü">
        <input type="hidden" name="storeId" value={storeId} />
        {FIELDS.map(([name, text, def]) => (
          <label key={name}>
            <span className={label}>{text}</span>
            <input
              name={name}
              defaultValue={def}
              placeholder={name === 'adCostAllocated' ? 'politika varsayılanı' : undefined}
              className={input}
              inputMode={name === 'buyerCountry' ? 'text' : 'decimal'}
            />
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
          <input type="checkbox" name="offsiteAds" className="h-4 w-4 accent-brand-600" /> Sipariş
          Offsite Ads üzerinden geldi
        </label>
        <div className="sm:col-span-2 flex items-center gap-3">
          <button className={btn} disabled={pending}>
            {pending ? 'Hesaplanıyor…' : 'Hesapla'}
          </button>
          <Fb s={s} />
        </div>
      </form>
      <div aria-live="polite">
        {r ? (
          <div className="space-y-3" data-testid="simulation-result">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-2xl font-semibold tabular-nums text-navy-900">
                {r.contribution} {r.currency}
              </span>
              <DecisionBadge decision={r.decision} />
            </div>
            <p className="text-sm text-slate-600">
              Net gelir {r.netRevenue} · Etsy ücretleri {r.totalFees} · reklam öncesi katkı{' '}
              {r.contributionBeforeAds} · vergi sonrası tahmin {r.contributionAfterTax}
            </p>
            {s.result?.recommendation.suggestedUnitPrice && (
              <p className="text-sm text-navy-800">
                Hedef katkı için en düşük fiyat{' '}
                <strong>{s.result.recommendation.minimumUnitPrice}</strong>, önerilen{' '}
                <strong>{s.result.recommendation.suggestedUnitPrice}</strong> {currency}
              </p>
            )}
            {r.warnings.length > 0 && (
              <ul className="list-disc space-y-1 rounded-lg border border-amber-200 bg-amber-50 py-2 pl-8 pr-3 text-xs text-amber-900">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">Kalem</th>
                  <th className="py-1">Matrah</th>
                  <th className="py-1">Oran / sabit</th>
                  <th className="py-1 text-right">Tutar</th>
                </tr>
              </thead>
              <tbody>
                {r.breakdown.map((l) => (
                  <tr key={l.code} className="border-t border-line">
                    <td className="py-1 pr-2">{l.label}</td>
                    <td className="py-1 pr-2 tabular-nums">{l.base ?? ''}</td>
                    <td className="py-1 pr-2 tabular-nums">
                      {[l.rate, l.fixed].filter(Boolean).join(' + ')}
                    </td>
                    <td className="py-1 text-right tabular-nums">{l.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            Fiyat ve maliyetleri girip hesaplayın. Sonuç tüm ücret kalemlerinin matrahıyla birlikte
            gösterilir.
          </p>
        )}
      </div>
    </div>
  );
}

export function VerifyRuleButton({ storeId, ruleId }: { storeId: string; ruleId: string }) {
  const [s, action, pending] = useActionState<FState, FormData>(verifyFeeRuleAction, {});
  return (
    <form action={action}>
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="ruleId" value={ruleId} />
      <button className={ghost} disabled={pending}>
        Doğrula
      </button>
      <Fb s={s} />
    </form>
  );
}

export function RecomputeButton({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<FState, FormData>(recomputeAction, {});
  return (
    <form action={action} className="space-y-1">
      <input type="hidden" name="storeId" value={storeId} />
      <button className={ghost} disabled={pending}>
        Sipariş katkılarını yeniden hesapla
      </button>
      <Fb s={s} />
    </form>
  );
}

export function PriceRecommendationForm({
  storeId,
  productId,
  country,
  hasProposals,
}: {
  storeId: string;
  productId: string;
  country: string;
  hasProposals: boolean;
}) {
  const [s, action, pending] = useActionState<FState, FormData>(priceRecommendationAction, {});
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="productId" value={productId} />
      <input type="hidden" name="country" value={country} />
      <button name="step" value="recommend" className={ghost} disabled={pending}>
        Fiyat önerisi oluştur
      </button>
      {hasProposals && (
        <button name="step" value="request" className={btn} disabled={pending}>
          Önerilen fiyatları onaya gönder
        </button>
      )}
      <Fb s={s} />
    </form>
  );
}
