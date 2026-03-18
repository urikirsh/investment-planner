from __future__ import annotations

import pytest

from portfolio_core.ticker_rules import (
    is_complete_nyse_ticker,
    is_complete_tase_ticker,
    normalize_nyse_ticker,
    normalize_tase_ticker,
)


def test_normalize_tase_ticker_keeps_only_digits() -> None:
    assert normalize_tase_ticker("12A-34 567") == "1234567"


def test_normalize_nyse_ticker_uppercases_and_filters_invalid_chars() -> None:
    assert normalize_nyse_ticker("brk.b-1%") == "BRK.B1"


@pytest.mark.parametrize("ticker", ["1234567"])
def test_is_complete_tase_ticker_accepts_valid_shape(ticker: str) -> None:
    assert is_complete_tase_ticker(ticker) is True


@pytest.mark.parametrize("ticker", ["123456", "12AB567", "12345678"])
def test_is_complete_tase_ticker_rejects_invalid_shape(ticker: str) -> None:
    assert is_complete_tase_ticker(ticker) is False


@pytest.mark.parametrize("ticker", ["T", "BRK.B", "ABCDEFGHIJKLMN"])
def test_is_complete_nyse_ticker_accepts_valid_shapes(ticker: str) -> None:
    assert is_complete_nyse_ticker(ticker) is True


@pytest.mark.parametrize("ticker", ["BRK..B", ".BRKB", "ABCDEFGHIJKLMNO"])
def test_is_complete_nyse_ticker_rejects_invalid_shapes(ticker: str) -> None:
    assert is_complete_nyse_ticker(ticker) is False
