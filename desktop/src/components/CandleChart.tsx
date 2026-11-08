import {
  CandlestickSeries,
  type CandlestickData,
  createChart,
  HistogramSeries,
  type HistogramData,
  type IChartApi,
  LineStyle,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface Candle {
  time: number; // ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceMark {
  price: number;
  title: string;
  color: string;
  dashed?: boolean;
}

const UP = "#16c784";
const DOWN = "#ea3943";

/** Mum grafiği (TradingView Lightweight Charts): mumlar, hacim, destek/direnç ve seviye çizgileri. */
export function CandleChart({ candles, marks = [], height = 420 }: { candles: Candle[]; marks?: PriceMark[]; height?: number }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#9aa4b2", fontFamily: "inherit" },
      grid: { vertLines: { color: "#1f2633" }, horzLines: { color: "#1f2633" } },
      rightPriceScale: { borderColor: "#2a3343" },
      timeScale: { borderColor: "#2a3343", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      localization: { locale: "tr-TR" },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    const toTime = (ms: number) => Math.floor(ms / 1000) as UTCTimestamp;
    series.setData(
      candles.map<CandlestickData>((c) => ({ time: toTime(c.time), open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    volume.setData(
      candles.map<HistogramData>((c) => ({
        time: toTime(c.time),
        value: c.volume,
        color: c.close >= c.open ? "rgba(22,199,132,0.35)" : "rgba(234,57,67,0.35)",
      })),
    );
    for (const mark of marks) {
      series.createPriceLine({
        price: mark.price,
        color: mark.color,
        lineWidth: 1,
        lineStyle: mark.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: mark.title,
      });
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, marks]);

  return <div ref={host} className="chart" style={{ height }} data-testid="candle-chart" />;
}

export function candlesFromRows(columns: string[], rows: number[][]): Candle[] {
  const index = (name: string) => columns.indexOf(name);
  const [t, o, h, l, c, v] = ["open_time", "open", "high", "low", "close", "volume"].map(index);
  if ([t, o, h, l, c, v].some((i) => i === undefined || i < 0)) return [];
  return rows.map((r) => ({
    time: r[t!]!,
    open: r[o!]!,
    high: r[h!]!,
    low: r[l!]!,
    close: r[c!]!,
    volume: r[v!]!,
  }));
}
