-- =============================================================================
-- 0013 Phase 2 — Etsy integration support
-- =============================================================================

-- Short-lived, single-use OAuth state (CSRF protection + PKCE verifier storage).
-- Only the SHA-256 of `state` is stored; the PKCE verifier is AES-GCM encrypted.
create table public.oauth_states (
  id                         uuid primary key default gen_random_uuid(),
  state_hash                 text not null unique,
  platform                   text not null check (platform in ('etsy','printify','meta_ads','google_ads','pinterest_ads','tiktok_ads')),
  store_id                   uuid not null references public.stores (id) on delete cascade,
  user_id                    uuid not null references public.users (id) on delete cascade,
  code_verifier_ciphertext   text not null,
  expires_at                 timestamptz not null,
  used_at                    timestamptz,
  created_at                 timestamptz not null default now()
);
create index oauth_states_store_idx on public.oauth_states (store_id);
create index oauth_states_user_idx on public.oauth_states (user_id);
create index oauth_states_expiry_idx on public.oauth_states (expires_at);
alter table public.oauth_states enable row level security;
revoke all on public.oauth_states from anon, authenticated;
grant select, insert, update, delete on public.oauth_states to service_role;
-- (no policies: server-side only)

-- Listing extras captured during import
alter table public.listings
  add column etsy_url             text,
  add column primary_image_url    text,
  add column etsy_updated_at      timestamptz;

-- One Etsy shop can be linked to only one store record across the platform
-- (already enforced by stores_platform_external_key); connected_accounts per store/platform/account is unique.

-- Shipments imported from Etsy receipts are deduplicated per order + tracking number
create unique index shipments_order_tracking_key on public.shipments (order_id, coalesce(tracking_number, ''));

-- Refunds imported from Etsy (read-only data; issuing refunds is not possible via the API)
create unique index refunds_external_key on public.refunds (order_id, external_ref) where external_ref is not null;
