from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from threading import Barrier, Thread
import time
from typing import cast

import pytest

from portfolio_core.domain.models import Exchange
from portfolio_core.market_data import (
    MarketDataService,
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupNotFound,
    force_lookup_ticker_in_exchange,
    get_cached_ticker_result_in_exchange,
    lookup_ticker_in_exchange,
)
from portfolio_core.market_data.lookup_service import _LookupCacheKey
from portfolio_core.domain.ticker_rules import canonicalize_ticker_for_exchange


_NASDAQ_AAPL_STOCK_URL = "https://api.nasdaq.com/api/quote/AAPL/info?assetclass=stocks"
_NASDAQ_AAPL_ETF_URL = "https://api.nasdaq.com/api/quote/AAPL/info?assetclass=etf"
_NASDAQ_BRKB_STOCK_URL = "https://api.nasdaq.com/api/quote/BRK.B/info?assetclass=stocks"
_NASDAQ_BRKB_ETF_URL = "https://api.nasdaq.com/api/quote/BRK.B/info?assetclass=etf"
_YAHOO_AAPL_URL = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d"
_YAHOO_BRKB_URL = "https://query1.finance.yahoo.com/v8/finance/chart/BRK-B?range=5d&interval=1d"
_TASE_URL = "https://api.tase.co.il/api/company/securitydata?securityId=1159094&lang=1"
_TASE_MUTUAL_FUND_URL = "https://maya.tase.co.il/api/v1/funds/mutual/5139910"


def _build_nasdaq_quote_payload(
    *,
    symbol: str = "AAPL",
    company_name: str = "Apple Inc. Common Stock",
    price: str = "$210.50",
    exchange: str = "NASDAQ-GS",
    last_trade_timestamp: str = "Jul 9, 2026 4:00 PM ET",
) -> str:
    """Build minimal Nasdaq quote payload with parsable fields."""
    return (
        '{"data":{"symbol":"'
        + symbol
        + '","companyName":"'
        + company_name
        + '","exchange":"'
        + exchange
        + '","primaryData":{"lastSalePrice":"'
        + price
        + '","lastTradeTimestamp":"'
        + last_trade_timestamp
        + '"}}}'
    )


def _build_yahoo_chart_payload(
    *,
    symbol: str = "AAPL",
    long_name: str = "Apple Inc",
    price: str = "210.50",
    currency: str = "USD",
    exchange_name: str = "NMS",
) -> str:
    """Build minimal Yahoo chart payload with parsable metadata."""
    return (
        '{"chart":{"result":[{"meta":{"symbol":"'
        + symbol
        + '","longName":"'
        + long_name
        + '","regularMarketPrice":'
        + price
        + ',"currency":"'
        + currency
        + '","exchangeName":"'
        + exchange_name
        + '","regularMarketTime":1783540800}}],"error":null}}'
    )


def _build_not_found_payload() -> str:
    """Build a public quote endpoint not-found payload."""
    return '{"data":null,"message":null,"status":{"rCode":400}}'


def _install_default_lookup_service_with_url_payloads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payloads_by_url: Mapping[str, str],
    calls: dict[str, int] | None = None,
    delay_seconds: float = 0.0,
) -> MarketDataService:
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
    service = MarketDataService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.market_data.lookup_service._default_market_data_service",
        service,
    )
    return service


def _install_default_lookup_service_with_failing_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exception: Exception,
) -> MarketDataService:
    """Install a default lookup service whose transport always raises."""

    def _raise_fetch(*_args, **_kwargs) -> str:
        raise exception

    http_client = type(
        "_FailingHttpClient",
        (),
        {"fetch_text": staticmethod(_raise_fetch)},
    )()
    service = MarketDataService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.market_data.lookup_service._default_market_data_service",
        service,
    )
    return service


def test_lookup_ticker_in_exchange_returns_true_for_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(),
        },
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_false_for_web_not_found_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_not_found_payload(),
            _NASDAQ_AAPL_ETF_URL: _build_not_found_payload(),
            _YAHOO_AAPL_URL: '{"chart":{"result":null,"error":{"code":"Not Found"}}}',
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_tries_yahoo_dashed_fallback_for_dot_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_BRKB_STOCK_URL: _build_not_found_payload(),
            _NASDAQ_BRKB_ETF_URL: _build_not_found_payload(),
            _YAHOO_BRKB_URL: _build_yahoo_chart_payload(
                symbol="BRK-B",
                long_name="Berkshire Hathaway Inc",
                price="482.06",
            ),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="BRK.B")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.canonical_ticker == "BRK.B"
    assert result.metadata.provider_data.get("source") == "yahoo_chart"
    assert result.metadata.provider_data.get("yahoo_symbol") == "BRK-B"
    assert result.metadata.display_name == "Berkshire Hathaway Inc"


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
        '(ISHARES CORE MSCI EUROPE UCITS ETF EUR (ACC)","LastRate":123.45}'
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
    assert result.metadata.last_traded_price == Decimal("1.2345")
    assert result.metadata.provider_data.get("Id") == 1159094


def test_lookup_ticker_in_exchange_exposes_deeply_immutable_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","Nested":{"levels":[{"k":"v"}]}}'
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _TASE_URL: payload,
            "https://maya.tase.co.il/api/v1/funds/mutual/1159094": "null",
        },
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
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=1234567&lang=1": payload,
            "https://maya.tase.co.il/api/v1/funds/mutual/1234567": "null",
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1234567")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == ""


def test_lookup_ticker_in_exchange_returns_not_found_for_missing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=9999999&lang=1": "null",
            "https://maya.tase.co.il/api/v1/funds/mutual/9999999": "null",
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="9999999")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_falls_back_to_tase_mutual_fund_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=5139910&lang=1": "null",
            _TASE_MUTUAL_FUND_URL: (
                '{"fundId":5139910,"name":"IBI MEHAKA S&P Bitcoin","longName":"I.B.I. MEHAKA (4D) S&P Bitcoin",'
                '"isin":"IL0051399108","redemptionPrice":63.94,"purchasePrice":63.94,"ratesAsOf":"2026-03-25"}'
            ),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="5139910")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.TASE
    assert result.metadata.canonical_ticker == "5139910"
    assert result.metadata.display_name == "IBI MEHAKA S&P Bitcoin"
    assert result.metadata.last_traded_price == Decimal("0.6394")
    assert result.metadata.isin == "IL0051399108"
    assert result.metadata.provider_data.get("fundId") == 5139910
    assert result.metadata.provider_data.get("ratesAsOf") == "2026-03-25"


def test_lookup_ticker_in_exchange_falls_back_to_tase_mutual_fund_when_primary_has_no_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=5139910&lang=1": '{"Id":5139910,"Name":"Bitcoin P&S"}',
            _TASE_MUTUAL_FUND_URL: '{"fundId":5139910,"name":"IBI MEHAKA S&P Bitcoin","redemptionPrice":63.94}',
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="5139910")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == "IBI MEHAKA S&P Bitcoin"
    assert result.metadata.last_traded_price == Decimal("0.6394")


def test_lookup_ticker_in_exchange_preserves_primary_tase_communication_error_when_mutual_fund_fallback_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=5139910&lang=1": "{invalid-json",
            _TASE_MUTUAL_FUND_URL: "null",
        },
    )

    with pytest.raises(TickerLookupCommunicationError, match="TASE security data response is not valid JSON"):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="5139910")


def test_lookup_ticker_in_exchange_raises_mutual_fund_communication_error_when_primary_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=5139910&lang=1": "null",
            _TASE_MUTUAL_FUND_URL: "{invalid-json",
        },
    )

    with pytest.raises(TickerLookupCommunicationError, match="TASE mutual fund response is not valid JSON"):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="5139910")


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
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(company_name="Apple Inc"),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.NYSE
    assert result.metadata.canonical_ticker == "AAPL"
    assert result.metadata.display_name == "Apple Inc"
    assert result.metadata.last_traded_price == Decimal("210.50")
    assert result.metadata.isin is None
    assert result.metadata.currency == "USD"
    assert result.metadata.provider_data.get("source") == "nasdaq"
    assert result.metadata.provider_data.get("symbol") == "AAPL"
    assert result.metadata.provider_data.get("asset_class") == "stocks"
    assert result.metadata.provider_data.get("last_sale_price") == "210.50"
    assert result.metadata.provider_data.get("exchange") == "NASDAQ-GS"
    assert result.metadata.provider_data.get("last_trade_timestamp") == "Jul 9, 2026 4:00 PM ET"


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


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_web_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: "broken",
            _YAHOO_AAPL_URL: "broken",
        },
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_uses_yahoo_fallback_when_nasdaq_quote_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _fetch_text_stub(*, url: str, headers: Mapping[str, str], timeout_seconds: float) -> str:  # noqa: ARG001
        calls["count"] += 1
        if url == _NASDAQ_AAPL_STOCK_URL:
            raise RuntimeError("nasdaq unavailable")
        if url == _YAHOO_AAPL_URL:
            return _build_yahoo_chart_payload(long_name="Apple Inc")
        raise AssertionError(f"Unexpected URL requested: {url}")

    http_client = type(
        "_StubHttpClient",
        (),
        {"fetch_text": staticmethod(_fetch_text_stub)},
    )()
    service = MarketDataService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.market_data.lookup_service._default_market_data_service",
        service,
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == "Apple Inc"
    assert result.metadata.provider_data.get("source") == "yahoo_chart"
    assert calls["count"] == 2


def test_lookup_ticker_in_exchange_uses_ticker_fallback_when_yahoo_name_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_not_found_payload(),
            _NASDAQ_AAPL_ETF_URL: _build_not_found_payload(),
            _YAHOO_AAPL_URL: _build_yahoo_chart_payload(long_name=""),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == "AAPL"


def test_lookup_ticker_in_exchange_raises_communication_error_for_nasdaq_quote_with_invalid_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(price="$bad"),
            _YAHOO_AAPL_URL: "broken",
        },
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_parses_nasdaq_quote_price_with_commas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(price="$1,210.50"),
        },
    )

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.last_traded_price == Decimal("1210.50")


def test_lookup_ticker_in_exchange_uses_nyse_per_ticker_cache_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(),
        },
        calls=calls,
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_uses_tase_per_ticker_cache_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={_TASE_URL: '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","LastRate":123.45}'},
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
        payloads_by_url={
            "https://api.tase.co.il/api/company/securitydata?securityId=312017&lang=1": (
                '{"Id":312017,"Name":"SAMPLE","LastRate":100.0}'
            )
        },
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


def test_lookup_ticker_in_exchange_caches_nyse_lookup_result_by_exchange_and_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(),
        },
    )

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    cache = service._lookup_store.get_cached_for_tests()
    expected_key = _LookupCacheKey(exchange=Exchange.NYSE, canonical_ticker="AAPL")
    assert set(cache.keys()) == {expected_key}
    assert isinstance(cache[expected_key], TickerLookupFound)
    cached_result = cache[expected_key]
    assert isinstance(cached_result, TickerLookupFound)
    assert cached_result.metadata.last_traded_price == Decimal("210.50")


def test_get_cached_ticker_result_in_exchange_returns_cached_result_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(),
        },
        calls=calls,
    )

    assert get_cached_ticker_result_in_exchange(exchange=Exchange.NYSE, ticker="AAPL") is None
    loaded = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")
    cached = get_cached_ticker_result_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(loaded, TickerLookupFound)
    assert cached == loaded
    assert calls["count"] == 1


def test_force_lookup_ticker_in_exchange_bypasses_cache_and_overwrites_cached_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    payloads_by_url = {
        _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(price="$210.50"),
    }
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url=payloads_by_url,
        calls=calls,
    )

    first = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")
    payloads_by_url[_NASDAQ_AAPL_STOCK_URL] = _build_nasdaq_quote_payload(price="$211.75")
    second = force_lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")
    cached = get_cached_ticker_result_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(first, TickerLookupFound)
    assert isinstance(second, TickerLookupFound)
    assert isinstance(cached, TickerLookupFound)
    assert first.metadata.last_traded_price == Decimal("210.50")
    assert second.metadata.last_traded_price == Decimal("211.75")
    assert cached.metadata.last_traded_price == Decimal("211.75")
    assert calls["count"] == 2


def test_lookup_ticker_in_exchange_populates_nyse_cache_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    barrier = Barrier(3)
    _install_default_lookup_service_with_url_payloads(
        monkeypatch,
        payloads_by_url={
            _NASDAQ_AAPL_STOCK_URL: _build_nasdaq_quote_payload(),
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
    assert calls["count"] == 1
