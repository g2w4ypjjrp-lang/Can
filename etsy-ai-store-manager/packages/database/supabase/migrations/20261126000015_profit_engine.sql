-- =============================================================================
-- 0015 Phase 4 — Profit Engine
-- =============================================================================

-- Fee rule extensions
alter table public.fee_rules
  add column seed_key     text,
  add column buyer_scope  text not null default 'any' check (buyer_scope in ('any','domestic','international')),
  add column cap_amount   numeric(12,4) check (cap_amount >= 0),
  add column cap_currency char(3),
  add column tier         text;
create unique index fee_rules_seed_key on public.fee_rules (seed_key) where store_id is null and seed_key is not null;

-- Global Etsy rules from the Etsy Help Center (read 2026-11-25). verified_at stays NULL:
-- the official legal page was not reachable from the server; each store owner verifies
-- them against their own Etsy statement (fee_rule_verifications).
insert into public.fee_rules
  (seed_key, platform, fee_type, rate, fixed_amount, fixed_currency, basis, country, country_scope, buyer_scope,
   cap_amount, cap_currency, tier, source_url, notes, effective_from)
select v.seed_key, v.platform, v.fee_type, v.rate::numeric, v.fixed_amount::numeric, v.fixed_currency, v.basis, v.country,
       v.country_scope, v.buyer_scope, v.cap_amount::numeric, v.cap_currency, v.tier, v.source_url, v.notes, date '2026-11-25'
from (values
  ('listing', 'etsy', 'listing', null, '0.20', 'USD', 'per_listing', null, null, 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115014483627', 'İlan başı 0.20 USD; çok adetli satışta her ek adet için 0.20 USD (otomatik yenileme). Sipariş başına adet × 0.20 olarak modellenir.'),
  ('transaction', 'etsy', 'transaction', '0.065', null, null, 'item_plus_shipping', null, null, 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115014483627', 'Toplam sipariş tutarının %6.5’i (kargo ve hediye paketi dahil). Satış vergisinin matraha dahil olup olmadığı kaynakta belirtilmiyor; hariç varsayıldı.'),
  ('currency_conversion', 'etsy', 'currency_conversion', '0.025', null, null, 'converted_amount', null, null, 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115014483627', 'İlan para birimi ile ödeme hesabı para birimi farklıysa %2.5.'),
  ('offsite:15', 'etsy', 'offsite_ads', '0.15', null, null, 'order_total', null, null, 'any', '100', 'USD', '15', 'https://help.etsy.com/hc/en-us/articles/115014483627', 'Son 365 günde 10.000 USD altı satış: %15; sipariş başı en fazla 100 USD.'),
  ('offsite:12', 'etsy', 'offsite_ads', '0.12', null, null, 'order_total', null, null, 'any', '100', 'USD', '12', 'https://help.etsy.com/hc/en-us/articles/115014483627', 'Son 365 günde en az 10.000 USD satış: %12; sipariş başı en fazla 100 USD.'),
  ('processing:US:any', 'etsy', 'payment_processing', '0.03', '0.25', 'USD', 'order_total_incl_tax', 'US', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:GB:any', 'etsy', 'payment_processing', '0.04', '0.20', 'GBP', 'order_total_incl_tax', 'GB', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:DE:any', 'etsy', 'payment_processing', '0.04', '0.30', 'EUR', 'order_total_incl_tax', 'DE', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:FR:any', 'etsy', 'payment_processing', '0.04', '0.30', 'EUR', 'order_total_incl_tax', 'FR', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:ES:any', 'etsy', 'payment_processing', '0.04', '0.30', 'EUR', 'order_total_incl_tax', 'ES', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:IT:any', 'etsy', 'payment_processing', '0.04', '0.30', 'EUR', 'order_total_incl_tax', 'IT', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:NL:any', 'etsy', 'payment_processing', '0.04', '0.30', 'EUR', 'order_total_incl_tax', 'NL', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:CA:domestic', 'etsy', 'payment_processing', '0.03', '0.25', 'CAD', 'order_total_incl_tax', 'CA', 'bank', 'domestic', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:CA:international', 'etsy', 'payment_processing', '0.04', '0.25', 'CAD', 'order_total_incl_tax', 'CA', 'bank', 'international', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:AU:domestic', 'etsy', 'payment_processing', '0.03', '0.25', 'AUD', 'order_total_incl_tax', 'AU', 'bank', 'domestic', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:AU:international', 'etsy', 'payment_processing', '0.04', '0.25', 'AUD', 'order_total_incl_tax', 'AU', 'bank', 'international', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('processing:TR:any', 'etsy', 'payment_processing', '0.065', '14', 'TRY', 'order_total_incl_tax', 'TR', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/115015628847', 'Toplam satış fiyatı + kargo + uygulanabilir satış vergisi üzerinden (Help Center). Sipariş başı sabit ücret.'),
  ('regulatory:CA', 'etsy', 'regulatory_operating', '0.005', null, null, 'item_plus_shipping', 'CA', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:FR', 'etsy', 'regulatory_operating', '0.0114', null, null, 'item_plus_shipping', 'FR', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:IT', 'etsy', 'regulatory_operating', '0.008', null, null, 'item_plus_shipping', 'IT', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:IN', 'etsy', 'regulatory_operating', '0.0005', null, null, 'item_plus_shipping', 'IN', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:ES', 'etsy', 'regulatory_operating', '0.0088', null, null, 'item_plus_shipping', 'ES', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:TR', 'etsy', 'regulatory_operating', '0.0167', null, null, 'item_plus_shipping', 'TR', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:GB', 'etsy', 'regulatory_operating', '0.0048', null, null, 'item_plus_shipping', 'GB', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:VN', 'etsy', 'regulatory_operating', '0.0124', null, null, 'item_plus_shipping', 'VN', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden.'),
  ('regulatory:HU', 'etsy', 'regulatory_operating', '0.0197', null, null, 'item_plus_shipping', 'HU', 'bank', 'any', null, null, null, 'https://help.etsy.com/hc/en-us/articles/1500011073202', 'Ürün fiyatı + kargo (+ hediye paketi/kişiselleştirme) üzerinden. İki Help Center makalesi Macaristan için çelişkili.')
) as v(seed_key, platform, fee_type, rate, fixed_amount, fixed_currency, basis, country, country_scope, buyer_scope,
       cap_amount, cap_currency, tier, source_url, notes)
on conflict do nothing;

-- Per-store verification of (global or store) fee rules by the owner/admin
create table public.fee_rule_verifications (
  store_id     uuid not null references public.stores (id) on delete cascade,
  fee_rule_id  uuid not null references public.fee_rules (id) on delete cascade,
  verified_by  uuid references public.users (id) on delete set null,
  verified_at  timestamptz not null default now(),
  note         text,
  primary key (store_id, fee_rule_id)
);
create index fee_rule_verifications_rule_idx on public.fee_rule_verifications (fee_rule_id);
alter table public.fee_rule_verifications enable row level security;
grant select, insert, update, delete on public.fee_rule_verifications to authenticated, service_role;
create policy fee_rule_verifications_select on public.fee_rule_verifications for select to authenticated
  using (private.has_store_role(store_id, 'viewer'));
create policy fee_rule_verifications_write on public.fee_rule_verifications for all to authenticated
  using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'));

-- Seller context for fee selection
alter table public.store_settings
  add column seller_country  char(2) check (seller_country ~ '^[A-Z]{2}$'),
  add column payout_currency char(3) check (payout_currency ~ '^[A-Z]{3}$');

-- Policy extensions
alter table public.profit_rules
  add column vat_on_fees_rate numeric(6,4) not null default 0 check (vat_on_fees_rate between 0 and 1),
  add column offsite_ads_tier text not null default '15' check (offsite_ads_tier in ('15','12'));

-- Snapshot extensions (ads allocation kept apart from contribution before ads)
alter table public.profit_snapshots
  add column contribution_before_ads numeric(14,4),
  add column ad_cost_allocated       numeric(14,4) not null default 0,
  add column complete                boolean not null default true,
  add column fees_verified           boolean not null default false,
  add column warnings                jsonb not null default '[]'::jsonb;

-- FX reference rates are written by the worker (ECB); readable by signed-in users
create index fx_rates_asof_idx on public.fx_rates (as_of desc);
