import { useState } from "react";
import { usePoll } from "../api/hooks";
import type { ExecutionOrderInfo, PaperAccountInfo, PaperPositionInfo, PaperTradeInfo } from "../api/types.gen";
import { Badge, Card, DataTable, Disclaimer, ErrorBox, Stat, Tabs } from "../components/ui";
import { MARKET_LABELS, num, pct, price, time, tone, usd } from "../lib/format";

type View = "paper" | "positions" | "trades" | "testnet";

export function Performance() {
  const [view, setView] = useState<View>("paper");
  const board = usePoll((c) => c.get<PaperAccountInfo[]>("/v1/paper/leaderboard"), 15000);
  const positions = usePoll((c) => c.get<PaperPositionInfo[]>("/v1/paper/positions"), 5000);
  const trades = usePoll((c) => c.get<PaperTradeInfo[]>("/v1/paper/trades", { limit: 500 }), 15000);
  const testnet = usePoll((c) => c.get<ExecutionOrderInfo[]>("/v1/execution/orders", { open_only: false }), 10000);

  const totalPnl = (trades.data ?? []).reduce((sum, t) => sum + t.net_pnl, 0);
  const wins = (trades.data ?? []).filter((t) => t.net_pnl > 0).length;
  const unrealized = (positions.data ?? []).reduce((sum, p) => sum + p.unrealized_pnl, 0);

  return (
    <div className="page" data-testid="page-performance">
      <div className="stats">
        <Stat label="Sanal işlem: kapanmış K/Z" value={<span className={tone(totalPnl)}>{usd(totalPnl)}</span>} hint={`${trades.data?.length ?? 0} işlem`} />
        <Stat label="Başarı oranı" value={trades.data?.length ? pct((wins / trades.data.length) * 100, 1, false) : "—"} />
        <Stat label="Açık sanal pozisyon" value={num(positions.data?.length ?? 0, 0)} hint={`gerçekleşmemiş ${usd(unrealized)}`} />
      </div>
      <Tabs
        value={view}
        onChange={setView}
        options={[
          { key: "paper", label: "Strateji yarışması" },
          { key: "positions", label: "Açık sanal pozisyonlar" },
          { key: "trades", label: "İşlem geçmişi" },
          { key: "testnet", label: "Demo Trading emirleri" },
        ]}
      />
      {view === "paper" && (
        <Card title="Strateji başına sanal hesaplar">
          <ErrorBox error={board.error} what="Sanal işlem yarışması" />
          <DataTable
            testId="leaderboard"
            rows={board.data}
            rowKey={(r) => `${r.strategy}-${r.market}`}
            initialSort={{ key: "ret", desc: true }}
            columns={[
              { key: "s", label: "Strateji", render: (r) => <b>{r.strategy}</b>, sort: (r) => r.strategy },
              { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
              { key: "st", label: "Aşama", render: (r) => <Badge>{r.stage ?? "—"}</Badge> },
              { key: "eq", label: "Sermaye", align: "right", render: (r) => usd(r.equity), sort: (r) => r.equity },
              { key: "ret", label: "Getiri", align: "right", render: (r) => <span className={tone(r.total_return_pct)}>{pct(r.total_return_pct)}</span>, sort: (r) => r.total_return_pct },
              { key: "n", label: "İşlem", align: "right", render: (r) => r.trades, sort: (r) => r.trades },
              { key: "wr", label: "Başarı", align: "right", render: (r) => (r.win_rate == null ? "—" : pct(r.win_rate * 100, 1, false)) },
              { key: "pf", label: "PF", align: "right", render: (r) => num(r.profit_factor, 2), sort: (r) => r.profit_factor },
              { key: "sh", label: "Sharpe", align: "right", render: (r) => num(r.sharpe, 2), sort: (r) => r.sharpe },
              { key: "dd", label: "Maks. düşüş", align: "right", render: (r) => pct(r.max_drawdown_pct, 1, false), sort: (r) => r.max_drawdown_pct },
              { key: "d", label: "Gün", align: "right", render: (r) => num(r.days, 1) },
            ]}
          />
        </Card>
      )}
      {view === "positions" && (
        <Card title="Açık sanal pozisyonlar">
          <DataTable
            rows={positions.data}
            rowKey={(r) => `${r.strategy}-${r.market}-${r.symbol}`}
            empty="Açık sanal pozisyon yok"
            columns={[
              { key: "st", label: "Strateji", render: (r) => r.strategy },
              { key: "s", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
              { key: "d", label: "Yön", render: (r) => <Badge tone={r.direction === "long" ? "up" : "down"}>{r.direction}</Badge> },
              { key: "e", label: "Giriş", align: "right", render: (r) => price(r.entry_price) },
              { key: "l", label: "Son", align: "right", render: (r) => price(r.last_price) },
              { key: "sl", label: "Stop", align: "right", render: (r) => price(r.stop) },
              { key: "tp", label: "Hedef", align: "right", render: (r) => price(r.target) },
              { key: "u", label: "K/Z", align: "right", render: (r) => <span className={tone(r.unrealized_pnl)}>{usd(r.unrealized_pnl)}</span>, sort: (r) => r.unrealized_pnl },
              { key: "r", label: "Gerekçe", render: (r) => <span className="muted small">{r.reason}</span> },
            ]}
          />
        </Card>
      )}
      {view === "trades" && (
        <Card title="Kapanmış sanal işlemler">
          <ErrorBox error={trades.error} />
          <DataTable
            testId="paper-trades"
            rows={trades.data}
            rowKey={(r, i) => `${r.strategy}-${r.symbol}-${r.entry_time_ms}-${i}`}
            empty="Henüz kapanmış işlem yok"
            columns={[
              { key: "t", label: "Kapanış", render: (r) => time(r.exit_time_ms), sort: (r) => r.exit_time_ms ?? 0 },
              { key: "st", label: "Strateji", render: (r) => r.strategy },
              { key: "s", label: "Sembol", render: (r) => r.symbol },
              { key: "d", label: "Yön", render: (r) => r.direction },
              { key: "e", label: "Giriş", align: "right", render: (r) => price(r.entry_price) },
              { key: "x", label: "Çıkış", align: "right", render: (r) => price(r.exit_price) },
              { key: "why", label: "Neden", render: (r) => r.exit_reason ?? "—" },
              { key: "rm", label: "R", align: "right", render: (r) => num(r.r_multiple, 2), sort: (r) => r.r_multiple },
              { key: "p", label: "Net K/Z", align: "right", render: (r) => <span className={tone(r.net_pnl)}>{usd(r.net_pnl)}</span>, sort: (r) => r.net_pnl },
            ]}
          />
        </Card>
      )}
      {view === "testnet" && (
        <Card title="Demo Trading emir geçmişi (bu oturum)">
          <ErrorBox error={testnet.error} what="Emir yürütme" />
          <DataTable
            rows={testnet.data}
            rowKey={(r) => r.client_id}
            empty="Kayıt yok"
            columns={[
              { key: "s", label: "Sembol", render: (r) => r.symbol },
              { key: "p", label: "Amaç", render: (r) => r.purpose },
              { key: "side", label: "Yön", render: (r) => r.side },
              { key: "st", label: "Durum", render: (r) => r.status },
              { key: "q", label: "Gerçekleşen", align: "right", render: (r) => num(r.executed_qty, 4) },
              { key: "ap", label: "Ort. fiyat", align: "right", render: (r) => price(r.avg_price) },
              { key: "e", label: "Hata", render: (r) => <span className="muted small">{r.last_error ?? ""}</span> },
            ]}
          />
        </Card>
      )}
      <Disclaimer />
    </div>
  );
}
