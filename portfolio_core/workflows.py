from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Mapping

from portfolio_core.constants import DEFAULT_MARKET_DATA_TIMEOUT_SECONDS
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.planning.calc_stock_units import commit_buy, commit_sell
from portfolio_core.io_json import load_portfolio, load_portfolio_file
from portfolio_core.domain.models import AssetGroupPlanRow, Currency, Exchange, Instrument, Portfolio
from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.market_data import (
    TickerLookupFound,
    force_lookup_ticker_in_exchange,
    get_cached_ticker_result_in_exchange,
    lookup_ticker_in_exchange,
)
from portfolio_core.planning.planning import (
    compute_invest_budget,
    map_asset_group_deltas_to_instruments,
    plan_invest_no_sell,
    plan_rebalance,
)
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote, PortfolioSession, build_default_portfolio
from portfolio_core.domain.validation import validate_portfolio

"""
workflows.py

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


@dataclass(frozen=True)
class HardRefreshPortfolioMarketDataResult:
    """Outcome of a network-first portfolio market-data refresh."""

    portfolio: Portfolio
    fresh_usd_ils_quote: UsdIlsRateQuote | None
    fallback_messages: tuple[str, ...]


@dataclass(frozen=True)
class _InstrumentLookupResolution:
    """Resolved lookup payload plus error/fallback messaging for one instrument."""

    lookup_result: TickerLookupFound | object
    missing_price_prefix: str
    missing_lookup_prefix: str
    fallback_message: str | None = None


def parse_portfolio_data(data: Mapping[str, Any]) -> Portfolio:
    """
    Parse raw JSON-like payload into a `Portfolio`.

    This function performs schema-level parsing only; business-rule validation
    is intentionally handled separately by `validate_portfolio`.
    """
    return load_portfolio(data)


def load_document(
    session: PortfolioSession,
    path: Path,
    *,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> Portfolio:
    """
    Load a portfolio file, refresh instrument prices, and update session state.

    Cache behavior
    --------------
    - Reuses the session-cached USD/ILS quote when a USD-priced instrument needs it.
    - Fetches and caches a USD/ILS quote only when a USD-priced instrument needs it
      and the session cache is empty.
    - Reuses the app-level instrument lookup cache via market-data lookups and
      fetches only the missing instrument prices.

    Side effects
    ------------
    - Updates the session USD/ILS cache when a fresh quote is fetched for a
      USD-priced instrument.
    - Updates `session.document` current/snapshot/active path.
    """
    portfolio = load_portfolio_file(path)
    refreshed_portfolio = refresh_portfolio_prices_for_startup(
        portfolio,
        usd_ils_rate=maybe_get_or_fetch_session_usd_ils_rate(
            session,
            portfolio=portfolio,
            lookup_timeout_seconds=lookup_timeout_seconds,
        ),
        lookup_timeout_seconds=lookup_timeout_seconds,
    )
    session.document.mark_loaded(refreshed_portfolio, path)
    session.set_active_file_path(path)
    return refreshed_portfolio


def create_new_default_document(
    session: PortfolioSession,
    *,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> Portfolio:
    """
    Create a refreshed default portfolio and mark it as a new unsaved document.

    Cache behavior
    --------------
    - Reuses the session-cached USD/ILS quote when a USD-priced instrument needs it.
    - Fetches and caches a USD/ILS quote only when a USD-priced instrument needs it
      and the session cache is empty.
    - Reuses the app-level instrument lookup cache via market-data lookups and
      fetches only the missing instrument prices.

    Side effects
    ------------
    - Updates the session USD/ILS cache when a fresh quote is fetched for a
      USD-priced instrument.
    - Sets current and saved snapshot to the refreshed default portfolio.
    - Clears the active file path in session without changing the remembered startup file.
    """
    portfolio = build_default_portfolio()
    refreshed_portfolio = refresh_portfolio_prices_for_startup(
        portfolio,
        usd_ils_rate=maybe_get_or_fetch_session_usd_ils_rate(
            session,
            portfolio=portfolio,
            lookup_timeout_seconds=lookup_timeout_seconds,
        ),
        lookup_timeout_seconds=lookup_timeout_seconds,
    )
    session.mark_new_document(refreshed_portfolio)
    return refreshed_portfolio


def portfolio_requires_usd_ils_rate(portfolio: Portfolio) -> bool:
    """Return whether any instrument in `portfolio` is priced in USD."""
    return any(instrument.exchange.currency is Currency.USD for instrument in portfolio.instruments)


def maybe_get_or_fetch_session_usd_ils_rate(
    session: PortfolioSession,
    *,
    portfolio: Portfolio,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> Decimal | None:
    """Return a USD/ILS rate only when startup refresh actually needs one.

    Portfolios that contain only ILS-priced instruments skip FX entirely and
    return ``None`` so callers can reuse the same refresh workflow without
    forcing an unnecessary BOI fetch.
    """
    if not portfolio_requires_usd_ils_rate(portfolio):
        return None
    return get_or_fetch_session_usd_ils_rate(
        session,
        lookup_timeout_seconds=lookup_timeout_seconds,
    )


def get_or_fetch_session_usd_ils_rate(
    session: PortfolioSession,
    *,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> Decimal:
    """Return the session USD/ILS rate, fetching and caching it when absent.

    This helper assumes the caller has already established that a USD-priced
    instrument requires FX for the current workflow.
    """
    cached_quote = session.cached_usd_ils_quote
    if cached_quote is not None:
        return cached_quote.rate

    quote = fetch_latest_usd_ils_rate(timeout_seconds=lookup_timeout_seconds)
    session.cache_usd_ils_quote(
        rate=quote.rate,
        effective_date=quote.effective_date,
        used_last_published=quote.used_last_published,
    )
    return quote.rate


def refresh_portfolio_prices_for_startup(
    portfolio: Portfolio,
    *,
    usd_ils_rate: Decimal | None,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> Portfolio:
    """Return a portfolio copy with instrument values refreshed from market data.

    TASE values are refreshed directly in ILS. USD-priced instruments are first
    refreshed from their exchange quote and then converted to ILS with the
    supplied startup FX rate when one is needed. Callers may pass ``None`` for
    ``usd_ils_rate`` when the portfolio contains only ILS-priced instruments.

    Raises
    ------
    StartupPortfolioPriceRefreshError
        If any instrument cannot be refreshed to a usable priced value.
    """
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


def hard_refresh_portfolio_market_data(
    portfolio: Portfolio,
    *,
    cached_usd_ils_quote: CachedUsdIlsQuote | None,
    lookup_timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
) -> HardRefreshPortfolioMarketDataResult:
    """Refresh portfolio prices from the network using the current session FX rate."""
    fallback_messages: list[str] = []
    usd_ils_rate: Decimal | None = None

    if portfolio_requires_usd_ils_rate(portfolio):
        if cached_usd_ils_quote is None:
            raise StartupPortfolioPriceRefreshError("USD/ILS rate is unavailable for hard refresh.")
        usd_ils_rate = cached_usd_ils_quote.rate

    refreshed_instruments = [
        _hard_refresh_instrument_market_value(
            instrument,
            usd_ils_rate=usd_ils_rate,
            lookup_timeout_seconds=lookup_timeout_seconds,
            fallback_messages=fallback_messages,
        )
        for instrument in portfolio.instruments
    ]
    return HardRefreshPortfolioMarketDataResult(
        portfolio=Portfolio(
            cash=portfolio.cash,
            asset_groups=portfolio.asset_groups,
            instruments=refreshed_instruments,
        ),
        fresh_usd_ils_quote=None,
        fallback_messages=tuple(fallback_messages),
    )


def _refresh_instrument_market_value(
    instrument: Instrument,
    *,
    usd_ils_rate: Decimal | None,
    lookup_timeout_seconds: float,
) -> Instrument:
    """Return one instrument with its market value recalculated in ILS."""
    resolution = _resolve_startup_instrument_lookup(
        instrument,
        lookup_timeout_seconds=lookup_timeout_seconds,
    )
    return _instrument_with_resolved_market_value(
        instrument,
        resolution=resolution,
        usd_ils_rate=usd_ils_rate,
    )


def _hard_refresh_instrument_market_value(
    instrument: Instrument,
    *,
    usd_ils_rate: Decimal | None,
    lookup_timeout_seconds: float,
    fallback_messages: list[str],
) -> Instrument:
    """Return one instrument refreshed from network, or from cache when network fails."""
    resolution = _resolve_hard_refresh_instrument_lookup(
        instrument,
        lookup_timeout_seconds=lookup_timeout_seconds,
    )
    refreshed = _instrument_with_resolved_market_value(
        instrument,
        resolution=resolution,
        usd_ils_rate=usd_ils_rate,
    )
    if resolution.fallback_message is not None:
        fallback_messages.append(resolution.fallback_message)
    return refreshed


def _resolve_startup_instrument_lookup(
    instrument: Instrument,
    *,
    lookup_timeout_seconds: float,
) -> _InstrumentLookupResolution:
    """Resolve the startup lookup source for one instrument."""
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

    return _InstrumentLookupResolution(
        lookup_result=lookup_result,
        missing_price_prefix="Fetched price is unavailable",
        missing_lookup_prefix="Failed to fetch instrument prices",
    )


def _resolve_hard_refresh_instrument_lookup(
    instrument: Instrument,
    *,
    lookup_timeout_seconds: float,
) -> _InstrumentLookupResolution:
    """Resolve the hard-refresh lookup source for one instrument."""
    try:
        lookup_result = force_lookup_ticker_in_exchange(
            exchange=instrument.exchange,
            ticker=instrument.ticker,
            timeout_seconds=lookup_timeout_seconds,
        )
        return _InstrumentLookupResolution(
            lookup_result=lookup_result,
            missing_price_prefix="Fetched price is unavailable",
            missing_lookup_prefix="Failed to fetch instrument prices",
        )
    except StartupPortfolioPriceRefreshError:
        raise
    except Exception as exc:
        cached_result = get_cached_ticker_result_in_exchange(
            exchange=instrument.exchange,
            ticker=instrument.ticker,
        )
        if cached_result is not None:
            return _InstrumentLookupResolution(
                lookup_result=cached_result,
                missing_price_prefix="Cached price is unavailable",
                missing_lookup_prefix="Cached price is unavailable",
                fallback_message=(
                    f"{instrument.name}: live price refresh failed, so the app reused the cached market price."
                ),
            )

        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        raise StartupPortfolioPriceRefreshError(
            f"Failed to fetch instrument prices for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker}){suffix}."
        ) from exc


def _instrument_with_resolved_market_value(
    instrument: Instrument,
    *,
    resolution: _InstrumentLookupResolution,
    usd_ils_rate: Decimal | None,
) -> Instrument:
    """Build one refreshed instrument value from an already resolved lookup source."""
    lookup_result = resolution.lookup_result
    if not isinstance(lookup_result, TickerLookupFound):
        raise StartupPortfolioPriceRefreshError(
            f"{resolution.missing_lookup_prefix} for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker})."
        )

    last_traded_price = lookup_result.metadata.last_traded_price
    if last_traded_price is None:
        raise StartupPortfolioPriceRefreshError(
            f"{resolution.missing_price_prefix} for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker})."
        )

    instrument_value = last_traded_price * D(instrument.quantity)
    if instrument.exchange.currency is Currency.USD:
        if usd_ils_rate is None:
            raise StartupPortfolioPriceRefreshError(
                f"USD/ILS rate is unavailable for '{instrument.name}' ({instrument.exchange.value}:{instrument.ticker})."
            )
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
