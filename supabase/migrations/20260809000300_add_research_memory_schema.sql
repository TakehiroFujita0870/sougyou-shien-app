-- Additive migration: existing decision_records and their API contract are unchanged.
-- The transaction makes a failed deployment atomic; rollback can drop these new objects
-- in reverse dependency order without changing pre-existing tables.
begin;

create table public.source_documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  source_type text not null check (source_type in ('file', 'web', 'manual')),
  title text not null check (char_length(btrim(title)) between 1 and 500),
  state text not null default 'pending'
    check (state in ('pending', 'processing', 'ready', 'failed', 'deleted')),
  current_version_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint source_documents_id_owner_unique unique (id, owner_id)
);

create table public.document_versions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null,
  version_number integer not null check (version_number > 0),
  storage_path text not null check (char_length(btrim(storage_path)) > 0),
  mime_type text not null check (char_length(btrim(mime_type)) > 0),
  content_hash text not null check (char_length(btrim(content_hash)) > 0),
  extraction_state text not null default 'pending'
    check (extraction_state in ('pending', 'processing', 'completed', 'failed')),
  created_at timestamptz not null default now(),
  constraint document_versions_document_owner_fk
    foreign key (document_id, owner_id)
    references public.source_documents(id, owner_id)
    on delete cascade,
  constraint document_versions_id_owner_unique unique (id, owner_id),
  constraint document_versions_document_version_unique unique (document_id, version_number)
);

alter table public.source_documents
  add constraint source_documents_current_version_fk
  foreign key (current_version_id)
  references public.document_versions(id)
  on delete set null;

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  version_id uuid not null,
  page integer check (page is null or page > 0),
  chunk_index integer not null check (chunk_index >= 0),
  content text not null check (char_length(btrim(content)) > 0),
  textsearch tsvector generated always as (to_tsvector('simple', content)) stored,
  created_at timestamptz not null default now(),
  constraint document_chunks_version_owner_fk
    foreign key (version_id, owner_id)
    references public.document_versions(id, owner_id)
    on delete cascade,
  constraint document_chunks_version_chunk_unique unique (version_id, chunk_index)
);

create table public.research_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idea_id uuid not null,
  selected_sources jsonb not null default '[]'::jsonb,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'completed', 'failed', 'cancelled')),
  model_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint research_runs_idea_owner_fk
    foreign key (idea_id, owner_id)
    references public.ideas(id, owner_id)
    on delete cascade,
  constraint research_runs_id_owner_unique unique (id, owner_id)
);

create table public.research_evidence (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  run_id uuid not null,
  source_type text not null check (source_type in ('web', 'patent', 'document', 'decision')),
  locator text not null check (char_length(btrim(locator)) > 0),
  excerpt text not null check (char_length(btrim(excerpt)) > 0),
  fetched_at timestamptz not null default now(),
  content_hash text not null check (char_length(btrim(content_hash)) > 0),
  created_at timestamptz not null default now(),
  constraint research_evidence_run_owner_fk
    foreign key (run_id, owner_id)
    references public.research_runs(id, owner_id)
    on delete cascade,
  constraint research_evidence_id_owner_unique unique (id, owner_id)
);

create table public.decision_observations (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  decision_id uuid not null,
  observation text not null check (char_length(btrim(observation)) > 0),
  disposition text not null check (disposition in ('accepted', 'rejected', 'pending', 'reconsider')),
  evidence_id uuid,
  created_at timestamptz not null default now(),
  constraint decision_observations_decision_owner_fk
    foreign key (decision_id, owner_id)
    references public.decision_records(id, owner_id)
    on delete cascade,
  constraint decision_observations_evidence_owner_fk
    foreign key (evidence_id, owner_id)
    references public.research_evidence(id, owner_id)
    on delete set null (evidence_id)
);

create index source_documents_owner_id_idx on public.source_documents(owner_id);
create index document_versions_owner_id_idx on public.document_versions(owner_id);
create index document_chunks_owner_id_idx on public.document_chunks(owner_id);
create index document_chunks_textsearch_idx on public.document_chunks using gin (textsearch);
create index research_runs_owner_id_idx on public.research_runs(owner_id);
create index research_evidence_owner_id_idx on public.research_evidence(owner_id);
create index decision_observations_owner_id_idx on public.decision_observations(owner_id);

-- pgvector/HNSW is intentionally deferred until the managed extension and its
-- lifecycle are verified in a dedicated spike. This migration is safe on the
-- existing pgcrypto-only environment and provides the keyword half of ADR-02.
create function public.search_document_chunks(search_query text, result_limit integer default 20)
returns table (
  chunk_id uuid,
  document_id uuid,
  version_id uuid,
  page integer,
  content text,
  rank real
)
language sql
stable
set search_path = ''
as $$
  select
    dc.id,
    sd.id,
    dc.version_id,
    dc.page,
    dc.content,
    ts_rank(dc.textsearch, websearch_to_tsquery('simple', search_query))::real
  from public.document_chunks as dc
  join public.document_versions as dv on dv.id = dc.version_id
  join public.source_documents as sd on sd.id = dv.document_id
  where dc.owner_id = (select auth.uid())
    and sd.owner_id = (select auth.uid())
    and sd.state = 'ready'
    and sd.current_version_id = dv.id
    and dc.textsearch @@ websearch_to_tsquery('simple', search_query)
  order by rank desc, dc.created_at desc
  limit greatest(1, least(result_limit, 100));
$$;

alter table public.source_documents enable row level security;
alter table public.document_versions enable row level security;
alter table public.document_chunks enable row level security;
alter table public.research_runs enable row level security;
alter table public.research_evidence enable row level security;
alter table public.decision_observations enable row level security;

alter table public.source_documents force row level security;
alter table public.document_versions force row level security;
alter table public.document_chunks force row level security;
alter table public.research_runs force row level security;
alter table public.research_evidence force row level security;
alter table public.decision_observations force row level security;

create policy source_documents_select_own on public.source_documents for select to authenticated using ((select auth.uid()) = owner_id);
create policy source_documents_insert_own on public.source_documents for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy source_documents_update_own on public.source_documents for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy source_documents_delete_own on public.source_documents for delete to authenticated using ((select auth.uid()) = owner_id);

create policy document_versions_select_own on public.document_versions for select to authenticated using ((select auth.uid()) = owner_id);
create policy document_versions_insert_own on public.document_versions for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy document_versions_update_own on public.document_versions for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy document_versions_delete_own on public.document_versions for delete to authenticated using ((select auth.uid()) = owner_id);

create policy document_chunks_select_own on public.document_chunks for select to authenticated using ((select auth.uid()) = owner_id);
create policy document_chunks_insert_own on public.document_chunks for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy document_chunks_update_own on public.document_chunks for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy document_chunks_delete_own on public.document_chunks for delete to authenticated using ((select auth.uid()) = owner_id);

create policy research_runs_select_own on public.research_runs for select to authenticated using ((select auth.uid()) = owner_id);
create policy research_runs_insert_own on public.research_runs for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy research_runs_update_own on public.research_runs for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy research_runs_delete_own on public.research_runs for delete to authenticated using ((select auth.uid()) = owner_id);

create policy research_evidence_select_own on public.research_evidence for select to authenticated using ((select auth.uid()) = owner_id);
create policy research_evidence_insert_own on public.research_evidence for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy research_evidence_update_own on public.research_evidence for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy research_evidence_delete_own on public.research_evidence for delete to authenticated using ((select auth.uid()) = owner_id);

create policy decision_observations_select_own on public.decision_observations for select to authenticated using ((select auth.uid()) = owner_id);
create policy decision_observations_insert_own on public.decision_observations for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy decision_observations_update_own on public.decision_observations for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy decision_observations_delete_own on public.decision_observations for delete to authenticated using ((select auth.uid()) = owner_id);

revoke all on public.source_documents from anon, authenticated;
revoke all on public.document_versions from anon, authenticated;
revoke all on public.document_chunks from anon, authenticated;
revoke all on public.research_runs from anon, authenticated;
revoke all on public.research_evidence from anon, authenticated;
revoke all on public.decision_observations from anon, authenticated;
grant select, insert, update, delete on public.source_documents to authenticated;
grant select, insert, update, delete on public.document_versions to authenticated;
grant select, insert, update, delete on public.document_chunks to authenticated;
grant select, insert, update, delete on public.research_runs to authenticated;
grant select, insert, update, delete on public.research_evidence to authenticated;
grant select, insert, update, delete on public.decision_observations to authenticated;

revoke all on function public.search_document_chunks(text, integer) from public;
grant execute on function public.search_document_chunks(text, integer) to authenticated;

commit;
