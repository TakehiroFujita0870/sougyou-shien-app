from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809000200_add_idea_definition.sql"
)
SQL = MIGRATION.read_text(encoding="utf-8").lower()


def test_idea_definition_has_required_title_and_summary() -> None:
    assert "add column title text" in SQL
    assert "add column idea_summary text" in SQL
    assert "alter column title set not null" in SQL
    assert "alter column idea_summary set not null" in SQL
    assert "ideas_title_length" in SQL
    assert "ideas_summary_length" in SQL
