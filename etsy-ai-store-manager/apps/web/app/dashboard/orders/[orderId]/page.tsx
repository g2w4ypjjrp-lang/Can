import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { ApprovalDto } from '@esm/shared';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { DecisionBadge } from '@/components/decision-badge';
import { CancelForm, RefundForm, TrackingForm } from '@/components/order-forms';
import { ConfirmManualForm } from '@/components/ads-forms';

export const metadata: Metadata = { title: 'Sipariş' };

interface Detail {
  id: string;
  etsyReceiptId: string | null;
  status: string;
  printifyStatus: string | null;
  currency: string;
  grandTotal: string;
  subtotal: string;
  shippingTotal: string;
  taxTotal: string;
  discountTotal: string;
  placedAt: string;
  shippedAt: string | null;
  late: boolean;
  fulfilledByPrintify: boolean;
  items: Array<{ title: string; quantity: number; unit_price: string; currency: string }>;
  shipmentsDetail: Array<{
    carrier: string | null;
    tracking_number: string | null;
    tracking_url: string | null;
    status: string;
    source: string;
    shipped_at: string | null;
  }>;
  refunds: Array<{
    id: string;
    amount: string;
    currency: string;
    reason: string | null;
    status: string;
    contribution_before: string | null;
    contribution_after: string | null;
  }>;
  profit: {
    contribution: string;
    contribution_before_ads: string | null;
    decision: string;
    warnings: string[];
    complete: boolean;
  } | null;
  messages: Array<{
    id: string;
    body: string;
    category: string | null;
    urgency: string | null;
    status: string;
  }>;
}

export default async function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(orderId)) notFound();
  const { current } = await loadStores();
  if (!current) notFound();
  let o: Detail;
  try {
    o = await api<Detail>(`/stores/${current.id}/orders/${orderId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const canEdit = current.role === 'owner' || current.role === 'admin';
  const approvals = canEdit ? await api<ApprovalDto[]>(`/stores/${current.id}/approvals`) : [];
  const mine = approvals.filter(
    (a) => (a.payload as { orderId?: string } | null)?.orderId === orderId,
  );
  const awaiting = mine.filter((a) => a.status === 'awaiting_manual');
  const pending = mine.filter((a) => a.status === 'pending');
  const closed = ['shipped', 'delivered', 'cancelled', 'refunded'].includes(o.status);
  const path = `/dashboard/orders/${orderId}`;
  return (
    <>
      <PageHeader
        title={`Sipariş #${o.etsyReceiptId ?? o.id.slice(0, 8)}`}
        description={`${formatDate(o.placedAt)} · ${o.status}${o.printifyStatus ? ` · Printify: ${o.printifyStatus}` : ''}`}
      >
        <Link href="/dashboard/orders" className="text-sm text-brand-600 hover:underline">
          ← Siparişler
        </Link>
      </PageHeader>
      {o.late && <Notice tone="warn">Sipariş hazırlık süresini aştı ve henüz gönderilmedi.</Notice>}
      {pending.length > 0 && (
        <Notice>
          {pending.length} onay isteği bekliyor:{' '}
          <Link href="/dashboard/etsy#approvals" className="text-brand-600 hover:underline">
            Onaylar
          </Link>
        </Notice>
      )}
      {awaiting.map((a) => (
        <Card key={a.id} title={`Manuel uygulama: ${a.title}`} className="mt-4">
          <p className="whitespace-pre-line text-sm">{a.what}</p>
          <p className="mt-1 text-xs text-amber-800">{a.apiOperation}</p>
          <ConfirmManualForm storeId={current.id} approvalId={a.id} path={path} />
        </Card>
      ))}
      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <Card title="Kalemler ve tutarlar" className="lg:col-span-2">
          <ul className="divide-y divide-line text-sm">
            {o.items.map((i, n) => (
              <li key={n} className="flex justify-between py-2">
                <span>
                  {i.title} ×{i.quantity}
                </span>
                <span className="tabular-nums">{formatMoney(i.unit_price, i.currency)}</span>
              </li>
            ))}
          </ul>
          <dl className="mt-3 grid grid-cols-2 gap-1 text-sm sm:grid-cols-5">
            <div>
              <dt className="text-xs text-slate-500">Ara toplam</dt>
              <dd>{formatMoney(o.subtotal, o.currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Kargo</dt>
              <dd>{formatMoney(o.shippingTotal, o.currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">İndirim</dt>
              <dd>{formatMoney(o.discountTotal, o.currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Vergi</dt>
              <dd>{formatMoney(o.taxTotal, o.currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Toplam</dt>
              <dd className="font-semibold">{formatMoney(o.grandTotal, o.currency)}</dd>
            </div>
          </dl>
        </Card>
        <Card title="Kârlılık">
          {o.profit ? (
            <>
              <p className="text-2xl font-semibold tabular-nums">
                {formatMoney(o.profit.contribution, o.currency)}
              </p>
              <DecisionBadge decision={o.profit.decision} />
              {!o.profit.complete && (
                <p className="mt-2 text-xs text-amber-800">
                  Eksik veri: {o.profit.warnings.join(' · ')}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-500">Henüz hesaplanmadı.</p>
          )}
        </Card>
      </div>
      <Card title="Kargo" className="mt-6">
        {o.shipmentsDetail.length === 0 ? (
          <p className="text-sm text-slate-500">Takip bilgisi yok.</p>
        ) : (
          <ul className="space-y-1 text-sm" aria-label="Gönderiler">
            {o.shipmentsDetail.map((s, i) => (
              <li key={i}>
                {s.carrier}{' '}
                {s.tracking_url ? (
                  <a
                    href={s.tracking_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-brand-600 hover:underline"
                  >
                    {s.tracking_number}
                  </a>
                ) : (
                  s.tracking_number
                )}{' '}
                · {s.status} ·{' '}
                {s.source === 'printify' ? 'Printify' : s.source === 'etsy' ? 'Etsy' : 'elle'}{' '}
                {s.shipped_at ? `· ${formatDate(s.shipped_at)}` : ''}
              </li>
            ))}
          </ul>
        )}
        {canEdit && !closed && !o.fulfilledByPrintify && (
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold">
              Takip numarası ekle (Etsy alıcıya bildirir)
            </h3>
            <TrackingForm storeId={current.id} orderId={o.id} />
          </div>
        )}
        {o.fulfilledByPrintify && (
          <p className="mt-2 text-xs text-slate-500">
            Printify siparişi: takip numarasını Printify, Etsy’ye otomatik iletir.
          </p>
        )}
      </Card>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="İadeler">
          {o.refunds.length > 0 && (
            <ul className="mb-3 space-y-1 text-sm">
              {o.refunds.map((r) => (
                <li key={r.id}>
                  {formatMoney(r.amount, r.currency)} · {r.status} {r.reason ? `· ${r.reason}` : ''}
                  {r.contribution_before && r.contribution_after && (
                    <span className="block text-xs text-slate-500">
                      katkı {formatMoney(r.contribution_before, o.currency)} →{' '}
                      {formatMoney(r.contribution_after, o.currency)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {canEdit && !['cancelled', 'refunded'].includes(o.status) && (
            <RefundForm storeId={current.id} orderId={o.id} currency={o.currency} />
          )}
          <p className="mt-2 text-xs text-slate-500">
            Etsy API iade desteklemez: onaydan sonra Etsy panelinde iade edip burada işaretlersiniz.
          </p>
        </Card>
        <Card title="İptal ve mesajlar">
          {canEdit && !o.shippedAt && !closed && <CancelForm storeId={current.id} orderId={o.id} />}
          {o.messages.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm">
              {o.messages.map((m) => (
                <li key={m.id}>
                  <span className="text-xs text-slate-500">
                    {m.category ?? 'mesaj'} · {m.urgency ?? ''} · {m.status}
                  </span>
                  <p className="line-clamp-2">{m.body}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-500">Bu siparişe bağlı mesaj yok.</p>
          )}
          <Link
            href="/dashboard/customers"
            className="mt-2 inline-block text-sm text-brand-600 hover:underline"
          >
            Müşteri mesajları →
          </Link>
        </Card>
      </div>
    </>
  );
}
