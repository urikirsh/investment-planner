from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Mapping

from portfolio_core.planning.calc_stock_units import commit_buy, commit_sell
from portfolio_core.io_json import load_portfolio
from portfolio_core.domain.models import AssetGroupPlanRow, Currency, Exchange, Instrument, Portfolio
from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.market_data import TickerLookupFound, lookup_ticker_in_exchange
from portfolio_core.planning.planning import (
    compute_invest_budget,
    map_asset_group_deltas_to_instruments,
    plan_invest_no_sell,
    plan_rebalance,
)
from portfolio_core.session.portfolio_session import PortfolioSession, build_default_portfolio
from portfolio_core.domain.validation import validate_portfolio

"""
use_cases.py

Application-level portfolio workflows ("use-cases").

This module is the orchestration layer between UI and domain logic.
It coordinates parsing, validation, planning, and persistence through
`PortfolioSession` and domain services, while keeping GUI code free from
business-flow details.

Design intent:
- UI gathers user input and handles presentation.
- Use-cases execute workflow steps and return domain-friendly outputs.
- Domain modules remain focused on pure calculations and invariants.
"""

D = Decimal
_TABLE_VALUE_PRECISION = Decimal("0.01")


class InsufficientQuantityForSellError(ValueError):
    """Raised when a wizard sell requests more units than tracked holdings.

    The wizard catches this error to present a user-friendly prompt and then
    continue to the next step without applying this sell action.
    """

    def __init__(self, *, instrument_name: str, available_units: int, requested_units: int) -> None:
        super().__init__(
            f"Cannot sell {requested_units} units of '{instrument_name}' because only {available_units} units are tracked."
        )
        self.instrument_name = instrument_name
        self.available_units = available_units
        self.requested_units = requested_units


class StartupPortfolioPriceRefreshError(ValueError):
    """Raised when startup cannot refresh all portfolio instrument prices."""


@dataclass(frozen=True)
class PlanStep:
    """
    One actionable instrument-level step in the planning wizard.

    A `PlanStep` is generated from group-level plan rows and tells the caller
    which instrument should be bought or sold and by how much planned value.

    Notes
    -----
    - `planned_delta_money` is always expressed in ILS.
    - `ticker` is copied from the selected instrument and is intended for
      wizard-step context display and user verification before execution.
    - `exchange` describes the instrument's trading exchange and drives
      wizard price-entry semantics via exchange->currency mapping.
    - Supported values are members of `Exchange`.
    """

    asset_group_id: str
    asset_group_name: str
    instrument_id: str
    ticker: str
    instrument_name: str
    exchange: Exchange
    planned_delta_money: D


@dataclass(frozen=True)
class PlanBuildResult:
    """
    Aggregate planning result consumed by summary and wizard screens.

    Attributes
    ----------
    portfolio:
        Portfolio used for planning.
    budget:
        Computed investable cash budget (floored at zero by planning logic).
    rows:
        Asset-group level plan rows.
    steps:
        Instrument-level actionable steps derived from `rows`.
    mode:
        Planning strategy used to produce this result.
    """

    portfolio: Portfolio
    budget: D
    rows: List[AssetGroupPlanRow]
    steps: List[PlanStep]
    mode: PlanningMode


def parse_portfolio_data(data: Mapping[str, Any]) -> Portfolio:
    """
    Parse raw JSON-like payload into a `Portfolio`.

    This function performs schema-level parsing only; business-rule validation
    is intentionally handled separately by `validate_portfolio`.
    """
    return load_portfolio(data)


def load_document(session: PortfolioSession, path: Path) -> Portfolio:
    """
    Load a portfolio file and update session document state.

    Side effects
    ------------
    - Updates `session.document` current/snapshot/active path.
    - Persists active path through session config behavior.
    """
    return session.load_document_from_path(path)


def create_new_default_document(session: PortfolioSession) -> Portfolio:
    """
    Create a new default portfolio and mark it as an unsaved document.

    Side effects
    ------------
    - Sets current and saved snapshot to default portfolio.
    - Clears active file path in session and persisted config.
    """
    portfolio = build_default_portfolio()
    session.mark_new_document(portfolio)
    return portfolio


def refresh_portfolio_prices_for_startup(
    portfolio: Portfolio,
    *,
    usd_ils_rate: Decimal,
    lookup_timeout_seconds: float = 8.0,
) -> Portfolio:
    """Return a portfolio copy with instrument values refreshed from market data."""
    refreshed_instruments = [
        _refresh_instrument_market_value(
            instrument,
            usd_ils_rate=usd_ils_rate,
            lookup_timeout_seconds=lookup_timeout_seconds,
        )
        for instrument in portfolio.instruments
    ]
    return Portfolio(
        cash=portfolio.cash,
        asset_groups=portfolio.asset_groups,
        instruments=refreshed_instruments,
    )


def _refresh_instrument_market_value(
    instrument: Instrument,
    *,
    usd_ils_rate: Decimal,
    lookup_timeout_seconds: float,
) -> Instrument:
    """Return one instrument with its market value recalculated in ILS."""
    try:
        lookup_result = lookup_ticker_in_exchange(
            exchange=instrument.exchange,
            ticker=instrument.ticker,
            timeout_seconds=lookup_timeout_seconds,
        )
    except Exception as exc:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        raise StartupPortfolioPriceRefreshError(
            f"Failed to fetch instrument prices for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker}){suffix}."
        ) from exc

    if not isinstance(lookup_result, TickerLookupFound):
        raise StartupPortfolioPriceRefreshError(
            f"Failed to fetch instrument prices for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker})."
        )

    last_traded_price = lookup_result.metadata.last_traded_price
    if last_traded_price is None:
        raise StartupPortfolioPriceRefreshError(
            f"Fetched price is unavailable for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker})."
        )

    instrument_value = last_traded_price * D(instrument.quantity)
    if instrument.exchange.currency is Currency.USD:
        instrument_value *= usd_ils_rate

    return replace(
        instrument,
        value=instrument_value.quantize(_TABLE_VALUE_PRECISION),
    )


def save_document_from_data(session: PortfolioSession, data: Mapping[str, Any], target_path: Path) -> Portfolio:
    """
    Parse, validate, and persist editor data to `target_path`.

    Workflow
    --------
    1. Parse UI payload into `Portfolio`.
    2. Validate business invariants.
    3. Set parsed portfolio as current document.
    4. Save document and update active path via session.

    Returns
    -------
    Portfolio
        The validated portfolio that was saved.
    """
    portfolio = parse_portfolio_data(data)
    validate_portfolio(portfolio)
    session.document.set_current(portfolio)
    session.save_document_to_path(target_path)
    return portfolio


def sync_document_from_data(session: PortfolioSession, data: Mapping[str, Any]) -> Portfolio:
    """
    Parse UI payload and update only the in-memory current document.

    This use-case does not validate or persist. It is useful for dirty-state
    checks where the UI needs a current parsed snapshot without saving.
    """
    portfolio = parse_portfolio_data(data)
    session.document.set_current(portfolio)
    return portfolio


def build_plan_for_current_document(session: PortfolioSession, mode: PlanningMode) -> PlanBuildResult:
    """
    Build planning output for the current document and selected strategy.

    Parameters
    ----------
    session:
        Session holding the current document to plan.
    mode:
        Planning strategy (`INVEST` or `REBALANCE`).

    Returns
    -------
    PlanBuildResult
        Includes budget, asset-group rows, and instrument-level steps.
        If budget is non-positive, `rows` and `steps` are returned empty.

    Raises
    ------
    ValueError
        If no current portfolio is loaded, or if an instrument referenced by
        the split plan cannot be found.
    """
    portfolio = session.document.current_portfolio
    if portfolio is None:
        raise ValueError("No portfolio loaded")

    budget = compute_invest_budget(portfolio)
    if budget <= 0:
        return PlanBuildResult(
            portfolio=portfolio,
            budget=budget,
            rows=[],
            steps=[],
            mode=mode,
        )

    rows = plan_invest_no_sell(portfolio) if mode == PlanningMode.INVEST else plan_rebalance(portfolio)
    instrument_steps = map_asset_group_deltas_to_instruments(portfolio, rows)
    instruments_by_id = {ins.id: ins for ins in portfolio.instruments}

    steps: List[PlanStep] = []
    for group_id, group_name, instrument_id, planned_delta in instrument_steps:
        if planned_delta == 0:
            continue
        instrument = instruments_by_id.get(instrument_id)
        if instrument is None:
            raise ValueError(f"Instrument not found: {instrument_id}")
        steps.append(
            PlanStep(
                asset_group_id=group_id,
                asset_group_name=group_name,
                instrument_id=instrument_id,
                ticker=instrument.ticker,
                instrument_name=instrument.name,
                exchange=instrument.exchange,
                planned_delta_money=planned_delta,
            )
        )

    return PlanBuildResult(
        portfolio=portfolio,
        budget=budget,
        rows=rows,
        steps=steps,
        mode=mode,
    )


def apply_wizard_step(
    session: PortfolioSession,
    step: PlanStep,
    calc_units: int,
    spent: D,
    *,
    min_buy_trade_ils: D = D("100"),
    min_sell_trade_ils: D = D("1"),
    min_apply_spent_ils: D = D("1"),
) -> bool:
    """
    Apply one wizard step trade and persist immediately when actionable.

    Actionability rules
    -------------------
    A step is applied only when:
    - `calc_units > 0`
    - `spent >= min_apply_spent_ils`

    If not actionable, this function returns `False` and performs no changes.

    Persistence behavior
    --------------------
    For actionable steps:
    - Applies buy/sell to current portfolio.
    - Updates the traded instrument `quantity`:
      - buy: add `calc_units`
      - sell: subtract `calc_units`
    - Updates current document in session.
    - Saves to the currently active file path.

    Sell quantity guard
    -------------------
    Sell steps require enough tracked units. If `calc_units` is greater than
    the instrument's tracked `quantity`,
    the function raises `InsufficientQuantityForSellError` and does not mutate
    or save the portfolio.

    Returns
    -------
    bool
        `True` when trade was applied and saved, otherwise `False`.

    Raises
    ------
    ValueError
        If no portfolio is loaded, there is no active save path, or the
        target instrument cannot be found.
    InsufficientQuantityForSellError
        If a sell step requests more units than tracked quantity.
    """
    portfolio = session.document.current_portfolio
    if portfolio is None:
        raise ValueError("No portfolio loaded")

    if calc_units <= 0 or spent < min_apply_spent_ils:
        return False

    instrument_index = next((idx for idx, ins in enumerate(portfolio.instruments) if ins.id == step.instrument_id), None)
    if instrument_index is None:
        raise ValueError(f"Instrument not found: {step.instrument_id}")
    instrument = portfolio.instruments[instrument_index]
    tracked_quantity = instrument.quantity

    if step.planned_delta_money > 0:
        updated = commit_buy(
            p=portfolio,
            instrument_id=step.instrument_id,
            spent=spent,
            min_trade_ils=min_buy_trade_ils,
        )
        updated_quantity = tracked_quantity + calc_units
    else:
        if calc_units > tracked_quantity:
            raise InsufficientQuantityForSellError(
                instrument_name=instrument.name,
                available_units=tracked_quantity,
                requested_units=calc_units,
            )
        updated = commit_sell(
            p=portfolio,
            instrument_id=step.instrument_id,
            proceeds=spent,
            min_trade_ils=min_sell_trade_ils,
        )
        updated_quantity = tracked_quantity - calc_units

    new_instruments = list(updated.instruments)
    updated_instrument = new_instruments[instrument_index]
    new_instruments[instrument_index] = Instrument(
        id=updated_instrument.id,
        ticker=updated_instrument.ticker,
        name=updated_instrument.name,
        value=updated_instrument.value,
        exchange=updated_instrument.exchange,
        investable=updated_instrument.investable,
        asset_group_id=updated_instrument.asset_group_id,
        target_in_group_pct=updated_instrument.target_in_group_pct,
        quantity=updated_quantity,
    )
    updated = Portfolio(
        cash=updated.cash,
        asset_groups=updated.asset_groups,
        instruments=new_instruments,
    )

    session.document.set_current(updated)
    target_path = session.current_file_path
    if target_path is None:
        raise ValueError("No target file selected. Save the portfolio before continuing.")
    session.save_document_to_path(target_path)
    return True
