import type pg from 'pg';

export const ECB_DAILY_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml';

/** Parses the ECB euro foreign exchange reference rates XML (units per 1 EUR). */
export function parseEcbXml(xml: string): { asOf: string; rates: Record<string, string> } {
  const time = xml.match(/<Cube\s+time=['"](\d{4}-\d{2}-\d{2})['"]/);
  if (!time) throw new Error('ECB XML: date not found');
  const rates: Record<string, string> = {};
  for (const m of xml.matchAll(
    /<Cube\s+currency=['"]([A-Z]{3})['"]\s+rate=['"]([0-9.]+)['"]\s*\/>/g,
  )) {
    rates[m[1]!] = m[2]!;
  }
  if (!Object.keys(rates).length) throw new Error('ECB XML: no rates');
  return { asOf: time[1]!, rates };
}

/** Stores ECB reference rates (base EUR). Idempotent per (base, quote, as_of, source). */
export async function refreshFxRates(
  pool: pg.Pool,
  fetchImpl: typeof fetch = fetch,
  url = ECB_DAILY_URL,
) {
  const res = await fetchImpl(url, { headers: { 'User-Agent': 'EtsyAIStoreManager/0.1' } });
  if (!res.ok) throw new Error(`ECB rates HTTP ${res.status}`);
  const { asOf, rates } = parseEcbXml(await res.text());
  let inserted = 0;
  for (const [quote, rate] of Object.entries(rates)) {
    const r = await pool.query(
      `insert into public.fx_rates (base, quote, rate, as_of, source) values ('EUR', $1, $2, $3::date, 'ECB')
       on conflict (base, quote, as_of, source) do nothing`,
      [quote, rate, asOf],
    );
    inserted += r.rowCount ?? 0;
  }
  return { asOf, currencies: Object.keys(rates).length, inserted };
}
