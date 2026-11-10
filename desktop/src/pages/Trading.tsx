import { type FormEvent, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type {
  ExecutionOrderInfo,
  ExecutionPositionInfo,
  ExecutionTradeResponse,
  Market,
  StatusResponse,
} from "../api/types.gen";
import { Badge, Card, Confirm, DataTable, ErrorBox, Field } from "../components/ui";
import { MARKET_LABELS, num, price, toNumber, tone } from "../lib/format";

interface ExecutionStatus {
  trading_mode: string;
  live_locked: boolean;
  markets: Record<
    string,
    { key_stored: boolean; connected: boolean; error: string | null; stream_connected?: boolean; open_positions?: number }
  >;
}

const PURPOSE_LABELS: Record<string, string> = {
  entry: "Giriş",
  stop_loss: "Zarar durdur",
  take_profit: "Hedef",
  trailing_stop: "İz süren stop",
  exit: "Çıkış",
  emergency_close: "Acil kapatma",
};

export function Trading() {
  const status = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status"), 3000);
  const engine = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const positions = usePoll((c) => c.get<ExecutionPositionInfo[]>("/v1/execution/positions"), 2000);
  const orders = usePoll((c) => c.get<ExecutionOrderInfo[]>("/v1/execution/orders"), 2000);
  const [closing, setClosing] = useState<ExecutionPositionInfo | null>(null);
  const [closeAll, setCloseAll] = useState(false);
  const close = useAction((c, p: ExecutionPositionInfo) =>
    c.post("/v1/execution/close", { market: p.market, symbol: p.symbol, reason: "kullanıcı" }),
  );
  const closeEverything = useAction((c) => c.post("/v1/execution/close-all", undefined, { reason: "kullanıcı: tümünü kapat" }));

  const refreshAll = async () => {
    await Promise.all([positions.refresh(), orders.refresh(), status.refresh()]);
  };
  const markets = status.data?.markets ?? {};
  const testnetMode = engine.data?.trading_mode === "testnet";

  return (
    <div className="page" data-testid="page-trading">
      <div className="notice">
        <b>Binance Demo Trading (sahte bakiye, gerçek fiyatlar).</b> Gerçek hesapla işlem bu sürümde kilitlidir; açılması için açık onayınız (G1: işlem yetkili ve para
        çekme yetkisi kapalı canlı anahtar, G2: ilk gerçek işlem) gerekir.
      </div>
      <ErrorBox error={status.error} what="Emir yürütme" />
      <div className="stats">
        {Object.entries(markets).map(([m, info]) => (
          <div className="stat" key={m} data-testid={`exec-${m}`}>
            <div className="stat-label">{MARKET_LABELS[m] ?? m}</div>
            <div className="stat-value">
              <Badge tone={info.connected ? (info.stream_connected ? "ok" : "warn") : "neutral"}>
                {info.connected ? (info.stream_connected ? "Bağlı" : "Akış bekleniyor") : info.key_stored ? "Bağlı değil" : "Anahtar yok"}
              </Badge>
            </div>
            <div className="stat-hint">{info.error ?? (info.connected ? `${info.open_positions ?? 0} açık pozisyon` : "Ayarlar → Demo Trading anahtarı")}</div>
          </div>
        ))}
      </div>

      <div className="grid-main">
        <div className="stack">
          <Card
            title="Açık pozisyonlar"
            actions={
              <button className="danger" disabled={!positions.data?.length} onClick={() => setCloseAll(true)} data-testid="close-all">
                Tümünü kapat
              </button>
            }
          >
            <ErrorBox error={positions.error ?? close.error ?? closeEverything.error} />
            <DataTable
              testId="positions"
              rows={positions.data}
              rowKey={(r) => `${r.market}-${r.symbol}`}
              empty="Açık pozisyon yok"
              columns={[
                { key: "s", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
                { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
                {
                  key: "q",
                  label: "Miktar",
                  align: "right",
                  render: (r) => <span className={tone(r.quantity)}>{num(r.quantity, 4)}</span>,
                },
                { key: "e", label: "Giriş", align: "right", render: (r) => price(r.entry_price) },
                { key: "pnl", label: "Gerçekleşen K/Z", align: "right", render: (r) => <span className={tone(r.realized_pnl)}>{num(r.realized_pnl, 2)}</span> },
                { key: "tp", label: "Dolan hedef", align: "right", render: (r) => r.take_profits_filled },
                { key: "pr", label: "Koruma", render: (r) => (r.protected ? <Badge tone="ok">Stop var</Badge> : <Badge tone="bad">Stop yok</Badge>) },
                {
                  key: "a",
                  label: "",
                  render: (r) => (
                    <button onClick={() => setClosing(r)} data-testid={`close-${r.symbol}`}>
                      Kapat
                    </button>
                  ),
                },
              ]}
            />
          </Card>
          <Card title="Açık emirler (borsada)">
            <DataTable
              testId="orders"
              rows={orders.data}
              rowKey={(r) => r.client_id}
              empty="Açık emir yok"
              columns={[
                { key: "s", label: "Sembol", render: (r) => r.symbol },
                { key: "p", label: "Amaç", render: (r) => PURPOSE_LABELS[r.purpose] ?? r.purpose },
                { key: "t", label: "Tür", render: (r) => <code>{r.type}</code> },
                { key: "side", label: "Yön", render: (r) => (r.side === "BUY" ? "Alış" : "Satış") },
                { key: "q", label: "Miktar", align: "right", render: (r) => (r.quantity == null ? "Tümü" : num(r.quantity, 4)) },
                { key: "tr", label: "Tetik / fiyat", align: "right", render: (r) => price(r.trigger_price ?? r.price) },
                { key: "st", label: "Durum", render: (r) => r.status },
              ]}
            />
          </Card>
        </div>
        <TradeForm enabled={testnetMode} markets={markets} onDone={refreshAll} />
      </div>

      <Confirm
        open={closing !== null}
        title={`${closing?.symbol ?? ""} pozisyonunu kapat`}
        danger
        confirmLabel="Piyasa fiyatından kapat"
        onCancel={() => setClosing(null)}
        onConfirm={async () => {
          const target = closing;
          setClosing(null);
          if (target) await close.execute(target);
          await refreshAll();
        }}
      >
        Pozisyon piyasa emriyle kapatılır ve koruma emirleri iptal edilir.
      </Confirm>
      <Confirm
        open={closeAll}
        title="Tüm Demo Trading pozisyonlarını kapat"
        danger
        confirmLabel="Tümünü kapat"
        onCancel={() => setCloseAll(false)}
        onConfirm={async () => {
          setCloseAll(false);
          await closeEverything.execute();
          await refreshAll();
        }}
      >
        Bütün açık pozisyonlar piyasa emriyle kapatılacak.
      </Confirm>
    </div>
  );
}

function TradeForm({
  enabled,
  markets,
  onDone,
}: {
  enabled: boolean;
  markets: ExecutionStatus["markets"];
  onDone: () => Promise<void>;
}) {
  const [market, setMarket] = useState<Market>("usdm_futures");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [direction, setDirection] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [stop, setStop] = useState("");
  const [tp1, setTp1] = useState("");
  const [tp2, setTp2] = useState("");
  const [leverage, setLeverage] = useState("2");
  const [result, setResult] = useState<ExecutionTradeResponse | null>(null);
  const submit = useAction((c, body: unknown) => c.post<ExecutionTradeResponse>("/v1/execution/trades", body));
  const connected = markets[market]?.connected ?? false;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setResult(null);
    const take_profits = [tp1, tp2]
      .filter((v) => toNumber(v) !== null)
      .map((v, _i, all) => ({ price: v, fraction: all.length === 2 ? "0.5" : "1" }));
    const response = await submit.execute({
      market,
      symbol: symbol.trim().toUpperCase(),
      direction,
      quantity,
      reference_price: reference,
      stop_loss: stop || null,
      take_profits,
      leverage: market === "usdm_futures" ? Number(leverage) : null,
      reason: "elle test ağı işlemi (arayüz)",
    });
    if (response) {
      setResult(response);
      await onDone();
    }
  };

  return (
    <Card title="Yeni Demo Trading işlemi" testId="trade-form">
      {!enabled && <div className="notice">İşlem açmak için Ayarlar'dan işlem modunu <b>Demo Trading</b> yapın.</div>}
      {enabled && !connected && <div className="notice">Bu piyasa için Demo Trading anahtarı bağlı değil.</div>}
      <form className="form" onSubmit={onSubmit}>
        <Field label="Piyasa">
          <select value={market} onChange={(e) => setMarket(e.target.value as Market)} data-testid="trade-market">
            <option value="usdm_futures">Futures</option>
            <option value="spot">Spot</option>
          </select>
        </Field>
        <Field label="Sembol">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} data-testid="trade-symbol" />
        </Field>
        <Field label="Yön">
          <select value={direction} onChange={(e) => setDirection(e.target.value as "long" | "short")} data-testid="trade-direction">
            <option value="long">Long (alış)</option>
            {market === "usdm_futures" && <option value="short">Short (açığa satış)</option>}
          </select>
        </Field>
        <Field label="Miktar">
          <input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required data-testid="trade-qty" />
        </Field>
        <Field label="Güncel fiyat" hint="Risk kapısı borsadaki fiyatla karşılaştırır">
          <input inputMode="decimal" value={reference} onChange={(e) => setReference(e.target.value)} required data-testid="trade-ref" />
        </Field>
        <Field label="Zarar durdur (zorunlu)">
          <input inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} data-testid="trade-stop" />
        </Field>
        <Field label="Hedef 1">
          <input inputMode="decimal" value={tp1} onChange={(e) => setTp1(e.target.value)} data-testid="trade-tp1" />
        </Field>
        <Field label="Hedef 2" hint="İki hedef verilirse yarı yarıya; ilk hedefte stop girişe çekilir">
          <input inputMode="decimal" value={tp2} onChange={(e) => setTp2(e.target.value)} data-testid="trade-tp2" />
        </Field>
        {market === "usdm_futures" && (
          <Field label="Kaldıraç">
            <input type="number" min={1} max={20} value={leverage} onChange={(e) => setLeverage(e.target.value)} data-testid="trade-leverage" />
          </Field>
        )}
        <button className="primary" type="submit" disabled={!enabled || !connected || submit.pending} data-testid="trade-submit">
          {submit.pending ? "Gönderiliyor…" : "Risk kapısından geçir ve aç"}
        </button>
      </form>
      <ErrorBox error={submit.error} />
      {result && (
        <div className="ok" data-testid="trade-result">
          Durum: <b>{result.state}</b> · dolan {num(result.filled_qty, 4)} · {result.protection_orders} koruma emri
          {result.error ? ` · ${result.error}` : ""}
        </div>
      )}
    </Card>
  );
}
