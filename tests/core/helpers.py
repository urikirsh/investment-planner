from __future__ import annotations

"""
Shared builders for core/domain tests.

This module centralizes fixture-like payload builders so core tests can
focus on behavior assertions instead of repeating portfolio JSON setup.
"""

import json
from collections.abc import Mapping
from decimal import Decimal
import time
from typing import Any
from typing import cast

from portfolio_core.io_json import load_portfolio
from portfolio_core.market_data import MarketDataService

D = Decimal


class FakeHttpClient:
    """Deterministic market-data HTTP client for lookup service tests."""

    def __init__(
        self,
        *,
        payloads_by_url: Mapping[str, str] | None = None,
        errors_by_url: Mapping[str, Exception] | None = None,
        default_exception: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._payloads_by_url = payloads_by_url or {}
        self._errors_by_url = errors_by_url or {}
        self._default_exception = default_exception
        self._delay_seconds = delay_seconds
        self.calls = 0

    def fetch_text(
        self,
        *,
        url: str,
        headers: Mapping[str, str],  # noqa: ARG002
        timeout_seconds: float,  # noqa: ARG002
    ) -> str:
        self.calls += 1
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)
        error = self._errors_by_url.get(url)
        if error is not None:
            raise error
        if url in self._payloads_by_url:
            return self._payloads_by_url[url]
        if self._default_exception is not None:
            raise self._default_exception
        raise AssertionError(f"Unexpected URL requested: {url}")


def build_nasdaq_quote_payload(
    *,
    symbol: str = "AAPL",
    company_name: str = "Apple Inc. Common Stock",
    price: str = "$210.50",
    exchange: str = "NASDAQ-GS",
    last_trade_timestamp: str = "Jul 9, 2026 4:00 PM ET",
) -> str:
    """Build minimal Nasdaq quote payload with parsable fields."""
    return json.dumps(
        {
            "data": {
                "symbol": symbol,
                "companyName": company_name,
                "exchange": exchange,
                "primaryData": {
                    "lastSalePrice": price,
                    "lastTradeTimestamp": last_trade_timestamp,
                },
            }
        }
    )


def build_yahoo_chart_payload(
    *,
    symbol: str = "AAPL",
    long_name: str = "Apple Inc",
    price: str = "210.50",
    currency: str = "USD",
    exchange_name: str = "NMS",
) -> str:
    """Build minimal Yahoo chart payload with parsable metadata."""
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "longName": long_name,
                            "regularMarketPrice": price,
                            "currency": currency,
                            "exchangeName": exchange_name,
                            "regularMarketTime": 1783540800,
                        }
                    }
                ],
                "error": None,
            }
        }
    )


def build_not_found_payload() -> str:
    """Build a public quote endpoint not-found payload."""
    return json.dumps({"data": None, "message": None, "status": {"rCode": 400}})


def install_default_lookup_service_with_url_payloads(
    monkeypatch: Any,
    *,
    payloads_by_url: Mapping[str, str],
    delay_seconds: float = 0.0,
) -> MarketDataService:
    """Install a default lookup service with deterministic URL-specific payload behavior."""
    http_client = FakeHttpClient(payloads_by_url=payloads_by_url, delay_seconds=delay_seconds)
    service = MarketDataService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.market_data.lookup_service._default_market_data_service",
        service,
    )
    return service


def fake_http_client(service: MarketDataService) -> FakeHttpClient:
    """Return the installed fake client for call-count assertions."""
    return cast(FakeHttpClient, service._http_client)


def install_default_lookup_service_with_failing_transport(
    monkeypatch: Any,
    *,
    exception: Exception,
) -> MarketDataService:
    """Install a default lookup service whose transport always raises."""
    http_client = FakeHttpClient(default_exception=exception)
    service = MarketDataService(http_client=http_client)
    monkeypatch.setattr(
        "portfolio_core.market_data.lookup_service._default_market_data_service",
        service,
    )
    return service


def make_valid_data(
    *,
    cash_value: str = "12000",
    cash_reserve: str = "2000",
    cash_future_tax: str = "0",
    group_targets: tuple[tuple[str, str, str], ...] = (("g1", "Asset 1", "60.0"), ("g2", "Asset 2", "40.0")),
    instruments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a valid JSON-like portfolio payload for tests.

    Callers can override cash/group/instrument parts to target specific
    validation or planning scenarios while preserving required defaults.
    """
    if instruments is None:
        instruments = [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "value": "6000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i2",
                "ticker": "2345678",
                "name": "Inst 2",
                "value": "4000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i3",
                "ticker": "3456789",
                "name": "Parking",
                "value": "1000",
                "exchange": "TASE",
                "investable": False,
                "targetInGroupPercentage": "0",
            },
        ]

    seen_by_group: dict[str, bool] = {}
    for ins in instruments:
        ins.setdefault("exchange", "TASE")
        exchange = str(ins["exchange"]).strip().upper()
        if exchange == "TASE":
            ins.setdefault("ticker", "1234567")
        elif exchange == "NYSE":
            ins.setdefault("ticker", "AB12")
        else:
            ins.setdefault("ticker", "UNKNOWN")
        ins.setdefault("quantity", 0)
        if "targetInGroupPercentage" in ins:
            continue
        if ins.get("investable") and ins.get("groupId"):
            gid = ins["groupId"]
            if gid not in seen_by_group:
                ins["targetInGroupPercentage"] = "100"
                seen_by_group[gid] = True
            else:
                ins["targetInGroupPercentage"] = "0"
        else:
            ins["targetInGroupPercentage"] = "0"

    groups = [{"id": gid, "name": name, "targetPercentage": pct} for gid, name, pct in group_targets]
    return {
        "cash": {"value": cash_value, "min_reserve": cash_reserve, "future_tax": cash_future_tax},
        "groups": groups,
        "instruments": instruments,
    }


def make_portfolio():
    """Build a compact one-group/one-instrument portfolio for stock-unit tests."""
    data = {
        "cash": {"value": "1000", "min_reserve": "100", "future_tax": "0"},
        "groups": [{"id": "g1", "name": "Asset", "targetPercentage": "100"}],
        "instruments": [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst",
                "quantity": 0,
                "value": "500",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            }
        ],
    }
    return load_portfolio(data)
