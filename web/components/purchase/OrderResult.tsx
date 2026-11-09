"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { Card, LinkButton, Notice } from "@/components/ui";
import { ApiError, type Order } from "@/lib/api";
import { formatDate, formatPrice, isOrderSettled, orderStatusLabel } from "@/lib/format";

const POLL_MS = 2000;
const MAX_POLLS = 45; // ~90 sn; ödeme sağlayıcısının bildirimi genelde saniyeler içinde gelir

type State = { kind: "loading" } | { kind: "ready"; order: Order; polls: number } | { kind: "error"; message: string };

/** Sağlayıcıdan dönüşte sipariş durumunu gösterir; lisans teslim edilene kadar yoklar. */
export function OrderResult({ orderNo }: { orderNo: number | null }) {
  const api = useApi();
  const router = useRouter();
  const [state, setState] = useState<State>(orderNo === null ? { kind: "error", message: "" } : { kind: "loading" });

  useEffect(() => {
    if (orderNo === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    const poll = () => {
      api
        .get<Order>(`/v1/me/orders/${orderNo}`)
        .then((order) => {
          if (cancelled) return;
          polls += 1;
          setState({ kind: "ready", order, polls });
          if (!isOrderSettled(order.status, order.under_review) && polls < MAX_POLLS) timer = setTimeout(poll, POLL_MS);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (err instanceof ApiError && err.status === 401) {
            router.replace(`/giris?sonra=${encodeURIComponent(`/odeme/sonuc?siparis=${orderNo}`)}`);
            return;
          }
          setState({ kind: "error", message: err instanceof Error ? err.message : "Sipariş yüklenemedi" });
        });
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, orderNo, router]);

  if (orderNo === null || (state.kind === "error" && !state.message)) {
    return (
      <Notice tone="info" title="Sipariş bulunamadı" role="status">
        Ödeme sonucunu müşteri panelinizdeki “Siparişlerim” bölümünden takip edebilirsiniz.
      </Notice>
    );
  }
  if (state.kind === "loading") {
    return (
      <p role="status" className="text-muted">
        Ödeme sonucu alınıyor…
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <Notice tone="danger" role="alert">
        {state.message}
      </Notice>
    );
  }

  const { order, polls } = state;
  const waiting = !isOrderSettled(order.status, order.under_review);
  return (
    <div className="space-y-6">
      {order.status === "fulfilled" ? (
        <Notice tone="success" title="Ödemeniz alındı, lisansınız hazır" role="status">
          Lisans hesabınıza tanımlandı. Masaüstü uygulamasında Ayarlar → Lisans bölümüne anahtarınızı girerek
          etkinleştirebilirsiniz; tam anahtarı müşteri panelinde görebilirsiniz.
        </Notice>
      ) : order.under_review ? (
        <Notice tone="warning" title="Ödemeniz inceleniyor" role="status">
          Ödeme bilgisi siparişle eşleşmedi; ekibimiz kontrol edip en kısa sürede size dönecek. Ek bir işlem yapmanıza
          gerek yok.
        </Notice>
      ) : order.status === "failed" ? (
        <Notice tone="danger" title="Ödeme tamamlanamadı" role="alert">
          Kartınızdan tahsilat yapılmadı. Bilgilerinizi kontrol edip yeniden deneyebilirsiniz.
        </Notice>
      ) : waiting && polls < MAX_POLLS ? (
        <Notice tone="info" title="Ödeme sonucu bekleniyor" role="status">
          Ödeme kuruluşundan onay bekleniyor; bu sayfa kendiliğinden güncellenir.
        </Notice>
      ) : waiting ? (
        <Notice tone="info" title="Onay gecikti" role="status">
          Ödeme kuruluşundan henüz yanıt gelmedi. Ödeme yaptıysanız lisansınız onay gelir gelmez hesabınıza tanımlanır;
          durumu müşteri panelinden izleyebilirsiniz.
        </Notice>
      ) : (
        <Notice tone="info" title={orderStatusLabel(order.status)} role="status">
          Ayrıntılar için müşteri panelinize bakın.
        </Notice>
      )}

      <Card>
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted">Sipariş no</dt>
          <dd className="text-fg">{order.order_no}</dd>
          <dt className="text-muted">Paket</dt>
          <dd className="text-fg">{order.plan_name ?? "—"}</dd>
          <dt className="text-muted">Tutar</dt>
          <dd className="text-fg">{formatPrice(order.total_minor, order.currency)}</dd>
          <dt className="text-muted">Durum</dt>
          <dd className="font-semibold text-fg" data-testid="order-status">
            {orderStatusLabel(order.status, order.under_review)}
          </dd>
          <dt className="text-muted">Tarih</dt>
          <dd className="text-fg">{formatDate(order.created_at)}</dd>
          {order.licenses.length > 0 ? (
            <>
              <dt className="text-muted">Lisans</dt>
              <dd className="font-mono text-fg">{order.licenses.join(", ")}</dd>
            </>
          ) : null}
          {order.invoice_no ? (
            <>
              <dt className="text-muted">Fatura kayıt no</dt>
              <dd className="text-fg">{order.invoice_no}</dd>
            </>
          ) : null}
        </dl>
      </Card>
      <div className="flex flex-wrap gap-3">
        <LinkButton href="/panel">Müşteri paneline git</LinkButton>
        {order.status === "failed" ? (
          <LinkButton href="/paketler" variant="secondary">
            Yeniden dene
          </LinkButton>
        ) : null}
        {order.status === "pending" && order.checkout_url ? (
          <a
            href={order.checkout_url}
            className="inline-flex items-center justify-center rounded-full border border-border-strong/40 bg-surface px-5 py-2.5 text-sm font-semibold text-fg hover:bg-surface-2"
          >
            Ödeme sayfasına dön
          </a>
        ) : null}
      </div>
    </div>
  );
}
