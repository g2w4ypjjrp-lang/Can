-- =============================================================================
-- 0001 Foundation: schemas, extensions, shared helper functions
-- Etsy AI Store Manager
-- =============================================================================

create extension if not exists pgcrypto with schema extensions;

-- Helpers that must never be exposed through the Data API live in "private".
create schema if not exists private;
revoke all on schema private from public;

-- Generic updated_at maintenance -------------------------------------------------
create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Append-only guard (used by audit_logs) ----------------------------------------
create or replace function private.prevent_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = '42501';
end;
$$;
