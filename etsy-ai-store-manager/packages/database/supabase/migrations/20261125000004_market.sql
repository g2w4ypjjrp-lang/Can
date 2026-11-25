-- =============================================================================
-- 0004 Market intelligence: research runs, competitors, keywords, opportunities
-- Every estimated metric carries is_estimate + confidence; Etsy does not expose
-- competitor sales data, so such values must never be presented as facts.
-- =============================================================================

create table public.market_research (
  id            uuid primary key default gen_random_uuid(),
  store_id      uuid not null references public.stores (id) on delete cascade,
  query         text not null,
  category      text,
  region        text not null default 'global',
  status        text not null default 'queued' check (status in ('queued','running','completed','failed')),
  summary       jsonb not null default '{}'::jsonb,
  data_sources  jsonb not null default '[]'::jsonb,
  confidence    text not null default 'low' check (confidence in ('low','medium','high')),
  is_estimate   boolean not null default true,
  ai_task_id    uuid,
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index market_research_store_idx on public.market_research (store_id, created_at desc);

create table public.competitor_research (
  id                  uuid primary key default gen_random_uuid(),
  store_id            uuid not null references public.stores (id) on delete cascade,
  market_research_id  uuid references public.market_research (id) on delete set null,
  competitor_shop_name text,
  competitor_shop_id  bigint,
  listing_url         text,
  listing_title       text,
  observed_price      numeric(12,2),
  currency            char(3),
  observed_at         timestamptz not null default now(),
  signals             jsonb not null default '{}'::jsonb,
  source              text not null,
  is_estimate         boolean not null default true,
  created_at          timestamptz not null default now()
);
create index competitor_research_store_idx on public.competitor_research (store_id, observed_at desc);

create table public.keywords (
  id                      uuid primary key default gen_random_uuid(),
  store_id                uuid not null references public.stores (id) on delete cascade,
  keyword                 text not null check (char_length(keyword) between 1 and 120),
  language                text not null default 'en',
  region                  text not null default 'global',
  search_volume_estimate  integer check (search_volume_estimate >= 0),
  competition_estimate    numeric(6,3),
  trend_direction         text check (trend_direction in ('rising','stable','falling','unknown')),
  source                  text not null,
  is_estimate             boolean not null default true,
  last_checked_at         timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create unique index keywords_unique_key on public.keywords (store_id, lower(keyword), language, region);

create table public.product_opportunities (
  id                    uuid primary key default gen_random_uuid(),
  store_id              uuid not null references public.stores (id) on delete cascade,
  market_research_id    uuid references public.market_research (id) on delete set null,
  title                 text not null,
  category              text,
  target_customer       text,
  keywords              text[] not null default array[]::text[],
  competition_level     text check (competition_level in ('low','medium','high','unknown')),
  demand_signals        jsonb not null default '[]'::jsonb,
  est_sale_price        numeric(12,2),
  est_production_cost   numeric(12,2),
  est_ad_cost           numeric(12,2),
  est_contribution      numeric(12,2),
  currency              char(3) not null default 'USD',
  opportunity_score     numeric(5,2) check (opportunity_score between 0 and 100),
  confidence            text not null default 'low' check (confidence in ('low','medium','high')),
  is_estimate           boolean not null default true,
  status                text not null default 'new'
                          check (status in ('new','shortlisted','rejected','in_design','launched')),
  rejection_reason      text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create index product_opportunities_store_idx on public.product_opportunities (store_id, status, opportunity_score desc);

create trigger market_research_updated_at before update on public.market_research
  for each row execute function private.set_updated_at();
create trigger keywords_updated_at before update on public.keywords
  for each row execute function private.set_updated_at();
create trigger product_opportunities_updated_at before update on public.product_opportunities
  for each row execute function private.set_updated_at();
