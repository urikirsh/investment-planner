"""NYSE ticker lookup provider backed by unauthenticated web quote endpoints."""

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
    """Normalized quote details shared by Nasdaq and Yahoo parser results.

    The provider consumes this internal shape to build the public
    ``TickerLookupFound`` metadata without coupling source-specific parsing code
    to service-level result construction.
    """

    display_name: str
    price: Decimal
    provider_data: Mapping[str, object]


def _load_json_mapping(raw_text: str, *, source_name: str) -> Mapping[str, object]:
    """Decode a provider JSON response and require an object root.

    Args:
        raw_text: Response body returned by the HTTP transport.
        source_name: Human-readable provider label used in diagnostics.

    Returns:
        Parsed JSON mapping for provider-specific parsers.

    Raises:
        TickerLookupCommunicationError: If the response is not valid JSON or
            does not decode to an object.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise TickerLookupCommunicationError(f"{source_name} response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TickerLookupCommunicationError(f"{source_name} response has an unexpected payload format")
    return payload


def _string_value(value: object) -> str | None:
    """Normalize optional string fields from provider payloads.

    Provider metadata frequently omits fields or returns blank strings for
    unavailable values. This helper keeps that absence represented consistently
    as ``None``.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


class _NasdaqQuoteParser:
    """Parser for Nasdaq public quote JSON responses.

    Nasdaq reports missing symbols with a successful JSON response whose
    ``data`` field is ``null``. The parser treats those as not-found outcomes,
    while malformed payloads raise communication errors.
    """

    def parse_quote(self, raw_text: str, *, expected_symbol: str, asset_class: str) -> _WebQuote | None:
        """Parse a Nasdaq quote response into normalized quote metadata.

        Args:
            raw_text: JSON response body from the Nasdaq quote endpoint.
            expected_symbol: Canonical NYSE ticker requested by the app.
            asset_class: Nasdaq asset-class route used for the request.

        Returns:
            ``_WebQuote`` when Nasdaq returns a matching symbol with a usable
            last-sale price, otherwise ``None`` for clean no-data responses.

        Raises:
            TickerLookupCommunicationError: If Nasdaq returns malformed JSON,
            an unexpected object shape, or an unparsable price.
        """
        payload = _load_json_mapping(raw_text, source_name="Nasdaq quote")
        data = payload.get("data")
        if data is None:
            return None
        if not isinstance(data, Mapping):
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected payload format")

        symbol = _string_value(data.get("symbol"))
        if symbol is None or symbol.upper() != expected_symbol.upper():
            return None

        primary_data = data.get("primaryData")
        if not isinstance(primary_data, Mapping):
            raise TickerLookupCommunicationError("Nasdaq quote response has an unexpected primary data format")

        raw_price = _string_value(primary_data.get("lastSalePrice"))
        price = self._parse_price(raw_price)
        if price is None:
            return None

        display_name = _string_value(data.get("companyName")) or expected_symbol
        last_trade_timestamp = _string_value(primary_data.get("lastTradeTimestamp"))
        return _WebQuote(
            display_name=display_name,
            price=price,
            provider_data=MappingProxyType(
                {
                    "source": "nasdaq",
                    "symbol": symbol.upper(),
                    "asset_class": asset_class,
                    "last_sale_price": str(price),
                    "exchange": _string_value(data.get("exchange")),
                    "last_trade_timestamp": last_trade_timestamp,
                }
            ),
        )

    def _parse_price(self, raw_price: str | None) -> Decimal | None:
        """Parse Nasdaq's display price into a Decimal quote amount.

        Nasdaq currently formats prices as strings such as ``"$210.50"`` or
        ``"$1,210.50"``. Missing and ``"N/A"`` prices are clean no-data
        outcomes; syntactically invalid prices indicate a provider contract
        change and raise a communication error.
        """
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
    """Parser for Yahoo Finance chart JSON responses.

    Yahoo chart responses expose price and display metadata under
    ``chart.result[0].meta``. Explicit Yahoo errors and empty result arrays are
    treated as no-data responses so the lookup provider can return not-found
    when all sources agree there is no usable quote.
    """

    def parse_quote(self, raw_text: str, *, expected_symbol: str, yahoo_symbol: str) -> _WebQuote | None:
        """Parse a Yahoo chart response into normalized quote metadata.

        Args:
            raw_text: JSON response body from the Yahoo chart endpoint.
            expected_symbol: Canonical NYSE ticker requested by the app.
            yahoo_symbol: Yahoo-specific ticker spelling used for the request.

        Returns:
            ``_WebQuote`` when Yahoo returns a matching symbol with a usable
            regular-market price, otherwise ``None`` for clean no-data
            responses.

        Raises:
            TickerLookupCommunicationError: If Yahoo returns malformed JSON,
            an unexpected object shape, or an unparsable price.
        """
        payload = _load_json_mapping(raw_text, source_name="Yahoo chart")
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

        symbol = _string_value(meta.get("symbol"))
        if symbol is None or symbol.upper() != yahoo_symbol.upper():
            return None

        price = self._parse_decimal_value(meta.get("regularMarketPrice"))
        if price is None:
            return None

        display_name = (
            _string_value(meta.get("longName"))
            or _string_value(meta.get("shortName"))
            or expected_symbol
        )
        return _WebQuote(
            display_name=display_name,
            price=price,
            provider_data=MappingProxyType(
                {
                    "source": "yahoo_chart",
                    "symbol": symbol.upper(),
                    "yahoo_symbol": yahoo_symbol.upper(),
                    "regular_market_price": str(price),
                    "currency": _string_value(meta.get("currency")),
                    "exchange_name": _string_value(meta.get("exchangeName")),
                    "regular_market_time": meta.get("regularMarketTime"),
                }
            ),
        )

    def _parse_decimal_value(self, value: object) -> Decimal | None:
        """Parse Yahoo's numeric price field into a Decimal quote amount.

        Yahoo may return the market price as a JSON number or string. Missing
        values are treated as clean no-data outcomes, while unsupported types or
        invalid decimal text indicate a provider contract change.
        """
        if isinstance(value, bool) or value is None:
            return None
        if not isinstance(value, (int, float, str)):
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected price format")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise TickerLookupCommunicationError("Yahoo chart response has an unexpected price format") from exc


class _NyseWebLookupProvider(_BaseHttpLookupProvider):
    """NYSE lookup provider backed by Nasdaq first, then Yahoo chart fallback.

    The app relies on this provider for free, no-key quote lookups. Nasdaq is
    preferred because it returns display name and price in one endpoint; Yahoo
    acts as a secondary source, including support for dashed class-share ticker
    spellings.
    """

    def __init__(
        self,
        *,
        http_client: TickerHttpClient,
        request_headers: Mapping[str, str],
        nasdaq_parser: _NasdaqQuoteParser | None = None,
        yahoo_parser: _YahooChartQuoteParser | None = None,
    ) -> None:
        """Initialize provider dependencies and parser instances.

        Args:
            http_client: Transport used to fetch provider response bodies.
            request_headers: Browser-like request headers shared by both web
                endpoints.
            nasdaq_parser: Optional parser override for tests.
            yahoo_parser: Optional parser override for tests.
        """
        super().__init__(http_client=http_client, request_headers=request_headers)
        self._nasdaq_parser = nasdaq_parser or _NasdaqQuoteParser()
        self._yahoo_parser = yahoo_parser or _YahooChartQuoteParser()

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Resolve one canonical NYSE ticker through the configured web sources.

        Nasdaq is queried first across supported asset classes. If Nasdaq has
        no usable quote or fails with a communication error, Yahoo is queried as
        a fallback. A found quote is returned immediately. If no provider
        returns a usable quote, the lookup returns ``TickerLookupNotFound``
        unless every attempted provider fails with a communication error.

        Raises:
            TickerLookupCommunicationError: If all attempted providers fail due to
            transport or parsing errors.
        """
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
        """Fetch and parse Nasdaq quote data across supported asset classes.

        Nasdaq separates stock and ETF quote routes. The provider tries each
        route in order and returns the first matching quote with a usable price.
        """
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
        """Fetch and parse Yahoo chart quote data for one canonical ticker.

        The request uses Yahoo's symbol spelling, which differs from the app's
        canonical NYSE spelling for dotted class-share tickers.
        """
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
        """Return Yahoo's US ticker spelling for the app's canonical ticker.

        Yahoo represents dotted class-share tickers with dashes, for example
        ``BRK.B`` becomes ``BRK-B``.
        """
        return ticker.replace(".", "-").upper()

    def _found_result(self, *, ticker: str, quote: _WebQuote) -> TickerLookupFound:
        """Build the public market-data result from a normalized web quote.

        The resulting metadata preserves the app's canonical ticker while
        carrying source-specific details in immutable ``provider_data`` for
        diagnostics and tests.
        """
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
