"""Deterministic local low-risk execution-plan contract; not financial or legal advice."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


ConstraintCategory = Literal["employee", "childcare", "caregiving", "weekend_only"]


class ExecutionInputError(ValueError):
    pass


class SmallExperiment(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    weekly_hours: Decimal = Field(gt=0)
    spend: Decimal = Field(ge=0)
    reversible: bool


class ExecutionPlanInput(BaseModel):
    weekly_hours_limit: Decimal = Field(gt=0)
    weekly_hours_committed: Decimal = Field(ge=0)
    household_fund_limit: Decimal = Field(ge=0)
    planned_spend: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    constraint_categories: list[ConstraintCategory] = Field(min_length=1, max_length=4)
    small_experiment: SmallExperiment
    withdrawal_condition: str = Field(max_length=500)
    required_resources: list[str] = Field(min_length=1, max_length=20)
    roadmap_steps: list[str] = Field(min_length=1, max_length=10)
    unit_economics_operating_profit: Decimal


class ExecutionPlanResult(BaseModel):
    safe_to_start: bool
    remaining_weekly_hours: Decimal
    remaining_household_fund: Decimal
    required_resources: list[str]
    roadmap_steps: list[str]
    funding_candidates: list[str]
    disclaimer: str


def evaluate_execution_plan(plan: ExecutionPlanInput) -> ExecutionPlanResult:
    total_hours = plan.weekly_hours_committed + plan.small_experiment.weekly_hours
    if total_hours > plan.weekly_hours_limit:
        raise ExecutionInputError("weekly_hours_exceeded")
    total_spend = plan.planned_spend + plan.small_experiment.spend
    if total_spend > plan.household_fund_limit:
        raise ExecutionInputError("household_fund_exceeded")
    if not plan.small_experiment.reversible:
        raise ExecutionInputError("experiment_must_be_reversible")
    if not plan.withdrawal_condition.strip():
        raise ExecutionInputError("withdrawal_condition_required")
    return ExecutionPlanResult(
        safe_to_start=True,
        remaining_weekly_hours=plan.weekly_hours_limit - total_hours,
        remaining_household_fund=plan.household_fund_limit - total_spend,
        required_resources=plan.required_resources,
        roadmap_steps=plan.roadmap_steps,
        funding_candidates=["self_funded_experiment", "official_conditions_check"],
        disclaimer="This local allocation is not financial advice, lending advice, investment advice, tax advice, or legal advice.",
    )
