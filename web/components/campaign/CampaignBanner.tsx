// Paketler sayfasındaki kampanya afişi: akan renkler, ışıltı, düşen konfeti, sallanan indirim
// etiketi ve geri sayım. Görseller süs amaçlıdır (ekran okuyucudan gizli); metin her zaman okunur.

import { Flame } from "lucide-react";

import { Countdown } from "@/components/campaign/Countdown";
import { formatDate } from "@/lib/format";
import type { CampaignInfo } from "@/lib/plans";

// Satır içi stil güvenlik politikasıyla engellenir: konum, gecikme ve renkler sınıf olarak verilir.
const CONFETTI = [
  "left-[4%] bg-amber-300 [animation-delay:0s]",
  "left-[11%] bg-white [animation-delay:1.9s]",
  "left-[19%] bg-pink-300 [animation-delay:3.1s]",
  "left-[27%] bg-yellow-200 [animation-delay:0.8s]",
  "left-[36%] bg-sky-300 [animation-delay:2.5s]",
  "left-[44%] bg-white [animation-delay:4s]",
  "left-[53%] bg-amber-300 [animation-delay:1.3s]",
  "left-[61%] bg-lime-300 [animation-delay:3.6s]",
  "left-[69%] bg-pink-200 [animation-delay:0.4s]",
  "left-[77%] bg-yellow-300 [animation-delay:2.2s]",
  "left-[85%] bg-white [animation-delay:3.3s]",
  "left-[93%] bg-sky-200 [animation-delay:1.1s]",
];

function DiscountTag({ percent }: { percent: number }) {
  return (
    <svg viewBox="0 0 120 150" className="tag-swing h-28 w-24 shrink-0 drop-shadow-xl sm:h-32 sm:w-28" aria-hidden="true">
      <path d="M60 4 v16" stroke="rgba(255,255,255,.85)" strokeWidth="3" strokeLinecap="round" />
      <path d="M24 32 L60 16 L96 32 V136 a10 10 0 0 1 -10 10 H34 a10 10 0 0 1 -10 -10 Z" fill="#fff" />
      <circle cx="60" cy="34" r="6" fill="#be123c" />
      <text x="60" y="84" textAnchor="middle" fontSize={percent >= 10 ? 29 : 34} fontWeight="800" fill="#be123c" fontFamily="inherit">
        %{percent}
      </text>
      <text x="60" y="110" textAnchor="middle" fontSize="15" fontWeight="800" fill="#7c2d12" letterSpacing="1.5" fontFamily="inherit">
        İNDİRİM
      </text>
    </svg>
  );
}

export function CampaignBanner({ campaign }: { campaign: CampaignInfo }) {
  const ends = campaign.endsAt && new Date(campaign.endsAt).getTime() > Date.now() ? campaign.endsAt : null;
  return (
    <section
      aria-label="İndirim kampanyası"
      data-testid="campaign-banner"
      className="sale-gradient sale-sparkles relative mb-10 overflow-hidden rounded-[2rem] px-6 py-7 shadow-lift sm:px-9"
    >
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        {CONFETTI.map((c) => (
          <span key={c} className={`confetti ${c}`} />
        ))}
      </div>
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <DiscountTag percent={campaign.percent} />
          <div>
            <p className="inline-flex items-center gap-1.5 rounded-full bg-black/25 px-3 py-1 text-xs font-bold uppercase tracking-wider">
              <Flame aria-hidden="true" className="wiggle h-3.5 w-3.5" /> Sınırlı süre
            </p>
            <h2 className="mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">
              %{campaign.percent} indirim başladı
            </h2>
            <p className="mt-1.5 text-base text-white/95">
              <strong className="font-semibold">{campaign.label ?? "Kampanya"}: bütün paketlerde %{campaign.percent} indirim</strong>
              {ends ? <> · {formatDate(ends)} tarihine kadar</> : null}. İndirimli fiyatlar aşağıda.
            </p>
          </div>
        </div>
        {ends ? (
          <div className="shrink-0">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/90">Bitmesine</p>
            <Countdown endsAt={ends} testId="campaign-countdown" />
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** Paket kartının üst kenarında asılı duran hareketli indirim etiketi. */
export function SaleRibbon({ percent }: { percent: number }) {
  return (
    <span className="sale-badge absolute -top-3.5 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap px-3.5 py-1 text-[13px] shadow-lg" data-testid="sale-ribbon">
      <Flame aria-hidden="true" className="wiggle h-3.5 w-3.5" /> %{percent} İNDİRİM
    </span>
  );
}
