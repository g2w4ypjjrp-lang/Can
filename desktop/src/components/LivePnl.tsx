import { useEffect, useRef, useState } from "react";

const fmt = (v: number) => v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Anlık kâr/zarar: yükselince yeşil, düşünce kırmızı yanıp söner; ok yönü işareti gösterir. */
export function LivePnl({ value, pct, testId }: { value: number | string | null | undefined; pct?: number | null; testId?: string }) {
  const n = value === null || value === undefined || value === "" ? null : Number(value);
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    const before = prev.current;
    prev.current = n;
    if (n === null || before === null || n === before) return;
    setFlash(n > before ? "up" : "down");
    const id = window.setTimeout(() => setFlash(""), 900);
    return () => window.clearTimeout(id);
  }, [n]);
  if (n === null || Number.isNaN(n)) return <span className="muted">—</span>;
  const tone = n > 0 ? "up" : n < 0 ? "down" : "";
  return (
    <span className={`pnl ${tone} ${flash ? `flash-${flash}` : ""}`} data-testid={testId}>
      <span aria-hidden="true">{n > 0 ? "▲" : n < 0 ? "▼" : "•"}</span> {n > 0 ? "+" : ""}
      {fmt(n)} USDT
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
