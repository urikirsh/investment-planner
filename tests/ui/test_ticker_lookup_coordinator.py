from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event

import pytest
from PySide6.QtWidgets import QApplication

from portfolio_core.market_data import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupResult,
)
from portfolio_core.domain.models import Exchange
from ui.ticker_lookup_coordinator import (
    TickerLookupCoordinator,
    TickerLookupErrorOutcome,
    TickerLookupSuccessOutcome,
)


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp: object) -> None:
    """Ensure a QApplication exists for all tests in this module."""
    _ = qapp


def _wait_until(predicate: Callable[[], bool], *, timeout_ms: int = 1500) -> None:
    """Pump Qt events until predicate returns true or timeout expires."""
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if predicate():
            return
        app.processEvents()
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for async coordinator state")


def test_ticker_lookup_coordinator_emits_result_then_stopped_for_success() -> None:
    coordinator = TickerLookupCoordinator(
        checker=lambda *, exchange, ticker: TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=exchange,
                canonical_ticker=ticker,
                display_name="Resolved Name",
            )
        )
    )
    events: list[str] = []
    payloads: list[object] = []

    def _on_success(payload: object) -> None:
        events.append("success")
        payloads.append(payload)
        assert coordinator.is_running is True

    coordinator.started.connect(lambda: events.append("started"))
    coordinator.success.connect(_on_success)
    coordinator.stopped.connect(lambda: events.append("stopped"))

    assert coordinator.start_lookup(exchange=Exchange.NYSE, ticker="AAPL") is True
    _wait_until(lambda: len(events) == 3)

    assert events == ["started", "success", "stopped"]
    assert isinstance(payloads[0], TickerLookupSuccessOutcome)
    assert payloads[0].metadata.display_name == "Resolved Name"
    assert coordinator.is_running is False


def test_ticker_lookup_coordinator_maps_communication_errors_to_network_outcome() -> None:
    def _raise_communication_error(*, exchange: Exchange, ticker: str) -> TickerLookupResult:
        _ = (exchange, ticker)
        raise TickerLookupCommunicationError("offline")

    coordinator = TickerLookupCoordinator(
        checker=_raise_communication_error,
    )
    payloads: list[object] = []

    coordinator.error.connect(payloads.append)
    assert coordinator.start_lookup(exchange=Exchange.TASE, ticker="1159094") is True
    _wait_until(lambda: len(payloads) == 1)

    assert isinstance(payloads[0], TickerLookupErrorOutcome)
    assert payloads[0].message_title == "Ticker lookup network error"


def test_ticker_lookup_coordinator_rejects_second_start_while_running() -> None:
    release = Event()
    checker_calls = {"count": 0}

    def _gated_success(*, exchange: Exchange, ticker: str) -> TickerLookupResult:
        checker_calls["count"] += 1
        assert release.wait(timeout=1.0)
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=exchange,
                canonical_ticker=ticker,
                display_name="Resolved Name",
            )
        )

    coordinator = TickerLookupCoordinator(checker=_gated_success)
    stop_events = {"count": 0}
    coordinator.stopped.connect(lambda: stop_events.__setitem__("count", stop_events["count"] + 1))

    assert coordinator.start_lookup(exchange=Exchange.NYSE, ticker="AAPL") is True
    assert coordinator.is_running is True
    assert coordinator.start_lookup(exchange=Exchange.NYSE, ticker="MSFT") is False
    assert coordinator.is_running is True

    release.set()
    _wait_until(lambda: stop_events["count"] == 1)

    assert checker_calls["count"] == 1
    assert coordinator.is_running is False
