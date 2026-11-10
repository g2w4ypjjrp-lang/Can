import {
  Activity,
  BarChart3,
  CandlestickChart,
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
import { type ReactNode, useEffect, useState } from "react";
import { useEvents, usePoll } from "./api/hooks";
import type { LicenseStatusResponse, StatusResponse } from "./api/types.gen";
import { ErrorBoundary, useGlobalErrorReports } from "./components/ErrorBoundary";
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
  { key: "dashboard", label: "Genel bakış", hint: "Motor durumu, acil durdurma, fırsatlar ve uyarılar", group: "Genel", icon: LayoutDashboard, render: () => <Dashboard /> },
  { key: "markets", label: "Piyasa", hint: "Canlı fiyatlar ve hacim", group: "Genel", icon: Activity, render: () => <Markets /> },
  { key: "opportunities", label: "Fırsatlar", hint: "Puanlanmış işlem fırsatları ve gerekçeleri", group: "Genel", icon: Sparkles, render: () => <Opportunities /> },
  { key: "whales", label: "Balina radarı", hint: "Büyük işlemler ve zincir üstü hareketler", group: "Genel", icon: Waves, render: () => <Whales /> },
  { key: "analysis", label: "Grafik ve AI analiz", hint: "Mum grafikleri, göstergeler ve model tahminleri", group: "Genel", icon: CandlestickChart, render: () => <Analysis /> },
  { key: "trading", label: "Spot / Futures işlemler", hint: "Emirler, pozisyonlar ve otomatik işlem", group: "İşlem", icon: BarChart3, render: () => <Trading /> },
  { key: "performance", label: "Kâr/zarar ve geçmiş", hint: "Sonuçlar ve işlem geçmişi", group: "İşlem", icon: Trophy, render: () => <Performance /> },
  { key: "risk", label: "Risk", hint: "Sınırlar, risk kapısı kararları ve olaylar", group: "İşlem", icon: ShieldAlert, render: () => <Risk /> },
  { key: "lab", label: "Backtest ve eğitim", hint: "Geçmiş veri indirme, geriye dönük test ve yapay zekâ modeli eğitimi", group: "İşlem", icon: FlaskConical, render: () => <Lab /> },
  { key: "strategies", label: "Strateji performansı", hint: "Stratejilerin sanal yarışma sonuçları", group: "İşlem", icon: Gauge, render: () => <Strategies /> },
  { key: "phone", label: "Telefon", hint: "QR kodla iPhone eşleştirme ve telefondan kontrol", group: "Sistem", icon: Smartphone, render: () => <Phone /> },
  { key: "settings", label: "Ayarlar", hint: "İşlem modu, borsa anahtarları, lisans ve denetim kaydı", group: "Sistem", icon: SettingsIcon, render: () => <Settings /> },
];

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
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const remote = usePoll((c) => c.get<RemoteStatus>("/v1/remote/status"), 5000);
  const license = usePoll((c) => c.get<LicenseStatusResponse>("/v1/license"), 10_000);
  const { connected, toasts, dismiss } = useEvents();
  useGlobalErrorReports();

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("page", page);
    window.history.replaceState(null, "", url);
  }, [page]);

  const s = status.data;
  const phone = phoneSummary(remote.data);
  const active = PAGES.find((p) => p.key === page) ?? PAGES[0]!;
  // Lisans zorunluyken (kurulum paketinde her zaman) geçerli lisans yoksa yalnızca lisans ekranı.
  if (license.data?.enforced && !license.data.valid) {
    return <LicenseGate status={license.data} onChange={license.refresh} />;
  }
  return (
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
              <div className="nav-group">{group}</div>
              {PAGES.filter((p) => p.group === group).map((p) => {
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
                <Badge tone={s.trading_mode === "paper" ? "neutral" : "info"} testId="top-mode">
                  {MODE_LABELS[s.trading_mode]}
                </Badge>
                {s.kill_switch.engaged && <Badge tone="bad">ACİL DURDURMA</Badge>}
              </>
            )}
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
  );
}

