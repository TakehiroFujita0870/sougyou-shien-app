from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dots.founder_graph import ContentChunk, EgressPolicy, Evidence, Idea, NodeType, RelationAssertion, Source, SourceRevision
from dots.founder_graph import Asset, Claim, PersonAsset, RelationAssertionEdgeType, RelationType, Status, relation_assertion_structural_edges
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_read import GraphRelationView, Neo4jGraphReadService
from dots.founder_graph_mcp import McpReadError, McpReadSurface
from dots.founder_graph_neo4j_idea_brief import _serialize_persisted_idea_brief
from dots.founder_graph_read import GraphReadError, GraphReadNotFoundError


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
        if "IdeaBriefVersion" in query:
            return FakeResult(self.brief_rows)
        if "MATCH (i:Idea" in query:
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
            return FakeResult([row for row in self.fetch_rows if row.get("id") == params.get("node_id")])
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


def _formal_fixture(*, assertion_brief_id: str | None = None, evidence_refs: tuple[str, ...] | None = None, assertion_policy=EgressPolicy.SHAREABLE):
    idea = Idea(owner_id="owner-1", id="idea-1", title="Foundry search seed", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    claim = Claim(owner_id="owner-1", id="claim-1", text="A supported claim", egress_policy=EgressPolicy.SHAREABLE)
    revision = SourceRevision(owner_id="owner-1", id="revision-1", source_id="source-1", content="grounded synthetic source")
    source = Source(owner_id="owner-1", id="source-1", title="Synthetic source",
                    current_revision_id=revision.id, revision=1)
    chunk = ContentChunk(owner_id="owner-1", id="chunk-1", source_revision_id=revision.id, ordinal=0,
                         char_start=0, char_end=len(revision.content), text=revision.content)
    evidence = Evidence(owner_id="owner-1", id="evidence-1", claim_id=claim.id,
                        source_revision_id=revision.id, content_chunk_id=chunk.id,
                        char_start=0, char_end=len(revision.content), locator=f"chars:0-{len(revision.content)}",
                        content_hash=chunk.text_hash, status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    brief = IdeaBriefVersion(owner_id="owner-1", idea_lineage_root_id=idea.id, based_on_idea_id=idea.id, id="brief-1", research_run_ids=("run-1",), egress_policy="shareable", sections=(IdeaBriefSection(index=0, content="A researched section", evidence_ids=(evidence.id,)),))
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
                      description="Safe synthetic summary", egress_policy=EgressPolicy.SHAREABLE)
    local = Asset(owner_id="owner-1", id="asset-local", name="Private kit", kind="data",
                  description="Private description", details={"private_notes": "synthetic secret"})
    driver.session_value.search_rows = [
        _persisted_row(shareable, search_text="Synthetic kit Safe synthetic summary"),
        _persisted_row(local, search_text="Private kit Private description"),
    ]
    driver.session_value.fetch_rows = [_persisted_row(shareable), _persisted_row(local)]
    surface = McpReadSurface(reads)

    search = surface.call("search", {"query": "synthetic"}, owner_id="owner-1")
    assert [item["id"] for item in search["results"]] == [shareable.id]
    assert set(search["results"][0]["fields"]) == {"name", "kind", "description", "status"}
    assert search["results"][0]["fields"]["description"] == "Safe synthetic summary"
    fetched = surface.call("fetch", {"id": shareable.id}, owner_id="owner-1")
    assert fetched["id"] == shareable.id
    assert set(fetched["fields"]) == {"name", "kind", "description", "status"}
    assert fetched["fields"]["description"] == "Safe synthetic summary"
    with pytest.raises(McpReadError):
        surface.call("fetch", {"id": local.id}, owner_id="owner-1")
    assert "synthetic secret" not in json.dumps(search, ensure_ascii=False)
    assert "synthetic secret" not in json.dumps(fetched, ensure_ascii=False)


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
    asset = _node_row("asset-1", node_type=NodeType.ASSET.value, title="Material expertise", search_text="material expertise")
    driver.session_value.search_rows = [person]
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
    idea, claim, evidence, brief, assertion, endpoint_rows, formal_rows, brief_row = _formal_fixture()
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
