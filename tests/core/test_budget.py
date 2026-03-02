from __future__ import annotations

from investment_planner.calc_stock_units import calculate_buy_units
from investment_planner.io_json import load_portfolio
from investment_planner.planning import compute_invest_budget, plan_invest_no_sell
from tests.core.helpers import D, make_valid_data


def test_compute_invest_budget_basic():
    p = load_portfolio(make_valid_data(cash_value="12000", cash_reserve="2000", cash_future_tax="500"))
    assert compute_invest_budget(p) == D("9500")


def test_compute_invest_budget_floors_at_zero():
    p = load_portfolio(make_valid_data(cash_value="1000", cash_reserve="900", cash_future_tax="200"))
    assert compute_invest_budget(p) == D("0")


def test_stock_unit_calculation_uses_budget_reduced_by_future_tax():
    data = make_valid_data(
        cash_value="1000",
        cash_reserve="100",
        cash_future_tax="200",
        group_targets=(("g1", "Asset 1", "100"),),
        instruments=[
            {
                "id": "i1",
                "name": "Inst 1",
                "value": "500",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            }
        ],
    )
    p = load_portfolio(data)

    plan_rows = plan_invest_no_sell(p)
    assert len(plan_rows) == 1
    assert plan_rows[0].planned_delta_money == D("700")

    calc = calculate_buy_units(
        instrument_id="i1",
        planned_money=plan_rows[0].planned_delta_money,
        price_ag=D("30000"),
    )
    assert calc.units == 2
    assert calc.spent == D("600")
    assert calc.leftover == D("100")

