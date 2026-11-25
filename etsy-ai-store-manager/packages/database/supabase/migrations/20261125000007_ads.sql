-- =============================================================================
-- 0007 Advertising
-- ad_spend is the ONLY ledger of actual ad expense. Per-order ad cost
-- allocations live inside profit_snapshots.breakdown and are never re-booked
-- as a separate expense (prevents double counting).
-- =============================================================================

create table public.ad_accounts (
  id                    uuid primary key default gen_random_uuid(),
  store_id              uuid not null references public.stores (id) on delete cascade,
  connected_account_id  uuid references public.connected_accounts (id) on delete set null,
  platform              text not null check (platform in
                          ('etsy_ads','meta_ads','google_ads','pinterest_ads','tiktok_ads')),
  external_account_id   text not null,
  name                  text,
  currency              char(3) not null default 'USD',
  -- 'api' = campaigns manageable via official API, 'manual' = reporting + approved manual workflow
  management_mode       text not null default 'manual' check (management_mode in ('api','manual')),
  status                text not null default 'active' check (status in ('active','paused','disconnected')),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (store_id, platform, external_account_id)
);

create table public.ad_campaigns (
  id                    uuid primary key default gen_random_uuid(),
  ad_account_id         uuid not null references public.ad_accounts (id) on delete cascade,
  store_id              uuid not null references public.stores (id) on delete cascade,
  external_campaign_id  text,
  name                  text not null,
  objective             text,
  status                text not null default 'draft'
                          check (status in ('draft','pending_approval','active','paused','ended','rejected')),
  daily_budget          numeric(12,2) check (daily_budget >= 0),
  currency              char(3) not null default 'USD',
  managed_via           text not null default 'manual' check (managed_via in ('api','manual')),
  started_at            timestamptz,
  ended_at              timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create unique index ad_campaigns_external_key on public.ad_campaigns (ad_account_id, external_campaign_id)
  where external_campaign_id is not null;
create index ad_campaigns_store_idx on public.ad_campaigns (store_id, status);

create table public.ad_metrics (
  id                      uuid primary key default gen_random_uuid(),
  campaign_id             uuid not null references public.ad_campaigns (id) on delete cascade,
  store_id                uuid not null references public.stores (id) on delete cascade,
  metric_date             date not null,
  impressions             bigint not null default 0 check (impressions >= 0),
  clicks                  bigint not null default 0 check (clicks >= 0),
  spend                   numeric(14,4) not null default 0 check (spend >= 0),
  conversions             numeric(12,2) not null default 0,
  conversion_value        numeric(14,4) not null default 0,
  currency                char(3) not null default 'USD',
  attribution_model       text,
  attribution_confidence  text not null default 'low' check (attribution_confidence in ('low','medium','high')),
  source                  text not null default 'api_report' check (source in ('api_report','csv_import','manual')),
  created_at              timestamptz not null default now(),
  unique (campaign_id, metric_date)
);
create index ad_metrics_store_date_idx on public.ad_metrics (store_id, metric_date desc);

create table public.ad_spend (
  id             uuid primary key default gen_random_uuid(),
  store_id       uuid not null references public.stores (id) on delete cascade,
  ad_account_id  uuid not null references public.ad_accounts (id) on delete cascade,
  campaign_id    uuid references public.ad_campaigns (id) on delete set null,
  spend_date     date not null,
  amount         numeric(14,4) not null check (amount >= 0),
  currency       char(3) not null,
  source         text not null check (source in ('platform_invoice','api_report','csv_import','manual')),
  external_ref   text,
  created_at     timestamptz not null default now()
);
create unique index ad_spend_dedupe_key on public.ad_spend
  (ad_account_id, spend_date, coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), source);
create index ad_spend_store_date_idx on public.ad_spend (store_id, spend_date desc);

create trigger ad_accounts_updated_at before update on public.ad_accounts
  for each row execute function private.set_updated_at();
create trigger ad_campaigns_updated_at before update on public.ad_campaigns
  for each row execute function private.set_updated_at();
