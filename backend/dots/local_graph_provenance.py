"""Safe, owner-local provenance projection for one current semantic edge."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Protocol

from dots.idea_brief import IdeaBriefVersion, SECTION_TITLES


class GraphProvenanceNotFound(LookupError):
    """The requested assertion is absent or is not current for this owner."""


class GraphProvenanceStore(Protocol):
    def fetch(self, node_id: str, *, owner_id: str) -> Any: ...
    def has_successor(self, assertion_id: str, *, owner_id: str) -> bool: ...
    def has_idea_successor(self, idea_id: str, *, owner_id: str) -> bool: ...
    def get_brief(self, brief_id: str, *, owner_id: str) -> IdeaBriefVersion | None: ...
    def get_latest_brief(self, root_id: str, *, owner_id: str) -> IdeaBriefVersion | None: ...


_ACTIVE = frozenset({"proposed", "inferred", "confirmed"})
_NON_CURRENT = frozenset({"deleted", "archived", "superseded", "retracted", "expired", "cancelled", "revoked"})
_SAFE_EVIDENCE_FIELDS = ("id", "polarity", "confidence", "status")


def read_local_graph_provenance(
    store: GraphProvenanceStore,
    *,
    assertion_id: str,
    owner_id: str,
    storage_status: str = "running",
    at: datetime | None = None,
) -> dict[str, Any]:
    """Validate current ownership/lineage, then return an allowlisted projection."""
    identity, owner = _identifier(assertion_id, "assertion_id"), _identifier(owner_id, "owner_id")
    if storage_status == "stopped":
        return {"status": "stopped", "assertion_id": identity, "section": None, "evidence": []}
    if storage_status != "running":
        raise RuntimeError("local graph storage is unavailable")
    assertion = store.fetch(identity, owner_id=owner)
    if assertion.id != identity or assertion.owner_id != owner or assertion.node_type != "relation_assertion":
        raise GraphProvenanceNotFound("provenance was not found")
    if store.has_successor(identity, owner_id=owner):
        raise GraphProvenanceNotFound("provenance was not found")

    fields = assertion.fields
    status = fields.get("status")
    if assertion.status not in _ACTIVE or status not in _ACTIVE:
        raise GraphProvenanceNotFound("provenance was not found")
    now = _utc(at or datetime.now(timezone.utc))
    valid_from = _timestamp(fields.get("valid_from"))
    expires_at = fields.get("expires_at")
    if valid_from is None or valid_from > now:
        raise GraphProvenanceNotFound("provenance was not found")
    if expires_at is not None and (_timestamp(expires_at) is None or _timestamp(expires_at) <= now):
        raise GraphProvenanceNotFound("provenance was not found")

    source_id, target_id = fields.get("source_id"), fields.get("target_id")
    if not _string(source_id) or not _string(target_id) or source_id == target_id:
        raise GraphProvenanceNotFound("provenance was not found")
    raw_ids = fields.get("evidence_ids", ())
    if not isinstance(raw_ids, (tuple, list)) or any(not _string(item) for item in raw_ids):
        raise GraphProvenanceNotFound("provenance was not found")
    for endpoint_id in (source_id, target_id):
        endpoint = store.fetch(endpoint_id, owner_id=owner)
        expected_kind = fields.get("source_kind") if endpoint_id == source_id else fields.get("target_kind")
        if (
            endpoint.id != endpoint_id or endpoint.owner_id != owner
            or endpoint.node_type in {"relation_assertion", "evidence"}
            or endpoint.node_type != expected_kind
            or (endpoint.status in _NON_CURRENT if _string(endpoint.status) else False)
        ):
            raise GraphProvenanceNotFound("provenance was not found")
        if endpoint.node_type == "idea" and store.has_idea_successor(endpoint_id, owner_id=owner):
            raise GraphProvenanceNotFound("provenance was not found")

    section = None
    brief_id = fields.get("based_on_brief_id")
    section_index = fields.get("based_on_brief_section_index")
    if (brief_id is None) != (section_index is None):
        raise GraphProvenanceNotFound("provenance was not found")
    if brief_id is not None:
        if not _string(brief_id) or type(section_index) is not int or not 0 <= section_index < len(SECTION_TITLES):
            raise GraphProvenanceNotFound("provenance was not found")
        brief = store.get_brief(brief_id, owner_id=owner)
        if (
            brief is None or brief.id != brief_id or brief.owner_id != owner
            or brief.based_on_idea_id not in {source_id, target_id}
        ):
            raise GraphProvenanceNotFound("provenance was not found")
        latest = store.get_latest_brief(brief.idea_lineage_root_id, owner_id=owner)
        if latest is None or latest.id != brief.id:
            raise GraphProvenanceNotFound("provenance was not found")
        selected = brief.sections[section_index]
        if selected.index != section_index or not selected.content.strip():
            raise GraphProvenanceNotFound("provenance was not found")
        if not set(raw_ids).issubset(selected.evidence_ids):
            raise GraphProvenanceNotFound("provenance was not found")
        section = {
            "brief_id": brief.id, "revision": brief.revision,
            "idea_id": brief.based_on_idea_id, "section_index": section_index,
            "title": SECTION_TITLES[section_index], "content": selected.content,
        }

    evidence: list[dict[str, Any]] = []
    for evidence_id in sorted(set(raw_ids)):
        try:
            node = store.fetch(evidence_id, owner_id=owner)
        except GraphProvenanceNotFound:
            continue
        values = node.fields
        if (
            node.id != evidence_id or node.owner_id != owner or node.node_type != "evidence"
            or values.get("egress_policy") != "shareable"
            or node.status != "active"
            or values.get("status") != "active"
        ):
            continue
        polarity = values.get("polarity")
        confidence = values.get("confidence")
        if polarity not in {"supports", "contradicts", "neutral"}:
            continue
        if (
            not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
            or not math.isfinite(confidence) or not 0 <= confidence <= 1
        ):
            continue
        evidence.append({
            key: node.id if key == "id" else node.status if key == "status" else values.get(key)
            for key in _SAFE_EVIDENCE_FIELDS
        })
    return {"status": "ready", "assertion_id": identity, "section": section, "evidence": evidence}


class Neo4jGraphProvenanceStore:
    """Adapter using the existing allowlisted graph reader and exact brief store."""

    _SUCCESSOR = (
        "MATCH (old:RelationAssertion {id: $assertion_id, owner_id: $owner_id}) "
        "RETURN EXISTS { MATCH (successor:RelationAssertion {owner_id: $owner_id})-[:SUPERSEDES]->(old) } AS value"
    )
    _IDEA_SUCCESSORS = (
        "MATCH (candidate:Idea {owner_id: $owner_id}) "
        "RETURN candidate.id AS id, candidate.payload_json AS payload_json "
        "ORDER BY candidate.id LIMIT 1001"
    )

    def __init__(self, driver: Any, *, owner_id: str, database: str = "neo4j") -> None:
        self.driver, self.owner_id, self.database = driver, _identifier(owner_id, "owner_id"), database

    def fetch(self, node_id: str, *, owner_id: str):
        if owner_id != self.owner_id:
            raise GraphProvenanceNotFound("provenance was not found")
        from dots.founder_graph_neo4j import Neo4jGraphGateway
        from dots.founder_graph_neo4j_read import Neo4jGraphReadService
        from dots.founder_graph_read import GraphReadNotFoundError
        try:
            return Neo4jGraphReadService(
                Neo4jGraphGateway(self.driver, self.owner_id, database=self.database),
            ).fetch(node_id, owner_id=self.owner_id)
        except GraphReadNotFoundError as error:
            raise GraphProvenanceNotFound("provenance was not found") from error

    def has_successor(self, assertion_id: str, *, owner_id: str) -> bool:
        if owner_id != self.owner_id:
            raise GraphProvenanceNotFound("provenance was not found")
        with self.driver.session(database=self.database) as session:
            row = session.run(self._SUCCESSOR, assertion_id=assertion_id, owner_id=owner_id).single()
        return row is None or row["value"] is not False

    def has_idea_successor(self, idea_id: str, *, owner_id: str) -> bool:
        if owner_id != self.owner_id:
            raise GraphProvenanceNotFound("provenance was not found")
        import json
        with self.driver.session(database=self.database) as session:
            rows = tuple(session.run(self._IDEA_SUCCESSORS, owner_id=owner_id))
        # A capped scan or malformed same-owner payload is ambiguous. Hide the
        # provenance rather than risk treating an old Idea as current.
        if len(rows) > 1000:
            return True
        try:
            for row in rows:
                payload = json.loads(row["payload_json"])
                if not isinstance(payload, dict):
                    return True
                if payload.get("supersedes_id") == idea_id:
                    return True
        except (KeyError, TypeError, ValueError):
            return True
        return False

    def get_brief(self, brief_id: str, *, owner_id: str) -> IdeaBriefVersion | None:
        if owner_id != self.owner_id:
            raise GraphProvenanceNotFound("provenance was not found")
        from dots.idea_brief_neo4j import Neo4jIdeaBriefStore
        return Neo4jIdeaBriefStore(self.driver, owner_id=self.owner_id, database=self.database).get(brief_id)

    def get_latest_brief(self, root_id: str, *, owner_id: str) -> IdeaBriefVersion | None:
        if owner_id != self.owner_id:
            raise GraphProvenanceNotFound("provenance was not found")
        from dots.idea_brief_neo4j import Neo4jIdeaBriefStore
        return Neo4jIdeaBriefStore(self.driver, owner_id=self.owner_id, database=self.database).latest(root_id)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value) if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed) if parsed.tzinfo is not None else None
