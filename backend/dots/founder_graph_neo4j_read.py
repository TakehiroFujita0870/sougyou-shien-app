"""Owner-scoped, read-only Neo4j adapter for the Founder Graph.

The write gateway stores each domain value as ``payload_json``.  This adapter
deliberately hydrates only the public read contract (``NodeView`` and
``SearchPage``); it does not reconstruct domain dataclasses or expose Cypher.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping

from .founder_graph import NodeType
from .founder_graph_neo4j import (
    Neo4jGraphGateway,
    Neo4jQueryContractError,
    Neo4jUnavailableError,
    _single,
)
from .founder_graph_read import (
    GraphReadError,
    GraphReadNotFoundError,
    GraphReadTimeoutError,
    GraphReadUnavailableError,
    NodeView,
    SearchHit,
    SearchPage,
    _FIELD_ALLOWLIST,
    _NON_CURRENT,
    _tokens,
)


class Neo4jReadUnavailableError(GraphReadUnavailableError):
    """The injected Neo4j driver could not complete a read operation."""


@dataclass(frozen=True, slots=True)
class GraphRelationView:
    source_id: str
    relation: str
    target_id: str
    source_node_type: str
    target_node_type: str


_FETCH_QUERY = (
    "MATCH (n) WHERE n.id = $node_id AND n.owner_id = $owner_id "
    "AND NOT coalesce(n.status, '') IN $non_current "
    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
    "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
    "n.search_text AS search_text LIMIT 1"
)

_SEARCH_QUERY = (
    "MATCH (n) WHERE n.owner_id = $owner_id "
    "AND NOT coalesce(n.status, '') IN $non_current "
    "AND any(token IN $tokens WHERE toLower(coalesce(n.search_text, '')) CONTAINS token) "
    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
    "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
    "n.search_text AS search_text"
)

_SEARCH_RELATIONS_QUERY = (
    "MATCH (a)-[r]->(b) "
    "WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id "
    "AND NOT coalesce(a.status, '') IN $non_current "
    "AND NOT coalesce(b.status, '') IN $non_current "
    "AND (a.id IN $matched_ids OR b.id IN $matched_ids) "
    "RETURN a.id AS source_id, type(r) AS relation, b.id AS target_id, "
    "a.owner_id AS source_owner_id, a.node_type AS source_node_type, "
    "a.status AS source_status, a.revision AS source_revision, "
    "a.payload_json AS source_payload_json, a.search_text AS source_search_text, "
    "b.owner_id AS target_owner_id, b.node_type AS target_node_type, "
    "b.status AS target_status, b.revision AS target_revision, "
    "b.payload_json AS target_payload_json, b.search_text AS target_search_text"
)

_RELATIONS_QUERY = (
    "MATCH (a)-[r]->(b) "
    "WHERE a.id = $node_id AND a.owner_id = $owner_id AND b.owner_id = $owner_id "
    "AND NOT coalesce(a.status, '') IN $non_current "
    "AND NOT coalesce(b.status, '') IN $non_current "
    "RETURN a.id AS source_id, type(r) AS relation, b.id AS target_id, "
    "a.owner_id AS source_owner_id, b.owner_id AS target_owner_id, "
    "a.node_type AS source_node_type, b.node_type AS target_node_type "
    "ORDER BY source_id, relation, target_id"
)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            value = getter(key)
        except (KeyError, TypeError):
            return default
        return default if value is None else value
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _rows(result: Any) -> tuple[Any, ...]:
    if result is None:
        return ()
    try:
        return tuple(result)
    except TypeError:
        row = _single(result)
        return () if row is None else (row,)


def _parse_payload(row: Any, *, prefix: str = "") -> dict[str, Any]:
    raw = _row_value(row, f"{prefix}payload_json")
    if not isinstance(raw, str) or not raw.strip():
        raise GraphReadError("Neo4j node payload is missing")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise GraphReadError("Neo4j node payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise GraphReadError("Neo4j node payload must be a JSON object")
    return payload


def _view_from_row(row: Any, *, owner_id: str, prefix: str = "", strict: bool = True) -> NodeView | None:
    payload = _parse_payload(row, prefix=prefix)
    node_id = _row_value(row, f"{prefix}id", payload.get("id"))
    row_owner = _row_value(row, f"{prefix}owner_id", payload.get("owner_id"))
    if not isinstance(node_id, str) or not node_id or row_owner != owner_id:
        if strict:
            raise GraphReadNotFoundError("node was not found")
        return None
    raw_type = _row_value(row, f"{prefix}node_type", payload.get("node_type"))
    try:
        node_type = raw_type if isinstance(raw_type, NodeType) else NodeType(raw_type)
    except (TypeError, ValueError) as error:
        raise GraphReadError("Neo4j node type is not in the Founder Graph allowlist") from error

    values = {
        field_name: payload[field_name]
        for field_name in _FIELD_ALLOWLIST[node_type]
        if field_name in payload
    }
    status = values.get("status", _row_value(row, f"{prefix}status"))
    status_value = status.value if hasattr(status, "value") else status
    if status_value in _NON_CURRENT:
        if strict:
            raise GraphReadNotFoundError("node was not found")
        return None
    if status_value is not None and not isinstance(status_value, str):
        status_value = str(status_value)
    values["status"] = status_value
    revision = values.get("revision", _row_value(row, f"{prefix}revision", 0))
    if not isinstance(revision, int) or isinstance(revision, bool):
        revision = 0
    title = next(
        (
            str(values[key])
            for key in ("title", "name", "display_name", "text", "purpose", "path")
            if values.get(key)
        ),
        node_id,
    )
    snippet_source = next(
        (
            str(values[key])
            for key in ("summary", "description", "content", "excerpt", "text", "purpose")
            if values.get(key)
        ),
        title,
    )
    return NodeView(
        id=node_id,
        node_type=node_type.value,
        owner_id=owner_id,
        title=title,
        snippet=snippet_source[:320],
        status=status_value,
        revision=revision,
        fields=MappingProxyType(values),
    )


def _required_owner(owner_id: str) -> str:
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise GraphReadError("owner_id is required")
    return owner_id.strip()


def _required_node_id(node_id: str) -> str:
    if not isinstance(node_id, str) or not node_id.strip():
        raise GraphReadError("node_id is required")
    return node_id.strip()


class Neo4jGraphReadService:
    """Read-only NodeView/SearchPage boundary over an injected gateway."""

    def __init__(self, gateway: Neo4jGraphGateway) -> None:
        if not isinstance(gateway, Neo4jGraphGateway):
            raise GraphReadError("a Neo4jGraphGateway is required")
        self._gateway = gateway

    @property
    def owner_id(self) -> str:
        """Expose the owner bound to the injected Neo4j gateway."""

        return self._gateway.owner_id

    @contextmanager
    def _read_session(self):
        try:
            with self._gateway._session() as session:
                yield session
        except Neo4jUnavailableError as error:
            raise Neo4jReadUnavailableError("Neo4j read is unavailable") from error

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        identifier = _required_node_id(node_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("node was not found")
        with self._read_session() as session:
            result = self._gateway._execute_read(
                session,
                lambda tx: tx.run(
                    _FETCH_QUERY,
                    node_id=identifier,
                    owner_id=owner,
                    non_current=sorted(_NON_CURRENT),
                ),
            )
            rows = _rows(result)
        if not rows:
            raise GraphReadNotFoundError("node was not found")
        view = _view_from_row(rows[0], owner_id=owner)
        if view is None:
            raise GraphReadNotFoundError("node was not found")
        return view

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
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            return SearchPage((), None)
        tokens = _tokens(query)
        started = monotonic()
        with self._read_session() as session:
            result = self._gateway._execute_read(
                session,
                lambda tx: tx.run(
                    _SEARCH_QUERY,
                    owner_id=owner,
                    tokens=list(tokens),
                    non_current=sorted(_NON_CURRENT),
                ),
            )
            rows = _rows(result)
            self._check_timeout(started, timeout_ms)
            views: dict[str, NodeView] = {}
            scores: dict[str, float] = {}
            paths: dict[str, tuple[str, ...]] = {}
            for row in rows:
                self._check_timeout(started, timeout_ms)
                view = _view_from_row(row, owner_id=owner, strict=False)
                if view is None:
                    continue
                views[view.id] = view
                haystack = str(_row_value(row, "search_text", "")).casefold()
                if not haystack:
                    haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True).casefold()
                matched = sum(1 for token in tokens if token in haystack)
                if matched:
                    scores[view.id] = matched / len(tokens) + (0.25 if query.casefold() in haystack else 0.0)

            if scores:
                relation_result = self._gateway._execute_read(
                    session,
                    lambda tx: tx.run(
                        _SEARCH_RELATIONS_QUERY,
                        owner_id=owner,
                        matched_ids=list(scores),
                        non_current=sorted(_NON_CURRENT),
                    ),
                )
                for row in _rows(relation_result):
                    self._check_timeout(started, timeout_ms)
                    source = _view_from_row(row, owner_id=owner, prefix="source_", strict=False)
                    target = _view_from_row(row, owner_id=owner, prefix="target_", strict=False)
                    if source is None or target is None:
                        continue
                    views[source.id] = source
                    views[target.id] = target
                    relation = _row_value(row, "relation")
                    try:
                        relation_name = Neo4jGraphGateway.relation_type_for(relation)
                    except Neo4jQueryContractError as error:
                        raise GraphReadError("Neo4j relation type is not in the Founder Graph allowlist") from error
                    path = (source.id, relation_name, target.id)
                    if source.id in scores and target.id not in scores:
                        scores[target.id] = scores[source.id] * 0.5
                        paths[target.id] = path
                    elif target.id in scores and source.id not in scores:
                        scores[source.id] = scores[target.id] * 0.5
                        paths[source.id] = path
            self._check_timeout(started, timeout_ms)

        ordered_ids = sorted(scores, key=lambda node_id: (-scores[node_id], node_id))
        page_ids = ordered_ids[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(ordered_ids) else None
        return SearchPage(
            tuple(SearchHit(views[node_id], scores[node_id], paths.get(node_id, ())) for node_id in page_ids),
            next_cursor,
        )

    def relations(self, node_id: str, *, owner_id: str) -> tuple[GraphRelationView, ...]:
        identifier = _required_node_id(node_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("node was not found")
        self.fetch(identifier, owner_id=owner)
        with self._read_session() as session:
            result = self._gateway._execute_read(
                session,
                lambda tx: tx.run(
                    _RELATIONS_QUERY,
                    node_id=identifier,
                    owner_id=owner,
                    non_current=sorted(_NON_CURRENT),
                ),
            )
            rows = _rows(result)
        relations: list[GraphRelationView] = []
        for row in rows:
            source_id = _row_value(row, "source_id")
            target_id = _row_value(row, "target_id")
            relation = _row_value(row, "relation")
            source_type = _row_value(row, "source_node_type")
            target_type = _row_value(row, "target_node_type")
            try:
                if (
                    _row_value(row, "source_owner_id") != owner
                    or _row_value(row, "target_owner_id") != owner
                ):
                    raise GraphReadNotFoundError("node was not found")
                source_kind = NodeType(source_type).value
                target_kind = NodeType(target_type).value
                relation_name = Neo4jGraphGateway.relation_type_for(relation)
            except (TypeError, ValueError, GraphReadNotFoundError, Neo4jQueryContractError) as error:
                raise GraphReadError("Neo4j relation row is not in the Founder Graph allowlist") from error
            relations.append(GraphRelationView(str(source_id), relation_name, str(target_id), source_kind, target_kind))
        return tuple(sorted(relations, key=lambda item: (item.source_id, item.relation, item.target_id)))

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


__all__ = ["GraphRelationView", "Neo4jGraphReadService", "Neo4jReadUnavailableError"]
