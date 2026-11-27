-- Kullanıcı işlemlerini denetim kaydına yazmanın tek yolu. Kimlik auth.uid()'den alınır, uydurulamaz.
create or replace function app.log_action(p_org uuid, p_action text, p_target_type text, p_target_id text,
                                          p_details jsonb default '{}')
returns void language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null or not app.is_member(p_org) then raise exception 'not allowed'; end if;
  if p_action !~ '^[a-z_]+\.[a-z_.]+$' then raise exception 'invalid action'; end if;
  insert into public.audit_logs(organization_id, actor_user_id, action, target_type, target_id, details)
  values (p_org, auth.uid(), p_action, p_target_type, p_target_id, coalesce(p_details, '{}'));
end $$;
grant execute on function app.log_action(uuid, text, text, text, jsonb) to authenticated;

-- Zamanlayıcı sorgusu için.
create index if not exists automation_rules_due on public.automation_rules(next_run_at) where enabled;
