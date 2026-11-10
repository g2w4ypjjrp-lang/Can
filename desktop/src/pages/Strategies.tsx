import { usePoll } from "../api/hooks";
import type { StrategyInfo, StrategyRegistryInfo } from "../api/types.gen";
import { Badge, Card, DataTable, Disclaimer, ErrorBox } from "../components/ui";
import { num, pct, time } from "../lib/format";

const STAGES = ["research", "backtest", "walk_forward", "paper", "live_candidate", "live"];
const STAGE_LABELS: Record<string, string> = {
  research: "Araştırma",
  backtest: "Backtest",
  walk_forward: "Yürüyen pencere",
  paper: "Sanal işlem",
  live_candidate: "Canlı adayı",
  live: "Canlı",
};

const CATEGORY_LABELS: Record<string, string> = {
  trend: "Trend",
  momentum: "Momentum",
  mean_reversion: "Ortalamaya dönüş",
  breakout: "Kırılım",
  pattern: "Formasyon",
  flow: "Akış",
  futures: "Vadeli verisi",
  model: "Model",
};

interface ReliabilityResponse {
  markets: Record<string, Record<string, { multiplier: number; trades: number; avg_r: number | null }>>;
  explanation: string;
}

function metric(m: StrategyRegistryInfo["metrics"], window: string, key: string): number | null {
  const value = m[window]?.[key];
  return typeof value === "number" ? value : null;
}

export function Strategies() {
  const registry = usePoll((c) => c.get<StrategyRegistryInfo[]>("/v1/strategies"), 30000);
  const library = usePoll((c) => c.get<StrategyInfo[]>("/v1/opportunities/strategies"), 0);
  const reliability = usePoll((c) => c.get<ReliabilityResponse>("/v1/opportunities/reliability"), 60_000);
  const weight = (name: string) => {
    const rows = Object.values(reliability.data?.markets ?? {})
      .map((m) => m[name])
      .filter((r) => r !== undefined);
    if (!rows.length) return null;
    return rows.reduce((a, r) => a + r.multiplier, 0) / rows.length;
  };

  return (
    <div className="page" data-testid="page-strategies">
      <div className="notice">
        Terfi hattı: {STAGES.map((s) => STAGE_LABELS[s]).join(" → ")}. <b>Canlı</b> aşamaya otomatik geçiş yoktur; açık
        onayınız gerekir.
      </div>
      <Card title="Strateji kayıt defteri ve performans">
        <ErrorBox error={registry.error} what="Strateji kayıt defteri" />
        <DataTable
          testId="strategies"
          rows={registry.data}
          rowKey={(r) => r.id}
          columns={[
            { key: "n", label: "Strateji", render: (r) => <b>{r.title || r.name}</b>, sort: (r) => r.name },
            { key: "c", label: "Tür", render: (r) => CATEGORY_LABELS[r.category] ?? r.category },
            {
              key: "st",
              label: "Aşama",
              render: (r) => <Badge tone={r.stage === "live_candidate" ? "ok" : r.stage === "paper" ? "info" : "neutral"}>{STAGE_LABELS[r.stage] ?? r.stage}</Badge>,
              sort: (r) => STAGES.indexOf(r.stage),
            },
            { key: "pf", label: "PF (sanal)", align: "right", render: (r) => num(metric(r.metrics, "paper", "profit_factor"), 2) },
            { key: "wr", label: "Başarı (sanal)", align: "right", render: (r) => { const v = metric(r.metrics, "paper", "win_rate"); return v == null ? "—" : pct(v * 100, 1, false); } },
            { key: "bt", label: "PF (backtest)", align: "right", render: (r) => num(metric(r.metrics, "backtest", "profit_factor"), 2) },
            {
              key: "w",
              label: "Puandaki ağırlık",
              align: "right",
              render: (r) => {
                const w = weight(r.name);
                if (w === null) return "—";
                return <Badge tone={w > 1.05 ? "ok" : w < 0.95 ? "warn" : "neutral"}>×{num(w, 2)}</Badge>;
              },
              sort: (r) => weight(r.name) ?? 1,
            },
            { key: "ch", label: "Aşama tarihi", render: (r) => time(r.stage_changed_at) },
          ]}
        />
        {reliability.data && <p className="muted small">{reliability.data.explanation}</p>}
      </Card>
      <Card title="Strateji kütüphanesi">
        <DataTable
          rows={library.data}
          rowKey={(r) => r.name}
          columns={[
            { key: "n", label: "Ad", render: (r) => <b>{r.name}</b> },
            { key: "c", label: "Tür", render: (r) => CATEGORY_LABELS[r.category] ?? r.category },
            { key: "d", label: "Açıklama", render: (r) => <span className="small">{r.description}</span> },
          ]}
        />
      </Card>
      <Disclaimer />
    </div>
  );
}
