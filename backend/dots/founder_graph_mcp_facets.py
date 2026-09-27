"""Small MCP catalog/dispatch adapters for existing Facet graph contracts."""

from __future__ import annotations

from typing import Any, Mapping

from .founder_graph import EgressPolicy, Facet, Provenance, RelationType
from .founder_graph_mcp_annotations import mcp_tool_annotations


FACET_WRITE_TOOL_NAMES = ("capture_facet", "classify_entity", "relate_facets")


def facet_write_tool_definitions() -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "name": "capture_facet",
            "description": "所有者の分類語を1件作成します。明示的に共有可能と指定しない限り、ローカル限定で保存します。",
            "readOnly": False,
            "annotations": mcp_tool_annotations(read_only=False),
            "inputSchema": {
                "type": "object",
                "required": ["namespace", "value", "idempotency_key"],
                "properties": {
                    "namespace": {"type": "string", "minLength": 1, "maxLength": 120},
                    "value": {"type": "string", "minLength": 1, "maxLength": 240},
                    "egress_policy": {"type": "string", "enum": [item.value for item in EgressPolicy]},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "classify_entity",
            "description": "根拠に基づく分類を追加します。複数のFacetや名前空間を併用できます。",
            "readOnly": False,
            "annotations": mcp_tool_annotations(read_only=False),
            "inputSchema": {
                "type": "object",
                "required": ["entity_id", "facet_id", "evidence_ids", "idempotency_key"],
                "properties": {
                    "entity_id": {"type": "string", "minLength": 1},
                    "facet_id": {"type": "string", "minLength": 1},
                    "evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                    "status": {"type": "string", "enum": ["proposed", "inferred"]},
                    "egress_policy": {"type": "string", "enum": ["local_only", "shareable"]},
                    "based_on_brief_id": {"type": "string", "minLength": 1},
                    "based_on_brief_section_index": {"type": "integer", "minimum": 0, "maximum": 7},
                    "supersedes_id": {"type": "string", "minLength": 1},
                    "expected_family_revision": {"type": "integer", "minimum": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "relate_facets",
            "description": "根拠に基づく上位から下位へのFacet関係を追加します。現行の関係先端を対象に、グラフ保存時に循環を検査します。",
            "readOnly": False,
            "annotations": mcp_tool_annotations(read_only=False),
            "inputSchema": {
                "type": "object",
                "required": ["broader_facet_id", "narrower_facet_id", "evidence_ids", "idempotency_key"],
                "properties": {
                    "broader_facet_id": {"type": "string", "minLength": 1},
                    "narrower_facet_id": {"type": "string", "minLength": 1},
                    "evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                    "status": {"type": "string", "enum": ["proposed", "inferred"]},
                    "egress_policy": {"type": "string", "enum": ["local_only", "shareable"]},
                    "supersedes_id": {"type": "string", "minLength": 1},
                    "expected_family_revision": {"type": "integer", "minimum": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
    )


def dispatch_facet_write(surface: Any, tool_name: str, arguments: Mapping[str, Any]):
    """Dispatch narrow Facet tools through existing canonical graph writes."""

    if tool_name == "capture_facet":
        surface._reject_unknown(arguments, {"namespace", "value", "egress_policy", "idempotency_key"})
        key = surface._idempotency(arguments)
        policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value))
        facet_id = surface._command_id("facet", key)
        facet = Facet(
            owner_id=surface.writes.owner_id,
            id=facet_id,
            namespace=surface._text(arguments.get("namespace"), "namespace", max_length=120),
            value=surface._text(arguments.get("value"), "value", max_length=240),
            egress_policy=policy,
            provenance=Provenance(actor="local-owner", operation="capture_facet", target_id=facet_id, idempotency_key=key),
        )
        return surface.writes.put_node(facet, idempotency_key=key, operation="capture_facet")
    if tool_name == "classify_entity":
        surface._reject_unknown(arguments, {
            "entity_id", "facet_id", "evidence_ids", "status", "egress_policy",
            "based_on_brief_id", "based_on_brief_section_index", "supersedes_id",
            "expected_family_revision", "idempotency_key",
        })
        return surface._link_entities({
            "source_id": arguments.get("entity_id"),
            "target_id": arguments.get("facet_id"),
            "relation": RelationType.CLASSIFIED_AS.value,
            "evidence_ids": arguments.get("evidence_ids"),
            "status": arguments.get("status", "proposed"),
            "egress_policy": arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value),
            "based_on_brief_id": arguments.get("based_on_brief_id"),
            "based_on_brief_section_index": arguments.get("based_on_brief_section_index"),
            "supersedes_id": arguments.get("supersedes_id"),
            "expected_family_revision": arguments.get("expected_family_revision"),
            "idempotency_key": arguments.get("idempotency_key"),
        })
    if tool_name == "relate_facets":
        surface._reject_unknown(arguments, {
            "broader_facet_id", "narrower_facet_id", "evidence_ids", "status", "egress_policy",
            "supersedes_id", "expected_family_revision", "idempotency_key",
        })
        return surface._link_entities({
            "source_id": arguments.get("broader_facet_id"),
            "target_id": arguments.get("narrower_facet_id"),
            "relation": RelationType.CLASSIFIED_AS.value,
            "evidence_ids": arguments.get("evidence_ids"),
            "status": arguments.get("status", "proposed"),
            "egress_policy": arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value),
            "supersedes_id": arguments.get("supersedes_id"),
            "expected_family_revision": arguments.get("expected_family_revision"),
            "idempotency_key": arguments.get("idempotency_key"),
        })
    raise ValueError("unknown Facet write tool")


def facet_read_tool_definitions() -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "name": "search_facets",
            "description": "Founder Graph内の現行かつ共有可能なFacet語だけを検索します。",
            "readOnly": True,
            "annotations": mcp_tool_annotations(read_only=True),
            "inputSchema": {
                "type": "object", "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 512},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "cursor": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "facet_region",
            "description": "Facetと、根拠に基づく下位Facetに分類された現行かつ共有可能なアイデアや資産を探します。",
            "readOnly": True,
            "annotations": mcp_tool_annotations(read_only=True),
            "inputSchema": {
                "type": "object", "required": ["facet_id"],
                "properties": {"facet_id": {"type": "string", "minLength": 1, "maxLength": 200}, "max_facet_depth": {"type": "integer", "minimum": 0, "maximum": 8}},
                "additionalProperties": False,
            },
        },
    )


__all__ = ["FACET_WRITE_TOOL_NAMES", "dispatch_facet_write", "facet_read_tool_definitions", "facet_write_tool_definitions"]
