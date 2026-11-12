import { History } from "lucide-react";
import { usePoll } from "../api/hooks";
import { MARKET_LABELS, time } from "../lib/format";
import { Badge, Card, DataTable, ErrorBox } from "./ui";

export interface ClosedTrade {
  id: string;
  market: string;
  symbol: string;
  side: "long" | "short";
  entry_price: string;
  exit_price: string | null;
  quantity: string | null;
  notional: string | null;
  net_pnl: string;
  fees: string;
  pnl_pct: number | null;
  source: "bot" | "manual";
  closed_at: number;
  duration_s: number;
}

export interface HistorySummary {
  count: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  net_total: string;
  gross_profit: string;
  gross_loss: string;
  best: string | null;
  worst: string | null;
  today_net: string;
}

interface HistoryResponse {
  environment: "testnet" | "live";
  trades: ClosedTrade[];
  summary: HistorySummary;
}

const money = (v: string | number | null | undefined) => {
  const n = Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
const priceText = (v: string | null) => (v === null ? "—" : Number(v).toLocaleString("tr-TR", { maximumFractionDigits: 6 }));
const tone = (v: string | number | null | undefined) => (Number(v) > 0 ? "up" : Number(v) < 0 ? "down" : "");

function duration(s: number): string {
  if (s < 60) return `${s} sn`;
  if (s < 3600) return `${Math.round(s / 60)} dk`;
  if (s < 86400) return `${Math.floor(s / 3600)} sa ${Math.round((s % 3600) / 60)} dk`;
  return `${Math.floor(s / 86400)} gün`;
}

export function PnlCell({ value, pct }: { value: string | number | null; pct?: number | null }) {
  const t = tone(value);
  return (
    <span className={`pnl ${t}`}>
      <span aria-hidden="true">{t === "up" ? "▲" : t === "down" ? "▼" : "•"}</span> {money(value)} USDT
      {pct !== null && pct !== undefined && (
        <small>
          {" "}
          ({pct > 0 ? "+" : ""}
          {pct.toFixed(2)}%)
        </small>
      )}
    </span>
  );
}

/** Kapanmış işlemler: özet kutuları (bugün, toplam, başarı, en iyi/kötü) ve net kâr/zarar tablosu.
 * ``compact``: ana ekranda son birkaç işlem. */
export function TradeHistory({ compact = false, limit = 200, onMore }: { compact?: boolean; limit?: number; onMore?: () => void }) {
  const data = usePoll((c) => c.get<HistoryResponse>("/v1/execution/history", { limit }), 10_000);
  const h = data.data;
  const s = h?.summary;
  const rows = compact ? h?.trades.slice(0, 5) : h?.trades;
  return (
    <Card
      title={
        <span className="row" style={{ gap: 8 }}>
          <History size={16} aria-hidden="true" /> {compact ? "Son kapanan işlemler" : "İşlem geçmişi"}
          {h && <Badge tone={h.environment === "live" ? "bad" : "info"}>{h.environment === "live" ? "Gerçek hesap" : "Demo"}</Badge>}
        </span>
      }
      testId={compact ? "history-compact" : "history"}
      actions={
        onMore ? (
          <button type="button" className="ghost" onClick={onMore}>
            Tümü
          </button>
        ) : undefined
      }
    >
      <ErrorBox error={data.error} what="İşlem geçmişi" />
      {s && s.count > 0 && (
        <div className="history-stats" data-testid="history-summary">
          <div>
            <span>Bugün</span>
            <b className={tone(s.today_net)}>{money(s.today_net)} USDT</b>
          </div>
          <div>
            <span>Toplam net</span>
            <b className={tone(s.net_total)} data-testid="history-net">
              {money(s.net_total)} USDT
            </b>
          </div>
          <div>
            <span>Başarı</span>
            <b>
              %{s.win_rate ?? 0} <small className="muted">({s.wins}/{s.count})</small>
            </b>
          </div>
          {!compact && (
            <>
              <div>
                <span>Kazanç / kayıp</span>
                <b>
                  <span className="up">{money(s.gross_profit)}</span> / <span className="down">{money(s.gross_loss)}</span>
                </b>
              </div>
              <div>
                <span>En iyi / en kötü</span>
                <b>
                  <span className="up">{money(s.best)}</span> / <span className="down">{money(s.worst)}</span>
                </b>
              </div>
            </>
          )}
        </div>
      )}
      <DataTable
        testId={compact ? "history-compact-rows" : "history-rows"}
        rows={rows}
        rowKey={(r) => r.id}
        empty="Henüz kapanmış işlem yok. Bot ya da siz bir işlemi kapatınca kâr/zararıyla burada görünür."
        columns={[
          { key: "t", label: "Kapanış", render: (r) => time(r.closed_at) },
          { key: "s", label: "Coin", render: (r) => <b>{r.symbol}</b> },
          ...(compact ? [] : [{ key: "m", label: "Piyasa", render: (r: ClosedTrade) => MARKET_LABELS[r.market] ?? r.market }]),
          { key: "d", label: "Yön", render: (r) => <Badge tone={r.side === "long" ? "up" : "down"}>{r.side === "long" ? "Long" : "Short"}</Badge> },
          ...(compact
            ? []
            : [
                { key: "e", label: "Giriş", align: "right" as const, render: (r: ClosedTrade) => priceText(r.entry_price) },
                { key: "x", label: "Çıkış", align: "right" as const, render: (r: ClosedTrade) => priceText(r.exit_price) },
                { key: "dur", label: "Süre", render: (r: ClosedTrade) => duration(r.duration_s) },
                { key: "src", label: "Kaynak", render: (r: ClosedTrade) => (r.source === "bot" ? "Bot" : "Elle") },
              ]),
          {
            key: "pnl",
            label: "Net kâr/zarar",
            align: "right",
            render: (r) => <PnlCell value={r.net_pnl} pct={r.pnl_pct} />,
          },
        ]}
      />
      {!compact && <p className="muted small">Net = gerçekleşen kâr/zarar − komisyon − fonlama. Kazanç garantisi yoktur.</p>}
    </Card>
  );
}
