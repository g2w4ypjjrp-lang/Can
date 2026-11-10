"use client";

import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, LinkButton, Notice, TextLink } from "@/components/ui";
import { ApiError, type CheckoutResult, type Me, type PaymentStatus } from "@/lib/api";
import { formatPrice } from "@/lib/format";

interface PlanSummary {
  code: string;
  name: string;
  price_minor: number;
  currency: string;
  is_trial: boolean;
}

interface Quote {
  code: string;
  subtotal_minor: number;
  discount_minor: number;
  total_minor: number;
  currency: string;
}

type Viewer = { kind: "loading" } | { kind: "anonymous" } | { kind: "customer"; me: Me } | { kind: "error"; message: string };

const CONSENTS = [
  {
    name: "accept_preinfo",
    label: (
      <>
        <TextLink href="/yasal/on-bilgilendirme" target="_blank" rel="noopener">
          Ön bilgilendirme formunu
        </TextLink>{" "}
        okudum ve onaylıyorum.
      </>
    ),
  },
  {
    name: "accept_contract",
    label: (
      <>
        <TextLink href="/yasal/mesafeli-satis-sozlesmesi" target="_blank" rel="noopener">
          Mesafeli satış sözleşmesini
        </TextLink>{" "}
        okudum ve kabul ediyorum.
      </>
    ),
  },
  {
    name: "accept_immediate_delivery",
    label: (
      <>
        Lisansın ödeme onayından hemen sonra elektronik ortamda teslim edileceğini ve bu nedenle{" "}
        <TextLink href="/yasal/iptal-ve-iade" target="_blank" rel="noopener">
          cayma hakkının
        </TextLink>{" "}
        kullanılamayacağını kabul ediyorum.
      </>
    ),
  },
] as const;

export function CheckoutForm({ plan }: { plan: PlanSummary }) {
  const api = useApi();
  const [viewer, setViewer] = useState<Viewer>({ kind: "loading" });
  const [status, setStatus] = useState<PaymentStatus | null>(null);
  const { pending, error, run } = useSubmit();
  const [leaving, setLeaving] = useState(false);
  const [couponInput, setCouponInput] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const coupon = useSubmit();
  const free = plan.price_minor === 0;
  const total = quote ? quote.total_minor : plan.price_minor;

  function applyCoupon() {
    const code = couponInput.trim();
    if (!code) return;
    void coupon.run(async () => {
      setQuote(await api.post<Quote>("/v1/coupons/check", { plan_code: plan.code, code }));
    });
  }
  const next = `/satin-al?paket=${encodeURIComponent(plan.code)}`;

  useEffect(() => {
    let cancelled = false;
    api
      .get<PaymentStatus>("/v1/payments/status")
      .then((value) => !cancelled && setStatus(value))
      .catch(() => !cancelled && setStatus({ open: false, test_mode: false, provider: null, legal_version: "" }));
    api
      .get<Me>("/v1/me")
      .then((me) => !cancelled && setViewer({ kind: "customer", me }))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) setViewer({ kind: "anonymous" });
        else setViewer({ kind: "error", message: err instanceof Error ? err.message : "Bilgiler yüklenemedi" });
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await run(async () => {
      const taxId = formValue(form, "tax_id").replace(/\s/g, "");
      const result = await api.post<CheckoutResult>("/v1/checkout", {
        plan_code: plan.code,
        billing: {
          full_name: formValue(form, "full_name").trim(),
          phone: formValue(form, "phone").trim(),
          address: formValue(form, "address").trim(),
          city: formValue(form, "city").trim(),
          country: formValue(form, "country").trim() || "Türkiye",
          tax_id: taxId || null,
        },
        accept_preinfo: data.get("accept_preinfo") === "on",
        accept_contract: data.get("accept_contract") === "on",
        accept_immediate_delivery: data.get("accept_immediate_delivery") === "on",
        coupon: quote?.code ?? null,
      });
      setLeaving(true);
      window.location.assign(result.redirect_url);
    });
  }

  if (viewer.kind === "loading" || status === null) {
    return (
      <p role="status" className="text-muted">
        Ödeme bilgileri yükleniyor…
      </p>
    );
  }
  if (viewer.kind === "error") {
    return (
      <Notice tone="danger" role="alert">
        {viewer.message}
      </Notice>
    );
  }
  if (viewer.kind === "anonymous") {
    return (
      <div className="space-y-4">
        <Notice tone="info" title="Satın almak için giriş yapın" role="status">
          Lisans, hesabınıza tanımlanır ve müşteri panelinizde görünür.
        </Notice>
        <div className="flex flex-wrap gap-3">
          <LinkButton href={`/giris?sonra=${encodeURIComponent(next)}`}>Giriş yap</LinkButton>
          <LinkButton href="/kayit" variant="secondary">
            Hesap oluştur
          </LinkButton>
        </div>
      </div>
    );
  }
  if (!viewer.me.email_verified) {
    return (
      <Notice tone="warning" title="E-posta adresinizi doğrulayın" role="status">
        Satın almadan önce {viewer.me.email} adresine gönderdiğimiz bağlantıyı açın. Bağlantı gelmediyse giriş
        sayfasından yeniden isteyebilirsiniz.
      </Notice>
    );
  }
  if (!free && !status.open) {
    return (
      <Notice tone="warning" title="Çevrim içi ödeme şu anda kapalı" role="status">
        Ödeme altyapısı açıldığında satın alma bu sayfadan yapılacak. Bilgi almak için{" "}
        <TextLink href="/iletisim">bize yazın</TextLink>.
      </Notice>
    );
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-5" aria-describedby="odeme-aciklama">
      {status.test_mode && !free ? (
        <Notice tone="warning" title="Test modu" role="note">
          Ödeme sistemi test modunda: gerçek tahsilat yapılmaz.
        </Notice>
      ) : null}
      <fieldset className="space-y-4">
        <legend className="text-base font-semibold text-fg">Fatura bilgileri</legend>
        <Field id="full_name" name="full_name" label="Ad soyad" autoComplete="name" required minLength={3} maxLength={120} defaultValue={viewer.me.full_name ?? ""} />
        <Field id="phone" name="phone" label="Telefon" type="tel" autoComplete="tel" required pattern="\+?[0-9 ()\-]{10,20}" placeholder="+90 5xx xxx xx xx" />
        <Field id="address" name="address" label="Adres" autoComplete="street-address" required minLength={10} maxLength={400} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="city" name="city" label="Şehir" autoComplete="address-level1" required minLength={2} maxLength={50} />
          <Field id="country" name="country" label="Ülke" autoComplete="country-name" required minLength={2} maxLength={50} defaultValue="Türkiye" />
        </div>
        <Field
          id="tax_id"
          name="tax_id"
          label="T.C. kimlik no veya vergi no"
          inputMode="numeric"
          pattern="[0-9]{10,11}"
          maxLength={11}
          hint="Fatura için; şirket adına alımda vergi numarası."
        />
      </fieldset>
      {free ? null : (
        <fieldset className="space-y-3">
          <legend className="text-base font-semibold text-fg">İndirim kuponu</legend>
          {quote ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-success-border bg-success-bg px-4 py-3 text-sm text-success-fg" role="status" data-testid="coupon-applied">
              <span>
                <strong>{quote.code}</strong> uygulandı: −{formatPrice(quote.discount_minor, quote.currency)} · Ödenecek{" "}
                <strong>{formatPrice(quote.total_minor, quote.currency)}</strong>
              </span>
              <Button type="button" variant="secondary" size="sm" className="px-3 py-1.5" onClick={() => setQuote(null)}>
                Kaldır
              </Button>
            </div>
          ) : (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field
                  id="coupon"
                  name="coupon"
                  label="Kupon kodu"
                  autoComplete="off"
                  maxLength={32}
                  value={couponInput}
                  onChange={(e) => setCouponInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      applyCoupon();
                    }
                  }}
                />
              </div>
              <Button type="button" variant="secondary" onClick={applyCoupon} disabled={coupon.pending || !couponInput.trim()}>
                Uygula
              </Button>
            </div>
          )}
          <ErrorBox error={coupon.error} />
        </fieldset>
      )}
      <fieldset className="space-y-3">
        <legend className="text-base font-semibold text-fg">Onaylar</legend>
        {CONSENTS.map((consent) => (
          <div key={consent.name} className="flex items-start gap-3">
            <input id={consent.name} name={consent.name} type="checkbox" required className="mt-1 h-4 w-4 shrink-0 accent-accent" />
            <label htmlFor={consent.name} className="text-sm text-fg">
              {consent.label}
            </label>
          </div>
        ))}
      </fieldset>
      <ErrorBox error={error} />
      <Button type="submit" className="w-full" disabled={pending || leaving}>
        {pending || leaving
          ? "Yönlendiriliyor…"
          : free
            ? "Denemeyi başlat"
            : total === 0
              ? "Lisansı al"
              : `Ödemeye geç · ${formatPrice(total, plan.currency)}`}
      </Button>
      <p id="odeme-aciklama" className="text-center text-sm text-muted">
        {free
          ? "Deneme lisansı hesabınıza hemen tanımlanır."
          : "Kart bilgileriniz bu sitede girilmez ve saklanmaz; ödeme, lisanslı ödeme kuruluşunun güvenli sayfasında yapılır."}
      </p>
    </form>
  );
}
