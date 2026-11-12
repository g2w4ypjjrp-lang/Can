import { useMemo, useState } from "react";
import { usePoll } from "../api/hooks";
import type { Market, ScannerTopResponse, SignalInfo, StatusResponse, TickersResponse } from "../api/types.gen";
import { LiveChange, LivePrice } from "../components/LivePrice";
import { Badge, Card, DataTable, ErrorBox, Tabs } from "../components/ui";
import { compact, num, pct, price, time, tone } from "../lib/format";

export function MarketSwitch({ value, onChange }: { value: Market; onChange: (m: Market) => void }) {
  return (
    <Tabs
      value={value}
      onChange={onChange}
      testId="market-switch"
      options={[
        { key: "spot", label: "Spot" },
        { key: "usdm_futures", label: "Futures" },
      ]}
    />
  );
}

export function Markets() {
  const [market, setMarket] = useState<Market>("usdm_futures");
  const [query, setQuery] = useState("");
  const tickers = usePoll((c) => c.get<TickersResponse>("/v1/market/tickers", { market, limit: 1000 }), 3000, [market]);
  const movers = usePoll(
    (c) => c.get<ScannerTopResponse>("/v1/scanner/top", { market, limit: 20, sort: "volume_z_60s" }),
    5000,
    [market],
  );
  const signals = usePoll((c) => c.get<SignalInfo[]>("/v1/scanner/signals", { limit: 30 }), 5000);
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 5000);
  const feed = status.data?.readiness.find((r) => r.name === `market_data.${market}`);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const rows = tickers.data?.tickers ?? [];
    return q ? rows.filter((t) => t.symbol.includes(q)) : rows;
  }, [tickers.data, query]);

  return (
    <div className="page" data-testid="page-markets">
      <div className="toolbar">
        <MarketSwitch value={market} onChange={setMarket} />
        <input
          className="search"
          placeholder="Sembol ara (ör. BTC)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="market-search"
        />
        <span className="muted">{tickers.data ? `${filtered.length} / ${tickers.data.count} coin` : ""}</span>
      </div>
      <ErrorBox error={tickers.error} what="Piyasa verisi" />
      {feed && !feed.ready && (
        <p className="notice" role="status" data-testid="feed-notice">
          Binance canlı veri bağlantısı: {feed.detail}. Coin listesi bu sırada dakikada bir yenilenir.
        </p>
      )}
      <div className="grid-main">
        <Card title="Tüm coinler">
          <DataTable
            testId="tickers"
            rows={filtered}
            rowKey={(r) => r.symbol}
            initialSort={{ key: "vol", desc: true }}
            empty="Binance'ten coin listesi alınıyor…"
            columns={[
              { key: "symbol", label: "Sembol", render: (r) => <b>{r.symbol}</b>, sort: (r) => r.symbol },
              { key: "last", label: "Fiyat", align: "right", render: (r) => <LivePrice id={`${market}:${r.symbol}`} fallback={r.last} />, sort: (r) => r.last },
              {
                key: "chg",
                label: "24 sa",
                align: "right",
                render: (r) => <LiveChange id={`${market}:${r.symbol}`} last={r.last} change={r.change_pct} />,
                sort: (r) => r.change_pct,
              },
              { key: "hi", label: "Yüksek", align: "right", render: (r) => price(r.high) },
              { key: "lo", label: "Düşük", align: "right", render: (r) => price(r.low) },
              { key: "vol", label: "Hacim (USDT)", align: "right", render: (r) => compact(r.quote_volume), sort: (r) => r.quote_volume },
              ...(market === "usdm_futures"
                ? [
                    {
                      key: "fund",
                      label: "Fonlama",
                      align: "right" as const,
                      render: (r: (typeof filtered)[number]) => pct((r.funding_rate ?? 0) * 100, 4),
                      sort: (r: (typeof filtered)[number]) => r.funding_rate ?? null,
                    },
                  ]
                : []),
            ]}
          />
        </Card>
        <div className="stack">
          <Card title="Anormal hareketler (60 sn)">
            <ErrorBox error={movers.error} what="Tarayıcı" />
            <DataTable
              rows={movers.data?.rows}
              rowKey={(r) => r.symbol}
              empty="Isınma sürüyor"
              columns={[
                { key: "s", label: "Sembol", render: (r) => r.symbol },
                { key: "vz", label: "Hacim z", align: "right", render: (r) => num(r.volume_z_60s, 1) },
                { key: "c5", label: "5 dk", align: "right", render: (r) => <span className={tone(r.change_5m_pct)}>{pct(r.change_5m_pct)}</span> },
                { key: "imb", label: "Alım/satım", align: "right", render: (r) => num(r.imbalance_60s, 2) },
              ]}
            />
          </Card>
          <Card title="Tarayıcı sinyalleri">
            <DataTable
              rows={signals.data}
              rowKey={(r, i) => `${r.ts_ms}-${r.symbol}-${i}`}
              empty="Sinyal yok"
              columns={[
                { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
                { key: "s", label: "Sembol", render: (r) => r.symbol },
                { key: "k", label: "Tür", render: (r) => <Badge tone={r.severity === "critical" ? "bad" : "info"}>{r.kind}</Badge> },
              ]}
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
