"""NYSE ticker lookup provider backed by free web quote endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from urllib.parse import quote

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

_NASDAQ_QUOTE_URL_TEMPLATE = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass={asset_class}"
_YAHOO_CHART_URL_TEMPLATE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
_NASDAQ_ASSET_CLASSES = ("stocks", "etf")


@dataclass(frozen=True)
class _WebQuote:
    """Minimal quote payload normalized from a free NYSE web source."""

    source: str
    symbol: str
    display_name: str
    price: Decimal
    provider_data: Mapping[str, object]


class _NasdaqQuoteParser:
    """Parser for Nasdaq public quote JSON responses."""

    def parse_quote(self, raw_text: str, *, expected_symbol: str, asset_class: str) -> _WebQuote | None:
        """Parse one Nasdaq quote payload, returning ``None`` when Nasdaq reports no match."""
        payload = self._load_json(raw_text)
        data = payload.get("data")
        if data is None:
            return None
        if not isinstance(data, Mapping):
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected payload format")

        symbol = self._string_value(data.get("symbol"))
        if symbol is None or symbol.upper() != expected_symbol.upper():
            return None

        primary_data = data.get("primaryData")
        if not isinstance(primary_data, Mapping):
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected primary data format")

        raw_price = self._string_value(primary_data.get("lastSalePrice"))
        price = self._parse_price(raw_price)
        if price is None:
            return None

        display_name = self._string_value(data.get("companyName")) or expected_symbol
        last_trade_timestamp = self._string_value(primary_data.get("lastTradeTimestamp"))
        return _WebQuote(
            source="nasdaq",
            symbol=symbol.upper(),
            display_name=display_name,
            price=price,
            provider_data=MappingProxyType(
                {
                    "source": "nasdaq",
                    "symbol": symbol.upper(),
                    "asset_class": asset_class,
                    "last_sale_price": str(price),
                    "exchange": self._string_value(data.get("exchange")),
                    "last_trade_timestamp": last_trade_timestamp,
                }
            ),
        )

    def _load_json(self, raw_text: str) -> Mapping[str, object]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise TickerLookupCommunicationError("Nasdaq quote response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected payload format")
        return payload

    def _string_value(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _parse_price(self, raw_price: str | None) -> Decimal | None:
        if raw_price is None:
            return None
        normalized = raw_price.strip().removeprefix("$").replace(",", "")
        if normalized in {"", "N/A"}:
            return None
        try:
            return Decimal(normalized)
        except (InvalidOperation, ValueError) as exc:
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected price format") from exc


class _YahooChartQuoteParser:
    """Parser for Yahoo Finance chart JSON responses."""

    def parse_quote(self, raw_text: str, *, expected_symbol: str, yahoo_symbol: str) -> _WebQuote | None:
        """Parse one Yahoo chart payload, returning ``None`` when Yahoo reports no data."""
        payload = self._load_json(raw_text)
        chart = payload.get("chart")
        if not isinstance(chart, Mapping):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected payload format")
        if chart.get("error") is not None:
            return None

        results = chart.get("result")
        if not isinstance(results, list) or not results:
            return None
        first_result = results[0]
        if not isinstance(first_result, Mapping):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected result format")
        meta = first_result.get("meta")
        if not isinstance(meta, Mapping):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected metadata format")

        symbol = self._string_value(meta.get("symbol"))
        if symbol is None or symbol.upper() != yahoo_symbol.upper():
            return None

        price = self._parse_decimal_value(meta.get("regularMarketPrice"))
        if price is None:
            return None

        display_name = (
            self._string_value(meta.get("longName"))
            or self._string_value(meta.get("shortName"))
            or expected_symbol
        )
        return _WebQuote(
            source="yahoo_chart",
            symbol=symbol.upper(),
            display_name=display_name,
            price=price,
            provider_data=MappingProxyType(
                {
                    "source": "yahoo_chart",
                    "symbol": symbol.upper(),
                    "yahoo_symbol": yahoo_symbol.upper(),
                    "regular_market_price": str(price),
                    "currency": self._string_value(meta.get("currency")),
                    "exchange_name": self._string_value(meta.get("exchangeName")),
                    "regular_market_time": meta.get("regularMarketTime"),
                }
            ),
        )

    def _load_json(self, raw_text: str) -> Mapping[str, object]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise TickerLookupCommunicationError("Yahoo chart response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected payload format")
        return payload

    def _string_value(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _parse_decimal_value(self, value: object) -> Decimal | None:
        if isinstance(value, bool) or value is None:
            return None
        if not isinstance(value, (int, float, str)):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected price format")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected price format") from exc


class _NyseWebLookupProvider(_BaseHttpLookupProvider):
    """NYSE lookup provider backed by Nasdaq first, then Yahoo chart fallback."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient,
        request_headers: Mapping[str, str],
        nasdaq_parser: _NasdaqQuoteParser | None = None,
        yahoo_parser: _YahooChartQuoteParser | None = None,
    ) -> None:
        super().__init__(http_client=http_client, request_headers=request_headers)
        self._nasdaq_parser = nasdaq_parser or _NasdaqQuoteParser()
        self._yahoo_parser = yahoo_parser or _YahooChartQuoteParser()

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Lookup one canonical NYSE ticker via free web quote sources."""
        errors: list[str] = []

        try:
            nasdaq_quote = self._lookup_nasdaq(ticker=ticker, timeout_seconds=timeout_seconds)
        except TickerLookupCommunicationError as exc:
            errors.append(str(exc))
        else:
            if nasdaq_quote is not None:
                return self._found_result(ticker=ticker, quote=nasdaq_quote)

        try:
            yahoo_quote = self._lookup_yahoo(ticker=ticker, timeout_seconds=timeout_seconds)
        except TickerLookupCommunicationError as exc:
            errors.append(str(exc))
        else:
            if yahoo_quote is not None:
                return self._found_result(ticker=ticker, quote=yahoo_quote)

        if len(errors) == 2:
            raise TickerLookupCommunicationError(
                "Failed to fetch NYSE quote data from Nasdaq and Yahoo: " + " | ".join(errors)
            )
        return TickerLookupNotFound()

    def _lookup_nasdaq(self, *, ticker: str, timeout_seconds: float) -> _WebQuote | None:
        """Return a Nasdaq quote for stock/ETF asset classes when available."""
        encoded_symbol = quote(ticker.upper(), safe="")
        for asset_class in _NASDAQ_ASSET_CLASSES:
            quote_url = _NASDAQ_QUOTE_URL_TEMPLATE.format(
                symbol=encoded_symbol,
                asset_class=asset_class,
            )
            payload = self._fetch_text_or_raise_communication_error(
                url=quote_url,
                timeout_seconds=timeout_seconds,
                error_message="Failed to fetch Nasdaq NYSE quote data",
            )
            quote_result = self._nasdaq_parser.parse_quote(
                payload,
                expected_symbol=ticker,
                asset_class=asset_class,
            )
            if quote_result is not None:
                return quote_result
        return None

    def _lookup_yahoo(self, *, ticker: str, timeout_seconds: float) -> _WebQuote | None:
        """Return a Yahoo chart quote when available."""
        yahoo_symbol = self._yahoo_symbol(ticker)
        quote_url = _YAHOO_CHART_URL_TEMPLATE.format(symbol=quote(yahoo_symbol, safe=""))
        payload = self._fetch_text_or_raise_communication_error(
            url=quote_url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch Yahoo NYSE chart data",
        )
        return self._yahoo_parser.parse_quote(
            payload,
            expected_symbol=ticker,
            yahoo_symbol=yahoo_symbol,
        )

    def _yahoo_symbol(self, ticker: str) -> str:
        """Return Yahoo's US ticker spelling for the app's canonical ticker."""
        return ticker.replace(".", "-").upper()

    def _found_result(self, *, ticker: str, quote: _WebQuote) -> TickerLookupFound:
        """Build public lookup metadata for a resolved web quote."""
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=Exchange.NYSE,
                canonical_ticker=ticker,
                display_name=quote.display_name,
                last_traded_price=quote.price,
                currency="USD",
                provider_data=quote.provider_data,
            )
        )
