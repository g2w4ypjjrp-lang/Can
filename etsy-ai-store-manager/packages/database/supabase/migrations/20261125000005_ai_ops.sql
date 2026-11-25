-- =============================================================================
-- 0005 AI & operations: tasks, decisions, approvals, jobs, notifications, logs
-- =============================================================================

create table public.ai_tasks (
  id               uuid primary key default gen_random_uuid(),
  store_id         uuid references public.stores (id) on delete cascade,
  task_type        text not null,
  status           text not null default 'queued'
                     check (status in ('queued','running','succeeded','failed','cancelled')),
  input            jsonb not null default '{}'::jsonb,
  output           jsonb,
  model            text,
  input_tokens     integer check (input_tokens >= 0),
  output_tokens    integer check (output_tokens >= 0),
  cost_usd         numeric(12,6) check (cost_usd >= 0),
  error            text,
  attempts         integer not null default 0,
  idempotency_key  text unique,
  created_by       uuid references public.users (id) on delete set null,
  started_at       timestamptz,
  finished_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index ai_tasks_store_idx on public.ai_tasks (store_id, created_at desc);
create index ai_tasks_status_idx on public.ai_tasks (status) where status in ('queued','running');

alter table public.market_research
  add constraint market_research_ai_task_fk foreign key (ai_task_id)
  references public.ai_tasks (id) on delete set null;

-- Every action with real-world side effects passes through an approval request.
create table public.approval_requests (
  id                    uuid primary key default gen_random_uuid(),
  store_id              uuid not null references public.stores (id) on delete cascade,
  requested_by_type     text not null check (requested_by_type in ('ai','user','system')),
  requested_by_user_id  uuid references public.users (id) on delete set null,
  action_type           text not null check (action_type in (
                          'publish_product','change_price','delete_listing','start_ad_campaign',
                          'increase_ad_budget','allocate_ad_budget','change_store_design','refund',
                          'send_customer_message','cancel_order','update_listing','other')),
  title                 text not null,
  what                  text not null,           -- Ne yapılacak?
  why                   text not null,           -- Neden?
  expected_benefit      text,                    -- Beklenen fayda
  estimated_cost        numeric(14,4),           -- Tahmini maliyet
  cost_currency         char(3) default 'USD',
  profit_impact         text,                    -- Kârlılığa etkisi
  api_operation         text not null,           -- Kullanılacak API işlemi
  payload               jsonb not null default '{}'::jsonb,
  risk_level            text not null default 'medium' check (risk_level in ('low','medium','high')),
  requires_reauth       boolean not null default false,
  status                text not null default 'pending' check (status in
                          ('pending','approved','rejected','expired','executing','executed','failed','cancelled')),
  decided_by            uuid references public.users (id) on delete set null,
  decided_at            timestamptz,
  decision_note         text,
  expires_at            timestamptz,
  executed_at           timestamptz,
  execution_result      jsonb,
  idempotency_key       text unique,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check ((status in ('pending','expired','cancelled')) or decided_at is not null or status = 'executing')
);
create index approval_requests_store_status_idx on public.approval_requests (store_id, status, created_at desc);

create table public.ai_decisions (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  ai_task_id           uuid references public.ai_tasks (id) on delete set null,
  decision_type        text not null,
  summary              text not null,
  rationale            text,
  expected_benefit     text,
  estimated_cost       numeric(14,4),
  profit_impact        text,
  confidence           text not null default 'low' check (confidence in ('low','medium','high')),
  data_refs            jsonb not null default '[]'::jsonb,
  status               text not null default 'proposed'
                         check (status in ('proposed','approval_requested','accepted','rejected','superseded')),
  approval_request_id  uuid references public.approval_requests (id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index ai_decisions_store_idx on public.ai_decisions (store_id, created_at desc);

create table public.automation_jobs (
  id               uuid primary key default gen_random_uuid(),
  store_id         uuid references public.stores (id) on delete cascade,
  job_name         text not null,
  queue            text not null,
  schedule         text,                 -- 'daily' | 'weekly' | 'monthly' | cron | null (one-off)
  status           text not null default 'queued'
                     check (status in ('queued','running','succeeded','failed','skipped')),
  idempotency_key  text not null unique,
  attempts         integer not null default 0,
  max_attempts     integer not null default 3,
  payload          jsonb not null default '{}'::jsonb,
  result           jsonb,
  last_error       text,
  scheduled_for    timestamptz,
  started_at       timestamptz,
  finished_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index automation_jobs_store_idx on public.automation_jobs (store_id, created_at desc);
create index automation_jobs_name_idx on public.automation_jobs (job_name, created_at desc);

create table public.notifications (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users (id) on delete cascade,
  store_id    uuid references public.stores (id) on delete cascade,
  type        text not null,
  severity    text not null default 'info' check (severity in ('info','success','warning','critical')),
  title       text not null,
  body        text,
  link        text,
  read_at     timestamptz,
  created_at  timestamptz not null default now()
);
create index notifications_user_unread_idx on public.notifications (user_id, created_at desc) where read_at is null;

create table public.audit_logs (
  id             bigint generated always as identity primary key,
  store_id       uuid references public.stores (id) on delete set null,
  actor_user_id  uuid references public.users (id) on delete set null,
  actor_type     text not null check (actor_type in ('user','ai','system','worker')),
  action         text not null,
  entity_type    text,
  entity_id      text,
  before         jsonb,
  after          jsonb,
  ip             inet,
  user_agent     text,
  request_id     text,
  created_at     timestamptz not null default now()
);
create index audit_logs_store_idx on public.audit_logs (store_id, created_at desc);
create index audit_logs_actor_idx on public.audit_logs (actor_user_id, created_at desc);
create trigger audit_logs_append_only before update or delete on public.audit_logs
  for each row execute function private.prevent_mutation();

-- Outbound third-party API call log. Never store bodies or tokens here.
create table public.api_logs (
  id                    bigint generated always as identity primary key,
  store_id              uuid references public.stores (id) on delete set null,
  provider              text not null,
  method                text not null,
  endpoint              text not null,
  status_code           integer,
  duration_ms           integer,
  request_id            text,
  error                 text,
  rate_limit_remaining  integer,
  created_at            timestamptz not null default now()
);
create index api_logs_store_idx on public.api_logs (store_id, created_at desc);
create index api_logs_provider_idx on public.api_logs (provider, created_at desc);

create trigger ai_tasks_updated_at before update on public.ai_tasks
  for each row execute function private.set_updated_at();
create trigger approval_requests_updated_at before update on public.approval_requests
  for each row execute function private.set_updated_at();
create trigger ai_decisions_updated_at before update on public.ai_decisions
  for each row execute function private.set_updated_at();
create trigger automation_jobs_updated_at before update on public.automation_jobs
  for each row execute function private.set_updated_at();
