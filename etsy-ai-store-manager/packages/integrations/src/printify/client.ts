/**
 * Printify API client — verified against https://developers.printify.com/ (2026-11-25).
 *  - Base https://api.printify.com/v1/, JSON, paths end with .json
 *  - Authorization: Bearer <personal access token>; User-Agent required
 *  - Limits: 600 req/min global, catalog +100 req/min, publish 200 / 30 min; 429 on exceed
 *  - Money: integer cents
 */
import { createHmac, timingSafeEqual } from 'node:crypto';

export const PRINTIFY_DEFAULT_BASE_URL = 'https://api.printify.com';
export const PRINTIFY_USER_AGENT = 'EtsyAIStoreManager/0.1 (Node.js)';

export interface PrintifyShop {
  id: number;
  title: string;
  sales_channel: string;
}

export interface PrintifyBlueprint {
  id: number;
  title: string;
  description: string;
  brand: string;
  model: string;
  images: string[];
}

export interface PrintifyProvider {
  id: number;
  title: string;
  production_time?: { average: number; unit: string } | null;
  location?: { country?: string; region?: string; city?: string } | null;
}

export interface PrintifyCatalogVariant {
  id: number;
  title: string;
  options: Record<string, string>;
  placeholders: Array<{
    position: string;
    height: number;
    width: number;
    decoration_method?: string;
  }>;
}

export interface PrintifyShippingV1 {
  handling_time: { value: number; unit: string };
  profiles: Array<{
    variant_ids: number[];
    first_item: { cost: number; currency: string };
    additional_items: { cost: number; currency: string };
    countries: string[];
  }>;
}

export interface PrintifyProductVariant {
  id: number;
  sku?: string;
  cost: number;
  price: number;
  title: string;
  grams?: number;
  is_enabled: boolean;
  is_default?: boolean;
  is_available?: boolean;
  options?: number[];
}

export interface PrintifyProduct {
  id: string;
  title: string;
  description: string;
  tags: string[];
  options?: Array<{ name: string; type: string; values: Array<{ id: number; title: string }> }>;
  variants: PrintifyProductVariant[];
  images: Array<{ src: string; variant_ids: number[]; position: string; is_default: boolean }>;
  created_at: string;
  updated_at: string;
  visible: boolean;
  is_locked: boolean;
  blueprint_id: number;
  print_provider_id: number;
  print_areas?: unknown[];
  external?: { id?: string; handle?: string; shipping_template_id?: string } | null;
  shop_id?: number;
}

export interface PrintifyOrderLineItem {
  id?: string;
  product_id: string;
  variant_id: number;
  quantity: number;
  print_provider_id?: number;
  blueprint_id?: number;
  cost: number;
  shipping_cost: number;
  status: string;
  metadata?: {
    title?: string;
    price?: number;
    variant_label?: string;
    sku?: string;
    country?: string;
    external_id?: string;
  };
  sent_to_production_at?: string | null;
  fulfilled_at?: string | null;
}

export interface PrintifyOrder {
  id: string;
  address_to?: { country?: string };
  line_items: PrintifyOrderLineItem[];
  metadata?: {
    order_type?: string;
    shop_order_id?: string | number;
    shop_order_label?: string;
    is_reprint?: boolean;
  };
  total_price: number;
  total_shipping: number;
  total_tax: number;
  status: string;
  shipping_method: number;
  shipments?: Array<{
    carrier: string;
    number: string;
    url: string;
    delivered_at: string | null;
    line_item_ids?: string[];
  }>;
  created_at: string;
  sent_to_production_at?: string | null;
  fulfilled_at?: string | null;
}

export interface PrintifyPage<T> {
  current_page: number;
  last_page: number;
  data: T[];
  total?: number;
}

export class PrintifyApiError extends Error {
  constructor(
    readonly status: number,
    readonly operation: string,
    message: string,
  ) {
    super(`Printify ${operation} failed (${status}): ${message}`);
    this.name = 'PrintifyApiError';
  }
  get isRetryable() {
    return (
      this.status === 429 ||
      this.status === 502 ||
      this.status === 503 ||
      this.status === 500 ||
      this.status === 0
    );
  }
}

export interface PrintifyClientOptions {
  token: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  maxRetries?: number;
  onCall?: (log: {
    method: string;
    endpoint: string;
    status: number | null;
    durationMs: number;
    error?: string;
  }) => void;
}

export class PrintifyClient {
  private readonly base: string;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(private readonly opts: PrintifyClientOptions) {
    this.base = (opts.baseUrl ?? PRINTIFY_DEFAULT_BASE_URL).replace(/\/+$/, '');
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.sleep = opts.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  getShops() {
    return this.request<PrintifyShop[]>('GET', '/v1/shops.json');
  }
  getBlueprints() {
    return this.request<PrintifyBlueprint[]>('GET', '/v1/catalog/blueprints.json');
  }
  getBlueprint(id: number) {
    return this.request<PrintifyBlueprint>('GET', `/v1/catalog/blueprints/${id}.json`);
  }
  getBlueprintProviders(blueprintId: number) {
    return this.request<PrintifyProvider[]>(
      'GET',
      `/v1/catalog/blueprints/${blueprintId}/print_providers.json`,
    );
  }
  getPrintProvider(providerId: number) {
    return this.request<PrintifyProvider>('GET', `/v1/catalog/print_providers/${providerId}.json`);
  }
  getVariants(blueprintId: number, providerId: number) {
    return this.request<{ id: number; title: string; variants: PrintifyCatalogVariant[] }>(
      'GET',
      `/v1/catalog/blueprints/${blueprintId}/print_providers/${providerId}/variants.json`,
    );
  }
  getShipping(blueprintId: number, providerId: number) {
    return this.request<PrintifyShippingV1>(
      'GET',
      `/v1/catalog/blueprints/${blueprintId}/print_providers/${providerId}/shipping.json`,
    );
  }
  listProducts(shopId: number | string, page = 1) {
    return this.request<PrintifyPage<PrintifyProduct>>(
      'GET',
      `/v1/shops/${shopId}/products.json?limit=50&page=${page}`,
    );
  }
  async *iterateProducts(shopId: number | string) {
    for (let page = 1; ; page++) {
      const p = await this.listProducts(shopId, page);
      for (const x of p.data) yield x;
      if (!p.data.length || p.current_page >= p.last_page) break;
    }
  }
  getProduct(shopId: number | string, productId: string) {
    return this.request<PrintifyProduct>('GET', `/v1/shops/${shopId}/products/${productId}.json`);
  }
  createProduct(shopId: number | string, body: Record<string, unknown>) {
    return this.request<PrintifyProduct>('POST', `/v1/shops/${shopId}/products.json`, body);
  }
  updateProduct(shopId: number | string, productId: string, body: Record<string, unknown>) {
    return this.request<PrintifyProduct>(
      'PUT',
      `/v1/shops/${shopId}/products/${productId}.json`,
      body,
    );
  }
  /** Sends the product to the connected sales channel (Etsy). Returns {} — the listing id arrives later on product.external. */
  publishProduct(
    shopId: number | string,
    productId: string,
    fields = {
      title: true,
      description: true,
      images: true,
      variants: true,
      tags: true,
      keyFeatures: true,
      shipping_template: true,
    },
  ) {
    return this.request<Record<string, never>>(
      'POST',
      `/v1/shops/${shopId}/products/${productId}/publish.json`,
      fields,
    );
  }
  uploadImageByUrl(fileName: string, url: string) {
    return this.request<{
      id: string;
      file_name: string;
      height: number;
      width: number;
      preview_url: string;
    }>('POST', '/v1/uploads/images.json', { file_name: fileName, url });
  }
  uploadImageBase64(fileName: string, contents: string) {
    return this.request<{
      id: string;
      file_name: string;
      height: number;
      width: number;
      preview_url: string;
    }>('POST', '/v1/uploads/images.json', { file_name: fileName, contents });
  }
  listOrders(shopId: number | string, page = 1) {
    return this.request<PrintifyPage<PrintifyOrder>>(
      'GET',
      `/v1/shops/${shopId}/orders.json?limit=50&page=${page}`,
    );
  }
  async *iterateOrders(shopId: number | string, maxPages = 20) {
    for (let page = 1; page <= maxPages; page++) {
      const p = await this.listOrders(shopId, page);
      for (const x of p.data) yield x;
      if (!p.data.length || p.current_page >= p.last_page) break;
    }
  }
  getOrder(shopId: number | string, orderId: string) {
    return this.request<PrintifyOrder>('GET', `/v1/shops/${shopId}/orders/${orderId}.json`);
  }
  /** Shipping quote in cents per method: {standard, express, priority, printify_express, economy} */
  calculateShipping(
    shopId: number | string,
    body: { line_items: unknown[]; address_to: Record<string, string> },
  ) {
    return this.request<Record<string, number>>(
      'POST',
      `/v1/shops/${shopId}/orders/shipping.json`,
      body,
    );
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const endpoint = `${method} ${path
      .split('?')[0]!
      .replace(/\/[0-9a-f]{24}(?=[/.])/g, '/{id}')
      .replace(/\/\d+(?=[/.])/g, '/{id}')}`;
    const max = this.opts.maxRetries ?? 3;
    for (let attempt = 0; ; attempt++) {
      const started = Date.now();
      let res: Response;
      try {
        res = await this.fetchImpl(this.base + path, {
          method,
          headers: {
            Authorization: `Bearer ${this.opts.token}`,
            'User-Agent': PRINTIFY_USER_AGENT,
            Accept: 'application/json',
            ...(body !== undefined ? { 'Content-Type': 'application/json;charset=utf-8' } : {}),
          },
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        this.opts.onCall?.({
          method,
          endpoint,
          status: null,
          durationMs: Date.now() - started,
          error: msg,
        });
        if (attempt < max) {
          await this.sleep(500 * 2 ** attempt);
          continue;
        }
        throw new PrintifyApiError(0, endpoint, `network error: ${msg}`);
      }
      const text = await res.text();
      this.opts.onCall?.({
        method,
        endpoint,
        status: res.status,
        durationMs: Date.now() - started,
        ...(res.ok ? {} : { error: text.slice(0, 300) }),
      });
      if (res.ok) return (text ? JSON.parse(text) : {}) as T;
      const err = new PrintifyApiError(res.status, endpoint, safeError(text));
      if (err.isRetryable && attempt < max) {
        const retryAfter = Number(res.headers.get('retry-after'));
        await this.sleep(
          Number.isFinite(retryAfter) && retryAfter >= 0 ? retryAfter * 1000 : 1000 * 2 ** attempt,
        );
        continue;
      }
      throw err;
    }
  }
}

function safeError(text: string): string {
  try {
    const j = JSON.parse(text) as { error?: string; message?: string; errors?: unknown };
    return [j.error ?? j.message, j.errors ? JSON.stringify(j.errors).slice(0, 200) : null]
      .filter(Boolean)
      .join(' ');
  } catch {
    return text.slice(0, 200);
  }
}

/** Integer cents -> exact decimal string ("1999" -> "19.99"). */
export function centsToDecimal(cents: number | null | undefined): string | null {
  if (cents === null || cents === undefined || !Number.isInteger(cents)) return null;
  const neg = cents < 0;
  const s = String(Math.abs(cents)).padStart(3, '0');
  return `${neg ? '-' : ''}${s.slice(0, -2)}.${s.slice(-2)}`;
}

/**
 * Verifies the X-Pfy-Signature header ("sha256=<hex>") = HMAC-SHA256(secret, raw body),
 * compared in constant time (as documented).
 */
export function verifyPrintifySignature(
  rawBody: Buffer | string,
  header: string | undefined,
  secret: string,
): boolean {
  if (!header || !secret) return false;
  const [algo, sig] = header.split('=');
  if (algo !== 'sha256' || !sig || !/^[0-9a-f]+$/i.test(sig)) return false;
  const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
  const a = Buffer.from(sig.toLowerCase(), 'hex');
  const b = Buffer.from(expected, 'hex');
  return a.length === b.length && timingSafeEqual(a, b);
}

export const PRINTIFY_WEBHOOK_TOPICS = [
  'shop:disconnected',
  'product:created',
  'product:updated',
  'product:deleted',
  'product:publish:started',
  'order:created',
  'order:updated',
  'order:line-item:canceled',
  'order:sent-to-production',
  'order:shipment:created',
  'order:shipment:delivered',
] as const;

/** Printify order status -> local production status bucket used by the panel. */
export function printifyProductionBucket(
  status: string,
): 'waiting' | 'in_production' | 'shipped' | 'problem' | 'cancelled' {
  switch (status) {
    case 'fulfilled':
    case 'partially-fulfilled':
      return 'shipped';
    case 'in-production':
    case 'sending-to-production':
    case 'sending_to_production_delegate':
    case 'sending_to_production_delegate_sync':
      return 'in_production';
    case 'canceled':
      return 'cancelled';
    case 'has-issues':
    case 'unfulfillable':
    case 'payment-not-received':
    case 'source-check-failed':
      return 'problem';
    default:
      return 'waiting';
  }
}
