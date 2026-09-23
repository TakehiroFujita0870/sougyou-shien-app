"""Classify an approved follow-up before any Founder Graph write occurs.

This module does not infer an intent from prose and never starts research,
writes a graph node, or opens a network connection.  Its sole responsibility
is to turn an explicit caller choice into one unambiguous local write plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping


class FollowUpInputError(ValueError):
    """Raised when an explicit follow-up choice lacks its required reference."""


class FollowUpIntent(StrEnum):
    """The only caller-selected reasons for continuing a research campaign."""

    EXTERNAL_RESEARCH = "external_research"
    REPORT_RECOMPOSITION = "report_recomposition"
    TRANSPORT_RETRY = "transport_retry"


class FollowUpOperation(StrEnum):
    """The one storage operation permitted by each follow-up intent."""

    CREATE_RESEARCH_RUN = "create_research_run"
    CREATE_REPORT_VERSION = "create_report_version"
    RETRY_RESEARCH_RUN = "retry_research_run"


@dataclass(frozen=True, slots=True)
class FollowUpPlan:
    """A pure, immutable instruction for a later persistence boundary."""

    operation: FollowUpOperation
    change_reason: str
    parent_run_id: str | None = None
    target_run_id: str | None = None
    parent_report_id: str | None = None
    input_snapshot: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.input_snapshot is not None:
            if not isinstance(self.input_snapshot, Mapping):
                raise FollowUpInputError("input_snapshot must be a mapping")
            object.__setattr__(self, "input_snapshot", _freeze_snapshot(self.input_snapshot))


def _identifier(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FollowUpInputError(f"{field_name} is required")
    return value.strip()


def _freeze_snapshot(value: Any, path: str = "input_snapshot") -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise FollowUpInputError(f"{path} must contain finite JSON-like numbers")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise FollowUpInputError(f"{path} must use string JSON-like keys")
            copied[key] = _freeze_snapshot(item, f"{path}.{key}")
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_snapshot(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise FollowUpInputError(f"{path} must contain only JSON-like values")


def _snapshot(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FollowUpInputError("input_snapshot is required")
    return _freeze_snapshot(value)


def _intent(value: FollowUpIntent | str) -> FollowUpIntent:
    try:
        return value if isinstance(value, FollowUpIntent) else FollowUpIntent(value)
    except (TypeError, ValueError) as error:
        raise FollowUpInputError("intent is not supported") from error


def classify_follow_up(
    intent: FollowUpIntent | str,
    *,
    prior_run_id: str | None = None,
    prior_report_id: str | None = None,
    input_snapshot: Mapping[str, Any] | None = None,
) -> FollowUpPlan:
    """Return the one safe persistence plan for an explicit follow-up choice.

    A new external investigation receives a new run linked to the prior run.
    A report-only recomposition receives a new report version linked to the
    prior report.  A transport retry retains the existing run identity.
    """

    selected_intent = _intent(intent)
    if selected_intent is FollowUpIntent.EXTERNAL_RESEARCH:
        return FollowUpPlan(
            operation=FollowUpOperation.CREATE_RESEARCH_RUN,
            change_reason="additional_external_research",
            parent_run_id=_identifier(prior_run_id, "prior_run_id"),
            input_snapshot=_snapshot(input_snapshot),
        )
    if selected_intent is FollowUpIntent.REPORT_RECOMPOSITION:
        return FollowUpPlan(
            operation=FollowUpOperation.CREATE_REPORT_VERSION,
            change_reason="report_recomposition",
            parent_report_id=_identifier(prior_report_id, "prior_report_id"),
        )
    return FollowUpPlan(
        operation=FollowUpOperation.RETRY_RESEARCH_RUN,
        change_reason="transport_retry",
        target_run_id=_identifier(prior_run_id, "prior_run_id"),
    )


__all__ = [
    "FollowUpInputError",
    "FollowUpIntent",
    "FollowUpOperation",
    "FollowUpPlan",
    "classify_follow_up",
]
