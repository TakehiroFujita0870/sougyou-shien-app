from pathlib import Path


SQL = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260809000500_add_project_knowledge_grants.sql").read_text(encoding="utf-8").lower()


def test_project_knowledge_and_grants_are_owner_scoped_with_full_rls() -> None:
    for table in ("dots_project_knowledge", "dots_knowledge_grants"):
        assert f"create table public.{table}" in SQL
        assert f"create index {table.removeprefix('dots_')}_owner_id_idx" in SQL
        assert f"alter table public.{table} enable row level security" in SQL
        assert f"alter table public.{table} force row level security" in SQL
        for operation in ("select", "insert", "update", "delete"):
            assert f"create policy {table.removeprefix('dots_')}_{operation}_own" in SQL


def test_grants_only_reference_anonymized_derivatives_and_active_candidates() -> None:
    assert "anonymized_customer_interview_derivative" in SQL
    assert "raw_customer_interview" not in SQL
    assert "deleted_at is null" in SQL
    assert "revoked_at is null" in SQL
    assert "auth.uid()" in SQL


def test_grant_source_project_is_bound_to_knowledge_and_revocation_is_final() -> None:
    assert "foreign key (knowledge_id, owner_id, source_project_id)" in SQL
    assert "references public.dots_project_knowledge(id, owner_id, source_project_id)" in SQL
    assert "create trigger knowledge_grants_revoke_is_final" in SQL
    assert "a revoked knowledge grant cannot be reactivated" in SQL
