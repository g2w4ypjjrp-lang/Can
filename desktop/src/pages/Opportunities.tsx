import { useState } from "react";
import { usePoll } from "../api/hooks";
import type { Market, OpportunityDetail, OpportunityStatsResponse, OpportunitySummary } from "../api/types.gen";
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
  const stats = usePoll((c) => c.get<OpportunityStatsResponse>("/v1/opportunities/stats"), 5000);
  const warming = Object.entries(stats.data?.warmup_total ?? {}).filter(
    ([m, total]) => (stats.data?.warmup_symbols[m] ?? 0) < total,
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
      {warming.length > 0 && (
        <div className="notice" role="status" data-testid="warmup-progress">
          <b>Fırsat taraması hazırlanıyor</b> (büyük coinler önce):{" "}
          {warming.map(([m, total]) => {
            const done = stats.data?.warmup_symbols[m] ?? 0;
            return (
              <span key={m} className="warmup-item">
                {MARKET_LABELS[m] ?? m} {done} / {total}
                <progress max={total} value={done} aria-label={`${MARKET_LABELS[m] ?? m} hazırlık`} />
              </span>
            );
          })}
        </div>
      )}
      <div className="grid-main">
        <Card title="Fırsatlar (açıklanabilir 0-100 puan)">
          <DataTable
            testId="opportunities"
            rows={list.data}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            onRowClick={setSelected}
            initialSort={{ key: "score", desc: true }}
            empty={
              warming.length > 0
                ? "Tarama sürüyor; ilk fırsatlar birkaç dakika içinde görünür"
                : `Şu an ${minScore} puan üstü fırsat yok. Puanlar her saat başı yenilenir; daha fazlası için "En düşük puan"ı düşürün.`
            }
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
              {detail.data.market_context && <MarketContextView ctx={detail.data.market_context} />}
              {(detail.data.patterns ?? []).length > 0 && (
                <>
                  <h4>Formasyonlar (bu mum)</h4>
                  <ul className="reasons" data-testid="opportunity-patterns">
                    {(detail.data.patterns ?? []).map((p, i) => (
                      <li key={`${String(p.key)}-${i}`} className={p.direction === "short" ? "down" : undefined}>
                        <b>{String(p.title)}</b> <span className="muted">{String(p.reason)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
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

const REGIME_TONE: Record<string, "ok" | "warn" | "bad" | "neutral" | "info"> = {
  trend: "ok",
  range: "info",
  volatile: "bad",
  mixed: "neutral",
};

/** Piyasa rejimi ve üst zaman dilimi trendi (puanın bağlamı). */
function MarketContextView({ ctx }: { ctx: Record<string, unknown> }) {
  const regime = String(ctx.regime ?? "mixed");
  const htf = typeof ctx.htf_trend === "number" ? ctx.htf_trend : null;
  const adx = typeof ctx.adx === "number" ? ctx.adx : null;
  return (
    <>
      <h4>Piyasa bağlamı</h4>
      <div className="row" data-testid="opportunity-context">
        <Badge tone={REGIME_TONE[regime] ?? "neutral"}>{String(ctx.regime_title ?? regime)} piyasa</Badge>
        <span className="muted small">
          {adx !== null ? `ADX ${num(adx, 0)}` : "ADX ısınıyor"} · verimlilik {num(Number(ctx.efficiency ?? 0), 2)} · oynaklık sırası %
          {num(Number(ctx.vol_rank ?? 0) * 100, 0)}
        </span>
      </div>
      <p className="muted small">
        {String(ctx.htf_label ?? "Üst zaman dilimi")} trend:{" "}
        {htf === null ? "henüz hesaplanmadı" : `${htf > 0 ? "+" : ""}${num(htf, 2)} (${htf > 0.25 ? "yükseliş" : htf < -0.25 ? "düşüş" : "kararsız"})`}
      </p>
    </>
  );
}
