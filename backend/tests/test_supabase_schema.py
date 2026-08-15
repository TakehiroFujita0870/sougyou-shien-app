from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809000100_initial_dots_schema.sql"
)
SQL = MIGRATION.read_text(encoding="utf-8").lower()

TABLES = (
    "dots_ideas",
    "dots_stage_runs",
    "dots_death_causes",
    "dots_decision_records",
    "dots_consents",
    "dots_deletion_requests",
)


@pytest.mark.parametrize("table", TABLES)
def test_owner_tables_enable_and_force_rls(table: str) -> None:
    assert f"create table public.{table}" in SQL
    assert f"alter table public.{table} enable row level security" in SQL
    assert f"alter table public.{table} force row level security" in SQL
    assert f"create policy {table.removeprefix('dots_')}_select_own" in SQL
    assert "auth.uid()" in SQL


@pytest.mark.parametrize("table", ("dots_stage_runs", "dots_death_causes", "dots_decision_records"))
def test_stage_data_is_read_only_for_authenticated_clients(table: str) -> None:
    assert f"grant select on public.{table} to authenticated" in SQL
    assert f"grant insert on public.{table} to authenticated" not in SQL
    assert f"grant update on public.{table} to authenticated" not in SQL
    assert f"grant delete on public.{table} to authenticated" not in SQL


def test_child_rows_are_bound_to_the_same_owner_as_the_idea() -> None:
    assert "constraint ideas_id_owner_unique unique (id, owner_id)" in SQL
    assert SQL.count("foreign key (idea_id, owner_id)") == 3
    assert SQL.count("references public.dots_ideas(id, owner_id)") == 3


def test_client_created_ideas_must_start_as_drafts() -> None:
    assert "create policy ideas_insert_own" in SQL
    assert "owner_id and status = 'draft'" in SQL


def test_consent_is_versioned_and_opt_in_defaults_off() -> None:
    assert "anonymized_statistics_opt_in boolean not null default false" in SQL
    assert "consent_version text not null" in SQL
    assert "withdrawn_at timestamptz" in SQL
