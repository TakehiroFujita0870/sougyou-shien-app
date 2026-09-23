"""Read-only MCP-shaped adapter for the local Founder Graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote

from .founder_graph import NodeType, RelationType, SHAREABLE_PROJECTION_ALLOWLIST
from .founder_graph_read import (
    GraphReadError,
    GraphReadPort,
    GraphReadNotFoundError,
    GraphReadTimeoutError,
    GraphReadUnavailableError,
)


class McpReadError(Exception):
    """A safe, machine-readable read-surface error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class McpReadSurface:
    reads: GraphReadPort

    def tool_definitions(self) -> tuple[Mapping[str, Any], ...]:
        return (
            {
                "name": "search",
                "description": "Search the local Founder Graph and return safe shareable result summaries.",
                "readOnly": True,
                "inputSchema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "maxLength": 512},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        "cursor": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "fetch",
                "description": "Fetch one safe shareable Founder Graph result by canonical id.",
                "readOnly": True,
                "inputSchema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 200}},
                    "additionalProperties": False,
                },
            },
        )

    def call(self, tool_name: str, arguments: Mapping[str, Any], *, owner_id: str) -> dict[str, Any]:
        if tool_name not in {"search", "fetch"}:
            raise McpReadError("unknown_tool", "Only the read-only search and fetch tools are available.")
        if not isinstance(arguments, Mapping):
            raise McpReadError("invalid_input", "Tool arguments must be an object.")
        try:
            if tool_name == "search":
                return self._search(arguments, owner_id=owner_id)
            return self._fetch(arguments, owner_id=owner_id)
        except GraphReadTimeoutError as error:
            raise McpReadError("read_timeout", str(error)) from error
        except GraphReadUnavailableError as error:
            raise McpReadError("unavailable", "The local Founder Graph is unavailable; retry after it starts.") from error
        except GraphReadNotFoundError as error:
            raise McpReadError("not_found", "The requested graph result was not found.") from error
        except GraphReadError as error:
            raise McpReadError("invalid_input", str(error)) from error

    def _search(self, arguments: Mapping[str, Any], *, owner_id: str) -> dict[str, Any]:
        self._reject_unknown(arguments, {"query", "limit", "cursor"})
        query = arguments.get("query")
        limit = arguments.get("limit", 20)
        cursor = arguments.get("cursor")
        page = self.reads.search(query, owner_id=owner_id, limit=limit, cursor=cursor)
        return {
            "results": [
                result
                for result in (self._project_hit(hit, owner_id=owner_id) for hit in page.hits)
                if result is not None
            ],
            "next_cursor": page.next_cursor,
        }

    def _fetch(self, arguments: Mapping[str, Any], *, owner_id: str) -> dict[str, Any]:
        self._reject_unknown(arguments, {"id"})
        identifier = arguments.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200:
            raise McpReadError("invalid_input", "id must be a non-empty string of at most 200 characters.")
        view = self.reads.fetch(identifier, owner_id=owner_id)
        result = self._project_view(view)
        if result is None:
            raise McpReadError("not_found", "The requested graph result was not found.")
        return result

    @staticmethod
    def _reject_unknown(arguments: Mapping[str, Any], allowed: set[str]) -> None:
        unknown = set(arguments).difference(allowed)
        if unknown:
            raise McpReadError("invalid_input", "Unknown tool arguments are not accepted.")

    def _project_hit(self, hit, *, owner_id: str) -> dict[str, Any] | None:
        result = self._project_view(hit.node)
        if result is not None and hit.path and self._shareable_relation_path(hit, owner_id=owner_id):
            result["relation_path"] = list(hit.path)
            evidence_ids = self._shareable_evidence_ids(hit.evidence_ids, owner_id=owner_id)
            if evidence_ids:
                result["evidence_ids"] = list(evidence_ids)
        return result

    def _shareable_relation_path(self, hit, *, owner_id: str) -> bool:
        path = hit.path
        if (
            not isinstance(path, (tuple, list))
            or len(path) < 3
            or len(path) % 2 == 0
            or not all(isinstance(item, str) and item.strip() for item in path)
            or hit.node.id not in {path[0], path[-1]}
        ):
            return False
        try:
            for index in range(1, len(path), 2):
                RelationType(path[index])
                left = self.reads.fetch(path[index - 1], owner_id=owner_id)
                right = self.reads.fetch(path[index + 1], owner_id=owner_id)
                if self._project_view(left) is None or self._project_view(right) is None:
                    return False
        except (GraphReadError, TypeError, ValueError):
            return False
        return True

    def _shareable_evidence_ids(self, evidence_ids: tuple[str, ...], *, owner_id: str) -> tuple[str, ...]:
        safe_ids: list[str] = []
        for evidence_id in evidence_ids:
            try:
                evidence = self.reads.fetch(evidence_id, owner_id=owner_id)
            except GraphReadError:
                continue
            if self._project_view(evidence) is not None:
                safe_ids.append(evidence_id)
        return tuple(dict.fromkeys(safe_ids))

    @staticmethod
    def _project_view(view) -> dict[str, Any] | None:
        fields = dict(view.fields)
        # Missing policy is local_only by contract. Explicit projections need a
        # current campaign context and therefore never pass this read surface.
        if fields.get("egress_policy") != "shareable":
            return None
        try:
            node_type = NodeType(view.node_type)
        except (TypeError, ValueError):
            return None
        # GraphReadService intentionally retains a wider local view for the UI
        # and local workflows.  The MCP boundary must narrow that view again
        # to the domain's static shareable projection; a denylist here would
        # eventually leak newly-added private fields.
        safe_fields = {
            key: value
            for key, value in fields.items()
            if key in SHAREABLE_PROJECTION_ALLOWLIST.get(node_type, ())
        }
        safe_title = next(
            (str(safe_fields[key]) for key in ("title", "name", "display_name", "text", "purpose") if safe_fields.get(key)),
            str(view.id),
        )
        safe_snippet = next(
            (str(safe_fields[key]) for key in ("summary", "description", "content", "excerpt", "text", "purpose") if safe_fields.get(key)),
            safe_title,
        )
        result: dict[str, Any] = {
            "id": view.id,
            "kind": view.node_type,
            "title": safe_title,
            "snippet": safe_snippet[:320],
            "canonical_url": f"dots://node/{quote(view.id, safe='')}",
            "untrusted_text": safe_snippet[:320],
            "fields": safe_fields,
        }
        for key in ("locator", "content_hash", "source_id"):
            if key in safe_fields and safe_fields[key] is not None:
                result[key] = safe_fields[key]
        if "content" in safe_fields:
            result["text"] = str(safe_fields["content"])
        return result
