import type { Metadata } from 'next';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import { ConnectPrintifyForm, SyncPrintifyButton } from '@/components/printify-forms';

export const metadata: Metadata = { title: 'Printify' };

interface Status {
  configured: boolean;
  webhooksConfigured: boolean;
  status: string;
  shopId: string | null;
  shopTitle: string | null;
  salesChannel: string | null;
  lastSyncedAt: string | null;
  lastError: string | null;
  lineCostBasis: string;
  counts: { products: number; orders: number; problem_orders: number };
}
interface Blueprint {
  id: number;
  title: string;
  brand: string;
  model: string;
  image: string | null;
}
interface Comparison {
  providers: Array<{
    printProviderId: number;
    title: string;
    location: string | null;
    productionTime: string | null;
    variantCount: number;
    shipping: {
      country: string;
      firstItem: string | null;
      additionalItem: string | null;
      currency: string | null;
      handlingDays: number | null;
    } | null;
  }>;
  note: string;
}

type SP = Promise<{ q?: string; bp?: string; country?: string }>;

export default async function PrintifyPage({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const st = await api<Status>(`/stores/${current.id}/integrations/printify`);
  const connected = st.status === 'active';
  const isOwner = current.role === 'owner';

  let shops: Array<{ id: number; title: string; salesChannel: string }> = [];
  let shopsError: string | null = null;
  if (st.configured && isOwner && !connected) {
    try {
      shops = await api(`/stores/${current.id}/integrations/printify/shops`);
    } catch (e) {
      shopsError = e instanceof ApiError ? e.message : 'Printify mağazaları alınamadı';
    }
  }

  let blueprints: Blueprint[] = [];
  let comparison: Comparison | null = null;
  const country = /^[A-Z]{2}$/.test(sp.country ?? '') ? sp.country! : 'US';
  if (st.configured && (sp.q !== undefined || sp.bp)) {
    try {
      blueprints = await api(
        `/stores/${current.id}/printify/catalog/blueprints?q=${encodeURIComponent(sp.q ?? '')}`,
      );
      if (sp.bp && /^\d+$/.test(sp.bp)) {
        comparison = await api(
          `/stores/${current.id}/printify/catalog/blueprints/${sp.bp}/providers?country=${country}`,
        );
      }
    } catch (e) {
      shopsError = e instanceof ApiError ? e.message : 'Katalog alınamadı';
    }
  }

  return (
    <>
      <PageHeader
        title="Printify"
        description="Resmî Printify API: ürünler, maliyetler, üretim ve sağlayıcı karşılaştırması"
      />
      <div className="mb-6 space-y-2">
        {!st.configured && (
          <Notice tone="warn">
            Printify yapılandırılmadı. Printify’da <strong>My Profile → Connections</strong>{' '}
            bölümünden kişisel erişim token’ı oluşturup sunucu <code>.env</code> dosyasına{' '}
            <code>PRINTIFY_API_TOKEN</code> olarak ekleyin (1 yıl geçerlidir).
          </Notice>
        )}
        {st.configured && !st.webhooksConfigured && (
          <Notice>
            Webhook imza anahtarı (<code>PRINTIFY_WEBHOOK_SECRET</code>) tanımlı değil;
            değişiklikler 3 saatte bir senkronize edilir.
          </Notice>
        )}
        {st.lastError && <Notice tone="warn">Son hata: {st.lastError}</Notice>}
        {shopsError && <Notice tone="warn">{shopsError}</Notice>}
        {connected && st.lineCostBasis === 'unverified' && (
          <Notice>
            Printify belgeleri sipariş kalemi maliyetinin birim mi satır toplamı mı olduğunu
            belirtmiyor. Miktarı 1’den büyük ilk siparişte otomatik doğrulanacak; o zamana kadar
            birim maliyet varsayılır.
          </Notice>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Bağlantı" className="lg:col-span-2">
          {connected ? (
            <>
              <dl className="grid gap-3 text-sm sm:grid-cols-2" data-testid="printify-connection">
                <div>
                  <dt className="text-xs uppercase text-slate-500">Printify mağazası</dt>
                  <dd>{st.shopTitle}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-slate-500">Satış kanalı</dt>
                  <dd>{st.salesChannel ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-slate-500">Son senkronizasyon</dt>
                  <dd>{formatDate(st.lastSyncedAt)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-slate-500">Kalem maliyeti esası</dt>
                  <dd>{st.lineCostBasis}</dd>
                </div>
              </dl>
              {current.role !== 'viewer' && current.role !== 'analyst' && (
                <div className="mt-4">
                  <SyncPrintifyButton storeId={current.id} />
                </div>
              )}
            </>
          ) : isOwner && shops.length > 0 ? (
            <ConnectPrintifyForm storeId={current.id} shops={shops} />
          ) : (
            <p className="text-sm text-slate-500">
              {isOwner ? 'Bağlantı için token gerekli.' : 'Bağlantıyı mağaza sahibi kurar.'}
            </p>
          )}
        </Card>
        <div className="grid grid-cols-3 gap-4 lg:grid-cols-1">
          <Kpi label="Ürün" value={String(st.counts.products)} />
          <Kpi label="Eşleşen sipariş" value={String(st.counts.orders)} />
          <Kpi label="Sorunlu üretim" value={String(st.counts.problem_orders)} />
        </div>
      </div>

      {st.configured && (
        <Card title="Katalog ve baskı sağlayıcı karşılaştırması" className="mt-6">
          <form className="mb-4 flex flex-wrap gap-2" role="search">
            <input
              name="q"
              defaultValue={sp.q ?? ''}
              placeholder="Ürün tipi ara (ör. mug, hoodie, canvas)"
              className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
            />
            <input
              name="country"
              defaultValue={country}
              maxLength={2}
              className="w-20 rounded-lg border border-line px-3 py-2 text-sm uppercase"
              aria-label="Hedef ülke"
            />
            <button className="rounded-lg border border-line px-3 py-2 text-sm">Ara</button>
          </form>
          {blueprints.length > 0 && (
            <ul className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {blueprints.map((b) => (
                <li key={b.id}>
                  <a
                    href={`?q=${encodeURIComponent(sp.q ?? '')}&bp=${b.id}&country=${country}`}
                    className={`block rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 ${String(b.id) === sp.bp ? 'border-brand-500' : 'border-line'}`}
                  >
                    <span className="font-medium text-navy-900">{b.title}</span>
                    <span className="block text-xs text-slate-500">
                      {b.brand} {b.model}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
          {comparison && (
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[640px] text-left text-sm"
                aria-label="Sağlayıcı karşılaştırması"
              >
                <thead className="border-b border-line text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2 pr-3">Sağlayıcı</th>
                    <th className="py-2 pr-3">Konum</th>
                    <th className="py-2 pr-3">Üretim</th>
                    <th className="py-2 pr-3">Kargo ilk ürün ({country})</th>
                    <th className="py-2 pr-3">Ek ürün</th>
                    <th className="py-2">Varyant</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.providers.map((p) => (
                    <tr key={p.printProviderId} className="border-b border-line last:border-0">
                      <td className="py-2 pr-3">{p.title}</td>
                      <td className="py-2 pr-3">{p.location ?? '—'}</td>
                      <td className="py-2 pr-3">{p.productionTime ?? '—'}</td>
                      <td className="py-2 pr-3 tabular-nums">
                        {p.shipping
                          ? formatMoney(p.shipping.firstItem, p.shipping.currency ?? 'USD')
                          : '—'}
                        {p.shipping?.country === 'REST_OF_THE_WORLD' ? ' (dünya)' : ''}
                      </td>
                      <td className="py-2 pr-3 tabular-nums">
                        {p.shipping
                          ? formatMoney(p.shipping.additionalItem, p.shipping.currency ?? 'USD')
                          : '—'}
                      </td>
                      <td className="py-2 tabular-nums">{p.variantCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">{comparison.note}</p>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
