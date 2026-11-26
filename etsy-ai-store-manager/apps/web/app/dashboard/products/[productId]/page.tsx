import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, PageHeader } from '@/components/ui';
import { PublishRequestForm } from '@/components/printify-forms';
import { PriceRecommendationForm } from '@/components/finance-forms';
import { DecisionBadge } from '@/components/decision-badge';
import { RequestSeoForm, SeoDraftCard, type SeoDraft } from '@/components/seo-forms';

interface Profitability {
  country: string;
  targetContribution: string;
  worstDecision: string | null;
  complete: boolean;
  feesVerified: boolean;
  pendingPriceProposals: number;
  variants: Array<{
    variantId: string;
    title: string;
    price: string | null;
    currency: string;
    shippingRegion: string | null;
    result: {
      contribution: string;
      decision: string;
      complete: boolean;
      warnings: string[];
      totalFees: string;
    };
    recommendation: { minimumUnitPrice: string | null; suggestedUnitPrice: string | null } | null;
  }>;
}

export const metadata: Metadata = { title: 'Ürün' };

interface Detail {
  id: string;
  title: string;
  productType: string;
  status: string;
  etsyListingId: string | null;
  locked: boolean | null;
  syncedAt: string | null;
  variants: Array<{
    id: string;
    title: string;
    sku: string | null;
    price: string | null;
    currency: string;
    enabled: boolean;
    available: boolean | null;
    productionCost: string | null;
    shipping: Array<{ country: string; type: string; amount: string; currency: string }>;
  }>;
  costHistory: Array<{
    variant: string;
    cost_type: string;
    amount: string;
    currency: string;
    destination_country: string | null;
    valid_from: string;
    valid_to: string;
  }>;
  images: Array<{ url: string; alt: string | null }>;
}

export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ productId: string }>;
  searchParams: Promise<{ country?: string }>;
}) {
  const { productId } = await params;
  const sp = await searchParams;
  const country = /^[A-Z]{2}$/.test(sp.country ?? '') ? sp.country! : 'US';
  if (!/^[0-9a-f-]{36}$/i.test(productId)) notFound();
  const { current } = await loadStores();
  if (!current) notFound();
  let p: Detail;
  try {
    p = await api<Detail>(`/stores/${current.id}/products/${productId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const canPublish = (current.role === 'owner' || current.role === 'admin') && !p.locked;
  const prof = await api<Profitability>(
    `/stores/${current.id}/products/${productId}/profitability?country=${country}`,
  );
  const warnings = [...new Set(prof.variants.flatMap((v) => v.result.warnings))];
  const seoDrafts = await api<SeoDraft[]>(
    `/stores/${current.id}/seo-drafts?productId=${productId}`,
  );
  const path = `/dashboard/products/${productId}`;
  return (
    <>
      <PageHeader
        title={p.title}
        description={`${p.productType} · ${p.status}${p.etsyListingId ? ` · Etsy #${p.etsyListingId}` : ''}`}
      >
        <Link href="/dashboard/products" className="text-sm text-brand-600 hover:underline">
          ← Ürünler
        </Link>
      </PageHeader>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Varyantlar ve maliyetler" className="lg:col-span-2">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-line text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Varyant</th>
                  <th className="py-2 pr-3">Satış</th>
                  <th className="py-2 pr-3">Üretim</th>
                  <th className="py-2 pr-3">Kargo (ilk / ek)</th>
                  <th className="py-2">Durum</th>
                </tr>
              </thead>
              <tbody>
                {p.variants.map((v) => {
                  const us = v.shipping.filter((s) => s.country === 'US');
                  const first = us.find((s) => s.type === 'shipping_first_item');
                  const add = us.find((s) => s.type === 'shipping_additional_item');
                  return (
                    <tr key={v.id} className="border-b border-line last:border-0 align-top">
                      <td className="py-2 pr-3">
                        {v.title}
                        <span className="block text-xs text-slate-500">{v.sku}</span>
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{formatMoney(v.price, v.currency)}</td>
                      <td className="py-2 pr-3 tabular-nums">
                        {formatMoney(v.productionCost, 'USD')}
                      </td>
                      <td className="py-2 pr-3 tabular-nums">
                        {first
                          ? `${formatMoney(first.amount, first.currency)} / ${formatMoney(add?.amount, add?.currency ?? 'USD')} (US)`
                          : '—'}
                        <span className="block text-xs text-slate-500">
                          {new Set(v.shipping.map((s) => s.country)).size} bölge
                        </span>
                      </td>
                      <td className="py-2">
                        {v.enabled ? 'aktif' : 'kapalı'}
                        {v.available === false ? ' · stok yok' : ''}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Son Printify senkronizasyonu: {formatDate(p.syncedAt)}. Katkı (kâr) hesabı Finans ve Kâr
            modülünde yapılır.
          </p>
        </Card>
        <div className="space-y-6">
          {p.images[0] && (
            <img
              src={p.images[0].url}
              alt={p.images[0].alt ?? ''}
              className="w-full rounded-xl border border-line"
            />
          )}
          <Card title="Etsy’de yayınla">
            {canPublish ? (
              <PublishRequestForm storeId={current.id} productId={p.id} country={country} />
            ) : (
              <p className="text-sm text-slate-500">
                {p.locked
                  ? 'Ürün Printify’da kilitli (yayınlama sürüyor).'
                  : 'Yönetici yetkisi gerekir.'}
              </p>
            )}
          </Card>
        </div>
      </div>
      <Card
        title={`Kârlılık (${prof.country} alıcısı, hedef ${prof.targetContribution})`}
        className="mt-6"
      >
        <form className="mb-3 flex items-end gap-2 text-sm">
          <label>
            <span className="mb-1 block text-slate-600">Alıcı ülkesi</span>
            <input
              name="country"
              defaultValue={country}
              maxLength={2}
              className="w-20 rounded-lg border border-line px-2 py-1.5 uppercase"
            />
          </label>
          <button className="rounded-lg border border-line px-3 py-1.5">Hesapla</button>
          <span className="ml-auto">
            <DecisionBadge decision={prof.worstDecision} />
          </span>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm" aria-label="Varyant kârlılığı">
            <thead className="border-b border-line text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">Varyant</th>
                <th className="py-2 pr-3">Fiyat</th>
                <th className="py-2 pr-3">Etsy ücretleri</th>
                <th className="py-2 pr-3">Katkı</th>
                <th className="py-2 pr-3">Karar</th>
                <th className="py-2">Önerilen fiyat</th>
              </tr>
            </thead>
            <tbody>
              {prof.variants.map((v) => (
                <tr key={v.variantId} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3">
                    {v.title}
                    <span className="block text-xs text-slate-500">
                      kargo bölgesi: {v.shippingRegion ?? '—'}
                    </span>
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{formatMoney(v.price, v.currency)}</td>
                  <td className="py-2 pr-3 tabular-nums">
                    {formatMoney(v.result.totalFees, v.currency)}
                  </td>
                  <td className="py-2 pr-3 tabular-nums font-medium">
                    {formatMoney(v.result.contribution, v.currency)}
                  </td>
                  <td className="py-2 pr-3">
                    <DecisionBadge decision={v.result.decision} />
                  </td>
                  <td className="py-2 tabular-nums">
                    {v.recommendation?.suggestedUnitPrice
                      ? formatMoney(v.recommendation.suggestedUnitPrice, v.currency)
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {warnings.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-800">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        {(current.role === 'owner' || current.role === 'admin') && (
          <div className="mt-4">
            <PriceRecommendationForm
              storeId={current.id}
              productId={p.id}
              country={country}
              hasProposals={prof.pendingPriceProposals > 0}
            />
          </div>
        )}
      </Card>
      {p.costHistory.length > 0 && (
        <Card title="Maliyet geçmişi (değişen maliyetler)" className="mt-6">
          <ul className="divide-y divide-line text-sm">
            {p.costHistory.map((h, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-2 py-2">
                <span>
                  {h.variant} · {h.cost_type}
                  {h.destination_country ? ` · ${h.destination_country}` : ''}
                </span>
                <span className="tabular-nums text-slate-600">
                  {formatMoney(h.amount, h.currency)} ({formatDate(h.valid_from)} –{' '}
                  {formatDate(h.valid_to)})
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="SEO (Printify ürünü)" className="mt-6">
        {canPublish && (
          <div className="mb-4">
            <RequestSeoForm
              storeId={current.id}
              target={{ productId }}
              languages={['en']}
              path={path}
            />
            <p className="mt-1 text-xs text-slate-500">
              Onaylanınca başlık, açıklama ve etiketler Printify’da güncellenir; ürün Etsy’deyse
              yalnızca bu alanlar yeniden gönderilir.
            </p>
          </div>
        )}
        {seoDrafts.length === 0 ? (
          <p className="text-sm text-slate-500">Henüz öneri yok.</p>
        ) : (
          <div className="space-y-4">
            {seoDrafts.slice(0, 3).map((d) => (
              <SeoDraftCard
                key={d.id}
                storeId={current.id}
                d={d}
                canEdit={canPublish}
                path={path}
              />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
