from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from portfolio_core.domain.models import Exchange
from portfolio_core.market_data import TickerLookupFound
import ui.shared.cached_instrument_pricing as pricing_mod


def test_resolve_cached_instrument_price_ils_returns_tase_price_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    make_cached_lookup,
) -> None:
    monkeypatch.setattr(
        pricing_mod,
        "get_cached_ticker_result_in_exchange",
        lambda *, exchange, ticker: make_cached_lookup(
            exchange=exchange,
            ticker=ticker,
            price=Decimal("12.5"),
        ),
    )

    result = pricing_mod.resolve_cached_instrument_price_ils(
        exchange=Exchange.TASE,
        ticker="1234567",
        instrument_name="ETF A",
    )

    assert result == Decimal("12.5")


def test_resolve_cached_instrument_price_ils_converts_usd_price(
    monkeypatch: pytest.MonkeyPatch,
    make_cached_lookup,
) -> None:
    monkeypatch.setattr(
        pricing_mod,
        "get_cached_ticker_result_in_exchange",
        lambda *, exchange, ticker: make_cached_lookup(
            exchange=exchange,
            ticker=ticker,
            price=Decimal("10"),
        ),
    )

    result = pricing_mod.resolve_cached_instrument_price_ils(
        exchange=Exchange.NYSE,
        ticker="ABCD",
        instrument_name="ETF B",
        usd_ils_rate=Decimal("3.1"),
    )

    assert result == Decimal("31")


def test_resolve_cached_instrument_price_ils_requires_cached_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pricing_mod,
        "get_cached_ticker_result_in_exchange",
        lambda *, exchange, ticker: None,
    )

    with pytest.raises(ValueError, match="Cached price unavailable"):
        pricing_mod.resolve_cached_instrument_price_ils(
            exchange=Exchange.TASE,
            ticker="1234567",
            instrument_name="ETF A",
        )


def test_resolve_cached_instrument_price_ils_requires_usd_ils_rate_for_usd(
    monkeypatch: pytest.MonkeyPatch,
    make_cached_lookup: Callable[..., TickerLookupFound],
) -> None:
    monkeypatch.setattr(
        pricing_mod,
        "get_cached_ticker_result_in_exchange",
        lambda *, exchange, ticker: make_cached_lookup(
            exchange=exchange,
            ticker=ticker,
            price=Decimal("10"),
        ),
    )

    with pytest.raises(ValueError, match="USD/ILS rate unavailable"):
        pricing_mod.resolve_cached_instrument_price_ils(
            exchange=Exchange.NYSE,
            ticker="ABCD",
            instrument_name="ETF B",
        )
