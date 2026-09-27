"""Safe, owner-local provenance projection for one current semantic edge."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping, Protocol, Sequence

from dots.founder_graph import Asset, Idea, NodeType, Status
from dots.founder_graph_lifecycle_resolver import decode_asset_lifecycle_record, lifecycle_reference_aliases
from dots.founder_graph_neo4j_idea import IdeaDecodeError, decode_persisted_idea
from dots.idea_brief import IdeaBriefVersion, SECTION_TITLES


class GraphProvenanceNotFound(LookupError):
    """The requested assertion is absent or is not current for this owner."""


class GraphProvenanceStore(Protocol):
    def fetch(self, node_id: str, *, owner_id: str) -> Any: ...
    def has_successor(self, assertion_id: str, *, owner_id: str) -> bool: ...
    def has_idea_successor(self, idea_id: str, *, owner_id: str) -> bool: ...
    def resolve_lifecycle_references(
        self, references: Sequence[tuple[str, str]], *, owner_id: str,
    ) -> Mapping[str, str | None]: ...
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
    endpoint_references = (
        (source_id, fields.get("source_kind")),
        (target_id, fields.get("target_kind")),
    )
    resolver = getattr(store, "resolve_lifecycle_references", None)
    resolved_endpoints = resolver(endpoint_references, owner_id=owner) if callable(resolver) else {}
    if not isinstance(resolved_endpoints, Mapping):
        raise GraphProvenanceNotFound("provenance was not found")
    for endpoint_id, expected_kind in endpoint_references:
        if callable(resolver):
            resolved_id = resolved_endpoints.get(
                endpoint_id, endpoint_id if expected_kind not in {"idea", "asset"} else None,
            )
            if not _string(resolved_id):
                raise GraphProvenanceNotFound("provenance was not found")
        else:
            resolved_id = endpoint_id
            successor_check = getattr(
                store,
                "has_idea_successor" if expected_kind == "idea" else "has_asset_successor",
                None,
            )
            if callable(successor_check) and successor_check(endpoint_id, owner_id=owner):
                raise GraphProvenanceNotFound("provenance was not found")
        endpoint = store.fetch(resolved_id, owner_id=owner)
        if (
            endpoint.id != resolved_id or endpoint.owner_id != owner
            or endpoint.node_type in {"relation_assertion", "evidence"}
            or endpoint.node_type != expected_kind
            or (endpoint.status in _NON_CURRENT if _string(endpoint.status) else False)
        ):
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
    _LIFECYCLE_RECORDS = (
        "MATCH (candidate) WHERE candidate.owner_id = $owner_id "
        "AND candidate.node_type IN $node_types "
        "RETURN candidate.id AS id, candidate.node_type AS node_type, candidate.revision AS revision, "
        "candidate.supersedes_id AS supersedes_id, candidate.status AS status, candidate.payload_json AS payload_json "
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

    def resolve_lifecycle_references(
        self, references: Sequence[tuple[str, str]], *, owner_id: str,
    ) -> Mapping[str, str | None]:
        """Resolve Idea/Asset lifecycle aliases in one bounded owner-scoped read."""
        requested = {identity: kind for identity, kind in references}
        if owner_id != self.owner_id:
            return {identity: None for identity in requested}
        revisioned_kinds = {kind for kind in requested.values() if kind in {"idea", "asset"}}
        if not revisioned_kinds:
            return {identity: identity for identity in requested}
        import json
        with self.driver.session(database=self.database) as session:
            rows = tuple(session.run(
                self._LIFECYCLE_RECORDS,
                owner_id=owner_id,
                node_types=sorted(revisioned_kinds),
            ))
        if len(rows) > 1000:
            return {identity: None for identity in requested}

        # Index lineage links using both scalar and payload identities. A bad
        # unrelated legacy row must not poison a valid reference, but a row
        # attached through either representation remains in that reference's
        # validation closure and fails closed if its two representations differ.
        descriptors: list[dict[str, Any]] = []
        rows_by_reference: dict[str, set[int]] = {}
        duplicate_ids: set[str] = set()
        seen_ids: set[str] = set()
        for index, row in enumerate(rows):
            try:
                identity = row["id"]
                node_type = row["node_type"]
                revision = row["revision"]
                scalar_parent = row["supersedes_id"]
                status = row["status"]
                payload_json = row["payload_json"]
            except (KeyError, TypeError):
                identity = node_type = revision = scalar_parent = status = payload_json = None
            if isinstance(identity, str):
                if identity in seen_ids:
                    duplicate_ids.add(identity)
                seen_ids.add(identity)
            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else None
            except (TypeError, ValueError):
                payload = None
            payload_identity = payload.get("id") if isinstance(payload, dict) else None
            payload_parent = payload.get("supersedes_id") if isinstance(payload, dict) else None
            references_in_row = {
                value for value in (identity, payload_identity, scalar_parent, payload_parent)
                if isinstance(value, str) and value
            }
            descriptor = {
                "identity": identity,
                "node_type": node_type,
                "revision": revision,
                "scalar_parent": scalar_parent,
                "status": status,
                "payload_json": payload_json,
                "payload": payload,
                "payload_identity": payload_identity,
                "payload_parent": payload_parent,
                "references": references_in_row,
            }
            descriptors.append(descriptor)
            for reference in references_in_row:
                rows_by_reference.setdefault(reference, set()).add(index)

        closures: dict[str, set[int]] = {}
        for identity, kind in requested.items():
            if kind not in {NodeType.IDEA.value, NodeType.ASSET.value}:
                continue
            closure: set[int] = set()
            pending = [identity]
            reached: set[str] = set()
            while pending:
                reference = pending.pop()
                if reference in reached:
                    continue
                reached.add(reference)
                for index in rows_by_reference.get(reference, ()):
                    if index in closure:
                        continue
                    closure.add(index)
                    pending.extend(descriptors[index]["references"] - reached)
            closures[identity] = closure

        related_indices = set().union(*closures.values()) if closures else set()
        related_duplicate_ids = duplicate_ids.intersection(
            descriptors[index]["identity"] for index in related_indices
            if isinstance(descriptors[index]["identity"], str)
        )
        records: list[Idea | Asset] = []
        invalid_references: set[str] = set()
        for index in related_indices:
            descriptor = descriptors[index]
            identity = descriptor["identity"]
            node_type = descriptor["node_type"]
            revision = descriptor["revision"]
            scalar_parent = descriptor["scalar_parent"]
            status = descriptor["status"]
            payload_json = descriptor["payload_json"]
            payload = descriptor["payload"]
            affected = {reference for reference, closure in closures.items() if index in closure}
            if (
                not isinstance(identity, str) or not isinstance(payload, dict)
                or descriptor["payload_identity"] != identity
                or payload.get("owner_id") != owner_id
                or scalar_parent != descriptor["payload_parent"]
                or (scalar_parent is not None and not isinstance(scalar_parent, str))
                or identity in related_duplicate_ids
            ):
                invalid_references.update(affected)
                continue
            try:
                if node_type == NodeType.IDEA.value:
                    record = decode_persisted_idea(
                        {
                            "id": identity, "owner_id": owner_id, "node_type": node_type,
                            "revision": revision, "payload_json": payload_json,
                        },
                        owner_id=owner_id, expected_id=identity,
                    )
                elif node_type == NodeType.ASSET.value:
                    legacy_initial_asset = (
                        "revision" not in payload and "supersedes_id" not in payload
                        and type(revision) is int and revision in {0, 1} and scalar_parent is None
                    )
                    record = decode_asset_lifecycle_record(
                        payload, owner_id=owner_id, expected_id=identity, expected_revision=revision,
                        expected_supersedes_id=scalar_parent, allow_legacy_initial_row=True,
                    )
                    if record.node_type.value != node_type:
                        raise ValueError("persisted Asset node type does not match its row")
                else:
                    raise ValueError("persisted lifecycle row has an unsupported node type")
                expected_record_revision = 1 if node_type == NodeType.ASSET.value and legacy_initial_asset else revision
                if record.revision != expected_record_revision or record.status.value != status:
                    raise ValueError("persisted lifecycle metadata does not match its row")
            except (KeyError, TypeError, ValueError, IdeaDecodeError):
                invalid_references.update(affected)
                continue
            records.append(record)

        aliases = lifecycle_reference_aliases(records)
        by_id = {record.id: record for record in records}
        superseded_ids = {record.supersedes_id for record in records if record.supersedes_id is not None}
        resolved: dict[str, str | None] = {}
        for identity, expected_kind in requested.items():
            if expected_kind not in {NodeType.IDEA.value, NodeType.ASSET.value}:
                resolved[identity] = identity
                continue
            if identity in invalid_references:
                resolved[identity] = None
                continue
            record = by_id.get(identity)
            record_kind_matches = record is not None and record.node_type.value == expected_kind
            if identity in aliases and record_kind_matches:
                resolved[identity] = aliases[identity]
            elif record_kind_matches and identity not in superseded_ids and record.status.value not in {
                Status.ARCHIVED.value, Status.SUPERSEDED.value,
            }:
                resolved[identity] = identity
            else:
                resolved[identity] = None
        return resolved

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
