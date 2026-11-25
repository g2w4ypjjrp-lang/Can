-- =============================================================================
-- 0006 Orders & customers
-- =============================================================================

create table public.customers (
  id              uuid primary key default gen_random_uuid(),
  store_id        uuid not null references public.stores (id) on delete cascade,
  etsy_user_id    bigint,
  name            text,
  email           text,
  country         char(2),
  first_order_at  timestamptz,
  last_order_at   timestamptz,
  total_orders    integer not null default 0 check (total_orders >= 0),
  data_origin     text not null default 'live' check (data_origin in ('live','imported','manual','demo')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create unique index customers_etsy_key on public.customers (store_id, etsy_user_id) where etsy_user_id is not null;

create table public.orders (
  id                 uuid primary key default gen_random_uuid(),
  store_id           uuid not null references public.stores (id) on delete cascade,
  customer_id        uuid references public.customers (id) on delete set null,
  etsy_receipt_id    bigint,
  printify_order_id  text,
  status             text not null default 'open' check (status in
                       ('open','paid','in_production','shipped','delivered','cancelled','refunded','partially_refunded')),
  currency           char(3) not null check (currency ~ '^[A-Z]{3}$'),
  subtotal           numeric(14,4) not null default 0,
  shipping_total     numeric(14,4) not null default 0,
  tax_total          numeric(14,4) not null default 0,
  discount_total     numeric(14,4) not null default 0,
  grand_total        numeric(14,4) not null default 0,
  buyer_country      char(2),
  placed_at          timestamptz not null,
  paid_at            timestamptz,
  shipped_at         timestamptz,
  data_origin        text not null default 'live' check (data_origin in ('live','imported','manual','demo')),
  raw                jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create unique index orders_etsy_key on public.orders (store_id, etsy_receipt_id) where etsy_receipt_id is not null;
create index orders_store_placed_idx on public.orders (store_id, placed_at desc);
create index orders_printify_idx on public.orders (printify_order_id) where printify_order_id is not null;

create table public.order_items (
  id                   uuid primary key default gen_random_uuid(),
  order_id             uuid not null references public.orders (id) on delete cascade,
  store_id             uuid not null references public.stores (id) on delete cascade,
  listing_id           uuid references public.listings (id) on delete set null,
  product_variant_id   uuid references public.product_variants (id) on delete set null,
  etsy_transaction_id  bigint,
  title                text not null,
  quantity             integer not null check (quantity > 0),
  unit_price           numeric(14,4) not null check (unit_price >= 0),
  currency             char(3) not null,
  created_at           timestamptz not null default now()
);
create unique index order_items_etsy_key on public.order_items (store_id, etsy_transaction_id)
  where etsy_transaction_id is not null;
create index order_items_order_idx on public.order_items (order_id);
create index order_items_variant_idx on public.order_items (product_variant_id);

create table public.shipments (
  id                     uuid primary key default gen_random_uuid(),
  order_id               uuid not null references public.orders (id) on delete cascade,
  store_id               uuid not null references public.stores (id) on delete cascade,
  carrier                text,
  tracking_number        text,
  tracking_url           text,
  status                 text not null default 'pending'
                           check (status in ('pending','in_transit','delivered','delayed','exception','returned')),
  printify_shipment_ref  text,
  shipped_at             timestamptz,
  estimated_delivery_at  timestamptz,
  delivered_at           timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create index shipments_order_idx on public.shipments (order_id);
create index shipments_store_status_idx on public.shipments (store_id, status);

create table public.refunds (
  id                   uuid primary key default gen_random_uuid(),
  order_id             uuid not null references public.orders (id) on delete cascade,
  store_id             uuid not null references public.stores (id) on delete cascade,
  amount               numeric(14,4) not null check (amount > 0),
  currency             char(3) not null,
  reason               text,
  status               text not null default 'requested'
                         check (status in ('requested','approved','processed','rejected')),
  approval_request_id  uuid references public.approval_requests (id) on delete set null,
  external_ref         text,
  processed_at         timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index refunds_order_idx on public.refunds (order_id);
create index refunds_store_idx on public.refunds (store_id, created_at desc);

create table public.customer_messages (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  customer_id          uuid references public.customers (id) on delete set null,
  order_id             uuid references public.orders (id) on delete set null,
  direction            text not null check (direction in ('inbound','outbound')),
  channel              text not null default 'etsy' check (channel in ('etsy','email','other')),
  body                 text not null,
  category             text check (category in ('question','complaint','return','shipping','personalization','other')),
  sentiment            text check (sentiment in ('positive','neutral','negative')),
  ai_draft             text,
  status               text not null default 'new'
                         check (status in ('new','draft_ready','awaiting_approval','sent','closed')),
  approval_request_id  uuid references public.approval_requests (id) on delete set null,
  received_at          timestamptz,
  sent_at              timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index customer_messages_store_status_idx on public.customer_messages (store_id, status, created_at desc);

create trigger customers_updated_at before update on public.customers
  for each row execute function private.set_updated_at();
create trigger orders_updated_at before update on public.orders
  for each row execute function private.set_updated_at();
create trigger shipments_updated_at before update on public.shipments
  for each row execute function private.set_updated_at();
create trigger refunds_updated_at before update on public.refunds
  for each row execute function private.set_updated_at();
create trigger customer_messages_updated_at before update on public.customer_messages
  for each row execute function private.set_updated_at();
