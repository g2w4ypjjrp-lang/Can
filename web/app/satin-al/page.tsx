import type { Metadata } from "next";

import { Card, Container, Notice, PageHeader, TextLink } from "@/components/ui";
import { deviceLabel, durationLabel, firstParam, formatPrice } from "@/lib/format";
import { fetchPlans } from "@/lib/plans";

export const metadata: Metadata = {
  title: "Satın al",
  robots: { index: false, follow: false },
};

export default async function PurchasePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const code = firstParam((await searchParams).paket);
  const { plans } = await fetchPlans();
  const plan = plans.find((p) => p.code === code);

  return (
    <>
      <PageHeader title="Satın al" />
      <Container className="py-12">
        <div className="max-w-2xl">
          {plan ? (
            <Card>
              <h2 className="text-xl font-semibold text-fg">{plan.name}</h2>
              <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <dt className="text-muted">Süre</dt>
                <dd className="text-fg">{durationLabel(plan.duration_days)}</dd>
                <dt className="text-muted">Bilgisayar</dt>
                <dd className="text-fg">{deviceLabel(plan.device_limit)}</dd>
                <dt className="text-muted">Tutar</dt>
                <dd className="text-lg font-bold text-fg">{formatPrice(plan.price_minor, plan.currency)}</dd>
              </dl>
              <div className="mt-6">
                <Notice tone="warning" title="Çevrim içi ödeme henüz açılmadı" role="status">
                  Ödeme altyapısı devreye alındığında satın alma bu sayfadan yapılacak. Ödeme öncesinde ön
                  bilgilendirme formu ve mesafeli satış sözleşmesi burada gösterilecektir.
                </Notice>
              </div>
              <button
                type="button"
                disabled
                aria-describedby="odeme-kapali"
                className="mt-6 w-full cursor-not-allowed rounded-lg bg-surface-2 px-5 py-3 text-sm font-semibold text-muted"
              >
                Ödemeye geç
              </button>
              <p id="odeme-kapali" className="mt-2 text-center text-sm text-muted">
                Ödeme şu anda kapalı.
              </p>
            </Card>
          ) : (
            <Notice tone="info" title="Paket bulunamadı" role="status">
              Seçtiğiniz paket satışta değil. <TextLink href="/paketler">Paketlere dönün</TextLink>.
            </Notice>
          )}
          <p className="mt-6 text-sm text-muted">
            Satın almadan önce <TextLink href="/yasal/kullanim-kosullari">kullanım koşullarını</TextLink> ve{" "}
            <TextLink href="/yasal/risk-bildirimi">risk bildirimini</TextLink> okuyun.
          </p>
        </div>
      </Container>
    </>
  );
}
