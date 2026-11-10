/** Türkçe sayı/zaman biçimlendirme. Motor ondalıkları hassasiyet için metin olarak gönderir. */

export type Numeric = number | string | null | undefined;

export function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

const cache = new Map<string, Intl.NumberFormat>();
function nf(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: min, maximumFractionDigits: max });
    cache.set(key, f);
  }
  return f;
}

export function num(value: Numeric, digits = 2): string {
  const n = toNumber(value);
  return n === null ? "—" : nf(digits, digits).format(n);
}

/** Fiyat: büyüklüğe göre anlamlı basamak (BTC 2, küçük coinler 6-8). */
export function price(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 4 : abs >= 0.01 ? 6 : 8;
  return nf(0, digits).format(n);
}

export function pct(value: Numeric, digits = 2, signed = true): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const text = nf(digits, digits).format(n);
  return `${signed && n > 0 ? "+" : ""}${text}%`;
}

/** 1.234.567 → 1,23 Mn */
export function compact(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  const units: [number, string][] = [
    [1e12, " Tn"],
    [1e9, " Mr"],
    [1e6, " Mn"],
    [1e3, " B"],
  ];
  for (const [size, suffix] of units) {
    if (abs >= size) return nf(2, 2).format(n / size) + suffix;
  }
  return nf(0, 2).format(n);
}

export function usd(value: Numeric, digits = 2): string {
  const n = toNumber(value);
  return n === null ? "—" : `${n < 0 ? "-" : ""}$${nf(digits, digits).format(Math.abs(n))}`;
}

export function time(ms: Numeric): string {
  const n = toNumber(ms);
  if (n === null || n <= 0) return "—";
  return new Date(n).toLocaleString("tr-TR", { hour12: false });
}

export function duration(seconds: Numeric): string {
  const s = toNumber(seconds);
  if (s === null) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h} sa ${m} dk`;
  if (m > 0) return `${m} dk`;
  return `${Math.floor(s)} sn`;
}

export function tone(value: Numeric): "up" | "down" | "flat" {
  const n = toNumber(value);
  if (n === null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export const STATE_LABELS: Record<string, string> = {
  running: "Çalışıyor",
  safe_mode: "Güvenli mod",
  halted: "Acil durdurma",
  starting: "Başlıyor",
  stopping: "Kapanıyor",
  stopped: "Durdu",
};

export const MODE_LABELS: Record<string, string> = {
  paper: "Sanal işlem",
  testnet: "Demo Trading",
  live: "Gerçek hesap",
};

export const MARKET_LABELS: Record<string, string> = {
  spot: "Spot",
  usdm_futures: "Futures",
};
