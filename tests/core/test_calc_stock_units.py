from __future__ import annotations

"""
Unit-level tests for stock unit and trade-commit helpers.

These tests cover floor rounding, invalid-price guards, and buy/sell mutation
effects on cash/instrument values.
"""

import pytest

from portfolio_core.calc_stock_units import (
    calculate_buy_units,
    calculate_buy_units_from_ils_price,
    commit_buy,
    commit_sell,
)
from tests.core.helpers import D, make_portfolio


def test_calculate_buy_units_floor():
    calc = calculate_buy_units(instrument_id="i1", planned_money=D("100"), price_ag=D("3300"))
    assert calc.units == 3
    assert calc.spent == D("99")
    assert calc.leftover == D("1")


def test_calculate_buy_units_from_ils_price_floor():
    calc = calculate_buy_units_from_ils_price(instrument_id="i1", planned_money=D("50"), price_ils=D("31"))
    assert calc.units == 1
    assert calc.spent == D("31")
    assert calc.leftover == D("19")


@pytest.mark.parametrize("price_ag", [D("0"), D("-1")])
def test_calculate_buy_units_non_positive_price_raises(price_ag: D):
    with pytest.raises(ValueError, match="price must be positive"):
        calculate_buy_units(instrument_id="i1", planned_money=D("100"), price_ag=price_ag)


def test_commit_buy_updates_cash_and_instrument():
    p2 = commit_buy(p=make_portfolio(), instrument_id="i1", spent=D("200"))
    assert p2.cash.value == D("800")
    assert p2.cash.future_tax == D("0")
    assert next(i for i in p2.instruments if i.id == "i1").value == D("700")


def test_commit_buy_below_min_trade_does_nothing():
    p = make_portfolio()
    assert commit_buy(p=p, instrument_id="i1", spent=D("0.5"), min_trade_ils=D("1")) == p


@pytest.mark.parametrize("spent", [D("0"), D("-1")])
def test_commit_buy_non_positive_spent_does_nothing(spent: D):
    p = make_portfolio()
    assert commit_buy(p=p, instrument_id="i1", spent=spent) == p


def test_commit_sell_updates_cash_and_instrument():
    p2 = commit_sell(p=make_portfolio(), instrument_id="i1", proceeds=D("200"))
    assert p2.cash.value == D("1200")
    assert p2.cash.future_tax == D("0")
    assert next(i for i in p2.instruments if i.id == "i1").value == D("300")


def test_commit_sell_cannot_sell_more_than_value():
    with pytest.raises(ValueError):
        commit_sell(p=make_portfolio(), instrument_id="i1", proceeds=D("9999"))


@pytest.mark.parametrize("proceeds", [D("0"), D("-1")])
def test_commit_sell_non_positive_proceeds_does_nothing(proceeds: D):
    p = make_portfolio()
    assert commit_sell(p=p, instrument_id="i1", proceeds=proceeds) == p
