from __future__ import annotations

"""Focused lifecycle tests for welcome startup market-data worker management."""

from datetime import date, datetime, timezone
from typing import Any, cast

import pytest

from portfolio_core.io_json import load_portfolio
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote
from tests.core.helpers import D
import ui.controllers.startup_transition as transition_mod


class _FakeLifecycle:
    def __init__(self) -> None:
        self.thread = object()
        self.worker = object()
        self.result_relay = object()
        self.start_calls: list[dict[str, object]] = []
        self.cancel_calls: list[tuple[int, bool]] = []
        self.clear_calls = 0

    def start(self, **kwargs: object) -> None:
        self.start_calls.append(kwargs)

    def cancel(self, *, wait_timeout_ms: int, delete_worker_on_cancel: bool = False) -> bool:
        self.cancel_calls.append((wait_timeout_ms, delete_worker_on_cancel))
        return True

    def clear(self) -> None:
        self.clear_calls += 1


def test_startup_market_data_lifecycle_start_builds_worker_and_delegates_to_shared_lifecycle() -> None:
    lifecycle = transition_mod.StartupMarketDataLifecycle()
    fake_lifecycle = _FakeLifecycle()
    lifecycle._lifecycle = cast(Any, fake_lifecycle)
    parent = object()
    portfolio = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [],
        }
    )
    cached_quote = CachedUsdIlsQuote(
        rate=D("3.55"),
        effective_date=date.fromisoformat("2026-04-10"),
        used_last_published=False,
        cached_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )

    def on_finished(_quote_obj: object, _portfolio_obj: object, _error_obj: object) -> None:
        return None

    lifecycle.start(
        parent=cast(Any, parent),
        portfolio=portfolio,
        cached_quote=cached_quote,
        on_finished=on_finished,
        timeout_seconds=12.5,
    )

    worker = fake_lifecycle.start_calls[0]["worker"]
    assert isinstance(worker, transition_mod.StartupMarketDataWorker)
    assert fake_lifecycle.start_calls == [
        {
            "parent": parent,
            "worker": worker,
            "on_finished": on_finished,
        }
    ]
    assert worker._portfolio == portfolio
    assert worker._cached_quote == cached_quote
    assert worker._timeout_seconds == 12.5


def test_startup_market_data_lifecycle_cancel_delegates_delete_worker_policy() -> None:
    lifecycle = transition_mod.StartupMarketDataLifecycle()
    fake_lifecycle = _FakeLifecycle()
    lifecycle._lifecycle = cast(Any, fake_lifecycle)

    result = lifecycle.cancel(wait_timeout_ms=55)

    assert result is True
    assert fake_lifecycle.cancel_calls == [(55, True)]


def test_startup_market_data_lifecycle_clear_delegates_to_shared_lifecycle() -> None:
    lifecycle = transition_mod.StartupMarketDataLifecycle()
    fake_lifecycle = _FakeLifecycle()
    lifecycle._lifecycle = cast(Any, fake_lifecycle)

    lifecycle.clear()

    assert fake_lifecycle.clear_calls == 1
    assert lifecycle.thread is fake_lifecycle.thread
    assert lifecycle.worker is fake_lifecycle.worker
    assert lifecycle.result_relay is fake_lifecycle.result_relay


def test_startup_market_data_worker_skips_fx_fetch_for_ils_only_portfolio(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = qapp
    portfolio = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "TASE Group", "targetPercentage": "100"}],
            "instruments": [
                {
                    "id": "i1",
                    "ticker": "1159094",
                    "name": "TASE ETF",
                    "quantity": 2,
                    "value": "0.00",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                }
            ],
        }
    )
    seen: list[tuple[object, object, object]] = []

    def fail_fetch_latest_usd_ils_rate(*, timeout_seconds: float = 8.0):
        _ = timeout_seconds
        raise AssertionError("USD/ILS fetch should be skipped for ILS-only startup portfolios.")

    def fake_refresh_portfolio_prices_for_startup(
        refreshed_portfolio: object,
        *,
        usd_ils_rate: object,
        lookup_timeout_seconds: float,
    ) -> object:
        assert refreshed_portfolio is portfolio
        assert usd_ils_rate is None
        assert lookup_timeout_seconds == 7.5
        return portfolio

    monkeypatch.setattr(transition_mod, "fetch_latest_usd_ils_rate", fail_fetch_latest_usd_ils_rate)
    monkeypatch.setattr(transition_mod, "refresh_portfolio_prices_for_startup", fake_refresh_portfolio_prices_for_startup)

    worker = transition_mod.StartupMarketDataWorker(
        portfolio=portfolio,
        cached_quote=None,
        timeout_seconds=7.5,
    )
    worker.finished.connect(lambda quote, refreshed, error: seen.append((quote, refreshed, error)))

    worker.run()

    assert seen == [(None, portfolio, None)]


def test_startup_market_data_worker_fetches_fx_for_usd_portfolio_when_cache_missing(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = qapp
    portfolio = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "NYSE Group", "targetPercentage": "100"}],
            "instruments": [
                {
                    "id": "i1",
                    "ticker": "SPY",
                    "name": "NYSE ETF",
                    "quantity": 2,
                    "value": "0.00",
                    "exchange": "NYSE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                }
            ],
        }
    )
    fake_quote = type("FakeQuote", (), {"rate": D("3.55")})()
    seen: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        transition_mod,
        "fetch_latest_usd_ils_rate",
        lambda *, timeout_seconds=8.0: fake_quote,
    )

    def fake_refresh_portfolio_prices_for_startup(
        refreshed_portfolio: object,
        *,
        usd_ils_rate: object,
        lookup_timeout_seconds: float,
    ) -> object:
        assert refreshed_portfolio is portfolio
        assert usd_ils_rate == D("3.55")
        assert lookup_timeout_seconds == 6.0
        return portfolio

    monkeypatch.setattr(transition_mod, "refresh_portfolio_prices_for_startup", fake_refresh_portfolio_prices_for_startup)

    worker = transition_mod.StartupMarketDataWorker(
        portfolio=portfolio,
        cached_quote=None,
        timeout_seconds=6.0,
    )
    worker.finished.connect(lambda quote, refreshed, error: seen.append((quote, refreshed, error)))

    worker.run()

    assert seen == [(fake_quote, portfolio, None)]
