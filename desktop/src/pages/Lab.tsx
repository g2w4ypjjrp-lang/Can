import { type FormEvent, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type {
  BacktestJobInfo,
  HistoryJobInfo,
  HistoryStatusResponse,
  Market,
  ModelInfo,
  TrainJobInfo,
} from "../api/types.gen";
import { Badge, Card, DataTable, Disclaimer, ErrorBox, Field, Tabs } from "../components/ui";
import { MARKET_LABELS, num, pct, time } from "../lib/format";

const INTERVALS = ["15m", "1h", "4h", "1d"];
const JOB_STATES: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  running: { label: "Çalışıyor", tone: "warn" },
  queued: { label: "Sırada", tone: "neutral" },
  done: { label: "Bitti", tone: "ok" },
  completed: { label: "Bitti", tone: "ok" },
  failed: { label: "Hata", tone: "bad" },
};

function symbolsOf(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

function JobState({ state, error }: { state: string; error?: string | null }) {
  const s = JOB_STATES[state] ?? { label: state, tone: "neutral" as const };
  return (
    <span title={error ?? undefined}>
      <Badge tone={s.tone}>{s.label}</Badge>
      {error ? <span className="small down"> {error}</span> : null}
    </span>
  );
}

function MarketTabs({ value, onChange }: { value: Market; onChange: (m: Market) => void }) {
  return (
    <Tabs
      value={value}
      onChange={onChange}
      options={[
        { key: "spot", label: MARKET_LABELS.spot ?? "Spot" },
        { key: "usdm_futures", label: MARKET_LABELS.usdm_futures ?? "Futures" },
      ]}
    />
  );
}

/** 1) Geçmiş veri: Binance'in herkese açık arşivinden indirilir (data.binance.vision, özet doğrulamalı). */
function HistorySection() {
  const status = usePoll((c) => c.get<HistoryStatusResponse>("/v1/history/status"), 5000);
  const [market, setMarket] = useState<Market>("spot");
  const [symbols, setSymbols] = useState("BTCUSDT, ETHUSDT");
  const [interval, setInterval] = useState("1h");
  const sync = useAction((c, body: unknown) => c.post<HistoryJobInfo>("/v1/history/sync", body));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await sync.execute({ market, symbols: symbolsOf(symbols), interval })) await status.refresh();
  }

  return (
    <Card title="1. Geçmiş veri" testId="lab-history">
      <ErrorBox error={status.error} what="Geçmiş veri" />
      <form className="toolbar" onSubmit={(e) => void submit(e)}>
        <MarketTabs value={market} onChange={setMarket} />
        <Field label="Semboller (virgülle)">
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} data-testid="lab-history-symbols" />
        </Field>
        <Field label="Aralık">
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </Field>
        <button className="primary" type="submit" disabled={sync.pending || symbolsOf(symbols).length === 0} data-testid="lab-history-start">
          Verileri indir
        </button>
      </form>
      <ErrorBox error={sync.error} />
      <p className="muted small">
        Mum verileri Binance'in herkese açık arşivinden indirilir ve özetleri doğrulanır; hesabınıza erişilmez.
      </p>
      <div className="grid-2">
        <DataTable
          rows={status.data?.coverage}
          rowKey={(r) => `${r.market}-${r.symbol}-${r.interval}`}
          empty="Henüz indirilmiş veri yok"
          columns={[
            { key: "s", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
            { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
            { key: "i", label: "Aralık", render: (r) => r.interval },
            { key: "n", label: "Mum", align: "right", render: (r) => num(r.rows, 0) },
          ]}
        />
        <DataTable
          rows={status.data?.jobs}
          rowKey={(j) => String(j.id)}
          empty="İndirme işi yok"
          columns={[
            { key: "t", label: "Başlangıç", render: (j) => time(j.started_ms) },
            { key: "s", label: "Semboller", render: (j) => j.symbols.join(", ") },
            { key: "d", label: "Durum", render: (j) => <JobState state={j.state} error={j.error} /> },
          ]}
        />
      </div>
    </Card>
  );
}

interface LeaderRow {
  name: string;
  kind: string;
  trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe: number | null;
}

interface BacktestReport {
  market: string;
  interval: string;
  symbols: string[];
  start_ms: number;
  end_ms: number;
  leaderboard: LeaderRow[];
  walk_forward: (LeaderRow & { promoted?: boolean; error?: string })[];
  disclaimer?: string;
}

function Leaderboard({ rows, testId }: { rows: LeaderRow[] | undefined; testId: string }) {
  return (
    <DataTable
      testId={testId}
      rows={rows}
      rowKey={(r) => `${r.kind}-${r.name}`}
      empty="Sonuç yok"
      columns={[
        { key: "n", label: "Strateji", render: (r) => <b>{r.name}</b> },
        { key: "t", label: "İşlem", align: "right", render: (r) => num(r.trades, 0) },
        { key: "w", label: "Kazanma", align: "right", render: (r) => pct(r.win_rate === null ? null : r.win_rate * 100, 1, false) },
        { key: "p", label: "Kâr faktörü", align: "right", render: (r) => num(r.profit_factor, 2) },
        {
          key: "r",
          label: "Getiri",
          align: "right",
          render: (r) => <span className={(r.total_return_pct ?? 0) >= 0 ? "up" : "down"}>{pct(r.total_return_pct, 2)}</span>,
        },
        { key: "d", label: "En büyük düşüş", align: "right", render: (r) => pct(r.max_drawdown_pct, 2, false) },
        { key: "s", label: "Sharpe", align: "right", render: (r) => num(r.sharpe, 2) },
      ]}
    />
  );
}

/** 2) Geriye dönük test: stratejiler geçmiş veride, ücret ve kayma dahil denenir. */
function BacktestSection() {
  const jobs = usePoll((c) => c.get<BacktestJobInfo[]>("/v1/backtest/jobs"), 4000);
  const reports = usePoll((c) => c.get<string[]>("/v1/backtest/reports"), 8000);
  const [market, setMarket] = useState<Market>("spot");
  const [symbols, setSymbols] = useState("BTCUSDT, ETHUSDT");
  const [interval, setInterval] = useState("1h");
  const [walkForward, setWalkForward] = useState(true);
  const [risk, setRisk] = useState("1");
  const [maxPositions, setMaxPositions] = useState("5");
  const [leverage, setLeverage] = useState("1");
  const [selected, setSelected] = useState<string | null>(null);
  const run = useAction((c, body: unknown) => c.post<BacktestJobInfo>("/v1/backtest/run", body));
  const report = usePoll(
    (c) => (selected ? c.get<BacktestReport>(`/v1/backtest/reports/${encodeURIComponent(selected)}`) : Promise.resolve(undefined)),
    0,
    [selected],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      market,
      symbols: symbolsOf(symbols),
      interval,
      walk_forward: walkForward,
      risk_per_trade: Number(risk) / 100,
      max_positions: Number(maxPositions),
      leverage: market === "usdm_futures" ? Number(leverage) : 1,
    };
    if (await run.execute(body)) await jobs.refresh();
  }

  const r = report.data;
  return (
    <Card title="2. Geriye dönük test (backtest)" testId="lab-backtest">
      <ErrorBox error={jobs.error} what="Backtest" />
      <form className="toolbar" onSubmit={(e) => void submit(e)}>
        <MarketTabs value={market} onChange={setMarket} />
        <Field label="Semboller (en çok 20)">
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} data-testid="lab-bt-symbols" />
        </Field>
        <Field label="Aralık">
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </Field>
        <Field label="İşlem başı risk (%)" hint="0,1 – 5">
          <input type="number" min="0.1" max="5" step="0.1" value={risk} onChange={(e) => setRisk(e.target.value)} />
        </Field>
        <Field label="En çok pozisyon">
          <input type="number" min="1" max="50" value={maxPositions} onChange={(e) => setMaxPositions(e.target.value)} />
        </Field>
        {market === "usdm_futures" && (
          <Field label="Kaldıraç" hint="1 – 5">
            <input type="number" min="1" max="5" step="1" value={leverage} onChange={(e) => setLeverage(e.target.value)} />
          </Field>
        )}
        <label className="row small">
          <input type="checkbox" checked={walkForward} onChange={(e) => setWalkForward(e.target.checked)} />
          Yürüyen pencere (aşırı uyumu yakalar)
        </label>
        <button className="primary" type="submit" disabled={run.pending || symbolsOf(symbols).length === 0} data-testid="lab-bt-start">
          Testi başlat
        </button>
      </form>
      <ErrorBox error={run.error} />
      <div className="grid-2">
        <DataTable
          testId="lab-bt-jobs"
          rows={jobs.data}
          rowKey={(j) => String(j.id)}
          empty="Henüz test çalıştırılmadı"
          columns={[
            { key: "t", label: "Başlangıç", render: (j) => time(j.started_ms) },
            { key: "s", label: "Semboller", render: (j) => j.symbols.join(", ") },
            { key: "a", label: "Aşama", render: (j) => j.stage },
            { key: "d", label: "Durum", render: (j) => <JobState state={j.state} error={j.error} /> },
          ]}
        />
        <DataTable
          testId="lab-bt-reports"
          rows={(reports.data ?? []).map((name) => ({ name }))}
          rowKey={(x) => x.name}
          empty="Rapor yok"
          onRowClick={(x) => setSelected(x.name)}
          columns={[
            {
              key: "n",
              label: "Raporlar (açmak için tıklayın)",
              render: (x) => (x.name === selected ? <b>{x.name}</b> : x.name),
            },
          ]}
        />
      </div>
      {r && (
        <div className="stack" data-testid="lab-bt-report">
          <h4>
            {r.symbols.join(", ")} · {r.interval} · {time(r.start_ms)} – {time(r.end_ms)}
          </h4>
          <Leaderboard rows={r.leaderboard} testId="lab-bt-leaderboard" />
          {r.walk_forward.length > 0 && (
            <>
              <h4>Yürüyen pencere (örneklem dışı)</h4>
              <Leaderboard rows={r.walk_forward.filter((w) => !w.error)} testId="lab-bt-walk" />
            </>
          )}
          <p className="muted small">{r.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}

/** 3) Model eğitimi: yapay zekâ modeli geçmiş veride eğitilir, örneklem dışı başarısı gösterilir. */
function TrainingSection() {
  const jobs = usePoll((c) => c.get<TrainJobInfo[]>("/v1/analysis/jobs"), 4000);
  const models = usePoll((c) => c.get<ModelInfo[]>("/v1/analysis/models"), 10_000);
  const [market, setMarket] = useState<Market>("spot");
  const [symbols, setSymbols] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1h");
  const [horizon, setHorizon] = useState("4");
  const [side, setSide] = useState<"long" | "short">("long");
  const train = useAction((c, body: unknown) => c.post<TrainJobInfo>("/v1/analysis/train", body));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = { market, symbols: symbolsOf(symbols), interval, horizon: Number(horizon), side, with_futures: market === "usdm_futures" };
    if (await train.execute(body)) await jobs.refresh();
  }

  return (
    <Card title="3. Yapay zekâ modeli eğitimi" testId="lab-train">
      <ErrorBox error={jobs.error} what="Model eğitimi" />
      <form className="toolbar" onSubmit={(e) => void submit(e)}>
        <MarketTabs value={market} onChange={setMarket} />
        <Field label="Semboller (en çok 50)">
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} data-testid="lab-train-symbols" />
        </Field>
        <Field label="Aralık">
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </Field>
        <Field label="Tahmin ufku (mum)">
          <input type="number" min="1" max="500" value={horizon} onChange={(e) => setHorizon(e.target.value)} />
        </Field>
        <Field label="Yön">
          <select value={side} onChange={(e) => setSide(e.target.value as "long" | "short")}>
            <option value="long">Yükseliş (long)</option>
            <option value="short">Düşüş (short)</option>
          </select>
        </Field>
        <button className="primary" type="submit" disabled={train.pending || symbolsOf(symbols).length === 0} data-testid="lab-train-start">
          Eğitimi başlat
        </button>
      </form>
      <ErrorBox error={train.error} />
      <div className="grid-2">
        <DataTable
          rows={jobs.data}
          rowKey={(j) => String(j.id)}
          empty="Henüz eğitim yapılmadı"
          columns={[
            { key: "t", label: "Başlangıç", render: (j) => time(j.started_ms) },
            { key: "s", label: "Semboller", render: (j) => j.symbols.join(", ") },
            { key: "a", label: "Aşama", render: (j) => j.stage },
            { key: "d", label: "Durum", render: (j) => <JobState state={j.state} error={j.error} /> },
          ]}
        />
        <DataTable
          rows={models.data}
          rowKey={(m) => m.id}
          empty="Eğitilmiş model yok"
          columns={[
            { key: "s", label: "Model", render: (m) => <b>{m.symbols.join(", ")}</b> },
            { key: "i", label: "Aralık / ufuk", render: (m) => `${m.interval} · ${m.horizon} mum` },
            { key: "y", label: "Yön", render: (m) => (m.side === "long" ? "Yükseliş" : "Düşüş") },
            { key: "t", label: "Eğitim", render: (m) => time(m.created_ms) },
          ]}
        />
      </div>
      <p className="muted small">
        Eğitilen model, Grafik ve AI analiz ekranında tahmin olarak kullanılır. Örneklem dışı sonuçlar geleceği garanti etmez.
      </p>
    </Card>
  );
}

export function Lab() {
  return (
    <div className="page" data-testid="page-lab">
      <HistorySection />
      <BacktestSection />
      <TrainingSection />
      <Disclaimer />
    </div>
  );
}
