-- =============================================================================
-- 0003 Catalog: designs, products, variants, costs, images, listings, translations
-- =============================================================================

create table public.designs (
  id                  uuid primary key default gen_random_uuid(),
  store_id            uuid not null references public.stores (id) on delete cascade,
  created_by          uuid references public.users (id) on delete set null,
  title               text not null,
  prompt              text,
  -- Human creative direction (Etsy AI policy: seller's own design input)
  human_contribution  text,
  status              text not null default 'draft'
                        check (status in ('draft','review','approved','rejected','archived')),
  ip_risk_level       text not null default 'unknown'
                        check (ip_risk_level in ('unknown','low','medium','high')),
  ip_risk_notes       jsonb not null default '[]'::jsonb,
  tags                text[] not null default array[]::text[],
  current_version_id  uuid,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index designs_store_idx on public.designs (store_id, status);

create table public.design_versions (
  id                 uuid primary key default gen_random_uuid(),
  design_id          uuid not null references public.designs (id) on delete cascade,
  store_id           uuid not null references public.stores (id) on delete cascade,
  version            integer not null check (version > 0),
  storage_path       text not null,
  width_px           integer check (width_px > 0),
  height_px          integer check (height_px > 0),
  dpi                integer check (dpi > 0),
  has_transparency   boolean,
  generator          text not null check (generator in ('ai','upload','edit')),
  generation_params  jsonb not null default '{}'::jsonb,
  checksum_sha256    text,
  created_by         uuid references public.users (id) on delete set null,
  created_at         timestamptz not null default now(),
  unique (design_id, version)
);
create index design_versions_store_idx on public.design_versions (store_id);

alter table public.designs
  add constraint designs_current_version_fk
  foreign key (current_version_id) references public.design_versions (id) on delete set null;

create table public.products (
  id                          uuid primary key default gen_random_uuid(),
  store_id                    uuid not null references public.stores (id) on delete cascade,
  design_id                   uuid references public.designs (id) on delete set null,
  title                       text not null,
  product_type                text not null,
  status                      text not null default 'draft'
                                check (status in ('idea','draft','ready','published','archived')),
  printify_shop_id            bigint,
  printify_product_id         text,
  printify_blueprint_id       integer,
  printify_print_provider_id  integer,
  data_origin                 text not null default 'live' check (data_origin in ('live','imported','manual','demo')),
  metadata                    jsonb not null default '{}'::jsonb,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now()
);
create unique index products_printify_key on public.products (store_id, printify_product_id)
  where printify_product_id is not null;
create index products_store_status_idx on public.products (store_id, status);

create table public.product_variants (
  id                   uuid primary key default gen_random_uuid(),
  product_id           uuid not null references public.products (id) on delete cascade,
  store_id             uuid not null references public.stores (id) on delete cascade,
  sku                  text,
  title                text not null,
  options              jsonb not null default '{}'::jsonb,
  printify_variant_id  bigint,
  price                numeric(12,2) check (price >= 0),
  currency             char(3) not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
  is_enabled           boolean not null default true,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create unique index product_variants_printify_key on public.product_variants (product_id, printify_variant_id)
  where printify_variant_id is not null;
create unique index product_variants_sku_key on public.product_variants (store_id, sku) where sku is not null;
create index product_variants_store_idx on public.product_variants (store_id);

create table public.product_costs (
  id                   uuid primary key default gen_random_uuid(),
  product_variant_id   uuid not null references public.product_variants (id) on delete cascade,
  store_id             uuid not null references public.stores (id) on delete cascade,
  cost_type            text not null check (cost_type in
                         ('production','shipping_first_item','shipping_additional_item','handling','other')),
  amount               numeric(14,4) not null check (amount >= 0),
  currency             char(3) not null check (currency ~ '^[A-Z]{3}$'),
  destination_country  char(2),
  source               text not null check (source in ('printify_api','manual')),
  valid_from           timestamptz not null default now(),
  valid_to             timestamptz,
  created_at           timestamptz not null default now(),
  check (valid_to is null or valid_to > valid_from)
);
create index product_costs_lookup_idx
  on public.product_costs (product_variant_id, cost_type, destination_country, valid_from desc);
create index product_costs_store_idx on public.product_costs (store_id);

create table public.product_images (
  id             uuid primary key default gen_random_uuid(),
  product_id     uuid not null references public.products (id) on delete cascade,
  store_id       uuid not null references public.stores (id) on delete cascade,
  storage_path   text,
  source_url     text,
  source         text not null check (source in ('printify_mockup','upload','ai','etsy')),
  position       integer not null default 0 check (position >= 0),
  alt_text       text,
  width_px       integer,
  height_px      integer,
  etsy_image_id  bigint,
  created_at     timestamptz not null default now(),
  check (storage_path is not null or source_url is not null)
);
create index product_images_product_idx on public.product_images (product_id, position);
create index product_images_store_idx on public.product_images (store_id);

create table public.listings (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  product_id           uuid references public.products (id) on delete set null,
  etsy_listing_id      bigint,
  state                text not null default 'draft'
                         check (state in ('draft','active','inactive','expired','sold_out','removed','edit')),
  title                text not null check (char_length(title) <= 140),
  description          text,
  tags                 text[] not null default array[]::text[] check (cardinality(tags) <= 13),
  materials            text[] not null default array[]::text[],
  taxonomy_id          integer,
  price                numeric(12,2) check (price >= 0),
  currency             char(3) check (currency ~ '^[A-Z]{3}$'),
  quantity             integer check (quantity >= 0),
  shipping_profile_id  bigint,
  who_made             text,
  when_made            text,
  is_supply            boolean,
  views                integer,
  num_favorers         integer,
  -- last raw payload fetched from Etsy; used to preserve fields on partial updates
  raw                  jsonb,
  data_origin          text not null default 'live' check (data_origin in ('live','imported','manual','demo')),
  last_synced_at       timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create unique index listings_etsy_key on public.listings (store_id, etsy_listing_id)
  where etsy_listing_id is not null;
create index listings_store_state_idx on public.listings (store_id, state);
create index listings_product_idx on public.listings (product_id);

create table public.listing_translations (
  id             uuid primary key default gen_random_uuid(),
  listing_id     uuid not null references public.listings (id) on delete cascade,
  store_id       uuid not null references public.stores (id) on delete cascade,
  language       text not null check (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  title          text not null check (char_length(title) <= 140),
  description    text,
  tags           text[] not null default array[]::text[] check (cardinality(tags) <= 13),
  status         text not null default 'draft' check (status in ('draft','reviewed','published','rejected')),
  quality_score  numeric(5,2) check (quality_score between 0 and 100),
  quality_notes  jsonb not null default '[]'::jsonb,
  source         text not null default 'ai' check (source in ('ai','manual','etsy')),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (listing_id, language)
);
create index listing_translations_store_idx on public.listing_translations (store_id);

create trigger designs_updated_at before update on public.designs
  for each row execute function private.set_updated_at();
create trigger products_updated_at before update on public.products
  for each row execute function private.set_updated_at();
create trigger product_variants_updated_at before update on public.product_variants
  for each row execute function private.set_updated_at();
create trigger listings_updated_at before update on public.listings
  for each row execute function private.set_updated_at();
create trigger listing_translations_updated_at before update on public.listing_translations
  for each row execute function private.set_updated_at();
