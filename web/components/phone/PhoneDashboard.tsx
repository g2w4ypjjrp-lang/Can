"use client";

// Telefon izleme paneli (görünüm). Bağlantı/şifreleme PhoneApp'te; burada yalnızca gösterim var.

import {
  Activity,
  AlertOctagon,
  Bell,
  BellOff,
  BellRing,
  Bot,
  CheckCircle2,
  Clock,
  Cpu,
  Gauge,
  Layers,
  PauseCircle,
  Radio,
  RefreshCw,
  ShieldAlert,
  Share,
  Sparkles,
  SquarePlus,
  Trophy,
  Unplug,
  Waves,
  Wallet,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { LogoMark } from "@/components/Logo";
import type { PushSupport } from "@/lib/push";
import type { EngineEvent, Phase } from "@/lib/remoteClient";

export type Snap = {
  engine?: { state: string; reason?: string; trading_mode: string; kill_switch: boolean; kill_reason?: string; uptime_s?: number; version?: string };
  risk?: {
    daily_loss_pct: number;
    halted: boolean;
    halt_reason?: string | null;
    equity: string;
    wallets?: { market: string; asset: string; balance: string; available: string; unrealized_pnl: string }[];
  } | null;
  positions?: {
    market: string;
    symbol: string;
    quantity: string;
    entry_price: string;
    realized_pnl: string;
    protected: boolean;
    mark_price?: string | null;
    unrealized_pnl?: string | null;
    pnl_pct?: number | null;
  }[];
  autotrade?: {
    enabled: boolean;
    opened: number;
    rejected: number;
    signals?: number;
    interval?: string;
    min_score?: number;
    next_decision_ms?: number;
    candidates?: { market: string; symbol: string; direction: string; score: number }[];
    recent?: { ts_ms: number; symbol: string; direction: string; score: number; result?: string }[];
  };
  opportunities?: { market: string; symbol: string; direction: string; score: number; reward_risk: number | null }[];
  whales?: { ts_ms: number; symbol: string; message: string }[];
  history?: {
    summary: { count: number; wins: number; win_rate: number | null; net_total: string; today_net: string };
    trades: { symbol: string; market: string; side: string; net_pnl: string; pnl_pct: number | null; closed_at: number; source: string }[];
  };
  license?: { valid: boolean; plan_name?: string | null };
  // Telefon bildirimleri: motorun gönderen anahtarı ve bu cihazın abonelik durumu.
  push?: { vapid_key: string; subscribed: boolean };
};

/** Telefon bildirimlerinin (kilit ekranı) durumu. */
export interface PushView {
  support: PushSupport | "loading";
  /** Bilgisayardaki uygulama bildirim gönderebiliyor mu (0.14.7+). */
  engineReady: boolean;
  on: boolean;
  busy: boolean;
}

/** Bakiye: cüzdanlar (bakiye + açık kâr/zarar) varsa onların toplamı, yoksa özsermaye. Futures
 * cüzdanının açık kâr/zararı anlık fiyattan biliniyorsa o kullanılır. */
export function totalBalance(snap: Snap | null, liveFuturesPnl: number | null = null): number | null {
  const wallets = snap?.risk?.wallets;
  if (wallets && wallets.length > 0)
    return wallets.reduce(
      (sum, w) => sum + Number(w.balance) + (w.market === "usdm_futures" && liveFuturesPnl !== null ? liveFuturesPnl : Number(w.unrealized_pnl)),
      0,
    );
  const equity = Number(snap?.risk?.equity);
  return snap?.risk && Number.isFinite(equity) ? equity : null;
}

const STATE: Record<string, [string, string]> = {
  running: ["Çalışıyor", "bg-up"],
  safe_mode: ["Güvenli mod", "bg-warn-fg"],
  starting: ["Başlıyor", "bg-warn-fg"],
  halted: ["Durduruldu", "bg-down"],
  stopped: ["Kapalı", "bg-muted"],
};
const MODE: Record<string, string> = { paper: "Sanal", testnet: "Demo para", live: "GERÇEK PARA" };
const MARKET: Record<string, string> = { spot: "Spot", usdm_futures: "Futures", "Market.SPOT": "Spot", "Market.USDM_FUTURES": "Futures" };
const EVERY: Record<string, string> = {
  "1m": "her dakika",
  "3m": "3 dakikada bir",
  "5m": "5 dakikada bir",
  "15m": "15 dakikada bir",
  "1h": "saat başı",
};
const INTERVAL_MS: Record<string, number> = { "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000 };
const PHASE_TEXT: Record<Phase, string> = {
  connecting: "Bilgisayara bağlanılıyor…",
  pairing: "Eşleştiriliyor…",
  online: "Bağlı",
  engine_offline: "Bilgisayar çevrim dışı",
  offline: "Bağlantı yok",
  rejected: "Reddedildi",
};
const SECTIONS = [
  ["ozet", "Özet"],
  ["bot", "Bot"],
  ["pozisyonlar", "Pozisyonlar"],
  ["gecmis", "Geçmiş"],
  ["firsatlar", "Fırsatlar"],
  ["bildirimler", "Bildirimler"],
] as const;
const AVATAR = [
  ["#0e7490", "#6d28d9"],
  ["#be185d", "#7c3aed"],
  ["#047857", "#0e7490"],
  ["#b45309", "#be185d"],
  ["#1d4ed8", "#7c3aed"],
  ["#4338ca", "#0e7490"],
];

// Motorun teknik durum gerekçesini (hazırlık koşulu adları) anlaşılır Türkçeye çevirir.
const REASONS: [RegExp, string][] = [
  [/(live\.)?exchange\.usdm_futures\.reconciled/g, "Binance Futures kayıtları uyuşmuyor (masaüstünde ayrıntı ve “Binance'e eşitle”)"],
  [/(live\.)?exchange\.spot\.reconciled/g, "Binance Spot kayıtları uyuşmuyor (masaüstünde ayrıntı)"],
  [/(live\.)?exchange\.(usdm_futures|spot)\.stream/g, "Binance hesap akışı kopuk"],
  [/(live\.)?risk\.daily_loss/g, "günlük zarar sınırı"],
  [/market_data\.(usdm_futures|spot)/g, "piyasa verisi bekleniyor"],
  [/license\.valid/g, "lisans"],
  [/hazır olmayan koşullar: /, "Yeni işlem açılmıyor: "],
];
function explainReason(reason: string): string {
  return REASONS.reduce((text, [pattern, label]) => text.replace(pattern, label), reason);
}

const clock = (ms?: number | null) =>
  ms ? new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
const money = (v?: string | number | null, digits = 2) => {
  const n = Number(v);
  return v === null || v === undefined || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};
const price = (v?: string | number | null) => {
  const n = Number(v);
  return v === null || v === undefined || !Number.isFinite(n) ? "—" : n.toLocaleString("tr-TR", { maximumFractionDigits: 6 });
};
const signed = (n: number) => `${n > 0 ? "+" : ""}${money(n)}`;
const toneOf = (n: number | null) => (n === null ? "text-fg" : n > 0 ? "text-up" : n < 0 ? "text-down" : "text-fg");
const side = (direction: string) => (direction === "long" ? "Long" : "Short");

// --- Küçük parçalar -------------------------------------------------------------------------------

function Card({ id, title, icon, action, children, testId }: { id?: string; title: string; icon: ReactNode; action?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section id={id} className="ph-card ph-rise scroll-mt-32 p-4" data-testid={testId} aria-labelledby={id ? `${id}-baslik` : undefined}>
      <header className="mb-3 flex items-center gap-2.5">
        <span className="ph-icon" aria-hidden="true">
          {icon}
        </span>
        <h2 id={id ? `${id}-baslik` : undefined} className="flex-1 text-[15px] font-semibold tracking-tight text-fg">
          {title}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function Empty({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <p className="flex flex-col items-center gap-1.5 rounded-2xl border border-dashed border-glass-border px-3 py-5 text-center text-sm text-muted">
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      {children}
    </p>
  );
}

function Skeleton({ className }: { className: string }) {
  return <span className={`ph-skel block rounded-xl ${className}`} aria-hidden="true" />;
}

/** Coin rozeti: varlığın ilk harfleri, sembole göre sabit renk. */
function CoinAvatar({ symbol }: { symbol: string }) {
  const base = symbol.replace(/(USDT|USDC|FDUSD|BUSD|TRY)$/, "") || symbol;
  let hash = 0;
  for (const ch of base) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const [from, to] = AVATAR[hash % AVATAR.length]!;
  return (
    <span
      className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl text-[11px] font-extrabold tracking-tight text-white shadow-md ring-1 ring-white/15"
      style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
      aria-hidden="true"
    >
      {base.slice(0, 4)}
    </span>
  );
}

function SidePill({ long }: { long: boolean }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${long ? "bg-success-bg text-success-fg" : "bg-danger-bg text-danger-fg"}`}>
      {long ? "Long" : "Short"}
    </span>
  );
}

/** Anlık kâr/zarar: yön oku, renk ve değişimde kısa parlama. */
function PnlText({ value, pct, size = "text-sm" }: { value?: string | number | null; pct?: number | null; size?: string }) {
  const n = value === null || value === undefined || value === "" ? null : Number(value);
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = n;
    if (n === null || before === null || n === before) return;
    setFlash(n > before ? "bg-success-bg" : "bg-danger-bg");
    const id = setTimeout(() => setFlash(""), 900);
    return () => clearTimeout(id);
  }, [n]);
  if (n === null || Number.isNaN(n)) return <span className="text-sm text-muted">—</span>;
  return (
    <span className={`inline-block rounded-lg px-1.5 font-bold tabular-nums transition-colors duration-500 ${size} ${toneOf(n)} ${flash}`} data-testid="phone-pnl">
      <span aria-hidden="true">{n > 0 ? "▲ " : n < 0 ? "▼ " : ""}</span>
      {signed(n)} USDT
      {pct !== null && pct !== undefined ? <span className="block text-[11px] font-semibold opacity-90">{`${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}</span> : null}
    </span>
  );
}

/** Anlık fiyat (Binance işlem akışı): değişimde kısa yeşil/kırmızı. */
function LiveTick({ value }: { value?: number }) {
  const prev = useRef<number | undefined>(undefined);
  const [flash, setFlash] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (value === undefined || before === undefined || value === before) return;
    setFlash(value > before ? "text-up" : "text-down");
    const id = setTimeout(() => setFlash(""), 700);
    return () => clearTimeout(id);
  }, [value]);
  if (value === undefined) return null;
  return <span className={`block text-[11px] font-semibold tabular-nums transition-colors duration-500 ${flash || "text-fg"}`}>{price(value)}</span>;
}

function ScoreBar({ score, threshold }: { score: number; threshold: number }) {
  const pass = score >= threshold;
  return (
    <span className="relative block h-2 flex-1 overflow-visible rounded-full bg-surface-3" aria-hidden="true">
      <span className={`ph-bar absolute inset-y-0 left-0 rounded-full ${pass ? "pass" : ""}`} style={{ width: `${Math.max(4, Math.min(100, score))}%` }} />
      <span className="absolute -inset-y-1 w-0.5 rounded bg-warn-fg" style={{ left: `${threshold}%` }} />
    </span>
  );
}

/** Halka gösterge (geri sayım, başarı oranı). */
function Ring({ value, size = 64, tone = "accent", children }: { value: number; size?: number; tone?: "accent" | "up"; children: ReactNode }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <span className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="32" cy="32" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          stroke={tone === "up" ? "var(--up)" : "url(#ph-ring)"}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${c * v} ${c}`}
          className="transition-[stroke-dasharray] duration-700"
        />
        <defs>
          <linearGradient id="ph-ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3be8ff" />
            <stop offset="1" stopColor="#c27bff" />
          </linearGradient>
        </defs>
      </svg>
      <span className="relative text-center text-xs font-bold leading-tight text-fg">{children}</span>
    </span>
  );
}

/** Bu oturumda alınan bakiye değerlerinden küçük çizgi grafik. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 300;
  const h = 56;
  const points = values.map((v, i) => [(i / (values.length - 1)) * w, h - 6 - ((v - min) / span) * (h - 12)] as const);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const up = values[values.length - 1]! >= values[0]!;
  const color = up ? "#3dffa8" : "#ff5c8a";
  return (
    <div className="mt-4">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-14 w-full" aria-hidden="true">
        <defs>
          <linearGradient id="ph-spark" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.35" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#ph-spark)" />
        <path d={line} fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-1 flex justify-between text-[11px] text-muted">
        <span>Bu oturum</span>
        <span className={up ? "text-up" : "text-down"}>
          {signed(values[values.length - 1]! - values[0]!)} USDT
        </span>
      </p>
    </div>
  );
}

function Tile({ icon, label, children, testId }: { icon: ReactNode; label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="ph-tile">
      <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
        <span aria-hidden="true" className="text-accent-text">
          {icon}
        </span>
        {label}
      </span>
      <span className="mt-1 block truncate text-[15px] font-bold text-fg" data-testid={testId}>
        {children}
      </span>
    </div>
  );
}

/** Kaydırınca hangi bölümde olunduğu (üstteki sekme çubuğu için). */
function useActiveSection(): string {
  const [active, setActive] = useState<string>(SECTIONS[0][0]);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-120px 0px -55% 0px" },
    );
    for (const [id] of SECTIONS) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
  return active;
}

// --- Panel ----------------------------------------------------------------------------------------

export interface DashboardProps {
  snap: Snap | null;
  snapAt: number | null;
  events: EngineEvent[];
  phase: Phase;
  detail: string | null;
  series: number[];
  now: number;
  busy: boolean;
  toast: { ok: boolean; text: string } | null;
  onRefresh: () => void;
  onPause: () => void;
  onKill: () => void;
  onForget: () => void;
  push: PushView;
  /** Anlık fiyatlar: "<piyasa>:<SEMBOL>" → fiyat. */
  live?: Record<string, number>;
  onPushEnable: () => void;
  onPushDisable: () => void;
  onPushTest: () => void;
}

/** Kilit ekranına bildirim: açma/kapama, deneme; iPhone'da ana ekrana ekleme adımları. */
function PushCard({ push, online, onEnable, onDisable, onTest }: { push: PushView; online: boolean; onEnable: () => void; onDisable: () => void; onTest: () => void }) {
  const body = (() => {
    if (push.support === "loading") return <Skeleton className="h-10 w-full" />;
    if (push.support === "ios_home_screen")
      return (
        <div className="space-y-2.5 text-sm text-fg" data-testid="phone-push-ios">
          <p className="text-muted">iPhone'da kilit ekranına bildirim için bu sayfayı ana ekrana ekleyin (iOS 16.4 ve üstü; uygulama indirmeden):</p>
          <ol className="space-y-2">
            {[
              [<Share key="i" size={15} />, "Safari'nin alt çubuğundaki Paylaş düğmesine dokunun."],
              [<SquarePlus key="i" size={15} />, "\"Ana Ekrana Ekle\" → \"Ekle\"."],
              [<LogoMark key="i" className="h-4 w-4" />, "Ana ekrandaki \"AI Trading\" simgesinden açın; bilgisayardaki QR'ı uygulamanın içinden okutun."],
              [<Bell key="i" size={15} />, "\"Bildirimleri aç\" düğmesine basıp izin verin."],
            ].map(([icon, text], i) => (
              <li key={i} className="flex items-start gap-2.5 rounded-2xl bg-surface-2 px-3 py-2">
                <span className="mt-0.5 shrink-0 text-accent-text" aria-hidden="true">
                  {icon}
                </span>
                <span>{text}</span>
              </li>
            ))}
          </ol>
        </div>
      );
    if (push.support === "unsupported")
      return <p className="text-sm text-muted">Bu tarayıcı bildirimleri desteklemiyor. iPhone'da Safari (ana ekrana ekleyerek), Android'de Chrome kullanın.</p>;
    if (push.support === "denied")
      return <p className="text-sm text-warn-fg">Bildirim izni kapalı. Telefon Ayarları → Bildirimler bölümünden bu uygulamaya izin verip sayfayı yeniden açın.</p>;
    if (!push.engineReady)
      return <p className="text-sm text-muted">Bilgisayardaki uygulamayı güncelleyin (0.14.7 ve üstü); bildirimleri o gönderir.</p>;
    if (push.on)
      return (
        <div className="space-y-3">
          <p className="text-sm text-muted">
            İşlem açılış/kapanışları (stop, hedef, kâr/zarar ayrıntısıyla), acil durdurma ve önemli uyarılar telefon kilitliyken de gelir.
            Bilgisayardaki uygulama açık olmalıdır.
          </p>
          <div className="flex gap-2">
            <button type="button" className="flex flex-1 items-center justify-center gap-2 rounded-2xl border border-glass-border bg-white/5 py-3 text-sm font-semibold text-fg disabled:opacity-50" onClick={onTest} disabled={push.busy || !online} data-testid="phone-push-test">
              <BellRing size={16} aria-hidden="true" /> Deneme bildirimi
            </button>
            <button type="button" className="flex items-center justify-center gap-2 rounded-2xl border border-glass-border px-4 py-3 text-sm font-semibold text-muted disabled:opacity-50" onClick={onDisable} disabled={push.busy || !online} data-testid="phone-push-disable">
              <BellOff size={16} aria-hidden="true" /> Kapat
            </button>
          </div>
        </div>
      );
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">Sayfa kapalıyken ve telefon kilitliyken de işlem açılış/kapanış bildirimleri alın.</p>
        <button type="button" className="ph-tab-cta flex w-full items-center justify-center gap-2 rounded-2xl py-3.5 text-sm font-bold disabled:opacity-50" onClick={onEnable} disabled={push.busy || !online} data-testid="phone-push-enable">
          <Bell size={17} aria-hidden="true" /> Bildirimleri aç
        </button>
      </div>
    );
  })();
  return (
    <Card
      id="bildirim-ayari"
      title="Telefon bildirimleri"
      icon={<Bell size={17} />}
      testId="phone-push"
      action={
        <span className={`ph-state ${push.on ? "on" : ""}`} data-testid="phone-push-state">
          {push.on ? "Açık" : "Kapalı"}
        </span>
      }
    >
      {body}
    </Card>
  );
}

type Position = NonNullable<Snap["positions"]>[number];

/** Anlık fiyat (Binance işlem akışı, motor 0,1 sn'de bir gönderir) ile fiyat ve kâr/zarar. */
export function withLivePrices(positions: Position[] | undefined, live: Record<string, number>): Position[] | undefined {
  return positions?.map((p) => {
    const price = live[`${p.market}:${p.symbol}`];
    const qty = Number(p.quantity);
    const entry = Number(p.entry_price);
    if (!price || !qty || !(entry > 0)) return p;
    return {
      ...p,
      mark_price: String(price),
      unrealized_pnl: String((price - entry) * qty),
      pnl_pct: (price / entry - 1) * 100 * (qty > 0 ? 1 : -1),
    };
  });
}

export function PhoneDashboard({ snap: raw, snapAt, events, phase, detail, series, now, busy, toast, onRefresh, onPause, onKill, onForget, push, onPushEnable, onPushDisable, onPushTest, live: livePrices = {} }: DashboardProps) {
  const snap = raw ? { ...raw, positions: withLivePrices(raw.positions, livePrices) } : raw;
  const futuresOpen = (snap?.positions ?? []).filter((p) => p.market === "usdm_futures" && p.unrealized_pnl != null);
  const liveFuturesPnl = futuresOpen.length ? futuresOpen.reduce((sum, p) => sum + Number(p.unrealized_pnl), 0) : null;
  const [confirmKill, setConfirmKill] = useState(false);
  const [spin, setSpin] = useState(false);
  const active = useActiveSection();
  const engine = snap?.engine;
  const auto = snap?.autotrade;
  const risk = snap?.risk;
  const threshold = auto?.min_score ?? 70;
  const live = engine?.trading_mode === "live";
  const online = phase === "online";
  const [stateText, stateDot] = STATE[engine?.state ?? ""] ?? ["Bekleniyor", "bg-muted"];
  const total = totalBalance(snap, liveFuturesPnl);
  const openPnl = snap?.positions?.some((p) => p.unrealized_pnl != null)
    ? snap.positions.reduce((sum, p) => sum + Number(p.unrealized_pnl ?? 0), 0)
    : null;
  const summary = snap?.history?.summary;
  const today = summary && summary.count > 0 ? Number(summary.today_net) : null;
  const intervalMs = INTERVAL_MS[auto?.interval ?? ""] ?? 0;
  const left = auto?.next_decision_ms ? Math.max(0, auto.next_decision_ms - now) : null;
  const minutes = left !== null ? Math.ceil(left / 60_000) : null;
  const stale = snapAt !== null && online && now - snapAt > 60_000;

  return (
    <main id="icerik" className="mx-auto max-w-md px-4 pb-36" data-testid="phone-app">
      {/* Üst çubuk: bağlantı durumu ve bölüm sekmeleri */}
      <header className="ph-header sticky top-0 z-10 -mx-4 px-4 pb-2 pt-3">
        <div className="flex items-center gap-3">
          <LogoMark className="h-10 w-10" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[15px] font-bold tracking-tight text-fg">
              AI Trading <span className="ph-gradient-text">Intelligence</span>
            </h1>
            <p className="flex items-center gap-1.5 text-xs text-muted" data-testid="phone-phase">
              <span className={`ph-dot ${online ? "bg-up" : phase === "rejected" ? "bg-down" : "bg-warn-fg"} ${online ? "ph-pulse" : ""}`} aria-hidden="true" />
              {PHASE_TEXT[phase]}
              {snapAt && online ? ` · ${clock(snapAt)}` : ""}
              {stale ? " · veri eski" : ""}
            </p>
          </div>
          <button
            type="button"
            aria-label="Yenile"
            className="ph-icon-button"
            onClick={() => {
              setSpin(true);
              setTimeout(() => setSpin(false), 900);
              onRefresh();
            }}
            disabled={!online}
          >
            <RefreshCw size={18} aria-hidden="true" className={spin ? "animate-spin" : ""} />
          </button>
        </div>
        <nav aria-label="Bölümler" className="ph-tabs -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} aria-current={active === id ? "true" : undefined} className="ph-tab">
              {label}
            </a>
          ))}
        </nav>
      </header>

      <div className="mt-3 space-y-4">
        {detail && !online && <p className="rounded-2xl border border-warn-border bg-warn-bg px-3 py-2 text-sm text-warn-fg">{detail}</p>}
        {phase === "engine_offline" && (
          <p className="flex items-center gap-2 rounded-2xl border border-warn-border bg-warn-bg px-3 py-2.5 text-sm text-warn-fg">
            <Unplug size={16} aria-hidden="true" className="shrink-0" /> Bilgisayar kapalı ya da uygulama çalışmıyor. Açıldığında otomatik bağlanır.
          </p>
        )}

        {/* Bakiye */}
        <section id="ozet" className={`ph-hero ph-rise scroll-mt-32 p-5 ${live ? "live" : ""}`} data-testid="phone-balance" aria-labelledby="ozet-baslik">
          <div className="flex items-center justify-between gap-3">
            <h2 id="ozet-baslik" className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#c9f8ff]">
              {risk?.wallets && risk.wallets.length > 0 ? "Binance bakiyesi" : "Özsermaye"}
            </h2>
            <span className={`ph-mode ${live ? "live" : ""}`} data-testid="phone-mode">
              {MODE[engine?.trading_mode ?? ""] ?? "—"}
            </span>
          </div>
          {total !== null ? (
            <p className="neon-value mt-2 text-[2.5rem] font-extrabold leading-none tracking-tight tabular-nums">
              {money(total)} <span className="text-lg font-bold">USDT</span>
            </p>
          ) : (
            <Skeleton className="mt-3 h-10 w-48" />
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {openPnl !== null && (
              <span className="ph-chip">
                <span className="text-muted">Açık</span>
                <PnlText value={openPnl} />
              </span>
            )}
            {today !== null && (
              <span className="ph-chip">
                <span className="text-muted">Bugün</span>
                <b className={`tabular-nums ${toneOf(today)}`}>{signed(today)}</b>
              </span>
            )}
          </div>
          <Sparkline values={series} />
          {risk?.wallets && risk.wallets.length > 0 && (
            <ul className="mt-4 grid grid-cols-2 gap-2">
              {risk.wallets.map((w) => (
                <li key={w.market} className="rounded-2xl border border-white/10 bg-black/15 px-3 py-2">
                  <span className="block text-[11px] text-muted">{MARKET[w.market] ?? w.market} cüzdanı</span>
                  <b className="block tabular-nums text-fg">
                    {money(w.balance)} {w.asset}
                  </b>
                  <span className="block text-[11px] text-muted">kullanılabilir {money(w.available)}</span>
                </li>
              ))}
            </ul>
          )}
          {risk?.halted && (
            <p className="mt-3 rounded-2xl border border-warn-border bg-warn-bg px-3 py-2 text-xs text-warn-fg">
              Bugün yeni işlem kilitli{risk.halt_reason ? `: ${risk.halt_reason}` : ""}. Kilidi masaüstünden kaldırabilirsiniz.
            </p>
          )}
        </section>

        {/* Durum */}
        <section className="ph-rise" data-testid="phone-status" aria-label="Durum">
          <div className="grid grid-cols-2 gap-2.5">
            <Tile icon={<Cpu size={13} />} label="Motor">
              <span className="flex items-center gap-2">
                <span className={`ph-dot ${stateDot}`} aria-hidden="true" />
                <span data-testid="phone-engine-state">{engine ? stateText : "Bekleniyor"}</span>
              </span>
            </Tile>
            <Tile icon={<Gauge size={13} />} label="Günlük zarar">
              <span className={risk && risk.daily_loss_pct > 0 ? "text-down" : ""}>{risk ? `%${money(risk.daily_loss_pct)}` : "—"}</span>
            </Tile>
            <Tile icon={<Layers size={13} />} label="Açık pozisyon">
              {snap?.positions?.length ?? 0}
            </Tile>
            <Tile icon={<Wallet size={13} />} label="Özsermaye">
              {risk ? `${money(risk.equity)}` : "—"}
            </Tile>
          </div>
          {engine?.state !== "running" && engine?.reason ? <p className="mt-2 px-1 text-xs text-muted" data-testid="phone-engine-reason">{explainReason(engine.reason)}</p> : null}
          {engine?.kill_switch && (
            <p className="mt-2.5 flex items-center gap-2 rounded-2xl border border-danger-border bg-danger-bg px-3 py-2.5 text-sm font-semibold text-danger-fg" data-testid="phone-kill-on">
              <AlertOctagon size={16} aria-hidden="true" className="shrink-0" /> Acil durdurma devrede{engine.kill_reason ? `: ${engine.kill_reason}` : ""}
            </p>
          )}
        </section>

        {/* Kilit ekranı bildirimleri (açıksa sayfanın sonunda, kapalıysa burada) */}
        {!push.on && <PushCard push={push} online={online} onEnable={onPushEnable} onDisable={onPushDisable} onTest={onPushTest} />}

        {/* Bot */}
        <Card
          id="bot"
          title="Bot"
          icon={<Bot size={17} />}
          testId="phone-bot"
          action={
            <span className={`ph-state ${auto?.enabled ? "on" : ""}`} data-testid="phone-bot-state">
              {auto?.enabled ? "Çalışıyor" : "Durdu"}
            </span>
          }
        >
          {auto ? (
            <>
              <div className="flex items-center gap-4">
                <Ring value={intervalMs && left !== null ? 1 - left / intervalMs : 0}>
                  {minutes !== null ? (
                    <>
                      {minutes > 0 ? minutes : "<1"}
                      <span className="block text-[10px] font-medium text-muted">dk</span>
                    </>
                  ) : (
                    "—"
                  )}
                </Ring>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
                    <Clock size={12} aria-hidden="true" /> Sonraki karar
                  </p>
                  <p className="text-xl font-bold tabular-nums text-fg">{clock(auto.next_decision_ms)}</p>
                  <p className="text-xs text-muted">
                    {EVERY[auto.interval ?? ""] ?? auto.interval ?? "—"} · eşik {threshold} puan
                  </p>
                </div>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                {(
                  [
                    ["Sinyal", auto.signals ?? 0, "text-fg"],
                    ["Açılan", auto.opened, "text-up"],
                    ["Risk reddi", auto.rejected, auto.rejected > 0 ? "text-warn-fg" : "text-fg"],
                  ] as const
                ).map(([label, value, tone]) => (
                  <div key={label} className="rounded-2xl bg-surface-2 px-2 py-2">
                    <dt className="text-[11px] text-muted">{label}</dt>
                    <dd className={`text-lg font-bold tabular-nums ${tone}`}>{value}</dd>
                  </div>
                ))}
              </dl>
              {auto.candidates && auto.candidates.length > 0 ? (
                <>
                  <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Adaylar</h3>
                  <ul className="space-y-2.5" data-testid="phone-candidates">
                    {auto.candidates.map((c) => (
                      <li key={`${c.market}-${c.symbol}`} className="flex items-center gap-3 text-sm">
                        <CoinAvatar symbol={c.symbol} />
                        <span className="w-24 min-w-0">
                          <b className="block truncate text-fg">{c.symbol}</b>
                          <span className="text-[11px] text-muted">
                            {MARKET[c.market] ?? c.market} · {side(c.direction)}
                          </span>
                          <LiveTick value={livePrices[`${c.market}:${c.symbol}`]} />
                        </span>
                        <ScoreBar score={c.score} threshold={threshold} />
                        <b className={`w-8 text-right tabular-nums ${c.score >= threshold ? "text-up" : "text-muted"}`}>{Math.round(c.score)}</b>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="mt-3 text-sm text-muted">Son mumda aday yok.</p>
              )}
              {auto.recent && auto.recent.length > 0 && (
                <>
                  <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Son kararlar</h3>
                  <ul className="ph-timeline space-y-2 text-xs">
                    {auto.recent.map((d) => {
                      const opened = d.result === "open";
                      return (
                        <li key={`${d.ts_ms}-${d.symbol}`} className="flex items-center justify-between gap-2">
                          <span className="text-muted">
                            {clock(d.ts_ms)} · <b className="text-fg">{d.symbol}</b> {side(d.direction)} · {Math.round(d.score)}
                          </span>
                          <span className={`flex items-center gap-1 font-semibold ${opened ? "text-up" : "text-down"}`}>
                            {opened ? <CheckCircle2 size={13} aria-hidden="true" /> : <XCircle size={13} aria-hidden="true" />}
                            {opened ? "Açıldı" : d.result === "rejected" ? "Reddedildi" : d.result}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}
        </Card>

        {/* Pozisyonlar */}
        <Card
          id="pozisyonlar"
          title="Açık pozisyonlar"
          icon={<Wallet size={17} />}
          testId="phone-positions"
          action={snap?.positions?.length ? <span className="ph-count">{snap.positions.length}</span> : undefined}
        >
          {snap?.positions && snap.positions.length > 0 ? (
            <ul className="space-y-2.5">
              {snap.positions.map((p) => {
                const qty = Number(p.quantity);
                return (
                  <li key={`${p.market}-${p.symbol}`} className="ph-row">
                    <div className="flex items-center gap-3">
                      <CoinAvatar symbol={p.symbol} />
                      <div className="min-w-0 flex-1">
                        <b className="block truncate text-fg">{p.symbol}</b>
                        <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                          <SidePill long={qty >= 0} /> {MARKET[p.market] ?? p.market}
                        </p>
                      </div>
                      <div className="text-right">
                        <PnlText value={p.unrealized_pnl} pct={p.pnl_pct} />
                      </div>
                    </div>
                    <dl className="mt-2.5 grid grid-cols-3 gap-2 border-t border-white/10 pt-2.5 text-[11px]">
                      <div>
                        <dt className="text-muted">Giriş</dt>
                        <dd className="font-semibold tabular-nums text-fg">{price(p.entry_price)}</dd>
                      </div>
                      <div>
                        <dt className="text-muted">Fiyat</dt>
                        <dd className="font-semibold tabular-nums text-fg">{price(p.mark_price)}</dd>
                      </div>
                      <div className="text-right">
                        <dt className="text-muted">Koruma</dt>
                        <dd className={`font-semibold ${p.protected ? "text-up" : "text-down"}`}>{p.protected ? "Stop var" : "Stopsuz!"}</dd>
                      </div>
                    </dl>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty icon={<Layers size={20} />}>Açık pozisyon yok</Empty>
          )}
        </Card>

        {/* Geçmiş */}
        <Card id="gecmis" title="İşlem geçmişi" icon={<Activity size={17} />} testId="phone-history">
          {snap?.history && summary && summary.count > 0 ? (
            <>
              <div className="mb-3 flex items-center gap-4">
                <Ring value={(summary.win_rate ?? 0) / 100} tone="up">
                  %{summary.win_rate ?? 0}
                  <span className="block text-[10px] font-medium text-muted">başarı</span>
                </Ring>
                <dl className="grid flex-1 grid-cols-2 gap-2">
                  {(
                    [
                      ["Bugün", Number(summary.today_net)],
                      ["Toplam", Number(summary.net_total)],
                    ] as const
                  ).map(([label, value]) => (
                    <div key={label} className="rounded-2xl bg-surface-2 px-3 py-2">
                      <dt className="text-[11px] text-muted">{label}</dt>
                      <dd className={`text-[15px] font-bold tabular-nums ${toneOf(value)}`}>{signed(value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <p className="-mt-1 mb-3 flex items-center gap-1.5 text-[11px] text-muted">
                <Trophy size={12} aria-hidden="true" /> {summary.wins} kazançlı / {summary.count} işlem · tutarlar USDT, net
              </p>
              <ul className="space-y-2">
                {snap.history.trades.map((t, i) => (
                  <li key={`${t.closed_at}-${t.symbol}-${i}`} className="flex items-center gap-3 rounded-2xl bg-surface-2 px-3 py-2">
                    <CoinAvatar symbol={t.symbol} />
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-fg">{t.symbol}</b>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                        <SidePill long={t.side === "long"} /> {clock(t.closed_at)} · {t.source === "bot" ? "Bot" : "Elle"}
                      </span>
                    </span>
                    <span className="text-right">
                      <PnlText value={t.net_pnl} pct={t.pnl_pct} />
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <Empty icon={<Activity size={20} />}>Henüz kapanmış işlem yok</Empty>
          )}
        </Card>

        {/* Fırsatlar */}
        <Card id="firsatlar" title="En iyi fırsatlar" icon={<Sparkles size={17} />} testId="phone-opportunities">
          {snap?.opportunities && snap.opportunities.length > 0 ? (
            <ul className="space-y-2.5">
              {snap.opportunities.map((o) => (
                <li key={`${o.market}-${o.symbol}`} className="flex items-center gap-3 text-sm">
                  <CoinAvatar symbol={o.symbol} />
                  <span className="w-24 min-w-0">
                    <b className="block truncate text-fg">{o.symbol}</b>
                    <span className="text-[11px] text-muted">
                      {MARKET[o.market] ?? o.market} · {side(o.direction)}
                    </span>
                    <LiveTick value={livePrices[`${o.market}:${o.symbol}`]} />
                  </span>
                  <ScoreBar score={o.score} threshold={threshold} />
                  <span className="w-11 text-right">
                    <b className="block tabular-nums text-fg">{Math.round(o.score)}</b>
                    {o.reward_risk ? <span className="block text-[10px] text-muted">R {o.reward_risk.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty icon={<Sparkles size={20} />}>Şu an 50 puan üstü fırsat yok</Empty>
          )}
        </Card>

        {/* Bildirimler */}
        <Card id="bildirimler" title="Bildirimler" icon={<Radio size={17} />} testId="phone-events">
          {events.length > 0 ? (
            <ul className="ph-timeline space-y-3">
              {events.map((e, i) => (
                <li key={`${e.ts_ms}-${i}`} className="text-sm">
                  <span className="flex justify-between gap-2">
                    <b className="text-fg">{e.title}</b>
                    <span className="shrink-0 text-xs text-muted">{clock(e.ts_ms)}</span>
                  </span>
                  <span className="block whitespace-pre-line text-muted">{e.body}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty icon={<Radio size={20} />}>Henüz bildirim yok</Empty>
          )}
        </Card>
        {snap?.whales && snap.whales.length > 0 && (
          <Card title="Balina hareketleri" icon={<Waves size={17} />}>
            <ul className="ph-timeline space-y-2.5 text-sm">
              {snap.whales.map((w, i) => (
                <li key={`${w.ts_ms}-${i}`}>
                  <span className="block text-xs text-muted">{clock(w.ts_ms)}</span>
                  <span className="text-fg">{w.message}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {push.on && <PushCard push={push} online={online} onEnable={onPushEnable} onDisable={onPushDisable} onTest={onPushTest} />}

        <section className="space-y-2 px-1 text-xs text-muted">
          <p className="flex items-start gap-2">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            Tarayıcıdan izleyebilir, acil durdurabilir ve botu durdurabilirsiniz. İşlem açma, pozisyon kapatma ve botu başlatma yalnızca
            masaüstünden yapılır. Kazanç garantisi yoktur.
          </p>
          <button type="button" className="underline underline-offset-2" onClick={onForget} data-testid="phone-forget">
            Bu telefonun eşleştirmesini sil
          </button>
        </section>
      </div>

      {toast && (
        <p
          role="status"
          className={`ph-toast fixed inset-x-4 bottom-32 z-20 mx-auto flex max-w-md items-start gap-2 rounded-2xl border px-4 py-3 text-sm font-medium shadow-xl ${toast.ok ? "border-success-fg/40 bg-[#123d3a] text-success-fg" : "border-danger-border bg-[#42142a] text-danger-fg"}`}
          data-testid="phone-toast"
        >
          {toast.ok ? <CheckCircle2 size={17} className="mt-0.5 shrink-0" aria-hidden="true" /> : <AlertOctagon size={17} className="mt-0.5 shrink-0" aria-hidden="true" />}
          {toast.text}
        </p>
      )}

      {/* Alt eylem çubuğu */}
      <nav className="ph-dock fixed inset-x-3 bottom-[max(env(safe-area-inset-bottom),12px)] z-20 mx-auto max-w-md p-2" aria-label="Hızlı işlemler">
        <div className="flex gap-2">
          <button
            type="button"
            className="flex flex-1 items-center justify-center gap-2 rounded-2xl border border-glass-border bg-white/5 py-3.5 text-sm font-semibold text-fg transition active:scale-[0.98] disabled:opacity-50"
            disabled={!auto?.enabled || busy || !online}
            onClick={onPause}
            data-testid="phone-pause"
          >
            <PauseCircle size={18} aria-hidden="true" /> Botu durdur
          </button>
          <button
            type="button"
            className="ph-kill flex flex-[1.3] items-center justify-center gap-2 rounded-2xl py-3.5 text-sm font-extrabold tracking-wide text-white transition active:scale-[0.98] disabled:opacity-50"
            disabled={engine?.kill_switch || busy || !online}
            onClick={() => setConfirmKill(true)}
            data-testid="phone-kill"
          >
            <AlertOctagon size={18} aria-hidden="true" /> ACİL DURDUR
          </button>
        </div>
      </nav>

      {confirmKill && (
        <div role="dialog" aria-modal="true" aria-labelledby="kill-title" className="fixed inset-0 z-30 grid place-items-end bg-black/60 p-3 backdrop-blur-sm sm:place-items-center">
          <div className="ph-sheet w-full max-w-md rounded-3xl p-5 pt-3">
            <span className="mx-auto mb-4 block h-1.5 w-12 rounded-full bg-white/25" aria-hidden="true" />
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-danger-bg text-danger-fg" aria-hidden="true">
                <AlertOctagon size={22} />
              </span>
              <h2 id="kill-title" className="text-lg font-bold text-fg">
                Acil durdurma
              </h2>
            </div>
            <p className="mt-3 text-sm text-muted">
              Yeni işlem açılması hemen durur. Açık pozisyonların borsadaki stopları yerinde kalır. Kaldırmak için masaüstü uygulaması gerekir.
            </p>
            <div className="mt-5 flex gap-3">
              <button type="button" className="flex-1 rounded-2xl border border-glass-border py-3.5 text-sm font-semibold text-fg" onClick={() => setConfirmKill(false)}>
                Vazgeç
              </button>
              <button
                type="button"
                className="ph-kill flex-1 rounded-2xl py-3.5 text-sm font-extrabold text-white"
                onClick={() => {
                  setConfirmKill(false);
                  onKill();
                }}
                data-testid="phone-kill-confirm"
              >
                Durdur
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
