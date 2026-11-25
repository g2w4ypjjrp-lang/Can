/** Etsy Money object (OpenAPI components.schemas.Money). */
export interface EtsyMoney {
  amount: number;
  divisor: number;
  currency_code: string;
}

/**
 * Exact conversion amount/divisor -> decimal string without floating point,
 * e.g. {amount: 1999, divisor: 100} -> "19.99"; {amount: 5, divisor: 1000} -> "0.005".
 */
export function moneyToDecimal(m: EtsyMoney | null | undefined): string | null {
  if (!m || !Number.isInteger(m.amount) || !Number.isInteger(m.divisor) || m.divisor <= 0)
    return null;
  const neg = m.amount < 0;
  const amount = BigInt(Math.abs(m.amount));
  const divisor = BigInt(m.divisor);
  // divisor is a power of ten in practice; fall back to long division otherwise
  const pow = String(m.divisor).match(/^10*$/) ? String(m.divisor).length - 1 : -1;
  let result: string;
  if (pow >= 0) {
    const s = amount.toString().padStart(pow + 1, '0');
    result = pow === 0 ? s : `${s.slice(0, -pow)}.${s.slice(-pow)}`;
  } else {
    const int = amount / divisor;
    let rem = amount % divisor;
    let frac = '';
    for (let i = 0; i < 8 && rem !== 0n; i++) {
      rem *= 10n;
      frac += (rem / divisor).toString();
      rem %= divisor;
    }
    result = frac ? `${int}.${frac}` : int.toString();
  }
  return neg ? `-${result}` : result;
}

/** Sum of decimal strings with the same scale handling (exact). */
export function addDecimals(...values: Array<string | null | undefined>): string {
  let scale = 0;
  for (const v of values)
    if (v && v.includes('.')) scale = Math.max(scale, v.split('.')[1]!.length);
  let total = 0n;
  for (const v of values) {
    if (!v) continue;
    const neg = v.startsWith('-');
    const [i = '0', f = ''] = (neg ? v.slice(1) : v).split('.');
    const n = BigInt(i + f.padEnd(scale, '0'));
    total += neg ? -n : n;
  }
  const neg = total < 0n;
  const s = (neg ? -total : total).toString().padStart(scale + 1, '0');
  const out = scale ? `${s.slice(0, -scale)}.${s.slice(-scale)}` : s;
  return neg ? `-${out}` : out;
}
