begin;

create extension if not exists pgcrypto;

create type public.dots_idea_status as enum (
  'draft',
  'stage_0',
  'stage_1',
  'stage_2',
  'stage_3',
  'stage_4',
  'graduated',
  'graveyard'
);

create type public.dots_stage_run_status as enum (
  'pending',
  'running',
  'passed',
  'failed',
  'cancelled'
);

create type public.dots_deletion_request_status as enum (
  'pending',
  'processing',
  'completed',
  'rejected'
);

create table public.dots_ideas (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  pain_statement text not null,
  status public.dots_idea_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ideas_pain_statement_length
    check (char_length(btrim(pain_statement)) between 1 and 500),
  constraint ideas_id_owner_unique unique (id, owner_id)
);

create table public.dots_stage_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  stage smallint not null check (stage between 0 and 4),
  actor_role text not null check (actor_role in ('ideator', 'falsifier', 'analyst', 'validator', 'recorder')),
  execution_id uuid not null default gen_random_uuid(),
  status public.dots_stage_run_status not null default 'pending',
  artifact jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint stage_runs_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.dots_ideas(id, owner_id)
    on delete cascade,
  constraint stage_runs_execution_unique unique (idea_id, stage, execution_id),
  constraint stage_runs_completion_consistent check (
    (status in ('passed', 'failed', 'cancelled') and completed_at is not null)
    or (status in ('pending', 'running') and completed_at is null)
  )
);

create table public.dots_death_causes (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  stage_run_id uuid references public.dots_stage_runs(id) on delete set null,
  surface_cause text not null check (char_length(btrim(surface_cause)) > 0),
  root_cause text not null check (char_length(btrim(root_cause)) > 0),
  source_url text not null check (source_url ~* '^https://'),
  created_at timestamptz not null default now(),
  constraint death_causes_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.dots_ideas(id, owner_id)
    on delete cascade
);

create table public.dots_decision_records (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  category text not null check (category in ('a', 'b', 'c', 'd', 'e')),
  reason text not null check (char_length(btrim(reason)) >= 5),
  decided_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint decision_records_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.dots_ideas(id, owner_id)
    on delete cascade
);

create table public.dots_consents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  anonymized_statistics_opt_in boolean not null default false,
  consent_version text not null,
  granted_at timestamptz not null default now(),
  withdrawn_at timestamptz,
  constraint consents_version_length check (char_length(btrim(consent_version)) > 0)
);

create table public.dots_deletion_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  status public.dots_deletion_request_status not null default 'pending',
  requested_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint deletion_requests_completion_consistent check (
    (status = 'completed' and completed_at is not null)
    or (status <> 'completed' and completed_at is null)
  )
);

create index ideas_owner_id_idx on public.dots_ideas(owner_id);
create index stage_runs_owner_idea_idx on public.dots_stage_runs(owner_id, idea_id);
create index death_causes_owner_idea_idx on public.dots_death_causes(owner_id, idea_id);
create index decision_records_owner_idea_idx on public.dots_decision_records(owner_id, idea_id);
create index consents_owner_id_idx on public.dots_consents(owner_id);
create index deletion_requests_owner_id_idx on public.dots_deletion_requests(owner_id);

create function public.dots_set_updated_at()
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
before update on public.dots_ideas
for each row execute function public.dots_set_updated_at();

alter table public.dots_ideas enable row level security;
alter table public.dots_stage_runs enable row level security;
alter table public.dots_death_causes enable row level security;
alter table public.dots_decision_records enable row level security;
alter table public.dots_consents enable row level security;
alter table public.dots_deletion_requests enable row level security;

alter table public.dots_ideas force row level security;
alter table public.dots_stage_runs force row level security;
alter table public.dots_death_causes force row level security;
alter table public.dots_decision_records force row level security;
alter table public.dots_consents force row level security;
alter table public.dots_deletion_requests force row level security;

create policy ideas_select_own on public.dots_ideas
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy ideas_insert_own on public.dots_ideas
for insert to authenticated
with check ((select auth.uid()) = owner_id and status = 'draft');

create policy ideas_update_own_draft on public.dots_ideas
for update to authenticated
using ((select auth.uid()) = owner_id and status = 'draft')
with check ((select auth.uid()) = owner_id and status = 'draft');

create policy stage_runs_select_own on public.dots_stage_runs
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy death_causes_select_own on public.dots_death_causes
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy decision_records_select_own on public.dots_decision_records
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy consents_select_own on public.dots_consents
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy consents_insert_own on public.dots_consents
for insert to authenticated
with check ((select auth.uid()) = owner_id);

create policy consents_withdraw_own on public.dots_consents
for update to authenticated
using ((select auth.uid()) = owner_id and withdrawn_at is null)
with check ((select auth.uid()) = owner_id and withdrawn_at is not null);

create policy deletion_requests_select_own on public.dots_deletion_requests
for select to authenticated
using ((select auth.uid()) = owner_id);

create policy deletion_requests_insert_own on public.dots_deletion_requests
for insert to authenticated
with check ((select auth.uid()) = owner_id and status = 'pending' and completed_at is null);

revoke all on public.dots_ideas from anon, authenticated;
revoke all on public.dots_stage_runs from anon, authenticated;
revoke all on public.dots_death_causes from anon, authenticated;
revoke all on public.dots_decision_records from anon, authenticated;
revoke all on public.dots_consents from anon, authenticated;
revoke all on public.dots_deletion_requests from anon, authenticated;

grant select, insert on public.dots_ideas to authenticated;
grant update (pain_statement) on public.dots_ideas to authenticated;
grant select on public.dots_stage_runs to authenticated;
grant select on public.dots_death_causes to authenticated;
grant select on public.dots_decision_records to authenticated;
grant select, insert on public.dots_consents to authenticated;
grant update (withdrawn_at) on public.dots_consents to authenticated;
grant select, insert on public.dots_deletion_requests to authenticated;

commit;
