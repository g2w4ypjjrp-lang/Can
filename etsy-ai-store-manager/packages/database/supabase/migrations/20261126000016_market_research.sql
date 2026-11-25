-- =============================================================================
-- 0016 Phase 5 — AI market research & product opportunities
-- =============================================================================
alter table public.market_research
  add column buyer_country  char(2),
  add column use_web_search boolean not null default false,
  add column error          text,
  add column completed_at   timestamptz;

alter table public.keywords
  add column active_listings   integer check (active_listings >= 0),
  add column median_price_usd  numeric(12,2),
  add column avg_favorers      numeric(12,2),
  add column top_tags          jsonb not null default '[]'::jsonb,
  add column market_research_id uuid references public.market_research (id) on delete set null;
create index keywords_market_research_idx on public.keywords (market_research_id);

alter table public.product_opportunities
  add column product_type     text,
  add column personalization  boolean not null default false,
  add column ip_risk          text check (ip_risk in ('low','medium','high')),
  add column ip_risk_notes    text,
  add column rationale        text,
  add column est_decision     text check (est_decision in ('excellent','publishable','needs_approval','not_recommended','rejected')),
  add column score_breakdown  jsonb not null default '{}'::jsonb,
  add column decided_by       uuid references public.users (id) on delete set null,
  add column decided_at       timestamptz;
