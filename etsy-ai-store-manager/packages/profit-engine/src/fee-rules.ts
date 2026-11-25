/**
 * Etsy fee rules as published in the Etsy Help Center (read 2026-11-25):
 *  - https://help.etsy.com/hc/en-us/articles/115014483627 (fees overview)
 *  - https://help.etsy.com/hc/en-us/articles/115015628847 (payment processing by country)
 *  - https://help.etsy.com/hc/en-us/articles/1500011073202 (regulatory operating fee)
 * The legal policy page (etsy.com/legal/fees) was not reachable from the server
 * (HTTP 403), so these rules are seeded as UNVERIFIED. The owner verifies them in
 * the panel against their own Etsy statement; until then every result carries a warning.
 */
import type { FeeRule } from './engine.js';

const OVERVIEW = 'https://help.etsy.com/hc/en-us/articles/115014483627';
const PROCESSING = 'https://help.etsy.com/hc/en-us/articles/115015628847';
const REGULATORY = 'https://help.etsy.com/hc/en-us/articles/1500011073202';

type Seed = Omit<FeeRule, 'id' | 'verified' | 'storeSpecific'> & { key: string; notes: string };

const proc = (
  country: string,
  rate: string,
  fixed: string,
  cur: string,
  scope: FeeRule['buyerScope'] = 'any',
): Seed => ({
  key: `processing:${country}:${scope}`,
  platform: 'etsy',
  feeType: 'payment_processing',
  rate,
  fixedAmount: fixed,
  fixedCurrency: cur,
  basis: 'order_total_incl_tax',
  country,
  buyerScope: scope,
  sourceUrl: PROCESSING,
  notes:
    'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.',
});

const reg = (country: string, rate: string, notes = ''): Seed => ({
  key: `regulatory:${country}`,
  platform: 'etsy',
  feeType: 'regulatory_operating',
  rate,
  fixedAmount: null,
  fixedCurrency: null,
  basis: 'item_plus_shipping',
  country,
  buyerScope: 'any',
  sourceUrl: REGULATORY,
  notes: `Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden. ${notes}`.trim(),
});

export const ETSY_FEE_RULE_SEEDS: Seed[] = [
  {
    key: 'listing',
    platform: 'etsy',
    feeType: 'listing',
    rate: null,
    fixedAmount: '0.20',
    fixedCurrency: 'USD',
    basis: 'per_listing',
    country: null,
    buyerScope: 'any',
    sourceUrl: OVERVIEW,
    notes:
      'İlan başı 0.20 USD; çok adetli satışta her ek adet için 0.20 USD (otomatik yenileme). Sipariş başına adet × 0.20 olarak modellenir.',
  },
  {
    key: 'transaction',
    platform: 'etsy',
    feeType: 'transaction',
    rate: '0.065',
    fixedAmount: null,
    fixedCurrency: null,
    basis: 'item_plus_shipping',
    country: null,
    buyerScope: 'any',
    sourceUrl: OVERVIEW,
    notes:
      'Toplam sipariş tutarının %6.5’i (kargo ve hediye paketi dahil). Satış vergisinin matraha dahil olup olmadığı kaynakta belirtilmiyor; hariç varsayıldı.',
  },
  {
    key: 'currency_conversion',
    platform: 'etsy',
    feeType: 'currency_conversion',
    rate: '0.025',
    fixedAmount: null,
    fixedCurrency: null,
    basis: 'converted_amount',
    country: null,
    buyerScope: 'any',
    sourceUrl: OVERVIEW,
    notes: 'İlan para birimi ile ödeme hesabı para birimi farklıysa %2.5.',
  },
  {
    key: 'offsite:15',
    platform: 'etsy',
    feeType: 'offsite_ads',
    rate: '0.15',
    fixedAmount: null,
    fixedCurrency: null,
    basis: 'order_total',
    country: null,
    buyerScope: 'any',
    capAmount: '100',
    capCurrency: 'USD',
    tier: '15',
    sourceUrl: OVERVIEW,
    notes: 'Son 365 günde 10.000 USD altı satış: %15; sipariş başı en fazla 100 USD.',
  },
  {
    key: 'offsite:12',
    platform: 'etsy',
    feeType: 'offsite_ads',
    rate: '0.12',
    fixedAmount: null,
    fixedCurrency: null,
    basis: 'order_total',
    country: null,
    buyerScope: 'any',
    capAmount: '100',
    capCurrency: 'USD',
    tier: '12',
    sourceUrl: OVERVIEW,
    notes: 'Son 365 günde en az 10.000 USD satış: %12; sipariş başı en fazla 100 USD.',
  },
  proc('US', '0.03', '0.25', 'USD'),
  proc('GB', '0.04', '0.20', 'GBP'),
  proc('DE', '0.04', '0.30', 'EUR'),
  proc('FR', '0.04', '0.30', 'EUR'),
  proc('ES', '0.04', '0.30', 'EUR'),
  proc('IT', '0.04', '0.30', 'EUR'),
  proc('NL', '0.04', '0.30', 'EUR'),
  proc('CA', '0.03', '0.25', 'CAD', 'domestic'),
  proc('CA', '0.04', '0.25', 'CAD', 'international'),
  proc('AU', '0.03', '0.25', 'AUD', 'domestic'),
  proc('AU', '0.04', '0.25', 'AUD', 'international'),
  proc('TR', '0.065', '14', 'TRY'),
  reg('CA', '0.005'),
  reg('FR', '0.0114'),
  reg('IT', '0.008'),
  reg('IN', '0.0005'),
  reg('ES', '0.0088'),
  reg('TR', '0.0167'),
  reg('GB', '0.0048'),
  reg('VN', '0.0124'),
  reg('HU', '0.0197', 'İki Help Center makalesi Macaristan için çelişkili.'),
];
