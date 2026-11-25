import { z } from 'zod';

/**
 * Money values travel between services as decimal strings (never JS floats).
 * Arithmetic is done with Decimal in the profit engine.
 */
export const DECIMAL_2_RE = /^-?\d{1,10}(\.\d{1,2})?$/;
export const DECIMAL_4_RE = /^-?\d{1,10}(\.\d{1,4})?$/;

export const moneyString = z
  .string()
  .trim()
  .regex(DECIMAL_2_RE, 'En fazla 2 ondalık basamaklı sayı olmalı (ör. 10.00)');

export const nonNegativeMoneyString = moneyString.refine(
  (v) => !v.startsWith('-'),
  'Negatif olamaz',
);

/** Non-negative amount with up to 4 decimals (cost allocations, e.g. "0.3750"). */
export const nonNegativeMoney4String = z
  .string()
  .trim()
  .regex(DECIMAL_4_RE, 'En fazla 4 ondalık basamaklı sayı olmalı')
  .refine((v) => !v.startsWith('-'), 'Negatif olamaz');

/** Rate in [0,1] with up to 4 decimals, as string (e.g. "0.0250" = %2,5). */
export const rateString = z
  .string()
  .trim()
  .regex(/^(0(\.\d{1,4})?|1(\.0{1,4})?)$/, '0 ile 1 arasında, en fazla 4 ondalık (ör. 0.0250)');

export const currencyCode = z
  .string()
  .trim()
  .toUpperCase()
  .regex(/^[A-Z]{3}$/, 'ISO 4217 para birimi kodu olmalı (ör. USD)');

/** Compare two decimal strings exactly (no float conversion). Returns -1, 0, 1. */
export function compareDecimalStrings(a: string, b: string): -1 | 0 | 1 {
  const norm = (s: string) => {
    const raw = s.trim();
    const negSign = raw.startsWith('-');
    const [i = '0', f = ''] = (negSign ? raw.slice(1) : raw).split('.');
    const int = i.replace(/^0+/, '');
    const frac = f.replace(/0+$/, '');
    const isZero = int === '' && frac === '';
    return { neg: negSign && !isZero, int, frac };
  };
  const x = norm(a);
  const y = norm(b);
  if (x.neg !== y.neg) return x.neg ? -1 : 1;
  const sign = x.neg ? -1 : 1;
  let cmp: number;
  if (x.int.length !== y.int.length) cmp = x.int.length > y.int.length ? 1 : -1;
  else if (x.int !== y.int) cmp = x.int > y.int ? 1 : -1;
  else {
    const len = Math.max(x.frac.length, y.frac.length);
    const xf = x.frac.padEnd(len, '0');
    const yf = y.frac.padEnd(len, '0');
    cmp = xf === yf ? 0 : xf > yf ? 1 : -1;
  }
  return cmp === 0 ? 0 : ((cmp * sign) as -1 | 1);
}
