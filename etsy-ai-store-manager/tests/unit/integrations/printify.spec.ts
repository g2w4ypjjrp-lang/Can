import { describe, expect, it } from 'vitest';
import { createHmac } from 'node:crypto';
import {
  centsToDecimal,
  printifyProductionBucket,
  verifyPrintifySignature,
} from '@esm/integrations';
import { detectLineCostBasis } from '../../../apps/worker/src/printify/sync.js';

describe('Printify money', () => {
  it.each([
    [1999, '19.99'],
    [5, '0.05'],
    [0, '0.00'],
    [-250, '-2.50'],
    [100000, '1000.00'],
  ])('%i cents -> %s', (c, s) => expect(centsToDecimal(c)).toBe(s));
  it('rejects non-integers', () => expect(centsToDecimal(1.5)).toBeNull());
});

describe('Printify webhook signature (X-Pfy-Signature: sha256=<hmac hex>)', () => {
  const secret = 'a'.repeat(40);
  const body = Buffer.from('{"id":"evt1","type":"order:updated"}');
  const sig = `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`;
  it('accepts a valid signature', () =>
    expect(verifyPrintifySignature(body, sig, secret)).toBe(true));
  it('rejects tampered body, wrong secret, wrong format, missing header', () => {
    expect(verifyPrintifySignature(Buffer.from('{"id":"evt2"}'), sig, secret)).toBe(false);
    expect(verifyPrintifySignature(body, sig, 'b'.repeat(40))).toBe(false);
    expect(verifyPrintifySignature(body, sig.replace('sha256=', 'sha1='), secret)).toBe(false);
    expect(verifyPrintifySignature(body, 'sha256=zz', secret)).toBe(false);
    expect(verifyPrintifySignature(body, undefined, secret)).toBe(false);
  });
});

describe('Printify order helpers', () => {
  it('maps production statuses', () => {
    expect(printifyProductionBucket('in-production')).toBe('in_production');
    expect(printifyProductionBucket('fulfilled')).toBe('shipped');
    expect(printifyProductionBucket('has-issues')).toBe('problem');
    expect(printifyProductionBucket('canceled')).toBe('cancelled');
    expect(printifyProductionBucket('pending')).toBe('waiting');
  });
  it('detects whether line cost is per unit or per line (docs do not say)', () => {
    const costs = new Map([['p1:1', 500]]);
    const order = (cost: number, quantity: number) =>
      ({
        line_items: [
          { product_id: 'p1', variant_id: 1, quantity, cost, shipping_cost: 0, status: 'x' },
        ],
      }) as never;
    expect(detectLineCostBasis(order(1000, 2), costs, 'unverified')).toBe('line_total');
    expect(detectLineCostBasis(order(500, 2), costs, 'unverified')).toBe('per_unit');
    expect(detectLineCostBasis(order(500, 1), costs, 'unverified')).toBe('unverified');
    expect(detectLineCostBasis(order(777, 2), costs, 'unverified')).toBe('unverified');
    expect(detectLineCostBasis(order(1000, 2), costs, 'per_unit')).toBe('per_unit');
  });
});
