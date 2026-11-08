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

function metric(m: StrategyRegistryInfo["metrics"], window: string, key: string): number | null {
  const value = m[window]?.[key];
  return typeof value === "number" ? value : null;
}

export function Strategies() {
  const registry = usePoll((c) => c.get<StrategyRegistryInfo[]>("/v1/strategies"), 30000);
  const library = usePoll((c) => c.get<StrategyInfo[]>("/v1/opportunities/strategies"), 0);

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
            { key: "c", label: "Tür", render: (r) => r.category },
            {
              key: "st",
              label: "Aşama",
              render: (r) => <Badge tone={r.stage === "live_candidate" ? "ok" : r.stage === "paper" ? "info" : "neutral"}>{STAGE_LABELS[r.stage] ?? r.stage}</Badge>,
              sort: (r) => STAGES.indexOf(r.stage),
            },
            { key: "pf", label: "PF (sanal)", align: "right", render: (r) => num(metric(r.metrics, "paper", "profit_factor"), 2) },
            { key: "wr", label: "Başarı (sanal)", align: "right", render: (r) => { const v = metric(r.metrics, "paper", "win_rate"); return v == null ? "—" : pct(v * 100, 1, false); } },
            { key: "bt", label: "PF (backtest)", align: "right", render: (r) => num(metric(r.metrics, "backtest", "profit_factor"), 2) },
            { key: "ch", label: "Aşama tarihi", render: (r) => time(r.stage_changed_at) },
          ]}
        />
      </Card>
      <Card title="Strateji kütüphanesi">
        <DataTable
          rows={library.data}
          rowKey={(r) => r.name}
          columns={[
            { key: "n", label: "Ad", render: (r) => <b>{r.name}</b> },
            { key: "c", label: "Tür", render: (r) => r.category },
            { key: "d", label: "Açıklama", render: (r) => <span className="small">{r.description}</span> },
          ]}
        />
      </Card>
      <Disclaimer />
    </div>
  );
}
