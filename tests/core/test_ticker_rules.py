from __future__ import annotations

import pytest

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import (
    ExchangeTickerKey,
    ExchangeTickerLocationIndex,
    build_exchange_ticker_key,
    canonicalize_nyse_ticker,
    canonicalize_tase_ticker,
    canonicalize_ticker_for_exchange,
    is_complete_nyse_ticker,
    is_complete_tase_ticker,
    normalize_nyse_ticker,
    normalize_ticker_for_exchange,
    normalize_tase_ticker,
)


def test_normalize_tase_ticker_keeps_only_digits() -> None:
    assert normalize_tase_ticker("12A-34 567") == "1234567"


def test_normalize_nyse_ticker_uppercases_and_filters_invalid_chars() -> None:
    assert normalize_nyse_ticker("brk.b-1%") == "BRK.B1"


def test_normalize_ticker_for_exchange_uses_tase_rules() -> None:
    assert normalize_ticker_for_exchange(exchange=Exchange.TASE, raw="12A-34 567") == "1234567"


def test_normalize_ticker_for_exchange_uses_nyse_rules() -> None:
    assert normalize_ticker_for_exchange(exchange=Exchange.NYSE, raw="brk.b-1%") == "BRK.B1"


def test_canonicalize_tase_ticker_strips_leading_zeros() -> None:
    assert canonicalize_tase_ticker(" 0312017 ") == "312017"


def test_canonicalize_tase_ticker_returns_zero_for_all_zeros() -> None:
    assert canonicalize_tase_ticker("0000000") == "0"


def test_canonicalize_tase_ticker_rejects_non_digit_input() -> None:
    assert canonicalize_tase_ticker("12A3456") == ""


def test_canonicalize_nyse_ticker_uses_uppercase_identifier_form() -> None:
    assert canonicalize_nyse_ticker("brk.b") == "BRK.B"


def test_canonicalize_nyse_ticker_rejects_invalid_chars() -> None:
    assert canonicalize_nyse_ticker("brk.b-1%") == ""


def test_canonicalize_ticker_for_exchange_uses_tase_rules() -> None:
    assert canonicalize_ticker_for_exchange(exchange=Exchange.TASE, raw=" 000312017 ") == "312017"


def test_canonicalize_ticker_for_exchange_uses_nyse_rules() -> None:
    assert canonicalize_ticker_for_exchange(exchange=Exchange.NYSE, raw=" brk.b ") == "BRK.B"


def test_canonicalize_ticker_for_exchange_rejects_invalid_nyse_input() -> None:
    assert canonicalize_ticker_for_exchange(exchange=Exchange.NYSE, raw=" brk.b-1% ") == ""


def test_build_exchange_ticker_key_builds_canonical_tase_key() -> None:
    key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=" 0312017 ")
    assert key == ExchangeTickerKey(exchange=Exchange.TASE, canonical_ticker="312017")


def test_build_exchange_ticker_key_builds_canonical_nyse_key() -> None:
    key = build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker=" brk.b ")
    assert key == ExchangeTickerKey(exchange=Exchange.NYSE, canonical_ticker="BRK.B")


def test_exchange_ticker_location_index_returns_none_when_key_missing() -> None:
    index = ExchangeTickerLocationIndex.empty()
    key = build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker="AB12")

    assert index.find_location(key=key) is None


def test_exchange_ticker_location_index_keeps_first_location_for_duplicate_key() -> None:
    key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker="0312017")
    index = ExchangeTickerLocationIndex.from_pairs(
        [
            (key, "IL Equity"),
            (key, "Duplicate Location"),
        ]
    )

    assert index.find_location(key=key) == "IL Equity"


@pytest.mark.parametrize("ticker", ["123456", "1234567"])
def test_is_complete_tase_ticker_accepts_valid_shape(ticker: str) -> None:
    assert is_complete_tase_ticker(ticker) is True


@pytest.mark.parametrize("ticker", ["12345", "12AB567", "12345678"])
def test_is_complete_tase_ticker_rejects_invalid_shape(ticker: str) -> None:
    assert is_complete_tase_ticker(ticker) is False


@pytest.mark.parametrize("ticker", ["T", "BRK.B", "ABCDEFGHIJKLMN"])
def test_is_complete_nyse_ticker_accepts_valid_shapes(ticker: str) -> None:
    assert is_complete_nyse_ticker(ticker) is True


@pytest.mark.parametrize("ticker", ["BRK..B", ".BRKB", "ABCDEFGHIJKLMNO"])
def test_is_complete_nyse_ticker_rejects_invalid_shapes(ticker: str) -> None:
    assert is_complete_nyse_ticker(ticker) is False
