import { AlertTriangle, Bot, CheckCircle2, ChevronRight, Clock, Play, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { isTauri } from "../lib/connection";
import { MARKET_LABELS, num } from "../lib/format";
import { useNavigate } from "../lib/nav";
import { Badge, Confirm, ErrorBox } from "./ui";

interface Check {
  key: string;
  ok: boolean;
  title: string;
  detail: string;
  page: string;
}

interface Candidate {
  market: string;
  symbol: string;
  direction: string;
  score: number;
  age_s: number;
  fresh: boolean;
}

interface Decision {
  ts_ms: number;
  market: string;
  symbol: string;
  direction: string;
  score: number;
  result?: string;
  reasons?: string[];
}

export interface BotStatus {
  enabled: boolean;
  environment: "paper" | "testnet" | "live";
  interval: string;
  signal_valid_s: number;
  decision_interval_saved: string | null;
  restart_required: boolean;
  next_decision_ms: number;
  candidates: Candidate[];
  checks: Check[];
  ready: boolean;
  settings: { min_score: number };
  stats: Record<string, number>;
  skipped: Record<string, number>;
  recent: Decision[];
  replayed_opened?: number;
}

/** Motorun sayfa adları → uygulamadaki sayfa. */
const PAGES: Record<string, string> = { license: "settings", bot: "trading" };

/** Botun bir sinyali neden kullanmadığı (motordaki kodlar). */
export const SKIP_LABELS: Record<string, string> = {
  kapalı: "Bot kapalıydı",
  mod_sanal: "İşlem modu Sanal",
  piyasa: "Bu piyasa botta seçili değil",
  puan: "Puan eşiğin altında",
  kayıp_serisi_molası: "Kayıp molası",
  yön: "Yön belirsiz",
  spot_short: "Spot'ta açığa satış yok",
  seviye_yok: "Stop/hedef seviyesi yok",
  eski_sinyal: "Sinyal eskidi (fiyat değişmiş olabilir)",
  fiyat_kaçtı: "Fiyat sinyalden çok uzaklaştı",
  saatlik_sınır: "Saatlik işlem sınırı doldu",
  bekleme: "Aynı coinde bekleme süresi",
  bağlı_değil: "Binance hesabı bağlı değil",
  test_ağında_yok: "Coin bu hesapta işlem görmüyor",
  açık_pozisyon: "Bu coinde zaten pozisyon var",
  hazırlık_hatası: "Emir hazırlanamadı",
  fiyat_yok: "Güncel fiyat alınamadı",
  miktar_küçük: "Miktar borsa alt sınırının altında",
};

const RESULT_LABELS: Record<string, string> = {
  open: "Açıldı",
  rejected: "Risk kapısı reddetti",
  blocked: "Engellendi",
  error: "Hata",
};

const INTERVALS: { key: string; label: string; every: string }[] = [
  { key: "1m", label: "1 dk", every: "her dakika" },
  { key: "5m", label: "5 dk", every: "5 dakikada bir" },
  { key: "15m", label: "15 dk", every: "15 dakikada bir" },
  { key: "1h", label: "1 saat", every: "her saat başı" },
];

const ENV_LABELS: Record<string, string> = { paper: "Sanal", testnet: "Demo para", live: "GERÇEK PARA" };

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function useNow(everyMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}

/** Genel bakıştaki bot paneli: başlat/durdur, "neden işlem açmıyor" listesi, sonraki karar
 * zamanı, en yakın adaylar ve son kararlar. */
export function BotPanel() {
  const navigate = useNavigate();
  const now = useNow();
  const auto = usePoll((c) => c.get<BotStatus>("/v1/autotrade"), 5000);
  const toggle = useAction((c, enabled: boolean) => c.post<BotStatus>("/v1/autotrade", { enabled }));
  const saveInterval = useAction((c, interval: string) => c.post<BotStatus>("/v1/autotrade/interval", { interval }));
  const [message, setMessage] = useState<string | null>(null);
  const [askInterval, setAskInterval] = useState<string | null>(null);
  const s = auto.data;

  if (!s) {
    return (
      <section className="bot-panel card" data-testid="bot-panel">
        <ErrorBox error={auto.error} what="Bot" />
      </section>
    );
  }

  const missing = s.checks.filter((c) => !c.ok && c.key !== "enabled");
  const minutes = Math.max(0, Math.ceil((s.next_decision_ms - now) / 60_000));
  const skipped = Object.entries(s.skipped)
    .filter(([code]) => code !== "kapalı")
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  async function applyInterval(interval: string) {
    setAskInterval(null);
    const result = await saveInterval.execute(interval);
    if (!result) return;
    if (isTauri()) {
      setMessage("Karar aralığı kaydedildi; motor yeniden başlatılıyor (birkaç saniye)…");
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("engine_restart");
      } catch (e) {
        setMessage(`Motor yeniden başlatılamadı: ${String(e)}. Uygulamayı kapatıp açın.`);
      }
    } else {
      setMessage("Karar aralığı kaydedildi. Uygulamayı kapatıp açınca geçerli olur.");
    }
    await auto.refresh();
  }

  async function onToggle() {
    setMessage(null);
    const result = await toggle.execute(!s?.enabled);
    if (result?.enabled) {
      setMessage(
        result.replayed_opened
          ? `Bot başladı ve hemen ${result.replayed_opened} işlem açtı.`
          : `Bot başladı. Şu an eşiği geçen taze sinyal yok; sonraki karar ${clock(result.next_decision_ms)}.`,
      );
    } else if (result) {
      setMessage("Bot durduruldu. Açık pozisyonlar ve borsadaki stoplar yerinde kalır.");
    }
    await auto.refresh();
  }

  return (
    <section className={`bot-panel card ${s.enabled ? "on" : ""}`} data-testid="bot-panel" aria-labelledby="bot-title">
      <div className="bot-head">
        <span className="bot-icon" aria-hidden="true">
          <Bot size={22} />
        </span>
        <div className="bot-title">
          <h2 id="bot-title">
            Bot{" "}
            <Badge tone={s.enabled ? "ok" : "neutral"} testId="auto-state">
              {s.enabled ? "Çalışıyor" : "Durdu"}
            </Badge>{" "}
            <Badge tone={s.environment === "live" ? "bad" : s.environment === "testnet" ? "info" : "warn"} testId="bot-env">
              {ENV_LABELS[s.environment]}
            </Badge>
          </h2>
          <span className="muted small" data-testid="bot-next">
            <Clock size={13} aria-hidden="true" /> Sonraki karar {clock(s.next_decision_ms)} (
            {minutes > 0 ? `${minutes} dk sonra` : "1 dk içinde"}) · {INTERVALS.find((i) => i.key === s.interval)?.every ?? s.interval}{" "}
            · puan eşiği {num(s.settings.min_score, 0)}
          </span>
          <div className="interval-picker" role="radiogroup" aria-label="Karar aralığı" data-testid="interval-picker">
            <span className="muted small">Karar aralığı</span>
            {INTERVALS.map((i) => {
              const target = s.decision_interval_saved ?? s.interval;
              return (
                <button
                  key={i.key}
                  type="button"
                  role="radio"
                  aria-checked={target === i.key}
                  className={`chip ${target === i.key ? "active" : ""}`}
                  disabled={saveInterval.pending || target === i.key}
                  onClick={() => setAskInterval(i.key)}
                  data-testid={`interval-${i.key}`}
                >
                  {i.label}
                </button>
              );
            })}
            {s.restart_required && <Badge tone="warn">Yeniden başlatınca geçerli</Badge>}
          </div>
        </div>
        <button
          type="button"
          className={s.enabled ? "big" : "primary big"}
          disabled={toggle.pending}
          onClick={() => void onToggle()}
          data-testid="auto-toggle"
        >
          {s.enabled ? <Square size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
          {s.enabled ? "Botu durdur" : "Botu başlat"}
        </button>
      </div>
      {message && (
        <p className="bot-message" role="status" data-testid="bot-message">
          {message}
        </p>
      )}
      <ErrorBox error={toggle.error ?? saveInterval.error} />
      <Confirm
        open={askInterval !== null}
        title="Karar aralığını değiştir"
        confirmLabel="Kaydet ve motoru yeniden başlat"
        onCancel={() => setAskInterval(null)}
        onConfirm={() => void applyInterval(askInterval ?? "1h")}
      >
        Bot, fırsatları {INTERVALS.find((i) => i.key === askInterval)?.every ?? ""} değerlendirecek. Kısa aralıkta daha sık
        sinyal çıkar, ama fiyat gürültüsü ve komisyon payı da artar; saatlik giriş sınırı ve risk kapısı aynen geçerlidir.
        Motor birkaç saniye yeniden başlar: bot kapanır, Gerçek para modundaysanız Sanal moda döner ve yeniden onay
        gerekir. Fırsat taraması yeni aralıkla 1–3 dakikada yeniden dolar. Borsadaki stop emirleri yerinde kalır.
      </Confirm>

      <div className="bot-grid">
        <div>
          <h3 className="section-title">{missing.length ? "Bot neden işlem açamıyor?" : "Hazırlık"}</h3>
          {missing.length === 0 ? (
            <p className="bot-ok" data-testid="bot-ready">
              <CheckCircle2 size={18} aria-hidden="true" /> Her şey hazır. Bot, puanı {num(s.settings.min_score, 0)} ve
              üzerindeki sinyallerde risk kapısından geçerek işlem açar.
            </p>
          ) : (
            <ul className="bot-checks" data-testid="bot-checks">
              {missing.map((c) => (
                <li key={c.key}>
                  <AlertTriangle size={16} aria-hidden="true" />
                  <span className="bot-check-text">
                    <b>{c.title}</b>
                    <span className="muted small">{c.detail}</span>
                  </span>
                  {c.page !== "dashboard" && (
                    <button type="button" className="ghost" onClick={() => navigate(PAGES[c.page] ?? c.page)} data-testid={`fix-${c.key}`}>
                      Düzelt <ChevronRight size={14} aria-hidden="true" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {skipped.length > 0 && (
            <>
              <h3 className="section-title">Kullanılmayan sinyaller</h3>
              <ul className="bot-reasons" data-testid="bot-reasons">
                {skipped.map(([code, count]) => (
                  <li key={code}>
                    <span>{SKIP_LABELS[code] ?? code}</span>
                    <b>{count}</b>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div>
          <h3 className="section-title">Son mumun en iyi adayları</h3>
          {s.candidates.length === 0 ? (
            <p className="muted small" data-testid="bot-no-candidates">
              Henüz aday yok. Fırsat taraması bittiğinde ve her saat başı burada en yüksek puanlı coinler görünür.
            </p>
          ) : (
            <ul className="bot-candidates" data-testid="bot-candidates">
              {s.candidates.map((c) => {
                const passes = c.score >= s.settings.min_score;
                return (
                  <li key={`${c.market}-${c.symbol}`}>
                    <span className="bot-cand-name">
                      <b>{c.symbol}</b>
                      <span className="muted small">
                        {MARKET_LABELS[c.market] ?? c.market} · {c.direction === "long" ? "Long" : "Short"}
                        {!c.fresh && " · eski"}
                      </span>
                    </span>
                    <span className="bot-meter" aria-hidden="true">
                      <span style={{ width: `${Math.min(100, c.score)}%` }} className={passes ? "pass" : ""} />
                      <i style={{ left: `${s.settings.min_score}%` }} />
                    </span>
                    <b className={passes ? "up" : "muted"}>{num(c.score, 0)}</b>
                  </li>
                );
              })}
            </ul>
          )}
          {s.recent.length > 0 && (
            <>
              <h3 className="section-title">Son kararlar</h3>
              <ul className="bot-reasons" data-testid="bot-recent">
                {s.recent.slice(0, 4).map((d) => (
                  <li key={`${d.ts_ms}-${d.symbol}`}>
                    <span>
                      {clock(d.ts_ms)} · {d.symbol} {d.direction === "long" ? "Long" : "Short"} · puan {num(d.score, 0)}
                    </span>
                    <b className={d.result === "open" ? "up" : "down"}>{RESULT_LABELS[d.result ?? ""] ?? d.result}</b>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      <p className="muted small bot-foot">
        Sinyal {s.stats.signals ?? 0} · açılan {s.stats.opened ?? 0} · risk reddi {s.stats.rejected ?? 0}. Kazanç garantisi
        yoktur; her işlem risk kapısından geçer.
      </p>
    </section>
  );
}
