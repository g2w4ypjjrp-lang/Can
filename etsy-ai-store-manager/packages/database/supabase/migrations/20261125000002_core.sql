-- =============================================================================
-- 0002 Core: users, settings, stores, membership, connected accounts, tokens
-- =============================================================================

-- Application profile mirroring auth.users (1:1) ---------------------------------
create table public.users (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null,
  full_name   text,
  locale      text not null default 'tr' check (char_length(locale) between 2 and 10),
  timezone    text not null default 'Europe/Istanbul',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create unique index users_email_key on public.users (lower(email));

create table public.user_settings (
  user_id                       uuid primary key references public.users (id) on delete cascade,
  ui_language                   text not null default 'tr' check (ui_language in ('tr','en')),
  base_currency                 char(3) not null default 'USD' check (base_currency ~ '^[A-Z]{3}$'),
  notify_email                  boolean not null default true,
  notify_push                   boolean not null default false,
  notify_daily_report           boolean not null default true,
  require_reauth_for_sensitive  boolean not null default true,
  dashboard_preferences         jsonb not null default '{}'::jsonb,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now()
);

-- Stores (multi-store / SaaS ready) ---------------------------------------------
create table public.stores (
  id                uuid primary key default gen_random_uuid(),
  owner_user_id     uuid not null references public.users (id) on delete restrict,
  name              text not null check (char_length(name) between 1 and 120),
  platform          text not null default 'etsy' check (platform in ('etsy')),
  external_shop_id  text,
  shop_url          text,
  currency          char(3) not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
  default_language  text not null default 'en',
  status            text not null default 'not_connected'
                      check (status in ('not_connected','connected','disconnected','suspended')),
  -- 'live' = real store data, 'demo' = sandbox/demo store, never mixed in reports
  data_origin       text not null default 'live' check (data_origin in ('live','demo')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create unique index stores_platform_external_key
  on public.stores (platform, external_shop_id) where external_shop_id is not null;
create index stores_owner_idx on public.stores (owner_user_id);

create table public.store_members (
  store_id    uuid not null references public.stores (id) on delete cascade,
  user_id     uuid not null references public.users (id) on delete cascade,
  role        text not null check (role in ('owner','admin','analyst','viewer')),
  created_at  timestamptz not null default now(),
  primary key (store_id, user_id)
);
create index store_members_user_idx on public.store_members (user_id);

create table public.store_settings (
  store_id              uuid primary key references public.stores (id) on delete cascade,
  sales_strategy        text not null default 'balanced'
                          check (sales_strategy in ('growth','balanced','profit')),
  automation_level      text not null default 'controlled'
                          check (automation_level in ('manual','controlled','autonomous_limited')),
  market_scope          text not null default 'global',
  default_language      text not null default 'en',
  languages             text[] not null default array['en'],
  target_markets        text[] not null default array[]::text[],
  daily_ad_budget_cap   numeric(12,2) not null default 0 check (daily_ad_budget_cap >= 0),
  ad_budget_currency    char(3) not null default 'USD' check (ad_budget_currency ~ '^[A-Z]{3}$'),
  timezone              text not null default 'UTC',
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint store_settings_default_lang_in_languages check (default_language = any (languages))
);

-- External platform connections --------------------------------------------------
create table public.connected_accounts (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  connected_by         uuid references public.users (id) on delete set null,
  platform             text not null check (platform in
                         ('etsy','printify','etsy_ads','meta_ads','google_ads','pinterest_ads','tiktok_ads')),
  external_account_id  text not null,
  display_name         text,
  scopes               text[] not null default array[]::text[],
  status               text not null default 'pending'
                         check (status in ('pending','active','expired','revoked','error')),
  last_synced_at       timestamptz,
  last_error           text,
  metadata             jsonb not null default '{}'::jsonb,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (store_id, platform, external_account_id)
);
create index connected_accounts_store_idx on public.connected_accounts (store_id, platform);

-- Tokens are AES-256-GCM encrypted by the API before insert. No client policies:
-- only the service role (server side) can read this table.
create table public.oauth_tokens (
  id                        uuid primary key default gen_random_uuid(),
  connected_account_id      uuid not null unique references public.connected_accounts (id) on delete cascade,
  access_token_ciphertext   text not null,
  refresh_token_ciphertext  text,
  token_type                text not null default 'Bearer',
  scopes                    text[] not null default array[]::text[],
  expires_at                timestamptz,
  refresh_expires_at        timestamptz,
  key_version               integer not null default 1,
  last_refreshed_at         timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);
create index oauth_tokens_expiry_idx on public.oauth_tokens (expires_at);

create trigger users_updated_at before update on public.users
  for each row execute function private.set_updated_at();
create trigger user_settings_updated_at before update on public.user_settings
  for each row execute function private.set_updated_at();
create trigger stores_updated_at before update on public.stores
  for each row execute function private.set_updated_at();
create trigger store_settings_updated_at before update on public.store_settings
  for each row execute function private.set_updated_at();
create trigger connected_accounts_updated_at before update on public.connected_accounts
  for each row execute function private.set_updated_at();
create trigger oauth_tokens_updated_at before update on public.oauth_tokens
  for each row execute function private.set_updated_at();
