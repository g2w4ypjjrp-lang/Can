import {
  Activity,
  BarChart3,
  CandlestickChart,
  ChevronDown,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  type LucideIcon,
  Settings as SettingsIcon,
  ShieldAlert,
  Smartphone,
  Sparkles,
  Trophy,
  Waves,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useEvents, usePoll } from "./api/hooks";
import type { LicenseStatusResponse, StatusResponse } from "./api/types.gen";
import { ErrorBoundary, useGlobalErrorReports } from "./components/ErrorBoundary";
import { KillSwitchControl } from "./components/KillSwitchControl";
import { Splash } from "./components/Splash";
import { Badge } from "./components/ui";
import { UpdateBanner } from "./components/UpdateBanner";
import { MODE_LABELS, STATE_LABELS } from "./lib/format";
import { NavContext } from "./lib/nav";
import { Analysis } from "./pages/Analysis";
import { Dashboard, stateTone } from "./pages/Dashboard";
import { Markets } from "./pages/Markets";
import { Opportunities } from "./pages/Opportunities";
import { Lab } from "./pages/Lab";
import { LicenseGate } from "./pages/LicenseGate";
import { Performance } from "./pages/Performance";
import { Phone, phoneSummary, type RemoteStatus } from "./pages/Phone";
import { Risk } from "./pages/Risk";
import { Settings } from "./pages/Settings";
import { Strategies } from "./pages/Strategies";
import { Trading } from "./pages/Trading";
import { Whales } from "./pages/Whales";

interface PageDef {
  key: string;
  label: string;
  hint: string;
  group: string;
  icon: LucideIcon;
  render: () => ReactNode;
}

export const PAGES: PageDef[] = [
  { key: "dashboard", label: "Kontrol paneli", hint: "Bot, hesabınız ve açık işlemler", group: "Ana", icon: LayoutDashboard, render: () => <Dashboard /> },
  { key: "trading", label: "İşlemler", hint: "Pozisyonlar, emirler ve bot ayarları", group: "Ana", icon: BarChart3, render: () => <Trading /> },
  { key: "opportunities", label: "Fırsatlar", hint: "Botun puanladığı coinler ve gerekçeleri", group: "Ana", icon: Sparkles, render: () => <Opportunities /> },
  { key: "markets", label: "Piyasa", hint: "Tüm coinlerin canlı fiyatı ve hacmi", group: "Ana", icon: Activity, render: () => <Markets /> },
  { key: "performance", label: "Kâr/zarar ve geçmiş", hint: "Sonuçlar ve işlem geçmişi", group: "Gelişmiş", icon: Trophy, render: () => <Performance /> },
  { key: "analysis", label: "Grafik ve AI analiz", hint: "Mum grafikleri, göstergeler ve model tahminleri", group: "Gelişmiş", icon: CandlestickChart, render: () => <Analysis /> },
  { key: "whales", label: "Balina radarı", hint: "Büyük işlemler ve zincir üstü hareketler", group: "Gelişmiş", icon: Waves, render: () => <Whales /> },
  { key: "risk", label: "Risk", hint: "Sınırlar, risk kapısı kararları ve olaylar", group: "Gelişmiş", icon: ShieldAlert, render: () => <Risk /> },
  { key: "strategies", label: "Strateji performansı", hint: "Stratejilerin sanal yarışma sonuçları", group: "Gelişmiş", icon: Gauge, render: () => <Strategies /> },
  { key: "lab", label: "Backtest ve eğitim", hint: "Geçmiş veri, geriye dönük test ve model eğitimi", group: "Gelişmiş", icon: FlaskConical, render: () => <Lab /> },
  { key: "phone", label: "Telefon", hint: "QR'ı telefonun kamerasıyla okutun; her yerden izleyin", group: "Sistem", icon: Smartphone, render: () => <Phone /> },
  { key: "settings", label: "Ayarlar", hint: "İşlem modu, Binance anahtarları, lisans", group: "Sistem", icon: SettingsIcon, render: () => <Settings /> },
];

/** Katlanabilir grup (varsayılan kapalı; açık sayfa içindeyse açık). */
const COLLAPSIBLE = "Gelişmiş";

const GROUPS = [...new Set(PAGES.map((p) => p.group))];

function currentPage(): string {
  const key = new URLSearchParams(window.location.search).get("page");
  return PAGES.some((p) => p.key === key) ? (key as string) : "dashboard";
}

function LogoMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="22" height="22" focusable="false">
        <path d="M7 22l6-7 4 4 8-10" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="25" cy="9" r="2.1" fill="#fff" />
      </svg>
    </span>
  );
}

export function App() {
  const [page, setPage] = useState(currentPage);
  const [advanced, setAdvanced] = useState(() => PAGES.find((p) => p.key === currentPage())?.group === COLLAPSIBLE);
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const remote = usePoll((c) => c.get<RemoteStatus>("/v1/remote/status"), 5000);
  const license = usePoll((c) => c.get<LicenseStatusResponse>("/v1/license"), 10_000);
  const { connected, toasts, dismiss } = useEvents();
  useGlobalErrorReports();
  const [splashDone, setSplashDone] = useState(false);
  const finishSplash = useCallback(() => setSplashDone(true), []);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("page", page);
    window.history.replaceState(null, "", url);
  }, [page]);

  const s = status.data;
  const phone = phoneSummary(remote.data);
  const active = PAGES.find((p) => p.key === page) ?? PAGES[0]!;
  // Lisans zorunluyken (kurulum paketinde her zaman) geçerli lisans yoksa yalnızca lisans ekranı.
  const marketsReady = (s?.readiness ?? []).filter((c) => c.name.startsWith("market_data."));
  const splash = splashDone ? null : (
    <Splash
      ready={Boolean((s && license.data) || status.error)}
      steps={[
        { label: "İşlem motoru başlatılıyor", done: Boolean(s) },
        { label: "Lisans denetleniyor", done: Boolean(license.data) },
        { label: "Binance piyasa verisi", done: marketsReady.length > 0 && marketsReady.every((c) => c.ready) },
      ]}
      onDone={finishSplash}
    />
  );
  if (license.data?.enforced && !license.data.valid) {
    return (
      <>
        {splash}
        <LicenseGate status={license.data} onChange={license.refresh} />
      </>
    );
  }
  return (
    <>
    {splash}
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <LogoMark />
          <div>
            AI Trading
            <br />
            <span>Intelligence</span>
          </div>
        </div>
        <nav aria-label="Ana menü">
          {GROUPS.map((group) => (
            <div key={group} className="stack" style={{ gap: 2 }}>
              {group === COLLAPSIBLE ? (
                <button
                  type="button"
                  className="nav-group nav-toggle"
                  aria-expanded={advanced}
                  onClick={() => setAdvanced(!advanced)}
                  data-testid="nav-advanced"
                >
                  {group}
                  <ChevronDown size={14} aria-hidden="true" className={advanced ? "open" : ""} />
                </button>
              ) : (
                <div className="nav-group">{group}</div>
              )}
              {PAGES.filter((p) => p.group === group && (group !== COLLAPSIBLE || advanced || p.key === page)).map((p) => {
                const Icon = p.icon;
                return (
                  <button
                    key={p.key}
                    className={p.key === page ? "active" : ""}
                    aria-current={p.key === page ? "page" : undefined}
                    onClick={() => setPage(p.key)}
                    data-testid={`nav-${p.key}`}
                    type="button"
                  >
                    <Icon aria-hidden="true" />
                    {p.label}
                    {p.key === "phone" && phone.tone === "ok" && <span className="nav-badge" aria-label="Telefon bağlı" />}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          {page !== "phone" && (
            <button type="button" className="phone-mini" onClick={() => setPage("phone")} data-testid="phone-mini">
              <Smartphone aria-hidden="true" />
              <span>
                <b>Telefondan kontrol</b>
                <span>{phone.label}</span>
              </span>
            </button>
          )}
          <div className="engine-foot">
            <span className={`dot ${connected ? "is-ok live" : "is-warn"}`} aria-hidden="true" />
            <span>
              Motor {s?.version ?? "—"} · olay akışı {connected ? "bağlı" : "bağlanıyor…"}
            </span>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <h1>{active.label}</h1>
            <p className="topbar-sub">{active.hint}</p>
          </div>
          <div className="row">
            {status.error && <Badge tone="bad">Motora ulaşılamıyor</Badge>}
            {s && (
              <>
                <Badge tone={stateTone(s.engine_state)} testId="top-state">
                  {STATE_LABELS[s.engine_state]}
                </Badge>
                <Badge tone={s.trading_mode === "live" ? "bad" : s.trading_mode === "paper" ? "neutral" : "info"} testId="top-mode">
                  {MODE_LABELS[s.trading_mode]}
                </Badge>
              </>
            )}
            {s && <KillSwitchControl engaged={s.kill_switch.engaged} onChange={status.refresh} />}
            <button
              type="button"
              className={`badge ${phone.tone} top-phone`}
              onClick={() => setPage("phone")}
              title="Telefondan kontrol"
              data-testid="top-phone"
            >
              <Smartphone aria-hidden="true" />
              {phone.short}
            </button>
          </div>
        </header>
        <UpdateBanner />
        <NavContext.Provider value={setPage}>
          <ErrorBoundary key={active.key}>{active.render()}</ErrorBoundary>
        </NavContext.Provider>
      </main>
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`} onClick={() => dismiss(t.id)}>
            <b>{t.title}</b>
            <div>{t.body}</div>
          </div>
        ))}
      </div>
    </div>
    </>
  );
}

