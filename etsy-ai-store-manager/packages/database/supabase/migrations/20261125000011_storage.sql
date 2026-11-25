-- =============================================================================
-- 0011 Supabase Storage buckets (private). Object path convention:
--   <store_id>/<entity>/<file>
-- Skipped automatically when the storage schema is absent (plain Postgres tests).
-- =============================================================================
do $$
begin
  if to_regclass('storage.buckets') is null then
    raise notice 'storage schema not present, skipping bucket setup';
    return;
  end if;

  insert into storage.buckets (id, name, public)
  values ('designs', 'designs', false), ('mockups', 'mockups', false), ('store-assets', 'store-assets', false)
  on conflict (id) do nothing;

  execute $p$
    create policy "store members read objects" on storage.objects for select to authenticated
    using (bucket_id in ('designs','mockups','store-assets')
           and private.has_store_role(((storage.foldername(name))[1])::uuid, 'viewer'))
  $p$;
  execute $p$
    create policy "store admins write objects" on storage.objects for insert to authenticated
    with check (bucket_id in ('designs','mockups','store-assets')
           and private.has_store_role(((storage.foldername(name))[1])::uuid, 'admin'))
  $p$;
  execute $p$
    create policy "store admins delete objects" on storage.objects for delete to authenticated
    using (bucket_id in ('designs','mockups','store-assets')
           and private.has_store_role(((storage.foldername(name))[1])::uuid, 'admin'))
  $p$;
end $$;
