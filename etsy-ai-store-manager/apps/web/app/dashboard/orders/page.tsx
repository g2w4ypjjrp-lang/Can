import type { Metadata } from 'next';
import Link from 'next/link';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { DecisionBadge } from '@/components/decision-badge';
import { SlaForm } from '@/components/order-forms';

export const metadata: Metadata = { title: 'Siparişler' };

interface Row {
  id: string;
  etsyReceiptId: string | null;
  status: string;
  printifyStatus: string | null;
  printifyOrderId: string | null;
  currency: string;
  grandTotal: string;
  buyerCountry: string | null;
  placedAt: string;
  late: boolean;
  shipments: Array<{ carrier: string | null; tracking: string | null; status: string }>;
  items: string | null;
  contribution: string | null;
  decision: string | null;
}

const FILTERS: Array<[string, string]> = [
  ['', 'Tümü'],
  ['unshipped', 'Gönderilmemiş'],
  ['delayed', 'Geciken'],
  ['issues', 'Sorunlu'],
];
const STATUS: Record<string, string> = {
  open: 'Açık',
  paid: 'Ödendi',
  in_production: 'Üretimde',
  shipped: 'Kargoda',
  delivered: 'Teslim edildi',
  cancelled: 'İptal',
  refunded: 'İade edildi',
  partially_refunded: 'Kısmi iade',
};

export default async function OrdersPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string; search?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const q = new URLSearchParams();
  if (sp.filter) q.set('filter', sp.filter);
  if (sp.search) q.set('search', sp.search);
  if (sp.page) q.set('page', sp.page);
  const data = await api<{
    total: number;
    items: Row[];
    sla: { processingDaysMax: number; transitDaysMax: number };
  }>(`/stores/${current.id}/orders?${q.toString()}`);
  const canEdit = current.role === 'owner' || current.role === 'admin';
  return (
    <>
      <PageHeader
        title="Siparişler"
        description="Etsy siparişleri, Printify üretim ve kargo durumu, sipariş başı katkı"
      />
      <div
        className="mb-4 flex flex-wrap items-center gap-2"
        role="navigation"
        aria-label="Sipariş filtreleri"
      >
        {FILTERS.map(([v, l]) => (
          <Link
            key={v}
            href={v ? `/dashboard/orders?filter=${v}` : '/dashboard/orders'}
            className={`rounded-full border px-3 py-1 text-sm ${(sp.filter ?? '') === v ? 'border-navy-900 bg-navy-900 text-white' : 'border-line'}`}
          >
            {l}
          </Link>
        ))}
        <form className="ml-auto" role="search">
          {sp.filter && <input type="hidden" name="filter" value={sp.filter} />}
          <input
            name="search"
            defaultValue={sp.search ?? ''}
            placeholder="Sipariş no"
            inputMode="numeric"
            className="rounded-lg border border-line px-3 py-1.5 text-sm"
            aria-label="Sipariş no ara"
          />
        </form>
      </div>
      <Card title={`Siparişler (${data.total})`}>
        {data.items.length === 0 ? (
          <p className="text-sm text-slate-500">
            Sipariş yok. Etsy bağlantısı kurulduğunda siparişler içe aktarılır.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm" aria-label="Siparişler">
              <thead className="border-b border-line text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Sipariş</th>
                  <th className="py-2 pr-3">Ürünler</th>
                  <th className="py-2 pr-3">Durum</th>
                  <th className="py-2 pr-3">Kargo</th>
                  <th className="py-2 pr-3">Tutar</th>
                  <th className="py-2">Katkı</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((o) => (
                  <tr key={o.id} className="align-top">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/dashboard/orders/${o.id}`}
                        className="font-medium text-brand-600 hover:underline"
                      >
                        #{o.etsyReceiptId ?? o.id.slice(0, 8)}
                      </Link>
                      <span className="block text-xs text-slate-500">
                        {formatDate(o.placedAt)} · {o.buyerCountry ?? '—'}
                      </span>
                    </td>
                    <td className="max-w-xs py-2 pr-3 text-xs">{o.items}</td>
                    <td className="py-2 pr-3">
                      {STATUS[o.status] ?? o.status}
                      {o.printifyStatus && (
                        <span className="block text-xs text-slate-500">
                          Printify: {o.printifyStatus}
                        </span>
                      )}
                      {o.late && (
                        <span className="mt-1 block rounded bg-red-100 px-1.5 text-xs font-semibold text-red-800">
                          Gecikiyor
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {o.shipments.length
                        ? o.shipments.map((s, i) => (
                            <span
                              key={i}
                              className={`block ${s.status === 'delayed' ? 'text-red-700' : ''}`}
                            >
                              {s.carrier} {s.tracking} · {s.status}
                            </span>
                          ))
                        : '—'}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">
                      {formatMoney(o.grandTotal, o.currency)}
                    </td>
                    <td className="py-2">
                      {o.contribution ? (
                        <span className="tabular-nums">
                          {formatMoney(o.contribution, o.currency)}
                        </span>
                      ) : (
                        '—'
                      )}
                      {o.decision && <DecisionBadge decision={o.decision} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Gecikme eşikleri" className="mt-6">
        <p className="mb-2 text-xs text-slate-500">
          Etsy hazırlık profilleri senkronize edilmediği için eşikleri siz belirlersiniz. Aşan
          siparişler “Geciken” sayılır ve bildirim gönderilir.
        </p>
        {canEdit ? (
          <SlaForm
            storeId={current.id}
            processing={data.sla.processingDaysMax}
            transit={data.sla.transitDaysMax}
          />
        ) : (
          <p className="text-sm">
            Hazırlık {data.sla.processingDaysMax} gün · kargo {data.sla.transitDaysMax} gün
          </p>
        )}
      </Card>
    </>
  );
}
