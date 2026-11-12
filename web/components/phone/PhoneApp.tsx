"use client";

import {
  Activity,
  AlertOctagon,
  Bot,
  CheckCircle2,
  Clock,
  Lock,
  PauseCircle,
  Radio,
  RefreshCw,
  ShieldAlert,
  Smartphone,
  Sparkles,
  Unplug,
  Waves,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { parsePairing, RemoteError } from "@/lib/remote";
import { deviceStore, type EngineEvent, type Phase, RemoteClient, type StoredDevice } from "@/lib/remoteClient";

type Snap = {
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
};

const STATE: Record<string, [string, string]> = {
  running: ["Çalışıyor", "text-up"],
  safe_mode: ["Güvenli mod", "text-warn-fg"],
  starting: ["Başlıyor", "text-warn-fg"],
  halted: ["Durduruldu", "text-down"],
  stopped: ["Kapalı", "text-muted"],
};
const MODE: Record<string, string> = { paper: "Sanal", testnet: "Demo para", live: "GERÇEK PARA" };
const MARKET: Record<string, string> = { spot: "Spot", usdm_futures: "Futures", "Market.SPOT": "Spot", "Market.USDM_FUTURES": "Futures" };
const EVERY: Record<string, string> = { "1m": "her dakika", "5m": "5 dakikada bir", "15m": "15 dakikada bir", "1h": "saat başı" };

const clock = (ms?: number) =>
  ms ? new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
const money = (v?: string | number) => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("tr-TR", { maximumFractionDigits: 2 }) : "—";
};

function Panel({ title, icon, children, testId, action }: { title: string; icon: ReactNode; children: ReactNode; testId?: string; action?: ReactNode }) {
  return (
    <section className="rounded-3xl border border-glass-border bg-glass p-4 shadow-sm backdrop-blur" data-testid={testId}>
      <header className="mb-3 flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-xl bg-surface-2 text-accent-text" aria-hidden="true">
          {icon}
        </span>
        <h2 className="flex-1 text-[15px] font-semibold text-fg">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

/** Anlık kâr/zarar: yön oku, renk ve değişimde kısa parlama. */
function PnlText({ value, pct }: { value?: string | number | null; pct?: number | null }) {
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
  const tone = n > 0 ? "text-up" : n < 0 ? "text-down" : "text-fg";
  return (
    <span className={`inline-block rounded-lg px-1.5 text-sm font-bold tabular-nums transition-colors duration-500 ${tone} ${flash}`} data-testid="phone-pnl">
      {n > 0 ? "▲ +" : n < 0 ? "▼ " : ""}
      {money(n)} USDT{pct !== null && pct !== undefined ? ` (${pct > 0 ? "+" : ""}${pct.toFixed(2)}%)` : ""}
    </span>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-2xl bg-surface-2 px-3 py-4 text-center text-sm text-muted">{children}</p>;
}

function ScoreBar({ score, threshold }: { score: number; threshold: number }) {
  const pass = score >= threshold;
  return (
    <span className="relative block h-2 flex-1 rounded-full bg-surface-3" aria-hidden="true">
      <span className={`absolute inset-y-0 left-0 rounded-full ${pass ? "bg-up" : "bg-accent"}`} style={{ width: `${Math.min(100, score)}%` }} />
      <span className="absolute -inset-y-1 w-0.5 bg-warn-fg" style={{ left: `${threshold}%` }} />
    </span>
  );
}

const PHASE_TEXT: Record<Phase, string> = {
  connecting: "Bilgisayara bağlanılıyor…",
  pairing: "Eşleştiriliyor…",
  online: "Bağlı",
  engine_offline: "Bilgisayar çevrim dışı",
  offline: "Bağlantı yok",
  rejected: "Reddedildi",
};

export function PhoneApp() {
  const [device, setDevice] = useState<StoredDevice | null | undefined>(undefined);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [detail, setDetail] = useState<string | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [snapAt, setSnapAt] = useState<number | null>(null);
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmKill, setConfirmKill] = useState(false);
  const [busy, setBusy] = useState(false);
  const client = useRef<RemoteClient | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);

  const listener = useCallback(
    () => ({
      phase: (p: Phase, d?: string) => {
        setPhase(p);
        setDetail(d ?? null);
      },
      snapshot: (data: Record<string, unknown>, evs: EngineEvent[], ts: number) => {
        setSnap(data as Snap);
        setSnapAt(ts);
        setEvents(evs.slice(0, 20));
      },
      event: (e: EngineEvent) => setEvents((list) => [e, ...list].slice(0, 20)),
      result: (ok: boolean, text: string) => {
        if (pending.current) clearTimeout(pending.current);
        setBusy(false);
        setToast({ ok, text });
        setTimeout(() => setToast(null), 5000);
      },
      paired: (d: StoredDevice) => setDevice(d),
    }),
    [],
  );

  // Açılış: adreste yeni QR varsa eşleş; yoksa kayıtlı eşleşmeyle bağlan.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const hash = window.location.hash;
      if (hash.includes("p=")) {
        // Gizli eşleştirme değeri tarayıcı geçmişinde kalmasın.
        history.replaceState(null, "", window.location.pathname);
        try {
          const code = await parsePairing(hash);
          const name = /iPhone|iPad/.test(navigator.userAgent) ? "iPhone (tarayıcı)" : /Android/.test(navigator.userAgent) ? "Android (tarayıcı)" : "Telefon (tarayıcı)";
          const c = await RemoteClient.pair(code, name, listener());
          if (cancelled) return;
          client.current?.stop();
          client.current = c;
          setDevice(null);
          c.start();
          return;
        } catch (e) {
          setError(e instanceof RemoteError ? e.message : "QR kodu açılamadı");
        }
      }
      const stored = await deviceStore.load().catch(() => undefined);
      if (cancelled) return;
      setDevice(stored ?? null);
      if (stored?.pairedAt) {
        const c = new RemoteClient(stored, listener());
        client.current = c;
        c.start();
      }
    })();
    return () => {
      cancelled = true;
      client.current?.stop();
    };
  }, [listener]);

  async function send(command: string) {
    setBusy(true);
    if (pending.current) clearTimeout(pending.current);
    // Motor, eşleştirmesi kaldırılmış cihaza yanıt vermez; sonsuza dek beklenmez.
    pending.current = setTimeout(() => {
      setBusy(false);
      setToast({ ok: false, text: "Bilgisayardan yanıt gelmedi. Eşleştirme masaüstünden kaldırılmış olabilir." });
    }, 10_000);
    try {
      await client.current?.command(command);
    } catch (e) {
      if (pending.current) clearTimeout(pending.current);
      setBusy(false);
      setToast({ ok: false, text: e instanceof Error ? e.message : "Gönderilemedi" });
    }
  }

  async function forget() {
    client.current?.stop();
    client.current = null;
    await deviceStore.clear();
    setDevice(null);
    setSnap(null);
  }

  const paired = Boolean(device?.pairedAt) || phase === "online";
  const engine = snap?.engine;
  const auto = snap?.autotrade;
  const threshold = auto?.min_score ?? 70;
  const live = engine?.trading_mode === "live";
  const [stateText, stateTone] = STATE[engine?.state ?? ""] ?? ["—", "text-muted"];
  const minutes = auto?.next_decision_ms ? Math.max(0, Math.ceil((auto.next_decision_ms - now) / 60_000)) : null;

  // --- Eşleşme yok ---------------------------------------------------------------------------
  if (device === undefined && !error) {
    return <div className="grid min-h-dvh place-items-center text-muted">Yükleniyor…</div>;
  }
  if (!paired && !client.current) {
    return (
      <div className="phone-neon">
      <main id="icerik" className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-5 py-10" data-testid="phone-welcome">
        <div className="flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-brand-1 to-brand-2 text-white">
            <Smartphone size={24} aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-xl font-semibold text-fg">Telefondan izleme</h1>
            <p className="text-sm text-muted">AI Trading Intelligence</p>
          </div>
        </div>
        {error && (
          <p role="alert" className="rounded-2xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg" data-testid="phone-error">
            {error}
          </p>
        )}
        <ol className="space-y-3 text-sm text-fg">
          {[
            "Bilgisayarda uygulamayı açın → Telefon ekranı → \"Telefondan kontrol\"ü açın.",
            "\"QR kodu göster\"e basın.",
            "Telefonun kamerasıyla QR'ı okutun; bu sayfa açılır ve birkaç saniyede eşleşir.",
          ].map((t, i) => (
            <li key={t} className="flex gap-3 rounded-2xl border border-glass-border bg-glass p-3">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-surface-2 font-semibold text-accent-text">{i + 1}</span>
              <span>{t}</span>
            </li>
          ))}
        </ol>
        <p className="flex items-start gap-2 text-xs text-muted">
          <Lock size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          Bağlantı uçtan uca şifrelidir; anahtarlar yalnızca bu telefonda durur. Tarayıcıdan işlem açılamaz, para çekilemez.
        </p>
      </main>
      </div>
    );
  }

  // --- Panel ---------------------------------------------------------------------------------
  return (
    <div className="phone-neon">
    <main id="icerik" className="mx-auto max-w-md space-y-4 px-4 pb-28 pt-4" data-testid="phone-app">
      <header className="sticky top-0 z-10 -mx-4 flex items-center gap-3 bg-bg/80 px-4 py-3 backdrop-blur">
        <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-brand-1 to-brand-2 text-white" aria-hidden="true">
          <Activity size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold text-fg">AI Trading Intelligence</h1>
          <p className="flex items-center gap-1.5 text-xs text-muted" data-testid="phone-phase">
            <span className={`h-2 w-2 rounded-full ${phase === "online" ? "bg-up" : phase === "rejected" ? "bg-down" : "bg-warn-fg"}`} aria-hidden="true" />
            {PHASE_TEXT[phase]}
            {snapAt && phase === "online" ? ` · ${clock(snapAt)}` : ""}
            {snapAt && phase === "online" && now - snapAt > 60_000 ? " · veri eski" : ""}
          </p>
        </div>
        <button
          type="button"
          aria-label="Yenile"
          className="grid h-10 w-10 place-items-center rounded-2xl border border-glass-border bg-glass text-fg"
          onClick={() => void send("request_snapshot")}
          disabled={phase !== "online"}
        >
          <RefreshCw size={18} aria-hidden="true" />
        </button>
      </header>

      {detail && phase !== "online" && <p className="rounded-2xl bg-warn-bg px-3 py-2 text-sm text-warn-fg">{detail}</p>}
      {phase === "engine_offline" && (
        <p className="flex items-center gap-2 rounded-2xl border border-warn-border bg-warn-bg px-3 py-2 text-sm text-warn-fg">
          <Unplug size={16} aria-hidden="true" /> Bilgisayar kapalı ya da uygulama çalışmıyor. Açıldığında otomatik bağlanır.
        </p>
      )}

      {/* Binance bakiyesi */}
      {snap?.risk?.wallets && snap.risk.wallets.length > 0 && (
        <section className={`neon-balance rounded-3xl p-5 ${live ? "live" : ""}`} data-testid="phone-balance">
          <p className="text-xs font-semibold uppercase tracking-wide text-[#bdf6ff]">Binance bakiyesi{live ? " · gerçek hesap" : ""}</p>
          <p className="neon-value mt-1 text-4xl font-extrabold tracking-tight">
            {money(snap.risk.wallets.reduce((sum, w) => sum + Number(w.balance) + Number(w.unrealized_pnl), 0))}{" "}
            <span className="text-lg">USDT</span>
          </p>
          {snap.positions && snap.positions.some((p) => p.unrealized_pnl != null) && (
            <p className="mt-1 text-sm text-muted">
              Açık pozisyonlar:{" "}
              <PnlText value={snap.positions.reduce((sum, p) => sum + Number(p.unrealized_pnl ?? 0), 0)} />
            </p>
          )}
          <ul className="mt-3 grid grid-cols-2 gap-2">
            {snap.risk.wallets.map((w) => (
              <li key={w.market} className="rounded-2xl border border-glass-border bg-surface-2 px-3 py-2">
                <span className="block text-[11px] text-muted">{MARKET[w.market] ?? w.market} cüzdanı</span>
                <b className="block text-fg">{money(w.balance)} {w.asset}</b>
                <span className="block text-[11px] text-muted">kullanılabilir {money(w.available)}</span>
              </li>
            ))}
          </ul>
          {snap.risk.halted && (
            <p className="mt-3 rounded-2xl border border-warn-border bg-warn-bg px-3 py-2 text-xs text-warn-fg">
              Bugün yeni işlem kilitli{snap.risk.halt_reason ? `: ${snap.risk.halt_reason}` : ""}. Kilidi masaüstünden kaldırabilirsiniz.
            </p>
          )}
        </section>
      )}

      {/* Durum kartı */}
      <section
        className={`relative overflow-hidden rounded-3xl p-5 text-white shadow-lg ${live ? "bg-gradient-to-br from-rose-700 to-orange-600" : "bg-gradient-to-br from-[#1366b8] to-[#5a37d6]"}`}
        data-testid="phone-status"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide opacity-80">Motor</p>
            <p className="text-2xl font-semibold" data-testid="phone-engine-state">
              {engine ? stateText : "Bekleniyor"}
            </p>
            {engine?.state !== "running" && engine?.reason ? <p className="mt-1 text-xs opacity-85">{engine.reason}</p> : null}
          </div>
          <span className="rounded-full bg-white/20 px-3 py-1 text-xs font-semibold" data-testid="phone-mode">
            {MODE[engine?.trading_mode ?? ""] ?? "—"}
          </span>
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-2xl bg-white/15 p-2">
            <dt className="text-[11px] opacity-80">Özsermaye</dt>
            <dd className="font-semibold">{snap?.risk ? money(snap.risk.equity) : "—"}</dd>
          </div>
          <div className="rounded-2xl bg-white/15 p-2">
            <dt className="text-[11px] opacity-80">Günlük zarar</dt>
            <dd className="font-semibold">{snap?.risk ? `%${money(snap.risk.daily_loss_pct)}` : "—"}</dd>
          </div>
          <div className="rounded-2xl bg-white/15 p-2">
            <dt className="text-[11px] opacity-80">Pozisyon</dt>
            <dd className="font-semibold">{snap?.positions?.length ?? 0}</dd>
          </div>
        </dl>
        {engine?.kill_switch && (
          <p className="mt-3 flex items-center gap-2 rounded-2xl bg-black/25 px-3 py-2 text-sm" data-testid="phone-kill-on">
            <AlertOctagon size={16} aria-hidden="true" /> Acil durdurma devrede{engine.kill_reason ? `: ${engine.kill_reason}` : ""}
          </p>
        )}
      </section>

      {/* Bot */}
      <Panel
        title="Bot"
        icon={<Bot size={17} />}
        testId="phone-bot"
        action={
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${auto?.enabled ? "bg-success-bg text-success-fg" : "bg-surface-2 text-muted"}`} data-testid="phone-bot-state">
            {auto?.enabled ? "Çalışıyor" : "Durdu"}
          </span>
        }
      >
        {auto ? (
          <>
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <Clock size={13} aria-hidden="true" /> Sonraki karar {clock(auto.next_decision_ms)}
              {minutes !== null ? ` (${minutes > 0 ? `${minutes} dk` : "1 dk içinde"})` : ""} · {EVERY[auto.interval ?? ""] ?? auto.interval} · eşik {threshold}
            </p>
            <p className="mt-1 text-xs text-muted">
              Sinyal {auto.signals ?? 0} · açılan {auto.opened} · risk reddi {auto.rejected}
            </p>
            {auto.candidates && auto.candidates.length > 0 ? (
              <ul className="mt-3 space-y-2" data-testid="phone-candidates">
                {auto.candidates.map((c) => (
                  <li key={`${c.market}-${c.symbol}`} className="flex items-center gap-3 text-sm">
                    <span className="w-28 min-w-0">
                      <b className="block truncate text-fg">{c.symbol}</b>
                      <span className="text-xs text-muted">
                        {MARKET[c.market] ?? c.market} · {c.direction === "long" ? "Long" : "Short"}
                      </span>
                    </span>
                    <ScoreBar score={c.score} threshold={threshold} />
                    <b className={c.score >= threshold ? "text-up" : "text-muted"}>{Math.round(c.score)}</b>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted">Son mumda aday yok.</p>
            )}
            {auto.recent && auto.recent.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-border pt-3 text-xs">
                {auto.recent.map((d) => (
                  <li key={`${d.ts_ms}-${d.symbol}`} className="flex justify-between gap-2">
                    <span className="text-muted">
                      {clock(d.ts_ms)} · {d.symbol} {d.direction === "long" ? "Long" : "Short"} · {Math.round(d.score)}
                    </span>
                    <b className={d.result === "open" ? "text-up" : "text-down"}>{d.result === "open" ? "Açıldı" : d.result === "rejected" ? "Reddedildi" : d.result}</b>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <Empty>Bot bilgisi bekleniyor</Empty>
        )}
      </Panel>

      {/* Pozisyonlar */}
      <Panel title="Açık pozisyonlar" icon={<Wallet size={17} />} testId="phone-positions">
        {snap?.positions && snap.positions.length > 0 ? (
          <ul className="space-y-2">
            {snap.positions.map((p) => {
              const qty = Number(p.quantity);
              return (
                <li key={`${p.market}-${p.symbol}`} className="flex items-center justify-between rounded-2xl bg-surface-2 px-3 py-2.5">
                  <span>
                    <b className="text-fg">{p.symbol}</b>{" "}
                    <span className={`text-xs font-semibold ${qty >= 0 ? "text-up" : "text-down"}`}>{qty >= 0 ? "Long" : "Short"}</span>
                    <span className="block text-xs text-muted">
                      {MARKET[p.market] ?? p.market} · giriş {money(p.entry_price)} · miktar {money(Math.abs(qty))}
                    </span>
                  </span>
                  <span className="text-right">
                    <PnlText value={p.unrealized_pnl} pct={p.pnl_pct} />
                    <span className="block text-[11px] text-muted">
                      {p.mark_price ? `fiyat ${money(p.mark_price)} · ` : ""}
                      {p.protected ? <span className="text-up">stop var</span> : <span className="text-down">stopsuz!</span>}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty>Açık pozisyon yok</Empty>
        )}
      </Panel>

      {/* İşlem geçmişi */}
      <Panel title="İşlem geçmişi" icon={<Activity size={17} />} testId="phone-history">
        {snap?.history && snap.history.summary.count > 0 ? (
          <>
            <div className="mb-3 grid grid-cols-3 gap-2 text-center">
              {[
                ["Bugün", snap.history.summary.today_net],
                ["Toplam", snap.history.summary.net_total],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl bg-surface-2 p-2">
                  <span className="block text-[11px] text-muted">{label}</span>
                  <b className={`text-sm ${Number(value) > 0 ? "text-up" : Number(value) < 0 ? "text-down" : "text-fg"}`}>
                    {Number(value) > 0 ? "+" : ""}
                    {money(value)}
                  </b>
                </div>
              ))}
              <div className="rounded-2xl bg-surface-2 p-2">
                <span className="block text-[11px] text-muted">Başarı</span>
                <b className="text-sm text-fg">%{snap.history.summary.win_rate ?? 0}</b>
              </div>
            </div>
            <ul className="space-y-2">
              {snap.history.trades.map((t, i) => (
                <li key={`${t.closed_at}-${t.symbol}-${i}`} className="flex items-center justify-between rounded-2xl bg-surface-2 px-3 py-2">
                  <span>
                    <b className="text-fg">{t.symbol}</b>{" "}
                    <span className={`text-xs font-semibold ${t.side === "long" ? "text-up" : "text-down"}`}>{t.side === "long" ? "Long" : "Short"}</span>
                    <span className="block text-[11px] text-muted">
                      {clock(t.closed_at)} · {t.source === "bot" ? "Bot" : "Elle"}
                    </span>
                  </span>
                  <PnlText value={t.net_pnl} pct={t.pnl_pct} />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <Empty>Henüz kapanmış işlem yok</Empty>
        )}
      </Panel>

      {/* Fırsatlar */}
      <Panel title="En iyi fırsatlar" icon={<Sparkles size={17} />} testId="phone-opportunities">
        {snap?.opportunities && snap.opportunities.length > 0 ? (
          <ul className="space-y-2">
            {snap.opportunities.map((o) => (
              <li key={`${o.market}-${o.symbol}`} className="flex items-center gap-3 text-sm">
                <span className="w-28 min-w-0">
                  <b className="block truncate text-fg">{o.symbol}</b>
                  <span className="text-xs text-muted">
                    {MARKET[o.market] ?? o.market} · {o.direction === "long" ? "Long" : "Short"}
                  </span>
                </span>
                <ScoreBar score={o.score} threshold={threshold} />
                <b className="text-fg">{o.score}</b>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Şu an 50 puan üstü fırsat yok</Empty>
        )}
      </Panel>

      {/* Bildirimler ve balinalar */}
      <Panel title="Bildirimler" icon={<Radio size={17} />} testId="phone-events">
        {events.length > 0 ? (
          <ul className="space-y-2">
            {events.map((e, i) => (
              <li key={`${e.ts_ms}-${i}`} className="rounded-2xl bg-surface-2 px-3 py-2 text-sm">
                <span className="flex justify-between gap-2">
                  <b className="text-fg">{e.title}</b>
                  <span className="text-xs text-muted">{clock(e.ts_ms)}</span>
                </span>
                <span className="text-muted">{e.body}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Henüz bildirim yok</Empty>
        )}
      </Panel>
      {snap?.whales && snap.whales.length > 0 && (
        <Panel title="Balina hareketleri" icon={<Waves size={17} />}>
          <ul className="space-y-2 text-sm">
            {snap.whales.map((w, i) => (
              <li key={`${w.ts_ms}-${i}`} className="flex gap-2">
                <span className="text-xs text-muted">{clock(w.ts_ms)}</span>
                <span className="text-fg">{w.message}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <section className="space-y-2 text-xs text-muted">
        <p className="flex items-start gap-2">
          <ShieldAlert size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          Tarayıcıdan izleyebilir, acil durdurabilir ve botu durdurabilirsiniz. İşlem açma, pozisyon kapatma ve botu başlatma
          yalnızca masaüstünden yapılır. Kazanç garantisi yoktur.
        </p>
        <button type="button" className="underline underline-offset-2" onClick={() => void forget()} data-testid="phone-forget">
          Bu telefonun eşleştirmesini sil
        </button>
      </section>

      {toast && (
        <p
          role="status"
          className={`fixed inset-x-4 bottom-28 z-20 mx-auto max-w-md rounded-2xl px-4 py-3 text-sm shadow-lg ${toast.ok ? "bg-success-bg text-success-fg" : "bg-danger-bg text-danger-fg"}`}
          data-testid="phone-toast"
        >
          {toast.ok ? <CheckCircle2 size={16} className="mr-1 inline" aria-hidden="true" /> : null}
          {toast.text}
        </p>
      )}

      {/* Alt eylem çubuğu */}
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-glass-border bg-bg/90 px-4 pb-[max(env(safe-area-inset-bottom),12px)] pt-3 backdrop-blur" aria-label="Hızlı işlemler">
        <div className="mx-auto flex max-w-md gap-3">
          <button
            type="button"
            className="flex flex-1 items-center justify-center gap-2 rounded-2xl border border-glass-border bg-glass py-3.5 text-sm font-semibold text-fg disabled:opacity-50"
            disabled={!auto?.enabled || busy || phase !== "online"}
            onClick={() => void send("pause_autotrade")}
            data-testid="phone-pause"
          >
            <PauseCircle size={18} aria-hidden="true" /> Botu durdur
          </button>
          <button
            type="button"
            className="flex flex-[1.3] items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-rose-600 to-red-500 py-3.5 text-sm font-bold text-white shadow-lg disabled:opacity-50"
            disabled={engine?.kill_switch || busy || phase !== "online"}
            onClick={() => setConfirmKill(true)}
            data-testid="phone-kill"
          >
            <AlertOctagon size={18} aria-hidden="true" /> ACİL DURDUR
          </button>
        </div>
      </nav>

      {confirmKill && (
        <div role="dialog" aria-modal="true" aria-labelledby="kill-title" className="fixed inset-0 z-30 grid place-items-end bg-black/50 p-4 sm:place-items-center">
          <div className="w-full max-w-md rounded-3xl bg-surface p-5 shadow-xl">
            <h2 id="kill-title" className="text-lg font-semibold text-fg">
              Acil durdurma
            </h2>
            <p className="mt-2 text-sm text-muted">
              Yeni işlem açılması hemen durur. Açık pozisyonların borsadaki stopları yerinde kalır. Kaldırmak için masaüstü uygulaması
              gerekir.
            </p>
            <div className="mt-4 flex gap-3">
              <button type="button" className="flex-1 rounded-2xl border border-border py-3 text-sm font-semibold text-fg" onClick={() => setConfirmKill(false)}>
                Vazgeç
              </button>
              <button
                type="button"
                className="flex-1 rounded-2xl bg-red-600 py-3 text-sm font-bold text-white"
                onClick={() => {
                  setConfirmKill(false);
                  void send("engage_kill_switch");
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
    </div>
  );
}
