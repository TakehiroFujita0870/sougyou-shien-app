"""Deterministic owner-scoped graph + full-text read contract."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .founder_graph import (
    Evidence,
    Idea,
    NodeType,
    RelationAssertion,
    RelationAssertionEdgeType,
    Relationship,
    RelationshipStatus,
    Status,
    DomainValidationError,
    relation_assertion_structural_edges,
)
from .founder_graph_write import GraphReadSnapshot, InMemoryGraphWriteService


class GraphReadError(Exception):
    """Base class for recoverable local read failures."""


class GraphReadUnavailableError(GraphReadError):
    """The local graph service is stopped or cannot accept a read."""


class GraphReadNotFoundError(GraphReadError):
    """The requested node is absent or belongs to another owner."""


class GraphReadTimeoutError(GraphReadError):
    """The read exceeded its bounded local time budget."""


@dataclass(frozen=True, slots=True)
class NodeView:
    id: str
    node_type: str
    owner_id: str
    title: str
    snippet: str
    status: str | None
    revision: int
    fields: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RelationPathStep:
    """One traversed edge, retaining its stored direction and optional identity."""

    from_id: str
    to_id: str
    source_id: str
    predicate: str
    target_id: str
    traversal_direction: str
    evidence_ids: tuple[str, ...] = ()
    status: str | None = None
    confidence: float | None = None
    valid_from: str | None = None
    expires_at: str | None = None
    relation_assertion_id: str | None = None
    based_on_brief_id: str | None = None
    based_on_brief_section_index: int | None = None

    @classmethod
    def from_relationship(
        cls,
        relationship: Relationship,
        *,
        from_id: str,
        to_id: str,
    ) -> "RelationPathStep":
        """Describe a legacy Relationship without inventing an assertion ID."""

        status = relationship.status.value if isinstance(relationship.status, Enum) else relationship.status
        return cls(
            from_id=from_id,
            to_id=to_id,
            source_id=relationship.source_id,
            predicate=relationship.relation.value,
            target_id=relationship.target_id,
            traversal_direction="outgoing" if from_id == relationship.source_id else "incoming",
            evidence_ids=tuple(relationship.evidence_ids),
            status=status,
            confidence=relationship.confidence,
            valid_from=None,
            expires_at=relationship.expires_at.isoformat() if relationship.expires_at is not None else None,
            relation_assertion_id=None,
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    node: NodeView
    score: float
    path: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    relation_path: tuple[RelationPathStep, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchPage:
    hits: tuple[SearchHit, ...]
    next_cursor: str | None


class GraphReadPort(Protocol):
    """The read-only service contract consumed by the MCP composition layer."""

    @property
    def owner_id(self) -> str:
        """The single local owner this service is allowed to read."""

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        """Return an owner-scoped search page."""

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        """Fetch one owner-scoped node view."""


_NON_CURRENT = frozenset({"retracted", "superseded", "expired", "cancelled", "revoked", "archived"})
_FIELD_ALLOWLIST: dict[NodeType, tuple[str, ...]] = {
    NodeType.OWNER_PROFILE: ("display_name", "status", "egress_policy"),
    NodeType.IDEA: ("title", "summary", "description", "source_text", "tags", "status", "egress_policy", "revision", "supersedes_id"),
    NodeType.ASSET: ("name", "kind", "description", "status", "egress_policy"),
    NodeType.PERSON: ("name", "description", "contact", "private_notes", "status", "egress_policy"),
    NodeType.ORGANIZATION: ("name", "description", "status", "egress_policy"),
    NodeType.SOURCE: ("title", "kind", "locator", "current_revision_id", "revision", "status", "egress_policy"),
    NodeType.RESEARCH_MATERIAL: ("title", "kind", "content", "locator", "content_hash", "status", "egress_policy"),
    NodeType.SOURCE_REVISION: ("source_id", "revision", "supersedes_id", "content", "locator", "content_hash", "retrieved_at", "egress_policy", "status"),
    NodeType.CLAIM: ("text", "claim_type", "confidence", "evidence_ids", "status", "revision", "supersedes_id", "egress_policy"),
    NodeType.EVIDENCE: ("material_id", "claim_id", "source_revision_id", "excerpt", "locator", "polarity", "confidence", "content_hash", "status", "egress_policy"),
    NodeType.RESEARCH_CAMPAIGN: ("purpose", "scope", "questions", "target_idea_id", "allowed_categories", "external_sources", "trial_budget", "expires_at", "status", "authorized", "aggregate_revision", "egress_policy"),
    NodeType.RESEARCH_RUN: ("campaign_id", "input_snapshot", "model_snapshot", "sources", "evidence_ids", "results", "failures", "status", "authorization_revision", "parent_run_id", "supersedes_id", "egress_policy"),
    NodeType.REPORT_VERSION: ("sections", "parent_id", "supersedes_id", "change_reason", "financial_formulas", "decision_criteria", "run_ids", "evidence_ids", "status", "egress_policy"),
    NodeType.REPORT_SECTION: ("id", "content", "facts", "ai_inferences", "unconfirmed", "owner_decisions", "claim_ids", "evidence_ids", "egress_policy"),
    NodeType.DECISION: ("text", "claim_ids", "report_ids", "experiment_ids", "status", "egress_policy"),
    NodeType.EXPERIMENT: ("name", "success_criteria", "stop_criteria", "status", "egress_policy"),
    NodeType.INSTRUCTION_ARTIFACT: ("path", "scope", "content_hash", "status", "egress_policy"),
    NodeType.ENTITY_REVISION: (
        "entity_id",
        "entity_type",
        "revision",
        "payload_schema",
        "public_payload",
        "content_hash",
        "created_at",
        "provenance_id",
        "status",
        "egress_policy",
    ),
    NodeType.RELATION_ASSERTION: (
        "source_id",
        "target_id",
        "source_kind",
        "target_kind",
        "predicate",
        "assertion_family_id",
        "revision",
        "status",
        "confidence",
        "evidence_ids",
        "valid_from",
        "expires_at",
        "supersedes_id",
        "provenance_id",
        "based_on_brief_id",
        "based_on_brief_section_index",
        "egress_policy",
    ),
    NodeType.CONTENT_CHUNK: (
        "source_revision_id",
        "ordinal",
        "char_start",
        "char_end",
        "text_hash",
        "status",
        "egress_policy",
    ),
    NodeType.FACET: ("namespace", "normalized_value", "status", "egress_policy"),
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _node_view(node: Any) -> NodeView:
    node_type = node.node_type if isinstance(node.node_type, NodeType) else NodeType(node.node_type)
    fields_to_copy = _FIELD_ALLOWLIST[node_type]
    values = {
        field_name: _json_value(getattr(node, field_name))
        for field_name in fields_to_copy
        if hasattr(node, field_name)
    }
    status = values.get("status")
    status_value = status if isinstance(status, str) else None
    title = next(
        (str(values[key]) for key in ("title", "name", "display_name", "text", "purpose", "path") if values.get(key)),
        str(node.id),
    )
    snippet_source = next(
        (str(values[key]) for key in ("summary", "description", "content", "excerpt", "text", "purpose") if values.get(key)),
        title,
    )
    revision = values.get("revision", 0)
    if not isinstance(revision, int):
        revision = 0
    return NodeView(
        id=str(node.id),
        node_type=node_type.value,
        owner_id=str(node.owner_id),
        title=title,
        snippet=snippet_source[:320],
        status=status_value,
        revision=revision,
        fields=MappingProxyType(values),
    )


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in value.casefold().replace("\n", " ").split() if token)


class GraphReadService:
    """Read-only view over a GraphWriteService snapshot."""

    def __init__(self, writes: InMemoryGraphWriteService) -> None:
        self._writes = writes

    @property
    def owner_id(self) -> str:
        """Expose the owner used by the underlying write snapshot."""

        return self._writes.owner_id

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise GraphReadError("query must be a non-empty string of at most 512 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise GraphReadError("limit must be between 1 and 50")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30_000:
            raise GraphReadError("timeout_ms must be between 1 and 30000")
        offset = self._cursor(cursor)
        started = monotonic()
        owner = owner_id.strip() if isinstance(owner_id, str) else ""
        if not owner:
            raise GraphReadError("owner_id is required")
        tokens = _tokens(query)
        snapshot = self._writes.read_snapshot()
        node_by_id = {node.id: node for node in snapshot.nodes}
        scores: dict[str, float] = {}
        paths: dict[str, tuple[str, ...]] = {}
        evidence_by_node: dict[str, tuple[str, ...]] = {}
        relation_paths: dict[str, tuple[RelationPathStep, ...]] = {}
        for node in node_by_id.values():
            self._check_timeout(started, timeout_ms)
            if isinstance(node, RelationAssertion):
                continue
            if not self._visible(node, owner):
                continue
            view = _node_view(node)
            haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True)
            matched = sum(1 for token in tokens if token in haystack.casefold())
            if matched:
                scores[node.id] = matched / len(tokens) + (0.25 if query.casefold() in haystack.casefold() else 0.0)

        adjacency: dict[str, list[tuple[str, RelationPathStep]]] = {}
        for relation in snapshot.relations:
            self._check_timeout(started, timeout_ms)
            if relation.owner_id != owner or not relation.is_active():
                continue
            source = node_by_id.get(relation.source_id)
            target = node_by_id.get(relation.target_id)
            if (
                source is None or target is None
                or isinstance(source, RelationAssertion) or isinstance(target, RelationAssertion)
                or not self._visible(source, owner) or not self._visible(target, owner)
            ):
                continue
            adjacency.setdefault(relation.source_id, []).append((
                relation.target_id,
                RelationPathStep.from_relationship(relation, from_id=source.id, to_id=target.id),
            ))
            adjacency.setdefault(relation.target_id, []).append((
                relation.source_id,
                RelationPathStep.from_relationship(relation, from_id=target.id, to_id=source.id),
            ))

        self._add_formal_assertion_edges(
            adjacency, snapshot, node_by_id, owner, datetime.now(timezone.utc), started, timeout_ms,
        )

        frontier = set(scores)
        for _depth in range(1, 3):
            next_frontier: set[str] = set()
            for current_id in sorted(frontier):
                self._check_timeout(started, timeout_ms)
                current_score = scores[current_id]
                current_path = paths.get(current_id, ())
                current_evidence = evidence_by_node.get(current_id, ())
                for neighbor_id, step in sorted(
                    adjacency.get(current_id, ()),
                    key=lambda item: (item[0], item[1].predicate, item[1].evidence_ids),
                ):
                    if neighbor_id in current_path[0::2]:
                        continue
                    neighbor = node_by_id.get(neighbor_id)
                    if neighbor is None or not self._visible(neighbor, owner):
                        continue
                    candidate_score = current_score * 0.5
                    candidate_path = current_path + (step.predicate, neighbor_id) if current_path else (current_id, step.predicate, neighbor_id)
                    previous_score = scores.get(neighbor_id)
                    if previous_score is not None and candidate_score <= previous_score:
                        continue
                    scores[neighbor_id] = candidate_score
                    paths[neighbor_id] = candidate_path
                    relation_paths[neighbor_id] = (*relation_paths.get(current_id, ()), step)
                    evidence_by_node[neighbor_id] = tuple(dict.fromkeys((*current_evidence, *step.evidence_ids)))
                    next_frontier.add(neighbor_id)
            frontier = next_frontier
            if not frontier:
                break

        ordered_ids = sorted(scores, key=lambda node_id: (-scores[node_id], node_id))
        page_ids = ordered_ids[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(ordered_ids) else None
        return SearchPage(
            tuple(
                SearchHit(
                    _node_view(node_by_id[node_id]),
                    scores[node_id],
                    paths.get(node_id, ()),
                    evidence_by_node.get(node_id, ()),
                    relation_paths.get(node_id, ()),
                )
                for node_id in page_ids
            ),
            next_cursor,
        )

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        node = self._writes.get_node(node_id)
        if node is None or not self._visible(node, owner_id):
            raise GraphReadNotFoundError("node was not found")
        return _node_view(node)

    @staticmethod
    def _visible(node: Any, owner_id: str) -> bool:
        if getattr(node, "owner_id", None) != owner_id:
            return False
        status = getattr(node, "status", None)
        value = status.value if isinstance(status, Enum) else status
        return value not in _NON_CURRENT

    def _add_formal_assertion_edges(
        self,
        adjacency: dict[str, list[tuple[str, RelationPathStep]]],
        snapshot: GraphReadSnapshot,
        node_by_id: Mapping[str, Any],
        owner_id: str,
        at: datetime,
        started: float,
        timeout_ms: int,
    ) -> None:
        assertions = {
            node.id: node for node in snapshot.nodes
            if isinstance(node, RelationAssertion) and node.owner_id == owner_id
        }
        edges = snapshot.structural_edges
        edge_labels = {edge.value for edge in RelationAssertionEdgeType}
        outgoing_lists: dict[str, list[tuple[str, str, str]]] = {assertion_id: [] for assertion_id in assertions}
        for edge in edges:
            if edge[0] in outgoing_lists and edge[1] in edge_labels:
                outgoing_lists[edge[0]].append(edge)
        outgoing = {assertion_id: tuple(values) for assertion_id, values in outgoing_lists.items()}
        successor_ids: dict[str, set[str]] = {}
        for assertion in assertions.values():
            if assertion.supersedes_id is not None:
                successor_ids.setdefault(assertion.supersedes_id, set()).add(assertion.id)
        for source_id, label, predecessor_id in edges:
            if label != RelationAssertionEdgeType.SUPERSEDES.value:
                continue
            successor = assertions.get(source_id)
            if successor is not None and predecessor_id in assertions:
                successor_ids.setdefault(predecessor_id, set()).add(successor.id)

        latest_briefs = dict(snapshot.latest_idea_briefs)
        for assertion in assertions.values():
            self._check_timeout(started, timeout_ms)
            # Any same-owner successor suppresses the predecessor, even when
            # the successor is rejected/expired or its two references disagree.
            if successor_ids.get(assertion.id):
                continue
            if not self._assertion_current(assertion, node_by_id, owner_id, at):
                continue
            if assertion.supersedes_id is not None and len(successor_ids.get(assertion.supersedes_id, ())) != 1:
                continue
            try:
                expected_edges = relation_assertion_structural_edges(assertion)
            except (DomainValidationError, TypeError, ValueError):
                continue
            actual_edges = outgoing.get(assertion.id, ())
            if len(actual_edges) != len(set(actual_edges)) or set(actual_edges) != set(expected_edges):
                continue
            source = node_by_id.get(assertion.source_id)
            target = node_by_id.get(assertion.target_id)
            if not self._current_endpoint(source, owner_id, node_by_id) or not self._current_endpoint(target, owner_id, node_by_id):
                continue
            if getattr(source, "node_type", None) is not assertion.source_kind:
                continue
            if getattr(target, "node_type", None) is not assertion.target_kind:
                continue
            valid_brief_id, valid_section = self._assertion_brief_reference(
                assertion, source, target, latest_briefs, node_by_id, owner_id,
            )
            if valid_brief_id is False:
                continue
            valid_evidence = True
            for evidence_id in assertion.evidence_ids:
                evidence = node_by_id.get(evidence_id)
                if not isinstance(evidence, Evidence) or evidence.owner_id != owner_id or evidence.status is not Status.ACTIVE:
                    valid_evidence = False
                    break
            if not valid_evidence:
                continue
            step = RelationPathStep(
                from_id=source.id,
                to_id=target.id,
                source_id=source.id,
                predicate=assertion.predicate.value,
                target_id=target.id,
                traversal_direction="outgoing",
                evidence_ids=tuple(assertion.evidence_ids),
                status=assertion.status.value,
                confidence=assertion.confidence,
                valid_from=assertion.valid_from.isoformat(),
                expires_at=assertion.expires_at.isoformat() if assertion.expires_at is not None else None,
                relation_assertion_id=assertion.id,
                based_on_brief_id=valid_brief_id,
                based_on_brief_section_index=valid_section,
            )
            adjacency.setdefault(source.id, []).append((target.id, step))
            adjacency.setdefault(target.id, []).append((source.id, replace(step, from_id=target.id, to_id=source.id, traversal_direction="incoming")))

    @staticmethod
    def _assertion_current(assertion: RelationAssertion, node_by_id: Mapping[str, Any], owner_id: str, at: datetime) -> bool:
        if assertion.status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED, RelationshipStatus.CONFIRMED}:
            return False
        if assertion.valid_from.tzinfo is None or (assertion.expires_at is not None and assertion.expires_at.tzinfo is None):
            return False
        if assertion.valid_from > at or (assertion.expires_at is not None and assertion.expires_at <= at):
            return False
        return not any(
            isinstance(candidate, RelationAssertion)
            and candidate.owner_id == owner_id
            and candidate.supersedes_id == assertion.id
            for candidate in node_by_id.values()
        )

    @classmethod
    def _current_endpoint(cls, node: Any, owner_id: str, node_by_id: Mapping[str, Any]) -> bool:
        if node is None or not cls._visible(node, owner_id):
            return False
        status = getattr(node, "status", None)
        status_value = status.value if isinstance(status, Enum) else status
        if status_value in {"failed"}:
            return False
        if isinstance(node, Idea):
            root = node
            seen = {root.id}
            while root.supersedes_id is not None:
                parent = node_by_id.get(root.supersedes_id)
                if not isinstance(parent, Idea) or parent.owner_id != owner_id or parent.id in seen:
                    return False
                if root.revision != parent.revision + 1:
                    return False
                seen.add(parent.id)
                root = parent
            current = root
            while True:
                children = [
                    candidate for candidate in node_by_id.values()
                    if isinstance(candidate, Idea) and candidate.owner_id == owner_id and candidate.supersedes_id == current.id
                ]
                if len(children) > 1:
                    return False
                if not children:
                    return current.id == node.id
                child = children[0]
                if child.revision != current.revision + 1 or child.id in seen:
                    return False
                seen.add(child.id)
                current = child
        return not any(
            getattr(candidate, "owner_id", None) == owner_id
            and getattr(candidate, "supersedes_id", None) == getattr(node, "id", None)
            for candidate in node_by_id.values()
        )

    @classmethod
    def _assertion_brief_reference(
        cls,
        assertion: RelationAssertion,
        source: Any,
        target: Any,
        latest_briefs: Mapping[str, Any],
        node_by_id: Mapping[str, Any],
        owner_id: str,
    ) -> tuple[str | None | bool, int | None]:
        idea_ends = [node for node in (source, target) if isinstance(node, Idea)]
        if not idea_ends:
            return (None, None) if assertion.based_on_brief_id is None and assertion.based_on_brief_section_index is None else (False, None)
        if assertion.based_on_brief_id is None or assertion.based_on_brief_section_index is None:
            return False, None
        primary = source if isinstance(source, Idea) else target
        root = primary
        seen = {root.id}
        while root.supersedes_id is not None:
            parent = node_by_id.get(root.supersedes_id)
            if not isinstance(parent, Idea) or parent.owner_id != owner_id or parent.id in seen:
                return False, None
            root = parent
            seen.add(root.id)
        latest = latest_briefs.get(root.id)
        if (
            latest is None or latest.owner_id != owner_id or latest.idea_lineage_root_id != root.id
            or latest.id != assertion.based_on_brief_id
            or latest.based_on_idea_id != primary.id or not latest.research_run_ids
        ):
            return False, None
        section_index = assertion.based_on_brief_section_index
        if type(section_index) is not int or not 0 <= section_index < len(latest.sections):
            return False, None
        section = latest.sections[section_index]
        if not section.content.strip(): return False, None
        if not set(assertion.evidence_ids).issubset(section.evidence_ids):
            return False, None
        return latest.id, section_index

    @staticmethod
    def _cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or not cursor.isdigit():
            raise GraphReadError("cursor must be a non-negative decimal offset")
        return int(cursor)

    @staticmethod
    def _check_timeout(started: float, timeout_ms: int) -> None:
        if (monotonic() - started) * 1000 > timeout_ms:
            raise GraphReadTimeoutError("local graph search timed out; retry with a narrower query")
