from __future__ import annotations

"""Market-data lookup service for NYSE/TASE with app-session caching."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from types import MappingProxyType

from portfolio_core.domain.models import Exchange
from portfolio_core.domain.ticker_rules import build_exchange_ticker_key, is_complete_nyse_ticker

from portfolio_core.market_data.models import (
    TickerLookupNotFound,
    TickerLookupResult,
)
from portfolio_core.market_data.providers.nyse_stooq import _NyseStooqLookupProvider
from portfolio_core.market_data.providers.tase_api import _TaseApiLookupProvider
from portfolio_core.market_data.transport import TickerHttpClient, UrlopenTickerHttpClient

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


class _TickerLookupProvider(Protocol):
    """Lookup-provider contract consumed by market-data orchestration."""

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult: ...


@dataclass(frozen=True)
class _ExchangeLookupRuntime:
    """Exchange lookup runtime bundle used by generic routing."""

    pre_validate: Callable[[str], bool]
    provider: _TickerLookupProvider


@dataclass(frozen=True)
class _LookupCacheKey:
    """Typed cache key for one canonical `(exchange, ticker)` lookup entry."""

    exchange: Exchange
    canonical_ticker: str


class _LookupCacheStore:
    """Thread-safe holder for app-session per-(exchange, ticker) lookup cache."""

    def __init__(self) -> None:
        """Initialize empty cache storage and synchronization primitive."""
        self._cache: dict[_LookupCacheKey, TickerLookupResult] = {}
        self._lock = Lock()

    def get_or_load(
        self,
        *,
        key: _LookupCacheKey,
        timeout_seconds: float,
        result_loader: Callable[[str, float], TickerLookupResult],
    ) -> TickerLookupResult:
        """Return cached ticker lookup result, loading once per cache key."""
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            result = result_loader(key.canonical_ticker, timeout_seconds)
            self._cache[key] = result
            return result

    def get_cached(self, *, key: _LookupCacheKey) -> TickerLookupResult | None:
        """Return cached lookup result for `key` without triggering a load."""
        with self._lock:
            return self._cache.get(key)

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache.clear()

    def get_cached_for_tests(self) -> dict[_LookupCacheKey, TickerLookupResult]:
        """Return current cached payload without triggering network load."""
        with self._lock:
            return dict(self._cache)


class MarketDataService:
    """Market-data lookup orchestration with injected providers and caches."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient | None = None,
        nyse_provider: _TickerLookupProvider | None = None,
        tase_provider: _TickerLookupProvider | None = None,
        lookup_store: _LookupCacheStore | None = None,
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
        self._lookup_store = lookup_store or _LookupCacheStore()
        self._runtime_by_exchange: Mapping[
            Exchange,
            _ExchangeLookupRuntime,
        ] = MappingProxyType(
            {
                Exchange.NYSE: _ExchangeLookupRuntime(
                    pre_validate=is_complete_nyse_ticker,
                    provider=self._nyse_provider,
                ),
                Exchange.TASE: _ExchangeLookupRuntime(
                    pre_validate=lambda _ticker: True,
                    provider=self._tase_provider,
                ),
            }
        )

    @staticmethod
    def _build_lookup_cache_key(*, exchange: Exchange, ticker: str) -> _LookupCacheKey | None:
        """Return canonical cache key for `(exchange, ticker)` or `None` when invalid."""
        key = build_exchange_ticker_key(exchange=exchange, raw_ticker=ticker)
        if not key.canonical_ticker:
            return None
        return _LookupCacheKey(
            exchange=exchange,
            canonical_ticker=key.canonical_ticker,
        )

    def lookup_ticker_in_exchange(
        self,
        *,
        exchange: Exchange,
        ticker: str,
        timeout_seconds: float = 8.0,
    ) -> TickerLookupResult:
        """Route ticker lookup to exchange-specific provider flow."""
        runtime = self._runtime_by_exchange.get(exchange)
        if runtime is None:
            return TickerLookupNotFound()
        cache_key = self._build_lookup_cache_key(exchange=exchange, ticker=ticker)
        if cache_key is None:
            return TickerLookupNotFound()
        if not runtime.pre_validate(cache_key.canonical_ticker):
            return TickerLookupNotFound()
        return self._lookup_store.get_or_load(
            key=cache_key,
            timeout_seconds=timeout_seconds,
            result_loader=runtime.provider.lookup_ticker,
        )

    def get_cached_ticker_in_exchange(
        self,
        *,
        exchange: Exchange,
        ticker: str,
    ) -> TickerLookupResult | None:
        """Return cached lookup result for `(exchange, ticker)` without fetching."""
        cache_key = self._build_lookup_cache_key(exchange=exchange, ticker=ticker)
        if cache_key is None:
            return None
        return self._lookup_store.get_cached(key=cache_key)


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


def get_cached_ticker_lookup_in_exchange(
    *,
    exchange: Exchange,
    ticker: str,
) -> TickerLookupResult | None:
    """Return cached lookup result for `(exchange, ticker)` without fetching."""
    return _default_market_data_service.get_cached_ticker_in_exchange(
        exchange=exchange,
        ticker=ticker,
    )
