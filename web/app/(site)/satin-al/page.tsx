import type { Metadata } from "next";

import { PriceTag } from "@/components/PriceTag";
import { CheckoutForm } from "@/components/purchase/CheckoutForm";
import { Card, Container, Notice, PageHeader, TextLink } from "@/components/ui";
import { deviceLabel, durationLabel, firstParam } from "@/lib/format";
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
        {plan ? (
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <Card className="order-2 lg:order-1">
              <CheckoutForm
                plan={{
                  code: plan.code,
                  name: plan.name,
                  price_minor: plan.price_minor,
                  list_price_minor: plan.list_price_minor ?? null,
                  campaign_percent: plan.campaign_percent ?? null,
                  currency: plan.currency,
                  is_trial: plan.is_trial,
                }}
              />
            </Card>
            <aside aria-labelledby="ozet" className="order-1 lg:order-2">
              <Card>
                <h2 id="ozet" className="text-lg font-semibold text-fg">
                  Sipariş özeti
                </h2>
                <p className="mt-1 text-fg">{plan.name}</p>
                <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                  <dt className="text-muted">Süre</dt>
                  <dd className="text-fg">{durationLabel(plan.duration_days)}</dd>
                  <dt className="text-muted">Bilgisayar</dt>
                  <dd className="text-fg">{deviceLabel(plan.device_limit)}</dd>
                  <dt className="text-muted">iPhone</dt>
                  <dd className="text-fg">{plan.companion_device_limit} cihaz</dd>
                  <dt className="text-muted">Tutar</dt>
                  <dd className="text-lg font-bold text-fg" data-testid="order-total">
                    <PriceTag
                      minor={plan.price_minor}
                      currency={plan.currency}
                      listMinor={plan.list_price_minor}
                      percent={plan.campaign_percent}
                      priceClassName="text-lg font-bold text-fg"
                    />
                  </dd>
                </dl>
                <p className="mt-4 text-sm text-muted">
                  Lisans süresi, ilk bilgisayarda etkinleştirildiği anda başlar. Satın almadan önce{" "}
                  <TextLink href="/yasal/risk-bildirimi">risk bildirimini</TextLink> okuyun: yazılım kazanç garantisi
                  vermez.
                </p>
              </Card>
            </aside>
          </div>
        ) : (
          <div className="max-w-2xl">
            <Notice tone="info" title="Paket bulunamadı" role="status">
              Seçtiğiniz paket satışta değil. <TextLink href="/paketler">Paketlere dönün</TextLink>.
            </Notice>
          </div>
        )}
      </Container>
    </>
  );
}
