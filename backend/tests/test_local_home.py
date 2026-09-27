from __future__ import annotations

import json
from dataclasses import asdict

from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.local_home import Neo4jHomeStore, read_local_home


class Session:
    def __init__(self, rows, briefs=()):
        self.rows = rows
        self.briefs = briefs
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        if "MATCH (b:IdeaBriefVersion" in query:
            return [row for row in self.briefs if row["owner_id"] == parameters["owner_id"]]
        return [row for row in self.rows if row["owner_id"] == parameters["owner_id"] and row["node_type"] in parameters["node_types"]]


class Driver:
    def __init__(self, rows, briefs=()):
        self.value = Session(rows, briefs)

    def session(self, **_kwargs):
        return self.value


def node(identity, kind, payload, *, owner="owner-a", status="active"):
    return {
        "id": identity,
        "owner_id": owner,
        "node_type": kind,
        "status": status,
        "payload_json": json.dumps({"id": identity, "owner_id": owner, **payload}),
    }


def brief_row(brief):
    payload = asdict(brief)
    payload["created_at"] = brief.created_at.isoformat()
    return {
        "id": brief.id,
        "owner_id": brief.owner_id,
        "root_id": brief.idea_lineage_root_id,
        "revision": brief.revision,
        "payload_json": json.dumps(payload, ensure_ascii=False),
    }


def test_home_lists_every_current_idea_and_safe_assets_without_raw_fields():
    rows = [
        node("idea-old", "idea", {"title": "Old", "summary": "old", "created_at": "2026-09-01T00:00:00Z"}),
        node("idea-new", "idea", {"title": "New", "summary": "Summary", "description": "Detail", "source_text": "private raw conversation", "supersedes_id": "idea-old", "created_at": "2026-09-02T00:00:00Z"}),
        node("asset-1", "asset", {"name": "製造業経験", "kind": "experience", "description": "現場の経験", "details": {"secret": "private"}, "created_at": "2026-09-03T00:00:00Z"}),
        node("profile-1", "owner_profile", {"display_name": "Takehiro", "created_at": "2026-09-01T00:00:00Z"}),
        node("foreign", "idea", {"title": "Foreign"}, owner="owner-b"),
        node("archived", "idea", {"title": "Archived"}, status="archived"),
    ]
    driver = Driver(rows)
    result = read_local_home(Neo4jHomeStore(driver), owner_id="owner-a")

    assert result["status"] == "ready"
    assert result["ideas"] == [{"id": "idea-new", "title": "New", "summary": "Summary", "description": "Detail", "revision": 0, "research_status": "unknown"}]
    assert result["assets"] == [{
        "id": "asset-1", "name": "製造業経験", "kind": "experience", "description": "現場の経験",
        "revision": 1, "egress_policy": "local_only",
    }]
    assert result["profile"] == {"display_name": "Takehiro"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private" not in serialized
    assert "Foreign" not in serialized
    assert "Old" not in serialized
    query, parameters = driver.value.calls[0]
    assert "n.owner_id = $owner_id" in query
    assert set(parameters["node_types"]) == {"idea", "asset", "owner_profile"}


def test_home_distinguishes_empty_stopped_and_sanitized_failure():
    store = Neo4jHomeStore(Driver([]))
    assert read_local_home(store, owner_id="owner-a")["status"] == "empty"
    assert read_local_home(store, owner_id="owner-a", storage_status="stopped")["status"] == "stopped"

    class BrokenStore:
        def read_home(self, _owner_id):
            raise RuntimeError("private database diagnostic")

    result = read_local_home(BrokenStore(), owner_id="owner-a")
    assert result == {"status": "failed", "ideas": [], "assets": [], "profile": None}


def test_home_fails_closed_on_identity_mismatch_or_invalid_payload():
    bad = node("idea-1", "idea", {"title": "Cannot show", "owner_id": "owner-b"})
    assert read_local_home(Neo4jHomeStore(Driver([bad])), owner_id="owner-a")["status"] == "failed"


def test_home_displays_only_latest_self_introduction_without_losing_history():
    rows = [
        node("asset-old", "asset", {"name": "自己紹介", "kind": "knowledge", "description": "元の自己紹介", "created_at": "2026-09-24T00:00:00Z"}),
        node("asset-new", "asset", {"name": "自己紹介", "kind": "knowledge", "description": "改訂版", "details": {"supersedes_id": "asset-old"}, "created_at": "2026-09-25T00:00:00Z"}),
    ]
    result = read_local_home(Neo4jHomeStore(Driver(rows)), owner_id="owner-a")
    assert result["assets"] == [{
        "id": "asset-new", "name": "自己紹介", "kind": "knowledge", "description": "改訂版",
        "revision": 1, "egress_policy": "local_only",
    }]


def test_home_overlays_latest_brief_by_idea_lineage_without_exposing_old_version():
    rows = [
        node("idea-root", "idea", {"title": "旧Idea", "summary": "旧概要", "created_at": "2026-09-01T00:00:00Z"}),
        node("idea-current", "idea", {"title": "現Idea", "summary": "概要", "supersedes_id": "idea-root", "created_at": "2026-09-02T00:00:00Z"}),
    ]
    first = IdeaBriefVersion(owner_id="owner-a", idea_lineage_root_id="idea-root", based_on_idea_id="idea-current", sections=(IdeaBriefSection(index=1, content="旧事業モデル"),))
    second = first.revise(sections=(IdeaBriefSection(index=1, content="新事業モデル"),))
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(first), brief_row(second)))), owner_id="owner-a")
    assert result["status"] == "ready"
    assert result["ideas"][0]["id"] == "idea-current"
    assert result["ideas"][0]["brief_revision"] == 2
    assert result["ideas"][0]["brief_sections"][1] == "新事業モデル"
    assert "旧事業モデル" not in json.dumps(result, ensure_ascii=False)


def test_home_keeps_a_draft_unresearched_even_when_it_has_a_brief():
    rows = [node(
        "idea-draft", "idea",
        {"title": "合成の下書き", "status": "draft", "created_at": "2026-09-26T00:00:00Z"},
        status="draft",
    )]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-draft", based_on_idea_id="idea-draft",
        sections=(IdeaBriefSection(index=0, content="仮の概要"),),
    )

    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")

    assert result["ideas"][0]["research_status"] == "unresearched"
    assert result["ideas"][0]["brief_sections"][0] == "仮の概要"


def test_home_reports_unknown_research_state_for_non_draft_idea_with_brief():
    rows = [node(
        "idea-active", "idea",
        {"title": "合成の記録", "status": "active", "created_at": "2026-09-26T00:00:00Z"},
        status="active",
    )]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-active", based_on_idea_id="idea-active",
        sections=(IdeaBriefSection(index=0, content="8観点の概要"),),
    )

    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")

    assert result["ideas"][0]["research_status"] == "unknown"
    assert result["ideas"][0]["brief_sections"][0] == "8観点の概要"


def test_home_does_not_overlay_a_brief_based_on_a_previous_idea_revision():
    rows = [
        node("idea-root", "idea", {"title": "旧案", "created_at": "2026-09-01T00:00:00Z"}),
        node("idea-current", "idea", {"title": "改訂案", "summary": "現在の説明", "supersedes_id": "idea-root", "created_at": "2026-09-02T00:00:00Z"}),
    ]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-root", based_on_idea_id="idea-root",
        sections=(IdeaBriefSection(index=0, content="改訂前だけの説明"),),
    )
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")
    assert result["status"] == "ready"
    assert result["ideas"][0]["summary"] == "現在の説明"
    assert "brief_sections" not in result["ideas"][0]
    assert "改訂前だけの説明" not in json.dumps(result, ensure_ascii=False)


def test_home_shows_researched_only_for_current_complete_brief_with_run_references():
    rows = [node("idea-draft", "idea", {"title": "調査された案", "status": "draft", "created_at": "2026-09-26T00:00:00Z"}, status="draft")]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-draft", based_on_idea_id="idea-draft",
        research_run_ids=("validated-run",),
        sections=tuple(IdeaBriefSection(index=i, content=f"調査済み観点{i}") for i in range(8)),
    )
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")
    assert result["ideas"][0]["research_status"] == "research_sources_missing"
    assert result["ideas"][0]["brief_citations"] == [[] for _ in range(8)]


def test_home_keeps_prior_research_origin_and_current_citations_without_campaign_run():
    rows = [node("idea-imported", "idea", {"title": "過去調査", "status": "draft", "created_at": "2026-09-26T00:00:00Z"}, status="draft")]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-imported", based_on_idea_id="idea-imported",
        origin="prior_research_import", egress_policy="shareable",
        sections=tuple(IdeaBriefSection(index=i, content=f"過去の概要{i}", evidence_ids=("evidence-public",) if i == 0 else ()) for i in range(8)),
    )
    store = Neo4jHomeStore(Driver(rows, (brief_row(brief),)))
    store.read_citations = lambda _owner, ids: {"evidence-public": {"url": "https://example.test/source", "title": "公開出典"}} if ids == ("evidence-public",) else {}

    result = read_local_home(store, owner_id="owner-a")

    assert result["ideas"][0]["brief_origin"] == "prior_research_import"
    assert result["ideas"][0]["research_status"] == "prior_research_import"
    assert result["ideas"][0]["brief_citations"][0] == [{"url": "https://example.test/source", "title": "公開出典"}]
    assert result["ideas"][0]["brief_citations"][1:] == [[] for _ in range(7)]


def test_home_marks_imported_research_missing_current_citations_not_unresearched():
    rows = [node("idea-imported", "idea", {"title": "過去調査", "status": "draft", "created_at": "2026-09-26T00:00:00Z"}, status="draft")]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-imported", based_on_idea_id="idea-imported",
        origin="prior_research_import", egress_policy="shareable",
        sections=tuple(IdeaBriefSection(index=i, content=f"過去の概要{i}") for i in range(8)),
    )

    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")

    assert result["ideas"][0]["brief_origin"] == "prior_research_import"
    assert result["ideas"][0]["research_status"] == "prior_research_sources_missing"
    assert result["ideas"][0]["research_status"] != "unresearched"
