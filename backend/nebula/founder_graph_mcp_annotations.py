"""Shared side-effect annotations for Founder Graph tool catalogs."""

from __future__ import annotations


def mcp_tool_annotations(*, read_only: bool, destructive: bool = False) -> dict[str, bool]:
    """Return complete, truthful annotations for this bounded private service."""

    if read_only and destructive:
        raise ValueError("a read-only tool cannot be destructive")
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "openWorldHint": False,
    }
