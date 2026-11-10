"use client";

import { useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { Card, Notice } from "@/components/ui";
import type { Order } from "@/lib/api";
import { formatDate, formatPrice, orderStatusLabel } from "@/lib/format";

/** Müşteri panelinde sipariş geçmişi. */
export function OrdersSection() {
  const api = useApi();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Order[]>("/v1/me/orders")
      .then((rows) => !cancelled && setOrders(rows))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : "Siparişler yüklenemedi"));
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <section aria-labelledby="siparisler" className="mt-10">
      <h2 id="siparisler" className="text-xl font-semibold text-fg">
        Siparişlerim
      </h2>
      {error ? (
        <div className="mt-4">
          <Notice tone="danger" role="alert">
            {error}
          </Notice>
        </div>
      ) : orders === null ? (
        <p role="status" className="mt-4 text-sm text-muted">
          Siparişler yükleniyor…
        </p>
      ) : orders.length === 0 ? (
        <Card className="mt-4">
          <p className="text-sm text-muted">Henüz siparişiniz yok.</p>
        </Card>
      ) : (
        <ul className="mt-4 divide-y divide-border rounded-2xl border border-border bg-surface">
          {orders.map((order) => (
            <li key={order.order_no} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
              <div>
                <p className="font-medium text-fg">
                  #{order.order_no} · {order.plan_name ?? "Lisans"}
                </p>
                <p className="text-muted">
                  {formatDate(order.created_at)}
                  {order.invoice_no ? ` · Fatura kayıt no ${order.invoice_no}` : ""}
                </p>
              </div>
              <div className="text-right">
                <p className="font-semibold text-fg">{formatPrice(order.total_minor, order.currency)}</p>
                {order.coupon_code ? (
                  <p className="text-xs text-muted">
                    {order.coupon_code} kuponu: −{formatPrice(order.discount_minor ?? 0, order.currency)}
                  </p>
                ) : null}
                <p className="text-muted" data-testid={`order-${order.order_no}-status`}>
                  {orderStatusLabel(order.status, order.under_review)}
                </p>
                {order.status === "pending" && order.checkout_url ? (
                  <a href={order.checkout_url} className="font-medium text-link underline underline-offset-2 hover:no-underline">
                    Ödemeyi tamamla
                  </a>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
