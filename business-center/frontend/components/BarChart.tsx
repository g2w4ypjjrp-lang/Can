"use client";
import { useState } from "react";

type Point = { label: string; value: number; empty?: boolean };

/** Tek serili çubuk grafik: ince çubuklar, yuvarlatılmış uç, tek eksen, üzerine gelince değer, tablo görünümü. */
export function BarChart({ title, unit, points, color, integer = false }:
  { title: string; unit: string; points: Point[]; color: string; integer?: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = 720, H = 220, L = 44, B = 26, T = 12;
  const max = Math.max(1, ...points.map((p) => p.value));
  const nice = integer ? Math.max(2, Math.ceil(niceMax(max))) : niceMax(max);
  const bw = (W - L - 8) / Math.max(points.length, 1);
  const barW = Math.max(2, Math.min(18, bw - 3));
  const y = (v: number) => T + (H - T - B) * (1 - v / nice);
  const ticks = integer && nice % 2 ? [0, nice] : [0, nice / 2, nice];
  const fmt = (v: number) => v.toLocaleString("tr-TR", { maximumFractionDigits: 1 });
  const total = points.reduce((s, p) => s + p.value, 0);

  return (
    <figure className="rounded-2xl border border-line bg-panel p-4">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="font-semibold">{title}</span>
        <span className="text-sm text-muted">Toplam {fmt(total)} {unit}</span>
        <button type="button" onClick={() => setTable(!table)} className="ml-auto text-xs text-brand underline">
          {table ? "Grafik" : "Tablo"}</button>
      </figcaption>
      {table ? (
        <div className="max-h-64 overflow-auto text-sm">
          <table className="w-full"><thead className="text-left text-xs text-muted"><tr><th className="py-1">Gün</th><th className="text-right">{unit}</th></tr></thead>
            <tbody>{points.map((p) => <tr key={p.label} className="border-t border-line"><td className="py-1">{p.label}</td>
              <td className="text-right tabular-nums">{p.empty ? "—" : fmt(p.value)}</td></tr>)}</tbody></table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${title}, toplam ${fmt(total)} ${unit}`}
            onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={L} x2={W - 4} y1={y(t)} y2={y(t)} stroke="currentColor" className="text-line" strokeWidth={1} />
                <text x={L - 6} y={y(t) + 4} textAnchor="end" className="fill-[var(--color-muted)] text-[11px]">{fmt(t)}</text>
              </g>
            ))}
            {points.map((p, i) => {
              const x = L + i * bw + (bw - barW) / 2, top = y(p.value), h = Math.max(0, H - B - top);
              return (
                <g key={p.label} onMouseEnter={() => setHover(i)}>
                  <rect x={L + i * bw} y={T} width={bw} height={H - T - B} fill="transparent" />
                  {h > 0 && <path d={roundedTop(x, top, barW, h, Math.min(4, barW / 2))} fill={color}
                    opacity={hover === null || hover === i ? 1 : 0.45} />}
                </g>
              );
            })}
            {points.map((p, i) => (i % Math.ceil(points.length / 6) === 0) && (
              <text key={p.label} x={L + i * bw + bw / 2} y={H - 8} textAnchor="middle" className="fill-[var(--color-muted)] text-[11px]">{p.label}</text>
            ))}
          </svg>
          {hover !== null && (
            <div className="pointer-events-none absolute -translate-x-1/2 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs shadow-md"
              style={{ left: `${((L + hover * bw + bw / 2) / W) * 100}%`, top: 0 }}>
              <div className="text-muted">{points[hover].label}</div>
              <div className="font-semibold tabular-nums">{points[hover].empty ? "Veri yok" : `${fmt(points[hover].value)} ${unit}`}</div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

function niceMax(v: number) {
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v) ?? v;
}

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}
