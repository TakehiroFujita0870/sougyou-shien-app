begin;

create table public.project_knowledge (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  source_project_id uuid not null,
  source_type text not null check (source_type in ('anonymized_customer_interview_derivative', 'decision', 'manual')),
  source_id uuid not null,
  anonymized_content text not null check (char_length(btrim(anonymized_content)) > 0),
  deleted_at timestamptz,
  constraint project_knowledge_source_project_owner_fk foreign key (source_project_id, owner_id) references public.ideas(id, owner_id) on delete cascade,
  constraint project_knowledge_id_owner_unique unique (id, owner_id),
  constraint project_knowledge_id_owner_project_unique unique (id, owner_id, source_project_id)
);

create table public.knowledge_grants (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  knowledge_id uuid not null,
  source_project_id uuid not null,
  target_project_id uuid not null,
  granted_at timestamptz not null default now(),
  revoked_at timestamptz,
  constraint knowledge_grants_knowledge_source_owner_fk foreign key (knowledge_id, owner_id, source_project_id) references public.project_knowledge(id, owner_id, source_project_id) on delete cascade,
  constraint knowledge_grants_source_project_owner_fk foreign key (source_project_id, owner_id) references public.ideas(id, owner_id) on delete cascade,
  constraint knowledge_grants_target_project_owner_fk foreign key (target_project_id, owner_id) references public.ideas(id, owner_id) on delete cascade
);

create index project_knowledge_owner_id_idx on public.project_knowledge(owner_id);
create index knowledge_grants_owner_id_idx on public.knowledge_grants(owner_id);
alter table public.project_knowledge enable row level security;
alter table public.project_knowledge force row level security;
alter table public.knowledge_grants enable row level security;
alter table public.knowledge_grants force row level security;
create policy project_knowledge_select_own on public.project_knowledge for select to authenticated using ((select auth.uid()) = owner_id);
create policy project_knowledge_insert_own on public.project_knowledge for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy project_knowledge_update_own on public.project_knowledge for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy project_knowledge_delete_own on public.project_knowledge for delete to authenticated using ((select auth.uid()) = owner_id);
create policy knowledge_grants_select_own on public.knowledge_grants for select to authenticated using ((select auth.uid()) = owner_id);
create policy knowledge_grants_insert_own on public.knowledge_grants for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy knowledge_grants_update_own on public.knowledge_grants for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy knowledge_grants_delete_own on public.knowledge_grants for delete to authenticated using ((select auth.uid()) = owner_id);

create function public.prevent_knowledge_grant_reactivation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at then
    raise exception 'a revoked knowledge grant cannot be reactivated';
  end if;
  return new;
end;
$$;
create trigger knowledge_grants_revoke_is_final
before update on public.knowledge_grants
for each row execute function public.prevent_knowledge_grant_reactivation();

create view public.active_project_knowledge with (security_invoker = true) as
  select kg.knowledge_id, kg.source_project_id, kg.target_project_id, pk.anonymized_content
  from public.knowledge_grants kg join public.project_knowledge pk on pk.id = kg.knowledge_id and pk.owner_id = kg.owner_id
  where kg.owner_id = (select auth.uid()) and kg.revoked_at is null and pk.deleted_at is null;
grant select, insert, update, delete on public.project_knowledge to authenticated;
grant select, insert, update, delete on public.knowledge_grants to authenticated;
grant select on public.active_project_knowledge to authenticated;
commit;
