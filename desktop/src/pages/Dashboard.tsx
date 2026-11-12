import { Activity, Briefcase, Gauge, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { usePoll } from "../api/hooks";
import type { ExecutionPositionInfo, OpportunitySummary, StatusResponse } from "../api/types.gen";
import { BotPanel } from "../components/BotPanel";
import { GettingStarted } from "../components/GettingStarted";
import { Badge, Card, DataTable, Disclaimer, ErrorBox } from "../components/ui";
import { duration, MARKET_LABELS, MODE_LABELS, num, pct, price, STATE_LABELS } from "../lib/format";
import { useNavigate } from "../lib/nav";

export function stateTone(state?: string): "ok" | "warn" | "bad" | "neutral" {
  if (state === "running") return "ok";
  if (state === "safe_mode" || state === "starting") return "warn";
  if (state === "halted") return "bad";
  return "neutral";
}

/** Motorun hazırlık koşullarının anlaşılır adları (kod adı ipucunda kalır). */
const CONDITION_LABELS: Record<string, string> = {
  "market_data.spot": "Spot piyasa verisi",
  "market_data.usdm_futures": "Futures piyasa verisi",
  "risk.daily_loss": "Günlük zarar sınırı",
  "live.risk.daily_loss": "Günlük zarar sınırı (gerçek hesap)",
  "license.valid": "Lisans",
};

function Kpi({ icon, label, value, hint, tone, testId }: { icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode; tone?: string; testId?: string }) {
  return (
    <div className={`kpi ${tone ?? ""}`} data-testid={testId}>
      <span className="kpi-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

/** Kontrol paneli: hesap, bot, açık pozisyonlar ve en iyi fırsatlar. Teknik ayrıntılar en altta. */
export function Dashboard() {
  const navigate = useNavigate();
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 2000);
  const risk = usePoll((c) => c.get<Record<string, unknown>>("/v1/risk/status"), 5000);
  const positions = usePoll((c) => c.get<ExecutionPositionInfo[]>("/v1/execution/positions"), 5000);
  const opportunities = usePoll((c) => c.get<OpportunitySummary[]>("/v1/opportunities", { limit: 6, min_score: 50 }), 15000);

  const s = status.data;
  const account = (risk.data?.account ?? null) as Record<string, unknown> | null;
  const live = s?.trading_mode === "live";
  const open = (positions.data ?? []).filter((p) => Number(p.quantity) !== 0);

  return (
    <div className="page" data-testid="page-dashboard">
      <ErrorBox error={status.error} what="Motor" />
      <GettingStarted mode={s?.trading_mode} />
      <div className="kpis">
        <Kpi
          icon={<Wallet size={18} />}
          label="Hesap"
          tone={live ? "live" : undefined}
          value={<span data-testid="trading-mode">{MODE_LABELS[s?.trading_mode ?? ""] ?? "—"}</span>}
          hint={s?.can_open_positions ? "Yeni işlem açılabilir" : "Şu an yeni işlem açılamaz"}
        />
        <Kpi
          icon={<Activity size={18} />}
          label="Özsermaye"
          value={account ? `${price(account.equity as string)} USDT` : "—"}
          hint={account ? (account.halted ? "Günlük zarar sınırı doldu; gün kilitli" : "Binance hesabı") : "Binance anahtarı bağlı değil"}
          tone={account?.halted ? "down" : undefined}
        />
        <Kpi
          icon={<Gauge size={18} />}
          label="Günlük zarar"
          value={account ? pct(account.daily_loss_pct as number, 2, false) : "—"}
          hint="Sınır aşılınca bot o gün durur"
        />
        <Kpi icon={<Briefcase size={18} />} label="Açık pozisyon" value={open.length} hint={open.length ? "Ayrıntı: İşlemler" : "Pozisyon yok"} />
      </div>

      <BotPanel />

      <div className="grid-2">
        <Card title="Açık pozisyonlar" actions={<button type="button" className="ghost" onClick={() => navigate("trading")}>Tümü</button>}>
          <DataTable
            rows={open}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            empty="Açık pozisyon yok. Bot uygun sinyalde risk kapısından geçerek açar."
            columns={[
              { key: "s", label: "Coin", render: (r) => <b>{r.symbol}</b> },
              { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
              {
                key: "d",
                label: "Yön",
                render: (r) => <Badge tone={Number(r.quantity) > 0 ? "up" : "down"}>{Number(r.quantity) > 0 ? "Long" : "Short"}</Badge>,
              },
              { key: "e", label: "Giriş", align: "right", render: (r) => price(r.entry_price) },
              { key: "p", label: "Stop", render: (r) => (r.protected ? <Badge tone="ok">Var</Badge> : <Badge tone="bad">Yok</Badge>) },
            ]}
          />
        </Card>
        <Card title="En iyi fırsatlar" actions={<button type="button" className="ghost" onClick={() => navigate("opportunities")}>Tümü</button>}>
          <ErrorBox error={opportunities.error} what="Fırsat taraması" />
          <DataTable
            rows={opportunities.data}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            empty="Tarama sürüyor ya da şu an 50 puan üstü fırsat yok"
            columns={[
              { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
              { key: "market", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] },
              { key: "dir", label: "Yön", render: (r) => <Badge tone={r.direction === "long" ? "up" : "down"}>{r.direction === "long" ? "Long" : "Short"}</Badge> },
              { key: "score", label: "Puan", align: "right", render: (r) => <b>{num(r.score, 0)}</b> },
              { key: "rr", label: "Ödül/Risk", align: "right", render: (r) => num(r.reward_risk, 2) },
            ]}
          />
        </Card>
      </div>

      <details className="card system-details" open={s ? s.engine_state !== "running" : false}>
        <summary>
          Sistem durumu · <Badge tone={stateTone(s?.engine_state)} testId="engine-state">{STATE_LABELS[s?.engine_state ?? ""] ?? "—"}</Badge>
          <span className="muted small"> · çalışma {duration(s?.uptime_s)} · gecikme {num(s?.loop_lag.p99_ms, 1)} ms · sürüm {s?.version ?? "—"}</span>
        </summary>
        <div className="card-body">
          {s && s.engine_state !== "running" && <p className="muted small">{s.state_reason}</p>}
          <ul className="conditions" data-testid="conditions">
            {(s?.readiness ?? [])
              // Gerçek parada deneme hesabının, denemede gerçek hesabın koşulu gösterilmez.
              .filter((c) => (live ? c.name !== "risk.daily_loss" : !c.name.startsWith("live.")))
              .map((c) => (
              <li key={c.name}>
                <Badge tone={c.ready ? "ok" : "warn"}>{c.ready ? "Hazır" : "Bekliyor"}</Badge>{" "}
                <b title={c.name}>{CONDITION_LABELS[c.name] ?? c.name}</b> <span className="muted">{c.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      </details>
      <Disclaimer />
    </div>
  );
}
