from __future__ import annotations

"""Ticker existence checks based on Nasdaq Trader symbol-directory files.

Current behavior is intentionally scoped to NYSE validation only. TASE lookup
is not implemented in this service yet.
"""

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO
from threading import Lock
from urllib.error import URLError
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange

_NASDAQ_OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
_NYSE_ACCEPTED_EXCHANGE_CODES = {"N", "A", "P", "Z"}
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


@dataclass
class _NyseLookupCache:
    """In-memory cache of NYSE-relevant rows and symbol index for app-session reuse."""

    rows: list[_NyseRelevantRow]
    rows_by_symbol: dict[str, _NyseRelevantRow]


class _NyseLookupCacheStore:
    """Thread-safe holder for app-session NYSE lookup cache."""

    def __init__(self) -> None:
        self._cache: _NyseLookupCache | None = None
        self._lock = Lock()

    def get_or_load(self, *, timeout_seconds: float) -> _NyseLookupCache:
        """Return cached NYSE rows/index, loading once on first access."""
        if self._cache is not None:
            return self._cache

        # Double-checked locking so only one thread populates cache at cold start.
        with self._lock:
            if self._cache is not None:
                return self._cache
            rows = _fetch_otherlisted_rows(timeout_seconds=timeout_seconds)
            rows_by_symbol = {row.act_symbol: row for row in rows}
            self._cache = _NyseLookupCache(rows=rows, rows_by_symbol=rows_by_symbol)
            return self._cache

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache = None

    def get_cached_for_tests(self) -> _NyseLookupCache | None:
        """Return current cached payload without triggering network load."""
        return self._cache


_nyse_lookup_store = _NyseLookupCacheStore()


def check_ticker_exists_in_exchange(
    *,
    exchange: Exchange,
    ticker: str,
    timeout_seconds: float = 8.0,
) -> bool:
    """Return whether `ticker` exists on `exchange` from official symbol directories.

    Notes:
    - NYSE lookup is supported via Nasdaq Trader `otherlisted.txt`.
    - TASE lookup is intentionally unsupported for now and always returns `False`.
    """
    if exchange is not Exchange.NYSE:
        return False
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        return False
    cache = _nyse_lookup_store.get_or_load(timeout_seconds=timeout_seconds)
    return normalized_ticker in cache.rows_by_symbol


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
        normalized_row = {
            key.strip().upper(): value.strip().upper()
            for key, value in row.items()
            if key is not None and value is not None
        }
        if normalized_row.get("ACT SYMBOL", "").startswith("FILE CREATION TIME"):
            continue
        maybe_row = _to_nyse_relevant_row(normalized_row)
        if maybe_row is not None:
            parsed_rows.append(maybe_row)
    return parsed_rows


def _looks_like_otherlisted_header(header: Sequence[str]) -> bool:
    """Return whether header columns match expected `otherlisted.txt` identifiers."""
    normalized = {item.strip().upper() for item in header}
    required = {"ACT SYMBOL", "EXCHANGE"}
    return required.issubset(normalized)


def _to_nyse_relevant_row(row: dict[str, str]) -> _NyseRelevantRow | None:
    """Return minimal cached row when exchange code is NYSE-relevant, otherwise ``None``."""
    if row.get("EXCHANGE", "") not in _NYSE_ACCEPTED_EXCHANGE_CODES:
        return None
    act_symbol = row.get("ACT SYMBOL", "")
    if not act_symbol:
        return None
    return _NyseRelevantRow(act_symbol=act_symbol)
