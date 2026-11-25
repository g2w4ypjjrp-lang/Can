-- =============================================================================
-- 0008 Finance / Profit engine storage
-- fee_rules hold NO hard-coded defaults: each rule records its official source
-- and verification timestamp; the profit engine only uses verified rules.
-- =============================================================================

create table public.fee_rules (
  id              uuid primary key default gen_random_uuid(),
  store_id        uuid references public.stores (id) on delete cascade,   -- null = global rule
  platform        text not null check (platform in ('etsy','printify','payment','fx','other')),
  fee_type        text not null check (fee_type in (
                    'listing','transaction','payment_processing','currency_conversion',
                    'offsite_ads','regulatory_operating','vat_on_fees','shipping_label','other')),
  rate            numeric(9,6) check (rate >= 0 and rate < 1),
  fixed_amount    numeric(12,4) check (fixed_amount >= 0),
  fixed_currency  char(3),
  -- matrah (base the rate applies to)
  basis           text not null check (basis in (
                    'item_price','item_plus_shipping','order_total','order_total_incl_tax',
                    'per_listing','per_order','converted_amount')),
  country         char(2),
  country_scope   text check (country_scope in ('seller','buyer','bank')),
  effective_from  date not null,
  effective_to    date,
  source_url      text not null,
  verified_at     timestamptz,
  verified_by     uuid references public.users (id) on delete set null,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check (rate is not null or fixed_amount is not null),
  check (fixed_amount is null or fixed_currency is not null),
  check (effective_to is null or effective_to > effective_from)
);
create index fee_rules_lookup_idx on public.fee_rules (platform, fee_type, country, effective_from desc);
create index fee_rules_store_idx on public.fee_rules (store_id);

create table public.fx_rates (
  id          uuid primary key default gen_random_uuid(),
  base        char(3) not null check (base ~ '^[A-Z]{3}$'),
  quote       char(3) not null check (quote ~ '^[A-Z]{3}$'),
  rate        numeric(20,10) not null check (rate > 0),
  as_of       timestamptz not null,
  source      text not null,
  created_at  timestamptz not null default now(),
  unique (base, quote, as_of, source)
);
create index fx_rates_lookup_idx on public.fx_rates (base, quote, as_of desc);

-- Contribution policy per store (editable from the panel) ----------------------
create table public.profit_rules (
  id                         uuid primary key default gen_random_uuid(),
  store_id                   uuid not null unique references public.stores (id) on delete cascade,
  currency                   char(3) not null default 'USD',
  target_contribution        numeric(12,2) not null default 10,
  excellent_threshold        numeric(12,2) not null default 15,   -- >= : Çok iyi
  publish_threshold          numeric(12,2) not null default 10,   -- >= : Yayınlanabilir
  review_threshold           numeric(12,2) not null default 7,    -- >= : Onay bekler
  min_threshold              numeric(12,2) not null default 0,    -- >= : Önerilmez, < : Reddedilir
  return_reserve_rate        numeric(6,4) not null default 0 check (return_reserve_rate between 0 and 1),
  remake_reserve_rate        numeric(6,4) not null default 0 check (remake_reserve_rate between 0 and 1),
  other_variable_cost_rate   numeric(6,4) not null default 0 check (other_variable_cost_rate between 0 and 1),
  other_variable_cost_fixed  numeric(12,4) not null default 0 check (other_variable_cost_fixed >= 0),
  default_ad_cost_per_order  numeric(12,4) not null default 0 check (default_ad_cost_per_order >= 0),
  tax_rate_on_profit         numeric(6,4) not null default 0 check (tax_rate_on_profit between 0 and 1),
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now(),
  constraint profit_rules_threshold_order check (
    excellent_threshold >= publish_threshold
    and publish_threshold >= review_threshold
    and review_threshold >= min_threshold
  )
);

create table public.profit_snapshots (
  id                     uuid primary key default gen_random_uuid(),
  store_id               uuid not null references public.stores (id) on delete cascade,
  product_variant_id     uuid references public.product_variants (id) on delete set null,
  listing_id             uuid references public.listings (id) on delete set null,
  order_id               uuid references public.orders (id) on delete cascade,
  order_item_id          uuid references public.order_items (id) on delete cascade,
  scenario               text not null check (scenario in ('simulation','listing_estimate','order_actual')),
  currency               char(3) not null,
  gross_revenue          numeric(14,4) not null,
  net_revenue            numeric(14,4) not null,
  total_variable_costs   numeric(14,4) not null,
  contribution           numeric(14,4) not null,     -- vergi öncesi katkı
  contribution_after_tax numeric(14,4),              -- tahmini vergi sonrası
  contribution_margin    numeric(9,6),
  decision               text not null check (decision in
                           ('excellent','publishable','needs_approval','not_recommended','rejected')),
  breakdown              jsonb not null,             -- line-by-line detail, always stored
  inputs                 jsonb not null,
  fee_rule_ids           uuid[] not null default array[]::uuid[],
  fx_rate_ids            uuid[] not null default array[]::uuid[],
  engine_version         text not null,
  calculated_at          timestamptz not null default now()
);
create index profit_snapshots_store_idx on public.profit_snapshots (store_id, calculated_at desc);
create index profit_snapshots_variant_idx on public.profit_snapshots (product_variant_id, calculated_at desc);
create unique index profit_snapshots_order_item_key on public.profit_snapshots (order_item_id)
  where scenario = 'order_actual';

create table public.price_recommendations (
  id                     uuid primary key default gen_random_uuid(),
  store_id               uuid not null references public.stores (id) on delete cascade,
  product_variant_id     uuid references public.product_variants (id) on delete cascade,
  listing_id             uuid references public.listings (id) on delete cascade,
  current_price          numeric(12,2),
  recommended_price      numeric(12,2) not null check (recommended_price > 0),
  currency               char(3) not null,
  target_contribution    numeric(12,2) not null,
  expected_contribution  numeric(12,2) not null,
  rationale              text,
  status                 text not null default 'proposed'
                           check (status in ('proposed','approved','rejected','applied','superseded')),
  approval_request_id    uuid references public.approval_requests (id) on delete set null,
  profit_snapshot_id     uuid references public.profit_snapshots (id) on delete set null,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  check (product_variant_id is not null or listing_id is not null)
);
create index price_recommendations_store_idx on public.price_recommendations (store_id, status);

create table public.tax_reserves (
  id               uuid primary key default gen_random_uuid(),
  store_id         uuid not null references public.stores (id) on delete cascade,
  period_start     date not null,
  period_end       date not null,
  taxable_base     numeric(14,4) not null,
  rate             numeric(6,4) not null check (rate between 0 and 1),
  reserved_amount  numeric(14,4) not null,
  currency         char(3) not null,
  notes            text,
  created_at       timestamptz not null default now(),
  unique (store_id, period_start, period_end),
  check (period_end >= period_start)
);

create trigger fee_rules_updated_at before update on public.fee_rules
  for each row execute function private.set_updated_at();
create trigger profit_rules_updated_at before update on public.profit_rules
  for each row execute function private.set_updated_at();
create trigger price_recommendations_updated_at before update on public.price_recommendations
  for each row execute function private.set_updated_at();
