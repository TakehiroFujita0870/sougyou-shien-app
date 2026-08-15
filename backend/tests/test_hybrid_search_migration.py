from pathlib import Path


MIGRATION = Path(__file__).parents[2] / "supabase" / "migrations" / "20260809000400_add_hybrid_search_embedding_contract.sql"
SQL = MIGRATION.read_text(encoding="utf-8").lower()


def test_embedding_contract_is_owner_scoped_without_assuming_pgvector_is_installed() -> None:
    assert "create table public.dots_document_chunk_embeddings" in SQL
    assert "embedding jsonb" in SQL
    assert "references public.dots_document_chunks(id, owner_id)" in SQL
    assert "enable row level security" in SQL
    assert "force row level security" in SQL
    for operation in ("select", "insert", "update", "delete"):
        assert f"create policy document_chunk_embeddings_{operation}_own" in SQL
    assert "(select auth.uid()) = owner_id" in SQL
    assert "create extension if not exists vector" not in SQL
    assert "hnsw" in SQL
