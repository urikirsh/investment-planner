from __future__ import annotations

"""Market-data lookup service for NYSE/TASE with app-session caching."""

from collections.abc import Callable, Mapping
from threading import Lock
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


class _LookupCacheStore:
    """Thread-safe holder for app-session per-(exchange, ticker) lookup cache."""

    def __init__(self) -> None:
        """Initialize empty cache storage and synchronization primitive."""
        self._cache: dict[tuple[Exchange, str], TickerLookupResult] = {}
        self._lock = Lock()

    def get_or_load(
        self,
        *,
        key: tuple[Exchange, str],
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
            result = result_loader(key[1], timeout_seconds)
            self._cache[key] = result
            return result

    def clear_for_tests(self) -> None:
        """Reset cache state for deterministic tests."""
        with self._lock:
            self._cache.clear()

    def get_cached_for_tests(self) -> dict[tuple[Exchange, str], TickerLookupResult]:
        """Return current cached payload without triggering network load."""
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
        return self._lookup_store.get_or_load(
            key=(Exchange.NYSE, key.canonical_ticker),
            timeout_seconds=timeout_seconds,
            result_loader=self._nyse_provider.lookup_ticker,
        )

    def _lookup_tase_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve TASE ticker metadata through the configured TASE provider."""
        key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=ticker)
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        return self._lookup_store.get_or_load(
            key=(Exchange.TASE, key.canonical_ticker),
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
