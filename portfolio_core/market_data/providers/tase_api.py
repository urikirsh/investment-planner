from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import build_exchange_ticker_key

from portfolio_core.market_data.models import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupNotFound,
    TickerLookupResult,
)
from portfolio_core.market_data.transport import TickerHttpClient

_TASE_SECURITYDATA_URL_TEMPLATE = "https://api.tase.co.il/api/company/securitydata?securityId={security_id}&lang=1"
_TASE_ENGLISH_NAME_KEYS = ("Name", "LongName", "SecurityLongName", "CompanyName")


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


class _TaseApiLookupProvider:
    """TASE lookup provider backed by ``api.tase.co.il`` security-data endpoint."""

    def __init__(
        self,
        *,
        http_client: TickerHttpClient,
        request_headers: Mapping[str, str],
        parser: _TaseSecurityDataParser | None = None,
    ) -> None:
        self._http_client = http_client
        self._request_headers = request_headers
        self._parser = parser or _TaseSecurityDataParser()

    def lookup_ticker(self, ticker: str, timeout_seconds: float) -> TickerLookupResult:
        """Lookup one canonical TASE security number."""
        payload = self._fetch_security_payload(ticker, timeout_seconds)
        return self._parser.parse_lookup_result(payload)

    def _fetch_security_payload(self, ticker: str, timeout_seconds: float) -> str:
        """Fetch raw TASE security-data API payload for one canonical security number."""
        url = _TASE_SECURITYDATA_URL_TEMPLATE.format(security_id=ticker)
        return self._fetch_text_or_raise_communication_error(
            url=url,
            timeout_seconds=timeout_seconds,
            error_message="Failed to fetch TASE security data",
        )

    def _fetch_text_or_raise_communication_error(
        self,
        *,
        url: str,
        timeout_seconds: float,
        error_message: str,
    ) -> str:
        """Fetch payload and normalize transport/parsing failures to communication errors."""
        try:
            return self._http_client.fetch_text(
                url=url,
                headers=self._request_headers,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            raise TickerLookupCommunicationError(error_message) from exc
