"""Owner-scoped, bounded read composition for Campaign comparison.

This module deliberately depends only on ``GraphReadPort``.  It narrows the
safe node views again before handing them to a UI or later MCP composition
layer; it never creates a driver, writes a node, or calls an external model.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .founder_graph import NodeType
from .founder_graph_read import GraphReadPort, NodeView
from .founder_graph_report_diff import SafeReportVersion, project_report_version


class CampaignComparisonInputError(ValueError):
    """Raised when a comparison request cannot be bounded safely."""


_CAMPAIGN_FIELDS = ("purpose", "status", "trial_budget", "run_count")
_RUN_FIELDS = ("status", "model_snapshot", "created_at", "finished_at")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise CampaignComparisonInputError(f"{label} must be a non-empty string of at most 256 characters")
    return value.strip()


def _scalar(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _safe_mapping(node: NodeView, field_names: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {"id": node.id}
    fields = node.fields if isinstance(node.fields, Mapping) else {}
    for name in field_names:
        value = _scalar(fields.get(name))
        if value:
            result[name] = value
    return result


def project_campaign_node(node: NodeView, *, owner_id: str) -> Mapping[str, str]:
    """Project one campaign node using only display-safe scalar fields."""

    if node.owner_id != owner_id or node.node_type != NodeType.RESEARCH_CAMPAIGN.value:
        raise CampaignComparisonInputError("node is not an owner-scoped research campaign")
    return MappingProxyType(_safe_mapping(node, _CAMPAIGN_FIELDS))


def project_run_node(node: NodeView, *, owner_id: str, campaign_id: str) -> Mapping[str, str] | None:
    """Project a run only when its owner and campaign endpoint both match."""

    if node.owner_id != owner_id or node.node_type != NodeType.RESEARCH_RUN.value:
        return None
    fields = node.fields if isinstance(node.fields, Mapping) else {}
    if _scalar(fields.get("campaign_id")) != campaign_id:
        return None
    return MappingProxyType(_safe_mapping(node, _RUN_FIELDS))


def project_report_node(node: NodeView, *, owner_id: str) -> SafeReportVersion:
    """Convert a safe report node to the fixed eight-chapter projection."""

    if node.owner_id != owner_id or node.node_type != NodeType.REPORT_VERSION.value:
        raise CampaignComparisonInputError("node is not an owner-scoped report version")
    fields = dict(node.fields) if isinstance(node.fields, Mapping) else {}
    fields["id"] = node.id
    report = project_report_version(fields)
    if report is None:
        raise CampaignComparisonInputError("report version is missing")
    return report


@dataclass(frozen=True, slots=True)
class CampaignComparisonProjection:
    """Immutable payload consumed by Campaign comparison UI composition."""

    owner_id: str
    campaign: Mapping[str, str]
    runs: tuple[Mapping[str, str], ...]
    previous_report: SafeReportVersion | None = None
    current_report: SafeReportVersion | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "campaign": dict(self.campaign),
            "runs": [dict(run) for run in self.runs],
            "previous_report": self.previous_report.as_dict() if self.previous_report else None,
            "current_report": self.current_report.as_dict() if self.current_report else None,
        }


def load_campaign_comparison(
    read_port: GraphReadPort,
    campaign_id: str,
    *,
    owner_id: str,
    previous_report_id: str | None = None,
    current_report_id: str | None = None,
    limit: int = 50,
    timeout_ms: int = 1_000,
) -> CampaignComparisonProjection:
    """Load one safe Campaign comparison with exactly one fetch and one search.

    GraphRead errors are intentionally allowed to propagate so the transport
    layer can preserve ``not_found``, ``unavailable`` and timeout semantics.
    """

    owner = _identifier(owner_id, "owner_id")
    identifier = _identifier(campaign_id, "campaign_id")
    if read_port.owner_id != owner:
        raise CampaignComparisonInputError("owner_id does not match the local read owner")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise CampaignComparisonInputError("limit must be between 1 and 50")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30_000:
        raise CampaignComparisonInputError("timeout_ms must be between 1 and 30000")

    campaign_node = read_port.fetch(identifier, owner_id=owner)
    campaign = project_campaign_node(campaign_node, owner_id=owner)
    page = read_port.search(identifier, owner_id=owner, limit=limit, timeout_ms=timeout_ms)
    runs_by_id: dict[str, Mapping[str, str]] = {}
    for hit in page.hits:
        projected = project_run_node(hit.node, owner_id=owner, campaign_id=identifier)
        if projected is not None:
            runs_by_id.setdefault(projected["id"], projected)

    previous = None
    if previous_report_id is not None:
        previous = project_report_node(read_port.fetch(_identifier(previous_report_id, "previous_report_id"), owner_id=owner), owner_id=owner)
    current = None
    if current_report_id is not None:
        current = project_report_node(read_port.fetch(_identifier(current_report_id, "current_report_id"), owner_id=owner), owner_id=owner)
    return CampaignComparisonProjection(
        owner_id=owner,
        campaign=campaign,
        runs=tuple(runs_by_id[key] for key in sorted(runs_by_id)),
        previous_report=previous,
        current_report=current,
    )


__all__ = [
    "CampaignComparisonInputError",
    "CampaignComparisonProjection",
    "load_campaign_comparison",
    "project_campaign_node",
    "project_report_node",
    "project_run_node",
]
