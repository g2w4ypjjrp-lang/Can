-- =============================================================================
-- 0019 Phase 8 — Advertising manager: budget policy, proposals, Etsy ledger import
-- =============================================================================

-- User-set advertising limits. Proposals and budget increases above the caps are refused.
create table public.ad_budget_policies (
  store_id                uuid primary key references public.stores (id) on delete cascade,
  daily_cap               numeric(12,2) not null default 0 check (daily_cap >= 0),
  monthly_cap             numeric(14,2) check (monthly_cap >= 0),
  currency                char(3) not null default 'USD',
  -- minimum clicks before a campaign is judged (avoid decisions on noise)
  min_clicks_for_decision integer not null default 100 check (min_clicks_for_decision between 10 and 10000),
  updated_by              uuid references public.users (id) on delete set null,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create index ad_budget_policies_updated_by_idx on public.ad_budget_policies (updated_by);
create trigger ad_budget_policies_updated_at before update on public.ad_budget_policies
  for each row execute function private.set_updated_at();
alter table public.ad_budget_policies enable row level security;
grant select, insert, update, delete on public.ad_budget_policies to authenticated, service_role;
create policy ad_budget_policies_select on public.ad_budget_policies for select to authenticated
  using (private.has_store_role(store_id, 'viewer'));
create policy ad_budget_policies_write on public.ad_budget_policies for all to authenticated
  using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'));

-- Budget split proposals (always go through an approval before anything changes)
create table public.ad_budget_proposals (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  period_start         date not null,
  period_end           date not null,
  total_daily_budget   numeric(12,2) not null check (total_daily_budget >= 0),
  currency             char(3) not null default 'USD',
  allocations          jsonb not null default '[]'::jsonb,
  assumptions          jsonb not null default '{}'::jsonb,
  status               text not null default 'draft'
                         check (status in ('draft','pending_approval','approved','applied','rejected')),
  approval_request_id  uuid references public.approval_requests (id) on delete set null,
  created_by           uuid references public.users (id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  check (period_end >= period_start)
);
create index ad_budget_proposals_store_idx on public.ad_budget_proposals (store_id, created_at desc);
create index ad_budget_proposals_approval_idx on public.ad_budget_proposals (approval_request_id);
create index ad_budget_proposals_created_by_idx on public.ad_budget_proposals (created_by);
create trigger ad_budget_proposals_updated_at before update on public.ad_budget_proposals
  for each row execute function private.set_updated_at();
alter table public.ad_budget_proposals enable row level security;
grant select, insert, update, delete on public.ad_budget_proposals to authenticated, service_role;
create policy ad_budget_proposals_select on public.ad_budget_proposals for select to authenticated
  using (private.has_store_role(store_id, 'viewer'));
create policy ad_budget_proposals_write on public.ad_budget_proposals for all to authenticated
  using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'));

-- Etsy payment-account ledger (getShopPaymentAccountLedgerEntries, transactions_r).
-- The API does not document ledger_type values; the owner maps which types are Etsy Ads.
create table public.etsy_ledger_entries (
  id                uuid primary key default gen_random_uuid(),
  store_id          uuid not null references public.stores (id) on delete cascade,
  entry_id          bigint not null,
  ledger_type       text,
  reference_type    text,
  reference_id      text,
  description       text,
  amount            numeric(14,4) not null,   -- signed, in currency units
  currency          char(3) not null,
  entry_created_at  timestamptz not null,
  imported_at       timestamptz not null default now(),
  unique (store_id, entry_id)
);
create index etsy_ledger_entries_store_idx on public.etsy_ledger_entries (store_id, entry_created_at desc);
alter table public.etsy_ledger_entries enable row level security;
grant select, insert, update, delete on public.etsy_ledger_entries to authenticated, service_role;
create policy etsy_ledger_entries_select on public.etsy_ledger_entries for select to authenticated
  using (private.has_store_role(store_id, 'admin'));

alter table public.store_settings
  add column etsy_ads_ledger_types text[] not null default array[]::text[];

-- Each ad account books spend from exactly ONE source (prevents double counting):
-- 'metrics' = daily campaign reports (API/CSV/manual), 'ledger' = Etsy payment ledger.
alter table public.ad_accounts
  add column spend_source   text not null default 'metrics' check (spend_source in ('metrics','ledger')),
  add column last_synced_at timestamptz,
  add column last_error     text;

-- Manually-applied approvals (no official API): the owner confirms after doing it on the platform
alter table public.approval_requests
  add column manual_confirmed_by uuid references public.users (id) on delete set null,
  add column manual_confirmed_at timestamptz;
create index approval_requests_manual_confirmed_by_idx on public.approval_requests (manual_confirmed_by);
alter table public.approval_requests drop constraint approval_requests_status_check;
alter table public.approval_requests add constraint approval_requests_status_check
  check (status in ('pending','approved','rejected','executing','executed','failed','expired','cancelled','awaiting_manual'));
