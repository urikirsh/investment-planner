from decimal import Decimal

import pytest

from investment_planner.io_json import load_portfolio
from investment_planner.validation import validate_portfolio
from investment_planner.planning import (
    compute_invest_budget,
    plan_invest_no_sell,
    plan_rebalance
)
from investment_planner.calc_stock_units import calculate_buy_units, commit_buy, commit_sell

D = Decimal


def make_valid_data(
    *,
    cash_value="12000",
    cash_reserve="2000",
    # Group targets sum to 100 exactly
    group_targets=(("g1", "Asset 1", "60.0"), ("g2", "Asset 2", "40.0")),
    preferred_map=None,
    instruments=None,
):
    """
    Helper to build JSON-like dict input for load_portfolio.

    - group_targets: iterable of (id, name, targetPercentage_str)
    - preferred_map: dict group_id -> instrument_id. If None, uses first instrument per group.
    - instruments: list of dicts with keys: id, name, value, investable, groupId (optional)
    """
    if instruments is None:
        instruments = [
            {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
            {"id": "i3", "name": "Parking", "value": "1000", "investable": False},
        ]

    if preferred_map is None:
        preferred_map = {}
        # default: first investable instrument seen per group
        for ins in instruments:
            gid = ins.get("groupId")
            if ins.get("investable") and gid and gid not in preferred_map:
                preferred_map[gid] = ins["id"]

    groups = []
    for gid, name, pct in group_targets:
        pref = preferred_map.get(gid, "")
        groups.append(
            {
                "id": gid,
                "name": name,
                "targetPercentage": pct,
                "preferredInstrumentId": pref,
            }
        )

    return {
        "cash": {"value": cash_value, "reserve": cash_reserve},
        "groups": groups,
        "instruments": instruments,
    }


# -------------------------
# Validation tests
# -------------------------

def test_validate_portfolio_happy_path():
    data = make_valid_data()
    p = load_portfolio(data)
    validate_portfolio(p)  # should not raise


def test_validation_cash_reserve_must_not_exceed_cash_value():
    data = make_valid_data(cash_value="100", cash_reserve="101")
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="cash.reserve must be <= cash.value"):
        validate_portfolio(p)


def test_validation_percentages_must_sum_to_100_exactly():
    data = make_valid_data(group_targets=(("g1", "Asset 1", "60.0"), ("g2", "Asset 2", "39.9")))
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="Sum of asset group target percentages must be exactly 100"):
        validate_portfolio(p)


def test_validation_value_cannot_be_negative():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "0", "investable": True, "groupId": "g1"},  # value 0 is fine
        {"id": "i2", "name": "Inst 2", "value": "-4000", "investable": True, "groupId": "g2"},
    ]
    data = make_valid_data(instruments=instruments)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="Instrument 'Inst 1' value must be positive"):
        validate_portfolio(p)

def test_validation_instrument_names_must_be_unique():
    instruments = [
        {"id": "i1", "name": "DUP", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "DUP", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    data = make_valid_data(instruments=instruments)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="Duplicate instrument.name"):
        validate_portfolio(p)


def test_validation_investable_instrument_must_have_group():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True},  # missing groupId
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    data = make_valid_data(instruments=instruments)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="must have an assetGroupId/groupId"):
        validate_portfolio(p)

def test_validation_group_must_exist():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g3"},  # fake group
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    data = make_valid_data(instruments=instruments)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="Instrument 'Inst 1' references unknown asset group id 'g3'"):
        validate_portfolio(p)


def test_validation_non_investable_instrument_must_not_have_group():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "Parking", "value": "4000", "investable": False, "groupId": "g2"},
    ]
    data = make_valid_data(instruments=instruments)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="Non-investable instrument .* must not have"):
        validate_portfolio(p)


def test_validation_preferred_instrument_must_exist():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    # set preferredInstrumentId to a non-existent id for g2
    preferred_map = {"g1": "i1", "g2": "DOES_NOT_EXIST"}
    data = make_valid_data(instruments=instruments, preferred_map=preferred_map)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="preferredInstrumentId not found"):
        validate_portfolio(p)


def test_validation_preferred_instrument_must_belong_to_same_group():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    # g1 points to i2 (wrong group)
    preferred_map = {"g1": "i2", "g2": "i2"}
    data = make_valid_data(instruments=instruments, preferred_map=preferred_map)
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="preferred instrument must belong to the same asset group"):
        validate_portfolio(p)


# -------------------------
# Budget tests
# -------------------------

def test_compute_invest_budget_basic():
    data = make_valid_data(cash_value="12000", cash_reserve="2000")
    p = load_portfolio(data)
    assert compute_invest_budget(p) == D("10000")


def test_compute_invest_budget_floors_at_zero():
    data = make_valid_data(cash_value="1000", cash_reserve="1000")
    p = load_portfolio(data)
    assert compute_invest_budget(p) == D("0")


# -------------------------
# Planning tests: Invest (no selling)
# -------------------------

def test_plan_invest_no_sell_empty_when_budget_zero():
    data = make_valid_data(cash_value="2000", cash_reserve="2000")
    p = load_portfolio(data)
    plan = plan_invest_no_sell(p)
    assert plan == []


def test_plan_invest_no_sell_preserves_group_order():
    # 3 groups in a specific order
    group_targets = (("gA", "A", "30"), ("gB", "B", "30"), ("gC", "C", "40"))
    instruments = [
        {"id": "iA", "name": "iA", "value": "100", "investable": True, "groupId": "gA"},
        {"id": "iB", "name": "iB", "value": "100", "investable": True, "groupId": "gB"},
        {"id": "iC", "name": "iC", "value": "100", "investable": True, "groupId": "gC"},
    ]
    preferred_map = {"gA": "iA", "gB": "iB", "gC": "iC"}
    data = make_valid_data(
        cash_value="300",
        cash_reserve="0.1",  # reserve must be positive; keep tiny but positive
        group_targets=group_targets,
        preferred_map=preferred_map,
        instruments=instruments,
    )
    p = load_portfolio(data)

    # Note: validation requires reserve > 0 and cash.value > 0; reserve is 0.1 so ok
    plan = plan_invest_no_sell(p)
    assert [r.asset_group_id for r in plan] == ["gA", "gB", "gC"]


def test_plan_invest_no_sell_excludes_overweight_groups_and_renormalizes():
    """
    Construct a case where g1 is heavily overweight relative to its target,
    so no-selling allocator should exclude it and invest only into g2.
    """
    data = make_valid_data(
        cash_value="6000",
        cash_reserve="2000",  # budget = 10000
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        preferred_map={"g1": "i1", "g2": "i2"},
        instruments=[
            # Current strategy exposure: g1=9000, g2=1000
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    plan = plan_invest_no_sell(p)

    # Expect only g2 remains (g1 overweight => negative delta => excluded)
    assert [r.asset_group_id for r in plan] == ["g2"]

    # With only g2 active, all budget goes to g2 to keep 100% of active set
    assert plan[0].planned_delta_money == D("4000")


# -------------------------
# Planning tests: Rebalance (selling allowed)
# -------------------------

def test_plan_rebalance_contains_buys_and_sells_in_group_order():
    """
    g1 overweight, g2 underweight, budget positive -> should produce a sell for g1 and buy for g2.
    """
    data = make_valid_data(
        cash_value="12000",
        cash_reserve="2000",  # budget=10000
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        preferred_map={"g1": "i1", "g2": "i2"},
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p = load_portfolio(data)
    rows = plan_rebalance(p)

    # Group order preserved
    assert [r.asset_group_id for r in rows] == ["g1", "g2"]

    # Strategy current total = 9000 + 1000 = 10000; total_after = 20000
    # Each target = 10000
    assert rows[0].planned_delta_money == D("10000") - D("9000")  # = 1000 buy? wait: 10k-9k=+1000
    assert rows[1].planned_delta_money == D("10000") - D("1000")  # = +9000

    # In this specific setup, both are buys (because budget increases total).
    # To force a sell, use zero budget with g1>target.
    data2 = make_valid_data(
        cash_value="2000",
        cash_reserve="2000",  # budget=0
        group_targets=(("g1", "Asset 1", "50"), ("g2", "Asset 2", "50")),
        preferred_map={"g1": "i1", "g2": "i2"},
        instruments=[
            {"id": "i1", "name": "Inst 1", "value": "9000", "investable": True, "groupId": "g1"},
            {"id": "i2", "name": "Inst 2", "value": "1000", "investable": True, "groupId": "g2"},
        ],
    )
    p2 = load_portfolio(data2)
    rows2 = plan_rebalance(p2)
    # total_after = 10000, targets=5000 each -> g1 sell -4000, g2 buy +4000
    assert rows2[0].planned_delta_money == D("5000") - D("9000")  # -4000
    assert rows2[1].planned_delta_money == D("5000") - D("1000")  # +4000

# -------------------------
# Planning tests: unit calculation tests
# -------------------------

def make_portfolio():
    data = {
        "cash": {"value": "1000", "reserve": "100"},
        "groups": [
            {"id": "g1", "name": "Asset", "targetPercentage": "100", "preferredInstrumentId": "i1"}
        ],
        "instruments": [
            {"id": "i1", "name": "Inst", "value": "500", "investable": True, "groupId": "g1"}
        ],
    }
    return load_portfolio(data)

def test_calculate_buy_units_floor():
    calc = calculate_buy_units(instrument_id="i1", planned_money=D("100"), price=D("33"))
    assert calc.units == 3
    assert calc.spent == D("99")
    assert calc.leftover == D("1")


def test_commit_buy_updates_cash_and_instrument():
    p = make_portfolio()
    p2 = commit_buy(p=p, instrument_id="i1", spent=D("200"))
    assert p2.cash.value == D("800")
    assert next(i for i in p2.instruments if i.id == "i1").value == D("700")


def test_commit_buy_below_min_trade_does_nothing():
    p = make_portfolio()
    p2 = commit_buy(p=p, instrument_id="i1", spent=D("0.5"), min_trade_ils=D("1"))
    assert p2 == p


def test_commit_sell_updates_cash_and_instrument():
    p = make_portfolio()
    p2 = commit_sell(p=p, instrument_id="i1", proceeds=D("200"))
    assert p2.cash.value == D("1200")
    assert next(i for i in p2.instruments if i.id == "i1").value == D("300")


def test_commit_sell_cannot_sell_more_than_value():
    p = make_portfolio()
    with pytest.raises(ValueError):
        commit_sell(p=p, instrument_id="i1", proceeds=D("9999"))

