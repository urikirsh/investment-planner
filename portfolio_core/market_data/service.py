from __future__ import annotations

"""Market-data lookup service for NYSE/TASE with app-session caching."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
import time
from types import MappingProxyType

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import build_exchange_ticker_key, is_complete_nyse_ticker

from portfolio_core.market_data.models import (
    TickerLookupFound,
    TickerLookupNotFound,
    TickerLookupResult,
)
from portfolio_core.market_data.providers.nyse_stooq import _NyseStooqLookupProvider
from portfolio_core.market_data.providers.tase_api import _TaseApiLookupProvider
from portfolio_core.market_data.transport import TickerHttpClient, UrlopenTickerHttpClient

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


class MarketDataService:
    """Market-data lookup orchestration with injected providers and caches."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient | None = None,
        nyse_provider: _NyseStooqLookupProvider | None = None,
        tase_provider: _TaseApiLookupProvider | None = None,
        nyse_lookup_store: _NyseLookupCacheStore | None = None,
        tase_lookup_store: _TaseLookupCacheStore | None = None,
    ) -> None:
        self._http_client = http_client or UrlopenTickerHttpClient()
        self._nyse_provider = nyse_provider or _NyseStooqLookupProvider(
            http_client=self._http_client,
            request_headers=MappingProxyType(dict(_REQUEST_HEADERS)),
        )
        self._tase_provider = tase_provider or _TaseApiLookupProvider(
            http_client=self._http_client,
            request_headers=MappingProxyType(dict(_TASE_REQUEST_HEADERS)),
        )
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
        """Route ticker lookup to exchange-specific provider flow."""
        provider = self._lookup_by_exchange.get(exchange)
        if provider is None:
            return TickerLookupNotFound()
        return provider(ticker, timeout_seconds)

    def _lookup_nyse_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve NYSE ticker metadata through the configured NYSE provider."""
        key = build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker=ticker)
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        if not is_complete_nyse_ticker(key.canonical_ticker):
            return TickerLookupNotFound()
        return self._nyse_lookup_store.get_or_load(
            ticker=key.canonical_ticker,
            timeout_seconds=timeout_seconds,
            result_loader=self._nyse_provider.lookup_ticker,
        )

    def _lookup_tase_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve TASE ticker metadata through the configured TASE provider."""
        key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=ticker)
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        return self._tase_lookup_store.get_or_load(
            ticker=key.canonical_ticker,
            timeout_seconds=timeout_seconds,
            result_loader=self._tase_provider.lookup_ticker,
        )


_default_market_data_service = MarketDataService()


def lookup_ticker_in_exchange(
    *,
    exchange: Exchange,
    ticker: str,
    timeout_seconds: float = 8.0,
) -> TickerLookupResult:
    """Route ticker lookup through the default app-level market-data service."""
    return _default_market_data_service.lookup_ticker_in_exchange(
        exchange=exchange,
        ticker=ticker,
        timeout_seconds=timeout_seconds,
    )
