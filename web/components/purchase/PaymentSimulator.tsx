"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { useSubmit } from "@/components/auth/useSubmit";
import { Button, Card, Notice } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/format";

interface SimulatedOrder {
  order_no: number;
  status: string;
  total_minor: number;
  currency: string;
  plan_name: string;
}

type State = { kind: "loading" } | { kind: "ready"; order: SimulatedOrder } | { kind: "error"; message: string };

/** Geliştirme/test ortamındaki ödeme simülatörü. Üretimde API 404 döner ve sayfa kapalıdır. */
export function PaymentSimulator({ token }: { token: string }) {
  const api = useApi();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const { pending, error, run } = useSubmit();

  useEffect(() => {
    let cancelled = false;
    api
      .get<SimulatedOrder>(`/v1/payments/simulator/session?token=${encodeURIComponent(token)}`)
      .then((order) => !cancelled && setState({ kind: "ready", order }))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/giris?sonra=${encodeURIComponent(`/odeme/test?oturum=${token}`)}`);
          return;
        }
        const closed = err instanceof ApiError && err.status === 404;
        setState({
          kind: "error",
          message: closed ? "Test ödeme sayfası bu ortamda kapalı veya sipariş bulunamadı." : err instanceof Error ? err.message : "Sipariş yüklenemedi",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [api, router, token]);

  async function complete(outcome: "success" | "failure") {
    await run(async () => {
      const result = await api.post<{ order_no: number }>("/v1/payments/simulator/complete", { token, outcome });
      router.push(`/odeme/sonuc?siparis=${result.order_no}`);
    });
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-muted">
        Sipariş yükleniyor…
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
  const { order } = state;
  return (
    <Card className="space-y-5">
      <Notice tone="warning" title="Test simülatörü" role="note">
        Bu sayfa gerçek bir ödeme sağlayıcısı değildir; kart bilgisi istenmez ve tahsilat yapılmaz.
      </Notice>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <dt className="text-muted">Sipariş no</dt>
        <dd className="text-fg">{order.order_no}</dd>
        <dt className="text-muted">Paket</dt>
        <dd className="text-fg">{order.plan_name}</dd>
        <dt className="text-muted">Tutar</dt>
        <dd className="font-semibold text-fg">{formatPrice(order.total_minor, order.currency)}</dd>
      </dl>
      <ErrorBox error={error} />
      {order.status === "pending" ? (
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => void complete("success")} disabled={pending}>
            Ödemeyi onayla (başarılı)
          </Button>
          <Button variant="secondary" onClick={() => void complete("failure")} disabled={pending}>
            Ödemeyi reddet (başarısız)
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted">Bu sipariş artık ödeme beklemiyor.</p>
      )}
    </Card>
  );
}
