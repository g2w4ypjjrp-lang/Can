// Canlı piyasa bandı: Binance'in herkese açık piyasa verisi (yalnızca fiyat; hesap ya da anahtar
// kullanılmaz). Sunucu tarafında kısa önbellekle okunur; ulaşılamazsa bant gösterilmez.
// ATI_MARKET_DATA_URL boş bırakılırsa tamamen kapalıdır (testler).

export interface Quote {
  symbol: string; // BTCUSDT
  base: string; // BTC
  price: number;
  changePct: number;
}

export const TICKER_SYMBOLS = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TON", "SUI", "PEPE"];

function marketBase(): string {
  const value = process.env.ATI_MARKET_DATA_URL;
  return (value === undefined ? "https://data-api.binance.vision" : value).replace(/\/+$/, "");
}

/** Binance 24 saatlik özetinden (MINI) fiyat ve değişim yüzdesi. Bozuk satırlar atlanır. */
export function parseQuotes(payload: unknown): Quote[] {
  if (!Array.isArray(payload)) return [];
  const quotes: Quote[] = [];
  for (const row of payload) {
    if (!row || typeof row !== "object") continue;
    const { symbol, lastPrice, openPrice } = row as Record<string, unknown>;
    if (typeof symbol !== "string" || !/^[A-Z0-9]{2,15}USDT$/.test(symbol)) continue;
    const price = Number(lastPrice);
    const open = Number(openPrice);
    if (!Number.isFinite(price) || price <= 0) continue;
    const changePct = Number.isFinite(open) && open > 0 ? ((price - open) / open) * 100 : 0;
    quotes.push({ symbol, base: symbol.slice(0, -4), price, changePct });
  }
  return quotes;
}

const cache = new Map<string, { at: number; quotes: Quote[] }>();

export async function fetchQuotes(bases: string[] = TICKER_SYMBOLS): Promise<Quote[]> {
  const base = marketBase();
  if (!base) return [];
  const symbols = [...new Set(bases.map((b) => b.toUpperCase()).filter((b) => /^[A-Z0-9]{2,12}$/.test(b)))].slice(0, 30);
  if (!symbols.length) return [];
  const key = symbols.join(",");
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < 10_000) return hit.quotes;
  const list = encodeURIComponent(JSON.stringify(symbols.map((s) => `${s}USDT`)));
  try {
    const response = await fetch(`${base}/api/v3/ticker/24hr?type=MINI&symbols=${list}`, {
      signal: AbortSignal.timeout(2500),
      cache: "no-store",
    });
    if (!response.ok) {
      // Listede Binance'te olmayan bir sembol varsa istek bütünüyle reddedilir: sabit listeye dön.
      if (response.status === 400 && key !== TICKER_SYMBOLS.join(",")) return fetchQuotes(TICKER_SYMBOLS);
      return [];
    }
    const order = new Map(symbols.map((s, i) => [s, i]));
    const quotes = parseQuotes(await response.json()).sort((a, b) => (order.get(a.base) ?? 99) - (order.get(b.base) ?? 99));
    if (cache.size > 50) cache.clear();
    cache.set(key, { at: Date.now(), quotes });
    return quotes;
  } catch {
    return [];
  }
}

/** Kripto fiyat biçimi: büyük fiyatlarda 2 hane, küçüklerde anlamlı hane kadar. */
export function formatQuote(price: number): string {
  const digits = price >= 1000 ? 2 : price >= 1 ? 3 : price >= 0.01 ? 5 : 8;
  return new Intl.NumberFormat("tr-TR", { minimumFractionDigits: Math.min(digits, 2), maximumFractionDigits: digits }).format(price);
}

export function formatChange(pct: number): string {
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}
