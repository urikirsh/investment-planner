from __future__ import annotations

"""Shared helpers for resolving cached instrument prices into ILS amounts."""

from decimal import Decimal

from portfolio_core.domain.models import Currency, Exchange
from portfolio_core.market_data import TickerLookupFound, get_cached_ticker_result_in_exchange

D = Decimal


def resolve_cached_instrument_price_ils(
    *,
    exchange: Exchange,
    ticker: str,
    instrument_name: str,
    usd_ils_rate: D | None = None,
) -> D:
    """Return cached per-unit price in ILS for one instrument identity."""
    cached_result = get_cached_ticker_result_in_exchange(exchange=exchange, ticker=ticker)
    if not isinstance(cached_result, TickerLookupFound):
        raise ValueError(_cached_price_unavailable_message(instrument_name))

    native_price = cached_result.metadata.last_traded_price
    if native_price is None:
        raise ValueError(_cached_price_unavailable_message(instrument_name))

    if exchange.currency is Currency.USD:
        if usd_ils_rate is None:
            raise ValueError("USD/ILS rate unavailable. Return to the welcome screen and try again.")
        return native_price * usd_ils_rate
    return native_price


def _cached_price_unavailable_message(instrument_name: str) -> str:
    """Return the standard user-facing message for missing cached prices."""
    return f"Cached price unavailable for '{instrument_name}'. Return to the welcome screen and try again."
