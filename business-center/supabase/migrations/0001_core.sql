-- AI Business Center — çekirdek şema (Supabase PostgreSQL)
-- Tüm iş tabloları organization_id ile kiracı bazlı ayrılır ve RLS ile korunur.
-- Bu dosya Supabase'in "auth" şemasını (auth.users, auth.uid()) ve "authenticated" rolünü varsayar.

create extension if not exists pgcrypto;
create schema if not exists app;

-- ---------------------------------------------------------------------------
-- Yardımcılar
-- ---------------------------------------------------------------------------
create or replace function app.touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at := now(); return new; end $$;

-- ---------------------------------------------------------------------------
-- Kimlik ve organizasyon
-- ---------------------------------------------------------------------------
create table public.users (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (length(name) between 1 and 120),
  base_currency char(3) not null default 'USD',
  created_by  uuid not null references public.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id         uuid not null references public.users(id) on delete cascade,
  role            text not null check (role in ('owner','admin','viewer')),
  created_at      timestamptz not null default now(),
  primary key (organization_id, user_id)
);
create index on public.organization_members(user_id);

create or replace function app.is_member(org uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.organization_members m
                where m.organization_id = org and m.user_id = auth.uid())
$$;

create or replace function app.has_role(org uuid, roles text[]) returns boolean
language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.organization_members m
                where m.organization_id = org and m.user_id = auth.uid() and m.role = any(roles))
$$;

-- ---------------------------------------------------------------------------
-- Departmanlar ve ajanlar
-- ---------------------------------------------------------------------------
create table public.departments (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  code            text not null check (code in ('executive','youtube','etsy','quality')),
  name            text not null,
  created_at      timestamptz not null default now(),
  unique (organization_id, code)
);

create table public.agents (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  department_id   uuid not null references public.departments(id) on delete cascade,
  code            text not null,
  name            text not null,
  description     text not null default '',
  allowed_tools   text[] not null default '{}',
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, code)
);
create index on public.agents(department_id);

create table public.agent_instructions (
  id          uuid primary key default gen_random_uuid(),
  agent_id    uuid not null references public.agents(id) on delete cascade,
  version     int  not null check (version > 0),
  content     text not null,
  is_active   boolean not null default false,
  created_by  uuid references public.users(id),
  created_at  timestamptz not null default now(),
  unique (agent_id, version)
);
create unique index agent_instructions_one_active on public.agent_instructions(agent_id) where is_active;

-- ---------------------------------------------------------------------------
-- Görevler
-- ---------------------------------------------------------------------------
create table public.tasks (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  parent_task_id  uuid references public.tasks(id) on delete cascade,
  assigned_agent_id uuid references public.agents(id) on delete set null,
  title           text not null,
  command         text not null,
  status          text not null default 'queued'
                  check (status in ('queued','running','waiting_qc','waiting_approval','completed','failed','cancelled')),
  result          jsonb,
  error           text,
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  completed_at    timestamptz
);
create index on public.tasks(organization_id, status);
create index on public.tasks(parent_task_id);

create table public.task_steps (
  id          uuid primary key default gen_random_uuid(),
  task_id     uuid not null references public.tasks(id) on delete cascade,
  position    int not null,
  agent_id    uuid references public.agents(id) on delete set null,
  description text not null,
  status      text not null default 'pending' check (status in ('pending','running','done','failed','skipped')),
  output      jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (task_id, position)
);

create table public.agent_runs (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  agent_id        uuid not null references public.agents(id) on delete cascade,
  task_id         uuid references public.tasks(id) on delete set null,
  status          text not null check (status in ('running','succeeded','failed')),
  model           text,
  input_tokens    int check (input_tokens >= 0),
  output_tokens   int check (output_tokens >= 0),
  cost_usd        numeric(12,6) check (cost_usd >= 0),
  error           text,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz
);
create index on public.agent_runs(organization_id, started_at desc);

-- ---------------------------------------------------------------------------
-- Onaylar (kritik işlemler kullanıcı onayı olmadan yapılamaz)
-- ---------------------------------------------------------------------------
create table public.approvals (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  task_id         uuid references public.tasks(id) on delete set null,
  requested_by_agent_id uuid references public.agents(id) on delete set null,
  platform        text not null check (platform in ('youtube','etsy','printify','system')),
  action          text not null,
  reason          text not null,
  expected_outcome text not null,
  risk_level      text not null check (risk_level in ('low','medium','high','critical')),
  cost_amount     numeric(14,2) check (cost_amount >= 0),
  cost_currency   char(3),
  before_state    jsonb,
  after_state     jsonb not null,
  payload         jsonb not null,
  payload_hash    text not null,
  status          text not null default 'pending'
                  check (status in ('pending','approved','rejected','expired','executed','failed')),
  decided_by      uuid references public.users(id),
  decided_at      timestamptz,
  decision_note   text,
  expires_at      timestamptz not null,
  created_at      timestamptz not null default now(),
  check (expires_at > created_at),
  check ((status in ('approved','rejected','executed','failed')) = (decided_by is not null and decided_at is not null)
         or status in ('pending','expired'))
);
create index on public.approvals(organization_id, status);
create index on public.approvals(expires_at) where status = 'pending';

create table public.approval_history (
  id          bigint generated always as identity primary key,
  approval_id uuid not null references public.approvals(id) on delete cascade,
  from_status text,
  to_status   text not null,
  actor_user_id uuid references public.users(id),
  note        text,
  created_at  timestamptz not null default now()
);
create index on public.approval_history(approval_id);

-- Durum geçişleri: yalnızca pending -> approved/rejected/expired, approved -> executed/failed.
create or replace function app.approvals_validate() returns trigger
language plpgsql as $$
begin
  if new.payload_hash <> old.payload_hash or new.payload <> old.payload
     or new.after_state <> old.after_state or new.action <> old.action
     or new.organization_id <> old.organization_id then
    raise exception 'approval payload is immutable';
  end if;
  if old.status <> new.status and not (
       (old.status = 'pending'  and new.status in ('approved','rejected','expired'))
    or (old.status = 'approved' and new.status in ('executed','failed'))) then
    raise exception 'invalid approval transition % -> %', old.status, new.status;
  end if;
  if old.status = 'pending' and new.status = 'approved' and old.expires_at <= now() then
    raise exception 'approval expired';
  end if;
  return new;
end $$;
create trigger approvals_validate before update on public.approvals
  for each row execute function app.approvals_validate();

create or replace function app.approvals_history() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' or old.status is distinct from new.status then
    insert into public.approval_history(approval_id, from_status, to_status, actor_user_id, note)
    values (new.id, case when tg_op = 'UPDATE' then old.status end, new.status,
            new.decided_by, new.decision_note);
  end if;
  return new;
end $$;
create trigger approvals_history after insert or update on public.approvals
  for each row execute function app.approvals_history();

-- ---------------------------------------------------------------------------
-- Entegrasyonlar (tokenlar yalnızca backend tarafından, şifreli olarak tutulur)
-- ---------------------------------------------------------------------------
create table public.integrations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  provider        text not null check (provider in ('youtube','etsy','printify','anthropic')),
  status          text not null default 'disconnected'
                  check (status in ('disconnected','connected','error','revoked')),
  external_account_id text,
  display_name    text,
  scopes          text[] not null default '{}',
  last_error      text,
  last_synced_at  timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, provider)
);

create table public.oauth_tokens (
  id              uuid primary key default gen_random_uuid(),
  integration_id  uuid not null unique references public.integrations(id) on delete cascade,
  access_token_enc  bytea not null,
  refresh_token_enc bytea,
  key_version     int not null default 1,
  expires_at      timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- YouTube
-- ---------------------------------------------------------------------------
create table public.youtube_channels (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  integration_id  uuid references public.integrations(id) on delete set null,
  youtube_channel_id text not null,
  title           text not null,
  subscriber_count bigint check (subscriber_count >= 0),
  view_count      bigint check (view_count >= 0),
  video_count     bigint check (video_count >= 0),
  stats_fetched_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, youtube_channel_id)
);

create table public.youtube_videos (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  channel_id      uuid not null references public.youtube_channels(id) on delete cascade,
  youtube_video_id text,
  title           text not null,
  description     text not null default '',
  tags            text[] not null default '{}',
  privacy_status  text check (privacy_status in ('private','unlisted','public')),
  lifecycle       text not null default 'draft'
                  check (lifecycle in ('idea','scripting','production','review','scheduled','published','archived','draft')),
  published_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (channel_id, youtube_video_id)
);
create index on public.youtube_videos(organization_id, lifecycle);

create table public.youtube_analytics (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  channel_id      uuid not null references public.youtube_channels(id) on delete cascade,
  video_id        uuid references public.youtube_videos(id) on delete cascade,
  day             date not null,
  views           bigint check (views >= 0),
  impressions     bigint check (impressions >= 0),
  ctr             numeric(7,4) check (ctr between 0 and 100),
  watch_time_minutes numeric(14,2) check (watch_time_minutes >= 0),
  subscribers_gained int,
  subscribers_lost int,
  estimated_revenue numeric(14,2),
  currency        char(3),
  fetched_at      timestamptz not null default now()
);
create unique index youtube_analytics_uniq on public.youtube_analytics
  (channel_id, coalesce(video_id, '00000000-0000-0000-0000-000000000000'::uuid), day);
create index on public.youtube_analytics(organization_id, day);

create table public.youtube_content_ideas (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  task_id         uuid references public.tasks(id) on delete set null,
  title           text not null,
  summary         text not null default '',
  opportunity_score int check (opportunity_score between 0 and 100),
  sources         jsonb not null default '[]',
  status          text not null default 'proposed' check (status in ('proposed','accepted','rejected','used')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.youtube_scripts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  idea_id         uuid references public.youtube_content_ideas(id) on delete set null,
  video_id        uuid references public.youtube_videos(id) on delete set null,
  version         int not null default 1,
  hook            text not null default '',
  body            text not null,
  voiceover       text,
  sources         jsonb not null default '[]',
  qc_status       text not null default 'pending' check (qc_status in ('pending','passed','failed')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.video_assets (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  video_id        uuid references public.youtube_videos(id) on delete cascade,
  kind            text not null check (kind in ('thumbnail','voiceover','footage','image','final_video','subtitle')),
  storage_path    text not null,
  mime_type       text,
  bytes           bigint check (bytes >= 0),
  license_note    text,
  qc_status       text not null default 'pending' check (qc_status in ('pending','passed','failed','needs_human')),
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Etsy ve Printify
-- ---------------------------------------------------------------------------
create table public.etsy_shops (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  integration_id  uuid references public.integrations(id) on delete set null,
  etsy_shop_id    bigint not null,
  name            text not null,
  currency        char(3),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, etsy_shop_id)
);

create table public.etsy_products (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  shop_id         uuid references public.etsy_shops(id) on delete cascade,
  name            text not null,
  design_storage_path text,
  status          text not null default 'concept' check (status in ('concept','designing','ready','listed','retired')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.etsy_listings (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  shop_id         uuid not null references public.etsy_shops(id) on delete cascade,
  product_id      uuid references public.etsy_products(id) on delete set null,
  etsy_listing_id bigint,
  title           text not null check (length(title) <= 140),
  description     text not null default '',
  tags            text[] not null default '{}' check (cardinality(tags) <= 13),
  price_amount    numeric(12,2) check (price_amount >= 0),
  currency        char(3),
  quantity        int check (quantity >= 0),
  state           text not null default 'draft' check (state in ('draft','active','inactive','sold_out','expired','removed')),
  seo_score       int check (seo_score between 0 and 100),
  synced_at       timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (shop_id, etsy_listing_id)
);
create index on public.etsy_listings(organization_id, state);

create table public.etsy_orders (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  shop_id         uuid not null references public.etsy_shops(id) on delete cascade,
  etsy_receipt_id bigint not null,
  status          text not null,
  grandtotal_amount numeric(12,2),
  currency        char(3),
  ordered_at      timestamptz not null,
  shipped_at      timestamptz,
  synced_at       timestamptz not null default now(),
  unique (shop_id, etsy_receipt_id)
);
create index on public.etsy_orders(organization_id, ordered_at desc);

create table public.etsy_transactions (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  order_id        uuid not null references public.etsy_orders(id) on delete cascade,
  listing_id      uuid references public.etsy_listings(id) on delete set null,
  etsy_transaction_id bigint not null unique,
  quantity        int not null check (quantity > 0),
  price_amount    numeric(12,2) not null,
  currency        char(3) not null,
  created_at      timestamptz not null default now()
);

create table public.printify_products (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  etsy_product_id uuid references public.etsy_products(id) on delete set null,
  printify_shop_id bigint not null,
  printify_product_id text not null,
  blueprint_id    int,
  print_provider_id int,
  title           text not null,
  variants        jsonb not null default '[]',
  synced_at       timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, printify_product_id)
);

create table public.printify_orders (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  etsy_order_id   uuid references public.etsy_orders(id) on delete set null,
  printify_order_id text not null,
  status          text not null,
  production_cost numeric(12,2),
  shipping_cost   numeric(12,2),
  currency        char(3),
  synced_at       timestamptz not null default now(),
  unique (organization_id, printify_order_id)
);

create table public.product_research (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  task_id         uuid references public.tasks(id) on delete set null,
  niche           text not null,
  idea            text not null,
  opportunity_score int check (opportunity_score between 0 and 100),
  evidence        jsonb not null default '[]',
  created_at      timestamptz not null default now()
);

create table public.competitor_analysis (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  task_id         uuid references public.tasks(id) on delete set null,
  platform        text not null check (platform in ('youtube','etsy')),
  competitor_name text not null,
  competitor_url  text,
  findings        jsonb not null default '{}',
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Finans (tutarlar kaynak para biriminde + dönüştürülmüş tutar ve kur)
-- ---------------------------------------------------------------------------
create table public.revenue_records (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  department      text not null check (department in ('youtube','etsy')),
  category        text not null,
  amount          numeric(14,2) not null,
  currency        char(3) not null,
  fx_rate         numeric(18,8),
  base_amount     numeric(14,2),
  occurred_on     date not null,
  source          text not null check (source in ('youtube_api','etsy_api','printify_api','manual')),
  source_ref      text,
  created_at      timestamptz not null default now(),
  unique (organization_id, source, source_ref)
);
create index on public.revenue_records(organization_id, occurred_on);

create table public.expenses (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  department      text check (department in ('youtube','etsy','shared')),
  category        text not null,
  amount          numeric(14,2) not null check (amount >= 0),
  currency        char(3) not null,
  fx_rate         numeric(18,8),
  base_amount     numeric(14,2),
  occurred_on     date not null,
  source          text not null check (source in ('youtube_api','etsy_api','printify_api','anthropic_usage','manual')),
  source_ref      text,
  note            text,
  created_at      timestamptz not null default now(),
  unique (organization_id, source, source_ref)
);
create index on public.expenses(organization_id, occurred_on);

create table public.financial_records (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  kind            text not null check (kind in ('fee','refund','discount','tax','fx_adjustment','payout')),
  department      text check (department in ('youtube','etsy','shared')),
  amount          numeric(14,2) not null,
  currency        char(3) not null,
  occurred_on     date not null,
  source          text not null,
  source_ref      text,
  created_at      timestamptz not null default now()
);
create index on public.financial_records(organization_id, occurred_on);

create table public.profit_reports (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  scope           text not null check (scope in ('youtube','etsy','combined')),
  period_start    date not null,
  period_end      date not null check (period_end >= period_start),
  currency        char(3) not null,
  figures         jsonb not null,
  missing_data    text[] not null default '{}',
  verified        boolean not null default false,
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Bildirim, otomasyon, denetim, ayarlar
-- ---------------------------------------------------------------------------
create table public.notifications (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id         uuid references public.users(id) on delete cascade,
  kind            text not null,
  title           text not null,
  body            text not null default '',
  link            text,
  read_at         timestamptz,
  created_at      timestamptz not null default now()
);
create index on public.notifications(organization_id, user_id, read_at);

create table public.automation_rules (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name            text not null,
  schedule_cron   text not null,
  timezone        text not null default 'Europe/Istanbul',
  command         text not null,
  enabled         boolean not null default false,
  last_run_at     timestamptz,
  next_run_at     timestamptz,
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.audit_logs (
  id              bigint generated always as identity primary key,
  organization_id uuid references public.organizations(id) on delete set null,
  actor_user_id   uuid references public.users(id) on delete set null,
  actor_agent_id  uuid references public.agents(id) on delete set null,
  action          text not null,
  target_type     text,
  target_id       text,
  details         jsonb not null default '{}',
  ip              inet,
  created_at      timestamptz not null default now()
);
create index on public.audit_logs(organization_id, created_at desc);

create or replace function app.audit_immutable() returns trigger
language plpgsql as $$ begin raise exception 'audit_logs is append-only'; end $$;
create trigger audit_logs_immutable before update or delete on public.audit_logs
  for each row execute function app.audit_immutable();

create table public.system_settings (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  key             text not null,
  value           jsonb not null,
  updated_by      uuid references public.users(id),
  updated_at      timestamptz not null default now(),
  primary key (organization_id, key)
);

-- ---------------------------------------------------------------------------
-- updated_at tetikleyicileri
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  for t in select c.table_name from information_schema.columns c
           where c.table_schema = 'public' and c.column_name = 'updated_at'
  loop
    execute format('create trigger %I before update on public.%I for each row execute function app.touch_updated_at()',
                   t || '_touch', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.users enable row level security;
create policy users_self on public.users for select using (id = auth.uid());
create policy users_self_update on public.users for update using (id = auth.uid());

alter table public.organizations enable row level security;
create policy org_read on public.organizations for select using (app.is_member(id));
create policy org_update on public.organizations for update using (app.has_role(id, array['owner','admin']));

alter table public.organization_members enable row level security;
create policy members_read on public.organization_members for select using (app.is_member(organization_id));

-- Kiracı tablolarında: üyeler okur, owner/admin yazar.
do $$
declare t text;
begin
  foreach t in array array[
    'departments','agents','tasks','agent_runs','integrations',
    'youtube_channels','youtube_videos','youtube_analytics','youtube_content_ideas','youtube_scripts','video_assets',
    'etsy_shops','etsy_products','etsy_listings','etsy_orders','etsy_transactions',
    'printify_products','printify_orders','product_research','competitor_analysis',
    'revenue_records','expenses','financial_records','profit_reports',
    'automation_rules','system_settings']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy %I on public.%I for select using (app.is_member(organization_id))', t||'_read', t);
    execute format('create policy %I on public.%I for insert with check (app.has_role(organization_id, array[''owner'',''admin'']))', t||'_ins', t);
    execute format('create policy %I on public.%I for update using (app.has_role(organization_id, array[''owner'',''admin'']))', t||'_upd', t);
    execute format('create policy %I on public.%I for delete using (app.has_role(organization_id, array[''owner'',''admin'']))', t||'_del', t);
  end loop;
end $$;

-- Alt tablolar: üst kayıt üzerinden.
alter table public.agent_instructions enable row level security;
create policy agent_instructions_read on public.agent_instructions for select
  using (exists(select 1 from public.agents a where a.id = agent_id and app.is_member(a.organization_id)));

alter table public.task_steps enable row level security;
create policy task_steps_read on public.task_steps for select
  using (exists(select 1 from public.tasks t where t.id = task_id and app.is_member(t.organization_id)));

-- Onaylar: üyeler okur; karar yalnızca app.decide_approval() ile verilir (doğrudan yazma yok).
alter table public.approvals enable row level security;
create policy approvals_read on public.approvals for select using (app.is_member(organization_id));

alter table public.approval_history enable row level security;
create policy approval_history_read on public.approval_history for select
  using (exists(select 1 from public.approvals a where a.id = approval_id and app.is_member(a.organization_id)));

-- Tokenlar: istemci rollerine hiçbir şekilde açık değil (yalnızca service_role).
alter table public.oauth_tokens enable row level security;

alter table public.notifications enable row level security;
create policy notifications_read on public.notifications for select
  using (app.is_member(organization_id) and (user_id is null or user_id = auth.uid()));
create policy notifications_mark_read on public.notifications for update
  using (user_id = auth.uid());

alter table public.audit_logs enable row level security;
create policy audit_read on public.audit_logs for select
  using (app.has_role(organization_id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- Güvenli işlemler (security definer, kimlik auth.uid()'den alınır)
-- ---------------------------------------------------------------------------

-- Yeni Supabase kullanıcısı için profil satırı.
create or replace function app.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.users(id, email) values (new.id, coalesce(new.email, ''))
  on conflict (id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function app.handle_new_user();

-- Onay kararı: kimlik, üyelik, rol, süre ve durum veritabanında doğrulanır.
create or replace function app.decide_approval(p_approval uuid, p_approve boolean, p_note text)
returns public.approvals
language plpgsql security definer set search_path = public as $$
declare a public.approvals;
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  select * into a from public.approvals where id = p_approval for update;
  if not found then raise exception 'approval not found'; end if;
  if not app.has_role(a.organization_id, array['owner','admin']) then
    raise exception 'not allowed';
  end if;
  if a.status <> 'pending' then raise exception 'approval is %', a.status; end if;
  if a.expires_at <= now() then
    update public.approvals set status = 'expired' where id = a.id returning * into a;
    return a;
  end if;
  if not p_approve and coalesce(trim(p_note), '') = '' then
    raise exception 'rejection reason required';
  end if;
  update public.approvals
     set status = case when p_approve then 'approved' else 'rejected' end,
         decided_by = auth.uid(), decided_at = now(), decision_note = p_note
   where id = a.id returning * into a;
  insert into public.audit_logs(organization_id, actor_user_id, action, target_type, target_id, details)
  values (a.organization_id, auth.uid(), 'approval.' || a.status, 'approval', a.id::text,
          jsonb_build_object('action', a.action, 'platform', a.platform));
  return a;
end $$;

-- Süresi dolan onaylar otomatik reddedilir (expired). Zamanlayıcı tarafından çağrılır.
create or replace function app.expire_approvals() returns int
language sql security definer set search_path = public as $$
  with x as (update public.approvals set status = 'expired'
             where status = 'pending' and expires_at <= now() returning 1)
  select count(*)::int from x
$$;

-- Organizasyon oluşturma: sahibi ekler, departmanları ve ajan kadrosunu kurar.
create or replace function app.create_organization(p_name text) returns uuid
language plpgsql security definer set search_path = public as $$
declare org uuid; d record; ag record;
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  insert into public.organizations(name, created_by) values (p_name, auth.uid()) returning id into org;
  insert into public.organization_members values (org, auth.uid(), 'owner', now());
  for d in select * from (values
      ('executive','Yönetim'),('youtube','YouTube'),('etsy','Etsy'),('quality','Kalite Kontrol')) v(code,name)
  loop
    insert into public.departments(organization_id, code, name) values (org, d.code, d.name);
  end loop;
  for ag in select * from (values
      ('executive','ceo','CEO Agent','Komutları anlar, işleri departmanlara dağıtır, raporlar.'),
      ('youtube','yt_trend_research','Trend Research Agent','Trendleri ve rakip kanalları araştırır, fırsatları puanlar.'),
      ('youtube','yt_channel_strategist','Channel Strategist Agent','İçerik stratejisi ve yayın takvimi hazırlar.'),
      ('youtube','yt_script_writer','Script Writer Agent','Kaynaklı video senaryoları ve seslendirme metni yazar.'),
      ('youtube','yt_video_production','Video Production Agent','Sahne listesi ve üretim iş akışını yönetir.'),
      ('youtube','yt_thumbnail_designer','Thumbnail Designer Agent','Kapak konseptleri hazırlar, okunabilirliği denetler.'),
      ('youtube','yt_seo','YouTube SEO Agent','Başlık, açıklama, etiket ve anahtar kelime çalışması yapar.'),
      ('youtube','yt_analytics','YouTube Analytics Agent','İzlenme, CTR, izlenme süresi ve gelir analizi yapar.'),
      ('etsy','etsy_product_research','Product Research Agent','Ürün fırsatlarını araştırır ve puanlar.'),
      ('etsy','etsy_competitor_analysis','Competitor Analysis Agent','Rakip mağazaları ve pazar boşluklarını inceler.'),
      ('etsy','etsy_design','Design Agent','Print-on-demand için özgün tasarım hazırlar.'),
      ('etsy','etsy_seo','Etsy SEO Agent','Başlık, açıklama ve 13 etiket hazırlar, SEO puanlar.'),
      ('etsy','etsy_listing_manager','Listing Manager Agent','Listelemeleri hazırlar, yayın öncesi onay ister.'),
      ('etsy','printify','Printify Agent','Katalog, maliyet, mockup ve sipariş takibi yapar.'),
      ('etsy','etsy_profit_analyst','Profit Analyst Agent','Ücretler, üretim, kargo, reklam ve kur dahil net kâr hesaplar.'),
      ('etsy','etsy_sales_analyst','Sales Analyst Agent','Sipariş ve satış trendlerini analiz eder.'),
      ('quality','qc_content','Content Quality Agent','İçerik kalitesini ve doğruluğu denetler.'),
      ('quality','qc_copyright','Copyright Compliance Agent','Telif ve marka riski işaretler (garanti vermez).'),
      ('quality','qc_seo','SEO Quality Agent','SEO çıktılarını kurallara göre denetler.'),
      ('quality','qc_financial','Financial Verification Agent','Finansal hesapları kaynak veriye göre doğrular.'),
      ('quality','qc_technical','Technical Testing Agent','Teknik çıktıları ve entegrasyon sonuçlarını test eder.')
    ) v(dept, code, name, descr)
  loop
    insert into public.agents(organization_id, department_id, code, name, description)
    select org, id, ag.code, ag.name, ag.descr from public.departments
     where organization_id = org and code = ag.dept;
  end loop;
  insert into public.audit_logs(organization_id, actor_user_id, action, target_type, target_id)
  values (org, auth.uid(), 'organization.created', 'organization', org::text);
  return org;
end $$;

-- Supabase rolleri: istemci yalnızca RLS'in izin verdiği kadarını görür.
grant usage on schema app to authenticated;
grant execute on function app.decide_approval(uuid, boolean, text) to authenticated;
grant execute on function app.create_organization(text) to authenticated;
revoke execute on function app.expire_approvals() from public;
grant select on all tables in schema public to authenticated;
grant insert, update, delete on all tables in schema public to authenticated;
revoke all on public.oauth_tokens from authenticated, anon;
revoke insert, update, delete on public.approvals, public.approval_history, public.audit_logs from authenticated;
revoke all on all tables in schema public from anon;
