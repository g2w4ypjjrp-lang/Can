import { useMemo, useState } from "react";
import { usePoll } from "../api/hooks";
import type {
  AnalysisSnapshotResponse,
  CandlesResponse,
  LevelsResponse,
  Market,
  ModelInfo,
  PredictionResponse,
  TrendResponse,
} from "../api/types.gen";
import { CandleChart, candlesFromRows, type PriceMark } from "../components/CandleChart";
import { Badge, Card, DataTable, ErrorBox, Field, Stat } from "../components/ui";
import { num, pct, price, time } from "../lib/format";
import { MarketSwitch } from "./Markets";

const INTERVALS = ["15m", "1h", "4h", "1d"];

export function Analysis() {
  const [market, setMarket] = useState<Market>("usdm_futures");
  const [symbolInput, setSymbolInput] = useState("BTCUSDT");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setTimeframe] = useState("1h");
  const deps = [market, symbol, interval];
  const candles = usePoll((c) => c.get<CandlesResponse>("/v1/history/candles", { symbol, market, interval, bars: 400 }), 60000, deps);
  const levels = usePoll((c) => c.get<LevelsResponse>("/v1/history/levels", { symbol, market, interval }), 60000, deps);
  const trend = usePoll((c) => c.get<TrendResponse>("/v1/history/trend", { symbol, market, interval }), 60000, deps);
  const snapshot = usePoll((c) => c.get<AnalysisSnapshotResponse>("/v1/analysis/snapshot", { symbol, market, interval }), 60000, deps);
  const models = usePoll((c) => c.get<ModelInfo[]>("/v1/analysis/models"), 0);
  const model = useMemo(
    () => models.data?.find((m) => m.market === market && m.interval === interval && m.symbols.includes(symbol)),
    [models.data, market, interval, symbol],
  );
  const prediction = usePoll(
    (c) => (model ? c.get<PredictionResponse>("/v1/analysis/predict", { model_id: model.id, symbol }) : Promise.resolve(undefined)),
    60000,
    [model?.id, symbol],
  );

  const data = useMemo(() => (candles.data ? candlesFromRows(candles.data.columns, candles.data.rows) : []), [candles.data]);
  const marks = useMemo<PriceMark[]>(() => {
    const result: PriceMark[] = [];
    for (const level of (levels.data?.levels ?? []).slice(0, 6)) {
      result.push({
        price: level.price,
        title: level.kind === "support" ? "Destek" : "Direnç",
        color: level.kind === "support" ? "#16c784" : "#ea3943",
        dashed: true,
      });
    }
    for (const line of trend.data?.active ?? []) {
      result.push({ price: line.value_now, title: line.kind === "support" ? "Trend desteği" : "Trend direnci", color: "#f0b90b" });
    }
    return result;
  }, [levels.data, trend.data]);

  const indicators = snapshot.data?.indicators ?? {};
  return (
    <div className="page" data-testid="page-analysis">
      <div className="toolbar">
        <MarketSwitch value={market} onChange={setMarket} />
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            setSymbol(symbolInput.trim().toUpperCase());
          }}
        >
          <input value={symbolInput} onChange={(e) => setSymbolInput(e.target.value)} className="search" data-testid="analysis-symbol" />
          <button type="submit">Göster</button>
        </form>
        <Field label="Aralık">
          <select value={interval} onChange={(e) => setTimeframe(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </Field>
      </div>
      <Card title={`${symbol} · ${interval}`}>
        <ErrorBox error={candles.error} what="Tarihsel veri" />
        {data.length > 0 ? <CandleChart candles={data} marks={marks} /> : !candles.error && <p className="muted">Yükleniyor…</p>}
      </Card>
      <div className="grid-2">
        <Card title="Yapay zekâ tahmini">
          {!model && <p className="muted">Bu sembol ve aralık için eğitilmiş model yok. Backtest ve eğitim ekranından model eğitebilirsiniz.</p>}
          <ErrorBox error={prediction.error} />
          {prediction.data && (
            <div className="stack">
              <div className="stats">
                <Stat label={`${prediction.data.horizon_bars} mum içinde ${prediction.data.side === "long" ? "yükseliş" : "düşüş"} olasılığı`} value={pct(prediction.data.probability * 100, 1, false)} />
                <Stat label="Taban oran" value={prediction.data.base_rate == null ? "—" : pct(prediction.data.base_rate * 100, 1, false)} />
                <Stat label="Örnek dışı AUC" value={num(prediction.data.oos_auc, 3)} />
              </div>
              <p className="disclaimer">{prediction.data.disclaimer}</p>
            </div>
          )}
        </Card>
        <Card title="Göstergeler">
          <ErrorBox error={snapshot.error} />
          {snapshot.data && (
            <>
              <p className="muted small">Mum: {time(snapshot.data.bar_open_time_ms)}</p>
              <DataTable
                rows={Object.entries(indicators)}
                rowKey={([k]) => k}
                columns={[
                  { key: "k", label: "Gösterge", render: ([k]) => <code>{k}</code> },
                  {
                    key: "v",
                    label: "Değer",
                    align: "right",
                    render: ([, v]) => (typeof v === "number" ? num(v, 4) : typeof v === "object" ? JSON.stringify(v) : String(v)),
                  },
                ]}
              />
            </>
          )}
        </Card>
      </div>
      <Card title="Destek / direnç seviyeleri">
        <ErrorBox error={levels.error} />
        <DataTable
          rows={levels.data?.levels}
          rowKey={(r) => `${r.kind}-${r.price}`}
          empty="Seviye yok"
          columns={[
            { key: "k", label: "Tür", render: (r) => <Badge tone={r.kind === "support" ? "up" : "down"}>{r.kind === "support" ? "Destek" : "Direnç"}</Badge> },
            { key: "p", label: "Fiyat", align: "right", render: (r) => price(r.price) },
            { key: "d", label: "Uzaklık", align: "right", render: (r) => pct(r.distance_pct) },
            { key: "t", label: "Temas", align: "right", render: (r) => num(r.touches, 0) },
            { key: "s", label: "Güç", align: "right", render: (r) => num(r.strength, 2) },
          ]}
        />
      </Card>
    </div>
  );
}
