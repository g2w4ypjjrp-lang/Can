import { useEffect, useRef, useState } from "react";
import { useLivePrice } from "../lib/livePrices";
import { pct, price } from "../lib/format";

function useFlash(value: number | null): "" | "up" | "down" {
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (value === null || before === null || value === before) return;
    setFlash(value > before ? "up" : "down");
    const id = window.setTimeout(() => setFlash(""), 700);
    return () => window.clearTimeout(id);
  }, [value]);
  return flash;
}

/** Anlık fiyat: Binance'te her yeni işlem fiyatında değişir; yükselişte yeşil, düşüşte kırmızı
 * yanıp söner. Anlık fiyat gelmemişse ``fallback`` (motorun son değeri) gösterilir. */
export function LivePrice({ id, fallback }: { id: string; fallback?: number | string | null }) {
  const live = useLivePrice(id);
  const value = live ?? (fallback === null || fallback === undefined || fallback === "" ? null : Number(fallback));
  const flash = useFlash(value);
  return (
    <span className={`live-price ${flash ? `flash-${flash}` : ""}`} data-live={live !== undefined ? "1" : undefined}>
      {price(value)}
    </span>
  );
}

/** 24 saatlik değişim, anlık fiyatla (açılış fiyatı son değerden türetilir). */
export function LiveChange({ id, last, change }: { id: string; last: number; change: number }) {
  const live = useLivePrice(id);
  const open = change > -100 ? last / (1 + change / 100) : 0;
  const value = live !== undefined && open > 0 ? (live / open - 1) * 100 : change;
  return <span className={value > 0 ? "up" : value < 0 ? "down" : ""}>{pct(value)}</span>;
}
