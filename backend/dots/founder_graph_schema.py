"""Neo4j schema plan and offline import validation for Founder Graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .founder_graph import NodeType, Relationship, _ALLOWED_RELATION_ENDPOINTS


SCHEMA_VERSION = 2
SCHEMA_NAME = "dots-founder-graph"


@dataclass(frozen=True, slots=True)
class SchemaMigration:
    version: int
    queries: tuple[str, ...]


_V1_LABELS = (
    "OwnerProfile",
    "Idea",
    "Asset",
    "Person",
    "Organization",
    "Source",
    "ResearchMaterial",
    "SourceRevision",
    "Evidence",
    "Claim",
    "ResearchCampaign",
    "ResearchRun",
    "ReportVersion",
    "ReportSection",
    "Decision",
    "Experiment",
    "InstructionArtifact",
)
_V2_LABELS = ("EntityRevision", "RelationAssertion", "ContentChunk", "Facet")
_LABELS = _V1_LABELS + _V2_LABELS


def _create_queries(labels: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        query
        for label in labels
        for query in (
            f"CREATE CONSTRAINT dots_{label.lower()}_id IF NOT EXISTS FOR (node:{label}) REQUIRE node.id IS UNIQUE",
            f"CREATE INDEX dots_{label.lower()}_owner IF NOT EXISTS FOR (node:{label}) ON (node.owner_id)",
        )
    )


def _search_queries(labels: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        f"CREATE INDEX dots_{label.lower()}_search IF NOT EXISTS FOR (node:{label}) ON (node.search_text)"
        for label in labels
    )


def _drop_queries(labels: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        query
        for label in reversed(labels)
        for query in (
            f"DROP INDEX dots_{label.lower()}_search IF EXISTS",
            f"DROP INDEX dots_{label.lower()}_owner IF EXISTS",
            f"DROP CONSTRAINT dots_{label.lower()}_id IF EXISTS",
        )
    )


_MIGRATIONS = (
    SchemaMigration(
        version=1,
        queries=_create_queries(_V1_LABELS)
        + _search_queries(("Idea", "Asset", "Person", "Organization", "ResearchMaterial", "Claim", "Evidence"))
        + (
            "CREATE CONSTRAINT dots_foundergraphaudit_id IF NOT EXISTS FOR (node:FounderGraphAudit) REQUIRE node.id IS UNIQUE",
            "CREATE INDEX dots_foundergraphaudit_idempotency IF NOT EXISTS FOR (node:FounderGraphAudit) ON (node.owner_id, node.idempotency_key)",
            "CREATE INDEX dots_foundergraphhistory_target IF NOT EXISTS FOR (node:FounderGraphHistory) ON (node.target_id, node.revision)",
        ),
    ),
    SchemaMigration(
        version=2,
        queries=_create_queries(_V2_LABELS) + _search_queries(_V2_LABELS),
    ),
)


def migration_plan(current_version: int = 0, target_version: int = SCHEMA_VERSION) -> tuple[SchemaMigration, ...]:
    if not isinstance(current_version, int) or isinstance(current_version, bool) or current_version < 0:
        raise ValueError("current_version must be a non-negative integer")
    if not isinstance(target_version, int) or isinstance(target_version, bool) or target_version < current_version:
        raise ValueError("target_version must be an integer not below current_version")
    if target_version > SCHEMA_VERSION:
        raise ValueError("target_version is newer than this application")
    return tuple(migration for migration in _MIGRATIONS if current_version < migration.version <= target_version)


def migration_queries(current_version: int = 0, target_version: int = SCHEMA_VERSION) -> tuple[str, ...]:
    return tuple(query for migration in migration_plan(current_version, target_version) for query in migration.queries)


def rollback_queries(current_version: int = SCHEMA_VERSION, target_version: int = 1) -> tuple[str, ...]:
    """Return non-destructive schema rollback queries for v2 and later.

    Rollback removes only v2 constraints and indexes. It never deletes graph
    nodes, relationships, payloads, audit records, or history.
    """

    if not isinstance(current_version, int) or isinstance(current_version, bool) or current_version < 0:
        raise ValueError("current_version must be a non-negative integer")
    if not isinstance(target_version, int) or isinstance(target_version, bool) or target_version < 0:
        raise ValueError("target_version must be a non-negative integer")
    if target_version > current_version:
        raise ValueError("target_version must not exceed current_version for rollback")
    if current_version > SCHEMA_VERSION:
        raise ValueError("current_version is newer than this application")
    if target_version < 1:
        raise ValueError("rollback below schema v1 is not supported")
    return _drop_queries(_V2_LABELS) if current_version >= 2 and target_version < 2 else ()


def validate_import_batch(nodes: Iterable[Any], relationships: Iterable[Relationship]) -> dict[str, int]:
    """Fail closed on duplicate ids, unknown nodes, or invalid endpoints."""

    node_values = tuple(nodes)
    relation_values = tuple(relationships)
    by_id: dict[str, Any] = {}
    for node in node_values:
        node_id = getattr(node, "id", None)
        owner_id = getattr(node, "owner_id", None)
        node_type = getattr(node, "node_type", None)
        if not isinstance(node_id, str) or not node_id or not isinstance(owner_id, str) or not owner_id:
            raise ValueError("every graph node requires id and owner_id")
        if not isinstance(node_type, NodeType):
            raise ValueError("graph node type is not in the allowlist")
        if node_id in by_id:
            raise ValueError(f"duplicate graph node id: {node_id}")
        by_id[node_id] = node
    for relation in relation_values:
        if not isinstance(relation, Relationship):
            raise ValueError("graph batch relationships must be Relationship values")
        source = by_id.get(relation.source_id)
        target = by_id.get(relation.target_id)
        if source is None or target is None:
            raise ValueError("relationship endpoint is missing from the graph batch")
        if relation.owner_id != getattr(source, "owner_id", None) or relation.owner_id != getattr(target, "owner_id", None):
            raise ValueError("relationship endpoints must share the relationship owner")
        pair = (source.node_type, target.node_type)
        if pair not in _ALLOWED_RELATION_ENDPOINTS[relation.relation]:
            raise ValueError("relationship endpoint types are not allowlisted")
    return {"nodes": len(node_values), "relationships": len(relation_values)}


def schema_manifest() -> dict[str, object]:
    return {
        "name": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "node_labels": list(_LABELS),
        "migration_count": len(_MIGRATIONS),
        "query_count": len(migration_queries()),
        "rollback_query_count": len(rollback_queries()),
    }
