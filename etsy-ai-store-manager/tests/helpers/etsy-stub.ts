/**
 * TEST DOUBLE of the Etsy Open API v3 — used only by automated tests.
 * It mirrors the documented contract (OAuth 2.0 + PKCE S256, x-api-key
 * "<keystring>:<shared_secret>", Bearer "<user_id>.<token>", 429 + retry-after,
 * limit/offset paging with max 100, form-urlencoded PATCH, Money objects).
 * It is NOT evidence that the live Etsy API behaves identically; live verification
 * requires real app credentials.
 */
import http from 'node:http';
import { createHash, randomBytes } from 'node:crypto';
import type { AddressInfo } from 'node:net';

export const STUB_APP = { keystring: 'stubkeystring123', sharedSecret: 'stubsharedsecret' };
export const STUB_USER_ID = 77001;
export const STUB_SHOP_ID = 55001;

interface Money {
  amount: number;
  divisor: number;
  currency_code: string;
}
const usd = (cents: number): Money => ({ amount: cents, divisor: 100, currency_code: 'USD' });

export interface StubListing {
  listing_id: number;
  shop_id: number;
  title: string;
  description: string;
  state: string;
  quantity: number;
  url: string;
  num_favorers: number;
  tags: string[];
  materials: string[];
  shipping_profile_id: number | null;
  shop_section_id: number | null;
  taxonomy_id: number;
  who_made: string;
  when_made: string;
  is_supply: boolean;
  price: Money;
  updated_timestamp: number;
  has_variations: boolean;
}

export interface EtsyStub {
  url: string;
  close(): Promise<void>;
  calls: Array<{ method: string; path: string; status: number }>;
  listings: Map<number, StubListing>;
  receipts: Array<Record<string, unknown>>;
  /** next N listing-page requests answer 429 with retry-after: 0 */
  rateLimitNext(n: number): void;
  expireAllAccessTokens(): void;
  revokeAll(): void;
  issuedAccessTokens(): number;
}

export async function startEtsyStub(
  opts: { listingCount?: number; port?: number } = {},
): Promise<EtsyStub> {
  const now = Math.floor(Date.now() / 1000);
  const codes = new Map<string, { challenge: string; redirectUri: string; clientId: string }>();
  const access = new Map<string, number>(); // token -> expiry (ms)
  const refresh = new Set<string>();
  let rateLimitRemaining = 0;
  let issued = 0;
  const calls: EtsyStub['calls'] = [];

  const listings = new Map<number, StubListing>();
  const count = opts.listingCount ?? 102;
  for (let i = 1; i <= count; i++) {
    const id = 900000 + i;
    listings.set(id, {
      listing_id: id,
      shop_id: STUB_SHOP_ID,
      title: `Handmade Ceramic Mug ${i}`,
      description: `Description ${i}`,
      state: i === count ? 'draft' : 'active',
      quantity: 5,
      url: `https://www.etsy.com/listing/${id}/mug-${i}`,
      num_favorers: i,
      tags: ['ceramic mug', 'gift'],
      materials: ['ceramic'],
      shipping_profile_id: 3001,
      shop_section_id: null,
      taxonomy_id: 1062,
      who_made: 'i_did',
      when_made: 'made_to_order',
      is_supply: false,
      price: usd(2450 + i),
      updated_timestamp: now - 1000 + i,
      has_variations: false,
    });
  }

  const receipts: Array<Record<string, unknown>> = [
    receipt(1001, 'paid', true, false, now - 7200, {
      subtotal: usd(4900),
      shipping: usd(599),
      tax: usd(0),
      vat: usd(980),
      discount: usd(490),
      grand: usd(5989),
      transactions: [tx(5001, 900001, 'Handmade Ceramic Mug 1', 2, usd(2451))],
    }),
    receipt(1002, 'completed', true, true, now - 3600, {
      subtotal: usd(2452),
      shipping: usd(0),
      tax: usd(196),
      vat: usd(0),
      discount: usd(0),
      grand: usd(2648),
      transactions: [tx(5002, 900002, 'Handmade Ceramic Mug 2', 1, usd(2452))],
      shipments: [
        {
          receipt_shipping_id: 1,
          carrier_name: 'usps',
          tracking_code: '9400TEST',
          shipment_notification_timestamp: now - 1800,
        },
      ],
      refunds: [
        {
          amount: usd(500),
          created_timestamp: now - 600,
          reason: 'damaged',
          note_from_issuer: null,
          status: 'COMPLETED',
        },
      ],
    }),
    receipt(1003, 'canceled', false, false, now - 600, {
      subtotal: usd(2453),
      shipping: usd(0),
      tax: usd(0),
      vat: usd(0),
      discount: usd(0),
      grand: usd(2453),
      transactions: [tx(5003, 900003, 'Handmade Ceramic Mug 3', 1, usd(2453))],
    }),
  ];

  function issueTokens() {
    issued++;
    const at = `${STUB_USER_ID}.${randomBytes(24).toString('base64url')}`;
    const rt = `${STUB_USER_ID}.${randomBytes(24).toString('base64url')}`;
    access.set(at, Date.now() + 3600_000);
    refresh.add(rt);
    return {
      access_token: at,
      token_type: 'Bearer',
      expires_in: 3600,
      refresh_token: rt,
      scope: 'shops_r listings_r listings_w transactions_r',
    };
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://stub');
    const body = await readBody(req);
    const send = (status: number, json: unknown, headers: Record<string, string> = {}) => {
      calls.push({ method: req.method ?? '', path: url.pathname, status });
      res.writeHead(status, { 'content-type': 'application/json', ...headers });
      res.end(JSON.stringify(json));
    };

    // ---- test-only inspection endpoint (not part of Etsy's API) ----
    const dbg = url.pathname.match(/^\/__test\/listings\/(\d+)$/);
    if (req.method === 'GET' && dbg) return send(200, listings.get(Number(dbg[1])) ?? null);

    // ---- OAuth consent (auto-approves, like a user clicking "Allow access") ----
    if (req.method === 'GET' && url.pathname === '/oauth/connect') {
      const p = url.searchParams;
      const required = [
        'response_type',
        'client_id',
        'redirect_uri',
        'scope',
        'state',
        'code_challenge',
        'code_challenge_method',
      ];
      if (
        required.some((k) => !p.get(k)) ||
        p.get('response_type') !== 'code' ||
        p.get('code_challenge_method') !== 'S256' ||
        p.get('client_id') !== STUB_APP.keystring
      ) {
        return send(400, { error: 'invalid_request' });
      }
      const code = randomBytes(16).toString('hex');
      codes.set(code, {
        challenge: p.get('code_challenge')!,
        redirectUri: p.get('redirect_uri')!,
        clientId: p.get('client_id')!,
      });
      calls.push({ method: 'GET', path: url.pathname, status: 302 });
      res.writeHead(302, {
        location: `${p.get('redirect_uri')}?code=${code}&state=${encodeURIComponent(p.get('state')!)}`,
      });
      return res.end();
    }

    // ---- Token endpoint ----
    if (req.method === 'POST' && url.pathname === '/v3/public/oauth/token') {
      if (!String(req.headers['content-type']).startsWith('application/x-www-form-urlencoded'))
        return send(400, { error: 'invalid_request' });
      const f = new URLSearchParams(body);
      if (f.get('client_id') !== STUB_APP.keystring) return send(401, { error: 'invalid_client' });
      if (f.get('grant_type') === 'authorization_code') {
        const c = codes.get(f.get('code') ?? '');
        if (!c) return send(400, { error: 'invalid_grant', error_description: 'code not found' });
        codes.delete(f.get('code')!);
        const challenge = createHash('sha256')
          .update(f.get('code_verifier') ?? '')
          .digest('base64url');
        if (challenge !== c.challenge)
          return send(400, {
            error: 'invalid_grant',
            error_description: 'PKCE verification failed',
          });
        if (f.get('redirect_uri') && f.get('redirect_uri') !== c.redirectUri)
          return send(400, { error: 'invalid_grant' });
        return send(200, issueTokens());
      }
      if (f.get('grant_type') === 'refresh_token') {
        const rt = f.get('refresh_token') ?? '';
        if (!refresh.has(rt))
          return send(400, { error: 'invalid_grant', error_description: 'refresh token invalid' });
        refresh.delete(rt);
        return send(200, issueTokens());
      }
      return send(400, { error: 'unsupported_grant_type' });
    }

    // ---- Application API: auth ----
    if (url.pathname.startsWith('/v3/application/')) {
      if (req.headers['x-api-key'] !== `${STUB_APP.keystring}:${STUB_APP.sharedSecret}`)
        return send(403, { error: 'Invalid API key' });
      // public marketplace search: API key only, no OAuth token (findAllListingsActive)
      if (req.method === 'GET' && url.pathname === '/v3/application/listings/active') {
        const kw = (url.searchParams.get('keywords') ?? '').toLowerCase();
        const limit = Number(url.searchParams.get('limit') ?? 25);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        if (!kw) return send(400, { error: 'keywords required' });
        if (limit > 100) return send(400, { error: 'limit max 100' });
        const nowTs = Math.floor(Date.now() / 1000);
        const all = Array.from({ length: 150 }, (_, i) => ({
          listing_id: 700000 + i,
          shop_id: 9000 + (i % 40),
          title: `${kw} design ${i}`,
          description: '',
          state: 'active',
          quantity: 10,
          url: `https://www.etsy.com/listing/${700000 + i}`,
          num_favorers: (i % 10) * 5,
          tags: [kw, 'gift', i % 2 ? 'personalized' : 'funny'],
          materials: [],
          shipping_profile_id: null,
          shop_section_id: null,
          taxonomy_id: 1,
          who_made: 'i_did',
          when_made: 'made_to_order',
          is_supply: false,
          price:
            i % 15 === 0
              ? { amount: 2000 + i * 10, divisor: 100, currency_code: 'EUR' }
              : { amount: 1500 + i * 10, divisor: 100, currency_code: 'USD' },
          updated_timestamp: nowTs,
          created_timestamp: nowTs - (i % 3) * 60 * 86400,
          has_variations: false,
        }));
        return send(200, { count: 12500, results: all.slice(offset, offset + limit) });
      }
      const auth = String(req.headers.authorization ?? '');
      const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
      const exp = access.get(token);
      if (!exp || exp < Date.now() || !token.startsWith(`${STUB_USER_ID}.`))
        return send(401, { error: 'invalid_token' });
      const rl = {
        'x-limit-per-second': '10',
        'x-remaining-this-second': '9',
        'x-limit-per-day': '10000',
        'x-remaining-today': '9990',
      };

      if (req.method === 'GET' && url.pathname === '/v3/application/users/me')
        return send(200, { user_id: STUB_USER_ID, shop_id: STUB_SHOP_ID }, rl);
      if (req.method === 'GET' && url.pathname === `/v3/application/shops/${STUB_SHOP_ID}`) {
        return send(
          200,
          {
            shop_id: STUB_SHOP_ID,
            user_id: STUB_USER_ID,
            shop_name: 'StubCeramics',
            title: 'Stub Ceramics',
            announcement: null,
            currency_code: 'USD',
            url: 'https://www.etsy.com/shop/StubCeramics',
            is_vacation: false,
            listing_active_count: count - 1,
            num_favorers: 10,
            languages: ['en-US'],
            icon_url_fullxfull: null,
            image_url_760x100: null,
            review_count: 3,
            review_average: 4.7,
            transaction_sold_count: 12,
            shop_location_country_iso: 'US',
          },
          rl,
        );
      }
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/listings`
      ) {
        if (rateLimitRemaining > 0) {
          rateLimitRemaining--;
          return send(429, { error: 'Rate limit exceeded' }, { 'retry-after': '0' });
        }
        const limit = Number(url.searchParams.get('limit') ?? 25);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        if (limit < 1 || limit > 100)
          return send(400, { error: 'limit must be between 1 and 100' });
        const state = url.searchParams.get('state') ?? 'active';
        const all = [...listings.values()].filter((l) => l.state === state);
        const withImages = (url.searchParams.get('includes') ?? '').split(',').includes('Images');
        const results = all.slice(offset, offset + limit).map((l) =>
          withImages
            ? {
                ...l,
                images: [
                  {
                    listing_image_id: l.listing_id * 10,
                    url_fullxfull: `https://i.etsystatic.com/${l.listing_id}.jpg`,
                    rank: 1,
                    alt_text: null,
                  },
                ],
              }
            : l,
        );
        return send(200, { count: all.length, results }, rl);
      }
      const lm = url.pathname.match(/^\/v3\/application\/listings\/(\d+)$/);
      if (req.method === 'GET' && lm) {
        const l = listings.get(Number(lm[1]));
        return l ? send(200, l, rl) : send(404, { error: 'listing not found' });
      }
      const um = url.pathname.match(
        new RegExp(`^/v3/application/shops/${STUB_SHOP_ID}/listings/(\\d+)$`),
      );
      if (req.method === 'PATCH' && um) {
        if (!String(req.headers['content-type']).startsWith('application/x-www-form-urlencoded'))
          return send(400, { error: 'expected form body' });
        const l = listings.get(Number(um[1]));
        if (!l) return send(404, { error: 'listing not found' });
        const f = new URLSearchParams(body);
        if (f.has('title')) l.title = f.get('title')!;
        if (f.has('description')) l.description = f.get('description')!;
        if (f.has('tags'))
          l.tags = f
            .get('tags')!
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean);
        if (f.has('materials'))
          l.materials = f
            .get('materials')!
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean);
        if (f.has('state')) {
          const s = f.get('state')!;
          if (!['active', 'inactive'].includes(s))
            return send(400, { error: 'state must be active or inactive' });
          l.state = s;
        }
        l.updated_timestamp = Math.floor(Date.now() / 1000);
        return send(200, l, rl);
      }
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/receipts`
      ) {
        const limit = Number(url.searchParams.get('limit') ?? 25);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        const minLm = Number(url.searchParams.get('min_last_modified') ?? 0);
        const all = receipts.filter((r) => (r.updated_timestamp as number) >= minLm);
        return send(200, { count: all.length, results: all.slice(offset, offset + limit) }, rl);
      }
      return send(404, { error: 'not found' });
    }
    send(404, { error: 'not found' });
  });

  await new Promise<void>((r) => server.listen(opts.port ?? 0, '127.0.0.1', r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((r) => server.close(() => r())),
    calls,
    listings,
    receipts,
    rateLimitNext: (n) => {
      rateLimitRemaining = n;
    },
    expireAllAccessTokens: () => {
      for (const k of access.keys()) access.set(k, 0);
    },
    revokeAll: () => {
      access.clear();
      refresh.clear();
    },
    issuedAccessTokens: () => issued,
  };
}

function receipt(
  id: number,
  status: string,
  isPaid: boolean,
  isShipped: boolean,
  ts: number,
  m: {
    subtotal: Money;
    shipping: Money;
    tax: Money;
    vat: Money;
    discount: Money;
    grand: Money;
    transactions: unknown[];
    shipments?: unknown[];
    refunds?: unknown[];
  },
) {
  return {
    receipt_id: id,
    receipt_type: 0,
    seller_user_id: STUB_USER_ID,
    buyer_user_id: 880000 + id,
    name: `Buyer ${id}`,
    country_iso: id === 1001 ? 'DE' : 'US',
    status,
    is_paid: isPaid,
    is_shipped: isShipped,
    created_timestamp: ts,
    updated_timestamp: ts + 60,
    buyer_email: `buyer${id}@example.test`,
    grandtotal: m.grand,
    subtotal: m.subtotal,
    total_price: m.subtotal,
    total_shipping_cost: m.shipping,
    total_tax_cost: m.tax,
    total_vat_cost: m.vat,
    discount_amt: m.discount,
    gift_wrap_price: usd(0),
    shipments: m.shipments ?? [],
    transactions: m.transactions,
    refunds: m.refunds ?? [],
  };
}

function tx(id: number, listingId: number, title: string, quantity: number, price: Money) {
  return {
    transaction_id: id,
    listing_id: listingId,
    product_id: id * 3,
    sku: `SKU-${listingId}`,
    title,
    quantity,
    price,
    shipping_cost: usd(0),
    is_digital: false,
    variations: [],
  };
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let data = '';
    req.on('data', (c) => (data += c));
    req.on('end', () => resolve(data));
  });
}
