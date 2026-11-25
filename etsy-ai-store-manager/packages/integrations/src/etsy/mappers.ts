import type { EtsyListing, EtsyReceipt } from './client.js';
import { addDecimals, moneyToDecimal } from './money.js';

/** Local listing columns derived from an Etsy listing. `raw` keeps the full payload. */
export function mapListing(l: EtsyListing) {
  return {
    etsyListingId: String(l.listing_id),
    state: normalizeListingState(l.state),
    title: (l.title ?? '').slice(0, 140),
    description: l.description ?? null,
    tags: (l.tags ?? []).slice(0, 13),
    materials: l.materials ?? [],
    taxonomyId: l.taxonomy_id ?? null,
    price: moneyToDecimal(l.price),
    currency: l.price?.currency_code ?? null,
    quantity: l.quantity ?? null,
    shippingProfileId: l.shipping_profile_id ? String(l.shipping_profile_id) : null,
    whoMade: l.who_made ?? null,
    whenMade: l.when_made ?? null,
    isSupply: l.is_supply ?? null,
    numFavorers: l.num_favorers ?? null,
    images: (l.images ?? []).map((i) => ({
      etsyImageId: String(i.listing_image_id),
      url: i.url_fullxfull,
      rank: i.rank,
      altText: i.alt_text,
    })),
    raw: l,
  };
}

const LISTING_STATES = new Set([
  'draft',
  'active',
  'inactive',
  'expired',
  'sold_out',
  'removed',
  'edit',
]);
function normalizeListingState(s: string): string {
  return LISTING_STATES.has(s) ? s : 'inactive';
}

/**
 * Etsy receipt status -> local order status. Receipt `status` enum (OpenAPI):
 * paid, completed, open, payment processing, canceled, fully refunded, partially refunded.
 */
export function mapReceiptStatus(
  r: Pick<EtsyReceipt, 'status' | 'is_paid' | 'is_shipped'>,
): string {
  switch (r.status?.toLowerCase()) {
    case 'canceled':
      return 'cancelled';
    case 'fully refunded':
      return 'refunded';
    case 'partially refunded':
      return 'partially_refunded';
    case 'completed':
      return 'shipped';
    case 'paid':
      return r.is_shipped ? 'shipped' : 'paid';
    default:
      return r.is_shipped ? 'shipped' : r.is_paid ? 'paid' : 'open';
  }
}

/**
 * Receipt -> order + items. Amounts are exact decimal strings.
 * tax_total = total_tax_cost + total_vat_cost (both collected from the buyer).
 * Buyer e-mail is intentionally NOT stored (data minimisation; not needed for operations).
 */
export function mapReceipt(r: EtsyReceipt) {
  const currency = r.grandtotal?.currency_code ?? r.total_price?.currency_code ?? 'USD';
  return {
    etsyReceiptId: String(r.receipt_id),
    status: mapReceiptStatus(r),
    currency,
    subtotal: moneyToDecimal(r.subtotal) ?? '0',
    shippingTotal: moneyToDecimal(r.total_shipping_cost) ?? '0',
    taxTotal: addDecimals(moneyToDecimal(r.total_tax_cost), moneyToDecimal(r.total_vat_cost)),
    discountTotal: moneyToDecimal(r.discount_amt) ?? '0',
    grandTotal: moneyToDecimal(r.grandtotal) ?? '0',
    buyerCountry: r.country_iso && /^[A-Z]{2}$/.test(r.country_iso) ? r.country_iso : null,
    placedAt: new Date(r.created_timestamp * 1000).toISOString(),
    paidAt: r.is_paid ? new Date(r.created_timestamp * 1000).toISOString() : null,
    shippedAt: firstShipmentAt(r),
    customer: r.buyer_user_id
      ? {
          etsyUserId: String(r.buyer_user_id),
          name: r.name ?? null,
          country: r.country_iso ?? null,
        }
      : null,
    items: (r.transactions ?? []).map((t) => ({
      etsyTransactionId: String(t.transaction_id),
      etsyListingId: t.listing_id ? String(t.listing_id) : null,
      sku: t.sku || null,
      title: t.title,
      quantity: t.quantity,
      unitPrice: moneyToDecimal(t.price) ?? '0',
      currency: t.price?.currency_code ?? currency,
    })),
    shipments: (r.shipments ?? []).map((s) => ({
      carrier: s.carrier_name ?? null,
      trackingNumber: s.tracking_code ?? null,
      shippedAt: s.shipment_notification_timestamp
        ? new Date(s.shipment_notification_timestamp * 1000).toISOString()
        : null,
    })),
    refunds: (r.refunds ?? []).map((f) => ({
      amount: moneyToDecimal(f.amount) ?? '0',
      currency: f.amount?.currency_code ?? currency,
      reason: f.reason ?? null,
      createdAt: new Date(f.created_timestamp * 1000).toISOString(),
    })),
    raw: r,
  };
}

function firstShipmentAt(r: EtsyReceipt): string | null {
  const ts = (r.shipments ?? [])
    .map((s) => s.shipment_notification_timestamp)
    .filter((x): x is number => typeof x === 'number')
    .sort((a, b) => a - b)[0];
  return ts ? new Date(ts * 1000).toISOString() : null;
}
