"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, Table, TotpInput, cell, inputClass, smallButton, useAdminAction, useAdminQuery, StatusPill, orderTone } from "@/components/admin/kit";
import { Button, Card } from "@/components/ui";
import { can, dateTime, formatMinor, parseMoney } from "@/lib/admin";
import { formatPrice, licenseStatusLabel, orderStatusLabel } from "@/lib/format";

interface OrderRow {
  id: string;
  order_no: number;
  status: string;
  currency: string;
  total_minor: number;
  payment_provider: string;
  review_reason: string | null;
  created_at: string;
  paid_at: string | null;
  customer_email: string;
  plan_name: string | null;
}

interface OrderDetail extends OrderRow {
  subtotal_minor: number;
  billing_snapshot: { billing?: Record<string, string>; legal?: { version?: string; accepted_at?: string; ip?: string }; mode?: string };
  fulfilled_at: string | null;
  customer_id: string;
  items: { plan_code: string; plan_name: string; quantity: number; unit_price_minor: number }[];
  payments: { id: string; provider: string; provider_payment_id: string; status: string; amount_minor: number; refunded_minor: number; currency: string; succeeded_at: string | null }[];
  refunds: { id: string; amount_minor: number; reason: string; status: string; license_action: string; created_at: string; requested_by: string | null; last_error: string | null }[];
  licenses: { id: string; key_hint: string; status: string; expires_at: string | null }[];
  invoice: { invoice_no: string; issued_at: string } | null;
}

const REVIEW_LABELS: Record<string, string> = {
  amount_mismatch: "Tutar veya para birimi uyuşmuyor",
  duplicate_payment: "Aynı siparişe ikinci tahsilat",
  provider_mismatch: "Ödeme başka sağlayıcıdan geldi",
};
const PROVIDER_LABELS: Record<string, string> = { paytr: "PayTR", iyzico: "iyzico", simulator: "Simülatör", free: "Ücretsiz" };
const STATUS_FILTERS = ["", "pending", "paid", "fulfilled", "failed", "refunded", "partially_refunded", "cancelled"];

function RefundForm({ order, onDone }: { order: OrderDetail; onDone: (message: string) => void }) {
  const api = useApi();
  const action = useAdminAction();
  const payment = order.payments.find((p) => p.status === "succeeded" || p.status === "partially_refunded");
  if (!payment) return null;
  const refundable = payment.amount_minor - payment.refunded_minor;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const amountText = String(data.get("amount") ?? "").trim();
    const amount = amountText ? parseMoney(amountText) : null;
    if (amountText && amount === null) {
      await action.run(async () => {
        throw new Error("Tutarı 1.499,90 biçiminde girin");
      });
      return;
    }
    const ok = await action.run(
      () =>
        api.post(`/admin/v1/orders/${order.id}/refund`, {
          amount_minor: amount,
          reason: data.get("reason"),
          license_action: data.get("license_action"),
          code: data.get("code"),
        }),
    );
    // Başarı mesajı ayrıntı kartında gösterilir (tam iadeden sonra bu form kaybolur).
    if (ok) onDone("İade yapıldı");
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 rounded-xl border border-border p-4" aria-labelledby="iade-baslik">
      <h3 id="iade-baslik" className="text-sm font-semibold text-fg">
        İade · en fazla {formatPrice(refundable, payment.currency)}
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm text-fg">
          Tutar (boş = kalanın tamamı)
          <input name="amount" inputMode="decimal" placeholder={formatMinor(refundable)} className={`mt-1 ${inputClass}`} />
        </label>
        <label className="text-sm text-fg">
          Lisans
          <select name="license_action" defaultValue="cancel" className={`mt-1 ${inputClass}`}>
            <option value="cancel">İptal et</option>
            <option value="keep">Koru</option>
            <option value="manual_review">Elle incelenecek</option>
          </select>
        </label>
      </div>
      <label className="block text-sm text-fg">
        Neden
        <input name="reason" required minLength={3} maxLength={300} className={`mt-1 ${inputClass}`} />
      </label>
      <TotpInput id="iade-kodu" />
      <Feedback error={action.error} message={action.message} />
      <Button type="submit" variant="secondary" disabled={action.pending}>
        İadeyi başlat
      </Button>
    </form>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const api = useApi();
  const { me } = useAdmin();
  const detail = useAdminQuery<OrderDetail>(`/admin/v1/orders/${id}`);
  const action = useAdminAction();
  const d = detail.data;
  if (!d) return <Feedback error={detail.error} />;
  const billing = d.billing_snapshot.billing ?? {};
  const refresh = () => {
    detail.reload();
    onChanged();
  };

  return (
    <Card as="section" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-lg font-semibold text-fg">
          Sipariş #{d.order_no} · <span data-testid="admin-order-status">{orderStatusLabel(d.status, Boolean(d.review_reason))}</span>
        </h2>
        {can(me, "payment.read") && (d.status === "pending" || d.status === "failed") ? (
          <button
            type="button"
            className={smallButton}
            disabled={action.pending}
            onClick={() =>
              void action
                .run(() => api.post<{ result: string }>(`/admin/v1/orders/${id}/reconcile`), undefined)
                .then((r) => {
                  if (r) action.setMessage(`Sağlayıcı sorgulandı: ${r.result}`);
                  refresh();
                })
            }
          >
            Sağlayıcıdan sorgula
          </button>
        ) : null}
      </div>
      {d.review_reason ? (
        <p className="rounded-lg border border-warn-border bg-warn-bg px-3 py-2 text-sm text-warn-fg">
          İnceleme gerekli: {REVIEW_LABELS[d.review_reason] ?? d.review_reason}. Lisans otomatik teslim edilmedi; ödemeyi
          sağlayıcı panelinden doğrulayıp elle lisans üretin veya iade edin.
        </p>
      ) : null}
      <Feedback error={action.error} message={action.message} />
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-muted">Müşteri</dt>
        <dd className="text-fg">{d.customer_email}</dd>
        <dt className="text-muted">Tutar</dt>
        <dd className="text-fg">{formatPrice(d.total_minor, d.currency)}</dd>
        <dt className="text-muted">Sağlayıcı</dt>
        <dd className="text-fg">
          {PROVIDER_LABELS[d.payment_provider] ?? d.payment_provider} ({d.billing_snapshot.mode === "live" ? "canlı" : d.billing_snapshot.mode ?? "—"})
        </dd>
        <dt className="text-muted">Fatura bilgisi</dt>
        <dd className="text-fg">
          {[billing.full_name, billing.phone, billing.address, billing.city, billing.country, billing.tax_id].filter(Boolean).join(" · ") || "—"}
        </dd>
        <dt className="text-muted">Yasal onay</dt>
        <dd className="text-fg">
          {d.billing_snapshot.legal ? `${d.billing_snapshot.legal.version} · ${dateTime(d.billing_snapshot.legal.accepted_at)} · ${d.billing_snapshot.legal.ip ?? ""}` : "—"}
        </dd>
        <dt className="text-muted">Fatura kaydı</dt>
        <dd className="text-fg">{d.invoice ? `${d.invoice.invoice_no} · ${dateTime(d.invoice.issued_at)}` : "—"}</dd>
      </dl>
      <div>
        <h3 className="text-sm font-semibold text-fg">Ödemeler</h3>
        <ul className="mt-1 text-sm text-fg">
          {d.payments.length === 0 ? <li className="text-muted">Yok</li> : null}
          {d.payments.map((p) => (
            <li key={p.id}>
              {PROVIDER_LABELS[p.provider] ?? p.provider} · {p.status} · {formatPrice(p.amount_minor, p.currency)}
              {p.refunded_minor ? ` · iade ${formatPrice(p.refunded_minor, p.currency)}` : ""} ·{" "}
              <span className="font-mono text-xs">{p.provider_payment_id}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-fg">Lisanslar</h3>
        <ul className="mt-1 text-sm text-fg">
          {d.licenses.length === 0 ? <li className="text-muted">Yok</li> : null}
          {d.licenses.map((l) => (
            <li key={l.id} data-testid="admin-order-license">
              <span className="font-mono">{l.key_hint}</span> · {licenseStatusLabel(l.status)}
            </li>
          ))}
        </ul>
      </div>
      {d.refunds.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold text-fg">İadeler</h3>
          <ul className="mt-1 text-sm text-fg">
            {d.refunds.map((r) => (
              <li key={r.id}>
                {dateTime(r.created_at)} · {formatPrice(r.amount_minor, d.currency)} · {r.status} · lisans: {r.license_action} · {r.reason}
                {r.requested_by ? ` · ${r.requested_by}` : ""}
                {r.last_error ? ` · hata: ${r.last_error}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {can(me, "payment.refund") ? (
        <RefundForm
          order={d}
          onDone={(message) => {
            action.setMessage(message);
            refresh();
          }}
        />
      ) : null}
    </Card>
  );
}

export function Orders() {
  const [filters, setFilters] = useState({ status: "", q: "", review: false });
  const [selected, setSelected] = useState<string | null>(null);
  const params = new URLSearchParams({ limit: "50" });
  if (filters.status) params.set("status", filters.status);
  if (filters.q) params.set("q", filters.q);
  if (filters.review) params.set("review", "true");
  const list = useAdminQuery<OrderRow[]>(`/admin/v1/orders?${params.toString()}`);

  return (
    <AdminPage title="Siparişler" lead="Ödemeler, teslim edilen lisanslar ve iadeler. İade ve sağlayıcı sorgusu denetim kaydına yazılır.">
      <form
        role="search"
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          setFilters({ status: String(data.get("status") ?? ""), q: String(data.get("q") ?? "").trim(), review: data.get("review") === "on" });
          setSelected(null);
        }}
      >
        <label className="text-sm text-fg">
          Sipariş no veya e-posta
          <input name="q" className={`mt-1 ${inputClass} w-64`} />
        </label>
        <label className="text-sm text-fg">
          Durum
          <select name="status" defaultValue="" className={`mt-1 ${inputClass}`}>
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {s ? orderStatusLabel(s) : "Tümü"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-fg">
          <input type="checkbox" name="review" className="h-4 w-4" /> Yalnızca inceleme bekleyenler
        </label>
        <Button type="submit" variant="secondary">
          Süz
        </Button>
      </form>
      <Feedback error={list.error} />
      {list.data ? (
        <Table caption="Siparişler" head={["No", "Müşteri", "Paket", "Tutar", "Durum", "Tarih", ""]}>
          {list.data.length === 0 ? (
            <tr>
              <td className={cell} colSpan={7}>
                Sipariş yok.
              </td>
            </tr>
          ) : null}
          {list.data.map((o) => (
            <tr key={o.id}>
              <td className={cell}>{o.order_no}</td>
              <td className={cell}>{o.customer_email}</td>
              <td className={cell}>{o.plan_name ?? "—"}</td>
              <td className={cell}>{formatPrice(o.total_minor, o.currency)}</td>
              <td className={cell}>{o.review_reason ? <StatusPill tone="warn">İnceleme gerekli</StatusPill> : <StatusPill tone={orderTone(o.status)}>{orderStatusLabel(o.status)}</StatusPill>}</td>
              <td className={cell}>{dateTime(o.created_at)}</td>
              <td className={cell}>
                <button type="button" className={smallButton} onClick={() => setSelected(o.id)} aria-label={`Sipariş ${o.order_no} ayrıntı`}>
                  Ayrıntı
                </button>
              </td>
            </tr>
          ))}
        </Table>
      ) : null}
      {selected ? <Detail key={selected} id={selected} onChanged={list.reload} /> : null}
    </AdminPage>
  );
}
