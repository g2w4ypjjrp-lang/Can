// Açık pozisyonların anlık fiyatı: motor, Binance işlem akışındaki her yeni fiyatı (en çok
// 0,1 sn'de bir) "PriceTick" olayıyla gönderir. Ekran kâr/zararı beklemeden bununla hesaplar.
import { useSyncExternalStore } from "react";

export type LivePrices = Record<string, number>;

let prices: LivePrices = {};
const listeners = new Set<() => void>();

export function applyPriceTick(update: unknown): void {
  if (!update || typeof update !== "object") return;
  const next: LivePrices = { ...prices };
  for (const [key, value] of Object.entries(update as Record<string, unknown>)) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) next[key] = n;
  }
  prices = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLivePrices(): LivePrices {
  return useSyncExternalStore(subscribe, () => prices);
}

/** Tek coinin anlık fiyatı ("<piyasa>:<SEMBOL>"): yalnızca bu coinin fiyatı değişince yeniden
 * çizilir (yüzlerce satırlık tablo her fiyatta baştan çizilmez). */
export function useLivePrice(key: string): number | undefined {
  return useSyncExternalStore(subscribe, () => prices[key]);
}

interface PositionLike {
  market: string;
  symbol: string;
  quantity: number | string;
  entry_price: number | string;
  mark_price?: number | string | null;
  unrealized_pnl?: number | string | null;
  pnl_pct?: number | null;
  notional?: number | string | null;
}

/** Pozisyonların fiyat ve kâr/zararını anlık fiyatla günceller (yoksa motorun son değeri kalır). */
export function withLivePrices<T extends PositionLike>(rows: T[] | null | undefined, live: LivePrices): T[] | undefined {
  if (!rows) return undefined;
  return rows.map((row) => {
    const price = live[`${row.market}:${row.symbol}`];
    const qty = Number(row.quantity);
    const entry = Number(row.entry_price);
    if (!price || !qty || !(entry > 0)) return row;
    return {
      ...row,
      mark_price: price,
      unrealized_pnl: (price - entry) * qty,
      pnl_pct: Math.round((price / entry - 1) * 100 * (qty > 0 ? 1 : -1) * 1000) / 1000,
      notional: Math.abs(qty) * price,
    };
  });
}

export function useLivePositions<T extends PositionLike>(rows: T[] | null | undefined): T[] | undefined {
  return withLivePrices(rows, useLivePrices());
}

/** Test ve bağlantı yenilemesi için. */
export function resetLivePrices(): void {
  prices = {};
  for (const listener of listeners) listener();
}
