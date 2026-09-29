from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from dots.founder_graph import Asset, AssetHomeCategory, AssetKind, Idea, Provenance, Status
from dots.founder_graph_neo4j import _node_properties
from dots.founder_graph_mcp_write import McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion, SECTION_TITLES
from dots.local_home import LocalAssetWriter, Neo4jHomeStore, read_local_home


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
        node("asset-2", "asset", {"name": "営業への迷い", "kind": "barrier", "description": "初回顧客獲得に不安", "created_at": "2026-09-04T00:00:00Z"}),
        node("profile-1", "owner_profile", {"display_name": "Takehiro", "created_at": "2026-09-01T00:00:00Z"}),
        node("foreign", "idea", {"title": "Foreign"}, owner="owner-b"),
        node("archived", "idea", {"title": "Archived"}, status="archived"),
    ]
    driver = Driver(rows)
    result = read_local_home(Neo4jHomeStore(driver), owner_id="owner-a")

    assert result["status"] == "ready"
    assert result["ideas"] == [{"id": "idea-new", "title": "New", "summary": "Summary", "description": "Detail", "revision": 0, "research_status": "unknown"}]
    assert result["assets"] == [{
        "id": "asset-1", "name": "製造業経験", "kind": "experience", "category": "strength", "description": "現場の経験",
        "revision": 1, "egress_policy": "local_only",
    }, {
        "id": "asset-2", "name": "営業への迷い", "kind": "barrier", "category": "barrier", "description": "初回顧客獲得に不安",
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


def test_home_category_is_projected_without_exposing_storage_metadata():
    row = node("criterion", "asset", {
        "name": "判断基準", "kind": "knowledge", "home_category": "criterion",
        "description": "関係密度を優先", "details": {"private": "hidden"},
        "created_at": "2026-09-01T00:00:00Z",
    })

    result = read_local_home(Neo4jHomeStore(Driver([row])), owner_id="owner-a")

    assert result["assets"] == [{
        "id": "criterion", "name": "判断基準", "kind": "knowledge", "category": "criterion",
        "description": "関係密度を優先", "revision": 1, "egress_policy": "local_only",
    }]
    assert "hidden" not in json.dumps(result, ensure_ascii=False)


def test_asset_edits_do_not_change_original_addition_order():
    rows = [
        node("asset-first", "asset", {
            "name": "先に追加", "kind": "knowledge", "created_at": "2026-09-01T00:00:00Z",
        }),
        node("asset-second", "asset", {
            "name": "後に追加", "kind": "knowledge", "created_at": "2026-09-02T00:00:00Z",
        }),
        node("asset-first-edit", "asset", {
            "name": "先に追加（編集済み）", "kind": "knowledge", "revision": 2,
            "supersedes_id": "asset-first", "created_at": "2026-09-03T00:00:00Z",
        }),
    ]

    result = read_local_home(Neo4jHomeStore(Driver(rows)), owner_id="owner-a")

    assert [asset["id"] for asset in result["assets"]] == ["asset-first-edit", "asset-second"]


def test_asset_restore_keeps_original_addition_order():
    rows = [
        node("asset-first", "asset", {
            "name": "先に追加", "kind": "knowledge", "created_at": "2026-09-01T00:00:00Z",
        }),
        node("asset-first-edit", "asset", {
            "name": "先に追加", "kind": "knowledge", "revision": 2,
            "supersedes_id": "asset-first", "created_at": "2026-09-03T00:00:00Z",
        }, status="superseded"),
        node("asset-first-archived", "asset", {
            "name": "先に追加", "kind": "knowledge", "revision": 3,
            "supersedes_id": "asset-first-edit", "created_at": "2026-09-04T00:00:00Z",
        }, status="archived"),
        node("asset-first-restored", "asset", {
            "name": "先に追加", "kind": "knowledge", "revision": 4,
            "supersedes_id": "asset-first-archived", "created_at": "2026-09-05T00:00:00Z",
        }),
        node("asset-second", "asset", {
            "name": "後から追加", "kind": "knowledge", "created_at": "2026-09-02T00:00:00Z",
        }),
    ]

    result = read_local_home(Neo4jHomeStore(Driver(rows)), owner_id="owner-a")

    assert [asset["id"] for asset in result["assets"]] == ["asset-first-restored", "asset-second"]


def test_mcp_criterion_capture_edit_and_reload_preserve_category_and_original_order(monkeypatch):
    owner_id = "owner-a"
    writes = InMemoryGraphWriteService(owner_id)
    receipt = McpWriteSurface(writes).call("capture_asset", {
        "name": "判断基準", "kind": "knowledge", "home_category": "criterion",
        "summary": "関係密度を優先", "egress_policy": "shareable", "idempotency_key": "criterion-mcp",
    }, owner_id=owner_id)
    criterion = writes.get_node(receipt.target_id)
    later = Asset(
        owner_id=owner_id, id="asset-later", name="後から追加した強み",
        kind=AssetKind.EXPERIENCE, created_at=criterion.created_at + timedelta(seconds=1),
    )
    writes.put_node(later, idempotency_key="asset-later-create", operation="capture_asset")
    monkeypatch.setattr(
        "dots.founder_graph.utc_now",
        lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    edited = LocalAssetWriter(writes).save(
        criterion.id, name=criterion.name, description=criterion.description,
        expected_revision=1, idempotency_key="criterion-edit",
        home_category=criterion.home_category,
    )

    class PersistedHome:
        def read_home(self, requested_owner):
            assert requested_owner == owner_id
            rows = []
            for asset in writes.nodes():
                if isinstance(asset, Asset):
                    properties = _node_properties(asset)
                    rows.append({
                        key: properties[key]
                        for key in ("id", "owner_id", "node_type", "status", "payload_json")
                    })
            return rows

    reloaded = read_local_home(PersistedHome(), owner_id=owner_id)

    assert reloaded["status"] == "ready"
    assert [asset["id"] for asset in reloaded["assets"]] == [edited.target_id, later.id]
    assert reloaded["assets"][0]["category"] == "criterion"
    assert reloaded["assets"][0]["kind"] == "knowledge"


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
        node("asset-new", "asset", {
            "name": "自己紹介", "kind": "knowledge", "description": "改訂版",
            "details": {"supersedes_id": "asset-old"},
            "provenance": {"operation": "edit_self_intro"},
            "created_at": "2026-09-25T00:00:00Z",
        }),
    ]
    result = read_local_home(Neo4jHomeStore(Driver(rows)), owner_id="owner-a")
    assert result["assets"] == [{
        "id": "asset-new", "name": "自己紹介", "kind": "knowledge", "description": "改訂版",
        "category": "strength", "revision": 1, "egress_policy": "local_only",
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


def test_home_projects_only_the_latest_markdown_report_with_its_brief():
    rows = [node("idea-current", "idea", {"title": "新事業", "created_at": "2026-09-28T00:00:00Z"})]
    first = IdeaBriefVersion(owner_id="owner-a", idea_lineage_root_id="idea-current", based_on_idea_id="idea-current", report_markdown="## 旧版")
    second = first.revise(report_markdown="## 新版\n\n| 項目 | 内容 |\n| --- | --- |\n| 顧客 | 店舗 |")
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(first), brief_row(second)))), owner_id="owner-a")
    assert result["ideas"][0]["report_markdown"] == second.report_markdown
    assert "旧版" not in json.dumps(result, ensure_ascii=False)


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


def test_local_title_edit_keeps_current_research_brief_visible():
    original = Idea(id="idea-root", owner_id="owner-a", title="元の題名", status=Status.ACTIVE)
    revised = original.revise(title="新しい題名")
    revised = replace(revised, provenance=Provenance(
        actor="local-owner", operation="revise_idea", target_id=revised.id, source_id=original.id,
        idempotency_key="edit-idea",
    ))
    rows = [_node_properties(idea) for idea in (original, revised)]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id=original.id, based_on_idea_id=original.id,
        sections=(IdeaBriefSection(index=0, content="調査結果を維持する"),),
    )
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")
    assert result["status"] == "ready"
    assert len(result["ideas"]) == 1
    assert result["ideas"][0]["title"] == "新しい題名"
    assert result["ideas"][0]["brief_sections"][0] == "調査結果を維持する"


def test_local_description_edit_keeps_old_brief_in_history_not_current_display():
    original = Idea(id="idea-root", owner_id="owner-a", title="元の題名", status=Status.ACTIVE)
    revised = original.revise(description="事業内容を変更")
    revised = replace(revised, provenance=Provenance(
        actor="local-owner", operation="revise_idea", target_id=revised.id, source_id=original.id,
        idempotency_key="edit-description",
    ))
    rows = [_node_properties(idea) for idea in (original, revised)]
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id=original.id, based_on_idea_id=original.id,
        sections=(IdeaBriefSection(index=0, content="変更前の調査結果"),),
    )
    result = read_local_home(Neo4jHomeStore(Driver(rows, (brief_row(brief),))), owner_id="owner-a")
    assert result["status"] == "ready"
    assert "brief_sections" not in result["ideas"][0]
    assert result["ideas"][0]["research_status"] == "unresearched"


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


def test_home_derives_researched_sections_from_markdown_without_duplicate_bodies():
    rows = [node("idea-markdown", "idea", {"title": "調査された案", "status": "draft", "created_at": "2026-09-26T00:00:00Z"}, status="draft")]
    report_markdown = "\n\n".join(
        f"## {title}\n\nMarkdown section {index}"
        + ("\n\n[Public](https://example.test/public)" if index == 3 else "")
        for index, title in enumerate(SECTION_TITLES)
    )
    brief = IdeaBriefVersion(
        owner_id="owner-a", idea_lineage_root_id="idea-markdown", based_on_idea_id="idea-markdown",
        research_run_ids=("validated-run",), report_markdown=report_markdown, egress_policy="shareable",
        sections=tuple(IdeaBriefSection(index=i, evidence_ids=("evidence-public",) if i == 0 else ()) for i in range(8)),
    )
    store = Neo4jHomeStore(Driver(rows, (brief_row(brief),)))
    store.read_citations = lambda _owner, ids: {"evidence-public": {"url": "https://example.test/evidence", "title": "Verified evidence"}} if ids == ("evidence-public",) else {}

    result = read_local_home(store, owner_id="owner-a")
    idea = result["ideas"][0]

    assert idea["research_status"] == "researched"
    assert idea["brief_sections"] == [
        f"Markdown section {index}" + ("\n\n[Public](https://example.test/public)" if index == 3 else "")
        for index in range(8)
    ]
    assert idea["brief_citations"][0] == [{"url": "https://example.test/evidence", "title": "Verified evidence"}]
    assert idea["report_projection"]["links"][0]["verification_status"] == "url_only"
    assert idea["report_projection"]["links"][0]["evidence_ids"] == []


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
