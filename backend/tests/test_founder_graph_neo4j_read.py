from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from nebula.founder_graph import ContentChunk, EgressPolicy, Evidence, Idea, NodeType, Provenance, RelationAssertion, RelationAssertionBasis, Source, SourceRevision
from nebula.founder_graph import Asset, Claim, PersonAsset, RelationAssertionEdgeType, RelationType, Status, relation_assertion_structural_edges
from nebula.idea_brief import IdeaBriefSection, IdeaBriefVersion, SECTION_TITLES
from nebula.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from nebula.founder_graph_neo4j_read import GraphRelationView, Neo4jGraphReadService
from nebula.founder_graph_mcp import McpReadError, McpReadSurface
from nebula.founder_graph_neo4j_idea_brief import _serialize_persisted_idea_brief
from nebula.founder_graph_read import GraphReadError, GraphReadNotFoundError, NodeView, RelationPathStep


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def single(self, **_kwargs):
        return self.rows[0] if self.rows else None


class FakeReadSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fetch_rows: list[dict[str, object]] = []
        self.search_rows: list[dict[str, object]] = []
        self.search_relation_rows: list[dict[str, object]] = []
        self.search_relation_rows_by_call: list[list[dict[str, object]]] = []
        self.search_relation_call_count = 0
        self.relation_rows: list[dict[str, object]] = []
        self.formal_rows: list[dict[str, object]] = []
        self.idea_rows: list[dict[str, object]] = []
        self.brief_rows: list[dict[str, object]] = []
        self.read_transactions = 0

    def close(self) -> None:
        return None

    def execute_read(self, callback):
        self.read_transactions += 1
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        all_node_rows = {row.get("id"): row for row in (*self.fetch_rows, *self.search_rows)}
        if "WHERE n.node_type IN $node_types" in query and "$id" in query:
            row = all_node_rows.get(params.get("id"))
            return FakeResult([row] if row is not None else [])
        if "supersedes_id: $parent_id" in query:
            rows = [
                row for row in all_node_rows.values()
                if row.get("owner_id") == params.get("owner_id")
                and row.get("supersedes_id") == params.get("parent_id")
                and row.get("node_type") in params.get("node_types", ())
            ]
            return FakeResult(rows)
        if "IdeaBriefVersion" in query:
            return FakeResult(self.brief_rows)
        if "MATCH (i:Idea" in query:
            if "$id" in query:
                rows = [row for row in self.idea_rows if row.get("id") == params.get("id")]
                return FakeResult(rows)
            return FakeResult(self.idea_rows)
        if "EVIDENCE_FROM" in query:
            evidence_id = params.get("evidence_id")
            for formal_row in self.formal_rows:
                if formal_row.get("relation") == "EVIDENCED_BY" and formal_row.get("target_id") == evidence_id:
                    return FakeResult([formal_row["_lineage"]])
            return FakeResult([])
        if "RelationAssertion" in query:
            return FakeResult([row for row in self.formal_rows if row.get("target_owner_id") in (None, params.get("owner_id"))])
        if "MATCH (a)-[r]->(b)" in query and "matched_ids" in query:
            if self.search_relation_rows_by_call:
                index = min(self.search_relation_call_count, len(self.search_relation_rows_by_call) - 1)
                self.search_relation_call_count += 1
                return FakeResult(self.search_relation_rows_by_call[index])
            return FakeResult(self.search_relation_rows)
        if "MATCH (a)-[r]->(b)" in query:
            return FakeResult(self.relation_rows)
        if "$node_id" in query:
            rows = [row for row in self.fetch_rows if row.get("id") == params.get("node_id")]
            if "successor {owner_id: $owner_id, supersedes_id: n.id}" in query:
                superseded_ids = {
                    row.get("supersedes_id")
                    for row in (*self.fetch_rows, *self.search_rows)
                    if row.get("owner_id") == params.get("owner_id")
                }
                rows = [row for row in rows if row.get("id") not in superseded_ids]
            return FakeResult(rows)
        return FakeResult(self.search_rows)


class FakeReadDriver:
    def __init__(self) -> None:
        self.session_value = FakeReadSession()

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


def _gateway() -> tuple[FakeReadDriver, Neo4jGraphReadService]:
    driver = FakeReadDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    return driver, Neo4jGraphReadService(gateway)


def test_read_adapter_exposes_one_managed_read_boundary() -> None:
    driver, reads = _gateway()

    with reads.read_session() as session:
        result = reads.gateway.execute_read(session, lambda tx: tx)

    assert result is driver.session_value
    assert driver.session_value.read_transactions == 1


def test_hybrid_fulltext_query_uses_escaped_or_terms_for_cjk() -> None:
    assert Neo4jGraphReadService._fulltext_query('創業者 graph "idea"') == '"創業者" OR "graph" OR "idea"'


def test_legacy_search_query_hides_superseded_idea_revisions() -> None:
    from nebula.founder_graph_neo4j_read import _SEARCH_QUERY

    assert "n.node_type IN ['idea', 'asset', 'person']" in _SEARCH_QUERY
    assert "supersedes_id: n.id" in _SEARCH_QUERY


def test_hybrid_reranks_only_top_forty_after_graph_expansion_and_keeps_tail(monkeypatch) -> None:
    driver, lexical_service = _gateway()

    class SearchModels:
        def __init__(self):
            self.candidates = ()

        def rerank(self, _query, candidates):
            self.candidates = tuple(candidates)
            return [float(index) for index in range(len(candidates))]

    models = SearchModels()
    service = Neo4jGraphReadService(
        lexical_service._gateway, search_models=models, rerank_enabled=True, rerank_candidate_limit=40,
    )
    views = {
        f"idea-{index:02d}": NodeView(
            f"idea-{index:02d}", NodeType.IDEA.value, "owner-1", f"Idea {index}", "Snippet",
            "active", 1, MappingProxyType({}),
        )
        for index in range(45)
    }
    path = RelationPathStep(
        from_id="idea-00", to_id="idea-01", source_id="idea-00", predicate="supports",
        target_id="idea-01", traversal_direction="outgoing", evidence_ids=("evidence-1",),
    )
    scores = {node_id: 1.0 / (index + 1) for index, node_id in enumerate(views)}
    monkeypatch.setattr(
        service,
        "_search_tx",
        lambda _tx, **_kwargs: (
            views, scores, {}, {"idea-00": ("evidence-1",)}, {"idea-00": (path,)}, {},
        ),
    )

    page = service.search("創業 graph", owner_id="owner-1", limit=50)

    assert len(models.candidates) == 40
    assert "relation path:" in models.candidates[0]
    assert "evidence ids: evidence-1" in models.candidates[0]
    assert [hit.node.id for hit in page.hits[:2]] == ["idea-39", "idea-38"]
    assert [hit.node.id for hit in page.hits[40:]] == [f"idea-{index:02d}" for index in range(40, 45)]
    assert page.hits[-1].score == pytest.approx(1 / 45)


def test_hybrid_search_discards_stale_asset_candidates_before_ranking(monkeypatch) -> None:
    driver, lexical_service = _gateway()
    current = Asset(
        owner_id="owner-1", id="asset-current", name="Current synthetic asset", kind="artifact",
        description="Current safe summary", revision=2, supersedes_id="asset-old",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    old = Asset(
        owner_id="owner-1", id="asset-old", name="Old synthetic asset", kind="artifact",
        description="Old safe summary", egress_policy=EgressPolicy.SHAREABLE,
    )
    models = object()
    service = Neo4jGraphReadService(lexical_service._gateway, search_models=models, rerank_enabled=False)
    monkeypatch.setattr(service, "_asset_current_tx", lambda _tx, asset_id: asset_id == current.id)
    monkeypatch.setattr(
        service,
        "_hybrid_candidates",
        lambda *_args, **_kwargs: (
            (_persisted_row(old), _persisted_row(current)),
            {old.id: 1.0, current.id: 0.5},
        ),
    )

    page = service.search("synthetic asset", owner_id="owner-1", limit=10)

    assert [hit.node.id for hit in page.hits] == [current.id]


@pytest.mark.parametrize("stale_is_source", [False, True])
def test_hybrid_search_does_not_reintroduce_stale_asset_through_legacy_edge(monkeypatch, stale_is_source) -> None:
    driver, lexical_service = _gateway()
    current = Asset(
        owner_id="owner-1", id="asset-current", name="Current synthetic asset", kind="artifact",
        description="Current safe summary", revision=2, supersedes_id="asset-old",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    old = Asset(
        owner_id="owner-1", id="asset-old", name="Old synthetic asset", kind="artifact",
        description="Old safe summary", egress_policy=EgressPolicy.SHAREABLE,
    )
    models = object()
    service = Neo4jGraphReadService(lexical_service._gateway, search_models=models, rerank_enabled=False)
    monkeypatch.setattr(service, "_asset_current_tx", lambda _tx, asset_id: asset_id == current.id)
    monkeypatch.setattr(
        service,
        "_hybrid_candidates",
        lambda *_args, **_kwargs: ((_persisted_row(current),), {current.id: 1.0}),
    )
    driver.session_value.search_relation_rows = [
        _relation_row(_persisted_row(old), _persisted_row(current), RelationType.REUSES.value)
        if stale_is_source else _relation_row(_persisted_row(current), _persisted_row(old), RelationType.REUSES.value)
    ]

    page = service.search("synthetic asset", owner_id="owner-1", limit=10)

    assert [hit.node.id for hit in page.hits] == [current.id]


def _node_row(
    node_id: str,
    *,
    node_type: str = NodeType.IDEA.value,
    owner_id: str = "owner-1",
    title: str = "Graph idea",
    status: str = "active",
    search_text: str = "graph idea",
    private_raw: str = "do not project",
) -> dict[str, object]:
    payload = {
        "id": node_id,
        "owner_id": owner_id,
        "node_type": node_type,
        "title": title,
        "status": status,
        "egress_policy": "shareable",
        "private_raw": private_raw,
        "source_text": "source text",
    }
    return {
        "id": node_id,
        "owner_id": owner_id,
        "node_type": node_type,
        "status": status,
        "revision": 0,
        "payload_json": json.dumps(payload),
        "search_text": search_text,
    }


def _relation_row(source: dict[str, object], target: dict[str, object], relation: str) -> dict[str, object]:
    return {
        "source_id": source["id"],
        "relation": relation,
        "evidence_ids_json": json.dumps(["evidence-1"]),
        "target_id": target["id"],
        "source_owner_id": source["owner_id"],
        "source_node_type": source["node_type"],
        "source_status": source["status"],
        "source_revision": source["revision"],
        "source_payload_json": source["payload_json"],
        "source_search_text": source["search_text"],
        "target_owner_id": target["owner_id"],
        "target_node_type": target["node_type"],
        "target_status": target["status"],
        "target_revision": target["revision"],
        "target_payload_json": target["payload_json"],
        "target_search_text": target["search_text"],
    }


def _persisted_row(node, *, search_text: str = "") -> dict[str, object]:
    return {**_node_properties(node), "search_text": search_text}


def _formal_edge_row(assertion, relation: str, target: dict[str, object]) -> dict[str, object]:
    stored = _persisted_row(assertion)
    return ({f"assertion_{key}": stored[key] for key in ("id", "owner_id", "node_type", "revision", "status", "egress_policy", "payload_json")}
            | {"relation": relation, "is_outgoing": True}
            | {f"target_{key}": target[key] for key in ("id", "owner_id", "node_type", "revision", "status", "egress_policy", "payload_json", "search_text")})


def _formal_fixture(*, assertion_brief_id: str | None = None, evidence_refs: tuple[str, ...] | None = None, assertion_policy=EgressPolicy.SHAREABLE, brief_origin=None):
    idea = Idea(owner_id="owner-1", id="idea-1", title="Foundry search seed", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    claim = Claim(owner_id="owner-1", id="claim-1", text="A supported claim", egress_policy=EgressPolicy.SHAREABLE)
    revision = SourceRevision(owner_id="owner-1", id="revision-1", source_id="source-1", content="grounded synthetic source", egress_policy=EgressPolicy.SHAREABLE)
    source = Source(owner_id="owner-1", id="source-1", title="Synthetic source", locator="https://example.test/reference?id=42#section",
                    current_revision_id=revision.id, revision=1, egress_policy=EgressPolicy.SHAREABLE)
    chunk = ContentChunk(owner_id="owner-1", id="chunk-1", source_revision_id=revision.id, ordinal=0,
                         char_start=0, char_end=len(revision.content), text=revision.content)
    evidence = Evidence(owner_id="owner-1", id="evidence-1", claim_id=claim.id,
                        source_revision_id=revision.id, content_chunk_id=chunk.id,
                        char_start=0, char_end=len(revision.content), locator=f"chars:0-{len(revision.content)}",
                        content_hash=chunk.text_hash, status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    brief = IdeaBriefVersion(owner_id="owner-1", idea_lineage_root_id=idea.id, based_on_idea_id=idea.id, id="brief-1", research_run_ids=() if brief_origin else ("run-1",), origin=brief_origin, egress_policy="shareable", sections=(IdeaBriefSection(index=0, content="A researched section", evidence_ids=(evidence.id,)),))
    assertion = RelationAssertion(owner_id="owner-1", id="assertion-1", source_id=idea.id, target_id=claim.id, source_kind=NodeType.IDEA, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES, assertion_family_id="family-1", status="inferred", confidence=0.8, evidence_ids=(evidence.id,), valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), egress_policy=assertion_policy, based_on_brief_id=assertion_brief_id or brief.id, based_on_brief_section_index=0)
    endpoint_rows = {node.id: _persisted_row(node, search_text=getattr(node, "title", getattr(node, "text", ""))) for node in (idea, claim, evidence)}
    rows = [_formal_edge_row(assertion, relation, endpoint_rows[target_id])
            for _source_id, relation, target_id in relation_assertion_structural_edges(assertion)]
    lineage = {
        "evidence_owner_id": evidence.owner_id,
        "evidence_status": evidence.status.value,
        "evidence_egress_policy": evidence.egress_policy.value,
        "evidence_payload_json": _persisted_row(evidence)["payload_json"],
        "evidence_edge_count": 1,
        "revision_edge_count": 1,
        "source_history_edge_count": 1,
        "source_current_edge_count": 1,
        "source_current_edge_total": 1,
        "lineages": [{
            "chunk_id": chunk.id, "chunk_labels": ["ContentChunk"],
            "chunk_owner_id": chunk.owner_id, "chunk_status": chunk.status.value,
            "chunk_source_revision_id": chunk.source_revision_id,
            "chunk_payload_json": _persisted_row(chunk)["payload_json"],
            "revision_id": revision.id, "revision_owner_id": revision.owner_id,
            "revision_status": revision.status.value, "revision_payload_json": _persisted_row(revision)["payload_json"],
            "source_id": source.id, "source_owner_id": source.owner_id,
            "source_status": source.status.value, "source_payload_json": _persisted_row(source)["payload_json"],
        }],
        "claim_id": claim.id, "claim_owner_id": claim.owner_id, "claim_status": claim.status.value,
        "claim_payload_json": _persisted_row(claim)["payload_json"],
    }
    next(row for row in rows if row["relation"] == "EVIDENCED_BY")["_lineage"] = lineage
    if evidence_refs is not None:
        rows = [row for row in rows if row["relation"] != "EVIDENCED_BY"]
        for evidence_id in evidence_refs:
            target_row = endpoint_rows.get(evidence_id, endpoint_rows[evidence.id])
            rows.append(_formal_edge_row(assertion, "EVIDENCED_BY", {**target_row, "id": evidence_id}))
    return idea, claim, evidence, brief, assertion, endpoint_rows, rows, _serialize_persisted_idea_brief(brief)


def _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row):
    state = driver.session_value
    state.search_rows, state.fetch_rows, state.formal_rows, state.idea_rows, state.brief_rows = [endpoint_rows[idea.id]], list(endpoint_rows.values()), formal_rows, [endpoint_rows[idea.id]], [brief_row]


def test_fetch_hydrates_allowlisted_view_without_exposing_raw_payload() -> None:
    driver, reads = _gateway()
    driver.session_value.fetch_rows = [_node_row("idea-1", title="A persisted idea")]

    view = reads.fetch("idea-1", owner_id="owner-1")

    assert view.id == "idea-1"
    assert view.title == "A persisted idea"
    assert view.fields["source_text"] == "source text"
    assert "private_raw" not in view.fields
    assert all("idea-1" not in query for query, _params in driver.session_value.calls)
    query, params = driver.session_value.calls[0]
    assert "owner_id = $owner_id" in query
    assert params["node_id"] == "idea-1"


def test_fetch_idea_brief_returns_latest_current_shareable_brief_with_valid_evidence_only() -> None:
    driver, reads = _gateway()
    idea, _claim, evidence, legacy, _assertion, _endpoints, rows, _brief_row = _formal_fixture()
    report_markdown = "\n\n".join(
        f"## {title}\n\nMarkdown section {index}"
        + ("\n\n[Public](https://example.test/public)" if index == 0 else "")
        for index, title in enumerate(SECTION_TITLES)
    )
    brief = replace(
        legacy, report_markdown=report_markdown,
        sections=tuple(IdeaBriefSection(index=index, evidence_ids=(evidence.id,) if index == 0 else ()) for index in range(8)),
    )
    brief_row = _serialize_persisted_idea_brief(brief)
    driver.session_value.idea_rows = [_persisted_row(idea)]
    driver.session_value.brief_rows = [brief_row]
    driver.session_value.formal_rows = rows

    result = reads.fetch_idea_brief(idea.id, owner_id="owner-1")

    assert result["brief_id"] == "brief-1"
    assert result["idea_id"] == idea.id
    assert result["origin"] is None
    assert result["report_projection"]["heading_status"] == "complete"
    assert result["report_projection"]["links"][0]["verification_status"] == "url_only"
    assert result["report_projection"]["links"][0]["evidence_ids"] == []
    assert result["report_projection"]["links"][0]["section_index"] == 0
    assert len(result["sections"]) == 8
    assert result["sections"][0] == {
        "index": 0,
        "title": "エグゼクティブサマリー",
        "content": "Markdown section 0\n\n[Public](https://example.test/public)",
        "evidence_ids": [evidence.id],
        "citations": [{"url": "https://example.test/reference?id=42#section", "title": "Synthetic source", "source_id": "source-1", "evidence_id": evidence.id}],
    }
    assert len(result["brief_citations"]) == 8
    assert result["brief_citations"][0] == [{"url": "https://example.test/reference?id=42#section", "title": "Synthetic source", "source_id": "source-1", "evidence_id": evidence.id}]
    assert result["brief_citations"][1:] == [[] for _ in range(7)]
    assert all("run-1" not in str(section) and "owner_decisions" not in section for section in result["sections"])
    assert all("IdeaBriefVersion" not in query or params["owner_id"] == "owner-1" for query, params in driver.session_value.calls)


def test_neo4j_archive_restore_hides_then_rebinds_existing_brief_and_assertion() -> None:
    driver, reads = _gateway()
    idea, claim, evidence, brief, assertion, endpoints, formal_rows, brief_row = _formal_fixture()
    archived = replace(
        idea, id="idea-archived", revision=1, supersedes_id=idea.id, status=Status.ARCHIVED,
        provenance=Provenance(
            actor="local-owner", operation="archive_idea", target_id="idea-archived",
            source_id=idea.id, idempotency_key="archive",
        ),
    )
    restored = replace(
        archived, id="idea-restored", revision=2, supersedes_id=archived.id, status=Status.ACTIVE,
        provenance=Provenance(
            actor="local-owner", operation="restore_idea", target_id="idea-restored",
            source_id=archived.id, idempotency_key="restore",
        ),
    )
    state = driver.session_value
    state.fetch_rows = [*endpoints.values(), _persisted_row(archived), _persisted_row(restored)]
    state.idea_rows = [_persisted_row(idea), _persisted_row(archived), _persisted_row(restored)]
    state.formal_rows = formal_rows
    state.brief_rows = [brief_row]

    state.search_rows = [_persisted_row(archived, search_text="Foundry search seed")]
    archived_page = reads.search("Foundry search seed", owner_id="owner-1")
    assert not archived_page.hits
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(idea.id, owner_id="owner-1")

    state.search_rows = [_persisted_row(restored, search_text="Foundry search seed")]
    restored_page = reads.search("Foundry search seed", owner_id="owner-1")
    assert restored_page.hits[0].node.id == restored.id
    assert any(
        step.relation_assertion_id == assertion.id and step.to_id == claim.id
        for hit in restored_page.hits for step in hit.relation_path
    )
    brief_result = reads.fetch_idea_brief(restored.id, owner_id="owner-1")
    assert brief_result["idea_id"] == restored.id
    assert len(brief_result["sections"]) == 8
    assert brief_result["brief_citations"][0][0]["url"] == "https://example.test/reference?id=42#section"
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch(idea.id, owner_id="owner-1")


def test_fetch_idea_brief_preserves_prior_import_origin_and_only_current_public_citations():
    import copy

    for invalid_lineage in ("private_source", "superseded_revision", "expired_evidence"):
        driver, reads = _gateway()
        idea, _claim, _evidence, _brief, _assertion, _endpoints, rows, brief_row = _formal_fixture(brief_origin="prior_research_import")
        driver.session_value.idea_rows = [_persisted_row(idea)]
        driver.session_value.brief_rows = [brief_row]
        driver.session_value.formal_rows = copy.deepcopy(rows)
        lineage = next(row["_lineage"] for row in driver.session_value.formal_rows if row["relation"] == "EVIDENCED_BY")
        if invalid_lineage == "private_source":
            source = json.loads(lineage["lineages"][0]["source_payload_json"])
            source["egress_policy"] = EgressPolicy.LOCAL_ONLY.value
            lineage["lineages"][0]["source_payload_json"] = json.dumps(source)
        elif invalid_lineage == "superseded_revision":
            revision = json.loads(lineage["lineages"][0]["revision_payload_json"])
            revision["status"] = Status.SUPERSEDED.value
            lineage["lineages"][0]["revision_payload_json"] = json.dumps(revision)
            lineage["lineages"][0]["revision_status"] = Status.SUPERSEDED.value
        else:
            evidence = json.loads(lineage["evidence_payload_json"])
            evidence["status"] = Status.EXPIRED.value
            lineage["evidence_payload_json"] = json.dumps(evidence)
            lineage["evidence_status"] = Status.EXPIRED.value

        result = reads.fetch_idea_brief(idea.id, owner_id="owner-1")

        assert result["origin"] == "prior_research_import"
        assert result["brief_citations"] == [[] for _ in range(8)]
        assert result["sections"][0]["evidence_ids"] == []


def test_fetch_idea_brief_rejects_a_stale_idea_revision() -> None:
    _driver, reads = _gateway()
    idea, _claim, _evidence, _brief, _assertion, _endpoints, _rows, _brief_row = _formal_fixture()
    child = idea.revise(title="Current corrected idea")
    driver = reads._gateway.driver
    driver.session_value.idea_rows = [_persisted_row(idea), _persisted_row(child)]
    driver.session_value.brief_rows = [_serialize_persisted_idea_brief(_brief)]

    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(idea.id, owner_id="owner-1")


def test_fetch_hides_foreign_and_non_current_rows() -> None:
    driver, reads = _gateway()
    driver.session_value.fetch_rows = [_node_row("foreign", owner_id="owner-2")]
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("foreign", owner_id="owner-1")

    driver.session_value.fetch_rows = [_node_row("old", status="superseded")]
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("old", owner_id="owner-1")

    assert reads.search("anything", owner_id="owner-2").hits == ()


def test_neo4j_mcp_asset_search_and_fetch_use_only_safe_shareable_fields() -> None:
    driver, reads = _gateway()
    shareable = Asset(owner_id="owner-1", id="asset-shareable", name="Synthetic kit", kind="artifact",
                      home_category="criterion", description="Safe synthetic summary",
                      egress_policy=EgressPolicy.SHAREABLE)
    local = Asset(owner_id="owner-1", id="asset-local", name="Private kit", kind="data",
                  description="Private description", details={"private_notes": "synthetic secret"})
    driver.session_value.search_rows = [
        _persisted_row(shareable, search_text="Synthetic kit criterion Safe synthetic summary"),
        _persisted_row(local, search_text="Private kit Private description"),
    ]
    driver.session_value.fetch_rows = [_persisted_row(shareable), _persisted_row(local)]
    surface = McpReadSurface(reads)

    search = surface.call("search", {"query": "synthetic"}, owner_id="owner-1")
    assert [item["id"] for item in search["results"]] == [shareable.id]
    assert set(search["results"][0]["fields"]) == {"name", "kind", "home_category", "description", "status"}
    assert search["results"][0]["fields"]["home_category"] == "criterion"
    assert search["results"][0]["fields"]["description"] == "Safe synthetic summary"
    criterion_search = surface.call("search", {"query": "criterion"}, owner_id="owner-1")
    assert [item["id"] for item in criterion_search["results"]] == [shareable.id]
    assert criterion_search["results"][0]["fields"]["home_category"] == "criterion"
    fetched = surface.call("fetch", {"id": shareable.id}, owner_id="owner-1")
    assert fetched["id"] == shareable.id
    assert set(fetched["fields"]) == {"name", "kind", "home_category", "description", "status"}
    assert fetched["fields"]["home_category"] == "criterion"
    assert fetched["fields"]["description"] == "Safe synthetic summary"
    with pytest.raises(McpReadError):
        surface.call("fetch", {"id": local.id}, owner_id="owner-1")
    assert "synthetic secret" not in json.dumps(search, ensure_ascii=False)
    assert "synthetic secret" not in json.dumps(fetched, ensure_ascii=False)


def test_neo4j_mcp_search_and_fetch_resolve_legacy_asset_category() -> None:
    driver, reads = _gateway()
    legacy = Asset(
        owner_id="owner-1", id="asset-legacy-strength", name="Legacy knowledge asset",
        kind="knowledge", description="Old persisted summary", egress_policy=EgressPolicy.SHAREABLE,
    )
    legacy_row = _persisted_row(legacy, search_text="Legacy knowledge asset knowledge Old persisted summary")
    payload = json.loads(legacy_row["payload_json"])
    payload.pop("home_category")
    legacy_row["payload_json"] = json.dumps(payload, ensure_ascii=False)
    driver.session_value.search_rows = [legacy_row]
    driver.session_value.fetch_rows = [legacy_row]
    surface = McpReadSurface(reads)

    searched = surface.call("search", {"query": "Legacy knowledge"}, owner_id="owner-1")
    fetched = surface.call("fetch", {"id": legacy.id}, owner_id="owner-1")

    assert [item["id"] for item in searched["results"]] == [legacy.id]
    assert searched["results"][0]["fields"]["home_category"] == "strength"
    assert fetched["fields"]["home_category"] == "strength"


def test_neo4j_mcp_fetch_and_search_normalize_legacy_initial_capability() -> None:
    driver, reads = _gateway()
    legacy = Asset(
        owner_id="owner-1", id="asset-legacy-capability", name="Legacy capability",
        kind="strength", description="Reusable skill", egress_policy=EgressPolicy.SHAREABLE,
    )
    row = _persisted_row(legacy, search_text="Legacy capability Reusable skill")
    payload = json.loads(row["payload_json"])
    payload["kind"] = "capability"
    payload.pop("revision")
    payload.pop("supersedes_id")
    row["revision"] = 0
    row["payload_json"] = json.dumps(payload)
    driver.session_value.search_rows = [row]
    driver.session_value.fetch_rows = [row]
    surface = McpReadSurface(reads)

    fetched = surface.call("fetch", {"id": legacy.id}, owner_id="owner-1")
    searched = surface.call("search", {"query": "Legacy capability"}, owner_id="owner-1")

    assert fetched["fields"]["kind"] == "strength"
    assert reads.fetch(legacy.id, owner_id="owner-1").revision == 1
    assert searched["results"][0]["fields"]["kind"] == "strength"


def test_neo4j_search_hides_capability_kind_outside_legacy_initial_shape() -> None:
    driver, reads = _gateway()
    asset = Asset(
        owner_id="owner-1", id="asset-invalid-capability", name="Invalid later capability",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    row = _persisted_row(asset, search_text="Invalid later capability")
    payload = json.loads(row["payload_json"])
    payload["kind"] = "capability"
    row["payload_json"] = json.dumps(payload)
    driver.session_value.search_rows = [row]

    searched = McpReadSurface(reads).call(
        "search", {"query": "Invalid later capability"}, owner_id="owner-1",
    )

    assert searched["results"] == []


def test_mcp_fetch_returns_validated_formal_relation_projection():
    driver, reads = _gateway()
    idea, _claim, _evidence, _brief, assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    driver.session_value.fetch_rows.append(_persisted_row(assertion))

    result = McpReadSurface(reads).call("fetch", {"id": assertion.id}, owner_id="owner-1")

    assert result["id"] == assertion.id
    assert result["status"] == assertion.status.value
    assert result["confidence"] == assertion.confidence
    assert result["valid_from"] == assertion.valid_from.isoformat()
    assert result["path"] == [assertion.source_id, assertion.predicate.value, assertion.target_id]
    assert result["evidence_ids"] == list(assertion.evidence_ids)
    assert not {"excerpt", "locator", "content_chunk_id", "source_revision_id", "claim_id"}.intersection(result)


def test_search_omits_formal_assertion_with_broken_source_lineage():
    driver, reads = _gateway()
    idea, claim, _evidence, _brief, _assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    evidence_row = next(row for row in formal_rows if row["relation"] == "EVIDENCED_BY")
    evidence_row["_lineage"]["source_current_edge_total"] = 2

    assert not any(item.node.id == claim.id for item in reads.search("Foundry", owner_id="owner-1").hits)


def test_search_omits_expired_formal_assertion():
    driver, reads = _gateway()
    idea, claim, _evidence, _brief, _assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    for row in formal_rows:
        payload = json.loads(row["assertion_payload_json"])
        payload["expires_at"] = "2026-09-01T00:00:00+00:00"
        row["assertion_payload_json"] = json.dumps(payload)
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)

    assert not any(item.node.id == claim.id for item in reads.search("Foundry", owner_id="owner-1").hits)


def test_search_ignores_known_source_chain_edges_but_rejects_unknown_domain_edges():
    driver, reads = _gateway()
    source = _node_row("source-1", node_type=NodeType.SOURCE.value, search_text="needle")
    revision = _node_row("revision-1", node_type=NodeType.SOURCE_REVISION.value, search_text="private")
    driver.session_value.search_rows = [source]
    driver.session_value.search_relation_rows = [_relation_row(source, revision, "HAS_SOURCE_REVISION")]

    page = reads.search("needle", owner_id="owner-1")

    assert [hit.node.id for hit in page.hits] == [source["id"]]
    relation_call = next(call for call in driver.session_value.calls if "matched_ids" in call[1])
    assert "HAS_SOURCE_REVISION" in relation_call[1]["internal_edge_types"]
    assert "CURRENT_SOURCE_REVISION" in relation_call[1]["internal_edge_types"]
    assert "HAS_CHUNK" in relation_call[1]["internal_edge_types"]
    assert "EVIDENCE_FROM" in relation_call[1]["internal_edge_types"]

    driver, reads = _gateway()
    driver.session_value.search_rows = [source]
    driver.session_value.search_relation_rows = [_relation_row(source, revision, "UNKNOWN_DOMAIN_EDGE")]
    with pytest.raises(GraphReadError):
        reads.search("needle", owner_id="owner-1")


def test_evidence_lineage_accepts_legacy_missing_chunk_reference_but_rejects_conflict():
    driver, reads = _gateway()
    _idea, _claim, evidence, _brief, _assertion, _endpoints, formal_rows, _brief_row = _formal_fixture()
    evidence_row = next(row for row in formal_rows if row["relation"] == "EVIDENCED_BY")
    evidence_row["_lineage"]["lineages"][0]["chunk_source_revision_id"] = None
    driver.session_value.formal_rows = formal_rows

    assert reads._evidence_lineage_valid(driver.session_value, evidence_id=evidence.id, owner_id="owner-1")

    driver, reads = _gateway()
    _idea, _claim, evidence, _brief, _assertion, _endpoints, formal_rows, _brief_row = _formal_fixture()
    evidence_row = next(row for row in formal_rows if row["relation"] == "EVIDENCED_BY")
    evidence_row["_lineage"]["lineages"][0]["chunk_source_revision_id"] = "conflicting-revision"
    driver.session_value.formal_rows = formal_rows

    assert not reads._evidence_lineage_valid(driver.session_value, evidence_id=evidence.id, owner_id="owner-1")


def test_search_chooses_lexically_first_assertion_for_equal_paths():
    driver, reads = _gateway()
    idea, claim, evidence, _brief, assertion, endpoint_rows, _rows, brief_row = _formal_fixture()
    assertions = (
        replace(assertion, id="assertion-z", assertion_family_id="family-z"),
        replace(assertion, id="assertion-a", assertion_family_id="family-a"),
    )
    formal_rows = [
        _formal_edge_row(item, relation, endpoint_rows[target_id])
        for item in assertions
        for _source_id, relation, target_id in relation_assertion_structural_edges(item)
    ]
    lineage = _formal_fixture()[6]
    evidence_lineage = next(row["_lineage"] for row in lineage if row["relation"] == "EVIDENCED_BY")
    for row in formal_rows:
        if row["relation"] == "EVIDENCED_BY":
            row["_lineage"] = evidence_lineage
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)

    hit = next(item for item in reads.search("Foundry", owner_id="owner-1").hits if item.node.id == claim.id)

    assert hit.evidence_ids == (evidence.id,)
    assert hit.relation_path[0].relation_assertion_id == "assertion-a"


def test_search_returns_neighbor_path_and_uses_parameterized_queries() -> None:
    driver, reads = _gateway()
    person = _node_row(
        "person-1",
        node_type=NodeType.PERSON.value,
        title="Founder network",
        search_text="founder network",
    )
    idea = _node_row("idea-1", title="Circular materials", search_text="circular materials")
    driver.session_value.search_rows = [person]
    driver.session_value.search_relation_rows = [_relation_row(person, idea, RelationType.CAN_CONTRIBUTE_TO.value)]

    page = reads.search("Founder ) MATCH (n)", owner_id="owner-1")

    assert page.hits[0].node.id == person["id"]
    idea_hit = next(hit for hit in page.hits if hit.node.id == idea["id"])
    assert idea_hit.path == ("person-1", RelationType.CAN_CONTRIBUTE_TO.value, "idea-1")
    assert idea_hit.relation_path == ()
    assert idea_hit.score < page.hits[0].score
    assert all("Founder ) MATCH (n)" not in query for query, _params in driver.session_value.calls)
    assert any(params.get("tokens") for _query, params in driver.session_value.calls)


def test_search_expands_two_parameterized_relation_queries_to_two_hops() -> None:
    driver, reads = _gateway()
    person = _node_row(
        "person-1",
        node_type=NodeType.PERSON.value,
        title="Founder network",
        search_text="founder network",
    )
    idea = _node_row("idea-1", title="Circular materials", search_text="circular materials")
    asset = _persisted_row(
        Asset(owner_id="owner-1", id="asset-1", name="Material expertise", kind="artifact"),
        search_text="material expertise",
    )
    driver.session_value.search_rows = [person, asset]
    driver.session_value.search_relation_rows_by_call = [
        [_relation_row(person, idea, RelationType.CAN_CONTRIBUTE_TO.value)],
        [_relation_row(idea, asset, RelationType.REUSES.value)],
    ]

    page = reads.search("Founder", owner_id="owner-1")

    asset_hit = next(hit for hit in page.hits if hit.node.id == asset["id"])
    assert asset_hit.path == (
        "person-1",
        RelationType.CAN_CONTRIBUTE_TO.value,
        "idea-1",
        RelationType.REUSES.value,
        "asset-1",
    )
    assert asset_hit.evidence_ids == ("evidence-1",)
    assert driver.session_value.search_relation_call_count == 2
    assert all(params.get("matched_ids") for query, params in driver.session_value.calls if "matched_ids" in params)


def test_search_projects_current_formal_assertion_from_one_read_transaction() -> None:
    driver, reads = _gateway()
    idea, claim, evidence, legacy, assertion, endpoint_rows, formal_rows, _brief_row = _formal_fixture()
    report_markdown = "\n\n".join(f"## {title}\n\nMarkdown section {index}" for index, title in enumerate(SECTION_TITLES))
    brief = replace(legacy, report_markdown=report_markdown, sections=(IdeaBriefSection(index=0, evidence_ids=(evidence.id,)),))
    brief_row = _serialize_persisted_idea_brief(brief)
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)

    page = reads.search("Foundry", owner_id="owner-1")

    hit = next(item for item in page.hits if item.node.id == claim.id)
    assert hit.path == (idea.id, RelationType.ADDRESSES.value, claim.id) and len(hit.relation_path) == 1
    step = hit.relation_path[0]
    assert (step.relation_assertion_id, step.evidence_ids, step.based_on_brief_id, step.based_on_brief_section_index, step.traversal_direction) == (assertion.id, (evidence.id,), brief.id, 0, "outgoing")
    assert driver.session_value.read_transactions == 1
    result = McpReadSurface(reads).call("search", {"query": "Foundry"}, owner_id="owner-1")
    semantic = next(item for item in result["results"] if item["id"] == claim.id)["semantic_relation_path"][0]
    assert (semantic["relation_assertion_id"], semantic["evidence_ids"], semantic["based_on_brief_id"], semantic["based_on_brief_section_index"]) == (assertion.id, [evidence.id], brief.id, 0)
    assert all(secret not in str(result) for secret in ("A researched section", "must never leave the adapter"))


@pytest.mark.parametrize(
    ("brief_policy", "stored_revision", "expect_relation"),
    [("shareable", 1, True), ("shareable", 2, False), ("local_only", 1, False)],
)
def test_search_projects_quote_only_from_the_current_shareable_brief_revision(
    brief_policy: str, stored_revision: int, expect_relation: bool,
) -> None:
    driver, reads = _gateway()
    idea, claim, evidence, legacy, assertion, endpoint_rows, original_rows, _brief_row = _formal_fixture()
    quote = "創業者が市場を検証する"
    markdown = "\n\n".join(f"## {title}\n\nMarkdown section {index}" for index, title in enumerate(SECTION_TITLES))
    markdown = markdown.replace("Markdown section 0", quote)
    brief = replace(
        legacy,
        report_markdown=markdown,
        egress_policy=brief_policy,
        sections=(IdeaBriefSection(index=0, evidence_ids=(evidence.id,)),),
    )
    quote_start = markdown.index(quote)
    located = replace(
        assertion,
        based_on_brief_revision=stored_revision,
        based_on_brief_quote_start=quote_start,
        based_on_brief_quote_end=quote_start + len(quote),
    )
    formal_rows = []
    for row in original_rows:
        replacement = _formal_edge_row(
            located,
            row["relation"],
            endpoint_rows[row["target_id"]],
        )
        if "_lineage" in row:
            replacement["_lineage"] = row["_lineage"]
        formal_rows.append(replacement)
    _seed_formal_search(
        driver, idea, endpoint_rows, formal_rows, _serialize_persisted_idea_brief(brief),
    )

    page = reads.search("Foundry", owner_id="owner-1")
    matching_steps = [
        step for hit in page.hits for step in hit.relation_path
        if step.relation_assertion_id == located.id
    ]

    if not expect_relation:
        assert not matching_steps
        return
    assert len(matching_steps) == 1
    step = matching_steps[0]
    assert step.based_on_brief_revision == brief.revision
    assert (step.based_on_brief_quote_start, step.based_on_brief_quote_end) == (
        quote_start, quote_start + len(quote),
    )
    assert step.support_quote == quote
    result = McpReadSurface(reads).call("search", {"query": "Foundry"}, owner_id="owner-1")
    hit = next(item for item in result["results"] if item["id"] == claim.id)
    semantic = hit["semantic_relation_path"][0]
    assert semantic["based_on_brief_revision"] == brief.revision
    assert semantic["based_on_brief_quote_start"] == quote_start
    assert semantic["based_on_brief_quote_end"] == quote_start + len(quote)
    assert semantic["support_quote"] == quote
    assert "Markdown section 0" not in str(hit)


def test_search_fails_closed_for_relations_when_markdown_heading_projection_is_ambiguous() -> None:
    driver, reads = _gateway()
    idea, _claim, evidence, legacy, _assertion, endpoint_rows, formal_rows, _brief_row = _formal_fixture()
    complete = "\n\n".join(f"## {title}\n\nMarkdown section {index}" for index, title in enumerate(SECTION_TITLES))
    ambiguous = complete + f"\n\n## {SECTION_TITLES[0]}\n\nDuplicate"
    brief = replace(
        legacy, report_markdown=ambiguous,
        sections=(IdeaBriefSection(index=0, evidence_ids=(evidence.id,)),),
    )
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, _serialize_persisted_idea_brief(brief))

    page = reads.search("Foundry", owner_id="owner-1")

    assert all(item.node.id != "claim-1" for item in page.hits)


def test_search_keeps_formal_path_for_directly_ranked_endpoint_without_changing_rank() -> None:
    driver, reads = _gateway()
    idea, claim, evidence, brief, assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    unrelated = _node_row(
        "idea-unrelated", node_type=NodeType.IDEA.value, title="Foundry unrelated",
        search_text="Foundry unrelated",
    )
    driver.session_value.search_rows = [
        {**endpoint_rows[idea.id], "search_text": "Foundry"},
        {**endpoint_rows[claim.id], "search_text": "Foundry"},
        unrelated,
    ]

    page = reads.search("Foundry", owner_id="owner-1")

    hits = {hit.node.id: hit for hit in page.hits}
    assert hits[idea.id].score == hits[claim.id].score == hits[unrelated["id"]].score
    assert hits[claim.id].path == (idea.id, RelationType.ADDRESSES.value, claim.id)
    assert len(hits[claim.id].relation_path) == 1
    assert hits[claim.id].relation_path[0].relation_assertion_id == assertion.id
    assert hits[claim.id].relation_path[0].evidence_ids == (evidence.id,)
    assert hits[unrelated["id"]].relation_path == ()
    mcp_page = McpReadSurface(reads).call("search", {"query": "Foundry"}, owner_id="owner-1")
    claim_projection = next(item for item in mcp_page["results"] if item["id"] == claim.id)
    assert claim_projection["semantic_relation_path"][0]["relation_assertion_id"] == assertion.id
    assert claim_projection["semantic_relation_path"][0]["evidence_ids"] == [evidence.id]


def test_search_keeps_two_hop_formal_path_for_directly_ranked_endpoint(monkeypatch) -> None:
    driver, reads = _gateway()
    person = _node_row("person-1", node_type=NodeType.PERSON.value, title="Foundry person", search_text="Foundry")
    idea = _node_row("idea-mid", node_type=NodeType.IDEA.value, title="Intermediate idea")
    claim = _node_row("claim-1", node_type=NodeType.CLAIM.value, title="Foundry claim", search_text="Foundry")
    driver.session_value.search_rows = [person, claim]
    driver.session_value.fetch_rows = [person, idea, claim]
    intermediate = NodeView(
        idea["id"], idea["node_type"], idea["owner_id"], idea["id"], idea["id"], idea["status"],
        idea["revision"], MappingProxyType({"egress_policy": EgressPolicy.SHAREABLE.value}),
    )
    first = RelationPathStep(
        from_id=person["id"], to_id=idea["id"], source_id=person["id"],
        predicate=RelationType.CAN_CONTRIBUTE_TO.value, target_id=idea["id"],
        traversal_direction="outgoing", evidence_ids=("evidence-1",),
        relation_assertion_id="assertion-person-idea", status="inferred", valid_from="2026-01-01T00:00:00+00:00",
    )
    second = RelationPathStep(
        from_id=idea["id"], to_id=claim["id"], source_id=idea["id"],
        predicate=RelationType.ADDRESSES.value, target_id=claim["id"],
        traversal_direction="outgoing", evidence_ids=("evidence-2",),
        relation_assertion_id="assertion-idea-claim", status="inferred", valid_from="2026-01-01T00:00:00+00:00",
    )
    adjacency = {
        person["id"]: [(idea["id"], first)],
        idea["id"]: [(claim["id"], second)],
    }
    monkeypatch.setattr(reads, "_formal_adjacency", lambda *_args, **_kwargs: (adjacency, {idea["id"]: intermediate}))

    page = reads.search("Foundry", owner_id="owner-1")

    hits = {hit.node.id: hit for hit in page.hits}
    assert hits[person["id"]].score == hits[claim["id"]].score
    assert hits[claim["id"]].path == (
        person["id"], RelationType.CAN_CONTRIBUTE_TO.value, idea["id"],
        RelationType.ADDRESSES.value, claim["id"],
    )
    assert [step.relation_assertion_id for step in hits[claim["id"]].relation_path] == [
        first.relation_assertion_id, second.relation_assertion_id,
    ]


def test_direct_hit_provenance_does_not_change_reranker_context(monkeypatch) -> None:
    driver, reads = _gateway()
    idea, claim, _evidence, _brief, assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    candidates = [endpoint_rows[idea.id], endpoint_rows[claim.id]]

    class SearchModels:
        candidate_texts = ()

        def rerank(self, _query, candidate_texts):
            self.candidate_texts = tuple(candidate_texts)
            return [1.0] * len(candidate_texts)

    models = SearchModels()
    service = Neo4jGraphReadService(reads._gateway, search_models=models, rerank_enabled=True)
    monkeypatch.setattr(
        service, "_hybrid_candidates",
        lambda *_args, **_kwargs: (tuple(candidates), {idea.id: 1.0, claim.id: 1.0}),
    )

    page = service.search("Foundry", owner_id="owner-1")

    assert all("relation path:" not in candidate_text for candidate_text in models.candidate_texts)
    claim_hit = next(hit for hit in page.hits if hit.node.id == claim.id)
    assert claim_hit.relation_path[0].relation_assertion_id == assertion.id


def test_search_and_fetch_project_inferred_successor_with_superseded_history_ref() -> None:
    driver, reads = _gateway()
    idea, claim, evidence, _brief, predecessor, endpoint_rows, old_rows, brief_row = _formal_fixture()
    predecessor = replace(predecessor, status="superseded")
    current = RelationAssertion(
        owner_id=predecessor.owner_id, id="assertion-current", source_id=predecessor.source_id,
        target_id=predecessor.target_id, source_kind=predecessor.source_kind,
        target_kind=predecessor.target_kind, predicate=predecessor.predicate,
        assertion_family_id=predecessor.assertion_family_id, revision=2, status="inferred",
        confidence=0.9, evidence_ids=(evidence.id,), valid_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
        supersedes_id=predecessor.id, egress_policy=EgressPolicy.SHAREABLE,
        provenance=predecessor.provenance.__class__(operation="link_entities", target_id="assertion-current", idempotency_key="successor-key"),
        based_on_brief_id=predecessor.based_on_brief_id, based_on_brief_section_index=0,
    )
    endpoint_rows[predecessor.id] = _persisted_row(predecessor)
    formal_rows = [
        _formal_edge_row(current, relation, endpoint_rows[target_id])
        for _source_id, relation, target_id in relation_assertion_structural_edges(current)
    ]
    evidence_row = next(row for row in old_rows if row["relation"] == "EVIDENCED_BY")
    next(row for row in formal_rows if row["relation"] == "EVIDENCED_BY").update({"_lineage": evidence_row["_lineage"]})
    from nebula.founder_graph_neo4j_read import _checked_historical_supersedes_ref
    history_row = next(row for row in formal_rows if row["relation"] == RelationAssertionEdgeType.SUPERSEDES.value)
    assert _checked_historical_supersedes_ref(history_row, owner_id="owner-1", successor=current).id == predecessor.id
    endpoint_rows[current.id] = _persisted_row(current, search_text="")
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    from time import monotonic
    adjacency, _views = reads._formal_adjacency(
        driver.session_value, owner_id="owner-1", at=datetime.now(timezone.utc), started=monotonic(), timeout_ms=30_000,
    )
    assert idea.id in adjacency, sorted(adjacency)
    assert any(step.relation_assertion_id == current.id for _neighbor, step in adjacency[idea.id])
    assert reads.fetch_relation_assertion(current.id, owner_id="owner-1").relation_assertion_id == current.id

    page = reads.search("Foundry", owner_id="owner-1")
    hit = next(item for item in page.hits if item.node.id == claim.id)
    assert len(hit.relation_path) == 1
    assert hit.relation_path[0].relation_assertion_id == current.id
    fetched = reads.fetch_relation_assertion(current.id, owner_id="owner-1")
    assert fetched.status == "inferred"
    assert fetched.relation_assertion_id == current.id
    mcp_fetched = McpReadSurface(reads).call("fetch", {"id": current.id}, owner_id="owner-1")
    assert mcp_fetched["id"] == current.id and mcp_fetched["status"] == "inferred"
    assert mcp_fetched["path"] == [idea.id, RelationType.ADDRESSES.value, claim.id]


@pytest.mark.parametrize("mutation", ["foreign_owner", "wrong_family", "wrong_revision", "wrong_endpoint"])
def test_historical_supersedes_ref_rejects_unrelated_or_invalid_predecessor(mutation: str) -> None:
    _driver, _reads = _gateway()
    idea, claim, evidence, _brief, prior, endpoint_rows, _old_rows, _brief_row = _formal_fixture()
    prior = replace(prior, status="superseded")
    current = RelationAssertion(
        owner_id="owner-1", id="assertion-current", source_id=idea.id, target_id=claim.id,
        source_kind=NodeType.IDEA, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id=prior.assertion_family_id, revision=2, status="inferred", confidence=0.9,
        evidence_ids=(evidence.id,), valid_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
        supersedes_id=prior.id, egress_policy=EgressPolicy.SHAREABLE,
        provenance=prior.provenance.__class__(operation="link_entities", target_id="assertion-current", idempotency_key="successor-key"),
        based_on_brief_id=prior.based_on_brief_id, based_on_brief_section_index=0,
    )
    if mutation == "foreign_owner":
        prior = replace(prior, owner_id="owner-2")
    elif mutation == "wrong_family":
        prior = replace(prior, assertion_family_id="different-family")
    elif mutation == "wrong_revision":
        prior = replace(prior, revision=2)
    else:
        prior = replace(prior, target_id="unrelated-claim")
    endpoint_rows[prior.id] = _persisted_row(prior)
    row = _formal_edge_row(current, RelationAssertionEdgeType.SUPERSEDES.value, endpoint_rows[prior.id])

    from nebula.founder_graph_neo4j_read import _checked_historical_supersedes_ref
    with pytest.raises((GraphReadNotFoundError, ValueError)):
        _checked_historical_supersedes_ref(row, owner_id="owner-1", successor=current)


@pytest.mark.parametrize(("brief_ref", "evidence_refs", "field", "value", "stale_idea", "policy"), [
    ("old-brief", None, None, None, False, EgressPolicy.SHAREABLE), (None, (), None, None, False, EgressPolicy.SHAREABLE), (None, ("evidence-1", "extra"), None, None, False, EgressPolicy.SHAREABLE),
    (None, None, "target_owner_id", "owner-2", False, EgressPolicy.SHAREABLE),
    (None, None, "target_node_type", NodeType.PERSON.value, False, EgressPolicy.SHAREABLE),
    (None, None, None, None, True, EgressPolicy.SHAREABLE),
    (None, None, None, None, False, EgressPolicy.LOCAL_ONLY),
    *((None, None, "target_status", status, False, EgressPolicy.SHAREABLE) for status in ("archived", "superseded", "retracted", "expired", "cancelled", "revoked")),
])
def test_search_omits_formal_assertion_with_stale_or_malformed_refs(brief_ref, evidence_refs, field, value, stale_idea, policy) -> None:
    driver, reads = _gateway()
    idea, claim, _evidence, _brief, _assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture(
        assertion_brief_id=brief_ref, evidence_refs=evidence_refs, assertion_policy=policy)
    if field:
        row = next(row for row in formal_rows if row["relation"] == "EVIDENCED_BY")
        row[field] = value
        if field == "target_status": row["target_payload_json"] = json.dumps({**json.loads(row["target_payload_json"]), "status": value})
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    if stale_idea:
        child = _persisted_row(idea.revise(title="New leaf"))
        driver.session_value.idea_rows.append(child)
    hits = [item for item in reads.search("Foundry", owner_id="owner-1").hits if item.node.id == claim.id]
    assert not hits or hits[0].relation_path == ()


def test_search_omits_formal_assertion_with_archived_claim_endpoint() -> None:
    driver, reads = _gateway(); idea, claim, _evidence, _brief, _assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row); row = next(row for row in formal_rows if row["relation"] == "ASSERTS_TO"); payload = json.loads(row["target_payload_json"])
    row["target_status"] = payload["status"] = "archived"; row["target_payload_json"] = json.dumps(payload)
    hits = [item for item in reads.search("Foundry", owner_id="owner-1").hits if item.node.id == claim.id]; assert not hits or hits[0].relation_path == ()


@pytest.mark.parametrize(("successor_owner", "visible"), [("owner-2", True), ("owner-1", False)])
def test_foreign_successor_does_not_hide_local_relation(successor_owner: str, visible: bool) -> None:
    driver, reads = _gateway()
    idea, claim, _evidence, _brief, assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, brief_row)
    successor = dict(endpoint_rows[claim.id], id="successor-1", owner_id=successor_owner,
                     node_type=NodeType.RELATION_ASSERTION.value, revision=2, status="inferred")
    incoming = _formal_edge_row(assertion, RelationAssertionEdgeType.SUPERSEDES.value, successor)
    formal_rows.append(incoming | {"is_outgoing": False})

    hits = [item for item in reads.search("Foundry", owner_id="owner-1").hits if item.node.id == claim.id]
    assert bool(hits and hits[0].relation_path) is visible


def test_higher_scoring_legacy_path_replaces_formal_path_provenance() -> None:
    driver, reads = _gateway(); idea, claim, _evidence, _brief, _assertion, rows, formal_rows, brief_row = _formal_fixture()
    _seed_formal_search(driver, idea, rows, formal_rows, brief_row)
    idea_row = {**rows[idea.id], "search_text": "foundry"}
    person = _node_row("person-1", node_type=NodeType.PERSON.value, title="Foundry graph", search_text="Foundry graph")
    driver.session_value.search_rows = [idea_row, person]; driver.session_value.fetch_rows.append(person)
    driver.session_value.search_relation_rows = [_relation_row(person, rows[claim.id], RelationType.USES_SKILL.value)]

    page = reads.search("Foundry graph", owner_id="owner-1")
    hit = next(item for item in page.hits if item.node.id == claim.id)
    assert hit.path == (person["id"], RelationType.USES_SKILL.value, claim.id) and hit.relation_path == ()
    result = McpReadSurface(reads).call("search", {"query": "Foundry graph"}, owner_id="owner-1")
    claim_result = next(item for item in result["results"] if item["id"] == claim.id)
    assert claim_result["relation_path"] == list(hit.path) and "semantic_relation_path" not in claim_result


def test_higher_scoring_formal_path_replaces_all_winning_path_metadata() -> None:
    driver, reads = _gateway()
    source_low = PersonAsset(owner_id="owner-1", id="person-a", name="Foundry", egress_policy=EgressPolicy.SHAREABLE)
    source_high = PersonAsset(owner_id="owner-1", id="person-z", name="Foundry graph", egress_policy=EgressPolicy.SHAREABLE)
    asset = Asset(owner_id="owner-1", id="asset-1", name="Target", egress_policy=EgressPolicy.SHAREABLE)
    _, claim, evidence, _, _grounded_assertion, endpoint_rows, grounded_rows, _brief_row = _formal_fixture()
    nodes = (source_low, source_high, asset)
    endpoint_rows.update({node.id: _persisted_row(node, search_text=getattr(node, "name", "")) for node in nodes})
    assertions = tuple(
        RelationAssertion(
            owner_id="owner-1", id=f"assertion-{suffix}", source_id=source.id, target_id=asset.id,
            source_kind=NodeType.PERSON, target_kind=NodeType.ASSET,
            predicate=RelationType.HAS_CAPABILITY, assertion_family_id=f"family-{suffix}",
            status="inferred", confidence=0.8, evidence_ids=(evidence.id,),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), egress_policy=EgressPolicy.SHAREABLE,
        )
        for suffix, source in (("low", source_low), ("high", source_high))
    )
    formal_rows = [
        _formal_edge_row(assertion, relation, endpoint_rows[target_id])
        for assertion in assertions
        for _source_id, relation, target_id in relation_assertion_structural_edges(assertion)
    ]
    grounded_lineage = next(row["_lineage"] for row in grounded_rows if row["relation"] == "EVIDENCED_BY")
    for row in formal_rows:
        if row["relation"] == "EVIDENCED_BY":
            row["_lineage"] = grounded_lineage
    driver.session_value.search_rows = [
        {**endpoint_rows[source_low.id], "search_text": "foundry"},
        {**endpoint_rows[source_high.id], "search_text": "foundry graph"},
    ]
    driver.session_value.fetch_rows = list(endpoint_rows.values())
    driver.session_value.formal_rows = formal_rows

    hit = next(item for item in reads.search("foundry graph", owner_id="owner-1").hits if item.node.id == asset.id)

    assert hit.path == (source_high.id, RelationType.HAS_CAPABILITY.value, asset.id)
    assert [step.relation_assertion_id for step in hit.relation_path] == ["assertion-high"]
    assert hit.evidence_ids == (evidence.id,)


def test_search_paginates_with_stable_cursor() -> None:
    driver, reads = _gateway()
    driver.session_value.search_rows = [
        _node_row("idea-0", title="Graph seed", search_text="graph seed"),
        _node_row("idea-1", title="Graph seed", search_text="graph seed"),
        _node_row("idea-2", title="Graph seed", search_text="graph seed"),
    ]

    first = reads.search("Graph", owner_id="owner-1", limit=2)
    second = reads.search("Graph", owner_id="owner-1", limit=2, cursor=first.next_cursor)

    assert first.next_cursor == "2"
    assert [hit.node.id for hit in first.hits] == ["idea-0", "idea-1"]
    assert [hit.node.id for hit in second.hits] == ["idea-2"]


def test_relations_are_owner_scoped_and_stably_sorted() -> None:
    driver, reads = _gateway()
    root = _node_row("root")
    first = _node_row("first")
    second = _node_row("second")
    driver.session_value.fetch_rows = [root]
    driver.session_value.relation_rows = [
        {
            "source_id": "root",
            "relation": RelationType.REUSES.value,
            "target_id": "second",
            "source_owner_id": "owner-1",
            "target_owner_id": "owner-1",
            "source_node_type": NodeType.IDEA.value,
            "target_node_type": NodeType.IDEA.value,
        },
        {
            "source_id": "root",
            "relation": RelationType.ADDRESSES.value,
            "target_id": "first",
            "source_owner_id": "owner-1",
            "target_owner_id": "owner-1",
            "source_node_type": NodeType.IDEA.value,
            "target_node_type": NodeType.IDEA.value,
        },
    ]

    relations = reads.relations("root", owner_id="owner-1")

    assert relations == (
        GraphRelationView("root", RelationType.ADDRESSES.value, "first", NodeType.IDEA.value, NodeType.IDEA.value),
        GraphRelationView("root", RelationType.REUSES.value, "second", NodeType.IDEA.value, NodeType.IDEA.value),
    )
    relation_query, relation_params = driver.session_value.calls[-1]
    assert "owner_id = $owner_id" in relation_query
    assert relation_params["owner_id"] == "owner-1"


def test_relations_require_a_current_local_node() -> None:
    _driver, reads = _gateway()

    with pytest.raises(GraphReadNotFoundError):
        reads.relations("missing", owner_id="owner-1")
    with pytest.raises(GraphReadNotFoundError):
        reads.relations("root", owner_id="owner-2")


def test_malformed_payload_is_a_recoverable_read_error() -> None:
    driver, reads = _gateway()
    row = _node_row("broken")
    row["payload_json"] = "not-json"
    driver.session_value.fetch_rows = [row]

    with pytest.raises(GraphReadError, match="valid JSON"):
        reads.fetch("broken", owner_id="owner-1")


def test_search_exposes_brief_hypothesis_from_prior_import_without_runs_or_edge_evidence():
    driver, reads = _gateway()
    idea, claim, _evidence, brief, assertion, endpoint_rows, _rows, _brief_row = _formal_fixture(
        brief_origin="prior_research_import",
    )
    hypothesis = replace(
        assertion, status="proposed", basis=RelationAssertionBasis.BRIEF_HYPOTHESIS, evidence_ids=(),
        based_on_brief_section_index=None,
    )
    brief = replace(
        brief,
        sections=tuple(replace(section, content="") for section in brief.sections),
        report_markdown="## Imported Brief\n\nSynthetic whole-draft anchor.",
    )
    formal_rows = [
        _formal_edge_row(hypothesis, relation, endpoint_rows[target_id])
        for _source_id, relation, target_id in relation_assertion_structural_edges(hypothesis)
    ]
    _seed_formal_search(driver, idea, endpoint_rows, formal_rows, _serialize_persisted_idea_brief(brief))

    page = reads.search("Foundry", owner_id="owner-1")
    hit = next(item for item in page.hits if item.node.id == claim.id)
    assert hit.relation_path[0].basis == RelationAssertionBasis.BRIEF_HYPOTHESIS.value
    assert hit.relation_path[0].evidence_ids == ()
    assert hit.relation_path[0].based_on_brief_section_index is None

    newer = brief.revise(change_reason="newer imported Brief", research_run_ids=(), origin="prior_research_import")
    driver.session_value.brief_rows.append(_serialize_persisted_idea_brief(newer))
    stale_page = reads.search("Foundry", owner_id="owner-1")
    assert all(
        step.relation_assertion_id != hypothesis.id
        for hit in stale_page.hits for step in hit.relation_path
    )
