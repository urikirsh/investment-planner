"""TASE ticker lookup provider backed by the TASE security-data API endpoint."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from portfolio_core.domain.models import Exchange
from portfolio_core.domain.ticker_rules import build_exchange_ticker_key

from portfolio_core.market_data.models import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupNotFound,
    TickerLookupResult,
)
from portfolio_core.market_data.providers.base import _BaseHttpLookupProvider
from portfolio_core.market_data.transport import TickerHttpClient

_TASE_SECURITYDATA_URL_TEMPLATE = "https://api.tase.co.il/api/company/securitydata?securityId={security_id}&lang=1"
_TASE_MUTUAL_FUND_URL_TEMPLATE = "https://maya.tase.co.il/api/v1/funds/mutual/{fund_id}"
_TASE_ENGLISH_NAME_KEYS = ("Name", "LongName", "SecurityLongName", "CompanyName")
_AGOROT_PER_ILS = Decimal("100")


class _TaseSecurityDataParser:
    """Parser for TASE ``company/securitydata`` JSON payloads."""

    def parse_lookup_result(self, raw_text: str) -> TickerLookupResult:
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
                last_traded_price=self._extract_last_traded_price(payload),
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

    def _extract_last_traded_price(self, payload: Mapping[str, object]) -> Decimal | None:
        """Return last traded TASE price normalized from agorot to ILS."""
        for key in ("LastRate", "TradeRate", "LastTradedRate", "ClosingRate", "Price"):
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if parsed > 0:
                return parsed / _AGOROT_PER_ILS
        return None

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


class _TaseMutualFundParser:
    """Parser for Maya mutual-fund JSON payloads."""

    def parse_lookup_result(self, raw_text: str) -> TickerLookupResult:
        """Parse one mutual-fund payload into found/not-found lookup result."""
        normalized_text = raw_text.strip()
        if not normalized_text or normalized_text == "null":
            return TickerLookupNotFound()
        try:
            payload = json.loads(normalized_text)
        except json.JSONDecodeError as exc:
            raise TickerLookupCommunicationError("TASE mutual fund response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise TickerLookupCommunicationError("TASE mutual fund response has an unexpected payload format")

        fund_id = payload.get("fundId")
        if fund_id in (None, ""):
            return TickerLookupNotFound()
        key = build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker=str(fund_id))
        if not key.canonical_ticker:
            return TickerLookupNotFound()
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=Exchange.TASE,
                canonical_ticker=key.canonical_ticker,
                display_name=self._extract_display_name(payload),
                last_traded_price=self._extract_last_traded_price(payload),
                isin=self._extract_optional_string(payload, "isin"),
                currency=None,
                provider_data=MappingProxyType(dict(payload)),
            )
        )

    def _extract_display_name(self, payload: Mapping[str, object]) -> str:
        """Return preferred mutual-fund display name."""
        short_name = self._extract_optional_string(payload, "name")
        if short_name is not None:
            return short_name
        long_name = self._extract_optional_string(payload, "longName")
        if long_name is not None:
            return long_name
        return ""

    def _extract_optional_string(self, payload: Mapping[str, object], key: str) -> str | None:
        """Return a stripped optional string value when present and non-empty."""
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        normalized_value = value.strip()
        return normalized_value or None

    def _extract_last_traded_price(self, payload: Mapping[str, object]) -> Decimal | None:
        """Return mutual-fund price from redemption/purchase fields in ILS."""
        for key in ("redemptionPrice", "purchasePrice"):
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if parsed > 0:
                return parsed
        return None


class _TaseApiLookupProvider(_BaseHttpLookupProvider):
    """TASE lookup provider backed by ``api.tase.co.il`` security-data endpoint."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient,
        request_headers: Mapping[str, str],
        parser: _TaseSecurityDataParser | None = None,
        mutual_fund_parser: _TaseMutualFundParser | None = None,
    ) -> None:
        super().__init__(http_client=http_client, request_headers=request_headers)
        self._parser = parser or _TaseSecurityDataParser()
        self._mutual_fund_parser = mutual_fund_parser or _TaseMutualFundParser()

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Lookup one canonical TASE security number."""
        primary_error: TickerLookupCommunicationError | None = None
        primary_result: TickerLookupResult = TickerLookupNotFound()
        try:
            payload = self._fetch_security_payload(ticker, timeout_seconds)
            primary_result = self._parser.parse_lookup_result(payload)
        except TickerLookupCommunicationError as exc:
            primary_error = exc
        else:
            if self._has_usable_price(primary_result):
                return primary_result

        mutual_fund_error: TickerLookupCommunicationError | None = None
        mutual_fund_result: TickerLookupResult = TickerLookupNotFound()
        try:
            mutual_fund_result = self._lookup_mutual_fund(ticker, timeout_seconds)
        except TickerLookupCommunicationError as exc:
            mutual_fund_error = exc
        if self._has_usable_price(mutual_fund_result):
            return mutual_fund_result
        if primary_error is not None:
            raise primary_error
        if mutual_fund_error is not None:
            return primary_result
        return primary_result

    def _fetch_security_payload(self, ticker: str, timeout_seconds: float) -> str:
        """Fetch raw TASE security-data API payload for one canonical security number."""
        url = _TASE_SECURITYDATA_URL_TEMPLATE.format(security_id=ticker)
        return self._fetch_text_or_raise_communication_error(
            url=url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch TASE security data",
        )

    def _lookup_mutual_fund(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Lookup one TASE mutual fund from the public Maya endpoint."""
        payload = self._fetch_mutual_fund_payload(ticker, timeout_seconds)
        return self._mutual_fund_parser.parse_lookup_result(payload)

    def _fetch_mutual_fund_payload(self, ticker: str, timeout_seconds: float) -> str:
        """Fetch raw Maya mutual-fund payload for one canonical fund number."""
        url = _TASE_MUTUAL_FUND_URL_TEMPLATE.format(fund_id=ticker)
        return self._fetch_text_or_raise_communication_error(
            url=url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch TASE mutual fund data",
        )

    def _has_usable_price(self, result: TickerLookupResult) -> bool:
        """Return whether lookup result is found and includes a usable price."""
        return isinstance(result, TickerLookupFound) and result.metadata.last_traded_price is not None
