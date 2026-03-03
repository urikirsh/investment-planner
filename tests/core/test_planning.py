from __future__ import annotations

"""
Planning algorithm behavior tests.

Includes invest-only and rebalance allocation behavior plus group->instrument
delta split semantics and defensive edge-path coverage.
"""

import pytest

import portfolio_core.planning as planning_mod
from portfolio_core.io_json import load_portfolio
from portfolio_core.models import AssetGroupPlanRow
from portfolio_core.planning import map_asset_group_deltas_to_instruments, plan_invest_no_sell, plan_rebalance
from tests.core.helpers import D, make_valid_data


def test_plan_invest_no_sell_empty_when_budget_zero():
    p = load_portfolio(make_valid_data(cash_value="2000", cash_reserve="2000"))
    assert plan_invest_no_sell(p) == []


def test_plan_invest_no_sell_preserves_group_order():
    group_targets = (("gA", "A", "30"), ("gB", "B", "30"), ("gC", "C", "40"))
    instruments = [
        {"id": "iA", "name": "iA", "value": "100", "investable": True, "groupId": "gA"},
        {"id": "iB", "name": "iB", "value": "100", "investable": True, "groupId": "gB"},
        {"id": "iC", "name": "iC", "value": "100", "investable": True, "groupId": "gC"},
    ]
    p = load_portfolio(make_valid_data(cash_value="300", cash_reserve="0.1", group_targets=group_targets, instruments=instruments))
    plan = plan_invest_no_sell(p)
    assert [r.asset_group_id for r in plan] == ["gA", "gB", "gC"]


def test_plan_invest_no_sell_excludes_overweight_groups_and_renormalizes():
    data = make_valid_data(
        cash_value="6000",
        cash_reserve="2000",
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    plan = plan_invest_no_sell(p)
    assert [r.asset_group_id for r in plan] == ["g2"]
    assert plan[0].planned_delta_money == D("4000")


def test_plan_rebalance_contains_buys_and_sells_in_group_order():
    data = make_valid_data(
        cash_value="12000",
        cash_reserve="2000",
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    rows = plan_rebalance(p)
    assert [r.asset_group_id for r in rows] == ["g1", "g2"]
    assert rows[0].planned_delta_money == D("10000") - D("9000")
    assert rows[1].planned_delta_money == D("10000") - D("1000")

    data2 = make_valid_data(
        cash_value="2000",
        cash_reserve="2000",
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p2 = load_portfolio(data2)
    rows2 = plan_rebalance(p2)
    assert rows2[0].planned_delta_money == D("5000") - D("9000")
    assert rows2[1].planned_delta_money == D("5000") - D("1000")


def test_map_asset_group_deltas_to_instruments_uses_post_investment_targets():
    data = make_valid_data(
        cash_value="1000",
        cash_reserve="0",
        group_targets=(("g1", "Gold", "100"),),
        instruments=[
            {"id": "d4", "name": "D4", "value": "200", "investable": True, "groupId": "g1", "targetInGroupPercentage": "50"},
            {"id": "d5", "name": "D5", "value": "100", "investable": True, "groupId": "g1", "targetInGroupPercentage": "50"},
        ],
    )
    p = load_portfolio(data)
    rows = plan_invest_no_sell(p)
    steps = map_asset_group_deltas_to_instruments(p, rows)
    by_id = {ins_id: delta for _, _, ins_id, delta in steps}
    assert by_id["d4"] == D("450")
    assert by_id["d5"] == D("550")
    assert sum(by_id.values(), D("0")) == rows[0].planned_delta_money


def test_map_asset_group_deltas_to_instruments_excludes_zero_pct_instruments():
    data = make_valid_data(
        cash_value="1000",
        cash_reserve="0",
        group_targets=(("g1", "Group", "100"),),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "300", "investable": True, "groupId": "g1", "targetInGroupPercentage": "100"},
            {"id": "i2", "name": "Inst 2", "value": "200", "investable": True, "groupId": "g1", "targetInGroupPercentage": "0"},
        ],
    )
    p = load_portfolio(data)
    rows = plan_invest_no_sell(p)
    steps = map_asset_group_deltas_to_instruments(p, rows)
    assert len(steps) == 1
    assert steps[0][2] == "i1"
    assert steps[0][3] == rows[0].planned_delta_money


def test_plan_invest_no_sell_defensive_return_when_pct_total_is_non_positive(monkeypatch):
    data = make_valid_data(
        group_targets=(("g1", "Asset 1", "0"), ("g2", "Asset 2", "0")),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "100", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "100", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    monkeypatch.setattr(planning_mod, "validate_portfolio", lambda _: None)
    assert planning_mod.plan_invest_no_sell(p) == []


def test_plan_invest_no_sell_defensive_when_all_active_groups_get_excluded(monkeypatch):
    data = make_valid_data(
        cash_value="1000",
        cash_reserve="0",
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "500", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "500", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    monkeypatch.setattr(planning_mod, "validate_portfolio", lambda _: None)
    monkeypatch.setattr(planning_mod, "compute_invest_budget", lambda _: D("-1"))
    assert planning_mod.plan_invest_no_sell(p) == []


def test_map_asset_group_deltas_to_instruments_uses_post_target_solver_for_zero_and_negative_group_deltas():
    data = make_valid_data(
        group_targets=(("g1", "Asset 1", "100"),),
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "200", "investable": True, "groupId": "g1", "targetInGroupPercentage": "50"},
            {"id": "i2", "name": "Inst 2", "value": "100", "investable": True, "groupId": "g1", "targetInGroupPercentage": "50"},
        ],
    )
    p = load_portfolio(data)

    zero_plan = [
        AssetGroupPlanRow(
            asset_group_id="g1",
            asset_group_name="Asset 1",
            target_pct=D("100"),
            current_value=D("300"),
            planned_delta_money=D("0"),
        )
    ]
    assert map_asset_group_deltas_to_instruments(p, zero_plan) == [("g1", "Asset 1", "i1", D("-50")), ("g1", "Asset 1", "i2", D("50"))]

    negative_plan = [
        AssetGroupPlanRow(
            asset_group_id="g1",
            asset_group_name="Asset 1",
            target_pct=D("100"),
            current_value=D("300"),
            planned_delta_money=D("-100"),
        )
    ]
    assert map_asset_group_deltas_to_instruments(p, negative_plan) == [("g1", "Asset 1", "i1", D("-100"))]
