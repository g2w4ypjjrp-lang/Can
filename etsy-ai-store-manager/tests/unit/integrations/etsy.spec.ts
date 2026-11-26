import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  addDecimals,
  buildAuthorizeUrl,
  createPkcePair,
  EtsyApiError,
  EtsyClient,
  exchangeAuthorizationCode,
  mapReceipt,
  mapReceiptStatus,
  moneyToDecimal,
  pkceChallenge,
  refreshAccessToken,
  TokenCipher,
} from '@esm/integrations';
import { listingChangeRequestSchema } from '@esm/shared';
import { startEtsyStub, STUB_APP, STUB_SHOP_ID, type EtsyStub } from '../../helpers/etsy-stub.js';

describe('Etsy Money -> exact decimal', () => {
  it.each([
    [{ amount: 1999, divisor: 100, currency_code: 'USD' }, '19.99'],
    [{ amount: 5, divisor: 100, currency_code: 'USD' }, '0.05'],
    [{ amount: 5, divisor: 1000, currency_code: 'USD' }, '0.005'],
    [{ amount: -250, divisor: 100, currency_code: 'EUR' }, '-2.50'],
    [{ amount: 1200, divisor: 1, currency_code: 'JPY' }, '1200'],
    [{ amount: 1, divisor: 3, currency_code: 'X' }, '0.33333333'],
  ])('%j -> %s', (m, expected) => expect(moneyToDecimal(m)).toBe(expected));
  it('rejects malformed money', () => {
    expect(moneyToDecimal({ amount: 1.5, divisor: 100, currency_code: 'USD' })).toBeNull();
    expect(moneyToDecimal({ amount: 1, divisor: 0, currency_code: 'USD' })).toBeNull();
    expect(moneyToDecimal(null)).toBeNull();
  });
  it('adds decimals exactly', () => {
    expect(addDecimals('0.10', '0.20')).toBe('0.30');
    expect(addDecimals('9.80', '0.2', null)).toBe('10.00');
    expect(addDecimals('-1.5', '1')).toBe('-0.5');
  });
});

describe('Etsy OAuth helpers', () => {
  it('builds a PKCE pair per RFC 7636 (S256)', () => {
    const p = createPkcePair();
    expect(p.verifier).toMatch(/^[A-Za-z0-9._~-]{43,128}$/);
    expect(p.challenge).toBe(pkceChallenge(p.verifier));
    // RFC 7636 appendix B test vector
    expect(pkceChallenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe(
      'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
    );
  });
  it('builds the documented authorize URL', () => {
    const u = new URL(
      buildAuthorizeUrl(
        {
          keystring: 'k',
          sharedSecret: 's',
          redirectUri: 'https://app.example.com/api/v1/integrations/etsy/callback',
        },
        { state: 'st', codeChallenge: 'ch' },
      ),
    );
    expect(u.origin + u.pathname).toBe('https://www.etsy.com/oauth/connect');
    expect(Object.fromEntries(u.searchParams)).toEqual({
      response_type: 'code',
      client_id: 'k',
      redirect_uri: 'https://app.example.com/api/v1/integrations/etsy/callback',
      scope: 'shops_r listings_r listings_w transactions_r transactions_w',
      state: 'st',
      code_challenge: 'ch',
      code_challenge_method: 'S256',
    });
    expect(u.toString()).not.toContain('s&'); // shared secret never in the browser URL
  });
});

describe('Etsy mappers', () => {
  it('maps receipt statuses', () => {
    expect(mapReceiptStatus({ status: 'paid', is_paid: true, is_shipped: false })).toBe('paid');
    expect(mapReceiptStatus({ status: 'paid', is_paid: true, is_shipped: true })).toBe('shipped');
    expect(mapReceiptStatus({ status: 'completed', is_paid: true, is_shipped: true })).toBe(
      'shipped',
    );
    expect(mapReceiptStatus({ status: 'canceled', is_paid: false, is_shipped: false })).toBe(
      'cancelled',
    );
    expect(mapReceiptStatus({ status: 'fully refunded', is_paid: true, is_shipped: true })).toBe(
      'refunded',
    );
    expect(
      mapReceiptStatus({ status: 'partially refunded', is_paid: true, is_shipped: true }),
    ).toBe('partially_refunded');
    expect(
      mapReceiptStatus({ status: 'payment processing', is_paid: false, is_shipped: false }),
    ).toBe('open');
  });
  it('maps money exactly, includes VAT in tax and drops buyer e-mail', async () => {
    const stub = await startEtsyStub({ listingCount: 3 });
    try {
      const m = mapReceipt(stub.receipts[0] as never);
      expect(m).toMatchObject({
        subtotal: '49.00',
        shippingTotal: '5.99',
        taxTotal: '9.80',
        discountTotal: '4.90',
        grandTotal: '59.89',
        buyerCountry: 'DE',
        status: 'paid',
      });
      expect(m.items[0]).toMatchObject({
        quantity: 2,
        unitPrice: '24.51',
        etsyListingId: '900001',
      });
      expect(JSON.stringify({ ...m, raw: undefined })).not.toContain('buyer1001@');
    } finally {
      await stub.close();
    }
  });
});

describe('Etsy client against the contract stub', () => {
  let stub: EtsyStub;
  let token = '';
  const cfg = () => ({
    ...STUB_APP,
    redirectUri: 'http://cb.test/cb',
    connectUrl: `${stub.url}/oauth/connect`,
    tokenUrl: `${stub.url}/v3/public/oauth/token`,
    apiBaseUrl: stub.url,
  });

  beforeAll(async () => {
    stub = await startEtsyStub({ listingCount: 150 });
    const pkce = createPkcePair();
    const res = await fetch(
      buildAuthorizeUrl(cfg(), { state: 'x', codeChallenge: pkce.challenge }),
      { redirect: 'manual' },
    );
    const code = new URL(res.headers.get('location')!).searchParams.get('code')!;
    await expect(
      exchangeAuthorizationCode(cfg(), {
        code,
        codeVerifier: 'wrong-verifier-wrong-verifier-wrong-verifier-1',
      }),
    ).rejects.toThrow(/PKCE/);
    const res2 = await fetch(
      buildAuthorizeUrl(cfg(), { state: 'x', codeChallenge: pkce.challenge }),
      { redirect: 'manual' },
    );
    const code2 = new URL(res2.headers.get('location')!).searchParams.get('code')!;
    const t = await exchangeAuthorizationCode(cfg(), { code: code2, codeVerifier: pkce.verifier });
    expect(t.userId).toBe('77001');
    expect(t.expiresAt.getTime() - Date.now()).toBeGreaterThan(3500_000);
    token = t.accessToken;
    const r = await refreshAccessToken(cfg(), t.refreshToken);
    token = r.accessToken;
    await expect(refreshAccessToken(cfg(), t.refreshToken)).rejects.toThrow(/invalid_grant/); // rotated
  });
  afterAll(() => stub.close());

  it('paginates (limit 100) and retries after 429 using retry-after', async () => {
    const sleeps: number[] = [];
    const client = new EtsyClient({
      app: cfg(),
      getAccessToken: async () => token,
      sleep: async (ms) => void sleeps.push(ms),
    });
    stub.rateLimitNext(2);
    const ids: number[] = [];
    for await (const l of client.iterateListings(STUB_SHOP_ID, 'active')) ids.push(l.listing_id);
    expect(ids).toHaveLength(149);
    expect(new Set(ids).size).toBe(149);
    expect(sleeps).toEqual([0, 0]);
    expect(stub.calls.filter((c) => c.status === 429)).toHaveLength(2);
  });

  it('sends form-urlencoded PATCH with comma separated tags', async () => {
    const client = new EtsyClient({ app: cfg(), getAccessToken: async () => token });
    const updated = await client.updateListing(STUB_SHOP_ID, 900001, {
      title: 'New title',
      tags: ['a b', 'c'],
    });
    expect(updated.title).toBe('New title');
    expect(stub.listings.get(900001)!.tags).toEqual(['a b', 'c']);
  });

  it('surfaces 401 as an auth error without leaking the token', async () => {
    const client = new EtsyClient({
      app: cfg(),
      getAccessToken: async () => '77001.bogus',
      maxRetries: 0,
    });
    const err = await client.getMe().catch((e) => e);
    expect(err).toBeInstanceOf(EtsyApiError);
    expect(err.isAuthError).toBe(true);
    expect(String(err.message)).not.toContain('bogus');
  });

  it('rejects a wrong x-api-key', async () => {
    const client = new EtsyClient({
      app: { ...cfg(), sharedSecret: 'wrong' },
      getAccessToken: async () => token,
      maxRetries: 0,
    });
    await expect(client.getMe()).rejects.toMatchObject({ status: 403 });
  });
});

describe('TokenCipher key rotation', () => {
  it('decrypts values written with a previous key version', () => {
    const k1 = Buffer.alloc(32, 1).toString('base64');
    const k2 = Buffer.alloc(32, 2).toString('base64');
    const old = new TokenCipher(1, { 1: k1 }).encrypt('secret', 'a');
    const rotated = TokenCipher.fromEnv({
      TOKEN_ENCRYPTION_KEY: k2,
      TOKEN_ENCRYPTION_KEY_VERSION: 2,
      TOKEN_ENCRYPTION_PREVIOUS_KEYS: `1:${k1}`,
    });
    expect(rotated.decrypt(old, 'a')).toBe('secret');
    expect(TokenCipher.versionOf(rotated.encrypt('x', 'a'))).toBe(2);
  });
});

describe('listing change validation (Etsy rules)', () => {
  it('accepts a valid change', () => {
    expect(
      listingChangeRequestSchema.safeParse({
        title: 'Personalized Mug – Gift for Mom',
        tags: ['mug', "mother's day"],
        reason: 'SEO',
      }).success,
    ).toBe(true);
  });
  it.each([
    [{ title: 'x'.repeat(141), reason: 'seo' }],
    [{ title: 'Sale 50% off 100% cotton', reason: 'seo' }],
    [{ title: 'Gift Mug 🎁', reason: 'seo' }],
    [{ tags: Array.from({ length: 14 }, (_, i) => `t${i}`), reason: 'seo' }],
    [{ tags: ['this tag is far too long'], reason: 'seo' }],
    [{ tags: ['mug', 'MUG'], reason: 'seo' }],
    [{ tags: ['bad#tag'], reason: 'seo' }],
    [{ state: 'draft', reason: 'seo' }],
    [{ reason: 'only a reason' }],
    [{ title: 'ok', reason: 'x' }],
  ])('rejects %j', (input) => {
    expect(listingChangeRequestSchema.safeParse(input).success).toBe(false);
  });
});
