from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, getcontext

from portfolio_core.models import Portfolio, Instrument, Cash

"""
calc_stock_units.py

Utility logic for translating value-based investment decisions into
concrete stock purchase quantities.

This module is responsible for:
- Converting user-entered stock prices (as shown by the broker, in agorot)
  into internal ILS values
- Calculating how many units of a stock can be purchased for a given
  allocation amount
- Enforcing discrete-unit constraints (stocks are always bought as integers)
- Applying consistent rounding rules (always round down)

Design principles:
- All portfolio values are handled internally in ILS
- User-facing price input mirrors the broker UI exactly (agorot),
  with explicit conversion handled here
- Calculations are deterministic and side-effect free
- No UI logic and no persistence logic lives in this module

This module is used by the per-instrument investment flow to ensure
that theoretical allocation plans are translated into realistic,
executable buy decisions.
"""

getcontext().prec = 28
D = Decimal


@dataclass(frozen=True)
class BuyCalculation:
    """
    Immutable result of a single stock purchase calculation.

    This data structure represents the outcome of translating a
    value-based investment decision into a concrete, executable
    buy plan for a specific instrument.

    Fields:
    - instrument_id:
        Identifier of the instrument to be purchased.
    - price:
        Price per unit in ILS (already converted from the broker-displayed
        agorot value).
    - planned_money:
        Amount of money (ILS) that the strategy intends to allocate
        to this instrument.
    - units:
        Number of units to buy (always a non-negative integer,
        rounded down to respect discrete trading constraints).
    - spent:
        Actual amount of money spent (units * price, in ILS).
    - leftover:
        Unused money from the planned allocation
        (planned_money - spent).

    Design notes:
    - The class is frozen (immutable) to ensure calculations remain
      deterministic and side-effect free.
    """
    instrument_id: str
    price: D
    planned_money: D
    units: int
    spent: D
    leftover: D


def _floor_units(planned_money: D, price: D) -> int:
    """
    Compute the maximum whole number of units affordable for a given budget.

    Parameters
    ----------
    planned_money:
        Budget in ILS allocated to this instrument.
    price:
        Unit price in ILS.

    Returns
    -------
    int
        Floor of `planned_money / price`. Returns `0` when `planned_money <= 0`.

    Raises
    ------
    ValueError
        If `price <= 0`.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    if planned_money <= 0:
        return 0
    # floor(planned_money / price)
    units_dec = (planned_money / price).to_integral_value(rounding=ROUND_FLOOR)
    return int(units_dec)


def calculate_buy_units(*, instrument_id: str, planned_money: D, price_ag: D) -> BuyCalculation:
    """
    Translate a value allocation into an executable buy order.

    Parameters
    ----------
    instrument_id:
        Target instrument identifier.
    planned_money:
        Planned allocation in ILS.
    price_ag:
        Unit price in agorot (broker-facing format).

    Returns
    -------
    BuyCalculation
        Includes converted ILS price, units to buy (floored), actual spent amount,
        and leftover cash from the planned allocation.

    Notes
    -----
    - Conversion rule: `price_ils = price_ag / 100`.
    - Units are always rounded down (never over-spend planned money).
    """
    price_ils = price_ag / Decimal("100")      # conversion
    return calculate_buy_units_from_ils_price(
        instrument_id=instrument_id,
        planned_money=planned_money,
        price_ils=price_ils,
    )


def calculate_buy_units_from_ils_price(*, instrument_id: str, planned_money: D, price_ils: D) -> BuyCalculation:
    """
    Translate a value allocation into an executable buy order using ILS unit price.

    Parameters
    ----------
    instrument_id:
        Target instrument identifier.
    planned_money:
        Planned allocation in ILS.
    price_ils:
        Unit price already expressed in ILS.

    Returns
    -------
    BuyCalculation
        Includes units to buy (floored), actual spent amount, and leftover cash.
    """
    units = _floor_units(planned_money, price_ils)
    spent = price_ils * D(units)
    leftover = planned_money - spent
    # Safety: leftover should never be negative
    if leftover < 0:
        leftover = D("0")
    return BuyCalculation(
        instrument_id=instrument_id,
        price=price_ils,
        planned_money=planned_money,
        units=units,
        spent=spent,
        leftover=leftover,
    )


def _find_instrument_index(p: Portfolio, instrument_id: str) -> int:
    """
    Locate an instrument by id and return its position in `p.instruments`.

    Raises
    ------
    ValueError
        If the instrument id does not exist in the portfolio.
    """
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
    Apply a buy transaction to portfolio state and return a new Portfolio.

    Behavior
    --------
    - Decreases `cash.value` by `spent`.
    - Increases the instrument's `value` by `spent`.
    - Leaves `cash.min_reserve` and `cash.future_tax` unchanged.
    - If `spent <= 0` or `spent < min_trade_ils`, returns the input portfolio unchanged.

    Raises
    ------
    ValueError
        If there is not enough cash, instrument is missing, or instrument is non-investable.
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
    # Keep reserve and future_tax unchanged; only liquid cash value is updated.
    new_instruments = list(p.instruments)
    new_instruments[idx] = Instrument(
        id=ins.id,
        name=ins.name,
        value=ins.value + spent,
        exchange=ins.exchange,
        investable=ins.investable,
        asset_group_id=ins.asset_group_id,
        target_in_group_pct=ins.target_in_group_pct,
        quantity=ins.quantity,
    )
    return Portfolio(
        cash=Cash(
            value=new_cash_value,
            min_reserve=p.cash.min_reserve,
            future_tax=p.cash.future_tax,
        ),
        asset_groups=p.asset_groups,
        instruments=new_instruments,
    )


def commit_sell(
    *,
    p: Portfolio,
    instrument_id: str,
    proceeds: D,
    min_trade_ils: D = D("1"),
) -> Portfolio:
    """
    Apply a sell transaction to portfolio state and return a new Portfolio.

    Behavior
    --------
    - Increases `cash.value` by `proceeds`.
    - Decreases the instrument's `value` by `proceeds`.
    - Leaves `cash.min_reserve` and `cash.future_tax` unchanged.
    - If `proceeds <= 0` or `proceeds < min_trade_ils`, returns input unchanged.

    Raises
    ------
    ValueError
        If instrument is missing, non-investable, or sale exceeds instrument value.
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
        exchange=ins.exchange,
        investable=ins.investable,
        asset_group_id=ins.asset_group_id,
        target_in_group_pct=ins.target_in_group_pct,
        quantity=ins.quantity,
    )
    return Portfolio(
        cash=Cash(
            value=new_cash_amount,
            min_reserve=p.cash.min_reserve,
            future_tax=p.cash.future_tax,
        ),
        asset_groups=p.asset_groups,
        instruments=new_instruments,
    )
