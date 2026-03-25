"""NYSE ticker lookup provider backed by Stooq quote and symbol-page endpoints."""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from io import StringIO
from types import MappingProxyType

from portfolio_core.domain.models import Exchange

from portfolio_core.market_data.models import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupNotFound,
    TickerLookupResult,
)
from portfolio_core.market_data.providers.base import _BaseHttpLookupProvider
from portfolio_core.market_data.transport import TickerHttpClient

_STOOQ_QUOTE_URL_TEMPLATE = "https://stooq.com/q/l/?s={symbol}"
_STOOQ_SYMBOL_PAGE_URL_TEMPLATE = "https://stooq.com/q/?s={symbol}"
_STOOQ_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
_STOOQ_MIN_QUOTE_COLUMNS = 8
_STOOQ_COL_SYMBOL = 0
_STOOQ_COL_DATE = 1
_STOOQ_COL_TIME = 2
_STOOQ_COL_CLOSE = 6
_STOOQ_COL_VOLUME = 7


@dataclass(frozen=True)
class _NyseStooqQuote:
    """Minimal parsed quote payload used for NYSE ticker lookup metadata."""

    symbol: str
    date: str
    time_utc: str
    close: str
    volume: str


class _NyseStooqQuoteParser:
    """Parser for one-line Stooq NYSE quote CSV payload."""

    def parse_quote(self, raw_text: str, *, expected_symbol: str) -> _NyseStooqQuote | None:
        """Parse one Stooq quote line and return quote payload when available."""
        parts = self._split_first_quote_row(raw_text)
        symbol = parts[_STOOQ_COL_SYMBOL].upper()
        date = parts[_STOOQ_COL_DATE]
        time_utc = parts[_STOOQ_COL_TIME]
        close = parts[_STOOQ_COL_CLOSE]
        volume = parts[_STOOQ_COL_VOLUME]
        if date == "N/D" or close == "N/D":
            return None
        if symbol != expected_symbol.upper():
            return None
        if not self._looks_like_stooq_symbol(symbol):
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected symbol format")
        if not self._looks_like_yyyymmdd(date):
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected date format")
        if not self._looks_like_hhmmss(time_utc):
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected time format")
        if not self._looks_like_decimal(close):
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected close format")
        return _NyseStooqQuote(
            symbol=symbol,
            date=date,
            time_utc=time_utc,
            close=close,
            volume=volume,
        )

    def _split_first_quote_row(self, raw_text: str) -> list[str]:
        """Return normalized first CSV row from payload or raise on malformed content."""
        normalized = raw_text.strip()
        if not normalized:
            raise TickerLookupCommunicationError("Stooq NYSE quote response is empty")
        first_line = normalized.splitlines()[0].strip()
        if not first_line:
            raise TickerLookupCommunicationError("Stooq NYSE quote response is empty")
        try:
            row = next(csv.reader(StringIO(first_line)))
        except (csv.Error, StopIteration) as exc:
            raise TickerLookupCommunicationError(
                "Stooq NYSE quote response has an unexpected payload format"
            ) from exc
        parts = [part.strip() for part in row]
        if len(parts) < _STOOQ_MIN_QUOTE_COLUMNS:
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected payload format")
        return parts

    def _looks_like_stooq_symbol(self, value: str) -> bool:
        """Return whether value looks like a US symbol key from Stooq quote rows."""
        return value.endswith(".US") and all(ch.isalnum() or ch in {".", "-"} for ch in value)

    def _looks_like_yyyymmdd(self, value: str) -> bool:
        """Return whether value matches an 8-digit date token."""
        return len(value) == 8 and value.isdigit()

    def _looks_like_hhmmss(self, value: str) -> bool:
        """Return whether value matches a 6-digit time token."""
        return len(value) == 6 and value.isdigit()

    def _looks_like_decimal(self, value: str) -> bool:
        """Return whether value can be parsed as decimal number."""
        try:
            Decimal(value)
        except (InvalidOperation, ValueError):
            return False
        return True


class _NyseStooqSymbolPageParser:
    """Parser for Stooq symbol page HTML fields used for NYSE display names."""

    def parse_company_name(self, raw_text: str, *, expected_symbol: str) -> str | None:
        """Extract company display name from the Stooq page ``<title>`` when available."""
        match = _STOOQ_TITLE_PATTERN.search(raw_text)
        if match is None:
            return None
        title = unescape(match.group(1)).strip()
        if not title:
            return None
        if title.endswith(" - Stooq"):
            title = title[: -len(" - Stooq")].strip()
        if " - " not in title:
            return None
        left, _, company = title.partition(" - ")
        if not left.upper().startswith(expected_symbol.upper()):
            return None
        normalized_company = company.strip()
        if not normalized_company:
            return None
        return normalized_company


class _NyseStooqLookupProvider(_BaseHttpLookupProvider):
    """NYSE lookup provider backed by Stooq quote and symbol-page endpoints."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient,
        request_headers: Mapping[str, str],
        quote_parser: _NyseStooqQuoteParser | None = None,
        symbol_page_parser: _NyseStooqSymbolPageParser | None = None,
    ) -> None:
        super().__init__(http_client=http_client, request_headers=request_headers)
        self._quote_parser = quote_parser or _NyseStooqQuoteParser()
        self._symbol_page_parser = symbol_page_parser or _NyseStooqSymbolPageParser()

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Lookup one canonical NYSE ticker via Stooq."""
        for stooq_symbol in self._stooq_symbol_candidates(ticker):
            payload = self._fetch_quote_payload(stooq_symbol, timeout_seconds)
            quote = self._quote_parser.parse_quote(payload, expected_symbol=stooq_symbol)
            if quote is None:
                continue
            display_name = self._fetch_display_name(
                stooq_symbol=stooq_symbol,
                timeout_seconds=timeout_seconds,
                fallback_ticker=ticker,
            )
            return TickerLookupFound(
                metadata=TickerLookupMetadata(
                    exchange=Exchange.NYSE,
                    canonical_ticker=ticker,
                    display_name=display_name,
                    currency="USD",
                    provider_data=MappingProxyType(
                        {
                            "source": "stooq",
                            "stooq_symbol": stooq_symbol.upper(),
                            "quote_symbol": quote.symbol,
                            "quote_date": quote.date,
                            "quote_time_utc": quote.time_utc,
                            "close": quote.close,
                            "volume": quote.volume,
                        }
                    ),
                )
            )
        return TickerLookupNotFound()

    def _stooq_symbol_candidates(self, ticker: str) -> list[str]:
        """Return ordered Stooq symbol candidates for a canonical NYSE ticker."""
        base = ticker.lower()
        candidates = [f"{base}.us"]
        dashed = base.replace(".", "-")
        if dashed != base:
            candidates.append(f"{dashed}.us")
        return candidates

    def _fetch_quote_payload(self, stooq_symbol: str, timeout_seconds: float) -> str:
        """Fetch one-line Stooq quote payload for one NYSE symbol key."""
        quote_url = _STOOQ_QUOTE_URL_TEMPLATE.format(symbol=stooq_symbol)
        return self._fetch_text_or_raise_communication_error(
            url=quote_url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Stooq NYSE quote data",
        )

    def _fetch_symbol_page_payload(self, stooq_symbol: str, timeout_seconds: float) -> str:
        """Fetch Stooq symbol page payload for one NYSE symbol key."""
        page_url = _STOOQ_SYMBOL_PAGE_URL_TEMPLATE.format(symbol=stooq_symbol)
        return self._fetch_text_or_raise_communication_error(
            url=page_url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Stooq NYSE symbol page data",
        )

    def _fetch_display_name(
        self,
        *,
        stooq_symbol: str,
        timeout_seconds: float,
        fallback_ticker: str,
    ) -> str:
        """Return Stooq company name when available, otherwise fallback ticker text."""
        try:
            payload = self._fetch_symbol_page_payload(stooq_symbol, timeout_seconds)
        except TickerLookupCommunicationError:
            return fallback_ticker
        parsed_name = self._symbol_page_parser.parse_company_name(
            payload,
            expected_symbol=stooq_symbol.upper(),
        )
        return parsed_name or fallback_ticker
