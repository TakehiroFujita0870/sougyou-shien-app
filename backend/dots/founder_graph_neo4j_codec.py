"""Pure serialization and record adapters for the Neo4j Founder Graph gateway."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
from typing import Any, Mapping

from .founder_graph import NodeType
from .founder_graph_read_contract import FIELD_ALLOWLIST
from .founder_graph_write import GraphWriteError


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


def _node_revision(node: Any) -> int:
    value = getattr(node, "aggregate_revision", getattr(node, "revision", 0))
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraphWriteError("node revision must be a non-negative integer")
    return value


def _node_properties(node: Any) -> dict[str, Any]:
    node_type = node.node_type if isinstance(node.node_type, NodeType) else NodeType(node.node_type)
    payload = _json_value(node)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Keep the persistent search projection aligned with the in-memory read
    # contract. In particular, local-only ContentChunk text may stay in the
    # stored payload but must not become searchable through the safe adapter.
    fields_for_search = (
        {field_name: payload[field_name] for field_name in FIELD_ALLOWLIST[node_type] if field_name in payload}
        if isinstance(payload, Mapping)
        else {"value": payload}
    )
    search_text = " ".join(str(item) for item in fields_for_search.values())
    status = getattr(node, "status", None)
    egress_policy = getattr(node, "egress_policy", None)
    properties = {
        "id": str(node.id),
        "owner_id": str(node.owner_id),
        "node_type": node_type.value,
        "status": status.value if isinstance(status, Enum) else (str(status) if status is not None else None),
        "egress_policy": egress_policy.value if isinstance(egress_policy, Enum) else (str(egress_policy) if egress_policy is not None else None),
        "revision": _node_revision(node),
        "payload_json": payload_json,
        "search_text": search_text[:16_000],
    }
    # These typed references remain queryable without asking Neo4j to interpret
    # opaque payload JSON; callers still pass values only as query parameters.
    if node_type is NodeType.SOURCE:
        current_revision_id = getattr(node, "current_revision_id", None)
        if current_revision_id is not None:
            properties["current_revision_id"] = str(current_revision_id)
    elif node_type is NodeType.IDEA:
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type in {NodeType.ASSET, NodeType.PERSON}:
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.SOURCE_REVISION:
        properties["source_id"] = str(node.source_id)
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.CONTENT_CHUNK:
        properties["source_revision_id"] = str(node.source_revision_id)
    elif node_type is NodeType.CLAIM:
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.EVIDENCE:
        for reference in ("claim_id", "source_revision_id", "content_chunk_id"):
            value = getattr(node, reference, None)
            if value is not None:
                properties[reference] = str(value)
    elif node_type is NodeType.RELATION_ASSERTION:
        properties["assertion_family_id"] = str(node.assertion_family_id)
        if node.supersedes_id is not None:
            properties["supersedes_id"] = str(node.supersedes_id)
    return properties


def _single(result: Any) -> Any | None:
    single = getattr(result, "single", None)
    if callable(single):
        try:
            return single(strict=False)
        except TypeError:
            return single()
    try:
        return next(iter(result), None)
    except TypeError:
        return None


def _rows(result: Any) -> tuple[Any, ...]:
    """Return all records from a Neo4j/fake result without query coupling."""

    try:
        return tuple(result)
    except TypeError:
        value = _single(result)
        return () if value is None else (value,)


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _content_chunk_ids(value: Any) -> tuple[str, ...]:
    """Decode the opaque chunk-id list persisted on a capture audit."""

    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as error:
            raise GraphWriteError("capture audit content chunk ids are invalid") from error
    if not isinstance(value, (tuple, list)):
        raise GraphWriteError("capture audit content chunk ids are invalid")
    identifiers = tuple(item for item in value if isinstance(item, str) and item.strip())
    if len(identifiers) != len(value):
        raise GraphWriteError("capture audit content chunk ids are invalid")
    return identifiers
