"""Deterministic owner-scoped graph + full-text read contract."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .founder_graph import NodeType
from .founder_graph_write import InMemoryGraphWriteService


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
class SearchHit:
    node: NodeView
    score: float
    path: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


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
        node_by_id = {node.id: node for node in self._writes.nodes()}
        scores: dict[str, float] = {}
        paths: dict[str, tuple[str, ...]] = {}
        evidence_by_node: dict[str, tuple[str, ...]] = {}
        for node in node_by_id.values():
            self._check_timeout(started, timeout_ms)
            if not self._visible(node, owner):
                continue
            view = _node_view(node)
            haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True)
            matched = sum(1 for token in tokens if token in haystack.casefold())
            if matched:
                scores[node.id] = matched / len(tokens) + (0.25 if query.casefold() in haystack.casefold() else 0.0)

        adjacency: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
        for relation in self._writes.relations():
            self._check_timeout(started, timeout_ms)
            if not relation.is_active():
                continue
            source = node_by_id.get(relation.source_id)
            target = node_by_id.get(relation.target_id)
            if source is None or target is None or not self._visible(source, owner) or not self._visible(target, owner):
                continue
            edge = (relation.relation.value, tuple(relation.evidence_ids))
            adjacency.setdefault(relation.source_id, []).append((relation.target_id, *edge))
            adjacency.setdefault(relation.target_id, []).append((relation.source_id, *edge))

        frontier = set(scores)
        for _depth in range(1, 3):
            next_frontier: set[str] = set()
            for current_id in sorted(frontier):
                self._check_timeout(started, timeout_ms)
                current_score = scores[current_id]
                current_path = paths.get(current_id, ())
                current_evidence = evidence_by_node.get(current_id, ())
                for neighbor_id, relation_name, edge_evidence in sorted(adjacency.get(current_id, ()), key=lambda item: (item[0], item[1], item[2])):
                    if neighbor_id in current_path[0::2]:
                        continue
                    neighbor = node_by_id.get(neighbor_id)
                    if neighbor is None or not self._visible(neighbor, owner):
                        continue
                    candidate_score = current_score * 0.5
                    candidate_path = current_path + (relation_name, neighbor_id) if current_path else (current_id, relation_name, neighbor_id)
                    previous_score = scores.get(neighbor_id)
                    if previous_score is not None and candidate_score <= previous_score:
                        continue
                    scores[neighbor_id] = candidate_score
                    paths[neighbor_id] = candidate_path
                    evidence_by_node[neighbor_id] = tuple(dict.fromkeys((*current_evidence, *edge_evidence)))
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
