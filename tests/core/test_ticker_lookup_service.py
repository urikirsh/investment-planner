from __future__ import annotations

from threading import Barrier, Thread
import time
from urllib.error import URLError

import pytest

import portfolio_core.ticker_lookup_service as ticker_lookup_service
from portfolio_core.models import Exchange
from portfolio_core.ticker_lookup_service import TickerLookupCommunicationError, check_ticker_exists_in_exchange


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)
        return None


@pytest.fixture(autouse=True)
def _reset_lookup_cache() -> None:
    ticker_lookup_service._nyse_lookup_cache = None


def test_check_ticker_exists_in_exchange_returns_true_for_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True


def test_check_ticker_exists_in_exchange_returns_true_for_bzx_symbol_under_nyse_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPY") is True


@pytest.mark.parametrize("exchange_code", ["A", "P"])
def test_check_ticker_exists_in_exchange_returns_true_for_nyse_family_exchange_codes(
    monkeypatch: pytest.MonkeyPatch,
    exchange_code: str,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        f"AAPL|Apple Inc.|{exchange_code}|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True


def test_check_ticker_exists_in_exchange_returns_false_for_non_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|Q|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is False


def test_check_ticker_exists_in_exchange_returns_false_for_tase_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not be called for TASE")),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.TASE, ticker="1234567") is False


def test_check_ticker_exists_in_exchange_raises_communication_error_on_url_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(TickerLookupCommunicationError):
        check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_check_ticker_exists_in_exchange_raises_communication_error_for_invalid_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "Unexpected|Header\nAAPL|N\n".encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    with pytest.raises(TickerLookupCommunicationError):
        check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_check_ticker_exists_in_exchange_uses_cached_rows_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    calls = {"count": 0}

    def _urlopen_counted(*_args, **_kwargs) -> _FakeResponse:
        calls["count"] += 1
        return _FakeResponse(raw)

    monkeypatch.setattr("portfolio_core.ticker_lookup_service.urlopen", _urlopen_counted)

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True
    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True
    assert calls["count"] == 1


def test_check_ticker_exists_in_exchange_uses_session_cache_without_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    calls = {"count": 0}

    def _urlopen_counted(*_args, **_kwargs) -> _FakeResponse:
        calls["count"] += 1
        return _FakeResponse(raw)

    monkeypatch.setattr("portfolio_core.ticker_lookup_service.urlopen", _urlopen_counted)

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True
    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True
    assert calls["count"] == 1


def test_check_ticker_exists_in_exchange_caches_only_nyse_relevant_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL\n"
        "QQQX|Sample Nasdaq Symbol|Q|QQQX|Y|100|N|QQQX\n"
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(raw),
    )

    assert check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is True
    cache = ticker_lookup_service._nyse_lookup_cache
    assert cache is not None
    cached_symbols = {row.act_symbol for row in cache.rows}
    assert cached_symbols == {"AAPL", "AAPY"}
    assert set(cache.rows_by_symbol.keys()) == {"AAPL", "AAPY"}
    assert cache.rows_by_symbol["AAPL"].act_symbol == "AAPL"


def test_check_ticker_exists_in_exchange_populates_cache_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL\n"
        "File Creation Time: 0317202611:00\n"
    ).encode("utf-8")
    calls = {"count": 0}
    barrier = Barrier(3)

    def _urlopen_counted(*_args, **_kwargs) -> _FakeResponse:
        calls["count"] += 1
        # Hold the first fetch briefly so both worker threads compete for cold cache.
        time.sleep(0.05)
        return _FakeResponse(raw)

    monkeypatch.setattr("portfolio_core.ticker_lookup_service.urlopen", _urlopen_counted)

    results: list[bool] = []

    def _worker() -> None:
        barrier.wait()
        results.append(check_ticker_exists_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"))

    t1 = Thread(target=_worker)
    t2 = Thread(target=_worker)
    t1.start()
    t2.start()
    barrier.wait()
    t1.join()
    t2.join()

    assert results == [True, True]
    assert calls["count"] == 1
