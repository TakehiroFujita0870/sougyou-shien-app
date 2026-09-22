"""Pure, deterministic safe JSON and Markdown export for Founder Graph.

The exporter accepts either the owner-scoped ``GraphReadPort`` contract or
already-safe node projections.  It never touches a database, filesystem,
network, model provider, or write service.  The domain shareable allowlist is
reapplied at this boundary so a wider local ``NodeView`` cannot accidentally
become an export.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, TypeAlias

from .founder_graph import NodeType, SHAREABLE_PROJECTION_ALLOWLIST
from .founder_graph_read import GraphReadPort, NodeView, SearchHit


EXPORT_SCHEMA_VERSION = "founder-graph-export-v1"
MAX_EXPORT_LIMIT = 50
MAX_EXPORT_BYTES = 2_000_000
DEFAULT_EXPORT_LIMIT = 50
DEFAULT_EXPORT_MAX_BYTES = 512_000
MAX_PROVENANCE_IDS = MAX_EXPORT_LIMIT * 10

_JsonValue: TypeAlias = None | bool | int | float | str | list[Any] | dict[str, Any]
_ProjectionInput: TypeAlias = NodeView | SearchHit | Mapping[str, Any]

# These keys are never part of an exported safe projection, including when a
# caller places them below an otherwise allowlisted report or metadata field.
_FORBIDDEN_KEYS = frozenset(
    {
        "actor",
        "contact",
        "egress_policy",
        "idempotency_key",
        "instruction_artifact_path",
        "instruction_path",
        "local_only",
        "owner_id",
        "path",
        "private_notes",
        "provenance",
        "prompt_version",
        "rule_version",
        "source_path",
        "source_text",
    }
)
_REFERENCE_FIELDS = frozenset(
    {
        "claim_id",
        "claim_ids",
        "current_revision_id",
        "evidence_ids",
        "experiment_ids",
        "material_id",
        "parent_id",
        "report_ids",
        "run_ids",
        "source_id",
        "source_revision_id",
        "sources",
        "supersedes_id",
        "target_idea_id",
    }
)
class FounderGraphExportError(ValueError):
    """Base class for safe export validation failures."""


class FounderGraphExportLimitError(FounderGraphExportError):
    """The caller requested or supplied a value outside the export bounds."""


class FounderGraphExportTooLargeError(FounderGraphExportError):
    """The deterministic JSON or Markdown output exceeds the byte bound."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FounderGraphExportError(f"{name} must be a non-empty string")
    return value.strip()


def _owner(value: object) -> str:
    return _text(value, "owner_id")


def _validate_limits(limit: object, max_bytes: object) -> tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_EXPORT_LIMIT:
        raise FounderGraphExportLimitError(f"limit must be between 1 and {MAX_EXPORT_LIMIT}")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= MAX_EXPORT_BYTES:
        raise FounderGraphExportLimitError(f"max_bytes must be between 1 and {MAX_EXPORT_BYTES}")
    return limit, max_bytes


def _normalize_ids(
    value: object,
    name: str,
    *,
    sort: bool = True,
    max_items: int | None = MAX_PROVENANCE_IDS,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if isinstance(value, Mapping) or not isinstance(value, Iterable):
        raise FounderGraphExportError(f"{name} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if max_items is not None and len(result) >= max_items:
            raise FounderGraphExportLimitError(f"{name} exceeds the bounded item limit")
        if not isinstance(item, str) or not item.strip():
            raise FounderGraphExportError(f"{name} must contain non-empty strings")
        normalized = item.strip()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(sorted(result) if sort else result)


def _reference_ids(value: object) -> tuple[str, ...]:
    """Extract opaque string references without traversing arbitrary mappings."""

    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Mapping):
        return ()
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        result: set[str] = set()
        for item in value:
            result.update(_reference_ids(item))
        return tuple(sorted(result))
    return ()


def _key_name(value: object) -> str:
    if not isinstance(value, str):
        raise FounderGraphExportError("projection mapping keys must be strings")
    return value


def _is_forbidden_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return normalized in _FORBIDDEN_KEYS or normalized.replace("_", "") in {
        "instructionartifactpath",
        "instructionpath",
        "privatenotes",
        "sourcetext",
    }


def _clean_json(value: Any, *, path: str) -> _JsonValue:
    """Copy JSON-like values while recursively dropping forbidden keys."""

    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise FounderGraphExportError(f"{path} must contain finite numbers")
        return value
    if isinstance(value, Enum):
        return _clean_json(value.value, path=path)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = _key_name(raw_key)
            if _is_forbidden_key(key):
                continue
            cleaned[key] = _clean_json(raw_item, path=f"{path}.{key}")
        return dict(sorted(cleaned.items()))
    if isinstance(value, (tuple, list)):
        return [_clean_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, (set, frozenset)):
        cleaned = [_clean_json(item, path=f"{path}[]") for item in value]
        return sorted(cleaned, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    raise FounderGraphExportError(f"{path} must contain JSON-like values")


def _node_type(value: object) -> NodeType | None:
    if isinstance(value, NodeType):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "ownerprofile": "owner_profile",
        "researchmaterial": "research_material",
        "researchcampaign": "research_campaign",
        "researchrun": "research_run",
        "reportversion": "report_version",
        "reportsection": "report_section",
        "sourcerevision": "source_revision",
        "instructionartifact": "instruction_artifact",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return NodeType(normalized)
    except (TypeError, ValueError):
        return None


def _mapping_for(value: _ProjectionInput) -> dict[str, Any]:
    if isinstance(value, SearchHit):
        value = value.node
    if isinstance(value, NodeView):
        return {
            "id": value.id,
            "kind": value.node_type,
            "owner_id": value.owner_id,
            "fields": dict(value.fields),
        }
    if isinstance(value, Mapping):
        return dict(value)
    raise FounderGraphExportError("export input must be a NodeView, SearchHit, or safe mapping")


def _raw_provenance_ids(raw: Mapping[str, Any], raw_fields: Mapping[str, Any]) -> set[str]:
    result = set(_normalize_ids(raw.get("provenance_ids"), "provenance_ids"))
    result.update(_normalize_ids(raw.get("provenance_id"), "provenance_id"))
    result.update(_normalize_ids(raw_fields.get("provenance_ids"), "provenance_ids"))
    result.update(_normalize_ids(raw_fields.get("provenance_id"), "provenance_id"))
    # A safe mapping may carry only an opaque provenance identity.  Never copy
    # the rest of a raw provenance object into fields or Markdown.
    for container in (raw.get("provenance"), raw_fields.get("provenance")):
        if isinstance(container, Mapping):
            result.update(_normalize_ids(container.get("id"), "provenance.id"))
            result.update(_normalize_ids(container.get("provenance_id"), "provenance.provenance_id"))
    return result


def _safe_node(value: _ProjectionInput, *, owner_id: str) -> "ExportNode | None":
    raw = _mapping_for(value)
    raw_fields = raw.get("fields")
    if raw_fields is None:
        raw_fields = raw
    if not isinstance(raw_fields, Mapping):
        raise FounderGraphExportError("projection fields must be a mapping")

    supplied_owners = (raw.get("owner_id"), raw_fields.get("owner_id"))
    if any(owner is not None and owner != owner_id for owner in supplied_owners):
        return None

    policies = (
        raw.get("egress_policy"),
        raw_fields.get("egress_policy"),
        raw.get("sensitivity"),
        raw_fields.get("sensitivity"),
    )
    for policy in policies:
        policy_value = getattr(policy, "value", policy)
        if policy_value is not None and policy_value != "shareable":
            return None
    if raw.get("local_only") is True or raw_fields.get("local_only") is True:
        return None

    node_id = raw.get("id", raw_fields.get("id"))
    node_kind = raw.get("kind", raw.get("node_type", raw_fields.get("kind", raw_fields.get("node_type"))))
    node_type = _node_type(node_kind)
    if not isinstance(node_id, str) or not node_id.strip() or node_type is None:
        return None
    node_id = node_id.strip()
    allowlist = SHAREABLE_PROJECTION_ALLOWLIST[node_type]
    safe_fields: dict[str, _JsonValue] = {}
    for key in allowlist:
        if key == "id":
            continue
        if key in raw_fields:
            raw_value = raw_fields[key]
        elif key in raw:
            raw_value = raw[key]
        else:
            continue
        safe_fields[key] = _clean_json(raw_value, path=f"{node_id}.{key}")
    references = set()
    for key, raw_value in safe_fields.items():
        if key in _REFERENCE_FIELDS:
            references.update(_reference_ids(raw_value))
    references.update(_raw_provenance_ids(raw, raw_fields))
    return ExportNode(
        id=node_id,
        node_type=node_type.value,
        fields=MappingProxyType(dict(sorted(safe_fields.items()))),
        provenance_ids=tuple(sorted(references)),
    )


@dataclass(frozen=True, slots=True)
class ExportNode:
    """One immutable, static-allowlisted node in an export."""

    id: str
    node_type: str
    fields: Mapping[str, _JsonValue]
    provenance_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.node_type,
            "fields": dict(self.fields),
            "provenance_ids": list(self.provenance_ids),
        }


@dataclass(frozen=True, slots=True)
class FounderGraphExport:
    """Deterministic safe export and its already-bounded renderings."""

    schema_version: str
    nodes: tuple[ExportNode, ...]
    provenance_ids: tuple[str, ...]
    next_cursor: str | None
    omitted_count: int
    owner_id: str = field(repr=False, compare=False)
    _json_text: str = field(repr=False, compare=False)
    _markdown: str = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": [node.as_dict() for node in self.nodes],
            "provenance_ids": list(self.provenance_ids),
            "next_cursor": self.next_cursor,
            "omitted_count": self.omitted_count,
        }

    @property
    def json_text(self) -> str:
        return self._json_text

    @property
    def markdown(self) -> str:
        return self._markdown

    def to_json(self) -> str:
        return self._json_text

    def to_markdown(self) -> str:
        return self._markdown


def _markdown_text(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in "`*_{}[]()#+-.!|":
        text = text.replace(character, f"\\{character}")
    return text


def _render_markdown(export: FounderGraphExport) -> str:
    lines = [
        "# Dots Founder Graph export",
        f"- schema_version: {_markdown_text(export.schema_version)}",
        f"- node_count: {len(export.nodes)}",
        f"- omitted_count: {export.omitted_count}",
        f"- provenance_ids: {_markdown_text(', '.join(export.provenance_ids) or '(none)')}",
    ]
    if export.next_cursor is not None:
        lines.append(f"- next_cursor: {_markdown_text(export.next_cursor)}")
    for node in export.nodes:
        lines.extend(("", f"## {_markdown_text(node.node_type)}: {_markdown_text(node.id)}"))
        if not node.fields:
            lines.append("- fields: (none)")
        for key, value in node.fields.items():
            serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            lines.append(f"- {_markdown_text(key)}: {_markdown_text(serialized)}")
        lines.append(f"- provenance_ids: {_markdown_text(', '.join(node.provenance_ids) or '(none)')}")
    return "\n".join(lines) + "\n"


def _build_export(
    values: Sequence[_ProjectionInput],
    *,
    owner_id: str,
    next_cursor: str | None,
    omitted_count: int,
    max_bytes: int,
    provenance_ids: Iterable[str] | str | None,
) -> FounderGraphExport:
    nodes: list[ExportNode] = []
    omitted = omitted_count
    for value in values:
        node = _safe_node(value, owner_id=owner_id)
        if node is None:
            omitted += 1
            continue
        nodes.append(node)
    nodes.sort(key=lambda item: (item.node_type, item.id, json.dumps(dict(item.fields), ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    aggregate_ids = set(_normalize_ids(provenance_ids, "provenance_ids"))
    for node in nodes:
        aggregate_ids.update(node.provenance_ids)
    export = FounderGraphExport(
        schema_version=EXPORT_SCHEMA_VERSION,
        nodes=tuple(nodes),
        provenance_ids=tuple(sorted(aggregate_ids)),
        next_cursor=next_cursor,
        omitted_count=omitted,
        owner_id=owner_id,
        _json_text="",
        _markdown="",
    )
    json_text = json.dumps(export.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    markdown = _render_markdown(export)
    if len(json_text.encode("utf-8")) > max_bytes or len(markdown.encode("utf-8")) > max_bytes:
        raise FounderGraphExportTooLargeError(f"safe export exceeds max_bytes={max_bytes}")
    return FounderGraphExport(
        schema_version=export.schema_version,
        nodes=export.nodes,
        provenance_ids=export.provenance_ids,
        next_cursor=export.next_cursor,
        omitted_count=export.omitted_count,
        owner_id=export.owner_id,
        _json_text=json_text,
        _markdown=markdown,
    )


def build_safe_export(
    source: GraphReadPort | _ProjectionInput | Iterable[_ProjectionInput],
    *,
    owner_id: str,
    query: str | None = None,
    node_ids: Sequence[str] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_EXPORT_LIMIT,
    timeout_ms: int = 1_000,
    max_bytes: int = DEFAULT_EXPORT_MAX_BYTES,
    provenance_ids: Iterable[str] | str | None = None,
) -> FounderGraphExport:
    """Build a bounded owner-scoped JSON/Markdown export.

    For a ``GraphReadPort``, provide either one bounded ``query`` or explicit
    ``node_ids``.  For direct safe mappings, pass one mapping or an iterable
    of mappings.  Read adapter failures are deliberately not caught so the
    caller can distinguish a stopped graph from an empty graph.
    """

    owner = _owner(owner_id)
    limit_value, max_bytes_value = _validate_limits(limit, max_bytes)
    is_read_port = callable(getattr(source, "search", None)) and callable(getattr(source, "fetch", None))
    if is_read_port:
        reads = source
        if getattr(reads, "owner_id", None) != owner:
            raise FounderGraphExportError("owner_id does not match the local graph owner")
        if query is not None and node_ids is not None:
            raise FounderGraphExportError("query and node_ids are mutually exclusive")
        if query is None and node_ids is None:
            raise FounderGraphExportError("query or node_ids is required for GraphReadPort export")
        if query is not None:
            query_value = _text(query, "query")
            if len(query_value) > 512:
                raise FounderGraphExportError("query must be at most 512 characters")
            page = reads.search(
                query_value,
                owner_id=owner,
                limit=limit_value,
                cursor=cursor,
                timeout_ms=timeout_ms,
            )
            hits = tuple(page.hits)
            if len(hits) > limit_value:
                raise FounderGraphExportLimitError("GraphReadPort returned more results than limit")
            return _build_export(
                hits,
                owner_id=owner,
                next_cursor=page.next_cursor,
                omitted_count=0,
                max_bytes=max_bytes_value,
                provenance_ids=provenance_ids,
            )
        if cursor is not None:
            raise FounderGraphExportError("cursor requires query")
        if isinstance(node_ids, (str, bytes, bytearray)):
            raise FounderGraphExportError("node_ids must be a sequence of strings")
        identifiers = tuple(_normalize_ids(node_ids, "node_ids", sort=False, max_items=limit_value))
        if len(identifiers) > limit_value:
            raise FounderGraphExportLimitError("node_ids exceeds limit")
        views = tuple(reads.fetch(identifier, owner_id=owner) for identifier in identifiers)
        return _build_export(
            views,
            owner_id=owner,
            next_cursor=None,
            omitted_count=0,
            max_bytes=max_bytes_value,
            provenance_ids=provenance_ids,
        )

    if query is not None or node_ids is not None or cursor is not None:
        raise FounderGraphExportError("query, node_ids, and cursor require a GraphReadPort")
    if isinstance(source, (NodeView, SearchHit, Mapping)):
        values: tuple[_ProjectionInput, ...] = (source,)
    else:
        if isinstance(source, (str, bytes, bytearray)) or not isinstance(source, Iterable):
            raise FounderGraphExportError("export input must be a safe projection or iterable of projections")
        values_list: list[_ProjectionInput] = []
        for value in source:
            if len(values_list) >= limit_value:
                raise FounderGraphExportLimitError("projection input exceeds limit")
            values_list.append(value)
        values = tuple(values_list)
    return _build_export(
        values,
        owner_id=owner,
        next_cursor=None,
        omitted_count=0,
        max_bytes=max_bytes_value,
        provenance_ids=provenance_ids,
    )


export_founder_graph = build_safe_export
build_founder_graph_export = build_safe_export


__all__ = [
    "DEFAULT_EXPORT_LIMIT",
    "DEFAULT_EXPORT_MAX_BYTES",
    "EXPORT_SCHEMA_VERSION",
    "ExportNode",
    "FounderGraphExport",
    "FounderGraphExportError",
    "FounderGraphExportLimitError",
    "FounderGraphExportTooLargeError",
    "MAX_EXPORT_BYTES",
    "MAX_EXPORT_LIMIT",
    "MAX_PROVENANCE_IDS",
    "build_founder_graph_export",
    "build_safe_export",
    "export_founder_graph",
]
