begin;

create extension if not exists pgcrypto;

create type public.idea_status as enum (
  'draft',
  'stage_0',
  'stage_1',
  'stage_2',
  'stage_3',
  'stage_4',
  'graduated',
  'graveyard'
);

create type public.stage_run_status as enum (
  'pending',
  'running',
  'passed',
  'failed',
  'cancelled'
);

create type public.deletion_request_status as enum (
  'pending',
  'processing',
  'completed',
  'rejected'
);

create table public.ideas (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  pain_statement text not null,
  status public.idea_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ideas_pain_statement_length
    check (char_length(btrim(pain_statement)) between 1 and 500),
  constraint ideas_id_owner_unique unique (id, owner_id)
);

create table public.stage_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  stage smallint not null check (stage between 0 and 4),
  actor_role text not null check (actor_role in ('ideator', 'falsifier', 'analyst', 'validator', 'recorder')),
  execution_id uuid not null default gen_random_uuid(),
  status public.stage_run_status not null default 'pending',
  artifact jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint stage_runs_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.ideas(id, owner_id)
    on delete cascade,
  constraint stage_runs_execution_unique unique (idea_id, stage, execution_id),
  constraint stage_runs_completion_consistent check (
    (status in ('passed', 'failed', 'cancelled') and completed_at is not null)
    or (status in ('pending', 'running') and completed_at is null)
  )
);

create table public.death_causes (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  stage_run_id uuid references public.stage_runs(id) on delete set null,
  surface_cause text not null check (char_length(btrim(surface_cause)) > 0),
  root_cause text not null check (char_length(btrim(root_cause)) > 0),
  source_url text not null check (source_url ~* '^https://'),
  created_at timestamptz not null default now(),
  constraint death_causes_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.ideas(id, owner_id)
    on delete cascade
);

create table public.decision_records (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  category text not null check (category in ('a', 'b', 'c', 'd', 'e')),
  reason text not null check (char_length(btrim(reason)) >= 5),
  decided_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint decision_records_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.ideas(id, owner_id)
    on delete cascade
);

create table public.consents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  anonymized_statistics_opt_in boolean not null default false,
  consent_version text not null,
  granted_at timestamptz not null default now(),
  withdrawn_at timestamptz,
  constraint consents_version_length check (char_length(btrim(consent_version)) > 0)
);

create table public.deletion_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  status public.deletion_request_status not null default 'pending',
  requested_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint deletion_requests_completion_consistent check (
    (status = 'completed' and completed_at is not null)
    or (status <> 'completed' and completed_at is null)
  )
);

create index ideas_owner_id_idx on public.ideas(owner_id);
create index stage_runs_owner_idea_idx on public.stage_runs(owner_id, idea_id);
create index death_causes_owner_idea_idx on public.death_causes(owner_id, idea_id);
create index decision_records_owner_idea_idx on public.decision_records(owner_id, idea_id);
create index consents_owner_id_idx on public.consents(owner_id);
create index deletion_requests_owner_id_idx on public.deletion_requests(owner_id);

create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger ideas_set_updated_at
before update on public.ideas
for each row execute function public.set_updated_at();

alter table public.ideas enable row level security;
alter table public.stage_runs enable row level security;
alter table public.death_causes enable row level security;
alter table public.decision_records enable row level security;
alter table public.consents enable row level security;
alter table public.deletion_requests enable row level security;

alter table public.ideas force row level security;
alter table public.stage_runs force row level security;
alter table public.death_causes force row level security;
alter table public.decision_records force row level security;
alter table public.consents force row level security;
alter table public.deletion_requests force row level security;

create policy ideas_select_own on public.ideas
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy ideas_insert_own on public.ideas
for insert to authenticated
with check ((select auth.uid()) = owner_id and status = 'draft');

create policy ideas_update_own_draft on public.ideas
for update to authenticated
using ((select auth.uid()) = owner_id and status = 'draft')
with check ((select auth.uid()) = owner_id and status = 'draft');

create policy stage_runs_select_own on public.stage_runs
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy death_causes_select_own on public.death_causes
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy decision_records_select_own on public.decision_records
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy consents_select_own on public.consents
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy consents_insert_own on public.consents
for insert to authenticated
with check ((select auth.uid()) = owner_id);

create policy consents_withdraw_own on public.consents
for update to authenticated
using ((select auth.uid()) = owner_id and withdrawn_at is null)
with check ((select auth.uid()) = owner_id and withdrawn_at is not null);

create policy deletion_requests_select_own on public.deletion_requests
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy deletion_requests_insert_own on public.deletion_requests
for insert to authenticated
with check ((select auth.uid()) = owner_id and status = 'pending' and completed_at is null);

revoke all on public.ideas from anon, authenticated;
revoke all on public.stage_runs from anon, authenticated;
revoke all on public.death_causes from anon, authenticated;
revoke all on public.decision_records from anon, authenticated;
revoke all on public.consents from anon, authenticated;
revoke all on public.deletion_requests from anon, authenticated;

grant select, insert on public.ideas to authenticated;
grant update (pain_statement) on public.ideas to authenticated;
grant select on public.stage_runs to authenticated;
grant select on public.death_causes to authenticated;
grant select on public.decision_records to authenticated;
grant select, insert on public.consents to authenticated;
grant update (withdrawn_at) on public.consents to authenticated;
grant select, insert on public.deletion_requests to authenticated;

commit;
