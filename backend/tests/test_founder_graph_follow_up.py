from __future__ import annotations

import pytest

from dots.founder_graph_follow_up import (
    FollowUpInputError,
    FollowUpIntent,
    FollowUpOperation,
    classify_follow_up,
)


def test_new_external_research_creates_a_distinct_child_run_plan() -> None:
    snapshot = {"question": "市場規模を再確認する", "scope": {"shareable": True}}
    plan = classify_follow_up(
        FollowUpIntent.EXTERNAL_RESEARCH,
        prior_run_id="run-previous",
        input_snapshot=snapshot,
    )
    snapshot["scope"]["shareable"] = False  # type: ignore[index]

    assert plan.operation is FollowUpOperation.CREATE_RESEARCH_RUN
    assert plan.parent_run_id == "run-previous"
    assert plan.input_snapshot == {"question": "市場規模を再確認する", "scope": {"shareable": True}}
    with pytest.raises(TypeError):
        plan.input_snapshot["scope"]["shareable"] = False  # type: ignore[index]
    assert plan.parent_report_id is None
    assert plan.change_reason == "additional_external_research"


def test_report_recomposition_creates_a_child_report_without_a_new_run() -> None:
    plan = classify_follow_up(
        "report_recomposition",
        prior_report_id="report-previous",
    )

    assert plan.operation is FollowUpOperation.CREATE_REPORT_VERSION
    assert plan.parent_report_id == "report-previous"
    assert plan.parent_run_id is None
    assert plan.input_snapshot is None
    assert plan.change_reason == "report_recomposition"


def test_transport_retry_keeps_the_existing_run_identity() -> None:
    plan = classify_follow_up(
        "transport_retry",
        prior_run_id="run-open",
    )

    assert plan.operation is FollowUpOperation.RETRY_RESEARCH_RUN
    assert plan.target_run_id == "run-open"
    assert plan.parent_run_id is None
    assert plan.parent_report_id is None
    assert plan.change_reason == "transport_retry"


@pytest.mark.parametrize(
    ("intent", "kwargs", "message"),
    [
        ("external_research", {}, "prior_run_id"),
        ("external_research", {"prior_run_id": "run-1"}, "input_snapshot"),
        ("report_recomposition", {}, "prior_report_id"),
        ("transport_retry", {}, "prior_run_id"),
        ("unknown", {}, "intent"),
    ],
)
def test_invalid_follow_up_requests_are_rejected_before_any_execution(
    intent: str,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(FollowUpInputError, match=message):
        classify_follow_up(intent, **kwargs)
