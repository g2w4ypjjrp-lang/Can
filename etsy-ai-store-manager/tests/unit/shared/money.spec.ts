import { describe, expect, it } from 'vitest';
import { compareDecimalStrings, moneyString, rateString, currencyCode } from '@esm/shared';

describe('compareDecimalStrings', () => {
  it.each([
    ['10', '10.00', 0],
    ['10.01', '10', 1],
    ['9.99', '10', -1],
    ['-1', '0', -1],
    ['-0', '0', 0],
    ['-0.00', '5', -1],
    ['-5', '-4.99', -1],
    ['-4.99', '-5', 1],
    ['100', '99.999', 1],
    ['0.1', '0.10', 0],
    ['007', '7', 0],
  ])('compare(%s, %s) = %s', (a, b, expected) => {
    expect(compareDecimalStrings(a, b)).toBe(expected);
  });

  it('is exact where floats are not (0.1+0.2 class of issues)', () => {
    expect(compareDecimalStrings('0.30', '0.3')).toBe(0);
    expect(compareDecimalStrings('9999999999.99', '9999999999.98')).toBe(1);
  });
});

describe('money validators', () => {
  it('accepts at most two decimals and rejects floats-as-numbers formats', () => {
    expect(moneyString.safeParse('10.00').success).toBe(true);
    expect(moneyString.safeParse('10.005').success).toBe(false);
    expect(moneyString.safeParse('1e3').success).toBe(false);
    expect(moneyString.safeParse('abc').success).toBe(false);
  });
  it('rates must be within [0,1]', () => {
    expect(rateString.safeParse('0.0250').success).toBe(true);
    expect(rateString.safeParse('1').success).toBe(true);
    expect(rateString.safeParse('1.5').success).toBe(false);
    expect(rateString.safeParse('-0.1').success).toBe(false);
  });
  it('normalises currency codes', () => {
    expect(currencyCode.parse('usd')).toBe('USD');
    expect(currencyCode.safeParse('US').success).toBe(false);
  });
});
