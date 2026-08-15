-- Additive storage contract for local/fake embeddings. pgvector is deliberately
-- not enabled here: its managed lifecycle is verified at release-gate #31.
begin;

create table public.dots_document_chunk_embeddings (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  chunk_id uuid not null,
  adapter_name text not null check (char_length(btrim(adapter_name)) > 0),
  embedding jsonb not null check (jsonb_typeof(embedding) = 'array'),
  state text not null default 'ready' check (state in ('pending', 'ready', 'failed', 'deleted')),
  created_at timestamptz not null default now(),
  constraint document_chunk_embeddings_chunk_owner_fk
    foreign key (chunk_id, owner_id)
    references public.dots_document_chunks(id, owner_id)
    on delete cascade,
  constraint document_chunk_embeddings_chunk_adapter_unique unique (chunk_id, adapter_name)
);

create index document_chunk_embeddings_owner_id_idx on public.dots_document_chunk_embeddings(owner_id);

-- Target SQL after release-gate #31: vector(384), HNSW and RRF with the existing
-- tsvector rank. Do not run `create extension vector` until that gate validates it.
alter table public.dots_document_chunk_embeddings enable row level security;
alter table public.dots_document_chunk_embeddings force row level security;

create policy document_chunk_embeddings_select_own on public.dots_document_chunk_embeddings for select to authenticated using ((select auth.uid()) = owner_id);
create policy document_chunk_embeddings_insert_own on public.dots_document_chunk_embeddings for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy document_chunk_embeddings_update_own on public.dots_document_chunk_embeddings for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy document_chunk_embeddings_delete_own on public.dots_document_chunk_embeddings for delete to authenticated using ((select auth.uid()) = owner_id);

revoke all on public.dots_document_chunk_embeddings from anon, authenticated;
grant select, insert, update, delete on public.dots_document_chunk_embeddings to authenticated;

commit;
