// Ana sayfa "Yenilikler" görseli: kilit ekranına gelen işlem bildirimleri ve anlık değişen fiyatlar.
// Temsilî görüntüdür (örnek veriler); kâr ve zarar örneği birlikte gösterilir, kazanç vaadi yoktur.

import { BellRing, LockKeyhole, Zap } from "lucide-react";

import { LogoMark } from "@/components/Logo";
import { Badge, Container, LinkButton } from "@/components/ui";

const NOTIFICATIONS = [
  {
    title: "📈 SOLUSDT Short açıldı",
    body: "Demo · Futures · 3 @ 182,40 · stop 186,10 · hedef 177,80",
    when: "şimdi",
  },
  {
    title: "✅ BNBUSDT Long kapandı · +6,42 USDT",
    body: "giriş 612,30 → çıkış 624,10 · kâr al hedefi · 1 sa 12 dk",
    when: "8 dk önce",
  },
  {
    title: "🔻 ETHUSDT Long kapandı · −0,79 USDT",
    body: "giriş 3.420,00 → çıkış 3.404,20 · zarar durdur (stop) · 26 dk",
    when: "41 dk önce",
  },
];

// Satır içi stil sitenin güvenlik politikasıyla (CSP) engellenir: gecikmeler sınıf olarak verilir.
const NOTIF_DELAY = ["[animation-delay:300ms]", "[animation-delay:650ms]", "[animation-delay:1000ms]"];
const TICK_DELAY = ["[animation-delay:0ms]", "[animation-delay:550ms]", "[animation-delay:1100ms]", "[animation-delay:1650ms]", "[animation-delay:2200ms]"];

const PRICES = [
  { symbol: "BTCUSDT", price: "97.250,10", change: "+1,18%", up: true },
  { symbol: "ETHUSDT", price: "3.404,20", change: "−0,46%", up: false },
  { symbol: "SOLUSDT", price: "177,79", change: "+2,53%", up: true },
  { symbol: "BNBUSDT", price: "624,10", change: "+0,74%", up: true },
  { symbol: "XRPUSDT", price: "2,1840", change: "−1,05%", up: false },
];

const POINTS = [
  { icon: Zap, title: "Fiyatlar anında", text: "Binance'teki her fiyat değişimi coin listesine, pozisyonlara ve bakiyeye beklemeden düşer." },
  { icon: BellRing, title: "Kilit ekranına bildirim", text: "İşlem açılınca ve kapanınca stop, hedef, kâr/zarar ayrıntısıyla telefona gelir. Uygulama indirmek gerekmez." },
  { icon: LockKeyhole, title: "Şifreli", text: "Bildirim içeriği bilgisayarınızda şifrelenir; aradaki sunucular okuyamaz." },
];

export function LiveShowcase() {
  return (
    <section id="yenilikler" aria-labelledby="yenilikler-baslik" className="relative overflow-hidden border-b border-border">
      <Container className="grid items-center gap-14 py-20 lg:grid-cols-[1fr_1.05fr] lg:py-24">
        <div>
          <Badge tone="accent" className="py-1.5 pl-1.5">
            <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-semibold text-white">Yeni</span>
            Anlık fiyat ve telefon bildirimleri
          </Badge>
          <h2 id="yenilikler-baslik" className="mt-6 text-3xl font-semibold tracking-tight text-fg sm:text-[2.6rem] sm:leading-[1.1]">
            Piyasa kıpırdadığı an <span className="text-gradient">ekranınızda</span>, işlem olduğu an cebinizde.
          </h2>
          <ul className="mt-8 space-y-5">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand text-white shadow-glow" aria-hidden="true">
                  <Icon className="h-5 w-5" />
                </span>
                <span>
                  <span className="block font-semibold text-fg">{title}</span>
                  <span className="mt-0.5 block text-muted">{text}</span>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-9 flex flex-wrap gap-3">
            <LinkButton href="/indir">Uygulamayı indirin</LinkButton>
            <LinkButton href="/ozellikler" variant="secondary">
              Tüm özellikler
            </LinkButton>
          </div>
        </div>

        <figure className="relative">
          <div aria-hidden="true" className="relative mx-auto flex max-w-xl justify-center sm:justify-end sm:pr-4">
            {/* Telefon kilit ekranı */}
            <div className="relative z-10 w-[17.5rem] rounded-[2.8rem] border border-white/10 bg-[#0b1024] p-2.5 shadow-lift">
              <div className="relative overflow-hidden rounded-[2.3rem] bg-[linear-gradient(160deg,#1b2a6b_0%,#3b1f73_55%,#11183f_100%)] px-3.5 pb-8 pt-10 text-white">
                <div className="absolute left-1/2 top-2.5 h-6 w-24 -translate-x-1/2 rounded-full bg-black/80" />
                <p className="text-center text-[13px] font-medium text-white/80">Perşembe, 13 Kasım</p>
                <p className="text-center text-6xl font-semibold tracking-tight">09:41</p>
                <ul className="mt-7 space-y-2.5">
                  {NOTIFICATIONS.map((n, i) => (
                    <li
                      key={n.title}
                      className={`notif-in rounded-2xl border border-white/15 bg-white/12 p-3 backdrop-blur-md ${NOTIF_DELAY[i] ?? ""}`}
                    >
                      <div className="flex items-center gap-2 text-[11px] text-white/75">
                        <LogoMark className="h-4 w-4" />
                        <span className="font-semibold uppercase tracking-wide">AI Trading</span>
                        <span className="ml-auto">{n.when}</span>
                      </div>
                      <p className="mt-1 text-[13px] font-semibold leading-snug">{n.title}</p>
                      <p className="text-[11.5px] leading-snug text-white/80">{n.body}</p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            {/* Anlık fiyat kartı */}
            <div className="absolute bottom-12 left-0 z-20 hidden w-60 rounded-3xl border border-border bg-surface p-4 shadow-lift sm:block">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-muted">
                <span className="pulse-dot h-2 w-2 rounded-full bg-up text-up" /> Canlı fiyatlar
              </p>
              <ul className="mt-2.5 space-y-1.5 text-sm">
                {PRICES.map((p, i) => (
                  <li key={p.symbol} className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-fg">{p.symbol}</span>
                    <span className="flex items-center gap-2">
                      <span className={`tick tabular rounded-md px-1.5 ${p.up ? "tick-up" : "tick-down"} ${TICK_DELAY[i] ?? ""}`}>
                        {p.price}
                      </span>
                      <span className={`w-14 text-right text-xs font-semibold ${p.up ? "text-success-fg" : "text-danger-fg"}`}>{p.change}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <figcaption className="mt-12 text-center text-xs text-muted">
            Temsilî görüntü, örnek verilerle. İşlemler kârla da zararla da sonuçlanabilir; kazanç garantisi yoktur.
          </figcaption>
        </figure>
      </Container>
    </section>
  );
}
