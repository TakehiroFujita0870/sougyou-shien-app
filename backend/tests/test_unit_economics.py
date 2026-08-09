from decimal import Decimal

import pytest

from kadode_api.unit_economics import CalculationInputError, Money, ScenarioInput, calculate_plan


def yen(value: str) -> Money:
    return Money(amount=Decimal(value), currency="JPY")


def scenario(name: str, *, units: int = 20, price: str = "1000", variable_cost: str = "400") -> ScenarioInput:
    return ScenarioInput(
        name=name,
        price=yen(price),
        variable_cost=yen(variable_cost),
        cac=yen("300"),
        fixed_cost=yen("6000"),
        sales_units=units,
        capacity_units=30,
        retention_periods=4,
        period_months=1,
    )


def test_calculates_base_upside_downside_with_deterministic_unit_economics() -> None:
    result = calculate_plan((scenario("base"), scenario("upside", units=25), scenario("downside", units=10)))
    base = result.scenarios[0]
    assert [item.name for item in result.scenarios] == ["base", "upside", "downside"]
    assert base.revenue == yen("20000")
    assert base.contribution_margin == yen("12000")
    assert base.contribution_margin_rate == Decimal("0.6")
    assert base.cac_payback_units == Decimal("0.5")
    assert base.break_even_units == Decimal("10")
    assert base.operating_profit == yen("6000")
    assert "tax" in result.disclaimer.lower()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [("price", yen("0"), "price_must_be_positive"), ("variable_cost", yen("1000"), "contribution_margin_must_be_positive")],
)
def test_rejects_zero_division_and_non_positive_margin(field: str, value: Money, reason: str) -> None:
    input_value = scenario("base")
    with pytest.raises(CalculationInputError, match=reason):
        calculate_plan((input_value.model_copy(update={field: value}), scenario("upside"), scenario("downside")))


def test_rejects_currency_mixing_capacity_overflow_and_missing_scenario() -> None:
    mixed = scenario("base").model_copy(update={"cac": Money(amount=Decimal("1"), currency="USD")})
    with pytest.raises(CalculationInputError, match="currency_mismatch"):
        calculate_plan((mixed, scenario("upside"), scenario("downside")))
    overflow = scenario("base").model_copy(update={"sales_units": 31})
    with pytest.raises(CalculationInputError, match="capacity_exceeded"):
        calculate_plan((overflow, scenario("upside"), scenario("downside")))
    mixed_period = scenario("upside").model_copy(update={"period_months": 2})
    with pytest.raises(CalculationInputError, match="period_mismatch"):
        calculate_plan((scenario("base"), mixed_period, scenario("downside")))
    with pytest.raises(CalculationInputError, match="missing_scenarios"):
        calculate_plan((scenario("base"), scenario("upside")))
