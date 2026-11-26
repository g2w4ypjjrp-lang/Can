import type { Metadata } from 'next';
import type { ApprovalDto } from '@esm/shared';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import { AddMessageForm, MessageCard, type Msg } from '@/components/order-forms';
import { ConfirmManualForm } from '@/components/ads-forms';

export const metadata: Metadata = { title: 'Müşteriler' };

interface Customer {
  id: string;
  name: string | null;
  country: string | null;
  totalOrders: number;
  revenue: string;
  repeat: boolean;
  lastOrderAt: string | null;
  openMessages: number;
}
interface Reviews {
  stats: { n: number; avg: string | null; low: number };
  items: Array<{
    id: string;
    rating: number;
    review: string | null;
    etsy_created_at: string;
    listing_title: string | null;
  }>;
}

export default async function CustomersPage() {
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const canEdit = current.role === 'owner' || current.role === 'admin';
  const reviews = await api<Reviews>(`/stores/${current.id}/reviews`);
  if (!canEdit)
    return (
      <>
        <PageHeader title="Müşteriler" description="Müşteri verisi yalnızca yöneticilere açıktır" />
        <Kpi
          label="Ortalama puan"
          value={reviews.stats.avg ?? '—'}
          hint={`${reviews.stats.n} yorum`}
        />
      </>
    );
  const [customers, messages, approvals] = await Promise.all([
    api<Customer[]>(`/stores/${current.id}/customers`),
    api<Msg[]>(`/stores/${current.id}/messages`),
    api<ApprovalDto[]>(`/stores/${current.id}/approvals`),
  ]);
  const open = messages.filter((m) => !['sent', 'closed'].includes(m.status));
  const awaiting = approvals.filter(
    (a) => a.actionType === 'send_customer_message' && a.status === 'awaiting_manual',
  );
  const repeatRate = customers.length
    ? Math.round((customers.filter((c) => c.repeat).length / customers.length) * 100)
    : 0;
  return (
    <>
      <PageHeader
        title="Müşteriler"
        description="Mesajlar ve yorumlar: AI sınıflandırma ve yanıt taslağı (gönderim sizde)"
      />
      <Notice>
        Etsy Open API v3 mesajlaşma uç noktası sunmaz. Müşteri mesajını buraya yapıştırın; AI
        sınıflandırıp sipariş bilgisine dayalı taslak hazırlar. Yanıtı onayladıktan sonra Etsy
        Mesajlar’dan gönderip burada işaretlersiniz. Düşük puanlı Etsy yorumları otomatik olarak
        listeye gelir.
      </Notice>
      <div className="mt-4 grid gap-4 sm:grid-cols-4">
        <Kpi
          label="Açık konu"
          value={String(open.length)}
          hint={`${open.filter((m) => m.urgency === 'high' || m.urgency === 'critical').length} acil`}
        />
        <Kpi
          label="Ortalama puan"
          value={reviews.stats.avg ?? '—'}
          hint={`${reviews.stats.n} yorum · ${reviews.stats.low} düşük`}
        />
        <Kpi label="Müşteri" value={String(customers.length)} />
        <Kpi label="Tekrar alan" value={`%${repeatRate}`} />
      </div>
      {awaiting.map((a) => (
        <Card key={a.id} title="Onaylandı — Etsy’de gönderin" className="mt-6">
          <pre className="whitespace-pre-wrap text-sm">{a.what}</pre>
          <ConfirmManualForm storeId={current.id} approvalId={a.id} path="/dashboard/customers" />
        </Card>
      ))}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2" aria-label="Açık konular">
          <h2 className="text-sm font-semibold text-navy-900">Açık konular ({open.length})</h2>
          {open.length === 0 && <p className="text-sm text-slate-500">Açık konu yok.</p>}
          {open.map((m) => (
            <MessageCard key={m.id} storeId={current.id} m={m} />
          ))}
        </div>
        <div className="space-y-6">
          <Card title="Mesaj ekle">
            <AddMessageForm storeId={current.id} />
          </Card>
          <Card title="Son yorumlar">
            <ul className="space-y-2 text-sm">
              {reviews.items.slice(0, 8).map((r) => (
                <li key={r.id}>
                  <span className={r.rating <= 3 ? 'font-semibold text-red-700' : ''}>
                    {'★'.repeat(r.rating)}
                  </span>{' '}
                  <span className="text-xs text-slate-500">
                    {formatDate(r.etsy_created_at)} · {r.listing_title ?? ''}
                  </span>
                  {r.review && <p className="line-clamp-2 text-slate-700">{r.review}</p>}
                </li>
              ))}
              {reviews.items.length === 0 && <li className="text-slate-500">Yorum yok.</li>}
            </ul>
          </Card>
        </div>
      </div>
      <Card title={`Müşteriler (${customers.length})`} className="mt-6">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm" aria-label="Müşteriler">
            <thead className="border-b border-line text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">Müşteri</th>
                <th className="py-2 pr-3">Ülke</th>
                <th className="py-2 pr-3">Sipariş</th>
                <th className="py-2 pr-3">Gelir</th>
                <th className="py-2">Son sipariş</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {customers.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 pr-3">
                    {c.name ?? '—'}{' '}
                    {c.repeat && (
                      <span className="rounded bg-emerald-100 px-1 text-xs text-emerald-800">
                        tekrar
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3">{c.country ?? '—'}</td>
                  <td className="py-2 pr-3 tabular-nums">{c.totalOrders}</td>
                  <td className="py-2 pr-3 tabular-nums">
                    {formatMoney(c.revenue, current.currency ?? 'USD')}
                  </td>
                  <td className="py-2">{formatDate(c.lastOrderAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
