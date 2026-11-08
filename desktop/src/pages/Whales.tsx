import { useState } from "react";
import { usePoll } from "../api/hooks";
import type { Market, PositioningInfo, WhaleAlertInfo, WhaleSummaryResponse, WhaleTradeInfo } from "../api/types.gen";
import { Badge, Card, DataTable, ErrorBox, Stat } from "../components/ui";
import { compact, MARKET_LABELS, num, pct, price, time, tone, usd } from "../lib/format";
import { MarketSwitch } from "./Markets";

export function Whales() {
  const [market, setMarket] = useState<Market>("usdm_futures");
  const summary = usePoll((c) => c.get<WhaleSummaryResponse>("/v1/whales/summary", { market, window_s: 3600, limit: 20 }), 10000, [market]);
  const trades = usePoll((c) => c.get<WhaleTradeInfo[]>("/v1/whales/trades", { market, limit: 100 }), 5000, [market]);
  const alerts = usePoll((c) => c.get<WhaleAlertInfo[]>("/v1/whales/alerts", { limit: 50 }), 5000);
  const positioning = usePoll((c) => c.get<PositioningInfo[]>("/v1/whales/positioning"), 60000);

  const stats = summary.data?.stats;
  return (
    <div className="page" data-testid="page-whales">
      <div className="toolbar">
        <MarketSwitch value={market} onChange={setMarket} />
        <span className="muted">Kaynak: Binance herkese açık işlem ve emir defteri verisi</span>
      </div>
      <ErrorBox error={summary.error} what="Balina radarı" />
      <div className="stats">
        <Stat label="Balina işlemi" value={num(stats?.whale_trades, 0)} />
        <Stat label="Uyarı" value={num(stats?.alerts, 0)} />
        <Stat label="İzlenen emir" value={compact(stats?.orders_seen)} />
        <Stat label="Zincir üstü veri" value={stats?.onchain_enabled ? "Açık" : "Kapalı"} hint={stats?.onchain_enabled ? undefined : "Ücretli sağlayıcı onayı (G4) gerekir"} />
      </div>
      <div className="grid-2">
        <Card title="Son 1 saat: sembol başına net akış">
          <DataTable
            rows={summary.data?.rows}
            rowKey={(r) => r.symbol}
            initialSort={{ key: "net", desc: true }}
            empty="Henüz balina işlemi yok"
            columns={[
              { key: "s", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
              { key: "buy", label: "Alım", align: "right", render: (r) => usd(r.buy_usd, 0) },
              { key: "sell", label: "Satım", align: "right", render: (r) => usd(r.sell_usd, 0) },
              { key: "net", label: "Net", align: "right", render: (r) => <span className={tone(r.net_usd)}>{usd(r.net_usd, 0)}</span>, sort: (r) => r.net_usd },
              { key: "max", label: "En büyük", align: "right", render: (r) => usd(r.largest_usd, 0) },
            ]}
          />
        </Card>
        <Card title="Uyarılar">
          <ErrorBox error={alerts.error} />
          <DataTable
            rows={alerts.data}
            rowKey={(r, i) => `${r.ts_ms}-${i}`}
            empty="Uyarı yok"
            columns={[
              { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
              { key: "k", label: "Tür", render: (r) => <Badge tone={r.severity === "critical" ? "bad" : r.severity === "warning" ? "warn" : "info"}>{r.kind}</Badge> },
              { key: "m", label: "Açıklama", render: (r) => r.message },
            ]}
          />
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Büyük işlemler">
          <DataTable
            rows={trades.data}
            rowKey={(r, i) => `${r.time_ms}-${r.symbol}-${i}`}
            empty="Kayıt yok"
            columns={[
              { key: "t", label: "Zaman", render: (r) => time(r.time_ms) },
              { key: "s", label: "Sembol", render: (r) => r.symbol },
              { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] },
              { key: "side", label: "Yön", render: (r) => <Badge tone={r.side === "buy" ? "up" : "down"}>{r.side === "buy" ? "Alım" : "Satım"}</Badge> },
              { key: "n", label: "Tutar", align: "right", render: (r) => usd(r.notional, 0) },
              { key: "p", label: "Fiyat", align: "right", render: (r) => price(r.avg_price) },
            ]}
          />
        </Card>
        <Card title="Büyük hesapların konumlanması (Futures)">
          <ErrorBox error={positioning.error} />
          <DataTable
            rows={positioning.data}
            rowKey={(r) => r.symbol}
            empty="Veri yok"
            columns={[
              { key: "s", label: "Sembol", render: (r) => r.symbol },
              { key: "top", label: "Büyükler long", align: "right", render: (r) => pct(r.top_long_pct, 1, false) },
              { key: "all", label: "Genel long", align: "right", render: (r) => pct(r.global_long_pct, 1, false) },
              { key: "oi", label: "Açık pozisyon Δ", align: "right", render: (r) => <span className={tone(r.open_interest_change_pct)}>{pct(r.open_interest_change_pct)}</span> },
              { key: "d", label: "Ayrışma", render: (r) => (r.divergence ? <Badge tone="warn">Var</Badge> : "—") },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
