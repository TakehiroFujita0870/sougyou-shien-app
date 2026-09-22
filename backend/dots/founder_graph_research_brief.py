"""Pure, owner-scoped preflight composition for the Founder Graph.

The builder deliberately consumes only ``GraphReadPort``.  It performs no
network access, model call, write-back, scheduling, or authorization upgrade.
Only the ordinary ``shareable`` projection is eligible for this first slice;
campaign-scoped ``explicit`` data belongs to the ResearchCampaign contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import quote

from .founder_graph import NodeType
from .founder_graph_read import GraphReadError, GraphReadPort, NodeView, SearchHit


_CATEGORY_BY_NODE_TYPE: dict[str, str] = {
    NodeType.IDEA.value: "ideas",
    NodeType.ASSET.value: "assets",
    NodeType.SOURCE.value: "sources",
    NodeType.SOURCE_REVISION.value: "sources",
    NodeType.RESEARCH_MATERIAL.value: "sources",
}
_PRIVATE_FIELDS = frozenset({
    "contact",
    "details",
    "private_notes",
    "source_text",
})


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _safe_fields(view: NodeView) -> Mapping[str, Any] | None:
    fields = dict(view.fields)
    if fields.get("egress_policy") != "shareable":
        return None
    result: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _PRIVATE_FIELDS:
            continue
        # ``content`` is a source body and is represented by the same neutral
        # text key used by the read MCP projection.  It is retained only after
        # the node's explicit shareable policy has passed.
        result["text" if key == "content" else key] = value
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class ResearchBriefItem:
    """One safe, externally addressable preflight result."""

    id: str
    node_type: str
    category: str
    title: str
    snippet: str
    score: float
    relation_path: tuple[str, ...]
    canonical_url: str
    fields: Mapping[str, Any]
    egress_policy: str = "shareable"
    sensitivity: str = "shareable"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.node_type,
            "category": self.category,
            "title": self.title,
            "snippet": self.snippet,
            "score": self.score,
            "relation_path": list(self.relation_path),
            "canonical_url": self.canonical_url,
            "egress_policy": self.egress_policy,
            "sensitivity": self.sensitivity,
            "fields": _json_value(self.fields),
        }


@dataclass(frozen=True, slots=True)
class ResearchBrief:
    """An immutable, paginated local preflight result."""

    query: str
    items: tuple[ResearchBriefItem, ...]
    next_cursor: str | None
    omitted_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "items": [item.as_dict() for item in self.items],
            "next_cursor": self.next_cursor,
            "omitted_count": self.omitted_count,
        }


def _brief_item(hit: SearchHit) -> ResearchBriefItem | None:
    category = _CATEGORY_BY_NODE_TYPE.get(hit.node.node_type)
    if category is None:
        return None
    fields = _safe_fields(hit.node)
    if fields is None:
        return None
    return ResearchBriefItem(
        id=hit.node.id,
        node_type=hit.node.node_type,
        category=category,
        title=hit.node.title,
        snippet=hit.node.snippet,
        score=float(hit.score),
        relation_path=tuple(str(part) for part in hit.path),
        canonical_url=f"dots://node/{quote(hit.node.id, safe='')}",
        fields=fields,
    )


def build_research_brief(
    reads: GraphReadPort,
    query: str,
    *,
    owner_id: str,
    limit: int = 50,
    timeout_ms: int = 1_000,
) -> ResearchBrief:
    """Compose a bounded, shareable preflight brief from local graph search."""

    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise GraphReadError("query must be a non-empty string of at most 512 characters")
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise GraphReadError("owner_id is required")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise GraphReadError("limit must be between 1 and 50")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30_000:
        raise GraphReadError("timeout_ms must be between 1 and 30000")
    owner = owner_id.strip()
    if reads.owner_id != owner:
        raise GraphReadError("owner_id does not match the local graph owner")

    # One bounded search call is intentional.  ``next_cursor`` lets the caller
    # request another preflight page without making the builder an unbounded
    # scanner or silently widening the read budget.
    page = reads.search(query.strip(), owner_id=owner, limit=limit, timeout_ms=timeout_ms)
    items = tuple(item for hit in page.hits if (item := _brief_item(hit)) is not None)
    return ResearchBrief(
        query=query.strip(),
        items=items,
        next_cursor=page.next_cursor,
        omitted_count=len(page.hits) - len(items),
    )


__all__ = ["ResearchBrief", "ResearchBriefItem", "build_research_brief"]
