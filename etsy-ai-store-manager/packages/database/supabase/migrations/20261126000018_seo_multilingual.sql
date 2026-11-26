-- =============================================================================
-- 0018 Phase 7 — SEO content drafts, multilingual translations, Etsy listing creation
-- =============================================================================

-- AI / manual SEO proposals for an Etsy listing or a (Printify) product. Nothing is sent to
-- Etsy or Printify from here: applying a draft creates an approval request.
create table public.seo_drafts (
  id                   uuid primary key default gen_random_uuid(),
  store_id             uuid not null references public.stores (id) on delete cascade,
  listing_id           uuid references public.listings (id) on delete cascade,
  product_id           uuid references public.products (id) on delete cascade,
  language             text not null default 'en' check (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  status               text not null default 'generating'
                         check (status in ('generating','draft','pending_approval','applied','rejected','failed')),
  primary_keyword      text,
  title                text check (char_length(title) <= 140),
  description          text,
  tags                 text[] not null default array[]::text[] check (cardinality(tags) <= 13),
  materials            text[] not null default array[]::text[],
  rationale            text,
  seo_score            numeric(5,2) check (seo_score between 0 and 100),
  issues               jsonb not null default '[]'::jsonb,
  -- values the proposal was based on (shown as a diff; used for conflict detection)
  baseline             jsonb not null default '{}'::jsonb,
  source               text not null default 'ai' check (source in ('ai','manual')),
  ai_task_id           uuid references public.ai_tasks (id) on delete set null,
  approval_request_id  uuid references public.approval_requests (id) on delete set null,
  error                text,
  created_by           uuid references public.users (id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint seo_drafts_target check (listing_id is not null or product_id is not null)
);
create index seo_drafts_store_idx on public.seo_drafts (store_id, created_at desc);
create index seo_drafts_listing_idx on public.seo_drafts (listing_id);
create index seo_drafts_product_idx on public.seo_drafts (product_id);
create index seo_drafts_ai_task_idx on public.seo_drafts (ai_task_id);
create index seo_drafts_approval_idx on public.seo_drafts (approval_request_id);
create index seo_drafts_created_by_idx on public.seo_drafts (created_by);
create trigger seo_drafts_updated_at before update on public.seo_drafts
  for each row execute function private.set_updated_at();

alter table public.seo_drafts enable row level security;
grant select, insert, update, delete on public.seo_drafts to authenticated, service_role;
create policy seo_drafts_select on public.seo_drafts for select to authenticated
  using (private.has_store_role(store_id, 'viewer'));
create policy seo_drafts_write on public.seo_drafts for all to authenticated
  using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'));

-- Translations: quality data + publication tracking
alter table public.listing_translations
  drop constraint listing_translations_status_check,
  add constraint listing_translations_status_check
    check (status in ('generating','draft','reviewed','pending_approval','published','rejected','failed')),
  add column back_translation     jsonb,
  add column localization_notes   jsonb not null default '[]'::jsonb,
  add column ai_task_id           uuid references public.ai_tasks (id) on delete set null,
  add column approval_request_id  uuid references public.approval_requests (id) on delete set null,
  add column reviewed_by          uuid references public.users (id) on delete set null,
  add column reviewed_at          timestamptz,
  add column published_at         timestamptz,
  add column error                text;
alter table public.listing_translations alter column title drop not null;
alter table public.listing_translations
  add constraint listing_translations_title_required
    check (status in ('generating','failed') or title is not null);
create index listing_translations_ai_task_idx on public.listing_translations (ai_task_id);
create index listing_translations_approval_idx on public.listing_translations (approval_request_id);
create index listing_translations_reviewed_by_idx on public.listing_translations (reviewed_by);

-- New approval action types executed through official APIs
alter table public.approval_requests
  drop constraint approval_requests_action_type_check,
  add constraint approval_requests_action_type_check check (action_type in (
    'publish_product','change_price','delete_listing','start_ad_campaign',
    'increase_ad_budget','allocate_ad_budget','change_store_design','refund',
    'send_customer_message','cancel_order','update_listing','other',
    'create_listing','update_listing_translation'));

-- Listing creation fields the platform tracks (Etsy createDraftListing)
alter table public.listings
  add column return_policy_id        bigint,
  add column production_partner_ids  bigint[] not null default array[]::bigint[],
  add column listing_type            text check (listing_type in ('physical','download','both'));
