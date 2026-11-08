import { useState } from "react";
import { usePoll } from "../api/hooks";
import type { Market, OpportunityDetail, OpportunitySummary } from "../api/types.gen";
import { Badge, Card, DataTable, Disclaimer, ErrorBox, Field, Stat } from "../components/ui";
import { MARKET_LABELS, num, pct, price, time } from "../lib/format";

export function Opportunities() {
  const [minScore, setMinScore] = useState(60);
  const [market, setMarket] = useState<Market | "">("");
  const [selected, setSelected] = useState<OpportunitySummary | null>(null);
  const list = usePoll(
    (c) => c.get<OpportunitySummary[]>("/v1/opportunities", { min_score: minScore, market: market || undefined, limit: 200 }),
    10000,
    [minScore, market],
  );
  const detail = usePoll(
    (c) =>
      selected
        ? c.get<OpportunityDetail>("/v1/opportunities/detail", { symbol: selected.symbol, market: selected.market })
        : Promise.resolve(undefined),
    0,
    [selected?.symbol, selected?.market],
  );

  return (
    <div className="page" data-testid="page-opportunities">
      <div className="toolbar">
        <Field label="En düşük puan">
          <input type="number" min={0} max={100} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} />
        </Field>
        <Field label="Piyasa">
          <select value={market} onChange={(e) => setMarket(e.target.value as Market | "")}>
            <option value="">Tümü</option>
            <option value="spot">Spot</option>
            <option value="usdm_futures">Futures</option>
          </select>
        </Field>
      </div>
      <ErrorBox error={list.error} what="Fırsat motoru" />
      <div className="grid-main">
        <Card title="Fırsatlar (açıklanabilir 0-100 puan)">
          <DataTable
            testId="opportunities"
            rows={list.data}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            onRowClick={setSelected}
            initialSort={{ key: "score", desc: true }}
            empty="Eşik üstü fırsat yok"
            columns={[
              { key: "symbol", label: "Sembol", render: (r) => <b>{r.symbol}</b>, sort: (r) => r.symbol },
              { key: "market", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] },
              {
                key: "dir",
                label: "Yön",
                render: (r) => <Badge tone={r.direction === "long" ? "up" : "down"}>{r.direction === "long" ? "Long" : "Short"}</Badge>,
              },
              { key: "score", label: "Puan", align: "right", render: (r) => num(r.score, 0), sort: (r) => r.score },
              { key: "price", label: "Fiyat", align: "right", render: (r) => price(r.price) },
              { key: "stop", label: "Stop", align: "right", render: (r) => price(r.stop_price) },
              { key: "target", label: "Hedef", align: "right", render: (r) => price(r.target_price) },
              { key: "rr", label: "Ödül/Risk", align: "right", render: (r) => num(r.reward_risk, 2), sort: (r) => r.reward_risk ?? null },
              {
                key: "hit",
                label: "Geçmiş isabet",
                align: "right",
                render: (r) => (r.historical_hit_rate == null ? "—" : pct(r.historical_hit_rate * 100, 0, false)),
              },
            ]}
          />
        </Card>
        <Card title={selected ? `${selected.symbol} — neden?` : "Ayrıntı"} testId="opportunity-detail">
          {!selected && <p className="muted">Gerekçeleri görmek için bir satır seçin.</p>}
          <ErrorBox error={detail.error} />
          {selected && detail.data && (
            <div className="stack">
              <div className="stats">
                <Stat label="Puan" value={num(detail.data.score, 0)} hint={`ham ${num(detail.data.raw_score, 0)}`} />
                <Stat
                  label="Maliyet"
                  value={pct(detail.data.cost.total_pct, 3, false)}
                  hint={detail.data.cost.estimated ? "gidiş-dönüş (tahmini)" : "gidiş-dönüş"}
                />
                <Stat label="Mum" value={detail.data.interval} hint={time(detail.data.bar_open_time_ms)} />
              </div>
              <h4>Bileşenler</h4>
              <ul className="reasons">
                {detail.data.components
                  .filter((c) => c.available)
                  .map((c) => (
                    <li key={c.key}>
                      <b>+{num(c.points, 1)}</b> {c.title} <span className="muted">{c.detail}</span>
                    </li>
                  ))}
                {detail.data.penalties.map((p) => (
                  <li key={p.key} className="down">
                    <b>−{num(Math.abs(p.points), 1)}</b> {p.title} <span className="muted">{p.detail}</span>
                  </li>
                ))}
              </ul>
              {detail.data.notes.length > 0 && (
                <ul className="muted small">
                  {detail.data.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              <p className="disclaimer">{detail.data.disclaimer}</p>
            </div>
          )}
        </Card>
      </div>
      <Disclaimer />
    </div>
  );
}
