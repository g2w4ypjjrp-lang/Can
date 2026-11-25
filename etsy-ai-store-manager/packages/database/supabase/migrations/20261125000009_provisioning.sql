-- =============================================================================
-- 0009 Provisioning triggers & access helpers
-- =============================================================================

create or replace function private.store_role_rank(p_role text)
returns integer
language sql
immutable
set search_path = ''
as $$
  select case p_role
    when 'owner' then 40
    when 'admin' then 30
    when 'analyst' then 20
    when 'viewer' then 10
    else 0
  end;
$$;

-- True when the current JWT subject has at least p_min_role on the store.
create or replace function private.has_store_role(p_store_id uuid, p_min_role text default 'viewer')
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.store_members m
    where m.store_id = p_store_id
      and m.user_id = (select auth.uid())
      and private.store_role_rank(m.role) >= private.store_role_rank(p_min_role)
  );
$$;

-- New Supabase Auth user -> application profile + default settings -------------
create or replace function private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.users (id, email, full_name)
  values (new.id, coalesce(new.email, ''), nullif(new.raw_user_meta_data ->> 'full_name', ''))
  on conflict (id) do nothing;

  insert into public.user_settings (user_id) values (new.id)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_auth_user();

create or replace function private.handle_auth_user_email_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.email is distinct from old.email then
    update public.users set email = coalesce(new.email, '') where id = new.id;
  end if;
  return new;
end;
$$;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row execute function private.handle_auth_user_email_change();

-- New store -> owner membership, settings and default profit policy -------------
create or replace function private.handle_new_store()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.store_members (store_id, user_id, role)
  values (new.id, new.owner_user_id, 'owner')
  on conflict do nothing;

  insert into public.store_settings (store_id, default_language, languages)
  values (new.id, new.default_language, array[new.default_language])
  on conflict (store_id) do nothing;

  insert into public.profit_rules (store_id, currency)
  values (new.id, new.currency)
  on conflict (store_id) do nothing;
  return new;
end;
$$;

create trigger on_store_created
  after insert on public.stores
  for each row execute function private.handle_new_store();

-- Ownership transfer is a privileged operation (service role only) -------------
create or replace function private.guard_store_owner()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.owner_user_id is distinct from old.owner_user_id
     and coalesce(current_setting('role', true), '') in ('authenticated','anon') then
    raise exception 'store ownership cannot be changed by clients' using errcode = '42501';
  end if;
  return new;
end;
$$;

create trigger stores_guard_owner before update on public.stores
  for each row execute function private.guard_store_owner();
