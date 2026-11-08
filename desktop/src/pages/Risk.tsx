import { usePoll } from "../api/hooks";
import type { DecisionInfo, RiskEventInfo } from "../api/types.gen";
import { Badge, Card, DataTable, ErrorBox, Stat } from "../components/ui";
import { MARKET_LABELS, num, pct, price, STATE_LABELS, time } from "../lib/format";

interface RiskStatus {
  engine_state: string;
  limits: Record<string, unknown>;
  gate: Record<string, number>;
  guard: { ts_ms: number; daily_loss_pct: number | null; halted: boolean; actions: string[]; errors: string[] } | null;
  account: {
    day: string;
    equity: string;
    day_start_equity: string;
    daily_loss_pct: number;
    halted: boolean;
    halt_reason: string | null;
    open_positions: number;
  } | null;
  conditions: { name: string; ready: boolean; detail: string }[];
}

const LIMIT_LABELS: Record<string, [string, (v: unknown) => string]> = {
  max_risk_per_trade_pct: ["İşlem başına en fazla risk", (v) => `%${String(v)}`],
  max_daily_loss_pct: ["Günlük zarar sınırı", (v) => `%${String(v)}`],
  max_open_positions: ["En fazla açık pozisyon", (v) => String(v)],
  max_leverage: ["En fazla kaldıraç", (v) => `${String(v)}x`],
  max_total_leverage: ["Toplam pozisyon / özsermaye", (v) => `${String(v)}x`],
  min_liquidation_distance_pct: ["Tasfiyeye en az uzaklık", (v) => `%${String(v)}`],
  max_price_deviation_pct: ["Sinyalden en fazla fiyat sapması", (v) => `%${String(v)}`],
  close_positions_on_daily_loss: ["Günlük sınırda pozisyonları kapat", (v) => (v ? "Evet" : "Hayır (stoplar kalır)")],
};

export function Risk() {
  const status = usePoll((c) => c.get<RiskStatus>("/v1/risk/status"), 3000);
  const events = usePoll((c) => c.get<RiskEventInfo[]>("/v1/risk/events", { limit: 100 }), 5000);
  const decisions = usePoll((c) => c.get<DecisionInfo[]>("/v1/risk/decisions", { limit: 100 }), 5000);
  const s = status.data;

  return (
    <div className="page" data-testid="page-risk">
      <ErrorBox error={status.error} what="Risk yönetimi" />
      <div className="stats">
        <Stat label="Motor" value={STATE_LABELS[s?.engine_state ?? ""] ?? "—"} />
        <Stat
          label="Günlük zarar"
          value={s?.account ? pct(s.account.daily_loss_pct, 2, false) : "—"}
          hint={s?.account?.halted ? (s.account.halt_reason ?? "Gün kilitli") : s?.account ? `Gün ${s.account.day} (UTC)` : "Test ağı bağlı değil"}
          tone={s?.account?.halted ? "down" : undefined}
          testId="risk-daily"
        />
        <Stat label="Özsermaye" value={price(s?.account?.equity)} hint={`gün başı ${price(s?.account?.day_start_equity)}`} />
        <Stat label="Kapı: onay / ret" value={`${s?.gate.approved ?? 0} / ${s?.gate.rejected ?? 0}`} hint={`geçersiz onay denemesi ${s?.gate.verify_failed ?? 0}`} />
      </div>
      <div className="grid-2">
        <Card title="Sınırlar" testId="risk-limits">
          <table>
            <tbody>
              {Object.entries(LIMIT_LABELS).map(([key, [label, fmt]]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td style={{ textAlign: "right" }}>
                    <b>{s ? fmt(s.limits[key]) : "—"}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Sınırlar ayar dosyasından değiştirilir; kodda aşılamayan üst sınırlar vardır.</p>
        </Card>
        <Card title="Hazırlık koşulları">
          <ul className="conditions">
            {(s?.conditions ?? []).map((c) => (
              <li key={c.name}>
                <Badge tone={c.ready ? "ok" : "warn"}>{c.ready ? "Hazır" : "Bekliyor"}</Badge> <code>{c.name}</code>{" "}
                <span className="muted">{c.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Card title="Karar günlüğü — işlem neden açıldı / açılmadı">
        <ErrorBox error={decisions.error} />
        <DataTable
          testId="decisions"
          rows={decisions.data}
          rowKey={(r) => r.id}
          empty="Karar yok"
          columns={[
            { key: "t", label: "Zaman", render: (r) => time(r.created_ms) },
            { key: "s", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
            { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
            { key: "d", label: "Yön", render: (r) => r.direction },
            {
              key: "v",
              label: "Risk kararı",
              render: (r) => <Badge tone={r.risk_verdict === "approved" ? "ok" : r.risk_verdict === "rejected" ? "bad" : "neutral"}>{r.risk_verdict === "approved" ? "Onaylandı" : r.risk_verdict === "rejected" ? "Reddedildi" : "Bekliyor"}</Badge>,
            },
            {
              key: "why",
              label: "Gerekçe",
              render: (r) => (
                <span className="small">
                  {r.risk_reasons.length ? r.risk_reasons.map((x) => String(x.message)).join("; ") : (r.reason ?? "")}
                </span>
              ),
            },
            { key: "risk", label: "Risk %", align: "right", render: (r) => num(r.risk_metrics.trade_risk_pct as number, 3) },
          ]}
        />
      </Card>
      <Card title="Risk olayları">
        <DataTable
          testId="risk-events"
          rows={events.data}
          rowKey={(r) => String(r.id)}
          empty="Olay yok"
          columns={[
            { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
            { key: "r", label: "Kural", render: (r) => <code>{r.rule}</code> },
            { key: "sv", label: "Önem", render: (r) => <Badge tone={r.severity === "critical" ? "bad" : r.severity === "warning" ? "warn" : "info"}>{r.severity}</Badge> },
            { key: "s", label: "Sembol", render: (r) => r.symbol ?? "—" },
            { key: "a", label: "Eylem", render: (r) => r.action },
          ]}
        />
      </Card>
    </div>
  );
}
