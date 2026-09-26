"""Persistent owner-scoped write adapter for the local Founder Graph.

The adapter keeps Cypher and transaction handling in ``Neo4jGraphGateway``.
It supplies the small read-back contract needed by the MCP write surface while
avoiding a generic, unbounded dataclass hydrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
import json
from typing import Any, Mapping

from .founder_graph import (
    Claim,
    EgressPolicy,
    Idea,
    NodeType,
    Provenance,
    ProvenanceOrigin,
    RelationAssertion,
    ResearchRun,
    Source,
    SourceRevision,
)
from .founder_graph_neo4j import Neo4jGraphGateway
from .idea_brief import IdeaBriefVersion
from .founder_graph_write import (
    GraphWriteError,
    GraphWriteNotFoundError,
    GraphWritePort,
    RevisionConflictError,
    SourceChainRepairPlan,
    WriteReceipt,
)


@dataclass(frozen=True, slots=True)
class PersistedNodeReference:
    """Minimum owner-bound node projection required to create a relationship."""

    id: str
    owner_id: str
    node_type: NodeType
    revision: int
    fields: Mapping[str, Any]


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GraphWriteError(f"persisted {field_name} is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GraphWriteError(f"persisted {field_name} is invalid") from error


def _provenance(value: Any) -> Provenance:
    if not isinstance(value, Mapping):
        raise GraphWriteError("persisted provenance is invalid")
    try:
        return Provenance(
            actor=value.get("actor", "system"),
            operation=value.get("operation", "create"),
            origin=value.get("origin", ProvenanceOrigin.MANUAL.value),
            target_id=value.get("target_id"),
            source_id=value.get("source_id"),
            model_snapshot=value.get("model_snapshot"),
            prompt_version=value.get("prompt_version"),
            rule_version=value.get("rule_version"),
            occurred_at=_timestamp(value.get("occurred_at"), "provenance.occurred_at"),
            idempotency_key=value.get("idempotency_key"),
        )
    except (TypeError, ValueError) as error:
        raise GraphWriteError("persisted provenance is invalid") from error


def _payload(record: Mapping[str, Any], owner_id: str) -> tuple[NodeType, dict[str, Any]]:
    if record.get("owner_id") != owner_id:
        raise GraphWriteNotFoundError("node does not belong to the local owner")
    raw_type = record.get("node_type")
    try:
        node_type = raw_type if isinstance(raw_type, NodeType) else NodeType(raw_type)
    except (TypeError, ValueError) as error:
        raise GraphWriteError("persisted node type is not in the Founder Graph allowlist") from error
    try:
        payload = json.loads(record["payload_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise GraphWriteError("persisted node payload is invalid JSON") from error
    if not isinstance(payload, dict):
        raise GraphWriteError("persisted node payload must be an object")
    if payload.get("id") != record.get("id") or payload.get("owner_id") != owner_id:
        raise GraphWriteError("persisted node identity does not match its record")
    return node_type, payload


def _hydrate_correction(node_type: NodeType, payload: Mapping[str, Any]) -> Idea | Claim | None:
    """Hydrate only correction-capable aggregates; return None for endpoints."""

    common = {
        "owner_id": payload.get("owner_id"),
        "id": payload.get("id"),
        "status": payload.get("status"),
        "egress_policy": payload.get("egress_policy", EgressPolicy.LOCAL_ONLY.value),
        "created_at": _timestamp(payload.get("created_at"), "created_at"),
        "provenance": _provenance(payload.get("provenance")),
    }
    if node_type is NodeType.IDEA:
        return Idea(
            title=payload.get("title", ""),
            summary=payload.get("summary", ""),
            description=payload.get("description", ""),
            source_text=payload.get("source_text", ""),
            tags=payload.get("tags", ()),
            revision=payload.get("revision", 0),
            supersedes_id=payload.get("supersedes_id"),
            updated_at=_timestamp(payload["updated_at"], "updated_at") if payload.get("updated_at") else None,
            **common,
        )
    if node_type is NodeType.CLAIM:
        return Claim(
            text=payload.get("text", ""),
            claim_type=payload.get("claim_type", "fact"),
            classification=payload.get("classification"),
            confidence=payload.get("confidence", 0.0),
            evidence_ids=payload.get("evidence_ids", ()),
            revision=payload.get("revision", 0),
            supersedes_id=payload.get("supersedes_id"),
            **common,
        )
    return None


class Neo4jGraphWriteService(GraphWritePort):
    """Write port backed entirely by one owner-bound Neo4j gateway."""

    def __init__(self, gateway: Neo4jGraphGateway) -> None:
        if not isinstance(gateway, Neo4jGraphGateway):
            raise GraphWriteError("a Neo4jGraphGateway is required")
        self.gateway = gateway

    @property
    def owner_id(self) -> str:
        return self.gateway.owner_id

    def put_node(self, node: Any, *, idempotency_key: str, expected_revision: int | None = None, operation: str = "put_node", actor: str = "local-owner") -> WriteReceipt:
        return self.gateway.put_node(
            node,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            operation=operation,
            actor=actor,
        )

    def capture_idea(
        self,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        return self.gateway.capture_idea(
            idea,
            source,
            source_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def capture_source(self, source: Source, source_revision: SourceRevision, *, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        return self.gateway.capture_source(source, source_revision, idempotency_key=idempotency_key, actor=actor)

    def preview_source_chain_repair(self) -> SourceChainRepairPlan:
        return self.gateway.preview_source_chain_repair()

    def apply_source_chain_repair(self, *, actor: str = "local-owner") -> SourceChainRepairPlan:
        return self.gateway.apply_source_chain_repair(actor=actor)

    def record_research_run(
        self,
        run: ResearchRun,
        *,
        expected_campaign_revision: int,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        return self.gateway.record_research_run(
            run,
            expected_campaign_revision=expected_campaign_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def link_entities(self, relationship: Any, *, idempotency_key: str, expected_revision: int | None = None, actor: str = "local-owner") -> WriteReceipt:
        if expected_revision not in (None, 0):
            raise RevisionConflictError("relationships do not have mutable revisions")
        return self.gateway.link_entities(relationship, idempotency_key=idempotency_key, actor=actor)

    def save_relation_assertion(
        self,
        assertion: RelationAssertion,
        *,
        expected_family_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        return self.gateway.save_relation_assertion(
            assertion,
            expected_family_revision=expected_family_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def confirm_person_merge(self, assertion: RelationAssertion, *, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        """Fail closed until the persistent adapter can archive and assert atomically."""

        raise GraphWriteError("confirmed person merge is unavailable until Neo4j supports atomic archive and RelationAssertion writes")

    def record_correction(self, previous_id: str, replacement: Any, *, idempotency_key: str, expected_revision: int | None = None, actor: str = "local-owner") -> WriteReceipt:
        previous = self.get_node(previous_id)
        if previous is None:
            raise GraphWriteNotFoundError(f"previous node does not exist: {previous_id}")
        if getattr(replacement, "supersedes_id", None) != previous_id:
            raise GraphWriteError("correction must supersede the previous node")
        if expected_revision is not None and getattr(previous, "revision", 0) != expected_revision:
            raise RevisionConflictError("expected previous revision does not match current revision")
        return self.gateway.put_node(
            replacement,
            idempotency_key=idempotency_key,
            expected_revision=0,
            operation="record_correction",
            actor=actor,
        )

    def get_node(self, node_id: str) -> Any | None:
        record = self.gateway.fetch_node_record(node_id)
        if record is None:
            return None
        node_type, payload = _payload(record, self.owner_id)
        hydrated = _hydrate_correction(node_type, payload) if node_type in {NodeType.IDEA, NodeType.CLAIM} else None
        if hydrated is not None:
            return hydrated
        if node_type is NodeType.RELATION_ASSERTION:
            return self.gateway._decode_relation_assertion_record(record)
        revision = record.get("revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise GraphWriteError("persisted node revision is invalid")
        return PersistedNodeReference(
            id=str(record["id"]),
            owner_id=self.owner_id,
            node_type=node_type,
            revision=revision,
            fields=MappingProxyType(dict(payload)),
        )


class Neo4jIdeaBriefStore:
    """Concrete-only owner-bound persistence for immutable IdeaBrief values."""

    def __init__(self, gateway: Neo4jGraphGateway) -> None:
        if not isinstance(gateway, Neo4jGraphGateway):
            raise GraphWriteError("a Neo4jGraphGateway is required")
        self.gateway = gateway

    def save(self, brief: IdeaBriefVersion, *, expected_latest_revision: int | None,
             idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        return self.gateway.save_idea_brief(
            brief, expected_latest_revision=expected_latest_revision,
            idempotency_key=idempotency_key, actor=actor,
        )

    def get(self, brief_id: str) -> IdeaBriefVersion | None:
        return self.gateway.get_idea_brief(brief_id)

    def get_latest(self, idea_lineage_root_id: str) -> IdeaBriefVersion | None:
        return self.gateway.get_latest_idea_brief(idea_lineage_root_id)
__all__ = ["Neo4jGraphWriteService", "Neo4jIdeaBriefStore", "PersistedNodeReference"]
