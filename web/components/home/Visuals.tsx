// Ana sayfa görselleri: örnek arayüz parçaları. Tümü süs amaçlıdır (ekran okuyucudan gizli),
// betik içermez ve gerçek piyasa verisi/işlem sonucu göstermez; açıklama metinleri bunu belirtir.
// Satır içi stil kullanılmaz (CSP): boyutlar SVG öznitelikleri ve sınıflarla verilir.

import { BellRing, CheckCircle2, Fingerprint, Gauge, LayoutDashboard, LineChart, Radar, ShieldCheck, Sparkles, Wallet } from "lucide-react";

// --- Belirlenimli örnek fiyat serisi (her derlemede aynı) ------------------------------------

function series(count: number, seed: number, drift = 0.18) {
  let state = seed;
  const random = () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
  const out: { o: number; h: number; l: number; c: number; v: number }[] = [];
  let price = 100;
  for (let i = 0; i < count; i++) {
    const open = price;
    const close = open + (random() - 0.5 + drift / 2) * 3.4;
    const high = Math.max(open, close) + random() * 1.6;
    const low = Math.min(open, close) - random() * 1.6;
    out.push({ o: open, h: high, l: low, c: close, v: 0.3 + random() * 0.7 });
    price = close;
  }
  return out;
}

const CANDLES = series(46, 11);

function ema(values: number[], period: number) {
  const k = 2 / (period + 1);
  const out: number[] = [];
  values.forEach((v, i) => out.push(i === 0 ? v : v * k + out[i - 1]! * (1 - k)));
  return out;
}

function CandleChart({ gradientId = "hero-ema" }: { gradientId?: string }) {
  const width = 560;
  const height = 220;
  const pad = 8;
  const lows = Math.min(...CANDLES.map((c) => c.l));
  const highs = Math.max(...CANDLES.map((c) => c.h));
  const y = (v: number) => pad + ((highs - v) / (highs - lows)) * (height - 70);
  const step = (width - pad * 2) / CANDLES.length;
  const body = Math.max(3, step * 0.58);
  const line = ema(
    CANDLES.map((c) => c.c),
    9,
  )
    .map((v, i) => `${i === 0 ? "M" : "L"}${(pad + i * step + step / 2).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const support = y(lows + (highs - lows) * 0.22);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" preserveAspectRatio="none" focusable="false">
      <defs>
        <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="var(--accent-text)" />
          <stop offset="1" stopColor="var(--accent-2)" />
        </linearGradient>
      </defs>
      {[0.2, 0.45, 0.7].map((f) => (
        <line key={f} x1="0" x2={width} y1={height * f} y2={height * f} stroke="var(--grid-line)" />
      ))}
      <line x1="0" x2={width} y1={support} y2={support} stroke="var(--accent-3)" strokeDasharray="5 6" strokeOpacity="0.7" />
      {CANDLES.map((c, i) => {
        const x = pad + i * step + step / 2;
        const up = c.c >= c.o;
        const color = up ? "var(--up)" : "var(--down)";
        const top = y(Math.max(c.o, c.c));
        const bottom = y(Math.min(c.o, c.c));
        return (
          <g key={i}>
            <rect x={x - body / 2} y={height - 8 - c.v * 34} width={body} height={c.v * 34} fill="var(--accent-text)" opacity="0.14" rx="1" />
            <line x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} stroke={color} strokeWidth="1.2" />
            <rect x={x - body / 2} y={top} width={body} height={Math.max(1.5, bottom - top)} fill={color} rx="1.2" />
          </g>
        );
      })}
      <path d={line} fill="none" stroke={`url(#${gradientId})`} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" className="draw-line" />
      <circle cx={pad + 31 * step + step / 2} cy={y(CANDLES[31]!.l) + 10} r="5" fill="var(--accent-2)" className="pulse-dot text-accent-2" />
    </svg>
  );
}

const SCAN = [
  { s: "SOLUSDT", tag: "Trend", score: 82 },
  { s: "ETHUSDT", tag: "Hacim artışı", score: 74 },
  { s: "AVAXUSDT", tag: "Sıkışma", score: 66 },
  { s: "LINKUSDT", tag: "Balina alımı", score: 58 },
];

const W = ["w-[82%]", "w-[74%]", "w-[66%]", "w-[58%]"];

/** Kahraman bölümündeki büyük örnek uygulama penceresi + çevresindeki yüzen kartlar. */
export function HeroVisual() {
  return (
    <figure className="relative">
      <div aria-hidden="true" className="preview-halo absolute -inset-16 rounded-[4rem]" />
      <div aria-hidden="true" className="relative">
        <div className="ring-gradient glass overflow-hidden rounded-[28px] shadow-lift">
          <div className="flex items-center gap-2 border-b border-glass-border px-4 py-3">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
            <span className="ml-3 text-xs font-medium text-muted">AI Trading Intelligence — Genel bakış</span>
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-info-border bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info-fg">
              <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-current" />
              Sanal işlem
            </span>
          </div>
          <div className="grid grid-cols-[3.25rem_1fr]">
            <div className="flex flex-col items-center gap-3 border-r border-glass-border py-4 text-muted">
              {[LayoutDashboard, LineChart, Radar, Gauge, Wallet].map((Icon, i) => (
                <span key={i} className={`inline-flex h-8 w-8 items-center justify-center rounded-xl ${i === 0 ? "bg-surface-3 text-accent-text" : ""}`}>
                  <Icon className="h-4 w-4" />
                </span>
              ))}
            </div>
            <div className="min-w-0 p-4">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Örnek grafik</p>
                  <p className="text-lg font-semibold tracking-tight text-fg">
                    BTCUSDT <span className="text-sm font-medium text-muted">· 1 saat</span>
                  </p>
                </div>
                <div className="flex gap-1.5 text-[11px]">
                  {["EMA 9", "Destek", "Balina"].map((chip) => (
                    <span key={chip} className="rounded-full border border-border bg-surface-2 px-2 py-0.5 font-medium text-fg">
                      {chip}
                    </span>
                  ))}
                </div>
              </div>
              <div className="mt-2 rounded-2xl border border-glass-border bg-bg/50 p-2">
                <CandleChart />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-[1.15fr_1fr]">
                <div className="rounded-2xl border border-glass-border bg-bg/50 p-3">
                  <p className="flex items-center gap-1.5 text-[11px] font-semibold text-fg">
                    <Sparkles className="h-3.5 w-3.5 text-accent-2" /> Fırsat tarayıcı
                  </p>
                  <ul className="mt-2 space-y-2">
                    {SCAN.map((row, i) => (
                      <li key={row.s} className="text-[11px]">
                        <div className="flex justify-between">
                          <span className="font-semibold text-fg">{row.s}</span>
                          <span className="text-muted">
                            {row.tag} · <span className="tabular font-semibold text-fg">{row.score}</span>
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
                          <div className={`h-full rounded-full bg-gradient-to-r from-[#2f5bea] to-[#8b5cf6] ${W[i]}`} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="flex flex-col gap-3">
                  <div className="rounded-2xl border border-glass-border bg-bg/50 p-3">
                    <p className="text-[11px] font-semibold text-fg">Günlük zarar sınırı</p>
                    <div className="mt-2 flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                        <div className="h-full w-[22%] rounded-full bg-up" />
                      </div>
                      <span className="tabular text-[11px] text-muted">%22</span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 rounded-2xl border border-glass-border bg-bg/50 p-3">
                    <span className="flex items-center gap-1.5 text-[11px] font-semibold text-fg">
                      <ShieldCheck className="h-3.5 w-3.5 text-up" /> Risk kapısı
                    </span>
                    <span className="rounded-full bg-danger-bg px-2.5 py-1 text-[11px] font-semibold text-danger-fg">Acil durdurma</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="float-slow absolute -left-14 top-[34%] hidden w-56 rounded-2xl border border-border bg-surface/95 p-3.5 shadow-lift backdrop-blur-xl xl:block">
          <p className="flex items-center gap-2 text-xs font-semibold text-fg">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-info-bg text-info-fg">
              <BellRing className="h-3.5 w-3.5" />
            </span>
            Balina uyarısı
          </p>
          <p className="mt-2 text-[11px] leading-relaxed text-muted">ETHUSDT · aynı yönde büyük alış kümesi ve emir defteri duvarı</p>
        </div>
        <div className="float-slower absolute -right-8 -top-12 hidden w-60 rounded-2xl border border-border bg-surface/95 p-3.5 shadow-lift backdrop-blur-xl xl:block">
          <p className="flex items-center gap-2 text-xs font-semibold text-fg">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-success-bg text-success-fg">
              <Fingerprint className="h-3.5 w-3.5" />
            </span>
            iPhone · Face ID
          </p>
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-muted">
            <CheckCircle2 className="h-3.5 w-3.5 text-up" /> Komut imzalandı ve doğrulandı
          </p>
        </div>
      </div>
      <figcaption className="relative mt-6 text-center text-xs text-muted">
        Örnek arayüz görünümüdür; gerçek piyasa verisi veya işlem sonucu içermez.
      </figcaption>
    </figure>
  );
}

// --- Özellik kartı görselleri ---------------------------------------------------------------

function spark(seed: number, up: boolean) {
  const data = series(18, seed, up ? 0.5 : -0.4).map((c) => c.c);
  const min = Math.min(...data);
  const max = Math.max(...data);
  return data.map((v, i) => `${i === 0 ? "M" : "L"}${(i * 100) / (data.length - 1)} ${(28 - ((v - min) / (max - min || 1)) * 24).toFixed(1)}`).join(" ");
}

const SCANNER_ROWS = [
  { s: "SOLUSDT", m: "Spot", tag: "Trend", score: 82, seed: 3, up: true },
  { s: "ETHUSDT", m: "Vadeli", tag: "Hacim artışı", score: 74, seed: 8, up: true },
  { s: "AVAXUSDT", m: "Spot", tag: "Sıkışma", score: 66, seed: 21, up: true },
  { s: "DOGEUSDT", m: "Vadeli", tag: "Aşırı funding", score: 41, seed: 5, up: false },
];
const SCORE_W = ["w-[82%]", "w-[74%]", "w-[66%]", "w-[41%]"];

export function ScannerViz() {
  return (
    <div aria-hidden="true" className="overflow-hidden rounded-2xl border border-border bg-bg/60">
      <div className="grid grid-cols-[1.2fr_1fr_1.2fr] gap-3 border-b border-border px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-muted">
        <span>Parite</span>
        <span>Hareket</span>
        <span>Fırsat puanı</span>
      </div>
      <ul>
        {SCANNER_ROWS.map((r, i) => (
          <li key={r.s} className="grid grid-cols-[1.2fr_1fr_1.2fr] items-center gap-3 border-b border-border px-4 py-2.5 last:border-0">
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-fg">{r.s}</span>
              <span className="text-[11px] text-muted">
                {r.m} · {r.tag}
              </span>
            </span>
            <svg viewBox="0 0 100 30" className="h-7 w-full" preserveAspectRatio="none" focusable="false">
              <path d={spark(r.seed, r.up)} fill="none" stroke={r.up ? "var(--up)" : "var(--down)"} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            </svg>
            <span className="flex items-center gap-2">
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                <span className={`block h-full rounded-full bg-gradient-to-r from-[#2f5bea] to-[#8b5cf6] ${SCORE_W[i]}`} />
              </span>
              <span className="tabular w-6 text-right text-xs font-semibold text-fg">{r.score}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RadarViz() {
  return (
    <div aria-hidden="true" className="relative mx-auto aspect-square w-full max-w-[15rem]">
      <div className="absolute inset-0 rounded-full border border-border bg-bg/60" />
      <div className="absolute inset-[16%] rounded-full border border-border" />
      <div className="absolute inset-[33%] rounded-full border border-border" />
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div className="absolute left-0 top-1/2 h-px w-full bg-border" />
      <div className="radar-sweep absolute inset-0 rounded-full opacity-60" />
      {[
        "left-[24%] top-[30%] bg-up text-up",
        "left-[64%] top-[22%] bg-accent-2 text-accent-2",
        "left-[70%] top-[62%] bg-down text-down",
        "left-[36%] top-[70%] bg-accent-3 text-accent-3",
      ].map((cls) => (
        <span key={cls} className={`pulse-dot absolute h-2.5 w-2.5 rounded-full ${cls}`} />
      ))}
    </div>
  );
}

export function ScoreRing({ score = 82 }: { score?: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div aria-hidden="true" className="flex items-center gap-5">
      <svg viewBox="0 0 128 128" className="h-32 w-32 shrink-0 -rotate-90" focusable="false">
        <defs>
          <linearGradient id="puan-halka" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#2f5bea" />
            <stop offset="0.6" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
        <circle cx="64" cy="64" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="12" />
        <circle cx="64" cy="64" r={r} fill="none" stroke="url(#puan-halka)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${(c * score) / 100} ${c}`} />
        <text x="64" y="74" textAnchor="middle" className="fill-fg text-[30px] font-semibold" transform="rotate(90 64 64)">
          {score}
        </text>
      </svg>
      <ul className="space-y-2 text-xs">
        {[
          ["Trend", "yukarı (EMA)"],
          ["Hacim", "ortalamanın üstünde"],
          ["Balina", "alış ağırlıklı"],
          ["Funding", "nötr"],
        ].map(([k, v]) => (
          <li key={k} className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-up" />
            <span className="font-semibold text-fg">{k}</span>
            <span className="text-muted">{v}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EquityViz({ gradientId = "bt-alan", title = "Örnek backtest eğrisi" }: { gradientId?: string; title?: string }) {
  const data = ema(
    series(60, 29, 0.32).map((c) => c.c),
    5,
  );
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pts = data.map((v, i) => [(i * 300) / (data.length - 1), 92 - ((v - min) / (max - min)) * 80] as const);
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return (
    <div aria-hidden="true" className="rounded-2xl border border-border bg-bg/60 p-3">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-semibold text-fg">{title}</span>
        <span className="rounded-full bg-surface-3 px-2 py-0.5 text-muted">komisyon + kayma dâhil</span>
      </div>
      <svg viewBox="0 0 300 100" className="mt-2 h-24 w-full" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--accent-text)" stopOpacity="0.32" />
            <stop offset="1" stopColor="var(--accent-text)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${line} L300 100 L0 100 Z`} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke="var(--accent-text)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

export function RiskViz() {
  const rows = [
    { k: "İşlem başına risk", v: "%0,5", w: "w-[25%]" },
    { k: "Günlük zarar sınırı", v: "%2 · kullanılan %22", w: "w-[22%]" },
    { k: "Açık pozisyon", v: "2 / 3", w: "w-[66%]" },
  ];
  return (
    <div aria-hidden="true" className="space-y-3">
      {rows.map((r) => (
        <div key={r.k}>
          <div className="flex justify-between text-xs">
            <span className="font-medium text-fg">{r.k}</span>
            <span className="tabular text-muted">{r.v}</span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-3">
            <div className={`h-full rounded-full bg-gradient-to-r from-[#0f9d58] to-[#22d3ee] ${r.w}`} />
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between rounded-2xl border border-danger-border bg-danger-bg px-3 py-2.5">
        <span className="text-xs font-semibold text-danger-fg">Acil durdurma · tek tuş</span>
        <span className="h-3 w-3 rounded-full bg-down" />
      </div>
    </div>
  );
}

export function PhoneViz() {
  return (
    <div aria-hidden="true" className="mx-auto w-56 rounded-[2.6rem] border border-border-strong/40 bg-bg p-2.5 shadow-lift">
      <div className="relative overflow-hidden rounded-[2.1rem] border border-border bg-surface px-4 pb-5 pt-7">
        <div className="absolute left-1/2 top-2 h-5 w-20 -translate-x-1/2 rounded-full bg-bg" />
        <p className="text-[11px] text-muted">Ofis bilgisayarı</p>
        <p className="flex items-center gap-1.5 text-sm font-semibold text-fg">
          <span className="pulse-dot h-2 w-2 rounded-full bg-up text-up" /> Motor çalışıyor
        </p>
        <div className="mt-4 space-y-2 text-[11px]">
          {[
            ["Açık pozisyon", "2"],
            ["Günlük sınır", "%22"],
            ["Balina uyarısı", "ETHUSDT"],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between rounded-xl bg-bg px-3 py-2">
              <span className="text-muted">{k}</span>
              <span className="font-semibold text-fg">{v}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-2xl bg-[#c42b2b] py-3 text-center text-xs font-bold text-white">Acil durdurma</div>
        <p className="mt-2 flex items-center justify-center gap-1 text-[10px] text-muted">
          <Fingerprint className="h-3 w-3" /> Pozisyon kapatma: Face ID
        </p>
      </div>
    </div>
  );
}

/** Platformlar bölümü: Windows uygulamasının küçük örnek görünümü. */
export function DesktopViz() {
  return (
    <div aria-hidden="true" className="overflow-hidden rounded-2xl border border-border bg-bg/70 shadow-sm">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-[#ff5f57]" />
        <span className="h-2 w-2 rounded-full bg-[#febc2e]" />
        <span className="h-2 w-2 rounded-full bg-[#28c840]" />
        <span className="ml-2 text-[10px] font-medium text-muted">Genel bakış</span>
      </div>
      <div className="grid grid-cols-[6.5rem_1fr] gap-3 p-3 text-[11px]">
        <ul className="space-y-1">
          {["Genel bakış", "Piyasa", "Fırsatlar", "Balina radarı", "Backtest", "Risk"].map((item, i) => (
            <li key={item} className={`rounded-lg px-2 py-1.5 ${i === 0 ? "bg-surface-3 font-semibold text-fg" : "text-muted"}`}>
              {item}
            </li>
          ))}
        </ul>
        <div className="min-w-0 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            {[
              ["Motor", "Çalışıyor"],
              ["Mod", "Sanal işlem"],
              ["Risk kapısı", "Etkin"],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl border border-border bg-surface px-2.5 py-2">
                <p className="text-[10px] text-muted">{k}</p>
                <p className="font-semibold text-fg">{v}</p>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-border bg-surface p-2">
            <CandleChart gradientId="masaustu-ema" />
          </div>
        </div>
      </div>
    </div>
  );
}
