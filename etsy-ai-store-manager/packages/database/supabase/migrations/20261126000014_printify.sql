-- =============================================================================
-- 0014 Phase 3 — Printify integration
-- =============================================================================

-- Catalog responses cached server-side (catalog endpoints: +100 req/min limit).
create table public.printify_catalog_cache (
  cache_key   text primary key,
  payload     jsonb not null,
  fetched_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);
alter table public.printify_catalog_cache enable row level security;
revoke all on public.printify_catalog_cache from anon, authenticated;
grant select, insert, update, delete on public.printify_catalog_cache to service_role;

-- Incoming webhook deliveries (idempotency + audit). Server-side only.
create table public.webhook_events (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null check (provider in ('printify','etsy','meta','google','pinterest','tiktok')),
  event_id      text not null,
  store_id      uuid references public.stores (id) on delete cascade,
  topic         text not null,
  payload       jsonb not null,
  received_at   timestamptz not null default now(),
  processed_at  timestamptz,
  error         text,
  unique (provider, event_id)
);
create index webhook_events_store_idx on public.webhook_events (store_id, received_at desc);
alter table public.webhook_events enable row level security;
revoke all on public.webhook_events from anon, authenticated;
grant select, insert, update, delete on public.webhook_events to service_role;

-- Printify product state
alter table public.products
  add column printify_visible      boolean,
  add column printify_is_locked    boolean,
  add column external_listing_id   text,          -- sales channel (Etsy) listing id reported by Printify
  add column printify_synced_at    timestamptz;

alter table public.product_variants
  add column is_available boolean;

-- Production data from Printify orders (actual costs for the Profit Engine)
alter table public.orders
  add column printify_status        text,
  add column printify_cost_total    numeric(14,4),   -- sum of line item production cost
  add column printify_shipping_total numeric(14,4),
  add column printify_tax_total     numeric(14,4),
  add column printify_currency      char(3),
  add column printify_synced_at     timestamptz,
  add column sent_to_production_at  timestamptz,
  add column fulfilled_at           timestamptz;
create index orders_printify_status_idx on public.orders (store_id, printify_status) where printify_status is not null;

alter table public.order_items
  add column printify_line_item_id text,
  add column printify_product_id   text,
  add column printify_variant_id   bigint,
  add column production_cost       numeric(14,4),
  add column production_shipping_cost numeric(14,4),
  add column printify_status       text;
