/**
 * Etsy Open API v3 constants, verified against the official documentation
 * (developers.etsy.com/documentation/essentials/authentication, /requests, /rate-limits)
 * and the OpenAPI document on 2026-11-25.
 */
export const ETSY_DEFAULTS = {
  connectUrl: 'https://www.etsy.com/oauth/connect',
  tokenUrl: 'https://api.etsy.com/v3/public/oauth/token',
  apiBaseUrl: 'https://openapi.etsy.com',
} as const;

/**
 * Scopes requested for this application. Least privilege for Phase 2:
 *  shops_r (getMe, shipping profiles), listings_r/w (import + edit), transactions_r (receipts).
 *  listings_d / transactions_w are NOT requested yet (delete listings / tracking come later with approval).
 */
export const ETSY_SCOPES = ['shops_r', 'listings_r', 'listings_w', 'transactions_r'] as const;

export interface EtsyAppConfig {
  /** App keystring (client_id). */
  keystring: string;
  /** App shared secret. Only used inside the x-api-key header, never sent to browsers. */
  sharedSecret: string;
  /** Exact registered redirect URI (https, case-sensitive, no trailing slash). */
  redirectUri: string;
  connectUrl?: string;
  tokenUrl?: string;
  apiBaseUrl?: string;
}

/** x-api-key header value: "<keystring>:<shared_secret>" (official requests page). */
export function etsyApiKeyHeader(cfg: Pick<EtsyAppConfig, 'keystring' | 'sharedSecret'>): string {
  return `${cfg.keystring}:${cfg.sharedSecret}`;
}

/**
 * Operations the official API does NOT offer (checked against the OpenAPI document).
 * The platform presents these as approved manual workflows instead of automating them.
 */
export const ETSY_UNSUPPORTED_OPERATIONS = {
  ads_campaigns: 'Etsy Ads kampanya yönetimi Open API v3 içinde yok',
  buyer_messages: 'Alıcı mesajlaşma (conversations) uç noktası yok',
  issue_refund: 'İade başlatma uç noktası yok (iadeler yalnızca okunabilir: receipt.refunds)',
  cancel_order: 'Sipariş iptal uç noktası yok',
  shop_banner_logo:
    'Mağaza banner/logo yükleme uç noktası yok (updateShop yalnızca metin alanları)',
} as const;
