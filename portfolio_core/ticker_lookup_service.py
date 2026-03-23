from __future__ import annotations

"""Ticker existence and metadata lookup for NYSE/TASE with app-session caching.

Behavior summary:
- NYSE uses Investing.com per-ticker scraping and caches lookup results per ticker
  for the app session.
- TASE uses `api.tase.co.il` per-security lookup with per-ticker TTL cache entries.
- TASE security numbers are normalized to canonical form (leading zeros removed)
  before network lookup and cache keying.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Lock
import time
from types import MappingProxyType
from typing import Protocol
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import build_exchange_ticker_key, is_complete_nyse_ticker

_INVESTING_SEARCH_URL_TEMPLATE = "https://www.investing.com/search/?q={query}"
_INVESTING_BASE_URL = "https://www.investing.com"
_TASE_SECURITYDATA_URL_TEMPLATE = "https://api.tase.co.il/api/company/securitydata?securityId={security_id}&lang=1"
_INVESTING_NYSE_EXCHANGE = "NYSE"
_TASE_ENGLISH_NAME_KEYS = ("Name", "LongName", "SecurityLongName", "CompanyName")
_TASE_CACHE_TTL_SECONDS = 900.0
_INVESTING_SEARCH_DATA_ARRAY_MARKER = "window.allResultsQuotesDataArray"
_INVESTING_PRICE_LAST_DATA_TEST = 'data-test="instrument-price-last">'
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


class _NyseInvestingSearchParser:
    """Parser for Investing.com search payload inlined JSON array."""

    def parse_results(self, raw_text: str) -> list["_NyseInvestingSearchResult"]:
        """Parse Investing.com search page HTML to structured quote search results."""
        marker_index = raw_text.find(_INVESTING_SEARCH_DATA_ARRAY_MARKER)
        if marker_index < 0:
            raise TickerLookupCommunicationError("Investing.com NYSE search response has an unexpected payload format")
        array_start_index = raw_text.find("[", marker_index)
        if array_start_index < 0:
            raise TickerLookupCommunicationError("Investing.com NYSE search response has an unexpected payload format")
        array_end_index = raw_text.find("];", array_start_index)
        if array_end_index < 0:
            raise TickerLookupCommunicationError("Investing.com NYSE search response has an unexpected payload format")

        json_array_text = raw_text[array_start_index : array_end_index + 1]
        try:
            payload = json.loads(json_array_text)
        except json.JSONDecodeError as exc:
            raise TickerLookupCommunicationError("Investing.com NYSE search response has an unexpected payload format") from exc
        if not isinstance(payload, list):
            raise TickerLookupCommunicationError("Investing.com NYSE search response has an unexpected payload format")

        parsed: list[_NyseInvestingSearchResult] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            symbol = _as_upper_string(item.get("symbol"))
            exchange = _as_upper_string(item.get("exchange"))
            if not symbol or exchange != _INVESTING_NYSE_EXCHANGE:
                continue
            pair_id = _as_int(item.get("pairId"))
            if pair_id is None:
                continue
            link = _as_string(item.get("link"))
            if not link:
                continue
            parsed.append(
                _NyseInvestingSearchResult(
                    symbol=symbol,
                    exchange=exchange,
                    name=_as_string(item.get("name")),
                    pair_id=pair_id,
                    link=link,
                    instrument_type=_as_string(item.get("type")),
                )
            )
        return parsed


class _NyseInvestingInstrumentParser:
    """Parser for Investing.com instrument page fields needed for NYSE lookup metadata."""

    def parse_metadata(
        self,
        *,
        raw_text: str,
        ticker: str,
        fallback_display_name: str,
        search_result: "_NyseInvestingSearchResult",
    ) -> "TickerLookupMetadata":
        """Extract NYSE lookup metadata from Investing.com instrument page HTML."""
        isin = self._extract_isin(raw_text)
        currency = self._extract_currency(raw_text)
        _ = self._extract_price(raw_text)
        return TickerLookupMetadata(
            exchange=Exchange.NYSE,
            canonical_ticker=ticker,
            display_name=fallback_display_name,
            isin=isin,
            currency=currency,
            provider_data=MappingProxyType(
                {
                    "source": "investing.com",
                    "pair_id": search_result.pair_id,
                    "instrument_link": search_result.link,
                    "instrument_type": search_result.instrument_type,
                    "search_exchange": search_result.exchange,
                }
            ),
        )

    def _extract_isin(self, raw_text: str) -> str | None:
        """Extract first plausible ISIN from page payload, when present."""
        for marker in ('"isin":"', '"isin": "'):
            index = raw_text.find(marker)
            while index >= 0:
                start = index + len(marker)
                end = raw_text.find('"', start)
                if end <= start:
                    break
                candidate = raw_text[start:end].strip()
                if _looks_like_isin(candidate):
                    return candidate
                index = raw_text.find(marker, end)
        return None

    def _extract_currency(self, raw_text: str) -> str | None:
        """Extract three-letter instrument currency when present."""
        for marker in ('"currency":"', '"currency": "'):
            index = raw_text.find(marker)
            if index < 0:
                continue
            start = index + len(marker)
            end = raw_text.find('"', start)
            if end <= start:
                continue
            candidate = raw_text[start:end].strip().upper()
            if len(candidate) == 3 and candidate.isalpha():
                return candidate
        return None

    def _extract_price(self, raw_text: str) -> str | None:
        """Extract visible headline price from page HTML when present."""
        index = raw_text.find(_INVESTING_PRICE_LAST_DATA_TEST)
        if index < 0:
            return None
        start = index + len(_INVESTING_PRICE_LAST_DATA_TEST)
        end = raw_text.find("<", start)
        if end <= start:
            return None
        price_text = raw_text[start:end].strip()
        return price_text or None


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
class _NyseInvestingSearchResult:
    """Relevant Investing.com search result used to resolve a NYSE ticker."""

    symbol: str
    exchange: str
    name: str
    pair_id: int
    link: str
    instrument_type: str


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
        nyse_search_parser: _NyseInvestingSearchParser | None = None,
        nyse_instrument_parser: _NyseInvestingInstrumentParser | None = None,
        tase_parser: _TaseSecurityDataParser | None = None,
        nyse_lookup_store: _NyseLookupCacheStore | None = None,
        tase_lookup_store: _TaseLookupCacheStore | None = None,
    ) -> None:
        self._http_client = http_client or _UrlopenTickerHttpClient()
        self._nyse_search_parser = nyse_search_parser or _NyseInvestingSearchParser()
        self._nyse_instrument_parser = nyse_instrument_parser or _NyseInvestingInstrumentParser()
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

    def fetch_nyse_search_results(self, ticker: str, timeout_seconds: float) -> list[_NyseInvestingSearchResult]:
        """Fetch and parse Investing.com quote search results for one ticker."""
        search_url = _INVESTING_SEARCH_URL_TEMPLATE.format(query=quote(ticker))
        body = self._fetch_text_or_raise_communication_error(
            url=search_url,
            headers=_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Investing.com NYSE search data",
        )
        return self._nyse_search_parser.parse_results(body)

    def fetch_nyse_instrument_payload(self, link: str, timeout_seconds: float) -> str:
        """Fetch raw Investing.com instrument page payload for one search result link."""
        normalized_link = link if link.startswith("/") else f"/{link}"
        url = f"{_INVESTING_BASE_URL}{normalized_link}"
        return self._fetch_text_or_raise_communication_error(
            url=url,
            headers=_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Investing.com NYSE instrument data",
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
        """Resolve NYSE ticker metadata from Investing.com search and instrument payloads."""
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
        """Fetch uncached NYSE ticker lookup result from Investing.com sources."""
        search_results = self.fetch_nyse_search_results(ticker, timeout_seconds)
        search_result = self._find_nyse_search_result(search_results, ticker)
        if search_result is None:
            return TickerLookupNotFound()
        display_name = search_result.name.strip()
        if not display_name:
            return TickerLookupNotFound()
        instrument_payload = self.fetch_nyse_instrument_payload(search_result.link, timeout_seconds)
        metadata = self._nyse_instrument_parser.parse_metadata(
            raw_text=instrument_payload,
            ticker=ticker,
            fallback_display_name=display_name,
            search_result=search_result,
        )
        return TickerLookupFound(metadata=metadata)

    def _find_nyse_search_result(
        self,
        search_results: list[_NyseInvestingSearchResult],
        ticker: str,
    ) -> _NyseInvestingSearchResult | None:
        """Return exact NYSE search match for canonical ticker, if present."""
        for item in search_results:
            if item.exchange == _INVESTING_NYSE_EXCHANGE and item.symbol == ticker:
                return item
        return None

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

def _as_string(value: object) -> str:
    """Return stripped string value when source value is string-like, else empty string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_upper_string(value: object) -> str:
    """Return upper-cased stripped string value when available, else empty string."""
    return _as_string(value).upper()


def _as_int(value: object) -> int | None:
    """Return integer value when source value can be parsed as integer, else ``None``."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _looks_like_isin(candidate: str) -> bool:
    """Return whether candidate is a plausible ISIN-like token."""
    if len(candidate) != 12:
        return False
    if not candidate[:2].isalpha():
        return False
    return candidate.isalnum()
