import type { Metadata } from "next";

import { BadgePercent, CalendarClock, Check, Infinity as InfinityIcon, Sparkles } from "lucide-react";

import { PriceTag } from "@/components/PriceTag";
import { RiskNotice } from "@/components/RiskNotice";
import { Badge, Container, IconTile, LinkButton, Notice, PageHeader } from "@/components/ui";
import { deviceLabel, durationLabel, formatDate, formatPrice } from "@/lib/format";
import { activeCampaign, fetchPlans, groupPlans } from "@/lib/plans";

export const metadata: Metadata = {
  title: "Paketler",
  description: "Lisans paketleri: süre ve bilgisayar sayısına göre seçenekler, 7 günlük deneme.",
};

const PLANNED_DURATIONS = ["30 gün", "90 gün", "180 gün", "365 gün", "Süresiz"];

export default async function PlansPage() {
  const { plans, reachable } = await fetchPlans();
  const { trial, groups } = groupPlans(plans);
  const onSale = groups.length > 0 || trial !== undefined;
  const campaign = activeCampaign(plans);

  return (
    <>
      <PageHeader
        eyebrow="Fiyatlandırma"
        title="Paketler"
        lead="Lisanslar süreye ve aynı anda kullanılabilecek bilgisayar sayısına göre ayrılır. Her pakette tüm özellikler ve iPhone uygulaması bulunur."
      />
      <Container className="py-14">
        {onSale ? (
          <>
            {campaign ? (
              <div
                className="mb-8 flex flex-wrap items-center gap-4 rounded-3xl border border-success-border bg-success-bg px-6 py-4 text-success-fg"
                role="status"
                data-testid="campaign-banner"
              >
                <BadgePercent aria-hidden="true" className="h-7 w-7 shrink-0" />
                <p className="text-base">
                  <strong className="font-semibold">{campaign.label ?? "Kampanya"}:</strong> bütün paketlerde %{campaign.percent} indirim
                  {campaign.endsAt ? <> · {formatDate(campaign.endsAt)} tarihine kadar</> : null}. İndirimli fiyatlar aşağıda gösterilir.
                </p>
              </div>
            ) : null}
            {trial ? (
              <div className="gradient-border mb-10 flex flex-col justify-between gap-6 rounded-3xl p-7 shadow-lift md:flex-row md:items-center">
                <div className="flex items-start gap-4">
                  <IconTile icon={Sparkles} tone="violet" />
                  <div>
                    <h2 className="text-xl font-semibold text-fg">{trial.name}</h2>
                    <p className="mt-1 text-muted">
                      {durationLabel(trial.duration_days)} boyunca {deviceLabel(trial.device_limit)}; tüm özellikler, sanal işlem ve Binance Demo Trading.
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-5">
                  <p className="text-3xl font-semibold tracking-tight text-fg">{formatPrice(trial.price_minor, trial.currency)}</p>
                  <LinkButton href={`/satin-al?paket=${encodeURIComponent(trial.code)}`}>Denemeyi başlat</LinkButton>
                </div>
              </div>
            ) : null}
            <ul className="grid gap-6 md:grid-cols-2 xl:grid-cols-3" aria-label="Paket seçenekleri">
              {groups.map((group) => {
                const long = group.durationDays === null || group.durationDays >= 365;
                return (
                  <li
                    key={group.key}
                    className={`card-lift relative flex flex-col rounded-3xl p-7 ${long ? "gradient-border shadow-lift" : "border border-border bg-surface shadow-sm"}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <IconTile icon={group.durationDays === null ? InfinityIcon : CalendarClock} tone={long ? "violet" : "accent"} />
                      {long ? (
                        <Badge tone="accent">{group.durationDays === null ? "Tek seferlik" : "Uzun dönem"}</Badge>
                      ) : null}
                    </div>
                    <h2 className="mt-5 text-2xl font-semibold tracking-tight text-fg">{durationLabel(group.durationDays)}</h2>
                    <p className="mt-1 text-sm text-muted">
                      {group.durationDays === null ? "Tek seferlik ödeme, süre sınırı yok" : "Süre sonunda yenileyebilirsiniz"}
                    </p>
                    <ul className="mt-6 space-y-2.5">
                      {group.options.map((plan) => (
                        <li key={plan.code} className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-bg/60 px-4 py-3">
                          <div>
                            <p className="text-sm font-medium text-muted">{deviceLabel(plan.device_limit)}</p>
                            <PriceTag
                              minor={plan.price_minor}
                              currency={plan.currency}
                              listMinor={plan.list_price_minor}
                              percent={plan.campaign_percent}
                              testId={`price-${plan.code}`}
                            />
                          </div>
                          <LinkButton
                            href={`/satin-al?paket=${encodeURIComponent(plan.code)}`}
                            variant={long ? "primary" : "secondary"}
                            size="sm"
                            aria-label={`${plan.name} paketini seç`}
                          >
                            Seç
                          </LinkButton>
                        </li>
                      ))}
                    </ul>
                    <ul className="mt-6 space-y-2 border-t border-border pt-5 text-sm text-fg">
                      {["Tüm özellikler", "iPhone uygulaması dâhil", "Cihazları panelden yönetme"].map((item) => (
                        <li key={item} className="flex items-center gap-2">
                          <Check aria-hidden="true" className="h-4 w-4 text-success-fg" /> {item}
                        </li>
                      ))}
                    </ul>
                  </li>
                );
              })}
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
