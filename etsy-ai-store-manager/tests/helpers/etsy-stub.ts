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
  translations: Map<string, Record<string, unknown>>;
  draftForms: Array<Record<string, string>>;
  shipmentsPosted: Array<Record<string, unknown>>;
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
  const translations = new Map<string, Record<string, unknown>>();
  const draftForms: Array<Record<string, string>> = [];
  const shipmentsPosted: Array<Record<string, unknown>> = [];
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
      scope: 'shops_r listings_r listings_w transactions_r transactions_w',
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
      // reviews (getReviewsByShop): ListingReview has no review id
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/reviews`
      ) {
        const nowTs = Math.floor(Date.now() / 1000);
        const all = [
          {
            shop_id: STUB_SHOP_ID,
            listing_id: 900001,
            rating: 5,
            review: 'Love it!',
            language: 'en',
            create_timestamp: nowTs - 5000,
            created_timestamp: nowTs - 5000,
          },
          {
            shop_id: STUB_SHOP_ID,
            listing_id: 900002,
            rating: 2,
            review: 'The mug arrived chipped and took three weeks.',
            language: 'en',
            create_timestamp: nowTs - 3000,
            created_timestamp: nowTs - 3000,
          },
        ];
        const offset = Number(url.searchParams.get('offset') ?? 0);
        const limit = Number(url.searchParams.get('limit') ?? 25);
        if (limit > 100) return send(400, { error: 'limit max 100' });
        return send(200, { count: all.length, results: all.slice(offset, offset + limit) });
      }
      // seller taxonomy: public, API key only
      if (req.method === 'GET' && url.pathname === '/v3/application/seller-taxonomy/nodes') {
        const leaf = (id: number, name: string, parent: number, path: number[]) => ({
          id,
          level: 2,
          name,
          parent_id: parent,
          children: [],
          full_path_taxonomy_ids: path,
        });
        return send(200, {
          count: 1,
          results: [
            {
              id: 1,
              level: 0,
              name: 'Clothing',
              parent_id: null,
              full_path_taxonomy_ids: [1],
              children: [
                {
                  id: 449,
                  level: 1,
                  name: 'Tops & Tees',
                  parent_id: 1,
                  full_path_taxonomy_ids: [1, 449],
                  children: [leaf(482, 'T-shirts', 449, [1, 449, 482])],
                },
              ],
            },
          ],
        });
      }
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
      // createReceiptShipment (transactions_w, JSON body)
      const shipM = url.pathname.match(
        new RegExp(`^/v3/application/shops/${STUB_SHOP_ID}/receipts/(\\d+)/tracking$`),
      );
      if (req.method === 'POST' && shipM) {
        if (!String(req.headers['content-type']).startsWith('application/json'))
          return send(400, { error: 'expected JSON body' });
        const b = JSON.parse(body || '{}') as { tracking_code?: string; carrier_name?: string };
        const rc = receipts.find((r) => r.receipt_id === Number(shipM[1]));
        if (!rc) return send(404, { error: 'receipt not found' });
        if (!b.tracking_code || !b.carrier_name)
          return send(400, { error: 'tracking_code and carrier_name required' });
        shipmentsPosted.push({ receiptId: Number(shipM[1]), ...b });
        rc.is_shipped = true;
        return send(200, { receipt_id: Number(shipM[1]), is_shipped: true }, rl);
      }
      // payment ledger (transactions_r); amounts in minor units
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/payment-account/ledger-entries`
      ) {
        const min = Number(url.searchParams.get('min_created'));
        const max = Number(url.searchParams.get('max_created'));
        if (!min || !max) return send(400, { error: 'min_created and max_created are required' });
        if (Number(url.searchParams.get('limit') ?? 25) > 100)
          return send(400, { error: 'limit max 100' });
        const nowTs = Math.floor(Date.now() / 1000);
        const mk = (
          id: number,
          type: string,
          amount: number,
          ago: number,
          description: string,
        ) => ({
          entry_id: id,
          ledger_id: 1,
          sequence_number: id,
          amount,
          currency: 'USD',
          description,
          balance: 0,
          create_date: nowTs - ago,
          created_timestamp: nowTs - ago,
          ledger_type: type,
          reference_type: 'shop',
          reference_id: String(STUB_SHOP_ID),
        });
        const all = [
          mk(1, 'PROLIST', -450, 86400, 'Etsy Ads'),
          mk(2, 'PROLIST', -300, 2 * 86400, 'Etsy Ads'),
          mk(3, 'offsite_ads_fee', -380, 86400, 'Offsite Ads fee'),
          mk(4, 'transaction', -65, 86400, 'Transaction fee'),
          mk(5, 'PAYMENT', 2899, 86400, 'Payment'),
        ].filter((e) => e.create_date >= min && e.create_date <= max);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        const limit = Number(url.searchParams.get('limit') ?? 25);
        return send(200, { count: all.length, results: all.slice(offset, offset + limit) }, rl);
      }
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/shipping-profiles`
      )
        return send(
          200,
          { count: 1, results: [{ shipping_profile_id: 3001, title: 'Standard (Printify)' }] },
          rl,
        );
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/policies/return`
      )
        return send(
          200,
          {
            count: 1,
            results: [
              {
                return_policy_id: 4001,
                shop_id: STUB_SHOP_ID,
                accepts_returns: true,
                accepts_exchanges: true,
                return_deadline: 30,
              },
            ],
          },
          rl,
        );
      if (
        req.method === 'GET' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/production-partners`
      )
        return send(
          200,
          {
            count: 1,
            results: [{ production_partner_id: 5001, partner_name: 'Printify', location: 'USA' }],
          },
          rl,
        );
      // createDraftListing (form body; required fields per the OAS schema)
      if (
        req.method === 'POST' &&
        url.pathname === `/v3/application/shops/${STUB_SHOP_ID}/listings`
      ) {
        if (!String(req.headers['content-type']).startsWith('application/x-www-form-urlencoded'))
          return send(400, { error: 'expected form body' });
        const f = new URLSearchParams(body);
        for (const k of [
          'quantity',
          'title',
          'description',
          'price',
          'who_made',
          'when_made',
          'taxonomy_id',
        ])
          if (!f.get(k)) return send(400, { error: `${k} is required` });
        if ((f.get('type') ?? 'physical') === 'physical' && !f.get('shipping_profile_id'))
          return send(400, { error: 'shipping_profile_id is required for physical listings' });
        if (/[^\p{L}\p{Nd}\p{P}\p{Sm}\p{Zs}™©®]/u.test(f.get('title')!))
          return send(400, { error: 'invalid title' });
        const id = 990000 + listings.size;
        const l: StubListing = {
          listing_id: id,
          shop_id: STUB_SHOP_ID,
          title: f.get('title')!,
          description: f.get('description')!,
          state: 'draft',
          quantity: Number(f.get('quantity')),
          url: `https://www.etsy.com/listing/${id}`,
          num_favorers: 0,
          tags: (f.get('tags') ?? '')
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
          materials: (f.get('materials') ?? '')
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
          shipping_profile_id: Number(f.get('shipping_profile_id')) || null,
          shop_section_id: null,
          taxonomy_id: Number(f.get('taxonomy_id')),
          who_made: f.get('who_made')!,
          when_made: f.get('when_made')!,
          is_supply: f.get('is_supply') === 'true',
          price: usd(Math.round(Number(f.get('price')) * 100)),
          updated_timestamp: Math.floor(Date.now() / 1000),
          has_variations: false,
        };
        listings.set(id, l);
        draftForms.push(Object.fromEntries(f));
        return send(201, l, rl);
      }
      const tm = url.pathname.match(
        new RegExp(
          `^/v3/application/shops/${STUB_SHOP_ID}/listings/(\\d+)/translations/([a-z]{2})$`,
        ),
      );
      if (tm) {
        const key = `${tm[1]}:${tm[2]}`;
        if (!listings.has(Number(tm[1]))) return send(404, { error: 'listing not found' });
        if (req.method === 'GET') {
          const t = translations.get(key);
          return t ? send(200, t, rl) : send(404, { error: 'translation not found' });
        }
        if (req.method === 'POST' || req.method === 'PUT') {
          if (req.method === 'POST' && translations.has(key)) return send(409, { error: 'exists' });
          if (req.method === 'PUT' && !translations.has(key))
            return send(404, { error: 'translation not found' });
          const f = new URLSearchParams(body);
          if (!f.get('title') || !f.get('description'))
            return send(400, { error: 'title and description required' });
          const t = {
            listing_id: Number(tm[1]),
            language: tm[2],
            title: f.get('title'),
            description: f.get('description'),
            tags: (f.get('tags') ?? '')
              .split(',')
              .map((x) => x.trim())
              .filter(Boolean),
          };
          translations.set(key, t);
          return send(req.method === 'POST' ? 201 : 200, t, rl);
        }
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
    translations,
    draftForms,
    shipmentsPosted,
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
