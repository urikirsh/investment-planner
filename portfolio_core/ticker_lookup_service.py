from __future__ import annotations

"""Ticker existence and name lookup for NYSE/TASE with app-session caching.

Behavior summary:
- NYSE uses Nasdaq Trader `otherlisted.txt` and caches a symbol index for the app session.
- TASE uses `api.tase.co.il` per-security lookup with per-ticker TTL cache entries.
- TASE security numbers are normalized to canonical form (leading zeros removed)
  before network lookup and cache keying.
"""

import csv
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from io import StringIO
from threading import Lock
import time
from types import MappingProxyType
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import canonicalize_ticker_for_exchange

_NASDAQ_OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
_TASE_SECURITYDATA_URL_TEMPLATE = "https://api.tase.co.il/api/company/securitydata?securityId={security_id}&lang=1"
_NYSE_ACCEPTED_EXCHANGE_CODES = {"N", "A", "P", "Z"}
_FIELD_ACT_SYMBOL = "ACT SYMBOL"
_FIELD_EXCHANGE = "EXCHANGE"
_FIELD_SECURITY_NAME = "SECURITY NAME"
_TASE_ENGLISH_NAME_KEYS = ("Name", "LongName", "SecurityLongName", "CompanyName")
_TASE_CACHE_TTL_SECONDS = 900.0
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


class _NyseOtherlistedParser:
    """Parser for Nasdaq Trader `otherlisted.txt` payloads."""

    def parse_rows(self, raw_text: str) -> list["_NyseRelevantRow"]:
        """Parse `otherlisted.txt` payload text into NYSE-relevant rows."""
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
        canonical_ticker = canonicalize_ticker_for_exchange(exchange=Exchange.TASE, raw=str(security_id))
        if not canonical_ticker:
            return TickerLookupNotFound()
        instrument_name = self._extract_english_instrument_name(payload)
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=Exchange.TASE,
                canonical_ticker=canonical_ticker,
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
class _NyseRelevantRow:
    """Minimal cached row used for NYSE ticker existence checks."""

    act_symbol: str
    security_name: str
    exchange_code: str


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
class _NyseLookupCache:
    """In-memory cache of NYSE symbol index for app-session reuse."""

    rows_by_symbol: Mapping[str, _NyseRelevantRow]


@dataclass(frozen=True)
class _TaseLookupCacheEntry:
    """Cached TASE ticker lookup result with monotonic expiration timestamp."""

    result: TickerLookupResult
    expires_at_monotonic: float


class _NyseLookupCacheStore:
    """Thread-safe holder for app-session NYSE lookup cache."""

    def __init__(self) -> None:
        """Initialize empty cache storage and synchronization primitive."""
        self._cache: _NyseLookupCache | None = None
        self._lock = Lock()

    def get_or_load(
        self,
        *,
        timeout_seconds: float,
        rows_loader: Callable[[float], list[_NyseRelevantRow]],
    ) -> _NyseLookupCache:
        """Return cached NYSE symbol index, loading once on first access."""
        if self._cache is not None:
            return self._cache

        # Double-checked locking so only one thread populates cache at cold start.
        with self._lock:
            if self._cache is not None:
                return self._cache
            rows = rows_loader(timeout_seconds)
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
        nyse_parser: _NyseOtherlistedParser | None = None,
        tase_parser: _TaseSecurityDataParser | None = None,
        nyse_lookup_store: _NyseLookupCacheStore | None = None,
        tase_lookup_store: _TaseLookupCacheStore | None = None,
    ) -> None:
        self._http_client = http_client or _UrlopenTickerHttpClient()
        self._nyse_parser = nyse_parser or _NyseOtherlistedParser()
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

    def fetch_otherlisted_rows(self, timeout_seconds: float) -> list[_NyseRelevantRow]:
        """Fetch and parse Nasdaq Trader `otherlisted.txt` rows."""
        body = self._fetch_text_or_raise_communication_error(
            url=_NASDAQ_OTHERLISTED_URL,
            headers=_REQUEST_HEADERS,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Nasdaq Trader symbol directory",
        )
        return self._nyse_parser.parse_rows(body)

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
        """Resolve NYSE ticker existence and canonical instrument name from cached rows."""
        normalized_ticker = canonicalize_ticker_for_exchange(exchange=Exchange.NYSE, raw=ticker)
        if not normalized_ticker:
            return TickerLookupNotFound()
        cache = self._nyse_lookup_store.get_or_load(
            timeout_seconds=timeout_seconds,
            rows_loader=self.fetch_otherlisted_rows,
        )
        row = cache.rows_by_symbol.get(normalized_ticker)
        if row is None:
            return TickerLookupNotFound()
        security_name = row.security_name.strip()
        if not security_name:
            return TickerLookupNotFound()
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=Exchange.NYSE,
                canonical_ticker=normalized_ticker,
                display_name=security_name,
                provider_data=MappingProxyType({"exchange_code": row.exchange_code}),
            )
        )

    def _lookup_tase_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve TASE ticker from cache/API after canonical security-number normalization."""
        normalized_ticker = canonicalize_ticker_for_exchange(exchange=Exchange.TASE, raw=ticker)
        if not normalized_ticker:
            return TickerLookupNotFound()
        return self._tase_lookup_store.get_or_load(
            ticker=normalized_ticker,
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
        """Fetch transport payload and normalize transport failures to communication errors."""
        try:
            return self._http_client.fetch_text(url=url, headers=headers, timeout_seconds=timeout_seconds)
        except Exception as exc:
            raise TickerLookupCommunicationError(error_message) from exc


_default_ticker_lookup_service = TickerLookupService()
_http_client = _default_ticker_lookup_service._http_client
_nyse_parser = _default_ticker_lookup_service._nyse_parser
_tase_parser = _default_ticker_lookup_service._tase_parser
_nyse_lookup_store = _default_ticker_lookup_service._nyse_lookup_store
_tase_lookup_store = _default_ticker_lookup_service._tase_lookup_store


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


def _fetch_otherlisted_rows(*, timeout_seconds: float) -> list[_NyseRelevantRow]:
    """Backward-compatible helper delegating to default lookup service."""
    return _default_ticker_lookup_service.fetch_otherlisted_rows(timeout_seconds)


def _fetch_tase_lookup_result(*, ticker: str, timeout_seconds: float) -> TickerLookupResult:
    """Backward-compatible helper delegating to default lookup service."""
    return _default_ticker_lookup_service.fetch_tase_lookup_result(ticker, timeout_seconds)


def _fetch_tase_security_payload(*, ticker: str, timeout_seconds: float) -> str:
    """Backward-compatible helper delegating to default lookup service."""
    return _default_ticker_lookup_service.fetch_tase_security_payload(ticker, timeout_seconds)


def normalize_tase_security_number(raw_ticker: str) -> str:
    """Return canonical TASE security number with leading zeros removed.

    Examples:
    - `"0312017"` -> `"312017"`
    - `"0000000"` -> `"0"`
    - `"   "` -> `""`
    """
    stripped = raw_ticker.strip()
    return canonicalize_ticker_for_exchange(exchange=Exchange.TASE, raw=stripped)


def _parse_otherlisted_text(raw_text: str) -> list[_NyseRelevantRow]:
    """Parse `otherlisted.txt` into NYSE-relevant rows only (`N/A/P/Z`)."""
    return _nyse_parser.parse_rows(raw_text)


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
    return _NyseRelevantRow(
        act_symbol=act_symbol,
        security_name=security_name,
        exchange_code=exchange_code,
    )
