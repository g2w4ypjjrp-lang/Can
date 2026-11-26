-- =============================================================================
-- 0020 Phase 9 — Orders, customers, shipping, refunds, reviews, AI reply drafts
-- =============================================================================

-- Etsy shop reviews (getReviewsByShop). The ListingReview schema has no review or
-- transaction id: (listing_id, created_timestamp) identifies a review.
create table public.shop_reviews (
  id                    uuid primary key default gen_random_uuid(),
  store_id              uuid not null references public.stores (id) on delete cascade,
  etsy_listing_id       bigint not null,
  listing_id            uuid references public.listings (id) on delete set null,
  rating                smallint not null check (rating between 1 and 5),
  review                text,
  language              text,
  etsy_created_at       timestamptz not null,
  etsy_updated_at       timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (store_id, etsy_listing_id, etsy_created_at)
);
create index shop_reviews_store_idx on public.shop_reviews (store_id, etsy_created_at desc);
create index shop_reviews_listing_idx on public.shop_reviews (listing_id);
create trigger shop_reviews_updated_at before update on public.shop_reviews
  for each row execute function private.set_updated_at();
alter table public.shop_reviews enable row level security;
grant select, insert, update, delete on public.shop_reviews to authenticated, service_role;
create policy shop_reviews_select on public.shop_reviews for select to authenticated
  using (private.has_store_role(store_id, 'viewer'));

-- Message triage: AI classification and reply drafts (never sent automatically)
alter table public.customer_messages
  add column source            text not null default 'manual' check (source in ('manual','etsy_review')),
  add column review_id         uuid references public.shop_reviews (id) on delete cascade,
  add column urgency           text check (urgency in ('low','normal','high','critical')),
  add column issues            jsonb not null default '[]'::jsonb,
  add column suggested_action  text check (suggested_action in ('reply','refund','replacement','shipping_check','personalization_fix','none')),
  add column internal_note     text,
  add column draft_language    text,
  add column ai_task_id        uuid references public.ai_tasks (id) on delete set null,
  add column ai_error          text,
  add column created_by        uuid references public.users (id) on delete set null;
create unique index customer_messages_review_key on public.customer_messages (review_id) where review_id is not null;
create index customer_messages_ai_task_idx on public.customer_messages (ai_task_id);
create index customer_messages_created_by_idx on public.customer_messages (created_by);
alter table public.customer_messages drop constraint customer_messages_status_check;
alter table public.customer_messages add constraint customer_messages_status_check
  check (status in ('new','classifying','draft_ready','awaiting_approval','sent','closed','failed'));

-- Refund requests carry the Profit Engine impact shown in the approval
alter table public.refunds
  add column contribution_before  numeric(14,4),
  add column contribution_after   numeric(14,4),
  add column requested_by         uuid references public.users (id) on delete set null;
create index refunds_requested_by_idx on public.refunds (requested_by);

-- Processing window used for delay detection (Etsy processing profiles are not synced)
alter table public.store_settings
  add column processing_days_max integer not null default 7 check (processing_days_max between 1 and 60),
  add column transit_days_max    integer not null default 21 check (transit_days_max between 1 and 90);

-- Shipments the platform submitted to Etsy (createReceiptShipment)
alter table public.shipments
  add column source           text not null default 'printify' check (source in ('printify','etsy','manual')),
  add column etsy_submitted_at timestamptz;

alter table public.approval_requests drop constraint approval_requests_action_type_check;
alter table public.approval_requests add constraint approval_requests_action_type_check check (action_type in (
  'publish_product','change_price','delete_listing','start_ad_campaign',
  'increase_ad_budget','allocate_ad_budget','change_store_design','refund',
  'send_customer_message','cancel_order','update_listing','other',
  'create_listing','update_listing_translation','add_tracking'));
