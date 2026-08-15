from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809000300_add_research_memory_schema.sql"
)
SQL = MIGRATION.read_text(encoding="utf-8").lower()

TABLES = (
    "dots_source_documents",
    "dots_document_versions",
    "dots_document_chunks",
    "dots_research_runs",
    "dots_research_evidence",
    "dots_decision_observations",
)


def test_research_memory_tables_are_owner_scoped_with_full_authenticated_crud() -> None:
    for table in TABLES:
        assert f"create table public.{table}" in SQL
        assert "owner_id uuid not null references auth.users(id) on delete cascade" in SQL
        assert f"create index {table.removeprefix('dots_')}_owner_id_idx" in SQL
        assert f"alter table public.{table} enable row level security" in SQL
        assert f"alter table public.{table} force row level security" in SQL
        for operation in ("select", "insert", "update", "delete"):
            assert f"create policy {table.removeprefix('dots_')}_{operation}_own" in SQL


def test_all_write_policies_check_the_authenticated_owner() -> None:
    for table in TABLES:
        for operation in ("insert", "update"):
            policy = SQL.split(f"create policy {table.removeprefix('dots_')}_{operation}_own", 1)[1].split(";", 1)[0]
            assert "(select auth.uid()) = owner_id" in policy
            assert "with check" in policy


def test_document_search_is_owner_derived_and_uses_safe_full_text_indexing() -> None:
    assert "textsearch tsvector generated always as" in SQL
    assert "create index document_chunks_textsearch_idx" in SQL
    assert "using gin (textsearch)" in SQL
    assert "create function public.dots_search_document_chunks" in SQL
    function = SQL.split("create function public.dots_search_document_chunks", 1)[1].split("$$;", 1)[0]
    assert "auth.uid()" in function
    assert "owner_id" not in function.split("(", 1)[0]
    assert "pgvector/hnsw is intentionally deferred" in SQL


def test_owner_matched_cascades_preserve_existing_decision_records() -> None:
    assert "references public.dots_source_documents(id, owner_id)" in SQL
    assert "references public.dots_document_versions(id, owner_id)" in SQL
    assert "references public.dots_research_runs(id, owner_id)" in SQL
    assert "references public.dots_decision_records(id, owner_id)" in SQL
    assert "on delete cascade" in SQL
    assert "alter table public.dots_decision_records" not in SQL


def test_service_role_is_not_granted_to_browser_facing_roles() -> None:
    assert "grant" in SQL
    assert "service_role" not in SQL
    assert "revoke all on function public.dots_search_document_chunks(text, integer) from public" in SQL
