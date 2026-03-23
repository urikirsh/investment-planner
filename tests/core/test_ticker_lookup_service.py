from __future__ import annotations

from collections.abc import Mapping
from threading import Barrier, Thread
import time
from typing import cast

import pytest

from portfolio_core.models import Exchange
from portfolio_core.ticker_lookup_service import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupNotFound,
    TickerLookupService,
    lookup_ticker_in_exchange,
)
from portfolio_core.ticker_rules import canonicalize_ticker_for_exchange


_INVESTING_SEARCH_URL = "https://www.investing.com/search/?q=AAPL"
_INVESTING_INSTRUMENT_URL = "https://www.investing.com/equities/apple-computer-inc"
_TASE_URL = "https://api.tase.co.il/api/company/securitydata?securityId=1159094&lang=1"


def _build_investing_search_payload(*, symbol: str = "AAPL", exchange: str = "NYSE", name: str = "Apple Inc.") -> str:
    """Build an Investing.com search page payload with one structured quote result."""
    result_json = (
        f'[{{"pairId":6408,"name":"{name}","link":"\\/equities\\/apple-computer-inc",'
        f'"symbol":"{symbol}","type":"Stock - {exchange}","exchange":"{exchange}"}}]'
    )
    return (
        "<html><body>"
        "<script>"
        f"window.allResultsQuotesDataArray = {result_json};"
        "</script>"
        "</body></html>"
    )


def _build_investing_instrument_payload(
    *,
    currency: str = "USD",
    isin: str = "US0378331005",
    price: str = "210.50",
) -> str:
    """Build minimal Investing.com instrument page payload with parsable fields."""
    return (
        "<html><body>"
        f'<div data-test="instrument-price-last">{price}</div>'
        f'<script>{{"currency":"{currency}","underlying":{{"isin":"{isin}"}}}}</script>'
        "</body></html>"
    )


def _install_default_lookup_service_with_url_payloads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payloads_by_url: Mapping[str, str],
    calls: dict[str, int] | None = None,
    delay_seconds: float = 0.0,
) -> TickerLookupService:
    """Install a default lookup service with deterministic URL-specific payload behavior."""

    def _fetch_text_stub(*, url: str, headers: Mapping[str, str], timeout_seconds: float) -> str:  # noqa: ARG001
        if calls is not None:
            calls["count"] += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        if url in payloads_by_url:
            return payloads_by_url[url]
        raise AssertionError(f"Unexpected URL requested: {url}")

    http_client = type(
        "_StubHttpClient",
        (),
        {"fetch_text": staticmethod(_fetch_text_stub)},
    )()
    service = TickerLookupService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service._default_ticker_lookup_service",
        service,
    )
    return service


def _install_default_lookup_service_with_failing_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exception: Exception,
) -> TickerLookupService:
    """Install a default lookup service whose transport always raises."""

    def _raise_fetch(*_args, **_kwargs) -> str:
        raise exception

    http_client = type(
        "_FailingHttpClient",
        (),
        {"fetch_text": staticmethod(_raise_fetch)},
    )()
    service = TickerLookupService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service._default_ticker_lookup_service",
        service,
    )
    return service


def test_lookup_ticker_in_exchange_returns_true_for_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _INVESTING_SEARCH_URL: _build_investing_search_payload(),
            _INVESTING_INSTRUMENT_URL: _build_investing_instrument_payload(),
        },
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_false_when_search_exchange_is_not_nyse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_INVESTING_SEARCH_URL: _build_investing_search_payload(exchange="NASDAQ")},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_returns_false_when_search_symbol_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_INVESTING_SEARCH_URL: _build_investing_search_payload(symbol="MSFT")},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


@pytest.mark.parametrize(
    ("exchange", "ticker"),
    [
        (Exchange.NYSE, "AAPL!"),
        (Exchange.NYSE, "BRK..B"),
        (Exchange.NYSE, "AAPL."),
        (Exchange.TASE, "12A3456"),
    ],
)
def test_lookup_ticker_in_exchange_rejects_malformed_canonical_input_without_transport(
    monkeypatch: pytest.MonkeyPatch,
    exchange: Exchange,
    ticker: str,
) -> None:
    _install_default_lookup_service_with_failing_transport(
        monkeypatch,
        exception=AssertionError("Transport should not be called for malformed canonical ticker input"),
    )

    result = lookup_ticker_in_exchange(exchange=exchange, ticker=ticker)

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_returns_name_for_existing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","LongName":"'
        '(ISHARES CORE MSCI EUROPE UCITS ETF EUR (ACC)"}'
    )
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_TASE_URL: payload},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.TASE
    assert result.metadata.canonical_ticker == "1159094"
    assert result.metadata.display_name == "ISH.FRF MSCIEUR"
    assert result.metadata.provider_data.get("Id") == 1159094


def test_lookup_ticker_in_exchange_exposes_deeply_immutable_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","Nested":{"levels":[{"k":"v"}]}}'
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_TASE_URL: payload},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")

    assert isinstance(result, TickerLookupFound)
    with pytest.raises(TypeError):
        cast(dict[str, object], result.metadata.provider_data)["Nested"] = {}

    nested = result.metadata.provider_data["Nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        cast(dict[str, object], nested)["x"] = "y"

    levels = nested["levels"]
    assert isinstance(levels, tuple)
    with pytest.raises(TypeError):
        cast(list[object], levels)[0] = "changed"

    first_level = levels[0]
    assert isinstance(first_level, Mapping)
    with pytest.raises(TypeError):
        cast(dict[str, object], first_level)["k"] = "changed"


def test_lookup_ticker_in_exchange_returns_found_with_empty_name_for_tase_without_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"Id":1234567,'
        '"Name":"\\u05d0\\u05d9\\u05d9\\u05e9\\u05e8\\u05e1 \\u05d7\\u05d5\\u05e5",'
        '"LongName":"\\u05d0\\u05d9\\u05d9\\u05e9\\u05e8\\u05e1 \\u05d7\\u05d5\\u05e5"}'
    )
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={"https://api.tase.co.il/api/company/securitydata?securityId=1234567&lang=1": payload},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1234567")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == ""


def test_lookup_ticker_in_exchange_returns_not_found_for_missing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={"https://api.tase.co.il/api/company/securitydata?securityId=9999999&lang=1": "null"},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="9999999")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_tase_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_TASE_URL: "{invalid-json"},
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")


def test_lookup_ticker_in_exchange_returns_metadata_for_existing_nyse_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _INVESTING_SEARCH_URL: _build_investing_search_payload(),
            _INVESTING_INSTRUMENT_URL: _build_investing_instrument_payload(),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.NYSE
    assert result.metadata.canonical_ticker == "AAPL"
    assert result.metadata.display_name == "Apple Inc."
    assert result.metadata.isin == "US0378331005"
    assert result.metadata.currency == "USD"
    assert result.metadata.provider_data.get("source") == "investing.com"
    assert result.metadata.provider_data.get("pair_id") == 6408
    assert result.metadata.provider_data.get("instrument_link") == "/equities/apple-computer-inc"
    assert result.metadata.provider_data.get("search_exchange") == "NYSE"


def test_lookup_ticker_in_exchange_raises_communication_error_on_url_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_failing_transport(
        monkeypatch,
        exception=OSError("offline"),
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_raises_communication_error_on_custom_transport_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_failing_transport(
        monkeypatch,
        exception=RuntimeError("custom transport failure"),
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")


def test_lookup_ticker_in_exchange_returns_not_found_for_investing_search_payload_without_results_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_INVESTING_SEARCH_URL: "<html>missing array</html>"},
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_uses_nyse_per_ticker_cache_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _INVESTING_SEARCH_URL: _build_investing_search_payload(),
            _INVESTING_INSTRUMENT_URL: _build_investing_instrument_payload(),
        },
        calls=calls,
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert calls["count"] == 2


def test_lookup_ticker_in_exchange_uses_tase_ttl_cache_without_refetch_during_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_TASE_URL: '{"Id":1159094,"Name":"ISH.FRF MSCIEUR"}'},
        calls=calls,
    )

    result1 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")
    result2 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")

    assert isinstance(result1, TickerLookupFound)
    assert isinstance(result2, TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_normalizes_leading_zeros_for_tase_lookup_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={"https://api.tase.co.il/api/company/securitydata?securityId=312017&lang=1": '{"Id":312017,"Name":"SAMPLE"}'},
        calls=calls,
    )

    result1 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="0312017")
    result2 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="312017")

    assert isinstance(result1, TickerLookupFound)
    assert isinstance(result2, TickerLookupFound)
    assert calls["count"] == 1


@pytest.mark.parametrize(
    ("raw_ticker", "normalized"),
    [
        ("312017", "312017"),
        ("0312017", "312017"),
        ("0000000", "0"),
        (" 001159094 ", "1159094"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_canonicalize_tase_security_number(raw_ticker: str, normalized: str) -> None:
    assert canonicalize_ticker_for_exchange(exchange=Exchange.TASE, raw=raw_ticker) == normalized


def test_lookup_ticker_in_exchange_caches_nyse_lookup_result_by_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _INVESTING_SEARCH_URL: _build_investing_search_payload(),
            _INVESTING_INSTRUMENT_URL: _build_investing_instrument_payload(),
        },
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    cache = service._nyse_lookup_store.get_cached_for_tests()
    assert set(cache.keys()) == {"AAPL"}
    assert isinstance(cache["AAPL"], TickerLookupFound)


def test_lookup_ticker_in_exchange_populates_nyse_cache_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    barrier = Barrier(3)
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _INVESTING_SEARCH_URL: _build_investing_search_payload(),
            _INVESTING_INSTRUMENT_URL: _build_investing_instrument_payload(),
        },
        calls=calls,
        delay_seconds=0.05,
    )

    results: list[bool] = []

    def _worker() -> None:
        barrier.wait()
        result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")
        results.append(isinstance(result, TickerLookupFound))

    t1 = Thread(target=_worker)
    t2 = Thread(target=_worker)
    t1.start()
    t2.start()
    barrier.wait()
    t1.join()
    t2.join()

    assert results == [True, True]
    assert calls["count"] == 2
