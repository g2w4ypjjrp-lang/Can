"use client";

// Yönetim paneli grafikleri: yalnızca SVG (öznitelikler; satır içi stil yok → CSP uyumlu).
// Tek seri: 2px çizgi, %10 alan dolgusu, kıl çizgisi kılavuz, uç noktada değer etiketi;
// üzerine gelince/klavyeyle dikey imleç + ipucu; her grafiğin tablo görünümü vardır.

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setWidth(Math.max(240, Math.floor(element.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** 0'dan başlayan "temiz" eksen adımları (1, 2, 2.5, 5 × 10^k). */
export function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(6)));
  if (ticks[ticks.length - 1]! < max) ticks.push(ticks[ticks.length - 1]! + step);
  return ticks;
}

export interface TrendPoint {
  key: string;
  label: string;
  value: number;
  detail?: string;
}

/** Zaman içinde tek ölçü (alan + çizgi), etkileşimli. */
export function AreaTrend({
  points,
  title,
  format,
  compact,
  height = 260,
  emptyText = "Bu dönemde veri yok.",
}: {
  points: TrendPoint[];
  title: string;
  format: (value: number) => string;
  compact: (value: number) => string;
  height?: number;
  emptyText?: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const gradient = useId().replace(/:/g, "");
  const pad = { top: 20, right: 64, bottom: 30, left: 72 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(0, ...points.map((p) => p.value));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const x = (i: number) => pad.left + (points.length <= 1 ? innerW / 2 : (i * innerW) / (points.length - 1));
  const y = (v: number) => pad.top + innerH - (v / top) * innerH;
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${x(points.length - 1).toFixed(1)} ${pad.top + innerH} L${x(0).toFixed(1)} ${pad.top + innerH} Z` : "";
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(innerW / 90))));
  const last = points.length - 1;
  const shown = active ?? null;

  function pick(clientX: number, rect: DOMRect) {
    if (!points.length) return;
    const rel = ((clientX - rect.left) / rect.width) * width - pad.left;
    const i = Math.round((rel / innerW) * (points.length - 1));
    setActive(Math.min(last, Math.max(0, i)));
  }

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (!points.length) return;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const step = event.key === "ArrowRight" ? 1 : -1;
      setActive((current) => Math.min(last, Math.max(0, (current ?? last) + step)));
    } else if (event.key === "Home") {
      setActive(0);
    } else if (event.key === "End") {
      setActive(last);
    } else if (event.key === "Escape") {
      setActive(null);
    }
  }

  if (!points.length || max === 0) {
    return (
      <div ref={ref} className="flex h-[200px] items-center justify-center rounded-2xl border border-dashed border-border text-sm text-muted">
        {emptyText}
      </div>
    );
  }

  const tip = shown !== null ? points[shown]! : null;
  const tipW = 168;
  const tipX = shown === null ? 0 : x(shown) + 12 + tipW > width - 4 ? x(shown) - tipW - 12 : x(shown) + 12;
  const hasDetail = points.some((p) => p.detail);

  return (
    <div>
      <div
        ref={ref}
        tabIndex={0}
        role="group"
        aria-label={`${title}. Değerleri incelemek için sol ve sağ ok tuşlarını kullanın.`}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
        className="relative rounded-2xl outline-none focus-visible:ring-4 focus-visible:ring-ring"
      >
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="block max-w-full touch-none select-none"
          onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setActive(null)}
          aria-hidden="true"
        >
          <defs>
            <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--chart-1)" stopOpacity="0.16" />
              <stop offset="1" stopColor="var(--chart-1)" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={pad.left - 10} y={y(t) + 4} textAnchor="end" className="fill-muted text-[11px] tabular">
                {compact(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % labelEvery === 0 || i === last ? (
              <text key={p.key} x={x(i)} y={height - 8} textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"} className="fill-muted text-[11px]">
                {p.label}
              </text>
            ) : null,
          )}
          <path d={area} fill={`url(#${gradient})`} />
          <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={x(last)} cy={y(points[last]!.value)} r="4" fill="var(--chart-1)" stroke="var(--surface)" strokeWidth="2" />
          <text x={x(last) + 10} y={y(points[last]!.value) + 4} className="fill-fg text-[12px] font-semibold tabular">
            {compact(points[last]!.value)}
          </text>
          {tip && shown !== null ? (
            <g>
              <line x1={x(shown)} x2={x(shown)} y1={pad.top} y2={pad.top + innerH} stroke="var(--border-strong)" strokeWidth="1" />
              <circle cx={x(shown)} cy={y(tip.value)} r="5" fill="var(--chart-1)" stroke="var(--surface)" strokeWidth="2" />
              <g transform={`translate(${tipX}, ${pad.top + 4})`}>
                <rect width={tipW} height={tip.detail ? 64 : 48} rx="12" fill="var(--surface)" stroke="var(--border)" />
                <text x="12" y="21" className="fill-fg text-[14px] font-semibold tabular">
                  {format(tip.value)}
                </text>
                <text x="12" y="38" className="fill-muted text-[11px]">
                  {tip.label}
                </text>
                {tip.detail ? (
                  <text x="12" y="54" className="fill-muted text-[11px]">
                    {tip.detail}
                  </text>
                ) : null}
              </g>
            </g>
          ) : null}
          <rect x={pad.left} y={pad.top} width={innerW} height={innerH} fill="transparent" />
        </svg>
        <p className="visually-hidden" aria-live="polite">
          {tip ? `${tip.label}: ${format(tip.value)}${tip.detail ? `, ${tip.detail}` : ""}` : ""}
        </p>
      </div>
      <TableView
        caption={title}
        head={hasDetail ? ["Gün", "Değer", "Ayrıntı"] : ["Gün", "Değer"]}
        rows={points.map((p) => (hasDetail ? [p.label, format(p.value), p.detail ?? ""] : [p.label, format(p.value)]))}
      />
    </div>
  );
}

/** Grafiklerin erişilebilir tablo görünümü (açılır). */
export function TableView({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="group mt-3">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-muted hover:bg-surface-2 hover:text-fg">
        Tablo olarak göster
      </summary>
      <div className="mt-2 max-h-64 overflow-auto rounded-xl border border-border">
        <table className="w-full text-left text-xs">
          <caption className="visually-hidden">{caption}</caption>
          <thead className="sticky top-0 bg-surface-2 text-muted">
            <tr>
              {head.map((h) => (
                <th key={h} scope="col" className="px-3 py-2 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((c, j) => (
                  <td key={j} className="tabular px-3 py-1.5 text-fg">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Küçük eğilim çizgisi (gösterge kartları). Süs: değer kartın kendisinde yazılıdır. */
export function Sparkline({ values, className = "h-10 w-28" }: { values: number[]; className?: string }) {
  const gradient = useId().replace(/:/g, "");
  if (values.length < 2) return null;
  const w = 112;
  const h = 40;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [(i * w) / (values.length - 1), h - 4 - (v / max) * (h - 8)] as const);
  const line = pts.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--chart-1)" stopOpacity="0.18" />
          <stop offset="1" stopColor="var(--chart-1)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w} ${h} L0 ${h} Z`} fill={`url(#${gradient})`} />
      <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export interface BarItem {
  key: string;
  label: string;
  value: number;
}

/** Yatay çubuklar (büyüklük karşılaştırması): tek renk, uçta değer etiketi, 4px yuvarlak uç. */
export function BarList({ items, title, format = (v) => v.toLocaleString("tr-TR") }: { items: BarItem[]; title: string; format?: (v: number) => string }) {
  const { ref, width } = useWidth<HTMLUListElement>(360);
  const sorted = useMemo(() => [...items].sort((a, b) => b.value - a.value), [items]);
  const max = Math.max(1, ...sorted.map((i) => i.value));
  const barMax = Math.max(40, width - 56);
  if (!sorted.length) return <p className="text-sm text-muted">Henüz veri yok.</p>;
  return (
    <div>
      <ul ref={ref} className="space-y-3" aria-label={title}>
        {sorted.map((item) => {
          const w = Math.max(6, (item.value / max) * barMax);
          return (
            <li key={item.key}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-fg">
                  {item.label}
                  <span className="visually-hidden">: {format(item.value)}</span>
                </span>
              </div>
              <svg width={width} height="18" viewBox={`0 0 ${width} 18`} className="mt-1 block max-w-full" aria-hidden="true" focusable="false">
                <path d={`M0 3 H${w - 4} Q${w} 3 ${w} 7 V11 Q${w} 15 ${w - 4} 15 H0 Z`} fill="var(--chart-1)" />
                <text x={w + 8} y="13" className="fill-fg text-[12px] font-semibold tabular">
                  {format(item.value)}
                </text>
              </svg>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
