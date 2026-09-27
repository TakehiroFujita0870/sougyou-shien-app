from __future__ import annotations

from dots.founder_graph import Claim, EgressPolicy, MaterialKind, Source, SourceRevision
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_mcp_write import McpWriteSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import InMemoryGraphWriteService


def test_facet_search_returns_only_shareable_facets() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    local = writer.call("capture_facet", {
        "namespace": "business", "value": "Private bakery", "idempotency_key": "facet-private",
    }, owner_id="owner-1")
    shared = writer.call("capture_facet", {
        "namespace": "business", "value": "Public bakery", "egress_policy": "shareable",
        "idempotency_key": "facet-public",
    }, owner_id="owner-1")
    reader = McpReadSurface(GraphReadService(writes))

    result = reader.call("search_facets", {"query": "bakery"}, owner_id="owner-1")

    assert [item["id"] for item in result["results"]] == [shared.target_id]
    assert local.target_id not in str(result)
    assert result["results"][0]["fields"]["normalized_value"] == "public bakery"


def test_facet_search_filters_before_page_limit_with_many_nonfacet_matches() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    for index in range(21):
        writer.call("capture_asset", {
            "name": f"Bakery asset {index}", "kind": "artifact", "egress_policy": "shareable",
            "idempotency_key": f"bakery-asset-{index}",
        }, owner_id="owner-1")
    expected = writer.call("capture_facet", {
        "namespace": "business", "value": "Bakery", "egress_policy": "shareable",
        "idempotency_key": "facet-after-many-assets",
    }, owner_id="owner-1")
    reader = McpReadSurface(GraphReadService(writes))

    result = reader.call("search_facets", {"query": "bakery", "limit": 1}, owner_id="owner-1")

    assert [facet["id"] for facet in result["results"]] == [expected.target_id]
    assert result["next_cursor"] is None


def test_mcp_classification_supports_multiple_facets_and_region_reads() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    root = writer.call("capture_facet", {
        "namespace": "domain", "value": "Food", "egress_policy": "shareable", "idempotency_key": "facet-food",
    }, owner_id="owner-1")
    child = writer.call("capture_facet", {
        "namespace": "domain", "value": "Bakery", "egress_policy": "shareable", "idempotency_key": "facet-bakery",
    }, owner_id="owner-1")
    asset = writer.call("capture_asset", {
        "name": "Oven", "kind": "equipment", "egress_policy": "shareable", "idempotency_key": "asset-oven",
    }, owner_id="owner-1")
    claim = writer.call("append_claim", {
        "text": "Synthetic public evidence claim", "confidence": 0.9,
        "egress_policy": "shareable", "idempotency_key": "claim-facet-evidence",
    }, owner_id="owner-1")
    source = Source(
        owner_id="owner-1", id="facet-source", title="Public source", kind=MaterialKind.WEB,
        locator="https://example.test/facet", current_revision_id="facet-source-revision", revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    revision = SourceRevision(
        owner_id="owner-1", id="facet-source-revision", source_id=source.id,
        content="Synthetic source text", locator=source.locator, egress_policy=EgressPolicy.SHAREABLE,
    )
    captured_source = writes.capture_source(source, revision, idempotency_key="capture-facet-source")
    evidence = writes.capture_evidence(
        claim.target_id, captured_source.content_chunk_ids[0],
        egress_policy=EgressPolicy.SHAREABLE, idempotency_key="capture-facet-evidence",
    )

    first = writer.call("classify_entity", {
        "entity_id": asset.target_id, "facet_id": root.target_id, "evidence_ids": [evidence.target_id],
        "status": "inferred", "egress_policy": "shareable", "idempotency_key": "classify-oven-food",
    }, owner_id="owner-1")
    second = writer.call("classify_entity", {
        "entity_id": asset.target_id, "facet_id": child.target_id, "evidence_ids": [evidence.target_id],
        "status": "inferred", "egress_policy": "shareable", "idempotency_key": "classify-oven-bakery",
    }, owner_id="owner-1")
    reader = McpReadSurface(GraphReadService(writes))

    root_region = reader.call("facet_region", {"facet_id": root.target_id}, owner_id="owner-1")
    child_region = reader.call("facet_region", {"facet_id": child.target_id}, owner_id="owner-1")
    ordinary_search = reader.call("search", {"query": "Oven"}, owner_id="owner-1")

    assert first.target_id != second.target_id
    assert [item["entity"]["id"] for item in root_region["results"]] == [asset.target_id]
    assert [item["entity"]["id"] for item in child_region["results"]] == [asset.target_id]
    assert root_region["results"][0]["facet_path"] == [
        {"facet_id": root.target_id, "label": "domain: Food", "depth": 0},
    ]
    assert child_region["results"][0]["facet_path"] == [
        {"facet_id": child.target_id, "label": "domain: Bakery", "depth": 0},
    ]
    assert any(item["id"] == asset.target_id for item in ordinary_search["results"])
