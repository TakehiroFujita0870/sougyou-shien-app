from __future__ import annotations

from dataclasses import FrozenInstanceError
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from dots.founder_graph_read import (
    GraphReadUnavailableError,
    NodeView,
    SearchHit,
    SearchPage,
)
from dots.founder_graph_enrichment import (
    ClusterProposal,
    EnrichmentKind,
    FacetProposal,
    NameResolutionProposal,
    SafeNodeProjection,
    build_enrichment_proposals,
)


def _view(node_id: str, node_type: str, *, policy: str, **fields: object) -> NodeView:
    values = {"egress_policy": policy, **fields}
    title = str(values.get("name") or values.get("title") or node_id)
    return NodeView(
        id=node_id,
        node_type=node_type,
        owner_id="owner-1",
        title=title,
        snippet=title,
        status="active",
        revision=0,
        fields=MappingProxyType(values),
    )


def _projection(node_id: str, name: str, *, kind: str, evidence: str, source: str) -> SafeNodeProjection:
    return SafeNodeProjection(
        id=node_id,
        node_type="person",
        fields={"name": name, "kind": kind, "status": "active"},
        evidence_ids=(evidence,),
        source_ids=(source,),
    )


def test_builder_emits_immutable_name_facet_and_cluster_proposals_with_luna_snapshot() -> None:
    batch = build_enrichment_proposals(
        (
            _projection("person-a", "Alice", kind="person", evidence="e-a", source="source-a"),
            _projection("person-b", " alice ", kind="person", evidence="e-b", source="source-b"),
            SafeNodeProjection(
                id="asset-a",
                node_type="asset",
                fields={"name": "Graph skill", "kind": "knowledge", "status": "active"},
                evidence_ids=("e-c",),
                source_ids=("source-c",),
            ),
            SafeNodeProjection(
                id="asset-b",
                node_type="asset",
                fields={"name": "Search skill", "kind": "knowledge", "status": "active"},
                evidence_ids=("e-d",),
                source_ids=("source-d",),
            ),
        )
    )

    assert batch.model_snapshot == "luna@founder-graph-v1"
    assert {proposal.kind for proposal in batch} == {
        EnrichmentKind.NAME_RESOLUTION,
        EnrichmentKind.FACET,
        EnrichmentKind.CLUSTER,
    }
    resolution = next(item for item in batch if isinstance(item, NameResolutionProposal))
    assert resolution.target_id == "person-b"
    assert resolution.canonical_id == "person-a"
    assert resolution.evidence_ids == ("e-a", "e-b")
    assert resolution.source_ids == ("source-a", "source-b")
    assert resolution.status.value == "proposed"
    assert 0.0 <= resolution.confidence <= 1.0

    facets = [item for item in batch if isinstance(item, FacetProposal)]
    assert any(item.target_id == "asset-a" and item.facet_value == "knowledge" for item in facets)
    clusters = [item for item in batch if isinstance(item, ClusterProposal)]
    assert any(item.member_ids == ("asset-a", "asset-b") for item in clusters)

    with pytest.raises(FrozenInstanceError):
        resolution.target_id = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        resolution.evidence_ids[0] = "mutated"  # type: ignore[index]

    serialized = batch.as_dict()
    assert "private_notes" not in str(serialized)
    assert "owner_id" not in serialized


def test_shareable_search_hits_are_sanitized_and_local_only_hits_are_omitted() -> None:
    shareable = _view(
        "person-1",
        "person",
        policy="shareable",
        name="Aki",
        kind="person",
        contact={"email": "private@example.test"},
        private_notes="do not include",
    )
    local_only = _view(
        "person-private",
        "person",
        policy="local_only",
        name="Aki",
        contact={"email": "local@example.test"},
    )

    batch = build_enrichment_proposals(
        (
            SearchHit(shareable, 1.0),
            SearchHit(local_only, 0.9),
        ),
        evidence_ids=("e-search",),
        source_ids=("source-search",),
    )

    assert batch.omitted_count == 1
    assert all("local@example.test" not in str(item.as_dict()) for item in batch)
    assert all("private_notes" not in str(item.as_dict()) for item in batch)
    assert all(item.evidence_ids == ("e-search",) for item in batch)
    assert all(item.source_ids == ("source-search",) for item in batch)


@dataclass
class _ReadStub:
    page: SearchPage
    calls: list[dict[str, object]]

    @property
    def owner_id(self) -> str:
        return "owner-1"

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        self.calls.append(
            {
                "query": query,
                "owner_id": owner_id,
                "limit": limit,
                "cursor": cursor,
                "timeout_ms": timeout_ms,
            }
        )
        return self.page

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        raise AssertionError("enrichment must not fetch or write graph nodes")


def test_graph_read_input_is_one_bounded_local_search_and_preserves_cursor() -> None:
    reads = _ReadStub(
        SearchPage(
            hits=(SearchHit(_view("idea-1", "idea", policy="shareable", title="Founder Graph"), 1.0),),
            next_cursor="20",
        ),
        [],
    )

    batch = build_enrichment_proposals(reads, "founder graph", owner_id="owner-1", limit=20, timeout_ms=250)

    assert batch.query == "founder graph"
    assert batch.next_cursor == "20"
    assert reads.calls == [
        {
            "query": "founder graph",
            "owner_id": "owner-1",
            "limit": 20,
            "cursor": None,
            "timeout_ms": 250,
        }
    ]


def test_graph_read_failure_is_propagated_without_partial_proposal() -> None:
    class _Unavailable(_ReadStub):
        def search(self, *args: object, **kwargs: object) -> SearchPage:
            raise GraphReadUnavailableError("stopped")

    reads = _Unavailable(SearchPage((), None), [])

    with pytest.raises(GraphReadUnavailableError, match="stopped"):
        build_enrichment_proposals(reads, "founder", owner_id="owner-1")


def test_safe_mapping_requires_shareable_policy_or_a_narrow_allowlist() -> None:
    batch = build_enrichment_proposals(
        {
            "id": "idea-1",
            "kind": "idea",
            "fields": {
                "title": "Safe idea",
                "egress_policy": "shareable",
                "source_text": "private source text",
            },
        }
    )
    assert batch.proposals == ()

    omitted = build_enrichment_proposals(
        {
            "id": "idea-private",
            "kind": "idea",
            "fields": {"title": "Private idea", "source_text": "private"},
        }
    )
    assert omitted.proposals == ()
    assert omitted.omitted_count == 1
