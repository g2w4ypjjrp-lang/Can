import { type ReactNode, useEffect, useState } from "react";
import { useEvents, usePoll } from "./api/hooks";
import type { StatusResponse } from "./api/types.gen";
import { Badge } from "./components/ui";
import { MODE_LABELS, STATE_LABELS } from "./lib/format";
import { Analysis } from "./pages/Analysis";
import { Dashboard, stateTone } from "./pages/Dashboard";
import { Markets } from "./pages/Markets";
import { Opportunities } from "./pages/Opportunities";
import { Performance } from "./pages/Performance";
import { Risk } from "./pages/Risk";
import { Settings } from "./pages/Settings";
import { Strategies } from "./pages/Strategies";
import { Trading } from "./pages/Trading";
import { Whales } from "./pages/Whales";

export const PAGES: { key: string; label: string; render: () => ReactNode }[] = [
  { key: "dashboard", label: "Genel bakış", render: () => <Dashboard /> },
  { key: "markets", label: "Piyasa", render: () => <Markets /> },
  { key: "opportunities", label: "Fırsatlar", render: () => <Opportunities /> },
  { key: "whales", label: "Balina radarı", render: () => <Whales /> },
  { key: "analysis", label: "Grafik ve AI analiz", render: () => <Analysis /> },
  { key: "trading", label: "Spot / Futures işlemler", render: () => <Trading /> },
  { key: "performance", label: "Kâr/zarar ve geçmiş", render: () => <Performance /> },
  { key: "risk", label: "Risk", render: () => <Risk /> },
  { key: "strategies", label: "Strateji performansı", render: () => <Strategies /> },
  { key: "settings", label: "Ayarlar", render: () => <Settings /> },
];

function currentPage(): string {
  const key = new URLSearchParams(window.location.search).get("page");
  return PAGES.some((p) => p.key === key) ? (key as string) : "dashboard";
}

export function App() {
  const [page, setPage] = useState(currentPage);
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const { connected, toasts, dismiss } = useEvents();

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("page", page);
    window.history.replaceState(null, "", url);
  }, [page]);

  const s = status.data;
  const active = PAGES.find((p) => p.key === page) ?? PAGES[0]!;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          AI Trading
          <br />
          <span>Intelligence</span>
        </div>
        <nav>
          {PAGES.map((p) => (
            <button
              key={p.key}
              className={p.key === page ? "active" : ""}
              onClick={() => setPage(p.key)}
              data-testid={`nav-${p.key}`}
              type="button"
            >
              {p.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot muted small">
          Sürüm {s?.version ?? "—"}
          <br />
          Olay akışı: {connected ? "bağlı" : "bağlanıyor…"}
        </div>
      </aside>
      <main>
        <header className="topbar">
          <h1>{active.label}</h1>
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
          </div>
        </header>
        {active.render()}
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
