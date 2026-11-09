import type { Metadata } from "next";

import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, LinkButton, Notice, PageHeader } from "@/components/ui";
import { deviceLabel, durationLabel, formatPrice } from "@/lib/format";
import { fetchPlans, groupPlans } from "@/lib/plans";

export const metadata: Metadata = {
  title: "Paketler",
  description: "Lisans paketleri: süre ve bilgisayar sayısına göre seçenekler, 7 günlük deneme.",
};

const PLANNED_DURATIONS = ["30 gün", "90 gün", "180 gün", "365 gün", "Süresiz"];

export default async function PlansPage() {
  const { plans, reachable } = await fetchPlans();
  const { trial, groups } = groupPlans(plans);
  const onSale = groups.length > 0 || trial !== undefined;

  return (
    <>
      <PageHeader
        eyebrow="Fiyatlandırma"
        title="Paketler"
        lead="Lisanslar süreye ve aynı anda kullanılabilecek bilgisayar sayısına göre ayrılır. Her pakette tüm özellikler ve iPhone uygulaması bulunur."
      />
      <Container className="py-12">
        {onSale ? (
          <>
            {trial ? (
              <Card className="mb-8 flex flex-col justify-between gap-4 md:flex-row md:items-center">
                <div>
                  <h2 className="text-xl font-semibold text-fg">{trial.name}</h2>
                  <p className="mt-1 text-muted">
                    {durationLabel(trial.duration_days)} boyunca {deviceLabel(trial.device_limit)}; tüm özellikler, sanal işlem ve test ağı.
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <p className="text-2xl font-bold text-fg">{formatPrice(trial.price_minor, trial.currency)}</p>
                  <LinkButton href={`/satin-al?paket=${encodeURIComponent(trial.code)}`}>Denemeyi başlat</LinkButton>
                </div>
              </Card>
            ) : null}
            <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3" aria-label="Paket seçenekleri">
              {groups.map((group) => (
                <Card as="li" key={group.key}>
                  <h2 className="text-xl font-semibold text-fg">{durationLabel(group.durationDays)}</h2>
                  <p className="mt-1 text-sm text-muted">
                    {group.durationDays === null ? "Tek seferlik ödeme, süre sınırı yok" : "Süre sonunda yenileyebilirsiniz"}
                  </p>
                  <ul className="mt-5 divide-y divide-border">
                    {group.options.map((plan) => (
                      <li key={plan.code} className="flex items-center justify-between gap-3 py-3">
                        <div>
                          <p className="font-medium text-fg">{deviceLabel(plan.device_limit)}</p>
                          <p className="text-lg font-bold text-fg">{formatPrice(plan.price_minor, plan.currency)}</p>
                        </div>
                        <LinkButton
                          href={`/satin-al?paket=${encodeURIComponent(plan.code)}`}
                          variant="secondary"
                          aria-label={`${plan.name} paketini seç`}
                        >
                          Seç
                        </LinkButton>
                      </li>
                    ))}
                  </ul>
                </Card>
              ))}
            </ul>
            <p className="mt-6 text-sm text-muted">Vergi, ödeme ve fatura ayrıntıları satın alma adımında gösterilir.</p>
          </>
        ) : (
          <div className="max-w-3xl">
            <Notice tone="info" title="Fiyatlar yakında açıklanacak" role="status">
              {reachable
                ? "Paketler henüz satışa açılmadı. Hesap oluşturursanız satış başladığında sizi bilgilendiririz."
                : "Paket bilgileri şu anda yüklenemedi. Lütfen biraz sonra tekrar deneyin."}
            </Notice>
            <h2 className="mt-10 text-xl font-semibold text-fg">Planlanan seçenekler</h2>
            <div className="legal">
              <ul>
                <li>Süre: {PLANNED_DURATIONS.join(", ")}</li>
                <li>Her sürede 1, 2 veya 3 bilgisayar seçeneği</li>
                <li>7 günlük deneme (1 bilgisayar)</li>
                <li>Tüm paketlerde iPhone uygulaması ve aynı özellikler</li>
              </ul>
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/kayit">Hesap oluştur</LinkButton>
              <LinkButton href="/iletisim" variant="secondary">
                Soru sorun
              </LinkButton>
            </div>
          </div>
        )}
        <div className="mt-12 max-w-3xl">
          <RiskNotice />
        </div>
      </Container>
    </>
  );
}
