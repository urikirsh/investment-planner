from __future__ import annotations

"""Ticker existence and metadata lookup for NYSE/TASE with app-session caching.

Behavior summary:
- NYSE uses Stooq per-ticker quote lookup and caches lookup results per ticker for
  the app session.
- TASE uses `api.tase.co.il` per-security lookup with per-ticker TTL cache entries.
- TASE security numbers are normalized to canonical form (leading zeros removed)
  before network lookup and cache keying.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import unescape
from threading import Lock
import time
from types import MappingProxyType
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import build_exchange_ticker_key, is_complete_nyse_ticker

_STOOQ_QUOTE_URL_TEMPLATE = "https://stooq.com/q/l/?s={symbol}"
_STOOQ_SYMBOL_PAGE_URL_TEMPLATE = "https://stooq.com/q/?s={symbol}"
_TASE_SECURITYDATA_URL_TEMPLATE = "https://api.tase.co.il/api/company/securitydata?securityId={security_id}&lang=1"
_TASE_ENGLISH_NAME_KEYS = ("Name", "LongName", "SecurityLongName", "CompanyName")
_TASE_CACHE_TTL_SECONDS = 900.0
_STOOQ_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}
_TASE_REQUEST_HEADERS = {
    **_REQUEST_HEADERS,
    "Referer": "https://market.tase.co.il/",
    "Origin": "https://market.tase.co.il",
    "Accept": "application/json, text/plain, */*",
}


class TickerLookupCommunicationError(Exception):
    """Raised when ticker lookup cannot be completed due to communication/parsing errors."""


class _TickerLookupTransportError(Exception):
    """Raised when HTTP transport cannot fetch remote ticker payloads."""


class _TickerHttpClient(Protocol):
    """Transport contract for retrieving textual payloads from remote endpoints."""

    # Any transport failure is wrapped by lookup orchestration into
    # `TickerLookupCommunicationError` for stable caller behavior.

    def fetch_text(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> str: ...


class _UrlopenTickerHttpClient:
    """Default HTTP transport backed by `urllib.request.urlopen`."""

    def fetch_text(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> str:
        """Fetch response payload text from URL using provided headers and timeout."""
        request = Request(url, headers=dict(headers))
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw_body = bytes(response.read())
                return raw_body.decode("utf-8", errors="replace")
        except (OSError, TimeoutError, URLError) as exc:
            raise _TickerLookupTransportError("HTTP transport failed") from exc


class _NyseStooqQuoteParser:
    """Parser for one-line Stooq NYSE quote CSV payload."""

    def parse_quote(self, raw_text: str, *, expected_symbol: str) -> "_NyseStooqQuote | None":
        """Parse one Stooq quote line and return quote payload when available."""
        normalized = raw_text.strip()
        if not normalized:
            raise TickerLookupCommunicationError("Stooq NYSE quote response is empty")
        first_line = normalized.splitlines()[0].strip()
        if not first_line:
            raise TickerLookupCommunicationError("Stooq NYSE quote response is empty")
        parts = [part.strip() for part in first_line.split(",")]
        if len(parts) < 8:
            raise TickerLookupCommunicationError("Stooq NYSE quote response has an unexpected payload format")

        symbol = parts[0].upper()
        date = parts[1]
        time_utc = parts[2]
        close = parts[6]
        volume = parts[7]
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

    def _looks_like_stooq_symbol(self, value: str) -> bool:
        """Return whether value looks like a US symbol key from Stooq quote rows."""
        return value.endswith(".US") and all(ch.isalnum() or ch in {".", "-", "_"} for ch in value)

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
        """Extract company display name from the Stooq page `<title>` when available."""
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


class _TaseSecurityDataParser:
    """Parser for TASE `company/securitydata` JSON payloads."""

    def parse_lookup_result(self, raw_text: str) -> "TickerLookupResult":
        """Parse one TASE security payload into found/not-found lookup result."""
        normalized_text = raw_text.strip()
        if not normalized_text or normalized_text == "null":
            return TickerLookupNotFound()
        try:
            payload = json.loads(normalized_text)
        except json.JSONDecodeError as exc:
            raise TickerLookupCommunicationError("TASE security data response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise TickerLookupCommunicationError("TASE security data response has an unexpected payload format")

        security_id = payload.get("Id")
        if security_id in (None, ""):
            return TickerLookupNotFound()
        key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=str(security_id))
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        instrument_name = self._extract_english_instrument_name(payload)
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=Exchange.TASE,
                canonical_ticker=key.canonical_ticker,
                display_name=instrument_name,
                isin=self._extract_optional_string(payload, "ISIN"),
                currency=self._extract_optional_string(payload, "Currency"),
                provider_data=MappingProxyType(dict(payload)),
            )
        )

    def _extract_optional_string(self, payload: Mapping[str, object], key: str) -> str | None:
        """Return a stripped optional string value when present and non-empty."""
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        normalized_value = value.strip()
        return normalized_value or None

    def _extract_english_instrument_name(self, payload: Mapping[str, object]) -> str:
        """Return preferred English instrument display name, or empty string when unavailable."""
        for key in _TASE_ENGLISH_NAME_KEYS:
            value = payload.get(key)
            if not isinstance(value, str):
                continue
            normalized_value = value.strip()
            if (
                normalized_value
                and self._contains_latin_letter(normalized_value)
                and not self._contains_hebrew_letter(normalized_value)
            ):
                return normalized_value
        return ""

    def _contains_latin_letter(self, text: str) -> bool:
        """Return whether text contains at least one basic Latin letter."""
        return any("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in text)

    def _contains_hebrew_letter(self, text: str) -> bool:
        """Return whether text contains at least one Hebrew letter."""
        return any("\u0590" <= ch <= "\u05FF" for ch in text)


@dataclass(frozen=True)
class TickerLookupMetadata:
    """Canonical metadata returned for a resolved ticker."""

    exchange: Exchange
    canonical_ticker: str
    display_name: str
    isin: str | None = None
    currency: str | None = None
    provider_data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze provider metadata into an immutable mapping."""
        object.__setattr__(self, "provider_data", _deep_freeze_mapping(self.provider_data))


@dataclass(frozen=True)
class _NyseStooqQuote:
    """Minimal parsed quote payload used for NYSE ticker lookup metadata."""

    symbol: str
    date: str
    time_utc: str
    close: str
    volume: str


@dataclass(frozen=True)
class TickerLookupFound:
    """Resolved payload for successful ticker lookup.

    `metadata.display_name` may be empty when the exchange confirms ticker
    existence but a preferred display name is unavailable (for example, TASE
    without an English-only name candidate).
    """

    metadata: TickerLookupMetadata

    @property
    def instrument_name(self) -> str:
        """Backward-compatible alias for display name used by existing callers."""
        return self.metadata.display_name


@dataclass(frozen=True)
class TickerLookupNotFound:
    """Resolved payload for missing/unsupported ticker lookup."""


TickerLookupResult = TickerLookupFound | TickerLookupNotFound


def _deep_freeze_mapping(raw: Mapping[str, object]) -> Mapping[str, object]:
    """Return recursively immutable metadata mapping."""
    return MappingProxyType({key: _deep_freeze_value(value) for key, value in raw.items()})


def _deep_freeze_value(value: object) -> object:
    """Return recursively immutable metadata value."""
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, object] = {}
        for key, nested_value in value.items():
            if isinstance(key, str):
                normalized_mapping[key] = _deep_freeze_value(nested_value)
        return MappingProxyType(normalized_mapping)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True)
class _TaseLookupCacheEntry:
    """Cached TASE ticker lookup result with monotonic expiration timestamp."""

    result: TickerLookupResult
    expires_at_monotonic: float


class _NyseLookupCacheStore:
    """Thread-safe holder for app-session NYSE per-ticker lookup cache."""

    def __init__(self) -> None:
        """Initialize empty cache storage and synchronization primitive."""
        self._cache: dict[str, TickerLookupResult] = {}
        self._lock = Lock()

    def get_or_load(
        self,
        *,
        ticker: str,
        timeout_seconds: float,
        result_loader: Callable[[str, float], TickerLookupResult],
    ) -> TickerLookupResult:
        """Return cached NYSE ticker lookup result, loading once per ticker."""
        cached = self._cache.get(ticker)
        if cached is not None:
            return cached

        with self._lock:
            cached = self._cache.get(ticker)
            if cached is not None:
                return cached
            result = result_loader(ticker, timeout_seconds)
            self._cache[ticker] = result
            return result

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache.clear()

    def get_cached_for_tests(self) -> dict[str, TickerLookupResult]:
        """Return current cached payload without triggering network load."""
        with self._lock:
            return dict(self._cache)


class _TaseLookupCacheStore:
    """Thread-safe per-ticker TTL cache for TASE lookup results."""

    def __init__(self, *, ttl_seconds: float) -> None:
        """Initialize empty cache store with a configured TTL."""
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, _TaseLookupCacheEntry] = {}
        self._lock = Lock()

    def get_or_load(
        self,
        *,
        ticker: str,
        timeout_seconds: float,
        result_loader: Callable[[str, float], TickerLookupResult],
    ) -> TickerLookupResult:
        """Return cached TASE lookup result for ticker, reloading when expired/missing."""
        now = time.monotonic()
        cached_entry = self._cache.get(ticker)
        if cached_entry is not None and cached_entry.expires_at_monotonic > now:
            return cached_entry.result

        with self._lock:
            now = time.monotonic()
            cached_entry = self._cache.get(ticker)
            if cached_entry is not None and cached_entry.expires_at_monotonic > now:
                return cached_entry.result
            result = result_loader(ticker, timeout_seconds)
            self._cache[ticker] = _TaseLookupCacheEntry(
                result=result,
                expires_at_monotonic=now + self._ttl_seconds,
            )
            return result

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache.clear()

    def get_cached_for_tests(self) -> dict[str, _TaseLookupCacheEntry]:
        """Return a shallow snapshot of current cache for test assertions."""
        with self._lock:
            return dict(self._cache)


class TickerLookupService:
    """Ticker lookup orchestration with injected transport/parsers/caches."""

    def __init__(
        self,
        *,
        http_client: _TickerHttpClient | None = None,
        nyse_quote_parser: _NyseStooqQuoteParser | None = None,
        nyse_symbol_page_parser: _NyseStooqSymbolPageParser | None = None,
        tase_parser: _TaseSecurityDataParser | None = None,
        nyse_lookup_store: _NyseLookupCacheStore | None = None,
        tase_lookup_store: _TaseLookupCacheStore | None = None,
    ) -> None:
        self._http_client = http_client or _UrlopenTickerHttpClient()
        self._nyse_quote_parser = nyse_quote_parser or _NyseStooqQuoteParser()
        self._nyse_symbol_page_parser = nyse_symbol_page_parser or _NyseStooqSymbolPageParser()
        self._tase_parser = tase_parser or _TaseSecurityDataParser()
        self._nyse_lookup_store = nyse_lookup_store or _NyseLookupCacheStore()
        self._tase_lookup_store = tase_lookup_store or _TaseLookupCacheStore(
            ttl_seconds=_TASE_CACHE_TTL_SECONDS
        )
        self._lookup_by_exchange: Mapping[
            Exchange,
            Callable[[str, float], TickerLookupResult],
        ] = MappingProxyType(
            {
                Exchange.NYSE: self._lookup_nyse_ticker,
                Exchange.TASE: self._lookup_tase_ticker,
            }
        )

    def lookup_ticker_in_exchange(
        self,
        *,
        exchange: Exchange,
        ticker: str,
        timeout_seconds: float = 8.0,
    ) -> TickerLookupResult:
        """Route ticker lookup to exchange-specific implementation."""
        provider = self._lookup_by_exchange.get(exchange)
        if provider is None:
            return TickerLookupNotFound()
        return provider(ticker, timeout_seconds)

    def fetch_nyse_quote_payload(self, stooq_symbol: str, timeout_seconds: float) -> str:
        """Fetch raw Stooq one-line quote payload for one NYSE symbol key."""
        quote_url = _STOOQ_QUOTE_URL_TEMPLATE.format(symbol=stooq_symbol)
        return self._fetch_text_or_raise_communication_error(
            url=quote_url,
            headers=_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Stooq NYSE quote data",
        )

    def fetch_nyse_symbol_page_payload(self, stooq_symbol: str, timeout_seconds: float) -> str:
        """Fetch raw Stooq symbol page payload for one NYSE symbol key."""
        page_url = _STOOQ_SYMBOL_PAGE_URL_TEMPLATE.format(symbol=stooq_symbol)
        return self._fetch_text_or_raise_communication_error(
            url=page_url,
            headers=_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Stooq NYSE symbol page data",
        )

    def fetch_tase_lookup_result(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Fetch and parse TASE security metadata for one security number."""
        payload_text = self.fetch_tase_security_payload(ticker, timeout_seconds)
        return self._tase_parser.parse_lookup_result(payload_text)

    def fetch_tase_security_payload(self, ticker: str, timeout_seconds: float) -> str:
        """Fetch raw TASE security-data API payload for one canonical security number."""
        url = _TASE_SECURITYDATA_URL_TEMPLATE.format(security_id=ticker)
        return self._fetch_text_or_raise_communication_error(
            url=url,
            headers=_TASE_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch TASE security data",
        )

    def _lookup_nyse_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve NYSE ticker metadata from Stooq quote and symbol page payloads."""
        key = build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker=ticker)
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        if not is_complete_nyse_ticker(key.canonical_ticker):
            return TickerLookupNotFound()
        return self._nyse_lookup_store.get_or_load(
            ticker=key.canonical_ticker,
            timeout_seconds=timeout_seconds,
            result_loader=self._fetch_nyse_lookup_result,
        )

    def _fetch_nyse_lookup_result(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Fetch uncached NYSE ticker lookup result from Stooq quote endpoint."""
        for stooq_symbol in self._nyse_stooq_symbol_candidates(ticker):
            payload = self.fetch_nyse_quote_payload(stooq_symbol, timeout_seconds)
            quote = self._nyse_quote_parser.parse_quote(payload, expected_symbol=stooq_symbol)
            if quote is None:
                continue
            display_name = self._fetch_nyse_display_name(
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

    def _fetch_nyse_display_name(
        self,
        *,
        stooq_symbol: str,
        timeout_seconds: float,
        fallback_ticker: str,
    ) -> str:
        """Return Stooq company name when available, otherwise fallback ticker text."""
        try:
            page_payload = self.fetch_nyse_symbol_page_payload(stooq_symbol, timeout_seconds)
        except TickerLookupCommunicationError:
            return fallback_ticker
        parsed_name = self._nyse_symbol_page_parser.parse_company_name(
            page_payload,
            expected_symbol=stooq_symbol.upper(),
        )
        return parsed_name or fallback_ticker

    def _nyse_stooq_symbol_candidates(self, ticker: str) -> list[str]:
        """Return ordered Stooq symbol candidates for a canonical NYSE ticker."""
        base = ticker.lower()
        candidates = [f"{base}.us"]
        dashed = base.replace(".", "-")
        if dashed != base:
            candidates.append(f"{dashed}.us")
        return candidates

    def _lookup_tase_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve TASE ticker from cache/API after canonical security-number normalization."""
        key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=ticker)
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        return self._tase_lookup_store.get_or_load(
            ticker=key.canonical_ticker,
            timeout_seconds=timeout_seconds,
            result_loader=self.fetch_tase_lookup_result,
        )

    def _fetch_text_or_raise_communication_error(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        error_message: str,
    ) -> str:
        """Fetch transport payload and normalize all transport exceptions to communication errors.

        This includes expected network failures and custom transport exceptions
        raised by injected HTTP client implementations.
        """
        try:
            return self._http_client.fetch_text(url=url, headers=headers, timeout_seconds=timeout_seconds)
        except Exception as exc:
            raise TickerLookupCommunicationError(error_message) from exc


_default_ticker_lookup_service = TickerLookupService()


def lookup_ticker_in_exchange(
    *,
    exchange: Exchange,
    ticker: str,
    timeout_seconds: float = 8.0,
) -> TickerLookupResult:
    """Route ticker lookup through the default app-level lookup service."""
    return _default_ticker_lookup_service.lookup_ticker_in_exchange(
        exchange=exchange,
        ticker=ticker,
        timeout_seconds=timeout_seconds,
    )
