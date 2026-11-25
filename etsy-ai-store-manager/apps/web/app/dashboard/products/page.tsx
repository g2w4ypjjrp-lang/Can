import type { Metadata } from 'next';
import Link from 'next/link';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatMoney } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';

export const metadata: Metadata = { title: 'Ürünler' };

interface Item {
  id: string;
  title: string;
  productType: string;
  status: string;
  etsyListingId: string | null;
  image: string | null;
  enabledVariants: number;
  priceRange: [string | null, string | null];
  productionCostRange: [string | null, string | null];
  locked: boolean | null;
}

const range = (r: [string | null, string | null]) =>
  r[0] === null
    ? '—'
    : r[0] === r[1]
      ? formatMoney(r[0], 'USD')
      : `${formatMoney(r[0], 'USD')} – ${formatMoney(r[1], 'USD')}`;

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const qs = new URLSearchParams({ limit: '100' });
  if (sp.q) qs.set('q', sp.q.slice(0, 100));
  if (sp.status && ['draft', 'ready', 'published', 'archived', 'idea'].includes(sp.status))
    qs.set('status', sp.status);
  const data = await api<{ total: number; items: Item[] }>(`/stores/${current.id}/products?${qs}`);
  return (
    <>
      <PageHeader
        title="Ürünler"
        description="Printify ürünleri, varyantlar, satış fiyatı ve güncel üretim maliyeti"
      />
      <Card title={`Ürünler (${data.total})`}>
        <form className="mb-4 flex flex-wrap gap-2" role="search">
          <input
            name="q"
            defaultValue={sp.q ?? ''}
            placeholder="Ürün ara"
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
          />
          <select
            name="status"
            defaultValue={sp.status ?? ''}
            className="rounded-lg border border-line px-3 py-2 text-sm"
            aria-label="Durum"
          >
            <option value="">Tümü</option>
            <option value="draft">Taslak</option>
            <option value="ready">Yayın bekliyor</option>
            <option value="published">Yayında</option>
          </select>
          <button className="rounded-lg border border-line px-3 py-2 text-sm">Filtrele</button>
        </form>
        {data.items.length === 0 ? (
          <p className="text-sm text-slate-500">
            Henüz ürün yok. Printify bağlandığında ürünleriniz burada görünür.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-line text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Ürün</th>
                  <th className="py-2 pr-3">Tip</th>
                  <th className="py-2 pr-3">Durum</th>
                  <th className="py-2 pr-3">Satış fiyatı</th>
                  <th className="py-2 pr-3">Üretim maliyeti</th>
                  <th className="py-2">Varyant</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id} className="border-b border-line last:border-0">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/dashboard/products/${p.id}`}
                        className="flex items-center gap-3 hover:underline"
                      >
                        {p.image ? (
                          <img
                            src={p.image}
                            alt=""
                            className="h-10 w-10 rounded object-cover"
                            loading="lazy"
                          />
                        ) : (
                          <span className="h-10 w-10 rounded bg-slate-100" />
                        )}
                        <span className="text-navy-900">{p.title}</span>
                      </Link>
                    </td>
                    <td className="py-2 pr-3 text-slate-600">{p.productType}</td>
                    <td className="py-2 pr-3">
                      {p.status}
                      {p.etsyListingId ? ' · Etsy' : ''}
                      {p.locked ? ' · kilitli' : ''}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{range(p.priceRange)}</td>
                    <td className="py-2 pr-3 tabular-nums">{range(p.productionCostRange)}</td>
                    <td className="py-2 tabular-nums">{p.enabledVariants}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
