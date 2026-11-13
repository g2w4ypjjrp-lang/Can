"use client";

// Canlı fiyatlar: sunucunun ilk verisiyle açılır, 15 saniyede bir aynı kökendeki /api/piyasa
// üzerinden yenilenir (tarayıcı Binance'e doğrudan bağlanmaz). Veri yoksa hiçbir şey gösterilmez.

import { ExternalLink, TrendingDown, TrendingUp } from "lucide-react";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { CoinToken } from "@/components/forum/Visuals";
import { formatChange, formatQuote, type Quote } from "@/lib/market";

interface Live {
  quotes: Quote[];
  flash: Record<string, { dir: "up" | "down"; n: number }>;
}

const LiveContext = createContext<Live>({ quotes: [], flash: {} });

export function QuotesProvider({ initial, extra = [], children }: { initial: Quote[]; extra?: string[]; children: ReactNode }) {
  const [live, setLive] = useState<Live>({ quotes: initial, flash: {} });
  const key = extra.join(",");
  const enabled = initial.length > 0;
  const counter = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    async function refresh() {
      try {
        const response = await fetch(`/api/piyasa${key ? `?c=${encodeURIComponent(key)}` : ""}`, { cache: "no-store" });
        if (!response.ok) return;
        const body = (await response.json()) as { quotes?: Quote[] };
        if (stopped || !body.quotes?.length) return;
        setLive((prev) => {
          const before = new Map(prev.quotes.map((q) => [q.base, q.price]));
          const flash = { ...prev.flash };
          for (const q of body.quotes ?? []) {
            const old = before.get(q.base);
            if (old !== undefined && old !== q.price) {
              counter.current += 1;
              flash[q.base] = { dir: q.price > old ? "up" : "down", n: counter.current };
            }
          }
          return { quotes: body.quotes ?? prev.quotes, flash };
        });
      } catch {
        // Ağ hatası: bir sonraki turda tekrar denenir.
      }
    }
    const timer = window.setInterval(() => void refresh(), 15_000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [enabled, key]);

  return <LiveContext.Provider value={live}>{children}</LiveContext.Provider>;
}

function useLive() {
  return useContext(LiveContext);
}

function Change({ pct, className = "" }: { pct: number; className?: string }) {
  const up = pct >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 font-semibold tabular ${up ? "text-up" : "text-down"} ${className}`}>
      <span aria-hidden="true">{up ? "▲" : "▼"}</span>
      {formatChange(pct)}
    </span>
  );
}

/** Sayfanın üstünde akan fiyat bandı. */
export function MarketTicker() {
  const { quotes, flash } = useLive();
  if (!quotes.length) return null;
  return (
    <aside aria-label="Canlı piyasa" className="relative border-b border-border bg-bg/90" data-testid="market-ticker">
      <div className="flex items-center">
        <p className="z-10 flex shrink-0 items-center gap-2 border-r border-border bg-surface px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-fg">
          <span aria-hidden="true" className="pulse-dot h-2 w-2 rounded-full bg-up text-up" /> Canlı
        </p>
        <div className="marquee-mask min-w-0 flex-1 overflow-hidden">
          <div className="marquee">
            {[0, 1].map((copy) => (
              <ul key={copy} aria-hidden={copy === 1 ? true : undefined} className="flex shrink-0 items-center gap-7 px-4 py-2 text-sm">
                {quotes.map((q) => {
                  const f = flash[q.base];
                  return (
                    <li key={q.base} className="flex items-center gap-2 whitespace-nowrap">
                      <CoinToken symbol={q.base} size="xs" />
                      <span className="font-semibold text-fg">{q.base}</span>
                      <span key={f?.n ?? 0} className={`tabular rounded px-1 text-fg ${f ? (f.dir === "up" ? "flash-up" : "flash-down") : ""}`}>
                        {formatQuote(q.price)}
                      </span>
                      <Change pct={q.changePct} className="text-xs" />
                    </li>
                  );
                })}
              </ul>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Kenar çubuğundaki piyasa tablosu. */
export function MarketBoard({ limit = 8 }: { limit?: number }) {
  const { quotes, flash } = useLive();
  if (!quotes.length) return null;
  return (
    <section aria-labelledby="piyasa-baslik" className="rounded-2xl border border-border bg-surface p-4">
      <h2 id="piyasa-baslik" className="flex items-center justify-between text-sm font-semibold text-fg">
        Piyasa <span className="text-xs font-normal text-muted">24 sa · USDT</span>
      </h2>
      <ul className="mt-3 space-y-1.5">
        {quotes.slice(0, limit).map((q) => {
          const f = flash[q.base];
          return (
            <li key={q.base} className="flex items-center justify-between gap-2 rounded-lg px-1.5 py-1 text-sm hover:bg-surface-2">
              <span className="flex items-center gap-2">
                <CoinToken symbol={q.base} size="xs" />
                <span className="font-semibold text-fg">{q.base}</span>
              </span>
              <span className="flex items-center gap-2">
                <span key={f?.n ?? 0} className={`tabular rounded px-1 text-fg ${f ? (f.dir === "up" ? "flash-up" : "flash-down") : ""}`}>
                  {formatQuote(q.price)}
                </span>
                <Change pct={q.changePct} className="w-16 justify-end text-xs" />
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[11px] text-muted">Kaynak: Binance herkese açık piyasa verisi. Bilgi amaçlıdır.</p>
    </section>
  );
}

/** Konunun coini: canlı fiyat ve 24 saatlik değişim (Binance'te işlem görüyorsa). */
export function CoinPriceCard({ symbol }: { symbol: string }) {
  const { quotes, flash } = useLive();
  const q = quotes.find((x) => x.base === symbol);
  const f = flash[symbol];
  return (
    <section aria-label={`${symbol} fiyatı`} className="neon-card overflow-hidden rounded-2xl p-5" data-testid="coin-card">
      <div className="flex items-center gap-3">
        <CoinToken symbol={symbol} size="md" />
        <div>
          <p className="text-lg font-bold text-fg">${symbol}</p>
          <p className="text-xs text-muted">{symbol}/USDT</p>
        </div>
        {q ? (
          q.changePct >= 0 ? (
            <TrendingUp aria-hidden="true" className="ml-auto h-6 w-6 text-up" />
          ) : (
            <TrendingDown aria-hidden="true" className="ml-auto h-6 w-6 text-down" />
          )
        ) : null}
      </div>
      {q ? (
        <div className="mt-4 flex items-end justify-between gap-2">
          <p key={f?.n ?? 0} className={`tabular rounded px-1 text-2xl font-bold text-fg ${f ? (f.dir === "up" ? "flash-up" : "flash-down") : ""}`}>
            {formatQuote(q.price)}
          </p>
          <Change pct={q.changePct} className="text-sm" />
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted">Bu coin için Binance fiyatı şu anda yok.</p>
      )}
      <a
        href={`https://www.binance.com/en/trade/${symbol}_USDT`}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-accent-text underline-offset-4 hover:underline"
      >
        Grafiği Binance&apos;te aç <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
      </a>
    </section>
  );
}

/** Trend coinin yanındaki küçük fiyat (varsa). */
export function InlineQuote({ symbol }: { symbol: string }) {
  const { quotes } = useLive();
  const q = quotes.find((x) => x.base === symbol);
  if (!q) return null;
  return (
    <span className="flex items-center gap-2 text-xs">
      <span className="tabular text-fg">{formatQuote(q.price)}</span>
      <Change pct={q.changePct} />
    </span>
  );
}
