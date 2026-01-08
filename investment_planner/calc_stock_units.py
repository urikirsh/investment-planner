from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, getcontext

from investment_planner.models import Portfolio, Instrument, Cash

getcontext().prec = 28
D = Decimal


@dataclass(frozen=True)
class BuyCalculation:
    instrument_id: str
    price: D
    planned_money: D
    units: int
    spent: D
    leftover: D


def _floor_units(planned_money: D, price: D) -> int:
    if price <= 0:
        raise ValueError("price must be positive")
    if planned_money <= 0:
        return 0
    # floor(planned_money / price)
    units_dec = (planned_money / price).to_integral_value(rounding=ROUND_FLOOR)
    return int(units_dec)


def calculate_buy_units(*, instrument_id: str, planned_money: D, price: D) -> BuyCalculation:
    """
    Given a planned money allocation and a unit price, compute units to buy (floor),
    spent and leftover.
    """
    units = _floor_units(planned_money, price)
    spent = price * D(units)
    leftover = planned_money - spent
    # Safety: leftover should never be negative
    if leftover < 0:
        leftover = D("0")
    return BuyCalculation(
        instrument_id=instrument_id,
        price=price,
        planned_money=planned_money,
        units=units,
        spent=spent,
        leftover=leftover,
    )


def _find_instrument_index(p: Portfolio, instrument_id: str) -> int:
    for idx, ins in enumerate(p.instruments):
        if ins.id == instrument_id:
            return idx
    raise ValueError(f"Instrument not found: {instrument_id}")


def commit_buy(
    *,
    p: Portfolio,
    instrument_id: str,
    spent: D,
    min_trade_ils: D = D("1"),
) -> Portfolio:
    """
    Apply a buy to the portfolio:
    - decrease cash.value by spent
    - increase instrument.value by spent
    If spent < min_trade_ils, does nothing (returns p unchanged).
    """
    if spent <= 0:
        return p
    if spent < min_trade_ils:
        return p
    if spent > p.cash.value:
        raise ValueError(f"Not enough cash to spend {spent} (cash.value={p.cash.value})")

    idx = _find_instrument_index(p, instrument_id)
    ins = p.instruments[idx]
    if not ins.investable:
        raise ValueError(f"Cannot buy non-investable instrument: {ins.name}")

    new_cash_value = p.cash.value - spent
    # keep reserve unchanged
    new_instruments = list(p.instruments)
    new_instruments[idx] = Instrument(
        id=ins.id,
        name=ins.name,
        value=ins.value + spent,
        investable=ins.investable,
        asset_group_id=ins.asset_group_id,
    )
    return Portfolio(cash=Cash(value=new_cash_value, min_reserve=p.cash.min_reserve),
                     asset_groups=p.asset_groups,
                     instruments=new_instruments)


def commit_sell(
    *,
    p: Portfolio,
    instrument_id: str,
    proceeds: D,
    min_trade_ils: D = D("1"),
) -> Portfolio:
    """
    Apply a sell to the portfolio:
    - increase cash.value by proceeds
    - decrease instrument.value by proceeds
    If proceeds < min_trade_ils, does nothing.
    """
    if proceeds <= 0:
        return p
    if proceeds < min_trade_ils:
        return p

    idx = _find_instrument_index(p, instrument_id)
    ins = p.instruments[idx]
    if not ins.investable:
        raise ValueError(f"Cannot sell non-investable instrument: {ins.name}")
    if proceeds > ins.value:
        raise ValueError(f"Cannot sell {proceeds} from '{ins.name}' (value={ins.value})")

    new_cash_amount = p.cash.value + proceeds
    new_instruments = list(p.instruments)
    new_instruments[idx] = Instrument(
        id=ins.id,
        name=ins.name,
        value=ins.value - proceeds,
        investable=ins.investable,
        asset_group_id=ins.asset_group_id,
    )
    return Portfolio(cash=Cash(value=new_cash_amount, min_reserve=p.cash.min_reserve),
                     asset_groups=p.asset_groups,
                     instruments=new_instruments)
