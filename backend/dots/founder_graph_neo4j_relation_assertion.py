"""Persistence checks for source-grounded RelationAssertion writes."""

from __future__ import annotations

from typing import Any

from .founder_graph import EgressPolicy, NodeType, RelationAssertion, Status
from .founder_graph_neo4j_codec import record_value as _record_value, single_record as _single
from .founder_graph_write import GraphWriteError, GraphWriteNotFoundError


def validate_relation_assertion_evidence_tx(gateway: Any, tx: Any, assertion: RelationAssertion) -> None:
    """Validate active, owner-scoped Evidence and its exact source lineage."""
    if not assertion.evidence_ids:
        raise GraphWriteError("formal relation assertion requires Evidence")
    for evidence_id in assertion.evidence_ids:
        evidence = _single(tx.run(
            "MATCH (e:Evidence {id: $id}) RETURN e.owner_id AS owner_id, e.node_type AS node_type, "
            "e.status AS status, e.egress_policy AS egress_policy",
            id=evidence_id,
        ))
        if evidence is None or _record_value(evidence, "owner_id") != gateway.owner_id:
            raise GraphWriteNotFoundError("relation assertion Evidence does not exist")
        if _record_value(evidence, "node_type") != NodeType.EVIDENCE.value:
            raise GraphWriteError("relation assertion Evidence has an invalid type")
        if _record_value(evidence, "status") != Status.ACTIVE.value:
            raise GraphWriteError("relation assertion Evidence must be active")
        lineage = _single(tx.run(
            "MATCH (e:Evidence {id: $evidence_id, owner_id: $owner_id}) "
            "OPTIONAL MATCH (e)-[ef:EVIDENCE_FROM]->(evidence_target) "
            "OPTIONAL MATCH (ch:ContentChunk) WHERE ch.id = e.content_chunk_id "
            "OPTIONAL MATCH (e)-[expected_ef:EVIDENCE_FROM]->(expected_ch:ContentChunk "
            "{owner_id: $owner_id}) WHERE expected_ch.id = e.content_chunk_id "
            "OPTIONAL MATCH (chunk_origin)-[hc:HAS_CHUNK]->(ch) "
            "OPTIONAL MATCH (r:SourceRevision {owner_id: $owner_id}) WHERE r.id = e.source_revision_id "
            "OPTIONAL MATCH (r)-[expected_hc:HAS_CHUNK]->(ch) "
            "RETURN e.content_chunk_id AS content_chunk_id, e.source_revision_id AS source_revision_id, "
            "ch.id AS chunk_id, ch.node_type AS chunk_type, ch.status AS chunk_status, "
            "r.id AS revision_id, r.node_type AS revision_type, r.status AS revision_status, "
            "count(DISTINCT ef) AS evidence_edge_count, count(DISTINCT expected_ef) AS expected_evidence_edge_count, "
            "count(DISTINCT hc) AS chunk_edge_count, count(DISTINCT expected_hc) AS expected_chunk_edge_count",
            evidence_id=evidence_id, owner_id=gateway.owner_id,
        ))
        if (
            lineage is None
            or _record_value(lineage, "content_chunk_id") != _record_value(lineage, "chunk_id")
            or _record_value(lineage, "source_revision_id") != _record_value(lineage, "revision_id")
            or _record_value(lineage, "chunk_type") != NodeType.CONTENT_CHUNK.value
            or _record_value(lineage, "revision_type") != NodeType.SOURCE_REVISION.value
            or _record_value(lineage, "chunk_status") != Status.ACTIVE.value
            or _record_value(lineage, "revision_status") != Status.ACTIVE.value
            or _record_value(lineage, "evidence_edge_count") != 1
            or _record_value(lineage, "expected_evidence_edge_count") != 1
            or _record_value(lineage, "chunk_edge_count") != 1
            or _record_value(lineage, "expected_chunk_edge_count") != 1
        ):
            raise GraphWriteError("relation assertion Evidence source-grounded lineage is invalid")
        if assertion.egress_policy is EgressPolicy.SHAREABLE and _record_value(
            evidence, "egress_policy"
        ) != EgressPolicy.SHAREABLE.value:
            raise GraphWriteError("shareable relation assertion requires shareable Evidence")
