import { ETSY_DEFAULTS, etsyApiKeyHeader, type EtsyAppConfig } from './config.js';
import { EtsyApiError } from './errors.js';
import type { EtsyMoney } from './money.js';

/* ---------- Response types (subset of the official OpenAPI schemas) ---------- */

export interface EtsySelf {
  user_id: number;
  shop_id: number;
}

export interface EtsyShop {
  shop_id: number;
  user_id: number;
  shop_name: string;
  title: string | null;
  announcement: string | null;
  currency_code: string;
  url: string;
  is_vacation: boolean;
  listing_active_count: number;
  num_favorers: number;
  languages: string[];
  icon_url_fullxfull: string | null;
  image_url_760x100: string | null;
  review_count: number | null;
  review_average: number | null;
  transaction_sold_count: number;
  shop_location_country_iso: string | null;
}

export type EtsyListingState = 'active' | 'inactive' | 'sold_out' | 'draft' | 'removed' | 'expired';

export interface EtsyListing {
  listing_id: number;
  shop_id: number;
  title: string;
  description: string;
  state: EtsyListingState | string;
  quantity: number;
  url: string;
  num_favorers: number;
  views?: number;
  tags: string[];
  materials: string[];
  shipping_profile_id: number | null;
  shop_section_id: number | null;
  taxonomy_id: number | null;
  who_made: string | null;
  when_made: string | null;
  is_supply: boolean | null;
  price: EtsyMoney;
  updated_timestamp: number;
  created_timestamp?: number;
  last_modified_timestamp?: number;
  has_variations: boolean;
  images?: Array<{
    listing_image_id: number;
    url_fullxfull: string;
    rank: number;
    alt_text: string | null;
  }>;
  [key: string]: unknown;
}

export interface EtsyTransaction {
  transaction_id: number;
  listing_id: number | null;
  product_id: number | null;
  sku: string | null;
  title: string;
  quantity: number;
  price: EtsyMoney;
  shipping_cost: EtsyMoney;
  is_digital: boolean;
  variations: Array<{ formatted_name: string; formatted_value: string }>;
}

export interface EtsyReceipt {
  receipt_id: number;
  buyer_user_id: number | null;
  name: string | null;
  country_iso: string | null;
  status: string;
  is_paid: boolean;
  is_shipped: boolean;
  created_timestamp: number;
  updated_timestamp: number;
  grandtotal: EtsyMoney;
  subtotal: EtsyMoney;
  total_price: EtsyMoney;
  total_shipping_cost: EtsyMoney;
  total_tax_cost: EtsyMoney;
  total_vat_cost: EtsyMoney;
  discount_amt: EtsyMoney;
  gift_wrap_price?: EtsyMoney;
  shipments: Array<{
    receipt_shipping_id: number | null;
    carrier_name: string | null;
    tracking_code: string | null;
    shipment_notification_timestamp: number | null;
  }>;
  transactions: EtsyTransaction[];
  refunds: Array<{
    amount: EtsyMoney;
    created_timestamp: number;
    reason: string | null;
    status: string | null;
  }>;
  [key: string]: unknown;
}

export interface EtsyTaxonomyNode {
  id: number;
  level: number;
  name: string;
  parent_id: number | null;
  children: EtsyTaxonomyNode[];
  full_path_taxonomy_ids: number[];
}

export interface EtsyLedgerEntry {
  entry_id: number;
  ledger_id: number;
  sequence_number: number;
  amount: number;
  currency: string;
  description: string;
  balance: number;
  create_date: number;
  created_timestamp?: number;
  ledger_type: string;
  reference_type: string;
  reference_id: string | null;
}

export interface EtsyListingTranslation {
  listing_id: number;
  language: string;
  title: string | null;
  description: string | null;
  tags: string[];
}

/** Fields of createDraftListing this platform sends (required ones are non-optional). */
export interface EtsyDraftListingInput {
  quantity: number;
  title: string;
  description: string;
  price: number;
  who_made: 'i_did' | 'someone_else' | 'collective';
  when_made: string;
  taxonomy_id: number;
  is_supply: boolean;
  type?: 'physical' | 'download' | 'both';
  shipping_profile_id?: number;
  return_policy_id?: number;
  tags?: string[];
  materials?: string[];
  production_partner_ids?: number[];
  processing_min?: number;
  processing_max?: number;
  readiness_state_id?: number;
}

interface Paged<T> {
  count: number;
  results: T[];
}

/** Fields accepted by updateListing (PATCH, form-urlencoded) that this platform edits. */
export interface EtsyListingPatch {
  title?: string;
  description?: string;
  tags?: string[];
  materials?: string[];
  state?: 'active' | 'inactive';
  shop_section_id?: number;
  shipping_profile_id?: number;
}

export interface EtsyCallLog {
  method: string;
  endpoint: string;
  status: number | null;
  durationMs: number;
  error?: string;
  rateLimitRemaining?: number | null;
}

export interface EtsyClientOptions {
  app: Pick<EtsyAppConfig, 'keystring' | 'sharedSecret' | 'apiBaseUrl'>;
  /** Returns the current "<user_id>.<token>" access token (refreshing if needed). */
  getAccessToken: () => Promise<string>;
  fetchImpl?: typeof fetch;
  onCall?: (log: EtsyCallLog) => void;
  maxRetries?: number;
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Minimal, typed Etsy Open API v3 client.
 *  - Sends x-api-key "<keystring>:<shared_secret>" and Bearer "<user_id>.<token>".
 *  - Honours 429 + retry-after, retries 5xx with exponential backoff.
 *  - Pauses when x-remaining-this-second reaches 0.
 *  - Logs every call (no bodies/tokens) through onCall.
 */
export class EtsyClient {
  private readonly base: string;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly maxRetries: number;

  constructor(private readonly opts: EtsyClientOptions) {
    this.base = (opts.app.apiBaseUrl ?? ETSY_DEFAULTS.apiBaseUrl).replace(/\/+$/, '');
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.sleep = opts.sleep ?? defaultSleep;
    this.maxRetries = opts.maxRetries ?? 3;
  }

  getMe(): Promise<EtsySelf> {
    return this.request('GET', '/v3/application/users/me');
  }

  getShop(shopId: number | string): Promise<EtsyShop> {
    return this.request('GET', `/v3/application/shops/${shopId}`);
  }

  getListingsByShop(
    shopId: number | string,
    q: { state: EtsyListingState; limit?: number; offset?: number; includes?: string[] },
  ): Promise<Paged<EtsyListing>> {
    return this.request('GET', `/v3/application/shops/${shopId}/listings`, {
      query: {
        state: q.state,
        limit: String(q.limit ?? 100),
        offset: String(q.offset ?? 0),
        ...(q.includes?.length ? { includes: q.includes.join(',') } : {}),
      },
    });
  }

  /** Iterates all pages (limit 100 = documented maximum). */
  async *iterateListings(shopId: number | string, state: EtsyListingState, includes?: string[]) {
    let offset = 0;
    for (;;) {
      const page = await this.getListingsByShop(shopId, { state, offset, limit: 100, includes });
      for (const l of page.results) yield l;
      offset += page.results.length;
      if (page.results.length === 0 || offset >= page.count) break;
    }
  }

  getListing(listingId: number | string, includes?: string[]): Promise<EtsyListing> {
    return this.request('GET', `/v3/application/listings/${listingId}`, {
      query: includes?.length ? { includes: includes.join(',') } : undefined,
    });
  }

  updateListing(
    shopId: number | string,
    listingId: number | string,
    patch: EtsyListingPatch,
  ): Promise<EtsyListing> {
    const form = new URLSearchParams();
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) continue;
      form.set(k, Array.isArray(v) ? v.join(',') : String(v));
    }
    return this.request('PATCH', `/v3/application/shops/${shopId}/listings/${listingId}`, {
      form,
    });
  }

  getShopReceipts(
    shopId: number | string,
    q: {
      limit?: number;
      offset?: number;
      minLastModified?: number;
      sortOn?: 'created' | 'updated' | 'receipt_id';
    },
  ): Promise<Paged<EtsyReceipt>> {
    return this.request('GET', `/v3/application/shops/${shopId}/receipts`, {
      query: {
        limit: String(q.limit ?? 100),
        offset: String(q.offset ?? 0),
        sort_on: q.sortOn ?? 'updated',
        sort_order: 'asc',
        ...(q.minLastModified !== undefined
          ? { min_last_modified: String(q.minLastModified) }
          : {}),
      },
    });
  }

  async *iterateReceipts(shopId: number | string, minLastModified?: number) {
    let offset = 0;
    for (;;) {
      const page = await this.getShopReceipts(shopId, { offset, limit: 100, minLastModified });
      for (const r of page.results) yield r;
      offset += page.results.length;
      if (page.results.length === 0 || offset >= page.count) break;
    }
  }

  /**
   * Public marketplace search (findAllListingsActive). Needs only the API key —
   * no OAuth token — so it works for market research on any keyword.
   */
  findActiveListings(q: {
    keywords: string;
    limit?: number;
    offset?: number;
    sortOn?: 'created' | 'price' | 'updated' | 'score';
    currency?: string;
    buyerCountry?: string;
  }): Promise<Paged<EtsyListing>> {
    return this.request(
      'GET',
      '/v3/application/listings/active',
      {
        query: {
          keywords: q.keywords,
          limit: String(q.limit ?? 100),
          offset: String(q.offset ?? 0),
          sort_on: q.sortOn ?? 'score',
          ...(q.sortOn && q.sortOn !== 'score' ? { sort_order: 'desc' } : {}),
          ...(q.currency ? { currency: q.currency } : {}),
          ...(q.buyerCountry ? { buyer_country: q.buyerCountry } : {}),
        },
      },
      false,
    );
  }

  getShopShippingProfiles(
    shopId: number | string,
  ): Promise<Paged<{ shipping_profile_id: number; title: string }>> {
    return this.request('GET', `/v3/application/shops/${shopId}/shipping-profiles`);
  }

  /** Payment-account ledger entries (transactions_r); amounts are in currency subunits per Etsy. */
  getLedgerEntries(
    shopId: number | string,
    q: { minCreated: number; maxCreated: number; limit?: number; offset?: number },
  ): Promise<Paged<EtsyLedgerEntry>> {
    return this.request('GET', `/v3/application/shops/${shopId}/payment-account/ledger-entries`, {
      query: {
        min_created: String(q.minCreated),
        max_created: String(q.maxCreated),
        limit: String(q.limit ?? 100),
        offset: String(q.offset ?? 0),
      },
    });
  }

  /** Seller taxonomy tree (public data; API key only). */
  getSellerTaxonomyNodes(): Promise<Paged<EtsyTaxonomyNode>> {
    return this.request('GET', '/v3/application/seller-taxonomy/nodes', {}, false);
  }

  getShopProductionPartners(
    shopId: number | string,
  ): Promise<Paged<{ production_partner_id: number; partner_name: string; location: string }>> {
    return this.request('GET', `/v3/application/shops/${shopId}/production-partners`);
  }

  getShopReturnPolicies(shopId: number | string): Promise<
    Paged<{
      return_policy_id: number;
      accepts_returns: boolean;
      accepts_exchanges: boolean;
      return_deadline: number | null;
    }>
  > {
    return this.request('GET', `/v3/application/shops/${shopId}/policies/return`);
  }

  /**
   * createDraftListing (listings_w). The listing is created in state "draft": it is not
   * visible to buyers and Etsy charges the listing fee only when it is published.
   */
  createDraftListing(shopId: number | string, input: EtsyDraftListingInput): Promise<EtsyListing> {
    return this.request('POST', `/v3/application/shops/${shopId}/listings`, {
      form: toForm(input as unknown as Record<string, unknown>),
    });
  }

  /** Returns null when the listing has no translation for this language (404). */
  async getListingTranslation(
    shopId: number | string,
    listingId: number | string,
    language: string,
  ): Promise<EtsyListingTranslation | null> {
    try {
      return await this.request(
        'GET',
        `/v3/application/shops/${shopId}/listings/${listingId}/translations/${encodeURIComponent(language)}`,
      );
    } catch (err) {
      if (err instanceof EtsyApiError && err.status === 404) return null;
      throw err;
    }
  }

  /** createListingTranslation (POST) or updateListingTranslation (PUT). */
  saveListingTranslation(
    shopId: number | string,
    listingId: number | string,
    language: string,
    t: { title: string; description: string; tags: string[] },
    exists: boolean,
  ): Promise<EtsyListingTranslation> {
    return this.request(
      exists ? 'PUT' : 'POST',
      `/v3/application/shops/${shopId}/listings/${listingId}/translations/${encodeURIComponent(language)}`,
      { form: toForm(t) },
    );
  }

  private async request<T>(
    method: string,
    path: string,
    opts: { query?: Record<string, string> | undefined; form?: URLSearchParams } = {},
    authenticated = true,
  ): Promise<T> {
    const url = new URL(this.base + path);
    for (const [k, v] of Object.entries(opts.query ?? {})) url.searchParams.set(k, v);
    const endpoint = `${method} ${path.replace(/\/\d+(?=\/|$)/g, '/{id}')}`;

    for (let attempt = 0; ; attempt++) {
      const started = Date.now();
      let res: Response;
      try {
        res = await this.fetchImpl(url, {
          method,
          headers: {
            'x-api-key': etsyApiKeyHeader(this.opts.app),
            ...(authenticated
              ? { Authorization: `Bearer ${await this.opts.getAccessToken()}` }
              : {}),
            Accept: 'application/json',
            ...(opts.form
              ? { 'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8' }
              : {}),
          },
          body: opts.form?.toString(),
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        this.opts.onCall?.({
          method,
          endpoint,
          status: null,
          durationMs: Date.now() - started,
          error: message,
        });
        if (attempt < this.maxRetries) {
          await this.sleep(500 * 2 ** attempt);
          continue;
        }
        throw new EtsyApiError(0, endpoint, `network error: ${message}`);
      }
      const remainingSecond = numHeader(res, 'x-remaining-this-second');
      const remainingToday = numHeader(res, 'x-remaining-today');
      const text = await res.text();
      this.opts.onCall?.({
        method,
        endpoint,
        status: res.status,
        durationMs: Date.now() - started,
        rateLimitRemaining: remainingToday,
        ...(res.ok ? {} : { error: errorText(text) }),
      });

      if (res.ok) {
        if (remainingSecond === 0) await this.sleep(1000);
        return (text ? JSON.parse(text) : null) as T;
      }
      const retryAfter = numHeader(res, 'retry-after');
      const err = new EtsyApiError(res.status, endpoint, errorText(text), retryAfter ?? undefined);
      if (err.isRetryable && attempt < this.maxRetries) {
        await this.sleep(res.status === 429 ? (retryAfter ?? 1) * 1000 : 500 * 2 ** attempt);
        continue;
      }
      throw err;
    }
  }
}

/** Form-urlencoded body; arrays are sent comma-separated (as documented for tags). */
function toForm(o: Record<string, unknown>): URLSearchParams {
  const form = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v)) {
      if (v.length) form.set(k, v.join(','));
      continue;
    }
    form.set(k, String(v));
  }
  return form;
}

function numHeader(res: Response, name: string): number | null {
  const v = res.headers.get(name);
  if (v === null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function errorText(text: string): string {
  try {
    const j = JSON.parse(text) as { error?: string; message?: string };
    return (j.error ?? j.message ?? 'error').slice(0, 300);
  } catch {
    return text.slice(0, 300);
  }
}
