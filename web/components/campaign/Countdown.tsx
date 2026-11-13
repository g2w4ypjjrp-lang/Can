"use client";

import { useEffect, useState } from "react";

const UNITS: [string, number][] = [
  ["Gün", 86_400_000],
  ["Saat", 3_600_000],
  ["Dk", 60_000],
  ["Sn", 1000],
];

function parts(ms: number): number[] {
  let rest = Math.max(0, ms);
  return UNITS.map(([, size]) => {
    const value = Math.floor(rest / size);
    rest -= value * size;
    return value;
  });
}

/** Kampanya bitişine geri sayım. Sunucu çıktısında "--" görünür (saat farkı uyuşmazlığı olmasın),
 *  tarayıcıda her saniye güncellenir. Sayılar ekran okuyuculardan gizlidir: her saniye okunmasın;
 *  bitiş tarihi ayrıca düz metin olarak verilir. */
export function Countdown({
  endsAt,
  compact = false,
  testId,
}: {
  endsAt: string;
  compact?: boolean;
  testId?: string;
}) {
  const end = new Date(endsAt).getTime();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const values = now === null ? null : parts(end - now);
  const label = new Intl.DateTimeFormat("tr-TR", { dateStyle: "long", timeStyle: "short" }).format(new Date(end));

  if (compact) {
    const pad = (n: number | undefined) => String(n ?? 0).padStart(2, "0");
    const [d = 0, h, m, sec] = values ?? [];
    const text = values ? `${d > 0 ? `${d}g ` : ""}${pad(h)}:${pad(m)}:${pad(sec)}` : "--:--:--";
    return (
      <span data-testid={testId}>
        <span aria-hidden="true" className="tabular font-semibold">
          {text}
        </span>
        <span className="visually-hidden">Bitiş: {label}</span>
      </span>
    );
  }

  return (
    <div data-testid={testId}>
      <div aria-hidden="true" className="flex gap-2">
        {UNITS.map(([unit], i) => (
          <div key={unit} className="count-box">
            <span key={values ? values[i] : "x"} className={`tabular block text-2xl font-bold leading-none ${i === 3 && values ? "count-flip" : ""}`}>
              {values ? String(values[i] ?? 0).padStart(2, "0") : "--"}
            </span>
            <span className="mt-1 block text-[10px] font-semibold uppercase tracking-wider text-white/85">{unit}</span>
          </div>
        ))}
      </div>
      <p className="visually-hidden">Kampanya bitişi: {label}</p>
    </div>
  );
}
