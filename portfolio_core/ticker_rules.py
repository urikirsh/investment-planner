from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Callable
from typing import Final

from portfolio_core.models import Exchange

TASE_TICKER_MAX_LENGTH: Final[int] = 7
NYSE_TICKER_MAX_LENGTH: Final[int] = 14

TASE_TICKER_PLACEHOLDER: Final[str] = "6-7 digits (e.g. 123456 or 1234567)"
NYSE_TICKER_PLACEHOLDER: Final[str] = "1-14 uppercase letters/digits, optional one dot (e.g. BRK.B)"

TASE_TICKER_ERROR: Final[str] = "Ticker for TASE must be 6 or 7 digits."
NYSE_TICKER_ERROR: Final[str] = "Ticker for NYSE must be 1-14 uppercase letters/digits, optionally one dot."

_TASE_TICKER_RE = re.compile(r"^\d{6,7}$")
_NYSE_TICKER_RE = re.compile(r"^(?=.{1,14}$)(?!.*\..*\.)(?!.*\.$)[A-Z0-9][A-Z0-9.]*$")
_NYSE_TICKER_INPUT_RE = re.compile(r"^(?=.{0,14}$)(?!.*\..*\.)(?:[A-Za-z0-9][A-Za-z0-9.]*|)$")

NYSE_TICKER_INPUT_PATTERN: Final[str] = _NYSE_TICKER_INPUT_RE.pattern
TASE_TICKER_INPUT_PATTERN: Final[str] = r"^\d{0,7}$"


@dataclass(frozen=True)
class ExchangeTickerKey:
    """Canonical exchange+ticker identity key used across lookup and duplicate checks."""

    exchange: Exchange
    canonical_ticker: str


def normalize_tase_ticker(raw: str) -> str:
    """Normalize TASE ticker text to digits only."""
    return "".join(ch for ch in raw if ch.isdigit())


def normalize_nyse_ticker(raw: str) -> str:
    """Normalize NYSE ticker text to uppercase ASCII alphanumerics plus dot."""
    return "".join(ch for ch in raw if ch.isascii() and (ch.isalnum() or ch == ".")).upper()


_TICKER_NORMALIZERS: Final[dict[Exchange, Callable[[str], str]]] = {
    Exchange.TASE: normalize_tase_ticker,
    Exchange.NYSE: normalize_nyse_ticker,
}


def normalize_ticker_for_exchange(*, exchange: Exchange, raw: str) -> str:
    """Normalize ticker text using exchange-specific input rules."""
    return _TICKER_NORMALIZERS[exchange](raw)


def canonicalize_tase_ticker(raw: str) -> str:
    """Return canonical TASE security number with leading zeros removed.

    Canonicalization is identity-focused and lossless except for trimming and
    leading-zero normalization. Inputs with non-digit characters are rejected.
    """
    stripped = raw.strip()
    if not stripped:
        return ""
    if any(not ch.isdigit() for ch in stripped):
        return ""
    return stripped.lstrip("0") or "0"


def canonicalize_nyse_ticker(raw: str) -> str:
    """Return canonical NYSE ticker identifier.

    Canonicalization is identity-focused and lossless except for trimming and
    case normalization. Inputs with unsupported characters are rejected.
    """
    stripped = raw.strip()
    if not stripped:
        return ""
    upper_ticker = stripped.upper()
    if any((not ch.isascii()) or (not (ch.isalnum() or ch == ".")) for ch in upper_ticker):
        return ""
    return upper_ticker


_TICKER_CANONICALIZERS: Final[dict[Exchange, Callable[[str], str]]] = {
    Exchange.TASE: canonicalize_tase_ticker,
    Exchange.NYSE: canonicalize_nyse_ticker,
}


def canonicalize_ticker_for_exchange(*, exchange: Exchange, raw: str) -> str:
    """Return exchange-specific canonical ticker identifier used for keying/lookups."""
    return _TICKER_CANONICALIZERS[exchange](raw)


def build_exchange_ticker_key(*, exchange: Exchange, raw_ticker: str) -> ExchangeTickerKey:
    """Build shared canonical exchange+ticker key from raw ticker text."""
    return ExchangeTickerKey(
        exchange=exchange,
        canonical_ticker=canonicalize_ticker_for_exchange(exchange=exchange, raw=raw_ticker),
    )


def is_complete_tase_ticker(ticker: str) -> bool:
    """Return whether normalized TASE ticker is complete."""
    return _TASE_TICKER_RE.fullmatch(ticker) is not None


def is_complete_nyse_ticker(ticker: str) -> bool:
    """Return whether normalized NYSE ticker is complete."""
    return _NYSE_TICKER_RE.fullmatch(ticker) is not None
