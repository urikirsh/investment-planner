from __future__ import annotations

from collections.abc import Mapping
from threading import Barrier, Thread
import time
from typing import cast

import pytest

import portfolio_core.ticker_lookup_service as ticker_lookup_service
from portfolio_core.models import Exchange
from portfolio_core.ticker_lookup_service import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupNotFound,
    lookup_ticker_in_exchange,
    normalize_tase_security_number,
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


def _patch_http_client_with_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes,
    calls: dict[str, int] | None = None,
    delay_seconds: float = 0.0,
) -> None:
    """Patch ticker-lookup HTTP transport to return payload with optional delay and counting."""
    decoded_payload = payload.decode("utf-8", errors="replace")

    def _fetch_text_stub(*_args, **_kwargs) -> str:
        if calls is not None:
            calls["count"] += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return decoded_payload

    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service._http_client.fetch_text",
        _fetch_text_stub,
    )


@pytest.fixture(autouse=True)
def _reset_lookup_cache() -> None:
    ticker_lookup_service._nyse_lookup_store.clear_for_tests()
    ticker_lookup_service._tase_lookup_store.clear_for_tests()


def test_lookup_ticker_in_exchange_returns_true_for_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_true_for_bzx_symbol_under_nyse_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPY"), TickerLookupFound)


def test_lookup_ticker_in_exchange_parses_quoted_pipe_in_security_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        'AAPL|"Apple|Inc."|N|AAPL|N|100|N|AAPL',
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


@pytest.mark.parametrize("exchange_code", ["A", "P"])
def test_lookup_ticker_in_exchange_returns_true_for_nyse_family_exchange_codes(
    monkeypatch: pytest.MonkeyPatch,
    exchange_code: str,
) -> None:
    raw = _build_otherlisted_payload(
        f"AAPL|Apple Inc.|{exchange_code}|AAPL|N|100|N|AAPL",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)


def test_lookup_ticker_in_exchange_returns_false_for_non_nyse_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|Q|AAPL|N|100|N|AAPL",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupNotFound)


def test_lookup_ticker_in_exchange_returns_name_for_existing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"Id":1159094,"Name":"ISH.FRF MSCIEUR","LongName":"'
        '(ISHARES CORE MSCI EUROPE UCITS ETF EUR (ACC)"}'
    ).encode("utf-8")
    _patch_http_client_with_payload(monkeypatch, payload=payload)

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
    _patch_http_client_with_payload(monkeypatch, payload=payload)

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
    _patch_http_client_with_payload(monkeypatch, payload=payload)

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1234567")

    assert isinstance(result, TickerLookupFound)
    assert result.metadata.display_name == ""


def test_lookup_ticker_in_exchange_returns_not_found_for_missing_tase_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http_client_with_payload(monkeypatch, payload=b"null")

    result = lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="9999999")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_tase_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http_client_with_payload(monkeypatch, payload=b"{invalid-json")

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.TASE, ticker="1159094")


def test_lookup_ticker_in_exchange_returns_name_for_existing_nyse_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

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
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    result = lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")

    assert isinstance(result, TickerLookupNotFound)


def test_lookup_ticker_in_exchange_raises_communication_error_on_url_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "portfolio_core.ticker_lookup_service._http_client.fetch_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ticker_lookup_service._TickerLookupTransportError("offline")
        ),
    )

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_raises_communication_error_for_invalid_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "Unexpected|Header\nAAPL|N\n".encode("utf-8")
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    with pytest.raises(TickerLookupCommunicationError):
        lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL")


def test_lookup_ticker_in_exchange_uses_cached_rows_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
    )
    calls = {"count": 0}
    _patch_http_client_with_payload(monkeypatch, payload=raw, calls=calls)

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
    _patch_http_client_with_payload(monkeypatch, payload=raw, calls=calls)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    assert calls["count"] == 1


def test_lookup_ticker_in_exchange_uses_tase_ttl_cache_without_refetch_during_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"Id":1159094,"Name":"ISH.FRF MSCIEUR"}'
    calls = {"count": 0}
    _patch_http_client_with_payload(monkeypatch, payload=payload, calls=calls)

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
    _patch_http_client_with_payload(monkeypatch, payload=payload, calls=calls)

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
def test_normalize_tase_security_number(raw_ticker: str, normalized: str) -> None:
    assert normalize_tase_security_number(raw_ticker) == normalized


def test_lookup_ticker_in_exchange_caches_only_nyse_relevant_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _build_otherlisted_payload(
        "AAPL|Apple Inc.|N|AAPL|N|100|N|AAPL",
        "QQQX|Sample Nasdaq Symbol|Q|QQQX|Y|100|N|QQQX",
        "AAPY|Kurv Yield Premium Strategy Apple (AAPL) ETF|Z|AAPY|Y|100|N|AAPY",
    )
    _patch_http_client_with_payload(monkeypatch, payload=raw)

    assert isinstance(lookup_ticker_in_exchange(exchange=Exchange.NYSE, ticker="AAPL"), TickerLookupFound)
    cache = ticker_lookup_service._nyse_lookup_store.get_cached_for_tests()
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
    _patch_http_client_with_payload(
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
