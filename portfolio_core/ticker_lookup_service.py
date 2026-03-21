from __future__ import annotations

"""Ticker existence checks based on Nasdaq Trader symbol-directory files.

Current behavior is intentionally scoped to NYSE validation only. TASE lookup
is not implemented in this service yet.
"""

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import StringIO
from threading import Lock
from types import MappingProxyType
from urllib.error import URLError
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange

_NASDAQ_OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
_NYSE_ACCEPTED_EXCHANGE_CODES = {"N", "A", "P", "Z"}
_FIELD_ACT_SYMBOL = "ACT SYMBOL"
_FIELD_EXCHANGE = "EXCHANGE"
_FIELD_SECURITY_NAME = "SECURITY NAME"
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}


class TickerLookupCommunicationError(Exception):
    """Raised when ticker lookup cannot be completed due to communication/parsing errors."""


@dataclass(frozen=True)
class _NyseRelevantRow:
    """Minimal cached row used for NYSE ticker existence checks."""

    act_symbol: str
    security_name: str


@dataclass(frozen=True)
class TickerLookupResult:
    """Resolved ticker lookup payload used by UI flows."""

    exists: bool
    instrument_name: str

    @classmethod
    def not_found(cls) -> "TickerLookupResult":
        """Return canonical payload for unresolved lookup."""
        return cls(exists=False, instrument_name="")

    @classmethod
    def found(cls, *, instrument_name: str) -> "TickerLookupResult":
        """Return canonical payload for successful lookup."""
        return cls(exists=True, instrument_name=instrument_name)


@dataclass(frozen=True)
class _NyseLookupCache:
    """In-memory cache of NYSE symbol index for app-session reuse."""

    rows_by_symbol: Mapping[str, _NyseRelevantRow]


class _NyseLookupCacheStore:
    """Thread-safe holder for app-session NYSE lookup cache."""

    def __init__(self) -> None:
        """Initialize empty cache storage and synchronization primitive."""
        self._cache: _NyseLookupCache | None = None
        self._lock = Lock()

    def get_or_load(self, *, timeout_seconds: float) -> _NyseLookupCache:
        """Return cached NYSE symbol index, loading once on first access."""
        if self._cache is not None:
            return self._cache

        # Double-checked locking so only one thread populates cache at cold start.
        with self._lock:
            if self._cache is not None:
                return self._cache
            rows = _fetch_otherlisted_rows(timeout_seconds=timeout_seconds)
            rows_by_symbol = MappingProxyType({row.act_symbol: row for row in rows})
            self._cache = _NyseLookupCache(rows_by_symbol=rows_by_symbol)
            return self._cache

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache = None

    def get_cached_for_tests(self) -> _NyseLookupCache | None:
        """Return current cached payload without triggering network load."""
        return self._cache


_nyse_lookup_store = _NyseLookupCacheStore()


def lookup_ticker_in_exchange(
    *,
    exchange: Exchange,
    ticker: str,
    timeout_seconds: float = 8.0,
) -> TickerLookupResult:
    """Return resolved lookup payload (`exists` + normalized instrument name)."""
    if exchange is Exchange.NYSE:
        return _lookup_nyse_ticker(ticker=ticker, timeout_seconds=timeout_seconds)
    return TickerLookupResult.not_found()


def _lookup_nyse_ticker(*, ticker: str, timeout_seconds: float) -> TickerLookupResult:
    """Resolve NYSE ticker existence and canonical instrument name from cached rows."""
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        return TickerLookupResult.not_found()
    cache = _nyse_lookup_store.get_or_load(timeout_seconds=timeout_seconds)
    row = cache.rows_by_symbol.get(normalized_ticker)
    if row is None:
        return TickerLookupResult.not_found()
    return TickerLookupResult.found(instrument_name=row.security_name)


def _fetch_otherlisted_rows(*, timeout_seconds: float) -> list[_NyseRelevantRow]:
    """Fetch and parse Nasdaq Trader `otherlisted.txt` rows."""
    request = Request(_NASDAQ_OTHERLISTED_URL, headers=_REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, URLError) as exc:
        raise TickerLookupCommunicationError("Failed to fetch Nasdaq Trader symbol directory") from exc
    return _parse_otherlisted_text(body)


def _parse_otherlisted_text(raw_text: str) -> list[_NyseRelevantRow]:
    """Parse `otherlisted.txt` into NYSE-relevant rows only (`N/A/P/Z`)."""
    if not raw_text.strip():
        raise TickerLookupCommunicationError("Nasdaq Trader symbol directory response is empty")
    reader = csv.DictReader(StringIO(raw_text), delimiter="|")
    if reader.fieldnames is None:
        raise TickerLookupCommunicationError("Nasdaq Trader symbol directory has an unexpected header format")
    if not _looks_like_otherlisted_header(reader.fieldnames):
        raise TickerLookupCommunicationError("Nasdaq Trader symbol directory has an unexpected header format")

    parsed_rows: list[_NyseRelevantRow] = []
    for row in reader:
        normalized_row = _normalize_otherlisted_row(row)
        maybe_row = _to_nyse_relevant_row(normalized_row)
        if maybe_row is not None:
            parsed_rows.append(maybe_row)
    return parsed_rows


def _normalize_otherlisted_row(row: dict[str | None, str | None]) -> dict[str, str]:
    """Normalize parsed CSV row keys and trim values for stable parsing."""
    return {
        key.strip().upper(): value.strip()
        for key, value in row.items()
        if key is not None and value is not None
    }


def _looks_like_otherlisted_header(header: Sequence[str]) -> bool:
    """Return whether header columns match expected `otherlisted.txt` identifiers."""
    normalized = {item.strip().upper() for item in header}
    required = {_FIELD_ACT_SYMBOL, _FIELD_EXCHANGE}
    return required.issubset(normalized)


def _to_nyse_relevant_row(row: dict[str, str]) -> _NyseRelevantRow | None:
    """Return minimal cached row when exchange code is NYSE-relevant, otherwise ``None``."""
    exchange_code = row.get(_FIELD_EXCHANGE, "").upper()
    if exchange_code not in _NYSE_ACCEPTED_EXCHANGE_CODES:
        return None
    act_symbol = row.get(_FIELD_ACT_SYMBOL, "").upper()
    if not act_symbol:
        return None
    security_name = row.get(_FIELD_SECURITY_NAME, "")
    return _NyseRelevantRow(act_symbol=act_symbol, security_name=security_name)
