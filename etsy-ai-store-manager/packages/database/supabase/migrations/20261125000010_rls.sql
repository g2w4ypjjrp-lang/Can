-- =============================================================================
-- 0010 Grants & Row Level Security
-- Principle: deny by default. anon gets nothing. authenticated users see only
-- data of stores they are members of. oauth_tokens has NO client policy at all.
-- =============================================================================

grant usage on schema public to authenticated, service_role;
grant usage on schema private to authenticated, service_role;
grant execute on function private.has_store_role(uuid, text) to authenticated, service_role;
grant execute on function private.store_role_rank(text) to authenticated, service_role;

grant select, insert, update, delete on all tables in schema public to authenticated, service_role;
grant usage, select on all sequences in schema public to authenticated, service_role;
revoke all on all tables in schema public from anon;

-- Enable RLS on every table in public ----------------------------------------
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;

-- Secrets: no client access whatsoever -----------------------------------------
revoke all on public.oauth_tokens from authenticated;

-- Users & personal settings -----------------------------------------------------
create policy users_select_self on public.users for select to authenticated
  using (id = (select auth.uid()));
create policy users_update_self on public.users for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

create policy user_settings_select_self on public.user_settings for select to authenticated
  using (user_id = (select auth.uid()));
create policy user_settings_insert_self on public.user_settings for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy user_settings_update_self on public.user_settings for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- Stores & membership -----------------------------------------------------------
create policy stores_select_member on public.stores for select to authenticated
  using (private.has_store_role(id, 'viewer'));
create policy stores_insert_owner on public.stores for insert to authenticated
  with check (owner_user_id = (select auth.uid()));
create policy stores_update_admin on public.stores for update to authenticated
  using (private.has_store_role(id, 'admin')) with check (private.has_store_role(id, 'admin'));
create policy stores_delete_owner on public.stores for delete to authenticated
  using (private.has_store_role(id, 'owner'));

create policy store_members_select on public.store_members for select to authenticated
  using (user_id = (select auth.uid()) or private.has_store_role(store_id, 'admin'));
create policy store_members_manage_owner on public.store_members for all to authenticated
  using (private.has_store_role(store_id, 'owner')) with check (private.has_store_role(store_id, 'owner'));

-- Generic store-scoped tables ---------------------------------------------------
-- read: viewer+, write: admin+
do $$
declare
  t text;
  rw_tables text[] := array[
    'store_settings','connected_accounts','designs','design_versions','products','product_variants',
    'product_costs','product_images','listings','listing_translations','market_research',
    'competitor_research','keywords','product_opportunities','approval_requests','orders',
    'order_items','shipments','refunds','ad_accounts','ad_campaigns','ad_metrics','ad_spend',
    'profit_rules','profit_snapshots','price_recommendations','tax_reserves'
  ];
  -- written only by the server/worker (service role); clients may read
  ro_tables text[] := array['ai_tasks','ai_decisions','automation_jobs'];
  -- contain customer PII: admin+ only
  pii_tables text[] := array['customers','customer_messages'];
begin
  foreach t in array rw_tables loop
    execute format($f$create policy %1$s_select on public.%1$I for select to authenticated
      using (private.has_store_role(store_id, 'viewer'))$f$, t);
    execute format($f$create policy %1$s_insert on public.%1$I for insert to authenticated
      with check (private.has_store_role(store_id, 'admin'))$f$, t);
    execute format($f$create policy %1$s_update on public.%1$I for update to authenticated
      using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'))$f$, t);
    execute format($f$create policy %1$s_delete on public.%1$I for delete to authenticated
      using (private.has_store_role(store_id, 'admin'))$f$, t);
  end loop;

  foreach t in array ro_tables loop
    execute format($f$create policy %1$s_select on public.%1$I for select to authenticated
      using (store_id is not null and private.has_store_role(store_id, 'viewer'))$f$, t);
  end loop;

  foreach t in array pii_tables loop
    execute format($f$create policy %1$s_all_admin on public.%1$I for all to authenticated
      using (private.has_store_role(store_id, 'admin')) with check (private.has_store_role(store_id, 'admin'))$f$, t);
  end loop;
end $$;

-- Store settings / profit rules rows are created by trigger; never deleted by clients
drop policy store_settings_delete on public.store_settings;
drop policy profit_rules_delete on public.profit_rules;
drop policy profit_rules_insert on public.profit_rules;
drop policy store_settings_insert on public.store_settings;

-- Approval requests: clients may create & decide, never delete (audit trail)
drop policy approval_requests_delete on public.approval_requests;
-- Profit snapshots are immutable calculation records
drop policy profit_snapshots_update on public.profit_snapshots;
drop policy profit_snapshots_delete on public.profit_snapshots;

-- Fee rules: global rules readable by everyone signed-in, written by service only
create policy fee_rules_select on public.fee_rules for select to authenticated
  using (store_id is null or private.has_store_role(store_id, 'viewer'));
create policy fee_rules_write_store on public.fee_rules for all to authenticated
  using (store_id is not null and private.has_store_role(store_id, 'admin'))
  with check (store_id is not null and private.has_store_role(store_id, 'admin'));

create policy fx_rates_select on public.fx_rates for select to authenticated using (true);

-- Notifications: personal
create policy notifications_select_self on public.notifications for select to authenticated
  using (user_id = (select auth.uid()));
create policy notifications_update_self on public.notifications for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- Logs: readable by store admins, written only by the server
create policy audit_logs_select_admin on public.audit_logs for select to authenticated
  using (store_id is not null and private.has_store_role(store_id, 'admin')
         or actor_user_id = (select auth.uid()));
create policy api_logs_select_admin on public.api_logs for select to authenticated
  using (store_id is not null and private.has_store_role(store_id, 'admin'));
