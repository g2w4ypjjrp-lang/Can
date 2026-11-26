-- =============================================================================
-- 0017 Phase 6 — Design studio
-- =============================================================================
alter table public.designs
  add column opportunity_id uuid references public.product_opportunities (id) on delete set null,
  add column product_type   text,
  add column style          text,
  add column ip_review      jsonb,
  add column ip_reviewed_at timestamptz,
  add column approved_by    uuid references public.users (id) on delete set null,
  add column approved_at    timestamptz;
create index designs_opportunity_idx on public.designs (opportunity_id);

alter table public.design_versions
  add column parent_version_id uuid references public.design_versions (id) on delete set null,
  add column operation         text not null default 'upload'
    check (operation in ('upload','ai_generate','remove_background','prepare_print')),
  add column fit_report        jsonb,
  add column print_area        jsonb,
  add column ai_task_id        uuid references public.ai_tasks (id) on delete set null;
create index design_versions_parent_idx on public.design_versions (parent_version_id);
create index design_versions_ai_task_idx on public.design_versions (ai_task_id);

-- the AI may only produce designs with an explicit human creative direction (Etsy AI policy)
alter table public.designs
  add constraint designs_ai_requires_human check (prompt is null or char_length(coalesce(human_contribution, '')) >= 20);
