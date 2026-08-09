"""Deterministic local unit-economics contract; not accounting, tax, or lending advice."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


ScenarioName = Literal["base", "upside", "downside"]


class CalculationInputError(ValueError):
    pass


class Money(BaseModel):
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ScenarioInput(BaseModel):
    name: ScenarioName
    price: Money
    variable_cost: Money
    cac: Money
    fixed_cost: Money
    sales_units: int = Field(ge=0)
    capacity_units: int = Field(gt=0)
    retention_periods: int = Field(gt=0)
    period_months: int = Field(gt=0)


class ScenarioResult(BaseModel):
    name: ScenarioName
    period_months: int
    revenue: Money
    variable_cost: Money
    contribution_margin: Money
    contribution_margin_rate: Decimal
    retention_contribution_margin: Money
    lifetime_value_to_cac_ratio: Decimal
    cac_payback_units: Decimal
    break_even_units: Decimal
    operating_profit: Money


class UnitEconomicsPlan(BaseModel):
    scenarios: list[ScenarioResult]
    disclaimer: str


def calculate_plan(scenarios: tuple[ScenarioInput, ...]) -> UnitEconomicsPlan:
    names = {scenario.name for scenario in scenarios}
    if names != {"base", "upside", "downside"} or len(scenarios) != 3:
        raise CalculationInputError("missing_scenarios")
    if len({scenario.period_months for scenario in scenarios}) != 1:
        raise CalculationInputError("period_mismatch")
    results = [_calculate(scenario) for scenario in scenarios]
    return UnitEconomicsPlan(
        scenarios=results,
        disclaimer="This deterministic local calculation is not accounting, tax, investment, or lending advice.",
    )


def _calculate(scenario: ScenarioInput) -> ScenarioResult:
    monies = (scenario.price, scenario.variable_cost, scenario.cac, scenario.fixed_cost)
    if len({money.currency for money in monies}) != 1:
        raise CalculationInputError("currency_mismatch")
    if scenario.price.amount <= 0:
        raise CalculationInputError("price_must_be_positive")
    if scenario.cac.amount <= 0:
        raise CalculationInputError("cac_must_be_positive")
    if scenario.sales_units > scenario.capacity_units:
        raise CalculationInputError("capacity_exceeded")
    margin_per_unit = scenario.price.amount - scenario.variable_cost.amount
    if margin_per_unit <= 0:
        raise CalculationInputError("contribution_margin_must_be_positive")
    currency = scenario.price.currency
    revenue = scenario.price.amount * scenario.sales_units
    variable_cost = scenario.variable_cost.amount * scenario.sales_units
    contribution_margin = revenue - variable_cost
    retention_contribution_margin = margin_per_unit * scenario.retention_periods
    return ScenarioResult(
        name=scenario.name,
        period_months=scenario.period_months,
        revenue=Money(amount=revenue, currency=currency),
        variable_cost=Money(amount=variable_cost, currency=currency),
        contribution_margin=Money(amount=contribution_margin, currency=currency),
        contribution_margin_rate=margin_per_unit / scenario.price.amount,
        retention_contribution_margin=Money(amount=retention_contribution_margin, currency=currency),
        lifetime_value_to_cac_ratio=retention_contribution_margin / scenario.cac.amount,
        cac_payback_units=scenario.cac.amount / margin_per_unit,
        break_even_units=scenario.fixed_cost.amount / margin_per_unit,
        operating_profit=Money(amount=contribution_margin - scenario.fixed_cost.amount, currency=currency),
    )
