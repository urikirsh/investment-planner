from __future__ import annotations

from collections.abc import Mapping
from threading import Barrier, Thread
import time
from typing import cast

import pytest

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import canonicalize_ticker_for_exchange
from portfolio_core.ticker_lookup_service import (
    TickerLookupService,
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupNotFound,
    lookup_ticker_in_exchange,
)


def _build_otherlisted_payload(*rows: str, include_footer: bool = True) -> bytes:
    """Build `otherlisted.txt` bytes with standard header and optional footer row."""
    lines = [
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
        *rows,
    ]
    if include_footer:
        lines.append("File Creation Time: 0317202611:00")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _install_default_lookup_service_with_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes,
    calls: dict[str, int] | None = None,
    delay_seconds: float = 0.0,
) -> TickerLookupService:
    """Install a default lookup service with deterministic HTTP payload behavior."""
    decoded_payload = payload.decode("utf-8", errors="replace")

    def _fetch_text_stub(*_args, **_kwargs) -> str:
        if calls is not None:
            calls["count"] += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return decoded_payload

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
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_true_for_bzx_symbol_under_nyse_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPY"), TickerLookupFound)


def test_lookup_ticker_in_exchange_parses_quoted_pipe_in_security_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        'AAPL|"Apple|Inc."|N|AAPL|N|100|N|AAPL',
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


@pytest.mark.parametrize("exchange_code", ["A", "P"])
def test_lookup_ticker_in_exchange_returns_true_for_nyse_family_exchange_codes(
    monkeypatch: pytest.MonkeyPatch,
    exchange_code: str,
) -> None:
    raw = _build_otherlisted_payload(
        f"AAPL|Apple Inc.|{exchange_code}|AAPL|N|100|N|AAPL",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_false_for_non_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|Q|AAPL|N|100|N|AAPL",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupNotFound)


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
    ).encode("utf-8")
    _install_default_lookup_service_with_payload(monkeypatch, payload=payload)

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.TASE
    assert result.metadata.canonical_ticker == "1159094"
    assert result.metadata.display_name == "ISH.FRF MSCIEUR"
    assert result.metadata.provider_data.get("Id") == 1159094


def test_lookup_ticker_in_exchange_exposes_deeply_immutable_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","Nested":{"levels":[{"k":"v"}]}}'
    ).encode("utf-8")
    _install_default_lookup_service_with_payload(monkeypatch, payload=payload)

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
    payload = '{"Id":1234567,"Name":"אשס.חוץ MSCIEURO","LongName":"איישרס חוץ"}'.encode("utf-8")
    _install_default_lookup_service_with_payload(monkeypatch, payload=payload)

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1234567")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == ""


def test_lookup_ticker_in_exchange_returns_not_found_for_missing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_payload(monkeypatch, payload=b"null")

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="9999999")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_tase_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_lookup_service_with_payload(monkeypatch, payload=b"{invalid-json")

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")


def test_lookup_ticker_in_exchange_returns_name_for_existing_nyse_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.exchange is Exchange.NYSE
    assert result.metadata.canonical_ticker == "AAPL"
    assert result.metadata.display_name == "Apple Inc."
    assert result.metadata.provider_data.get("exchange_code") == "N"


def test_lookup_ticker_in_exchange_returns_empty_name_when_symbol_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "MSFT|Microsoft Corp.|N|MSFT|N|100|N|MSFT",
    )
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


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


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "Unexpected|Header\nAAPL|N\n".encode("utf-8")
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_uses_cached_rows_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    calls = {"count": 0}
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw, calls=calls)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_uses_session_cache_without_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    calls = {"count": 0}
    _install_default_lookup_service_with_payload(monkeypatch, payload=raw, calls=calls)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_uses_tase_ttl_cache_without_refetch_during_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"Id":1159094,"Name":"ISH.FRF MSCIEUR"}'
    calls = {"count": 0}
    _install_default_lookup_service_with_payload(monkeypatch, payload=payload, calls=calls)

    result1 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")
    result2 = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")

    assert isinstance(result1, TickerLookupFound)
    assert isinstance(result2, TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_normalizes_leading_zeros_for_tase_lookup_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"Id":312017,"Name":"SAMPLE"}'
    calls = {"count": 0}
    _install_default_lookup_service_with_payload(monkeypatch, payload=payload, calls=calls)

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


def test_lookup_ticker_in_exchange_caches_only_nyse_relevant_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
        "QQQX|Sample Nasdaq Symbol|Q|QQQX|Y|100|N|QQQX",
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY",
    )
    service = _install_default_lookup_service_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    cache = service._nyse_lookup_store.get_cached_for_tests()
    assert cache is not None
    assert set(cache.rows_by_symbol.keys()) == {"AAPL", "AAPY"}
    assert cache.rows_by_symbol["AAPL"].act_symbol == "AAPL"
    assert cache.rows_by_symbol["AAPL"].security_name == "Apple Inc."
    assert cache.rows_by_symbol["AAPL"].exchange_code == "N"


def test_lookup_ticker_in_exchange_populates_cache_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    calls = {"count": 0}
    barrier = Barrier(3)
    _install_default_lookup_service_with_payload(
        monkeypatch,
        payload=raw,
        calls=calls,
        # Hold the first fetch briefly so both worker threads compete for cold cache.
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
