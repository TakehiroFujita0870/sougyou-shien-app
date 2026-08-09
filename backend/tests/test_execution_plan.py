from decimal import Decimal

import pytest

from kadode_api.execution_plan import ExecutionInputError, ExecutionPlanInput, SmallExperiment, evaluate_execution_plan


def plan(**overrides: object) -> ExecutionPlanInput:
    values = {
        "weekly_hours_limit": Decimal("8"),
        "weekly_hours_committed": Decimal("4"),
        "household_fund_limit": Decimal("30000"),
        "planned_spend": Decimal("10000"),
        "currency": "JPY",
        "constraint_categories": ["employee", "childcare", "weekend_only"],
        "small_experiment": SmallExperiment(title="週末の顧客課題インタビュー", weekly_hours=Decimal("2"), spend=Decimal("5000"), reversible=True),
        "withdrawal_condition": "検証費が上限に達したら停止する",
        "required_resources": ["interview_script", "prototype"],
        "roadmap_steps": ["problem_check", "small_experiment", "review"],
        "unit_economics_operating_profit": Decimal("6000"),
    }
    values.update(overrides)
    return ExecutionPlanInput(**values)


def test_returns_safe_allocation_for_employee_childcare_weekend_low_capital_fixture() -> None:
    result = evaluate_execution_plan(plan())
    assert result.remaining_weekly_hours == Decimal("2")
    assert result.remaining_household_fund == Decimal("15000")
    assert result.profit_funded_experiment_limit == Decimal("6000")
    assert result.safe_to_start is True
    assert result.funding_candidates == ["self_funded_experiment", "official_conditions_check"]
    assert result.required_resources == ["interview_script", "prototype"]
    assert result.roadmap_steps == ["problem_check", "small_experiment", "review"]
    assert "not financial advice" in result.disclaimer.lower()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"weekly_hours_committed": Decimal("7"), "small_experiment": SmallExperiment(title="x", weekly_hours=Decimal("2"), spend=Decimal("1"), reversible=True)}, "weekly_hours_exceeded"),
        ({"planned_spend": Decimal("29000"), "small_experiment": SmallExperiment(title="x", weekly_hours=Decimal("1"), spend=Decimal("2000"), reversible=True)}, "household_fund_exceeded"),
        ({"small_experiment": SmallExperiment(title="x", weekly_hours=Decimal("1"), spend=Decimal("1"), reversible=False)}, "experiment_must_be_reversible"),
        ({"withdrawal_condition": ""}, "withdrawal_condition_required"),
    ],
)
def test_rejects_unsafe_time_money_and_irreversible_actions(override: dict[str, object], reason: str) -> None:
    with pytest.raises(ExecutionInputError, match=reason):
        evaluate_execution_plan(plan(**override))


def test_rejects_personal_details_and_preserves_no_institution_recommendation() -> None:
    with pytest.raises(ValueError):
        plan(constraint_categories=["employee", "family-name"])
    result = evaluate_execution_plan(plan(constraint_categories=["caregiving", "weekend_only"]))
    assert all("bank" not in candidate.lower() for candidate in result.funding_candidates)


def test_unit_economics_profit_limits_experiment_funding() -> None:
    safe = evaluate_execution_plan(plan(unit_economics_operating_profit=Decimal("5000")))
    assert safe.profit_funded_experiment_limit == Decimal("5000")
    with pytest.raises(ExecutionInputError, match="unit_economics_funding_exceeded"):
        evaluate_execution_plan(plan(unit_economics_operating_profit=Decimal("-1")))
