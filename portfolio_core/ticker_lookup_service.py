from __future__ import annotations

"""Ticker existence checks based on Nasdaq Trader symbol-directory files.

Current behavior is intentionally scoped to NYSE validation only. TASE lookup
is not implemented in this service yet.
"""

from urllib.error import URLError
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange

_NASDAQ_OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
_NYSE_ACCEPTED_EXCHANGE_CODES = {"N", "Z"}
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}


class TickerLookupCommunicationError(Exception):
    """Raised when ticker lookup cannot be completed due to communication/parsing errors."""


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
    rows = _fetch_otherlisted_rows(timeout_seconds=timeout_seconds)
    return any(_row_matches_nyse_ticker(row=row, ticker=normalized_ticker) for row in rows)


def _fetch_otherlisted_rows(*, timeout_seconds: float) -> list[dict[str, str]]:
    """Fetch and parse Nasdaq Trader `otherlisted.txt` rows."""
    request = Request(_NASDAQ_OTHERLISTED_URL, headers=_REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, URLError) as exc:
        raise TickerLookupCommunicationError("Failed to fetch Nasdaq Trader symbol directory") from exc
    return _parse_otherlisted_text(body)


def _parse_otherlisted_text(raw_text: str) -> list[dict[str, str]]:
    """Parse `otherlisted.txt` content into uppercase keyed row dictionaries."""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise TickerLookupCommunicationError("Nasdaq Trader symbol directory response is empty")
    header = lines[0].split("|")
    if not _looks_like_otherlisted_header(header):
        raise TickerLookupCommunicationError("Nasdaq Trader symbol directory has an unexpected header format")

    parsed_rows: list[dict[str, str]] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        values = line.split("|")
        if len(values) != len(header):
            continue
        row = {header[idx].strip().upper(): values[idx].strip().upper() for idx in range(len(header))}
        parsed_rows.append(row)
    return parsed_rows


def _looks_like_otherlisted_header(header: list[str]) -> bool:
    """Return whether header columns match expected `otherlisted.txt` identifiers."""
    normalized = {item.strip().upper() for item in header}
    required = {"ACT SYMBOL", "EXCHANGE"}
    return required.issubset(normalized)


def _row_matches_nyse_ticker(*, row: dict[str, str], ticker: str) -> bool:
    """Return whether one parsed row represents the requested NYSE ticker."""
    return row.get("ACT SYMBOL", "") == ticker and row.get("EXCHANGE", "") in _NYSE_ACCEPTED_EXCHANGE_CODES
