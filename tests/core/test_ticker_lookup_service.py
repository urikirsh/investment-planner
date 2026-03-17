from __future__ import annotations

from urllib.error import URLError

import pytest

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
